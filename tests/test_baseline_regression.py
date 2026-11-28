"""A small evaluation that runs on every push: the rules baseline on seed 42 must not get worse.

The agent is not run here: it needs an API key and costs tokens. Its results are in eval/results.md.
"""

import json

from close.db import build_db
from close.rules import run_rules
from data.generate import generate
from eval.run import score


def test_rules_baseline_does_not_regress(tmp_path):
    generate(42, out_dir=tmp_path)
    db_path = build_db(data_dir=tmp_path, db_path=tmp_path / "books.db")
    errors = json.loads((tmp_path / "ground_truth.json").read_text())["errors"]
    wp = run_rules(db_path=db_path)
    result = score(errors, wp.flags, wp.drafts)
    assert (
        result["found"] >= 32
    )  # every duplicate, deposit, transposition and unapproved vendor
    assert result["correct_flags"] == result["flags"]  # no false alarms
    assert (
        result["fixes_correct"] == result["fixes_needed"]
    )  # every drafted fix is right
