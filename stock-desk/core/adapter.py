"""Data access boundary for the desk.

Every module downstream talks to a ``DataAdapter`` and never to a network
call, a file path, or a vendor SDK.  That indirection is the whole point:
the deterministic core can be unit-tested against fixtures with known
answers, and swapping in a live NSE/BSE provider touches this file only.

Prices are assumed **split- and bonus-adjusted**.  Feeding unadjusted
series into the backtest produces a fake -50% bar on every split, which is
the failure mode that makes a backtest confidently wrong rather than
obviously broken.  An adapter that cannot guarantee adjustment must say so
via :attr:`DataAdapter.adjusted`.
"""

from __future__ import annotations

import csv
import json
import os
import re
from abc import ABC, abstractmethod
from typing import NamedTuple


class Bar(NamedTuple):
    """One daily OHLCV bar.  ``date`` is an ISO ``YYYY-MM-DD`` string."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class Holding(NamedTuple):
    """One line of a broker holdings export."""

    symbol: str
    qty: float
    avg_cost: float

    @property
    def invested(self) -> float:
        return self.qty * self.avg_cost


class DataAdapter(ABC):
    """The contract every data source must satisfy."""

    #: Whether :meth:`prices` returns split/bonus-adjusted series.
    adjusted: bool = True

    #: Symbol used as the portfolio benchmark.
    benchmark_symbol: str = "NIFTY50"

    @abstractmethod
    def prices(self, symbol: str, lookback_days: int) -> list[Bar]:
        """Most recent ``lookback_days`` bars, oldest first."""

    @abstractmethod
    def fundamentals(self, symbol: str) -> dict:
        """Point-in-time fundamentals for ``symbol``."""

    @abstractmethod
    def sector(self, symbol: str) -> str:
        """Sector label used for concentration analysis."""

    @abstractmethod
    def news(self, symbol: str, limit: int = 10) -> list[dict]:
        """Recent headlines, newest first.  May be empty."""

    def benchmark(self, lookback_days: int) -> list[Bar]:
        return self.prices(self.benchmark_symbol, lookback_days)

    def universe(self) -> list[str]:
        """Symbols this adapter can serve.  Used for fixture validation."""
        return []


class FixtureAdapter(DataAdapter):
    """Offline adapter backed by checked-in CSV/JSON fixtures.

    Layout::

        fixtures/
          prices/<SYMBOL>.csv      date,open,high,low,close,volume
          fundamentals.json        {"<SYMBOL>": {...}}
          sectors.json             {"<SYMBOL>": "Banking"}
          news.json                {"<SYMBOL>": [{"date":..,"headline":..}]}
    """

    adjusted = True

    def __init__(self, root: str):
        self.root = root
        self._prices: dict[str, list[Bar]] = {}
        self._fundamentals = self._load_json("fundamentals.json")
        self._sectors = self._load_json("sectors.json")
        self._news = self._load_json("news.json")

    def _load_json(self, name: str) -> dict:
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def prices(self, symbol: str, lookback_days: int) -> list[Bar]:
        if symbol not in self._prices:
            path = os.path.join(self.root, "prices", f"{symbol}.csv")
            if not os.path.exists(path):
                raise KeyError(f"no price fixture for {symbol!r} at {path}")
            with open(path, encoding="utf-8") as fh:
                self._prices[symbol] = [
                    Bar(
                        row["date"],
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        int(float(row["volume"])),
                    )
                    for row in csv.DictReader(fh)
                ]
        bars = self._prices[symbol]
        return bars[-lookback_days:] if lookback_days else bars

    def fundamentals(self, symbol: str) -> dict:
        return self._fundamentals.get(symbol, {})

    def sector(self, symbol: str) -> str:
        return self._sectors.get(symbol, "Unknown")

    def news(self, symbol: str, limit: int = 10) -> list[dict]:
        return self._news.get(symbol, [])[:limit]

    def universe(self) -> list[str]:
        d = os.path.join(self.root, "prices")
        if not os.path.isdir(d):
            return []
        return sorted(f[:-4] for f in os.listdir(d) if f.endswith(".csv"))


def _norm(header: str) -> str:
    """Collapse a broker CSV header to a comparable key."""
    return re.sub(r"[^a-z]", "", header.lower())


# Broker exports disagree on spelling; map every variant we have seen.
_SYMBOL_KEYS = ("instrument", "symbol", "stock", "scrip", "tradingsymbol")
_QTY_KEYS = ("qty", "quantity", "qtyavailable", "shares")
_COST_KEYS = ("avgcost", "averagecost", "avgprice", "buyavg", "averageprice")


def load_holdings(path: str) -> list[Holding]:
    """Parse a broker holdings export into :class:`Holding` rows.

    Tolerates the header spellings used by common Indian brokers (Zerodha's
    ``Qty.``/``Avg. cost``, Groww's ``Quantity``/``Average price``) rather
    than demanding one exact format, because the user is pasting whatever
    their broker gave them.
    """
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} has no data rows")

    lookup = {_norm(k): k for k in rows[0] if k}

    def pick(candidates: tuple[str, ...], label: str) -> str:
        for cand in candidates:
            if cand in lookup:
                return lookup[cand]
        raise ValueError(
            f"{path}: no {label} column found "
            f"(looked for {candidates}, saw {sorted(lookup)})"
        )

    sym_col = pick(_SYMBOL_KEYS, "symbol")
    qty_col = pick(_QTY_KEYS, "quantity")
    cost_col = pick(_COST_KEYS, "average cost")

    holdings = []
    for row in rows:
        symbol = (row[sym_col] or "").strip().upper()
        if not symbol:
            continue
        qty = float(str(row[qty_col]).replace(",", "").strip())
        cost = float(str(row[cost_col]).replace(",", "").strip())
        if qty <= 0:
            continue
        holdings.append(Holding(symbol, qty, cost))
    if not holdings:
        raise ValueError(f"{path}: parsed 0 holdings with positive quantity")
    return holdings
