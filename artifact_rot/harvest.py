"""E3 — full-text harvesting, link extraction, and recall measurement.

Pass criterion (PLAN.md §7): **recall verified on a subset where links are already known
through structured metadata.**

The subset is not assembled by hand: it builds itself. Every retrieved document carries
links **tagged by its publisher** — `/URI` annotations in a PDF, `<a href>` in HTML,
`<ext-link>` in JATS. That markup is the structured metadata of the criterion. Our
extractor works on the rendered text. Recall is measured one against the other, without
any human ever having to judge anything — the same principle the project rests on.

Recall is computed on **artifact links** only. Computing it on every URL would mix what
we care about with the hundreds of DOIs of a bibliography and give a flattering, hollow
figure.

Usage:
    ARTIFACT_ROT_CONTACT="you@example.org" python -m artifact_rot.harvest fetch 400
    ARTIFACT_ROT_CONTACT="you@example.org" python -m artifact_rot.harvest recall

3x extension of the grey zone (docs/extension.md):
    python -m artifact_rot.harvest fetch-ext
    python -m artifact_rot.harvest links-ext     # artifacts only
"""

from __future__ import annotations

import collections
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import ConfigError, Settings
from .extract.links import (
    count_on_request,
    extract_links,
    is_artifact_link,
    iter_raw_links,
)
from .extract.normalize import canonicalize, host_of
from .fulltext import Document, fetch_document, fetch_locations, load, save
from .sample import latest_sample_dir

HARVEST_SEED = 20260920
RUNS = Path("runs")

TRUTH_KINDS = {"pdf", "jats"}
"""Formats whose markup is **scoped to the paper**.

Measured on 2026-09-20: of 78 supposedly missed repository links, 70 came from HTML
pages, and they were the host site's menu and footer — `zenodo.org/help/...`,
`github.com/zenodo/zenodo-rdm`. Those are not artifacts of the paper but links of the
site hosting it.

A PDF's annotations and a JATS file's `<ext-link>` elements belong to the document. An
arbitrary HTML page mixes the paper with site chrome, and nothing reliable separates
them by regex. Recall is therefore measured only where the ground truth really is one.
The number of excluded documents is reported, never hidden."""


def load_sample(sample_dir: Path) -> list[dict]:
    path = sample_dir / "sample.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def pick(rows: list[dict], n: int, seed: int = HARVEST_SEED) -> list[dict]:
    """Subsample balanced by stratum, reproducible.

    Balanced rather than proportional: every stratum has 2,000 papers, and an unbalanced
    subset would make per-discipline recall unreadable.
    """
    by: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by[row["stratum"]].append(row)
    per = max(1, n // len(by))
    rng = random.Random(seed)
    out: list[dict] = []
    for stratum in sorted(by):
        items = by[stratum]
        out.extend(rng.sample(items, min(per, len(items))))
    return out


BASE_N = 2000
EXTENSION_SEED = 20261004
EXTENSION_PER_STRATUM = 200
ARTIFACT_KINDS = {"code_repo", "data_repo", "dataset_doi"}


def pick_extension(
    rows: list[dict],
    already: list[dict],
    per_stratum: int = EXTENSION_PER_STRATUM,
    seed: int = EXTENSION_SEED,
) -> list[dict]:
    """The 3x extension of the grey zone (docs/extension.md §4).

    Drawn from papers **not yet harvested** in each stratum, with a distinct seed.
    Calling `pick` again with three times the size would not give a superset of the first
    2,000: `random.sample` does not guarantee that a draw of 300 starts with the draw of
    100. Links already probed three times would be lost.
    """
    taken = {r["openalex_id"] for r in already}
    by: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row["openalex_id"] not in taken:
            by[row["stratum"]].append(row)
    rng = random.Random(seed)
    out: list[dict] = []
    for stratum in sorted(by):
        items = by[stratum]
        out.extend(rng.sample(items, min(per_stratum, len(items))))
    return out


def _client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
        },
        timeout=settings.timeout_s,
        follow_redirects=True,
    )


def fetch(rows: list[dict], settings: Settings) -> dict:
    """Retrieve and cache full text. The cache is never rewritten."""
    stats: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    with _client(settings) as client:
        for i, row in enumerate(rows, 1):
            paper_id = row["openalex_id"]
            doc = load(paper_id)
            if doc is None:
                try:
                    locations = fetch_locations(client, paper_id, settings)
                except httpx.HTTPError as exc:
                    doc = Document(paper_id, "", "", "none", error=f"openalex:{type(exc).__name__}")
                else:
                    doc = fetch_document(client, paper_id, locations, settings)
                save(doc)
                time.sleep(settings.per_host_delay_s / 2)

            key = row["stratum"]
            stats[key]["n"] += 1
            stats[key][doc.kind if doc.ok else "failed"] += 1
            if not doc.ok:
                stats[key][f"cause:{(doc.error or 'unknown').split(':')[0]}"] += 1
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}", file=sys.stderr)

    return {k: dict(v) for k, v in sorted(stats.items())}


def recall(rows: list[dict]) -> dict:
    """Recall of text extraction against publisher markup.

    Three populations, not to be confused:

    * `truth`   — artifact links tagged by the publisher (ground truth);
    * `found`   — artifact links found in the rendered text;
    * `extra`   — found in the text but absent from the markup. These are not false
                  positives: a link written in plain text and not tagged is a real link.
                  They are counted separately because they measure what a purely
                  structured approach would lose.
    """
    per_stratum: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    per_family: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    misses: list[dict] = []
    totals = collections.Counter()
    skipped = collections.Counter()

    for row in rows:
        doc = load(row["openalex_id"])
        if doc is None or not doc.ok:
            continue
        if doc.kind not in TRUTH_KINDS:
            skipped["html_non_article"] += 1
            continue

        truth = {canonicalize(u) for u in doc.structured_urls if is_artifact_link(u)}
        found = {
            canonicalize(raw) for _, raw in iter_raw_links(doc.text) if is_artifact_link(raw)
        }

        # The two families are kept apart because they do not say the same thing. A
        # paper cites dozens of DOIs in its bibliography: an overall recall would be
        # driven by them and would hide performance on repositories, which are the
        # population the project measures.
        for family in ("repo_host", "doi"):
            t = {u for u in truth if _family(u) == family}
            f = {u for u in found if _family(u) == family}
            per_family[family]["truth"] += len(t)
            per_family[family]["hit"] += len(t & f)
            per_family[family]["extra"] += len(f - t)

        key = row["stratum"]
        per_stratum[key]["docs"] += 1
        per_stratum[key]["truth"] += len(truth)
        per_stratum[key]["hit"] += len(truth & found)
        per_stratum[key]["extra"] += len(found - truth)
        totals["docs"] += 1
        totals["truth"] += len(truth)
        totals["hit"] += len(truth & found)
        totals["extra"] += len(found - truth)
        totals["docs_with_truth"] += int(bool(truth))

        for url in sorted(truth - found):
            misses.append({"paper_id": doc.paper_id, "kind": doc.kind, "url": url})

    by_stratum = {}
    for key, c in sorted(per_stratum.items()):
        by_stratum[key] = {
            "docs": c["docs"],
            "truth": c["truth"],
            "hit": c["hit"],
            "extra": c["extra"],
            "recall": round(c["hit"] / c["truth"], 4) if c["truth"] else None,
        }

    miss_hosts = collections.Counter(
        canonicalize(m["url"]).split("/")[2] for m in misses if "/" in m["url"]
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "docs": totals["docs"],
        "docs_skipped_html": skipped["html_non_article"],
        "docs_with_truth": totals["docs_with_truth"],
        "truth": totals["truth"],
        "hit": totals["hit"],
        "extra": totals["extra"],
        "recall": round(totals["hit"] / totals["truth"], 4) if totals["truth"] else None,
        "by_family": {
            family: {
                "truth": c["truth"],
                "hit": c["hit"],
                "extra": c["extra"],
                "recall": round(c["hit"] / c["truth"], 4) if c["truth"] else None,
            }
            for family, c in sorted(per_family.items())
        },
        "by_stratum": by_stratum,
        "miss_hosts": dict(miss_hosts.most_common(15)),
        "misses": misses[:200],
    }


def _family(url: str) -> str:
    """`repo_host` = identifiable repository (GitHub, Zenodo, OSF…). `doi` = everything
    else, i.e. the vast majority of a bibliography's DOIs."""
    from .extract.links import ARTIFACT_HOSTS
    from .extract.normalize import host_of

    return "repo_host" if host_of(url) in ARTIFACT_HOSTS else "doi"


def links_of(rows: list[dict]) -> list[dict]:
    """Links extracted from the whole subset, ready to be probed."""
    out: list[dict] = []
    for row in rows:
        doc = load(row["openalex_id"])
        if doc is None or not doc.ok:
            continue
        links = extract_links(
            doc.text,
            paper_id=row["openalex_id"],
            paper_doi=row["doi"],
            paper_year=row["year"],
            discipline=row["discipline"],
            publisher=row["publisher"],
            structured_urls=doc.structured_urls,
            # Site chrome is only a problem for HTML: a PDF's annotations belong to the
            # document.
            chrome_host=host_of(doc.source_url) if doc.kind == "html" else None,
        )
        for link in links:
            out.append(link.model_dump() | {"link_id": link.link_id, "stratum": row["stratum"]})
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "recall"

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    sample_dir = latest_sample_dir()
    if sample_dir is None:
        print("no sample: run `python -m artifact_rot.sample build`", file=sys.stderr)
        return 2
    sample = load_sample(sample_dir)
    if command.endswith("-ext"):
        rows = pick_extension(sample, pick(sample, BASE_N))
        command = command.removesuffix("-ext")
    else:
        rows = pick(sample, int(args[1]) if len(args) > 1 else 400)
    # The extension probes artifacts only (docs/extension.md §4.3).
    artifacts_only = len(args) > 0 and args[0] == "links-ext"

    if command == "fetch":
        print(f"E3 — harvesting {len(rows)} papers", file=sys.stderr)
        stats = fetch(rows, settings)
        total = sum(s["n"] for s in stats.values())
        ok = total - sum(s.get("failed", 0) for s in stats.values())
        print(f"full text obtained: {ok}/{total} ({100 * ok / total:.0f}%)")
        for key, s in stats.items():
            got = s["n"] - s.get("failed", 0)
            print(f"  {key:<28} {got:>3}/{s['n']:<3} pdf={s.get('pdf', 0):>3} "
                  f"html={s.get('html', 0):>2} jats={s.get('jats', 0):>2}")
        _write(RUNS / _stamp("harvest") / "coverage.json", stats)
        return 0

    if command == "recall":
        report = recall(rows)
        if not report["truth"]:
            print("no tagged artifact link: run `fetch` first", file=sys.stderr)
            return 2
        print("E3 — recall against publisher markup")
        print(f"  documents used           : {report['docs']}  (PDF and JATS only)")
        print(f"  HTML pages excluded      : {report['docs_skipped_html']}")
        print(f"  carrying artifacts       : {report['docs_with_truth']}")
        print(f"  tagged links (truth)     : {report['truth']}")
        print(f"  found in the text        : {report['hit']}")
        print(f"  RECALL                   : {report['recall']}")
        print(f"  found outside markup     : {report['extra']}")
        for family, f in report["by_family"].items():
            print(
                f"    {family:<10} truth={f['truth']:>5}  recall={f['recall']}  "
                f"outside markup={f['extra']}"
            )
        if report["miss_hosts"]:
            print("  most-missed hosts        :")
            for host, n in list(report["miss_hosts"].items())[:6]:
                print(f"      {n:>4}  {host}")
        out = RUNS / _stamp("recall") / "recall.json"
        _write(out, report)
        print(f"  report: {out}")
        return 0

    if command == "links":
        links = links_of(rows)
        if artifacts_only:
            print(f"extension: {len(links)} links extracted, artifacts only kept")
            links = [link for link in links if link["kind"] in ARTIFACT_KINDS]
        out = RUNS / _stamp("links-ext" if artifacts_only else "links") / "links.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            for link in links:
                fh.write(json.dumps(link, ensure_ascii=False, default=str, sort_keys=True) + "\n")
        kinds = collections.Counter(link["kind"] for link in links)
        sources = collections.Counter(link["source"] for link in links)
        print(f"{len(links)} links extracted -> {out}")
        print("  by kind      :", dict(kinds.most_common()))
        print("  by provenance:", dict(sources.most_common()))
        on_request = sum(
            count_on_request(doc.text)
            for doc in (load(r["openalex_id"]) for r in rows)
            if doc is not None and doc.ok
        )
        print(f"  \"on request\" (never probed, §4 pitfall 4): {on_request}")
        return 0

    print(
        f"unknown command: {command!r} (fetch | recall | links | fetch-ext | links-ext)",
        file=sys.stderr,
    )
    return 2


def _stamp(name: str) -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{name}"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
