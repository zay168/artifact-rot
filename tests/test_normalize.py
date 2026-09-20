"""Regressions nommees, issues des modes d'echec mesures par metacheck (issue #411).

Chaque test porte le nom du mode d'echec qu'il interdit. Voir docs/etat-de-lart.md §2.2.
"""

from __future__ import annotations

import pytest

from artifact_rot.extract.normalize import (
    FIGSHARE_ID,
    canonicalize,
    dedupe,
    is_malformed,
    is_on_request,
    kind_of,
    repair_spaced_hosts,
)


class TestMetacheckBug2GrobidWhitespace:
    """85 % des articles du corpus Cooper contiennent des URL coupees par GROBID."""

    @pytest.mark.parametrize(
        ("broken", "expected"),
        [
            ("https://doi. org/10.7939/DVN/QYMAYV", "https://doi.org/10.7939/DVN/QYMAYV"),
            ("https://github. com/owner/repo", "https://github.com/owner/repo"),
            ("https :// zenodo.org/records/123", "https://zenodo.org/records/123"),
            ("https://osf. io/ezcuj", "https://osf.io/ezcuj"),
        ],
    )
    def test_recolle_les_hotes_coupes(self, broken: str, expected: str) -> None:
        assert repair_spaced_hosts(broken) == expected

    def test_ne_recolle_pas_deux_phrases(self) -> None:
        """Recoller trop large inventerait des liens — pire que d'en manquer."""
        text = "Voir https://example.org/data. Les auteurs remercient le laboratoire."
        assert repair_spaced_hosts(text) == text


class TestMetacheckBug3FigsharePattern:
    """`/articles/<slug>/<id>` renvoyait NA dans metacheck."""

    def test_motif_sans_type_de_ressource(self) -> None:
        m = FIGSHARE_ID.search("https://figshare.com/articles/my_dataset/9885334")
        assert m is not None and m.group(1) == "9885334"

    def test_motif_avec_type_de_ressource(self) -> None:
        m = FIGSHARE_ID.search("https://figshare.com/articles/dataset/my_dataset/9885334")
        assert m is not None and m.group(1) == "9885334"


class TestCanonicalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://www.github.com/owner/repo/", "https://github.com/owner/repo"),
            ("github.com/owner/repo", "https://github.com/owner/repo"),
            ("https://example.org/d?utm_source=x&id=7", "https://example.org/d?id=7"),
            ("https://example.org/data.", "https://example.org/data"),
            ("doi:10.1371/journal.pone.0304781", "https://doi.org/10.1371/journal.pone.0304781"),
            ("10.1371/journal.pone.0304781", "https://doi.org/10.1371/journal.pone.0304781"),
        ],
    )
    def test_formes_equivalentes(self, raw: str, expected: str) -> None:
        assert canonicalize(raw) == expected

    def test_dedupe_conserve_l_ordre_du_texte(self) -> None:
        urls = [
            "https://github.com/a/b",
            "http://www.github.com/a/b/",
            "https://zenodo.org/records/1",
        ]
        assert dedupe(urls) == ["https://github.com/a/b", "https://zenodo.org/records/1"]


class TestPiege4OnRequest:
    """« Disponible sur demande » n'est ni mort ni vivant : il n'est pas un lien."""

    @pytest.mark.parametrize(
        "statement",
        [
            "Data are available from the corresponding author upon reasonable request.",
            "The dataset is available upon request.",
            "Please contact the corresponding author for access.",
            "Les donnees sont disponibles sur demande raisonnable.",
        ],
    )
    def test_detecte(self, statement: str) -> None:
        assert is_on_request(statement)

    @pytest.mark.parametrize(
        "statement",
        [
            "All data are available at https://zenodo.org/records/3509134.",
            "Code is deposited in the repository listed below.",
        ],
    )
    def test_ne_declenche_pas_a_tort(self, statement: str) -> None:
        assert not is_on_request(statement)


class TestPiege3MalformedAtSource:
    """Casse des la publication != mort apres avoir vecu. Deux chiffres, jamais additionnes."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/",
            "http://doi.org/notadoi",
            "https://.com/owner/repo",
            "https://-badhost.org/data",
            "https://localhost/data",
            "https://github.com/owner repo",
        ],
    )
    def test_casse(self, url: str) -> None:
        assert is_malformed(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo",
            "https://doi.org/10.1371/journal.pone.0304781",
            "https://zenodo.org/records/3509134",
            # Bien forme mais pointant nulle part : c'est `dead`, pas `malformed`.
            "https://github.com/artifact-rot-absent-0000/repo-0000",
        ],
    )
    def test_bien_forme(self, url: str) -> None:
        assert not is_malformed(url)


class TestKind:
    @pytest.mark.parametrize(
        ("url", "kind"),
        [
            ("https://github.com/a/b", "code_repo"),
            ("https://gitlab.com/a/b", "code_repo"),
            ("https://zenodo.org/records/1", "data_repo"),
            ("https://osf.io/ezcuj", "data_repo"),
            ("https://doi.org/10.5281/zenodo.123", "data_repo"),
            ("https://doi.org/10.1371/journal.pone.1", "dataset_doi"),
            ("https://lab.univ.fr/data", "generic_url"),
        ],
    )
    def test_classement(self, url: str, kind: str) -> None:
        assert kind_of(url) == kind
