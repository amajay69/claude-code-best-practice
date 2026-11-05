"""Selectable verdict strategies.

A strategy turns the deterministic fact sheet into an action per holding.
There is deliberately more than one, because reasonable frameworks disagree
about the same book — and the disagreement is worth seeing rather than
averaging away.

| Strategy | Judges a stock by | Needs the whole book first? |
| --- | --- | --- |
| ``baseline`` | additive score: technical + fundamental | no |
| ``bajaj`` | independent gates, all must pass | yes — market regime and sector ranks |
| ``factor`` | position relative to the other holdings | yes — z-scores are cross-sectional |

**Why this is a record rather than a bare function.**

The first version of this registry was ``{name: evaluate}`` plus a
``NEEDS_CONTEXT`` set of strings, and the runner asked *"is this bajaj?"* in
three places. That held for exactly two strategies. The factor model broke
it immediately: it needs a different context (cross-sectional z-scores, not
a market regime) and its own report tables, so name-checking would have
grown a second branch beside the first.

Each strategy now declares what it needs and the runner asks the strategy,
never its name. Adding a fourth touches one file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import fallback
from . import bajaj, factor


@dataclass(frozen=True)
class Strategy:
    """What the runner needs to know about a verdict strategy.

    Only ``evaluate`` is required. A strategy that judges each stock in
    isolation and needs no extra reporting declares nothing else.
    """

    name: str
    #: evaluate(symbol, adapter, *, horizon, risk_profile, avg_cost, context?) -> verdict
    evaluate: Callable
    #: build_context(symbols, adapter, book) -> dict passed to every evaluate call.
    #: Present only for strategies that cannot score one stock in isolation.
    build_context: Callable | None = None
    #: post_process(verdicts, book) -> dict merged into the run payload.
    post_process: Callable | None = None
    #: render_sections(payload) -> markdown appended to the report card.
    render_sections: Callable | None = None

    @property
    def needs_context(self) -> bool:
        return self.build_context is not None


STRATEGIES: dict[str, Strategy] = {
    "baseline": Strategy(name="baseline", evaluate=fallback.evaluate),
    "bajaj": Strategy(
        name="bajaj",
        evaluate=bajaj.evaluate,
        build_context=bajaj.build_context,
        post_process=bajaj.post_process,
        render_sections=bajaj.render_sections,
    ),
    "factor": Strategy(
        name="factor",
        evaluate=factor.evaluate,
        build_context=factor.build_context,
        render_sections=factor.render_sections,
    ),
}


def get(name: str) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; known: {sorted(STRATEGIES)}")
    return STRATEGIES[name]
