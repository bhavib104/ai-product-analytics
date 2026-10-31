"""Deterministic statistical analysis.

All numbers shown in the product are produced here (or by the analytics
engines), never by a language model.  Each result records the hypotheses,
sample sizes, test, statistic, p-value, confidence interval, effect size and
assumptions.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats as scipy_stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import confint_proportions_2indep, proportions_ztest


def _clean(x: float | None) -> float | None:
    if x is None:
        return None
    if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
        return None
    return float(x)


def wilson_ci(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    z = scipy_stats.norm.ppf(1 - alpha / 2)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cohens_h(p1: float, p2: float) -> float:
    return 2 * math.asin(math.sqrt(max(0.0, min(1.0, p2)))) - 2 * math.asin(
        math.sqrt(max(0.0, min(1.0, p1)))
    )


def odds_ratio(a: int, n_a: int, b: int, n_b: int) -> float | None:
    # a = successes control, b = successes treatment
    fail_a = n_a - a
    fail_b = n_b - b
    if a == 0 or b == 0 or fail_a == 0 or fail_b == 0:
        return None
    return (b / fail_b) / (a / fail_a)


def two_proportion_test(
    successes_control: int,
    n_control: int,
    successes_treatment: int,
    n_treatment: int,
    alpha: float = 0.05,
) -> dict:
    p_control = successes_control / n_control if n_control else 0.0
    p_treatment = successes_treatment / n_treatment if n_treatment else 0.0
    result = {
        "null_hypothesis": "The two conversion rates are equal.",
        "alternative_hypothesis": "The two conversion rates differ (two-sided).",
        "n_control": n_control,
        "n_treatment": n_treatment,
        "successes_control": successes_control,
        "successes_treatment": successes_treatment,
        "rate_control": round(p_control, 6),
        "rate_treatment": round(p_treatment, 6),
        "absolute_lift": round(p_treatment - p_control, 6),
        "relative_lift": round((p_treatment - p_control) / p_control, 6) if p_control else None,
        "alpha": alpha,
        "test": None,
        "statistic": None,
        "p_value": None,
        "ci_low": None,
        "ci_high": None,
        "effect_size": {
            "cohens_h": round(cohens_h(p_control, p_treatment), 6),
            "odds_ratio": _clean(odds_ratio(successes_control, n_control, successes_treatment, n_treatment)),
        },
        "assumptions": [
            "Independent observations.",
            "Random assignment to control/treatment.",
            "Binary outcome with sufficient expected counts.",
        ],
        "interpretation": "",
    }
    if n_control == 0 or n_treatment == 0:
        result["interpretation"] = "Insufficient data: one or both groups are empty."
        return result

    expected = [
        p_control * n_control,
        (1 - p_control) * n_control,
        p_treatment * n_treatment,
        (1 - p_treatment) * n_treatment,
    ]
    small_counts = min(expected) < 5
    if small_counts:
        table = [
            [successes_control, n_control - successes_control],
            [successes_treatment, n_treatment - successes_treatment],
        ]
        _, p_value = scipy_stats.fisher_exact(table)
        result["test"] = "Fisher exact test (small expected counts)"
        result["p_value"] = _clean(p_value)
        result["statistic"] = None
    else:
        stat, p_value = proportions_ztest(
            [successes_treatment, successes_control], [n_treatment, n_control]
        )
        result["test"] = "Two-proportion z-test"
        result["statistic"] = _clean(stat)
        result["p_value"] = _clean(p_value)

    try:
        low, high = confint_proportions_2indep(
            successes_treatment,
            n_treatment,
            successes_control,
            n_control,
            method="newcombe",
            alpha=alpha,
        )
        result["ci_low"] = _clean(low)
        result["ci_high"] = _clean(high)
    except Exception:
        diff = p_treatment - p_control
        se = math.sqrt(
            p_control * (1 - p_control) / n_control + p_treatment * (1 - p_treatment) / n_treatment
        )
        z = scipy_stats.norm.ppf(1 - alpha / 2)
        result["ci_low"] = _clean(diff - z * se)
        result["ci_high"] = _clean(diff + z * se)

    significant = result["p_value"] is not None and result["p_value"] < alpha
    result["significant"] = significant
    direction = "higher" if p_treatment > p_control else "lower"
    result["interpretation"] = (
        f"Treatment conversion is {direction} than control "
        f"({p_treatment:.2%} vs {p_control:.2%}; absolute lift "
        f"{(p_treatment - p_control) * 100:+.2f} pp). "
        f"{'Statistically significant' if significant else 'Not statistically significant'} "
        f"at alpha={alpha}. Statistical significance is not proof of business importance or "
        f"causality; check assignment integrity and practical impact."
    )
    return result


def required_sample_size(
    p_control: float, p_treatment: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    if p_control <= 0 or p_control >= 1 or p_treatment <= 0 or p_treatment >= 1:
        return 0
    effect = abs(cohens_h(p_control, p_treatment))
    if effect == 0:
        return 0
    analysis = NormalIndPower()
    n = analysis.solve_power(effect_size=effect, alpha=alpha, power=power, alternative="two-sided")
    return int(math.ceil(n))


def achieved_power(
    p_control: float, p_treatment: float, n_control: int, n_treatment: int, alpha: float = 0.05
) -> float:
    if n_control <= 0 or n_treatment <= 0:
        return 0.0
    effect = abs(cohens_h(p_control, p_treatment))
    if effect == 0:
        return 0.0
    analysis = NormalIndPower()
    ratio = n_treatment / n_control
    try:
        return float(
            analysis.power(
                effect_size=effect,
                nobs1=n_control,
                alpha=alpha,
                ratio=ratio,
                alternative="two-sided",
            )
        )
    except Exception:
        return 0.0


def welch_ttest(a: list[float], b: list[float], alpha: float = 0.05) -> dict:
    if len(a) < 2 or len(b) < 2:
        return {"test": "Welch t-test", "error": "Insufficient data", "p_value": None}
    stat, p = scipy_stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
    mean_a, mean_b = float(np.mean(a)), float(np.mean(b))
    return {
        "test": "Welch t-test",
        "statistic": _clean(stat),
        "p_value": _clean(p),
        "mean_control": round(mean_a, 6),
        "mean_treatment": round(mean_b, 6),
        "difference": round(mean_b - mean_a, 6),
        "significant": bool(p < alpha),
        "assumptions": [
            "Independent observations.",
            "Approximately normal sampling distribution or large samples.",
            "Unequal variances allowed (Welch correction).",
        ],
    }


def mann_whitney(a: list[float], b: list[float], alpha: float = 0.05) -> dict:
    if len(a) < 2 or len(b) < 2:
        return {"test": "Mann-Whitney U", "error": "Insufficient data", "p_value": None}
    stat, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return {
        "test": "Mann-Whitney U",
        "statistic": _clean(stat),
        "p_value": _clean(p),
        "significant": bool(p < alpha),
        "assumptions": ["Independent observations.", "Ordinal or continuous outcome."],
    }


def chi_square(table: list[list[int]], alpha: float = 0.05) -> dict:
    arr = np.array(table, dtype=float)
    if arr.sum() == 0:
        return {"test": "Chi-square", "error": "Empty table", "p_value": None}
    stat, p, dof, expected = scipy_stats.chi2_contingency(arr, correction=False)
    return {
        "test": "Chi-square test of independence",
        "statistic": _clean(stat),
        "p_value": _clean(p),
        "degrees_of_freedom": int(dof),
        "expected_min": float(expected.min()),
        "significant": bool(p < alpha),
        "assumptions": ["Independent observations.", "Expected counts >= 5 (check expected_min)."],
    }


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[dict]:
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [1.0] * n
    prev = 1.0
    for rank, (idx, p) in enumerate(reversed(indexed), start=1):
        k = n - rank + 1
        val = min(prev, p * n / k)
        adjusted[idx] = val
        prev = val
    return [
        {"index": i, "p_value": p, "adjusted_p": adjusted[i], "significant": adjusted[i] < alpha}
        for i, p in enumerate(p_values)
    ]
