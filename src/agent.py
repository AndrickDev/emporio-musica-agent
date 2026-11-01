"""The customer-service agent: an LLM loop with function calling.

Design: a thin loop over any OpenAI-compatible endpoint. Structured data
(catalog, orders, promotions) is fetched with SQL tools; policy questions go
through keyword retrieval over the policy manual. The system prompt encodes
the store persona and the non-negotiable service rules from the manual.
"""
import json
import time
from pathlib import Path

from openai import APIError, OpenAI

from . import config
from .tools import TOOL_SCHEMAS, call_tool

SYSTEM_PROMPT = """Você é o assistente virtual da Empório da Música, loja de instrumentos musicais de Campo Grande/MS, atendendo clientes por mensagem de texto.

Tom de voz: informal, mas profissional. Acolhedor, como um amigo que entende de música. Respostas curtas e diretas, em português brasileiro. Chame o cliente pelo nome quando souber.

Regras obrigatórias:
- NUNCA informe preço, estoque, prazo, promoção ou status de pedido sem antes consultar as ferramentas. Se não consultou, não afirme.
- Para dúvidas sobre regras (troca, devolução, frete, pagamento, garantia, horários, funcionamento), consulte a ferramenta de políticas antes de responder.
- A loja vende APENAS instrumentos musicais. Não vende acessórios (cordas, palhetas, cabos, cases, pedais, amplificadores). Se pedirem acessórios, explique com simpatia e sugira procurar uma loja de acessórios.
- Para assuntos fora do escopo da loja, redirecione educadamente para o atendimento.
- Promoções: verifique se estão ativas antes de mencionar qualquer desconto. Nunca prometa desconto vencido.
- Pedidos: só consulte quando o cliente informar um identificador (número do pedido, código de rastreio ou e-mail cadastrado). Se faltar, peça.
- Você não finaliza vendas nem processa pagamentos. Para comprar, oriente o cliente a chamar no WhatsApp (67) 3321-4500 ou visitar a loja.
- Reclamações: acolha com empatia e informe que a equipe retorna em até 24h úteis.
- Se algo não estiver nos dados nem nas políticas, diga que vai confirmar com a equipe. Nunca invente informação.
"""


class Agent:
    def __init__(self, client: OpenAI | None = None, model: str | None = None):
        self.client = client or OpenAI(
            base_url=config.BASE_URL, api_key=config.API_KEY
        )
        self.model = model or config.MODEL
        self.messages: list = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _create_completion(self):
        """Call the model with simple backoff for transient errors.

        Free-tier endpoints throttle under load (429) or return 503 when
        capacity is short; both are retryable and never produce charges.
        """
        last_error = None
        for attempt in range(10):
            try:
                kwargs = {}
                if config.REASONING_EFFORT:
                    kwargs["reasoning_effort"] = config.REASONING_EFFORT
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    temperature=config.TEMPERATURE,
                    **kwargs,
                )
            except APIError as exc:
                last_error = exc
                status = getattr(exc, "status_code", None)
                if status not in (429, 500, 502, 503, 504):
                    raise
                time.sleep(min(2 ** attempt * 5, 90))
        raise last_error

    def chat(self, user_input: str) -> dict:
        """Send one user message; return the reply and the tool-call trace."""
        self.messages.append({"role": "user", "content": user_input})
        trace = []
        for _ in range(config.MAX_TOOL_ROUNDS):
            response = self._create_completion()
            message = response.choices[0].message
            self.messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                return {"reply": message.content or "", "tool_calls": trace}
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = call_tool(name, arguments)
                trace.append({"tool": name, "arguments": arguments})
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
        return {
            "reply": "Desculpa, tive uma dificuldade técnica aqui. Pode repetir?",
            "tool_calls": trace,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.messages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path, **kwargs) -> "Agent":
        agent = cls(**kwargs)
        agent.messages = json.loads(Path(path).read_text(encoding="utf-8"))
        return agent
