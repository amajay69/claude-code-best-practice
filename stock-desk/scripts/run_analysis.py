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
from core.backtest import HOLD_DAYS, STOP_ATR                   # noqa: E402
from core.regime import market_regime                         # noqa: E402
from core.relative_strength import sector_rankings            # noqa: E402
from core.strategies import NEEDS_CONTEXT, STRATEGIES, get    # noqa: E402
from core.strategies.bajaj import portfolio_construction      # noqa: E402
from core.portfolio import analyse                              # noqa: E402
from core.report import (                                      # noqa: E402
    action_queue, health_verdict, render_bajaj_sections, render_markdown, write_run,
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
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    adapter = FixtureAdapter(args.fixtures)
    holdings = load_holdings(args.holdings)

    book = analyse(holdings, adapter, stated_risk=args.risk)

    # Market context is computed once and shared. Bajaj's first rule is that
    # the regime is assessed before any stock is read, so it cannot be a
    # per-symbol afterthought.
    symbols = [h.symbol for h in holdings]
    context: dict | None = None
    if args.strategy in NEEDS_CONTEXT:
        context = {
            "regime": market_regime(adapter, symbols),
            "sector_rankings": sector_rankings(symbols, adapter),
            "portfolio_value": book["totals"]["market_value"],
        }

    strategy = get(args.strategy)
    verdicts = {}
    for h in holdings:
        kwargs = dict(
            horizon=args.horizon, risk_profile=args.risk, avg_cost=h.avg_cost
        )
        if context is not None:
            kwargs["context"] = dict(context, held_qty=h.qty)
        verdicts[h.symbol] = strategy(h.symbol, adapter, **kwargs)
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
        "health": health,
        "action_queue": queue,
        # 'quick' keeps the run folder small; 'deep' keeps every setup's stats.
        "verdicts": verdicts if args.depth == "deep" else {
            s: {k: v for k, v in vd.items() if k != "backtest"}
            for s, vd in verdicts.items()
        },
    }
    if args.strategy == "bajaj":
        payload["portfolio_construction"] = portfolio_construction(verdicts, book)

    markdown = render_markdown(book, health, queue, dials)
    if args.strategy == "bajaj":
        markdown += render_bajaj_sections(payload)
    path = write_run(args.out, payload, markdown, stamp=args.stamp)

    if not args.quiet:
        print(markdown)
        print(f"\nrun written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
