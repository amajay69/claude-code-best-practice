"""Deterministic core for the stock desk.

Everything quantitative lives here and nowhere else.  Agents read what this
package produces; they never recompute it.  Stdlib only — a clean clone runs
``python3 scripts/run_analysis.py`` with no install step.
"""
