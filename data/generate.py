"""Generate one month of synthetic books with planted errors.

    python -m data.generate --seed 42

Writes CSV files to data/generated/.
"""

import argparse
import random
from pathlib import Path
import pandas as pd
from faker import Faker
import datetime as dt

import json

OUT_DIR = Path("data/generated")
PERIOD = "2026-10"


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
VENDOR_CATEGORIES = {
    5000: 7,
    6100: 2,
    6200: 8,
    6300: 6,
    6400: 3,
    6500: 4,
    6600: 5,
    6700: 5,
}

# Expense account -> (min, max) payment size in dollars
AMOUNT_RANGES = {
    5000: (500, 20_000),
    6100: (8_000, 15_000),
    6200: (50, 3_000),
    6300: (100, 2_500),
    6400: (200, 1_500),
    6500: (1_000, 12_000),
    6600: (20, 600),
    6700: (300, 8_000),
}
N_PAYMENTS = 1080
N_RECEIPTS = 900
N_INVOICES = 950


def make_vendors(rng, fake):
    rows = []
    for account_id, count in VENDOR_CATEGORIES.items():
        for _ in range(count):
            rows.append(
                {
                    "vendor_id": f"V{len(rows) + 1:03d}",
                    "name": fake.unique.company(),
                    "account_id": account_id,
                    "approved": True,
                }
            )
    # A few vendors that were never approved. Only planted errors will pay them.
    for _ in range(4):
        rows.append(
            {
                "vendor_id": f"V{len(rows) + 1:03d}",
                "name": fake.unique.company(),
                "account_id": rng.choice(list(VENDOR_CATEGORIES)),
                "approved": False,
            }
        )
    return pd.DataFrame(rows)


def business_days(period):
    """Every Monday-to-Friday date in the month, e.g. '2026-10'."""
    year, month = map(int, period.split("-"))
    day = dt.date(year, month, 1)
    days = []
    while day.month == month:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def random_cents(rng, low_dollars, high_dollars):
    return rng.randint(low_dollars * 100, high_dollars * 100)


class Ledger:
    """Collects journal-entry lines and refuses any entry that does not balance."""

    def __init__(self):
        self.lines = []
        self.n_entries = 0

    def post(self, date, lines, memo, vendor_id=""):
        debits = sum(debit for _, debit, _ in lines)
        credits = sum(credit for _, _, credit in lines)
        if debits != credits:
            raise ValueError(
                f"unbalanced entry '{memo}': debits {debits} != credits {credits}"
            )
        self.n_entries += 1
        entry_id = f"JE{self.n_entries:05d}"
        for account_id, debit, credit in lines:
            self.lines.append(
                {
                    "entry_id": entry_id,
                    "date": date.isoformat(),
                    "account_id": account_id,
                    "debit_cents": debit,
                    "credit_cents": credit,
                    "vendor_id": vendor_id,
                    "memo": memo,
                }
            )
        return entry_id


def make_ledger(rng, vendors, days):
    planned = []  # (date, lines, memo, vendor_id); posted in date order at the end
    approved = vendors[vendors["approved"]]
    month_end = days[-1]

    # Rent on the first business day
    for _, v in approved[approved["account_id"] == 6100].iterrows():
        cents = random_cents(rng, *AMOUNT_RANGES[6100])
        planned.append(
            (
                days[0],
                [(6100, cents, 0), (1000, 0, cents)],
                f"Rent - {v['name']}",
                v["vendor_id"],
            )
        )

    # Payroll twice a month: gross wages, 22% withheld, net pay leaves cash
    for day in (days[10], month_end):
        gross = random_cents(rng, 150_000, 170_000)
        withheld = gross * 22 // 100
        planned.append(
            (
                day,
                [(6000, gross, 0), (2200, 0, withheld), (1000, 0, gross - withheld)],
                "Payroll",
                "",
            )
        )

    # Vendor payments (rent vendors excluded: already paid above)
    others = approved[approved["account_id"] != 6100]
    for _ in range(N_PAYMENTS):
        v = others.iloc[rng.randrange(len(others))]
        cents = random_cents(rng, *AMOUNT_RANGES[v["account_id"]])
        planned.append(
            (
                rng.choice(days),
                [(v["account_id"], cents, 0), (1000, 0, cents)],
                f"Payment - {v['name']}",
                v["vendor_id"],
            )
        )

    # Sales invoices: revenue earned on credit. No cash moves, so not on the bank statement.
    for _ in range(N_INVOICES):
        cents = random_cents(rng, 200, 25_000)
        revenue_account = rng.choice([4000, 4100])
        planned.append(
            (
                rng.choice(days),
                [(1100, cents, 0), (revenue_account, 0, cents)],
                "Sales invoice",
                "",
            )
        )

    # Customer receipts: customers paying their invoices
    for _ in range(N_RECEIPTS):
        cents = random_cents(rng, 200, 25_000)
        planned.append(
            (
                rng.choice(days),
                [(1000, cents, 0), (1100, 0, cents)],
                "Customer receipt",
                "",
            )
        )

    # Month-end entries. Depreciation and the accrual never touch cash, so they are not on the bank statement.
    planned.append(
        (
            month_end,
            [(6800, 420_000, 0), (1510, 0, 420_000)],
            "Monthly depreciation",
            "",
        )
    )
    planned.append(
        (month_end, [(6500, 600_000, 0), (2100, 0, 600_000)], "Accrue audit fees", "")
    )
    planned.append(
        (month_end, [(6900, 4_500, 0), (1000, 0, 4_500)], "Bank service fee", "")
    )

    ledger = Ledger()
    for date, lines, memo, vendor_id in sorted(planned, key=lambda e: e[0]):
        ledger.post(date, lines, memo, vendor_id)
    return pd.DataFrame(ledger.lines)


def add_business_days(date, n):
    """The date n business days after `date` (weekends skipped)."""
    while n > 0:
        date += dt.timedelta(days=1)
        if date.weekday() < 5:
            n -= 1
    return date


def bank_description(memo):
    """Turn a ledger memo into the kind of text a bank prints."""
    if memo.startswith(("Payment - ", "Rent - ")):
        return "ACH DEBIT " + memo.split(" - ", 1)[1].upper()[:22]
    if memo == "Customer receipt":
        return "DEPOSIT"
    return memo.upper()


def make_bank(rng, gl, month_end):
    """The bank statement for the month, built from the ledger's cash lines."""
    cash = gl[gl["account_id"] == 1000]
    rows = []
    for _, line in cash.iterrows():
        amount = int(
            line["debit_cents"] - line["credit_cents"]
        )  # + money in, - money out
        if line["memo"] == "Bank service fee":
            delay = 0  # the bank charges its own fee on the day
        elif amount > 0:
            delay = rng.choice([0, 0, 1])  # deposits usually clear the same day
        else:
            delay = rng.choice(
                [1, 2, 2, 3]
            )  # payments take 1 to 3 business days to clear
        cleared = add_business_days(dt.date.fromisoformat(line["date"]), delay)
        if cleared > month_end:
            continue  # clears next month: an outstanding item, so not on this statement
        rows.append(
            {
                "date": cleared.isoformat(),
                "amount_cents": amount,
                "description": bank_description(line["memo"]),
                "entry_id": line["entry_id"],
            }
        )
    bank = pd.DataFrame(rows).sort_values("date", kind="stable").reset_index(drop=True)
    bank.insert(0, "bank_id", [f"B{i + 1:05d}" for i in range(len(bank))])
    return bank


ERRORS_PER_TYPE = 8


def fix_line(account_id, debit_cents, credit_cents):
    return {
        "account_id": int(account_id),
        "debit_cents": int(debit_cents),
        "credit_cents": int(credit_cents),
    }


class Planter:
    """Plants known errors into correct books and records each one for the answer key."""

    def __init__(self, rng, gl, bank, vendors, days):
        self.rng, self.gl, self.bank, self.vendors, self.days = (
            rng,
            gl,
            bank,
            vendors,
            days,
        )
        self.used = set()  # entries that already carry an error
        self.errors = []
        self.n_new = 0

    def cents_of(self, entry_id):
        cash = self.gl[
            (self.gl["entry_id"] == entry_id) & (self.gl["account_id"] == 1000)
        ].iloc[0]
        return int(abs(cash["debit_cents"] - cash["credit_cents"]))

    def pick(self, memo_prefix, keep=lambda cents: True):
        """ERRORS_PER_TYPE unused entries whose memo starts with memo_prefix and whose cash line is on the bank."""
        on_bank = set(self.bank["entry_id"])
        candidates = sorted(
            e
            for e in self.gl.loc[
                self.gl["memo"].str.startswith(memo_prefix), "entry_id"
            ].unique()
            if e in on_bank and e not in self.used and keep(self.cents_of(e))
        )
        chosen = self.rng.sample(candidates, ERRORS_PER_TYPE)
        self.used.update(chosen)
        return chosen

    def record(self, error_type, ref, fix, note, related=None):
        self.errors.append(
            {
                "type": error_type,
                "ref": ref,
                "related": related,
                "fix": fix,
                "note": note,
            }
        )

    def duplicate_payments(self):
        for i, entry_id in enumerate(self.pick("Payment - ")):
            lines = self.gl[self.gl["entry_id"] == entry_id]
            date = dt.date.fromisoformat(lines["date"].iloc[0])
            copy_date = min(
                add_business_days(date, self.rng.randint(0, 4)), self.days[-1]
            )
            copy_id = f"DUP{i + 1}"
            self.gl = pd.concat(
                [self.gl, lines.assign(entry_id=copy_id, date=copy_date.isoformat())],
                ignore_index=True,
            )
            expense = lines[lines["account_id"] != 1000].iloc[0]
            cents = int(expense["debit_cents"])
            self.record(
                "duplicate_payment",
                copy_id,
                [fix_line(1000, cents, 0), fix_line(expense["account_id"], 0, cents)],
                "Invoice entered twice; the bank paid it once. Reverse the copy.",
                related=entry_id,
            )

    def missing_deposits(self):
        for entry_id in self.pick("Customer receipt"):
            cents = self.cents_of(entry_id)
            self.gl = self.gl[
                self.gl["entry_id"] != entry_id
            ]  # the receipt was never recorded
            self.record(
                "missing_deposit",
                entry_id,
                [fix_line(1000, cents, 0), fix_line(1100, 0, cents)],
                "Customer deposit on the bank statement was never recorded.",
            )

    def renumber(self):
        """Final ids in date order, shuffled within each day, so no error can be spotted by its id."""
        keys = {e: self.rng.random() for e in sorted(self.gl["entry_id"].unique())}
        gl = self.gl.assign(
            _key=self.gl["entry_id"].map(keys), _line=range(len(self.gl))
        )
        gl = (
            gl.sort_values(["date", "_key", "_line"])
            .drop(columns=["_key", "_line"])
            .reset_index(drop=True)
        )
        self.gl_map = {
            old: f"JE{i + 1:05d}" for i, old in enumerate(dict.fromkeys(gl["entry_id"]))
        }
        gl["entry_id"] = gl["entry_id"].map(self.gl_map)
        bank = self.bank.assign(_key=[self.rng.random() for _ in range(len(self.bank))])
        bank = (
            bank.sort_values(["date", "_key"])
            .drop(columns="_key")
            .reset_index(drop=True)
        )
        bank["bank_id"] = [f"B{i + 1:05d}" for i in range(len(bank))]
        self.bank_map = dict(zip(bank["entry_id"], bank["bank_id"]))
        self.gl, self.bank = gl, bank

    def answer_key(self):
        return [
            {
                "error_id": f"E{i + 1:02d}",
                "type": e["type"],
                "entry_id": self.gl_map.get(e["ref"]),
                "bank_id": self.bank_map.get(e["ref"]),
                "related_entry_id": self.gl_map.get(e["related"]),
                "fix": e["fix"],
                "note": e["note"],
            }
            for i, e in enumerate(self.errors)
        ]


def plant_errors(rng, gl, bank, vendors, days):
    p = Planter(rng, gl, bank, vendors, days)
    p.duplicate_payments()
    p.missing_deposits()
    p.renumber()
    return p.gl, p.bank, p.answer_key()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    fake = Faker()
    fake.seed_instance(args.seed)

    accounts = pd.DataFrame(ACCOUNTS, columns=["account_id", "name", "type"])
    vendors = make_vendors(rng, fake)

    days = business_days(PERIOD)
    gl = make_ledger(rng, vendors, days)
    bank = make_bank(rng, gl, days[-1])

    gl, bank, errors = plant_errors(rng, gl, bank, vendors, days)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    accounts.to_csv(OUT_DIR / "accounts.csv", index=False)
    vendors.to_csv(OUT_DIR / "vendors.csv", index=False)
    gl.to_csv(OUT_DIR / "gl.csv", index=False)
    bank.drop(columns="entry_id").to_csv(OUT_DIR / "bank.csv", index=False)
    answer_key = {"seed": args.seed, "period": PERIOD, "errors": errors}
    (OUT_DIR / "ground_truth.json").write_text(json.dumps(answer_key, indent=2))
    print(
        f"wrote {len(accounts)} accounts, {len(vendors)} vendors, "
        f"{gl['entry_id'].nunique()} journal entries ({len(gl)} lines) "
        f"and {len(bank)} bank lines to {OUT_DIR}/"
    )


if __name__ == "__main__":
    main()
