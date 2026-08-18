#!/usr/bin/env python3
"""Merge the desk's decisions into the deterministic run and re-render.

The agents produce judgments; this script produces the report.  Keeping
rendering out of the model matters for two reasons: the arithmetic in the
report card (weights, share counts, cash) stays reproducible, and the engine
badge is set from the data rather than from whatever the model claims about
itself.

    python3 scripts/render_report.py --run runs/<stamp> --decisions decisions.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adapter import Holding                                # noqa: E402
from core.report import action_queue, health_verdict, render_markdown  # noqa: E402

VALID_ACTIONS = {"exit", "trim", "hold", "accumulate", "buy"}


def merge(analysis: dict, decisions: dict) -> tuple[dict, list[str]]:
    """Overlay agent plans onto the rules baseline, reporting what was used.

    A symbol with no plan keeps its rules verdict and stays badged ``rules``.
    Partial model coverage therefore degrades to a mixed report rather than
    silently presenting rules output as AI output.
    """
    verdicts = dict(analysis["verdicts"])
    notes: list[str] = []

    for plan in decisions.get("plans", []):
        symbol = plan.get("symbol")
        action = plan.get("action")
        if symbol not in verdicts:
            notes.append(f"ignored plan for unknown symbol {symbol!r}")
            continue
        if action not in VALID_ACTIONS:
            notes.append(f"{symbol}: invalid action {action!r}, kept rules verdict")
            continue

        verdict = dict(verdicts[symbol])
        verdict["action"] = action
        verdict["engine"] = "llm"
        verdict["confidence"] = plan.get("confidence", verdict.get("confidence"))
        if plan.get("stop"):
            verdict["stop"] = plan["stop"]
        reasons = [r for r in (plan.get("rationale"), plan.get("dissent")) if r]
        if reasons:
            verdict["reasons"] = reasons + list(verdict.get("reasons", []))
        verdict["evidence"] = plan.get("evidence")
        verdict["setup"] = plan.get("setup")
        verdicts[symbol] = verdict

    missing = [s for s, v in verdicts.items() if v.get("engine") != "llm"]
    if missing:
        notes.append(
            f"{len(missing)} holding(s) kept the rules verdict: {', '.join(sorted(missing))}"
        )
    return verdicts, notes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", required=True, help="run folder containing analysis.json")
    p.add_argument("--decisions", required=True, help="decision-maker JSON output")
    args = p.parse_args(argv)

    with open(os.path.join(args.run, "analysis.json"), encoding="utf-8") as fh:
        analysis = json.load(fh)
    with open(args.decisions, encoding="utf-8") as fh:
        decisions = json.load(fh)

    verdicts, notes = merge(analysis, decisions)
    book = analysis["book"]
    if "holdings" not in analysis:
        raise SystemExit(
            f"{args.run}/analysis.json predates holdings persistence; "
            "re-run scripts/run_analysis.py to regenerate it"
        )
    holdings = [
        Holding(h["symbol"], h["qty"], h["avg_cost"]) for h in analysis["holdings"]
    ]

    health = health_verdict(book)
    queue = action_queue(verdicts, holdings, book)
    markdown = render_markdown(book, health, queue, analysis["dials"])

    analysis["verdicts"] = verdicts
    analysis["action_queue"] = queue
    analysis["engine"] = "llm" if not notes else "mixed"
    analysis["merge_notes"] = notes

    with open(os.path.join(args.run, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(analysis, fh, indent=2, default=str)
        fh.write("\n")
    with open(os.path.join(args.run, "report-card.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown)

    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
