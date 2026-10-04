"""E6 — applique `survival.verdict_h1` a l'etat courant de la file.

Ne contient aucune decision statistique : elles sont toutes dans `survival.py`, ecrit le
2026-09-21 avant les passes 2 et 3. Ce module ne fait que compter et appeler.

Deux perimetres (docs/prolongation.md §4.1) :
  * `artefacts` — code_repo, data_repo, dataset_doi. Analyse principale depuis le 2026-10-04.
  * `tout`      — tous les liens, y compris les URL generiques. Publie a part.

Usage :
    ARTIFACT_ROT_CONTACT="vous@exemple.org" python -m artifact_rot.verdict artefacts
"""

from __future__ import annotations

import collections
import json
import sys
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .config import ConfigError, Settings
from .harvest import ARTIFACT_KINDS
from .resolve import resolve
from .schedule import _probes_by_link, connect
from .survival import AgePoint, StratumCounts, survival_curve, verdict_h1

OBSERVATION_YEAR = 2026
SCOPES = ("artefacts", "tout")


def in_scope(payload: dict, scope: str) -> bool:
    return scope == "tout" or payload["kind"] in ARTIFACT_KINDS


def count(
    payloads: dict[str, dict], probes: dict, settings: Settings, scope: str, key: str
) -> dict:
    """Comptes des quatre etats, par valeur de `key` (paper_year, discipline, kind…).

    Un lien jamais sonde n'est compte nulle part : il n'a pas d'etat.
    """
    out: dict = collections.defaultdict(StratumCounts)
    for link_id, payload in payloads.items():
        if not in_scope(payload, scope) or not probes.get(link_id):
            continue
        status = resolve(link_id, probes[link_id], settings).status.value
        counts = out[payload[key]]
        setattr(counts, status, getattr(counts, status) + 1)
    return dict(out)


def analyse(conn, settings: Settings, scope: str) -> dict:
    payloads = {
        r["link_id"]: json.loads(r["payload"])
        for r in conn.execute("SELECT link_id, payload FROM links")
    }
    probes = _probes_by_link(conn)
    by_year = count(payloads, probes, settings, scope, "paper_year")
    report: dict = {"scope": scope, "generated_at": datetime.now(UTC).isoformat()}
    for policy in ("alive", "exclude"):
        result = verdict_h1(by_year, policy)
        curve = survival_curve(
            [AgePoint(OBSERVATION_YEAR - y, c, str(y)) for y, c in by_year.items()], policy
        )
        report[f"restricted_{policy}"] = {
            "h1": asdict(result),
            "survival": dict(zip(curve.labels, curve.survival, strict=True)),
            "half_life_years": curve.half_life,
        }
    for key in ("paper_year", "discipline", "kind"):
        report[f"by_{key}"] = {
            str(k): asdict(c) for k, c in sorted(count(payloads, probes, settings, scope, key).items())
        }
    return report


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = list(sys.argv[1:] if argv is None else argv)
    scope = args[0] if args else "artefacts"
    if scope not in SCOPES:
        print(f"perimetre inconnu : {scope!r} ({' | '.join(SCOPES)})", file=sys.stderr)
        return 2
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"erreur de configuration : {exc}", file=sys.stderr)
        return 2

    with closing(connect()) as conn:
        report = analyse(conn, settings, scope)

    out = Path("runs") / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-verdict-{scope}" / "verdict.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"perimetre : {scope}")
    for year, c in report["by_paper_year"].items():
        print(f"  {year}  {c}")
    for policy in ("alive", "exclude"):
        block = report[f"restricted_{policy}"]
        print(f"restricted={policy} : verdict {block['h1']['verdict']}")
        for reason in block["h1"]["reasons"]:
            print(f"   - {reason}")
        print(f"   unknown {block['h1']['unknown_rate']:.1%}, demi-vie {block['half_life_years']}")
    print(f"rapport : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
