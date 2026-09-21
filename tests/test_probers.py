"""Routage des sondes et heuristiques de soft-404, testes hors ligne.

Le routage est teste parce qu'une erreur d'aiguillage envoie un lien GitHub vers la
sonde HTTP generique, qui lira du HTML — exactement ce que le §4 interdit.
"""

from __future__ import annotations

import pytest

from artifact_rot.extract.normalize import canonicalize, host_of, kind_of
from artifact_rot.models import Link
from artifact_rot.probe import default_registry
from artifact_rot.probe.http_generic import (
    SOFT404_SIMILARITY,
    _redirected_to_root,
    _similarity,
    _title_of,
)


def link(url: str) -> Link:
    n = canonicalize(url)
    return Link(
        paper_id="W0000000000",
        paper_year=2020,
        discipline="test",
        publisher="test",
        raw=url,
        normalized=n,
        kind=kind_of(n),  # type: ignore[arg-type]
        host=host_of(n),
    )


class TestRoutage:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/owner/repo", "github"),
            ("https://github.com/owner/repo/blob/main/data.csv", "github"),
            ("https://gitlab.com/group/sub/project", "gitlab"),
            ("https://bitbucket.org/owner/repo", "bitbucket"),
            ("https://zenodo.org/records/3509134", "zenodo"),
            ("https://doi.org/10.5281/zenodo.3509134", "zenodo"),
            ("https://osf.io/ezcuj/", "osf"),
            ("https://figshare.com/articles/dataset/name/9885334", "figshare"),
            ("https://doi.org/10.1371/journal.pone.0304781", "doi"),
            ("https://lab.univ-exemple.fr/donnees/", "http_generic"),
        ],
    )
    def test_selection(self, url: str, expected: str) -> None:
        assert default_registry().select(link(url)).name == expected

    def test_les_api_passent_avant_le_html(self) -> None:
        """Invariant du §4 : aucun hote a API ne doit tomber sur la sonde generique."""
        registry = default_registry()
        for url in (
            "https://github.com/a/b",
            "https://zenodo.org/records/1",
            "https://osf.io/abcde",
            "https://doi.org/10.1234/abc",
        ):
            assert registry.select(link(url)).method == "api"


class TestSoft404:
    def test_redirection_vers_la_racine(self) -> None:
        assert _redirected_to_root("https://lab.fr/donnees/set1", "https://lab.fr/")

    def test_redirection_interne_legitime(self) -> None:
        assert not _redirected_to_root("https://lab.fr/donnees", "https://lab.fr/donnees/v2")

    def test_racine_vers_racine_n_est_pas_un_signal(self) -> None:
        assert not _redirected_to_root("https://lab.fr/", "https://lab.fr/")

    def test_deux_pages_d_erreur_identiques_au_bruit_pres(self) -> None:
        a = "<html><title>Not Found</title><body>Request id 8f3a91bc2d id 4412</body></html>"
        b = "<html><title>Not Found</title><body>Request id 11de77aa90 id 9930</body></html>"
        assert _similarity(a, b) >= SOFT404_SIMILARITY

    def test_une_vraie_page_differe_de_la_page_d_erreur(self) -> None:
        page = "<html><title>Dataset: soil cores 2014</title><body>Download 1.2 GB NetCDF</body></html>"
        err = "<html><title>Not Found</title><body>The page you requested does not exist</body></html>"
        assert _similarity(page, err) < SOFT404_SIMILARITY

    def test_extraction_du_titre(self) -> None:
        assert _title_of("<html><TITLE> Page Not Found </TITLE></html>") == "Page Not Found"
        assert _title_of("<html><body>rien</body></html>") is None


class TestJeuDeControle:
    def test_reproductible_a_graine_fixe(self) -> None:
        from artifact_rot.control import build_cases

        a = [c.url for c in build_cases()]
        b = [c.url for c in build_cases()]
        assert a == b

    def test_les_cas_morts_sont_bien_formes(self) -> None:
        """Un cas `dead` mal forme testerait `is_malformed`, pas la sonde."""
        from artifact_rot.control import build_cases
        from artifact_rot.extract.normalize import is_malformed

        for case in build_cases():
            if case.family == "dead":
                assert not is_malformed(case.url), case.url

    def test_verdict_non_emis_si_une_famille_manque(self) -> None:
        """Annoncer 98 % en omettant `restricted` serait une mise en scene."""
        from artifact_rot.control import _score

        report = _score(
            [
                {"family": "alive", "case_id": "a", "url": "u", "observed": "alive", "correct": True, "reason": "r"},
                {"family": "dead", "case_id": "d", "url": "u", "observed": "dead", "correct": True, "reason": "r"},
                {"family": "malformed", "case_id": "m", "url": "u", "observed": "malformed", "correct": True, "reason": "r"},
            ]
        )
        assert report["verdict"] == "incomplet"
        assert report["missing_families"] == ["restricted"]


class TestDNS:
    """Un nom de domaine qui n'existe plus est une reponse, pas un echec du crawler.

    Decision prise le 2026-09-21, avant la passe 3 et donc avant d'avoir vu le moindre
    resultat final — le seul moment ou elle peut etre prise sans soupcon.
    """

    def test_nom_inexistant(self) -> None:
        from artifact_rot.probe.dns import resolve

        assert resolve("absent-" + "z" * 24 + "-artifact-rot.invalid") == "nxdomain"

    def test_nom_vide_ne_leve_pas(self) -> None:
        from artifact_rot.probe.dns import resolve

        assert resolve("") == "unknown"

    def test_les_codes_temporaires_ne_sont_pas_nxdomain(self) -> None:
        """Le garde-fou central : une panne de resolveur ne doit pas produire un mort."""
        import socket

        from artifact_rot.probe import dns

        assert socket.EAI_NONAME in dns._NXDOMAIN_ERRNOS
        assert socket.EAI_NONAME not in dns._TRANSIENT_ERRNOS
        for name in ("EAI_AGAIN", "EAI_FAIL"):
            code = getattr(socket, name, None)
            if code is not None:
                assert code not in dns._NXDOMAIN_ERRNOS, name

    def test_memorisation(self) -> None:
        from artifact_rot.probe.dns import _cache, reset_cache, resolve

        reset_cache()
        host = "absent-" + "y" * 24 + "-artifact-rot.invalid"
        resolve(host)
        assert host in _cache
        reset_cache()
        assert host not in _cache


class TestTldInvalide:
    """`arcjournals.or` : un `.org` tronque a l'extraction, pas un site disparu.

    Le compter mort ajouterait au taux de mortalite un lien qui n'a jamais existe — et
    dans le sens qui arrange la these du projet.
    """

    def test_tld_absent_de_l_iana(self) -> None:
        from artifact_rot.extract.normalize import is_malformed

        assert is_malformed("https://arcjournals.or/article/12")

    def test_tld_valide(self) -> None:
        from artifact_rot.extract.normalize import is_malformed

        assert not is_malformed("https://arcjournals.org/article/12")

    def test_la_liste_est_chargee(self) -> None:
        from artifact_rot.extract.normalize import VALID_TLDS

        assert len(VALID_TLDS) > 1000
        assert "org" in VALID_TLDS and "fr" in VALID_TLDS
        assert "or" not in VALID_TLDS
