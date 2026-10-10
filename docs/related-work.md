# E0 — Related work

> Review carried out on 2026-09-20. E0 pass criterion: "nothing equivalent running continuously, or
> a pivot decided".
> **Verdict: criterion met. No equivalent continuous observatory exists. Moving on to E1.**
> Every claim below is sourced. Figures quoted are the authors' own, not recomputed by us.

---

## 1. Verdict in one sentence

The literature on *link rot* of research artifacts consists of **retrospective snapshots, each
covering one discipline or one institution, never replayed**; existing tools (`metacheck`) are
**checking components**, not measurements published at scale; existing dashboards track the
**access status of the paper**, not the survival of its artifacts. The **public, multi-discipline,
multi-publisher and replayable survival curve** that `artifact-rot` aims for does not exist.

## 2. What exists

### 2.1 One-off studies — the reference points for the E6 report

| Study | Scope | Headline figure | Why it is not our measurement |
|---|---|---|---|
| **Caltech "Measuring data rot"** (PLOS ONE, 2024) — 2,166 supplementary links, 1,419 records, publications 2014–2022 (80.7% from 2020–2022) | One university | **5.4%** of links unavailable; **1.7%** for DOIs vs **5.9%** for URLs | One institution, a very recent corpus (hence heavy survivorship bias), a single probe in May 2023, completed **manually** in a browser. The authors acknowledge that roughly half of the real links are missing because of curation errors. |
| **PLOS ONE long term** (2022) — ~50,000 *Data Availability Statements*, 8,503 URLs and DOIs | One journal | **80%** of resources retrievable automatically; **78%** of URLs, **98%** of DOIs | One journal, one snapshot. Confirms the URL/DOI gap. |
| **American Astronomical Society** | One discipline | **44%** of 10-year-old links do not resolve | The order of magnitude that makes H1 plausible on the oldest stratum. |
| **Software engineering artifacts** (arXiv 2404.06852) | One discipline | **9.4%** average rot; **32.6%** on Dropbox/Google Drive, **11.8%** on personal pages, **6.4%** GitHub, **7.1%** Zenodo | The gradient by host type — exactly the breakdown planned in §6 of the plan, but for a single discipline. |
| **"Knock knock! Who's there?"** (arXiv 2207.12879) | 13,000+ *repository* URLs from FAIRsharing, re3data, OpenDOAR, ROAR | Availability "far from granted" | Measures **the repository's** home page, not the link to a paper's artifact. A single snapshot from July 2022. |
| **URL decay in MEDLINE**, **20 years of link rot in LIS** | Bibliographic references | Half-life estimated between **4 and 14 years** depending on the corpus | About **web citations**, not artifacts announced as available. They nonetheless set the expected order of magnitude of our half-life. |

**Consequence for §2 of the plan.** The H1 threshold of `20%` on the 2018 stratum is consistent
with this literature without being guaranteed: Caltech measures 5.4% on an almost contemporary
corpus, the AAS measures 44% at 10 years. A 2018 stratum (8 years old) sits in between. The
threshold is not renegotiated — it is simply noted as not trivially reached, which is the
condition for it to be a test.

### 2.2 `scienceverse/metacheck` — the component not to reimplement

- **Nature**: an **R** package, **AGPL-3.0** licence, lifecycle declared "experimental". Stated
  goal: automatically check research outputs against good practice. Successor to
  `scienceverse/papercheck`.
- **Ecosystem**: `scienceverse/bibr` is the upstream extraction pipeline (PDF, DOCX, JATS XML,
  HTML, ePub → versioned JSON: metadata, references, full text, tables, figures).
- **What is reusable here**: the tool is R under AGPL-3.0, our stack is Python. **No code can be
  reused without contaminating the licence or translating it.** What can be reused, and is worth
  more than code: its **documented failure modes**, listed below. They come from work on a real
  corpus that we will not have to redo.
- **What can be contributed back**: our existence probes (§4 of the plan) and our E2 control set
  are exactly what `metacheck` publicly lacks. Contribution considered after E2, not before:
  nothing is offered before having a reliability figure.

**Link-extraction failure modes measured by `metacheck` on the Cooper validation corpus (1,861
papers)** — *issue #411*. To be treated as a test specification for E3, not as an anecdote:

1. **References section excluded by default.** The 14 text-search backends use
   `include_refs = FALSE`. A repository DOI cited only in the bibliography, in the form
   `Data from: Author (Year). Title [Dataset]. https://doi.org/…`, becomes invisible. **55 of 1,861
   papers (3%)** affected.
2. **URLs split by GROBID.** PDF-to-text extraction inserts spaces into URLs:
   `https://doi. org/10.7939/DVN/QYMAYV`. Present in **1,582 of 1,861 papers (85%)**, mostly
   harmless, but fatal when a repository DOI falls on a line break.
3. **Uncovered Figshare pattern.** URLs of the form `/articles/<slug>/<id>`, without a
   resource-type segment, are not parsed and return `NA` even though the link was detected.

→ **Engineering decision, taken here**: `normalize.py` normalises whitespace **before** any regex
(pitfall 2); `links.py` treats the bibliography as a separate, flagged source, with the
misattribution risk recorded in the schema rather than silently discarded (pitfall 1); the
Figshare pattern `/articles/[^/]+/([0-9]+)` is covered from the start (pitfall 3). All three cases
enter `tests/` as named regressions.

### 2.3 Raw material

`OpenAlex`, `Crossref`, `DataCite`: open data, free APIs. These are inputs, not results. OpenAlex
provides the stratified sampling (E1) and the open-access status; DataCite and Crossref resolve
dataset DOIs.

### 2.4 Existing dashboards

*Open access* dashboards (HOAD and the landscape surveyed in *Scientific Data*, 2026) track the
**OA status of the paper**. None tracks the resolution of the links announced **inside** the paper.
A search was carried out explicitly on this point: no public, continuous service checking the
resolution of links in *Data Availability Statements* was found.

## 3. What is missing — our contribution, restated after the review

Three things that none of the sources above produces together:

1. **Continuity.** All studies are one-off probes. None is replayable: the method is described, the
   code and sample rarely published, and nobody repeats it six months later.
2. **The age × discipline × host × publisher crossing.** Each study holds a single one of these
   variables. The AAS age effect and the software-engineering host effect have never been measured
   on the same corpus.
3. **The half-life as a deliverable.** None of the studies publishes a survival curve with right
   censoring. The 4-to-14-year figures circulating in the literature concern **web citations**, not
   research artifacts, and are estimates derived from raw rates.

## 4. What the review changes in the plan

Nothing in the scope (§3), nothing in the thresholds (§2), nothing in the stopping rule. Three
execution additions:

- The three `metacheck` failure modes become named regression tests in E3.
- The E6 report will compare its figures with Caltech (5.4%), PLOS ONE (80% retrievable), AAS (44%
  at 10 years) and software engineering (9.4%), flagging the difference in scope each time. An
  isolated figure is contestable; a figure placed within a literature is less so.
- Caltech's method (**manual** browser checks of failures) is what our §4 forbids. It is a
  differentiating argument to write in the report: our classification is fully deterministic and
  therefore replayable, at the cost of an `unknown` category that is acknowledged and reported
  separately.

## 5. Sources

- [Measuring data rot: continued availability of shared data from a Single University — PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0304781)
- [Long-term availability of data associated with articles in PLOS ONE](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9401135/)
- [Inaccessible data sharing: Link rot in the Data Availability Statement](https://www.researchgate.net/publication/367547002_Inaccessible_data_sharing_Link_rot_in_the_Data_Availability_Statement)
- [Research Artifacts in Software Engineering Publications: Status and Trends — arXiv 2404.06852](https://arxiv.org/pdf/2404.06852)
- ["Knock knock! Who's there?" A study on scholarly repositories' availability — arXiv 2207.12879](https://arxiv.org/abs/2207.12879)
- [An update on URL decay in MEDLINE abstracts](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2435527/)
- [Link rot in LIS literature: a 20-year study](https://www.researchgate.net/publication/399761240_Link_rot_in_LIS_literature_a_20-year_study_of_web_citation_decay_recovery_and_preservation_challenges)
- [scienceverse/metacheck](https://github.com/scienceverse/metacheck) · [issue #411](https://github.com/scienceverse/metacheck/issues/411) · [scienceverse/bibr](https://github.com/scienceverse/bibr)
- [Mapping the Landscape of Open Access Dashboards — Scientific Data](https://www.nature.com/articles/s41597-026-07217-z)
- [OpenAlex](https://openalex.org/) · [developer documentation](https://developers.openalex.org)
