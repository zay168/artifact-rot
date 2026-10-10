"""E3 — full-text retrieval. Open sources only.

Three measurements made on the sample on 2026-09-20, which drive the whole design:

1. **The dominant format is PDF** (54% of `best_oa_location` locations), far ahead of
   HTML (7%). An extractor that only reads HTML would measure one discipline, not four.
2. **Europe PMC only covers medicine**: 38% of medical papers available as JATS, 1 to 2%
   elsewhere. An excellent source, but not a sample-wide source.
3. **Preferring repositories over publisher sites raises the retrieval rate from 61% to
   72%.** Large publishers (Wiley, ScienceDirect, MDPI, OUP) answer 403 to a robot;
   institutional repositories, arXiv and PMC do not.

Hence the order of preference: repository first, publisher last. This is not a
workaround — we politely ask elsewhere for a copy the author deposited themselves. A 403
remains a 403: it is never forced.

**The residual attrition (~28%) is a limitation, not a detail.** It must be measured by
stratum: if it correlates with year, it biases the main explanatory variable.
`coverage_report` produces this figure, and E6 must publish it.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

from .config import Settings

CACHE_DIR = Path("data/fulltext")
OPENALEX = "https://api.openalex.org"

DocKind = Literal["pdf", "html", "jats", "none"]

MAX_LOCATION_ATTEMPTS = 4
"""Maximum number of locations tried for a paper.

Four attempts cover the normal case (repository PDF, publisher PDF, repository page,
publisher page). Beyond that, we pay for timeouts to learn what we already know."""


@dataclass
class Document:
    """A retrieved full text, with the links tagged by the source.

    `structured_urls` is the key to E3: these are the URLs placed by the publisher (`/URI`
    annotations in a PDF, `<a href>` in HTML, `<ext-link>` in JATS). They form a free
    ground truth against which to measure the recall of text extraction — the same
    principle the whole project rests on.
    """

    paper_id: str
    source_url: str
    source_type: str
    kind: DocKind
    text: str = ""
    structured_urls: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind != "none" and bool(self.text)


# --- Choosing the location ---------------------------------------------------------


def rank_locations(locations: list[dict]) -> list[tuple[str, str]]:
    """Order open locations. **Every PDF comes before every HTML page.**

    The first version ranked by source type only — repositories first — and so picked a
    repository's record page (for example `zenodo.org/records/…`) before the publisher's
    PDF. But **a record page is not the paper**: its text is the host site's, and its
    links are those of its menu and footer.

    The defect did not show at retrieval, which "worked". It showed in the recall
    computation: the supposedly missed repository links were in fact the Zenodo site's
    links to its own code (`github.com/zenodo/zenodo-rdm`). Without that measurement, the
    whole S1 run would have extracted links from record pages instead of papers.

    Hence the order: repository PDF, publisher PDF, repository page, publisher page.
    """
    buckets: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for loc in locations:
        if not loc.get("is_oa"):
            continue
        source = loc.get("source") or {}
        stype = source.get("type") or "unknown"
        repo_rank = 0 if stype == "repository" else 1
        for is_pdf, url in ((0, loc.get("pdf_url")), (1, loc.get("landing_page_url"))):
            if url:
                buckets.setdefault((is_pdf, repo_rank), []).append((url, stype))

    ordered = [item for key in sorted(buckets) for item in buckets[key]]

    # One attempt per host, and MAX_LOCATION_ATTEMPTS in total.
    #
    # Measured on 2026-09-20: without this limit, harvesting fell to ~2 papers per
    # minute, because a paper sometimes has ten locations, several at the same publisher
    # — which answers 403 or times out every time. We were paying the same twenty-second
    # timeout five times in a row to learn the same thing.
    #
    # Insisting with a host that has just refused is not only slow: it is exactly what
    # §4, pitfall 5, forbids.
    seen_hosts: set[str] = set()
    capped: list[tuple[str, str]] = []
    for url, stype in ordered:
        host = httpx.URL(url).host
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        capped.append((url, stype))
        if len(capped) >= MAX_LOCATION_ATTEMPTS:
            break
    return capped


def fetch_locations(client: httpx.Client, paper_id: str, settings: Settings) -> list[dict]:
    r = client.get(
        f"{OPENALEX}/works/{paper_id}",
        params={"select": "locations", "mailto": settings.contact},
    )
    r.raise_for_status()
    return r.json().get("locations") or []


# --- Retrieval ---------------------------------------------------------------------

_WAF = re.compile(r"(just a moment|checking your browser|cloudflare|captcha|access denied)", re.IGNORECASE)


def fetch_document(
    client: httpx.Client, paper_id: str, locations: list[dict], settings: Settings
) -> Document:
    """Try the locations in order and keep the first usable one."""
    last_error = "no open location"
    for url, stype in rank_locations(locations):
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            last_error = f"transport:{type(exc).__name__}"
            continue

        if r.status_code != 200:
            last_error = f"http_{r.status_code}"
            continue

        ctype = (r.headers.get("content-type") or "").split(";")[0].lower()
        try:
            if "pdf" in ctype:
                text, urls = read_pdf(r.content)
                return Document(paper_id, url, stype, "pdf", text, urls)
            if "xml" in ctype:
                text, urls = read_jats(r.text)
                return Document(paper_id, url, stype, "jats", text, urls)
            if "html" in ctype:
                if _WAF.search(r.text[:4000]):
                    last_error = "waf"
                    continue
                text, urls = read_html(r.text)
                return Document(paper_id, url, stype, "html", text, urls)
        except Exception as exc:  # noqa: BLE001 — an unreadable document does not stop a run
            last_error = f"parse:{type(exc).__name__}"
            continue
        last_error = f"content_type:{ctype or 'empty'}"

    return Document(paper_id, "", "", "none", error=last_error)


# --- Reading by format ---------------------------------------------------------------


def read_pdf(payload: bytes) -> tuple[str, list[str]]:
    """Rendered text + link annotations.

    `/URI` annotations are placed by the publisher when the PDF is produced. Measured on
    2026-09-20: 52% of PDFs carry them, and they contain more URLs than the raw text (276
    against 188 on a sample of 29 PDFs) — the gap is exactly what line hyphenation makes a
    purely textual extraction lose.
    """
    from pypdf import PdfReader  # late import: pypdf is slow to load

    reader = PdfReader(io.BytesIO(payload))
    urls: list[str] = []
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001,S110 — an unreadable page does not invalidate the document
            pass
        for annot in page.get("/Annots") or []:
            try:
                action = annot.get_object().get("/A") or {}
                uri = action.get("/URI")
                if uri:
                    urls.append(str(uri))
            except Exception:  # noqa: BLE001,S110 — an unreadable annotation is ignored
                pass
    return sanitize("\n".join(chunks)), [sanitize(u) for u in _dedupe_preserving(urls)]


_HREF = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)


def read_html(payload: str) -> tuple[str, list[str]]:
    urls = [sanitize(u) for u in _HREF.findall(payload) if u.startswith("http")]
    text = _TAG.sub(" ", payload)
    return _unescape(text), _dedupe_preserving(urls)


_EXT_LINK = re.compile(
    r"""<ext-link\b[^>]*xlink:href\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)


def read_jats(payload: str) -> tuple[str, list[str]]:
    """JATS: `<ext-link>` is the most explicit editorial markup there is."""
    urls = [
        sanitize(u) for u in _EXT_LINK.findall(payload) if u.startswith(("http", "doi:", "10."))
    ]
    text = _TAG.sub(" ", payload)
    return _unescape(text), _dedupe_preserving(urls)


def sanitize(text: str) -> str:
    """Make a text writable as UTF-8, whatever it contains.

    Measured on 2026-09-20: PDF extraction sometimes produces **lone surrogates** —
    isolated UTF-16 code points, which Python accepts in memory but no UTF-8 encoder
    accepts. Harvesting died on one after 200 papers, on
    `UnicodeEncodeError: surrogates not allowed`.

    This is not an exotic case: PDF is a format in which fonts declare their own
    character tables, and an inconsistent table produces exactly this. Over 40,000
    papers, this defect would have interrupted the run at an unpredictable moment — and
    after hours of work already done.

    Same principle as for hostile URLs: nothing that comes out of a PDF should be able to
    bring the pipeline down.
    """
    return text.encode("utf-8", "replace").decode("utf-8")


_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " "}


def _unescape(text: str) -> str:
    text = sanitize(text)
    for k, v in _ENTITIES.items():
        text = text.replace(k, v)
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _dedupe_preserving(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# --- Cache ---------------------------------------------------------------------------


def cache_path(paper_id: str) -> Path:
    # Two levels: 40,000 files in a single directory is unmanageable on Windows.
    return CACHE_DIR / paper_id[1:4] / f"{paper_id}.json"


def save(doc: Document) -> None:
    """**Atomic** write: temporary file, then rename.

    On 2026-09-20, a run died mid-write and left a truncated cache file. The next run
    resumed, read it back, and died on it in turn — so one interrupted run poisoned all
    the following ones.

    A rename is atomic on usual file systems: the final file is either absent or
    complete, never half-written. It is the same requirement as `synchronous=FULL` on the
    SQLite queue (§E4), for the same reason: the project lasts two weeks and nothing
    guarantees it will not be interrupted.
    """
    path = cache_path(doc.paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "paper_id": doc.paper_id,
            "source_url": doc.source_url,
            "source_type": doc.source_type,
            "kind": doc.kind,
            "text": doc.text,
            "structured_urls": doc.structured_urls,
            "error": doc.error,
        },
        ensure_ascii=False,
    )
    tmp = path.with_suffix(".json.part")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def load(paper_id: str) -> Document | None:
    """Read a cache entry. An unreadable entry counts as **absent**, never as an error.

    A cache is an optimisation, not a source of truth: if it is corrupt, we download
    again. Raising would stop a two-week run because of a file rebuildable in one request.
    """
    path = cache_path(paper_id)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return Document(
            paper_id=d["paper_id"],
            source_url=d["source_url"],
            source_type=d["source_type"],
            kind=d["kind"],
            text=d["text"],
            structured_urls=d["structured_urls"],
            error=d["error"],
        )
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError, OSError):
        return None
