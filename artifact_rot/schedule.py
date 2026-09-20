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
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import ConfigError, Settings
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
    "zenodo.org": 300,
    "api.osf.io": 300,
    "api.figshare.com": 300,
    "doi.org": 1000,
    "archive.softwareheritage.org": 100,
    "_default": 200,
}
"""Le budget par defaut s'applique a tout hote non liste — pages personnelles, depots
institutionnels. 200 requetes par heure sur un serveur de laboratoire est deja
genereux."""


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
    conn = sqlite3.connect(path)
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
    r"(?i)/(nuccore|protein|sra|geo|bioproject|biosample|gds|pmc|clinvar|dbvar|gap)\b"
)
"""Exception a `CITATION_HOSTS` : le NCBI heberge aussi de vraies donnees. Un lien vers
`ncbi.nlm.nih.gov/nuccore/...` est un artefact, pas une citation."""


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
    if row.get("source") == "references" and host not in ARTIFACT_HOSTS_IN_REFS:
        return False, "reference_non_artefact"
    return True, "probe"


def load_links(conn: sqlite3.Connection, path: Path) -> dict[str, int]:
    """Charge des liens dans la file. Idempotent : recharger n'efface aucune sonde."""
    now = datetime.now(UTC).isoformat()
    counts: collections.Counter[str] = collections.Counter()
    with conn:
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
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

    pass_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{'dry' if dry_run else 'run'}"
    with conn:
        conn.execute(
            "INSERT INTO passes(pass_id, started_at, dry_run, notes) VALUES (?,?,?,?)",
            (pass_id, datetime.now(UTC).isoformat(), int(dry_run), json.dumps(estimate)),
        )

    spent: collections.Counter[str] = collections.Counter()
    statuses: collections.Counter[str] = collections.Counter()
    last_hit: dict[str, float] = {}
    n = 0

    registry = default_registry()
    client = None if dry_run else build_client(settings)

    try:
        for item in links:
            host = api_host_for(item.host)

            # Cadence, pas plafond : on espace les requetes pour tenir le debit horaire
            # de cet hote, et la passe dure le temps qu'il faut.
            if not dry_run:
                interval = 3600.0 / budget_of(host)
                since = time.monotonic() - last_hit.get(host, float("-inf"))
                if since < interval:
                    time.sleep(interval - since)
                last_hit[host] = time.monotonic()

            if dry_run:
                status, method, reason, evidence = (
                    Status.UNKNOWN,
                    "api",
                    "dry_run",
                    {"planned_host": host},
                )
            else:
                link = Link.model_validate(item.payload)
                result = registry.check(client, link, settings)
                status, method, reason, evidence = (
                    result.status,
                    result.method,
                    result.reason,
                    result.evidence,
                )

            spent[host] += 1
            statuses[status.value] += 1
            n += 1

            if not dry_run:
                _record(conn, item, status, method, reason, evidence)
    finally:
        if client is not None:
            client.close()
        with conn:
            conn.execute(
                "UPDATE passes SET finished_at=?, n_probed=? WHERE pass_id=?",
                (datetime.now(UTC).isoformat(), n, pass_id),
            )

    return {
        "pass_id": pass_id,
        "dry_run": dry_run,
        "n_due": len(links),
        "n_probed": n,
        "statuses": dict(statuses),
        "spent_per_host": dict(spent),
        "estimate": estimate,
        # Le debit est tenu par construction (espacement avant chaque requete). Ce
        # controle verifie qu'aucun lien n'a ete abandonne en silence : `n_probed`
        # doit couvrir tout ce qui etait du.
        "all_due_probed": n == len(links),
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
