
"""Generate one month of synthetic books with planted errors.

    python -m data.generate --seed 42

Writes CSV files to data/generated/.
"""



import argparse
import random
from pathlib import Path
import pandas as pd
from faker import Faker

OUT_DIR = Path("data/generated")
PERIOD ="2026-10"


# (account_id, name, type)
ACCOUNTS = [
    (1000, "Cash - Operating", "asset"),
    (1100, "Accounts Receivable", "asset"),
    (1200, "Prepaid Expenses", "asset"),
    (1500, "Equipment", "asset"),
    (1510, "Accumulated Depreciation", "asset"),
    (2000, "Accounts Payable", "liability"),
    (2100, "Accrued Expenses", "liability"),
    (2200, "Payroll Liabilities", "liability"),
    (3000, "Common Stock", "equity"),
    (3100, "Retained Earnings", "equity"),
    (4000, "Product Revenue", "revenue"),
    (4100, "Service Revenue", "revenue"),
    (5000, "Cost of Goods Sold", "expense"),
    (6000, "Salaries and Wages", "expense"),
    (6100, "Rent", "expense"),
    (6200, "Software Subscriptions", "expense"),
    (6300, "Travel", "expense"),
    (6400, "Utilities", "expense"),
    (6500, "Professional Fees", "expense"),
    (6600, "Office Supplies", "expense"),
    (6700, "Marketing", "expense"),
    (6800, "Depreciation Expense", "expense"),
    (6900, "Bank Fees", "expense"),
]


# Expense account -> how many vendors book to it
VENDOR_CATEGORIES = {5000: 7, 6100: 2, 6200: 8, 6300: 6, 6400: 3, 6500: 4, 6600: 5, 6700: 5}


def make_vendors(rng, fake):
    rows = []
    for account_id, count in VENDOR_CATEGORIES.items():
        for _ in range(count):
            rows.append({"vendor_id": f"V{len(rows) + 1:03d}", "name": fake.unique.company(),
                         "account_id": account_id, "approved": True})
    # A few vendors that were never approved. Only planted errors will pay them.
    for _ in range(4):
        rows.append({"vendor_id": f"V{len(rows) + 1:03d}", "name": fake.unique.company(),
                     "account_id": rng.choice(list(VENDOR_CATEGORIES)), "approved": False})
    return pd.DataFrame(rows)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    fake = Faker()
    fake.seed_instance(args.seed)

    accounts = pd.DataFrame(ACCOUNTS, columns=["account_id", "name", "type"])
    vendors = make_vendors(rng, fake)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    accounts.to_csv(OUT_DIR / "accounts.csv", index=False)
    vendors.to_csv(OUT_DIR / "vendors.csv", index=False)
    print(f"wrote {len(accounts)} accounts and {len(vendors)} vendors to {OUT_DIR}/")


if __name__ == "__main__":
    main()