"""Prober foundation. Pitfall 1 (§4): the HTTP code lies.

Structuring rule: for any host that exposes an API, we query the API and never the HTML.
An API answers unambiguously about existence; an HTML page can return a 200 on
"repository not found", or a Cloudflare 403 on a perfectly live resource.

Each prober returns a `ProbeResult` carrying, besides the status, the named reason for
the classification. Without that reason, a disagreement over a published figure cannot be
arbitrated.
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
    """Short, stable identifier of the rule applied, e.g. `github_api_404`.
    Tested directly by the E2 control set."""
    evidence: dict[str, Any] = field(default_factory=dict)


class Prober(abc.ABC):
    """A prober specialised for one family of hosts."""

    name: str
    method: Literal["api", "http"] = "api"

    @abc.abstractmethod
    def handles(self, link: Link) -> bool:
        """True if this prober can answer unambiguously about this link."""

    @abc.abstractmethod
    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        """Probe the link. Never raises: a network error becomes UNKNOWN."""

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
    """Translate a network exception into a named reason. All of it ends up UNKNOWN: a
    crawler failure is not a link failure (§4 pitfall 2)."""
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
    """Prober selection: the first one that declares it can answer.

    Order matters. API probers come before the generic HTTP prober, which is a safety net
    and not a default choice.
    """

    def __init__(self, probers: list[Prober]) -> None:
        self._probers = probers

    def select(self, link: Link) -> Prober:
        for prober in self._probers:
            if prober.handles(link):
                return prober
        raise LookupError(f"no prober for {link.normalized!r} (host={link.host!r})")

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        prober = self.select(link)
        try:
            return prober.check(client, link, settings)
        except Exception as exc:  # noqa: BLE001 — a prober never brings down a run
            reason, evidence = classify_transport_error(exc)
            return ProbeResult(Status.UNKNOWN, prober.method, reason, evidence)


def truncate_body(response: httpx.Response, settings: Settings) -> str:
    try:
        return response.text[: settings.body_evidence_bytes]
    except Exception:  # noqa: BLE001 — evidence is optional, the probe is not
        return ""
