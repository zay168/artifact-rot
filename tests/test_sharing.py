"""Detecting sharing announcements — method taken from ODDPub (CC BY 4.0).

The false positives tested here all come from the real corpus of 2026-09-20. They are
named, because a detector that fires on "these symmetries are not generally available in
curved space time" does not measure data sharing.
"""

from __future__ import annotations

import pytest

from artifact_rot.extract.sharing import detect
from artifact_rot.extract.statements import find_availability_spans


class TestCoOccurrence:
    """A single category is never enough — that is the principle taken from ODDPub."""

    def test_general_repository_plus_deposit_verb(self) -> None:
        s = detect("All data are available at https://zenodo.org/records/3509134.")
        assert s.open_data
        assert "general_repo_data" in s.categories

    def test_specialised_repository_plus_accession_number(self) -> None:
        s = detect("Sequences were deposited in the Gene Expression Omnibus under GSE123456.")
        assert s.open_data
        assert "field_repo_accession" in s.categories

    def test_source_code(self) -> None:
        s = detect("The analysis code is available at https://github.com/labo/projet.")
        assert s.open_code

    def test_isolated_mention_does_not_fire(self) -> None:
        """"github" in a bibliography announces nothing."""
        s = detect("12. Dupont A. Some arbitrary title. github.com/other/project, 2019.")
        assert not s.claims_sharing

    def test_repository_name_alone_does_not_fire(self) -> None:
        s = detect("Zenodo is a general-purpose repository operated by CERN.")
        assert not s.claims_sharing


class TestFalsePositivesFromRealCorpus:
    def test_symmetries_not_available_in_curved_space(self) -> None:
        """Used to fire `explicitly_restricted`: the broad form `not ... available`
        caught a theoretical-physics sentence."""
        s = detect(
            "These translational symmetries are not generally available in curved "
            "space time and thus Noether's power tools are not available."
        )
        assert not s.explicitly_restricted

    def test_reference_list_with_numbers(self) -> None:
        """Used to fire `field_repo_accession`: the generic identifier pattern caught
        bibliographic reference numbers."""
        s = detect(
            "[Joffrin et al., 2024] Joffrin, E., Wischmeier, M., Baruzzo, M., "
            "Hakola, A., Kappatou, A., Keeling, D., Labit, B., the ASDEX Upgrade Team."
        )
        assert not s.claims_sharing

    def test_pdb_code_alone_is_not_enough(self) -> None:
        """A PDB code has the shape `1ABC`: too short to carry a signal alone."""
        s = detect("The structure 6VXX was used as a template for the model.")
        assert not s.open_data


class TestRefusalAndRequest:
    def test_explicit_refusal(self) -> None:
        s = detect("The data are not publicly available due to patient privacy.")
        assert s.explicitly_restricted
        assert not s.claims_sharing

    def test_on_request(self) -> None:
        s = detect(
            "Data Availability The data are available from the corresponding author "
            "upon reasonable request."
        )
        assert s.on_request

    def test_evidence_kept(self) -> None:
        """Without the triggering sentence, a disagreement cannot be arbitrated."""
        s = detect("All data are available at https://osf.io/ezcuj.")
        assert s.sentences and "osf.io" in s.sentences[0]


class TestHeadingWithoutPunctuation:
    """Measured on 2026-09-20: four documents out of ten write the heading without a
    separator, PDF extraction gluing it to the paragraph."""

    @pytest.mark.parametrize(
        "text",
        [
            "Data Availability As declared in the paper, data will be provided on request.",
            "Data availability: the dataset is at https://osf.io/ezcuj.",
            "Code Availability - the code is at https://github.com/a/b.",
        ],
    )
    def test_detected(self, text: str) -> None:
        assert find_availability_spans(text)

    def test_does_not_fire_on_an_ordinary_sentence(self) -> None:
        assert not find_availability_spans("We discuss data availability in section 4.")
