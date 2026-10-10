"""Probers for data repositories with an API: Zenodo, Figshare, OSF, Dryad.

These hosts are the only cases where `restricted` is frequent and legitimate: an
embargoed or access-controlled deposit exists, it resolves, it simply cannot be
downloaded. Counting it dead would be wrong; counting it alive without saying so would be
misleading. Hence the fourth category of §4.
"""

from __future__ import annotations

import httpx

from ..config import Settings
from ..extract.normalize import FIGSHARE_ID, OSF_ID, ZENODO_DOI, ZENODO_ID
from ..models import Link, Status
from .base import Prober, ProbeResult, truncate_body


class ZenodoProber(Prober):
    name = "zenodo"
    method = "api"

    def handles(self, link: Link) -> bool:
        return bool(ZENODO_ID.search(link.normalized) or ZENODO_DOI.search(link.normalized))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = ZENODO_ID.search(link.normalized) or ZENODO_DOI.search(link.normalized)
        if m is None:
            return self._unknown("zenodo_id_unparsed", url=link.normalized)
        record_id = m.group(1)
        url = f"https://zenodo.org/api/records/{record_id}"
        r = client.get(url)
        ev = {"api_url": url, "http_status": r.status_code, "record_id": record_id}

        if r.status_code == 200:
            body = r.json()
            access = (body.get("metadata") or {}).get("access_right") or body.get("access", {})
            ev["access"] = access
            if isinstance(access, str) and access in {"restricted", "closed", "embargoed"}:
                return ProbeResult(Status.RESTRICTED, "api", f"zenodo_access_{access}", ev)
            if isinstance(access, dict) and access.get("files") in {"restricted", "embargoed"}:
                return ProbeResult(Status.RESTRICTED, "api", "zenodo_access_files_restricted", ev)
            return ProbeResult(Status.ALIVE, "api", "zenodo_api_200", ev)

        if r.status_code in (404, 410):
            return ProbeResult(Status.DEAD, "api", f"zenodo_api_{r.status_code}", ev)
        if r.status_code in (401, 403):
            # Zenodo returns 403 on a restricted record, which does exist.
            return ProbeResult(Status.RESTRICTED, "api", "zenodo_api_forbidden", ev)
        if r.status_code == 429:
            return ProbeResult(Status.UNKNOWN, "api", "zenodo_rate_limited", ev)
        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"zenodo_api_{r.status_code}", ev)


class OSFProber(Prober):
    name = "osf"
    method = "api"

    def handles(self, link: Link) -> bool:
        return link.host == "osf.io" and bool(OSF_ID.search(link.normalized))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = OSF_ID.search(link.normalized)
        if m is None:
            return self._unknown("osf_id_unparsed", url=link.normalized)
        guid = m.group(1)
        url = f"https://api.osf.io/v2/guids/{guid}/"
        r = client.get(url)
        ev = {"api_url": url, "http_status": r.status_code, "guid": guid}

        if r.status_code == 200:
            body = r.json().get("data", {})
            attrs = body.get("attributes", {})
            ev |= {"type": body.get("type"), "public": attrs.get("public")}
            if attrs.get("public") is False:
                return ProbeResult(Status.RESTRICTED, "api", "osf_private_node", ev)
            return ProbeResult(Status.ALIVE, "api", "osf_api_200", ev)

        if r.status_code in (401, 403):
            # OSF genuinely distinguishes private (403) from deleted (404, 410).
            return ProbeResult(Status.RESTRICTED, "api", "osf_api_forbidden", ev)
        if r.status_code in (404, 410):
            return ProbeResult(Status.DEAD, "api", f"osf_api_{r.status_code}", ev)
        if r.status_code == 429:
            return ProbeResult(Status.UNKNOWN, "api", "osf_rate_limited", ev)
        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"osf_api_{r.status_code}", ev)


class FigshareProber(Prober):
    name = "figshare"
    method = "api"

    def handles(self, link: Link) -> bool:
        m = FIGSHARE_ID.search(link.normalized)
        return bool(m and m.group(1))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = FIGSHARE_ID.search(link.normalized)
        if m is None or not m.group(1):
            return self._unknown("figshare_id_unparsed", url=link.normalized)
        article_id = m.group(1)
        url = f"https://api.figshare.com/v2/articles/{article_id}"
        r = client.get(url)
        ev = {"api_url": url, "http_status": r.status_code, "article_id": article_id}

        if r.status_code == 200:
            body = r.json()
            ev |= {"is_embargoed": body.get("is_embargoed"), "is_public": body.get("is_public")}
            if body.get("is_embargoed") or body.get("is_public") is False:
                return ProbeResult(Status.RESTRICTED, "api", "figshare_embargoed", ev)
            return ProbeResult(Status.ALIVE, "api", "figshare_api_200", ev)
        if r.status_code in (404, 410):
            return ProbeResult(Status.DEAD, "api", f"figshare_api_{r.status_code}", ev)
        if r.status_code in (401, 403):
            return ProbeResult(Status.RESTRICTED, "api", "figshare_api_forbidden", ev)
        if r.status_code == 429:
            return ProbeResult(Status.UNKNOWN, "api", "figshare_rate_limited", ev)
        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"figshare_api_{r.status_code}", ev)
