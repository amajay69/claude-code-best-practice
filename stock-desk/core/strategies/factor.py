"""Factor-model strategy: rank the book on value, quality, momentum, low-vol.

This strategy is shaped differently from the other two, and the difference
is the reason it was worth building.

``baseline`` and ``bajaj`` both judge a stock against **absolute**
criteria — a score threshold, a gate. Either can be computed for one stock
in isolation. A factor model cannot: a stock's value score is its position
relative to the others, so the whole book must be read before any single
verdict exists. That is why this module needs a prepared context and could
not be bolted onto a per-symbol interface.

**It also cannot, on its own, say a stock is bad.**

Standardising across ten holdings guarantees a bottom quintile even if all
ten are excellent, and a top quintile even if all ten are dreadful. A pure
rank-to-action mapping would therefore recommend selling something every
single run, forever — turnover manufactured by arithmetic rather than
discovered in the data.

So ranks are paired with **absolute floors**. A low rank alone is a trim at
most; an exit needs the rank *and* genuinely poor raw values. The rank says
"worst of what you own"; the floors say "bad in its own right". Both are
required before the strategy will tell anyone to sell.
"""

from __future__ import annotations

from ..adapter import DataAdapter
from ..backtest import replay_all
from ..factors import DEFAULT_WEIGHTS, book_tilt, factor_model
from ..indicators import snapshot

#: Composite z above which a holding is a candidate to add to.
TOP_Z = 0.40

#: Composite z below which a holding is a candidate to reduce.
BOTTOM_Z = -0.30

#: Absolute floors — "bad in its own right", independent of rank.
FLOORS = {
    "momentum": 0.0,      # 12-1 return below zero: lost money over the year
    "quality": 0.0,       # blended quality score below zero
    "value": 0.02,        # earnings yield under 2% (PE above 50)
}

#: Absolute floors that must fail before a bottom-ranked name is exited.
FLOORS_FOR_EXIT = 2


def build_context(
    symbols: list[str], adapter: DataAdapter, book: dict, **_: object
) -> dict:
    """Cross-sectional pass. Must run before any symbol can be evaluated."""
    model = factor_model(symbols, adapter)
    return {
        "factor_model": model,
        "book_tilt": book_tilt(model, book.get("weights", {})),
    }


def failed_floors(raw: dict) -> list[str]:
    """Which absolute floors this stock fails, ignoring its rank entirely."""
    failures = []
    for factor, floor in FLOORS.items():
        value = raw.get(factor)
        if value is not None and value < floor:
            failures.append(factor)
    return failures


def evaluate(
    symbol: str,
    adapter: DataAdapter,
    horizon: str = "positional",
    risk_profile: str = "balanced",
    avg_cost: float | None = None,
    lookback_days: int = 504,
    context: dict | None = None,
) -> dict:
    """Produce a factor verdict for one symbol, given the book-wide context."""
    context = context or {}
    model = context.get("factor_model")
    if not model:
        raise ValueError(
            "factor strategy requires a prepared context: call build_context() "
            "over the whole book first. A factor score is a relative position, "
            "so it cannot be computed for one symbol in isolation."
        )

    bars = adapter.prices(symbol, lookback_days)
    snap = snapshot(bars)
    last = snap["last_close"]

    z = model["z"][symbol]
    composite = model["composite"][symbol]
    rank = model["ranks"][symbol]
    raw = model["raw"][symbol]
    floors = failed_floors(raw)

    action, reasons = _decide(symbol, composite, rank, model, floors, z)

    atr14 = snap.get("atr_14")
    stop = round(last - 2.5 * atr14, 2) if atr14 and last else None
    pnl_pct = ((last - avg_cost) / avg_cost * 100) if avg_cost else None

    setups = replay_all(bars, horizon, risk_profile)
    usable = [s for s in setups.values() if s.get("sufficient")]
    best = max(usable, key=lambda s: s["expectancy"], default=None)

    return {
        "symbol": symbol,
        "engine": "rules",
        "strategy": "factor",
        "action": action,
        "confidence": _confidence(composite, floors, model),
        "reasons": reasons,
        "last_close": last,
        "avg_cost": avg_cost,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "stop": stop,
        "stop_basis": f"2.5x ATR({round(atr14, 2)})" if atr14 else None,
        "technical": snap,
        "factor": {
            "composite_z": composite,
            "rank": rank,
            "of": model["universe_size"],
            "z": z,
            "raw": raw,
            "failed_floors": floors,
            "within_book_only": True,
            "reliable": model["reliable"],
        },
        "backtest": {
            "best_supported_setup": best["setup"] if best else None,
            "evidence": best,
            "all_setups": setups,
        },
        "horizon": horizon,
        "risk_profile": risk_profile,
    }


def _strongest(z: dict) -> tuple[str, float]:
    factor = max(z, key=lambda f: abs(z[f]))
    return factor, z[factor]


def _decide(symbol, composite, rank, model, floors, z) -> tuple[str, list[str]]:
    total = model["universe_size"]
    lead_factor, lead_z = _strongest(z)
    reasons: list[str] = []
    position = f"rank {rank}/{total} on the composite (z {composite:+.2f})"

    if composite <= BOTTOM_Z and len(floors) >= FLOORS_FOR_EXIT:
        reasons.append(
            f"EXIT — {position}, and it fails {len(floors)} absolute floors "
            f"({', '.join(floors)}). Weakest in the book *and* weak in its own right."
        )
        return "exit", reasons

    if composite <= BOTTOM_Z:
        reasons.append(
            f"TRIM — {position}. "
            + (
                f"Fails the {floors[0]} floor."
                if floors
                else "Passes every absolute floor, so this is a relative call only: "
                     "it is the weakest thing you own, not necessarily a weak stock."
            )
        )
        return "trim", reasons

    if composite >= TOP_Z:
        if floors:
            reasons.append(
                f"HOLD — {position} but fails the {', '.join(floors)} floor. "
                "Ranking well among your holdings is not a reason to add to "
                "something failing on its own terms."
            )
            return "hold", reasons
        reasons.append(
            f"ACCUMULATE — {position}, driven by {lead_factor} (z {lead_z:+.2f}), "
            "and clears every absolute floor."
        )
        return "accumulate", reasons

    reasons.append(f"HOLD — {position}, mid-book on every factor.")
    if floors:
        reasons.append(f"watch: fails the {', '.join(floors)} floor")
    return "hold", reasons


def _confidence(composite: float, floors: list[str], model: dict) -> float:
    """Conviction scales with the z-score, then is halved on a tiny universe.

    Ten-name cross-sectional statistics do not support confident calls, and
    reporting a rank from them at full conviction would be the clearest
    possible way to mislead a reader.
    """
    base = min(abs(composite) / 1.5, 1.0)
    if floors:
        base = min(base + 0.15, 1.0)
    if not model["reliable"]:
        base *= 0.5
    return round(base, 2)


def render_sections(analysis: dict) -> str:
    """Factor tables appended to the report card."""
    ctx = analysis.get("market_context") or {}
    model = ctx.get("factor_model")
    if not model:
        return ""
    tilt = ctx.get("book_tilt") or {}
    lines = ["", "## Factor model", ""]

    if model.get("caveat"):
        lines += [f"> ⚠ **{model['caveat']}**", ""]

    lines += [
        f"Weights: " + ", ".join(f"{k} {v:.0%}" for k, v in model["weights"].items()),
        "",
        "| Rank | Symbol | Value | Quality | Momentum | Low-vol | Composite | Floors failed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for symbol in model["ordered"]:
        z = model["z"][symbol]
        floors = failed_floors(model["raw"][symbol])
        lines.append(
            f"| {model['ranks'][symbol]} | {symbol} | {z['value']:+.2f} | "
            f"{z['quality']:+.2f} | {z['momentum']:+.2f} | {z['low_vol']:+.2f} | "
            f"**{model['composite'][symbol]:+.2f}** | "
            f"{', '.join(floors) if floors else '—'} |"
        )

    lines += [
        "",
        "_z-scores are standardised across these holdings only. A positive score "
        "means better than the rest of your book — not good in absolute terms. "
        "Absolute floors are the separate check that can say a stock is weak "
        "on its own merits._",
        "",
    ]

    if tilt:
        lines += [
            "### Allocation tilt",
            "",
            "| Factor | Weighted exposure |",
            "| --- | --- |",
        ]
        for factor in DEFAULT_WEIGHTS:
            lines.append(f"| {factor} | {tilt['by_factor'][factor]:+.3f} |")
        lines += [
            "",
            f"Dominant: **{tilt['dominant_factor']}** "
            f"({tilt['dominant_exposure']:+.3f}). "
            f"{tilt.get('basis', '')}.",
            "",
        ]
    return "\n".join(lines)
