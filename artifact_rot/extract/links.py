"""Extraction des liens d'artefacts depuis le texte integral.

L'extraction se fait sur le **texte reparé** (§ `normalize.repair_spaced_hosts`), jamais
sur le texte brut : 85 % des articles du corpus de validation de metacheck contiennent
des URL coupees par l'extraction PDF, et une regex appliquee avant reparation les perd
silencieusement.

Ce module ne juge pas si un lien est vivant. Il produit des `Link`, avec leur provenance
et leur forme canonique. La classification, c'est `probe/`.
"""

from __future__ import annotations

import re

from ..models import Link, LinkKind
from .normalize import (
    DOI,
    canonicalize,
    host_of,
    is_malformed,
    is_on_request,
    kind_of,
    repair_spaced_hosts,
)
from .statements import classify_position, find_availability_spans, find_references_span

URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
BARE_DOI = re.compile(r"\bdoi\s*:\s*(10\.\d{4,9}/[-._;()/:a-z0-9]+[a-z0-9])", re.IGNORECASE)

ARTIFACT_HOSTS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    "softwareheritage.org",
    "archive.softwareheritage.org",
    "zenodo.org",
    "figshare.com",
    "osf.io",
    "datadryad.org",
    "dataverse.harvard.edu",
    "dataverse.org",
    "openneuro.org",
    "dandiarchive.org",
    "huggingface.co",
    "kaggle.com",
    "mendeley.com",
    "data.mendeley.com",
    "pangaea.de",
    "zenodo.figshare.com",
}
"""Hebergeurs d'artefacts reconnus. Un lien hors de cette liste n'est pas ecarte : il
devient `generic_url` et reste sonde. La liste sert a mesurer le rappel (E3) sur la
population qui compte, pas a filtrer."""

BOILERPLATE = re.compile(
    r"""(?ix)
    creativecommons\.org
  | crossmark\.crossref\.org
  | ^https?://(www\.)?(doi|dx\.doi)\.org/?$
  | orcid\.org
  | ror\.org
  | scholar\.google
  | \.(?:png|jpe?g|gif|svg|css|js|ico)(?:$|\?)
  | ^https?://(www\.)?(twitter|x|facebook|linkedin|instagram)\.com
  | ^https?://(www\.)?researchgate\.net
  | issn\.
  | lattes\.cnpq\.br
    """
)
"""Liens de fabrication editoriale, presents dans presque tout PDF : licence, marque de
controle, profils d'auteurs, feuilles de style. Les compter comme artefacts gonflerait
le denominateur avec des liens dont la survie n'interesse personne."""


def is_boilerplate(url: str) -> bool:
    return bool(BOILERPLATE.search(url))


def is_artifact_link(url: str) -> bool:
    """Le lien designe-t-il un artefact de recherche ?

    Sert au calcul du rappel d'E3 : mesurer le rappel sur *toutes* les URL d'un article
    melangerait les liens qui nous interessent avec les centaines de DOI de sa
    bibliographie, et produirait un chiffre flatteur et vide de sens.
    """
    if is_boilerplate(url):
        return False
    host = host_of(url)
    if host in ARTIFACT_HOSTS:
        return True
    return bool(DOI.search(url)) and host in {"doi.org", "dx.doi.org"}


TRAILING_PUNCT = ".,;:!?”»'\"" + ")]}"


def iter_raw_links(text: str):
    """Chaque URL ou DOI du texte, avec sa position — la position donne la provenance.

    La ponctuation de fin de phrase est retiree ici et pas plus loin : `Link.raw` doit
    porter l'URL telle que l'auteur l'a ecrite, et le point qui termine la phrase ne
    fait pas partie de l'URL. Le laisser obligerait chaque consommateur a s'en occuper,
    et un seul oubli produirait un lien mort qui n'a jamais existe.
    """
    repaired = repair_spaced_hosts(text)
    for m in URL_IN_TEXT.finditer(repaired):
        url = m.group(0).rstrip(TRAILING_PUNCT)
        if url:
            yield m.start(), url
    for m in BARE_DOI.finditer(repaired):
        yield m.start(), f"https://doi.org/{m.group(1).rstrip(TRAILING_PUNCT)}"


def extract_links(
    text: str,
    *,
    paper_id: str,
    paper_year: int,
    discipline: str,
    publisher: str,
    paper_doi: str | None = None,
    structured_urls: list[str] | None = None,
) -> list[Link]:
    """Produit les `Link` d'un article, dedupliques et attribues a leur provenance.

    `structured_urls` (annotations PDF, `<a href>`, `<ext-link>`) est **fusionne** avec
    l'extraction textuelle, pas oppose a elle : la mesure du 2026-09-20 montre que les
    annotations contiennent des URL que le texte perd par cesure, et le texte contient
    des URL que l'editeur n'a pas balisees. Prendre l'union est la seule option qui ne
    jette rien.

    La provenance d'un lien venu des seules annotations est `body` : une annotation ne
    dit pas dans quelle section elle se trouve.
    """
    repaired = repair_spaced_hosts(text)
    availability = find_availability_spans(repaired)
    references = find_references_span(repaired)

    seen: set[str] = set()
    links: list[Link] = []

    def add(raw: str, source: str) -> None:
        normalized = canonicalize(raw)
        if normalized in seen or is_boilerplate(normalized):
            return
        seen.add(normalized)
        links.append(
            Link(
                paper_id=paper_id,
                paper_doi=paper_doi,
                paper_year=paper_year,
                discipline=discipline,
                publisher=publisher,
                raw=raw,
                normalized=normalized,
                kind=_kind(normalized),
                host=host_of(normalized),
                source=source,  # type: ignore[arg-type]
                malformed_at_source=is_malformed(raw),
            )
        )

    for pos, raw in iter_raw_links(text):
        add(raw, classify_position(pos, availability, references))

    for raw in structured_urls or []:
        # Les annotations d'un PDF contiennent aussi `mailto:`, `tel:` et `file:///` —
        # les adresses des auteurs et des chemins locaux restes dans le document. Ce ne
        # sont pas des liens d'artefacts, et il n'est pas question de les toucher.
        if raw.lower().startswith(("http://", "https://")):
            add(raw, "body")

    return links


def _kind(url: str) -> LinkKind:
    return kind_of(url)  # type: ignore[return-value]


def count_on_request(text: str) -> int:
    """Piege 4 : « disponible sur demande » n'est pas un lien.

    Compte a part, jamais sonde, et le rapport dit qu'on n'a pas teste — on n'ecrit pas
    a des milliers d'auteurs. Le compte porte sur les declarations de disponibilite
    seules : la formule apparait aussi dans des contextes sans rapport.
    """
    repaired = repair_spaced_hosts(text)
    return sum(
        1 for span in find_availability_spans(repaired) if is_on_request(span.slice(repaired))
    )
