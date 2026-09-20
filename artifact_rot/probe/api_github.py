"""Sonde GitHub / GitLab / Bitbucket : API uniquement, jamais le HTML.

Limite structurelle, assumee et reportee dans le rapport (§9) : l'API GitHub renvoie
**404 pour un depot supprime comme pour un depot passe en prive**. Aucun appel public
ne distingue les deux. On classe donc `dead` en portant dans la preuve le drapeau
`indistinguishable_private_or_deleted`, et `probe/api_swh.py` permet de savoir
a posteriori si le depot a existe publiquement (Software Heritage l'aurait archive).

Un depot `archived` ou `disabled` reste `alive` : il resout, on peut le lire. C'est la
resolution qu'on mesure, pas la sante du projet.

Portee : on sonde l'existence du **depot**, pas celle d'un fichier ou d'un commit
particulier a l'interieur. Un lien vers `…/blob/main/data.csv` est compte vivant si le
depot vit. Choix conservateur, ecrit dans les limites du rapport.
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

        # Garde de quota : on ne frappe pas une API dont on sait qu'elle va refuser.
        # Bruler le reste du quota en 403 est incorrect envers l'hebergeur et ne produit
        # que des `unknown` (§4, piege 5).
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
                # Ne leve PAS l'ambiguite prive/supprime — rien de public ne le peut.
                # Repond a l'autre question, celle du piege 3 : ce depot a-t-il existe
                # publiquement ? Une archive SWH prouve qu'il a vecu, donc que son
                # absence d'aujourd'hui est du rot et non un lien qui n'a jamais marche.
                arch = ever_existed(client, f"https://github.com/{owner}/{repo}")
                ev["swh_known"] = arch.known
                ev["swh_last_visit"] = arch.last_visit
                ev["swh_reason"] = arch.reason
            return ProbeResult(Status.DEAD, "api", "github_api_404", ev)

        if r.status_code == 451:
            # Retrait pour raisons legales : la ressource a existe, l'acces est bloque.
            return ProbeResult(Status.RESTRICTED, "api", "github_api_451_legal", ev)

        if r.status_code in (403, 429):
            remaining = r.headers.get("x-ratelimit-remaining")
            ev |= {"x_ratelimit_remaining": remaining, "retry_after": r.headers.get("retry-after")}
            if remaining == "0" or r.status_code == 429:
                # Echec du crawler, pas du lien (§4 piege 1).
                return ProbeResult(Status.UNKNOWN, "api", "github_rate_limited", ev)
            return ProbeResult(Status.UNKNOWN, "api", "github_api_403_unexplained", ev)

        ev["body"] = truncate_body(r, settings)
        return ProbeResult(Status.UNKNOWN, "api", f"github_api_{r.status_code}", ev)


class _RateLimitTracker:
    """Suit le quota annonce par GitHub dans ses en-tetes.

    Ajoute apres le run du 2026-09-20, ou trois passages du jeu de controle ont epuise
    les 60 requetes/heure du mode anonyme et rendu neuf cas `dead` en `unknown`. Le
    classement etait correct — un echec de crawler n'est pas un lien mort — mais la
    mesure devenait impossible. Le probleme est d'ordonnancement, pas de classification.

    Deux consequences, toutes deux de la responsabilite du §4 piege 5 :
    la sonde cesse de frapper quand le quota est epuise plutot que d'accumuler des 403,
    et le controle du proprietaire (qui double le cout de chaque 404) devient optionnel.
    """

    RESERVE = 2
    """Requetes gardees en reserve : le controle de proprietaire ne doit jamais etre ce
    qui epuise le quota au detriment d'une sonde principale."""

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
    """Le compte proprietaire existe-t-il encore ? N'est pas une preuve d'existence du
    depot, mais separe « compte supprime » de « depot supprime » dans l'analyse.

    Enrichissement, pas classification : il est abandonne des que le quota devient
    serre, et le resultat vaut alors `None` (indetermine), jamais une valeur inventee.
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
