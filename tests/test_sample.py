"""E1 — query construction and flattening, tested offline.

Reproducibility itself is checked against the API (`python -m artifact_rot.sample
verify`), not here: it depends on OpenAlex, not on our code. What can be tested offline is
that the request sent is the one we think we send — E1's costliest defect would be a
silently missing filter.
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


class TestStratumPlan:
    def test_five_years_four_disciplines(self) -> None:
        assert len(YEARS) == 5
        assert len(DISCIPLINES) == 4
        assert len(strata()) == 20

    def test_volume_matches_scope(self) -> None:
        """§3: >= 2,000 papers per crossed stratum."""
        assert N_PER_STRATUM >= 2000

    def test_pagination_covers_the_draw(self) -> None:
        """The first attempt's defect: a single page brought back instead of ten."""
        pages_needed = (N_PER_STRATUM + PER_PAGE - 1) // PER_PAGE
        assert pages_needed * PER_PAGE >= N_PER_STRATUM


class TestFilter:
    def test_contains_the_scope_restrictions(self) -> None:
        f = Stratum(year=2018, discipline="medicine", field_id="27").filter_string
        # §3: open access, accessible full text, and nothing but articles.
        assert "open_access.is_oa:true" in f
        assert "has_fulltext:true" in f
        assert "type:article" in f
        assert "publication_year:2018" in f
        assert "primary_topic.field.id:fields/27" in f

    def test_no_doi_filter(self) -> None:
        """Filtering on has_doi would remove 31% of social sciences 2010 against 2% of
        2022: a selection bias carried by the main explanatory variable."""
        for stratum in strata():
            assert "has_doi" not in stratum.filter_string

    def test_stratum_key(self) -> None:
        assert Stratum(year=2010, discipline="medicine", field_id="27").key == "medicine-2010"


class TestFlattening:
    def test_extracts_useful_fields(self) -> None:
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
        assert row["doi"] == "10.7717/peerj.4375"  # resolver prefix removed
        assert row["publisher"] == "PeerJ, Inc."
        assert row["journal"] == "PeerJ"
        assert row["fulltext_url"].endswith(".pdf")
        assert row["n_authors"] == 2
        assert row["stratum"] == "medicine-2018"

    def test_missing_doi_breaks_nothing(self) -> None:
        """22% of computer science papers from 2010 have no DOI. They stay in the
        sample, identified by their OpenAlex identifier."""
        work = {"id": "https://openalex.org/W1", "doi": None, "publication_year": 2010}
        row = flatten(work, Stratum(year=2010, discipline="computer_science", field_id="17"))
        assert row["openalex_id"] == "W1"
        assert row["doi"] is None
        assert row["publisher"] == "unknown"

    def test_missing_source_breaks_nothing(self) -> None:
        work = {"id": "https://openalex.org/W2", "primary_location": None, "publication_year": 2014}
        row = flatten(work, Stratum(year=2014, discipline="social_sciences", field_id="33"))
        assert row["publisher"] == "unknown"
        assert row["fulltext_url"] is None
