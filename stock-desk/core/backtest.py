"""Historical replay of a proposed setup against a stock's own past.

This is the one stage that can contradict the model from outside it.  The
bull/bear debate is still two agents sharing a base model and therefore its
blind spots; the replay is arithmetic on price history and does not care
what the desk concluded.

Two correctness properties the implementation must hold, because violating
either turns the win rate into a flattering lie:

**No lookahead.**  A setup predicate evaluated at bar ``i`` may read
``series[:i + 1]`` and nothing later.  Forward outcome is measured strictly
over ``series[i + 1:]``.

**Sample independence.**  Consecutive triggers overlap: a condition true on
Monday is usually still true on Tuesday, and scoring both double-counts one
market event.  Headline statistics use a greedily selected non-overlapping
subset; the raw trigger count is reported separately so the shrinkage is
visible rather than hidden.
"""

from __future__ import annotations

from typing import Callable

from .adapter import Bar
from .indicators import atr, rsi, sma_series

#: Trading days held per horizon dial setting.
HOLD_DAYS = {
    "intraday": 1,
    "swing": 10,
    "positional": 21,
    "medium": 63,
    "long": 252,
    "wealth": 504,
}

#: Stop distance in ATR multiples per risk-profile dial setting.
STOP_ATR = {
    "conservative": 1.5,
    "balanced": 2.5,
    "aggressive": 4.0,
}

# A setup predicate receives precomputed context and an index, and answers
# "did this setup trigger at bar i?" using only information available then.
Predicate = Callable[[dict, int], bool]


def _context(bars: list[Bar]) -> dict:
    px = [b.close for b in bars]
    ctx = {
        "close": px,
        "sma_50": sma_series(px, 50),
        "sma_200": sma_series(px, 200),
        "high_55": [None] * len(px),
        "rsi_14": [None] * len(px),
    }
    for i in range(len(px)):
        if i >= 55:
            ctx["high_55"][i] = max(px[i - 55:i])
        if i >= 15:
            ctx["rsi_14"][i] = rsi(px[max(0, i - 120):i + 1])
    return ctx


def _trend_follow(c: dict, i: int) -> bool:
    f, s = c["sma_50"][i], c["sma_200"][i]
    return f is not None and s is not None and c["close"][i] > f > s


def _trend_pullback(c: dict, i: int) -> bool:
    f, s, r = c["sma_50"][i], c["sma_200"][i], c["rsi_14"][i]
    return None not in (f, s, r) and f > s and r < 40


def _breakout(c: dict, i: int) -> bool:
    h = c["high_55"][i]
    return h is not None and c["close"][i] > h


def _momentum(c: dict, i: int) -> bool:
    f, r = c["sma_50"][i], c["rsi_14"][i]
    return None not in (f, r) and c["close"][i] > f and r > 55


def _oversold(c: dict, i: int) -> bool:
    r = c["rsi_14"][i]
    return r is not None and r < 30


#: Setups the Decision agent may name.  Anything else is rejected loudly.
SETUPS: dict[str, Predicate] = {
    "trend_follow": _trend_follow,
    "trend_pullback": _trend_pullback,
    "breakout": _breakout,
    "momentum": _momentum,
    "oversold_bounce": _oversold,
}


def _outcome(bars: list[Bar], entry: int, hold: int, stop: float | None) -> float:
    """Return of one trade entered at ``entry`` close, as a fraction.

    Exits at the stop if any bar's low breaches it, otherwise at the close
    ``hold`` bars later.  Filling at the stop price is an approximation: a
    gap-down opens below it, so real slippage makes losses worse, never
    better.  The bias is therefore conservative in the right direction.
    """
    entry_px = bars[entry].close
    last = min(entry + hold, len(bars) - 1)
    for j in range(entry + 1, last + 1):
        if stop is not None and bars[j].low <= stop:
            return (stop - entry_px) / entry_px
    return (bars[last].close - entry_px) / entry_px


def replay(
    bars: list[Bar],
    setup: str,
    horizon: str = "positional",
    risk_profile: str = "balanced",
) -> dict:
    """Score ``setup`` against this stock's own history.

    Returns win rate, expectancy and supporting counts.  ``sufficient`` is
    the field callers should gate on: a 100% win rate over two samples is
    noise wearing a statistic's clothes.
    """
    if setup not in SETUPS:
        raise ValueError(f"unknown setup {setup!r}; known: {sorted(SETUPS)}")
    hold = HOLD_DAYS.get(horizon, 21)
    stop_mult = STOP_ATR.get(risk_profile, 2.5)
    predicate = SETUPS[setup]
    ctx = _context(bars)

    triggers = [
        i
        for i in range(200, len(bars) - hold - 1)
        if predicate(ctx, i)
    ]

    # Greedily keep non-overlapping triggers so one market event is scored once.
    independent: list[int] = []
    for i in triggers:
        if not independent or i - independent[-1] >= hold:
            independent.append(i)

    trades = []
    for i in independent:
        a = atr(bars[max(0, i - 60):i + 1])
        stop = bars[i].close - stop_mult * a if a else None
        trades.append(_outcome(bars, i, hold, stop))

    n = len(trades)
    if n == 0:
        return {
            "setup": setup,
            "horizon": horizon,
            "hold_days": hold,
            "stop_atr_multiple": stop_mult,
            "samples": 0,
            "raw_triggers": len(triggers),
            "sufficient": False,
            "note": "setup never triggered in the available history",
        }

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    return {
        "setup": setup,
        "horizon": horizon,
        "hold_days": hold,
        "stop_atr_multiple": stop_mult,
        "samples": n,
        "raw_triggers": len(triggers),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "expectancy": round(expectancy, 4),
        "best": round(max(trades), 4),
        "worst": round(min(trades), 4),
        # Ten independent samples is already thin; below that the desk is
        # told to treat the number as colour, not evidence.
        "sufficient": n >= 10,
    }


def replay_all(bars: list[Bar], horizon: str, risk_profile: str) -> dict[str, dict]:
    """Score every known setup — used to show which the stock actually rewards."""
    return {
        name: replay(bars, name, horizon, risk_profile) for name in SETUPS
    }
