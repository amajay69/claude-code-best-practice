---
name: technical-method
description: How to read the price action slice of analysis.json. Preloaded into technical-analyst.
user-invocable: false
---

# Reading price action

Your question is **"is now a good moment?"** — not "is this a good company".
A great business at the wrong moment is still a bad trade, and answering the
business question is another agent's job.

## Your slice

`verdicts.<SYM>.technical` holds everything you may cite:

| Field | Read it as |
| --- | --- |
| `trend` | `uptrend` / `downtrend` / `sideways` from the 50/200-DMA relationship |
| `rsi_14` | <30 stretched down, >70 stretched up, 40-60 uninformative |
| `atr_pct` | daily range as a fraction of price — the position-sizing unit |
| `annualised_vol` | how violently this name moves |
| `max_drawdown_2y` | worst peak-to-trough over the window |
| `pct_from_52w_high` | negative; below -25% means materially broken |

## How to weigh them

1. **Trend dominates.** A hostile trend outranks a friendly oscillator. RSI
   30 in a downtrend is not a bounce signal, it is a falling knife.
2. **Oscillators only inside a trend.** Read `rsi_14` as timing *within* the
   regime `trend` establishes, never as a regime call of its own.
3. **Volatility sets size, not direction.** High `atr_pct` never argues for
   or against a position — it argues for a smaller one.
4. **Distance from high is context.** -40% in an uptrend is recovery; -40%
   in a downtrend is continuation.

## What disqualifies your stance

Say `neutral` with low confidence when `trend` is `sideways` and `rsi_14`
sits between 40 and 60. That combination genuinely carries no information,
and manufacturing a view from it is how the desk produces confident noise.

Never cite a backtest win rate whose `sufficient` flag is `false`.
