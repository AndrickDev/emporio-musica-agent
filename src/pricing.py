"""Regras de pagamento do manual (§3 e §6.2) implementadas em código.

O LLM não faz contas: ele chama a ferramenta get_payment_options, que usa estas
funções. Assim o desconto do PIX e o número de parcelas são sempre os mesmos e
são testados.

Interpretações (documentadas no README porque o manual é ambíguo):
- §3.1 diz "até 3x: sem valor mínimo de parcela (exceto abaixo de R$ 50,00)".
  Lemos como: em 2x ou 3x cada parcela precisa ser de pelo menos R$ 50,00.
- 4x a 6x: parcela mínima R$ 80,00; 7x a 12x: parcela mínima R$ 100,00.
- O desconto de 5% no PIX vale sobre o preço de tabela e NÃO se aplica sobre
  preço promocional (§6.2).
- Combinar formas de pagamento só é permitido em compras ACIMA de R$ 2.000,00.
"""

PIX_DISCOUNT = 0.05
COMBINED_PAYMENT_ABOVE = 2000.00


def min_installment(n: int) -> float:
    """Valor mínimo de cada parcela para pagar em n vezes."""
    if n <= 1:
        return 0.0
    if n <= 3:
        return 50.0
    if n <= 6:
        return 80.0
    return 100.0


def max_installments(amount: float) -> int:
    """Maior número de parcelas sem juros (até 12) que respeita o mínimo da faixa."""
    for n in range(12, 0, -1):
        if n == 1 or amount / n >= min_installment(n):
            return n
    return 1


def payment_options(list_price: float, promo_price: float | None = None) -> dict:
    """Formas de pagamento para um valor. promo_price=None quando não há promoção ativa."""
    on_promo = promo_price is not None
    price = round(promo_price if on_promo else list_price, 2)
    n = max_installments(price)
    return {
        "price_to_pay": price,
        "pix": {
            "price": price if on_promo else round(list_price * (1 - PIX_DISCOUNT), 2),
            "rule": "Desconto de 5% no PIX não se aplica sobre preço promocional (manual §6.2)."
            if on_promo
            else "5% de desconto no PIX sobre o preço de tabela (manual §3).",
        },
        "debit_card": {"price": price},
        "boleto": {"price": price, "note": "Compensação em até 3 dias úteis (manual §3)."},
        "credit_card": {
            "max_interest_free_installments": n,
            "installment_value": round(price / n, 2),
            "rule": "Sem juros. Parcela mínima: 2-3x R$ 50; 4-6x R$ 80; 7-12x R$ 100 (manual §3.1).",
        },
        "combined_payment_allowed": price > COMBINED_PAYMENT_ABOVE,
    }


# ---------------------------------------------------------------- frete (§5)
LOCAL_FREE_SHIPPING_ABOVE = 500.00
LOCAL_SHIPPING_FEE = 35.00


def shipping_estimate(order_value: float, city: str | None) -> dict:
    """Regras de frete do manual.

    §5.1: na região metropolitana de Campo Grande, frete grátis ACIMA de R$ 500,00;
    abaixo disso, taxa fixa de R$ 35,00; prazo de 1 a 3 dias úteis, por motoboy.
    O manual não lista as cidades da região metropolitana, então só "Campo Grande"
    recebe a regra local; outras cidades caem na §5.2, cujo valor depende de CEP,
    peso e dimensões e NÃO está nos dados (o agente não deve estimar).
    """
    from .database import norm

    city_norm = norm(city or "").replace("-", " ").replace("/", " ").split()
    if city_norm[:2] == ["campo", "grande"]:
        free = order_value > LOCAL_FREE_SHIPPING_ABOVE
        return {
            "region": "Campo Grande (entrega local)",
            "shipping_fee": 0.0 if free else LOCAL_SHIPPING_FEE,
            "free_shipping": free,
            "delivery_time": "1 a 3 dias úteis, por motoboy próprio; o cliente recebe uma ligação antes",
            "source": "manual §5.1",
        }
    return {
        "region": f"Fora de Campo Grande ({city or 'cidade não informada'})",
        "shipping_fee": None,
        "options": {
            "PAC (Correios)": "5 a 12 dias úteis",
            "SEDEX (Correios)": "2 a 5 dias úteis",
            "Jadlog (.package)": "3 a 8 dias úteis",
        },
        "note": ("O valor depende do CEP, peso e dimensões e não está disponível para o assistente; não "
                 "estime. Instrumentos grandes podem exigir cotação especial. Envios têm rastreio e seguro. "
                 "Ofereça registrar o pedido de cotação para a equipe."),
        "source": "manual §5.2",
    }
