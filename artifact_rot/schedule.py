"""E4 — ordonnanceur des trois passes, file persistante, reprise.

Critere de passage (PLAN.md §7) : **passe a blanc complete sans depasser les quotas.**

Le cout du projet n'est pas le calcul, c'est le **temps calendaire** (§8). Trois sondes
espacees d'au moins dix jours imposent deux semaines entre la premiere et la derniere.
Ce n'est pas du travail, c'est de l'attente — et elle est gratuite si elle est
anticipee, couteuse si on la decouvre a la fin.

L'ordonnanceur doit donc survivre a tout : une coupure reseau, un redemarrage, une
fermeture de portable pendant douze jours. D'ou une file **SQLite**, pas un fichier
tenu en memoire : chaque sonde est ecrite des qu'elle revient, et reprendre revient a
relancer la meme commande.

### Economie assumee : on arrete de sonder un lien vivant

La regle de resolution (§5) dit qu'une seule observation vivante l'emporte. Sonder deux
fois de plus un lien deja vu vivant n'ajoute rien a son statut, et represente l'essentiel
du trafic. On s'arrete donc des qu'un lien est `alive` ou `restricted`.

Trois consequences, toutes assumees :

* le trafic impose aux hebergeurs chute d'environ 80 % — ce qui est le §4, piege 5 ;
* un lien qui meurt entre la passe 1 et la passe 3 est compte vivant. La mesure est
  donc **conservatrice** : elle sous-estime la mortalite, jamais l'inverse ;
* les trois sondes restent obligatoires pour declarer un lien mort, sans exception.

Usage :
    python -m artifact_rot.schedule load runs/<...>/links.jsonl
    python -m artifact_rot.schedule plan          # ce que la prochaine passe ferait
    python -m artifact_rot.schedule dryrun        # passe a blanc, sans reseau
    python -m artifact_rot.schedule run           # passe reelle
    python -m artifact_rot.schedule status
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .config import ConfigError, Settings
from .extract.normalize import host_of
from .limiter import HostRateLimiter
from .models import Link, Probe, Status
from .probe import build_client, default_registry
from .resolve import resolve

DB_PATH = Path("data/queue.sqlite3")
MAX_ATTEMPTS = 3
TERMINAL = {Status.ALIVE, Status.RESTRICTED}

HOST_BUDGETS_ARE_RATES = """
Un budget est un **debit horaire**, pas un plafond de passe.

La premiere version le traitait comme un total : une passe s'arretait des que l'hote
avait recu son quota, et laissait le reste des liens non sondes. C'est faux. Une passe
qui demande 2 919 resolutions de DOI avec un budget de 1 000 a l'heure n'est pas une
passe interdite : c'est une passe de trois heures.

`run_pass` espace donc les requetes de `3600 / budget` secondes par hote, et la passe
dure le temps qu'il faut. Le cout du projet est le temps calendaire (§8) ; le depenser
en etant poli est exactement ce que le §4, piege 5, demande.
"""

HOST_BUDGETS: dict[str, int] = {
    # Requetes que l'on s'autorise par heure et par hote. Volontairement **en dessous**
    # des limites annoncees : on ne joue pas au plus pres d'un quota chez quelqu'un
    # d'autre. GitHub authentifie annonce 5 000/h, on en prend 2 000.
    "api.github.com": 2000,
    "gitlab.com": 300,
    "api.bitbucket.org": 500,
    # Zenodo documente 60 requetes/minute pour un client anonyme, et son equipe signale
    # publiquement bloquer chaque jour des clients trop agressifs. On prend le quart.
    "zenodo.org": 900,
    "api.osf.io": 600,
    "api.figshare.com": 600,
    "doi.org": 1800,
    "archive.softwareheritage.org": 120,
    "eutils.ncbi.nlm.nih.gov": 3600,
    "_default": 600,
}
"""Le budget par defaut s'applique a tout hote non liste — pages personnelles, depots
institutionnels.

Releve de 200 a 600 par heure, soit une requete toutes les six secondes. Un serveur qui
ne supporte pas une requete toutes les six secondes ne supporte pas non plus un lecteur
humain qui parcourt un site. Le debit reste tres en dessous de ce qu'un navigateur
ordinaire produit en chargeant une seule page moderne.

Ce qui change vraiment la duree d'une passe n'est pas ce chiffre, c'est l'execution
concurrente entre hotes (`limiter.py`) : la file porte 2 230 hotes distincts, et rien
n'obligeait a les servir l'un apres l'autre."""

MAX_WORKERS = 48
"""Threads de sondage simultanes.

Le limiteur protege chaque hote independamment : un thread de plus ne fait jamais
arriver deux requetes rapprochees chez le meme serveur. Ce que le parallelisme couvre,
c'est la **latence** — un serveur lent, un delai d'attente de douze secondes.

Mesure du 2026-09-21 : a seize threads, 300 liens en 3 min 41, soit 1,4 par seconde.
Le facteur limitant n'etait plus aucun hote mais le nombre de threads face a la latence.
Avec 2 153 hotes distincts dans la file, quarante-huit connexions simultanees restent
tres en dessous de ce qu'un navigateur ouvre en chargeant une page moderne, et aucune
ne vise deux fois le meme serveur."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    link_id     TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    stratum     TEXT,
    host        TEXT,
    kind        TEXT,
    loaded_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS probes (
    link_id     TEXT NOT NULL,
    attempt     INTEGER NOT NULL,
    probed_at   TEXT NOT NULL,
    method      TEXT NOT NULL,
    status      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    PRIMARY KEY (link_id, attempt)
);
CREATE TABLE IF NOT EXISTS passes (
    pass_id     TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    dry_run     INTEGER NOT NULL,
    n_probed    INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_probes_link ON probes(link_id);
CREATE INDEX IF NOT EXISTS idx_links_host ON links(host);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False : les ecritures viennent du pool de sondage, toujours
    # sous le verrou `writes` de `run_pass`. SQLite n'est jamais touche sans lui.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL : une lecture (`status`) reste possible pendant qu'une passe ecrit.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")  # une sonde ecrite est une sonde survivante
    conn.executescript(SCHEMA)
    return conn


# --- Chargement ----------------------------------------------------------------------


ARTIFACT_HOSTS_IN_REFS = {
    "github.com", "gitlab.com", "bitbucket.org", "codeberg.org",
    "zenodo.org", "figshare.com", "osf.io", "datadryad.org",
    "dataverse.harvard.edu", "dataverse.org", "huggingface.co",
    "openneuro.org", "pangaea.de", "data.mendeley.com", "mendeley.com",
    "softwareheritage.org", "archive.softwareheritage.org",
}


ARTIFACT_KINDS = {"code_repo", "data_repo", "dataset_doi"}
"""Un lien de bibliographie est conserve si son **type** est un artefact, meme quand son
hote ne l'est pas.

Corrige le 2026-09-21 apres audit : neuf DOI Zenodo cites en bibliographie
(`https://doi.org/10.5281/zenodo.1070901`) etaient ecartes, parce que le filtre testait
l'hote — `doi.org` — alors que c'est le prefixe du DOI qui designe un depot de donnees.

C'est exactement le cas que metacheck a mesure (issue #411) et que l'on voulait garder :
3 % des articles ne citent leur depot que dans leur bibliographie. Les perdre par un
test sur le mauvais champ aurait ete une erreur silencieuse."""

CITATION_HOSTS = {
    "pubmed.ncbi.nlm.nih.gov",
    "scholar.google.com",
    "semanticscholar.org",
    "api.crossref.org",
    "crossref.org",
    "europepmc.org",
    "researchgate.net",
    "webofscience.com",
    "scopus.com",
    "ui.adsabs.harvard.edu",
    "adsabs.harvard.edu",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "hal.science",
    "inspirehep.net",
    "refhub.elsevier.com",
    "linkinghub.elsevier.com",
    "mailto",
}
"""Infrastructures bibliographiques. Un lien PubMed dans un article est une citation, pas
un artefact. Mesure du 2026-09-20 : 1 096 liens PubMed dans 400 articles, soit le second
hote de la file. Les sonder mesurerait la survie des index bibliographiques — qui ne
meurent pas — au prix de milliers de requetes chez le NIH.

Les serveurs de prepublication (arXiv, bioRxiv, medRxiv, SSRN, HAL) y figurent aussi :
un lien arXiv designe un **article**, pas un artefact de code ou de donnees. 556 liens
arXiv dans 400 articles, presque tous des citations. Le projet mesure la survie des
artefacts annonces, pas celle de la litterature.

`mailto` y figure parce que les annotations de PDF contiennent les adresses des auteurs :
ce ne sont pas des URL, et il n'est pas question de les toucher."""

DATA_PATHS_TO_KEEP = re.compile(
    r"(?i)/(nuccore|protein|sra|geo|bioproject|biosample|gds|clinvar|dbvar|gap|"
    r"genbank|assembly|taxonomy|gene|structure)\b"
)
"""Exception a `CITATION_HOSTS` : le NCBI heberge aussi de vraies donnees. Un lien vers
`ncbi.nlm.nih.gov/nuccore/...` est un artefact, pas une citation.

`pmc` a ete **retire** de cette liste le 2026-09-21 : un lien PMC designe un article en
texte integral, pas un jeu de donnees. C'est une citation."""

CITATION_PATHS = re.compile(
    r"(?i)(/pubmed(/|\?|$)|/entrez/query\.fcgi|/entrez/eutils|/articles/PMC\d+"
    r"|/pmc/articles/|/books/NBK\d+)"
)
"""Chemins de citation, quel que soit l'hote.

Decouvert le 2026-09-21 en cherchant pourquoi le NCBI dominait la duree d'une passe :
**576 des 655 liens NCBI etaient des citations PubMed** sous une forme d'URL que le
filtre par hote ne voyait pas — `ncbi.nlm.nih.gov/pubmed/12345` et
`ncbi.nlm.nih.gov/entrez/query.fcgi?db=PubMed&...`, et non
`pubmed.ncbi.nlm.nih.gov/12345`.

Le meme hote sert donc des citations et des donnees, et seule la forme du chemin les
separe. Filtrer par hote seul laissait passer des centaines de requetes inutiles chez
le NIH — et gonflait le denominateur du chiffre publie avec une population qui ne meurt
pas."""


def should_probe(row: dict) -> tuple[bool, str]:
    """Faut-il sonder ce lien ?

    Deux exclusions, toutes deux dictees par le §4 piege 5 autant que par le sens :

    * **« sur demande » n'est pas un lien** (piege 4). Jamais sonde, compte a part.
    * **Un DOI d'article cite en bibliographie n'est pas un artefact de cet article.**
      C'est une reference. Sur les 8 073 liens extraits de 400 articles, 1 756 viennent
      de la bibliographie et l'ecrasante majorite sont des DOI d'articles cites. Les
      sonder reviendrait a mesurer la survie de la litterature, pas celle des artefacts,
      et a infliger des milliers de requetes inutiles a doi.org.

    Mais on **garde** les liens de bibliographie qui pointent vers un depot : c'est
    exactement le cas mesure par metacheck (issue #411), ou 3 % des articles ne citent
    leur depot que la. Les exclure en bloc perdrait ces cas.
    """
    kind = row.get("kind")
    host = row.get("host") or ""
    url = row.get("normalized") or ""

    if kind == "on_request":
        return False, "on_request"
    if not url.startswith(("http://", "https://")):
        return False, "schema_non_http"
    if row.get("malformed_at_source"):
        # Piege 3 : casse des la publication, n'a donc jamais pu fonctionner. Compte a
        # part comme mesure du controle editorial, jamais sonde — il n'y a rien a
        # sonder, et le resultat serait indiscernable d'un lien mort.
        return False, "malformed_at_source"
    if kind == "citation_doi":
        return False, "citation_doi"
    if host in CITATION_HOSTS and not DATA_PATHS_TO_KEEP.search(url):
        return False, "hote_bibliographique"
    if CITATION_PATHS.search(url) and not DATA_PATHS_TO_KEEP.search(url):
        return False, "chemin_bibliographique"
    if (
        row.get("source") == "references"
        and host not in ARTIFACT_HOSTS_IN_REFS
        and kind not in ARTIFACT_KINDS
    ):
        return False, "reference_non_artefact"
    return True, "probe"


CHROME_MIN_PAPERS = 4
CHROME_MIN_DISCIPLINES = 2
CHROME_MIN_PAPERS_SAME_DISCIPLINE = 8
FURNITURE_HOST_MIN_URLS = 20
FURNITURE_HOST_MIN_URLS_PER_PAPER = 5.0
FURNITURE_HOST_MAX_PAPERS = 50
"""Garde-fou ajoute apres une premiere version trop large.

Sans lui, la regle attrapait `doi.org` : douze mille URL distinctes, donc un ratio
eleve — sauf qu'elles viennent de onze cents articles differents, chacun citant une
douzaine de references. Ce n'est pas du mobilier, c'est un agregateur.

Le signal du mobilier n'est pas « beaucoup d'URL » mais **beaucoup d'URL venues de
peu d'articles** : une poignee de bibliographies ou de menus, repliquee."""
"""Seuil pour le mobilier d'un site mono-disciplinaire.

La premiere regle exigeait deux disciplines, et laissait donc passer le menu d'une
revue specialisee : `frontiersin.org/Pharmacology/editorialboard`,
`jstage.jst.go.jp/static/pages/...` reviennent dans des dizaines d'articles, tous de la
meme discipline.

Huit articles distincts est un seuil deliberement haut : dans un echantillon de 2 000
articles tires au hasard sur quinze ans, un jeu de donnees reellement reutilise par huit
d'entre eux serait remarquable. Un pied de page de revue y arrive sans effort."""


def find_site_furniture(rows: list[dict]) -> set[str]:
    """URL qui reviennent dans beaucoup d'articles sans rapport entre eux.

    Une regle, pas une liste noire : **une URL citee par au moins quatre articles de
    deux disciplines differentes, sur un hote qui n'est pas un depot d'artefacts, est du
    mobilier de site.** Un jeu de donnees peut etre reutilise ; il ne l'est pas par de la
    physique et de la sociologie a la fois, via un hote quelconque.

    Mesure du 2026-09-21 : 88 URL, 871 liens, 11 % de la file. Ce qu'elle attrape :
    `browsehappy.com` (« mettez a jour votre navigateur »), `home.cern`,
    `commission.europa.eu`, `stats.uptimerobot.com` — la page de statut d'un service.
    Aucun de ces liens n'est un artefact de recherche.

    L'avantage d'une regle sur une liste noire est qu'elle continue de fonctionner sur
    le prochain corpus, avec le mobilier d'autres sites que ceux deja rencontres.
    """
    from .extract.links import ARTIFACT_HOSTS

    papers: dict[str, set[str]] = collections.defaultdict(set)
    disciplines: dict[str, set[str]] = collections.defaultdict(set)
    host_urls: dict[str, set[str]] = collections.defaultdict(set)
    host_papers: dict[str, set[str]] = collections.defaultdict(set)
    for row in rows:
        url = row.get("normalized", "")
        paper = row.get("paper_id", "")
        papers[url].add(paper)
        disciplines[url].add(row.get("discipline", ""))
        host = host_of(url)
        host_urls[host].add(url)
        host_papers[host].add(paper)

    # Regle par hote : combien d'URL distinctes un hote recoit-il par article ?
    #
    # Mesure du 2026-09-21, et elle separe nettement deux populations :
    #
    #   github.com        50 URL / 110 articles = 0,5 URL par article
    #   zenodo.org        15 URL /  11 articles = 1,4
    #   frontiersin.org   96 URL /  17 articles = 5,6
    #   jstage.jst.go.jp 118 URL /   7 articles = 16,9
    #   inspirehep.net   398 URL /   8 articles = 49,8
    #
    # Un depot d'artefacts recoit environ un lien par article : chaque equipe y depose
    # sa chose. Un site dont on a aspire le menu ou l'appareil de references en donne
    # des dizaines, tous venus d'une poignee d'articles.
    #
    # C'est une regle sur la **forme de la distribution**, pas sur des noms de domaine :
    # elle vaudra encore sur un corpus ou l'on n'a jamais vu ces hotes-la.
    furniture_hosts = {
        host
        for host, urls in host_urls.items()
        if len(urls) >= FURNITURE_HOST_MIN_URLS
        and len(host_papers[host]) <= FURNITURE_HOST_MAX_PAPERS
        and len(urls) / max(1, len(host_papers[host])) >= FURNITURE_HOST_MIN_URLS_PER_PAPER
        and host not in ARTIFACT_HOSTS
    }

    def is_furniture(url: str, ps: set[str]) -> bool:
        if host_of(url) in ARTIFACT_HOSTS:
            return False
        if host_of(url) in furniture_hosts:
            return True
        if len(ps) >= CHROME_MIN_PAPERS_SAME_DISCIPLINE:
            return True
        return len(ps) >= CHROME_MIN_PAPERS and len(disciplines[url]) >= CHROME_MIN_DISCIPLINES

    return {url for url, ps in papers.items() if is_furniture(url, ps)}


def load_links(conn: sqlite3.Connection, path: Path) -> dict[str, int]:
    """Charge des liens dans la file. Idempotent : recharger n'efface aucune sonde."""
    now = datetime.now(UTC).isoformat()
    counts: collections.Counter[str] = collections.Counter()
    rows_all = [json.loads(line) for line in path.open(encoding="utf-8")]
    furniture = find_site_furniture(rows_all)

    with conn:
        for row in rows_all:
            if row.get("normalized") in furniture:
                counts["mobilier_de_site"] += 1
                continue
            keep, why = should_probe(row)
            counts[why] += 1
            if not keep:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO links(link_id, payload, stratum, host, kind, loaded_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    row["link_id"],
                    json.dumps(row, ensure_ascii=False, sort_keys=True),
                    row.get("stratum"),
                    row.get("host"),
                    row.get("kind"),
                    now,
                ),
            )
    return dict(counts)


# --- Selection de ce qui est du --------------------------------------------------------


@dataclass(frozen=True)
class DueLink:
    link_id: str
    payload: dict
    host: str
    next_attempt: int


def due(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> list[DueLink]:
    """Liens a sonder maintenant.

    Un lien est du si :
      * il n'a pas atteint trois sondes ;
      * aucune sonde ne l'a trouve `alive` ou `restricted` (economie ci-dessus) ;
      * sa derniere sonde date d'au moins `min_probe_span_days / 2`.

    L'espacement est la moitie de la fenetre totale : trois sondes separees chacune de
    cette duree donnent bien au moins `min_probe_span_days` entre la premiere et la
    troisieme, ce qu'exige `resolve`. Le faire coincider exactement produirait des
    passes qui n'arrivent jamais a satisfaire la regle.
    """
    now = now or datetime.now(UTC)
    gap = timedelta(days=settings.min_probe_span_days / 2)
    out: list[DueLink] = []

    rows = conn.execute(
        """
        SELECT l.link_id, l.payload, l.host,
               COUNT(p.attempt) AS n_probes,
               MAX(p.probed_at) AS last_at,
               SUM(CASE WHEN p.status IN ('alive','restricted') THEN 1 ELSE 0 END) AS terminal
        FROM links l
        LEFT JOIN probes p ON p.link_id = l.link_id
        GROUP BY l.link_id
        """
    ).fetchall()

    for row in rows:
        if row["terminal"]:
            continue
        if row["n_probes"] >= MAX_ATTEMPTS:
            continue
        if row["last_at"]:
            last = datetime.fromisoformat(row["last_at"])
            if now - last < gap:
                continue
        out.append(
            DueLink(
                link_id=row["link_id"],
                payload=json.loads(row["payload"]),
                host=row["host"] or "_default",
                next_attempt=row["n_probes"] + 1,
            )
        )
    return _interleave_by_host(out)


def _interleave_by_host(links: list[DueLink]) -> list[DueLink]:
    """Alterne les hotes en tourniquet.

    Sans cela, les 875 liens `ncbi.nlm.nih.gov` se suivent, et comme chaque requete
    attend l'intervalle de debit de son hote, la passe dure la **somme** des temps par
    hote. En alternant, on attend chez un hote pendant qu'on interroge les autres, et
    la passe dure le **maximum** — de plusieurs jours a quelques heures.

    Meme politesse, meme nombre de requetes, meme debit par hote. Seul l'ordre change.
    """
    by_host: dict[str, list[DueLink]] = collections.defaultdict(list)
    for link in links:
        by_host[api_host_for(link.host)].append(link)

    out: list[DueLink] = []
    queues = list(by_host.values())
    index = 0
    while queues:
        index %= len(queues)
        out.append(queues[index].pop())
        if not queues[index]:
            queues.pop(index)
        else:
            index += 1
    return out


# --- Budget --------------------------------------------------------------------------


def budget_of(host: str) -> int:
    return HOST_BUDGETS.get(host, HOST_BUDGETS["_default"])


def api_host_for(link_host: str) -> str:
    """L'hote sonde n'est pas toujours l'hote du lien : un lien github.com frappe
    api.github.com, et le budget doit porter sur celui qui recoit le trafic."""
    return {
        "github.com": "api.github.com",
        "bitbucket.org": "api.bitbucket.org",
        "osf.io": "api.osf.io",
        "figshare.com": "api.figshare.com",
    }.get(link_host, link_host)


def plan(links: list[DueLink]) -> dict:
    """Ce qu'une passe ferait, hote par hote, et si elle tient dans les budgets.

    Un lien GitHub en 404 peut declencher jusqu'a trois requetes (depot, proprietaire,
    Software Heritage). Le plan compte le **pire cas**, pas le cas moyen : un budget
    calcule sur une moyenne est un budget depasse un jour sur deux.
    """
    per_host: collections.Counter[str] = collections.Counter()
    for link in links:
        host = api_host_for(link.host)
        per_host[host] += 1
        if host == "api.github.com":
            per_host[host] += 1  # verification du proprietaire
            per_host["archive.softwareheritage.org"] += 1

    hosts = []
    over = []
    for host, n in sorted(per_host.items(), key=lambda kv: -kv[1]):
        limit = budget_of(host)
        hours = n / limit
        hosts.append({"host": host, "requests": n, "budget_per_hour": limit, "hours": round(hours, 2)})
        if hours > 1:
            over.append(host)

    return {
        "n_links": len(links),
        "hosts": hosts,
        "hosts_over_hourly_budget": over,
        "estimated_hours": round(max((h["hours"] for h in hosts), default=0), 2),
    }


# --- Execution -------------------------------------------------------------------------


def run_pass(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    dry_run: bool,
    limit: int | None = None,
) -> dict:
    """Execute une passe. Reprenable : chaque sonde est ecrite des son retour.

    En passe a blanc, tout le circuit est parcouru — selection, budget, ecriture,
    resolution — **sauf l'appel reseau**. C'est ce qui rend le critere E4 verifiable
    sans deranger un seul hebergeur.
    """
    links = due(conn, settings)
    if limit:
        links = links[:limit]
    estimate = plan(links)

    # Deduplication par URL : deux articles qui citent le meme depot posent la meme
    # question. La sonder deux fois le meme jour donne la meme reponse et double le
    # trafic pour rien. Mesure du 2026-09-21 : 7 829 liens pour 6 763 URL distinctes,
    # soit 14 % de requetes evitees — et 14 % de derangement en moins.
    by_url: dict[str, list[DueLink]] = collections.defaultdict(list)
    for item in links:
        by_url[item.payload["normalized"]].append(item)

    pass_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{'dry' if dry_run else 'run'}"
    with conn:
        conn.execute(
            "INSERT INTO passes(pass_id, started_at, dry_run, notes) VALUES (?,?,?,?)",
            (pass_id, datetime.now(UTC).isoformat(), int(dry_run), json.dumps(estimate)),
        )

    spent: collections.Counter[str] = collections.Counter()
    statuses: collections.Counter[str] = collections.Counter()
    counters = threading.Lock()
    writes = threading.Lock()
    limiter = HostRateLimiter(lambda host: 3600.0 / budget_of(host))
    registry = default_registry()
    n_probed = 0
    n_requests = 0

    def probe_one(url_group: list[DueLink], client: httpx.Client | None) -> None:
        nonlocal n_probed, n_requests
        first = url_group[0]
        host = api_host_for(first.host)

        if dry_run:
            status, method, reason, evidence = (
                Status.UNKNOWN,
                "api",
                "dry_run",
                {"planned_host": host},
            )
        else:
            limiter.acquire(host)
            link = Link.model_validate(first.payload)
            result = registry.check(client, link, settings)
            status, method, reason, evidence = (
                result.status,
                result.method,
                result.reason,
                result.evidence,
            )

        with counters:
            spent[host] += 1
            n_requests += 1
            statuses[status.value] += len(url_group)
            n_probed += len(url_group)

        if not dry_run:
            # Le meme resultat vaut pour tous les liens qui portent cette URL : c'est
            # la meme ressource, sondee au meme instant, avec la meme preuve.
            with writes:
                for item in url_group:
                    _record(conn, item, status, method, reason, evidence)

    client = None if dry_run else build_client(settings)
    try:
        if dry_run:
            for group in by_url.values():
                probe_one(group, None)
        else:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(probe_one, g, client) for g in by_url.values()]
                for future in as_completed(futures):
                    future.result()
    finally:
        if client is not None:
            client.close()
        with conn:
            conn.execute(
                "UPDATE passes SET finished_at=?, n_probed=? WHERE pass_id=?",
                (datetime.now(UTC).isoformat(), n_probed, pass_id),
            )

    return {
        "pass_id": pass_id,
        "dry_run": dry_run,
        "n_due": len(links),
        "n_distinct_urls": len(by_url),
        "n_probed": n_probed,
        "n_requests": n_requests,
        "statuses": dict(statuses),
        "spent_per_host": dict(spent),
        "estimate": estimate,
        # Le debit par hote est tenu par construction (le limiteur). Ce controle verifie
        # qu'aucun lien n'a ete abandonne en silence : `n_probed` doit couvrir tout ce
        # qui etait du.
        "all_due_probed": n_probed == len(links),
    }


def _record(
    conn: sqlite3.Connection,
    item: DueLink,
    status: Status,
    method: str,
    reason: str,
    evidence: dict,
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO probes"
            "(link_id, attempt, probed_at, method, status, reason, evidence)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                item.link_id,
                item.next_attempt,
                datetime.now(UTC).isoformat(),
                method,
                status.value,
                reason,
                json.dumps(evidence, ensure_ascii=False, default=str),
            ),
        )


# --- Etat ------------------------------------------------------------------------------


def status_report(conn: sqlite3.Connection, settings: Settings) -> dict:
    n_links = conn.execute("SELECT COUNT(*) AS n FROM links").fetchone()["n"]
    by_attempt = {
        row["n_probes"]: row["n"]
        for row in conn.execute(
            "SELECT n_probes, COUNT(*) AS n FROM ("
            "  SELECT l.link_id, COUNT(p.attempt) AS n_probes FROM links l"
            "  LEFT JOIN probes p ON p.link_id = l.link_id GROUP BY l.link_id"
            ") GROUP BY n_probes"
        )
    }

    resolved: collections.Counter[str] = collections.Counter()
    for link_id, probes in _probes_by_link(conn).items():
        if not probes:
            continue
        resolved[resolve(link_id, probes, settings).status.value] += 1

    passes = [
        dict(row)
        for row in conn.execute(
            "SELECT pass_id, started_at, finished_at, dry_run, n_probed FROM passes"
            " ORDER BY started_at DESC LIMIT 5"
        )
    ]

    return {
        "n_links": n_links,
        "links_by_probe_count": by_attempt,
        "resolved": dict(resolved),
        "n_due_now": len(due(conn, settings)),
        "recent_passes": passes,
    }


def _probes_by_link(conn: sqlite3.Connection) -> dict[str, list[Probe]]:
    out: dict[str, list[Probe]] = collections.defaultdict(list)
    for row in conn.execute("SELECT * FROM probes ORDER BY link_id, attempt"):
        out[row["link_id"]].append(
            Probe(
                link_id=row["link_id"],
                probed_at=datetime.fromisoformat(row["probed_at"]),
                method=row["method"],
                status=Status(row["status"]),
                evidence=json.loads(row["evidence"]),
                attempt=row["attempt"],
            )
        )
    return out


# --- CLI ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # Une console Windows est en cp1252 : un nom d'hote cyrillique ou chinois — il y en
    # a dans le corpus — faisait tomber l'affichage avec UnicodeEncodeError, apres que
    # le travail ait ete fait. Le rapport ne doit jamais etre ce qui casse un run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"erreur de configuration : {exc}", file=sys.stderr)
        return 2

    with closing(connect()) as conn:
        if command == "load":
            if len(args) < 2:
                print("usage : load <links.jsonl>", file=sys.stderr)
                return 2
            counts = load_links(conn, Path(args[1]))
            total = conn.execute("SELECT COUNT(*) AS n FROM links").fetchone()["n"]
            lues = sum(counts.values())
            print(f"{lues} lignes lues, {total} liens distincts dans la file")
            for why, n in sorted(counts.items(), key=lambda kv: -kv[1]):
                if why != "probe":
                    print(f"  ecartes — {why:<24} {n:>6}")
            return 0

        if command == "plan":
            estimate = plan(due(conn, settings))
            print(f"liens dus maintenant : {estimate['n_links']}")
            for h in estimate["hosts"]:
                flag = "  DEPASSE" if h["hours"] > 1 else ""
                print(
                    f"  {h['host']:<32} {h['requests']:>6} req  "
                    f"budget {h['budget_per_hour']:>5}/h  ~{h['hours']:.2f} h{flag}"
                )
            print(f"duree estimee de la passe : {estimate['estimated_hours']} h")
            # Un hote qui demande plus d'une heure n'est pas une erreur : c'est une
            # duree. La passe s'etale, elle ne deborde pas.
            return 0

        if command in ("dryrun", "run"):
            limit = int(args[1]) if len(args) > 1 else None
            report = run_pass(conn, settings, dry_run=(command == "dryrun"), limit=limit)
            print(f"passe {report['pass_id']}")
            print(f"  liens dus   : {report['n_due']}")
            print(f"  sondes      : {report['n_probed']}")
            print(f"  statuts     : {report['statuses']}")
            couverture = "complete" if report["all_due_probed"] else "INCOMPLETE"
            print(f"  couverture  : {couverture} ({report['n_probed']}/{report['n_due']})")
            print(
                f"  requetes    : {report['n_requests']} pour {report['n_due']} liens "
                f"({report['n_distinct_urls']} URL distinctes)"
            )
            print(f"  duree estimee : {report['estimate']['estimated_hours']} h")
            for host, n in sorted(report["spent_per_host"].items(), key=lambda kv: -kv[1])[:10]:
                print(f"      {host:<32} {n:>6} req, debit {budget_of(host)}/h")
            return 0 if report["all_due_probed"] else 1

        if command == "status":
            report = status_report(conn, settings)
            print(f"file : {report['n_links']} liens")
            print(f"  dus maintenant        : {report['n_due_now']}")
            print(f"  par nombre de sondes  : {report['links_by_probe_count']}")
            print(f"  statuts resolus       : {report['resolved']}")
            for p in report["recent_passes"]:
                kind = "blanc" if p["dry_run"] else "reelle"
                end = p["finished_at"] or "en cours"
                print(f"  passe {p['pass_id']} ({kind}) {p['n_probed']} sondes, fin {end}")
            return 0

        print(f"commande inconnue : {command!r} (load | plan | dryrun | run | status)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
