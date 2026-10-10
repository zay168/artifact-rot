"""E6 — survival analysis, validated on synthetic data with a known answer.

These tests were written **before** passes 2 and 3, hence before seeing any real figure.
That is their purpose: an analysis validated on data whose answer is known can no longer
be tuned to the result one hoped for.

The procedure is that of the E2 control set, applied to statistics: build a world whose
half-life is known, run the estimator on it, and check that it recovers the number.
"""

from __future__ import annotations

import math

import pytest

from artifact_rot.survival import (
    H1_GAP_THRESHOLD,
    H1_RATE_THRESHOLD,
    AgePoint,
    StratumCounts,
    pava,
    survival_curve,
    verdict_h1,
    wilson_difference,
    wilson_interval,
)


def exponential_world(half_life: float, ages: list[float], n: int = 4000) -> list[AgePoint]:
    """A world where survival follows an exponential with a known half-life.

    At age a, the proportion of links still alive is 2**(-a / half_life). Each stratum is
    observed at its age, exactly as the project does: a single instant, papers of
    different ages.
    """
    points = []
    for age in ages:
        alive_fraction = 2 ** (-age / half_life)
        alive = round(n * alive_fraction)
        points.append(AgePoint(age_years=age, counts=StratumCounts(alive=alive, dead=n - alive)))
    return points


class TestWilson:
    def test_classic_proportion(self) -> None:
        low, high = wilson_interval(50, 100)
        assert low == pytest.approx(0.404, abs=0.01)
        assert high == pytest.approx(0.596, abs=0.01)

    def test_stays_within_zero_one_at_extremes(self) -> None:
        """Wilson's advantage over the normal interval: no negative bound."""
        low, high = wilson_interval(0, 10)
        assert low == pytest.approx(0.0, abs=1e-12)
        assert 0 < high < 1
        low, high = wilson_interval(10, 10)
        assert high == pytest.approx(1.0, abs=1e-12)
        assert 0 < low < 1

    def test_zero_count(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_interval_narrows_with_sample_size(self) -> None:
        small = wilson_interval(5, 10)
        large = wilson_interval(500, 1000)
        assert (large[1] - large[0]) < (small[1] - small[0])


class TestDifferenceOfProportions:
    def test_clear_difference(self) -> None:
        low, high = wilson_difference(400, 1000, 100, 1000)
        assert low > 0
        assert 0.3 == pytest.approx((400 / 1000) - (100 / 1000), abs=1e-9)
        assert low < 0.3 < high

    def test_zero_difference_contains_zero(self) -> None:
        low, high = wilson_difference(500, 1000, 500, 1000)
        assert low < 0 < high


class TestIsotonicRegression:
    def test_already_increasing_sequence_is_unchanged(self) -> None:
        values = [0.1, 0.2, 0.3, 0.4]
        assert pava(values, [1] * 4) == pytest.approx(values)

    def test_a_violation_is_pooled(self) -> None:
        """Survival rising with age is impossible: it is noise, and showing it would
        present an artefact as a result."""
        out = pava([0.1, 0.5, 0.3, 0.6], [1] * 4)
        assert out == pytest.approx([0.1, 0.4, 0.4, 0.6])
        assert all(out[i] <= out[i + 1] + 1e-9 for i in range(len(out) - 1))

    def test_weights_matter(self) -> None:
        """A stratum of 1,000 links must not be pulled by a stratum of 10."""
        out = pava([0.5, 0.1], [1000, 10])
        assert out[0] == pytest.approx(out[1])
        assert out[0] > 0.45

    def test_empty_sequence(self) -> None:
        assert pava([], []) == []


class TestHalfLife:
    @pytest.mark.parametrize("half_life", [3.0, 5.0, 8.0, 12.0])
    def test_recovers_a_known_half_life(self, half_life: float) -> None:
        """The central test: a built world, an answer known in advance."""
        ages = [1.0, 4.0, 8.0, 12.0, 16.0]
        curve = survival_curve(exponential_world(half_life, ages))
        estimated = curve.half_life
        assert estimated is not None, "the curve should cross 0.5"
        assert estimated == pytest.approx(half_life, rel=0.15)

    def test_no_half_life_if_the_curve_does_not_drop(self) -> None:
        """Extrapolating beyond the last stratum would invent the figure everyone will
        quote."""
        curve = survival_curve(exponential_world(50.0, [1.0, 4.0, 8.0]))
        assert curve.half_life is None

    def test_survival_always_decreases(self) -> None:
        curve = survival_curve(exponential_world(6.0, [1.0, 4.0, 8.0, 12.0, 16.0]))
        assert all(
            curve.survival[i] >= curve.survival[i + 1] - 1e-9
            for i in range(len(curve.survival) - 1)
        )

    def test_world_without_mortality(self) -> None:
        points = [AgePoint(a, StratumCounts(alive=1000, dead=0)) for a in (1.0, 8.0, 16.0)]
        curve = survival_curve(points)
        assert curve.half_life is None
        assert curve.survival == pytest.approx([1.0, 1.0, 1.0])

    def test_consistent_with_the_exponential_formula(self) -> None:
        """Independent check: at one half-life, theoretical survival is 0.5."""
        assert 2 ** (-1.0) == pytest.approx(0.5)
        assert math.isclose(2 ** (-2.0), 0.25)


class TestDenominators:
    def test_unknown_never_enters_the_denominator(self) -> None:
        """§4, pitfall 2. A crawl failure turned into a rate is a falsification."""
        counts = StratumCounts(alive=40, dead=10, restricted=0, unknown=950)
        assert counts.denominator() == 50
        assert counts.dead_rate() == pytest.approx(0.2)
        assert counts.unknown_rate() == pytest.approx(0.95)

    def test_restricted_counts_alive_by_default(self) -> None:
        counts = StratumCounts(alive=30, dead=10, restricted=10)
        assert counts.denominator("alive") == 50
        assert counts.dead_rate("alive") == pytest.approx(0.2)

    def test_variant_excluding_restricted(self) -> None:
        """The choice is debatable: the variant is computed and published alongside."""
        counts = StratumCounts(alive=30, dead=10, restricted=10)
        assert counts.denominator("exclude") == 40
        assert counts.dead_rate("exclude") == pytest.approx(0.25)

    def test_empty_stratum(self) -> None:
        assert StratumCounts().dead_rate() is None


class TestVerdictH1:
    def test_h1_supported(self) -> None:
        """2018 rate above 20% and gap above 15 points."""
        by_year = {
            2010: StratumCounts(alive=500, dead=500),
            2018: StratumCounts(alive=650, dead=350),
            2025: StratumCounts(alive=950, dead=50),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "supported"
        assert result.reference_rate == pytest.approx(0.35)
        assert result.gap == pytest.approx(0.45)
        assert result.gap_interval is not None and result.gap_interval[0] > 0

    def test_h1_refuted_when_links_survive(self) -> None:
        """The plan requires publishing the positive result and stopping."""
        by_year = {
            2010: StratumCounts(alive=980, dead=20),
            2018: StratumCounts(alive=985, dead=15),
            2025: StratumCounts(alive=990, dead=10),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "refuted"

    def test_h1_refuted_without_age_effect(self) -> None:
        """Many dead links but no relation to age.

        H1 asserts two things at once, one being that the rate rises **clearly** with
        age. Without an age effect, it is false whatever the rate — and the plan requires
        publishing and stopping, not enlarging the sample.
        """
        by_year = {
            2010: StratumCounts(alive=650, dead=350),
            2018: StratumCounts(alive=650, dead=350),
            2025: StratumCounts(alive=650, dead=350),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "refuted"
        assert any("age" in r for r in result.reasons)

    def test_grey_zone_real_age_effect_but_below_threshold(self) -> None:
        """The only true grey-zone case: both signals exist, one of them does not reach
        its threshold. That is where enlarging the sample can decide."""
        by_year = {
            2010: StratumCounts(alive=670, dead=330),
            2018: StratumCounts(alive=750, dead=250),
            2025: StratumCounts(alive=770, dead=230),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "grey_zone"
        assert result.gap is not None and 0 < result.gap < H1_GAP_THRESHOLD

    def test_small_sample_is_not_enough(self) -> None:
        """Two dead links out of five make 40%, but the interval is huge. The threshold
        alone is not enough — that is why §2 requires an interval."""
        by_year = {
            2010: StratumCounts(alive=3, dead=2),
            2018: StratumCounts(alive=3, dead=2),
            2025: StratumCounts(alive=4, dead=1),
        }
        result = verdict_h1(by_year)
        assert result.verdict != "supported"

    def test_reference_stratum_missing(self) -> None:
        by_year = {2010: StratumCounts(alive=500, dead=500)}
        result = verdict_h1(by_year)
        assert result.verdict == "grey_zone"
        assert any("2018" in r for r in result.reasons)

    def test_unknown_rate_is_reported(self) -> None:
        by_year = {
            2010: StratumCounts(alive=500, dead=500, unknown=1000),
            2018: StratumCounts(alive=650, dead=350, unknown=0),
            2025: StratumCounts(alive=950, dead=50, unknown=0),
        }
        result = verdict_h1(by_year)
        assert result.unknown_rate == pytest.approx(1000 / 4000)

    def test_thresholds_are_the_plan_s(self) -> None:
        assert H1_RATE_THRESHOLD == 0.20
        assert H1_GAP_THRESHOLD == 0.15
