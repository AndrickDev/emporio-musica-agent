"""Tools the agent can call, in OpenAI function-calling format.

Every answer about prices, stock, orders, promotions, policies or store info
must come from one of these tools; the LLM never answers from memory. This
mirrors the store's own rule: never state a price or deadline without
checking the system first.
"""
import json

from .database import load_db
from .policies import search_policies

_DB = load_db()

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search the instrument catalog by text, category and/or maximum "
                "price. Use for any question about products, prices or availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Term to match in product name/description, e.g. 'violao nylon' or 'Takamine'.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category name, e.g. 'Violoes', 'Guitarras', 'Teclados e Pianos'.",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price in BRL.",
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "If true, return only products with stock > 0.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Get full details of one product: price, stock, specs, description and any active promotion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Exact product id, if known."},
                    "product_name": {"type": "string", "description": "Product name or distinctive part of it, e.g. 'Takamine GD20'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_promotions",
            "description": "List promotions currently active in the system, with original and discounted prices.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": (
                "Look up an order by id, tracking code or the customer's registered "
                "e-mail. Use for any question about order status or delivery. At "
                "least one identifier is required; ask the customer for one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Order number."},
                    "tracking_code": {"type": "string", "description": "Tracking code, format BRxxxxxxxxxBR."},
                    "customer_email": {"type": "string", "description": "Customer's registered e-mail."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_store_policy",
            "description": (
                "Consult the store's internal policy manual (exchanges, returns, "
                "shipping, payment, warranty, opening hours, service rules). Use "
                "whenever the answer depends on a store policy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "What to look up in the policy manual."},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_store_info",
            "description": "Get general store information: address, phone, WhatsApp, e-mail and opening hours.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _rows(cur) -> list:
    return [dict(r) for r in cur.fetchall()]


def _search_products(query=None, category=None, max_price=None, in_stock_only=False):
    sql = (
        "SELECT p.product_id, p.name, p.price_brl, p.stock_quantity, c.name AS category "
        "FROM products p JOIN categories c ON c.category_id = p.category_id "
        "WHERE p.status = 'active'"
    )
    params = []
    if query:
        for word in str(query).split():
            if len(word) > 1:
                sql += " AND LOWER(p.name || ' ' || p.description) LIKE ?"
                params.append(f"%{word.lower()}%")
    if category:
        sql += " AND LOWER(c.name) LIKE ?"
        params.append(f"%{str(category).lower()}%")
    if max_price is not None:
        sql += " AND CAST(p.price_brl AS REAL) <= ?"
        params.append(float(max_price))
    if in_stock_only:
        sql += " AND CAST(p.stock_quantity AS INTEGER) > 0"
    sql += " ORDER BY CAST(p.price_brl AS REAL) LIMIT 10"
    results = _rows(_DB.execute(sql, params))
    return {"count": len(results), "products": results}


def _get_product_details(product_id=None, product_name=None):
    row = None
    if product_id is not None:
        row = _DB.execute(
            "SELECT * FROM products WHERE product_id = ?", (str(product_id),)
        ).fetchone()
    if row is None and product_name:
        row = _DB.execute(
            "SELECT * FROM products WHERE LOWER(name) LIKE ? LIMIT 1",
            (f"%{str(product_name).lower()}%",),
        ).fetchone()
    if row is None:
        return {"found": False, "message": "Product not found in the catalog."}
    product = dict(row)
    try:
        product["specs"] = json.loads(product.get("specs") or "{}")
    except json.JSONDecodeError:
        pass
    category = _DB.execute(
        "SELECT name FROM categories WHERE category_id = ?", (product["category_id"],)
    ).fetchone()
    product["category"] = category["name"] if category else None
    promo = _DB.execute(
        "SELECT discount_percent, description FROM promotions "
        "WHERE product_id = ? AND is_active = '1'",
        (product["product_id"],),
    ).fetchone()
    if promo:
        price = float(product["price_brl"])
        product["active_promotion"] = dict(promo)
        product["promotional_price_brl"] = round(price * (1 - int(promo["discount_percent"]) / 100), 2)
    else:
        product["active_promotion"] = None
    return {"found": True, "product": product}


def _list_active_promotions():
    rows = _rows(
        _DB.execute(
            "SELECT pr.name, pr.price_brl, pr.stock_quantity, pm.discount_percent, "
            "pm.description FROM promotions pm "
            "JOIN products pr ON pr.product_id = pm.product_id "
            "WHERE pm.is_active = '1' AND pr.status = 'active'"
        )
    )
    for r in rows:
        r["promotional_price_brl"] = round(
            float(r["price_brl"]) * (1 - int(r["discount_percent"]) / 100), 2
        )
    return {"count": len(rows), "promotions": rows}


def _get_order_status(order_id=None, tracking_code=None, customer_email=None):
    if not any([order_id, tracking_code, customer_email]):
        return {
            "found": False,
            "message": "An identifier is required: order number, tracking code or registered e-mail.",
        }
    sql = (
        "SELECT o.*, c.name AS customer_name FROM orders o "
        "JOIN customers c ON c.customer_id = o.customer_id WHERE "
    )
    if order_id is not None:
        sql += "o.order_id = ?"
        params = (str(order_id),)
    elif tracking_code:
        sql += "o.tracking_code = ?"
        params = (tracking_code,)
    else:
        sql += "LOWER(c.email) = ? ORDER BY o.order_date DESC LIMIT 1"
        params = (str(customer_email).lower(),)
    row = _DB.execute(sql, params).fetchone()
    if row is None:
        return {"found": False, "message": "No order found for the given identifier."}
    order = dict(row)
    items = _rows(
        _DB.execute(
            "SELECT p.name, oi.quantity FROM order_items oi "
            "JOIN products p ON p.product_id = oi.product_id WHERE oi.order_id = ?",
            (order["order_id"],),
        )
    )
    order["items"] = items
    return {"found": True, "order": order}


def _get_store_policy(question):
    excerpts = search_policies(question or "", top_k=3)
    if not excerpts:
        return {"found": False, "message": "No policy excerpt matched the question."}
    return {"found": True, "excerpts": excerpts}


def _get_store_info():
    return {
        "store": "Empório da Música",
        "tagline": "Sua música começa aqui.",
        "address": "Rua 14 de Maio, 3200 - Centro, Campo Grande - MS, CEP 79202-333",
        "phone": "(67) 3341-4444",
        "whatsapp": "(67) 3321-4500",
        "email": "contato@emporiodamusica.com.br",
        "opening_hours": {
            "monday_to_friday": "09:00 - 18:00",
            "saturday": "09:00 - 13:00",
            "sunday_and_holidays": "closed",
        },
        "note": "The store sells musical instruments only, no accessories.",
    }


_FUNCTIONS = {
    "search_products": _search_products,
    "get_product_details": _get_product_details,
    "list_active_promotions": _list_active_promotions,
    "get_order_status": _get_order_status,
    "get_store_policy": _get_store_policy,
    "get_store_info": _get_store_info,
}


def call_tool(name: str, arguments: dict) -> str:
    fn = _FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
    try:
        result = fn(**(arguments or {}))
    except Exception as exc:  # surface failures to the model instead of crashing
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result, ensure_ascii=False)
