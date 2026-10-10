"""E6 — survival curve, half-life, and the H1 verdict.

**Written on 2026-09-21, before passes 2 and 3, hence before seeing any final figure.**
This is deliberate: an analysis written after the fact can always be adjusted, even in
good faith, until it says what was hoped for. Written beforehand, it no longer can.
Plan §2 already requires the decision criterion to be fixed before the first run; this
module is its executable form.

*Comments and labels translated into English on 2026-10-10. The logic is unchanged. The
French original is git blob `7d1e63ef152c8151f3ea6d85e62266e7aa0b0b4e`, archived by
Software Heritage on 2026-10-10.*

---

## A deviation from PLAN.md §6, and the important point of this file

The plan prescribes **Kaplan-Meier**. Kaplan-Meier does not apply to these data, and
using it would produce a curve that looks impeccable and is wrong.

Kaplan-Meier assumes that, for each subject, we observe **either its time of death or
the last time it was seen alive**. Here we never observe when a link died. We look, at a
single instant, at links from papers of different ages, and record for each one: alive
or dead **today**.

In other words, for a link from an eight-year-old paper, we only know:
  * if it is dead  -> it died somewhere between 0 and 8 years. Nothing more.
  * if it is alive -> it survived at least 8 years.

The literature calls these **current status data** (single-instant inspection, or case-1
interval censoring). The appropriate nonparametric estimator is not Kaplan-Meier but
**isotonic regression** of the proportion dead as a function of age — here equivalent to
the Turnbull estimator, computed with the pool-adjacent-violators algorithm (PAVA).

Feeding these data to Kaplan-Meier would amount to telling it that every dead link died
on the day its paper was published. The resulting curve would be systematically too
pessimistic, and nothing in its shape would reveal it.

**What isotonic regression adds**: it forces survival to decrease with age. If sampling
noise makes a stratum go back up — 2014 better served than 2018, for instance — it pools
the two rather than publishing a rising curve, which would be an artefact, not a result.

Once the project has two campaigns six months apart, the data become genuinely
interval-censored with known bounds, and Turnbull applies in its general form.
Kaplan-Meier still will not.

---

## What never enters a denominator

`unknown` (§4, pitfall 2). Never, under any pretext. It is counted and reported
separately.

`restricted` is more delicate: the resource exists, it simply does not resolve in open
access. The main computation counts it as **alive** — which is what it is, in the sense
of existence. A variant excluding it entirely from the denominator is computed at the
same time and published alongside, because the choice is debatable and a reader must be
able to see what it changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Z95 = 1.959963984540054

RestrictedPolicy = Literal["alive", "exclude"]


# --- Confidence intervals ----------------------------------------------------------------


def wilson_interval(successes: int, total: int, z: float = Z95) -> tuple[float, float]:
    """Wilson interval for a proportion. Required by plan §2.

    Preferred to the normal interval because it stays valid on small samples and near
    0 or 1 — exactly the situation of the least populated strata, where the normal
    interval produces bounds below zero or above one.
    """
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def wilson_difference(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float]:
    """Interval for the **difference** of two proportions, Newcombe's method.

    §2 requires the gap between the oldest and the newest stratum to exceed fifteen
    points with an interval excluding zero. What is needed is an interval on a
    difference, not two separate intervals: two intervals that overlap slightly can very
    well correspond to a significant difference, and the reverse error is even more
    common.
    """
    if n1 <= 0 or n2 <= 0:
        return (-1.0, 1.0)
    l1, u1 = wilson_interval(k1, n1, z)
    l2, u2 = wilson_interval(k2, n2, z)
    p1, p2 = k1 / n1, k2 / n2
    lower = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


# --- Strata ------------------------------------------------------------------------------


@dataclass
class StratumCounts:
    """Raw counts for a stratum. All four states are there, including excluded ones."""

    alive: int = 0
    dead: int = 0
    restricted: int = 0
    unknown: int = 0

    @property
    def total_observed(self) -> int:
        """Everything observed, `unknown` included. Used to compute the unknown rate,
        never a mortality rate."""
        return self.alive + self.dead + self.restricted + self.unknown

    def denominator(self, policy: RestrictedPolicy = "alive") -> int:
        """Denominator of a published rate. `unknown` is never in it (§4, pitfall 2)."""
        base = self.alive + self.dead
        return base + self.restricted if policy == "alive" else base

    def numerator(self) -> int:
        return self.dead

    def dead_rate(self, policy: RestrictedPolicy = "alive") -> float | None:
        n = self.denominator(policy)
        return self.dead / n if n else None

    def unknown_rate(self) -> float | None:
        n = self.total_observed
        return self.unknown / n if n else None


@dataclass
class AgePoint:
    """An age stratum: proportion dead observed at that age."""

    age_years: float
    counts: StratumCounts
    label: str = ""

    def rate(self, policy: RestrictedPolicy = "alive") -> float:
        return self.counts.dead_rate(policy) or 0.0

    def interval(self, policy: RestrictedPolicy = "alive") -> tuple[float, float]:
        return wilson_interval(self.counts.dead, self.counts.denominator(policy))


# --- Survival curve ----------------------------------------------------------------------


def pava(values: list[float], weights: list[float]) -> list[float]:
    """Increasing isotonic regression, by pooling adjacent violators.

    Returns the increasing sequence closest to the observed values, in the weighted
    least-squares sense. Applied here to the proportion dead as a function of age: a
    proportion dead cannot decrease as age increases, and if the sample says otherwise,
    it is noise.

    Pooling two strata rather than publishing a curve that rises is not cosmetic
    smoothing: survival increasing with age is impossible, and showing it would present
    a sampling artefact as a result.
    """
    if not values:
        return []
    blocks: list[tuple[float, float]] = []  # (mean, weight)
    for value, weight in zip(values, weights, strict=True):
        blocks.append((value, max(weight, 1e-12)))
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            (v2, w2), (v1, w1) = blocks.pop(), blocks.pop()
            blocks.append(((v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2))

    out: list[float] = []
    index = 0
    for mean, weight in blocks:
        size = 0
        acc = 0.0
        while index + size < len(values) and acc < weight - 1e-9:
            acc += max(weights[index + size], 1e-12)
            size += 1
        out.extend([mean] * size)
        index += size
    return out[: len(values)]


@dataclass
class SurvivalCurve:
    ages: list[float]
    survival: list[float]
    raw_dead_rate: list[float]
    intervals: list[tuple[float, float]]
    labels: list[str] = field(default_factory=list)
    policy: RestrictedPolicy = "alive"

    @property
    def half_life(self) -> float | None:
        """Age at which survival reaches 0.5, by linear interpolation.

        Returns `None` if the curve never falls below 0.5 over the observed range.
        **Extrapolating beyond the oldest stratum would be inventing a figure**: there is
        no observation beyond it, and it is precisely the figure everyone will quote. If
        it is not reached, the report must say so — "the half-life exceeds N years" is
        information; an extrapolated number is not.
        """
        for i in range(len(self.survival)):
            if self.survival[i] <= 0.5:
                if i == 0:
                    return self.ages[0]
                s0, s1 = self.survival[i - 1], self.survival[i]
                a0, a1 = self.ages[i - 1], self.ages[i]
                if s0 == s1:
                    return a1
                return a0 + (s0 - 0.5) * (a1 - a0) / (s0 - s1)
        return None


def survival_curve(points: list[AgePoint], policy: RestrictedPolicy = "alive") -> SurvivalCurve:
    ordered = sorted(points, key=lambda p: p.age_years)
    ages = [p.age_years for p in ordered]
    raw = [p.rate(policy) for p in ordered]
    weights = [float(p.counts.denominator(policy)) for p in ordered]
    monotone = pava(raw, weights)
    return SurvivalCurve(
        ages=ages,
        survival=[1.0 - d for d in monotone],
        raw_dead_rate=raw,
        intervals=[p.interval(policy) for p in ordered],
        labels=[p.label for p in ordered],
        policy=policy,
    )


# --- H1 verdict ----------------------------------------------------------------------------

H1_RATE_THRESHOLD = 0.20
H1_GAP_THRESHOLD = 0.15
H1_REFERENCE_YEAR = 2018
GREY_ZONE_FACTOR = 3

Verdict = Literal["supported", "refuted", "grey_zone"]


@dataclass
class H1Result:
    verdict: Verdict
    reference_rate: float | None
    reference_interval: tuple[float, float] | None
    gap: float | None
    gap_interval: tuple[float, float] | None
    unknown_rate: float
    reasons: list[str]
    policy: RestrictedPolicy


def verdict_h1(
    by_year: dict[int, StratumCounts],
    policy: RestrictedPolicy = "alive",
) -> H1Result:
    """The §2 criterion, applied as written. No room for interpretation.

    "H1 is supported if the rate of unresolved links exceeds 20% on the 2018 stratum,
    **and** if the gap between the oldest and the newest stratum exceeds 15 points, with
    the 95% (Wilson) CI excluding 0 on both."

    The function makes no decision that is not in that sentence. That is the whole point
    of having written it before having the numbers.
    """
    reasons: list[str] = []
    years = sorted(by_year)
    if not years:
        return H1Result("grey_zone", None, None, None, None, 0.0, ["no stratum"], policy)

    oldest, newest = by_year[years[0]], by_year[years[-1]]
    ref = by_year.get(H1_REFERENCE_YEAR)

    total_obs = sum(c.total_observed for c in by_year.values())
    total_unknown = sum(c.unknown for c in by_year.values())
    unknown_rate = total_unknown / total_obs if total_obs else 0.0

    if ref is None:
        reasons.append(f"reference stratum {H1_REFERENCE_YEAR} missing")
        return H1Result("grey_zone", None, None, None, None, unknown_rate, reasons, policy)

    ref_rate = ref.dead_rate(policy)
    ref_ci = wilson_interval(ref.dead, ref.denominator(policy))

    gap = None
    gap_ci = None
    old_rate, new_rate = oldest.dead_rate(policy), newest.dead_rate(policy)
    if old_rate is not None and new_rate is not None:
        gap = old_rate - new_rate
        gap_ci = wilson_difference(
            oldest.dead, oldest.denominator(policy), newest.dead, newest.denominator(policy)
        )

    rate_ok = ref_rate is not None and ref_rate > H1_RATE_THRESHOLD and ref_ci[0] > 0
    gap_ok = gap is not None and gap > H1_GAP_THRESHOLD and gap_ci is not None and gap_ci[0] > 0

    if rate_ok:
        reasons.append(
            f"{H1_REFERENCE_YEAR} rate = {ref_rate:.1%} > {H1_RATE_THRESHOLD:.0%}, "
            f"CI [{ref_ci[0]:.1%}; {ref_ci[1]:.1%}]"
        )
    else:
        reasons.append(
            f"{H1_REFERENCE_YEAR} rate = "
            f"{ref_rate:.1%}" if ref_rate is not None else "rate unavailable"
        )
    if gap_ok:
        reasons.append(
            f"gap {years[0]}-{years[-1]} = {gap:.1%} > {H1_GAP_THRESHOLD:.0%}, "
            f"CI [{gap_ci[0]:.1%}; {gap_ci[1]:.1%}]"
        )
    elif gap is not None:
        reasons.append(f"gap {years[0]}-{years[-1]} = {gap:.1%}")

    # "H1 is refuted if the rate stays below 20% **everywhere** OR if the age effect is
    # null."
    #
    # The plan says "or", and the first version of this code had read "and". The
    # difference is not cosmetic: with "and", a world where links die a lot but with no
    # relation to age would be classified "grey zone" and would justify enlarging the
    # sample. But H1 asserts two things at once, including that "the death rate grows
    # markedly with age". Without an age effect, H1 is false whatever the rate — and the
    # plan then requires publishing and stopping.
    rates = [c.dead_rate(policy) for c in by_year.values()]
    all_below = all(r is not None and r < H1_RATE_THRESHOLD for r in rates)
    no_age_effect = gap_ci is not None and gap_ci[0] <= 0 <= gap_ci[1]

    if rate_ok and gap_ok:
        verdict: Verdict = "supported"
    elif all_below:
        verdict = "refuted"
        reasons.append(f"every stratum below {H1_RATE_THRESHOLD:.0%}")
    elif no_age_effect:
        verdict = "refuted"
        reasons.append("age effect not demonstrated: the gap's interval contains zero")
    else:
        verdict = "grey_zone"
        reasons.append(
            f"one criterion out of two: enlarge the sample once only, "
            f"factor {GREY_ZONE_FACTOR} (§2)"
        )

    return H1Result(verdict, ref_rate, ref_ci, gap, gap_ci, unknown_rate, reasons, policy)
