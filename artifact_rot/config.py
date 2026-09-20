"""Configuration d'execution. Piege 5 (§4) : etre un citoyen correct du reseau.

Le contact du `User-Agent` n'est pas code en dur : il est lu dans l'environnement et
son absence est une erreur bloquante. Sonder des milliers de depots scientifiques sans
laisser de moyen de nous joindre est exactement ce que le §4 interdit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

PROJECT_URL = "https://github.com/artifact-rot/artifact-rot"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    contact: str
    """Adresse de contact publique, exposee dans le User-Agent. Via ARTIFACT_ROT_CONTACT."""

    github_token: str | None = None
    """Facultatif mais fortement conseille : 60 req/h sans jeton, 5000 avec.
    Via GITHUB_TOKEN. Un jeton sans aucun scope suffit — on ne lit que du public."""

    timeout_s: float = 20.0
    max_concurrency: int = 4
    """Volontairement bas. Le cout du projet est le temps calendaire (§8), pas le debit."""

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
        return cls(
            contact=contact,
            github_token=os.environ.get("GITHUB_TOKEN") or None,
        )
