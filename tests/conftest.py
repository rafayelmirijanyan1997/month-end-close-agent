import sqlite3

import pytest


@pytest.fixture
def db(tmp_path):
    """A tiny hand-made database, so every expected answer is known exactly."""
    path = tmp_path / "books.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE accounts (account_id INTEGER, name TEXT, type TEXT);
        INSERT INTO accounts VALUES (1000, 'Cash - Operating', 'asset'),
                                    (6200, 'Software Subscriptions', 'expense');
    """)
    con.close()
    return path
