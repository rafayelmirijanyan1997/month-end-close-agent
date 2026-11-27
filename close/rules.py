"""Rules baseline: the close done with fixed logic and the same tools as the agent, with no LLM.

python -m close.rules
"""

import datetime as dt
from collections import Counter
from pathlib import Path

from close.db import DB_PATH, connect
from close.tools import check_vendor, find_duplicates, match_bank_to_gl
from close.workpaper import Workpaper

RUNS_DIR = Path("runs")


def days_between(earlier, later):
    return (dt.date.fromisoformat(later) - dt.date.fromisoformat(earlier)).days


def expense_line(entry_id, db_path):
    """The non-cash line of a payment entry, as (account_id, debit_cents)."""
    con = connect(db_path)
    row = con.execute(
        "SELECT account_id, debit_cents FROM gl WHERE entry_id = ? AND account_id != 1000",
        (entry_id,),
    ).fetchone()
    con.close()
    return row


def run_rules(db_path=DB_PATH, window_days=5):
    wp = Workpaper(db_path=db_path)
    match = match_bank_to_gl(window_days=window_days, db_path=db_path)

    # Rule 1: a deposit on the bank with no ledger entry was never recorded
    for b in match["unmatched_bank"]:
        if b["amount_cents"] > 0:
            flag = wp.flag_exception(
                "missing_deposit",
                "Deposit on the bank statement has no ledger entry",
                bank_id=b["bank_id"],
            )
            wp.draft_journal_entry(
                flag["flag_id"],
                [
                    {"account_id": 1000, "debit_cents": b["amount_cents"]},
                    {"account_id": 1100, "credit_cents": b["amount_cents"]},
                ],
                "Record unrecorded customer deposit",
            )
    # Rule 2: an unmatched bank payment and an unmatched ledger payment a few days apart whose amounts
    # differ by a whole multiple of 9 dollars are a transposition (e.g. 1,906 recorded, 1,096 paid)
    candidates = [
        g
        for g in match["unmatched_gl"] + match["possibly_outstanding_gl"]
        if g["amount_cents"] < 0
    ]
    for b in match["unmatched_bank"]:
        if b["amount_cents"] > 0:
            continue
        for g in candidates:
            diff = (
                g["amount_cents"] - b["amount_cents"]
            )  # bank paid minus ledger recorded, in cents
            if (
                0 <= days_between(g["date"], b["date"]) <= window_days
                and diff != 0
                and diff % 900 == 0
            ):
                flag = wp.flag_exception(
                    "transposed_amount",
                    f"Ledger {-g['amount_cents']} vs bank "
                    f"{-b['amount_cents']}: difference is a multiple of 9 dollars",
                    entry_id=g["entry_id"],
                    bank_id=b["bank_id"],
                )
                account, _ = expense_line(g["entry_id"], db_path)
                if diff > 0:  # the bank paid more than was recorded
                    lines = [
                        {"account_id": account, "debit_cents": diff},
                        {"account_id": 1000, "credit_cents": diff},
                    ]
                else:
                    lines = [
                        {"account_id": 1000, "debit_cents": -diff},
                        {"account_id": account, "credit_cents": -diff},
                    ]
                wp.draft_journal_entry(
                    flag["flag_id"], lines, "Correct transposed amount"
                )
                candidates.remove(g)
                break
    # Rule 3: same vendor, same amount, within a week: reverse the later entry
    for pair in find_duplicates(db_path=db_path):
        flag = wp.flag_exception(
            "duplicate_payment",
            f"Same vendor and amount as {pair['first_entry_id']}",
            entry_id=pair["second_entry_id"],
            related_entry_id=pair["first_entry_id"],
        )
        if flag["status"] == "flagged":
            account, cents = expense_line(pair["second_entry_id"], db_path)
            wp.draft_journal_entry(
                flag["flag_id"],
                [
                    {"account_id": 1000, "debit_cents": cents},
                    {"account_id": account, "credit_cents": cents},
                ],
                "Reverse duplicate payment",
            )
    # Rule 4: any payment to a vendor that is missing from, or not approved in, the vendor master
    con = connect(db_path)
    payments = con.execute(
        "SELECT entry_id, vendor_id FROM gl WHERE account_id = 1000 AND credit_cents > 0 "
        "AND vendor_id IS NOT NULL ORDER BY entry_id"
    ).fetchall()
    con.close()
    vendors = {}
    for entry_id, vendor_id in payments:
        if vendor_id not in vendors:
            vendors[vendor_id] = check_vendor(vendor_id, db_path=db_path)
        if not vendors[vendor_id].get("approved"):
            wp.flag_exception(
                "unapproved_vendor",
                f"{vendor_id} is not an approved vendor",
                entry_id=entry_id,
            )

    return wp


if __name__ == "__main__":
    wp = run_rules()
    RUNS_DIR.mkdir(exist_ok=True)
    wp.save(RUNS_DIR / "rules.json")
    print(
        f"{len(wp.flags)} flags, {len(wp.drafts)} drafts -> {RUNS_DIR / 'rules.json'}"
    )
    print(dict(Counter(f["type"] for f in wp.flags)))
