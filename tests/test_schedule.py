"""E4 — scheduler: selection, spacing, budgets, resumption.

Resumption is tested because it is the stage's central promise: two weeks separate the
first probe from the last, and nothing guarantees the machine stays on. A scheduler that
loses its state forces starting over, which costs two more weeks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from artifact_rot.config import Settings
from artifact_rot.schedule import (
    MAX_ATTEMPTS,
    budget_of,
    connect,
    due,
    load_links,
    plan,
    should_probe,
    status_report,
)

SETTINGS = Settings(contact="test@exemple.org")
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "queue.sqlite3")
    yield c
    c.close()


def link_row(link_id: str, **over) -> dict:
    row = {
        "link_id": link_id,
        "normalized": "https://github.com/labo/projet",
        "host": "github.com",
        "kind": "code_repo",
        "source": "availability_statement",
        "stratum": "medicine-2018",
        "malformed_at_source": False,
    }
    row.update(over)
    return row


def write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "links.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def probe_row(conn, link_id: str, attempt: int, status: str, at: datetime) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO probes"
            "(link_id, attempt, probed_at, method, status, reason, evidence)"
            " VALUES (?,?,?,?,?,?,?)",
            (link_id, attempt, at.isoformat(), "api", status, "test", "{}"),
        )


class TestWhatGetsProbed:
    def test_an_artifact_link_is_probed(self) -> None:
        assert should_probe(link_row("a"))[0]

    def test_on_request_never_probed(self) -> None:
        """Pitfall 4: it is not a link."""
        keep, why = should_probe(link_row("a", kind="on_request"))
        assert not keep and why == "on_request"

    def test_cited_paper_doi_excluded(self) -> None:
        """Measuring the survival of the literature is not the subject, and a paper DOI
        does not die: the figure would be excellent and off-topic."""
        keep, why = should_probe(link_row("a", kind="citation_doi", host="doi.org"))
        assert not keep and why == "citation_doi"

    def test_citation_host_excluded(self) -> None:
        keep, why = should_probe(
            link_row(
                "a",
                host="pubmed.ncbi.nlm.nih.gov",
                normalized="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                kind="generic_url",
            )
        )
        assert not keep and why == "citation_host"

    def test_but_ncbi_data_is_kept(self) -> None:
        """NCBI also hosts real data: a nuccore link is an artifact."""
        keep, _ = should_probe(
            link_row(
                "a",
                host="ncbi.nlm.nih.gov",
                normalized="https://www.ncbi.nlm.nih.gov/nuccore/MN908947",
                kind="generic_url",
            )
        )
        assert keep

    def test_link_broken_at_source_never_probed(self) -> None:
        """Pitfall 3: it never worked, there is nothing to probe, and the result would be
        indistinguishable from a dead link."""
        keep, why = should_probe(link_row("a", malformed_at_source=True))
        assert not keep and why == "malformed_at_source"

    def test_non_http_scheme_excluded(self) -> None:
        keep, why = should_probe(link_row("a", normalized="mailto:auteur@labo.fr"))
        assert not keep and why == "non_http_scheme"

    def test_repository_cited_in_bibliography_kept(self) -> None:
        """The case measured by metacheck: 3% of papers cite their repository only there."""
        assert should_probe(link_row("a", source="references", host="zenodo.org"))[0]

    def test_paper_cited_in_bibliography_excluded(self) -> None:
        keep, why = should_probe(
            link_row("a", source="references", host="journals.plos.org", kind="generic_url")
        )
        assert not keep and why == "non_artifact_reference"


class TestSelection:
    def test_a_new_link_is_due(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        assert len(due(conn, SETTINGS, NOW)) == 1

    def test_a_live_link_is_no_longer_probed(self, conn, tmp_path: Path) -> None:
        """Deliberate saving: one live observation already wins (§5). Two more probes add
        nothing and account for most of the traffic."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "alive", NOW - timedelta(days=30))
        assert due(conn, SETTINGS, NOW) == []

    def test_a_restricted_link_is_no_longer_probed(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "restricted", NOW - timedelta(days=30))
        assert due(conn, SETTINGS, NOW) == []

    def test_spacing_respected(self, conn, tmp_path: Path) -> None:
        """"Three attempts several days apart, never in the same minute" (§4, pitfall 1)."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "dead", NOW - timedelta(hours=1))
        assert due(conn, SETTINGS, NOW) == []
        assert len(due(conn, SETTINGS, NOW + timedelta(days=6))) == 1

    def test_three_probes_are_enough(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        for i in range(1, MAX_ATTEMPTS + 1):
            probe_row(conn, "a", i, "dead", NOW - timedelta(days=30 - i * 6))
        assert due(conn, SETTINGS, NOW) == []

    def test_next_attempt_is_computed(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "dead", NOW - timedelta(days=30))
        assert due(conn, SETTINGS, NOW)[0].next_attempt == 2


class TestResumption:
    def test_reloading_erases_no_probe(self, conn, tmp_path: Path) -> None:
        path = write(tmp_path, [link_row("a")])
        load_links(conn, path)
        probe_row(conn, "a", 1, "dead", NOW - timedelta(days=30))
        load_links(conn, path)  # reload, as after a restart
        assert conn.execute("SELECT COUNT(*) AS n FROM probes").fetchone()["n"] == 1
        assert due(conn, SETTINGS, NOW)[0].next_attempt == 2

    def test_state_survives_closing(self, tmp_path: Path) -> None:
        """The queue is on disk: closing and reopening loses nothing."""
        path = tmp_path / "queue.sqlite3"
        c1 = connect(path)
        load_links(c1, write(tmp_path, [link_row("a"), link_row("b")]))
        probe_row(c1, "a", 1, "dead", NOW - timedelta(days=30))
        c1.close()

        c2 = connect(path)
        try:
            report = status_report(c2, SETTINGS)
            assert report["n_links"] == 2
            assert report["resolved"] == {"unknown": 1}
        finally:
            c2.close()


class TestBudgets:
    def test_a_github_link_costs_three_requests_at_worst(self, conn, tmp_path: Path) -> None:
        """Repository, owner, Software Heritage. A budget computed on the average is a
        budget exceeded one day out of two."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        estimate = plan(due(conn, SETTINGS, NOW))
        per_host = {h["host"]: h["requests"] for h in estimate["hosts"]}
        assert per_host["api.github.com"] == 2
        assert per_host["archive.softwareheritage.org"] == 1

    def test_budget_applies_to_the_receiving_host(self, conn, tmp_path: Path) -> None:
        """A github.com link hits api.github.com."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        hosts = {h["host"] for h in plan(due(conn, SETTINGS, NOW))["hosts"]}
        assert "api.github.com" in hosts
        assert "github.com" not in hosts

    def test_unknown_host_gets_default_budget(self) -> None:
        assert budget_of("labo.univ-exemple.fr") == budget_of("_default")

    def test_duration_is_a_duration_not_an_error(self, conn, tmp_path: Path) -> None:
        """A budget is an hourly rate. 500 requests at 200/h is 2.5 hours, not a
        forbidden pass."""
        rows = [
            link_row(
                f"l{i}",
                host="labo.fr",
                normalized=f"https://labo.fr/{i}",
                kind="generic_url",
                paper_id=f"W{i}",
            )
            for i in range(500)
        ]
        load_links(conn, write(tmp_path, rows))
        estimate = plan(due(conn, SETTINGS, NOW))
        expected = 500 / budget_of("labo.fr")
        assert estimate["estimated_hours"] == pytest.approx(expected, abs=0.01)
        assert estimate["hosts_over_hourly_budget"] or expected <= 1


class TestHostInterleaving:
    """Without interleaving, the pass lasts the sum of per-host times instead of the
    maximum.

    875 NCBI links at 200 requests/hour take 4.4 hours. If they follow one another, we wait
    4.4 hours before touching the first link of the second host. By interleaving, we query
    the other hosts while waiting for NCBI.
    """

    def test_hosts_alternate(self, conn, tmp_path: Path) -> None:
        rows = [
            link_row(f"a{i}", host="gros.fr", normalized=f"https://gros.fr/{i}")
            for i in range(10)
        ] + [
            link_row(f"b{i}", host="petit.fr", normalized=f"https://petit.fr/{i}")
            for i in range(3)
        ]
        load_links(conn, write(tmp_path, rows))
        hosts = [item.host for item in due(conn, SETTINGS, NOW)]
        # The small host must be served early, not after the big one's ten.
        assert "petit.fr" in hosts[:6]

    def test_nothing_is_lost(self, conn, tmp_path: Path) -> None:
        rows = [
            link_row(f"a{i}", host=f"h{i % 4}.fr", normalized=f"https://h{i % 4}.fr/{i}")
            for i in range(20)
        ]
        load_links(conn, write(tmp_path, rows))
        got = due(conn, SETTINGS, NOW)
        assert len(got) == 20
        assert len({item.link_id for item in got}) == 20


class TestSiteFurniture:
    """A rule, not a blocklist — it must keep working on another corpus, with the
    furniture of sites other than those already encountered."""

    def test_url_repeated_across_disciplines_is_discarded(self, conn, tmp_path: Path) -> None:
        rows = [
            link_row(
                f"c{i}",
                normalized="https://browsehappy.com/",
                host="browsehappy.com",
                kind="generic_url",
                paper_id=f"W{i}",
                discipline=("medicine", "physics_astronomy", "social_sciences")[i % 3],
            )
            for i in range(6)
        ]
        counts = load_links(conn, write(tmp_path, rows))
        assert counts.get("site_furniture") == 6
        assert due(conn, SETTINGS, NOW) == []

    def test_a_repeated_repository_is_kept(self, conn, tmp_path: Path) -> None:
        """A dataset can be reused by several teams. The rule must not mistake it for
        furniture — hence the exemption for artifact hosts."""
        rows = [
            link_row(
                f"z{i}",
                normalized="https://zenodo.org/records/3509134",
                host="zenodo.org",
                kind="data_repo",
                paper_id=f"W{i}",
                discipline=("medicine", "physics_astronomy", "social_sciences")[i % 3],
            )
            for i in range(6)
        ]
        load_links(conn, write(tmp_path, rows))
        assert len(due(conn, SETTINGS, NOW)) == 6

    def test_a_single_discipline_url_is_kept(self, conn, tmp_path: Path) -> None:
        rows = [
            link_row(
                f"d{i}",
                normalized="https://labo.fr/donnees",
                host="labo.fr",
                kind="generic_url",
                paper_id=f"W{i}",
                discipline="medicine",
            )
            for i in range(6)
        ]
        load_links(conn, write(tmp_path, rows))
        assert len(due(conn, SETTINGS, NOW)) == 6


class TestRateLimiter:
    def test_a_host_is_spaced(self) -> None:
        import time

        from artifact_rot.limiter import HostRateLimiter

        # Deliberately wide interval: `time.sleep` granularity on Windows is about 15 ms,
        # and a tight threshold would make the test flaky for a reason unrelated to what
        # it checks.
        interval, n = 0.1, 4
        limiter = HostRateLimiter(lambda _host: interval)
        start = time.monotonic()
        for _ in range(n):
            limiter.acquire("a.fr")
        assert time.monotonic() - start >= interval * (n - 1) * 0.8

    def test_two_hosts_do_not_wait_for_each_other(self) -> None:
        """The point of the whole optimisation: waiting for host A must cost host B
        nothing."""
        import time

        from artifact_rot.limiter import HostRateLimiter

        limiter = HostRateLimiter(lambda _host: 0.2)
        limiter.acquire("a.fr")
        start = time.monotonic()
        limiter.acquire("b.fr")
        assert time.monotonic() - start < 0.05


class TestRepositoryCitedInBibliography:
    """3% of papers cite their repository only in their bibliography (metacheck issue
    #411). Losing them through a test on the wrong field would be silent."""

    def test_zenodo_doi_in_bibliography_kept(self) -> None:
        keep, _ = should_probe(
            link_row(
                "a",
                source="references",
                host="doi.org",
                kind="data_repo",
                normalized="https://doi.org/10.5281/zenodo.1070901",
            )
        )
        assert keep

    def test_dataset_doi_in_bibliography_kept(self) -> None:
        keep, _ = should_probe(
            link_row(
                "a",
                source="references",
                host="doi.org",
                kind="dataset_doi",
                normalized="https://doi.org/10.6084/m9.figshare.1",
            )
        )
        assert keep

    def test_paper_doi_in_bibliography_discarded(self) -> None:
        keep, why = should_probe(
            link_row(
                "a",
                source="references",
                host="doi.org",
                kind="citation_doi",
                normalized="https://doi.org/10.1371/journal.pone.1",
            )
        )
        assert not keep and why == "citation_doi"
