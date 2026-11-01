"""OPTIONAL: anonymizes customer names, phones and e-mails in data/customers.csv.

Not applied by default. The case states the store is fictional and provides
these CSVs for the agent, so publishing them as-is is acceptable; this script
exists in case the author prefers a sanitized public repo anyway.

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
