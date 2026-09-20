"""Socle des sondes. Piege 1 (§4) : le code HTTP ment.

Regle structurante : pour tout hebergeur qui expose une API, on interroge l'API et
jamais le HTML. Une API repond sans ambiguite sur l'existence ; une page HTML peut
rendre un 200 sur « depot introuvable », ou un 403 Cloudflare sur une ressource
parfaitement vivante.

Chaque sonde renvoie un `ProbeResult` portant, en plus du statut, la raison nommee de
la classification. Sans cette raison, un desaccord sur un chiffre publie est
inarbitrable.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from ..config import Settings
from ..models import Link, Status


@dataclass(frozen=True)
class ProbeResult:
    status: Status
    method: Literal["api", "http"]
    reason: str
    """Identifiant court et stable de la regle appliquee, ex. `github_api_404`.
    Teste directement par le jeu de controle E2."""
    evidence: dict[str, Any] = field(default_factory=dict)


class Prober(abc.ABC):
    """Une sonde specialisee pour une famille d'hebergeurs."""

    name: str
    method: Literal["api", "http"] = "api"

    @abc.abstractmethod
    def handles(self, link: Link) -> bool:
        """Vrai si cette sonde sait repondre de facon non ambigue sur ce lien."""

    @abc.abstractmethod
    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        """Sonde le lien. Ne leve jamais : une erreur reseau devient UNKNOWN."""

    def _unknown(self, reason: str, **evidence: Any) -> ProbeResult:
        return ProbeResult(Status.UNKNOWN, self.method, reason, evidence)


def build_client(settings: Settings) -> httpx.Client:
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "application/json;q=0.9,*/*;q=0.8",
        **settings.extra_headers,
    }
    return httpx.Client(
        headers=headers,
        timeout=settings.timeout_s,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=settings.max_concurrency),
    )


def classify_transport_error(exc: Exception) -> tuple[str, dict[str, Any]]:
    """Traduit une exception reseau en raison nommee. Tout cela finit en UNKNOWN :
    un echec du crawler n'est pas un echec du lien (§4 piege 2)."""
    if isinstance(exc, httpx.TimeoutException):
        return "transport_timeout", {"error": type(exc).__name__}
    if isinstance(exc, httpx.ConnectError):
        return "transport_connect", {"error": type(exc).__name__, "detail": str(exc)[:200]}
    if isinstance(exc, httpx.TooManyRedirects):
        return "transport_redirect_loop", {"error": type(exc).__name__}
    if isinstance(exc, httpx.HTTPError):
        return "transport_http_error", {"error": type(exc).__name__, "detail": str(exc)[:200]}
    return "transport_unexpected", {"error": type(exc).__name__, "detail": str(exc)[:200]}


class ProberRegistry:
    """Selection de la sonde : premiere qui declare savoir repondre.

    L'ordre compte. Les sondes d'API passent avant la sonde HTTP generique, qui est un
    filet de securite et non un choix par defaut.
    """

    def __init__(self, probers: list[Prober]) -> None:
        self._probers = probers

    def select(self, link: Link) -> Prober:
        for prober in self._probers:
            if prober.handles(link):
                return prober
        raise LookupError(f"aucune sonde pour {link.normalized!r} (host={link.host!r})")

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        prober = self.select(link)
        try:
            return prober.check(client, link, settings)
        except Exception as exc:  # noqa: BLE001 — une sonde ne fait jamais tomber un run
            reason, evidence = classify_transport_error(exc)
            return ProbeResult(Status.UNKNOWN, prober.method, reason, evidence)


def truncate_body(response: httpx.Response, settings: Settings) -> str:
    try:
        return response.text[: settings.body_evidence_bytes]
    except Exception:  # noqa: BLE001 — la preuve est optionnelle, la sonde ne l'est pas
        return ""
