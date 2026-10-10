"""Generic HTTP prober — the safety net, not the default choice.

It is only used for hosts without an API: personal pages, institutional repositories,
lab servers. This is where §4 pitfall 1 bites hardest, because a `200` means nothing.

**Soft-404 detection by control probe**, a classic and fully deterministic technique,
with no human annotation: we ask the same host for a deliberately non-existent URL, and
compare its response with the target URL's. If the server answers the same to both, its
`200` carries no information and the target is declared dead.

`403` is handled with care: a web application firewall blocking a robot is a crawler
failure (`unknown`), not controlled access (`restricted`) nor a disappearance. Confusing
them would be exactly the falsification §4 forbids.
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
"""Above this, the target's response is deemed indistinguishable from that of a
non-existent URL. Threshold fixed before the first run and validated by the E2 control
set."""

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

        # Name resolution before any request. A name that does not exist yields an
        # answer — the DNS's — and not a crawler failure. See `probe/dns.py` for the
        # decision and its safeguards.
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
                # Probing forbidden: we know nothing, and we do not override (§4 pitfall 5).
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
                # Likely anti-robot blocking: crawler failure, status undetermined.
                return ProbeResult(Status.UNKNOWN, "http", "http_blocked_by_waf", ev)
            return ProbeResult(Status.RESTRICTED, "http", f"http_{r.status_code}_auth", ev)

        if r.status_code != 200:
            ev["body"] = body
            return ProbeResult(Status.UNKNOWN, "http", f"http_{r.status_code}", ev)

        # 200 — this is where the code lies. Three tests, from cheapest to most expensive.
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
            # The server can say no: its 200 is credible.
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
    """A redirect from a specific resource to the site root is a classic soft-404: the
    server no longer knows where the resource is and sends the home page."""
    o, f = urlsplit(original), urlsplit(final)
    return bool(o.path.strip("/")) and f.path.strip("/") == "" and o.netloc == f.netloc


def _title_of(body: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def _control_probe(client: httpx.Client, url: str, settings: Settings) -> dict:
    """Request a URL guaranteed not to exist on the same host, in the same directory.

    The path carries a UUID and the project name: anyone reading their logs immediately
    sees who is knocking and why."""
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
    """Structural similarity between two responses, after removing variable noise.

    Digits, UUIDs and whitespace are stripped: two identical error pages often differ
    only by a timestamp or a request identifier."""
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
                parser.parse([])  # no robots.txt = everything allowed
        except httpx.HTTPError:
            _ROBOTS_CACHE[origin] = None
            return None
        _ROBOTS_CACHE[origin] = parser
    parser = _ROBOTS_CACHE[origin]
    if parser is None:
        return None
    return parser.can_fetch(settings.user_agent, url)
