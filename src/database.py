"""Carrega os CSVs da loja em um banco SQLite em memória.

O SQLite já vem com o Python: a camada de dados não precisa de serviço externo
nem de dependência extra. Os CSVs são a fonte da verdade; o banco é recriado a
cada inicialização, então as leituras estão sempre atualizadas.

Também registramos duas funções SQL próprias, usadas nas buscas:
- norm(texto): minúsculas e sem acento ("Violões" -> "violoes"). O LOWER() do
  SQLite só trata letras ASCII, então sem isso "Violoes" não encontrava "Violões".
- compact(texto): só letras e números ("GD-20" -> "gd20"), para que códigos de
  modelo funcionem com ou sem hífen/espaço.
"""
import csv
import re
import sqlite3
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

TABLES = {
    "categories": "categories.csv",
    "products": "products.csv",
    "customers": "customers.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "promotions": "promotions.csv",
}


def norm(text) -> str:
    """Minúsculas e sem acentos."""
    if text is None:
        return ""
    decomposed = unicodedata.normalize("NFD", str(text).lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def compact(text) -> str:
    """Somente letras e números, sem acento: 'GD-20' e 'gd 20' viram 'gd20'."""
    return re.sub(r"[^a-z0-9]", "", norm(text))


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.create_function("norm", 1, norm, deterministic=True)
    conn.create_function("compact", 1, compact, deterministic=True)
    for table, filename in TABLES.items():
        path = DATA_DIR / filename
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        header, body = rows[0], rows[1:]
        cols = ", ".join(_quote_ident(c) for c in header)
        conn.execute(f"CREATE TABLE {_quote_ident(table)} ({cols})")
        placeholders = ", ".join("?" for _ in header)
        conn.executemany(
            f"INSERT INTO {_quote_ident(table)} VALUES ({placeholders})", body
        )
    conn.execute(CATALOG_VIEW)
    return conn


# Visão única do catálogo: preço de tabela, promoção ATIVA (se houver) e preço
# atual já calculado. Todas as ferramentas de produto leem daqui, então a regra
# "preço promocional vale só se a promoção estiver ativa" fica em um lugar só.
# Se um produto tivesse duas promoções ativas (não acontece nos dados), vale a
# maior, porque o manual diz que promoções não são cumulativas (§6.2).
CATALOG_VIEW = """
CREATE VIEW catalog AS
SELECT
    CAST(p.product_id AS INTEGER)      AS product_id,
    p.name                             AS name,
    p.description                      AS description,
    p.specs                            AS specs,
    p.status                           AS status,
    CAST(p.stock_quantity AS INTEGER)  AS stock_quantity,
    CAST(p.price_brl AS REAL)          AS list_price,
    c.name                             AS category,
    CAST(p.category_id AS INTEGER)     AS category_id,
    pm.discount_percent                AS discount_percent,
    pm.promo_name                      AS promo_name,
    ROUND(CAST(p.price_brl AS REAL) * (1 - COALESCE(pm.discount_percent, 0) / 100.0), 2)
                                       AS current_price
FROM products p
JOIN categories c ON c.category_id = p.category_id
LEFT JOIN (
    SELECT product_id,
           MAX(CAST(discount_percent AS REAL)) AS discount_percent,
           description                          AS promo_name
    FROM promotions
    WHERE is_active = '1'
    GROUP BY product_id
) pm ON pm.product_id = p.product_id
"""
