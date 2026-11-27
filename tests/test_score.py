from eval.run import score

FIX = [
    {"account_id": 1000, "debit_cents": 500, "credit_cents": 0},
    {"account_id": 6200, "debit_cents": 0, "credit_cents": 500},
]
ERRORS = [
    {
        "error_id": "E1",
        "type": "duplicate_payment",
        "entry_id": "JE2",
        "bank_id": None,
        "related_entry_id": "JE1",
        "fix": FIX,
    },
    {
        "error_id": "E2",
        "type": "missing_deposit",
        "entry_id": None,
        "bank_id": "B1",
        "related_entry_id": None,
        "fix": FIX,
    },
    {
        "error_id": "E3",
        "type": "unapproved_vendor",
        "entry_id": "JE5",
        "bank_id": "B5",
        "related_entry_id": None,
        "fix": None,
    },
]


def flag(flag_id, error_type, entry_id=None, bank_id=None):
    return {
        "flag_id": flag_id,
        "type": error_type,
        "entry_id": entry_id,
        "bank_id": bank_id,
    }


def test_perfect_workpaper():
    flags = [
        flag("F1", "duplicate_payment", "JE2"),
        flag("F2", "missing_deposit", bank_id="B1"),
        flag("F3", "unapproved_vendor", "JE5"),
    ]
    drafts = [{"flag_id": "F1", "lines": FIX}, {"flag_id": "F2", "lines": FIX}]
    result = score(ERRORS, flags, drafts)
    assert (result["found"], result["correct_flags"], result["fixes_correct"]) == (
        3,
        3,
        2,
    )
    assert (
        result["fixes_needed"] == 2
    )  # an unapproved vendor needs escalation, not an entry


def test_flagging_the_original_of_a_duplicate_counts():
    assert score(ERRORS, [flag("F1", "duplicate_payment", "JE1")], [])["found"] == 1


def test_right_line_wrong_type_is_not_a_find():
    result = score(ERRORS, [flag("F1", "transposed_amount", bank_id="B1")], [])
    assert (result["found"], result["correct_flags"]) == (0, 0)


def test_a_flag_on_a_normal_line_is_a_false_alarm():
    result = score(
        ERRORS,
        [
            flag("F1", "duplicate_payment", "JE2"),
            flag("F2", "duplicate_payment", "JE99"),
        ],
        [],
    )
    assert (result["flags"], result["correct_flags"]) == (2, 1)


def test_two_flags_on_one_error_find_it_once():
    flags = [
        flag("F1", "unapproved_vendor", "JE5"),
        flag("F2", "unapproved_vendor", bank_id="B5"),
    ]
    assert score(ERRORS, flags, [])["found"] == 1


def test_fix_lines_may_come_in_any_order_but_amounts_must_match():
    flags = [
        flag("F1", "duplicate_payment", "JE2"),
        flag("F2", "missing_deposit", bank_id="B1"),
    ]
    wrong_amount = [
        {"account_id": 1000, "debit_cents": 600, "credit_cents": 0},
        {"account_id": 6200, "debit_cents": 0, "credit_cents": 600},
    ]
    drafts = [
        {"flag_id": "F1", "lines": list(reversed(FIX))},
        {"flag_id": "F2", "lines": wrong_amount},
    ]
    assert score(ERRORS, flags, drafts)["fixes_correct"] == 1
