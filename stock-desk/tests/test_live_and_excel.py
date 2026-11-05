"""Tests for live data intake, history import and the Excel export.

This is where bad data gets in. Every indicator, backtest and correlation
downstream inherits whatever these modules accept, so the tests here are
weighted toward *rejecting and flagging* rather than toward happy paths.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import excel                                           # noqa: E402
from core.adapter import load_holdings                           # noqa: E402
from core.live import QuoteCache, LiveAdapter, read_history      # noqa: E402
from core.portfolio import analyse                               # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import import_history                                            # noqa: E402


def write_csv(path: str, header: list[str], rows: list[list]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def series(n: int, start: float = 100.0, split_at: int | None = None) -> list[list]:
    rows, px = [], start
    day = datetime(2024, 1, 1)
    for i in range(n):
        px *= 1.001
        if split_at is not None and i == split_at:
            px /= 2
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append([day.date().isoformat(), round(px * 0.999, 2), round(px * 1.005, 2),
                     round(px * 0.995, 2), round(px, 2), 100000])
        day += timedelta(days=1)
    return rows


class TestHistoryImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _load(self, header, rows, name="X.csv"):
        path = os.path.join(self.tmp, name)
        write_csv(path, header, rows)
        return import_history.load(path)

    def test_tradingview_headers(self):
        rows, _ = self._load(["time", "open", "high", "low", "close", "Volume"], series(30))
        self.assertEqual(len(rows), 30)

    def test_broker_headers_with_different_spellings(self):
        src = [[r[0], r[4]] for r in series(30)]
        rows, _ = self._load(["Date", "Price"], src)
        self.assertEqual(len(rows), 30)
        # A close-only export collapses OHLC to the close rather than inventing it.
        self.assertEqual(rows[0]["open"], rows[0]["close"])

    def test_split_is_detected(self):
        """The single most damaging thing a price file can hide."""
        _, notes = self._load(
            ["date", "open", "high", "low", "close", "volume"], series(60, split_at=30)
        )
        self.assertTrue(any("beyond" in n for n in notes), notes)
        self.assertTrue(any("unadjusted" in n for n in notes))

    def test_clean_series_raises_no_split_warning(self):
        _, notes = self._load(["date", "open", "high", "low", "close", "volume"], series(60))
        self.assertFalse(any("beyond" in n for n in notes), notes)

    def test_duplicate_dates_are_collapsed(self):
        rows = series(10)
        rows.append(rows[-1])
        parsed, notes = self._load(["date", "open", "high", "low", "close", "volume"], rows)
        self.assertEqual(len(parsed), 10)
        self.assertTrue(any("duplicate" in n for n in notes))

    def test_rows_are_sorted_ascending(self):
        rows = list(reversed(series(20)))
        parsed, _ = self._load(["date", "open", "high", "low", "close", "volume"], rows)
        self.assertEqual(parsed, sorted(parsed, key=lambda r: r["date"]))

    def test_short_history_is_flagged(self):
        _, notes = self._load(["date", "open", "high", "low", "close", "volume"], series(40))
        self.assertTrue(any("200-DMA" in n for n in notes))

    def test_inconsistent_ohlc_is_flagged(self):
        bad = [["2024-01-01", 100, 90, 110, 100, 1000]]      # high<low
        _, notes = self._load(["date", "open", "high", "low", "close", "volume"], bad)
        self.assertTrue(any("inconsistent OHLC" in n for n in notes))

    def test_indian_date_and_thousands_formats(self):
        rows, _ = self._load(["Date", "Price"], [["05-11-2026", "1,234.50"]])
        self.assertEqual(rows[0]["date"], "2026-11-05")
        self.assertEqual(rows[0]["close"], 1234.50)

    def test_volume_suffixes(self):
        rows, _ = self._load(["Date", "Price", "Vol."], [["2024-01-01", "100", "1.5M"]])
        self.assertEqual(rows[0]["volume"], 1_500_000)

    def test_missing_close_column_is_a_loud_failure(self):
        with self.assertRaises(ValueError):
            self._load(["Date", "Volume"], [["2024-01-01", 100]])

    def test_symbol_extracted_from_tradingview_filename(self):
        self.assertEqual(import_history.symbol_from_path("NSE_HDFCBANK, 1D.csv"), "HDFCBANK")
        self.assertEqual(import_history.symbol_from_path("/x/TCS.csv"), "TCS")


class TestQuoteCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "quotes.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, fetched_at: str, quotes: dict):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": fetched_at, "source": "test", "quotes": quotes}, fh)

    def test_missing_file_is_empty_not_an_error(self):
        cache = QuoteCache(os.path.join(self.tmp, "nope.json"))
        self.assertFalse(cache)
        self.assertTrue(cache.stale)

    def test_fresh_quotes_are_not_stale(self):
        self._write(datetime.now(timezone.utc).isoformat(), {"X": {"lastTradedPrice": 10}})
        self.assertFalse(QuoteCache(self.path).stale)

    def test_old_quotes_are_stale_and_say_so(self):
        old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        self._write(old, {"X": {"lastTradedPrice": 10}})
        cache = QuoteCache(self.path)
        self.assertTrue(cache.stale)
        self.assertIn("stale", cache.status()["note"])

    def test_quote_becomes_a_bar_only_when_ohlc_is_complete(self):
        self._write(datetime.now(timezone.utc).isoformat(), {
            "FULL": {"openPrice": 10, "highPrice": 11, "lowPrice": 9,
                     "lastTradedPrice": 10.5, "volume": 100,
                     "latestTimestamp": "2026-11-05 16:00:28"},
            "PARTIAL": {"lastTradedPrice": 10.5, "latestTimestamp": "2026-11-05 16:00:28"},
        })
        cache = QuoteCache(self.path)
        self.assertIsNotNone(cache.as_bar("FULL"))
        self.assertIsNone(cache.as_bar("PARTIAL"))


class TestLiveAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.hist = os.path.join(self.tmp, "history")
        for sym in ("AAA", "BBB"):
            write_csv(os.path.join(self.hist, f"{sym}.csv"),
                      ["date", "open", "high", "low", "close", "volume"], series(300))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_history_is_read(self):
        self.assertEqual(len(LiveAdapter(self.tmp).prices("AAA", 0)), 300)

    def test_missing_stock_history_raises_with_the_fix_in_the_message(self):
        with self.assertRaises(KeyError) as ctx:
            LiveAdapter(self.tmp).prices("ZZZ", 0)
        self.assertIn("import_history.py", str(ctx.exception))

    def test_missing_benchmark_degrades_rather_than_raising(self):
        """A user can export their holdings and forget the index."""
        self.assertEqual(LiveAdapter(self.tmp).benchmark(0), [])

    def test_benchmark_filename_tolerates_the_space(self):
        write_csv(os.path.join(self.hist, "NIFTY50.csv"),
                  ["date", "open", "high", "low", "close", "volume"], series(300))
        self.assertEqual(len(LiveAdapter(self.tmp).benchmark(0)), 300)

    def test_live_quote_appends_only_when_newer(self):
        bars = read_history(os.path.join(self.hist, "AAA.csv"))
        older = bars[-1].date
        with open(os.path.join(self.tmp, "quotes.json"), "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "quotes": {"AAA": {"openPrice": 1, "highPrice": 2, "lowPrice": 1,
                                          "lastTradedPrice": 1.5, "volume": 5,
                                          "latestTimestamp": f"{older} 16:00:00"}}}, fh)
        # Same date as the last settled bar: must not overwrite it.
        self.assertEqual(len(LiveAdapter(self.tmp).prices("AAA", 0)), 300)

    def test_last_price_names_its_source(self):
        price, source = LiveAdapter(self.tmp).last_price("AAA")
        self.assertIsNotNone(price)
        self.assertIn("history", source)

    def test_coverage_reports_what_is_unsupported(self):
        write_csv(os.path.join(self.hist, "SHORT.csv"),
                  ["date", "open", "high", "low", "close", "volume"], series(30))
        cov = LiveAdapter(self.tmp).coverage("SHORT")
        self.assertIn("sma_200_trend", cov["missing"])
        self.assertIn("backtest", cov["missing"])
        self.assertFalse(cov["supports"]["sma_50"])

    def test_report_warns_about_unadjusted_prices(self):
        report = LiveAdapter(self.tmp).report(["AAA", "BBB"])
        self.assertTrue(any("split-adjusted" in w for w in report["warnings"]))

    def test_analyse_survives_a_missing_benchmark(self):
        from core.adapter import Holding
        adapter = LiveAdapter(self.tmp)
        book = analyse([Holding("AAA", 10, 100.0), Holding("BBB", 5, 100.0)], adapter)
        self.assertFalse(book["benchmark"]["available"])
        self.assertIsNone(book["benchmark"]["beating_index"])
        self.assertIsNotNone(book["correlation"]["effective_bets"])


@unittest.skipUnless(excel.AVAILABLE, "openpyxl not installed")
class TestExcelExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "wb.xlsx")
        self.payload = {
            "holdings": [{"symbol": "AAA", "qty": 10, "avg_cost": 90.0}],
            "book": {"totals": {"market_value": 1000, "invested": 900, "pnl": 100,
                                "return_pct": 11.1, "holdings": 1},
                     "weights": {"AAA": 1.0},
                     "benchmark": {"symbol": "NIFTY 50"},
                     "correlation": {"headline": "1 stock ≈ 1.0 real bets"},
                     "concentration": {"diversification_score": 0},
                     "risk": {"level": "medium"}},
            "health": {"status": "Needs attention", "reasons": ["single holding"]},
            "action_queue": [],
            "verdicts": {"AAA": {"last_close": 100.0, "technical": {"trend": "uptrend"},
                                 "backtest": {}}},
            "strategy_runs": {"baseline": {"AAA": {"action": "hold", "reasons": ["r"]}},
                              "bajaj": {"AAA": {"action": "exit", "reasons": ["r"]}}},
            "data_source": {"adapter": "LiveAdapter", "synthetic": False},
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_sheet_is_present(self):
        excel.write_workbook(self.payload, self.path, prices={"AAA": (100.0, "NSE live")})
        from openpyxl import load_workbook
        wb = load_workbook(self.path)
        self.assertEqual(wb.sheetnames,
                         ["Summary", "Holdings", "Facts", "Agent Notes",
                          "Verdicts", "Provenance"])

    def test_gaps_are_written_as_na_never_blank(self):
        """A blank cell invites the reader to assume zero."""
        excel.write_workbook(self.payload, self.path, prices={"AAA": (100.0, "NSE live")})
        from openpyxl import load_workbook
        ws = load_workbook(self.path)["Facts"]
        values = [ws.cell(3, c).value for c in range(1, ws.max_column + 1)]
        self.assertNotIn(None, values)
        self.assertTrue(any(str(v).startswith("n/a") for v in values))

    def test_money_cells_are_formulas_not_frozen_numbers(self):
        excel.write_workbook(self.payload, self.path, prices={"AAA": (100.0, "NSE live")})
        from openpyxl import load_workbook
        ws = load_workbook(self.path)["Holdings"]
        self.assertTrue(str(ws["H3"].value).startswith("="))
        self.assertTrue(str(ws["I3"].value).startswith("="))

    def test_directional_agreement_treats_exit_and_trim_as_one(self):
        self.assertEqual(excel._agreement(["reduce", "reduce"]), "UNANIMOUS — reduce")
        self.assertIn("SPLIT", excel._agreement(["reduce", "add"]))
        self.assertIn("MAJORITY", excel._agreement(["hold", "hold", "add"]))
        self.assertEqual(excel.DIRECTION["exit"], excel.DIRECTION["trim"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
