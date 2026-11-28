"""The LLM agent: a LangGraph loop that investigates the books with the same tools as the rules.

python -m close.agent
"""

import json
import threading
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
4. Flag only what you have evidence for, once per error. Flag each error as soon as you have the
   evidence, and draft its fix in the same or the next turn; do not save them all for the end.
Make up to 10 tool calls per turn, not more. You have at most {max_steps} turns."""


class JournalLine(BaseModel):
    account_id: int
    debit_cents: int = 0
    credit_cents: int = 0


def make_tools(wp, db_path):
    """The agent's tools: thin wrappers around the tested functions, bound to this close's books."""
    lock = (
        threading.Lock()
    )  # several tool calls can run at once; only one may write to the workpaper

    @tool
    def query_ledger(sql: str) -> dict:
        """Run one read-only SQL SELECT on the books. Returns at most 50 rows and whether it cut any off."""
        return tools.query_ledger(sql, db_path=db_path)

    @tool
    def match_bank_to_gl() -> dict:
        """Match bank lines to ledger cash lines by amount within 5 days. Returns what is left unmatched."""
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
    ) -> dict:
        """Record one error with your evidence. Give the entry_id and/or bank_id it is about."""
        with lock:
            return wp.flag_exception(
                error_type,
                reason,
                entry_id=entry_id,
                bank_id=bank_id,
                related_entry_id=related_entry_id,
            )

    @tool
    def draft_journal_entry(flag_id: str, lines: list[JournalLine], memo: str) -> dict:
        """Draft the correcting entry for a flag. Each line has account_id and a debit_cents or credit_cents."""
        with lock:
            return wp.draft_journal_entry(
                flag_id, [line.model_dump() for line in lines], memo
            )

    return [
        query_ledger,
        match_bank_to_gl,
        find_duplicates,
        check_vendor,
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


def build_graph(llm, tool_list, max_steps):
    model = llm.bind_tools(tool_list)

    def think(state):
        reply = model.invoke(compact(state["messages"]))
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
        if state["steps"] >= max_steps:
            return END
        if isinstance(last, HumanMessage):
            return "think"
        if last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(State)
    graph.add_node("think", think)
    graph.add_node("tools", ToolNode(tool_list, handle_tool_errors=True))
    graph.add_edge(START, "think")
    graph.add_edge("tools", "think")
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


def run_agent(db_path=DB_PATH, llm=None, max_steps=MAX_STEPS):
    if llm is None:
        from close.llm import make_llm

        llm = make_llm()
    wp = Workpaper(db_path=db_path)
    graph = build_graph(llm, make_tools(wp, db_path), max_steps)
    messages = [
        SystemMessage(SYSTEM_PROMPT.format(max_steps=max_steps)),
        HumanMessage("Please do the October 2026 close."),
    ]
    result = graph.invoke(
        {"messages": messages, "steps": 0}, {"recursion_limit": 2 * max_steps + 5}
    )
    wp.trace = to_trace(result["messages"])
    wp.tokens = sum(
        t.get("input_tokens", 0) + t.get("output_tokens", 0) for t in wp.trace
    )
    trace_path = Path(db_path).with_name("agent_trace.jsonl")
    trace_path.write_text("".join(json.dumps(t) + "\n" for t in wp.trace))
    return wp


if __name__ == "__main__":
    wp = run_agent()
    RUNS_DIR.mkdir(exist_ok=True)
    wp.save(RUNS_DIR / "agent.json")
    print(
        f"{len(wp.flags)} flags, {len(wp.drafts)} drafts, {wp.tokens:,} tokens -> {RUNS_DIR / 'agent.json'}"
    )
