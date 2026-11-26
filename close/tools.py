"""Tools shared by the rules baseline and the agent. Each returns plain Python data."""

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
