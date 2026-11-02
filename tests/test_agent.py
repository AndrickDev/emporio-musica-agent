"""Testes do loop do agente com um cliente OpenAI simulado (sem rede, sem chave).

Verificam a orquestração (execução de ferramentas, devolução dos resultados,
limite de rodadas, falhas do provedor). NÃO medem a qualidade das respostas de
um modelo real; isso se vê nas conversas de examples/.

Rodar:  python tests/test_agent.py    ou    python -m pytest tests/
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai.types.chat import ChatCompletion  # noqa: E402

from src import agent as agent_module  # noqa: E402
from src import config  # noqa: E402
from src.agent import FALLBACK_REPLY, Agent  # noqa: E402
from src.tools import StoreTools  # noqa: E402


def completion(content=None, tool_calls=None) -> ChatCompletion:
    """Resposta no formato real da API (validada pelos tipos da SDK)."""
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
            for i, (name, args) in enumerate(tool_calls)
        ]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop", "message": msg}],
    })


class FakeClient:
    """Imita client.chat.completions.create devolvendo respostas pré-definidas."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def make_agent(responses):
    tools = StoreTools(tickets_file=Path(tempfile.mkdtemp()) / "t.jsonl")
    return Agent(client=FakeClient(responses), model="fake", tools=tools)


def test_tool_result_is_sent_back_to_the_model():
    a = make_agent([
        completion(tool_calls=[("get_product_details", {"product_name": "Takamine GD20"})]),
        completion("O Takamine GD20 sai por R$ 2.199,00."),
    ])
    r = a.chat("Quanto custa o Takamine GD20?")
    assert r["reply"] == "O Takamine GD20 sai por R$ 2.199,00."
    assert r["tool_calls"][0]["result"]["product"]["price_brl"] == 2199.0
    last = a.client.requests[1][-1]
    assert last["role"] == "tool" and json.loads(last["content"])["found"]


def test_order_flow_needs_contact_before_data():
    a = make_agent([
        completion(tool_calls=[("get_order_status", {"order_id": 8})]),
        completion("Me passa o e-mail da compra?"),
        completion(tool_calls=[("get_order_status", {"order_id": 8, "customer_email": "cliente002@example.com"})]),
        completion("Seu pedido foi despachado."),
    ])
    first = a.chat("Cadê meu pedido 8?")
    assert not first["tool_calls"][0]["result"]["found"]
    second = a.chat("cliente002@example.com")
    assert second["tool_calls"][0]["result"]["order"]["status"] == "shipped"


def test_tool_round_limit_returns_fallback():
    old = config.MAX_TOOL_ROUNDS
    config.MAX_TOOL_ROUNDS = 2
    try:
        a = make_agent([completion(tool_calls=[("get_store_info", {})])] * 5)
        assert a.chat("oi")["reply"] == FALLBACK_REPLY
        assert len(a.client.requests) == 2
        assert a.messages[-1] == {"role": "assistant", "content": FALLBACK_REPLY}
    finally:
        config.MAX_TOOL_ROUNDS = old


def test_empty_reply_is_replaced():
    a = make_agent([completion("")])
    assert a.chat("oi")["reply"] == FALLBACK_REPLY


def test_provider_error_rolls_back_history():
    a = make_agent([completion("Olá!"), RuntimeError("quota")])
    a.chat("oi")
    size = len(a.messages)
    try:
        a.chat("de novo")
    except RuntimeError:
        pass
    assert len(a.messages) == size  # a rodada que falhou não fica no histórico


def test_system_prompt_has_current_date_and_no_hardcoded_facts():
    old = config.STORE_TODAY
    config.STORE_TODAY = "2026-11-03"
    try:
        prompt = agent_module.build_system_prompt()
    finally:
        config.STORE_TODAY = old
    assert "03/11/2026" in prompt and "terça-feira" in prompt
    for fact in ("R$", "3321", "3341", "Rua 14"):
        assert fact not in prompt, fact


def test_session_save_and_load():
    path = Path(tempfile.mkdtemp()) / "s.json"
    a = make_agent([completion("Olá!")])
    a.chat("oi")
    a.save(path)
    b = Agent.load(path, client=FakeClient([]), model="fake")
    assert [m["content"] for m in b.messages[1:]] == ["oi", "Olá!"]


def test_min_seconds_between_calls_is_respected():
    import time
    old = config.MIN_SECONDS_BETWEEN_CALLS
    config.MIN_SECONDS_BETWEEN_CALLS = 0.3
    try:
        a = make_agent([completion(tool_calls=[("get_store_info", {})]), completion("ok")])
        start = time.monotonic()
        a.chat("oi")
        assert time.monotonic() - start >= 0.3  # duas chamadas, uma pausa entre elas
    finally:
        config.MIN_SECONDS_BETWEEN_CALLS = old


def test_api_error_description_shows_provider_reason():
    response = SimpleNamespace(text='{"error": {"message": "Quota exceeded: requests per day"}}',
                               headers={"retry-after": "12"})
    exc = SimpleNamespace(status_code=429, response=response)
    msg = agent_module.describe_api_error(exc)
    assert "429" in msg and "requests per day" in msg
    assert agent_module._retry_after_seconds(exc, 0) == 12.0
    no_header = SimpleNamespace(status_code=429, response=SimpleNamespace(text="", headers={}))
    assert agent_module._retry_after_seconds(no_header, 1) == 30


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok - {name}")
    print(f"\nTodos os {len(tests)} testes passaram.")
