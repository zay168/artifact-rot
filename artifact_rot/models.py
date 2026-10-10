"""Data contracts. Defined in PLAN.md §5 and frozen here.

Any change to one of these models invalidates earlier runs: a run is immutable (§5), so
a schema change requires a new run directory, never a rewrite.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    """The four states of pitfall 2 (§4). Never two, never three.

    ALIVE      : the resource's existence is positively confirmed.
    DEAD       : its non-existence is positively confirmed (API 404, 410, unregistered DOI).
    RESTRICTED : the resource exists but access is controlled (authenticable 401/403,
                 confirmed private repository, embargo). A legitimate case, frequent in
                 medicine.
    UNKNOWN    : the crawler failed (timeout, 429, 5xx, DNS, TLS, forbidden by robots.txt).
                 NEVER enters the denominator of a published rate.
    """

    ALIVE = "alive"
    DEAD = "dead"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


LinkKind = Literal[
    "code_repo",
    "data_repo",
    "dataset_doi",
    "citation_doi",  # DOI of a cited paper: a reference, not an artifact. See below.
    "generic_url",
    "on_request",  # pitfall 4: "available upon request" is not a link, never probed
]
"""**Deliberate deviation from PLAN.md §5**: the `citation_doi` type is added.

The plan lists `dataset_doi` among the tracked types. Without a further distinction,
this type absorbed **every** DOI encountered, including the thousands of DOIs of papers
cited in bibliographies — 3,449 links out of 8,073 extracted from 400 papers.

Counting them as artifacts would have produced an excellent and false survival rate,
carried by a population that is not the project's: a paper's DOI is maintained by its
publisher, it does not die. See `extract/normalize.DATASET_DOI_PREFIXES`."""

LinkSource = Literal["availability_statement", "body", "references"]
"""Where the link comes from within the paper.

`references` is kept separate because of metacheck failure mode no. 1 (issue #411): a
repository DOI cited only in the bibliography is invisible if that section is excluded,
but including it creates a misattribution risk (the repository may belong to a cited
paper, not the current one). We extract, flag, and let the report decide afterwards.
See docs/related-work.md §2.2.
"""


class Link(BaseModel):
    """An artifact link extracted from a paper. One row = one promise made by a paper.

    **Deliberate deviation from PLAN.md §5**, decided at E1 on 2026-09-20: the plan uses
    `paper_doi: str` as the key. Measurement on the sample shows that 6.8% of drawn
    papers have no DOI in OpenAlex, and that the gap is **strongly correlated with age**
    — 44% in computer science 2010 against 4% in 2025. Filtering on the presence of a DOI
    would therefore have introduced a selection bias on precisely the project's main
    explanatory variable. The key becomes the OpenAlex identifier, stable and universal
    across the sample; the DOI is kept when it exists, because it is what speaks to
    publishers and readers.
    """

    paper_id: str
    """OpenAlex identifier (`W…`). Primary key: present on 100% of the sample."""
    paper_doi: str | None = None
    paper_year: int
    discipline: str
    publisher: str
    raw: str
    """As written in the paper, before any normalisation. Evidence: without it, a dispute
    about extraction cannot be arbitrated."""
    normalized: str
    kind: LinkKind
    host: str
    source: LinkSource = "availability_statement"
    malformed_at_source: bool = False
    """Pitfall 3 (§4): broken from publication, never worked. A different category from a
    dead link. Measures editorial control, not rot."""

    @property
    def link_id(self) -> str:
        """Deterministic identifier, stable across runs."""
        payload = f"{self.paper_id}\x1f{self.normalized}\x1f{self.kind}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Probe(BaseModel):
    """A probe, i.e. a dated observation of a link's state."""

    link_id: str
    probed_at: datetime
    method: Literal["api", "http"]
    status: Status
    evidence: dict[str, Any] = Field(default_factory=dict)
    """HTTP code, truncated body, API response, classification reason. §5: all evidence
    is kept, otherwise a dispute cannot be arbitrated."""
    attempt: int = Field(ge=1, le=3)


class LinkOutcome(BaseModel):
    """Final status of a link, a deterministic function of its probes. See `resolve`."""

    link_id: str
    status: Status
    rule: str
    """Name of the rule applied. Makes the decision auditable line by line."""
    probes: list[Probe]
    first_probe_at: datetime
    last_probe_at: datetime
    right_censored: bool
    """§6: a link still alive today is a right-censored observation, not a definitive
    success. The field exists from the start, not patched in later."""
