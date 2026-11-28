"""The LLM agent: a LangGraph loop that investigates the books with the same tools as the rules.

python -m close.agent
"""

import json
import re
import threading
from collections import Counter
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

from close import tools
from close.db import DB_PATH
from close.workpaper import Workpaper

MAX_STEPS = 40


CUT_OFF_NOTE = (
    "Your last reply was cut off because it was too long, so none of its tool calls ran. "
    "Send at most 10 tool calls per turn."
)


KEEP_RECENT = 8  # older ones are shortened


SAME_SHAPE_LIMIT = (
    3  # repeats of one query shape before the agent is told it looks like paging
)
PAGING_NOTE = (
    "You have now run this query several times with only its values changed, which looks like paging "
    "through a table. That wastes turns: match_bank_to_gl has already compared every bank line with the "
    "ledger. To check particular items, query them together, for example WHERE debit_cents IN (...). To "
    "review a kind of entry, narrow by account, date range or memo, or GROUP BY, so one query covers it."
)


def query_shape(sql):
    """The query with its values blanked out, so successive pages of one table look identical."""
    sql = re.sub(r"'[^']*'", "?", sql)
    sql = re.sub(r"\b\d+\b", "?", sql)
    return " ".join(sql.lower().split())


RUNS_DIR = Path("runs")

SYSTEM_PROMPT = """You are a senior accountant doing the October 2026 month-end close for a small company.
Your job: reconcile the bank statement to the general ledger, find the errors, flag each one with
evidence, and draft the journal entry that corrects it. A person reviews and posts your drafts.

The books are in a SQLite database:
- accounts(account_id, name, type)
- vendors(vendor_id, name, account_id, approved)   approved is 1 or 0
- gl(entry_id, date, account_id, debit_cents, credit_cents, vendor_id, memo)
  one row per journal-entry line; account 1000 is Cash, 1100 Accounts Receivable, 1200 Prepaid Expenses
- bank(bank_id, date, amount_cents, description)   positive = money in, negative = money out
All amounts are whole cents (541025 means $5,410.25). Use whole cents in every tool call.

Error types you may flag (use these exact names):
- duplicate_payment: the same payment recorded twice. Flag the later entry, with related_entry_id
  set to the earlier one. Fix: debit Cash, credit the expense account, for the duplicated amount.
- missing_deposit: money received on the bank statement that was never recorded. Flag the bank_id.
  Fix: debit Cash, credit Accounts Receivable.
- transposed_amount: the ledger amount has two digits swapped compared with the bank. Flag the
  entry_id and the bank_id together. Fix: book only the difference between the two amounts.
- wrong_period: an expense recorded this month that belongs to another period. Fix: move it to
  Prepaid Expenses (debit 1200, credit the expense account).
- unapproved_vendor: a payment to a vendor that is not approved. Flag the entry. Do not draft an
  entry; it must be escalated.

How to work:
1. Call match_bank_to_gl once. Unmatched ledger payments dated in the last days of the month are
   usually outstanding items that clear next month: they are normal, not errors.
2. Investigate what is left, and use find_duplicates. Check vendor approval with SQL or check_vendor.
3. Consider cut-off: do any expenses recorded in October relate to a different period?
   review_expense_memos shows what each expense was for.
4. Flag only what you have evidence for, once per error. Flag each error as soon as you have the
   evidence, giving its fix_lines in the same flag_exception call; do not save them all for the end."""


class JournalLine(BaseModel):
    account_id: int
    debit_cents: int = 0
    credit_cents: int = 0


def make_tools(wp, db_path):
    """The agent's tools: thin wrappers around the tested functions, bound to this close's books."""
    lock = (
        threading.Lock()
    )  # several tool calls can run at once; only one may write to the workpaper
    shapes = Counter()  # how often each query shape has been run in this close

    @tool
    def query_ledger(sql: str) -> dict:
        """Run one read-only SQL SELECT on the books. Returns at most 50 rows and whether any were cut off.

        Ask targeted questions (filter by entry_id, amount or vendor) or aggregate ones (COUNT, SUM,
        GROUP BY). Do not page through a table in chunks: that wastes turns, and match_bank_to_gl has
        already compared every bank line with the ledger.
        """
        result = tools.query_ledger(sql, db_path=db_path)
        with lock:
            shapes[query_shape(sql)] += 1
            if shapes[query_shape(sql)] >= SAME_SHAPE_LIMIT:
                result["note"] = PAGING_NOTE
        return result

    @tool
    def match_bank_to_gl() -> dict:
        """Compare every bank line with every ledger cash line and return what has no partner.

        Two lines are partners if they have the same amount and the bank date is 0 to 5 days after the
        ledger date; each line is used at most once. So an unmatched line has no line of the same amount
        within that window anywhere in the books: you do not need to search the ledger to confirm it.
        Look closer only at what could explain it, such as a nearby line with a different amount.
        """
        result = tools.match_bank_to_gl(db_path=db_path)
        late = result.pop("possibly_outstanding_gl")
        result["possibly_outstanding_gl"] = {
            "count": len(late),
            "total_cents": sum(g["amount_cents"] for g in late),
            "note": "ledger lines from the last days of the month with no bank line yet; usually items "
            "that clear next month. Query gl if you need details.",
        }
        return result

    @tool
    def find_duplicates() -> list:
        """Pairs of payments to the same vendor for the same amount within 7 days."""
        return tools.find_duplicates(db_path=db_path)

    @tool
    def check_vendor(vendor_id: str) -> dict:
        """Look up a vendor: is it in the vendor master, is it approved, which account does it book to."""
        return tools.check_vendor(vendor_id, db_path=db_path)

    @tool
    def flag_exception(
        error_type: str,
        reason: str,
        entry_id: str | None = None,
        bank_id: str | None = None,
        related_entry_id: str | None = None,
        fix_lines: list[JournalLine] | None = None,
    ) -> dict:
        """Record one error with your evidence, together with the journal entry that corrects it.

        Give the entry_id and/or bank_id the error is about. Give fix_lines for every error type except
        unapproved_vendor; each line has account_id and a debit_cents or credit_cents. Recording the
        error and its fix in one call keeps each fix attached to the right error.
        """
        with lock:
            result = wp.flag_exception(
                error_type,
                reason,
                entry_id=entry_id,
                bank_id=bank_id,
                related_entry_id=related_entry_id,
            )
            if fix_lines and result["status"] == "flagged":
                try:
                    lines = [line.model_dump() for line in fix_lines]
                    result["draft"] = wp.draft_journal_entry(
                        result["flag_id"], lines, reason
                    )
                except ValueError as e:
                    result["draft_error"] = (
                        f"{e}. The error was still recorded as {result['flag_id']}; "
                        "send a corrected entry with draft_journal_entry."
                    )
            return result

    @tool
    def draft_journal_entry(flag_id: str, lines: list[JournalLine], memo: str) -> dict:
        """Draft the correcting entry for a flag. Each line has account_id and a debit_cents or credit_cents."""
        with lock:
            return wp.draft_journal_entry(
                flag_id, [line.model_dump() for line in lines], memo
            )

    @tool
    def review_expense_memos() -> list:
        """List every distinct description of this month's expense entries: how often it occurs, its total and dates.

        About a thousand expense lines collapse to a few dozen descriptions, so unusual ones stand out.
        Use it to review what payments were for, for example for cut-off. For a description used at
        most 3 times, entry_ids lists its entries.
        """
        return tools.summarize_expense_memos(db_path=db_path)

    return [
        query_ledger,
        match_bank_to_gl,
        find_duplicates,
        check_vendor,
        review_expense_memos,
        flag_exception,
        draft_journal_entry,
    ]


def compact(messages, keep_recent=KEEP_RECENT):
    """Shorten old tool results so each turn's input stays small.

    The match_bank_to_gl result is never shortened: it is the worklist. The full history stays in
    the graph state (and the trace); only what is sent to the model is shortened.
    """
    tool_positions = [i for i, m in enumerate(messages) if isinstance(m, ToolMessage)]
    old = set(tool_positions[:-keep_recent]) if keep_recent else set(tool_positions)
    out = []
    for i, m in enumerate(messages):
        if i in old and m.name != "match_bank_to_gl" and len(str(m.content)) > 300:
            short = (
                str(m.content)[:300]
                + " ...[older result shortened; call the tool again if you need it]"
            )
            m = m.model_copy(update={"content": short})
        out.append(m)
    return out


class State(MessagesState):
    steps: int


def progress_note(wp, steps, max_steps):
    """A short status the code keeps for the model: what is already recorded, and turns left."""
    recorded = {}
    for f in wp.flags:
        recorded.setdefault(f["type"], []).append(f["entry_id"] or f["bank_id"])
    lines = [f"Progress: this is turn {steps + 1} of {max_steps}."]
    if recorded:
        lines.append(
            f"Errors already recorded ({len(wp.flags)}); they need no more work:"
        )
        lines += [f"- {kind}: {', '.join(ids)}" for kind, ids in recorded.items()]
    else:
        lines.append(
            "No errors recorded yet. Record each one as soon as you have the evidence."
        )
    return "\n".join(lines)


def build_graph(llm, tool_list, max_steps, wp):
    model = llm.bind_tools(tool_list)

    def think(state):
        note = HumanMessage(progress_note(wp, state["steps"], max_steps))
        reply = model.invoke(compact(state["messages"]) + [note])
        update = {"messages": [reply], "steps": state["steps"] + 1}
        cut_off = (
            reply.response_metadata.get("finish_reason") == "length"
            and not reply.tool_calls
        )
        retried_already = state["messages"][-1].content == CUT_OFF_NOTE
        if cut_off and not retried_already:
            update["messages"].append(
                HumanMessage(CUT_OFF_NOTE)
            )  # tell the model, and let it try once more
        return update

    def next_node(state):
        last = state["messages"][-1]
        if isinstance(
            last, HumanMessage
        ):  # a cut-off note: try again if turns are left
            return "think" if state["steps"] < max_steps else END
        if last.tool_calls:  # run them even on the last turn, so its findings are saved
            return "tools"
        return END

    def after_tools(state):
        return "think" if state["steps"] < max_steps else END

    graph = StateGraph(State)
    graph.add_node("think", think)
    graph.add_node("tools", ToolNode(tool_list, handle_tool_errors=True))
    graph.add_edge(START, "think")
    graph.add_conditional_edges("tools", after_tools, ["think", END])
    graph.add_conditional_edges("think", next_node, ["tools", "think", END])
    return graph.compile()


def to_trace(messages):
    """One record per model turn and per tool result: what was asked, what came back, what it cost."""
    trace = []
    for m in messages:
        if isinstance(m, AIMessage):
            usage = m.usage_metadata or {}
            trace.append(
                {
                    "kind": "model",
                    "tool_calls": [
                        {"name": c["name"], "args": c["args"]} for c in m.tool_calls
                    ],
                    "text": str(m.content)[:1000],
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "finish_reason": m.response_metadata.get("finish_reason"),
                    "invalid_tool_calls": [
                        {"name": c.get("name"), "args": str(c.get("args"))[:300]}
                        for c in m.invalid_tool_calls
                    ],
                    "reasoning_chars": len(
                        str(m.additional_kwargs.get("reasoning_content") or "")
                    ),
                }
            )
        elif isinstance(m, ToolMessage):
            trace.append(
                {
                    "kind": "tool",
                    "name": m.name,
                    "error": m.status == "error",
                    "chars": len(str(m.content)),
                    "result": str(m.content)[:300],
                }
            )
    return trace


HYBRID_STEPS = """How to work:
1. A rules engine has already done the bank reconciliation, duplicate, transposition and vendor checks,
   and its flags are in the progress note. Do not call match_bank_to_gl or find_duplicates, and do not
   re-check those error types.
2. Look for cut-off errors: expense payments recorded in October that relate to a different period.
   Start with review_expense_memos, which lists every distinct expense description in one call; the
   memo usually says what a payment was for. Query single entries only to confirm details.
3. Flag each error you have evidence for as soon as you find it, with its fix_lines in the same
   flag_exception call. When nothing is left to check, stop."""
HYBRID_SYSTEM_PROMPT = SYSTEM_PROMPT.split("How to work:")[0] + HYBRID_STEPS

DEFAULT_TASK = "Please do the October 2026 close."
HYBRID_TASK = (
    "A rules engine has already reconciled the books. It covers duplicate payments, unrecorded deposits, "
    "transposed amounts and unapproved vendors, and the errors it recorded are listed in the progress note: "
    "do not re-check them. It does not assess cut-off or anything that needs judgement. Your job is to find "
    "the errors it would miss, record each one you have evidence for, and then stop."
)


def run_agent(
    db_path=DB_PATH,
    llm=None,
    max_steps=MAX_STEPS,
    wp=None,
    task=DEFAULT_TASK,
    trace_name="agent_trace.jsonl",
    system_prompt=SYSTEM_PROMPT,
):
    if llm is None:
        from close.llm import make_llm

        llm = make_llm()

    if wp is None:
        wp = Workpaper(db_path=db_path)
    graph = build_graph(llm, make_tools(wp, db_path), max_steps, wp)

    messages = [
        SystemMessage(system_prompt.format(max_steps=max_steps)),
        HumanMessage(task),
    ]
    result = graph.invoke(
        {"messages": messages, "steps": 0}, {"recursion_limit": 2 * max_steps + 5}
    )
    wp.trace = to_trace(result["messages"])
    wp.tokens = sum(
        t.get("input_tokens", 0) + t.get("output_tokens", 0) for t in wp.trace
    )

    trace_path = Path(db_path).with_name(trace_name)
    trace_path.write_text("".join(json.dumps(t) + "\n" for t in wp.trace))
    return wp


def run_rules_then_agent(db_path=DB_PATH, llm=None, max_steps=15):
    """Rules do the mechanical checks; the agent then looks only for what needs judgement."""
    from close.rules import run_rules

    wp = run_rules(db_path=db_path)
    return run_agent(
        db_path=db_path,
        llm=llm,
        max_steps=max_steps,
        wp=wp,
        task=HYBRID_TASK,
        trace_name="rules+agent_trace.jsonl",
        system_prompt=HYBRID_SYSTEM_PROMPT,
    )


if __name__ == "__main__":
    wp = run_agent()
    RUNS_DIR.mkdir(exist_ok=True)
    wp.save(RUNS_DIR / "agent.json")
    print(
        f"{len(wp.flags)} flags, {len(wp.drafts)} drafts, {wp.tokens:,} tokens -> {RUNS_DIR / 'agent.json'}"
    )
