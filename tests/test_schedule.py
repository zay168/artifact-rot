"""E4 — ordonnanceur : selection, espacement, budgets, reprise.

La reprise est testee parce que c'est la promesse centrale de l'etape : deux semaines
separent la premiere sonde de la derniere, et rien ne garantit que la machine reste
allumee. Un ordonnanceur qui perd son etat oblige a tout recommencer, ce qui coute
deux semaines de plus.
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


class TestCeQuOnSonde:
    def test_un_lien_d_artefact_est_sonde(self) -> None:
        assert should_probe(link_row("a"))[0]

    def test_sur_demande_jamais_sonde(self) -> None:
        """Piege 4 : ce n'est pas un lien."""
        keep, why = should_probe(link_row("a", kind="on_request"))
        assert not keep and why == "on_request"

    def test_doi_d_article_cite_exclu(self) -> None:
        """Mesurer la survie de la litterature n'est pas le sujet, et un DOI d'article
        ne meurt pas : le chiffre serait excellent et hors sujet."""
        keep, why = should_probe(link_row("a", kind="citation_doi", host="doi.org"))
        assert not keep and why == "citation_doi"

    def test_hote_bibliographique_exclu(self) -> None:
        keep, why = should_probe(
            link_row(
                "a",
                host="pubmed.ncbi.nlm.nih.gov",
                normalized="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                kind="generic_url",
            )
        )
        assert not keep and why == "hote_bibliographique"

    def test_mais_les_donnees_du_ncbi_restent(self) -> None:
        """Le NCBI heberge aussi de vraies donnees : un lien nuccore est un artefact."""
        keep, _ = should_probe(
            link_row(
                "a",
                host="ncbi.nlm.nih.gov",
                normalized="https://www.ncbi.nlm.nih.gov/nuccore/MN908947",
                kind="generic_url",
            )
        )
        assert keep

    def test_lien_casse_a_la_source_jamais_sonde(self) -> None:
        """Piege 3 : il n'a jamais fonctionne, il n'y a rien a sonder, et le resultat
        serait indiscernable d'un lien mort."""
        keep, why = should_probe(link_row("a", malformed_at_source=True))
        assert not keep and why == "malformed_at_source"

    def test_schema_non_http_exclu(self) -> None:
        keep, why = should_probe(link_row("a", normalized="mailto:auteur@labo.fr"))
        assert not keep and why == "schema_non_http"

    def test_depot_cite_en_bibliographie_conserve(self) -> None:
        """Le cas mesure par metacheck : 3 % des articles ne citent leur depot que la."""
        assert should_probe(link_row("a", source="references", host="zenodo.org"))[0]

    def test_article_cite_en_bibliographie_exclu(self) -> None:
        keep, why = should_probe(
            link_row("a", source="references", host="journals.plos.org", kind="generic_url")
        )
        assert not keep and why == "reference_non_artefact"


class TestSelection:
    def test_un_lien_neuf_est_du(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        assert len(due(conn, SETTINGS, NOW)) == 1

    def test_un_lien_vivant_n_est_plus_sonde(self, conn, tmp_path: Path) -> None:
        """Economie assumee : une observation vivante l'emporte deja (§5). Deux sondes
        de plus n'ajoutent rien et representent l'essentiel du trafic."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "alive", NOW - timedelta(days=30))
        assert due(conn, SETTINGS, NOW) == []

    def test_un_lien_restreint_n_est_plus_sonde(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "restricted", NOW - timedelta(days=30))
        assert due(conn, SETTINGS, NOW) == []

    def test_espacement_respecte(self, conn, tmp_path: Path) -> None:
        """« Trois tentatives espacees de plusieurs jours, jamais dans la meme
        minute » (§4, piege 1)."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "dead", NOW - timedelta(hours=1))
        assert due(conn, SETTINGS, NOW) == []
        assert len(due(conn, SETTINGS, NOW + timedelta(days=6))) == 1

    def test_trois_sondes_suffisent(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        for i in range(1, MAX_ATTEMPTS + 1):
            probe_row(conn, "a", i, "dead", NOW - timedelta(days=30 - i * 6))
        assert due(conn, SETTINGS, NOW) == []

    def test_l_attempt_suivant_est_calcule(self, conn, tmp_path: Path) -> None:
        load_links(conn, write(tmp_path, [link_row("a")]))
        probe_row(conn, "a", 1, "dead", NOW - timedelta(days=30))
        assert due(conn, SETTINGS, NOW)[0].next_attempt == 2


class TestReprise:
    def test_recharger_n_efface_aucune_sonde(self, conn, tmp_path: Path) -> None:
        path = write(tmp_path, [link_row("a")])
        load_links(conn, path)
        probe_row(conn, "a", 1, "dead", NOW - timedelta(days=30))
        load_links(conn, path)  # rechargement, comme apres un redemarrage
        assert conn.execute("SELECT COUNT(*) AS n FROM probes").fetchone()["n"] == 1
        assert due(conn, SETTINGS, NOW)[0].next_attempt == 2

    def test_l_etat_survit_a_la_fermeture(self, tmp_path: Path) -> None:
        """La file est sur disque : fermer et rouvrir ne perd rien."""
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
    def test_un_lien_github_coute_trois_requetes_au_pire(self, conn, tmp_path: Path) -> None:
        """Depot, proprietaire, Software Heritage. Un budget calcule sur la moyenne est
        un budget depasse un jour sur deux."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        estimate = plan(due(conn, SETTINGS, NOW))
        per_host = {h["host"]: h["requests"] for h in estimate["hosts"]}
        assert per_host["api.github.com"] == 2
        assert per_host["archive.softwareheritage.org"] == 1

    def test_le_budget_porte_sur_l_hote_qui_recoit(self, conn, tmp_path: Path) -> None:
        """Un lien github.com frappe api.github.com."""
        load_links(conn, write(tmp_path, [link_row("a")]))
        hosts = {h["host"] for h in plan(due(conn, SETTINGS, NOW))["hosts"]}
        assert "api.github.com" in hosts
        assert "github.com" not in hosts

    def test_hote_inconnu_recoit_le_budget_par_defaut(self) -> None:
        assert budget_of("labo.univ-exemple.fr") == budget_of("_default")

    def test_la_duree_est_une_duree_pas_une_erreur(self, conn, tmp_path: Path) -> None:
        """Un budget est un debit horaire. 500 requetes a 200/h, c'est 2,5 heures, pas
        une passe interdite."""
        rows = [
            link_row(
                f"l{i}", host="labo.fr", normalized=f"https://labo.fr/{i}", kind="generic_url"
            )
            for i in range(500)
        ]
        load_links(conn, write(tmp_path, rows))
        estimate = plan(due(conn, SETTINGS, NOW))
        assert estimate["estimated_hours"] == pytest.approx(2.5, abs=0.01)
