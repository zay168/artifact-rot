# S1 extension — refocusing on artifacts, written before collection

> Written on 2026-10-04, **after** the verdict of the three passes and **before** any further
> collection. The commit introducing this file precedes the harvesting; the git history attests it.
>
> *English translation. The French original (`docs/prolongation.md`, git blob
> `60250bdf4e304483d9f9c14656a0e4a5b87f05eb`, archived by Software Heritage on 2026-10-10) is the
> preregistered text and prevails in case of discrepancy.*

## 1. What happened

The three passes (21 Sep, 26 Sep, 4 Oct 2026) on 3,988 links from 1,496 papers gave the following,
with the §2 criterion applied unchanged (`runs/20261004T014500Z-verdict/`):

| | Measured | Threshold | |
|---|---|---|---|
| Non-resolution rate, 2018 stratum | 33.1% (CI 29.4–37.0) | > 20% | met |
| Gap 2010 – 2025 | 7.8 pts (CI 2.3–13.4) | > 15 pts | not met |

Verdict: **grey zone**. §2 allows one extension, and only one, by a factor of 3.

## 2. Two findings that change what the extension must measure

**The figure is not about the project's subject.** 95% of probed links are `generic_url` links
cited in the body text (who.int, cdc.gov, youtube.com…). Links to code and data, the subject of
§1, number only 177. The 33% rate measures the disappearance of web references, a phenomenon
already documented, not that of artifacts.

**The E5 criterion is unreachable on generic URLs.** 22.8% `unknown`, against < 5% required. The
causes are firewalls (263), `robots.txt` (176), connection failures and timeouts (271). The first
two are permanent, and §4 forbids bypassing them.

## 3. What we already know — declared so as not to hide it

Among the 177 artifact links already probed three times: 6% of code repositories and 1% of data
repositories do not resolve. The refocusing is therefore decided **while knowing** a signal that
points toward refuting H1 on this scope. This is the opposite of an opportunistic refocusing: it
moves the project toward a negative result, not a spectacular one. We say so anyway.

## 4. What is fixed now, before collection

1. **Scope of the main analysis**: `kind ∈ {code_repo, data_repo, dataset_doi}`. The `generic_url`
   links already measured are published separately, with their "grey zone" verdict, never merged
   into the main figure.
2. **3x extension, the only one allowed**: from 100 to 300 papers per crossed stratum
   (2,000 → 6,000), taken from the already frozen E1 sample (40,000 papers). The 200 new papers per
   stratum are drawn from papers not yet harvested, seed `20261004`. No new OpenAlex draw.
3. **Only artifact links from the new papers are probed.** Probing thousands of generic URLs that
   no longer serve the main analysis would be a needless load on other people's servers (§4,
   pitfall 5).
4. **H1 criterion unchanged, word for word**: rate > 20% on 2018, and oldest – newest gap > 15 pts,
   95% CI excluding 0 on both. Same code (`verdict_h1`), same resolution rule (three failures on
   three dates at least 10 days apart).
5. **No second extension.** If the result is still in the grey zone, the grey zone is published.
6. **E5 criterion** assessed on the artifact scope, where probes go through APIs.

## 5. Limitations known now

- Extraction recall on repository links: 0.54 (E3). One artifact link in two is not extracted. No
  indication that this recall depends on the year; to be checked on the extension.
- Institutional repositories are classified `generic_url` by the extractor and therefore fall
  outside the scope. The published rate covers recognised hosts.
- Expected size: about 530 artifact links, roughly a hundred per year. Wide intervals per stratum;
  breakdowns by discipline will be indicative.

## 6. Schedule

Extension pass 1 on 2026-10-04; pass 2 from D+5; pass 3 from D+10; verdict on the evening of
pass 3.

*Note added on 2026-10-10 (not part of the preregistered text): pass 2 took place on 2026-10-10,
one day late. Pass 3 and the verdict therefore move to 2026-10-15. The criterion is unchanged.*
