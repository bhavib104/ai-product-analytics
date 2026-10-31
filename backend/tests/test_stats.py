from __future__ import annotations

import math

import pytest

from app.analytics import stats


def test_wilson_interval_bounds_are_valid() -> None:
    low, high = stats.wilson_ci(50, 100)
    assert 0 <= low < 0.5 < high <= 1
    assert low == pytest.approx(0.404, abs=0.01)
    assert high == pytest.approx(0.596, abs=0.01)


def test_wilson_interval_handles_empty_sample() -> None:
    assert stats.wilson_ci(0, 0) == (0.0, 0.0)


def test_two_proportion_test_detects_large_lift() -> None:
    result = stats.two_proportion_test(520, 1200, 700, 1200)
    assert result["test"] == "Two-proportion z-test"
    assert result["p_value"] is not None and result["p_value"] < 0.001
    assert result["significant"] is True
    assert result["absolute_lift"] > 0
    assert result["ci_low"] < result["ci_high"]
    assert result["effect_size"]["cohens_h"] > 0
    assert result["effect_size"]["odds_ratio"] > 1


def test_two_proportion_test_uses_fisher_for_small_counts() -> None:
    result = stats.two_proportion_test(1, 10, 8, 10)
    assert result["test"].startswith("Fisher exact")
    assert result["p_value"] is not None


def test_two_proportion_test_handles_empty_group() -> None:
    result = stats.two_proportion_test(10, 100, 0, 0)
    assert result["p_value"] is None
    assert "Insufficient data" in result["interpretation"]


def test_power_helpers_return_sane_values() -> None:
    n = stats.required_sample_size(0.10, 0.12)
    assert n > 0
    power = stats.achieved_power(0.10, 0.12, 10_000, 10_000)
    assert 0 < power <= 1
    assert math.isfinite(power)


def test_chi_square_and_multiple_testing() -> None:
    result = stats.chi_square([[30, 70], [50, 50]])
    assert result["p_value"] is not None
    adjusted = stats.benjamini_hochberg([0.001, 0.02, 0.5])
    assert [item["adjusted_p"] for item in adjusted] == sorted(
        item["adjusted_p"] for item in adjusted
    )
    assert adjusted[0]["significant"] is True
