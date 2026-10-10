"""Prober registry.

Order matters: every API prober comes before the generic HTTP prober (§4, pitfall 1 —
"query the API, never the HTML"). The generic prober closes the list because it accepts
anything starting with `http`.
"""

from __future__ import annotations

from .api_doi import DOIProber
from .api_github import BitbucketProber, GitHubProber, GitLabProber
from .api_zenodo import FigshareProber, OSFProber, ZenodoProber
from .base import Prober, ProbeResult, ProberRegistry, build_client
from .http_generic import GenericHTTPProber


def default_registry() -> ProberRegistry:
    return ProberRegistry(
        [
            GitHubProber(),
            GitLabProber(),
            BitbucketProber(),
            ZenodoProber(),
            OSFProber(),
            FigshareProber(),
            DOIProber(),
            GenericHTTPProber(),  # always last
        ]
    )


__all__ = [
    "BitbucketProber",
    "DOIProber",
    "FigshareProber",
    "GenericHTTPProber",
    "GitHubProber",
    "GitLabProber",
    "OSFProber",
    "ProbeResult",
    "Prober",
    "ProberRegistry",
    "ZenodoProber",
    "build_client",
    "default_registry",
]
