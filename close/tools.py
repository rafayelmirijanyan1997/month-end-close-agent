"""Tools shared by the rules baseline and the agent. Each returns plain Python data."""

import datetime as dt
import sqlite3

from close.db import DB_PATH, connect

MAX_ROWS = 50


def query_ledger(sql, db_path=DB_PATH):
    """Run one read-only SELECT query and return at most MAX_ROWS rows."""
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ValueError("only SELECT queries are allowed")
    con = connect(db_path)
    try:
        cursor = con.execute(sql)
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchmany(
            MAX_ROWS + 1
        )  # one extra row tells us whether we cut anything off
    finally:
        con.close()
    return {
        "columns": columns,
        "rows": [list(r) for r in rows[:MAX_ROWS]],
        "truncated": len(rows) > MAX_ROWS,
    }


def match_bank_to_gl(window_days=5, db_path=DB_PATH):
    """Pair each bank line with a ledger cash line of the same amount, dated 0 to window_days earlier.

    Returns how many lines matched and the lines left over on each side. Unmatched ledger lines
    from the last window_days of the month are listed separately: they may simply clear next month.
    """
    con = connect(db_path)
    con.row_factory = sqlite3.Row
    gl = [
        dict(r)
        for r in con.execute(
            "SELECT entry_id, date, debit_cents - credit_cents AS amount_cents, vendor_id, memo "
            "FROM gl WHERE account_id = 1000 ORDER BY date, entry_id"
        )
    ]
    bank = [
        dict(r)
        for r in con.execute(
            "SELECT bank_id, date, amount_cents, description FROM bank ORDER BY date, bank_id"
        )
    ]
    con.close()

    open_gl = {}  # amount_cents -> ledger lines with that amount not yet matched
    for line in gl:
        open_gl.setdefault(line["amount_cents"], []).append(line)

    matched, unmatched_bank = 0, []
    for b in bank:
        bank_date = dt.date.fromisoformat(b["date"])
        candidates = [
            g
            for g in open_gl.get(b["amount_cents"], [])
            if 0 <= (bank_date - dt.date.fromisoformat(g["date"])).days <= window_days
        ]
        if not candidates:
            unmatched_bank.append(b)
            continue
        best = min(
            candidates,
            key=lambda g: (bank_date - dt.date.fromisoformat(g["date"])).days,
        )
        open_gl[b["amount_cents"]].remove(best)
        matched += 1

    leftover = sorted(
        (g for lines in open_gl.values() for g in lines),
        key=lambda g: (g["date"], g["entry_id"]),
    )
    cutoff = (
        dt.date.fromisoformat(gl[-1]["date"]) - dt.timedelta(days=window_days)
    ).isoformat()
    return {
        "matched": matched,
        "unmatched_bank": unmatched_bank,
        "unmatched_gl": [g for g in leftover if g["date"] <= cutoff],
        "possibly_outstanding_gl": [g for g in leftover if g["date"] > cutoff],
    }


def find_duplicates(window_days=7, db_path=DB_PATH):
    """Pairs of payments to the same vendor for the same amount, no more than window_days apart."""
    sql = """
        SELECT a.vendor_id, a.credit_cents AS amount_cents,
               a.entry_id AS first_entry_id, a.date AS first_date,
               b.entry_id AS second_entry_id, b.date AS second_date, a.memo
        FROM gl AS a
        JOIN gl AS b
          ON a.vendor_id = b.vendor_id
         AND a.credit_cents = b.credit_cents
         AND a.entry_id < b.entry_id
        WHERE a.account_id = 1000 AND b.account_id = 1000
          AND a.credit_cents > 0
          AND ABS(julianday(b.date) - julianday(a.date)) <= ?
        ORDER BY a.date, a.entry_id
    """
    con = connect(db_path)
    con.row_factory = sqlite3.Row
    pairs = [dict(r) for r in con.execute(sql, (window_days,))]
    con.close()
    return pairs


def check_vendor(vendor_id, db_path=DB_PATH):
    """Look a vendor up in the vendor master: is it approved, and which account does it book to?"""
    con = connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT vendor_id, name, account_id, approved FROM vendors WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    con.close()
    if row is None:
        return {"vendor_id": vendor_id, "found": False}
    return {
        "vendor_id": row["vendor_id"],
        "found": True,
        "name": row["name"],
        "default_account_id": row["account_id"],
        "approved": bool(row["approved"]),
    }


def summarize_expense_memos(db_path=DB_PATH):
    """Every distinct description of this month's expense entries, with how often it occurs.

    About a thousand expense lines collapse to a few dozen descriptions, so unusual ones stand out.
    For a description used at most 3 times, entry_ids lists its entries.
    """
    sql = """
        SELECT memo, account_id, COUNT(*) AS entries, SUM(debit_cents) AS total_cents,
               MIN(date) AS first_date, MAX(date) AS last_date,
               CASE WHEN COUNT(*) <= 3 THEN GROUP_CONCAT(entry_id) END AS entry_ids
        FROM gl
        WHERE debit_cents > 0
          AND account_id IN (SELECT account_id FROM accounts WHERE type = 'expense')
        GROUP BY memo, account_id
        ORDER BY memo
    """
    con = connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql)]
    con.close()
    return rows
