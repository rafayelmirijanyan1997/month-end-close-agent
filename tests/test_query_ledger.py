import sqlite3

import pytest

from close.tools import MAX_ROWS, query_ledger


def test_returns_columns_and_rows(db):
    result = query_ledger(
        "SELECT account_id, name FROM accounts ORDER BY account_id", db_path=db
    )
    assert result["columns"] == ["account_id", "name"]
    assert result["rows"] == [
        [1000, "Cash - Operating"],
        [6200, "Software Subscriptions"],
    ]
    assert result["truncated"] is False


def test_caps_rows_and_says_so(db):
    sixty_rows = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 60) SELECT x FROM n"
    result = query_ledger(sixty_rows, db_path=db)
    assert len(result["rows"]) == MAX_ROWS
    assert result["truncated"] is True


def test_rejects_statements_that_are_not_select(db):
    with pytest.raises(ValueError):
        query_ledger("DELETE FROM accounts", db_path=db)


def test_read_only_connection_blocks_a_write_disguised_as_select(db):
    # Starts with WITH, so it passes the text check, but it is really a DELETE
    with pytest.raises(sqlite3.OperationalError):
        query_ledger("WITH x AS (SELECT 1) DELETE FROM accounts", db_path=db)
    assert len(query_ledger("SELECT * FROM accounts", db_path=db)["rows"]) == 2


def test_refuses_a_second_statement(db):
    # Python 3.12 raises ProgrammingError; older versions raise Warning
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.Warning)):
        query_ledger("SELECT 1; DROP TABLE accounts", db_path=db)
