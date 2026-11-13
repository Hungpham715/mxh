"""Reliable knowledge-graph accuracy estimation (Wilson family + stratified ESS).

Vendored and adapted from the HEREDITARY project's ``reliable-kg-estimation`` framework
(``references/external/reliable-kg-estimation-main``, research use only). That work replaces the
naive Wald / normal-approximation confidence interval -- which suffers from zero-width and
overshooting intervals -- with Wilson-family intervals (Wilson, continuity-corrected Wilson,
Agresti-Coull), and extends them to complex sampling designs through an *effective sample size*
(ESS) that absorbs the design's variance inflation.

The external repository is git-ignored (read-only research input), so the mathematics is
reproduced here to keep the offline pipeline self-contained and reproducible after a clone.

Offline's graph-accuracy audit draws a **stratified simple random sample**: strata are
relationship types, each stratum ``h`` has a population size ``N_h`` (``graph_count_type``), a
sample size ``n_h`` and a number of correct edges ``k_h``. The framework's cluster/stratified
estimator (``STWCSSampler``) therefore reduces to a stratified estimator with no intra-stratum
clustering: the point estimate is the population-weighted mean of stratum precisions, and the
confidence interval is a Wilson-family interval evaluated at an ESS chosen so that its implied
binomial variance equals the true stratified variance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from scipy import stats

# Confidence-interval methods, named exactly as the reference framework's `computeMoE` keys.
WILSON = "wilson"
WILSON_CC = "wilsonCC"
AGRESTI_COULL = "agresti-coull"


def _z(alpha: float) -> float:
    """Normal critical value with right-tail probability alpha/2."""
    return float(stats.norm.isf(alpha / 2))


def _sqrt_non_negative(value: float) -> float:
    """Guard against tiny negative radicands from floating-point error near ae in {0, 1}."""
    return math.sqrt(value) if value > 0 else 0.0


def wilson_bounds(ae: float, n: float, x: float, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval, with exact chi-square bounds for counts near 0 or n.

    Mirrors ``SRSSampler.computeWCI`` / ``STWCSSampler.computeWCI``: ``ae`` is the point estimate,
    ``n`` the (effective) sample size and ``x`` the (effective) number of successes.
    """
    z = _z(alpha)
    n_adj = n + z * z
    x_adj = x + (z * z) / 2
    ae_adj = x_adj / n_adj
    moe = ((z * math.sqrt(n)) / n_adj) * _sqrt_non_negative(ae * (1 - ae) + (z * z) / (4 * n))

    near_floor = (n <= 50 and x in (1, 2)) or (n >= 51 and x in (1, 2, 3))
    near_ceiling = (n <= 50 and x in (n - 1, n - 2)) or (n >= 51 and x in (n - 1, n - 2, n - 3))

    if near_floor:
        lower = 0.5 * float(stats.chi2.isf(1 - alpha, 2 * x)) / n
    else:
        lower = ae_adj - moe
    if near_ceiling:
        upper = 1 - (0.5 * float(stats.chi2.isf(1 - alpha, 2 * (n - x))) / n)
    else:
        upper = ae_adj + moe
    return max(0.0, lower), min(1.0, upper)


def wilson_cc_bounds(ae: float, n: float, x: float, alpha: float = 0.05) -> tuple[float, float]:
    """Continuity-corrected Wilson interval (reference ``computeCCWCI``)."""
    z = _z(alpha)
    complement = 1 - ae
    denom = 2 * (n + z * z)
    center = (2 * n * ae + z * z) / denom

    if x == 0:
        lower = 0.0
    else:
        radicand = z * z - 2 - 1 / n + 4 * ae * (n * complement + 1)
        lower = center - (1 + z * _sqrt_non_negative(radicand)) / denom
    if x == n:
        upper = 1.0
    else:
        radicand = z * z + 2 - 1 / n + 4 * ae * (n * complement - 1)
        upper = center + (1 + z * _sqrt_non_negative(radicand)) / denom
    return max(0.0, lower), min(1.0, upper)


def agresti_coull_bounds(ae: float, n: float, x: float, alpha: float = 0.05) -> tuple[float, float]:
    """Agresti-Coull interval (reference ``computeACCI``)."""
    z = _z(alpha)
    n_adj = n + z * z
    x_adj = x + (z * z) / 2
    ae_adj = x_adj / n_adj
    moe = z * _sqrt_non_negative((1 / n_adj) * (ae_adj * (1 - ae_adj)))
    return max(0.0, ae_adj - moe), min(1.0, ae_adj + moe)


_BOUNDS: dict[str, Callable[[float, float, float, float], tuple[float, float]]] = {
    WILSON: wilson_bounds,
    WILSON_CC: wilson_cc_bounds,
    AGRESTI_COULL: agresti_coull_bounds,
}


def proportion_ci(k: int, n: int, alpha: float = 0.05, method: str = WILSON) -> tuple[float, float]:
    """Binomial confidence interval for ``k`` successes out of ``n`` trials."""
    if n == 0:
        return (0.0, 0.0)
    if method not in _BOUNDS:
        raise ValueError(f"unknown ci method {method!r}; expected one of {sorted(_BOUNDS)}")
    ae = k / n
    return _BOUNDS[method](ae, float(n), float(k), alpha)


@dataclass
class Stratum:
    """One stratum of the audit sample (a relationship type)."""

    correct: int  # k_h: edges labelled correct
    n: int  # n_h: edges sampled
    population: int  # N_h: edges of this type in the graph (graph_count_type)


def stratified_estimate(
    strata: list[Stratum],
    alpha: float = 0.05,
    method: str = WILSON,
    use_fpc: bool = True,
) -> dict[str, object]:
    """Population-weighted accuracy estimate with a Wilson-family CI on the effective sample size.

    The point estimate is ``sum_h w_h * p_h`` with ``w_h = N_h / sum(N_h)``. The variance is the
    stratified-SRS variance ``sum_h w_h^2 * p_h(1-p_h)/n_h`` (optionally with the finite population
    correction). The effective sample size ``ess`` solves ``ae(1-ae)/ess = variance``, so a Wilson
    interval at ``ess`` reproduces the design's true precision; a Student-t design factor (reference
    ``dFactor``, df = number of sampled units minus number of strata) widens it slightly to account
    for estimating the per-stratum variances.
    """
    if method not in _BOUNDS:
        raise ValueError(f"unknown ci method {method!r}; expected one of {sorted(_BOUNDS)}")
    used = [s for s in strata if s.n > 0]
    if not used:
        return {
            "estimate": None,
            "ess": None,
            "variance": None,
            "design_effect": None,
            "ci": None,
            "ci_method": method,
            "n_total": 0,
            "n_strata": 0,
        }

    total_population = sum(s.population for s in used)
    n_total = sum(s.n for s in used)
    n_strata = len(used)

    estimate = 0.0
    variance = 0.0
    for s in used:
        weight = s.population / total_population if total_population else 0.0
        p = s.correct / s.n
        estimate += weight * p
        term = (weight**2) * (p * (1 - p) / s.n)
        if use_fpc and s.population > 1:
            term *= (s.population - s.n) / (s.population - 1)
        variance += term

    # Effective sample size tying the Wilson width to the stratified variance.
    if variance <= 0:
        ess = float(n_total)
        design_effect = 1.0
    else:
        ess = estimate * (1 - estimate) / variance
        df = max(n_total - n_strata, 1)
        design_factor = (_z(alpha) / float(stats.t.isf(alpha / 2, df))) ** 2
        ess = ess * design_factor
        design_effect = (n_total / ess) if ess else None
        if ess <= 0:
            ess = float(n_total)
            design_effect = 1.0

    successes = ess * estimate
    lower, upper = _BOUNDS[method](estimate, ess, successes, alpha)
    return {
        "estimate": estimate,
        "ess": ess,
        "variance": variance,
        "design_effect": design_effect,
        "ci": (lower, upper),
        "ci_method": method,
        "n_total": n_total,
        "n_strata": n_strata,
    }
