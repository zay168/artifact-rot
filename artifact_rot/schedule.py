"""E4 — scheduler for the three passes, persistent queue, resumption.

Pass criterion (PLAN.md §7): **a complete dry run without exceeding quotas.**

The project's cost is not computation, it is **calendar time** (§8). Three probes at
least ten days apart impose two weeks between the first and the last. That is not work,
it is waiting — and it is free if anticipated, costly if discovered at the end.

The scheduler must therefore survive anything: a network cut, a restart, a laptop closed
for twelve days. Hence a **SQLite** queue, not a file held in memory: each probe is
written as soon as it returns, and resuming means running the same command again.

### A deliberate saving: we stop probing a live link

The resolution rule (§5) says a single live observation wins. Probing a link already
seen alive twice more adds nothing to its status, and accounts for most of the traffic.
We therefore stop as soon as a link is `alive` or `restricted`.

Three consequences, all accepted:

* traffic imposed on hosts drops by about 80% — which is §4, pitfall 5;
* a link that dies between pass 1 and pass 3 is counted alive. The measurement is
  therefore **conservative**: it underestimates mortality, never the reverse;
* all three probes remain mandatory to declare a link dead, without exception.

Usage:
    python -m artifact_rot.schedule load runs/<...>/links.jsonl
    python -m artifact_rot.schedule plan          # what the next pass would do
    python -m artifact_rot.schedule dryrun        # dry run, no network
    python -m artifact_rot.schedule run           # real pass
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
A budget is an **hourly rate**, not a per-pass ceiling.

The first version treated it as a total: a pass stopped as soon as the host had received
its quota, and left the remaining links unprobed. That is wrong. A pass that needs 2,919
DOI resolutions with a budget of 1,000 per hour is not a forbidden pass: it is a
three-hour pass.

`run_pass` therefore spaces requests by `3600 / budget` seconds per host, and the pass
lasts as long as it takes. The project's cost is calendar time (§8); spending it on
being polite is exactly what §4, pitfall 5, asks for.
"""

HOST_BUDGETS: dict[str, int] = {
    # Requests we allow ourselves per hour and per host. Deliberately **below** the
    # announced limits: we do not play close to someone else's quota. Authenticated
    # GitHub announces 5,000/h; we take 2,000.
    "api.github.com": 2000,
    "gitlab.com": 300,
    "api.bitbucket.org": 500,
    # Zenodo documents 60 requests/minute for an anonymous client, and its team publicly
    # reports blocking overly aggressive clients every day. We take a quarter of that.
    "zenodo.org": 900,
    "api.osf.io": 600,
    "api.figshare.com": 600,
    "doi.org": 1800,
    "archive.softwareheritage.org": 120,
    "eutils.ncbi.nlm.nih.gov": 3600,
    "_default": 600,
}
"""The default budget applies to any unlisted host — personal pages, institutional
repositories.

Raised from 200 to 600 per hour, i.e. one request every six seconds. A server that cannot
take one request every six seconds cannot take a human reader browsing a site either. The
rate remains far below what an ordinary browser produces loading a single modern page.

What really changes a pass's duration is not this figure, it is concurrent execution
across hosts (`limiter.py`): the queue holds 2,230 distinct hosts, and nothing required
serving them one after another."""

MAX_WORKERS = 48
"""Simultaneous probing threads.

The limiter protects each host independently: an extra thread never makes two close
requests reach the same server. What parallelism covers is **latency** — a slow server, a
twelve-second timeout.

Measured on 2026-09-21: with sixteen threads, 300 links in 3 min 41 s, i.e. 1.4 per
second. The limiting factor was no longer any host but the number of threads against
latency. With 2,153 distinct hosts in the queue, forty-eight simultaneous connections stay
far below what a browser opens loading a modern page, and none targets the same server
twice."""


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
    # check_same_thread=False: writes come from the probing pool, always under the
    # `writes` lock of `run_pass`. SQLite is never touched without it.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL: a read (`status`) remains possible while a pass is writing.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")  # a written probe is a surviving probe
    conn.executescript(SCHEMA)
    return conn


# --- Loading ---------------------------------------------------------------------------


ARTIFACT_HOSTS_IN_REFS = {
    "github.com", "gitlab.com", "bitbucket.org", "codeberg.org",
    "zenodo.org", "figshare.com", "osf.io", "datadryad.org",
    "dataverse.harvard.edu", "dataverse.org", "huggingface.co",
    "openneuro.org", "pangaea.de", "data.mendeley.com", "mendeley.com",
    "softwareheritage.org", "archive.softwareheritage.org",
}


ARTIFACT_KINDS = {"code_repo", "data_repo", "dataset_doi"}
"""A bibliography link is kept if its **kind** is an artifact, even when its host is not.

Fixed on 2026-09-21 after an audit: nine Zenodo DOIs cited in bibliographies
(`https://doi.org/10.5281/zenodo.1070901`) were discarded, because the filter tested the
host — `doi.org` — whereas it is the DOI prefix that designates a data repository.

This is exactly the case metacheck measured (issue #411) and that we wanted to keep: 3%
of papers cite their repository only in their bibliography. Losing them through a test on
the wrong field would have been a silent error."""

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
"""Bibliographic infrastructure. A PubMed link in a paper is a citation, not an artifact.
Measured on 2026-09-20: 1,096 PubMed links in 400 papers, the second host in the queue.
Probing them would measure the survival of bibliographic indexes — which do not die — at
the cost of thousands of requests to the NIH.

Preprint servers (arXiv, bioRxiv, medRxiv, SSRN, HAL) are listed too: an arXiv link
designates a **paper**, not a code or data artifact. 556 arXiv links in 400 papers, almost
all citations. The project measures the survival of announced artifacts, not of the
literature.

`mailto` is listed because PDF annotations contain the authors' addresses: they are not
URLs, and touching them is out of the question."""

DATA_PATHS_TO_KEEP = re.compile(
    r"(?i)/(nuccore|protein|sra|geo|bioproject|biosample|gds|clinvar|dbvar|gap|"
    r"genbank|assembly|taxonomy|gene|structure)\b"
)
"""Exception to `CITATION_HOSTS`: NCBI also hosts real data. A link to
`ncbi.nlm.nih.gov/nuccore/...` is an artifact, not a citation.

`pmc` was **removed** from this list on 2026-09-21: a PMC link designates a full-text
paper, not a dataset. It is a citation."""

CITATION_PATHS = re.compile(
    r"(?i)(/pubmed(/|\?|$)|/entrez/query\.fcgi|/entrez/eutils|/articles/PMC\d+"
    r"|/pmc/articles/|/books/NBK\d+)"
)
"""Citation paths, whatever the host.

Discovered on 2026-09-21 while looking for why NCBI dominated a pass's duration: **576 of
the 655 NCBI links were PubMed citations** in a URL form the host filter did not see —
`ncbi.nlm.nih.gov/pubmed/12345` and `ncbi.nlm.nih.gov/entrez/query.fcgi?db=PubMed&...`,
rather than `pubmed.ncbi.nlm.nih.gov/12345`.

The same host therefore serves citations and data, and only the shape of the path tells
them apart. Filtering by host alone let through hundreds of useless requests to the NIH —
and inflated the denominator of the published figure with a population that does not
die."""


def should_probe(row: dict) -> tuple[bool, str]:
    """Should this link be probed?

    Two exclusions, both dictated by §4 pitfall 5 as much as by common sense:

    * **"on request" is not a link** (pitfall 4). Never probed, counted separately.
    * **A paper DOI cited in the bibliography is not an artifact of this paper.** It is a
      reference. Of the 8,073 links extracted from 400 papers, 1,756 come from the
      bibliography and the vast majority are DOIs of cited papers. Probing them would
      measure the survival of the literature, not of artifacts, and inflict thousands of
      useless requests on doi.org.

    But bibliography links pointing to a repository are **kept**: this is exactly the case
    measured by metacheck (issue #411), where 3% of papers cite their repository only
    there. Excluding them wholesale would lose those cases.
    """
    kind = row.get("kind")
    host = row.get("host") or ""
    url = row.get("normalized") or ""

    if kind == "on_request":
        return False, "on_request"
    if not url.startswith(("http://", "https://")):
        return False, "non_http_scheme"
    if row.get("malformed_at_source"):
        # Pitfall 3: broken from publication, so it could never have worked. Counted
        # separately as a measure of editorial control, never probed — there is nothing
        # to probe, and the result would be indistinguishable from a dead link.
        return False, "malformed_at_source"
    if kind == "citation_doi":
        return False, "citation_doi"
    if host in CITATION_HOSTS and not DATA_PATHS_TO_KEEP.search(url):
        return False, "citation_host"
    if CITATION_PATHS.search(url) and not DATA_PATHS_TO_KEEP.search(url):
        return False, "citation_path"
    if (
        row.get("source") == "references"
        and host not in ARTIFACT_HOSTS_IN_REFS
        and kind not in ARTIFACT_KINDS
    ):
        return False, "non_artifact_reference"
    return True, "probe"


CHROME_MIN_PAPERS = 4
CHROME_MIN_DISCIPLINES = 2
CHROME_MIN_PAPERS_SAME_DISCIPLINE = 8
"""Threshold for the furniture of a single-discipline site.

The first rule required two disciplines, and so let through the menu of a specialised
journal: `frontiersin.org/Pharmacology/editorialboard`, `jstage.jst.go.jp/static/pages/...`
recur in dozens of papers, all from the same discipline.

Eight distinct papers is a deliberately high threshold: in a sample of 2,000 papers drawn
at random over fifteen years, a dataset genuinely reused by eight of them would be
remarkable. A journal footer gets there effortlessly."""
FURNITURE_HOST_MIN_URLS = 20
FURNITURE_HOST_MIN_URLS_PER_PAPER = 5.0
FURNITURE_HOST_MAX_PAPERS = 50
"""Safeguard added after a first version that was too broad.

Without it, the rule caught `doi.org`: twelve thousand distinct URLs, hence a high ratio —
except they come from eleven hundred different papers, each citing a dozen references.
That is not furniture, it is an aggregator.

The furniture signal is not "many URLs" but **many URLs from few papers**: a handful of
bibliographies or menus, replicated."""


def find_site_furniture(rows: list[dict]) -> set[str]:
    """URLs that recur in many unrelated papers.

    A rule, not a blocklist: **a URL cited by at least four papers from two different
    disciplines, on a host that is not an artifact repository, is site furniture.** A
    dataset can be reused; it is not reused by physics and sociology at once, through an
    arbitrary host.

    Measured on 2026-09-21: 88 URLs, 871 links, 11% of the queue. What it catches:
    `browsehappy.com` ("please update your browser"), `home.cern`,
    `commission.europa.eu`, `stats.uptimerobot.com` — a service's status page. None of
    these links is a research artifact.

    The advantage of a rule over a blocklist is that it keeps working on the next corpus,
    with the furniture of sites other than those already encountered.
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

    # Per-host rule: how many distinct URLs does a host receive per paper?
    #
    # Measured on 2026-09-21, and it clearly separates two populations:
    #
    #   github.com        50 URLs / 110 papers = 0.5 URL per paper
    #   zenodo.org        15 URLs /  11 papers = 1.4
    #   frontiersin.org   96 URLs /  17 papers = 5.6
    #   jstage.jst.go.jp 118 URLs /   7 papers = 16.9
    #   inspirehep.net   398 URLs /   8 papers = 49.8
    #
    # An artifact repository receives about one link per paper: each team deposits its
    # thing there. A site whose menu or reference apparatus was scraped yields dozens,
    # all from a handful of papers.
    #
    # This is a rule on the **shape of the distribution**, not on domain names: it will
    # still hold on a corpus where these hosts were never seen.
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
    """Load links into the queue. Idempotent: reloading erases no probe."""
    now = datetime.now(UTC).isoformat()
    counts: collections.Counter[str] = collections.Counter()
    rows_all = [json.loads(line) for line in path.open(encoding="utf-8")]
    furniture = find_site_furniture(rows_all)

    with conn:
        for row in rows_all:
            if row.get("normalized") in furniture:
                counts["site_furniture"] += 1
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


# --- Selecting what is due ---------------------------------------------------------------


@dataclass(frozen=True)
class DueLink:
    link_id: str
    payload: dict
    host: str
    next_attempt: int


def due(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> list[DueLink]:
    """Links to probe now.

    A link is due if:
      * it has not reached three probes;
      * no probe has found it `alive` or `restricted` (saving described above);
      * its last probe is at least `min_probe_span_days / 2` old.

    The spacing is half the total window: three probes each separated by that duration
    give at least `min_probe_span_days` between the first and the third, as `resolve`
    requires. Making it coincide exactly would produce passes that never manage to
    satisfy the rule.
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
    """Alternate hosts round-robin.

    Without this, the 875 `ncbi.nlm.nih.gov` links follow one another, and since each
    request waits for its host's rate interval, the pass lasts the **sum** of per-host
    times. By alternating, we wait at one host while querying the others, and the pass
    lasts the **maximum** — from several days to a few hours.

    Same politeness, same number of requests, same per-host rate. Only the order changes.
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


# --- Budget ----------------------------------------------------------------------------


def budget_of(host: str) -> int:
    return HOST_BUDGETS.get(host, HOST_BUDGETS["_default"])


def api_host_for(link_host: str) -> str:
    """The probed host is not always the link's host: a github.com link hits
    api.github.com, and the budget must apply to whoever receives the traffic."""
    return {
        "github.com": "api.github.com",
        "bitbucket.org": "api.bitbucket.org",
        "osf.io": "api.osf.io",
        "figshare.com": "api.figshare.com",
    }.get(link_host, link_host)


def plan(links: list[DueLink]) -> dict:
    """What a pass would do, host by host, and whether it fits within the budgets.

    A GitHub link returning 404 can trigger up to three requests (repository, owner,
    Software Heritage). The plan counts the **worst case**, not the average case: a budget
    computed on an average is a budget exceeded one day out of two.
    """
    per_host: collections.Counter[str] = collections.Counter()
    for link in links:
        host = api_host_for(link.host)
        per_host[host] += 1
        if host == "api.github.com":
            per_host[host] += 1  # owner check
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


# --- Execution ---------------------------------------------------------------------------


def run_pass(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    dry_run: bool,
    limit: int | None = None,
) -> dict:
    """Run a pass. Resumable: each probe is written as soon as it returns.

    In a dry run, the whole circuit is traversed — selection, budget, writing,
    resolution — **except the network call**. That is what makes the E4 criterion
    checkable without disturbing a single host.
    """
    links = due(conn, settings)
    if limit:
        links = links[:limit]
    estimate = plan(links)

    # Deduplication by URL: two papers citing the same repository ask the same question.
    # Probing it twice on the same day gives the same answer and doubles the traffic for
    # nothing. Measured on 2026-09-21: 7,829 links for 6,763 distinct URLs, i.e. 14% of
    # requests avoided — and 14% less disturbance.
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
            # The same result holds for every link carrying this URL: it is the same
            # resource, probed at the same instant, with the same evidence.
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
        # The per-host rate is held by construction (the limiter). This check verifies
        # that no link was silently dropped: `n_probed` must cover everything that was due.
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


# --- Status ------------------------------------------------------------------------------


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


# --- CLI -----------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # A Windows console uses cp1252: a Cyrillic or Chinese host name — there are some in
    # the corpus — crashed the display with UnicodeEncodeError, after the work was done.
    # The report must never be what breaks a run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    with closing(connect()) as conn:
        if command == "load":
            if len(args) < 2:
                print("usage: load <links.jsonl>", file=sys.stderr)
                return 2
            counts = load_links(conn, Path(args[1]))
            total = conn.execute("SELECT COUNT(*) AS n FROM links").fetchone()["n"]
            n_read = sum(counts.values())
            print(f"{n_read} rows read, {total} distinct links in the queue")
            for why, n in sorted(counts.items(), key=lambda kv: -kv[1]):
                if why != "probe":
                    print(f"  discarded — {why:<24} {n:>6}")
            return 0

        if command == "plan":
            estimate = plan(due(conn, settings))
            print(f"links due now: {estimate['n_links']}")
            for h in estimate["hosts"]:
                flag = "  OVER" if h["hours"] > 1 else ""
                print(
                    f"  {h['host']:<32} {h['requests']:>6} req  "
                    f"budget {h['budget_per_hour']:>5}/h  ~{h['hours']:.2f} h{flag}"
                )
            print(f"estimated pass duration: {estimate['estimated_hours']} h")
            # A host needing more than an hour is not an error: it is a duration. The
            # pass spreads out, it does not overflow.
            return 0

        if command in ("dryrun", "run"):
            limit = int(args[1]) if len(args) > 1 else None
            report = run_pass(conn, settings, dry_run=(command == "dryrun"), limit=limit)
            print(f"pass {report['pass_id']}")
            print(f"  links due  : {report['n_due']}")
            print(f"  probed     : {report['n_probed']}")
            print(f"  statuses   : {report['statuses']}")
            coverage = "complete" if report["all_due_probed"] else "INCOMPLETE"
            print(f"  coverage   : {coverage} ({report['n_probed']}/{report['n_due']})")
            print(
                f"  requests   : {report['n_requests']} for {report['n_due']} links "
                f"({report['n_distinct_urls']} distinct URLs)"
            )
            print(f"  estimated duration: {report['estimate']['estimated_hours']} h")
            for host, n in sorted(report["spent_per_host"].items(), key=lambda kv: -kv[1])[:10]:
                print(f"      {host:<32} {n:>6} req, rate {budget_of(host)}/h")
            return 0 if report["all_due_probed"] else 1

        if command == "status":
            report = status_report(conn, settings)
            print(f"queue: {report['n_links']} links")
            print(f"  due now              : {report['n_due_now']}")
            print(f"  by number of probes  : {report['links_by_probe_count']}")
            print(f"  resolved statuses    : {report['resolved']}")
            for p in report["recent_passes"]:
                kind = "dry" if p["dry_run"] else "real"
                end = p["finished_at"] or "running"
                print(f"  pass {p['pass_id']} ({kind}) {p['n_probed']} probes, finished {end}")
            return 0

        print(f"unknown command: {command!r} (load | plan | dryrun | run | status)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
