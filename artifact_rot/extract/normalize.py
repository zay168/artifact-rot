"""Canonicalisation et deduplication des liens.

Trois des regles de ce module viennent directement des modes d'echec mesures par
`scienceverse/metacheck` sur son corpus de validation de 1 861 articles (issue #411,
AGPL-3.0, R — rien n'est repris du code, seulement les cas d'echec documentes ; voir
docs/etat-de-lart.md §2.2). Ils sont reproduits comme tests de regression nommes :

* `repair_spaced_hosts` : GROBID insere des espaces en fin de ligne dans les URL
  (`https://doi. org/10.7939/DVN/QYMAYV`), observe dans 85 % des articles du corpus.
  La reparation s'applique AVANT toute regex, jamais apres.
* `FIGSHARE_ID` couvre `/articles/<slug>/<id>`, motif sans segment de type de
  ressource que metacheck renvoyait en `NA`.
* la provenance `references` est portee par `Link.source` et non ecartee en silence.

L'apport propre de ce module est la separation `on_request` / `malformed_at_source`
(pieges 3 et 4 du §4), absente de metacheck.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# --- Reparation des URL cassees par l'extraction PDF -------------------------------

_SPACED_TLD = re.compile(
    r"\b((?:https?://)?(?:[\w-]+\.)+)\s+((?:org|com|net|edu|io|gov|fr|de|uk|ac\.uk)\b)",
    re.IGNORECASE,
)
_SPACED_SCHEME = re.compile(r"\bhttps?\s*:\s*//\s*", re.IGNORECASE)
_SPACED_PATH = re.compile(r"(https?://[^\s]+?)\s+(/[^\s]+)")


def repair_spaced_hosts(text: str) -> str:
    """Recolle les URL coupees par l'extraction PDF -> texte.

    Conservatrice a dessein : ne recolle que les coupures dont le membre droit est un
    TLD connu ou un segment de chemin. Recoller plus largement inventerait des liens,
    ce qui est pire qu'en manquer — on mesure du rot, pas de la creativite de regex.
    """
    out = _SPACED_SCHEME.sub("https://", text)
    out = _SPACED_TLD.sub(lambda m: m.group(1) + m.group(2), out)
    out = _SPACED_PATH.sub(lambda m: m.group(1) + m.group(2), out)
    return out


# --- Detection « sur demande » (piege 4) -------------------------------------------

_ON_REQUEST = re.compile(
    r"\b("
    r"(?:available|obtainable|provided|shared|furnished)\s+"
    r"(?:(?:from|by|upon|on)\s+)*(?:the\s+)?"
    r"(?:reasonable\s+)?request"
    r"|upon\s+reasonable\s+request"
    r"|contact\s+the\s+(?:corresponding\s+)?author"
    r"|sur\s+demande(?:\s+raisonnable)?"
    r")\b",
    re.IGNORECASE,
)


def is_on_request(statement: str) -> bool:
    """« Disponible sur demande » n'est pas un lien : ni mort, ni vivant, jamais sonde.

    Compte et reporte a part (§4 piege 4). On n'ecrit pas a des milliers d'auteurs.
    """
    return bool(_ON_REQUEST.search(statement))


# --- Identifiants d'hebergeurs ------------------------------------------------------

GITHUB_SLUG = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?=[/#?]|$)",
    re.IGNORECASE,
)
GITLAB_PATH = re.compile(r"(?:https?://)?(?:www\.)?gitlab\.com/((?:[\w.-]+/)+[\w.-]+?)(?=[/#?]|$)")
BITBUCKET_SLUG = re.compile(r"(?:https?://)?(?:www\.)?bitbucket\.org/([\w.-]+)/([\w.-]+?)(?=[/#?]|$)")
ZENODO_ID = re.compile(r"zenodo\.org/(?:record|records|doi/10\.5281/zenodo\.)?/?(\d+)", re.IGNORECASE)
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
OSF_ID = re.compile(r"osf\.io/([a-z0-9]{5})(?=[/#?]|$)", re.IGNORECASE)
FIGSHARE_ID = re.compile(r"figshare\.com/(?:s/\w+|articles/(?:[^/]+/)?[^/]+/(\d+))", re.IGNORECASE)
DRYAD_DOI = re.compile(r"10\.5061/dryad\.(\w+)", re.IGNORECASE)
SWH_ID = re.compile(r"swh:1:(snp|rel|rev|dir|cnt):[0-9a-f]{40}", re.IGNORECASE)
DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+[a-z0-9]", re.IGNORECASE)

_CODE_HOSTS = {"github.com", "gitlab.com", "bitbucket.org", "softwareheritage.org", "codeberg.org"}
_DATA_HOSTS = {
    "zenodo.org",
    "figshare.com",
    "osf.io",
    "datadryad.org",
    "dataverse.harvard.edu",
    "dataverse.org",
    "opendata.example",
}

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"}
_TRAILING_PUNCT = ".,;:)]}>\"'"


def host_of(url: str) -> str:
    netloc = urlsplit(url if "//" in url else f"https://{url}").netloc.lower()
    netloc = netloc.removeprefix("www.")
    return netloc.split(":")[0]


def canonicalize(raw: str) -> str:
    """Forme canonique servant a la deduplication et au `link_id`.

    Ne resout rien, ne suit aucune redirection : deux liens differents dans le texte
    doivent rester deux liens si les auteurs les ont ecrits differemment, sauf
    difference purement cosmetique (schema, `www.`, ponctuation finale, parametres de
    tracking, slash final).
    """
    url = raw.strip().rstrip(_TRAILING_PUNCT).strip()
    url = repair_spaced_hosts(url)
    if url.lower().startswith("doi:"):
        url = "https://doi.org/" + url[4:].strip()
    elif DOI.fullmatch(url):
        url = "https://doi.org/" + url
    if "//" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    scheme = "https"
    netloc = parts.netloc.lower()
    netloc = netloc.removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    query = "&".join(
        q for q in parts.query.split("&") if q and q.split("=")[0].lower() not in _TRACKING_PARAMS
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def kind_of(url: str) -> str:
    host = host_of(url)
    if host == "doi.org" or DOI.search(url):
        if ZENODO_DOI.search(url) or DRYAD_DOI.search(url):
            return "data_repo"
        return "dataset_doi"
    if host in _CODE_HOSTS or SWH_ID.search(url):
        return "code_repo"
    if host in _DATA_HOSTS:
        return "data_repo"
    return "generic_url"


_VALID_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(\.(?!-)[a-z0-9-]{1,63})+$")


def is_malformed(raw: str) -> bool:
    """Piege 3 (§4) : casse des la publication, n'a donc jamais pu fonctionner.

    Mesure le controle editorial, pas le rot. A ne surtout pas melanger au taux de
    liens morts : ce sont deux chiffres, tous deux interessants, jamais additionnes.

    Volontairement syntaxique et hors-ligne : aucune requete reseau n'intervient ici.
    Un lien bien forme mais pointant nulle part est `dead`, pas `malformed`.
    """
    candidate = canonicalize(raw)
    parts = urlsplit(candidate)
    host = parts.netloc.split(":")[0]
    if not host or not _VALID_HOSTNAME.match(host):
        return True
    if " " in candidate.strip():
        return True
    if host == "doi.org":
        return not DOI.search(parts.path)
    if host == "github.com":
        # Un lien GitHub sans owner/repo ne designe aucune ressource.
        return not GITHUB_SLUG.search(candidate)
    return False


def dedupe(urls: list[str]) -> list[str]:
    """Deduplication stable : premiere occurrence conservee, ordre du texte preserve."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        key = canonicalize(url)
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out
