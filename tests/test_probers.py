"""Prober routing and soft-404 heuristics, tested offline.

Routing is tested because a routing error sends a GitHub link to the generic HTTP prober,
which will read HTML — exactly what §4 forbids.
"""

from __future__ import annotations

import pytest

from artifact_rot.extract.normalize import canonicalize, host_of, kind_of
from artifact_rot.models import Link
from artifact_rot.probe import default_registry
from artifact_rot.probe.http_generic import (
    SOFT404_SIMILARITY,
    _redirected_to_root,
    _similarity,
    _title_of,
)


def link(url: str) -> Link:
    n = canonicalize(url)
    return Link(
        paper_id="W0000000000",
        paper_year=2020,
        discipline="test",
        publisher="test",
        raw=url,
        normalized=n,
        kind=kind_of(n),  # type: ignore[arg-type]
        host=host_of(n),
    )


class TestRouting:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/owner/repo", "github"),
            ("https://github.com/owner/repo/blob/main/data.csv", "github"),
            ("https://gitlab.com/group/sub/project", "gitlab"),
            ("https://bitbucket.org/owner/repo", "bitbucket"),
            ("https://zenodo.org/records/3509134", "zenodo"),
            ("https://doi.org/10.5281/zenodo.3509134", "zenodo"),
            ("https://osf.io/ezcuj/", "osf"),
            ("https://figshare.com/articles/dataset/name/9885334", "figshare"),
            ("https://doi.org/10.1371/journal.pone.0304781", "doi"),
            ("https://lab.univ-exemple.fr/donnees/", "http_generic"),
        ],
    )
    def test_selection(self, url: str, expected: str) -> None:
        assert default_registry().select(link(url)).name == expected

    def test_apis_come_before_html(self) -> None:
        """§4 invariant: no host with an API may fall to the generic prober."""
        registry = default_registry()
        for url in (
            "https://github.com/a/b",
            "https://zenodo.org/records/1",
            "https://osf.io/abcde",
            "https://doi.org/10.1234/abc",
        ):
            assert registry.select(link(url)).method == "api"


class TestSoft404:
    def test_redirect_to_root(self) -> None:
        assert _redirected_to_root("https://lab.fr/donnees/set1", "https://lab.fr/")

    def test_legitimate_internal_redirect(self) -> None:
        assert not _redirected_to_root("https://lab.fr/donnees", "https://lab.fr/donnees/v2")

    def test_root_to_root_is_not_a_signal(self) -> None:
        assert not _redirected_to_root("https://lab.fr/", "https://lab.fr/")

    def test_two_error_pages_identical_up_to_noise(self) -> None:
        a = "<html><title>Not Found</title><body>Request id 8f3a91bc2d id 4412</body></html>"
        b = "<html><title>Not Found</title><body>Request id 11de77aa90 id 9930</body></html>"
        assert _similarity(a, b) >= SOFT404_SIMILARITY

    def test_a_real_page_differs_from_the_error_page(self) -> None:
        page = "<html><title>Dataset: soil cores 2014</title><body>Download 1.2 GB NetCDF</body></html>"
        err = "<html><title>Not Found</title><body>The page you requested does not exist</body></html>"
        assert _similarity(page, err) < SOFT404_SIMILARITY

    def test_title_extraction(self) -> None:
        assert _title_of("<html><TITLE> Page Not Found </TITLE></html>") == "Page Not Found"
        assert _title_of("<html><body>nothing</body></html>") is None


class TestControlSet:
    def test_reproducible_with_fixed_seed(self) -> None:
        from artifact_rot.control import build_cases

        a = [c.url for c in build_cases()]
        b = [c.url for c in build_cases()]
        assert a == b

    def test_dead_cases_are_well_formed(self) -> None:
        """A malformed `dead` case would test `is_malformed`, not the prober."""
        from artifact_rot.control import build_cases
        from artifact_rot.extract.normalize import is_malformed

        for case in build_cases():
            if case.family == "dead":
                assert not is_malformed(case.url), case.url

    def test_no_verdict_if_a_family_is_missing(self) -> None:
        """Announcing 98% while omitting `restricted` would be window dressing."""
        from artifact_rot.control import _score

        report = _score(
            [
                {"family": "alive", "case_id": "a", "url": "u", "observed": "alive", "correct": True, "reason": "r"},
                {"family": "dead", "case_id": "d", "url": "u", "observed": "dead", "correct": True, "reason": "r"},
                {"family": "malformed", "case_id": "m", "url": "u", "observed": "malformed", "correct": True, "reason": "r"},
            ]
        )
        assert report["verdict"] == "incomplete"
        assert report["missing_families"] == ["restricted"]


class TestDNS:
    """A domain name that no longer exists is an answer, not a crawler failure.

    Decision taken on 2026-09-21, before pass 3 and therefore before seeing any final
    result — the only moment it can be taken without suspicion.
    """

    def test_nonexistent_name(self) -> None:
        from artifact_rot.probe.dns import resolve

        assert resolve("absent-" + "z" * 24 + "-artifact-rot.invalid") == "nxdomain"

    def test_empty_name_does_not_raise(self) -> None:
        from artifact_rot.probe.dns import resolve

        assert resolve("") == "unknown"

    def test_transient_codes_are_not_nxdomain(self) -> None:
        """The central safeguard: a resolver outage must not produce a dead link."""
        import socket

        from artifact_rot.probe import dns

        assert socket.EAI_NONAME in dns._NXDOMAIN_ERRNOS
        assert socket.EAI_NONAME not in dns._TRANSIENT_ERRNOS
        for name in ("EAI_AGAIN", "EAI_FAIL"):
            code = getattr(socket, name, None)
            if code is not None:
                assert code not in dns._NXDOMAIN_ERRNOS, name

    def test_memoisation(self) -> None:
        from artifact_rot.probe.dns import _cache, reset_cache, resolve

        reset_cache()
        host = "absent-" + "y" * 24 + "-artifact-rot.invalid"
        resolve(host)
        assert host in _cache
        reset_cache()
        assert host not in _cache


class TestInvalidTld:
    """`arcjournals.or`: a `.org` truncated at extraction, not a vanished site.

    Counting it dead would add to the mortality rate a link that never existed — and in
    the direction that suits the project's thesis.
    """

    def test_tld_absent_from_iana(self) -> None:
        from artifact_rot.extract.normalize import is_malformed

        assert is_malformed("https://arcjournals.or/article/12")

    def test_valid_tld(self) -> None:
        from artifact_rot.extract.normalize import is_malformed

        assert not is_malformed("https://arcjournals.org/article/12")

    def test_list_is_loaded(self) -> None:
        from artifact_rot.extract.normalize import VALID_TLDS

        assert len(VALID_TLDS) > 1000
        assert "org" in VALID_TLDS and "fr" in VALID_TLDS
        assert "or" not in VALID_TLDS
