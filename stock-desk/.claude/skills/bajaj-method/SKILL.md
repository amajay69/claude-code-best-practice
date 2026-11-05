---
name: bajaj-method
description: Vivek Bajaj's techno-funda framework as the desk applies it — gates, regime, sizing and exits. Preloaded into regime-analyst and available to the orchestrator when the bajaj strategy is selected.
user-invocable: false
---

# The Bajaj framework

A rule-based techno-funda method: quality **and** momentum, inside a
favourable market, sized so no single loss matters. Run with
`--strategy bajaj`; the deterministic core computes every figure below and
writes it to `analysis.json` under `verdicts.<SYM>.bajaj` and
`market_context`.

## The one structural difference

**Gates, not sums.**

The baseline strategy adds a technical score to a fundamental score, so a
superb business at a poor moment nets out positive and buys. This framework
forbids that outright: *a great company without price momentum is a
narrative, not a trade.* Every gate passes on its own or the stock is
rejected. When you read a Bajaj verdict, never describe a failed gate as
"offset" by a strong one — nothing offsets anything here.

## Order of operations

The sequence is not decorative; each step gates the next.

1. **Market regime** (`market_context.regime`) — bullish / volatile /
   bearish, carrying a `deployment_ceiling` of 100% / 50% / 25%. A good
   setup in a bearish tape is still a bad trade. The ceiling caps new
   exposure; it never obliges you to deploy.
2. **Sector ranking** (`market_context.sector_rankings`) — only stocks in
   leading sectors are eligible.
3. **The six entry rules** (`bajaj.entry_checklist`) — regime, sector,
   fundamental ≥ 70/100, momentum green, strong zone, stop defined first.
4. **Sizing** (`bajaj.position_sizing`) — risk first, size second.
5. **Exit** (`bajaj.exit_signal`) — see below.

## Reading the momentum zone

| Zone | Means |
| --- | --- |
| `green` | RS above zero and not materially falling, RSI > 50 |
| `fading` | RS still positive but being handed back |
| `recovering` | RS negative but turning up |
| `red` | RS negative and falling |

Only `green` passes the gate. `fading` is a warning, not a pass.

## Reading the exit signal

Two independent triggers with different rules, and conflating them is the
most common misreading:

- **Technical exit needs BOTH** — RS below zero **and** Supertrend red. One
  alone is a hold. That tolerance for noise is deliberate and is the rule
  investors break first, exiting on the first red candle.
- **Double-yellow is separate** — fundamentals poor **and** momentum poor.
  That is a failed thesis, not a wobble, and exits on its own.

When reporting a hold where one trigger has fired, say which one and that
the framework requires two. Silence there reads as "nothing is wrong".

## What the framework tolerates

A position down 10% or more whose fundamentals are still green is expected
to be **sat through**, not sold. Never recommend exiting on drawdown alone,
and never because the broader market is correcting — only because the
stock-specific thesis has failed.

## Position sizing

```
shares = rupee_risk / (entry - stop)        then capped at 25% of the book
```

Both halves are load-bearing. The division bounds the **loss**; the cap
bounds the **position**. A stop ₹3 below a ₹223 share turns a ₹10,550 risk
budget into 3,049 shares — 64% of the book on one name, with the loss still
correctly bounded at 1%. When `capped_by_concentration` is true, say so:
the position carries less risk than budgeted and the stop drove it.

## Portfolio construction

- 10-15 names on limited capital, up to 20-25 on large capital
- 50-60% of the book in **core** positions: strong on *both* legs
- `portfolio_construction.issues` lists every breach

## What is NOT implemented, and why

State these when they are relevant rather than implying full coverage:

| Missing | Reason |
| --- | --- |
| Mother-Daughter 2-hour entry timing | this desk has daily bars only; faking it would produce a precise-looking entry price that means nothing |
| True sector-index ranking | approximated from the holdings' own RS — a sector held by one stock is ranked on that stock |
| Broad-market breadth | computed over the portfolio, flagged unreliable, and ignored in the regime call below 50 names |

## Scope

Educational only. A ranked suggestion list for a human, never an order.
