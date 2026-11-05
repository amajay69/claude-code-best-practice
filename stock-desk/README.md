[← Back to main README](../README.md)

# Stock Desk

A multi-agent portfolio review desk, built as a self-contained agent team.
Point it at a broker holdings export and it grades every position and the
book as a whole, returning a ranked list of what to do first.

> **Educational and research use only.** Every verdict is AI-generated and
> can be wrong, including confidently wrong. This is not investment advice
> and not a recommendation to buy, sell or hold any security. The bundled
> fixture data is **synthetic** — real NSE tickers, generated prices — and
> describes no real company. Consult a SEBI-registered adviser before acting.

## Run it

```bash
cd stock-desk

# deterministic pass — no model, no API key, no network
python3 scripts/run_analysis.py --horizon positional --risk balanced

# the same book under Vivek Bajaj's techno-funda framework
python3 scripts/run_analysis.py --strategy bajaj --risk balanced

# the full desk
claude
> /portfolio-review fixtures/holdings.csv positional balanced standard
```

Stdlib only. No `pip install`, no dependencies.

```bash
python3 -m unittest discover -s tests    # 83 tests
```

## Architecture

Fan out to gather, sequential to decide.

```
holdings.csv
     │
     ▼
 ┌── FOUR SPECIALISTS (parallel, one lens each) ──┐
 │  Technical   Fundamental   Sentiment   Macro   │
 │  "good        "good         "what's    "what's │
 │   moment?"     company?"     said?"     the    │
 │                                         weather?"│
 └────────────────────┬───────────────────────────┘
                      ▼
              stock-orchestrator          ← the one barrier
                      ▼
      research-bull  ⚔  research-bear     ← parallel, independent
                      ▼
                   trader                 ← stance & timing
                      ▼
                risk-officer              ← constrains, holds a veto
                      ▼
                decision-maker            ← plan + backtest evidence
                      ▼
              runs/<timestamp>/
```

Risk sits *after* the trader on purpose: it constrains a stance that
already exists, rather than pre-emptively shaping one.

## The one rule

**Agents interpret numbers. Agents never compute numbers.**

Everything quantitative — indicators, correlations, beta, win rates,
expectancy, share counts — is computed by `core/` and written to
`analysis.json` before any agent starts. Agents read it. That is what makes
two runs of the same portfolio agree on the facts even when they disagree on
the call, and it is why the report card's arithmetic is reproducible.

## Two strategies, deliberately disagreeing

`--strategy` selects the verdict logic. Both read the same fact sheet.

| | `baseline` (default) | `bajaj` |
| --- | --- | --- |
| Logic | additive: technical + fundamental | independent gates, all must pass |
| Market regime | not consulted | assessed first; caps deployment at 100/50/25% |
| Sector | concentration only | only leading sectors are eligible |
| Buys | weakness in one leg offset by strength in the other | quality **and** momentum **and** leading sector **and** near highs |
| Exit | combined score below a threshold | RS < 0 **and** Supertrend red, or fundamentals and momentum both poor |
| Sizing | target weight multipliers | `shares = rupee risk / (entry − stop)`, capped at 25% |

**The structural difference is gates versus sums.** A sum lets a +3
fundamental offset a −2 momentum and buy. Bajaj forbids exactly that — *a
great company without price momentum is a narrative, not a trade* — so no
amount of quality rescues dead momentum. That is why this is a separate
strategy rather than extra indicators on the existing one.

They disagree on the bundled fixture book, and a test asserts they must:
the baseline rates KOTAKBANK and HINDUNILVR as `accumulate`, Bajaj exits
both on RS below zero plus a red Supertrend. Seeing the disagreement is the
point.

### What the Bajaj strategy does NOT implement

Stated plainly, because partial implementations of a published framework
invite the assumption of full coverage:

| Missing | Why |
| --- | --- |
| Mother-Daughter 2-hour entry timing | daily bars only; faking it on daily data yields a precise-looking entry price that means nothing |
| True sector-index ranking | approximated from holdings' own RS — a sector held by one stock is ranked on that stock, and flagged `proxy_warning` |
| Broad-market breadth | computed over the portfolio, marked `reliable: false`, and ignored in the regime call below 50 names |

### One definition that is a judgement call

"RS above 0" is ambiguous in the source — a raw `stock / index` ratio is
always positive. [`core/relative_strength.py`](core/relative_strength.py)
uses the Dorsey-style centred form, `(ratio / SMA(ratio, 55) − 1) × 100`,
so zero means "outperforming by more than its own recent average". Change
it there; nothing else assumes a particular formula.

## Layout

| Path | What it is |
| --- | --- |
| [`core/adapter.py`](core/adapter.py) | Data boundary. Swap `FixtureAdapter` for a live NSE/BSE provider here and nowhere else. |
| [`core/indicators.py`](core/indicators.py) | SMA, EMA, RSI, ATR, vol, drawdown — pure functions |
| [`core/backtest.py`](core/backtest.py) | Setup replay: win rate, expectancy, sufficiency |
| [`core/portfolio.py`](core/portfolio.py) | Concentration, correlation, effective bets, beta, benchmark |
| [`core/relative_strength.py`](core/relative_strength.py) | Centred RS, RS zones, sector ranking |
| [`core/regime.py`](core/regime.py) | Market regime and the deployment ceiling |
| [`core/strategies/bajaj.py`](core/strategies/bajaj.py) | The techno-funda gates, sizing and exit rules |
| [`core/fallback.py`](core/fallback.py) | Deterministic verdicts — the amber path and the agents' fact sheet |
| [`core/report.py`](core/report.py) | Health verdict, action queue, run persistence |
| [`.claude/agents/`](.claude/agents/) | The ten desk agents |
| [`.claude/skills/`](.claude/skills/) | `desk-contract` plus one method skill per specialist |
| [`.claude/commands/portfolio-review.md`](.claude/commands/portfolio-review.md) | The orchestration entry point |

## Three checks on the model

Most agent systems have none of these. This one has three, deliberately
independent of each other:

| Check | What it catches | Why it is independent |
| --- | --- | --- |
| **Adversarial** — bull vs bear | one-sided cases | two agents, neither seeing the other's argument |
| **Deterministic** — 2-year replay | plausible narratives with no historical support | arithmetic on price history; does not care what the desk concluded |
| **Structural** — correlation | ten holdings that feel diversified and aren't | operates on the book, can overrule any per-stock verdict |

The replay is the load-bearing one. Bull and bear still share a base model
and therefore its blind spots; only the backtest can say "this setup has
failed six times out of ten in *this* stock".

## Design decisions worth knowing

**Proceeds are never force-redeployed.** Target weights are absolute, not
renormalised to 100%. Renormalising would push every rupee freed by an exit
straight back into whatever remains, turning "sell three names" into
"concentrate harder into the rest". Unallocated capital stays in cash, and
the report says how much.

**Risk sizing without a position cap is dangerous.** `shares = risk /
(entry − stop)` bounds the *loss*; it does not bound the *position*. A stop
₹3 below a ₹223 share turns a ₹10,550 budget into 3,049 shares — 64% of the
book on one name, with the loss still correctly capped at 1%. Bajaj's rules
4 and 5 are not redundant, and implementing either alone is unsafe. See
`position_size` in [`core/strategies/bajaj.py`](core/strategies/bajaj.py).

**Adding to a deep loser requires evidence, not a score.** A position more
than 25% underwater can only be added to when its own history supports the
setup with enough independent samples. Otherwise the call is capped at
`hold` — never reversed to a sell, which would be the same overconfidence
pointing the other way. See `_guard_averaging_down` in
[`core/fallback.py`](core/fallback.py).

**Thin samples are labelled, not hidden.** A 100% win rate over three trades
is noise wearing a statistic's clothes. Every backtest result carries
`sufficient`, and agents are forbidden from citing statistics that fail it.

**The engine badge comes from the data.** 🟢 all-LLM, 🟠 all-rules, 🟡 mixed —
set by `render_report.py` from what actually produced each row, never from
what a model claims about itself. Partial model coverage degrades to a mixed
report rather than silently presenting rules output as AI output.

**The output boundary is a suggestion list.** This desk never places an
order. Its worst failure mode is a bad suggestion a human declines.

## Going live

Implement `DataAdapter` against a real provider and pass it in place of
`FixtureAdapter`. Two things matter more than the rest:

1. **Prices must be split- and bonus-adjusted.** Unadjusted series produce a
   fake -50% bar at every split, which makes the backtest confidently wrong
   rather than obviously broken. Declare `adjusted = False` if you cannot
   guarantee it.
2. **Point-in-time fundamentals.** Scoring a 2024 setup against today's
   balance sheet is lookahead by another name.

## Provenance

The architecture follows the desk described in Niteen Badgujar's
["I Gave My Stock Portfolio to a Team of AI Analysts"](https://www.niteenbadgujar.me/blog/i-gave-my-stock-portfolio-to-a-team-of-ai-analysts)
(August 2026) — four specialists into an orchestrator, then a five-station
desk with an adversarial research pair, backtest verification and provenance
badging.

The article documents topology only; it names no framework, model, data
provider or code. Everything in `core/` is an independent implementation.
Two deliberate departures:

- **Fan out by lens, not by stock.** Each specialist reads the whole book in
  one pass — ~10 agent calls for a 10-holding book instead of ~100.
- **Bull and bear are separate agents.** The article's diagram shows one
  "Research" station. Splitting it preserves genuine independence; a single
  agent asked to argue both sides hedges into mush.
