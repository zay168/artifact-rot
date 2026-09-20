"""Sonde DOI : resolution de l'identifiant via l'API Handle, pas via la page.

Deux choses differentes que la litterature confond regulierement :

* le **DOI est-il enregistre** et pointe-t-il quelque part ? C'est l'API Handle qui
  repond, sans ambiguite et sans dependre de l'etat du serveur cible ;
* la **page de destination repond-elle** ? C'est une autre question, dont la reponse
  peut etre non alors que le DOI resout parfaitement.

Le statut renvoye par cette sonde porte la premiere question — c'est la definition de
« resolution d'identifiant » du §1 du plan. La seconde est mesuree quand meme et
rangee dans la preuve sous `landing_*`, pour que le rapport E6 puisse publier les deux
chiffres cote a cote au lieu d'en melanger un seul. Un DOI enregistre pointant vers un
serveur mort est un resultat en soi, et il serait malhonnete de le noyer.
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
    """Mesure l'etat de la page de destination — en preuve, jamais en statut.

    Aucune exception ne remonte : l'echec de cette mesure secondaire ne doit pas
    degrader la sonde principale, qui a deja sa reponse.
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
