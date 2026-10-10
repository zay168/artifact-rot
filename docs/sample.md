# E1 — The sample

> Pass criterion (PLAN.md §7): **replaying the seed yields the same sample**.
> **Met on 2026-09-20**: file integrity verified, mean Jaccard index of **1.0** over the twenty
> strata after a full replay of the query.

---

## 1. What was drawn

40,000 papers, 2,000 per crossed stratum, seed `20260920`.

| | 2010 | 2014 | 2018 | 2022 | 2025 |
|---|---|---|---|---|---|
| Medicine (OpenAlex `fields/27`) | 2,000 | 2,000 | 2,000 | 2,000 | 2,000 |
| Computer science (`fields/17`) | 2,000 | 2,000 | 2,000 | 2,000 | 2,000 |
| Social sciences (`fields/33`) | 2,000 | 2,000 | 2,000 | 2,000 | 2,000 |
| Physics / astronomy (`fields/31`) | 2,000 | 2,000 | 2,000 | 2,000 | 2,000 |

Filters applied, identical across all strata:
`open_access.is_oa:true`, `has_fulltext:true`, `type:article`.

Resulting composition: **9,211 distinct publishers**, **15,903 distinct journals**. The top five
publishers — Elsevier (2,418), IOP (1,394), Springer (1,249), Wiley (1,114), MDPI (1,080) —
account for 18% of the sample. Open-access status: diamond 12,067, bronze 9,753, gold 6,851,
green 6,187, hybrid 5,142.

All 40,000 papers have a full-text URL. There is therefore no attrition at this stage — E3's
attrition will come from extraction, not availability.

## 2. Two reproducibility mechanisms, not to be confused

**The seed.** OpenAlex's `sample=N&seed=S` returns the same draw for an identical query. Verified
on 2026-09-20: two successive calls, same identifiers, same order, across all twenty strata.

**The on-disk freeze.** The seed is not enough, because the queried *population* moves: OpenAlex
indexes continuously, corrects metadata, and its `has_fulltext` flag evolves. Replaying the same
query in six months may therefore yield a different draw without any bug being involved.

**The official sample is the file**, `data/sample/<timestamp>-seed<seed>/sample.jsonl`, together
with a manifest recording the exact query for each stratum, the seed, the extraction date and the
SHA-256 fingerprint.

`verify` checks the two separately:

- **integrity** — does the file match its fingerprint? A failure is always an error;
- **drift** — does replaying the query today return the same identifiers? A discrepancy is
  information about OpenAlex, measured and reported, never silently corrected.

## 3. Two decisions taken at this step

### 3.1 No filter on the presence of a DOI — and it matters

The §5 contract uses `paper_doi: str` as the key of a link. Measurement on the sample shows that
**the share of papers without a DOI in OpenAlex is strongly correlated with age**:

| share without DOI (%) | 2010 | 2014 | 2018 | 2022 | 2025 |
|---|---|---|---|---|---|
| Social sciences | **31.2** | 26.2 | 12.8 | 2.2 | 4.8 |
| Computer science | **22.6** | 15.6 | 11.8 | 1.9 | 2.2 |
| Physics / astronomy | 7.3 | 5.1 | 5.0 | 1.4 | 2.2 |
| Medicine | 5.7 | 3.3 | 2.3 | 0.7 | 1.2 |

Adding `has_doi:true` would have removed nearly a third of the oldest social-sciences stratum
against 2% of the newest. The filter would thus have introduced **a selection bias carried by the
project's main explanatory variable** — exactly the kind of choice that produces an age effect
without age having anything to do with it.

Decision: the key becomes the OpenAlex identifier (`W…`), present on 100% of the sample. The DOI is
kept when it exists, because it is what speaks to publishers and readers. Deliberate deviation from
§5, recorded in `models.py` where it applies.

### 3.2 "Medicine" rather than "biology/medicine"

The plan says "biology/medicine". The closest OpenAlex field is `Medicine` (27).
`Biochemistry, Genetics and Molecular Biology` (13) would be the other defensible choice, and closer
to "biology".

Medicine is chosen because it is the culture where "available on request" dominates — the case
pitfall 4 must be able to count separately. The choice is closed until E7. It is recorded here to be
contestable: someone redoing the draw with `fields/13` would probably obtain a higher sharing rate,
and that would be a result in itself.

## 4. A defect caught by the criterion, not by review

The first version of the code paginated the draw **by cursor**, as OpenAlex's documentation
prescribes for walking large sets. Under `sample=`, the API returns `next_cursor: null` from the
first page: the cursor does not paginate a draw.

Result: 200 papers per stratum instead of 2,000, **without any error raised**. The code worked; it
simply returned ten times less than requested.

Two fixes:

- classic `page=` pagination, verified against the API — disjoint pages, and the same (seed, page)
  pair returns exactly the same page;
- `build` now compares obtained against requested for each stratum, prints incomplete strata and
  **exits with code 1**. A short draw must be loud.

This shows the value of a numeric pass criterion: "replaying the seed yields the same sample" would
have been satisfied by the 200 papers. "2,000 per stratum" was not.

## 5. Limitations to report in E6

To be listed by us, first, as §9 requires:

- **Restriction to open access.** The scope excludes paywalled papers (§3). The measured rate holds
  only for OA, and nothing says practices there are representative.
- **`has_fulltext` is an OpenAlex flag**, not a guarantee that the text is usable. Real attrition is
  measured in E3.
- **OpenAlex indexing bias.** Coverage is finer for recent and English-language work. The
  missing-DOI gap above is a direct, measured manifestation of it.
- **One field per discipline.** An interdisciplinary paper is counted only under its
  `primary_topic`. The boundaries are OpenAlex's, not ours.
- **2025 is a young stratum.** Some of its papers are less than a year old; OA indexing there is
  still incomplete and will keep growing after the freeze.

## 6. Commands

```bash
export ARTIFACT_ROT_CONTACT="you@example.org"

uv run python -m artifact_rot.sample build      # draw, freeze, manifest
uv run python -m artifact_rot.sample verify     # integrity + population drift
```

`build` writes a timestamped directory and updates the `data/sample/LATEST` pointer. It never
overwrites an existing sample.
