# E3 — Finding the links in papers

> Pass criterion (PLAN.md §7): **recall verified on a subset where links are already known through
> structured metadata.**
> **Verified on 2026-09-20. The result is poor, and that is the useful information.**

---

## 1. The ground truth builds itself, once again

Not a single paper had to be annotated. Every published document carries its links **tagged by the
publisher**:

- a PDF stores them as `/URI` annotations — which is what makes a link clickable;
- a JATS file tags them as `<ext-link>`;
- an HTML page puts them in `<a href>`.

Our extractor works on the **rendered text**. Recall is measured one against the other. Same
principle as the one the whole project rests on: when ground truth is expensive, move the experiment
to where it builds itself.

## 2. The figure

On 187 PDF and JATS documents from the subsample:

| | tagged links | found in the text | recall |
|---|---|---|---|
| **Overall** | 1,359 | 673 | **0.495** |
| DOIs (mostly bibliography) | 1,347 | 669 | 0.497 |
| Repositories (GitHub, Zenodo, OSF…) | 12 | 4 | 0.333 |

And the other way round: **690 links found in the text that the markup does not contain.**

**Conclusion, which is E3's real output: neither source suffices.** Text extraction misses half of
what the publisher tagged; the markup misses 690 links that the text carries in plain form. The
production extractor therefore takes **the union of the two**, which was already the case in
`extract/links.py`, and is now justified by a measurement rather than an intuition.

### The caveat not to hide

**Twelve repository links are too few to conclude anything** about recall on the population the
project actually cares about. 0.333 on n = 12 is four links out of twelve. This figure must not be
quoted.

That is a result in itself: across 400 open-access papers, publisher markup declares only twelve
repository links. Artifact links are **rare**, and the E3 subsample had to be enlarged substantially
before E5 for per-family recall to mean anything.

## 3. Three defects found by measuring, not by reviewing

### 3.1 A landing page is not a paper — the most serious

The first version ranked locations by source type: repositories first, publishers next. It
therefore picked a repository's **landing page** (`zenodo.org/records/…`) over the publisher's PDF.

But a landing page is not the paper. Its text belongs to the host site, and its links are those of
its menu and footer.

The defect was invisible at retrieval time: retrieval "worked", returning 200 and HTML. It surfaced
when computing recall, in a puzzling form: the supposedly missed repository links were Zenodo's own
links **to its own source code** — `github.com/zenodo/zenodo-rdm`, `zenodo.org/help/statistics`. Of
78 missed repository links, 70 were of this kind.

Without this measurement, the full S1 run would have extracted links from landing pages instead of
papers, and produced a perfectly clean and perfectly wrong survival rate.

Fix: **every PDF now ranks before every HTML page.** The order is now repository PDF, publisher PDF,
repository page, publisher page.

> **Operational consequence**: the full-text cache built before this fix contained landing pages.
> It was **rebuilt before E5**.

### 3.2 Recall measured on HTML is meaningless

A corollary of the above. An HTML page mixes the paper with the site's chrome, and no
regular-expression rule separates them reliably. A PDF's annotations and a JATS file's
`<ext-link>` elements, by contrast, belong to the document.

Recall is therefore computed only on PDF and JATS. **125 HTML pages were excluded from the
computation**, and this number is reported on every run rather than kept quiet.

### 3.3 A real URL brought the pipeline down

The computation stopped dead on `ValueError: Invalid IPv6 URL` — a lone `[` in a URL found in a PDF
is enough to make the standard library's `urlsplit` raise.

A paper's URL is a string found in a PDF: it can be anything. No function in `normalize.py` may
raise because of it. Seven hostile URLs were added as regressions.

On a 40,000-paper run, this defect would have interrupted processing at an unpredictable moment.

## 4. The causes of missed links, counted

Among repository links tagged in the markup but not found in the text:

| cause | share | fixable? |
|---|---|---|
| absent from the text (link placed behind a clickable word) | 73% | no — a limit of the world, not of the code |
| host mentioned but URL hidden | 12% | no |
| unrepaired PDF line break | 10% | partly |
| present but missed by extraction | 5% | yes |

The top 85% of the table are **not** an extractor defect: when a publisher writes "our GitHub
repository" and puts the URL behind the words, no reading of the text can recover it. That is
precisely why the markup is part of the union.

PDF line breaks remain partly irreducible: a URL split in the middle of a path segment
(`low-code-LLM-CDE-`, then a line break, then `extraction`) cannot be rejoined without risking
inventing links. Rejoining too broadly would be worse than missing.

## 5. Full-text retrieval: what is accessible

Three measurements made before writing a single line:

- **PDF 54%, HTML 7%** among `best_oa_location` locations. An HTML-only extractor would have
  measured one discipline, not four.
- **Europe PMC only covers medicine**: 38% of medical papers in JATS, 1 to 2% elsewhere. An
  excellent source, but not a sampling source.
- **Preferring repositories raises retrieval from 61% to 72%**, and real harvesting reaches ~80%.
  Wiley, ScienceDirect, MDPI and OUP answer 403 to a crawler; arXiv, PMC and institutional
  repositories do not.

We fetch elsewhere a copy the author deposited themselves. **No 403 is forced**, no block is
bypassed (§4, pitfall 5).

**The residual attrition (~20%) is a limitation to be published**, broken down by stratum: if it
correlated with year, it would bias the project's main explanatory variable.

## 6. Provenance of a link

A link announced in "Data Availability" is an explicit promise by the paper. The same link in the
bibliography may belong to a cited paper. Confusing the two would attribute to authors a promise
they did not make — which §9 forbids.

Three provenances: `availability_statement`, `body`, `references`. The bibliography is located at
the **last** occurrence of its heading, not the first: a paper often mentions "References" in a
table of contents before the real section, and taking the first would classify half of the body
text as doubtful provenance.

A link that comes only from annotations is marked `body`: an annotation does not say which section
it sits in.

## 7. Commands

```bash
export ARTIFACT_ROT_CONTACT="you@example.org"

uv run python -m artifact_rot.harvest fetch 400    # download and cache
uv run python -m artifact_rot.harvest recall       # measure recall
uv run python -m artifact_rot.harvest links        # produce the links to probe
```

---

## 8. What exists elsewhere — three options evaluated, one adopted

The plan requires looking before building. Three tools or services were evaluated **on our own
sample**, not on their documentation.

### 8.1 ScholExplorer / Scholix — dropped, and that is a result

[ScholExplorer](https://scholexplorer.openaire.eu/) (OpenAIRE) aggregates publication ↔ dataset
links declared by Crossref, DataCite and OpenAIRE. On paper, it is the ideal shortcut: nothing to
extract, just query a curated database.

Measured on 200 papers from our sample that have a DOI:

| | |
|---|---|
| papers with at least one Scholix link | 126 / 200 (63%) |
| of which at least one link to a **dataset** | **2 / 200 (1%)** |
| `IsRelatedTo → publication` links (citations) | 1,060 |
| `IsRelatedTo → dataset` links | 2 |

**The curated graph is almost empty for what we need.** What it contains is citations between
papers. This option is dropped.

It is itself an observation for the E6 report: not only do links die, but **the structured metadata
meant to record them barely exists**. A data link announced in a paper has, in the vast majority of
cases, no trace anywhere other than in the paper's text.

### 8.2 GROBID / Docling — not now, for a measured reason

[GROBID](https://github.com/grobidOrg/grobid) is the reference tool for converting a scientific PDF
into structured XML; [Docling](https://github.com/docling-project/docling) does comparable work
without a Java server. The [pdf4llm](https://github.com/The-Metascience-Observatory/pdf4llm) project
shows that combining the two recovers ~10% of papers that neither handles alone.

That would be the reflex. The measurement says to hold off for now:

| indicator on our 187 documents | value |
|---|---|
| median length of extracted text | 36,767 characters |
| documents under 5,000 characters | 6 / 187 |
| end-of-line hyphenation breaks | 0.81 per 1,000 characters |
| documents with visibly damaged text | 32 / 187 |

**Extracted text is not the bottleneck.** Whole papers come out, and 85% of missed links are missed
for reasons no parser fixes — the URL sits behind a clickable word, and only the PDF annotation
contains it. And we already read annotations.

Decision: **GROBID remains an option, not a dependency.** It will be reconsidered if E5 shows
attrition correlated with text quality. Adding a Java service and Docker to a one-person project,
for a gain bounded at ~10% of a subset, is a bad trade today.

### 8.3 ODDPub — method reused, code not reusable

[ODDPub](https://github.com/quest-bih/oddpub) detects data and code sharing in biomedical
publications. The package is **R under AGPL-3.0**: same situation as `metacheck`, the code cannot be
reused in a Python stack without contaminating the licence.

But [the published paper](https://doi.org/10.5334/dsj-2020-042) is under **CC BY 4.0**, so the
**method** can be reused with attribution. What is reused: the principle that a sharing statement is
detected by **co-occurrence of keyword categories within a single sentence**, and the split into
categories. What belongs to this repository: the lists themselves, rewritten for four disciplines
instead of biomedicine only.

Performance reported by the authors, as a reference point and not a promise on our corpus:
sensitivity 0.73 / specificity 0.97 for data, 0.94 / 0.82 for code.

Result of the implementation, measured on our 187 documents: section detection rose from **7 to 11
documents**, and false positives disappeared (8 → 0 on explicit refusals).

Two false positives from the real corpus were added as named regressions:

- "these translational symmetries are **not generally available** in curved space time" — triggered
  a refusal to share on a sentence of theoretical physics;
- a list of bibliographic references triggered an accession number, because the generic pattern
  `[A-Z]{1,2}\d{5,}` matches citation numbers.

And a subtle bug found along the way: under `re.IGNORECASE`, `[A-Z]` also matches lowercase. The
rule "the heading runs into the sentence, recognisable by the capital that follows" therefore did
not work at all, and "we discuss data availability in section 4" passed as a section heading.

## 9. The data availability statement is a recent institution

Measured on our 187 documents:

| year | papers with a data availability statement |
|---|---|
| 2010 | 0% |
| 2014 | 2.9% |
| 2018 | 0% |
| 2022 | 5.4% |
| 2025 | **16.3%** |

The gradient is clear and real — verified by searching for the phrase in the raw text, not only
through our rules.

**Design consequence**: restricting extraction to availability statements would produce almost
nothing on the old strata, which are precisely where the age effect is measured. Extraction
therefore covers **the whole paper**, and provenance is used to interpret, not to filter.

**Consequence for E6**: the crossing "does the paper announce sharing?" × "does the link resolve?"
will be very unbalanced across strata. It must be published as two separate measurements, never as a
single rate.
