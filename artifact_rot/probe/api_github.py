"""GitHub / GitLab / Bitbucket prober: API only, never the HTML.

Structural limitation, accepted and stated in the report (§9): the GitHub API returns
**404 for a deleted repository as well as for one made private**. No public call tells
the two apart. We therefore classify `dead` while carrying the
`indistinguishable_private_or_deleted` flag in the evidence, and `probe/api_swh.py` lets
us know after the fact whether the repository existed publicly (Software Heritage would
have archived it).

An `archived` or `disabled` repository stays `alive`: it resolves, it can be read. We
measure resolution, not project health.

Scope: we probe the existence of the **repository**, not of a particular file or commit
inside it. A link to `…/blob/main/data.csv` counts as alive if the repository lives. A
conservative choice, written into the report's limitations.
"""

from __future__ import annotations

import httpx

from ..config import Settings
from ..extract.normalize import BITBUCKET_SLUG, GITHUB_SLUG, GITLAB_PATH
from ..models import Link, Status
from .api_swh import ever_existed
from .base import Prober, ProbeResult, truncate_body


class GitHubProber(Prober):
    name = "github"
    method = "api"

    def handles(self, link: Link) -> bool:
        return link.host == "github.com" and bool(GITHUB_SLUG.search(link.normalized))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = GITHUB_SLUG.search(link.normalized)
        if m is None:
            return self._unknown("github_slug_unparsed", url=link.normalized)
        owner, repo = m.group(1), m.group(2)

        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        url = f"https://api.github.com/repos/{owner}/{repo}"

        # Quota guard: we do not hit an API we know will refuse. Burning the rest of the
        # quota on 403s is impolite to the host and only produces `unknown` (§4,
        # pitfall 5).
        if _QUOTA.exhausted():
            return self._unknown("github_quota_guard", api_url=url, **_QUOTA.snapshot())

        r = client.get(url, headers=headers)
        _QUOTA.observe(r)
        ev = {"api_url": url, "http_status": r.status_code, "owner": owner, "repo": repo}

        if r.status_code == 200:
            body = r.json()
            ev |= {
                "full_name": body.get("full_name"),
                "archived": body.get("archived"),
                "disabled": body.get("disabled"),
                "pushed_at": body.get("pushed_at"),
            }
            return ProbeResult(Status.ALIVE, "api", "github_api_200", ev)

        if r.status_code == 404:
            ev["indistinguishable_private_or_deleted"] = True
            if settings.github_owner_check:
                ev["owner_still_exists"] = _owner_exists(client, owner, headers)
            if settings.swh_enrichment:
                # Does NOT lift the private/deleted ambiguity — nothing public can.
                # Answers the other question, pitfall 3's: did this repository exist
                # publicly? A SWH archive proves it lived, so its absence today is rot
                # and not a link that never worked.
                arch = ever_existed(client, f"https://github.com/{owner}/{repo}")
                ev["swh_known"] = arch.known
                ev["swh_last_visit"] = arch.last_visit
                ev["swh_reason"] = arch.reason
            return ProbeResult(Status.DEAD, "api", "github_api_404", ev)

        if r.status_code == 451:
            # Taken down for legal reasons: the resource existed, access is blocked.
            return ProbeResult(Status.RESTRICTED, "api", "github_api_451_legal", ev)

        if r.status_code in (403, 429):
            remaining = r.headers.get("x-ratelimit-remaining")
            ev |= {"x_ratelimit_remaining": remaining, "retry_after": r.headers.get("retry-after")}
            if remaining == "0" or r.status_code == 429:
                # A crawler failure, not a link failure (§4 pitfall 1).
                return ProbeResult(Status.UNKNOWN, "api", "github_rate_limited", ev)
            return ProbeResult(Status.UNKNOWN, "api", "github_api_403_unexplained", ev)

        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"github_api_{r.status_code}", ev)


class _RateLimitTracker:
    """Track the quota GitHub announces in its headers.

    Added after the 2026-09-20 run, where three runs of the control set exhausted the 60
    requests/hour of anonymous mode and turned nine `dead` cases into `unknown`. The
    classification was correct — a crawler failure is not a dead link — but measurement
    became impossible. The problem is one of scheduling, not classification.

    Two consequences, both falling under §4 pitfall 5: the prober stops hitting when the
    quota is exhausted rather than piling up 403s, and the owner check (which doubles the
    cost of each 404) becomes optional.
    """

    RESERVE = 2
    """Requests kept in reserve: the owner check must never be what exhausts the quota at
    the expense of a main probe."""

    def __init__(self) -> None:
        self.remaining: int | None = None
        self.reset_at: int | None = None

    def observe(self, response: httpx.Response) -> None:
        raw = response.headers.get("x-ratelimit-remaining")
        if raw is not None and raw.isdigit():
            self.remaining = int(raw)
        raw_reset = response.headers.get("x-ratelimit-reset")
        if raw_reset is not None and raw_reset.isdigit():
            self.reset_at = int(raw_reset)

    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0

    def low(self) -> bool:
        return self.remaining is not None and self.remaining <= self.RESERVE

    def snapshot(self) -> dict[str, int | None]:
        return {"x_ratelimit_remaining": self.remaining, "x_ratelimit_reset": self.reset_at}

    def reset_tracking(self) -> None:
        self.remaining = None
        self.reset_at = None


_QUOTA = _RateLimitTracker()


def _owner_exists(client: httpx.Client, owner: str, headers: dict[str, str]) -> bool | None:
    """Does the owner account still exist? Not proof that the repository exists, but it
    separates "account deleted" from "repository deleted" in the analysis.

    Enrichment, not classification: it is dropped as soon as the quota gets tight, and the
    result is then `None` (undetermined), never an invented value.
    """
    if _QUOTA.low():
        return None
    try:
        r = client.get(f"https://api.github.com/users/{owner}", headers=headers)
    except httpx.HTTPError:
        return None
    _QUOTA.observe(r)
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    return None


class GitLabProber(Prober):
    name = "gitlab"
    method = "api"

    def handles(self, link: Link) -> bool:
        return link.host == "gitlab.com" and bool(GITLAB_PATH.search(link.normalized))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = GITLAB_PATH.search(link.normalized)
        if m is None:
            return self._unknown("gitlab_path_unparsed", url=link.normalized)
        path = httpx.URL(f"https://gitlab.com/{m.group(1)}").path.strip("/")
        from urllib.parse import quote

        url = f"https://gitlab.com/api/v4/projects/{quote(path, safe='')}"
        r = client.get(url)
        ev = {"api_url": url, "http_status": r.status_code, "path": path}

        if r.status_code == 200:
            body = r.json()
            ev |= {"visibility": body.get("visibility"), "archived": body.get("archived")}
            return ProbeResult(Status.ALIVE, "api", "gitlab_api_200", ev)
        if r.status_code == 404:
            ev["indistinguishable_private_or_deleted"] = True
            return ProbeResult(Status.DEAD, "api", "gitlab_api_404", ev)
        if r.status_code in (401, 403):
            return ProbeResult(Status.RESTRICTED, "api", "gitlab_api_forbidden", ev)
        if r.status_code == 429:
            return ProbeResult(Status.UNKNOWN, "api", "gitlab_rate_limited", ev)
        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"gitlab_api_{r.status_code}", ev)


class BitbucketProber(Prober):
    name = "bitbucket"
    method = "api"

    def handles(self, link: Link) -> bool:
        return link.host == "bitbucket.org" and bool(BITBUCKET_SLUG.search(link.normalized))

    def check(self, client: httpx.Client, link: Link, settings: Settings) -> ProbeResult:
        m = BITBUCKET_SLUG.search(link.normalized)
        if m is None:
            return self._unknown("bitbucket_slug_unparsed", url=link.normalized)
        url = f"https://api.bitbucket.org/2.0/repositories/{m.group(1)}/{m.group(2)}"
        r = client.get(url)
        ev = {"api_url": url, "http_status": r.status_code}

        if r.status_code == 200:
            return ProbeResult(Status.ALIVE, "api", "bitbucket_api_200", ev)
        if r.status_code == 404:
            ev["indistinguishable_private_or_deleted"] = True
            return ProbeResult(Status.DEAD, "api", "bitbucket_api_404", ev)
        if r.status_code in (401, 403):
            return ProbeResult(Status.RESTRICTED, "api", "bitbucket_api_forbidden", ev)
        if r.status_code == 429:
            return ProbeResult(Status.UNKNOWN, "api", "bitbucket_rate_limited", ev)
        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"bitbucket_api_{r.status_code}", ev)
