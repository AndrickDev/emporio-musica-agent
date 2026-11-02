"""Gera as conversas de exemplo pedidas no case, rodando o agente com o modelo REAL.

Cada cenário roda em um agente novo e vira um arquivo Markdown em examples/,
com as ferramentas chamadas e um cabeçalho dizendo modelo, data e data da loja
usada. As respostas do agente NÃO são editadas.

Uso:
    python scripts/generate_examples.py              # todos os cenários
    python scripts/generate_examples.py 3 5          # só os cenários 3 e 5
    python scripts/generate_examples.py --translate  # acrescenta tradução para o inglês
                                                     # (feita pelo mesmo modelo, marcada como tal)

Cota: cada mensagem custa de 1 a 4 chamadas ao modelo. Os 5 cenários somam
cerca de 13 mensagens (~30-40 chamadas). Em plano gratuito com limite diário
baixo, rode alguns cenários por vez.

Data da loja: os pedidos do dataset vão até 22/03/2026. Para os exemplos fazerem
sentido, a data da loja é fixada em 23/03/2026 (segunda-feira), a menos que
STORE_TODAY esteja definido no ambiente.
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

config.STORE_TODAY = os.getenv("STORE_TODAY") or "2026-03-23"

from src.agent import Agent, describe_api_error  # noqa: E402

SCENARIOS = [
    (
        "01-catalog-search.md",
        "Busca no catálogo com filtro de preço / Catalog search with a price filter",
        [
            "Quais opções de violões vocês têm custando até R$1000?",
            "E tem algum violão de nylon com captação (eletroacústico) nessa faixa?",
        ],
    ),
    (
        "02-price-payment-and-return-policy.md",
        "Preço, pagamento e política de devolução / Price, payment and return policy",
        [
            "Quanto custa o Takamine GD20?",
            "Dá pra parcelar? E no PIX sai quanto?",
            "Se eu comprar online e me arrepender, consigo devolver?",
        ],
    ),
    (
        "03-order-status-with-verification.md",
        "Não trivial: pedido com verificação de identidade e reclamação / "
        "Non-trivial: order lookup with identity check and a complaint",
        [
            "Oi! Queria saber onde está minha encomenda, o rastreio é BRJL5544332BR",
            "O e-mail da compra é cliente002@example.com",
            "Mas a previsão já passou faz tempo, isso é um absurdo!",
        ],
    ),
    (
        "04-out-of-scope-and-store-info.md",
        "Fora de escopo e informações da loja / Out of scope and store information",
        [
            "Vocês vendem cordas de violão e palhetas?",
            "Entendi. Qual o endereço da loja? Vocês abrem amanhã?",
            "Valeu! Aproveitando, você me ajuda com uma lição de matemática?",
        ],
    ),
    (
        "05-expired-and-active-promotions.md",
        "Não trivial: promoção vencida, promoções ativas e PIX / "
        "Non-trivial: expired promotion, active promotions and PIX",
        [
            "Vi que o violão Crafter CE-15 teve desconto na Black Friday. Ainda tá com desconto?",
            "E quais promoções estão ativas hoje?",
            "Se eu pagar o ukulele Kalani KAL-700T no PIX, fica ainda mais barato?",
        ],
    ),
]

TRANSLATE_PROMPT = (
    "Translate the following customer-service conversation from Brazilian Portuguese to "
    "English. Translate faithfully, do not add or remove information, keep Markdown, "
    "product names, prices and the lines starting with '> _consulta' unchanged except for "
    "translating the word 'consulta ao sistema' to 'system query'. Output only the translation."
)


def run_scenario(title: str, messages: list) -> str:
    agent = Agent()
    lines = [
        f"# {title}",
        "",
        f"> Gerado por `scripts/generate_examples.py` em {datetime.now():%Y-%m-%d %H:%M} com o modelo "
        f"`{config.MODEL}`. Data da loja usada pelo agente: {config.STORE_TODAY}. "
        "Respostas do agente sem edição. Dados de clientes do repositório são anonimizados.",
        "",
    ]
    for user_message in messages:
        lines += [f"**Cliente:** {user_message}", ""]
        result = agent.chat(user_message)
        for call in result["tool_calls"]:
            lines += [f"> _consulta ao sistema: `{call['tool']}` {call['arguments']}_", ""]
        lines += [f"**Agente:** {result['reply']}", ""]
    return "\n".join(lines)


def translate(conversation_md: str) -> str:
    agent = Agent()
    resp = agent.client.chat.completions.create(
        model=config.MODEL,
        messages=[{"role": "system", "content": TRANSLATE_PROMPT},
                  {"role": "user", "content": conversation_md.split("\n", 4)[-1]}],
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", type=int, help="números dos cenários (1 a 5)")
    parser.add_argument("--translate", action="store_true", help="acrescenta tradução para o inglês")
    parser.add_argument("--skip-existing", action="store_true",
                        help="pula cenários cujo arquivo já existe (para retomar depois de estourar a cota)")
    args = parser.parse_args()
    if not config.API_KEY:
        sys.exit("Defina LLM_API_KEY no ambiente ou no .env (veja .env.example).")

    out_dir = Path(__file__).resolve().parent.parent / "examples"
    out_dir.mkdir(exist_ok=True)
    for number, (filename, title, messages) in enumerate(SCENARIOS, start=1):
        if args.only and number not in args.only:
            continue
        if args.skip_existing and (out_dir / filename).exists():
            print(f"já existe, pulando {filename}")
            continue
        try:
            text = run_scenario(title, messages)
            if args.translate:
                text += ("\n---\n\n## English translation\n\n_Machine translation of the conversation "
                         f"above, produced by `{config.MODEL}` for reviewers; the original is the "
                         "Portuguese text._\n\n" + translate(text) + "\n")
        except Exception as exc:  # cota/rede: para sem gravar arquivo pela metade
            sys.exit(f"Parou no cenário {number} ({filename}): {describe_api_error(exc)}\n"
                     "Os cenários anteriores foram salvos. Rode de novo com --skip-existing para continuar.")
        (out_dir / filename).write_text(text, encoding="utf-8")
        print(f"gerado {filename}")


if __name__ == "__main__":
    main()
