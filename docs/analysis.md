# E6 — The analysis, written before the numbers

> Written on 2026-09-21, **before passes 2 and 3**, hence before seeing any final result. Plan §2
> requires the decision criterion to be fixed before the first run; this document and
> `artifact_rot/survival.py` are its executable form.
>
> *English translation. The French original (`docs/analyse.md`, git blob
> `e8ab190ca9070089ed6bef267ce3d4a38ea86091`, archived by Software Heritage on 2026-10-10) is the
> preregistered text and prevails in case of discrepancy.*

An analysis written after the fact can always be adjusted, even in good faith, until it says what
was hoped for. Written beforehand, it no longer can.

---

## 1. A deviation from PLAN.md §6, and the important point

**The plan prescribes Kaplan-Meier. Kaplan-Meier does not apply to these data.**

Kaplan-Meier assumes that, for each subject, we observe **either its time of death or the last time
it was seen alive**.

That is not what we observe. We look, at a single instant, at links from papers of different ages,
and record for each one: alive or dead **today**. For a link from an eight-year-old paper, we only
know:

- if it is dead → it died somewhere between 0 and 8 years. Nothing more.
- if it is alive → it survived at least 8 years.

The literature calls these **current status data** (single-instant inspection, or case-1 interval
censoring). The appropriate nonparametric estimator is not Kaplan-Meier but **isotonic regression**
of the proportion dead as a function of age — here equivalent to the Turnbull estimator, computed
with the pool-adjacent-violators algorithm (PAVA).

**What Kaplan-Meier would have produced**: given these data, it is implicitly told that every dead
link died on the day its paper was published. The resulting curve would be systematically too
pessimistic — and nothing in its shape would reveal it. It would look perfectly normal.

This is exactly the kind of error §0 warns would backfire: the project measures other people's
rigour, and would publish a misspecified survival curve.

**What isotonic regression adds**: it forces survival to decrease with age. If sampling noise makes
a stratum go back up — 2014 better served than 2018 — it pools the two rather than publishing a
curve that rises. Survival that increases with age is impossible; showing it would present a
sampling artefact as a result.

**When the plan becomes applicable again**: once the project has two campaigns six months apart,
the data become genuinely interval-censored with known bounds, and Turnbull applies in its general
form. Kaplan-Meier still will not.

## 2. What never enters a denominator

**`unknown`.** Never, under any pretext (§4, pitfall 2). Counted and reported separately. This is
tested.

**`restricted`** is more delicate: the resource exists, it simply does not resolve in open access.
The main computation counts it as **alive** — which is what it is, in the sense of existence.

A variant that excludes it entirely from the denominator is computed at the same time and published
alongside, because the choice is debatable and a reader must be able to see what it changes.

## 3. The half-life is never extrapolated

If the curve does not fall below 0.5 over the observed range, the function returns **`None`**, not a
number.

It is the figure everyone will quote. Producing it by extrapolating beyond the oldest stratum would
be inventing it. "The half-life exceeds N years" is information; an extrapolated number is not.

## 4. The H1 verdict, coded word for word

§2 says:

> **H1 is supported** if the rate of unresolved links exceeds `20%` on the 2018 stratum, **and** if
> the gap between the oldest and the newest stratum exceeds `15 points`, with the 95% (Wilson) CI
> excluding 0 on both.
> **H1 is refuted** if the rate stays below 20% everywhere **or** if the age effect is null.
> Grey zone: enlarge the sample **once only**, by a factor of 3.

`verdict_h1()` makes no decision that is not in these three sentences.

### An "or" read as "and" — corrected before measuring

The first version required, to refute, that the rate be low **and** that the age effect be null.
The plan says "or".

The difference is not cosmetic. With "and", a world where links die a lot but without any relation
to age would have been classified "grey zone", which would have justified enlarging the sample —
that is, carrying on searching.

But H1 asserts **two things at once**, including that "the death rate grows markedly with age".
Without an age effect, H1 is false, whatever the rate. And the plan then requires publishing and
stopping.

In other words, the error ran in the direction that keeps the project going rather than the one
that stops it. That is the direction in which a bias most easily goes unnoticed.

### What remains a genuine grey zone

One case only: both signals exist, but one does not reach its threshold — for instance a 25% rate
and a real age effect of only 10 points. There, enlarging the sample can settle it.

### The interval is on the difference, not on two proportions

§2 requires the gap between strata to exceed 15 points "with the CI excluding 0". What is needed is
an interval on a **difference** (Newcombe's method), not two separate intervals: two intervals that
overlap slightly can correspond to a significant difference, and the reverse error is even more
common.

## 5. How the analysis was validated without real data

Same procedure as the E2 control set, applied to statistics: **build a world whose half-life is
known, run the estimator on it, and check that it recovers the number.**

`tests/test_survival.py` generates worlds with half-lives of 3, 5, 8 and 12 years, observed exactly
as the project observes its own — a single instant, strata of different ages. The estimator must
recover the half-life to within 15%.

Also checked, on constructed cases:

- `unknown` never enters the denominator;
- the survival curve is always decreasing;
- an out-of-range half-life returns `None`, not a number;
- all four possible verdicts, each on a world that calls for it;
- a small sample is not enough to support H1, even with a 40% rate — which is precisely what the
  confidence interval is there to prevent.

## 6. What is still missing

- The **unknown rate** is at 26% after pass 1, while E5 requires under 5%. It is carried by
  `H1Result.unknown_rate` and must be published at the top of the report, not in a footnote.
- The breakdowns **by host, discipline and publisher** (§6) use the same functions on subsets.
  Nothing new to write, but cell sizes will be small and intervals wide: to be published with their
  intervals, never alone.
- `report.py` — the formatting. It comes **after** the verdict, never before (§9).
