"""Generates the example conversations required by the case.

Runs scripted scenarios through a fresh agent and saves one Markdown file per
scenario under examples/, including the tool calls made along the way.

Usage:
    python scripts/generate_examples.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import Agent  # noqa: E402

SCENARIOS = [
    (
        "01-catalog-search.md",
        "Catalog search with price filter",
        ["Quais opções de violões vocês têm custando até R$1000?"],
    ),
    (
        "02-price-and-return-policy.md",
        "Product price, then return policy (regret)",
        [
            "Quanto custa o Takamine GD20?",
            "E se eu comprar e me arrepender, consigo devolver?",
        ],
    ),
    (
        "03-order-status.md",
        "Order status lookup by tracking code",
        [
            "Oi! Queria saber onde está minha encomenda, o rastreio é BRAB1234567BR",
        ],
    ),
    (
        "04-out-of-scope-and-store-info.md",
        "Out-of-scope request (accessories) redirected, then address and hours",
        [
            "Vocês vendem cordas de violão e palhetas?",
            "Entendi. Qual o endereço da loja e o horário de funcionamento?",
        ],
    ),
    (
        "05-active-promotions.md",
        "Non-trivial: asks for a discount on a product whose promotion expired",
        [
            "Vi que o violão Yamaha C40 já teve promoção. Tem algum desconto nele agora?",
            "E tem alguma promoção ativa na loja hoje?",
        ],
    ),
]


def run() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "examples"
    out_dir.mkdir(exist_ok=True)
    for filename, title, messages in SCENARIOS:
        agent = Agent()
        lines = [f"# {title}", ""]
        for user_message in messages:
            lines.append(f"**Cliente:** {user_message}")
            lines.append("")
            result = agent.chat(user_message)
            for call in result["tool_calls"]:
                lines.append(f"> _consulta ao sistema: `{call['tool']}` {call['arguments']}_")
                lines.append("")
            lines.append(f"**Agente:** {result['reply']}")
            lines.append("")
        path = out_dir / filename
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    run()
