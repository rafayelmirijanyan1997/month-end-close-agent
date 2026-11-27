from close.tools import check_vendor, find_duplicates


def test_finds_same_vendor_same_amount_close_together(db):
    pairs = find_duplicates(db_path=db)
    assert [(p["first_entry_id"], p["second_entry_id"]) for p in pairs] == [
        ("JE7", "JE8")
    ]


def test_same_vendor_and_amount_far_apart_is_not_a_duplicate(db):
    # JE1 and JE9: both V1 for 500.00, but 15 days apart (a monthly bill, not a duplicate)
    assert all(
        "JE9" not in (p["first_entry_id"], p["second_entry_id"])
        for p in find_duplicates(db_path=db)
    )


def test_same_amount_to_a_different_vendor_is_not_a_duplicate(db):
    # JE10 pays V2 the same 250.00 as JE7 and JE8 pay V5, four days earlier
    assert all(
        "JE10" not in (p["first_entry_id"], p["second_entry_id"])
        for p in find_duplicates(db_path=db)
    )


def test_approved_vendor(db):
    assert check_vendor("V1", db_path=db) == {
        "vendor_id": "V1",
        "found": True,
        "name": "Alpha LLC",
        "default_account_id": 6200,
        "approved": True,
    }


def test_unapproved_vendor(db):
    assert check_vendor("V6", db_path=db)["approved"] is False


def test_unknown_vendor(db):
    assert check_vendor("V999", db_path=db) == {"vendor_id": "V999", "found": False}
