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
        "bars": len(bars),
    }
