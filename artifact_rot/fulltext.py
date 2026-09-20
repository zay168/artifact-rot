"""E3 — recuperation du texte integral. Sources ouvertes uniquement.

Trois mesures faites sur l'echantillon le 2026-09-20, qui dictent toute la conception :

1. **Le format dominant est le PDF** (54 % des localisations de `best_oa_location`),
   loin devant le HTML (7 %). Un extracteur qui ne lit que du HTML mesurerait une
   discipline, pas quatre.
2. **Europe PMC ne couvre que la medecine** : 38 % des articles medicaux disponibles en
   JATS, 1 a 2 % ailleurs. Excellente source, mais pas une source d'echantillon.
3. **Preferer les depots aux sites d'editeurs fait passer le taux de recuperation de
   61 % a 72 %.** Les gros editeurs (Wiley, ScienceDirect, MDPI, OUP) repondent 403 a un
   robot ; les depots institutionnels, arXiv et PMC ne le font pas.

D'ou l'ordre de preference : depot d'abord, editeur en dernier. Ce n'est pas un
contournement — on demande poliment ailleurs une copie que l'auteur a lui-meme deposee.
Un 403 reste un 403 : on ne le force jamais.

**L'attrition residuelle (~28 %) est une limite, pas un detail.** Elle doit etre mesuree
par strate : si elle est correlee a l'annee, elle biaise la variable explicative
principale. `coverage_report` produit ce chiffre, et E6 doit le publier.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

from .config import Settings

CACHE_DIR = Path("data/fulltext")
OPENALEX = "https://api.openalex.org"

DocKind = Literal["pdf", "html", "jats", "none"]

MAX_LOCATION_ATTEMPTS = 4
"""Nombre maximal de localisations essayees pour un article.

Quatre essais couvrent le cas normal (PDF de depot, PDF d'editeur, page de depot,
page d'editeur). Au-dela, on paie des timeouts pour apprendre ce qu'on sait deja."""


@dataclass
class Document:
    """Un texte integral recupere, avec ses liens balises par la source.

    `structured_urls` est la cle d'E3 : ce sont les URL posees par l'editeur
    (annotations `/URI` d'un PDF, `<a href>` d'un HTML, `<ext-link>` d'un JATS). Elles
    constituent une verite terrain gratuite contre laquelle mesurer le rappel de
    l'extraction textuelle — le meme principe que celui qui fonde le projet entier.
    """

    paper_id: str
    source_url: str
    source_type: str
    kind: DocKind
    text: str = ""
    structured_urls: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind != "none" and bool(self.text)


# --- Choix de la localisation ------------------------------------------------------


def rank_locations(locations: list[dict]) -> list[tuple[str, str]]:
    """Ordonne les localisations ouvertes. **Tout PDF passe avant toute page HTML.**

    La premiere version classait par type de source seulement — depots d'abord — et
    choisissait donc la page de notice d'un depot (par exemple `zenodo.org/records/…`)
    avant le PDF de l'editeur. Or **une page de notice n'est pas l'article** : son texte
    est celui du site hote, et ses liens sont ceux de son menu et de son pied de page.

    Le defaut ne s'est pas vu a la recuperation, qui « marchait ». Il s'est vu au calcul
    de rappel : les liens de depot soi-disant manques etaient en realite les liens du
    site Zenodo vers son propre code (`github.com/zenodo/zenodo-rdm`). Sans cette
    mesure, tout le run S1 aurait extrait des liens de pages de notice au lieu
    d'articles.

    D'ou l'ordre : PDF de depot, PDF d'editeur, page de depot, page d'editeur.
    """
    buckets: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for loc in locations:
        if not loc.get("is_oa"):
            continue
        source = loc.get("source") or {}
        stype = source.get("type") or "unknown"
        repo_rank = 0 if stype == "repository" else 1
        for is_pdf, url in ((0, loc.get("pdf_url")), (1, loc.get("landing_page_url"))):
            if url:
                buckets.setdefault((is_pdf, repo_rank), []).append((url, stype))

    ordered = [item for key in sorted(buckets) for item in buckets[key]]

    # Un seul essai par hote, et MAX_LOCATION_ATTEMPTS au total.
    #
    # Mesure du 2026-09-20 : sans cette limite, le moissonnage tombait a ~2 articles
    # par minute, parce qu'un article a parfois dix localisations dont plusieurs chez
    # le meme editeur — qui repond 403 ou expire a chaque fois. On payait donc le meme
    # timeout de vingt secondes cinq fois de suite pour apprendre la meme chose.
    #
    # Insister chez un hote qui vient de refuser n'est pas seulement lent : c'est
    # exactement ce que le §4, piege 5, interdit.
    seen_hosts: set[str] = set()
    capped: list[tuple[str, str]] = []
    for url, stype in ordered:
        host = httpx.URL(url).host
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        capped.append((url, stype))
        if len(capped) >= MAX_LOCATION_ATTEMPTS:
            break
    return capped


def fetch_locations(client: httpx.Client, paper_id: str, settings: Settings) -> list[dict]:
    r = client.get(
        f"{OPENALEX}/works/{paper_id}",
        params={"select": "locations", "mailto": settings.contact},
    )
    r.raise_for_status()
    return r.json().get("locations") or []


# --- Recuperation -------------------------------------------------------------------

_WAF = re.compile(r"(just a moment|checking your browser|cloudflare|captcha|access denied)", re.IGNORECASE)


def fetch_document(
    client: httpx.Client, paper_id: str, locations: list[dict], settings: Settings
) -> Document:
    """Essaie les localisations dans l'ordre et retient la premiere exploitable."""
    last_error = "aucune localisation ouverte"
    for url, stype in rank_locations(locations):
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            last_error = f"transport:{type(exc).__name__}"
            continue

        if r.status_code != 200:
            last_error = f"http_{r.status_code}"
            continue

        ctype = (r.headers.get("content-type") or "").split(";")[0].lower()
        try:
            if "pdf" in ctype:
                text, urls = read_pdf(r.content)
                return Document(paper_id, url, stype, "pdf", text, urls)
            if "xml" in ctype:
                text, urls = read_jats(r.text)
                return Document(paper_id, url, stype, "jats", text, urls)
            if "html" in ctype:
                if _WAF.search(r.text[:4000]):
                    last_error = "waf"
                    continue
                text, urls = read_html(r.text)
                return Document(paper_id, url, stype, "html", text, urls)
        except Exception as exc:  # noqa: BLE001 — un document illisible n'arrete pas un run
            last_error = f"parse:{type(exc).__name__}"
            continue
        last_error = f"content_type:{ctype or 'vide'}"

    return Document(paper_id, "", "", "none", error=last_error)


# --- Lecture par format --------------------------------------------------------------


def read_pdf(payload: bytes) -> tuple[str, list[str]]:
    """Texte rendu + annotations de lien.

    Les annotations `/URI` sont posees par l'editeur au moment de la fabrication du PDF.
    Mesure du 2026-09-20 : 52 % des PDF en portent, et elles contiennent plus d'URL que
    le texte brut (276 contre 188 sur un echantillon de 29 PDF) — l'ecart est exactement
    ce que la cesure de ligne fait perdre a une extraction purement textuelle.
    """
    from pypdf import PdfReader  # import tardif : pypdf est lent a charger

    reader = PdfReader(io.BytesIO(payload))
    urls: list[str] = []
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001,S110 — une page illisible n'invalide pas le document
            pass
        for annot in page.get("/Annots") or []:
            try:
                action = annot.get_object().get("/A") or {}
                uri = action.get("/URI")
                if uri:
                    urls.append(str(uri))
            except Exception:  # noqa: BLE001,S110 — une annotation illisible est ignoree
                pass
    return sanitize("\n".join(chunks)), [sanitize(u) for u in _dedupe_preserving(urls)]


_HREF = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)


def read_html(payload: str) -> tuple[str, list[str]]:
    urls = [sanitize(u) for u in _HREF.findall(payload) if u.startswith("http")]
    text = _TAG.sub(" ", payload)
    return _unescape(text), _dedupe_preserving(urls)


_EXT_LINK = re.compile(
    r"""<ext-link\b[^>]*xlink:href\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)


def read_jats(payload: str) -> tuple[str, list[str]]:
    """JATS : `<ext-link>` est le balisage editorial le plus explicite qui existe."""
    urls = [
        sanitize(u) for u in _EXT_LINK.findall(payload) if u.startswith(("http", "doi:", "10."))
    ]
    text = _TAG.sub(" ", payload)
    return _unescape(text), _dedupe_preserving(urls)


def sanitize(text: str) -> str:
    """Rend un texte ecrivable en UTF-8, quoi qu'il contienne.

    Mesure du 2026-09-20 : l'extraction PDF produit parfois des **demi-paires de
    substitution** — des points de code UTF-16 isoles, que Python accepte en memoire
    mais qu'aucun encodeur UTF-8 n'accepte. Le moissonnage est mort dessus apres
    200 articles, sur `UnicodeEncodeError: surrogates not allowed`.

    Ce n'est pas un cas exotique : un PDF est un format ou les polices declarent leurs
    propres tables de caracteres, et une table incoherente produit exactement ca. Sur
    40 000 articles, ce defaut aurait interrompu le run a un moment imprevisible — et
    apres des heures de travail deja faites.

    Meme principe que pour les URL hostiles : rien de ce qui sort d'un PDF ne doit
    pouvoir faire tomber la chaine.
    """
    return text.encode("utf-8", "replace").decode("utf-8")


_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " "}


def _unescape(text: str) -> str:
    text = sanitize(text)
    for k, v in _ENTITIES.items():
        text = text.replace(k, v)
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _dedupe_preserving(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# --- Cache ---------------------------------------------------------------------------


def cache_path(paper_id: str) -> Path:
    # Deux niveaux : 40 000 fichiers dans un seul repertoire est ingerable sous Windows.
    return CACHE_DIR / paper_id[1:4] / f"{paper_id}.json"


def save(doc: Document) -> None:
    path = cache_path(doc.paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "paper_id": doc.paper_id,
                "source_url": doc.source_url,
                "source_type": doc.source_type,
                "kind": doc.kind,
                "text": doc.text,
                "structured_urls": doc.structured_urls,
                "error": doc.error,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load(paper_id: str) -> Document | None:
    path = cache_path(paper_id)
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return Document(
        paper_id=d["paper_id"],
        source_url=d["source_url"],
        source_type=d["source_type"],
        kind=d["kind"],
        text=d["text"],
        structured_urls=d["structured_urls"],
        error=d["error"],
    )
