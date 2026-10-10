# artifact-rot

Measuring, at scale and repeatably, **whether the links to code and data announced in scientific
papers actually resolve**, and how fast they die.

The deliverable is not a raw rate but **the half-life of a research-artifact link**, estimated from
a survival curve and broken down by host, discipline and publisher. No public, replayable version
of this figure exists.

## What the project measures, and what it does not

It measures **HTTP responses and identifier resolutions**. Nothing else.

- Measured: "on 20 September 2026, this link does not resolve".
- Not measured, never claimed: "these authors did not share their data".

A dead link can come from a university migration, a renamed repository, or a server that happened
to be down that day. The report says so, and measures anyway, because for a reader trying to
reproduce the work the outcome is the same.

**No author is ever named.** Aggregates are about institutions, which have policies; an individual
has no policy, only a server that went down.

## Status

| Step | Status |
|---|---|
| E0 — literature review | **done** — [`docs/related-work.md`](docs/related-work.md); no equivalent continuous observatory |
| E1 — frozen stratified sample | **passed** on 2026-09-20: 40,000 papers, 20 strata, Jaccard 1.0 on replay ([`docs/sample.md`](docs/sample.md)) |
| E2 — probes and classification | **passed** on 2026-09-20: 139/141 (0.9858) against a 0.98 threshold; `restricted` family of 24 cases, 15 non-circular ([`docs/control-set.md`](docs/control-set.md)) |
| E3 — extraction from full text | **measured**: text recall 0.495; extraction takes the union of text and publisher markup ([`docs/extraction.md`](docs/extraction.md)) |
| E4 — three-pass scheduler | **passed**: complete dry run 2,363/2,363, no quota exceeded ([`docs/scheduler.md`](docs/scheduler.md)) |
| E5 — official S1 run | **three passes done** (21 Sep, 26 Sep, 4 Oct 2026) on 3,988 links. Preregistered verdict: **grey zone**. Unknown rate 22.8%, above the 5% criterion |
| Extension — artifacts only, 3x | **in progress**, declared before collection ([`docs/extension.md`](docs/extension.md)). Verdict scheduled for 2026-10-15 |
| E6 — survival, half-life, H1 verdict | **analysis written and validated on 2026-09-21, before any numbers** ([`docs/analysis.md`](docs/analysis.md)) |
| E7 — decision | after the extension verdict |

No step starts before the previous one meets its criterion (PLAN.md §7).

## Preregistration

The decision rule and the analysis were written before the data they judge, and this can be
checked independently:

- the repository was archived by [Software Heritage](https://archive.softwareheritage.org/) on
  **2026-10-10 at 16:54 UTC**, five days before the extension verdict;
- the preregistration documents were written in French. Their original text is identified by its
  git content hash, which is identical in the Software Heritage archive and in this repository's
  history:

| Document | Written | Git blob of the French original |
|---|---|---|
| Analysis plan (`docs/analyse.md`, now `docs/analysis.md`) | 2026-09-21 | `e8ab190ca9070089ed6bef267ce3d4a38ea86091` |
| Extension plan (`docs/prolongation.md`, now `docs/extension.md`) | 2026-10-04 | `60250bdf4e304483d9f9c14656a0e4a5b87f05eb` |
| Decision code (`artifact_rot/survival.py`) | 2026-09-21 | `7d1e63ef152c8151f3ea6d85e62266e7aa0b0b4e` |

The English files are translations. Where they differ from the French originals, the originals
prevail.

## The four states of a link

`alive` / `dead` / `restricted` / `unknown`. Never two.

`unknown` (the crawler failed) **never enters the denominator of a published rate**. It is counted
and reported separately. Turning a crawl failure into a "dead link" would be falsification, and it
is the error that would destroy the project.

A link is declared `dead` only after **three failures on three distinct dates at least ten days
apart**. The rule is a deterministic function, named in every result, and tested
(`tests/test_resolve.py`).

## Being a good network citizen

`robots.txt` is respected, request rates are deliberately low, API quotas are respected, and no
protection is ever bypassed. The `User-Agent` carries the project URL and **a reachable contact**:
the `ARTIFACT_ROT_CONTACT` variable is mandatory and its absence is a blocking error.

If a host asks us to stop, we stop and say so in the report.

## Getting started

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

uv run pytest                                    # offline test suite

export ARTIFACT_ROT_CONTACT="you@example.org"
export GITHUB_TOKEN="ghp_..."                    # optional, 60 req/h -> 5,000 req/h
uv run python -m artifact_rot.control            # E2 control set
```

## Reuse, not reimplementation

`scienceverse/metacheck` (R, AGPL-3.0) already extracts and checks repository links. Its code
cannot be reused here, because of language and licence, but its **failure modes measured on 1,861
papers** can, and they are worth more than code: URLs split by GROBID, the references section
excluded by default, an uncovered Figshare pattern. All three are named regression tests in
`tests/test_normalize.py`. Details and sources: `docs/related-work.md` §2.2.

This repository's own contribution: existence probes through APIs with a named classification
reason, the separation between `restricted` and `unknown`, the distinction between "dead" and
"never existed" through Software Heritage, and a control set whose ground truth is built by
construction.

## Stopping rule

If hypothesis H1 is refuted (links survive well), the positive result is published, since it is
informative in its own right, and the project stops. No maintenance out of inertia.

The full plan: [`PLAN.md`](PLAN.md).

## Licence

Code under the MIT licence. See [`LICENSE`](LICENSE) and [`CITATION.cff`](CITATION.cff).
