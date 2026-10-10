"""Link extraction from full text (E3)."""

from __future__ import annotations

import pytest

from artifact_rot.extract.links import (
    count_on_request,
    extract_links,
    is_artifact_link,
    is_boilerplate,
    iter_raw_links,
)

PAPER = {
    "paper_id": "W123",
    "paper_doi": "10.1371/journal.pone.1",
    "paper_year": 2018,
    "discipline": "medicine",
    "publisher": "PLOS",
}


class TestBoilerplate:
    @pytest.mark.parametrize(
        "url",
        [
            "https://creativecommons.org/licenses/by/4.0/",
            "http://crossmark.crossref.org/dialog/?doi=10.1371/x&domain=pdf",
            "https://orcid.org/0000-0002-1825-0097",
            "https://twitter.com/labo",
            "https://www.researchgate.net/profile/X",
            "https://cdn.exemple.org/logo.png",
        ],
    )
    def test_discards_editorial_production_links(self, url: str) -> None:
        """Present in almost every PDF. Counting them would inflate the denominator with
        links whose survival interests nobody."""
        assert is_boilerplate(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/labo/projet",
            "https://zenodo.org/records/3509134",
            "https://doi.org/10.5281/zenodo.3509134",
        ],
    )
    def test_leaves_artifacts_alone(self, url: str) -> None:
        assert not is_boilerplate(url)
        assert is_artifact_link(url)

    def test_a_lab_url_is_not_a_recognised_artifact(self) -> None:
        """It is still extracted and probed; it simply does not count towards recall."""
        assert not is_artifact_link("https://labo.univ-exemple.fr/donnees/")


class TestTextExtraction:
    def test_url_and_bare_doi(self) -> None:
        text = "Code: https://github.com/labo/p. Data: doi:10.5281/zenodo.123."
        found = [url for _, url in iter_raw_links(text)]
        assert "https://github.com/labo/p" in found
        assert "https://doi.org/10.5281/zenodo.123" in found

    def test_url_split_by_pdf_is_rejoined(self) -> None:
        """metacheck failure mode no. 2, on the real extraction path."""
        text = "See https://doi. org/10.7939/DVN/QYMAYV for the data."
        found = [url for _, url in iter_raw_links(text)]
        assert "https://doi.org/10.7939/DVN/QYMAYV" in found

    def test_trailing_punctuation_removed(self) -> None:
        links = extract_links("Data: https://zenodo.org/records/42.", **PAPER)
        assert links[0].normalized == "https://zenodo.org/records/42"

    def test_provenance_carried_by_the_link(self) -> None:
        text = (
            "Introduction\nSee https://github.com/x/corps.\n\n"
            "Data Availability\nData: https://zenodo.org/records/7.\n\n"
            "References\n1. https://github.com/y/cite\n"
        )
        by_host = {link.normalized: link.source for link in extract_links(text, **PAPER)}
        assert by_host["https://github.com/x/corps"] == "body"
        assert by_host["https://zenodo.org/records/7"] == "availability_statement"
        assert by_host["https://github.com/y/cite"] == "references"

    def test_deduplication(self) -> None:
        text = "https://github.com/a/b and http://www.github.com/a/b/ are the same repository."
        assert len(extract_links(text, **PAPER)) == 1

    def test_union_with_markup(self) -> None:
        """Annotations carry links that hyphenation makes the text lose, and the text
        carries links the publisher did not tag. We take the union."""
        links = extract_links(
            "Code: https://github.com/labo/depuis-le-texte.",
            structured_urls=["https://zenodo.org/records/999"],
            **PAPER,
        )
        normalized = {link.normalized for link in links}
        assert "https://github.com/labo/depuis-le-texte" in normalized
        assert "https://zenodo.org/records/999" in normalized

    def test_markup_links_have_body_provenance(self) -> None:
        """An annotation does not say which section it is in."""
        links = extract_links("Text.", structured_urls=["https://osf.io/abcde"], **PAPER)
        assert links[0].source == "body"

    def test_stable_identifier(self) -> None:
        a = extract_links("https://github.com/a/b", **PAPER)[0]
        b = extract_links("http://www.github.com/a/b/", **PAPER)[0]
        assert a.link_id == b.link_id


class TestOnRequest:
    def test_counted_in_the_statement(self) -> None:
        text = (
            "Data Availability\n"
            "Data are available from the corresponding author upon reasonable request.\n"
        )
        assert count_on_request(text) == 1

    def test_not_counted_outside_a_statement(self) -> None:
        """The phrase also appears in unrelated contexts."""
        text = "Introduction\nLes reactifs ont ete fournis sur demande du comite.\n"
        assert count_on_request(text) == 0

    def test_a_statement_with_a_link_is_not_on_request(self) -> None:
        text = "Data Availability\nAll data are at https://zenodo.org/records/1.\n"
        assert count_on_request(text) == 0


class TestHostileText:
    """Nothing that comes out of a PDF may bring the pipeline down.

    Encountered on 2026-09-20: harvesting died after 200 papers on
    `UnicodeEncodeError: surrogates not allowed`. A PDF font with an inconsistent
    character table produces lone surrogates, which Python accepts in memory but no UTF-8
    encoder accepts.
    """

    def test_lone_surrogates_are_neutralised(self) -> None:
        from artifact_rot.fulltext import sanitize

        hostile = "Data 𐀀 available \udfff here"
        cleaned = sanitize(hostile)
        cleaned.encode("utf-8")  # must not raise
        assert "Data" in cleaned and "available" in cleaned

    def test_normal_text_is_intact(self) -> None:
        from artifact_rot.fulltext import sanitize

        text = "Données disponibles à https://zenodo.org/records/1 — accès libre ✓"
        assert sanitize(text) == text

    def test_extraction_on_sanitised_text(self) -> None:
        from artifact_rot.fulltext import sanitize

        text = sanitize("Code: https://github.com/labo/p \ud800 end.")
        links = extract_links(text, **PAPER)
        assert any(link.host == "github.com" for link in links)


class TestDurableCache:
    """A two-week run must not be poisoned by its own interruption.

    On 2026-09-20, a run died mid-write and left a truncated file. The next run read it
    back and died on it in turn.
    """

    def test_a_corrupt_entry_counts_as_absent(self, tmp_path, monkeypatch) -> None:
        from artifact_rot import fulltext

        monkeypatch.setattr(fulltext, "CACHE_DIR", tmp_path)
        path = fulltext.cache_path("W42")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"paper_id": "W42", "text": "trun', encoding="utf-8")
        assert fulltext.load("W42") is None

    def test_an_empty_entry_counts_as_absent(self, tmp_path, monkeypatch) -> None:
        from artifact_rot import fulltext

        monkeypatch.setattr(fulltext, "CACHE_DIR", tmp_path)
        path = fulltext.cache_path("W43")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        assert fulltext.load("W43") is None

    def test_round_trip(self, tmp_path, monkeypatch) -> None:
        from artifact_rot import fulltext

        monkeypatch.setattr(fulltext, "CACHE_DIR", tmp_path)
        doc = fulltext.Document("W44", "https://x/y.pdf", "repository", "pdf", "text", ["https://z"])
        fulltext.save(doc)
        back = fulltext.load("W44")
        assert back is not None and back.text == "text" and back.structured_urls == ["https://z"]

    def test_no_temporary_file_remains(self, tmp_path, monkeypatch) -> None:
        from artifact_rot import fulltext

        monkeypatch.setattr(fulltext, "CACHE_DIR", tmp_path)
        fulltext.save(fulltext.Document("W45", "u", "repository", "pdf", "t", []))
        assert list(tmp_path.rglob("*.part")) == []
