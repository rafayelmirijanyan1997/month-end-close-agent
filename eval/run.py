"""Score each approach against the answer key on several seeds, and write eval/results.md.

python -m eval.run
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from close.agent import run_agent
from close.db import build_db
from close.rules import run_rules
from close.workpaper import ERROR_TYPES
from data.generate import generate

APPROACHES = {"rules": run_rules, "agent": run_agent}

SEEDS = [42, 7, 123]
WORK_DIR = Path("data/generated/eval")
RESULTS = Path("eval/results.md")


def ids(item, keys):
    return {item.get(k) for k in keys} - {None}


def lines_key(lines):
    """A journal entry's lines in a fixed order, so two entries can be compared."""
    return sorted(
        (line["account_id"], line["debit_cents"], line["credit_cents"])
        for line in lines
    )


def score(errors, flags, drafts):
    """Compare one workpaper's flags and drafts with the answer key.

    A flag is correct if it has the same type as a planted error and points at one of its lines
    (for a duplicate, either entry of the pair). An error counts as found once, however many flags
    point at it. A fix is correct if a draft on one of its flags has exactly the expected lines.
    """
    flags_for = {}  # error_id -> ids of the flags that point at it
    correct_flags = 0
    for f in flags:
        hits = [
            e
            for e in errors
            if e["type"] == f["type"]
            and ids(f, ["entry_id", "bank_id"])
            & ids(e, ["entry_id", "bank_id", "related_entry_id"])
        ]
        correct_flags += bool(hits)
        for e in hits:
            flags_for.setdefault(e["error_id"], []).append(f["flag_id"])

    drafts_for = {}  # flag_id -> the line sets drafted for it
    for d in drafts:
        drafts_for.setdefault(d["flag_id"], []).append(lines_key(d["lines"]))
    needs_fix = [e for e in errors if e["error_id"] in flags_for and e["fix"]]
    fixes_correct = sum(
        any(
            lines_key(e["fix"]) in drafts_for.get(flag_id, [])
            for flag_id in flags_for[e["error_id"]]
        )
        for e in needs_fix
    )
    return {
        "errors": len(errors),
        "found": len(flags_for),
        "flags": len(flags),
        "correct_flags": correct_flags,
        "fixes_needed": len(needs_fix),
        "fixes_correct": fixes_correct,
        "errors_by_type": dict(Counter(e["type"] for e in errors)),
        "found_by_type": dict(
            Counter(e["type"] for e in errors if e["error_id"] in flags_for)
        ),
    }


def evaluate(approaches, seeds):
    rows = []
    for seed in seeds:
        data_dir = WORK_DIR / f"seed_{seed}"
        generate(seed, out_dir=data_dir)
        db_path = build_db(data_dir=data_dir, db_path=data_dir / "books.db")
        errors = json.loads((data_dir / "ground_truth.json").read_text())["errors"]
        for name in approaches:
            start = time.perf_counter()
            wp = APPROACHES[name](db_path=db_path)
            seconds = time.perf_counter() - start
            wp.save(data_dir / f"{name}_workpaper.json")
            rows.append(
                {
                    "approach": name,
                    "seed": seed,
                    "seconds": seconds,
                    "tokens": getattr(wp, "tokens", 0),  # only the agent uses a model
                    **score(errors, wp.flags, wp.drafts),
                }
            )
    return rows


def pct(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def report(rows):
    seeds = sorted({r["seed"] for r in rows})
    out = [
        "# Evaluation results",
        "",
        f"Seeds {', '.join(map(str, seeds))}; 40 planted errors per seed. Written by `python -m eval.run`.",
        "",
        "| approach | recall | precision | correct fixes | seconds per close | tokens per close |",
        "|---|---|---|---|---|---|",
    ]
    by_approach = {}
    for r in rows:
        by_approach.setdefault(r["approach"], []).append(r)
    for name, rs in by_approach.items():
        total = {
            k: sum(r[k] for r in rs)
            for k in (
                "errors",
                "found",
                "flags",
                "correct_flags",
                "fixes_needed",
                "fixes_correct",
                "seconds",
                "tokens",
            )
        }
        out.append(
            f"| {name} | {pct(total['found'], total['errors'])} ({total['found']}/{total['errors']}) "
            f"| {pct(total['correct_flags'], total['flags'])} ({total['correct_flags']}/{total['flags']}) "
            f"| {pct(total['fixes_correct'], total['fixes_needed'])} "
            f"| {total['seconds'] / len(rs):.2f} | {total['tokens'] // len(rs):,} |"
        )
    out += [
        "",
        "## Recall by error type (all seeds)",
        "",
        "| approach | " + " | ".join(ERROR_TYPES) + " |",
        "|---|" + "---|" * len(ERROR_TYPES),
    ]
    for name, rs in by_approach.items():
        cells = [
            f"{sum(r['found_by_type'].get(t, 0) for r in rs)}/{sum(r['errors_by_type'].get(t, 0) for r in rs)}"
            for t in ERROR_TYPES
        ]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    out += [
        "",
        "## Every run",
        "",
        "| approach | seed | found | flags | correct flags | correct fixes |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r['approach']} | {r['seed']} | {r['found']}/{r['errors']} | {r['flags']} "
            f"| {r['correct_flags']} | {r['fixes_correct']}/{r['fixes_needed']} |"
        )
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--approaches", nargs="+", default=list(APPROACHES), choices=list(APPROACHES)
    )
    ap.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    args = ap.parse_args()
    rows = evaluate(args.approaches, args.seeds)
    Path("eval/rows.json").write_text(json.dumps(rows, indent=2))
    text = report(rows)
    RESULTS.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
