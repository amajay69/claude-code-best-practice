#!/usr/bin/env python3
"""Normalise exported price history into the desk's canonical form.

    python3 scripts/import_history.py ~/Downloads/*.csv --adjusted
    python3 scripts/import_history.py HDFCBANK.csv --symbol HDFCBANK

Accepts the column spellings used by TradingView, Zerodha, Groww,
Investing.com and plain exports, and writes
``data/history/<SYMBOL>.csv`` as ``date,open,high,low,close,volume``.

**It validates rather than trusts.**  An exported CSV is the single most
likely place for bad data to enter, and every downstream number — every
indicator, the backtest, the correlation matrix — inherits whatever comes
in here.  The checks below are ordered by how badly each failure corrupts
the output, not by how likely it is.

The most important is **split detection**.  A 1:2 split in an unadjusted
series looks exactly like a -50% day.  The backtest cannot tell the
difference, scores it as a catastrophic loss, and reports a confidently
wrong win rate.  Any single-day move beyond 35% is therefore flagged, and
the import refuses to mark the file adjusted unless you said it is.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(HERE, "data", "history")

#: Header spellings seen in the wild, normalised to our field names.
ALIASES = {
    "date": ("date", "time", "datetime", "timestamp", "tradedate"),
    "open": ("open", "openprice", "o"),
    "high": ("high", "highprice", "h"),
    "low": ("low", "lowprice", "l"),
    "close": ("close", "closeprice", "adjclose", "adjustedclose", "price", "ltp", "c"),
    "volume": ("volume", "vol", "sharestraded", "quantity", "totaltradedquantity"),
}

#: A one-day move beyond this is almost always a corporate action, not a trade.
SPLIT_THRESHOLD = 0.35

#: Calendar days without a bar before we call it a gap.
GAP_DAYS = 10


def _norm(header: str) -> str:
    return re.sub(r"[^a-z]", "", header.lower())


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    lookup = {_norm(f): f for f in fieldnames if f}
    mapping = {}
    for field, candidates in ALIASES.items():
        for cand in candidates:
            if cand in lookup:
                mapping[field] = lookup[cand]
                break
    return mapping


def _parse_date(raw: str) -> str | None:
    raw = raw.strip()
    if raw.isdigit() and len(raw) >= 10:          # unix seconds (TradingView)
        return datetime.utcfromtimestamp(int(raw[:10])).date().isoformat()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%b %d, %Y"):
        try:
            return datetime.strptime(raw.split("T")[0] if "T" in fmt else raw, fmt).date().isoformat()
        except ValueError:
            continue
    try:                                           # ISO with timezone or time
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("₹", "").replace("$", "")
    if not text or text in ("-", "n/a", "N/A", "null"):
        return None
    # Investing.com writes volume as 1.23M / 4.5K
    multiplier = 1.0
    if text and text[-1] in "KMB":
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9}[text[-1]]
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def load(path: str) -> tuple[list[dict], list[str]]:
    """Read and normalise one export. Returns rows plus validation notes."""
    notes: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path}: no header row")
        mapping = _map_columns(reader.fieldnames)
        missing = [f for f in ("date", "close") if f not in mapping]
        if missing:
            raise ValueError(
                f"{path}: could not find {missing} among {reader.fieldnames}"
            )
        raw_rows = list(reader)

    rows, skipped = [], 0
    for r in raw_rows:
        iso = _parse_date(r[mapping["date"]])
        close = _number(r[mapping["close"]])
        if not iso or close is None or close <= 0:
            skipped += 1
            continue
        # A close-only export still works for most measures; OHLC collapses
        # to the close rather than being invented.
        o = _number(r.get(mapping.get("open", ""), "")) or close
        h = _number(r.get(mapping.get("high", ""), "")) or max(o, close)
        low = _number(r.get(mapping.get("low", ""), "")) or min(o, close)
        v = _number(r.get(mapping.get("volume", ""), "")) or 0
        rows.append({"date": iso, "open": o, "high": h, "low": low,
                     "close": close, "volume": int(v)})

    if skipped:
        notes.append(f"skipped {skipped} unparseable row(s)")
    if not rows:
        raise ValueError(f"{path}: no usable rows")

    rows.sort(key=lambda r: r["date"])

    # Duplicates: keep the last entry for a date, which is the settled one.
    deduped, seen = [], set()
    for r in reversed(rows):
        if r["date"] not in seen:
            seen.add(r["date"])
            deduped.append(r)
    deduped.reverse()
    if len(deduped) != len(rows):
        notes.append(f"removed {len(rows) - len(deduped)} duplicate date(s)")
    rows = deduped

    notes.extend(_validate(rows))
    return rows, notes


def _validate(rows: list[dict]) -> list[str]:
    notes = []

    bad_bars = sum(
        1 for r in rows
        if r["high"] < r["low"]
        or r["high"] < max(r["open"], r["close"]) - 1e-9
        or r["low"] > min(r["open"], r["close"]) + 1e-9
    )
    if bad_bars:
        notes.append(f"⚠ {bad_bars} bar(s) have inconsistent OHLC (high<low or outside range)")

    jumps = []
    for prev, cur in zip(rows, rows[1:]):
        if prev["close"] <= 0:
            continue
        move = (cur["close"] - prev["close"]) / prev["close"]
        if abs(move) > SPLIT_THRESHOLD:
            jumps.append((cur["date"], round(move * 100, 1)))
    if jumps:
        shown = ", ".join(f"{d} {m:+.0f}%" for d, m in jumps[:5])
        notes.append(
            f"⚠ {len(jumps)} single-day move(s) beyond ±{SPLIT_THRESHOLD:.0%}: {shown}. "
            "These are usually unadjusted splits or bonuses. An unadjusted series "
            "makes the backtest confidently wrong — verify before trusting results."
        )

    gaps = []
    for prev, cur in zip(rows, rows[1:]):
        delta = (datetime.fromisoformat(cur["date"]) - datetime.fromisoformat(prev["date"])).days
        if delta > GAP_DAYS:
            gaps.append((prev["date"], cur["date"], delta))
    if gaps:
        notes.append(
            f"⚠ {len(gaps)} gap(s) over {GAP_DAYS} days, e.g. "
            + ", ".join(f"{a}→{b} ({d}d)" for a, b, d in gaps[:3])
        )

    span_years = (
        datetime.fromisoformat(rows[-1]["date"]) - datetime.fromisoformat(rows[0]["date"])
    ).days / 365.25
    if len(rows) < 260:
        notes.append(
            f"only {len(rows)} bars ({span_years:.1f}y) — the 200-DMA and the 2-year "
            "backtest need ~260+. Shorter measures (RSI, ATR) will still work."
        )
    return notes


def symbol_from_path(path: str) -> str:
    """TradingView writes 'NSE_HDFCBANK, 1D.csv'; brokers write 'HDFCBANK.csv'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.split(r"[,_\-\s]", stem)
    for part in stem:
        cleaned = re.sub(r"[^A-Za-z0-9&]", "", part).upper()
        if cleaned and cleaned not in ("NSE", "BSE", "1D", "D", "DAILY") and not cleaned.isdigit():
            return cleaned
    return re.sub(r"[^A-Za-z0-9&]", "", os.path.basename(path)).upper()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="+", help="exported CSV file(s)")
    p.add_argument("--symbol", help="override the symbol (single file only)")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument(
        "--adjusted", action="store_true",
        help="declare the source split/bonus-adjusted. Only pass this if it is "
             "true: the backtest refuses to run on undeclared series precisely "
             "because an unadjusted split looks like a -50%% day.",
    )
    args = p.parse_args(argv)

    if args.symbol and len(args.files) > 1:
        p.error("--symbol works with a single file only")

    os.makedirs(args.out, exist_ok=True)
    imported, failed = [], []

    for path in args.files:
        symbol = args.symbol or symbol_from_path(path)
        try:
            rows, notes = load(path)
        except (ValueError, OSError) as exc:
            failed.append((path, str(exc)))
            print(f"✗ {os.path.basename(path)}: {exc}", file=sys.stderr)
            continue

        target = os.path.join(args.out, f"{symbol}.csv")
        with open(target, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["date", "open", "high", "low", "close", "volume"])
            w.writeheader()
            w.writerows(rows)

        imported.append(symbol)
        print(f"✓ {symbol}: {len(rows)} bars, {rows[0]['date']} → {rows[-1]['date']}")
        for note in notes:
            print(f"    {note}")

    marker = os.path.join(args.out, ".adjusted")
    if args.adjusted and imported:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("prices declared split/bonus-adjusted at import\n")
    elif imported and not os.path.exists(marker):
        print(
            "\nNote: prices are NOT declared adjusted, so the backtest will refuse "
            "to run. Re-import with --adjusted if your export is adjusted "
            "(TradingView's is).",
            file=sys.stderr,
        )

    print(f"\n{len(imported)} imported, {len(failed)} failed → {args.out}")
    return 1 if failed and not imported else 0


if __name__ == "__main__":
    raise SystemExit(main())
