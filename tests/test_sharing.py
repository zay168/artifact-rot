"""Detection des annonces de partage — methode reprise d'ODDPub (CC BY 4.0).

Les faux positifs testes ici viennent tous du corpus reel du 2026-09-20. Ils sont
nommes, parce qu'une detection qui declenche sur « these symmetries are not generally
available in curved space time » ne mesure pas le partage de donnees.
"""

from __future__ import annotations

import pytest

from artifact_rot.extract.sharing import detect
from artifact_rot.extract.statements import find_availability_spans


class TestCoOccurrence:
    """Une seule categorie ne suffit jamais — c'est le principe repris d'ODDPub."""

    def test_depot_generaliste_plus_verbe_de_depot(self) -> None:
        s = detect("All data are available at https://zenodo.org/records/3509134.")
        assert s.open_data
        assert "general_repo_data" in s.categories

    def test_depot_specialise_plus_numero_d_acces(self) -> None:
        s = detect("Sequences were deposited in the Gene Expression Omnibus under GSE123456.")
        assert s.open_data
        assert "field_repo_accession" in s.categories

    def test_code_source(self) -> None:
        s = detect("The analysis code is available at https://github.com/labo/projet.")
        assert s.open_code

    def test_mention_isolee_ne_declenche_pas(self) -> None:
        """« github » dans une bibliographie n'annonce rien."""
        s = detect("12. Dupont A. Un titre quelconque. github.com/autre/projet, 2019.")
        assert not s.claims_sharing

    def test_nom_de_depot_seul_ne_declenche_pas(self) -> None:
        s = detect("Zenodo is a general-purpose repository operated by CERN.")
        assert not s.claims_sharing


class TestFauxPositifsDuCorpusReel:
    def test_symetries_non_disponibles_en_espace_courbe(self) -> None:
        """Declenchait `explicitly_restricted` : la forme large `not ... available`
        attrapait une phrase de physique theorique."""
        s = detect(
            "These translational symmetries are not generally available in curved "
            "space time and thus Noether's power tools are not available."
        )
        assert not s.explicitly_restricted

    def test_liste_de_references_avec_numeros(self) -> None:
        """Declenchait `field_repo_accession` : le motif generique d'identifiant
        attrapait des numeros de reference bibliographique."""
        s = detect(
            "[Joffrin et al., 2024] Joffrin, E., Wischmeier, M., Baruzzo, M., "
            "Hakola, A., Kappatou, A., Keeling, D., Labit, B., the ASDEX Upgrade Team."
        )
        assert not s.claims_sharing

    def test_code_pdb_seul_ne_suffit_pas(self) -> None:
        """Un code PDB a la forme `1ABC` : trop court pour porter un signal seul."""
        s = detect("The structure 6VXX was used as a template for the model.")
        assert not s.open_data


class TestRefusEtDemande:
    def test_refus_explicite(self) -> None:
        s = detect("The data are not publicly available due to patient privacy.")
        assert s.explicitly_restricted
        assert not s.claims_sharing

    def test_sur_demande(self) -> None:
        s = detect(
            "Data Availability The data are available from the corresponding author "
            "upon reasonable request."
        )
        assert s.on_request

    def test_preuve_conservee(self) -> None:
        """Sans la phrase declencheuse, un desaccord est inarbitrable."""
        s = detect("All data are available at https://osf.io/ezcuj.")
        assert s.sentences and "osf.io" in s.sentences[0]


class TestTitreSansPonctuation:
    """Mesure du 2026-09-20 : quatre documents sur dix ecrivent le titre sans
    separateur, l'extraction PDF le collant au paragraphe."""

    @pytest.mark.parametrize(
        "text",
        [
            "Data Availability As declared in the paper, data will be provided on request.",
            "Data availability: the dataset is at https://osf.io/ezcuj.",
            "Code Availability - the code is at https://github.com/a/b.",
        ],
    )
    def test_detecte(self, text: str) -> None:
        assert find_availability_spans(text)

    def test_ne_declenche_pas_sur_une_phrase_ordinaire(self) -> None:
        assert not find_availability_spans("We discuss data availability in section 4.")
