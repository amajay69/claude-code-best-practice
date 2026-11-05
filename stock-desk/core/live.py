"""Live data adapter: uploaded history + an NSE quote cache.

**Why a cache file rather than a direct API call.**

The NSE data arrives through an MCP server, which only the agent session can
call — a Python process cannot. So the split is: the session fetches quotes
and writes them to ``data/quotes.json``; this module reads that file. The
deterministic core stays offline-testable and reproducible, and a run can be
replayed later from exactly the quotes it saw.

Three inputs, each optional, each with a different failure mode:

| Input | Path | Missing means |
| --- | --- | --- |
| Daily history | ``data/history/<SYM>.csv`` | no indicators, no backtest, no correlation |
| Live quote | ``data/quotes.json`` | prices are as of the last history bar |
| Fundamentals | ``data/fundamentals.json`` | quality and value gates score neutral |

Nothing here substitutes a missing input with a plausible one. A gap is
reported as a gap, because a number no one can trace is worse than an
admitted absence.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta, timezone

from .adapter import Bar, DataAdapter

#: NSE's own name for the benchmark, as the MCP server spells it.
BENCHMARK = "NIFTY 50"

#: A quote older than this is reported stale rather than used silently.
STALE_AFTER_HOURS = 24

#: Minimum bars needed before each family of measures means anything.
HISTORY_REQUIREMENTS = {
    "rsi_14": 15,
    "atr_supertrend": 25,
    "sma_50": 50,
    "relative_strength": 65,
    "sma_200_trend": 200,
    "backtest": 260,
    "correlation_beta": 120,
    "annualised_vol": 60,
}


def _parse_timestamp(raw: str | None) -> datetime | None:
    """NSE sends either an ISO timestamp or 'YYYY-MM-DD HH:MM:SS'."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class QuoteCache:
    """Live NSE snapshots written by the session, read by the core."""

    def __init__(self, path: str):
        self.path = path
        self.quotes: dict = {}
        self.indices: dict = {}
        self.fetched_at: datetime | None = None
        self.source: str | None = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            self.quotes = payload.get("quotes", {})
            self.indices = payload.get("indices", {})
            self.fetched_at = _parse_timestamp(payload.get("fetched_at"))
            self.source = payload.get("source")

    def __bool__(self) -> bool:
        return bool(self.quotes)

    @property
    def age_hours(self) -> float | None:
        if not self.fetched_at:
            return None
        delta = datetime.now(timezone.utc) - self.fetched_at
        return round(delta.total_seconds() / 3600, 1)

    @property
    def stale(self) -> bool:
        age = self.age_hours
        return age is None or age > STALE_AFTER_HOURS

    def get(self, symbol: str) -> dict | None:
        return self.quotes.get(symbol)

    def as_bar(self, symbol: str) -> Bar | None:
        """Today's session as an OHLCV bar, if the quote carries a full one.

        The NSE quote gives open, high, low, last and volume, so a genuine
        bar can be built — this is not an estimate. It is only used when its
        date is strictly newer than the last bar of uploaded history, so a
        partial intraday bar never overwrites a settled daily one.
        """
        q = self.get(symbol)
        if not q:
            return None
        stamp = _parse_timestamp(q.get("latestTimestamp"))
        if not stamp:
            return None
        required = ("openPrice", "highPrice", "lowPrice", "lastTradedPrice")
        if any(q.get(k) in (None, 0) for k in required):
            return None
        return Bar(
            stamp.date().isoformat(),
            float(q["openPrice"]),
            float(q["highPrice"]),
            float(q["lowPrice"]),
            float(q["lastTradedPrice"]),
            int(q.get("volume") or 0),
        )

    def status(self) -> dict:
        return {
            "present": bool(self.quotes),
            "symbols": sorted(self.quotes),
            "indices": sorted(self.indices),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "age_hours": self.age_hours,
            "stale": self.stale,
            "source": self.source,
            "note": (
                None
                if not self.stale
                else "quotes are stale; prices shown are the last published values, "
                     "not live. Re-run the quote fetch before acting on them."
            ),
        }


def read_history(path: str) -> list[Bar]:
    """Read a normalised history CSV into bars, oldest first."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    bars = [
        Bar(
            r["date"],
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            int(float(r.get("volume") or 0)),
        )
        for r in rows
        if r.get("date") and r.get("close")
    ]
    bars.sort(key=lambda b: b.date)
    return bars


class LiveAdapter(DataAdapter):
    """History from disk, last price from the quote cache.

    ``adjusted`` defaults to False because an exported broker or charting
    CSV is not guaranteed split-adjusted, and the backtest refuses to trust
    an unadjusted series. Pass ``adjusted=True`` only when the export is
    known to be adjusted — TradingView's is.
    """

    benchmark_symbol = BENCHMARK

    def __init__(self, root: str, adjusted: bool = False):
        self.root = root
        self.adjusted = adjusted
        self.history_dir = os.path.join(root, "history")
        self.quotes = QuoteCache(os.path.join(root, "quotes.json"))
        self._fundamentals = self._load("fundamentals.json")
        self._sectors = self._load("sectors.json")
        self._cache: dict[str, list[Bar]] = {}

    def _load(self, name: str) -> dict:
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _history(self, symbol: str) -> list[Bar]:
        if symbol in self._cache:
            return self._cache[symbol]
        bars: list[Bar] = []
        # "NIFTY 50" is NSE's spelling; a file is as likely to be NIFTY50.csv.
        for candidate in (symbol, symbol.replace(" ", ""), symbol.replace(" ", "_")):
            path = os.path.join(self.history_dir, f"{candidate}.csv")
            if os.path.exists(path):
                bars = read_history(path)
                break

        # Append today's live bar only when it is genuinely newer, so a
        # partial intraday session never overwrites a settled daily close.
        live = self.quotes.as_bar(symbol)
        if live and (not bars or live.date > bars[-1].date):
            bars = bars + [live]

        self._cache[symbol] = bars
        return bars

    def prices(self, symbol: str, lookback_days: int) -> list[Bar]:
        bars = self._history(symbol)
        if not bars:
            raise KeyError(
                f"no price history for {symbol!r}. Upload a daily OHLC CSV to "
                f"{os.path.join(self.history_dir, symbol + '.csv')} "
                f"(scripts/import_history.py normalises broker exports)."
            )
        return bars[-lookback_days:] if lookback_days else bars

    def fundamentals(self, symbol: str) -> dict:
        return self._fundamentals.get(symbol, {})

    def sector(self, symbol: str) -> str:
        return self._sectors.get(symbol, "Unknown")

    def news(self, symbol: str, limit: int = 10) -> list[dict]:
        return []

    def benchmark(self, lookback_days: int) -> list[Bar]:
        """Index history, or an empty list when it was never uploaded.

        Deliberately does not raise. A user who exports their holdings but
        forgets the index should lose beta, relative strength and the
        benchmark comparison — not the entire run. The absence surfaces as
        a warning in :meth:`report` and as ``n/a`` in the output.
        """
        return self._history(self.benchmark_symbol)[-lookback_days:] if lookback_days \
            else self._history(self.benchmark_symbol)

    def universe(self) -> list[str]:
        if not os.path.isdir(self.history_dir):
            return []
        return sorted(f[:-4] for f in os.listdir(self.history_dir) if f.endswith(".csv"))

    def last_price(self, symbol: str) -> tuple[float | None, str]:
        """Latest price and where it came from.

        Live quote when present, else the final history close. The source is
        returned with the number so the report can show which it used — a
        price from a three-day-old close must not look like a live one.
        """
        quote = self.quotes.get(symbol)
        if quote and quote.get("lastTradedPrice"):
            return float(quote["lastTradedPrice"]), "NSE live"
        bars = self._history(symbol)
        if bars:
            return bars[-1].close, f"last history close ({bars[-1].date})"
        return None, "unavailable"

    def coverage(self, symbol: str) -> dict:
        """What this symbol's data does and does not support.

        Drives the ``n/a — needs daily history`` cells in the report. Writing
        a blank or a zero there would invite the reader to treat an absence
        as a measurement.
        """
        bars = self._history(symbol)
        n = len(bars)
        supported = {k: n >= need for k, need in HISTORY_REQUIREMENTS.items()}
        return {
            "bars": n,
            "first": bars[0].date if bars else None,
            "last": bars[-1].date if bars else None,
            "has_history": n > 0,
            "has_quote": self.quotes.get(symbol) is not None,
            "has_fundamentals": bool(self.fundamentals(symbol)),
            "supports": supported,
            "missing": sorted(k for k, ok in supported.items() if not ok),
            "adjusted": self.adjusted,
        }

    def report(self, symbols: list[str]) -> dict:
        """Whole-run data health, for the provenance sheet."""
        per_symbol = {s: self.coverage(s) for s in symbols}
        no_history = [s for s, c in per_symbol.items() if not c["has_history"]]
        no_quote = [s for s, c in per_symbol.items() if not c["has_quote"]]
        no_fundamentals = [s for s, c in per_symbol.items() if not c["has_fundamentals"]]
        return {
            "quotes": self.quotes.status(),
            "per_symbol": per_symbol,
            "symbols_without_history": no_history,
            "symbols_without_quote": no_quote,
            "symbols_without_fundamentals": no_fundamentals,
            "adjusted_prices": self.adjusted,
            "warnings": [
                w
                for w in (
                    f"{len(no_history)} symbol(s) have no price history: "
                    f"{', '.join(no_history)}" if no_history else None,
                    f"{len(no_quote)} symbol(s) have no live quote: "
                    f"{', '.join(no_quote)}" if no_quote else None,
                    f"{len(no_fundamentals)} symbol(s) have no fundamentals: "
                    f"{', '.join(no_fundamentals)}" if no_fundamentals else None,
                    self.quotes.status()["note"],
                    None
                    if self._history(self.benchmark_symbol)
                    else f"no history for the benchmark ({self.benchmark_symbol}): "
                         "beta, relative strength, sector ranking and the index "
                         "comparison are unavailable. Export the index too.",
                    None
                    if self.adjusted
                    else "prices are NOT declared split-adjusted; the backtest will "
                         "refuse to run. Re-import with --adjusted if your export is "
                         "adjusted (TradingView's is).",
                )
                if w
            ],
        }
