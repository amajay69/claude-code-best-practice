#!/usr/bin/env python3
"""Generate the offline fixture set the desk develops against.

SYNTHETIC DATA.  Real NSE ticker names are used so the pipeline exercises
realistic symbols, but every price, fundamental and headline here is
generated.  Nothing in ``fixtures/`` describes any real company.

Prices come from a factor model rather than independent random walks::

    r_stock = beta_market * r_market + beta_sector * r_sector + idiosyncratic

Independent walks would leave the correlation module untested — every pair
would sit near zero and "effective bets" would always equal the holding
count.  A factor model builds real sector clusters, so the fixture book
genuinely has fewer independent bets than names, and the maths has
something to find.

Deterministic: a fixed seed means regenerating produces byte-identical
fixtures, so tests can assert on exact numbers.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import random

SEED = 20260818
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
YEARS = 2.6
BENCHMARK = "NIFTY50"

# symbol -> (sector, market beta, sector beta, annual drift, annual vol, start price)
UNIVERSE = {
    "HDFCBANK":   ("Banking",  0.95, 0.80, 0.05, 0.22, 1450.0),
    "ICICIBANK":  ("Banking",  1.05, 0.85, 0.09, 0.24, 1050.0),
    "KOTAKBANK":  ("Banking",  0.90, 0.82, -0.02, 0.23, 1750.0),
    "INFY":       ("IT",       0.85, 0.88, 0.03, 0.26, 1520.0),
    "TCS":        ("IT",       0.80, 0.86, 0.02, 0.23, 3900.0),
    "RELIANCE":   ("Energy",   1.10, 0.70, 0.07, 0.25, 2850.0),
    "ONGC":       ("Energy",   1.15, 0.75, -0.05, 0.31, 240.0),
    "HINDUNILVR": ("FMCG",     0.65, 0.60, -0.01, 0.18, 2400.0),
    "JUBLFOOD":   ("Consumer", 1.20, 0.55, -0.22, 0.36, 620.0),
    "MARUTI":     ("Auto",     1.00, 0.65, 0.05, 0.27, 11200.0),
}

# Deliberately unbalanced: bank-heavy with one oversized position, so the
# concentration and correlation checks have something real to flag.
# Values are (quantity, entry bar index) — the average cost is read off the
# generated series at that bar rather than hardcoded, so every position's
# P&L is consistent with the price history the backtest also reads.
BOOK = {
    "HDFCBANK":   (140, 40),
    "ICICIBANK":  (95, 120),
    "KOTAKBANK":  (40, 60),
    "INFY":       (60, 300),
    "TCS":        (18, 420),
    "RELIANCE":   (45, 90),
    "ONGC":       (300, 200),
    "HINDUNILVR": (22, 480),
    "JUBLFOOD":   (110, 150),
    "MARUTI":     (6, 520),
}


HEADLINES = {
    "Banking": [
        "{sym} reports steady deposit growth in quarterly update",
        "Analysts flag margin pressure across private banks",
        "{sym} board approves fresh capital raise plan",
    ],
    "IT": [
        "{sym} guides cautiously on discretionary spending",
        "Deal wins improve at {sym} but pricing stays soft",
        "Sector commentary points to a slower hiring quarter",
    ],
    "Energy": [
        "Crude swings weigh on {sym} refining margins",
        "{sym} announces incremental capex in exploration",
        "Regulatory review adds uncertainty for the sector",
    ],
    "FMCG": [
        "Rural demand recovery stays patchy for {sym}",
        "{sym} holds pricing despite input cost relief",
    ],
    "Consumer": [
        "{sym} same-store sales decline for a third quarter",
        "Store expansion at {sym} outpaces footfall growth",
        "Management reiterates margin guidance despite weak demand",
    ],
    "Auto": [
        "{sym} monthly dispatches beat street expectations",
        "Rising input costs cloud the outlook for {sym}",
    ],
}


def demean(series: list[float], target_mean: float) -> list[float]:
    """Shift a random series so its *realised* mean hits the target.

    Without this the fixture's drift is whatever the seed happened to draw.
    A 2-sigma market path turns a 5%/yr universe into a 130% melt-up and the
    example book stops being believable.  Shifting preserves the random
    shape while making the scenario the one we intended to construct.
    """
    actual = sum(series) / len(series)
    shift = target_mean - actual
    return [x + shift for x in series]


def business_days(n: int, end: dt.date) -> list[str]:
    days, day = [], end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= dt.timedelta(days=1)
    return sorted(days)


def bars_from_closes(rng: random.Random, dates: list[str], closes: list[float]) -> list[dict]:
    rows = []
    prev = closes[0]
    for date, close in zip(dates, closes):
        gap = rng.gauss(0, 0.002)
        open_ = prev * (1 + gap)
        spread = abs(rng.gauss(0, 0.006)) + 0.002
        high = max(open_, close) * (1 + spread)
        low = min(open_, close) * (1 - spread)
        rows.append(
            {
                "date": date,
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": int(rng.uniform(3e5, 4e6)),
            }
        )
        prev = close
    return rows


def main() -> None:
    rng = random.Random(SEED)
    n = int(252 * YEARS)
    dates = business_days(n, dt.date(2026, 8, 14))
    os.makedirs(os.path.join(ROOT, "prices"), exist_ok=True)

    # Shared factors: one market, one per sector.
    market = demean(
        [rng.gauss(0.0, 0.13 / (252 ** 0.5)) for _ in range(n)], 0.06 / 252
    )
    sectors = sorted({meta[0] for meta in UNIVERSE.values()})
    sector_factor = {
        s: demean([rng.gauss(0.0, 0.11 / (252 ** 0.5)) for _ in range(n)], 0.0)
        for s in sectors
    }

    # Benchmark is the market factor itself, so beta-vs-index is meaningful.
    level = 24000.0
    bench_closes = []
    for r in market:
        level *= 1 + r
        bench_closes.append(level)
    _write_prices(BENCHMARK, bars_from_closes(rng, dates, bench_closes))

    series_closes: dict[str, list[float]] = {}
    for sym, (sector, bm, bs, drift, vol, start) in UNIVERSE.items():
        idio_sd = max(vol ** 2 - (bm * 0.13) ** 2 - (bs * 0.11) ** 2, 0.01 ** 2) ** 0.5
        idio = demean([rng.gauss(0.0, idio_sd / (252 ** 0.5)) for _ in range(n)], 0.0)
        price, closes = start, []
        for k in range(n):
            r = drift / 252 + bm * market[k] + bs * sector_factor[sector][k] + idio[k]
            price *= 1 + r
            closes.append(price)
        series_closes[sym] = closes
        _write_prices(sym, bars_from_closes(rng, dates, closes))

    _write_json("sectors.json", {s: m[0] for s, m in UNIVERSE.items()} | {BENCHMARK: "Index"})
    _write_json("fundamentals.json", _fundamentals(rng))
    _write_json("news.json", _news(rng, dates[-1]))
    _write_holdings(rng, series_closes)

    print(f"wrote {len(UNIVERSE) + 1} price series x {n} bars to {ROOT}")
    print("SYNTHETIC DATA — real tickers, generated prices. Not real market data.")


def _write_prices(symbol: str, rows: list[dict]) -> None:
    path = os.path.join(ROOT, "prices", f"{symbol}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def _write_json(name: str, payload: dict) -> None:
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _fundamentals(rng: random.Random) -> dict:
    out = {}
    for sym, (sector, *_rest) in UNIVERSE.items():
        out[sym] = {
            "pe": round(rng.uniform(14, 62), 1),
            "industry_pe": round(rng.uniform(18, 40), 1),
            "roe_pct": round(rng.uniform(6, 28), 1),
            "debt_to_equity": round(rng.uniform(0.0, 1.8), 2),
            "revenue_growth_3y_pct": round(rng.uniform(-4, 22), 1),
            "profit_growth_3y_pct": round(rng.uniform(-12, 26), 1),
            "promoter_holding_pct": round(rng.uniform(0, 74), 1),
            "promoter_pledge_pct": round(rng.choice([0, 0, 0, rng.uniform(1, 12)]), 1),
            "market_cap_cr": int(rng.uniform(25_000, 1_400_000)),
            "sector": sector,
            "_synthetic": True,
        }
    return out


def _news(rng: random.Random, latest: str) -> dict:
    out = {}
    for sym, (sector, *_rest) in UNIVERSE.items():
        pool = HEADLINES[sector]
        out[sym] = [
            {
                "date": latest,
                "headline": tpl.format(sym=sym),
                "source": "SYNTHETIC",
            }
            for tpl in pool
        ]
    return out


def _write_holdings(rng: random.Random, series_closes: dict[str, list[float]]) -> None:
    """Written in Zerodha's header style to exercise the header normaliser.

    Average cost is the close at the position's entry bar, jittered slightly
    to look like a real averaged-in cost rather than a single fill.
    """
    path = os.path.join(ROOT, "holdings.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Instrument", "Qty.", "Avg. cost"])
        for sym, (qty, entry_bar) in BOOK.items():
            cost = series_closes[sym][entry_bar] * (1 + rng.uniform(-0.015, 0.015))
            writer.writerow([sym, qty, round(cost, 2)])


if __name__ == "__main__":
    main()
