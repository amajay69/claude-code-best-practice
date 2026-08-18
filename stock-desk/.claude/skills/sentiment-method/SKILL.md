---
name: sentiment-method
description: How to read the narrative slice of analysis.json. Preloaded into sentiment-analyst.
user-invocable: false
---

# Reading the narrative

Your question is **"what is the market saying?"** — the story attached to
the stock, which moves prices in the short run and matters less the longer
the horizon.

## Your slice

`news` from the adapter, plus `verdicts.<SYM>.technical.pct_from_52w_high`
and `rsi_14` as crowd-positioning proxies.

## How to weigh it

1. **Scale your own relevance to the dial.** At `intraday` or `swing`
   horizons narrative dominates. At `wealth` (3y+) it is close to noise, and
   you should say so and lower your confidence rather than pretending to a
   view.
2. **Separate news from priced-in news.** A bad headline on a stock already
   -40% may be the *end* of the story, not the start. Compare the headline's
   tone against `pct_from_52w_high`.
3. **Absence is information.** No coverage on a large position is itself
   worth flagging.
4. **Headlines are claims, not facts.** Report what is being said and who is
   saying it, never restate a headline as established truth.

## Fixture caveat

Fixture headlines carry `"source": "SYNTHETIC"`. When you see that, say so
in your `evidence` — a sentiment read on generated headlines describes the
fixture, not any real company, and a reader must not mistake one for the
other.

## What disqualifies your stance

Return `neutral` with low confidence when the only available headlines are
generic sector commentary that mentions no specific holding.
