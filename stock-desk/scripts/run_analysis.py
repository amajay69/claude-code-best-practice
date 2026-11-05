#!/usr/bin/env python3
"""Deterministic end-to-end pass over a holdings file.

This is the rules-only path: no model involved, every number reproducible.
It exists for three reasons — it is the amber fallback when the desk cannot
reach a model, it is the fact sheet the agents read when they can, and it
makes the whole pipeline runnable in CI without an API key.

    python3 scripts/run_analysis.py --holdings fixtures/holdings.csv \
        --horizon positional --risk balanced --depth standard
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adapter import FixtureAdapter, load_holdings          # noqa: E402
from core.live import LiveAdapter                              # noqa: E402
from core.backtest import HOLD_DAYS, STOP_ATR                   # noqa: E402
from core.strategies import STRATEGIES, get                   # noqa: E402
from core.portfolio import analyse                              # noqa: E402
from core.report import (                                      # noqa: E402
    action_queue, health_verdict, render_markdown, write_run,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPTHS = ("quick", "standard", "deep")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--holdings", default=os.path.join(HERE, "fixtures", "holdings.csv"))
    p.add_argument("--fixtures", default=os.path.join(HERE, "fixtures"))
    p.add_argument("--horizon", default="positional", choices=sorted(HOLD_DAYS))
    p.add_argument("--risk", default="balanced", choices=sorted(STOP_ATR))
    p.add_argument("--depth", default="standard", choices=DEPTHS)
    p.add_argument(
        "--strategy", default="baseline", choices=sorted(STRATEGIES),
        help="verdict logic: 'baseline' sums scores, 'bajaj' applies independent gates",
    )
    p.add_argument("--out", default=os.path.join(HERE, "runs"))
    p.add_argument("--stamp", default=None, help="fixed run folder name (for tests)")
    p.add_argument(
        "--data", default=None,
        help="use live data from this directory (history/, quotes.json) instead "
             "of the synthetic fixtures",
    )
    p.add_argument(
        "--adjusted", action="store_true",
        help="declare --data prices split-adjusted (see scripts/import_history.py)",
    )
    p.add_argument(
        "--excel", nargs="?", const=True, default=False,
        help="also write an Excel workbook. Runs every strategy, since the "
             "Verdicts sheet compares them.",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.data:
        marker = os.path.join(args.data, "history", ".adjusted")
        adapter = LiveAdapter(
            args.data, adjusted=args.adjusted or os.path.exists(marker)
        )
    else:
        adapter = FixtureAdapter(args.fixtures)
    holdings = load_holdings(args.holdings)

    book = analyse(holdings, adapter, stated_risk=args.risk)

    # Book-wide context is computed once, by the strategy that needs it.
    # Some strategies cannot score a stock in isolation at all: the factor
    # model's z-scores are cross-sectional, and Bajaj reads the market regime
    # before any stock. The runner asks the strategy rather than its name.
    strategy = get(args.strategy)
    symbols = [h.symbol for h in holdings]
    context = (
        strategy.build_context(symbols, adapter, book)
        if strategy.needs_context
        else None
    )
    verdicts = {}
    for h in holdings:
        kwargs = dict(
            horizon=args.horizon, risk_profile=args.risk, avg_cost=h.avg_cost
        )
        if context is not None:
            kwargs["context"] = dict(context, held_qty=h.qty)
        verdicts[h.symbol] = strategy.evaluate(h.symbol, adapter, **kwargs)
    # The Verdicts sheet compares strategies, so Excel output needs them all.
    strategy_runs: dict[str, dict] = {args.strategy: verdicts}
    if args.excel:
        for name in STRATEGIES:
            if name == args.strategy:
                continue
            other = get(name)
            other_ctx = (
                other.build_context(symbols, adapter, book)
                if other.needs_context
                else None
            )
            strategy_runs[name] = {
                h.symbol: other.evaluate(
                    h.symbol, adapter, horizon=args.horizon,
                    risk_profile=args.risk, avg_cost=h.avg_cost,
                    **({"context": dict(other_ctx, held_qty=h.qty)} if other_ctx else {}),
                )
                for h in holdings
            }
        strategy_runs = {n: strategy_runs[n] for n in STRATEGIES if n in strategy_runs}

    health = health_verdict(book)
    queue = action_queue(verdicts, holdings, book)
    dials = {"horizon": args.horizon, "risk_profile": args.risk, "depth": args.depth}

    payload = {
        "dials": dials,
        "strategy": args.strategy,
        "engine": "rules",
        "market_context": context,
        "data_source": {
            "adapter": type(adapter).__name__,
            "adjusted": adapter.adjusted,
            "synthetic": isinstance(adapter, FixtureAdapter),
        },
        # Persist the holdings verbatim.  Reconstructing quantities from
        # weights later loses precision, and "EXIT: sell 59" on a 60-share
        # position is not an exit — it is a rounding error wearing a
        # recommendation's clothes.
        "holdings": [
            {"symbol": h.symbol, "qty": h.qty, "avg_cost": h.avg_cost} for h in holdings
        ],
        "book": book,
        "strategy_runs": {
            name: {s: {"action": v["action"], "reasons": v.get("reasons", [])}
                   for s, v in run.items()}
            for name, run in strategy_runs.items()
        } if args.excel else None,
        "health": health,
        "action_queue": queue,
        # 'quick' keeps the run folder small; 'deep' keeps every setup's stats.
        "verdicts": verdicts if args.depth == "deep" else {
            s: {k: v for k, v in vd.items() if k != "backtest"}
            for s, vd in verdicts.items()
        },
    }
    if strategy.post_process:
        payload.update(strategy.post_process(verdicts, book))

    markdown = render_markdown(book, health, queue, dials)
    if strategy.render_sections:
        markdown += strategy.render_sections(payload)
    path = write_run(args.out, payload, markdown, stamp=args.stamp)

    if args.excel:
        from core.excel import write_workbook

        prices = (
            {h.symbol: adapter.last_price(h.symbol) for h in holdings}
            if isinstance(adapter, LiveAdapter)
            else {h.symbol: (verdicts[h.symbol]["last_close"], "fixture") for h in holdings}
        )
        coverage = (
            adapter.report(symbols) if isinstance(adapter, LiveAdapter) else None
        )
        xlsx = args.excel if isinstance(args.excel, str) else os.path.join(
            path, "portfolio-review.xlsx"
        )
        write_workbook(payload, xlsx, prices=prices, coverage=coverage)
        if not args.quiet:
            print(f"workbook written to {xlsx}")

    if not args.quiet:
        print(markdown)
        print(f"\nrun written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
