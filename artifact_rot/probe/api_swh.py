"""Software Heritage : separer « a disparu » de « n'a jamais existe » (§4, piege 3).

Software Heritage archive en continu les forges publiques. Si SWH connait une origine,
le depot a existe publiquement a une date connue. Cela ne dit rien de son etat
aujourd'hui — ce n'est donc pas une sonde d'etat, et la classe ci-dessous n'est
volontairement pas un `Prober`.

C'est l'enrichissement qui rend le chiffre principal defendable sur deux points :

* un depot GitHub en 404 dont SWH possede une archive a bien vecu puis est mort : c'est
  du rot au sens strict ;
* un depot GitHub en 404 inconnu de SWH peut n'avoir jamais existe (faute de frappe
  dans l'article, depot toujours reste prive), ce qui releve du controle editorial.

Sans cette distinction, les deux populations sont melangees dans le meme taux, ce que
le §4 interdit explicitement.
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
    """True : SWH connait l'origine. False : inconnue. None : indetermine (crawler en echec)."""
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
