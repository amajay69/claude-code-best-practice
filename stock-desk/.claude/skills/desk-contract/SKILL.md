---
name: desk-contract
description: The shared data contract every desk agent reads and writes. Preloaded into all analyst, research, trader, risk and decision agents.
user-invocable: false
---

# Desk data contract

Every agent on this desk reads the **same** deterministic fact sheet and
writes the **same** shaped output. This file is that interface.

## The one rule

**Agents interpret numbers. Agents never compute numbers.**

Every price, ratio, correlation, beta, win rate and expectancy has already
been computed by `core/` and written to `analysis.json`. Read it. Do not
recalculate it, do not estimate it, and do not cite a figure that is not in
the file. If a number you want is absent, say it is absent — that is a
finding, not a gap to fill from memory.

This is what makes two runs of the same portfolio agree on the facts even
when they disagree on the call.

## Where the facts live

The command writes a run folder before any agent starts:

```
runs/<timestamp>/analysis.json
```

Read it with `Read`. Its shape:

| Path | What it holds |
| --- | --- |
| `dials` | `horizon`, `risk_profile`, `depth` — the user's settings |
| `book.totals` | market value, invested, P&L, return % |
| `book.weights` | symbol → portfolio weight (0-1) |
| `book.concentration` | top name/sector, breaches, HHI, diversification score |
| `book.correlation` | `effective_bets`, `most_correlated_pairs` |
| `book.risk` | beta, annualised vol, level, stated profile, `mismatch` |
| `book.benchmark` | portfolio vs index return, `beating_index` |
| `verdicts.<SYM>` | the rules-engine baseline for each holding |
| `verdicts.<SYM>.technical` | trend, RSI, ATR, drawdown, distance from high |
| `verdicts.<SYM>.backtest` | per-setup win rate, expectancy, `sufficient` |
| `action_queue` | the rules-engine baseline ranking |

## Reading the backtest honestly

`backtest.all_setups.<name>` carries `samples`, `raw_triggers`, `win_rate`,
`expectancy` and `sufficient`.

- **`sufficient: false` means the numbers are colour, not evidence.** A 100%
  win rate over 3 samples is noise wearing a statistic's clothes. Never cite
  a win rate from an insufficient setup as support for a call.
- `raw_triggers` far exceeding `samples` is expected — overlapping triggers
  are collapsed so one market event is counted once.
- `expectancy` is per-trade expected return as a fraction, already net of
  the stop implied by the risk dial.

## Output shape

Return **only** a JSON object, no prose wrapper, no code fence:

```json
{
  "agent": "technical-analyst",
  "engine": "llm",
  "views": {
    "HDFCBANK": {
      "stance": "supportive",
      "confidence": 0.6,
      "evidence": ["cites only figures present in analysis.json"],
      "concern": "the strongest argument against this stance"
    }
  }
}
```

- `stance` ∈ `supportive` | `neutral` | `hostile` (analysts) or an action in
  `exit` | `trim` | `hold` | `accumulate` | `buy` (orchestrator, decision).
- `confidence` ∈ 0.0–1.0. Below 0.35 means "I would not act on this."
- `concern` is mandatory. An analyst who cannot state the best argument
  against their own view has not finished the analysis.
- `engine` is always `"llm"` from an agent. The value `"rules"` is reserved
  for the deterministic fallback, and mislabelling it would let a
  degraded answer be read with full-pipeline trust.

## Scope

This desk produces a ranked suggestion list for a human. It never places an
order, and no agent should write output phrased as an instruction to a
broker. Every report carries the educational-use disclaimer.
