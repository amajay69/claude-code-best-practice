"""Deterministic per-stock verdict — the amber path, and the agents' facts.

This module does two jobs on purpose:

1. **Fallback.**  When no model is reachable, the desk still produces a
   verdict, badged ``rules`` instead of ``llm``.  The badge is part of the
   output object, not a UI flourish: a reader must never mistake a
   rules-only answer for the full pipeline's.

2. **Fact sheet.**  When the model *is* reachable, this same computation is
   what the specialist agents read.  Agents interpret numbers; they never
   compute them.  That keeps two runs of the same portfolio agreeing on the
   facts even when they disagree on the call.
"""

from __future__ import annotations

from .adapter import Bar, DataAdapter
from .backtest import STOP_ATR, replay_all
from .indicators import snapshot

ACTIONS = ("exit", "trim", "hold", "accumulate", "buy")


def technical_view(bars: list[Bar]) -> dict:
    """Score price action from -3 (hostile) to +3 (supportive)."""
    snap = snapshot(bars)
    score, reasons = 0, []

    if snap["trend"] == "uptrend":
        score += 2
        reasons.append("50-DMA above 200-DMA: trend is up")
    elif snap["trend"] == "downtrend":
        score -= 2
        reasons.append("50-DMA below 200-DMA: trend is down")
    else:
        reasons.append("moving averages entangled: no clear trend")

    rsi = snap["rsi_14"]
    if rsi is not None:
        if rsi < 30:
            score += 1
            reasons.append(f"RSI {rsi:.0f}: oversold")
        elif rsi > 70:
            score -= 1
            reasons.append(f"RSI {rsi:.0f}: overbought")

    off_high = snap["pct_from_52w_high"]
    if off_high is not None and off_high < -0.25:
        score -= 1
        reasons.append(f"{off_high * 100:.0f}% below its 52-week high")

    return {"score": score, "reasons": reasons, "snapshot": snap}


def fundamental_view(f: dict) -> dict:
    """Score the business from -3 (poor) to +3 (strong)."""
    if not f:
        return {"score": 0, "reasons": ["no fundamental data available"]}
    score, reasons = 0, []

    pe, ind = f.get("pe"), f.get("industry_pe")
    if pe and ind:
        if pe < ind * 0.8:
            score += 1
            reasons.append(f"PE {pe} below industry {ind}")
        elif pe > ind * 1.3:
            score -= 1
            reasons.append(f"PE {pe} above industry {ind}")

    roe = f.get("roe_pct")
    if roe is not None:
        if roe >= 18:
            score += 1
            reasons.append(f"ROE {roe}%: strong returns on capital")
        elif roe < 10:
            score -= 1
            reasons.append(f"ROE {roe}%: weak returns on capital")

    de = f.get("debt_to_equity")
    if de is not None:
        if de > 1.2:
            score -= 1
            reasons.append(f"debt/equity {de}: leveraged")
        elif de < 0.3:
            score += 1
            reasons.append(f"debt/equity {de}: lightly geared")

    growth = f.get("profit_growth_3y_pct")
    if growth is not None:
        if growth >= 15:
            score += 1
            reasons.append(f"profit growth {growth}% over 3y")
        elif growth < 0:
            score -= 1
            reasons.append(f"profit shrinking {growth}% over 3y")

    pledge = f.get("promoter_pledge_pct")
    if pledge:
        score -= 1
        reasons.append(f"promoter pledge {pledge}%: governance flag")

    return {"score": max(-3, min(3, score)), "reasons": reasons}


#: Below this loss, adding to a position needs more than a favourable score.
DEEP_LOSS_PCT = -25.0


def _action(total: float) -> str:
    """Map a combined score to one of the five allowed actions."""
    if total <= -3:
        return "exit"
    if total <= -1:
        return "trim"
    if total >= 3:
        return "buy"
    if total >= 1:
        return "accumulate"
    return "hold"


def _guard_averaging_down(
    action: str, pnl_pct: float | None, evidence: dict | None
) -> tuple[str, str | None]:
    """Refuse to add to a deeply losing position on score alone.

    Averaging down into a falling holding is the most expensive habit this
    tool exists to interrupt, and a favourable *current* signal is exactly
    what makes it feel justified at the time.  So adding to a position more
    than 25% underwater requires the one check that does not share the
    model's priors: this stock's own history must support the setup with
    enough independent samples to mean anything.  Otherwise the call is
    capped at hold — never reversed to a sell, which would be the same
    overconfidence pointing the other way.
    """
    if action not in ("accumulate", "buy"):
        return action, None
    if pnl_pct is None or pnl_pct > DEEP_LOSS_PCT:
        return action, None
    if evidence and evidence.get("sufficient") and evidence.get("expectancy", 0) > 0:
        return action, (
            f"adding to a {pnl_pct:.0f}% loser, supported by {evidence['samples']} "
            f"historical samples of '{evidence['setup']}'"
        )
    return "hold", (
        f"signal favours adding, but the position is {pnl_pct:.0f}% underwater and "
        f"no setup cleared the evidence bar — capped at hold rather than averaging down"
    )


def evaluate(
    symbol: str,
    adapter: DataAdapter,
    horizon: str = "positional",
    risk_profile: str = "balanced",
    avg_cost: float | None = None,
    lookback_days: int = 504,
) -> dict:
    """Produce a complete rules-based verdict for one symbol."""
    bars = adapter.prices(symbol, lookback_days)
    tech = technical_view(bars)
    fund = fundamental_view(adapter.fundamentals(symbol))
    snap = tech["snapshot"]
    last = snap["last_close"]

    pnl_pct = ((last - avg_cost) / avg_cost * 100) if avg_cost else None
    total = tech["score"] + fund["score"]

    atr14 = snap["atr_14"]
    stop_mult = STOP_ATR.get(risk_profile, 2.5)
    stop = round(last - stop_mult * atr14, 2) if atr14 and last else None

    # Score every setup, then name the one this stock has actually rewarded.
    setups = replay_all(bars, horizon, risk_profile)
    usable = [s for s in setups.values() if s.get("sufficient")]
    best = max(usable, key=lambda s: s["expectancy"], default=None)

    action, guard_note = _guard_averaging_down(_action(total), pnl_pct, best)
    reasons = tech["reasons"] + fund["reasons"]
    if guard_note:
        reasons.insert(0, guard_note)

    return {
        "symbol": symbol,
        "engine": "rules",          # the amber badge
        "action": action,
        "confidence": min(1.0, abs(total) / 6),
        "score": {"technical": tech["score"], "fundamental": fund["score"], "total": total},
        "reasons": reasons,
        "guard": guard_note,
        "last_close": last,
        "avg_cost": avg_cost,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "stop": stop,
        "stop_basis": f"{stop_mult}x ATR({round(atr14, 2)})" if atr14 else None,
        "technical": snap,
        "backtest": {
            "best_supported_setup": best["setup"] if best else None,
            "evidence": best,
            "all_setups": setups,
            "note": (
                None
                if best
                else "no setup cleared the 10-sample bar; treat history as colour, not evidence"
            ),
        },
        "horizon": horizon,
        "risk_profile": risk_profile,
    }
