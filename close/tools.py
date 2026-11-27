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
