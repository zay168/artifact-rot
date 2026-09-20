"""Reperage des sections de disponibilite et de la bibliographie.

La provenance d'un lien decide de ce qu'on a le droit d'en dire. Un lien annonce dans
« Data Availability » est une promesse explicite de l'article ; le meme lien dans la
bibliographie peut appartenir a un article cite. Confondre les deux, c'est attribuer a
des auteurs une promesse qu'ils n'ont pas faite — exactement ce que le §9 interdit.
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
Nous avons collecte des donnees sur trois ans. Voir https://exemple.org/methode.

Methods
Le code est decrit ci-dessous.

Data Availability
All data are available at https://zenodo.org/records/3509134 and the analysis code
at https://github.com/labo/projet.

Acknowledgements
Merci au laboratoire.

References
1. Dupont A. (2019). Titre. https://github.com/autre-equipe/autre-depot
"""


class TestDeclarationsDeDisponibilite:
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
            "Disponibilite des donnees",
            "3. Data Availability",
        ],
    )
    def test_titres_reconnus(self, heading: str) -> None:
        text = f"Intro\n\n{heading}\nLes donnees sont sur https://zenodo.org/records/1.\n"
        spans = find_availability_spans(text)
        assert spans, heading
        assert "zenodo.org" in spans[0].slice(text)

    def test_forme_en_ligne(self) -> None:
        """Dans un PDF, le titre n'est souvent pas isole sur sa ligne."""
        text = "Data availability: the dataset is at https://osf.io/ezcuj."
        spans = find_availability_spans(text)
        assert spans and "osf.io" in spans[0].slice(text)

    def test_borne_a_la_section_suivante(self) -> None:
        spans = find_availability_spans(ARTICLE)
        assert len(spans) == 1
        body = spans[0].slice(ARTICLE)
        assert "zenodo.org" in body
        assert "github.com/labo/projet" in body
        # La bibliographie ne doit pas entrer dans la declaration.
        assert "autre-equipe" not in body

    @pytest.mark.parametrize(
        "text",
        [
            "Introduction\nRien a declarer ici.",
            "Availability of the instrument was limited to weekdays.",
        ],
    )
    def test_pas_de_faux_positif(self, text: str) -> None:
        assert find_availability_spans(text) == []


class TestBibliographie:
    def test_derniere_occurrence(self) -> None:
        """« References » apparait souvent dans un sommaire avant la vraie section.

        Prendre la premiere occurrence classerait la moitie du corps de texte en
        bibliographie, donc en provenance douteuse.
        """
        text = "Sommaire\nReferences\n\nIntroduction\nCorps du texte.\n\nReferences\n1. Dupont\n"
        span = find_references_span(text)
        assert span is not None
        assert "Dupont" in span.slice(text)
        assert "Corps du texte" not in span.slice(text)

    def test_absente(self) -> None:
        assert find_references_span("Un texte sans bibliographie.") is None


class TestProvenance:
    def test_les_trois_provenances(self) -> None:
        availability = find_availability_spans(ARTICLE)
        references = find_references_span(ARTICLE)

        pos_body = ARTICLE.index("https://exemple.org/methode")
        pos_avail = ARTICLE.index("https://zenodo.org")
        pos_ref = ARTICLE.index("https://github.com/autre-equipe")

        assert classify_position(pos_body, availability, references) == "body"
        assert classify_position(pos_avail, availability, references) == "availability_statement"
        assert classify_position(pos_ref, availability, references) == "references"
