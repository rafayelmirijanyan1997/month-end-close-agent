import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from close.agent import run_agent


class ScriptedModel(BaseChatModel):
    """A fake LLM that gives fixed replies, one per turn, so the agent loop can be tested offline."""

    replies: list
    seen: list = []

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        reply = self.replies[min(len(self.seen), len(self.replies)) - 1]
        reply = reply.model_copy(
            update={"id": None}
        )  # a fresh message each turn, as a real model gives
        return ChatResult(generations=[ChatGeneration(message=reply)])


def call(name, args, call_id):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_agent_flags_and_drafts_through_the_tools(db):
    model = ScriptedModel(
        replies=[
            AIMessage(content="", tool_calls=[call("match_bank_to_gl", {}, "c1")]),
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "flag_exception",
                        {
                            "error_type": "missing_deposit",
                            "reason": "B3 not in ledger",
                            "bank_id": "B3",
                        },
                        "c2",
                    )
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "draft_journal_entry",
                        {
                            "flag_id": "F1",
                            "memo": "Record deposit",
                            "lines": [
                                {"account_id": 1000, "debit_cents": 88800},
                                {"account_id": 6200, "credit_cents": 88800},
                            ],
                        },
                        "c3",
                    )
                ],
            ),
            AIMessage(content="Done: one missing deposit."),
        ]
    )
    wp = run_agent(db_path=db, llm=model)
    assert [f["bank_id"] for f in wp.flags] == ["B3"]
    assert len(wp.drafts) == 1
    assert [t["name"] for t in wp.trace if t["kind"] == "tool"] == [
        "match_bank_to_gl",
        "flag_exception",
        "draft_journal_entry",
    ]


def test_tool_errors_go_back_to_the_model_as_feedback(db):
    model = ScriptedModel(
        replies=[
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "flag_exception",
                        {
                            "error_type": "duplicate_payment",
                            "reason": "?",
                            "entry_id": "JE999",
                        },
                        "c1",
                    )
                ],
            ),
            AIMessage(content="I could not find JE999."),
        ]
    )
    wp = run_agent(db_path=db, llm=model)
    feedback = model.seen[-1][-1]
    assert (
        isinstance(feedback, ToolMessage)
        and "JE999 is not in the gl table" in feedback.content
    )
    assert wp.flags == []


def test_the_loop_stops_at_the_step_limit(db):
    model = ScriptedModel(
        replies=[AIMessage(content="", tool_calls=[call("find_duplicates", {}, "c1")])]
    )
    run_agent(db_path=db, llm=model, max_steps=3)
    assert len(model.seen) == 3


def test_the_trace_is_saved_next_to_the_database(db):
    run_agent(
        db_path=db, llm=ScriptedModel(replies=[AIMessage(content="Nothing to do.")])
    )
    lines = (db.parent / "agent_trace.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["kind"] == "model"


def test_old_tool_results_are_shortened_but_the_worklist_is_kept():
    from close.agent import compact

    messages = [
        ToolMessage(content="m" * 5000, name="match_bank_to_gl", tool_call_id="t0")
    ]
    messages += [
        ToolMessage(content="x" * 5000, name="query_ledger", tool_call_id=f"t{i}")
        for i in range(1, 11)
    ]
    sent = compact(messages, keep_recent=3)
    assert len(sent[0].content) == 5000  # the worklist stays whole
    assert all(
        len(m.content) < 400 for m in sent[1:8]
    )  # the 7 older queries are shortened
    assert all(len(m.content) == 5000 for m in sent[8:])  # the 3 most recent stay whole
    assert len(messages[1].content) == 5000  # the stored history is untouched


def test_a_reply_that_is_cut_off_is_retried_not_treated_as_finished(db):
    model = ScriptedModel(
        replies=[
            AIMessage(content="", response_metadata={"finish_reason": "length"}),
            AIMessage(content="Done."),
        ]
    )
    run_agent(db_path=db, llm=model)
    assert len(model.seen) == 2  # it was given a second turn
    note = model.seen[1][-1]
    assert isinstance(note, HumanMessage) and "cut off" in note.content


def test_a_second_cut_off_in_a_row_ends_the_close(db):
    cut_off = AIMessage(content="", response_metadata={"finish_reason": "length"})
    model = ScriptedModel(
        replies=[cut_off, cut_off, AIMessage(content="never reached")]
    )
    run_agent(db_path=db, llm=model)
    assert (
        len(model.seen) == 2
    )  # one retry, then stop instead of looping until the step limit


def test_a_flag_and_its_fix_are_recorded_together(db):
    fix = [
        {"account_id": 1000, "debit_cents": 88800},
        {"account_id": 6200, "credit_cents": 88800},
    ]
    model = ScriptedModel(
        replies=[
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "flag_exception",
                        {
                            "error_type": "missing_deposit",
                            "reason": "r",
                            "bank_id": "B3",
                            "fix_lines": fix,
                        },
                        "c1",
                    )
                ],
            ),
            AIMessage(content="Done."),
        ]
    )
    wp = run_agent(db_path=db, llm=model)
    assert (
        wp.drafts[0]["flag_id"] == wp.flags[0]["flag_id"]
    )  # the fix is attached to its own error


def test_a_bad_fix_still_records_the_error_and_says_how_to_correct_it(db):
    unbalanced = [
        {"account_id": 1000, "debit_cents": 88800},
        {"account_id": 6200, "credit_cents": 1},
    ]
    model = ScriptedModel(
        replies=[
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "flag_exception",
                        {
                            "error_type": "missing_deposit",
                            "reason": "r",
                            "bank_id": "B3",
                            "fix_lines": unbalanced,
                        },
                        "c1",
                    )
                ],
            ),
            AIMessage(content="Done."),
        ]
    )
    wp = run_agent(db_path=db, llm=model)
    assert len(wp.flags) == 1 and wp.drafts == []
    assert "does not balance" in model.seen[-1][-1].content
