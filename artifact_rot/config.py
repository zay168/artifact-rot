"""Configuration d'execution. Piege 5 (§4) : etre un citoyen correct du reseau.

Le contact du `User-Agent` n'est pas code en dur : il est lu dans l'environnement et
son absence est une erreur bloquante. Sonder des milliers de depots scientifiques sans
laisser de moyen de nous joindre est exactement ce que le §4 interdit.
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
    """Adresse de contact publique, exposee dans le User-Agent. Via ARTIFACT_ROT_CONTACT."""

    github_token: str | None = None
    """60 req/h sans jeton, 5000 avec. Via GITHUB_TOKEN. Un jeton sans aucun scope
    suffit : on ne lit que du public.

    Sans jeton, le run S1 (§3, >= 2000 articles par strate croisee) est impossible :
    le quota anonyme est epuise par quelques centaines de liens. Ce n'est donc pas
    une commodite, c'est une condition de faisabilite de E5."""

    github_owner_check: bool = True
    """Sur un 404 GitHub, verifier si le compte proprietaire existe encore. C'est un
    enrichissement d'analyse qui **double le cout en quota de chaque 404** — et le 404
    est le cas majoritaire dans un observatoire de liens morts. Desactive
    automatiquement en l'absence de jeton (voir `from_env`)."""

    swh_enrichment: bool = True
    """Sur un 404 de forge, demander a Software Heritage si l'origine a ete archivee.

    Ne leve pas l'ambiguite prive/supprime — rien de public ne le peut. Repond a l'autre
    question, celle du piege 3 : le depot a-t-il existe publiquement ? Une archive prouve
    qu'il a vecu, donc que son absence est du rot et non un lien qui n'a jamais marche.

    Une requete supplementaire par 404, sur une API tierce a quota propre. A couper si
    SWH limite le debit pendant un run.
    """

    timeout_s: float = 12.0
    max_concurrency: int = 64
    """Connexions HTTP simultanees du client.

    **Ne regle pas la politesse** — c'est le limiteur par hote (`limiter.py`) qui s'en
    charge, et lui seul. Ce nombre ne fait que plafonner le pool de connexions.

    Il valait 4, herite d'une epoque ou le sondage etait sequentiel. Une fois le pool de
    threads en place, ce 4 annulait tout le parallelisme en silence : quarante-huit
    threads se partageaient quatre connexions, et le debit restait identique a celui de
    seize threads. Un plafond cache est pire qu'un plafond assume."""

    per_host_delay_s: float = 1.0
    respect_robots: bool = True
    body_evidence_bytes: int = 2048
    """Taille du corps conserve comme preuve. Tronque, mais conserve (§5)."""

    min_probe_span_days: int = 10
    """Ecart calendaire minimal entre la premiere et la troisieme sonde avant qu'un
    lien puisse etre declare `dead`. §4 piege 1 : jamais dans la meme minute."""

    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def user_agent(self) -> str:
        return f"artifact-rot/0.1 (+{PROJECT_URL}; {self.contact})"

    @classmethod
    def from_env(cls) -> Settings:
        contact = os.environ.get("ARTIFACT_ROT_CONTACT", "").strip()
        if not contact:
            raise ConfigError(
                "ARTIFACT_ROT_CONTACT est obligatoire : le User-Agent doit porter un "
                "contact joignable (PLAN.md §4, piege 5). Exemple : "
                'ARTIFACT_ROT_CONTACT="artifact-rot@exemple.org"'
            )
        token = os.environ.get("GITHUB_TOKEN") or None
        return cls(
            contact=contact,
            github_token=token,
            # Sans jeton, 60 requetes/heure : l'enrichissement passe apres la mesure.
            github_owner_check=token is not None,
        )
