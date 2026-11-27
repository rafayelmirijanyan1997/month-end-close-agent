from close.tools import match_bank_to_gl


def ids(lines, key):
    return [line[key] for line in lines]


def test_matches_same_amount_within_the_window(db):
    result = match_bank_to_gl(db_path=db)
    assert (
        result["matched"] == 3
    )  # B1-JE1 (2 days late), B2-JE2 (same day), B5 with one of JE7/JE8


def test_bank_lines_without_a_ledger_line(db):
    # B3: a deposit nobody recorded. B4: right amount, but 11 days after JE6, outside the window
    assert ids(match_bank_to_gl(db_path=db)["unmatched_bank"], "bank_id") == [
        "B3",
        "B4",
    ]


def test_each_ledger_line_is_matched_at_most_once(db):
    unmatched = match_bank_to_gl(db_path=db)["unmatched_gl"]
    assert sum(1 for g in unmatched if g["entry_id"] in ("JE7", "JE8")) == 1


def test_early_unmatched_ledger_lines_are_suspicious(db):
    assert ids(match_bank_to_gl(db_path=db)["unmatched_gl"], "entry_id")[:2] == [
        "JE6",
        "JE3",
    ]


def test_late_unmatched_ledger_lines_may_clear_next_month(db):
    assert ids(match_bank_to_gl(db_path=db)["possibly_outstanding_gl"], "entry_id") == [
        "JE4"
    ]


def test_non_cash_entries_are_ignored(db):
    result = match_bank_to_gl(db_path=db)
    every_gl_id = ids(
        result["unmatched_gl"] + result["possibly_outstanding_gl"], "entry_id"
    )
    assert "JE5" not in every_gl_id
