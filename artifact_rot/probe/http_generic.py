"""Sonde HTTP generique — le filet de securite, pas le choix par defaut.

Elle ne sert que pour les hotes sans API : pages personnelles, depots institutionnels,
serveurs de laboratoire. C'est la que le piege 1 du §4 mord le plus fort, parce qu'un
`200` ne veut rien dire.

**Detection de soft-404 par sonde de controle**, technique classique et entierement
deterministe, sans aucune annotation humaine : on demande au meme hote une URL
volontairement inexistante, et on compare sa reponse a celle de l'URL cible. Si le
serveur repond la meme chose aux deux, son `200` ne porte aucune information et la
cible est declaree morte.

Le `403` est traite avec prudence : un pare-feu applicatif qui bloque un robot est un
echec du crawler (`unknown`), pas un acces controle (`restricted`) ni une disparition.
Les confondre serait exactement la falsification que le §4 interdit.
"""

from __future__ import annotations

import re
import urllib.robotparser
import uuid
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import Settings
from ..models import Link, Status
from .base import Prober, ProbeResult, truncate_body
from .dns import resolve as resolve_host

SOFT404_SIMILARITY = 0.90
"""Au-dela, la reponse de la cible est jugee indiscernable de celle d'une URL
inexistante. Seuil fixe avant le premier run et valide par le jeu de controle E2."""

_WAF_MARKERS = re.compile(
    r"(cloudflare|just a moment|checking your browser|attention required|akamai|"
    r"incapsula|perimeterx|access denied by|ddos[- ]guard|captcha)",
    re.IGNORECASE,
)

_SOFT404_MARKERS = re.compile(
    r"(page not found|not found|404 error|doesn'?t exist|no longer available|"
    r"page introuvable|cette page n'existe|repository not found|file not found)",
    re.IGNORECASE,
)


class GenericHTTPProber(Prober):
    name = "http_generic"
    method = "http"

    def handles(self, link: Link) -> bool:
        return link.normalized.startswith("http")

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        url = link.normalized
        ev: dict = {"url": url}

        # Resolution du nom avant toute requete. Un nom qui n'existe pas rend une
        # reponse — celle du DNS — et non un echec du crawler. Voir `probe/dns.py`
        # pour la decision et ses garde-fous.
        verdict = resolve_host(link.host)
        ev["dns"] = verdict
        if verdict == "nxdomain":
            return ProbeResult(Status.DEAD, "http", "dns_nxdomain", ev)
        if verdict == "transient":
            return ProbeResult(Status.UNKNOWN, "http", "dns_transient", ev)

        if settings.respect_robots:
            allowed = _robots_allows(client, url, settings)
            ev["robots_allowed"] = allowed
            if allowed is False:
                # Interdit de sonder : on ne sait rien, et on ne passe pas outre (§4 piege 5).
                return ProbeResult(Status.UNKNOWN, "http", "robots_disallowed", ev)

        r = client.get(url)
        ev |= {"http_status": r.status_code, "final_url": str(r.url)}

        if r.status_code in (404, 410):
            return ProbeResult(Status.DEAD, "http", f"http_{r.status_code}", ev)

        if r.status_code == 429 or 500 <= r.status_code < 600:
            ev["retry_after"] = r.headers.get("retry-after")
            return ProbeResult(Status.UNKNOWN, "http", f"http_{r.status_code}", ev)

        body = truncate_body(r, settings)

        if r.status_code in (401, 403):
            ev["body"] = body
            if _WAF_MARKERS.search(body) or r.status_code == 403 and not _looks_like_auth(r, body):
                # Blocage anti-robot probable : echec du crawler, statut indetermine.
                return ProbeResult(Status.UNKNOWN, "http", "http_blocked_by_waf", ev)
            return ProbeResult(Status.RESTRICTED, "http", f"http_{r.status_code}_auth", ev)

        if r.status_code != 200:
            ev["body"] = body
            return ProbeResult(Status.UNKNOWN, "http", f"http_{r.status_code}", ev)

        # 200 — c'est ici que le code ment. Trois tests, du moins couteux au plus couteux.
        if _redirected_to_root(url, str(r.url)):
            ev["soft404_signal"] = "redirect_to_root"
            return ProbeResult(Status.DEAD, "http", "soft404_redirect_to_root", ev)

        if _SOFT404_MARKERS.search(_title_of(body) or ""):
            ev["soft404_signal"] = "title_marker"
            ev["title"] = _title_of(body)
            return ProbeResult(Status.DEAD, "http", "soft404_title_marker", ev)

        control = _control_probe(client, url, settings)
        ev["control"] = {k: v for k, v in control.items() if k != "body"}
        if control.get("status") is None:
            ev["body"] = body
            return ProbeResult(Status.UNKNOWN, "http", "control_probe_failed", ev)

        if control["status"] in (404, 410):
            # Le serveur sait dire non : son 200 est credible.
            return ProbeResult(Status.ALIVE, "http", "http_200_control_404", ev)

        similarity = _similarity(body, control.get("body", ""))
        ev["control_similarity"] = round(similarity, 4)
        if similarity >= SOFT404_SIMILARITY:
            return ProbeResult(Status.DEAD, "http", "soft404_control_similar", ev)

        return ProbeResult(Status.ALIVE, "http", "http_200_control_differs", ev)


def _looks_like_auth(response: httpx.Response, body: str) -> bool:
    if "www-authenticate" in response.headers:
        return True
    return bool(re.search(r"(sign in|log in|connexion|authentication required)", body, re.IGNORECASE))


def _redirected_to_root(original: str, final: str) -> bool:
    """Une redirection d'une ressource precise vers la racine du site est un soft-404
    classique : le serveur ne sait plus ou est la ressource et renvoie l'accueil."""
    o, f = urlsplit(original), urlsplit(final)
    return bool(o.path.strip("/")) and f.path.strip("/") == "" and o.netloc == f.netloc


def _title_of(body: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def _control_probe(client: httpx.Client, url: str, settings: Settings) -> dict:
    """Demande une URL garantie inexistante sur le meme hote, dans le meme repertoire.

    Le chemin porte un UUID et le nom du projet : si quelqu'un lit ses journaux, il voit
    immediatement qui frappe et pourquoi."""
    parts = urlsplit(url)
    parent = parts.path.rsplit("/", 1)[0]
    token = uuid.uuid4().hex
    control_url = urlunsplit(
        (parts.scheme, parts.netloc, f"{parent}/artifact-rot-control-{token}", "", "")
    )
    try:
        r = client.get(control_url)
    except httpx.HTTPError as exc:
        return {"url": control_url, "status": None, "error": type(exc).__name__}
    return {
        "url": control_url,
        "status": r.status_code,
        "body": r.text[: settings.body_evidence_bytes],
    }


def _similarity(a: str, b: str) -> float:
    """Similarite structurelle entre deux reponses, apres retrait du bruit variable.

    On enleve chiffres, UUID et espaces : deux pages d'erreur identiques ne different
    souvent que par un horodatage ou un identifiant de requete."""
    norm = lambda s: re.sub(r"[\d\s]+", "", re.sub(r"[0-9a-f]{8,}", "", s.lower()))
    na, nb = norm(a), norm(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _robots_allows(client: httpx.Client, url: str, settings: Settings) -> bool | None:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _ROBOTS_CACHE:
        parser = urllib.robotparser.RobotFileParser()
        try:
            r = client.get(f"{origin}/robots.txt")
            if r.status_code == 200:
                parser.parse(r.text.splitlines())
            else:
                parser.parse([])  # pas de robots.txt = tout autorise
        except httpx.HTTPError:
            _ROBOTS_CACHE[origin] = None
            return None
        _ROBOTS_CACHE[origin] = parser
    parser = _ROBOTS_CACHE[origin]
    if parser is None:
        return None
    return parser.can_fetch(settings.user_agent, url)
