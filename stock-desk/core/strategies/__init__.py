"""Selectable verdict strategies.

A strategy turns the deterministic fact sheet into an action per holding.
There is deliberately more than one, because reasonable frameworks disagree
about the same book — and the disagreement is worth seeing rather than
averaging away.

| Strategy | Logic | Buys |
| --- | --- | --- |
| ``baseline`` | additive score: technical + fundamental | weakness in one leg offset by strength in the other |
| ``bajaj`` | independent gates, all must pass | only quality *and* momentum *and* a leading sector *and* strength |

The two will not agree, and that is the point: a stock the baseline rates
"good company at a mediocre moment" is a buy under a sum and a reject under
a gate.
"""

from __future__ import annotations

from typing import Callable

from .. import fallback
from . import bajaj

#: name -> evaluate(symbol, adapter, **kwargs) -> verdict dict
STRATEGIES: dict[str, Callable] = {
    "baseline": fallback.evaluate,
    "bajaj": bajaj.evaluate,
}

#: Strategies that need a prepared market context (regime, sector ranks).
NEEDS_CONTEXT = {"bajaj"}


def get(name: str) -> Callable:
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; known: {sorted(STRATEGIES)}")
    return STRATEGIES[name]
