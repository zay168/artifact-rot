"""GitHub quota guard, added after the 2026-09-20 run.

Three runs of the control set exhausted the 60 requests/hour of anonymous mode. The
probers did return `unknown` — a crawler failure is not a dead link — but measurement
became impossible and we kept hitting an API that was refusing.
"""

from __future__ import annotations

import httpx
import pytest

from artifact_rot.config import Settings
from artifact_rot.probe.api_github import _RateLimitTracker


def response(remaining: str | None, reset: str | None = None) -> httpx.Response:
    headers = {}
    if remaining is not None:
        headers["x-ratelimit-remaining"] = remaining
    if reset is not None:
        headers["x-ratelimit-reset"] = reset
    return httpx.Response(200, headers=headers)


class TestQuotaTracker:
    def test_reads_headers(self) -> None:
        t = _RateLimitTracker()
        t.observe(response("57", "1790000000"))
        assert t.snapshot() == {"x_ratelimit_remaining": 57, "x_ratelimit_reset": 1790000000}

    def test_quota_exhausted(self) -> None:
        t = _RateLimitTracker()
        t.observe(response("0"))
        assert t.exhausted()

    def test_tight_quota_cuts_enrichment_before_measurement(self) -> None:
        """The owner check must never be what exhausts the quota."""
        t = _RateLimitTracker()
        t.observe(response("2"))
        assert t.low()
        assert not t.exhausted()

    def test_no_header_means_no_assumption(self) -> None:
        """No header = no information. We do not block on an assumption."""
        t = _RateLimitTracker()
        t.observe(response(None))
        assert not t.exhausted()
        assert not t.low()

    def test_non_numeric_header_ignored(self) -> None:
        t = _RateLimitTracker()
        t.observe(response("unknown"))
        assert not t.exhausted()


class TestConfigWithoutToken:
    def test_enrichment_off_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """60 req/h: doubling the cost of each 404 makes the control set unmeasurable."""
        monkeypatch.setenv("ARTIFACT_ROT_CONTACT", "test@exemple.org")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert Settings.from_env().github_owner_check is False

    def test_enrichment_on_with_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTIFACT_ROT_CONTACT", "test@exemple.org")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")
        assert Settings.from_env().github_owner_check is True
