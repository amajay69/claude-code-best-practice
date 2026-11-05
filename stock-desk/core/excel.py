"""Excel workbook output — the human-facing deliverable.

Six sheets: Holdings, Facts, Agent Notes, Verdicts, Summary, Provenance.

Three rules this module enforces, each because the alternative misleads:

**Gaps are written, never left blank.** A missing indicator reads
``n/a — needs daily history``. A blank cell invites the reader to assume
zero, and a zero is a measurement that was never taken.

**Live figures are formulas, not frozen numbers.** Market value, P&L and
weights are Excel formulas over the price cell, so editing a price
recalculates the book. A pasted constant goes stale the moment the reader
changes anything.

**Opinion is quarantined.** Agent judgement lives on its own sheet behind a
banner. Nothing on the Facts sheet came from a model.

``openpyxl`` is an optional dependency: the analysis core is stdlib-only
and keeps working without it. Only this exporter needs it.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

try:
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    AVAILABLE = True
except ImportError:                                    # pragma: no cover
    AVAILABLE = False

FONT = "Arial"
NA = "n/a — needs daily history"
NA_FUND = "n/a — needs fundamentals"

HEADER_FILL = PatternFill("solid", fgColor="1F3864") if AVAILABLE else None
WARN_FILL = PatternFill("solid", fgColor="FFF2CC") if AVAILABLE else None
OPINION_FILL = PatternFill("solid", fgColor="FCE4D6") if AVAILABLE else None
NA_FILL = PatternFill("solid", fgColor="F2F2F2") if AVAILABLE else None

#: Blue marks a value you supplied, per the financial-model convention.
INPUT_FONT = Font(name=FONT, color="0000FF") if AVAILABLE else None
BODY_FONT = Font(name=FONT) if AVAILABLE else None
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF") if AVAILABLE else None
TITLE_FONT = Font(name=FONT, bold=True, size=13) if AVAILABLE else None

#: Action -> direction, so "exit" and "trim" count as agreement.
DIRECTION = {
    "exit": "reduce", "trim": "reduce",
    "hold": "hold",
    "accumulate": "add", "buy": "add",
}


def _header(ws, row: int, labels: list[str], notes: dict[str, str] | None = None) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        if notes and label in notes:
            cell.comment = Comment(notes[label], "stock-desk")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _write(ws, row: int, col: int, value, *, fmt=None, font=None, fill=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = font or BODY_FONT
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    if isinstance(value, str) and value.startswith("n/a"):
        cell.fill = NA_FILL
        cell.font = Font(name=FONT, italic=True, color="808080")
    return cell


def _autosize(ws, widths: dict[int, int] | None = None, cap: int = 52) -> None:
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        if widths and col in widths:
            ws.column_dimensions[letter].width = widths[col]
            continue
        longest = max(
            (len(str(ws.cell(row=r, column=col).value or "")) for r in range(1, ws.max_row + 1)),
            default=10,
        )
        ws.column_dimensions[letter].width = min(max(longest + 2, 10), cap)


def _banner(ws, text: str, fill) -> None:
    cell = ws.cell(row=1, column=1, value=text)
    cell.font = Font(name=FONT, bold=True, size=11)
    cell.fill = fill
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
    ws.row_dimensions[1].height = 30


# --------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------

def _holdings_sheet(wb, payload: dict, prices: dict) -> None:
    ws = wb.create_sheet("Holdings")
    _banner(ws, "Blue cells are your input. Everything else is a formula — "
                "edit a price and the book recalculates.", WARN_FILL)
    cols = ["Symbol", "Qty", "Avg Cost", "Last Price", "Price Source", "Day %",
            "Invested", "Market Value", "P&L", "P&L %", "Weight %"]
    _header(ws, 2, cols)

    holdings = payload.get("holdings", [])
    first = 3
    for i, h in enumerate(holdings):
        r = first + i
        symbol = h["symbol"]
        px, source = prices.get(symbol, (None, "unavailable"))
        _write(ws, r, 1, symbol)
        _write(ws, r, 2, h["qty"], fmt="#,##0", font=INPUT_FONT)
        _write(ws, r, 3, h["avg_cost"], fmt="₹#,##0.00", font=INPUT_FONT)
        _write(ws, r, 4, px if px is not None else NA, fmt="₹#,##0.00")
        _write(ws, r, 5, source)
        _write(ws, r, 6, h.get("day_pct") if h.get("day_pct") is not None else "n/a",
               fmt="0.00%")
        _write(ws, r, 7, f"=B{r}*C{r}", fmt="₹#,##0")
        _write(ws, r, 8, f"=B{r}*D{r}", fmt="₹#,##0")
        _write(ws, r, 9, f"=H{r}-G{r}", fmt="₹#,##0;(₹#,##0);-")
        _write(ws, r, 10, f"=IFERROR(I{r}/G{r},\"\")", fmt="0.0%")
        last = first + len(holdings) - 1
        _write(ws, r, 11, f"=IFERROR(H{r}/SUM($H${first}:$H${last}),\"\")", fmt="0.0%")

    total = first + len(holdings)
    _write(ws, total, 1, "TOTAL", font=Font(name=FONT, bold=True))
    for col, letter in ((7, "G"), (8, "H"), (9, "I")):
        _write(ws, total, col, f"=SUM({letter}{first}:{letter}{total - 1})",
               fmt="₹#,##0", font=Font(name=FONT, bold=True))
    _write(ws, total, 10, f"=IFERROR(I{total}/G{total},\"\")", fmt="0.0%",
           font=Font(name=FONT, bold=True))
    _autosize(ws)


#: Facts columns: (label, source tag, path into the verdict, number format)
FACT_COLUMNS = [
    ("Symbol", "", None, None),
    ("Sector", "[DATA]", "sector", None),
    ("Last", "[NSE]", "last_close", "₹#,##0.00"),
    ("% from 52w High", "[NSE]", "technical.pct_from_52w_high", "0.0%"),
    ("Trend", "[CALC]", "technical.trend", None),
    ("50-DMA", "[CALC]", "technical.sma_50", "₹#,##0.00"),
    ("200-DMA", "[CALC]", "technical.sma_200", "₹#,##0.00"),
    ("RSI(14)", "[CALC]", "technical.rsi_14", "0.0"),
    ("ATR(14)", "[CALC]", "technical.atr_14", "₹#,##0.00"),
    ("Supertrend", "[CALC]", "technical.supertrend.direction", None),
    ("Ann. Vol", "[CALC]", "technical.annualised_vol", "0.0%"),
    ("Max DD 2y", "[CALC]", "technical.max_drawdown_2y", "0.0%"),
    ("Stop", "[CALC]", "stop", "₹#,##0.00"),
    ("Backtest setup", "[CALC]", "backtest.best_supported_setup", None),
    ("Win rate", "[CALC]", "backtest.evidence.win_rate", "0.0%"),
    ("Samples", "[CALC]", "backtest.evidence.samples", "0"),
]

SOURCE_NOTES = {
    "[NSE]": "Live NSE quote.",
    "[CALC]": "Computed from daily price history.",
    "[DATA]": "From your uploaded reference data.",
}


def _dig(obj: dict, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _facts_sheet(wb, payload: dict, coverage: dict | None) -> None:
    ws = wb.create_sheet("Facts")
    _banner(ws, "Computed facts only — nothing on this sheet came from an AI. "
                "Column tags: [NSE] live quote · [CALC] from price history · "
                "[DATA] your upload. Greyed cells are genuinely unavailable.", WARN_FILL)
    labels = [f"{label}\n{tag}" if tag else label for label, tag, _, _ in FACT_COLUMNS]
    notes = {
        f"{label}\n{tag}": SOURCE_NOTES.get(tag, "")
        for label, tag, _, _ in FACT_COLUMNS if tag
    }
    _header(ws, 2, labels, notes)

    verdicts = payload.get("verdicts", {})
    for i, (symbol, v) in enumerate(sorted(verdicts.items())):
        r = 3 + i
        for col, (_, tag, path, fmt) in enumerate(FACT_COLUMNS, start=1):
            if path is None:
                _write(ws, r, col, symbol)
                continue
            value = _dig(v, path)
            if value is None:
                fallback = NA_FUND if tag == "[DATA]" else NA
                _write(ws, r, col, fallback)
            else:
                _write(ws, r, col, value, fmt=fmt)
    _autosize(ws, widths={1: 13})


def _agent_sheet(wb, payload: dict) -> None:
    ws = wb.create_sheet("Agent Notes")
    _banner(ws, "AI OPINION — not data. Every cell below is a model's judgement "
                "about the Facts sheet. No number here is a measurement.", OPINION_FILL)
    lenses = ["Technical", "Fundamental", "Sentiment", "Macro"]
    cols = ["Symbol"] + [f"{l} {k}" for l in lenses for k in ("stance", "concern")]
    _header(ws, 2, cols)

    notes = payload.get("agent_notes") or {}
    for i, symbol in enumerate(sorted(payload.get("verdicts", {}))):
        r = 3 + i
        _write(ws, r, 1, symbol)
        per = notes.get(symbol, {})
        for j, lens in enumerate(lenses):
            entry = per.get(lens.lower(), {})
            _write(ws, r, 2 + j * 2, entry.get("stance", "not run"), fill=OPINION_FILL)
            _write(ws, r, 3 + j * 2, entry.get("concern", ""), fill=OPINION_FILL)
    _autosize(ws, widths={1: 13}, cap=44)


def _verdicts_sheet(wb, payload: dict) -> None:
    ws = wb.create_sheet("Verdicts")
    _banner(ws, "Each strategy reads the Facts sheet independently. "
                "Agreement is compared on DIRECTION — exit and trim both mean "
                "'reduce' — so wording differences are not counted as conflict.",
            WARN_FILL)
    runs = payload.get("strategy_runs") or {}
    names = list(runs) or [payload.get("strategy", "baseline")]
    cols = ["Symbol"] + [f"{n} action" for n in names] + \
           [f"{n} why" for n in names] + ["Directions", "Agreement"]
    _header(ws, 2, cols)

    symbols = sorted(payload.get("verdicts", {}))
    for i, symbol in enumerate(symbols):
        r = 3 + i
        _write(ws, r, 1, symbol)
        actions = []
        for j, name in enumerate(names):
            v = (runs.get(name) or {}).get(symbol, {})
            action = v.get("action", "—")
            actions.append(action)
            _write(ws, r, 2 + j, action.upper())
            reasons = v.get("reasons") or []
            _write(ws, r, 2 + len(names) + j, reasons[0] if reasons else "")
        directions = [DIRECTION.get(a, "?") for a in actions]
        _write(ws, r, 2 + 2 * len(names), " / ".join(directions))
        _write(ws, r, 3 + 2 * len(names), _agreement(directions),
               fill=WARN_FILL if len(set(directions)) > 1 else None)
    _autosize(ws, widths={1: 13}, cap=60)


def _agreement(directions: list[str]) -> str:
    unique = set(directions)
    if len(unique) == 1:
        return f"UNANIMOUS — {directions[0]}"
    counts = {d: directions.count(d) for d in unique}
    top, n = max(counts.items(), key=lambda kv: kv[1])
    if n > len(directions) / 2:
        return f"MAJORITY — {top} ({n}/{len(directions)})"
    return "SPLIT — your call"


def _summary_sheet(wb, payload: dict) -> None:
    ws = wb.create_sheet("Summary", 0)
    book = payload.get("book", {})
    totals, bench = book.get("totals", {}), book.get("benchmark", {})
    corr, conc = book.get("correlation", {}), book.get("concentration", {})
    health = payload.get("health", {})

    _write(ws, 1, 1, "Portfolio Report Card", font=TITLE_FONT)
    _write(ws, 2, 1, f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")

    rows = [
        ("Health verdict", health.get("status")),
        ("Market value", totals.get("market_value")),
        ("Invested", totals.get("invested")),
        ("P&L", totals.get("pnl")),
        ("Return %", totals.get("return_pct")),
        (f"vs {bench.get('symbol', 'index')} %", bench.get("benchmark_return_pct")),
        ("Effective bets", corr.get("headline")),
        ("Diversification /100", conc.get("diversification_score")),
        ("Risk level", (book.get("risk") or {}).get("level")),
    ]
    r = 4
    for label, value in rows:
        _write(ws, r, 1, label, font=Font(name=FONT, bold=True))
        _write(ws, r, 2, value if value is not None else NA)
        r += 1

    r += 1
    _write(ws, r, 1, "Why", font=TITLE_FONT)
    r += 1
    for reason in health.get("reasons", []) or ["—"]:
        _write(ws, r, 1, f"• {reason}")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        r += 1

    r += 1
    _write(ws, r, 1, "Do this first", font=TITLE_FONT)
    r += 1
    _header(ws, r, ["#", "Action", "Symbol", "Shares", "Weight →", "P&L", "Stop"])
    r += 1
    rank = 0
    for row in payload.get("action_queue", []):
        if row["action"] == "hold" and not row["shares_delta"]:
            continue
        rank += 1
        _write(ws, r, 1, rank)
        _write(ws, r, 2, row["action"].upper())
        _write(ws, r, 3, row["symbol"])
        _write(ws, r, 4, f"{row['side']} {abs(row['shares_delta'])}"
                         if row["shares_delta"] else "—")
        _write(ws, r, 5, f"{row['current_weight_pct']}% → {row['target_weight_pct']}%")
        _write(ws, r, 6, row.get("pnl_pct"), fmt="0.0")
        _write(ws, r, 7, row.get("stop"), fmt="₹#,##0.00")
        r += 1
    if rank == 0:
        _write(ws, r, 1, "No action — every position held.")
        r += 1

    r += 2
    _write(ws, r, 1,
           "Educational and research use only. AI-generated and can be wrong, "
           "including confidently wrong. Not investment advice and not a "
           "recommendation to buy, sell or hold any security. Consult a "
           "SEBI-registered adviser before acting.",
           font=Font(name=FONT, italic=True, size=9))
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    _autosize(ws, widths={1: 26, 2: 20, 5: 20})


def _provenance_sheet(wb, payload: dict, coverage: dict | None) -> None:
    ws = wb.create_sheet("Provenance")
    _write(ws, 1, 1, "Where every number came from", font=TITLE_FONT)
    r = 3

    synthetic = (payload.get("data_source") or {}).get("synthetic")
    if synthetic:
        cell = _write(ws, r, 1,
                      "⚠ THIS RUN USED SYNTHETIC FIXTURE DATA. Real ticker names, "
                      "generated prices. Nothing here describes a real company.")
        cell.fill = WARN_FILL
        cell.font = Font(name=FONT, bold=True)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        r += 2

    for label, value in (payload.get("data_source") or {}).items():
        _write(ws, r, 1, label, font=Font(name=FONT, bold=True))
        _write(ws, r, 2, str(value))
        r += 1

    if not coverage:
        _autosize(ws, widths={1: 26})
        return

    r += 1
    quotes = coverage.get("quotes", {})
    _write(ws, r, 1, "Quote cache", font=TITLE_FONT)
    r += 1
    for label, value in (("fetched at", quotes.get("fetched_at")),
                         ("age (hours)", quotes.get("age_hours")),
                         ("stale", quotes.get("stale")),
                         ("source", quotes.get("source"))):
        _write(ws, r, 1, label, font=Font(name=FONT, bold=True))
        _write(ws, r, 2, str(value))
        r += 1

    for warning in coverage.get("warnings", []):
        cell = _write(ws, r, 1, f"⚠ {warning}")
        cell.fill = WARN_FILL
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        r += 1

    r += 1
    _write(ws, r, 1, "Per-symbol data coverage", font=TITLE_FONT)
    r += 1
    _header(ws, r, ["Symbol", "Bars", "From", "To", "Live quote",
                    "Fundamentals", "Unsupported measures"])
    r += 1
    for symbol, cov in sorted((coverage.get("per_symbol") or {}).items()):
        _write(ws, r, 1, symbol)
        _write(ws, r, 2, cov["bars"])
        _write(ws, r, 3, cov["first"] or "—")
        _write(ws, r, 4, cov["last"] or "—")
        _write(ws, r, 5, "yes" if cov["has_quote"] else "no")
        _write(ws, r, 6, "yes" if cov["has_fundamentals"] else "no")
        _write(ws, r, 7, ", ".join(cov["missing"]) or "none")
        r += 1
    _autosize(ws, widths={1: 13, 7: 50})


def write_workbook(
    payload: dict,
    path: str,
    prices: dict | None = None,
    coverage: dict | None = None,
) -> str:
    """Build the workbook. Returns the path written."""
    if not AVAILABLE:
        raise RuntimeError(
            "openpyxl is not installed. The analysis core is stdlib-only; only "
            "Excel export needs it. Install with: pip install openpyxl"
        )
    wb = Workbook()
    wb.remove(wb.active)
    _summary_sheet(wb, payload)
    _holdings_sheet(wb, payload, prices or {})
    _facts_sheet(wb, payload, coverage)
    _agent_sheet(wb, payload)
    _verdicts_sheet(wb, payload)
    _provenance_sheet(wb, payload, coverage)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)
    return path
