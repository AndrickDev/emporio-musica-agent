"""Deterministic checks for the tool layer (no LLM calls).

Run with: python tests/test_tools.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools import call_tool  # noqa: E402

PASSED = 0


def check(label: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {label}"
    PASSED += 1
    print(f"ok - {label}")


def call(name, **kwargs):
    return json.loads(call_tool(name, kwargs))


# Product details: known product from the catalog
details = call("get_product_details", product_name="Takamine GD20")
check("Takamine GD20 found", details["found"])
check("Takamine GD20 price is 2199", float(details["product"]["price_brl"]) == 2199)
check("Takamine GD20 in stock", int(details["product"]["stock_quantity"]) > 0)

# Catalog search with price ceiling
search = call("search_products", query="violão", max_price=1000, in_stock_only=True)
check("violao search under R$1000 returns results", search["count"] >= 3)
check(
    "all results respect the price ceiling",
    all(float(p["price_brl"]) <= 1000 for p in search["products"]),
)

# Promotions: exactly the active ones
promos = call("list_active_promotions")
check("active promotions listed", promos["count"] > 0)
check(
    "promotional price lower than original",
    all(p["promotional_price_brl"] < float(p["price_brl"]) for p in promos["promotions"]),
)

# Order lookup
order = call("get_order_status", order_id=1)
check("order 1 found", order["found"])
check("order 1 delivered", order["order"]["status"] == "delivered")
check("order 1 has tracking code", order["order"]["tracking_code"] == "BRAB1234567BR")
check("order 1 has items", len(order["order"]["items"]) > 0)
missing = call("get_order_status")
check("order lookup requires an identifier", not missing["found"])

# Policy retrieval
policy = call("get_store_policy", question="posso devolver um produto se me arrepender da compra?")
check("policy excerpts found", policy["found"])
check(
    "return policy mentions 7 days",
    any("7" in e and "arrependimento" in e.lower() for e in policy["excerpts"]),
)

# Store info
info = call("get_store_info")
check("store address present", "Rua 14 de Maio" in info["address"])

print(f"\nAll {PASSED} checks passed.")
