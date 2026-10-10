"""Software Heritage: separating "disappeared" from "never existed" (§4, pitfall 3).

Software Heritage continuously archives public forges. If SWH knows an origin, the
repository existed publicly at a known date. That says nothing about its state today —
so it is not a state prober, and the class below is deliberately not a `Prober`.

It is the enrichment that makes the main figure defensible on two points:

* a GitHub repository returning 404 that SWH has archived did live and then die: that is
  rot in the strict sense;
* a GitHub repository returning 404 unknown to SWH may never have existed (a typo in the
  paper, a repository that always stayed private), which falls under editorial control.

Without this distinction, the two populations are mixed into the same rate, which §4
explicitly forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

ORIGIN_API = "https://archive.softwareheritage.org/api/1/origin/{origin}/get/"
VISITS_API = "https://archive.softwareheritage.org/api/1/origin/{origin}/visits/"


@dataclass(frozen=True)
class ArchiveEvidence:
    known: bool | None
    """True: SWH knows the origin. False: unknown. None: undetermined (crawler failure)."""
    first_visit: str | None = None
    last_visit: str | None = None
    reason: str = ""


def ever_existed(client: httpx.Client, origin_url: str) -> ArchiveEvidence:
    origin = quote(origin_url, safe="")
    try:
        r = client.get(ORIGIN_API.format(origin=origin))
    except httpx.HTTPError as exc:
        return ArchiveEvidence(None, reason=f"swh_transport_{type(exc).__name__}")

    if r.status_code == 404:
        return ArchiveEvidence(False, reason="swh_origin_unknown")
    if r.status_code == 429:
        return ArchiveEvidence(None, reason="swh_rate_limited")
    if r.status_code != 200:
        return ArchiveEvidence(None, reason=f"swh_http_{r.status_code}")

    try:
        v = client.get(VISITS_API.format(origin=origin), params={"per_page": 1})
        visits = v.json() if v.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        visits = []

    last = visits[0].get("date") if visits else None
    return ArchiveEvidence(True, first_visit=None, last_visit=last, reason="swh_origin_known")
