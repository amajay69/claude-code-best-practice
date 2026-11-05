"""Cross-sectional factor exposures: value, quality, momentum, low-volatility.

This module is structurally different from everything else in ``core/``.
Every other measure here is a property of one stock computed from its own
data.  A factor score is not: it is a stock's **position relative to the
others**, so nothing can be scored until the whole book has been read.

**The within-book trap, which matters more than the maths.**

Academic factor models rank across hundreds or thousands of names, where
"top decile value" means genuinely cheap.  Ranking across the ten stocks a
person happens to own means something else entirely: it identifies which of
*their* holdings is cheapest, and says nothing about whether any of them is
cheap.  Standardisation guarantees a top and a bottom quintile even in a
book of ten uniformly terrible stocks — the spread is manufactured by the
arithmetic, not discovered in the data.

Two consequences the code enforces rather than merely documents:

* every output carries ``within_book_only: True``
* raw values travel alongside z-scores, so an absolute reading stays
  available to anyone who wants one

With a universe this small the standard deviation is also unstable — one
outlier moves every other z-score — so ``reliable`` is false below 30
names.
"""

from __future__ import annotations

import math

from .adapter import DataAdapter
from .indicators import annualised_vol, closes

#: Below this many names, cross-sectional standardisation is noise.
MIN_UNIVERSE = 30

#: Classic 12-1 momentum: one year of return, skipping the most recent month
#: to avoid picking up short-term reversal.
MOMENTUM_LOOKBACK = 252
MOMENTUM_SKIP = 21

#: Default factor weights for the composite. Equal-weighted: there is no
#: evidence in this codebase to justify tilting one factor over another, and
#: inventing weights would dress a guess as a model.
DEFAULT_WEIGHTS = {"value": 0.25, "quality": 0.25, "momentum": 0.25, "low_vol": 0.25}


def _earnings_yield(f: dict) -> float | None:
    pe = f.get("pe")
    return (1 / pe) if pe and pe > 0 else None


def _quality_raw(f: dict) -> float | None:
    """Blend ROE, leverage and profit growth into one pre-standardised number."""
    roe, de, growth = (
        f.get("roe_pct"),
        f.get("debt_to_equity"),
        f.get("profit_growth_3y_pct"),
    )
    parts = []
    if roe is not None:
        parts.append(roe)
    if de is not None:
        parts.append(-de * 10)        # scale leverage onto a comparable range
    if growth is not None:
        parts.append(growth)
    return sum(parts) / len(parts) if parts else None


def _momentum_raw(bars) -> float | None:
    """12-1 return: t-252 to t-21, as a fraction."""
    px = closes(bars)
    if len(px) < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
        return None
    start = px[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]
    end = px[-MOMENTUM_SKIP]
    return (end - start) / start if start else None


def _low_vol_raw(bars) -> float | None:
    vol = annualised_vol(closes(bars))
    return -vol if vol is not None else None   # higher is better, so negate


def raw_factors(symbols: list[str], adapter: DataAdapter, lookback_days: int = 504) -> dict:
    """Per-symbol raw factor values, before any standardisation."""
    out = {}
    for symbol in symbols:
        bars = adapter.prices(symbol, lookback_days)
        f = adapter.fundamentals(symbol)
        out[symbol] = {
            "value": _earnings_yield(f),
            "quality": _quality_raw(f),
            "momentum": _momentum_raw(bars),
            "low_vol": _low_vol_raw(bars),
        }
    return out


def _zscores(values: dict[str, float | None]) -> tuple[dict[str, float], dict]:
    """Standardise one factor across the book.

    A symbol with no data scores 0 — the cross-sectional mean — rather than
    being dropped or scored badly. Dropping it would silently change the
    universe the other z-scores are measured against.
    """
    present = {s: v for s, v in values.items() if v is not None}
    if len(present) < 2:
        return {s: 0.0 for s in values}, {"mean": None, "stdev": None, "n": len(present)}

    mean = sum(present.values()) / len(present)
    var = sum((v - mean) ** 2 for v in present.values()) / (len(present) - 1)
    stdev = math.sqrt(var)

    if stdev == 0:
        # Every name identical on this factor: it carries no information,
        # and dividing by zero would manufacture infinite conviction.
        return {s: 0.0 for s in values}, {"mean": mean, "stdev": 0.0, "n": len(present),
                                          "note": "no dispersion; factor ignored"}

    scores = {s: ((present[s] - mean) / stdev if s in present else 0.0) for s in values}
    return (
        {s: round(v, 3) for s, v in scores.items()},
        {"mean": round(mean, 4), "stdev": round(stdev, 4), "n": len(present)},
    )


def factor_model(
    symbols: list[str],
    adapter: DataAdapter,
    weights: dict[str, float] | None = None,
    lookback_days: int = 504,
) -> dict:
    """Standardise every factor across the book and build the composite."""
    weights = weights or DEFAULT_WEIGHTS
    raw = raw_factors(symbols, adapter, lookback_days)
    names = list(DEFAULT_WEIGHTS)

    z: dict[str, dict[str, float]] = {s: {} for s in symbols}
    stats = {}
    for factor in names:
        scores, meta = _zscores({s: raw[s][factor] for s in symbols})
        stats[factor] = meta
        for symbol, value in scores.items():
            z[symbol][factor] = value

    composite = {
        s: round(sum(z[s][f] * weights.get(f, 0.0) for f in names), 3) for s in symbols
    }
    ordered = sorted(composite, key=lambda s: composite[s], reverse=True)
    ranks = {s: i + 1 for i, s in enumerate(ordered)}

    return {
        "weights": weights,
        "raw": raw,
        "z": z,
        "composite": composite,
        "ranks": ranks,
        "ordered": ordered,
        "stats": stats,
        "universe_size": len(symbols),
        "reliable": len(symbols) >= MIN_UNIVERSE,
        "within_book_only": True,
        "caveat": (
            None
            if len(symbols) >= MIN_UNIVERSE
            else (
                f"z-scores computed across only {len(symbols)} holdings. These are "
                "ranks WITHIN your own book, not against the market: a top-ranked "
                "name here is your cheapest/best holding, not a cheap or good one. "
                "Standardisation produces a top and bottom quintile even if every "
                "holding is poor."
            )
        ),
    }


def book_tilt(model: dict, weights_by_symbol: dict[str, float]) -> dict:
    """What the *allocation* tilts the book toward.

    Weighted-average z-score per factor.  Because z-scores are standardised
    across the same book, their equal-weighted mean is zero by construction
    — so the weighted exposure **is** the tilt the position sizing creates,
    with no baseline to subtract.  Reporting a separate "allocation tilt"
    would print the same number twice and imply two findings where there is
    one.

    A positive momentum exposure therefore means: the names carrying the
    most weight are the higher-momentum ones *within this book*. It says
    nothing about whether they have momentum in absolute terms.
    """
    symbols = list(model["z"])
    if not symbols:
        return {}
    tilts = {
        factor: round(
            sum(weights_by_symbol.get(s, 0.0) * model["z"][s][factor] for s in symbols), 3
        )
        for factor in DEFAULT_WEIGHTS
    }
    strongest = max(tilts, key=lambda f: abs(tilts[f]))
    return {
        "by_factor": tilts,
        "dominant_factor": strongest,
        "dominant_exposure": tilts[strongest],
        "basis": "weighted mean z-score; equal-weight baseline is 0 by construction",
        "within_book_only": True,
    }
