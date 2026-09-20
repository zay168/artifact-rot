"""Registre des sondes.

L'ordre est significatif : toute sonde d'API passe avant la sonde HTTP generique
(§4, piege 1 — « interroger l'API, jamais le HTML »). La sonde generique ferme la
liste parce qu'elle accepte tout ce qui commence par `http`.
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
            GenericHTTPProber(),  # toujours en dernier
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
