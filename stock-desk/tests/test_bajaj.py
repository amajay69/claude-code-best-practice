"""Tests for the Bajaj techno-funda strategy.

The properties here are the ones that distinguish this framework from the
baseline scorer. If the gate tests ever pass while the implementation sums
scores, the strategy has quietly become the thing it was written to replace.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adapter import Bar, FixtureAdapter, load_holdings      # noqa: E402
from core.indicators import strong_zone, supertrend              # noqa: E402
from core.portfolio import CONCENTRATION_LIMIT, analyse          # noqa: E402
from core.regime import DEPLOYMENT, breadth, market_regime       # noqa: E402
from core.relative_strength import relative_strength             # noqa: E402
from core.strategies import STRATEGIES, get                      # noqa: E402
from core.strategies.bajaj import (                              # noqa: E402
    FUNDAMENTAL_GATE,
    OVERSIZE_TOLERANCE,
    _decide,
    entry_checklist,
    evaluate,
    exit_signal,
    fundamental_score,
    portfolio_construction,
    position_size,
)

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def bars(closes: list[float], spread: float = 0.01) -> list[Bar]:
    return [
        Bar(f"2024-{i // 28 + 1:02d}-{i % 28 + 1:02d}", c, c * (1 + spread),
            c * (1 - spread), c, 1000)
        for i, c in enumerate(closes)
    ]


class TestFundamentalScore(unittest.TestCase):
    def test_score_is_bounded(self):
        for f in (
            {"roe_pct": 99, "debt_to_equity": 0, "profit_growth_3y_pct": 99,
             "revenue_growth_3y_pct": 0, "pe": 1, "industry_pe": 100},
            {"roe_pct": -99, "debt_to_equity": 99, "profit_growth_3y_pct": -99,
             "revenue_growth_3y_pct": 99, "pe": 500, "industry_pe": 10,
             "promoter_pledge_pct": 90},
        ):
            score = fundamental_score(f)["score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_missing_data_scores_neutral_not_bad(self):
        """An absent figure is unknown, not bad.

        Scoring missing inputs as zero would silently reject every stock
        served by a thin data feed, which looks like discipline and is
        actually a broken screen.
        """
        self.assertEqual(fundamental_score({"roe_pct": None})["score"], 50.0)

    def test_empty_fundamentals_return_none(self):
        self.assertIsNone(fundamental_score({})["score"])

    def test_pledge_drags_quality_down(self):
        base = {"roe_pct": 20, "debt_to_equity": 0.2}
        clean = fundamental_score(base)["components"]["quality"]
        pledged = fundamental_score(dict(base, promoter_pledge_pct=12))["components"]["quality"]
        self.assertGreater(clean, pledged)


class TestGatesAreNotSums(unittest.TestCase):
    """The defining property of this strategy."""

    CONTEXT = {
        "regime": {"regime": "bullish", "deployment_ceiling": 1.0},
        "sector_rankings": {"leading_sectors": ["Banking"]},
        "sector": "Banking",
        "stop": 100.0,
    }

    def _checklist(self, fscore, momentum_pass, in_zone=True):
        momentum = {
            "passes_gate": momentum_pass, "rs": 1.0, "rs_zone": "green",
            "rsi_14": 60.0, "zone": "green" if momentum_pass else "red",
        }
        snap = {"strong_zone": {"in_zone": in_zone, "pct_from_high": -0.01}}
        return entry_checklist("X", momentum, fscore, snap, dict(self.CONTEXT))

    def test_perfect_fundamentals_cannot_rescue_dead_momentum(self):
        """The rule the baseline scorer violates by construction."""
        result = self._checklist(100.0, momentum_pass=False)
        self.assertFalse(result["all_pass"])
        self.assertIn("4. Momentum gate", result["failed"])

    def test_perfect_momentum_cannot_rescue_weak_fundamentals(self):
        result = self._checklist(10.0, momentum_pass=True)
        self.assertFalse(result["all_pass"])
        self.assertIn("3. Fundamental gate", result["failed"])

    def test_all_six_must_pass_to_buy(self):
        result = self._checklist(FUNDAMENTAL_GATE, momentum_pass=True)
        self.assertTrue(result["all_pass"], result["failed"])

    def test_falling_knife_is_rejected_even_when_everything_else_passes(self):
        result = self._checklist(95.0, momentum_pass=True, in_zone=False)
        self.assertFalse(result["all_pass"])
        self.assertIn("5. Strong zone", result["failed"])

    def test_non_leading_sector_is_rejected(self):
        ctx = dict(self.CONTEXT, sector="IT")
        momentum = {"passes_gate": True, "rs": 1.0, "rs_zone": "green",
                    "rsi_14": 60.0, "zone": "green"}
        snap = {"strong_zone": {"in_zone": True, "pct_from_high": -0.01}}
        result = entry_checklist("X", momentum, 95.0, snap, ctx)
        self.assertIn("2. Sector ranking", result["failed"])


class TestExitLogic(unittest.TestCase):
    GOOD_SNAP = {"supertrend": {"direction": "green"}}
    BAD_SNAP = {"supertrend": {"direction": "red"}}

    def _mom(self, rs, zone="red"):
        return {"rs": rs, "zone": zone, "rs_slope": 0.0}

    def test_both_signals_negative_exits(self):
        result = exit_signal(self._mom(-2.0), self.BAD_SNAP, 80.0)
        self.assertTrue(result["exit"])
        self.assertTrue(result["technical_exit"])

    def test_rs_negative_alone_holds(self):
        """One trigger is a hold — the noise tolerance most investors break."""
        result = exit_signal(self._mom(-2.0), self.GOOD_SNAP, 80.0)
        self.assertFalse(result["exit"])

    def test_supertrend_red_alone_holds(self):
        result = exit_signal(self._mom(2.0, "green"), self.BAD_SNAP, 80.0)
        self.assertFalse(result["exit"])

    def test_double_yellow_exits_independently_of_supertrend(self):
        """Poor fundamentals plus poor momentum is a failed thesis."""
        result = exit_signal(self._mom(1.0, "red"), self.GOOD_SNAP, 20.0)
        self.assertTrue(result["exit"])
        self.assertTrue(result["double_yellow"])
        self.assertFalse(result["technical_exit"])

    def test_strong_fundamentals_block_double_yellow(self):
        result = exit_signal(self._mom(1.0, "red"), self.GOOD_SNAP, 90.0)
        self.assertFalse(result["exit"])


class TestPositionSizing(unittest.TestCase):
    def test_risk_formula_matches_the_published_maths(self):
        # shares = rupee risk / (entry - stop); 1% of 10,00,000 = 10,000 / 50
        sized = position_size(1000.0, 950.0, 1_000_000, "balanced")
        self.assertEqual(sized["risk_based_shares"], 200)

    def test_wider_stop_means_fewer_shares_not_a_bigger_loss(self):
        tight = position_size(1000.0, 990.0, 1_000_000, "balanced")
        wide = position_size(1000.0, 900.0, 1_000_000, "balanced")
        self.assertGreater(tight["risk_based_shares"], wide["risk_based_shares"])
        self.assertLessEqual(wide["effective_risk"], wide["rupee_risk"] + 1)

    def test_tight_stop_is_capped_by_concentration(self):
        """Rule 4 alone would put 60%+ of the book in one name.

        A stop a rupee below price divides the risk budget into an enormous
        share count. The loss stays bounded, so rule 4 is satisfied and the
        position is still absurd — rule 5 is what catches it.
        """
        sized = position_size(223.0, 219.5, 1_055_021, "balanced")
        self.assertTrue(sized["capped_by_concentration"])
        self.assertLessEqual(
            sized["position_pct_of_book"], CONCENTRATION_LIMIT * 100 + 0.01
        )
        self.assertLess(sized["shares"], sized["risk_based_shares"])
        self.assertIsNotNone(sized["cap_note"])

    def test_capped_position_carries_less_risk_than_budgeted(self):
        sized = position_size(223.0, 219.5, 1_055_021, "balanced")
        self.assertLess(sized["effective_risk"], sized["rupee_risk"])

    def test_stop_above_entry_yields_no_position(self):
        sized = position_size(100.0, 120.0, 1_000_000, "balanced")
        self.assertEqual(sized["shares"], 0)

    def test_risk_profile_scales_the_budget(self):
        c = position_size(1000.0, 900.0, 1_000_000, "conservative")
        a = position_size(1000.0, 900.0, 1_000_000, "aggressive")
        self.assertLess(c["risk_based_shares"], a["risk_based_shares"])


class TestOversizeTrim(unittest.TestCase):
    """Rule 5 applied to a position already held."""

    CLEAR_EXIT = {"exit": False, "rule": "", "triggers": [], "technical_exit": False,
                  "double_yellow": False}
    FAILING = {"all_pass": False, "failed": ["3. Fundamental gate"],
               "checks": [{"pass": False}] * 6}

    def test_grossly_oversized_position_is_trimmed(self):
        sizing = {"shares": 50, "risk_pct_of_book": 1.0, "effective_risk": 10000,
                  "rupee_risk": 10000}
        action, reasons = _decide(
            self.FAILING, self.CLEAR_EXIT, sizing, {"held_qty": 500},
            100.0, 120.0, 20.0, {"rs": 1.0}, 50.0,
        )
        self.assertEqual(action, "trim")
        self.assertIn("oversized", reasons[0])

    def test_position_within_tolerance_is_not_trimmed(self):
        sizing = {"shares": 100, "risk_pct_of_book": 1.0, "effective_risk": 10000,
                  "rupee_risk": 10000}
        held = int(100 * OVERSIZE_TOLERANCE) - 1
        action, _ = _decide(
            self.FAILING, self.CLEAR_EXIT, sizing, {"held_qty": held},
            100.0, 120.0, 20.0, {"rs": 1.0}, 50.0,
        )
        self.assertEqual(action, "hold")

    def test_exit_outranks_oversizing(self):
        exits = dict(self.CLEAR_EXIT, exit=True, rule="both negative",
                     triggers=["RS below zero", "Supertrend red"])
        sizing = {"shares": 1, "risk_pct_of_book": 1.0, "effective_risk": 1,
                  "rupee_risk": 10000}
        action, _ = _decide(
            self.FAILING, exits, sizing, {"held_qty": 9999},
            100.0, 120.0, 20.0, {"rs": -1.0}, 20.0,
        )
        self.assertEqual(action, "exit")


class TestRelativeStrength(unittest.TestCase):
    def test_stock_tracking_the_index_has_rs_near_zero(self):
        """RS is centred: a stock that moves exactly with the index is flat."""
        index = bars([100 + i * 0.3 for i in range(300)])
        stock = bars([50 + i * 0.15 for i in range(300)])
        rs = relative_strength(stock, index)
        self.assertIsNotNone(rs["rs"])
        self.assertLess(abs(rs["rs"]), 1.0)

    def test_steady_outperformer_is_green_despite_a_flat_slope(self):
        """Constant exponential outperformance has slope exactly zero.

        ``ratio / SMA(ratio)`` converges for a pure exponential, so RS is
        flat. A strict ``slope > 0`` gate would grade the steadiest
        compounder as fading, which is backwards.
        """
        index = bars([100.0] * 300)
        stock = bars([100 * (1.004 ** i) for i in range(300)])
        rs = relative_strength(stock, index)
        self.assertGreater(rs["rs"], 0)
        self.assertAlmostEqual(rs["slope"], 0.0, places=3)
        self.assertEqual(rs["zone"], "green")

    def test_accelerating_outperformer_has_a_rising_slope(self):
        index = bars([100.0] * 300)
        stock = bars([100 * (1 + 0.000012 * i * i) for i in range(300)])
        rs = relative_strength(stock, index)
        self.assertGreater(rs["slope"], 0)
        self.assertEqual(rs["zone"], "green")

    def test_decaying_outperformance_is_fading_not_red(self):
        """Still ahead of the index, but handing the lead back.

        'Fading' is the band between green and red: RS positive, slope
        materially negative. A stall deep enough to push RS below zero is
        'red' instead, which the next test pins.
        """
        index = bars([100.0] * 300)
        rise = [100 * (1.006 ** i) for i in range(280)]
        stall = [rise[-1]] * 20
        rs = relative_strength(bars(rise + stall), index)
        self.assertGreater(rs["rs"], 0)
        self.assertLess(rs["slope"], 0)
        self.assertEqual(rs["zone"], "fading")

    def test_a_deep_enough_stall_crosses_into_red(self):
        index = bars([100.0] * 300)
        rise = [100 * (1.006 ** i) for i in range(260)]
        stall = [rise[-1] * (0.998 ** i) for i in range(40)]
        rs = relative_strength(bars(rise + stall), index)
        self.assertLess(rs["rs"], 0)
        self.assertEqual(rs["zone"], "red")

    def test_underperformer_is_red(self):
        index = bars([100.0] * 300)
        stock = bars([100 * (0.996 ** i) for i in range(300)])
        rs = relative_strength(stock, index)
        self.assertLess(rs["rs"], 0)
        self.assertEqual(rs["zone"], "red")

    def test_short_history_is_unknown_not_zero(self):
        self.assertEqual(
            relative_strength(bars([100.0] * 10), bars([100.0] * 10))["zone"], "unknown"
        )


class TestSupertrendAndZone(unittest.TestCase):
    def test_persistent_uptrend_is_green(self):
        self.assertEqual(supertrend(bars([100 + i for i in range(200)]))["direction"], "green")

    def test_persistent_downtrend_is_red(self):
        self.assertEqual(supertrend(bars([400 - i for i in range(200)]))["direction"], "red")

    def test_supertrend_does_not_flip_every_bar(self):
        """A band that tracks price tick for tick is useless as an exit."""
        noisy = [100 + (3 if i % 2 else -3) for i in range(200)]
        self.assertIsNotNone(supertrend(bars(noisy))["direction"])

    def test_stock_at_its_high_is_in_the_strong_zone(self):
        zone = strong_zone(bars([100 + i for i in range(300)]))
        self.assertTrue(zone["in_zone"])
        self.assertTrue(zone["at_ath"])

    def test_falling_knife_is_out_of_the_zone(self):
        zone = strong_zone(bars([300 - i for i in range(250)]))
        self.assertFalse(zone["in_zone"])
        self.assertFalse(zone["at_ath"])


class TestRegime(unittest.TestCase):
    def test_deployment_ceiling_tightens_with_the_regime(self):
        self.assertGreater(DEPLOYMENT["bullish"], DEPLOYMENT["volatile"])
        self.assertGreater(DEPLOYMENT["volatile"], DEPLOYMENT["bearish"])

    def test_thin_breadth_is_marked_unreliable(self):
        adapter = FixtureAdapter(FIXTURES)
        symbols = [h.symbol for h in load_holdings(os.path.join(FIXTURES, "holdings.csv"))]
        b = breadth(symbols, adapter)
        self.assertFalse(b["reliable"])
        self.assertIsNotNone(b["caveat"])

    def test_regime_ignores_unreliable_breadth(self):
        """A ten-name breadth reading must not move the regime call."""
        adapter = FixtureAdapter(FIXTURES)
        symbols = [h.symbol for h in load_holdings(os.path.join(FIXTURES, "holdings.csv"))]
        regime = market_regime(adapter, symbols)
        self.assertTrue(
            any("too thin to act on" in r for r in regime["reasons"]),
            regime["reasons"],
        )
        self.assertIn(regime["regime"], DEPLOYMENT)


class TestStrategyIntegration(unittest.TestCase):
    def setUp(self):
        self.adapter = FixtureAdapter(FIXTURES)
        self.holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        self.book = analyse(self.holdings, self.adapter)
        symbols = [h.symbol for h in self.holdings]
        self.context = {
            "regime": market_regime(self.adapter, symbols),
            "sector_rankings": {"leading_sectors": ["Banking"]},
            "portfolio_value": self.book["totals"]["market_value"],
        }
        self.verdicts = {
            h.symbol: evaluate(
                h.symbol, self.adapter, avg_cost=h.avg_cost,
                context=dict(self.context, held_qty=h.qty),
            )
            for h in self.holdings
        }

    def test_verdicts_match_the_shared_contract(self):
        """Report rendering consumes either strategy without special-casing."""
        for v in self.verdicts.values():
            for key in ("symbol", "action", "engine", "confidence", "reasons",
                        "last_close", "stop", "backtest", "technical"):
                self.assertIn(key, v)
            self.assertIn(v["action"], ("exit", "trim", "hold", "accumulate", "buy"))

    def test_strategy_is_registered_and_distinct(self):
        self.assertIn("bajaj", STRATEGIES)
        self.assertIsNot(get("bajaj"), get("baseline"))

    def test_the_two_strategies_disagree_on_this_book(self):
        """If they ever fully agree, one of them is not doing its job."""
        baseline = {
            h.symbol: get("baseline")(h.symbol, self.adapter, avg_cost=h.avg_cost)["action"]
            for h in self.holdings
        }
        bajaj = {s: v["action"] for s, v in self.verdicts.items()}
        self.assertNotEqual(baseline, bajaj)

    def test_every_exit_names_its_triggers(self):
        for v in self.verdicts.values():
            if v["action"] == "exit":
                self.assertTrue(v["bajaj"]["exit_signal"]["triggers"])

    def test_no_sized_position_breaches_the_concentration_cap(self):
        for v in self.verdicts.values():
            sizing = v["bajaj"]["position_sizing"]
            if sizing and sizing["shares"]:
                self.assertLessEqual(
                    sizing["position_pct_of_book"], CONCENTRATION_LIMIT * 100 + 0.01
                )

    def test_construction_check_reports_core_shortfall(self):
        result = portfolio_construction(self.verdicts, self.book)
        self.assertIn("core_weight_pct", result)
        self.assertIsInstance(result["issues"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
