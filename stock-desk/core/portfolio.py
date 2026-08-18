"""Book-level analysis: the stage that can overrule the per-stock verdicts.

A holding can earn a standalone BUY and still surface as "trim" because it
correlates 0.9 with three others.  That inversion is the point of the
portfolio pass — per-stock calls answer "is this good?", this answers "does
owning it *again* add anything?".
"""

from __future__ import annotations

import math

from .adapter import Bar, DataAdapter, Holding
from .indicators import annualised_vol, returns

#: Any single name or sector above this share of the book is flagged.
CONCENTRATION_LIMIT = 0.25


def _aligned_returns(
    series_by_symbol: dict[str, list[Bar]]
) -> tuple[list[str], list[list[float]]]:
    """Daily returns for every symbol over their common trading dates.

    Aligning on the date intersection matters: a symbol listed midway
    through the window would otherwise silently shift every other series by
    a few bars and corrupt every correlation in the matrix.
    """
    if not series_by_symbol:
        return [], []
    common = set.intersection(
        *({b.date for b in bars} for bars in series_by_symbol.values())
    )
    symbols = sorted(series_by_symbol)
    matrix = []
    for sym in symbols:
        px = [b.close for b in series_by_symbol[sym] if b.date in common]
        matrix.append(returns(px))
    width = min((len(r) for r in matrix), default=0)
    return symbols, [r[-width:] for r in matrix]


def _covariance(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    if n == 0 or len(matrix[0]) < 2:
        return [[0.0] * n for _ in range(n)]
    m = len(matrix[0])
    means = [sum(row) / m for row in matrix]
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = sum(
                (matrix[i][k] - means[i]) * (matrix[j][k] - means[j])
                for k in range(m)
            )
            cov[i][j] = cov[j][i] = s / (m - 1)
    return cov


def correlation_matrix(matrix: list[list[float]]) -> list[list[float]]:
    cov = _covariance(matrix)
    n = len(cov)
    sd = [math.sqrt(cov[i][i]) if cov[i][i] > 0 else 0.0 for i in range(n)]
    corr = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            corr[i][j] = cov[i][j] / (sd[i] * sd[j]) if sd[i] and sd[j] else 0.0
    return corr


def _eigenvalues(sym: list[list[float]], sweeps: int = 100) -> list[float]:
    """Eigenvalues of a symmetric matrix via cyclic Jacobi rotation.

    Stdlib-only so the core has no numeric dependencies.  Jacobi is the
    right choice here: matrices are tiny (one row per holding) and it is
    unconditionally stable for symmetric input.
    """
    n = len(sym)
    a = [row[:] for row in sym]
    for _ in range(sweeps):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off < 1e-12:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-15:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = math.copysign(1.0, theta) / (
                    abs(theta) + math.sqrt(theta * theta + 1)
                )
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
    return sorted((a[i][i] for i in range(n)), reverse=True)


def effective_bets(weights: list[float], matrix: list[list[float]]) -> float:
    """How many genuinely independent bets the book holds.

    Eigen-decompose the weight-scaled covariance and take the participation
    ratio of its eigenvalues.  Ten names moving as one give ~1; ten truly
    independent names give ~10.  This is the "your 10 stocks are really 2.8
    bets" number.
    """
    cov = _covariance(matrix)
    n = len(cov)
    if n == 0:
        return 0.0
    scaled = [[weights[i] * weights[j] * cov[i][j] for j in range(n)] for i in range(n)]
    raw = _eigenvalues(scaled)
    largest = max(raw, default=0.0)
    if largest <= 0:
        # No measurable variance anywhere — every series is flat (a halted or
        # illiquid name).  Absolute zero never survives floating point, so
        # without this the ratio of noise-to-noise reports a fully
        # diversified book built entirely from stocks that never move.
        return 0.0
    # Discard eigenvalues that are numerically indistinguishable from zero;
    # keeping them makes perfectly correlated holdings look independent.
    lam = [v for v in raw if v > largest * 1e-9]
    total = sum(lam)
    sq = sum(v * v for v in lam)
    if total <= 0 or sq <= 0:
        return 0.0
    return (total * total) / sq


def beta(portfolio_rets: list[float], market_rets: list[float]) -> float | None:
    width = min(len(portfolio_rets), len(market_rets))
    if width < 2:
        return None
    p, m = portfolio_rets[-width:], market_rets[-width:]
    mean_p, mean_m = sum(p) / width, sum(m) / width
    cov = sum((p[k] - mean_p) * (m[k] - mean_m) for k in range(width)) / (width - 1)
    var = sum((m[k] - mean_m) ** 2 for k in range(width)) / (width - 1)
    return cov / var if var else None


def analyse(
    holdings: list[Holding],
    adapter: DataAdapter,
    lookback_days: int = 504,
    stated_risk: str = "balanced",
) -> dict:
    """Full book-level pass.  Pure arithmetic — no model involved."""
    series = {h.symbol: adapter.prices(h.symbol, lookback_days) for h in holdings}
    last = {s: bars[-1].close for s, bars in series.items()}

    values = {h.symbol: h.qty * last[h.symbol] for h in holdings}
    total = sum(values.values())
    weights = {s: (v / total if total else 0.0) for s, v in values.items()}
    invested = sum(h.invested for h in holdings)

    # --- concentration -------------------------------------------------
    sectors: dict[str, float] = {}
    for h in holdings:
        sectors[adapter.sector(h.symbol)] = (
            sectors.get(adapter.sector(h.symbol), 0.0) + weights[h.symbol]
        )
    top_name, top_weight = max(weights.items(), key=lambda kv: kv[1])
    top_sector, top_sector_weight = max(sectors.items(), key=lambda kv: kv[1])
    hhi = sum(w * w for w in weights.values())

    # --- correlation ---------------------------------------------------
    symbols, matrix = _aligned_returns(series)
    ordered_weights = [weights[s] for s in symbols]
    n_bets = effective_bets(ordered_weights, matrix)
    corr = correlation_matrix(matrix)
    pairs = [
        {"a": symbols[i], "b": symbols[j], "corr": round(corr[i][j], 3)}
        for i in range(len(symbols))
        for j in range(i + 1, len(symbols))
    ]
    pairs.sort(key=lambda p: p["corr"], reverse=True)

    # --- portfolio return series, beta, benchmark ----------------------
    width = min((len(r) for r in matrix), default=0)
    portfolio_rets = [
        sum(ordered_weights[i] * matrix[i][k] for i in range(len(symbols)))
        for k in range(width)
    ]
    bench = adapter.benchmark(lookback_days)
    bench_rets = returns([b.close for b in bench])
    port_beta = beta(portfolio_rets, bench_rets)
    port_vol = annualised_vol([1.0] + _compound(portfolio_rets))
    bench_return = (bench[-1].close - bench[0].close) / bench[0].close if bench else None
    port_return = (total - invested) / invested if invested else None

    # --- risk score ----------------------------------------------------
    score_level = _risk_level(port_beta, port_vol)
    mismatch = _mismatch(score_level, stated_risk)

    diversification = _diversification_score(n_bets, len(holdings), top_weight)

    return {
        "totals": {
            "market_value": round(total, 2),
            "invested": round(invested, 2),
            "pnl": round(total - invested, 2),
            "return_pct": round(port_return * 100, 2) if port_return is not None else None,
            "holdings": len(holdings),
        },
        "weights": {s: round(w, 4) for s, w in sorted(weights.items())},
        "concentration": {
            "top_name": top_name,
            "top_name_weight": round(top_weight, 4),
            "top_name_breach": top_weight > CONCENTRATION_LIMIT,
            "top_sector": top_sector,
            "top_sector_weight": round(top_sector_weight, 4),
            "top_sector_breach": top_sector_weight > CONCENTRATION_LIMIT,
            "hhi": round(hhi, 4),
            "sectors": {k: round(v, 4) for k, v in sorted(sectors.items())},
            "diversification_score": diversification,
        },
        "correlation": {
            "effective_bets": round(n_bets, 2),
            "nominal_holdings": len(holdings),
            "headline": f"{len(holdings)} stocks ≈ {n_bets:.1f} real bets",
            "most_correlated_pairs": pairs[:5],
        },
        "risk": {
            "beta_vs_benchmark": round(port_beta, 3) if port_beta is not None else None,
            "annualised_vol": round(port_vol, 4) if port_vol else None,
            "level": score_level,
            "stated_profile": stated_risk,
            "mismatch": mismatch,
        },
        "benchmark": {
            "symbol": adapter.benchmark_symbol,
            "benchmark_return_pct": round(bench_return * 100, 2) if bench_return is not None else None,
            "portfolio_return_pct": round(port_return * 100, 2) if port_return is not None else None,
            "beating_index": (
                port_return > bench_return
                if None not in (port_return, bench_return)
                else None
            ),
        },
    }


def _compound(rets: list[float]) -> list[float]:
    """Rebuild an index series from returns so vol can be measured on it."""
    out, level = [], 1.0
    for r in rets:
        level *= 1 + r
        out.append(level)
    return out


def _risk_level(port_beta: float | None, vol: float | None) -> str:
    if port_beta is None or vol is None:
        return "unknown"
    if port_beta > 1.2 or vol > 0.30:
        return "high"
    if port_beta < 0.85 and vol < 0.20:
        return "low"
    return "medium"


_ORDER = {"low": 0, "medium": 1, "high": 2}
_PROFILE_TO_LEVEL = {"conservative": "low", "balanced": "medium", "aggressive": "high"}


def _mismatch(actual: str, stated: str) -> str | None:
    """Flag when the book carries more (or less) risk than the user claimed."""
    expected = _PROFILE_TO_LEVEL.get(stated)
    if actual == "unknown" or expected is None or actual == expected:
        return None
    if _ORDER[actual] > _ORDER[expected]:
        return (
            f"book risk is {actual} but you selected {stated} — "
            f"you are carrying more risk than you asked for"
        )
    return (
        f"book risk is {actual} but you selected {stated} — "
        f"you are more defensive than your stated appetite"
    )


def _diversification_score(n_bets: float, n_holdings: int, top_weight: float) -> int:
    """0-100.  Rewards independent bets, penalises a dominant position."""
    if n_holdings <= 1:
        return 0
    breadth = min(n_bets / n_holdings, 1.0)          # 1.0 = fully independent
    penalty = max(0.0, top_weight - CONCENTRATION_LIMIT) * 2
    return max(0, min(100, round((breadth - penalty) * 100)))
