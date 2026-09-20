"""Extraction des liens depuis le texte integral (E3)."""

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
    def test_ecarte_la_fabrication_editoriale(self, url: str) -> None:
        """Presents dans presque tout PDF. Les compter gonflerait le denominateur avec
        des liens dont la survie n'interesse personne."""
        assert is_boilerplate(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/labo/projet",
            "https://zenodo.org/records/3509134",
            "https://doi.org/10.5281/zenodo.3509134",
        ],
    )
    def test_ne_touche_pas_aux_artefacts(self, url: str) -> None:
        assert not is_boilerplate(url)
        assert is_artifact_link(url)

    def test_une_url_de_labo_n_est_pas_un_artefact_reconnu(self) -> None:
        """Elle reste extraite et sondee, simplement elle ne compte pas dans le rappel."""
        assert not is_artifact_link("https://labo.univ-exemple.fr/donnees/")


class TestExtractionTextuelle:
    def test_url_et_doi_nu(self) -> None:
        text = "Code : https://github.com/labo/p. Donnees : doi:10.5281/zenodo.123."
        found = [url for _, url in iter_raw_links(text)]
        assert "https://github.com/labo/p" in found
        assert "https://doi.org/10.5281/zenodo.123" in found

    def test_url_coupee_par_le_pdf_est_recollee(self) -> None:
        """Le mode d'echec n°2 de metacheck, sur le chemin d'extraction reel."""
        text = "Voir https://doi. org/10.7939/DVN/QYMAYV pour les donnees."
        found = [url for _, url in iter_raw_links(text)]
        assert "https://doi.org/10.7939/DVN/QYMAYV" in found

    def test_ponctuation_finale_retiree(self) -> None:
        links = extract_links("Donnees : https://zenodo.org/records/42.", **PAPER)
        assert links[0].normalized == "https://zenodo.org/records/42"

    def test_provenance_portee_par_le_lien(self) -> None:
        text = (
            "Introduction\nVoir https://github.com/x/corps.\n\n"
            "Data Availability\nDonnees : https://zenodo.org/records/7.\n\n"
            "References\n1. https://github.com/y/cite\n"
        )
        by_host = {link.normalized: link.source for link in extract_links(text, **PAPER)}
        assert by_host["https://github.com/x/corps"] == "body"
        assert by_host["https://zenodo.org/records/7"] == "availability_statement"
        assert by_host["https://github.com/y/cite"] == "references"

    def test_deduplication(self) -> None:
        text = "https://github.com/a/b et http://www.github.com/a/b/ sont le meme depot."
        assert len(extract_links(text, **PAPER)) == 1

    def test_union_avec_le_balisage(self) -> None:
        """Les annotations portent des liens que la cesure fait perdre au texte, et le
        texte porte des liens que l'editeur n'a pas balises. On prend l'union."""
        links = extract_links(
            "Code : https://github.com/labo/depuis-le-texte.",
            structured_urls=["https://zenodo.org/records/999"],
            **PAPER,
        )
        normalized = {link.normalized for link in links}
        assert "https://github.com/labo/depuis-le-texte" in normalized
        assert "https://zenodo.org/records/999" in normalized

    def test_les_liens_du_balisage_sont_en_provenance_body(self) -> None:
        """Une annotation ne dit pas dans quelle section elle se trouve."""
        links = extract_links("Texte.", structured_urls=["https://osf.io/abcde"], **PAPER)
        assert links[0].source == "body"

    def test_identifiant_stable(self) -> None:
        a = extract_links("https://github.com/a/b", **PAPER)[0]
        b = extract_links("http://www.github.com/a/b/", **PAPER)[0]
        assert a.link_id == b.link_id


class TestSurDemande:
    def test_compte_dans_la_declaration(self) -> None:
        text = (
            "Data Availability\n"
            "Data are available from the corresponding author upon reasonable request.\n"
        )
        assert count_on_request(text) == 1

    def test_ne_compte_pas_hors_declaration(self) -> None:
        """La formule apparait aussi dans des contextes sans rapport."""
        text = "Introduction\nLes reactifs ont ete fournis sur demande du comite.\n"
        assert count_on_request(text) == 0

    def test_une_declaration_avec_lien_n_est_pas_sur_demande(self) -> None:
        text = "Data Availability\nAll data are at https://zenodo.org/records/1.\n"
        assert count_on_request(text) == 0


class TestTexteHostile:
    """Ce qui sort d'un PDF ne doit jamais pouvoir faire tomber la chaine.

    Rencontre le 2026-09-20 : le moissonnage est mort apres 200 articles sur
    `UnicodeEncodeError: surrogates not allowed`. Une police de PDF avec une table de
    caracteres incoherente produit des demi-paires de substitution, que Python accepte
    en memoire mais qu'aucun encodeur UTF-8 n'accepte.
    """

    def test_les_demi_paires_de_substitution_sont_neutralisees(self) -> None:
        from artifact_rot.fulltext import sanitize

        hostile = "Donnees 𐀀 disponibles \udfff ici"
        cleaned = sanitize(hostile)
        cleaned.encode("utf-8")  # ne doit pas lever
        assert "Donnees" in cleaned and "disponibles" in cleaned

    def test_le_texte_normal_est_intact(self) -> None:
        from artifact_rot.fulltext import sanitize

        text = "Données disponibles à https://zenodo.org/records/1 — accès libre ✓"
        assert sanitize(text) == text

    def test_extraction_sur_texte_assaini(self) -> None:
        from artifact_rot.fulltext import sanitize

        text = sanitize("Code : https://github.com/labo/p \ud800 fin.")
        links = extract_links(text, **PAPER)
        assert any(link.host == "github.com" for link in links)
