# Implementation plan — Observatory of research-artifact survival

> File to be placed at the root of the repository. To be read in full by the implementing agent
> before the first line of code.
> Code name: `artifact-rot`. The public name will be decided after the first report.
> This plan replaces the two previous ones (`calibration-bench`, `provenance-watch`), both abandoned:
> annotation cost for the first, an unwanted AI scope for the second.
>
> *English translation of the original French plan. The French text is kept in the git history and
> in the Software Heritage archive of 2026-10-10.*

---

## 0. Working framework (overrides the agent's default habits)

### Register
- **To Zayd** (diagnosis, result, estimate): strictly factual. No embellished figure, no polite
  congratulations.
- **To the outside world** (report, README, website): framing and selection are deliberate, facts
  are untouchable. The project measures other people's rigour — the slightest approximation will
  backfire.

### Epistemic calibration
This project measures **HTTP responses and identifier resolutions**, not scientific honesty. A
structuring distinction, held in every line of code as in every line of the report:
- Measured: "on 20 September 2026, this link does not resolve".
- Not measured, never claimed: "these authors did not share their data".
A dead link can come from a university migration, a renamed repository, a server down that day. The
report says so, and measures anyway — because from the point of view of a reader trying to
reproduce, the outcome is the same.

### Posture
- **Deliver finished work.** No sketch awaiting a follow-up. Edge cases are handled before they
  arise.
- **Autonomy.** Settle execution details alone. One question only, and only if the ambiguity changes
  the result; otherwise pick the most defensible option and flag the assumption in one line.
- **Candour.** Say when a path is wrong, a figure false, a hypothesis dead. Criticism targets the
  path, never the height of the goal.
- **Zero complacency.**

### Always up to date
`scienceverse/metacheck` exists and already extracts and resolves repository links from papers —
**read it, assess it, reuse it or contribute to it rather than reimplement**. Likewise for the
OpenAlex and Crossref clients. Reimplementing an existing component is a methodological fault, just
like starting from scratch without looking. The code states in comments: what is reused, from where,
and where the original contribution lies.

### Conduct
- **Descartes**: decompose, order from simple to compound, exhaustively enumerate the possible states
  of a link.
- **Bacon**: test the most fragile hypothesis first, with the smallest experiment that breaks it
  (§2).
- **Clausewitz**: centre of gravity = **the reliability of classifying a link as dead**. Everything
  else follows. Expected friction: crawl false positives.
- **Sun Tzu**: only fight battles already won on paper. No additional front before the S1 verdict.
- **Franklin**: a written metric, measured before being optimised.

### Stopping rule
If H1 (§2) is refuted — links survive well — the positive result is published, which is publishable
information in itself, and the project stops. No maintenance out of inertia.

---

## 1. Purpose

Measure, at scale and continuously, **whether the links to code and data announced in scientific
papers actually resolve**, and how fast they die.

### The structural trick: zero annotation cost
The ground truth is an **HTTP response code** and an **identifier resolution**. No human ever has to
judge anything. The label is produced by the machine, for free, on millions of cases.

It is a general principle, reusable well beyond this project: when ground truth is expensive, move
the experiment to a terrain where it builds itself. Here, the world answers on its own.

### The second asset: age builds the time series
Unlike a classic observatory that must wait months before having a curve, this one produces one
**from the first run**: sample papers from 2010, 2014, 2018, 2022, 2025, test everything today, and
the survival curve as a function of age comes out immediately. Continuous monitoring then adds the
prospective dimension.

Consequence: a publishable figure exists after a few weeks, not after a year. That is what makes the
project feasible for one person.

### What exists, what is missing
| Exists | Nature | Why it does not cover the need |
|---|---|---|
| "Data rot" studies (PLOS One, one university; PLOS ONE long term) | One-off, retrospective, narrow scope | A snapshot, one discipline, never replayed |
| `scienceverse/metacheck` | Extraction and checking tool | A component, not a measurement published at scale |
| Open Access dashboards (HOAD, etc.) | Track OA status | Measure access to the paper, not the survival of its artifacts |
| OpenAlex, Crossref, DataCite | Open data, free APIs | Raw material, not results |

**Original contribution**: scale (multi-publisher, multi-discipline), continuity, and the **survival
curve** — the half-life of a data link, a figure that exists nowhere in public, replayable form.

---

## 2. Hypothesis to break first (milestone S1)

**H1 — A substantial share of the code and data links announced in papers no longer resolves, and
the death rate grows markedly with the age of the paper.**

Decision criterion, written **before** the first run, not renegotiable after seeing the results:
- **H1 is supported** if the rate of unresolved links exceeds `20%` on the 2018 stratum, **and** if
  the gap between the oldest and the newest stratum exceeds `15 points`, with the 95% (Wilson) CI
  excluding 0 on both.
- **H1 is refuted** if the rate stays below 20% everywhere or if the age effect is null.
- Grey zone: enlarge the sample **once only**, by a factor of 3. No second extension.

The most fragile hypothesis, to test before anything else (Bacon): **is the classification of a dead
link reliable?** If the crawler produces 30% false positives, the main figure is noise and the
project is dead. That is E2 (§7), and it is the first code to write.

---

## 3. S1 scope (and S1 only)

- **Time strata**: 5 sampled years (e.g. 2010, 2014, 2018, 2022, 2025). Year is the main explanatory
  variable.
- **Discipline strata**: 4 fields with very different sharing cultures — biology/medicine, computer
  science, social sciences, physics/astronomy. The gap between disciplines is the second most
  interesting figure.
- **S1 volume**: ≥ 2,000 papers randomly sampled per crossed stratum, from OpenAlex, restricted to
  open-access papers whose full text is accessible.
- **Link types tracked**: code repositories (GitHub, GitLab, Bitbucket, Software Heritage), data
  repositories (Zenodo, Figshare, Dryad, OSF, institutional repositories), dataset DOIs, raw URLs.

**Out of S1 scope** — do not start, do not "just lay the groundwork": public website, named publisher
ranking, API, alerts, paywalled papers, analysis of repository *contents*, correlation with
citations.

---

## 4. The five pitfalls that kill the project

This is where the value is decided. Everything else is plumbing.

**1. The HTTP code lies.** A `200` can be a "repository not found" page. A `403` can be Cloudflare,
not a deletion. A `429` is a crawler failure, not a link failure. Mandatory handling:
- For hosts with an API (GitHub, GitLab, Zenodo, Figshare, OSF, DataCite, Crossref): **query the
  API, never the HTML**. The API answers unambiguously about existence.
- For the rest: soft-404 detection by deterministic heuristics (comparison with the response to a
  deliberately non-existent URL on the same domain — a classic technique, no annotation).
- Three attempts, **several days apart**, never within the same minute. A link is declared dead only
  after failing on three distinct dates.

**2. Four states, never two.** `alive` / `dead` / `restricted` (exists but access is controlled — a
legitimate case, frequent in medicine) / `unknown` (the crawler failed). `unknown` **never** enters
the denominator of a published rate; it is counted and reported separately. A crawl failure turned
into a "dead link" is falsification — the error that would destroy the project.

**3. Dead ≠ never existed.** A link typographically broken from publication is a different category
from a link that worked and then disappeared. Separate them in the schema from the start. The second
category is the real measure of rot; the first is a measure of editorial control, just as
interesting but not to be mixed in.

**4. "Available on request" is not a link.** It is a separate category, known to fail in practice,
and it would be dishonest to count it as a dead link or as a live one. It is counted separately and
the report says it was not tested — we will not write to thousands of authors.

**5. Be a good network citizen.** Respect `robots.txt`, aggressively low rate limits, a `User-Agent`
carrying a contact and the project URL, strict respect of API quotas, no bypassing of any
protection. An observatory that hammers scientific repositories is dead at birth, and deservedly so.
If a host asks us to stop, we stop and say so in the report.

---

## 5. Architecture

```
artifact-rot/
  PLAN.md                     ← this file
  pyproject.toml              ← uv, Python 3.12
  artifact_rot/
    sample.py                 ← stratified sampling from OpenAlex, fixed seed
    fulltext.py               ← full-text retrieval (open sources only)
    extract/
      statements.py           ← locating availability sections
      links.py                ← URL / DOI / identifier extraction
      normalize.py            ← canonicalisation, deduplication
    probe/
      base.py                 ← Prober(ABC): check(link) -> Status
      api_github.py / api_zenodo.py / api_osf.py / api_doi.py
      http_generic.py         ← soft-404 via control probe
    schedule.py               ← 3 spaced passes, persistent queue, resume
    survival.py               ← survival curve by age, Wilson CI, half-life
    report.py
  data/sample/                ← frozen sample, seed and query versioned
  runs/                       ← <ISO8601>-<git_sha>/ never overwritten
  tests/
```

### Contracts

```python
class Link(BaseModel):
    paper_doi: str
    paper_year: int
    discipline: str
    publisher: str
    raw: str                        # as written in the paper
    normalized: str
    kind: Literal["code_repo","data_repo","dataset_doi","generic_url","on_request"]
    host: str
    malformed_at_source: bool       # pitfall 3

class Probe(BaseModel):
    link_id: str
    probed_at: datetime
    method: Literal["api","http"]
    status: Literal["alive","dead","restricted","unknown"]
    evidence: dict                  # code, truncated body, API response
    attempt: int                    # 1..3
```

### Technical rules
- A run is immutable: `runs/<ISO8601>-<git_sha>/`, never overwritten, never cleaned up.
- The sample is frozen and versioned: seed, OpenAlex query, extraction date. A non-reproducible
  sample makes everything else unverifiable.
- A link's final status = a deterministic function of its 3 probes, defined in code and documented.
  No case-by-case judgement.
- All evidence kept: without the truncated response body, a dispute cannot be arbitrated.

---

## 6. The metric that carries the project

The raw rate of dead links is banal and will be contested on sampling grounds. The metric that holds,
and is the real deliverable:

**The half-life of a research-artifact link** — the time after which half of the links no longer
resolve, estimated from a survival curve (Kaplan-Meier), broken down by host type, discipline and
publisher.

It is better than the raw rate for three reasons: it absorbs sampling differences between strata, it
can be compared from one year to the next, and it can be said in one memorable sentence. It is the
figure that circulates — and it is honest, which is the condition for it to hold up when it does.

Design corollary: the data schema must allow right censoring from the start (a link still alive
today is a censored observation, not a definitive success). Planned now, not patched in later.

---

## 7. Execution steps

Strict order. No step is started before the previous one meets its criterion.

| # | Step | Output | Pass criterion |
|---|---|---|---|
| E0 | Review: read `metacheck`, check that no equivalent observatory exists, list existing one-off studies for comparison | `docs/related-work.md` | Nothing equivalent running continuously, or a pivot decided |
| E1 | Stratified, frozen, reproducible sampling | `data/sample/` | Replaying the seed yields the same sample |
| E2 | **Probes + classification** (§4) | code + tests | On a control set of 200 links whose state is known **by construction** (fabricated URLs: existing, deleted, private, malformed), correct classification ≥ 98% |
| E3 | Link extraction from full text | code + tests | Recall verified on a subset where links are already known through structured metadata |
| E4 | 3-pass scheduler, persistent queue | code | Complete dry run without exceeding quotas |
| E5 | Official S1 run (3 passes, ≥ 2 calendar weeks) | `runs/…` | `unknown` rate < 5%, no host under sustained rate limiting |
| E6 | Survival, half-life, analysis against the §2 criterion | `report.md` + figures | H1 verdict written **before** any formatting |
| E7 | Decision | — | Continuous monitoring, or publication of the negative result and stop |

**E2 is the project's health check.** The control set is built without annotation: create public
repositories yourself, delete some, make some private, fabricate malformed URLs. The truth is known
by construction — exactly the same principle as the one the whole project rests on. If
classification does not reach 98% on it, no figure produced afterwards is worth anything.

---

## 8. Budget and friction

- **Monetary cost**: zero, apart from a possible domain name. OpenAlex, Crossref, DataCite, the
  GitHub/Zenodo/OSF APIs: all free. No GPU, no annotator, no privileged access.
- **Real cost**: **calendar time**. The three spaced passes impose ≥ 2 weeks between the first and
  the last probe. It is not work, it is waiting — to be started early and left running while doing
  something else. It is Clausewitz's friction in its most benign form: predictable and free if
  anticipated, costly if discovered at the end.
- **Dispersion trap**: the temptation will be to add disciplines, years, link types. Each addition
  delays the first published figure without strengthening it. The §3 scope is closed until E7.

---

## 9. Editorial line of the report (E6)

- The verdict is written before the figures, before the title, before any formatting.
- **We measure resolutions, not intentions.** Every claim takes the form "of N links extracted from
  papers of year A, M did not resolve after three probes between such and such dates". Never
  "researchers in field X do not share".
- **No author ever named.** Aggregates are about publishers, journals, disciplines, hosts —
  institutions, which have policies. An individual has no policy, only a server that went down.
- Limitations are listed by us, first, exhaustively: restriction to open access, imperfect
  extraction, untested "on request" links, `restricted` distinct from `dead`, short probing window,
  OpenAlex sampling bias.
- Method, code, sample and evidence published **at the same time** as the figures.
- The title carries the half-life, not outrage. A simple figure circulates; the nuances in the body
  are what make it hold up when it does.

---

## 10. What this project is not

We are not building a fraud-detection tool, nor a verification service sold to journals, nor an
archiver, nor a moral ranking. We measure one thing, correctly, publish it, and do it again in six
months. Everything else comes after S1 — or does not come at all.
