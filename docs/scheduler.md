# E4 — The three-pass scheduler

> Pass criterion (PLAN.md §7): **complete dry run without exceeding quotas.**
> **Met on 2026-09-20**: 2,363 links due, 2,363 processed, no quota exceeded, estimated duration
> 1.16 h.

---

## 1. Why a database and not a script

The project's cost is not computation but **calendar time** (§8). Three probes at least ten days
apart impose two weeks between the first and the last.

The scheduler must therefore survive anything: a network outage, a reboot, a laptop closed for
twelve days. Hence a **SQLite** queue in WAL mode with `synchronous=FULL`: every probe is written to
disk as soon as it returns, and resuming means re-running the same command.

Two tests cover this promise — reloading the queue erases no probe, and closing then reopening the
database recovers the exact state.

## 2. A deliberate saving: a live link is no longer probed

The resolution rule (§5) says a single live observation wins. Probing an already-live link twice
more adds nothing to its status, and makes up most of the traffic.

Consequences, all accepted:

- the traffic imposed on hosts drops by about **80%** — that is §4, pitfall 5;
- a link that dies between pass 1 and pass 3 is counted alive. The measurement is therefore
  **conservative**: it underestimates mortality, never the reverse;
- the three probes remain mandatory to declare a link dead, **without exception**.

## 3. A budget is a rate, not a cap

First version: a pass stopped as soon as a host had received its quota, and silently dropped the
remaining links. That was wrong, and worse than wrong — it was silent.

A pass needing 2,919 DOI resolutions with a budget of 1,000 per hour is not a forbidden pass: it is
**a three-hour pass**. The scheduler therefore spaces requests `3600 / budget` seconds apart per
host, and the pass takes as long as it takes.

Budgets are deliberately **below** published limits: authenticated GitHub allows 5,000 requests per
hour, we take 2,000. We do not play close to someone else's quota.

Current rates (`artifact_rot/schedule.py`):

| host | rate |
|---|---|
| `eutils.ncbi.nlm.nih.gov` | 3,600 / h |
| `api.github.com` | 2,000 / h |
| `doi.org` | 1,800 / h |
| `zenodo.org` | 900 / h (a quarter of Zenodo's documented anonymous limit) |
| `api.osf.io`, `api.figshare.com` | 600 / h |
| `api.bitbucket.org` | 500 / h |
| `gitlab.com` | 300 / h |
| `archive.softwareheritage.org` | 120 / h |
| any other host | 600 / h (one request every six seconds) |

The plan counts the **worst case**, not the average: a GitHub link returning 404 triggers up to
three requests (repository, owner, Software Heritage). A budget computed on an average is a budget
exceeded every other day.

## 4. What is probed, and above all what is not

This is where the step produced the most value. The raw queue held **7,959 links** extracted from
400 papers. After filtering: **2,363**. The 5,596 excluded were excluded for four reasons, all
measured.

| excluded | n | why |
|---|---|---|
| `citation_doi` | 3,392 | DOI of a cited paper, not an artifact |
| bibliographic host | 1,688 | PubMed, arXiv, Scholar… a citation, not an artifact |
| `malformed_at_source` | 264 | broken since publication: nothing to probe (pitfall 3) |
| non-artifact reference | 252 | bibliography link to something other than a repository |

### 4.1 The most important: not every DOI is a dataset DOI

**Deliberate deviation from PLAN.md §5.** The plan lists `dataset_doi` among the tracked types.
Without a further distinction, this type absorbed **every** DOI encountered: 3,449 links out of
8,073.

The vast majority are DOIs of papers cited in bibliographies. Probing them would have produced an
excellent and irrelevant survival rate — **a paper's DOI is maintained by its publisher, it does not
die** — while inflicting thousands of needless requests on `doi.org`.

Hence an additional type, `citation_doi`, excluded from probing. The list of prefixes recognised as
data repositories (`10.5281` Zenodo, `10.6084` Figshare, `10.17605` OSF, `10.7910` Dataverse…) is
deliberately **conservative**: when in doubt, a DOI is a citation. A missed repository is a loss; a
paper counted as a dataset is a fault.

### 4.2 Preprint servers are citations

arXiv, bioRxiv, medRxiv, SSRN, HAL: 556 arXiv links in 400 papers, almost all citations. An arXiv
link points to a **paper**, not a code or data artifact.

### 4.3 Broken links are never probed

Pitfall 3. A malformed link could never have worked: there is nothing to probe, and the result
would be indistinguishable from a dead link. It is counted separately, as a measure of editorial
control.

### 4.4 What is kept despite its provenance

A **bibliography link pointing to a repository** is still probed. That is exactly the case measured
by metacheck (issue #411), where 3% of papers cite their repository only there. Excluding them
wholesale would lose these cases.

And NCBI is still probed when the URL designates data (`/nuccore/`, `/sra/`, `/geo/`…) rather than a
PubMed record.

## 5. The closing demonstration

Real pass on 60 links, with a GitHub token:

```
statuses: {'alive': 35, 'unknown': 18, 'dead': 7}
```

Then the state of the queue:

```
resolved statuses: {'alive': 35, 'unknown': 25}
```

**The 7 `dead` probes produce no dead link.** They become `unknown`, because one observation is not
enough: three are needed, on three distinct dates at least ten days apart.

That is §4 pitfall 2 in action, checkable on real output rather than on a promise.

## 6. Commands

```bash
export ARTIFACT_ROT_CONTACT="you@example.org"
export GITHUB_TOKEN="ghp_..."

uv run python -m artifact_rot.schedule load runs/<...>/links.jsonl
uv run python -m artifact_rot.schedule plan        # what the next pass would do
uv run python -m artifact_rot.schedule dryrun      # dry run, no network
uv run python -m artifact_rot.schedule run [n]     # real pass, at most n links
uv run python -m artifact_rot.schedule status
```

`run` can be interrupted and resumed: re-running the same command continues where the pass stopped.

## 7. Changes made after E4 (before the official run)

- **Concurrent execution across hosts** (`artifact_rot/limiter.py`). The queue holds over 2,000
  distinct hosts; serving them one at a time made a pass last the *sum* of per-host times. A
  per-host rate limiter with a thread pool makes it last the *maximum*. No host receives more
  requests, or faster, than before.
- **A hidden cap removed.** The HTTP client's connection pool was fixed at 4, a leftover from the
  sequential version, which silently cancelled all parallelism. Measured throughput went from 1.4
  to 7.7 links per second.
- **Deduplication by URL.** Two papers citing the same repository ask the same question; it is
  probed once per pass.
- **Site furniture removed by a rule rather than a blocklist**: a host that receives many distinct
  URLs from few papers is a scraped menu or reference apparatus, not a repository.
- **Citation paths**, not just citation hosts: `ncbi.nlm.nih.gov/pubmed/…` and
  `entrez/query.fcgi?db=PubMed` are PubMed citations served by a host that also serves data.
- **A domain name that no longer exists is classified `dead`**, not `unknown` (`probe/dns.py`),
  still subject to the three-pass rule and reported separately.
- **Windows console forced to UTF-8**: a Cyrillic hostname in the corpus crashed a report under
  cp1252 after the work had been done. The report must never be what breaks a run.
