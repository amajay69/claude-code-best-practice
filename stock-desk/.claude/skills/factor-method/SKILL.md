---
name: factor-method
description: How to read the cross-sectional factor model — ranks, z-scores, absolute floors and allocation tilt. Preloaded when the factor strategy is selected.
user-invocable: false
---

# Reading the factor model

Run with `--strategy factor`. Everything below is precomputed into
`analysis.json` under `verdicts.<SYM>.factor` and `market_context`.

## What makes this strategy different

`baseline` and `bajaj` judge a stock against **absolute** criteria — a
score threshold, a gate — so either can be computed for one stock alone.
This one cannot. A factor score is a stock's **position relative to the
other holdings**, so the whole book is read before any verdict exists.

## The trap you must never let a reader fall into

**Ranks here are within their own book, not against the market.**

Standardising across ten holdings guarantees a top and a bottom quintile.
If every holding is excellent, two still rank in the bottom. If every
holding is dreadful, two still rank at the top. The spread is produced by
the arithmetic, not discovered in the data.

So: a `+1.5` value z-score means **"the cheapest thing you own"**, never
"cheap". Never write "ICICIBANK scores well on momentum" without the
qualifier. Always carry the `within_book_only` flag into your prose, and
quote `market_context.factor_model.caveat` when `reliable` is false.

## Rank versus floors

Two separate signals, and conflating them is the main failure mode:

| Signal | Answers | Can say a stock is bad? |
| --- | --- | --- |
| Composite z / rank | "worst of what you own" | **no** |
| `failed_floors` | "bad in its own right" | yes |

Absolute floors: 12-1 momentum below 0, blended quality below 0, earnings
yield below 2% (PE above 50).

An **exit needs both** — a bottom-ranked composite *and* at least two
failed floors. A low rank alone is a trim at most, and the verdict says
explicitly that it is "a relative call only". Without this pairing the
strategy would recommend a sale every run forever.

## The four factors

| Factor | Raw measure | Note |
| --- | --- | --- |
| `value` | earnings yield (1/PE) | higher is cheaper |
| `quality` | blend of ROE, −leverage, profit growth | |
| `momentum` | 12-1 return (t−252 to t−21) | skips the last month to avoid short-term reversal |
| `low_vol` | negated annualised volatility | higher is calmer |

Weights are equal by default. There is no evidence in this repository to
justify tilting one factor over another, and inventing weights would dress
a guess as a model — say so if asked why they are equal.

## Allocation tilt

`market_context.book_tilt` is the weighted mean z-score per factor. Because
z-scores are standardised over this same book, the equal-weighted baseline
is **zero by construction** — so the weighted exposure *is* the tilt the
position sizing creates. Do not describe it as a deviation from some
neutral portfolio; there is no external baseline here.

## Confidence

Conviction scales with the composite z and is then **halved** whenever the
universe is under 30 names. Ten-name cross-sectional statistics do not
support confident calls. If you report a rank at full conviction you have
misled the reader about the strongest claim in the whole strategy.

## Scope

Educational only. A ranked suggestion list for a human, never an order.
