import sqlite3

from close.db import TABLES, build_db


def test_build_db_loads_tables_but_never_the_answer_key(tmp_path):
    for table in TABLES:
        (tmp_path / f"{table}.csv").write_text("id\n1\n")
    (tmp_path / "ground_truth.json").write_text("{}")

    db_path = build_db(data_dir=tmp_path, db_path=tmp_path / "books.db")

    con = sqlite3.connect(db_path)
    names = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    con.close()
    assert names == set(TABLES)
