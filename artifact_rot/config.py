"""Run configuration. Pitfall 5 (§4): be a good network citizen.

The `User-Agent` contact is not hard-coded: it is read from the environment and its
absence is a blocking error. Probing thousands of scientific repositories without
leaving a way to reach us is exactly what §4 forbids.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

PROJECT_URL = "https://github.com/zay168/artifact-rot"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    contact: str
    """Public contact address, exposed in the User-Agent. Via ARTIFACT_ROT_CONTACT."""

    github_token: str | None = None
    """60 req/h without a token, 5,000 with one. Via GITHUB_TOKEN. A token with no scope
    at all is enough: we only read public data.

    Without a token the S1 run (§3, >= 2,000 papers per crossed stratum) is impossible:
    the anonymous quota is exhausted by a few hundred links. It is therefore not a
    convenience but a feasibility condition for E5."""

    github_owner_check: bool = True
    """On a GitHub 404, check whether the owner account still exists. It is an analysis
    enrichment that **doubles the quota cost of every 404** — and the 404 is the majority
    case in a dead-link observatory. Disabled automatically without a token (see
    `from_env`)."""

    swh_enrichment: bool = True
    """On a forge 404, ask Software Heritage whether the origin was archived.

    It does not resolve the private/deleted ambiguity — nothing public can. It answers
    the other question, pitfall 3: did the repository ever exist publicly? An archive
    proves it lived, hence that its absence is rot and not a link that never worked.

    One extra request per 404, on a third-party API with its own quota. To be switched
    off if SWH throttles during a run.
    """

    timeout_s: float = 12.0
    max_concurrency: int = 64
    """Simultaneous HTTP connections of the client.

    **It sets no politeness** — the per-host limiter (`limiter.py`) does that, and only
    it. This number merely caps the connection pool.

    It used to be 4, inherited from the time when probing was sequential. Once the thread
    pool was in place, that 4 silently cancelled all parallelism: forty-eight threads
    shared four connections, and throughput stayed identical to sixteen threads. A hidden
    cap is worse than a declared one."""

    per_host_delay_s: float = 1.0
    respect_robots: bool = True
    body_evidence_bytes: int = 2048
    """Size of the response body kept as evidence. Truncated, but kept (§5)."""

    min_probe_span_days: int = 10
    """Minimum calendar gap between the first and the third probe before a link can be
    declared `dead`. §4 pitfall 1: never within the same minute."""

    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def user_agent(self) -> str:
        return f"artifact-rot/0.1 (+{PROJECT_URL}; {self.contact})"

    @classmethod
    def from_env(cls) -> Settings:
        contact = os.environ.get("ARTIFACT_ROT_CONTACT", "").strip()
        if not contact:
            raise ConfigError(
                "ARTIFACT_ROT_CONTACT is mandatory: the User-Agent must carry a reachable "
                "contact (PLAN.md §4, pitfall 5). Example: "
                'ARTIFACT_ROT_CONTACT="artifact-rot@example.org"'
            )
        token = os.environ.get("GITHUB_TOKEN") or None
        return cls(
            contact=contact,
            github_token=token,
            # Without a token, 60 requests/hour: enrichment comes after measurement.
            github_owner_check=token is not None,
        )
