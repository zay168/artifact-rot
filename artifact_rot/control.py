"""E2 — control set with ground truth known **by construction**.

This is the project's first code and its health check (§2, §7). If classification does
not reach 98% here, no figure produced afterwards is worth anything, and the plan
requires stopping rather than carrying on.

The principle is the one the whole project rests on: ground truth is not annotated, it
is built. Several families of cases, each true by construction rather than by judgement:

* `dead`       — URL on a real host, in a namespace guaranteed not to exist (128-bit
                 random identifier). The probability of collision is nil at any
                 practical scale.
* `alive`      — public, stable, widely referenced resources. Their disappearance during
                 a run would itself be information, and the control report would flag it
                 as such.
* `malformed`  — syntactically broken URLs, evaluated offline: no network request is
                 involved, hence no uncertainty.
* `restricted` — the only family that does not build itself: one must own a genuinely
                 private or embargoed resource, or find an independent record of one. It
                 is provided by a provisioning file (see `docs/control-set.md`).
                 **Without it, no overall score is issued**: announcing 98% while silently
                 omitting the hardest category would be precisely the kind of
                 approximation §0 forbids.

Usage:
    ARTIFACT_ROT_CONTACT="you@example.org" python -m artifact_rot.control
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
"""Fixed seed. Replaying the control set must return exactly the same URLs."""

RESTRICTED_FIXTURES = Path("data/control/restricted.json")
TARGET_ACCURACY = 0.98

# --- `alive` cases: stable public resources ----------------------------------------
# Chosen for their institutional permanence, not their popularity. Each is backed by an
# organisation that will outlive the project.
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

# --- `waf` cases: hosts behind a web application firewall ------------------------
# Added after the first real run, which showed that openalex.org answers 403
# (Cloudflare) to a crawler. This is not a probe defect: it is exactly the case of §4,
# pitfall 1 ("a 403 can be Cloudflare, not a deletion"). The correct answer is
# `unknown`, and it must be checked as such rather than suffered as a scoring error.
#
# These cases therefore prove that the crawler *refuses to conclude* when blocked. A
# regression that flipped them to `dead` would be the falsification the plan names as
# the fatal error.
WAF_CASES: list[tuple[str, str]] = [
    ("generic_url", "https://openalex.org/"),
    ("generic_url", "https://openalex.org/artifact-rot-absent-{t}"),
]

# --- `dead` cases: real hosts, namespaces guaranteed empty --------------------------
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

# --- `malformed` cases: broken from the start, evaluated offline ---------------------
MALFORMED_CASES: list[str] = [
    "https://github.com/",
    "https://github.com",
    "http://doi.org/notadoi",
    # NB: `https://doi. org/10.7939/…` was removed from this list after the first real
    # run. It is NOT a malformed link: it is a valid link broken by PDF extraction, which
    # `repair_spaced_hosts` rejoins — and must rejoin. Counting it `malformed` would have
    # made a successful repair look like a failure. The case is still tested, in its
    # proper place, in `tests/test_normalize.py::TestMetacheckBug2GrobidWhitespace`.
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
    """None for the `malformed` family, evaluated by `is_malformed` and not by a probe."""
    family: str
    provenance: str
    """How the truth is known. Makes the set auditable without trusting its author."""
    circular: bool = False
    """Does the truth come from the **same field** the probe reads?

    A Zenodo record declared `restricted` by the API, checked by a probe reading that
    same field, does not test judgement: it tests that the pipeline holds. Useful, but
    not the same thing, and a score that mixes the two overstates.

    The report therefore separates circular cases from the others. A GitHub repository
    taken down for legal reasons, by contrast, is non-circular: the truth comes from the
    public `github/dmca` register, a legal document, not from an HTTP code."""


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
                provenance="stable public resource, backed by a durable organisation",
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
                provenance="128-bit random namespace on a real host",
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
                provenance="syntactic invalidity, checked offline",
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
                provenance="host behind a web application firewall: the correct answer is unknown",
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
            circular=bool(entry.get("circular", False)),
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
                        "circular": case.circular,
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
                    "circular": case.circular,
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

    # A case whose truth comes from the same field the probe reads does not test
    # judgement: it tests that the pipeline holds. Mixing the two overstates the score.
    for family, f in families.items():
        rows = [r for r in results if r["family"] == family]
        circ = [r for r in rows if r.get("circular")]
        noncirc = [r for r in rows if not r.get("circular")]
        f["accuracy"] = f["correct"] / f["n"] if f["n"] else None
        f["n_circular"] = len(circ)
        f["accuracy_non_circular"] = (
            sum(r["correct"] for r in noncirc) / len(noncirc) if noncirc else None
        )

    # `waf` is not a required family: it is an added safeguard, not a §4 category. Its
    # absence does not invalidate the verdict; its failure does.
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
        # A verdict is issued only if all four families are present. A score computed on
        # an amputated set is not a score, it is window dressing.
        "verdict": (
            "incomplete"
            if missing
            else ("pass" if n and correct / n >= TARGET_ACCURACY else "fail")
        ),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.github_token:
        print(
            "warning: GITHUB_TOKEN not set. The anonymous quota (60 req/h) is not enough "
            "to replay the control set several times within an hour; GitHub cases will "
            "come back `unknown` without saying anything about their state.",
            file=sys.stderr,
        )

    report = run(build_cases(), settings)

    out_dir = Path("runs") / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-control"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "control.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"E2 control set — {report['n_cases']} cases — verdict: {report['verdict']}")
    for family, f in sorted(report["families"].items()):
        acc = f["accuracy"]
        line = f"  {family:<11} n={f['n']:<4} accuracy={acc:.3f}  unknown={f['unknown']}"
        if f.get("n_circular"):
            nc = f["accuracy_non_circular"]
            nc_txt = f"{nc:.3f}" if nc is not None else "n/a"
            line += f"  [{f['n_circular']} circular; excluding circular: {nc_txt}]"
        print(line)
        for err in f["errors"][:5]:
            print(f"      X {err['case_id']} {err['observed']:<10} {err['reason']}  {err['url']}")
    if report["missing_families"]:
        print(
            "  missing families: "
            + ", ".join(report["missing_families"])
            + " — no verdict issued (see docs/control-set.md)"
        )
    print(f"  report: {out_dir / 'control.json'}")

    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
