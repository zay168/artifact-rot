"""E1 — echantillonnage stratifie depuis OpenAlex, fige et reproductible.

Critere de passage (PLAN.md §7) : **rejouer la graine redonne le meme echantillon**.
Un echantillon non reproductible rend tout le reste invérifiable — ce n'est pas une
commodite d'ingenierie, c'est la condition pour qu'un tiers puisse contester un chiffre
autrement qu'en nous croyant sur parole.

Deux mecanismes distincts, a ne pas confondre :

1. **La graine OpenAlex.** `sample=N&seed=S` renvoie le meme tirage a requete identique.
   Verifie sur l'API le 2026-09-20 : deux appels successifs, memes identifiants, meme
   ordre.
2. **Le gel sur disque.** La graine ne suffit pas, parce que la *population* interrogee
   bouge : OpenAlex indexe de nouveaux articles, corrige des metadonnees, et son
   indicateur `has_fulltext` evolue. Rejouer la meme requete dans six mois peut donc
   donner un autre tirage sans qu'aucun bug ne soit en cause. L'echantillon officiel est
   le **fichier**, accompagne d'un manifeste qui porte la requete exacte, la graine, la
   date d'extraction et l'empreinte du fichier.

`verify` controle les deux separement : l'integrite du fichier (qui doit toujours
passer) et la derive de la population (qui est une information, pas une erreur).

Usage :
    ARTIFACT_ROT_CONTACT="vous@exemple.org" python -m artifact_rot.sample build
    ARTIFACT_ROT_CONTACT="vous@exemple.org" python -m artifact_rot.sample verify
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
"""Graine figee. Elle est publiee avec le rapport : quiconque veut refaire le tirage
doit pouvoir le faire sans nous demander quoi que ce soit."""

N_PER_STRATUM = 2000
"""§3 : >= 2 000 articles par strate croisee. 5 annees x 4 disciplines = 40 000 articles."""

YEARS: tuple[int, ...] = (2010, 2014, 2018, 2022, 2025)
"""L'annee est la variable explicative principale (§3). L'ecart 2010-2025 est ce qui
fabrique la courbe de survie des le premier run, sans attendre."""

DISCIPLINES: dict[str, str] = {
    # Quatre cultures de partage tres differentes (§3). Identifiants de `fields`
    # OpenAlex, verifies sur l'API le 2026-09-20.
    "medicine": "27",
    "computer_science": "17",
    "social_sciences": "33",
    "physics_astronomy": "31",
}
"""Hypothese signalee : le plan dit « biologie/medecine » ; le champ OpenAlex le plus
proche est `Medicine` (27). `Biochemistry, Genetics and Molecular Biology` (13) serait
l'autre choix defendable et plus proche de « biologie ». Medicine est retenu parce que
c'est la culture ou « disponible sur demande » domine — le cas que le piege 4 doit
precisement savoir compter a part. Le choix est inscrit ici pour etre contestable, et
il est ferme jusqu'a E7."""

BASE_FILTERS = (
    "open_access.is_oa:true",  # §3 : restreint a l'acces ouvert
    "has_fulltext:true",  # §3 : texte integral accessible, sinon rien a extraire
    "type:article",  # exclut jeux de donnees, chapitres, actes, errata
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
    # `mailto` place la requete dans le « polite pool » d'OpenAlex : debit plus stable
    # et identification de l'appelant. C'est le §4 piege 5 sous sa forme OpenAlex.
    return httpx.Client(
        base_url=OPENALEX,
        headers={"User-Agent": settings.user_agent},
        params={"mailto": settings.contact},
        timeout=settings.timeout_s,
        follow_redirects=True,
    )


PER_PAGE = 200
"""Maximum autorise par OpenAlex."""


def fetch_stratum(client: httpx.Client, stratum: Stratum, n: int, seed: int) -> list[dict]:
    """Tire `n` articles d'une strate.

    **Pagination classique `page=`, pas par curseur.** Verifie sur l'API le 2026-09-20 :
    sous `sample=`, OpenAlex renvoie `next_cursor: null` des la premiere page — le
    curseur ne pagine pas un tirage. La pagination classique, elle, fonctionne : pages
    disjointes, et le meme couple (graine, page) redonne exactement la meme page.

    Le premier essai avait donc silencieusement ramene 200 articles par strate au lieu
    de 2 000 sans lever d'erreur. C'est le genre de defaut qu'un critere de passage
    formule en nombre attrape, et qu'un code qui « a l'air de marcher » laisse passer.
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
    """Ou aller chercher le texte integral en E3. Sources ouvertes uniquement."""
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
            print(f"  {stratum.key:<28} {len(works):>5} articles", file=sys.stderr)

    # JSON Lines : lisible sans dependance, diffable, et l'empreinte porte sur un
    # format stable dans le temps — ce qu'un parquet ne garantit pas entre versions.
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
            "L'echantillon officiel est ce fichier, pas la requete. OpenAlex indexe en "
            "continu et son indicateur has_fulltext evolue : rejouer la requete plus tard "
            "peut donner un autre tirage sans qu'aucun bug ne soit en cause."
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
    """Un pointeur, pas une copie : l'echantillon lui-meme n'est jamais ecrase."""
    (SAMPLE_DIR / "LATEST").write_text(out_dir.name + "\n", encoding="utf-8")


def latest_sample_dir() -> Path | None:
    pointer = SAMPLE_DIR / "LATEST"
    if not pointer.exists():
        return None
    path = SAMPLE_DIR / pointer.read_text(encoding="utf-8").strip()
    return path if path.exists() else None


def verify(settings: Settings, sample_dir: Path, check_drift: bool = True) -> dict:
    """Deux controles distincts, a ne jamais confondre.

    * **Integrite** : le fichier correspond-il a son empreinte ? Un echec ici est une
      corruption ou une modification — toujours une erreur.
    * **Derive** : rejouer la requete aujourd'hui redonne-t-il les memes identifiants ?
      Un ecart ici est une information sur OpenAlex, pas un defaut de notre code. Il est
      mesure et reporte, jamais corrige en silence.
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
        print(f"erreur de configuration : {exc}", file=sys.stderr)
        return 2

    if command == "build":
        n = int(args[1]) if len(args) > 1 else N_PER_STRATUM
        print(
            f"E1 — tirage de {n} articles x {len(strata())} strates "
            f"(graine {SAMPLE_SEED})",
            file=sys.stderr,
        )
        out_dir = build(settings, n=n)
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        print(f"echantillon fige : {out_dir}")
        print(f"  {manifest['n_rows']} articles, sha256 {manifest['sha256'][:16]}…")

        # Le §3 exige >= n par strate croisee. Un tirage court doit etre bruyant : la
        # premiere version de ce code ramenait 200 articles au lieu de 2 000 sans rien
        # dire, parce que rien ne verifiait le nombre obtenu contre le nombre demande.
        short = {
            key: s for key, s in manifest["strata"].items() if s["obtained"] < s["requested"]
        }
        if short:
            print(f"  ATTENTION — {len(short)} strates incompletes :", file=sys.stderr)
            for key, s in sorted(short.items()):
                print(f"    {key:<28} {s['obtained']}/{s['requested']}", file=sys.stderr)
            return 1
        return 0

    if command == "verify":
        sample_dir = Path(args[1]) if len(args) > 1 else latest_sample_dir()
        if sample_dir is None:
            print("aucun echantillon : lancer `build` d'abord", file=sys.stderr)
            return 2
        report = verify(settings, sample_dir)
        print(f"integrite du fichier : {'ok' if report['integrity_ok'] else 'ECHEC'}")
        print(f"  {report['n_rows']} lignes (attendu {report['expected_rows']})")
        if "mean_jaccard" in report:
            print(f"derive de population : jaccard moyen {report['mean_jaccard']}")
            for key, d in sorted(report["drift"].items()):
                if d["jaccard"] is not None and d["jaccard"] < 1.0:
                    print(f"  {key:<28} jaccard={d['jaccard']}  communs={d['shared']}")
        return 0 if report["integrity_ok"] else 1

    print(f"commande inconnue : {command!r} (build | verify)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
