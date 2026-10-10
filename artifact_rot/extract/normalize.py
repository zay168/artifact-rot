"""Link canonicalisation and deduplication.

Three of this module's rules come directly from failure modes measured by
`scienceverse/metacheck` on its validation corpus of 1,861 papers (issue #411,
AGPL-3.0, R — none of its code is reused, only the documented failure cases; see
docs/related-work.md §2.2). They are reproduced as named regression tests:

* `repair_spaced_hosts`: GROBID inserts spaces at line ends inside URLs
  (`https://doi. org/10.7939/DVN/QYMAYV`), observed in 85% of the corpus's papers.
  The repair is applied BEFORE any regex, never after.
* `FIGSHARE_ID` covers `/articles/<slug>/<id>`, a pattern without a resource-type
  segment that metacheck returned as `NA`.
* the `references` provenance is carried by `Link.source`, not silently discarded.

This module's own contribution is the separation of `on_request` / `malformed_at_source`
(pitfalls 3 and 4 of §4), absent from metacheck.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# --- Repairing URLs broken by PDF extraction ---------------------------------------

_SPACED_TLD = re.compile(
    r"\b((?:https?://)?(?:[\w-]+\.)+)\s+((?:org|com|net|edu|io|gov|fr|de|uk|ac\.uk)\b)",
    re.IGNORECASE,
)
_SPACED_SCHEME = re.compile(r"\bhttps?\s*:\s*//\s*", re.IGNORECASE)
_SPACED_PATH = re.compile(r"(https?://[^\s]+?)\s+(/[^\s]+)")


def repair_spaced_hosts(text: str) -> str:
    """Rejoin URLs split by PDF-to-text extraction.

    Conservative by design: only rejoins splits whose right-hand side is a known TLD or a
    path segment. Rejoining more broadly would invent links, which is worse than missing
    some — we measure rot, not regex creativity.
    """
    out = _SPACED_SCHEME.sub("https://", text)
    out = _SPACED_TLD.sub(lambda m: m.group(1) + m.group(2), out)
    out = _SPACED_PATH.sub(lambda m: m.group(1) + m.group(2), out)
    return out


# --- "On request" detection (pitfall 4) ---------------------------------------------

_ON_REQUEST = re.compile(
    r"\b("
    r"(?:available|obtainable|provided|shared|furnished)\s+"
    r"(?:(?:from|by|upon|on)\s+)*(?:the\s+)?"
    r"(?:reasonable\s+)?request"
    r"|upon\s+reasonable\s+request"
    r"|contact\s+the\s+(?:corresponding\s+)?author"
    r"|sur\s+demande(?:\s+raisonnable)?"
    r")\b",
    re.IGNORECASE,
)


def is_on_request(statement: str) -> bool:
    """"Available on request" is not a link: neither dead nor alive, never probed.

    Counted and reported separately (§4 pitfall 4). We do not write to thousands of
    authors.
    """
    return bool(_ON_REQUEST.search(statement))


# --- Host identifiers ----------------------------------------------------------------

GITHUB_SLUG = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?=[/#?]|$)",
    re.IGNORECASE,
)
GITLAB_PATH = re.compile(r"(?:https?://)?(?:www\.)?gitlab\.com/((?:[\w.-]+/)+[\w.-]+?)(?=[/#?]|$)")
BITBUCKET_SLUG = re.compile(r"(?:https?://)?(?:www\.)?bitbucket\.org/([\w.-]+)/([\w.-]+?)(?=[/#?]|$)")
ZENODO_ID = re.compile(r"zenodo\.org/(?:record|records|doi/10\.5281/zenodo\.)?/?(\d+)", re.IGNORECASE)
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
OSF_ID = re.compile(r"osf\.io/([a-z0-9]{5})(?=[/#?]|$)", re.IGNORECASE)
FIGSHARE_ID = re.compile(r"figshare\.com/(?:s/\w+|articles/(?:[^/]+/)?[^/]+/(\d+))", re.IGNORECASE)
DRYAD_DOI = re.compile(r"10\.5061/dryad\.(\w+)", re.IGNORECASE)
SWH_ID = re.compile(r"swh:1:(snp|rel|rev|dir|cnt):[0-9a-f]{40}", re.IGNORECASE)
DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+[a-z0-9]", re.IGNORECASE)

_CODE_HOSTS = {"github.com", "gitlab.com", "bitbucket.org", "softwareheritage.org", "codeberg.org"}
_DATA_HOSTS = {
    "zenodo.org",
    "figshare.com",
    "osf.io",
    "datadryad.org",
    "dataverse.harvard.edu",
    "dataverse.org",
    "opendata.example",
}

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"}
_TRAILING_PUNCT = ".,;:)]}>\"'"


_ENTITY_IN_URL = {"&amp;": "&", "&#38;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}


def _decode_entities(url: str) -> str:
    """Decode HTML entities left inside a URL.

    Observed on 2026-09-21 in the corpus: hundreds of URLs of the form
    `…query.fcgi?cmd=Retrieve&amp;db=PubMed&amp;dopt=Abstract`. The entity comes from the
    original HTML or PDF and passes through extraction unchanged.

    Probed as is, the URL is not the one the author wrote: the server receives a parameter
    named `amp;db` and may answer anything. A badly decoded URL therefore produces a wrong
    status — and, in the direction that suits the project's thesis, a false dead link.
    """
    for entity, char in _ENTITY_IN_URL.items():
        url = url.replace(entity, char)
    return url


def _safe_split(url: str):
    """`urlsplit` raises on some real URLs — a lone `[` is enough ("Invalid IPv6 URL").
    Encountered on 2026-09-20 in the real corpus, where it brought down the recall
    computation. A paper's URL is a string found in a PDF: it can be anything. No function
    in this module may raise because of it.
    """
    try:
        return urlsplit(url if "//" in url else f"https://{url}")
    except ValueError:
        return None


def host_of(url: str) -> str:
    parts = _safe_split(url)
    if parts is None:
        return ""
    netloc = parts.netloc.lower().removeprefix("www.")
    return netloc.split(":")[0]


def canonicalize(raw: str) -> str:
    """Canonical form used for deduplication and for `link_id`.

    Resolves nothing, follows no redirect: two different links in the text must stay two
    links if the authors wrote them differently, except for purely cosmetic differences
    (scheme, `www.`, trailing punctuation, tracking parameters, trailing slash).
    """
    url = raw.strip().rstrip(_TRAILING_PUNCT).strip()
    url = _decode_entities(url)
    url = repair_spaced_hosts(url)
    if url.lower().startswith("doi:"):
        url = "https://doi.org/" + url[4:].strip()
    elif DOI.fullmatch(url):
        url = "https://doi.org/" + url
    if "//" not in url:
        url = "https://" + url
    parts = _safe_split(url)
    if parts is None:
        # A URL that cannot be split: returned as is. It will be classed
        # `malformed_at_source` and counted separately, never as a dead link.
        return url
    scheme = "https"
    netloc = parts.netloc.lower()
    netloc = netloc.removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    query = "&".join(
        q for q in parts.query.split("&") if q and q.split("=")[0].lower() not in _TRACKING_PARAMS
    )
    return urlunsplit((scheme, netloc, path, query, ""))


DATASET_DOI_PREFIXES = {
    "10.5281",   # Zenodo
    "10.5061",   # Dryad
    "10.6084",   # Figshare
    "10.17605",  # OSF
    "10.7910",   # Harvard Dataverse
    "10.1594",   # PANGAEA
    "10.17182",  # HEPData
    "10.3886",   # ICPSR
    "10.18150",  # UK Data Service
    "10.17632",  # Mendeley Data
    "10.5063",   # KNB / DataONE
    "10.15468",  # GBIF
    "10.25493",  # various institutional repositories
    "10.4121",   # 4TU.ResearchData
    "10.7937",   # TCIA
    "10.18112",  # various
}
"""DOI prefixes of data repository agencies.

**Deliberate deviation from PLAN.md §5.** The plan lists `dataset_doi` among the tracked
kinds. The first version labelled **every** DOI this way, including those of papers cited
in the bibliography. Measured on 2026-09-20: of 8,073 links extracted from 400 papers,
3,449 were classed `dataset_doi` whereas the vast majority are paper DOIs.

Probing them would measure the survival of the scientific literature — which does not
die, a paper DOI is maintained by its publisher — and inflict thousands of useless
requests on doi.org. It would also be a misleading figure: an excellent survival rate,
carried by a population that is not the project's.

Hence an additional kind, `citation_doi`, excluded from probing by default. The prefix
list is deliberately conservative: when in doubt, a DOI is a citation. A missed
repository is a loss; a paper counted as a dataset is a mistake."""


def doi_prefix(url: str) -> str | None:
    m = DOI.search(url)
    return m.group(0).split("/", 1)[0] if m else None


def kind_of(url: str) -> str:
    host = host_of(url)
    if host in {"doi.org", "dx.doi.org"} or DOI.search(url):
        if ZENODO_DOI.search(url) or DRYAD_DOI.search(url):
            return "data_repo"
        return "dataset_doi" if doi_prefix(url) in DATASET_DOI_PREFIXES else "citation_doi"
    if host in _CODE_HOSTS or SWH_ID.search(url):
        return "code_repo"
    if host in _DATA_HOSTS:
        return "data_repo"
    return "generic_url"


_VALID_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(\.(?!-)[a-z0-9-]{1,63})+$")


def _load_tlds() -> frozenset[str]:
    """Official list of top-level domains (IANA), versioned in the repository.

    It is bundled rather than downloaded: a measurement must be replayable in six months
    without depending on a third-party service that day.
    """
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "tlds.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(x.strip().lower() for x in lines if x.strip() and not x.startswith("#"))


VALID_TLDS = _load_tlds()
"""Used to separate two populations nothing else separates (§4, pitfall 3).

Measured on 2026-09-21: among domains that no longer resolve, `arcjournals.or`. This is
not a dead site — it is a `.org` truncated by PDF extraction. Counting it dead would add
to the mortality rate a link that never existed, and in the direction that suits the
project's thesis.

A TLD absent from the IANA list cannot designate any resource: the link is broken at the
source, not dead."""


def is_malformed(raw: str) -> bool:
    """Pitfall 3 (§4): broken from publication, so it could never have worked.

    Measures editorial control, not rot. Must never be mixed into the dead-link rate: they
    are two figures, both interesting, never added together.

    Deliberately syntactic and offline: no network request is involved here. A
    well-formed link pointing nowhere is `dead`, not `malformed`.
    """
    candidate = canonicalize(raw)
    parts = _safe_split(candidate)
    if parts is None:
        return True  # cannot be split by the standard library: broken, by definition
    host = parts.netloc.split(":")[0]
    if not host or not _VALID_HOSTNAME.match(host):
        return True
    if " " in candidate.strip():
        return True
    tld = host.rsplit(".", 1)[-1]
    if VALID_TLDS and tld not in VALID_TLDS:
        # `arcjournals.or`: a `.org` truncated at extraction, not a vanished site.
        return True
    if host == "doi.org":
        return not DOI.search(parts.path)
    if host == "github.com":
        # A GitHub link without owner/repo designates no resource.
        return not GITHUB_SLUG.search(candidate)
    return False


def dedupe(urls: list[str]) -> list[str]:
    """Stable deduplication: first occurrence kept, text order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        key = canonicalize(url)
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out
