import json

import pytest

from close.workpaper import Workpaper

BALANCED = [
    {"account_id": 1000, "debit_cents": 50000},
    {"account_id": 6200, "credit_cents": 50000},
]


@pytest.fixture
def wp(db):
    return Workpaper(db_path=db)


def test_records_a_valid_finding(wp):
    assert wp.flag_exception(
        "duplicate_payment", "paid twice", entry_id="JE8", related_entry_id="JE7"
    ) == {"flag_id": "F1", "status": "flagged"}
    assert wp.flags[0]["type"] == "duplicate_payment"


def test_rejects_an_unknown_error_type(wp):
    with pytest.raises(ValueError, match="error_type"):
        wp.flag_exception("looks_weird", "?", entry_id="JE1")


def test_rejects_an_id_that_is_not_in_the_books(wp):
    with pytest.raises(ValueError, match="JE999"):
        wp.flag_exception("duplicate_payment", "?", entry_id="JE999")


def test_rejects_a_finding_about_nothing(wp):
    with pytest.raises(ValueError):
        wp.flag_exception("missing_deposit", "?")


def test_flagging_the_same_line_twice_keeps_one_flag(wp):
    wp.flag_exception("missing_deposit", "not recorded", bank_id="B3")
    assert (
        wp.flag_exception("missing_deposit", "again", bank_id="B3")["status"]
        == "already flagged"
    )
    assert len(wp.flags) == 1


def test_saves_a_balanced_draft(wp):
    wp.flag_exception("duplicate_payment", "paid twice", entry_id="JE8")
    assert wp.draft_journal_entry("F1", BALANCED, "Reverse duplicate") == {
        "draft_id": "D1",
        "status": "saved",
    }


@pytest.mark.parametrize(
    "lines, problem",
    [
        (
            [
                {"account_id": 1000, "debit_cents": 50000},
                {"account_id": 6200, "credit_cents": 40000},
            ],
            "balance",
        ),
        (
            [
                {"account_id": 9999, "debit_cents": 50000},
                {"account_id": 6200, "credit_cents": 50000},
            ],
            "chart of accounts",
        ),
        (
            [
                {"account_id": 1000, "debit_cents": 500.0},
                {"account_id": 6200, "credit_cents": 500.0},
            ],
            "whole",
        ),
        (
            [
                {"account_id": 1000, "debit_cents": 100, "credit_cents": 100},
                {"account_id": 6200},
            ],
            "either",
        ),
        ([{"account_id": 1000, "debit_cents": 50000}], "two lines"),
    ],
)
def test_refuses_an_invalid_draft(wp, lines, problem):
    wp.flag_exception("duplicate_payment", "paid twice", entry_id="JE8")
    with pytest.raises(ValueError, match=problem):
        wp.draft_journal_entry("F1", lines, "bad")
    assert wp.drafts == []


def test_a_draft_needs_a_flag(wp):
    with pytest.raises(ValueError, match="flag"):
        wp.draft_journal_entry("F7", BALANCED, "no flag")


def test_save_writes_flags_and_drafts(wp, tmp_path):
    wp.flag_exception("duplicate_payment", "paid twice", entry_id="JE8")
    wp.draft_journal_entry("F1", BALANCED, "Reverse duplicate")
    wp.save(tmp_path / "workpaper.json")
    saved = json.loads((tmp_path / "workpaper.json").read_text())
    assert len(saved["flags"]) == 1 and len(saved["drafts"]) == 1
