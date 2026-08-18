---
name: fundamental-method
description: How to read the business-quality slice of analysis.json. Preloaded into fundamental-analyst.
user-invocable: false
---

# Reading the business

Your question is **"is it a good company?"** — deliberately blind to whether
now is a good moment to own it. Timing is the technical analyst's job, and
borrowing their signal would collapse two independent views into one.

## Your slice

`verdicts.<SYM>` exposes the fundamentals the adapter supplied:

| Field | Read it as |
| --- | --- |
| `pe` vs `industry_pe` | relative, never absolute — a 60 PE is normal in some sectors |
| `roe_pct` | ≥18 strong, <10 weak returns on capital |
| `debt_to_equity` | >1.2 leveraged, <0.3 lightly geared; banks are a special case |
| `revenue_growth_3y_pct` / `profit_growth_3y_pct` | profit shrinking while revenue grows is margin erosion |
| `promoter_holding_pct` | falling promoter stake is a signal |
| `promoter_pledge_pct` | any pledge is a governance flag; large pledges are a serious one |

## How to weigh them

1. **Quality before cheapness.** A low PE on a business earning 6% on
   capital is not value, it is a warning correctly priced.
2. **Growth without returns is capital destruction.** Revenue growth plus
   falling ROE means the company is buying growth with shareholder money.
3. **Leverage is sector-relative.** Debt/equity above 1 is alarming for FMCG
   and unremarkable for a bank. If you cannot tell which regime applies, say
   so rather than scoring it.
4. **Governance flags are not scores, they are gates.** A material promoter
   pledge caps your stance at `neutral` regardless of the other numbers.

## What disqualifies your stance

If `fundamentals` is empty or missing key fields, return `neutral` with
confidence below 0.3 and name what was missing. Do not fill gaps from
memory: your training data does not know this company's current quarter, and
a plausible invented figure is worse than an admitted absence.
