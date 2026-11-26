"""Load the generated CSV files into a SQLite database that the tools query.

python -m close.db
"""

import sqlite3
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data/generated")
DB_PATH = DATA_DIR / "books.db"
TABLES = [
    "accounts",
    "vendors",
    "gl",
    "bank",
]  # never ground_truth: the agent must not see the answers


def build_db(data_dir=DATA_DIR, db_path=DB_PATH):
    db_path = Path(db_path)
    db_path.unlink(missing_ok=True)  # start fresh every time
    con = sqlite3.connect(db_path)
    for table in TABLES:
        pd.read_csv(Path(data_dir) / f"{table}.csv").to_sql(table, con, index=False)
    con.close()
    return db_path


def connect(db_path=DB_PATH):
    """A read-only connection: any attempt to change the data raises an error."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


if __name__ == "__main__":
    print(f"built {build_db()}")
