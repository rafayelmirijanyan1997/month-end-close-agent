"""The close workpaper: findings and draft journal entries are recorded here, after validation."""

import json
from pathlib import Path

from close.db import DB_PATH, connect

ERROR_TYPES = (
    "duplicate_payment",
    "missing_deposit",
    "transposed_amount",
    "wrong_period",
    "unapproved_vendor",
)


class Workpaper:
    """Collects the exceptions and draft journal entries for one close. Drafts are never posted to the ledger."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.flags = []
        self.drafts = []

    def _exists(self, table, column, value):
        con = connect(self.db_path)
        found = con.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,)
        ).fetchone()
        con.close()
        return found is not None

    def flag_exception(
        self, error_type, reason, entry_id=None, bank_id=None, related_entry_id=None
    ):
        """Record one finding. Every id must exist in the books, so a made-up id is refused."""
        if error_type not in ERROR_TYPES:
            raise ValueError(f"error_type must be one of: {', '.join(ERROR_TYPES)}")
        if entry_id is None and bank_id is None:
            raise ValueError("give the entry_id or bank_id that the finding is about")
        for value, table, column in [
            (entry_id, "gl", "entry_id"),
            (related_entry_id, "gl", "entry_id"),
            (bank_id, "bank", "bank_id"),
        ]:
            if value is not None and not self._exists(table, column, value):
                raise ValueError(f"{value} is not in the {table} table")
        for flag in self.flags:
            if (entry_id and entry_id == flag["entry_id"]) or (
                bank_id and bank_id == flag["bank_id"]
            ):
                return {"flag_id": flag["flag_id"], "status": "already flagged"}
        flag_id = f"F{len(self.flags) + 1}"
        self.flags.append(
            {
                "flag_id": flag_id,
                "type": error_type,
                "entry_id": entry_id,
                "bank_id": bank_id,
                "related_entry_id": related_entry_id,
                "reason": reason,
            }
        )
        return {"flag_id": flag_id, "status": "flagged"}

    def draft_journal_entry(self, flag_id, lines, memo):
        """Validate and save a correcting entry for a flagged exception. It stays a draft: a person posts it."""
        if flag_id not in {f["flag_id"] for f in self.flags}:
            raise ValueError(f"{flag_id} is not a flag id; call flag_exception first")
        if len(lines) < 2:
            raise ValueError("a journal entry needs at least two lines")
        clean = []
        for line in lines:
            debit, credit = line.get("debit_cents", 0), line.get("credit_cents", 0)
            if (
                not (isinstance(debit, int) and isinstance(credit, int))
                or debit < 0
                or credit < 0
            ):
                raise ValueError(
                    "debit_cents and credit_cents must be whole, non-negative numbers of cents"
                )
            if (debit > 0) == (credit > 0):
                raise ValueError(
                    "each line needs either a debit or a credit, not both and not neither"
                )
            if not self._exists("accounts", "account_id", line.get("account_id")):
                raise ValueError(
                    f"account {line.get('account_id')} is not in the chart of accounts"
                )
            clean.append(
                {
                    "account_id": line["account_id"],
                    "debit_cents": debit,
                    "credit_cents": credit,
                }
            )
        debits = sum(line["debit_cents"] for line in clean)
        credits = sum(line["credit_cents"] for line in clean)
        if debits != credits:
            raise ValueError(
                f"entry does not balance: debits {debits} != credits {credits}"
            )
        draft_id = f"D{len(self.drafts) + 1}"
        self.drafts.append(
            {"draft_id": draft_id, "flag_id": flag_id, "memo": memo, "lines": clean}
        )
        return {"draft_id": draft_id, "status": "saved"}

    def save(self, path):
        Path(path).write_text(
            json.dumps({"flags": self.flags, "drafts": self.drafts}, indent=2)
        )
