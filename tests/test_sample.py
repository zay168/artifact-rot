"""E1 — construction des requetes et aplatissement, testes hors ligne.

La reproductibilite elle-meme se verifie contre l'API (`python -m artifact_rot.sample
verify`), pas ici : elle depend d'OpenAlex, pas de notre code. Ce qui se teste hors
ligne, c'est que la requete envoyee est bien celle qu'on croit envoyer — le defaut le
plus couteux d'E1 serait un filtre silencieusement absent.
"""

from __future__ import annotations

from artifact_rot.sample import (
    DISCIPLINES,
    N_PER_STRATUM,
    PER_PAGE,
    YEARS,
    Stratum,
    flatten,
    strata,
)


class TestPlanDesStrates:
    def test_cinq_annees_quatre_disciplines(self) -> None:
        assert len(YEARS) == 5
        assert len(DISCIPLINES) == 4
        assert len(strata()) == 20

    def test_volume_conforme_au_perimetre(self) -> None:
        """§3 : >= 2 000 articles par strate croisee."""
        assert N_PER_STRATUM >= 2000

    def test_pagination_couvre_le_tirage(self) -> None:
        """Le defaut du premier essai : une seule page ramenee au lieu de dix."""
        pages_needed = (N_PER_STRATUM + PER_PAGE - 1) // PER_PAGE
        assert pages_needed * PER_PAGE >= N_PER_STRATUM


class TestFiltre:
    def test_contient_les_restrictions_du_perimetre(self) -> None:
        f = Stratum(year=2018, discipline="medicine", field_id="27").filter_string
        # §3 : acces ouvert, texte integral accessible, et rien d'autre que des articles.
        assert "open_access.is_oa:true" in f
        assert "has_fulltext:true" in f
        assert "type:article" in f
        assert "publication_year:2018" in f
        assert "primary_topic.field.id:fields/27" in f

    def test_pas_de_filtre_sur_le_doi(self) -> None:
        """Filtrer sur has_doi retirerait 31 % des sciences sociales 2010 contre 2 % de
        2022 : un biais de selection porte par la variable explicative principale."""
        for stratum in strata():
            assert "has_doi" not in stratum.filter_string

    def test_cle_de_strate(self) -> None:
        assert Stratum(year=2010, discipline="medicine", field_id="27").key == "medicine-2010"


class TestAplatissement:
    def test_extrait_les_champs_utiles(self) -> None:
        work = {
            "id": "https://openalex.org/W2741809807",
            "doi": "https://doi.org/10.7717/peerj.4375",
            "publication_year": 2018,
            "primary_location": {
                "source": {"display_name": "PeerJ", "host_organization_name": "PeerJ, Inc."}
            },
            "best_oa_location": {"pdf_url": "https://peerj.com/articles/4375.pdf"},
            "open_access": {"oa_status": "gold"},
            "primary_topic": {"display_name": "Scientometrics"},
            "authorships": [{}, {}],
        }
        row = flatten(work, Stratum(year=2018, discipline="medicine", field_id="27"))
        assert row["openalex_id"] == "W2741809807"
        assert row["doi"] == "10.7717/peerj.4375"  # prefixe resolveur retire
        assert row["publisher"] == "PeerJ, Inc."
        assert row["journal"] == "PeerJ"
        assert row["fulltext_url"].endswith(".pdf")
        assert row["n_authors"] == 2
        assert row["stratum"] == "medicine-2018"

    def test_absence_de_doi_ne_casse_rien(self) -> None:
        """22 % des articles d'informatique 2010 n'ont pas de DOI. Ils restent dans
        l'echantillon, identifies par leur identifiant OpenAlex."""
        work = {"id": "https://openalex.org/W1", "doi": None, "publication_year": 2010}
        row = flatten(work, Stratum(year=2010, discipline="computer_science", field_id="17"))
        assert row["openalex_id"] == "W1"
        assert row["doi"] is None
        assert row["publisher"] == "unknown"

    def test_source_absente_ne_casse_rien(self) -> None:
        work = {"id": "https://openalex.org/W2", "primary_location": None, "publication_year": 2014}
        row = flatten(work, Stratum(year=2014, discipline="social_sciences", field_id="33"))
        assert row["publisher"] == "unknown"
        assert row["fulltext_url"] is None
