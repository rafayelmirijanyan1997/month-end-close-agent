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
        CREATE TABLE gl (entry_id TEXT, date TEXT, account_id INTEGER, debit_cents INTEGER,
                         credit_cents INTEGER, vendor_id TEXT, memo TEXT);
        INSERT INTO gl VALUES
            ('JE1', '2026-10-05', 1000, 0, 50000, 'V1', 'Payment - A'),
            ('JE2', '2026-10-06', 1000, 30000, 0, NULL, 'Customer receipt'),
            ('JE3', '2026-10-08', 1000, 0, 12345, 'V2', 'Payment - B'),
            ('JE4', '2026-10-29', 1000, 0, 77700, 'V3', 'Payment - C'),
            ('JE5', '2026-10-30', 6800, 420000, 0, NULL, 'Monthly depreciation'),
            ('JE6', '2026-10-01', 1000, 0, 99900, 'V4', 'Payment - D'),
            ('JE7', '2026-10-13', 1000, 0, 25000, 'V5', 'Payment - E'),
            ('JE8', '2026-10-13', 1000, 0, 25000, 'V5', 'Payment - E');

        CREATE TABLE bank (bank_id TEXT, date TEXT, amount_cents INTEGER, description TEXT);
        INSERT INTO bank VALUES
            ('B1', '2026-10-07', -50000, 'ACH DEBIT A'),
            ('B2', '2026-10-06', 30000, 'DEPOSIT'),
            ('B3', '2026-10-09', 88800, 'DEPOSIT'),
            ('B4', '2026-10-12', -99900, 'ACH DEBIT D'),
            ('B5', '2026-10-14', -25000, 'ACH DEBIT E');
    """)
    con.close()
    return path
