"""E1 — stratified sampling from OpenAlex, frozen and reproducible.

Pass criterion (PLAN.md §7): **replaying the seed gives back the same sample**.
A non-reproducible sample makes everything else unverifiable — this is not an
engineering convenience, it is the condition for a third party to challenge a figure
other than by taking our word for it.

Two distinct mechanisms, not to be confused:

1. **The OpenAlex seed.** `sample=N&seed=S` returns the same draw for an identical
   request. Checked on the API on 2026-09-20: two successive calls, same identifiers,
   same order.
2. **Freezing on disk.** The seed is not enough, because the queried *population* moves:
   OpenAlex indexes new papers, fixes metadata, and its `has_fulltext` flag changes.
   Replaying the same request in six months can therefore give another draw without any
   bug involved. The official sample is the **file**, together with a manifest carrying
   the exact request, the seed, the extraction date and the file's hash.

`verify` checks the two separately: file integrity (which must always pass) and
population drift (which is information, not an error).

Usage:
    ARTIFACT_ROT_CONTACT="you@example.org" python -m artifact_rot.sample build
    ARTIFACT_ROT_CONTACT="you@example.org" python -m artifact_rot.sample verify
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import ConfigError, Settings

OPENALEX = "https://api.openalex.org"
SAMPLE_DIR = Path("data/sample")
SAMPLE_SEED = 20260920
"""Frozen seed. It is published with the report: anyone wanting to redo the draw must be
able to do so without asking us anything."""

N_PER_STRATUM = 2000
"""§3: >= 2,000 papers per crossed stratum. 5 years x 4 disciplines = 40,000 papers."""

YEARS: tuple[int, ...] = (2010, 2014, 2018, 2022, 2025)
"""Year is the main explanatory variable (§3). The 2010-2025 span is what builds the
survival curve from the first run, without waiting."""

DISCIPLINES: dict[str, str] = {
    # Four very different sharing cultures (§3). OpenAlex `fields` identifiers, checked
    # on the API on 2026-09-20.
    "medicine": "27",
    "computer_science": "17",
    "social_sciences": "33",
    "physics_astronomy": "31",
}
"""Flagged assumption: the plan says "biology/medicine"; the closest OpenAlex field is
`Medicine` (27). `Biochemistry, Genetics and Molecular Biology` (13) would be the other
defensible choice, closer to "biology". Medicine is kept because it is the culture where
"available on request" dominates — precisely the case pitfall 4 must count separately.
The choice is written here so it can be challenged, and it is closed until E7."""

BASE_FILTERS = (
    "open_access.is_oa:true",  # §3: restricted to open access
    "has_fulltext:true",  # §3: accessible full text, otherwise nothing to extract
    "type:article",  # excludes datasets, chapters, proceedings, errata
)

SELECT = (
    "id,doi,publication_year,type,primary_location,best_oa_location,"
    "primary_topic,open_access,authorships"
)


@dataclass(frozen=True)
class Stratum:
    year: int
    discipline: str
    field_id: str

    @property
    def key(self) -> str:
        return f"{self.discipline}-{self.year}"

    @property
    def filter_string(self) -> str:
        return ",".join(
            [
                f"publication_year:{self.year}",
                *BASE_FILTERS,
                f"primary_topic.field.id:fields/{self.field_id}",
            ]
        )


def strata() -> list[Stratum]:
    return [
        Stratum(year=y, discipline=d, field_id=f)
        for d in DISCIPLINES
        for f in [DISCIPLINES[d]]
        for y in YEARS
    ]


def _client(settings: Settings) -> httpx.Client:
    # `mailto` puts the request in OpenAlex's "polite pool": a steadier rate and
    # identification of the caller. This is §4 pitfall 5 in its OpenAlex form.
    return httpx.Client(
        base_url=OPENALEX,
        headers={"User-Agent": settings.user_agent},
        params={"mailto": settings.contact},
        timeout=settings.timeout_s,
        follow_redirects=True,
    )


PER_PAGE = 200
"""Maximum allowed by OpenAlex."""


def fetch_stratum(client: httpx.Client, stratum: Stratum, n: int, seed: int) -> list[dict]:
    """Draw `n` papers from a stratum.

    **Classic `page=` pagination, not cursor-based.** Checked on the API on 2026-09-20:
    under `sample=`, OpenAlex returns `next_cursor: null` from the first page — the
    cursor does not paginate a draw. Classic pagination does work: disjoint pages, and the
    same (seed, page) pair gives back exactly the same page.

    The first attempt had therefore silently brought back 200 papers per stratum instead
    of 2,000 without raising an error. This is the kind of defect a pass criterion stated
    as a number catches, and that code which "seems to work" lets through.
    """
    out: list[dict] = []
    for page in range(1, (n + PER_PAGE - 1) // PER_PAGE + 1):
        r = client.get(
            "/works",
            params={
                "filter": stratum.filter_string,
                "sample": n,
                "seed": seed,
                "per-page": PER_PAGE,
                "page": page,
                "select": SELECT,
            },
        )
        r.raise_for_status()
        results = r.json()["results"]
        out.extend(results)
        if len(results) < PER_PAGE:
            break
    return out[:n]


def _publisher_of(work: dict) -> str:
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    return source.get("host_organization_name") or source.get("display_name") or "unknown"


def _journal_of(work: dict) -> str:
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    return source.get("display_name") or "unknown"


def _fulltext_url(work: dict) -> str | None:
    """Where to fetch the full text in E3. Open sources only."""
    best = work.get("best_oa_location") or {}
    return best.get("pdf_url") or best.get("landing_page_url")


def flatten(work: dict, stratum: Stratum) -> dict[str, Any]:
    return {
        "openalex_id": work["id"].rsplit("/", 1)[-1],
        "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
        "year": work.get("publication_year"),
        "discipline": stratum.discipline,
        "field_id": stratum.field_id,
        "stratum": stratum.key,
        "publisher": _publisher_of(work),
        "journal": _journal_of(work),
        "oa_status": (work.get("open_access") or {}).get("oa_status"),
        "fulltext_url": _fulltext_url(work),
        "topic": (work.get("primary_topic") or {}).get("display_name"),
        "n_authors": len(work.get("authorships") or []),
    }


def build(settings: Settings, n: int = N_PER_STRATUM, seed: int = SAMPLE_SEED) -> Path:
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out_dir = SAMPLE_DIR / f"{stamp}-seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    per_stratum: dict[str, dict] = {}

    with _client(settings) as client:
        for stratum in strata():
            works = fetch_stratum(client, stratum, n, seed)
            rows.extend(flatten(w, stratum) for w in works)
            per_stratum[stratum.key] = {
                "filter": stratum.filter_string,
                "requested": n,
                "obtained": len(works),
            }
            print(f"  {stratum.key:<28} {len(works):>5} papers", file=sys.stderr)

    # JSON Lines: readable without dependencies, diffable, and the hash covers a format
    # that is stable over time — which parquet does not guarantee across versions.
    sample_path = out_dir / "sample.jsonl"
    with sample_path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in sorted(rows, key=lambda r: (r["stratum"], r["openalex_id"])):
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "n_per_stratum": n,
        "years": list(YEARS),
        "disciplines": DISCIPLINES,
        "base_filters": list(BASE_FILTERS),
        "select": SELECT,
        "openalex_base": OPENALEX,
        "strata": per_stratum,
        "n_rows": len(rows),
        "sha256": _sha256(sample_path),
        "note": (
            "The official sample is this file, not the request. OpenAlex indexes "
            "continuously and its has_fulltext flag changes: replaying the request later "
            "can give another draw without any bug involved."
        ),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_latest_pointer(out_dir)
    return out_dir


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_latest_pointer(out_dir: Path) -> None:
    """A pointer, not a copy: the sample itself is never overwritten."""
    (SAMPLE_DIR / "LATEST").write_text(out_dir.name + "\n", encoding="utf-8")


def latest_sample_dir() -> Path | None:
    pointer = SAMPLE_DIR / "LATEST"
    if not pointer.exists():
        return None
    path = SAMPLE_DIR / pointer.read_text(encoding="utf-8").strip()
    return path if path.exists() else None


def verify(settings: Settings, sample_dir: Path, check_drift: bool = True) -> dict:
    """Two distinct checks, never to be confused.

    * **Integrity**: does the file match its hash? A failure here is corruption or a
      modification — always an error.
    * **Drift**: does replaying the request today give back the same identifiers? A gap
      here is information about OpenAlex, not a defect in our code. It is measured and
      reported, never silently corrected.
    """
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8"))
    sample_path = sample_dir / "sample.jsonl"

    report: dict[str, Any] = {
        "sample_dir": str(sample_dir),
        "integrity_ok": _sha256(sample_path) == manifest["sha256"],
        "n_rows": sum(1 for _ in sample_path.open(encoding="utf-8")),
        "expected_rows": manifest["n_rows"],
    }
    if not check_drift:
        return report

    frozen: dict[str, set[str]] = {}
    with sample_path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            frozen.setdefault(row["stratum"], set()).add(row["openalex_id"])

    drift: dict[str, dict] = {}
    with _client(settings) as client:
        for stratum in strata():
            works = fetch_stratum(
                client, stratum, manifest["n_per_stratum"], manifest["seed"]
            )
            now = {w["id"].rsplit("/", 1)[-1] for w in works}
            was = frozen.get(stratum.key, set())
            shared = len(now & was)
            drift[stratum.key] = {
                "frozen": len(was),
                "replayed": len(now),
                "shared": shared,
                "jaccard": round(shared / len(now | was), 4) if (now | was) else None,
            }

    report["drift"] = drift
    overlaps = [d["jaccard"] for d in drift.values() if d["jaccard"] is not None]
    report["mean_jaccard"] = round(sum(overlaps) / len(overlaps), 4) if overlaps else None
    return report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "build"

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if command == "build":
        n = int(args[1]) if len(args) > 1 else N_PER_STRATUM
        print(
            f"E1 — drawing {n} papers x {len(strata())} strata (seed {SAMPLE_SEED})",
            file=sys.stderr,
        )
        out_dir = build(settings, n=n)
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        print(f"frozen sample: {out_dir}")
        print(f"  {manifest['n_rows']} papers, sha256 {manifest['sha256'][:16]}…")

        # §3 requires >= n per crossed stratum. A short draw must be loud: the first
        # version of this code brought back 200 papers instead of 2,000 without a word,
        # because nothing checked the number obtained against the number requested.
        short = {
            key: s for key, s in manifest["strata"].items() if s["obtained"] < s["requested"]
        }
        if short:
            print(f"  WARNING — {len(short)} incomplete strata:", file=sys.stderr)
            for key, s in sorted(short.items()):
                print(f"    {key:<28} {s['obtained']}/{s['requested']}", file=sys.stderr)
            return 1
        return 0

    if command == "verify":
        sample_dir = Path(args[1]) if len(args) > 1 else latest_sample_dir()
        if sample_dir is None:
            print("no sample: run `build` first", file=sys.stderr)
            return 2
        report = verify(settings, sample_dir)
        print(f"file integrity: {'ok' if report['integrity_ok'] else 'FAILED'}")
        print(f"  {report['n_rows']} rows (expected {report['expected_rows']})")
        if "mean_jaccard" in report:
            print(f"population drift: mean jaccard {report['mean_jaccard']}")
            for key, d in sorted(report["drift"].items()):
                if d["jaccard"] is not None and d["jaccard"] < 1.0:
                    print(f"  {key:<28} jaccard={d['jaccard']}  shared={d['shared']}")
        return 0 if report["integrity_ok"] else 1

    print(f"unknown command: {command!r} (build | verify)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
