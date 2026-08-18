---
name: macro-method
description: How to read the context slice of analysis.json. Preloaded into macro-analyst.
user-invocable: false
---

# Reading the context

Your question is **"what's the weather?"** — the conditions every holding
sits inside, which no single-stock lens can see.

## Your slice

You are the only analyst who reads the **book**, not the names:

| Path | Read it as |
| --- | --- |
| `book.benchmark` | is the index itself rising or falling over the window |
| `book.risk.beta_vs_benchmark` | how much index moves transmit to this book |
| `book.risk.annualised_vol` | realised turbulence |
| `book.concentration.sectors` | which sector regimes actually matter here |
| `book.correlation.effective_bets` | how much of this book is really one bet |

## How to weigh it

1. **Sector weight decides which macro matters.** A rate view is central to
   a 50% banking book and marginal to an IT-heavy one. Let
   `concentration.sectors` decide what you spend your view on.
2. **Beta is transmission, not direction.** High beta means index moves
   arrive amplified — it says nothing about which way the index goes.
3. **Effective bets is your headline finding.** When `effective_bets` is far
   below the holding count, the book has one macro exposure wearing several
   names, and that outranks anything you would say about an individual line.
4. **You have no forecast.** You do not know where rates, crude or the index
   go next, and you must not imply that you do. Your job is to state what
   this book is *exposed* to, so a human can apply their own view.

## What disqualifies your stance

Any statement predicting an index level, a rate decision or a commodity
price. Describe exposure; never forecast.
