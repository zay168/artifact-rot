# E2 — The control set

> E2 pass criterion (PLAN.md §7): **correct classification ≥ 98%** on a control set whose state is
> known **by construction**.
> If this threshold is not met, no figure produced afterwards is worth anything. It is the project's
> health check, which is why it was the first code written.

---

## 1. Why "by construction"

The project rests on one idea: when ground truth is expensive, move the experiment to a terrain
where it builds itself. The control set applies the same principle to itself. Nobody annotates.
Each case is true for a mechanical reason, written in its `provenance` field and checkable without
trusting whoever wrote the list.

## 2. The families

| Family | n | How the truth is built | Cost |
|---|---|---|---|
| `dead` | 90 | URL on a real host, in a namespace drawn from **128 random bits**. A collision is impossible at any practical scale. | none |
| `alive` | 16 | Public resources backed by durable organisations (Linux, CPython, NumPy, GNU, Software Heritage, DOIs of published papers). | none |
| `malformed` | 9 | **Syntactic** invalidity, evaluated offline. No network request, hence no uncertainty. | none |
| `waf` | 2 | Host behind a web application firewall. The expected answer is `unknown`. | none |
| `restricted` | 24 | Three sources, see §2a: GitHub legal takedowns (12, **non-circular**), restricted Zenodo records (9, partially circular), resources owned by the author (3). | one manual step, once |

## 2a. Result measured on 2026-09-20 (`restricted` family completed)

```
E2 control set — 141 cases — verdict: pass
  alive       n=16   accuracy=0.938  unknown=1
      X alive-012  unknown  transport_timeout  https://osf.io/ezcuj/
  dead        n=90   accuracy=1.000  unknown=0
  malformed   n=9    accuracy=1.000  unknown=0
  restricted  n=24   accuracy=0.958  [9 circular; excluding circular: 0.933]
      X restricted-000  dead  github_api_404  https://github.com/zay168/Lucid-project
  waf         n=2    accuracy=1.000  unknown=2
```

**139 out of 141, i.e. 0.9858. The 98% criterion is met.**

And this time the `restricted` family weighs enough to say something: **24 cases, 15 of which have
a truth that does not come from our own probe.**

### Two sources for `restricted`, of different quality

**Non-circular — GitHub repositories taken down for legal reasons (12 cases).** The truth comes from
the public [`github/dmca`](https://github.com/github/dmca) repository, which archives every takedown
notice. We read an HTTP code; the register archives a legal document. The two are independent. All
12 are classified `restricted` by `github_api_451_legal`.

It is the only source of `restricted` ground truth that requires owning nothing, and it could not be
found until we looked on the legal side rather than the technical side.

**Partially circular — restricted or embargoed Zenodo records (9 cases).** The truth comes from the
`access` field of the Zenodo API, which our probe reads itself. These cases check that the pipeline
holds, **not that the classification is right**. The `circular` field flags them, and the report
gives accuracy excluding circular cases next to overall accuracy — announcing 0.958 without this
distinction would have overstated.

**Owned by the author (3 cases).** A GitHub repository made private, a private OSF project, a Zenodo
deposit under embargo until 2030.

### The two errors, and why they are not of the same kind

`alive-012` — `https://osf.io/ezcuj/` came back with a **network timeout**, hence `unknown`. This is
not a classification error: it is the correct answer when the crawler fails (§4, pitfall 2). It
counts as an error in the score because the score compares against the expected value, and rightly
so — but it measures the state of the network that day, not the quality of the probes.

`restricted-000` — the private GitHub repository is classified `dead`. **This is the error announced
before measuring, and it is irreducible**: the GitHub API returns 404 for a private repository as
for a deleted one, and no public call distinguishes the two.

### Consequence for the E6 report

The limitation cannot be fixed, only bounded. The report must publish **the number of GitHub `dead`
links flagged `indistinguishable_private_or_deleted`**, which bounds the population of possibly
`restricted` links wrongly counted as dead. A reader can then redo the computation the other way.
It is the only honest way to handle an ambiguity that cannot be resolved.

**Done on 2026-09-20**: the family went from 3 to 24 entries. With n = 3, a single error moved
family accuracy by 33 points, which made it unreadable.

### What the first real run corrected — in the set, not in the probes

The first run gave 0.938 on `alive` and 0.889 on `dead`. Both causes were defects of the control
set, not of the classification:

1. **`openalex.org` answers `403` (Cloudflare) to a crawler.** The eleven cases using it came back
   `unknown` — which is the **correct** answer under §4 ("a `403` can be Cloudflare, not a
   deletion"). Counting them as errors amounted to penalising the probe for refusing to conclude.
   These cases became the `waf` family, whose expected answer *is* `unknown`: they now check that
   the crawler never flips a block into a death. The generic `alive` and `dead` cases moved to
   `python.org` and `gnu.org`, which answer honestly.
2. **`https://doi. org/10.7939/…` was wrongly classified `malformed`.** It is not a broken link but a
   valid link split by PDF extraction, which `repair_spaced_hosts` rejoins — and must rejoin.
   Counting it `malformed` made a successful repair look like a failure. The case stayed, in its
   proper place, in `tests/test_normalize.py::TestMetacheckBug2GrobidWhitespace`.

No probe was changed to raise the score. Both corrections concern cases whose expected label was
wrong, and the reasoning is written here so that it can be contested.

## 3. The `restricted` family — how it was built

This was the honest gap in the setup. It is filled, and how it was filled is worth recording,
because it came down to an idea rather than effort.

`restricted` (the resource exists but access is controlled) is the hardest category to classify
correctly and the most costly to get wrong: confusing it with `dead` artificially inflates the main
figure, in exactly the direction that flatters the project's thesis. A control set that omits it
measures everything except what matters.

**Consequence encoded in the code**: `_score()` refuses to issue a verdict until all four families
are present. It returns `verdict: "incomplete"`, never an overall percentage. This rule has its own
test (`test_no_verdict_if_a_family_is_missing`).

### Provisioning, once and for all

Create a file `data/control/restricted.json`:

```json
[
  {
    "url": "https://github.com/<you>/<private-repo>",
    "kind": "code_repo",
    "provenance": "GitHub repository created then made private on 2026-09-20; owned by the author"
  },
  {
    "url": "https://osf.io/<guid>/",
    "kind": "data_repo",
    "provenance": "OSF project created as private on 2026-09-20; owned by the author"
  },
  {
    "url": "https://zenodo.org/records/<id>",
    "kind": "data_repo",
    "provenance": "Zenodo deposit under embargo until 2030; owned by the author"
  }
]
```

Six to ten entries suffice: the family's weight in the overall score is small, but its **presence**
is the condition for a verdict. The file is versioned (the URLs are public; only access to the
content is not).

### A revealing case to include

A **GitHub repository created, made public, then made private**. The GitHub API will return `404`,
as for a deleted repository — the two are indistinguishable publicly (see `probe/api_github.py`).
This case will therefore be *classified `dead` although it is `restricted`*, and it **must** count as
an error in the score.

That is intended. This case measures the only known structural limitation of the probes, and it must
appear in the figure rather than in a footnote. If this limitation drags accuracy below 98%, the plan
requires dealing with the problem — systematic Software Heritage enrichment (`probe/api_swh.py`), or
reclassifying every GitHub `404` into its own category — not removing the case from the set.

## 4. Running

```bash
export ARTIFACT_ROT_CONTACT="you@example.org"    # mandatory: PLAN.md §4, pitfall 5
export GITHUB_TOKEN="ghp_..."                    # optional: 60 req/h -> 5,000 req/h
uv run python -m artifact_rot.control
```

Output: one table per family and a full report in `runs/<timestamp>-control/control.json`,
containing each case, the observed status, the **named reason** for the classification and the raw
evidence. Exit code `0` only if the verdict is `pass`.

## 5. Reading the result

Three readings, in this order:

1. **`verdict`**. `incomplete` means a family is missing — not a failure, unfinished work.
2. **Accuracy per family**, never only the overall figure. 98% overall with 60% on `restricted` is a
   failure disguised by unequal family sizes.
3. **The `unknown` count**. An `unknown` is not a classification error — §4 explicitly says so — but
   a high rate on the `alive` family signals a blocked crawler, and E5 requires under 5% `unknown` to
   pass.

Each listed error carries its named reason (`github_api_404`, `soft404_control_similar`,
`http_blocked_by_waf`…). An error without an identifiable reason is a bug in the control setup, to be
fixed before touching the probes.

## 6. What the control set does not measure

To be written in the E6 report, among the limitations:

- It measures the **classification of a link**, not the **extraction** of a link from a paper. That
  is E3, with its own criterion and its own regressions (see `docs/related-work.md` §2.2).
- The `alive` cases are highly visible, hence well-served resources. A slow or erratic lab server is
  under-represented — which is precisely where the generic probe is most fragile. The `unknown` rate
  of the real run (E5) is the true judge of this, not the control set.
- The `dead` cases have always been dead. A link that died *recently*, whose host still keeps a
  transition page, is not represented.
