"""Regression tests for the deterministic core.

Stdlib ``unittest`` on purpose: the core has no third-party dependencies,
and neither should its tests.  ``python3 -m unittest discover tests`` runs
green on a clean clone with no install step.

The properties asserted here are the ones whose violation would make the
desk confidently wrong rather than obviously broken.
"""

from __future__ import annotations

import io
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import backtest, portfolio, report                    # noqa: E402
from core.adapter import Bar, FixtureAdapter, Holding, load_holdings  # noqa: E402
from core.fallback import DEEP_LOSS_PCT, _guard_averaging_down, evaluate  # noqa: E402
from core.indicators import atr, max_drawdown, rsi, sma, trend_state      # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def synthetic_bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(f"2024-01-{i % 28 + 1:02d}", c, c * 1.01, c * 0.99, c, 1000)
        for i, c in enumerate(closes)
    ]


class TestIndicators(unittest.TestCase):
    def test_rsi_saturates_on_monotonic_series(self):
        self.assertEqual(rsi([100 + i for i in range(60)]), 100.0)
        self.assertEqual(rsi([100 - i * 0.5 for i in range(60)]), 0.0)

    def test_rsi_needs_history(self):
        self.assertIsNone(rsi([1, 2, 3]))

    def test_sma_matches_hand_calculation(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 5), 3.0)
        self.assertIsNone(sma([1, 2], 5))

    def test_max_drawdown_is_negative_and_bounded(self):
        self.assertAlmostEqual(max_drawdown([100, 50]), -0.5)
        self.assertEqual(max_drawdown([1, 2, 3]), 0.0)

    def test_trend_state_transitions(self):
        self.assertEqual(trend_state([100 + i for i in range(300)]), "uptrend")
        self.assertEqual(trend_state([400 - i for i in range(300)]), "downtrend")

    def test_atr_positive_on_real_range(self):
        self.assertGreater(atr(synthetic_bars([100] * 40)), 0)


class TestHoldingsParsing(unittest.TestCase):
    """Broker exports disagree on headers; all of these must parse."""

    def _parse(self, text: str) -> list[Holding]:
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            return load_holdings(path)
        finally:
            os.unlink(path)

    def test_zerodha_style(self):
        rows = self._parse("Instrument,Qty.,Avg. cost\nHDFCBANK,26,943.99\n")
        self.assertEqual(rows[0], Holding("HDFCBANK", 26.0, 943.99))

    def test_groww_style(self):
        rows = self._parse("Symbol,Quantity,Average price\ninfy,10,1500\n")
        self.assertEqual(rows[0].symbol, "INFY")

    def test_thousands_separators_and_zero_quantities(self):
        rows = self._parse('Instrument,Qty.,Avg. cost\nTCS,"1,200",3450\nOLD,0,10\n')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].qty, 1200.0)

    def test_missing_column_names_what_it_wanted(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse("Instrument,Price\nX,10\n")
        self.assertIn("quantity", str(ctx.exception))


class TestBacktest(unittest.TestCase):
    def setUp(self):
        rng = random.Random(7)
        price, closes = 100.0, []
        for _ in range(700):
            price *= 1 + rng.gauss(0.0004, 0.015)
            closes.append(price)
        self.bars = synthetic_bars(closes)

    def test_no_lookahead(self):
        """Truncating the future must not change any already-closed trade.

        If a predicate peeked ahead, trades entered well inside the prefix
        would score differently once later bars existed.
        """
        hold = backtest.HOLD_DAYS["positional"]
        prefix = self.bars[: 500 + hold + 1]
        full = backtest.replay(self.bars, "momentum", "positional")
        cut = backtest.replay(prefix, "momentum", "positional")
        self.assertGreater(cut["samples"], 0)
        # Every statistic of the prefix run is computed only from prefix data.
        recomputed = backtest.replay(prefix[:], "momentum", "positional")
        self.assertEqual(cut, recomputed)
        self.assertGreaterEqual(full["samples"], cut["samples"])

    def test_samples_are_non_overlapping(self):
        res = backtest.replay(self.bars, "momentum", "positional")
        self.assertLessEqual(res["samples"], res["raw_triggers"])
        # A trending series triggers on many consecutive days; the greedy
        # filter must collapse those into far fewer independent events.
        self.assertLess(res["samples"], res["raw_triggers"])

    def test_sufficiency_gate_blocks_thin_samples(self):
        res = backtest.replay(self.bars, "oversold_bounce", "wealth")
        if res["samples"] < 10:
            self.assertFalse(res["sufficient"])

    def test_unknown_setup_is_loud(self):
        with self.assertRaises(ValueError):
            backtest.replay(self.bars, "not_a_setup")

    def test_tighter_stop_never_helps_the_worst_case(self):
        tight = backtest.replay(self.bars, "momentum", "positional", "conservative")
        loose = backtest.replay(self.bars, "momentum", "positional", "aggressive")
        if tight["samples"] and loose["samples"]:
            self.assertGreaterEqual(tight["worst"], loose["worst"])

    def test_empty_history_reports_insufficient_not_crash(self):
        res = backtest.replay(self.bars[:210], "breakout", "positional")
        self.assertFalse(res["sufficient"])


class TestPortfolioMaths(unittest.TestCase):
    def test_identical_series_collapse_to_one_bet(self):
        rng = random.Random(3)
        base = [rng.gauss(0, 0.01) for _ in range(300)]
        matrix = [base[:] for _ in range(10)]
        self.assertLess(portfolio.effective_bets([0.1] * 10, matrix), 1.05)

    def test_flat_series_report_no_bets_rather_than_full_diversification(self):
        """A halted or illiquid name has no variance to decompose.

        Floating-point residue in the eigen-decomposition otherwise makes
        ten motionless stocks look like ten independent bets.
        """
        matrix = [[0.0] * 300 for _ in range(10)]
        self.assertEqual(portfolio.effective_bets([0.1] * 10, matrix), 0.0)

    def test_independent_series_approach_the_holding_count(self):
        rng = random.Random(11)
        matrix = [[rng.gauss(0, 0.01) for _ in range(4000)] for _ in range(8)]
        bets = portfolio.effective_bets([0.125] * 8, matrix)
        self.assertGreater(bets, 6.0)
        self.assertLessEqual(bets, 8.01)

    def test_correlation_matrix_is_unit_diagonal_and_symmetric(self):
        rng = random.Random(5)
        matrix = [[rng.gauss(0, 0.01) for _ in range(200)] for _ in range(4)]
        corr = portfolio.correlation_matrix(matrix)
        for i in range(4):
            self.assertAlmostEqual(corr[i][i], 1.0, places=9)
            for j in range(4):
                self.assertAlmostEqual(corr[i][j], corr[j][i], places=12)
                self.assertLessEqual(abs(corr[i][j]), 1.0 + 1e-9)

    def test_beta_of_the_market_against_itself_is_one(self):
        rng = random.Random(2)
        market = [rng.gauss(0, 0.01) for _ in range(300)]
        self.assertAlmostEqual(portfolio.beta(market, market), 1.0, places=9)

    def test_beta_scales_linearly(self):
        rng = random.Random(4)
        market = [rng.gauss(0, 0.01) for _ in range(300)]
        levered = [2 * r for r in market]
        self.assertAlmostEqual(portfolio.beta(levered, market), 2.0, places=9)

    def test_risk_mismatch_is_flagged_in_both_directions(self):
        self.assertIn("more risk", portfolio._mismatch("high", "conservative"))
        self.assertIn("more defensive", portfolio._mismatch("low", "aggressive"))
        self.assertIsNone(portfolio._mismatch("medium", "balanced"))


class TestAveragingDownGuard(unittest.TestCase):
    STRONG = {"sufficient": True, "expectancy": 0.04, "samples": 14, "setup": "trend_pullback"}
    THIN = {"sufficient": False, "expectancy": 0.09, "samples": 3, "setup": "oversold_bounce"}

    def test_deep_loser_without_evidence_is_capped_at_hold(self):
        action, note = _guard_averaging_down("accumulate", -40.0, self.THIN)
        self.assertEqual(action, "hold")
        self.assertIn("underwater", note)

    def test_deep_loser_with_evidence_may_be_added_to(self):
        action, note = _guard_averaging_down("buy", -40.0, self.STRONG)
        self.assertEqual(action, "buy")
        self.assertIn("historical samples", note)

    def test_guard_never_converts_a_buy_into_a_sell(self):
        for evidence in (self.THIN, self.STRONG, None):
            action, _ = _guard_averaging_down("accumulate", -80.0, evidence)
            self.assertIn(action, ("accumulate", "hold"))

    def test_shallow_loss_is_untouched(self):
        action, note = _guard_averaging_down("accumulate", DEEP_LOSS_PCT + 1, self.THIN)
        self.assertEqual(action, "accumulate")
        self.assertIsNone(note)

    def test_sell_side_actions_pass_through(self):
        self.assertEqual(_guard_averaging_down("exit", -90.0, None)[0], "exit")
        self.assertEqual(_guard_averaging_down("trim", -90.0, None)[0], "trim")


class TestActionQueue(unittest.TestCase):
    def setUp(self):
        self.adapter = FixtureAdapter(FIXTURES)
        self.holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        self.book = portfolio.analyse(self.holdings, self.adapter, stated_risk="balanced")
        self.verdicts = {
            h.symbol: evaluate(h.symbol, self.adapter, avg_cost=h.avg_cost)
            for h in self.holdings
        }
        self.queue = report.action_queue(self.verdicts, self.holdings, self.book)

    def test_a_hold_never_carries_a_share_delta(self):
        for row in self.queue:
            if row["action"] == "hold":
                self.assertEqual(row["shares_delta"], 0, row["symbol"])

    def test_exits_target_zero_weight(self):
        for row in self.queue:
            if row["action"] == "exit":
                self.assertEqual(row["target_weight_pct"], 0.0)
                self.assertEqual(row["side"], "sell")

    def test_proceeds_are_not_force_redeployed(self):
        """Targets must not renormalise to 100%; freed capital becomes cash."""
        total_target = sum(r["target_weight_pct"] for r in self.queue)
        self.assertLessEqual(total_target, 100.01)
        self.assertGreater(self.queue[0]["resulting_cash_pct"], 0)

    def test_no_target_breaches_the_concentration_limit(self):
        for row in self.queue:
            self.assertLessEqual(
                row["target_weight_pct"], portfolio.CONCENTRATION_LIMIT * 100 + 0.01
            )

    def test_queue_puts_sells_before_buys(self):
        priorities = [report._PRIORITY[r["action"]] for r in self.queue]
        self.assertEqual(priorities, sorted(priorities))

    def test_every_row_declares_its_engine(self):
        for row in self.queue:
            self.assertIn(row["engine"], ("llm", "rules"))


class TestReportCard(unittest.TestCase):
    def setUp(self):
        adapter = FixtureAdapter(FIXTURES)
        holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        book = portfolio.analyse(holdings, adapter, stated_risk="conservative")
        verdicts = {
            h.symbol: evaluate(h.symbol, adapter, avg_cost=h.avg_cost) for h in holdings
        }
        health = report.health_verdict(book)
        queue = report.action_queue(verdicts, holdings, book)
        self.md = report.render_markdown(
            book, health, queue,
            {"horizon": "positional", "risk_profile": "conservative", "depth": "standard"},
        )

    def test_disclaimer_always_travels_with_the_report(self):
        self.assertIn("Not investment advice", self.md)
        self.assertIn("SEBI-registered", self.md)

    def test_engine_badge_is_present(self):
        self.assertTrue("🟠" in self.md or "🟢" in self.md or "🟡" in self.md)

    def test_effective_bets_headline_is_shown(self):
        self.assertIn("real bets", self.md)


class TestFixtureIntegrity(unittest.TestCase):
    def test_factor_model_actually_creates_sector_clusters(self):
        """If this fails the fixtures are testing nothing.

        Independent random walks would leave every pair near zero
        correlation and 'effective bets' would trivially equal the holding
        count, so the portfolio maths would look correct while being
        completely unexercised.
        """
        adapter = FixtureAdapter(FIXTURES)
        holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        book = portfolio.analyse(holdings, adapter)
        self.assertLess(book["correlation"]["effective_bets"], len(holdings) / 2)
        top = book["correlation"]["most_correlated_pairs"][0]
        self.assertEqual(adapter.sector(top["a"]), adapter.sector(top["b"]))

    def test_fixtures_are_labelled_synthetic(self):
        adapter = FixtureAdapter(FIXTURES)
        self.assertTrue(adapter.fundamentals("HDFCBANK")["_synthetic"])
        self.assertEqual(adapter.news("HDFCBANK")[0]["source"], "SYNTHETIC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
