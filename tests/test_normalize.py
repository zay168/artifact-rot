"""Named regressions, from the failure modes measured by metacheck (issue #411).

Each test bears the name of the failure mode it forbids. See docs/related-work.md §2.2.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from artifact_rot.extract.normalize import (
    FIGSHARE_ID,
    canonicalize,
    dedupe,
    host_of,
    is_malformed,
    is_on_request,
    kind_of,
    repair_spaced_hosts,
)


class TestMetacheckBug2GrobidWhitespace:
    """85% of the papers in the Cooper corpus contain URLs split by GROBID."""

    @pytest.mark.parametrize(
        ("broken", "expected"),
        [
            ("https://doi. org/10.7939/DVN/QYMAYV", "https://doi.org/10.7939/DVN/QYMAYV"),
            ("https://github. com/owner/repo", "https://github.com/owner/repo"),
            ("https :// zenodo.org/records/123", "https://zenodo.org/records/123"),
            ("https://osf. io/ezcuj", "https://osf.io/ezcuj"),
        ],
    )
    def test_rejoins_split_hosts(self, broken: str, expected: str) -> None:
        assert repair_spaced_hosts(broken) == expected

    def test_does_not_join_two_sentences(self) -> None:
        """Rejoining too broadly would invent links — worse than missing some."""
        text = "See https://example.org/data. The authors thank the laboratory."
        assert repair_spaced_hosts(text) == text


class TestMetacheckBug3FigsharePattern:
    """`/articles/<slug>/<id>` returned NA in metacheck."""

    def test_pattern_without_resource_type(self) -> None:
        m = FIGSHARE_ID.search("https://figshare.com/articles/my_dataset/9885334")
        assert m is not None and m.group(1) == "9885334"

    def test_pattern_with_resource_type(self) -> None:
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
    def test_equivalent_forms(self, raw: str, expected: str) -> None:
        assert canonicalize(raw) == expected

    def test_dedupe_keeps_text_order(self) -> None:
        urls = [
            "https://github.com/a/b",
            "http://www.github.com/a/b/",
            "https://zenodo.org/records/1",
        ]
        assert dedupe(urls) == ["https://github.com/a/b", "https://zenodo.org/records/1"]


class TestPitfall4OnRequest:
    """"Available on request" is neither dead nor alive: it is not a link."""

    @pytest.mark.parametrize(
        "statement",
        [
            "Data are available from the corresponding author upon reasonable request.",
            "The dataset is available upon request.",
            "Please contact the corresponding author for access.",
            "Les donnees sont disponibles sur demande raisonnable.",  # French, supported
        ],
    )
    def test_detected(self, statement: str) -> None:
        assert is_on_request(statement)

    @pytest.mark.parametrize(
        "statement",
        [
            "All data are available at https://zenodo.org/records/3509134.",
            "Code is deposited in the repository listed below.",
        ],
    )
    def test_does_not_fire_wrongly(self, statement: str) -> None:
        assert not is_on_request(statement)


class TestPitfall3MalformedAtSource:
    """Broken from publication != dead after having lived. Two figures, never added."""

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
    def test_broken(self, url: str) -> None:
        assert is_malformed(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo",
            "https://doi.org/10.1371/journal.pone.0304781",
            "https://zenodo.org/records/3509134",
            # Well-formed but pointing nowhere: that is `dead`, not `malformed`.
            "https://github.com/artifact-rot-absent-0000/repo-0000",
        ],
    )
    def test_well_formed(self, url: str) -> None:
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
            ("https://lab.univ.fr/data", "generic_url"),
            # Data repository agency prefixes: real artifacts.
            ("https://doi.org/10.6084/m9.figshare.9885334", "dataset_doi"),
            ("https://doi.org/10.17605/OSF.IO/ABCDE", "dataset_doi"),
            ("https://doi.org/10.7910/DVN/XYZ", "dataset_doi"),
            ("https://doi.org/10.17182/hepdata.77284", "dataset_doi"),
            # DOIs of cited papers: references, not artifacts.
            ("https://doi.org/10.1371/journal.pone.1", "citation_doi"),
            ("https://doi.org/10.1038/s41586-020-2649-2", "citation_doi"),
            ("https://dx.doi.org/10.1016/j.cell.2020.01.001", "citation_doi"),
        ],
    )
    def test_classification(self, url: str, kind: str) -> None:
        assert kind_of(url) == kind

    def test_an_unknown_doi_is_a_citation_not_a_dataset(self) -> None:
        """When in doubt, a DOI is a citation. A missed repository is a loss; a paper
        counted as a dataset is a mistake."""
        assert kind_of("https://doi.org/10.99999/unknown.2026.1") == "citation_doi"


class TestHostileUrls:
    """Real URLs that made the standard library raise.

    Encountered on 2026-09-20 in the corpus: the recall computation stopped dead on a lone
    `[` ("Invalid IPv6 URL"). A paper's URL is a string found in a PDF: it can be
    anything, and no function in this module may raise because of it.
    """

    HOSTILES: ClassVar[list[str]] = [
        "https://exemple.org/[truc]",
        "https://[pas-une-ipv6/data",
        "https://ex]emple.org/x",
        "https://",
        "http://[",
        "https://a b c",
        "",
    ]

    @pytest.mark.parametrize("url", HOSTILES)
    def test_host_of_never_raises(self, url: str) -> None:
        assert isinstance(host_of(url), str)

    @pytest.mark.parametrize("url", HOSTILES)
    def test_canonicalize_never_raises(self, url: str) -> None:
        assert isinstance(canonicalize(url), str)

    @pytest.mark.parametrize("url", HOSTILES)
    def test_is_malformed_never_raises(self, url: str) -> None:
        assert isinstance(is_malformed(url), bool)

    @pytest.mark.parametrize("url", HOSTILES)
    def test_kind_of_never_raises(self, url: str) -> None:
        assert isinstance(kind_of(url), str)
