[← Back to stock-desk](README.md)

# Portfolio Pipeline — design for review

**Status: proposal. Nothing here is built yet.** Read the data gap in §2
first; it changes what is worth building.

---

## 1. The flow

```
  ┌─────────────────────────────────────────────────────┐
  │ 1. UPLOAD      your holdings sheet                  │
  └──────────────────────┬──────────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────────┐
  │ 2. FETCH + COMPUTE          no AI, fully repeatable │
  │    live NSE prices → every measurable number        │
  │    → Excel "Facts" sheet, every column source-tagged│
  └──────────────────────┬──────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
  ┌──────────────────────┐  ┌──────────────────────────┐
  │ 3. AGENTS ANNOTATE   │  │ 4. STRATEGIES DECIDE     │
  │  4 specialists add   │  │  baseline / bajaj /      │
  │  stance + concern    │  │  factor — each reads     │
  │  OPINION ONLY,       │  │  ONLY the Facts sheet    │
  │  never numbers       │  │  → 3 verdict columns     │
  └──────────┬───────────┘  └────────────┬─────────────┘
             └───────────┬───────────────┘
                         ▼
  ┌─────────────────────────────────────────────────────┐
  │ 5. SUMMARY   agreement map + what to do first       │
  └─────────────────────────────────────────────────────┘
```

**Stages 3 and 4 run side by side, not in sequence.** Both read the Facts
sheet. Agents never feed the strategies — that is what keeps strategy
output reproducible. Run the same book twice and the verdicts are
identical; only the agent prose may vary.

---

## 2. The data gap — read this before anything else

Your `NSE_LiveCM_Data` server is live. Here is exactly what one call returns:

```json
{"symbol":"HDFCBANK","lastTradedPrice":760.0,"openPrice":760.0,
 "highPrice":762.7,"lowPrice":749.1,"preClosePrice":736.7,
 "change":23.3,"perChange":3.16,"volume":65401905,
 "fiftyTwoWeekHigh":1017.5,"fiftyTwoWeekLow":669.2,
 "perChange30d":7.83,"latestTimestamp":"2026-11-05 16:00:28"}
```

It is a **snapshot**, not a history. That single fact decides what the
pipeline can honestly do.

### What we can compute from it

| Available | Gives us |
| --- | --- |
| `lastTradedPrice` | real market value, real P&L |
| `fiftyTwoWeekHigh/Low` | % from 52-week high → Bajaj's **strong zone** |
| `perChange30d` | a crude momentum reading |
| `perChange`, `volume` | today's move and participation |
| sectoral indices (NIFTY BANK, NIFTY IT…) | **real sector ranking** — removes the current proxy |
| `cm_get_index_quote` 1w/1m/1y | real benchmark comparison |

### What it cannot give us

Everything below needs a **daily price series**, which the server does not serve:

| Needs history | Used by |
| --- | --- |
| 50-DMA, 200-DMA, trend | baseline, bajaj |
| RSI(14) | baseline, bajaj |
| ATR, Supertrend | bajaj stops **and** half its exit rule |
| Relative Strength (55-day) | bajaj entry gate **and** half its exit rule |
| Correlation, effective bets, beta | the whole portfolio layer |
| 2-year backtest replay | the only non-AI check in the system |
| Annualised volatility | factor low-vol |

**Also absent: fundamentals.** No PE, ROE, debt, promoter holding. That
removes the Bajaj fundamental gate and two of the four factors.

### Plainly

Live prices fix **valuation**. They do not fix **analysis**. Roughly 70% of
what the three strategies read is unavailable today.

### Four ways to close it

| Option | Gets us working | Cost |
| --- | --- | --- |
| **A. Upload history** — one CSV per stock from your broker or TradingView | immediately | manual, repeat per stock |
| **B. Accumulate** — snapshot daily, build history going forward | ~3 months for RSI, ~1 year for 200-DMA | zero effort, slow start |
| **C. Reduced-signal mode** — only what snapshots support | immediately | much weaker; most rules switch off |
| **D. Another history source** | immediately | currently blocked by the network policy |

**Recommendation: A for history, and C as the honest fallback while you
have neither.** B should run regardless from day one — it costs nothing and
every day of delay is a day of history not captured.

Fundamentals need their own answer: upload a sheet, or leave those gates
scored neutral and say so.

### Also noted

The NSE server **disconnected and reconnected twice** during this session.
The pipeline must treat a failed fetch as a visible gap in the Facts sheet,
never as a zero, and never silently fall back to stale fixtures.

---

## 3. The Excel workbook

One file per run: `runs/<timestamp>/portfolio-review.xlsx`.

### Sheet 1 — `Holdings` (your input, priced)

| Column | Source |
| --- | --- |
| Symbol, Qty, Avg Cost | your upload |
| Last Price, Day % | NSE live |
| Market Value, Weight %, P&L ₹, P&L % | computed |

### Sheet 2 — `Facts` (deterministic; the only thing strategies read)

Grouped, and **every column header carries its source tag**:
`[NSE]` live · `[CALC]` computed from history · `[UPLOAD]` your file ·
`[—]` unavailable.

| Group | Columns |
| --- | --- |
| Identity | Symbol, Sector, Series |
| Live price | Last, Day %, Volume, 52w High, 52w Low, % from 52w High, 30d % |
| Trend *(needs history)* | 50-DMA, 200-DMA, Trend, RSI14, ATR, ATR %, Supertrend, Supertrend Level |
| Relative *(needs history)* | RS, RS slope, RS zone, Sector index, Sector rank |
| Fundamentals *(needs upload)* | PE, Industry PE, ROE %, D/E, Rev growth 3y, Profit growth 3y, Promoter %, Pledge % |
| Backtest *(needs history)* | Best setup, Samples, Win rate, Expectancy, Sufficient? |
| Risk *(needs history)* | Annualised vol, Beta, Max drawdown 2y |

Unavailable cells read **`n/a — needs daily history`**, never blank and
never 0. A blank invites the reader to assume zero; a zero is a lie.

### Sheet 3 — `Agent Notes` (AI opinion — banner at the top saying so)

| Column | Content |
| --- | --- |
| Symbol | |
| Technical stance / concern | "is now a good moment?" |
| Fundamental stance / concern | "is it a good company?" |
| Sentiment stance / concern | "what is the market saying?" |
| Macro stance / concern | "what's the weather?" |

Stance ∈ `supportive` · `neutral` · `hostile`. **Concern is mandatory** —
the strongest argument against the agent's own stance. An agent that cannot
write one has asserted, not analysed.

Agents may cite only figures present in `Facts`. Where a fact is `n/a` they
say so; they never fill the gap from memory.

### Sheet 4 — `Verdicts` (the three strategies)

| Column |
| --- |
| Symbol |
| Baseline — action, why |
| Bajaj — action, why |
| Factor — action, why |
| **Exact agreement** (3/3, 2/3, split) |
| **Directional agreement** (see §5) |

### Sheet 5 — `Summary`

Portfolio header, the agreement map, the action queue, the open conflicts.

### Sheet 6 — `Provenance`

Every data source, its timestamp, and whether any value is synthetic.
If any fixture data was used, this sheet says so in the first row.

---

## 4. What the agents write

**Stance + concern. Never a number.**

The rule that makes the whole thing trustworthy: *agents interpret
numbers, agents never produce them.* If an agent writes a price, a ratio or
a growth rate, nothing downstream can tell it from a real one.

This is the one correction to your original stage 2. "Bring additional data
points" splits into two jobs that must stay apart:

- **data** comes from sources, tagged with where it came from (§3)
- **judgement** comes from agents, in its own sheet, marked as opinion

---

## 5. How the summary combines three strategies

**It does not blend them.** Averaging "exit", "hold" and "accumulate" gives
mush and throws away the only thing that made three strategies worth having.

### Compare on direction, not exact wording

| Action | Direction |
| --- | --- |
| exit, trim | **reduce** |
| hold | **hold** |
| accumulate, buy | **add** |

"Exit" and "trim" both mean reduce. Comparing exact labels would call that
a disagreement when the strategies actually concur.

### The agreement map

| Case | What it means | What the summary says |
| --- | --- | --- |
| **3/3 same direction** | strongest signal in the system | act — three methods with non-overlapping failure modes agree |
| **2/3** | majority with a dissenter | name the dissenter and the one thing it saw differently |
| **split** | genuine conflict | your decision; state exactly what it hinges on |

On the current fixture book, 7 of 10 holdings split. RELIANCE is the only
unanimous call. That ratio is the product — not any single verdict.

---

## 6. Decisions I need from you

| # | Question | My recommendation |
| --- | --- | --- |
| 1 | **History**: upload CSVs, accumulate daily, or run reduced-signal? | Upload for the stocks you care about; start accumulating today regardless |
| 2 | **Fundamentals**: upload a sheet, or score those gates neutral? | Upload — without it Bajaj loses its main gate and factor loses half its model |
| 3 | **Scope**: holdings only, or also a watchlist of stocks you don't own? | Holdings first. Watchlist changes the factor model's universe, for the better |
| 4 | **Agent cost**: 4 agents × 1 pass over the whole book, or per stock? | Whole book — 4 calls, not 4 × N |
| 5 | **Excel vs Sheets**: local .xlsx file, or a Google Sheet? | .xlsx first; it needs no connector |

---

## 7. Build order

Each step is independently useful, so you can stop after any of them.

1. **NSE adapter** — implement `DataAdapter` against the live server; live
   prices, real P&L, real sector indices. *Valuation becomes real.*
2. **Excel writer** — the workbook above from the existing run payload.
   *Output becomes readable.*
3. **Summary sheet** — directional agreement map. *The three strategies
   start paying for themselves.*
4. **History intake** — CSV upload per stock, plus the daily snapshot
   accumulator. *Analysis becomes real.*
5. **Agents to stance + concern** — mostly deleting from the current ones.
6. **Fundamentals intake.**

Steps 1-3 work with what exists today. Step 4 is the one that matters most
and is the one blocked on your decision in §6.

---

_Educational and research use only. Not investment advice. Not a
recommendation to buy, sell or hold any security. Consult a SEBI-registered
adviser before acting._
