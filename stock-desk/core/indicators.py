"""Deterministic technical measures computed from OHLCV bars.

Pure stdlib and pure functions: every indicator here is reproducible and
unit-testable.  The LLM agents *read* these numbers; they never compute
them.  Keeping arithmetic out of the model is what makes two runs of the
same portfolio produce the same technical facts.
"""

from __future__ import annotations

import math

from .adapter import Bar


def closes(bars: list[Bar]) -> list[float]:
    return [b.close for b in bars]


def returns(series: list[float]) -> list[float]:
    """Simple period-over-period returns.  Length is ``len(series) - 1``."""
    out = []
    for prev, cur in zip(series, series[1:]):
        out.append((cur - prev) / prev if prev else 0.0)
    return out


def sma(series: list[float], window: int) -> float | None:
    if len(series) < window or window <= 0:
        return None
    return sum(series[-window:]) / window


def sma_series(series: list[float], window: int) -> list[float | None]:
    """Rolling SMA aligned to ``series`` (``None`` until the window fills)."""
    out: list[float | None] = [None] * len(series)
    if window <= 0:
        return out
    running = 0.0
    for i, value in enumerate(series):
        running += value
        if i >= window:
            running -= series[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def ema(series: list[float], window: int) -> float | None:
    if len(series) < window or window <= 0:
        return None
    k = 2 / (window + 1)
    value = sum(series[:window]) / window
    for price in series[window:]:
        value = price * k + value * (1 - k)
    return value


def rsi(series: list[float], window: int = 14) -> float | None:
    """Wilder's RSI.  ``None`` when there is not enough history."""
    if len(series) < window + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(series, series[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    for g, l in zip(gains[window:], losses[window:]):
        avg_gain = (avg_gain * (window - 1) + g) / window
        avg_loss = (avg_loss * (window - 1) + l) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(bars: list[Bar], window: int = 14) -> float | None:
    """Average True Range — the unit stop distances are quoted in."""
    if len(bars) < window + 1:
        return None
    trs = []
    for prev, cur in zip(bars, bars[1:]):
        trs.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    value = sum(trs[:window]) / window
    for tr in trs[window:]:
        value = (value * (window - 1) + tr) / window
    return value


def atr_series(bars: list[Bar], window: int = 14) -> list[float | None]:
    """Rolling Wilder ATR aligned to ``bars`` (``None`` until the window fills).

    Supertrend needs ATR at every bar, not just the last one, so this exists
    alongside the scalar :func:`atr`.
    """
    out: list[float | None] = [None] * len(bars)
    if len(bars) < window + 1:
        return out
    trs = []
    for prev, cur in zip(bars, bars[1:]):
        trs.append(
            max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        )
    value = sum(trs[:window]) / window
    out[window] = value
    for i, tr in enumerate(trs[window:], start=window + 1):
        value = (value * (window - 1) + tr) / window
        out[i] = value
    return out


def supertrend(bars: list[Bar], window: int = 10, multiplier: float = 3.0) -> dict:
    """Supertrend direction and level — one half of Bajaj's exit trigger.

    Returns ``{"direction": "green"|"red"|None, "level": float|None,
    "flipped_bars_ago": int|None}``.

    The band carry-forward is the part people get wrong: a band only moves in
    the favourable direction while the trend holds, and ratchets rather than
    tracking price tick for tick.  Recomputing the raw band each bar produces
    a Supertrend that flips constantly and is useless as an exit.
    """
    atrs = atr_series(bars, window)
    n = len(bars)
    if n < window + 2:
        return {"direction": None, "level": None, "flipped_bars_ago": None}

    final_upper: list[float | None] = [None] * n
    final_lower: list[float | None] = [None] * n
    direction: list[int | None] = [None] * n   # +1 green (long), -1 red (short)

    for i in range(n):
        a = atrs[i]
        if a is None:
            continue
        mid = (bars[i].high + bars[i].low) / 2
        basic_upper, basic_lower = mid + multiplier * a, mid - multiplier * a
        prev_u, prev_l = final_upper[i - 1], final_lower[i - 1]

        if prev_u is None or basic_upper < prev_u or bars[i - 1].close > prev_u:
            final_upper[i] = basic_upper
        else:
            final_upper[i] = prev_u
        if prev_l is None or basic_lower > prev_l or bars[i - 1].close < prev_l:
            final_lower[i] = basic_lower
        else:
            final_lower[i] = prev_l

        if direction[i - 1] is None:
            direction[i] = 1 if bars[i].close > final_upper[i] else -1
        elif direction[i - 1] == 1:
            direction[i] = -1 if bars[i].close < final_lower[i] else 1
        else:
            direction[i] = 1 if bars[i].close > final_upper[i] else -1

    last = direction[-1]
    if last is None:
        return {"direction": None, "level": None, "flipped_bars_ago": None}

    flipped = None
    for back in range(1, n):
        if direction[-1 - back] is not None and direction[-1 - back] != last:
            flipped = back
            break

    return {
        "direction": "green" if last == 1 else "red",
        "level": round(final_lower[-1] if last == 1 else final_upper[-1], 2),
        "flipped_bars_ago": flipped,
    }


def strong_zone(bars: list[Bar], tolerance: float = 0.05, window: int = 252) -> dict:
    """Is the stock in Bajaj's 'strong zone' — at or near its highs?

    His entry rule is to buy strength rather than catch falling knives, so
    this measures proximity to the rolling high and to the all-time high in
    the available history.
    """
    px = closes(bars)
    if not px:
        return {"in_zone": False, "pct_from_high": None, "at_ath": False}
    recent_high = max(px[-window:])
    ath = max(px)
    off = (px[-1] - recent_high) / recent_high if recent_high else None
    return {
        "in_zone": off is not None and off >= -tolerance,
        "pct_from_high": round(off, 4) if off is not None else None,
        "at_ath": px[-1] >= ath * (1 - 1e-9),
        "rolling_high": round(recent_high, 2),
    }


def annualised_vol(series: list[float], periods: int = 252) -> float | None:
    """Annualised stdev of daily returns."""
    rets = returns(series)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(periods)


def max_drawdown(series: list[float]) -> float:
    """Worst peak-to-trough decline as a negative fraction."""
    if not series:
        return 0.0
    peak = series[0]
    worst = 0.0
    for price in series:
        peak = max(peak, price)
        if peak:
            worst = min(worst, (price - peak) / peak)
    return worst


def pct_from_high(series: list[float], window: int = 252) -> float | None:
    """Distance below the rolling high, as a negative fraction."""
    if not series:
        return None
    recent = series[-window:]
    high = max(recent)
    return (series[-1] - high) / high if high else None


def trend_state(series: list[float]) -> str:
    """Coarse regime label from the 50/200 SMA relationship."""
    fast, slow = sma(series, 50), sma(series, 200)
    if fast is None or slow is None:
        return "unknown"
    if fast > slow * 1.02:
        return "uptrend"
    if fast < slow * 0.98:
        return "downtrend"
    return "sideways"


def snapshot(bars: list[Bar]) -> dict:
    """Every technical fact the Technical specialist is allowed to cite."""
    px = closes(bars)
    last = px[-1] if px else None
    atr14 = atr(bars)
    return {
        "last_close": last,
        "sma_50": sma(px, 50),
        "sma_200": sma(px, 200),
        "ema_20": ema(px, 20),
        "rsi_14": rsi(px),
        "atr_14": atr14,
        "atr_pct": (atr14 / last) if atr14 and last else None,
        "annualised_vol": annualised_vol(px),
        "max_drawdown_2y": max_drawdown(px),
        "pct_from_52w_high": pct_from_high(px),
        "trend": trend_state(px),
        "supertrend": supertrend(bars),
        "strong_zone": strong_zone(bars),
        "bars": len(bars),
    }
