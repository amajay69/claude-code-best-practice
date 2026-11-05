"""Relative Strength: the single most load-bearing measure in Bajaj's method.

Both his entry gate ("RS above 0 and sloping up") and half his exit trigger
("RS drops below zero") hang on this one number, so how it is defined
matters more than anything else in the strategy.

**The definition is a choice, and the source is ambiguous.**  "RS above 0"
cannot mean the raw price ratio ``stock / index`` — that is always positive
and carries no information about its own level.  A centred measure is
required.  The convention used here is the Dorsey-style normalisation:

    ratio = stock_close / index_close
    RS    = (ratio / SMA(ratio, n) - 1) * 100

RS > 0 means the stock is outperforming the index *by more than it has on
average over the last n sessions* — i.e. relative outperformance is
accelerating, not merely present.  That is the reading consistent with
Bajaj using it as a momentum entry trigger rather than a long-term
outperformance screen.

An implementation that instead compares the ratio against a fixed start date
would be anchored to an arbitrary day and drift into permanent positive or
negative territory, making "crosses below zero" fire once a decade.  If you
prefer a different convention, change it here; nothing else in the codebase
assumes a particular formula.
"""

from __future__ import annotations

from .adapter import Bar, DataAdapter
from .indicators import sma_series

#: Lookback for the RS baseline, in trading days (~2.5 months).
RS_WINDOW = 55

#: Sessions over which the RS slope is measured.
SLOPE_WINDOW = 10

#: RS points of slope movement treated as flat rather than directional.
#:
#: A strict ``slope > 0`` test misclassifies the steadiest compounders. For a
#: stock outperforming at a *constant* exponential rate, ``ratio / SMA(ratio)``
#: converges and RS is exactly flat — slope 0 — so the one stock Bajaj most
#: wants to own would be graded "fading". Only a materially falling RS means
#: outperformance is being handed back.
SLOPE_TOLERANCE = 0.25


def rs_series(stock: list[Bar], index: list[Bar], window: int = RS_WINDOW) -> list[float | None]:
    """Centred relative-strength series aligned to the common dates."""
    index_by_date = {b.date: b.close for b in index}
    ratio = [
        b.close / index_by_date[b.date]
        for b in stock
        if b.date in index_by_date and index_by_date[b.date]
    ]
    baseline = sma_series(ratio, window)
    return [
        ((r / base) - 1) * 100 if base else None
        for r, base in zip(ratio, baseline)
    ]


def relative_strength(
    stock: list[Bar], index: list[Bar], window: int = RS_WINDOW
) -> dict:
    """Current RS level, slope and the zone Bajaj's gate reads.

    ``zone`` is ``green`` only when RS is both positive **and** rising.
    A positive but falling RS is ``fading`` — outperformance that is being
    handed back — which his method treats as a warning rather than a pass.
    """
    series = rs_series(stock, index, window)
    usable = [v for v in series if v is not None]
    if len(usable) < SLOPE_WINDOW + 1:
        return {"rs": None, "slope": None, "zone": "unknown", "above_zero": None}

    current = usable[-1]
    slope = current - usable[-1 - SLOPE_WINDOW]

    if current > 0:
        zone = "green" if slope > -SLOPE_TOLERANCE else "fading"
    else:
        zone = "recovering" if slope > SLOPE_TOLERANCE else "red"

    return {
        "rs": round(current, 3),
        "slope": round(slope, 3),
        "zone": zone,
        "above_zero": current > 0,
        "window": window,
    }


def sector_rankings(
    symbols: list[str], adapter: DataAdapter, lookback_days: int = 504
) -> dict:
    """Rank sectors by the mean RS of their constituents.

    **A proxy, and a weak one.**  Bajaj ranks sectors using actual sector
    indices (Nifty Bank, Nifty IT and so on).  Here the only sector signal
    available is the holdings themselves, so a sector represented by one
    stock is ranked on that stock alone — which measures the stock, not the
    sector.  ``constituents`` is reported per sector precisely so a reader
    can discount a rank built on a sample of one.

    Wire real sector indices into ``DataAdapter`` before trusting this to
    gate entries.
    """
    index = adapter.benchmark(lookback_days)
    per_sector: dict[str, list[tuple[str, float]]] = {}

    for symbol in symbols:
        rs = relative_strength(adapter.prices(symbol, lookback_days), index)
        if rs["rs"] is None:
            continue
        per_sector.setdefault(adapter.sector(symbol), []).append((symbol, rs["rs"]))

    ranked = []
    for sector, members in per_sector.items():
        mean_rs = sum(v for _, v in members) / len(members)
        ranked.append(
            {
                "sector": sector,
                "mean_rs": round(mean_rs, 3),
                "constituents": len(members),
                "members": sorted(members, key=lambda m: m[1], reverse=True),
                "proxy_warning": len(members) < 3,
            }
        )
    ranked.sort(key=lambda r: r["mean_rs"], reverse=True)
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
        # "Leading" is the top half, as Bajaj's relative-strength screen implies.
        row["leading"] = position <= max(1, len(ranked) // 2)

    return {
        "ranked": ranked,
        "leading_sectors": [r["sector"] for r in ranked if r["leading"]],
        "basis": "mean RS of holdings in each sector (proxy for a sector index)",
    }
