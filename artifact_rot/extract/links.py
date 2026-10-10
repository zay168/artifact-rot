"""Extracting artifact links from full text.

Extraction runs on the **repaired text** (see `normalize.repair_spaced_hosts`), never on
the raw text: 85% of the papers in metacheck's validation corpus contain URLs split by PDF
extraction, and a regex applied before repair silently loses them.

This module does not judge whether a link is alive. It produces `Link` objects, with their
provenance and canonical form. Classification is `probe/`'s job.
"""

from __future__ import annotations

import re

from ..models import Link, LinkKind
from .normalize import (
    DOI,
    canonicalize,
    host_of,
    is_malformed,
    is_on_request,
    kind_of,
    repair_spaced_hosts,
)
from .statements import classify_position, find_availability_spans, find_references_span

URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
BARE_DOI = re.compile(r"\bdoi\s*:\s*(10\.\d{4,9}/[-._;()/:a-z0-9]+[a-z0-9])", re.IGNORECASE)

ARTIFACT_HOSTS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    "softwareheritage.org",
    "archive.softwareheritage.org",
    "zenodo.org",
    "figshare.com",
    "osf.io",
    "datadryad.org",
    "dataverse.harvard.edu",
    "dataverse.org",
    "openneuro.org",
    "dandiarchive.org",
    "huggingface.co",
    "kaggle.com",
    "mendeley.com",
    "data.mendeley.com",
    "pangaea.de",
    "zenodo.figshare.com",
}
"""Recognised artifact hosts. A link outside this list is not discarded: it becomes
`generic_url` and is still probed. The list is used to measure recall (E3) on the
population that matters, not to filter."""

BOILERPLATE = re.compile(
    r"""(?ix)
    creativecommons\.org
  | crossmark\.crossref\.org
  | ^https?://(www\.)?(doi|dx\.doi)\.org/?$
  | orcid\.org
  | ror\.org
  | scholar\.google
  | \.(?:png|jpe?g|gif|svg|css|js|ico)(?:$|\?)
  | ^https?://(www\.)?(twitter|x|facebook|linkedin|instagram)\.com
  | ^https?://(www\.)?researchgate\.net
  | issn\.
  | lattes\.cnpq\.br
    """
)
"""Editorial production links, present in almost every PDF: licence, Crossmark, author
profiles, stylesheets. Counting them as artifacts would inflate the denominator with
links whose survival interests nobody."""


def is_boilerplate(url: str) -> bool:
    return bool(BOILERPLATE.search(url))


def is_artifact_link(url: str) -> bool:
    """Does the link designate a research artifact?

    Used for E3 recall: measuring recall on *all* of a paper's URLs would mix the links we
    care about with the hundreds of DOIs in its bibliography, and produce a flattering,
    meaningless figure.
    """
    if is_boilerplate(url):
        return False
    host = host_of(url)
    if host in ARTIFACT_HOSTS:
        return True
    return bool(DOI.search(url)) and host in {"doi.org", "dx.doi.org"}


TRAILING_PUNCT = ".,;:!?”»'\"" + ")]}"


def iter_raw_links(text: str):
    """Each URL or DOI in the text, with its position — the position gives provenance.

    End-of-sentence punctuation is stripped here and nowhere else: `Link.raw` must carry
    the URL as the author wrote it, and the full stop ending the sentence is not part of
    the URL. Leaving it would force every consumer to deal with it, and a single omission
    would produce a dead link that never existed.
    """
    repaired = repair_spaced_hosts(text)
    for m in URL_IN_TEXT.finditer(repaired):
        url = m.group(0).rstrip(TRAILING_PUNCT)
        if url:
            yield m.start(), url
    for m in BARE_DOI.finditer(repaired):
        yield m.start(), f"https://doi.org/{m.group(1).rstrip(TRAILING_PUNCT)}"


def extract_links(
    text: str,
    *,
    paper_id: str,
    paper_year: int,
    discipline: str,
    publisher: str,
    paper_doi: str | None = None,
    structured_urls: list[str] | None = None,
    chrome_host: str | None = None,
) -> list[Link]:
    """Produce a paper's `Link` objects, deduplicated and attributed to their provenance.

    `structured_urls` (PDF annotations, `<a href>`, `<ext-link>`) is **merged** with text
    extraction, not opposed to it: the 2026-09-20 measurement shows that annotations
    contain URLs the text loses to hyphenation, and the text contains URLs the publisher
    did not tag. Taking the union is the only option that throws nothing away.

    The provenance of a link found only in annotations is `body`: an annotation does not
    say which section it is in.
    """
    repaired = repair_spaced_hosts(text)
    availability = find_availability_spans(repaired)
    references = find_references_span(repaired)

    seen: set[str] = set()
    links: list[Link] = []

    def add(raw: str, source: str) -> None:
        normalized = canonicalize(raw)
        if normalized in seen or is_boilerplate(normalized):
            return
        # Host-site chrome. An HTML page mixes the paper with the menu of the site hosting
        # it: a Zenodo record links to `about.zenodo.org`, a journal portal to its own
        # sections. 216 `about.zenodo.org` links in a single batch on 2026-09-21. These
        # are the site's links, not the paper's.
        #
        # Only applies to HTML documents: a PDF's annotations belong to the document, and
        # a PDF deposited on Zenodo may legitimately cite Zenodo.
        if chrome_host and _same_site(host_of(normalized), chrome_host):
            return
        seen.add(normalized)
        links.append(
            Link(
                paper_id=paper_id,
                paper_doi=paper_doi,
                paper_year=paper_year,
                discipline=discipline,
                publisher=publisher,
                raw=raw,
                normalized=normalized,
                kind=_kind(normalized),
                host=host_of(normalized),
                source=source,  # type: ignore[arg-type]
                malformed_at_source=is_malformed(raw),
            )
        )

    for pos, raw in iter_raw_links(text):
        add(raw, classify_position(pos, availability, references))

    for raw in structured_urls or []:
        # A PDF's annotations also contain `mailto:`, `tel:` and `file:///` — the
        # authors' addresses and local paths left in the document. They are not artifact
        # links, and touching them is out of the question.
        if raw.lower().startswith(("http://", "https://")):
            add(raw, "body")

    return links


def _kind(url: str) -> LinkKind:
    return kind_of(url)  # type: ignore[return-value]


def count_on_request(text: str) -> int:
    """Pitfall 4: "available on request" is not a link.

    Counted separately, never probed, and the report says it was not tested — we do not
    write to thousands of authors. The count covers availability statements only: the
    phrase also appears in unrelated contexts.
    """
    repaired = repair_spaced_hosts(text)
    return sum(
        1 for span in find_availability_spans(repaired) if is_on_request(span.slice(repaired))
    )


def _same_site(host: str, other: str) -> bool:
    """Do two hosts belong to the same site? Compares the last two labels.

    `about.zenodo.org` and `zenodo.org`: yes. `github.com` and `zenodo.org`: no.
    Deliberately coarse — a full public suffix list (`co.uk`, `jst.go.jp`) would require
    an external list, and the use case does not call for it: we discard noise, we do not
    decide a status.
    """
    a, b = host.lower().split("."), other.lower().split(".")
    return len(a) >= 2 and len(b) >= 2 and a[-2:] == b[-2:]
