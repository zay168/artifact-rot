"""DOI prober: resolves the identifier through the Handle API, not through the page.

Two different things the literature regularly conflates:

* **is the DOI registered**, and does it point somewhere? The Handle API answers,
  unambiguously and without depending on the target server's state;
* **does the landing page respond**? That is another question, whose answer can be no
  while the DOI resolves perfectly.

The status returned by this prober answers the first question — it is the plan's §1
definition of "identifier resolution". The second is measured anyway and stored in the
evidence under `landing_*`, so that the E6 report can publish both figures side by side
instead of blending them into one. A registered DOI pointing to a dead server is a result
in itself, and it would be dishonest to bury it.
"""

from __future__ import annotations

import httpx

from ..config import Settings
from ..extract.normalize import DOI
from ..models import Link, Status
from .base import Prober, ProbeResult, truncate_body

HANDLE_API = "https://doi.org/api/handles/{doi}"

_HANDLE_RESPONSE_CODES = {
    1: ("doi_handle_registered", Status.ALIVE),
    2: ("doi_handle_server_error", Status.UNKNOWN),
    100: ("doi_handle_not_found", Status.DEAD),
    200: ("doi_handle_values_not_found", Status.DEAD),
}


class DOIProber(Prober):
    name = "doi"
    method = "api"

    def handles(self, link: Link) -> bool:
        return link.host == "doi.org" or bool(DOI.search(link.normalized))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = DOI.search(link.normalized)
        if m is None:
            return self._unknown("doi_unparsed", url=link.normalized)
        doi = m.group(0)
        url = HANDLE_API.format(doi=doi)
        r = client.get(url)
        ev: dict = {"api_url": url, "http_status": r.status_code, "doi": doi}

        if r.status_code not in (200, 404):
            ev["body"] = truncate_body(r, settings)
            return ProbeResult(Status.UNKNOWN, "api", f"doi_handle_http_{r.status_code}", ev)

        try:
            body = r.json()
        except ValueError:
            ev["body"] = truncate_body(r, settings)
            return ProbeResult(Status.UNKNOWN, "api", "doi_handle_unparseable", ev)

        code = body.get("responseCode")
        ev["response_code"] = code
        reason, status = _HANDLE_RESPONSE_CODES.get(code, ("doi_handle_unexpected", Status.UNKNOWN))

        target = _target_url(body)
        if target:
            ev["target_url"] = target
            _annotate_landing(client, target, ev, settings)

        return ProbeResult(status, "api", reason, ev)


def _target_url(body: dict) -> str | None:
    for value in body.get("values", []):
        if value.get("type") == "URL":
            data = value.get("data", {})
            if isinstance(data, dict):
                return data.get("value")
    return None


def _annotate_landing(
    client: httpx.Client, target: str, ev: dict, settings: Settings
) -> None:
    """Measure the landing page's state — as evidence, never as status.

    No exception propagates: failure of this secondary measurement must not degrade the
    main probe, which already has its answer.
    """
    try:
        r = client.head(target)
        if r.status_code in (405, 501):
            r = client.get(target)
    except httpx.HTTPError as exc:
        ev["landing_error"] = type(exc).__name__
        return
    ev["landing_status"] = r.status_code
    ev["landing_final_url"] = str(r.url)
