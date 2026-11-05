"""Market regime: the umbrella filter that runs before any stock is judged.

Bajaj's first rule is that you do not assess a stock before you assess the
weather it trades in, and that the regime sets *how much capital deploys at
all* rather than merely colouring the commentary.  A good setup in a bearish
tape is still a bad trade.

Regime drives a deployment ceiling:

| Regime   | Deployment | Reading |
| -------- | ---------- | ------- |
| bullish  | 100%       | trade the plan at full size |
| volatile | 50%        | half size; the tape is undecided |
| bearish  | 25%        | survival mode; new risk is a luxury |

The ceiling is a cap on *new* exposure, never an instruction to force
capital in. A bullish regime permits 100%; it does not require it.
"""

from __future__ import annotations

from .adapter import Bar, DataAdapter
from .indicators import closes, max_drawdown, pct_from_high, sma, trend_state

DEPLOYMENT = {"bullish": 1.0, "volatile": 0.5, "bearish": 0.25}


def breadth(symbols: list[str], adapter: DataAdapter, lookback_days: int = 504) -> dict:
    """Share of the universe trading above its own 200-day average.

    **Sample-size caveat, and it is a serious one.**  Bajaj reads breadth
    across a broad universe (Nifty 500 or the whole market).  Computed over a
    ten-stock portfolio this is a statistic with a ±10% quantisation step and
    no claim to represent the market — one holding flipping moves it a full
    ten points.  ``reliable`` is false below 50 names, and callers must
    degrade rather than quietly treat it as market breadth.
    """
    above = 0
    counted = 0
    for symbol in symbols:
        px = closes(adapter.prices(symbol, lookback_days))
        dma200 = sma(px, 200)
        if dma200 is None or not px:
            continue
        counted += 1
        if px[-1] > dma200:
            above += 1
    if not counted:
        return {"pct_above_200dma": None, "counted": 0, "reliable": False}
    return {
        "pct_above_200dma": round(above / counted * 100, 1),
        "above": above,
        "counted": counted,
        "reliable": counted >= 50,
        "caveat": (
            None
            if counted >= 50
            else f"breadth over only {counted} names is not market breadth; "
                 f"wire a broad universe into DataAdapter before relying on it"
        ),
    }


def market_regime(
    adapter: DataAdapter,
    universe: list[str],
    lookback_days: int = 504,
) -> dict:
    """Classify the tape and derive the deployment ceiling."""
    index_bars: list[Bar] = adapter.benchmark(lookback_days)
    if not index_bars:
        return {
            "regime": "unknown",
            "deployment_ceiling": None,
            "index_symbol": adapter.benchmark_symbol,
            "index_trend": "unknown",
            "breadth": breadth(universe, adapter, lookback_days),
            "reasons": [
                f"no history for {adapter.benchmark_symbol}: the regime cannot be "
                "assessed, so no deployment ceiling is set. Export the index."
            ],
        }
    px = closes(index_bars)
    trend = trend_state(px)
    off_high = pct_from_high(px)
    drawdown = max_drawdown(px[-252:]) if len(px) >= 252 else max_drawdown(px)
    b = breadth(universe, adapter, lookback_days)

    reasons = []

    # The index's own trend is the primary input; breadth only confirms or
    # contradicts it, and is ignored outright when the sample is too thin to
    # mean anything.
    if trend == "uptrend":
        regime = "bullish"
        reasons.append("index 50-DMA above 200-DMA")
    elif trend == "downtrend":
        regime = "bearish"
        reasons.append("index 50-DMA below 200-DMA")
    else:
        regime = "volatile"
        reasons.append("index moving averages entangled")

    if off_high is not None and off_high < -0.10:
        if regime == "bullish":
            regime = "volatile"
        reasons.append(f"index {off_high * 100:.1f}% below its 52-week high")

    pct = b["pct_above_200dma"]
    if b["reliable"] and pct is not None:
        if pct < 35 and regime != "bearish":
            regime = "bearish" if pct < 20 else "volatile"
            reasons.append(f"only {pct}% of the universe above its 200-DMA")
        elif pct > 65:
            reasons.append(f"{pct}% of the universe above its 200-DMA")
    elif pct is not None:
        reasons.append(
            f"breadth {pct}% over {b['counted']} names — too thin to act on, ignored"
        )

    return {
        "regime": regime,
        "deployment_ceiling": DEPLOYMENT[regime],
        "index_symbol": adapter.benchmark_symbol,
        "index_trend": trend,
        "index_pct_from_high": round(off_high, 4) if off_high is not None else None,
        "index_max_drawdown_1y": round(drawdown, 4),
        "breadth": b,
        "reasons": reasons,
    }
