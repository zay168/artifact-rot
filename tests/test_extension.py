"""x3 extension of the grey zone (docs/extension.md)."""

from artifact_rot.harvest import BASE_N, pick, pick_extension
from artifact_rot.verdict import in_scope


def _sample(strata: int = 20, per: int = 2000) -> list[dict]:
    return [
        {"openalex_id": f"W{s}-{i}", "stratum": f"s{s:02d}"}
        for s in range(strata)
        for i in range(per)
    ]


def test_extension_disjoint_from_already_harvested_papers():
    rows = _sample()
    base = pick(rows, BASE_N)
    ext = pick_extension(rows, base)
    assert not {r["openalex_id"] for r in base} & {r["openalex_id"] for r in ext}


def test_extension_triples_the_per_stratum_count():
    rows = _sample()
    base = pick(rows, BASE_N)
    ext = pick_extension(rows, base)
    assert len(base) == 2000 and len(ext) == 4000
    per = {}
    for r in base + ext:
        per[r["stratum"]] = per.get(r["stratum"], 0) + 1
    assert set(per.values()) == {300}


def test_extension_reproducible():
    rows = _sample()
    base = pick(rows, BASE_N)
    assert pick_extension(rows, base) == pick_extension(rows, base)


def test_base_stays_the_same():
    """The extension must never change the draw of the 2,000 already probed."""
    rows = _sample()
    before = pick(rows, BASE_N)
    pick_extension(rows, before)
    assert pick(rows, BASE_N) == before


def test_artifacts_scope():
    assert in_scope({"kind": "code_repo"}, "artifacts")
    assert in_scope({"kind": "dataset_doi"}, "artifacts")
    assert not in_scope({"kind": "generic_url"}, "artifacts")
    assert in_scope({"kind": "generic_url"}, "all")


def test_french_scope_names_still_accepted():
    """Commands written down before the translation must keep working."""
    assert not in_scope({"kind": "generic_url"}, "artefacts")
    assert in_scope({"kind": "generic_url"}, "tout")
