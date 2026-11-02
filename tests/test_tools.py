"""Verificações determinísticas da camada de ferramentas (sem chamar LLM).

Rodar:  python tests/test_tools.py      (sem dependências extras)
   ou:  python -m pytest tests/         (se tiver pytest)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.pricing import max_installments, payment_options  # noqa: E402
from src.tools import StoreTools, description_conflicts  # noqa: E402

TMP = Path(tempfile.mkdtemp())


def new_tools() -> StoreTools:
    return StoreTools(tickets_file=TMP / "tickets.jsonl")


def call(tools, name, **kwargs):
    return json.loads(tools.call(name, kwargs))


# ------------------------------------------------------------------ catálogo
def test_price_lookup_takamine_gd20_with_name_variants():
    t = new_tools()
    for name in ["Takamine GD20", "takamine gd-20", "Takamine GD 20"]:
        r = call(t, "get_product_details", product_name=name)
        assert r["found"] and r["product"]["product_id"] == 95, name
        assert r["product"]["price_brl"] == 2199.0
        assert r["product"]["availability"] == "em_estoque"


def test_ambiguous_name_returns_candidates():
    r = call(new_tools(), "get_product_details", product_name="Martin D-28")
    assert r["ambiguous"] and {c["product_id"] for c in r["candidates"]} == {93, 108}


def test_unknown_product():
    assert not call(new_tools(), "get_product_details", product_name="Stradivarius 1715")["found"]


def test_category_search_is_accent_insensitive():
    t = new_tools()
    sem = call(t, "search_products", category="Violoes", max_price=1000)
    com = call(t, "search_products", category="Violões", max_price=1000)
    assert sem["total_found"] == com["total_found"] == 12


def test_search_respects_price_and_stock_and_flags_truncation():
    r = call(new_tools(), "search_products", category="Violões", max_price=1000)
    assert r["truncated"] and len(r["products"]) == 10 and r["note"]
    assert all(p["price_brl"] <= 1000 and p["availability"] == "em_estoque" for p in r["products"])
    prices = [p["price_brl"] for p in r["products"]]
    assert prices == sorted(prices)


def test_search_uses_promotional_price():
    # Ohana CK-20: R$ 549,00 de tabela, R$ 439,20 com 20% ativo -> entra em "até R$ 450"
    r = call(new_tools(), "search_products", category="Ukuleles", max_price=450)
    ck20 = [p for p in r["products"] if p["product_id"] == 121]
    assert ck20 and ck20[0]["price_brl"] == 439.2
    assert ck20[0]["original_price_brl"] == 549.0 and ck20[0]["discount_percent"] == 20.0


def test_unknown_category_is_an_error_not_an_empty_list():
    r = call(new_tools(), "search_products", category="Acoustic guitars")
    assert "error" in r and "Violões" in r["valid_categories"]


def test_availability_states():
    t = new_tools()
    states = {pid: call(t, "get_product_details", product_id=pid)["product"]["availability"]
              for pid in (95, 96, 113, 130, 136)}
    assert states == {95: "em_estoque", 96: "sem_estoque", 113: "descontinuado",
                      130: "em_breve", 136: "descontinuado"}  # 136 tem estoque 13, mas saiu de linha


def test_unavailable_product_suggests_available_alternatives():
    r = call(new_tools(), "get_product_details", product_id=96)
    alts = r["product"]["similar_available"]
    assert alts and all(a["availability"] == "em_estoque" for a in alts)


def test_contradictory_descriptions_are_withheld():
    for pid in (135, 137, 139, 140, 142, 144):
        p = call(new_tools(), "get_product_details", product_id=pid)["product"]
        assert p["description"] is None and p["data_note"], pid
    assert call(new_tools(), "get_product_details", product_id=95)["product"]["description"]
    assert not description_conflicts("Yamaha C40", "Violão clássico Yamaha")


def test_only_active_promotions():
    r = call(new_tools(), "list_active_promotions")
    assert {p["product_id"] for p in r["promotions"]} == {90, 94, 121, 127}
    assert all(p["price_brl"] < p["original_price_brl"] for p in r["promotions"])
    # Crafter CE-15 (102) teve Black Friday, mas está inativa: preço cheio
    p = call(new_tools(), "get_product_details", product_id=102)["product"]
    assert p["price_brl"] == 3899.0 and p["discount_percent"] is None


# ------------------------------------------------------------------ pagamento
def test_installment_tiers():
    cases = {90: 1, 100: 2, 150: 3, 319: 3, 320: 4, 480: 6, 700: 7, 1200: 12, 11499: 12}
    for amount, expected in cases.items():
        assert max_installments(amount) == expected, amount


def test_pix_discount_on_list_price():
    r = call(new_tools(), "get_payment_options", product_id=95)
    assert r["pix"]["price"] == 2089.05
    assert r["credit_card"]["max_interest_free_installments"] == 12
    assert r["combined_payment_allowed"] is True


def test_pix_discount_does_not_stack_with_promotion():
    r = call(new_tools(), "get_payment_options", product_id=127)  # 359 -> 323,10 (10%)
    assert r["price_to_pay"] == 323.1 and r["pix"]["price"] == 323.1
    assert r["credit_card"]["max_interest_free_installments"] == 4


def test_combined_payment_is_strictly_above_2000():
    assert payment_options(2000.0)["combined_payment_allowed"] is False
    assert payment_options(2000.01)["combined_payment_allowed"] is True


# ------------------------------------------------------------------ pedidos e privacidade
def test_order_requires_identifier_and_contact():
    t = new_tools()
    assert not call(t, "get_order_status")["found"]
    r = call(t, "get_order_status", order_id=1)  # só o número não basta
    assert not r["found"] and "e-mail ou telefone" in r["message"]
    assert t.failed_verifications == 0  # pedir dado não conta como tentativa


def test_order_by_id_or_tracking_with_email_or_phone():
    t = new_tools()
    a = call(t, "get_order_status", order_id=1, customer_email="CLIENTE003@example.com ")
    b = call(t, "get_order_status", tracking_code="brab1234567br", customer_phone="(67) 90000-0003")
    c = call(t, "get_order_status", order_id=1, customer_phone="90000-0003")
    for r in (a, b, c):
        assert r["found"] and r["order"]["status"] == "delivered"
        assert r["order"]["tracking_code"] == "BRAB1234567BR" and r["order"]["items"]


def test_order_result_has_no_personal_data():
    r = call(new_tools(), "get_order_status", order_id=1, customer_email="cliente003@example.com")
    blob = json.dumps(r, ensure_ascii=False).lower()
    for forbidden in ("customer_id", "customer_name", "cliente 003", "example.com", "90000"):
        assert forbidden not in blob, forbidden


def test_wrong_contact_and_missing_order_look_identical():
    t = new_tools()
    wrong = call(t, "get_order_status", order_id=1, customer_email="outra@example.org")
    missing = call(t, "get_order_status", order_id=999, customer_email="outra@example.org")
    assert wrong["message"] == missing["message"] and not wrong["found"]


def test_another_customers_email_does_not_open_order():
    # e-mail do cliente 1 (dono do pedido 4) não abre o pedido 1 (cliente 3)
    assert not call(new_tools(), "get_order_status", order_id=1, customer_email="cliente001@example.com")["found"]


def test_lockout_after_three_failures():
    t = new_tools()
    for _ in range(3):
        call(t, "get_order_status", order_id=1, customer_email="errado@example.org")
    r = call(t, "get_order_status", order_id=1, customer_email="cliente003@example.com")
    assert not r["found"] and "bloqueada" in r["message"]


def test_enumeration_is_no_longer_possible():
    t = new_tools()
    found = [call(t, "get_order_status", order_id=i, customer_email="chute@example.org")["found"] for i in range(1, 21)]
    assert not any(found)


def test_every_order_opens_only_with_its_owner_email():
    import csv
    data = Path(__file__).resolve().parent.parent / "data"
    emails = {r["customer_id"]: r["email"] for r in csv.DictReader((data / "customers.csv").open(encoding="utf-8"))}
    for o in csv.DictReader((data / "orders.csv").open(encoding="utf-8")):
        r = call(new_tools(), "get_order_status", order_id=int(o["order_id"]), customer_email=emails[o["customer_id"]])
        assert r["found"] and r["order"]["order_id"] == int(o["order_id"])


def test_order_dates_use_store_today():
    old = config.STORE_TODAY
    config.STORE_TODAY = "2026-03-01"
    try:
        r = call(new_tools(), "get_order_status", order_id=8, customer_email="cliente002@example.com")
        assert r["order"]["today"] == "2026-03-01" and r["order"]["days_since_estimated_delivery"] == 1
    finally:
        config.STORE_TODAY = old


def test_ticket_only_references_verified_orders():
    t = new_tools()
    assert "error" in call(t, "create_support_ticket", ticket_type="reclamacao", summary="atraso", order_id=8)
    call(t, "get_order_status", order_id=8, customer_email="cliente002@example.com")
    r = call(t, "create_support_ticket", ticket_type="reclamacao", summary="atraso", order_id=8)
    assert r["ticket_id"].startswith("EM-") and "24 horas úteis" in r["response_time"]


# ------------------------------------------------------------------ políticas e loja
def test_return_policy_mentions_7_days():
    r = call(new_tools(), "get_store_policy", question="posso devolver um produto se me arrepender da compra?")
    assert r["found"] and any("7" in e and "arrependimento" in e.lower() for e in r["excerpts"])


def test_installment_policy_found():
    r = call(new_tools(), "get_store_policy", question="posso parcelar no cartão?")
    assert r["found"] and "Parcelamento" in r["excerpts"][0]


def test_off_topic_policy_question_finds_nothing():
    assert not call(new_tools(), "get_store_policy", question="receita de bolo de chocolate")["found"]


def test_store_info():
    assert "Rua 14 de Maio" in call(new_tools(), "get_store_info")["address"]


def test_unknown_tool_and_bad_arguments_do_not_crash():
    t = new_tools()
    assert "error" in call(t, "drop_database")
    assert "error" in json.loads(t.call("get_order_status", {"wrong_arg": 1}))


# ------------------------------------------------------------------ frete (§5)
def test_local_shipping_free_only_above_500():
    t = new_tools()
    assert call(t, "estimate_shipping", order_value_brl=500, city="Campo Grande")["shipping_fee"] == 35.0
    r = call(t, "estimate_shipping", order_value_brl=500.01, city="campo grande - MS")
    assert r["shipping_fee"] == 0.0 and r["free_shipping"] is True


def test_other_cities_never_get_an_invented_price():
    for city in ("Dourados", None):
        r = call(new_tools(), "estimate_shipping", order_value_brl=800, city=city)
        assert r["shipping_fee"] is None and "SEDEX (Correios)" in r["options"]


# ------------------------------------------------------------------ perguntas reais de cliente x manual
POLICY_QUESTIONS = [
    ("Posso trocar a boquilha do meu saxofone?", "4.4"),
    ("Quanto tempo de garantia tem um violão?", "8.1"),
    ("Vocês entregam em Dourados? Qual o prazo?", "5.2"),
    ("Posso pagar parte no PIX e parte no cartão?", "3.1"),
    ("Vocês abrem sábado? Até que horas?", "2."),
    ("O instrumento chegou quebrado, o que eu faço?", "4.2"),
    ("Meus dados pessoais ficam com vocês?", "9."),
    ("Vocês vendem cordas?", "1."),
    ("Como faço para rastrear meu pedido?", "5.3"),
    ("Tem desconto na Black Friday?", "6.1"),
]


def test_customer_questions_retrieve_the_right_policy_section():
    """A seção certa precisa estar entre os 3 trechos devolvidos ao modelo."""
    t = new_tools()
    for question, section in POLICY_QUESTIONS:
        r = call(t, "get_store_policy", question=question)
        heads = [e.split("\n")[0] for e in r.get("excerpts", [])]
        assert any(h.startswith(section) for h in heads), (question, heads)


# ------------------------------------------------------------------ execução como script
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok - {name}")
    print(f"\nTodos os {len(tests)} testes passaram.")
