"""Vivek Bajaj's techno-funda framework, implemented as gates.

The defining property, and the reason this is a separate strategy rather
than a tweak to the baseline scorer:

    **Gates, not sums.**

The baseline engine adds a technical score to a fundamental score, so a
superb business at a poor moment nets out positive and buys.  Bajaj
forbids exactly that — *"Never buy a stock that has strong fundamentals but
sits in the red zone for price momentum"* — because a great company without
price momentum is a narrative, not a trade.  Every gate must pass on its
own, and no amount of quality rescues dead momentum.

Implemented from the framework as described:

- market regime decides the deployment ceiling before any stock is read
- only leading sectors are eligible
- fundamental score >= 70 **and** momentum zone green
- entry only in the "strong zone", near highs, never into a falling knife
- stop fixed *before* entry; size derived from the rupee risk, not the other
  way round
- exit when RS < 0 **and** Supertrend is red; one alone is a hold
- double-yellow: fundamentals and momentum both poor -> exit

Three parts of the published framework are **not** implemented, because the
data to do so honestly is absent rather than because they were overlooked:

1. **Mother-Daughter entry timing.**  Needs 2-hour bars; this desk has daily
   data only.  Faking it on daily bars would produce an entry price that
   looks precise and means nothing.
2. **True sector-index ranking.**  Approximated from holdings' own RS; see
   ``relative_strength.sector_rankings``.
3. **Broad-market breadth.**  Computed over the portfolio, flagged
   unreliable, and ignored in the regime call below 50 names.
"""

from __future__ import annotations

from ..adapter import DataAdapter
from ..portfolio import CONCENTRATION_LIMIT
from ..backtest import replay_all
from ..indicators import rsi, snapshot
from ..relative_strength import relative_strength

#: Fundamental score a stock must clear to be buyable.
FUNDAMENTAL_GATE = 70.0

#: Below this, fundamentals count as "poor" for the double-yellow exit.
FUNDAMENTAL_POOR = 40.0

#: RSI floor confirming bullish momentum.
RSI_GATE = 50.0

#: Rupee risk per trade as a share of the book, by risk profile.
RISK_PER_TRADE = {"conservative": 0.005, "balanced": 0.01, "aggressive": 0.02}

#: Trim when a position exceeds its risk-derived size by more than this.
OVERSIZE_TOLERANCE = 1.5


def _band(value: float | None, low: float, high: float, invert: bool = False) -> float:
    """Map a raw metric onto 0-100, clamped. ``invert`` for lower-is-better."""
    if value is None:
        return 50.0            # absent data scores neutral, never favourable
    pct = (value - low) / (high - low) if high != low else 0.5
    pct = max(0.0, min(1.0, pct))
    return round((1 - pct if invert else pct) * 100, 1)


def fundamental_score(f: dict) -> dict:
    """Six-parameter 0-100 score, mirroring the StockEdge-style composite.

    Growth, profitability, efficiency, solvency, quality and valuation, each
    scored independently and averaged.  Missing inputs score 50 rather than
    0 — an absent figure is unknown, not bad, and scoring it as bad would
    silently reject every stock with a thin data feed.
    """
    if not f:
        return {"score": None, "components": {}, "note": "no fundamental data"}

    revenue = f.get("revenue_growth_3y_pct")
    profit = f.get("profit_growth_3y_pct")
    margin_trend = (
        profit - revenue if revenue is not None and profit is not None else None
    )
    pe, industry = f.get("pe"), f.get("industry_pe")
    relative_pe = (pe / industry) if pe and industry else None
    # `or 0.0` here would collapse *missing* into *zero* and hand a perfect
    # quality score to any company that simply discloses no pledge data —
    # the "absent data scores favourable" failure this module warns about.
    pledge = f.get("promoter_pledge_pct")

    components = {
        "growth": _band(profit, -10, 25),
        "profitability": _band(f.get("roe_pct"), 5, 25),
        # Profit growing faster than revenue means margins are expanding.
        "efficiency": _band(margin_trend, -10, 10),
        "solvency": _band(f.get("debt_to_equity"), 0.0, 1.5, invert=True),
        "quality": _band(pledge, 0.0, 15.0, invert=True),
        "valuation": _band(relative_pe, 0.6, 2.0, invert=True),
    }
    score = round(sum(components.values()) / len(components), 1)
    return {"score": score, "components": components}


def momentum_zone(bars, index_bars) -> dict:
    """Green only when RS is positive and rising **and** RSI clears 50.

    Both conditions, because each catches a different failure: RS says the
    stock is beating the index, RSI says it is rising at all.  A stock can
    outperform a falling index while still falling.
    """
    rs = relative_strength(bars, index_bars)
    rsi14 = rsi([b.close for b in bars])
    passes = rs["zone"] == "green" and rsi14 is not None and rsi14 > RSI_GATE

    if passes:
        zone = "green"
    elif rs["above_zero"] is False and (rsi14 or 0) <= RSI_GATE:
        zone = "red"
    else:
        zone = "amber"

    return {
        "zone": zone,
        "rs": rs["rs"],
        "rs_slope": rs["slope"],
        "rs_zone": rs["zone"],
        "rsi_14": round(rsi14, 1) if rsi14 is not None else None,
        "passes_gate": passes,
    }


def position_size(
    entry: float, stop: float, portfolio_value: float, risk_profile: str
) -> dict:
    """Bajaj's sizing math, with both capital rules applied.

    Rule 4, *Fix the Risk*: ``shares = rupee risk / (entry - stop)``. Size is
    derived from the risk, never the other way round — a wide stop does not
    mean a wider loss, it means fewer shares.

    Rule 5, *Respect the Capital*: the result is then capped at
    ``CONCENTRATION_LIMIT`` of the book.

    **Both rules are needed, and applying rule 4 alone is dangerous.** They
    bound different things — rule 4 bounds the loss, rule 5 bounds the
    position — and they diverge exactly where a stop is tight. A stop ₹3
    below a ₹223 share divides a ₹10,550 risk budget into 3,049 shares,
    which is 64% of the book riding on one name. The loss is still bounded
    at 1%, so rule 4 is satisfied and the position is still absurd. When the
    cap binds it is reported, because a capped position carries less risk
    than requested and the reader should know the stop drove it.
    """
    risk_pct = RISK_PER_TRADE.get(risk_profile, 0.01)
    rupee_risk = portfolio_value * risk_pct
    distance = entry - stop
    if distance <= 0:
        return {
            "shares": 0,
            "rupee_risk": round(rupee_risk, 2),
            "note": "stop is at or above entry — no valid position",
        }

    risk_shares = int(rupee_risk / distance)
    cap_shares = int(portfolio_value * CONCENTRATION_LIMIT / entry) if entry else 0
    shares = min(risk_shares, cap_shares)
    capped = shares < risk_shares

    return {
        "shares": shares,
        "risk_based_shares": risk_shares,
        "cap_shares": cap_shares,
        "capped_by_concentration": capped,
        "rupee_risk": round(rupee_risk, 2),
        "effective_risk": round(shares * distance, 2),
        "risk_pct_of_book": risk_pct * 100,
        "stop_distance": round(distance, 2),
        "position_value": round(shares * entry, 2),
        "position_pct_of_book": round(shares * entry / portfolio_value * 100, 2)
        if portfolio_value
        else None,
        "cap_note": (
            f"risk sizing wanted {risk_shares} shares ({risk_shares * entry / portfolio_value * 100:.0f}% "
            f"of the book) because the stop is only {distance:.2f} away; "
            f"capped at {CONCENTRATION_LIMIT * 100:.0f}%"
            if capped
            else None
        ),
    }


def exit_signal(momentum: dict, snap: dict, fscore: float | None) -> dict:
    """Bajaj's exit logic. Two independent triggers, each with its own rule.

    **Technical exit needs BOTH to fail.** RS below zero *and* Supertrend
    red. One alone is a hold — a deliberate tolerance for noise, and the
    rule most often broken by investors who exit on the first red candle.

    **Double-yellow is separate.** Fundamentals poor *and* momentum poor
    means the thesis is gone, not that the chart wobbled.
    """
    st = (snap.get("supertrend") or {}).get("direction")
    rs_negative = momentum["rs"] is not None and momentum["rs"] < 0
    st_red = st == "red"

    technical_exit = rs_negative and st_red
    double_yellow = (
        fscore is not None and fscore < FUNDAMENTAL_POOR and momentum["zone"] == "red"
    )

    triggers = []
    if rs_negative:
        triggers.append(f"RS {momentum['rs']} below zero")
    if st_red:
        triggers.append("Supertrend red")
    if double_yellow:
        triggers.append(f"double-yellow: fundamental {fscore} and momentum red")

    return {
        "exit": technical_exit or double_yellow,
        "technical_exit": technical_exit,
        "double_yellow": double_yellow,
        "rs_negative": rs_negative,
        "supertrend_red": st_red,
        "triggers": triggers,
        "rule": (
            "both technical signals negative"
            if technical_exit
            else (
                "fundamentals and momentum both poor"
                if double_yellow
                else "fewer than two signals negative — hold"
            )
        ),
    }


def entry_checklist(
    symbol: str,
    momentum: dict,
    fscore: float | None,
    snap: dict,
    context: dict,
) -> dict:
    """The six rules that must all pass before any capital is committed."""
    regime = context.get("regime", {})
    rankings = context.get("sector_rankings", {})
    sector = context.get("sector", "Unknown")
    zone = snap.get("strong_zone") or {}

    checks = [
        {
            "rule": "1. Market regime",
            "pass": regime.get("regime") in ("bullish", "volatile"),
            "detail": f"regime {regime.get('regime')}, deployment ceiling "
                      f"{int((regime.get('deployment_ceiling') or 0) * 100)}%",
        },
        {
            "rule": "2. Sector ranking",
            "pass": sector in rankings.get("leading_sectors", []),
            "detail": f"{sector} "
                      f"{'is' if sector in rankings.get('leading_sectors', []) else 'is not'}"
                      f" a leading sector",
        },
        {
            "rule": "3. Fundamental gate",
            "pass": fscore is not None and fscore >= FUNDAMENTAL_GATE,
            "detail": f"fundamental score {fscore}/100 (gate {FUNDAMENTAL_GATE})",
        },
        {
            "rule": "4. Momentum gate",
            "pass": momentum["passes_gate"],
            "detail": f"RS {momentum['rs']} ({momentum['rs_zone']}), "
                      f"RSI {momentum['rsi_14']}",
        },
        {
            "rule": "5. Strong zone",
            "pass": bool(zone.get("in_zone")),
            "detail": f"{(zone.get('pct_from_high') or 0) * 100:.1f}% from the "
                      f"52-week high"
                      + (" (at all-time high)" if zone.get("at_ath") else ""),
        },
        {
            "rule": "6. Stop defined before entry",
            "pass": context.get("stop") is not None,
            "detail": f"stop {context.get('stop')}",
        },
    ]
    failed = [c["rule"] for c in checks if not c["pass"]]
    return {"checks": checks, "all_pass": not failed, "failed": failed}


def evaluate(
    symbol: str,
    adapter: DataAdapter,
    horizon: str = "positional",
    risk_profile: str = "balanced",
    avg_cost: float | None = None,
    lookback_days: int = 504,
    context: dict | None = None,
) -> dict:
    """Produce a Bajaj-framework verdict for one symbol.

    Returns the same shape as the baseline engine so the report renderer and
    action queue consume either without caring which produced it, plus a
    ``bajaj`` block carrying the gate detail.
    """
    context = dict(context or {})
    bars = adapter.prices(symbol, lookback_days)
    index_bars = adapter.benchmark(lookback_days)
    snap = snapshot(bars)
    last = snap["last_close"]

    fund = fundamental_score(adapter.fundamentals(symbol))
    fscore = fund["score"]
    momentum = momentum_zone(bars, index_bars)

    # Stop comes from Supertrend when it is supportive, ATR otherwise.  Rule 3
    # requires a stop to exist *before* the entry decision, so it is computed
    # here rather than attached to a buy afterwards.
    st = snap.get("supertrend") or {}
    atr14 = snap.get("atr_14")
    if st.get("direction") == "green" and st.get("level") and st["level"] < last:
        stop, stop_basis = st["level"], "Supertrend level"
    elif atr14:
        stop, stop_basis = round(last - 2.5 * atr14, 2), f"2.5x ATR({round(atr14, 2)})"
    else:
        stop, stop_basis = None, None

    context.setdefault("sector", adapter.sector(symbol))
    context["stop"] = stop

    checklist = entry_checklist(symbol, momentum, fscore, snap, context)
    exits = exit_signal(momentum, snap, fscore)

    portfolio_value = context.get("portfolio_value") or 0.0
    sizing = (
        position_size(last, stop, portfolio_value, risk_profile)
        if stop and portfolio_value
        else None
    )

    pnl_pct = ((last - avg_cost) / avg_cost * 100) if avg_cost else None
    action, reasons = _decide(
        checklist, exits, sizing, context, avg_cost, last, pnl_pct, momentum, fscore
    )

    setups = replay_all(bars, horizon, risk_profile)
    usable = [s for s in setups.values() if s.get("sufficient")]
    best = max(usable, key=lambda s: s["expectancy"], default=None)

    return {
        "symbol": symbol,
        "engine": "rules",
        "strategy": "bajaj",
        "action": action,
        "confidence": _confidence(checklist, exits),
        "reasons": reasons,
        "last_close": last,
        "avg_cost": avg_cost,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "stop": stop,
        "stop_basis": stop_basis,
        "technical": snap,
        "bajaj": {
            "fundamental": fund,
            "momentum": momentum,
            "entry_checklist": checklist,
            "exit_signal": exits,
            "position_sizing": sizing,
            "regime": context.get("regime", {}).get("regime"),
            "sector": context["sector"],
        },
        "backtest": {
            "best_supported_setup": best["setup"] if best else None,
            "evidence": best,
            "all_setups": setups,
        },
        "horizon": horizon,
        "risk_profile": risk_profile,
    }


def _decide(
    checklist, exits, sizing, context, avg_cost, last, pnl_pct, momentum, fscore
) -> tuple[str, list[str]]:
    """Map gates and exit triggers to an action for an existing holding."""
    reasons: list[str] = []

    if exits["exit"]:
        reasons.append(f"EXIT — {exits['rule']}: {'; '.join(exits['triggers'])}")
        return "exit", reasons

    # Rule 5, Respect the Capital: a position far larger than its risk-derived
    # size is a sizing failure regardless of how good the stock looks.
    held_qty = context.get("held_qty")
    if sizing and held_qty and sizing["shares"]:
        if held_qty > sizing["shares"] * OVERSIZE_TOLERANCE:
            reasons.append(
                f"TRIM — holding {int(held_qty)} shares against a risk-derived size of "
                f"{sizing['shares']} ({sizing['risk_pct_of_book']}% of book at risk); "
                f"oversized by {held_qty / sizing['shares']:.1f}x"
            )
            return "trim", reasons

    if checklist["all_pass"]:
        reasons.append(
            f"BUY — all six entry rules pass (fundamental {fscore}/100, "
            f"RS {momentum['rs']}, momentum green, in the strong zone)"
        )
        if sizing:
            reasons.append(
                f"size {sizing['shares']} shares, risking "
                f"₹{sizing['effective_risk']:,.0f} at the stop"
            )
            if sizing.get("cap_note"):
                reasons.append(sizing["cap_note"])
        return "accumulate" if avg_cost else "buy", reasons

    reasons.append(
        f"HOLD — no exit triggered, but {len(checklist['failed'])} entry rule(s) fail: "
        + ", ".join(checklist["failed"])
    )
    if exits["triggers"]:
        reasons.append("watch: " + "; ".join(exits["triggers"]))
    # Bajaj's explicit tolerance: sit through a structural decline while the
    # fundamentals hold, rather than selling into fear.
    if pnl_pct is not None and pnl_pct < -10 and (fscore or 0) >= FUNDAMENTAL_GATE:
        reasons.append(
            f"down {pnl_pct:.0f}% but fundamentals remain green ({fscore}/100) — "
            "the framework expects this to be sat through, not panic-sold"
        )
    return "hold", reasons


def _confidence(checklist, exits) -> float:
    passed = sum(1 for c in checklist["checks"] if c["pass"])
    base = passed / len(checklist["checks"])
    if exits["exit"]:
        # A both-signals exit is the framework's highest-conviction call.
        return 0.8 if exits["technical_exit"] and exits["double_yellow"] else 0.7
    return round(base, 2)


#: Holding-count bands. Bajaj gives two anchors — 10-15 names on ₹5-10L and
#: 20-25 on "large capital" — so the middle band is interpolated between them.
COUNT_BANDS = [
    (1_000_000, (10, 15), "limited capital (up to ₹10L)"),
    (2_500_000, (15, 20), "mid capital (₹10L-₹25L)"),
    (float("inf"), (20, 25), "large capital (above ₹25L)"),
]

#: Share of the book Bajaj wants in names strong on BOTH legs.
CORE_TARGET = (0.50, 0.60)


def portfolio_construction(verdicts: dict, book: dict) -> dict:
    """Check the book against Bajaj's construction rules.

    Two rules, both about structure rather than any individual stock:
    hold a number of names matched to capital, and keep 50-60% of the book
    in *core* positions — strong fundamentals **and** strong momentum, the
    same dual test the entry gate applies.
    """
    value = book["totals"]["market_value"]
    count = book["totals"]["holdings"]
    weights = book["weights"]

    band, label = next(
        (rng, lbl) for ceiling, rng, lbl in COUNT_BANDS if value <= ceiling
    )
    low, high = band

    core, core_weight = [], 0.0
    for symbol, verdict in verdicts.items():
        detail = verdict.get("bajaj") or {}
        fscore = (detail.get("fundamental") or {}).get("score")
        zone = (detail.get("momentum") or {}).get("zone")
        if fscore is not None and fscore >= FUNDAMENTAL_GATE and zone == "green":
            core.append(symbol)
            core_weight += weights.get(symbol, 0.0)

    issues = []
    if count < low:
        issues.append(
            f"holding {count} names on ₹{value:,.0f} — {label} calls for {low}-{high}"
        )
    elif count > high:
        issues.append(
            f"holding {count} names on ₹{value:,.0f} — {label} calls for {low}-{high}; "
            "this is more positions than can be reviewed properly"
        )
    if core_weight < CORE_TARGET[0]:
        issues.append(
            f"core allocation {core_weight * 100:.0f}% against a {CORE_TARGET[0] * 100:.0f}-"
            f"{CORE_TARGET[1] * 100:.0f}% target — too little of the book is in names "
            "strong on both fundamentals and momentum"
        )

    return {
        "holdings": count,
        "capital_band": label,
        "target_range": list(band),
        "count_ok": low <= count <= high,
        "core_symbols": sorted(core),
        "core_weight_pct": round(core_weight * 100, 1),
        "core_target_pct": [CORE_TARGET[0] * 100, CORE_TARGET[1] * 100],
        "core_ok": CORE_TARGET[0] <= core_weight <= CORE_TARGET[1],
        "issues": issues,
    }
