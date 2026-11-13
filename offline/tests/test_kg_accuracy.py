"""Unit tests for the vendored reliable-kg-estimation accuracy estimators."""

from src.evaluation.kg_accuracy import (
    AGRESTI_COULL,
    WILSON,
    WILSON_CC,
    Stratum,
    proportion_ci,
    stratified_estimate,
)


def test_proportion_ci_wilson_known_value():
    lo, hi = proportion_ci(19, 20, method=WILSON)
    assert round(lo, 3) == 0.764
    assert round(hi, 3) == 0.997  # exact chi-square upper bound near the ceiling


def test_proportion_ci_empty_and_zero():
    assert proportion_ci(0, 0) == (0.0, 0.0)
    lo, hi = proportion_ci(0, 20, method=WILSON)
    assert lo == 0.0 and 0.0 < hi < 0.2


def test_all_methods_return_ordered_bounds_in_unit_interval():
    for method in (WILSON, WILSON_CC, AGRESTI_COULL):
        for k, n in [(0, 30), (1, 30), (15, 30), (29, 30), (30, 30)]:
            lo, hi = proportion_ci(k, n, method=method)
            assert 0.0 <= lo <= hi <= 1.0, (method, k, n, lo, hi)


def test_stratified_estimate_is_population_weighted_mean():
    strata = [
        Stratum(correct=20, n=20, population=900),  # p=1.0, weight 0.9
        Stratum(correct=10, n=20, population=100),  # p=0.5, weight 0.1
    ]
    result = stratified_estimate(strata, method=WILSON)
    assert round(result["estimate"], 4) == 0.95  # 0.9*1.0 + 0.1*0.5
    lo, hi = result["ci"]
    assert 0.0 <= lo <= result["estimate"] <= hi <= 1.0
    assert result["ess"] > 0
    assert result["n_total"] == 40 and result["n_strata"] == 2


def test_stratified_estimate_agresti_coull_and_wilson_both_valid():
    strata = [
        Stratum(correct=18, n=20, population=5000),
        Stratum(correct=9, n=20, population=2000),
        Stratum(correct=20, n=20, population=3000),
    ]
    for method in (WILSON, AGRESTI_COULL):
        result = stratified_estimate(strata, method=method)
        lo, hi = result["ci"]
        assert 0.0 <= lo <= hi <= 1.0
        assert result["ci_method"] == method


def test_stratified_estimate_empty():
    result = stratified_estimate([])
    assert result["estimate"] is None and result["ci"] is None and result["n_total"] == 0


def test_perfect_sample_has_tight_lower_bound():
    strata = [Stratum(correct=20, n=20, population=1000) for _ in range(5)]
    result = stratified_estimate(strata, method=WILSON)
    assert result["estimate"] == 1.0
    assert result["ci"][1] == 1.0
    assert result["ci"][0] > 0.9
