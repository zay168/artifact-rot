"""Locating availability sections and the bibliography.

A link's provenance decides what we are allowed to say about it. A link announced in
"Data Availability" is an explicit promise by the paper; the same link in the
bibliography may belong to a cited paper. Confusing the two attributes to authors a
promise they did not make — exactly what §9 forbids.
"""

from __future__ import annotations

import pytest

from artifact_rot.extract.statements import (
    classify_position,
    find_availability_spans,
    find_references_span,
)

ARTICLE = """
Introduction
We collected data over three years. See https://exemple.org/methode.

Methods
The code is described below.

Data Availability
All data are available at https://zenodo.org/records/3509134 and the analysis code
at https://github.com/labo/projet.

Acknowledgements
Thanks to the laboratory.

References
1. Dupont A. (2019). Title. https://github.com/autre-equipe/autre-depot
"""


class TestAvailabilityStatements:
    @pytest.mark.parametrize(
        "heading",
        [
            "Data Availability",
            "Data availability statement",
            "Code Availability",
            "Data and code availability",
            "Availability of data",
            "Data Accessibility",
            "Accession Codes",
            "Open Practices Statement",
            "Disponibilite des donnees",  # French heading, deliberately supported
            "3. Data Availability",
        ],
    )
    def test_recognised_headings(self, heading: str) -> None:
        text = f"Intro\n\n{heading}\nThe data are at https://zenodo.org/records/1.\n"
        spans = find_availability_spans(text)
        assert spans, heading
        assert "zenodo.org" in spans[0].slice(text)

    def test_inline_form(self) -> None:
        """In a PDF, the heading is often not alone on its line."""
        text = "Data availability: the dataset is at https://osf.io/ezcuj."
        spans = find_availability_spans(text)
        assert spans and "osf.io" in spans[0].slice(text)

    def test_bounded_by_the_next_section(self) -> None:
        spans = find_availability_spans(ARTICLE)
        assert len(spans) == 1
        body = spans[0].slice(ARTICLE)
        assert "zenodo.org" in body
        assert "github.com/labo/projet" in body
        # The bibliography must not enter the statement.
        assert "autre-equipe" not in body

    @pytest.mark.parametrize(
        "text",
        [
            "Introduction\nNothing to declare here.",
            "Availability of the instrument was limited to weekdays.",
        ],
    )
    def test_no_false_positive(self, text: str) -> None:
        assert find_availability_spans(text) == []


class TestBibliography:
    def test_last_occurrence(self) -> None:
        """"References" often appears in a table of contents before the real section.

        Taking the first occurrence would class half the body text as bibliography, and
        thus as doubtful provenance.
        """
        text = "Contents\nReferences\n\nIntroduction\nBody text.\n\nReferences\n1. Dupont\n"
        span = find_references_span(text)
        assert span is not None
        assert "Dupont" in span.slice(text)
        assert "Body text" not in span.slice(text)

    def test_absent(self) -> None:
        assert find_references_span("A text without a bibliography.") is None


class TestProvenance:
    def test_the_three_provenances(self) -> None:
        availability = find_availability_spans(ARTICLE)
        references = find_references_span(ARTICLE)

        pos_body = ARTICLE.index("https://exemple.org/methode")
        pos_avail = ARTICLE.index("https://zenodo.org")
        pos_ref = ARTICLE.index("https://github.com/autre-equipe")

        assert classify_position(pos_body, availability, references) == "body"
        assert classify_position(pos_avail, availability, references) == "availability_statement"
        assert classify_position(pos_ref, availability, references) == "references"
