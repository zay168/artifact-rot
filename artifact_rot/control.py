"""E2 — jeu de controle a verite connue **par construction**.

C'est le premier code du projet et son test de sante (§2, §7). Si la classification
n'atteint pas 98 % ici, aucun chiffre produit ensuite ne vaut rien, et le plan impose
de s'arreter plutot que de continuer.

Le principe est celui qui fonde le projet entier : la verite terrain ne s'annote pas,
elle se fabrique. Quatre familles de cas, chacune vraie par construction et non par
jugement :

* `dead`       — URL sur un hebergeur reel, dans un espace de noms garanti inexistant
                 (identifiant aleatoire de 128 bits). La probabilite de collision est
                 nulle a toute echelle pratique.
* `alive`      — ressources publiques, stables, massivement referencees. Leur
                 disparition pendant un run serait elle-meme une information, et le
                 rapport de controle la signalerait comme telle.
* `malformed`  — URL syntaxiquement cassees, evaluees hors ligne : aucune requete
                 reseau n'intervient, donc aucune incertitude.
* `restricted` — la seule famille qui ne se fabrique pas toute seule : il faut posseder
                 une ressource reellement privee ou sous embargo. Elle est donc fournie
                 par un fichier de provisionnement (voir `docs/jeu-de-controle.md`).
                 **Sans elle, le score global n'est pas emis** : annoncer 98 % en ayant
                 silencieusement omis la categorie la plus difficile serait precisement
                 le genre d'approximation que le §0 interdit.

Usage :
    ARTIFACT_ROT_CONTACT="vous@exemple.org" python -m artifact_rot.control
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from .config import ConfigError, Settings
from .extract.normalize import canonicalize, host_of, is_malformed
from .models import Link, Status
from .probe import build_client, default_registry

CONTROL_SEED = 20260920
"""Graine figee. Rejouer le jeu de controle doit redonner exactement les memes URL."""

RESTRICTED_FIXTURES = Path("data/control/restricted.json")
TARGET_ACCURACY = 0.98

# --- Cas `alive` : ressources publiques stables ------------------------------------
# Choisies pour leur permanence institutionnelle, pas pour leur popularite. Chacune est
# adossee a une organisation qui survivra au projet.
KNOWN_ALIVE: list[tuple[str, str]] = [
    ("code_repo", "https://github.com/torvalds/linux"),
    ("code_repo", "https://github.com/python/cpython"),
    ("code_repo", "https://github.com/numpy/numpy"),
    ("code_repo", "https://github.com/scikit-learn/scikit-learn"),
    ("code_repo", "https://github.com/pandas-dev/pandas"),
    ("code_repo", "https://github.com/scienceverse/metacheck"),
    ("code_repo", "https://gitlab.com/gitlab-org/gitlab"),
    ("code_repo", "https://gitlab.com/inkscape/inkscape"),
    ("dataset_doi", "https://doi.org/10.1371/journal.pone.0304781"),
    ("dataset_doi", "https://doi.org/10.1038/s41586-020-2649-2"),
    ("dataset_doi", "https://doi.org/10.1371/journal.pbio.3000385"),
    ("data_repo", "https://zenodo.org/records/3509134"),
    ("data_repo", "https://osf.io/ezcuj/"),
    ("generic_url", "https://www.python.org/downloads/"),
    ("generic_url", "https://www.gnu.org/software/"),
    ("generic_url", "https://archive.softwareheritage.org/"),
]

# --- Cas `waf` : hotes derriere un pare-feu applicatif -----------------------------
# Ajoutes apres le premier run reel, qui a montre qu'openalex.org repond 403 Cloudflare
# a un robot. Ce n'est pas un defaut des sondes : c'est exactement le cas du §4, piege 1
# (« un 403 peut etre Cloudflare, pas une suppression »). La bonne reponse est `unknown`,
# et elle doit etre verifiee comme telle plutot que subie comme une erreur de score.
#
# Ces cas servent donc a prouver que le crawler *refuse de conclure* quand il est bloque.
# Une regression qui les ferait basculer en `dead` serait la falsification que le plan
# designe comme l'erreur fatale.
WAF_CASES: list[tuple[str, str]] = [
    ("generic_url", "https://openalex.org/"),
    ("generic_url", "https://openalex.org/artifact-rot-absent-{t}"),
]

# --- Cas `dead` : hebergeurs reels, espaces de noms garantis vides -----------------
DEAD_TEMPLATES: list[tuple[str, str]] = [
    ("code_repo", "https://github.com/artifact-rot-absent-{t}/repo-{t}"),
    ("code_repo", "https://gitlab.com/artifact-rot-absent-{t}/repo-{t}"),
    ("code_repo", "https://bitbucket.org/artifact-rot-absent-{t}/repo-{t}"),
    ("data_repo", "https://zenodo.org/records/9{t9}"),
    ("data_repo", "https://figshare.com/articles/dataset/absent/9{t9}"),
    ("dataset_doi", "https://doi.org/10.5281/zenodo.9{t9}"),
    ("dataset_doi", "https://doi.org/10.9999/artifact-rot-absent-{t}"),
    ("generic_url", "https://www.python.org/artifact-rot-absent-{t}/"),
    ("generic_url", "https://www.gnu.org/artifact-rot-absent-{t}/"),
]

# --- Cas `malformed` : casses des l'origine, evalues hors ligne --------------------
MALFORMED_CASES: list[str] = [
    "https://github.com/",
    "https://github.com",
    "http://doi.org/notadoi",
    # NB : `https://doi. org/10.7939/…` a ete retire de cette liste apres le premier run
    # reel. Ce n'est PAS un lien malforme : c'est un lien valide casse par l'extraction
    # PDF, que `repair_spaced_hosts` recolle — et doit recoller. Le compter `malformed`
    # aurait fait passer une reparation reussie pour un echec. Le cas reste teste, a sa
    # vraie place, dans `tests/test_normalize.py::TestMetacheckBug2GrobidWhitespace`.
    "https://.com/owner/repo",
    "https://github..com/owner/repo",
    "https://-badhost.org/data",
    "https://localhost/data",
    "https://github.com/owner repo",
    "https:///owner/repo",
]


class ControlCase(BaseModel):
    case_id: str
    url: str
    kind: str
    expected: Status | None = None
    """None pour la famille `malformed`, evaluee par `is_malformed` et non par une sonde."""
    family: str
    provenance: str
    """Comment la verite est connue. Rend le jeu auditable sans faire confiance a l'auteur."""


def build_cases(n_dead: int = 90) -> list[ControlCase]:
    rng = random.Random(CONTROL_SEED)
    cases: list[ControlCase] = []

    for i, (kind, url) in enumerate(KNOWN_ALIVE):
        cases.append(
            ControlCase(
                case_id=f"alive-{i:03d}",
                url=url,
                kind=kind,
                expected=Status.ALIVE,
                family="alive",
                provenance="ressource publique stable, adossee a une organisation perenne",
            )
        )

    for i in range(n_dead):
        kind, template = DEAD_TEMPLATES[i % len(DEAD_TEMPLATES)]
        token = f"{rng.getrandbits(128):032x}"
        url = template.format(t=token, t9=rng.randrange(10**8, 10**9))
        cases.append(
            ControlCase(
                case_id=f"dead-{i:03d}",
                url=url,
                kind=kind,
                expected=Status.DEAD,
                family="dead",
                provenance="espace de noms aleatoire de 128 bits sur un hebergeur reel",
            )
        )

    for i, url in enumerate(MALFORMED_CASES):
        cases.append(
            ControlCase(
                case_id=f"malformed-{i:03d}",
                url=url,
                kind="generic_url",
                expected=None,
                family="malformed",
                provenance="invalidite syntaxique, verifiee hors ligne",
            )
        )

    for i, (kind, template) in enumerate(WAF_CASES):
        cases.append(
            ControlCase(
                case_id=f"waf-{i:03d}",
                url=template.format(t=f"{rng.getrandbits(128):032x}"),
                kind=kind,
                expected=Status.UNKNOWN,
                family="waf",
                provenance="hote derriere un pare-feu applicatif : la bonne reponse est unknown",
            )
        )

    cases.extend(_load_restricted())
    return cases


def _load_restricted() -> list[ControlCase]:
    if not RESTRICTED_FIXTURES.exists():
        return []
    raw = json.loads(RESTRICTED_FIXTURES.read_text(encoding="utf-8"))
    return [
        ControlCase(
            case_id=f"restricted-{i:03d}",
            url=entry["url"],
            kind=entry.get("kind", "data_repo"),
            expected=Status.RESTRICTED,
            family="restricted",
            provenance=entry["provenance"],
        )
        for i, entry in enumerate(raw)
    ]


def _as_link(case: ControlCase) -> Link:
    normalized = canonicalize(case.url)
    return Link(
        paper_id="W0000000001",
        paper_year=2026,
        discipline="control",
        publisher="control",
        raw=case.url,
        normalized=normalized,
        kind=case.kind,  # type: ignore[arg-type]
        host=host_of(normalized),
        malformed_at_source=is_malformed(case.url),
    )


def run(cases: list[ControlCase], settings: Settings) -> dict:
    registry = default_registry()
    results: list[dict] = []

    with build_client(settings) as client:
        for case in cases:
            link = _as_link(case)

            if case.family == "malformed":
                observed = is_malformed(case.url)
                results.append(
                    {
                        "case_id": case.case_id,
                        "family": case.family,
                        "url": case.url,
                        "expected": "malformed",
                        "observed": "malformed" if observed else "well_formed",
                        "correct": observed,
                        "reason": "offline_syntax_check",
                        "evidence": {},
                    }
                )
                continue

            result = registry.check(client, link, settings)
            results.append(
                {
                    "case_id": case.case_id,
                    "family": case.family,
                    "url": case.url,
                    "expected": case.expected.value if case.expected else None,
                    "observed": result.status.value,
                    "correct": result.status is case.expected,
                    "reason": result.reason,
                    "evidence": result.evidence,
                }
            )

    return _score(results)


def _score(results: list[dict]) -> dict:
    families: dict[str, dict] = {}
    for r in results:
        f = families.setdefault(r["family"], {"n": 0, "correct": 0, "unknown": 0, "errors": []})
        f["n"] += 1
        f["correct"] += int(r["correct"])
        f["unknown"] += int(r["observed"] == Status.UNKNOWN.value)
        if not r["correct"]:
            f["errors"].append(
                {"case_id": r["case_id"], "url": r["url"], "observed": r["observed"], "reason": r["reason"]}
            )

    for f in families.values():
        f["accuracy"] = f["correct"] / f["n"] if f["n"] else None

    # `waf` n'est pas dans les familles requises : c'est un garde-fou ajoute, pas une
    # categorie du §4. Son absence n'invalide pas le verdict ; son echec, si.
    missing = {"alive", "dead", "malformed", "restricted"} - set(families)
    n = sum(f["n"] for f in families.values())
    correct = sum(f["correct"] for f in families.values())

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": CONTROL_SEED,
        "n_cases": n,
        "overall_accuracy": correct / n if n else None,
        "target_accuracy": TARGET_ACCURACY,
        "families": families,
        "missing_families": sorted(missing),
        # Le verdict n'est emis que si les quatre familles sont presentes. Un score
        # calcule sur un jeu ampute n'est pas un score, c'est une mise en scene.
        "verdict": (
            "incomplet"
            if missing
            else ("passe" if n and correct / n >= TARGET_ACCURACY else "echoue")
        ),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"erreur de configuration : {exc}", file=sys.stderr)
        return 2

    if not settings.github_token:
        print(
            "avertissement : GITHUB_TOKEN absent. Le quota anonyme (60 req/h) ne suffit "
            "pas a rejouer le jeu de controle plusieurs fois dans l'heure ; les cas "
            "GitHub reviendront `unknown` sans que cela dise rien de leur etat.",
            file=sys.stderr,
        )

    report = run(build_cases(), settings)

    out_dir = Path("runs") / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-control"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "control.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"jeu de controle E2 — {report['n_cases']} cas — verdict : {report['verdict']}")
    for family, f in sorted(report["families"].items()):
        acc = f["accuracy"]
        print(f"  {family:<11} n={f['n']:<4} exactitude={acc:.3f}  unknown={f['unknown']}")
        for err in f["errors"][:5]:
            print(f"      X {err['case_id']} {err['observed']:<10} {err['reason']}  {err['url']}")
    if report["missing_families"]:
        print(
            "  familles absentes : "
            + ", ".join(report["missing_families"])
            + " — verdict non emis (voir docs/jeu-de-controle.md)"
        )
    print(f"  rapport : {out_dir / 'control.json'}")

    return 0 if report["verdict"] == "passe" else 1


if __name__ == "__main__":
    raise SystemExit(main())
