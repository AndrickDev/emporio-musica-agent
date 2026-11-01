"""Loads the store CSVs into an in-memory SQLite database.

SQLite is part of the Python standard library, so the data layer needs no
external service and no extra dependency. The CSVs are the source of truth;
the database is rebuilt on every startup, which keeps reads always fresh.
"""
import csv
import sqlite3
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


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
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
    return conn
