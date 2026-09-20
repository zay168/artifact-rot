"""E3 — moissonnage du texte integral, extraction des liens, et mesure du rappel.

Critere de passage (PLAN.md §7) : **rappel verifie sur un sous-ensemble ou les liens
sont deja connus via metadonnees structurees.**

Le sous-ensemble ne se constitue pas a la main : il se fabrique. Tout document recupere
porte des liens **balises par l'editeur** — annotations `/URI` d'un PDF, `<a href>` d'un
HTML, `<ext-link>` d'un JATS. Ce balisage est la metadonnee structuree du critere. Notre
extracteur, lui, travaille sur le texte rendu. Le rappel se mesure de l'un contre
l'autre, sans qu'aucun humain n'ait jamais a juger quoi que ce soit — le meme principe
que celui qui fonde le projet.

Le rappel est calcule sur les **liens d'artefacts** seulement. Le calculer sur toutes
les URL melangerait ce qui nous interesse avec les centaines de DOI d'une bibliographie
et donnerait un chiffre flatteur et creux.

Usage :
    ARTIFACT_ROT_CONTACT="vous@exemple.org" python -m artifact_rot.harvest fetch 400
    ARTIFACT_ROT_CONTACT="vous@exemple.org" python -m artifact_rot.harvest recall
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
from .extract.normalize import canonicalize
from .fulltext import Document, fetch_document, fetch_locations, load, save
from .sample import latest_sample_dir

HARVEST_SEED = 20260920
RUNS = Path("runs")

TRUTH_KINDS = {"pdf", "jats"}
"""Formats dont le balisage est **a l'echelle de l'article**.

Mesure du 2026-09-20 : sur 78 liens de depot soi-disant manques, 70 venaient de pages
HTML, et il s'agissait du menu et du pied de page du site hote — `zenodo.org/help/...`,
`github.com/zenodo/zenodo-rdm`. Ce ne sont pas des artefacts de l'article, ce sont les
liens du site qui l'heberge.

Les annotations d'un PDF et les `<ext-link>` d'un JATS, elles, appartiennent au document.
Une page HTML quelconque melange l'article et l'habillage du site, et rien de fiable ne
les separe par regex. On ne mesure donc le rappel que la ou la verite terrain en est
vraiment une. Le nombre de documents ecartes est reporte, jamais tu."""


def load_sample(sample_dir: Path) -> list[dict]:
    path = sample_dir / "sample.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def pick(rows: list[dict], n: int, seed: int = HARVEST_SEED) -> list[dict]:
    """Sous-echantillon equilibre par strate, reproductible.

    Equilibre et non proportionnel : les strates ont toutes 2 000 articles, et un
    sous-ensemble desequilibre rendrait le rappel par discipline illisible.
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
    """Recupere et met en cache le texte integral. Le cache n'est jamais reecrit."""
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
            stats[key][doc.kind if doc.ok else "echec"] += 1
            if not doc.ok:
                stats[key][f"cause:{(doc.error or 'inconnu').split(':')[0]}"] += 1
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}", file=sys.stderr)

    return {k: dict(v) for k, v in sorted(stats.items())}


def recall(rows: list[dict]) -> dict:
    """Rappel de l'extraction textuelle contre le balisage editorial.

    Trois populations, a ne pas confondre :

    * `truth`   — liens d'artefacts balises par l'editeur (verite terrain) ;
    * `found`   — liens d'artefacts trouves dans le texte rendu ;
    * `extra`   — trouves dans le texte mais absents du balisage. Ce ne sont pas des
                  faux positifs : un lien ecrit en clair et non balise est un vrai lien.
                  Ils sont comptes a part, parce qu'ils mesurent ce que l'approche
                  purement structuree perdrait.
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

        # Les deux familles sont separees parce qu'elles ne disent pas la meme chose.
        # Un article cite des dizaines de DOI dans sa bibliographie : un rappel global
        # serait porte par eux et masquerait la performance sur les depots, qui sont la
        # population que le projet mesure.
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
    """`repo_host` = depot identifiable (GitHub, Zenodo, OSF…). `doi` = tout le reste,
    c'est-a-dire l'immense majorite des DOI d'une bibliographie."""
    from .extract.links import ARTIFACT_HOSTS
    from .extract.normalize import host_of

    return "repo_host" if host_of(url) in ARTIFACT_HOSTS else "doi"


def links_of(rows: list[dict]) -> list[dict]:
    """Les liens extraits de tout le sous-ensemble, prets a etre sondes."""
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
        print(f"erreur de configuration : {exc}", file=sys.stderr)
        return 2

    sample_dir = latest_sample_dir()
    if sample_dir is None:
        print("aucun echantillon : lancer `python -m artifact_rot.sample build`", file=sys.stderr)
        return 2
    rows = pick(load_sample(sample_dir), int(args[1]) if len(args) > 1 else 400)

    if command == "fetch":
        print(f"E3 — moissonnage de {len(rows)} articles", file=sys.stderr)
        stats = fetch(rows, settings)
        total = sum(s["n"] for s in stats.values())
        ok = total - sum(s.get("echec", 0) for s in stats.values())
        print(f"texte integral obtenu : {ok}/{total} ({100 * ok / total:.0f} %)")
        for key, s in stats.items():
            got = s["n"] - s.get("echec", 0)
            print(f"  {key:<28} {got:>3}/{s['n']:<3} pdf={s.get('pdf', 0):>3} "
                  f"html={s.get('html', 0):>2} jats={s.get('jats', 0):>2}")
        _write(RUNS / _stamp("harvest") / "coverage.json", stats)
        return 0

    if command == "recall":
        report = recall(rows)
        if not report["truth"]:
            print("aucun lien d'artefact balise : lancer `fetch` d'abord", file=sys.stderr)
            return 2
        print("E3 — rappel contre le balisage editorial")
        print(f"  documents exploites      : {report['docs']}  (PDF et JATS seuls)")
        print(f"  pages HTML ecartees      : {report['docs_skipped_html']}")
        print(f"  dont porteurs d'artefact : {report['docs_with_truth']}")
        print(f"  liens balises (verite)   : {report['truth']}")
        print(f"  retrouves dans le texte  : {report['hit']}")
        print(f"  RAPPEL                   : {report['recall']}")
        print(f"  trouves hors balisage    : {report['extra']}")
        for family, f in report["by_family"].items():
            print(
                f"    {family:<10} verite={f['truth']:>5}  rappel={f['recall']}  "
                f"hors balisage={f['extra']}"
            )
        if report["miss_hosts"]:
            print("  hotes les plus manques   :")
            for host, n in list(report["miss_hosts"].items())[:6]:
                print(f"      {n:>4}  {host}")
        out = RUNS / _stamp("recall") / "recall.json"
        _write(out, report)
        print(f"  rapport : {out}")
        return 0

    if command == "links":
        links = links_of(rows)
        out = RUNS / _stamp("links") / "links.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            for link in links:
                fh.write(json.dumps(link, ensure_ascii=False, default=str, sort_keys=True) + "\n")
        kinds = collections.Counter(link["kind"] for link in links)
        sources = collections.Counter(link["source"] for link in links)
        print(f"{len(links)} liens extraits -> {out}")
        print("  par type     :", dict(kinds.most_common()))
        print("  par provenance:", dict(sources.most_common()))
        on_request = sum(
            count_on_request(doc.text)
            for doc in (load(r["openalex_id"]) for r in rows)
            if doc is not None and doc.ok
        )
        print(f"  « sur demande » (jamais sonde, §4 piege 4) : {on_request}")
        return 0

    print(f"commande inconnue : {command!r} (fetch | recall | links)", file=sys.stderr)
    return 2


def _stamp(name: str) -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{name}"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
