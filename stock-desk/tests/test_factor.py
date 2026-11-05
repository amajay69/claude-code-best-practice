"""Tests for the cross-sectional factor strategy.

The properties here guard the two things that make a factor model on a
small, self-selected book dangerous: standardisation manufactures a bottom
quintile whether or not one is deserved, and ten-name statistics do not
support confident calls.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adapter import FixtureAdapter, load_holdings            # noqa: E402
from core.factors import (                                        # noqa: E402
    DEFAULT_WEIGHTS,
    MIN_UNIVERSE,
    _zscores,
    book_tilt,
    factor_model,
)
from core.portfolio import analyse                                # noqa: E402
from core.strategies import STRATEGIES, get                       # noqa: E402
from core.strategies.factor import (                              # noqa: E402
    BOTTOM_Z,
    FLOORS,
    build_context,
    evaluate,
    failed_floors,
)

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


class TestStandardisation(unittest.TestCase):
    def test_zscores_centre_on_zero(self):
        scores, meta = _zscores({"A": 1.0, "B": 2.0, "C": 3.0})
        self.assertAlmostEqual(sum(scores.values()), 0.0, places=9)
        self.assertEqual(meta["n"], 3)

    def test_identical_values_carry_no_information(self):
        """Zero dispersion must not divide by zero into infinite conviction."""
        scores, meta = _zscores({"A": 5.0, "B": 5.0, "C": 5.0})
        self.assertEqual(set(scores.values()), {0.0})
        self.assertEqual(meta["stdev"], 0.0)

    def test_missing_values_score_the_mean_not_the_floor(self):
        """Dropping a symbol would change the universe others are measured against."""
        scores, _ = _zscores({"A": 1.0, "B": 3.0, "C": None})
        self.assertEqual(scores["C"], 0.0)

    def test_single_value_is_not_standardisable(self):
        scores, meta = _zscores({"A": 1.0, "B": None})
        self.assertEqual(scores["A"], 0.0)
        self.assertIsNone(meta["mean"])


class TestWithinBookTrap(unittest.TestCase):
    """The failure mode that makes factor models on your own book misleading."""

    def setUp(self):
        self.adapter = FixtureAdapter(FIXTURES)
        self.holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        self.symbols = [h.symbol for h in self.holdings]
        self.model = factor_model(self.symbols, self.adapter)

    def test_small_universe_is_flagged_unreliable(self):
        self.assertFalse(self.model["reliable"])
        self.assertIsNotNone(self.model["caveat"])
        self.assertIn("WITHIN your own book", self.model["caveat"])

    def test_every_verdict_declares_within_book_only(self):
        ctx = build_context(self.symbols, self.adapter, analyse(self.holdings, self.adapter))
        for h in self.holdings:
            v = evaluate(h.symbol, self.adapter, avg_cost=h.avg_cost, context=ctx)
            self.assertTrue(v["factor"]["within_book_only"])

    def test_ranking_always_produces_a_bottom_even_when_all_are_strong(self):
        """Proof the rank alone cannot mean 'bad'.

        Standardisation guarantees a worst-ranked name in any book. If a low
        rank alone triggered a sell, the strategy would recommend selling
        something on every run forever.
        """
        scores, _ = _zscores({"A": 90.0, "B": 92.0, "C": 95.0})
        self.assertLess(min(scores.values()), 0)

    def test_confidence_is_halved_on_an_unreliable_universe(self):
        ctx = build_context(self.symbols, self.adapter, analyse(self.holdings, self.adapter))
        for h in self.holdings:
            v = evaluate(h.symbol, self.adapter, avg_cost=h.avg_cost, context=ctx)
            self.assertLessEqual(v["confidence"], 0.575)


class TestAbsoluteFloors(unittest.TestCase):
    """Rank says 'worst you own'; floors say 'bad in its own right'."""

    def test_floors_are_independent_of_rank(self):
        self.assertEqual(failed_floors({"momentum": -0.2, "quality": 10, "value": 0.05}),
                         ["momentum"])
        self.assertEqual(failed_floors({"momentum": 0.2, "quality": 10, "value": 0.05}), [])

    def test_missing_raw_value_does_not_fail_a_floor(self):
        self.assertEqual(failed_floors({"momentum": None, "quality": None, "value": None}), [])

    def test_expensive_stock_fails_the_value_floor(self):
        # earnings yield below 2% == PE above 50
        self.assertIn("value", failed_floors({"value": 0.015}))
        self.assertNotIn("value", failed_floors({"value": FLOORS["value"] + 0.001}))


class TestStrategyBehaviour(unittest.TestCase):
    def setUp(self):
        self.adapter = FixtureAdapter(FIXTURES)
        self.holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        self.book = analyse(self.holdings, self.adapter)
        self.symbols = [h.symbol for h in self.holdings]
        self.ctx = build_context(self.symbols, self.adapter, self.book)
        self.verdicts = {
            h.symbol: evaluate(h.symbol, self.adapter, avg_cost=h.avg_cost, context=self.ctx)
            for h in self.holdings
        }

    def test_evaluate_refuses_to_run_without_a_book_wide_context(self):
        """A relative score cannot be computed for one symbol in isolation."""
        with self.assertRaises(ValueError) as ctx:
            evaluate("HDFCBANK", self.adapter)
        self.assertIn("cannot be computed for one symbol", str(ctx.exception))

    def test_no_exit_without_failed_absolute_floors(self):
        """The guard against manufactured turnover."""
        for v in self.verdicts.values():
            if v["action"] == "exit":
                self.assertGreaterEqual(len(v["factor"]["failed_floors"]), 2, v["symbol"])

    def test_top_ranked_name_failing_a_floor_is_not_added_to(self):
        for v in self.verdicts.values():
            if v["factor"]["failed_floors"] and v["action"] in ("accumulate", "buy"):
                self.fail(f"{v['symbol']} added to while failing {v['factor']['failed_floors']}")

    def test_ranks_are_a_permutation_of_the_book(self):
        ranks = sorted(v["factor"]["rank"] for v in self.verdicts.values())
        self.assertEqual(ranks, list(range(1, len(self.holdings) + 1)))

    def test_verdicts_match_the_shared_contract(self):
        for v in self.verdicts.values():
            for key in ("symbol", "action", "engine", "confidence", "reasons",
                        "last_close", "stop", "backtest", "technical"):
                self.assertIn(key, v)
            self.assertIn(v["action"], ("exit", "trim", "hold", "accumulate", "buy"))

    def test_bottom_ranked_trim_explains_it_is_relative_only(self):
        for v in self.verdicts.values():
            if v["action"] == "trim" and not v["factor"]["failed_floors"]:
                self.assertIn("relative call only", " ".join(v["reasons"]))


class TestBookTilt(unittest.TestCase):
    def test_equal_weighting_produces_no_tilt(self):
        """z-scores sum to zero, so an equal-weighted book is factor-neutral."""
        adapter = FixtureAdapter(FIXTURES)
        holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        symbols = [h.symbol for h in holdings]
        model = factor_model(symbols, adapter)
        equal = {s: 1 / len(symbols) for s in symbols}
        tilt = book_tilt(model, equal)
        for factor in DEFAULT_WEIGHTS:
            self.assertAlmostEqual(tilt["by_factor"][factor], 0.0, places=2)

    def test_actual_weights_produce_a_measurable_tilt(self):
        adapter = FixtureAdapter(FIXTURES)
        holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        book = analyse(holdings, adapter)
        model = factor_model([h.symbol for h in holdings], adapter)
        tilt = book_tilt(model, book["weights"])
        self.assertIn(tilt["dominant_factor"], DEFAULT_WEIGHTS)
        self.assertTrue(tilt["within_book_only"])


class TestRegistryGeneralisation(unittest.TestCase):
    """The registry must describe strategies, not name-check them."""

    def test_all_three_strategies_are_registered(self):
        self.assertEqual(set(STRATEGIES), {"baseline", "bajaj", "factor"})

    def test_context_requirement_is_declared_not_hardcoded(self):
        self.assertFalse(get("baseline").needs_context)
        self.assertTrue(get("bajaj").needs_context)
        self.assertTrue(get("factor").needs_context)

    def test_renderers_are_owned_by_their_strategy(self):
        self.assertIsNone(get("baseline").render_sections)
        self.assertIsNotNone(get("bajaj").render_sections)
        self.assertIsNotNone(get("factor").render_sections)

    def test_shared_report_module_has_no_strategy_knowledge(self):
        from core import report
        with open(report.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for name in ("bajaj", "factor"):
            self.assertNotIn(name, source)

    def test_unknown_strategy_is_loud(self):
        with self.assertRaises(ValueError):
            get("nonexistent")


class TestStrategiesDisagree(unittest.TestCase):
    def test_all_three_produce_different_verdict_sets(self):
        """If any two fully agree, one of them is redundant."""
        adapter = FixtureAdapter(FIXTURES)
        holdings = load_holdings(os.path.join(FIXTURES, "holdings.csv"))
        book = analyse(holdings, adapter)
        symbols = [h.symbol for h in holdings]

        results = {}
        for name in ("baseline", "bajaj", "factor"):
            strategy = get(name)
            ctx = (
                strategy.build_context(symbols, adapter, book)
                if strategy.needs_context
                else None
            )
            results[name] = {
                h.symbol: strategy.evaluate(
                    h.symbol, adapter, avg_cost=h.avg_cost,
                    **({"context": ctx} if ctx else {}),
                )["action"]
                for h in holdings
            }

        self.assertNotEqual(results["baseline"], results["bajaj"])
        self.assertNotEqual(results["baseline"], results["factor"])
        self.assertNotEqual(results["bajaj"], results["factor"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
