"""Contrats de donnees. Definis au §5 du PLAN.md et figes ici.

Toute modification d'un de ces modeles invalide les runs anterieurs : un run est
immuable (§5), donc un changement de schema impose un nouveau repertoire de run,
jamais une reecriture.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    """Les quatre etats du piege 2 (§4). Jamais deux, jamais trois.

    ALIVE      : l'existence de la ressource est positivement confirmee.
    DEAD       : l'inexistence est positivement confirmee (404 d'API, 410, DOI non enregistre).
    RESTRICTED : la ressource existe mais l'acces est controle (401/403 authentifiable,
                 depot prive avere, embargo). Cas legitime, frequent en medecine.
    UNKNOWN    : le crawler a echoue (timeout, 429, 5xx, DNS, TLS, robots.txt interdit).
                 N'entre JAMAIS au denominateur d'un taux publie.
    """

    ALIVE = "alive"
    DEAD = "dead"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


LinkKind = Literal[
    "code_repo",
    "data_repo",
    "dataset_doi",
    "generic_url",
    "on_request",  # piege 4 : « available upon request » n'est pas un lien, jamais sonde
]

LinkSource = Literal["availability_statement", "body", "references"]
"""D'ou vient le lien dans l'article.

`references` est isole a cause du mode d'echec n°1 de metacheck (issue #411) : un DOI
de depot cite uniquement en bibliographie est invisible si l'on exclut cette section,
mais l'inclure cree un risque de fausse attribution (le depot peut appartenir a un
article cite, pas a l'article courant). On extrait, on marque, et le rapport peut
trancher a posteriori. Voir docs/etat-de-lart.md §2.2.
"""


class Link(BaseModel):
    """Un lien d'artefact extrait d'un article. Une ligne = une promesse faite par un article.

    **Ecart assume au PLAN.md §5**, decide a E1 le 2026-09-20 : le plan donne
    `paper_doi: str` comme cle. La mesure sur l'echantillon montre que 6,8 % des articles
    tires n'ont pas de DOI dans OpenAlex, et que le manque est **fortement correle a
    l'age** — 44 % en informatique 2010 contre 4 % en 2025. Filtrer sur la presence d'un
    DOI aurait donc introduit un biais de selection portant precisement sur la variable
    explicative principale du projet. La cle devient l'identifiant OpenAlex, stable et
    universel sur l'echantillon ; le DOI reste porte quand il existe, parce que c'est lui
    qui parle aux editeurs et aux lecteurs.
    """

    paper_id: str
    """Identifiant OpenAlex (`W…`). Cle primaire : present sur 100 % de l'echantillon."""
    paper_doi: str | None = None
    paper_year: int
    discipline: str
    publisher: str
    raw: str
    """Tel qu'ecrit dans l'article, avant toute normalisation. Preuve : sans lui, on ne
    peut pas arbitrer une contestation sur l'extraction."""
    normalized: str
    kind: LinkKind
    host: str
    source: LinkSource = "availability_statement"
    malformed_at_source: bool = False
    """Piege 3 (§4) : casse des la publication, n'a jamais fonctionne. Categorie
    differente d'un lien mort. Mesure le controle editorial, pas le rot."""

    @property
    def link_id(self) -> str:
        """Identifiant deterministe et stable entre runs."""
        payload = f"{self.paper_id}\x1f{self.normalized}\x1f{self.kind}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Probe(BaseModel):
    """Une sonde, c'est-a-dire une observation datee de l'etat d'un lien."""

    link_id: str
    probed_at: datetime
    method: Literal["api", "http"]
    status: Status
    evidence: dict[str, Any] = Field(default_factory=dict)
    """Code HTTP, corps tronque, reponse d'API, raison de classification. §5 : toute
    preuve conservee, sinon une contestation est inarbitrable."""
    attempt: int = Field(ge=1, le=3)


class LinkOutcome(BaseModel):
    """Statut final d'un lien, fonction deterministe de ses sondes. Voir `resolve`."""

    link_id: str
    status: Status
    rule: str
    """Nom de la regle appliquee. Rend la decision auditable ligne a ligne."""
    probes: list[Probe]
    first_probe_at: datetime
    last_probe_at: datetime
    right_censored: bool
    """§6 : un lien encore vivant aujourd'hui est une observation censuree a droite,
    pas un succes definitif. Le champ existe des maintenant, pas rattrape apres."""
