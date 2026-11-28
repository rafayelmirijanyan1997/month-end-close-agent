import sqlite3

import pytest

from close.rules import run_rules


@pytest.fixture
def books(db):
    """The shared test books plus one transposition, one unapproved payment and expense lines."""
    con = sqlite3.connect(db)
    con.executescript("""
        INSERT INTO accounts VALUES (1100, 'Accounts Receivable', 'asset');
        INSERT INTO vendors VALUES ('V2', 'Beta', 6200, 1), ('V3', 'Gamma', 6200, 1),
                                   ('V4', 'Delta', 6200, 1), ('V5', 'Epsilon', 6200, 1);
        INSERT INTO gl VALUES
            ('JE7', '2026-10-13', 6200, 25000, 0, 'V5', 'Payment - E'),
            ('JE8', '2026-10-13', 6200, 25000, 0, 'V5', 'Payment - E'),
            ('JE11', '2026-10-15', 6200, 30000, 0, 'V6', 'Payment - Shadow'),
            ('JE11', '2026-10-15', 1000, 0, 30000, 'V6', 'Payment - Shadow'),
            ('JE12', '2026-10-16', 6200, 54100, 0, 'V2', 'Payment - B'),
            ('JE12', '2026-10-16', 1000, 0, 54100, 'V2', 'Payment - B');
        INSERT INTO bank VALUES ('B6', '2026-10-19', -51400, 'ACH DEBIT B'),
                                ('B7', '2026-10-16', -30000, 'ACH DEBIT SHADOW');
    """)
    con.commit()
    con.close()
    return db


def flags_by_type(wp):
    return {f["type"]: f for f in wp.flags}


def test_unrecorded_deposit(books):
    assert flags_by_type(run_rules(db_path=books))["missing_deposit"]["bank_id"] == "B3"


def test_transposition_is_paired_by_the_rule_of_nine(books):
    # 541.00 recorded, 514.00 paid: the difference, 27.00, is 3 x 9
    flag = flags_by_type(run_rules(db_path=books))["transposed_amount"]
    assert (flag["entry_id"], flag["bank_id"]) == ("JE12", "B6")


def test_transposition_fix_takes_the_excess_back_out_of_expense(books):
    wp = run_rules(db_path=books)
    flag_id = flags_by_type(wp)["transposed_amount"]["flag_id"]
    draft = next(d for d in wp.drafts if d["flag_id"] == flag_id)
    assert draft["lines"] == [
        {"account_id": 1000, "debit_cents": 2700, "credit_cents": 0},
        {"account_id": 6200, "debit_cents": 0, "credit_cents": 2700},
    ]


def test_duplicate_payment(books):
    flag = flags_by_type(run_rules(db_path=books))["duplicate_payment"]
    assert (flag["entry_id"], flag["related_entry_id"]) == ("JE8", "JE7")


def test_payment_to_unapproved_vendor(books):
    assert (
        flags_by_type(run_rules(db_path=books))["unapproved_vendor"]["entry_id"]
        == "JE11"
    )


def test_does_not_guess_about_what_it_cannot_explain(books):
    # B4 is an unmatched payment, but no rule explains it, so it is not flagged
    wp = run_rules(db_path=books)
    assert len(wp.flags) == 4
    assert all(f["bank_id"] != "B4" for f in wp.flags)


def test_rules_then_agent_starts_from_the_rules_findings(books):
    from langchain_core.messages import AIMessage

    from close.agent import run_rules_then_agent
    from tests.test_agent import ScriptedModel

    model = ScriptedModel(replies=[AIMessage(content="Nothing more to record.")])
    wp = run_rules_then_agent(db_path=books, llm=model)
    assert len(wp.flags) == 4  # the rules' findings are kept
    first_turn = model.seen[0]
    assert "rules engine" in first_turn[1].content  # the agent is told its narrower job
    assert (
        "Errors already recorded (4)" in first_turn[-1].content
    )  # and sees what the rules found
