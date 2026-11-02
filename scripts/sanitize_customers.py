"""Anonimiza nomes, telefones e e-mails em data/customers.csv.

JÁ FOI APLICADO neste repositório: o customers.csv versionado tem nomes
"Cliente NNN", telefones (67) 90000-NNNN e e-mails clienteNNN@example.com.
Os dados originais do case (também fictícios) não estão no histórico git.
Rodar de novo não muda nada. O script fica como registro de como foi feito.

Usage:
    python scripts/sanitize_customers.py   # rewrites data/customers.csv
"""
import csv
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "data" / "customers.csv"
rows = list(csv.DictReader(path.open(encoding="utf-8")))
for i, row in enumerate(rows, start=1):
    row["name"] = f"Cliente {i:03d}"
    row["phone"] = f"(67) 90000-{i:04d}"
    row["email"] = f"cliente{i:03d}@example.com"
with path.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"sanitized {len(rows)} customers in {path}")
