"""Garde de quota GitHub, ajoutee apres le run du 2026-09-20.

Trois passages du jeu de controle ont epuise les 60 requetes/heure du mode anonyme.
Les sondes ont bien renvoye `unknown` — un echec de crawler n'est pas un lien mort —
mais la mesure devenait impossible et l'on continuait a frapper une API qui refusait.
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
    def test_lit_les_en_tetes(self) -> None:
        t = _RateLimitTracker()
        t.observe(response("57", "1790000000"))
        assert t.snapshot() == {"x_ratelimit_remaining": 57, "x_ratelimit_reset": 1790000000}

    def test_quota_epuise(self) -> None:
        t = _RateLimitTracker()
        t.observe(response("0"))
        assert t.exhausted()

    def test_quota_serre_coupe_l_enrichissement_avant_la_mesure(self) -> None:
        """Le controle de proprietaire ne doit jamais etre ce qui epuise le quota."""
        t = _RateLimitTracker()
        t.observe(response("2"))
        assert t.low()
        assert not t.exhausted()

    def test_sans_en_tete_on_ne_suppose_rien(self) -> None:
        """Pas d'en-tete = pas d'information. On ne bloque pas sur une supposition."""
        t = _RateLimitTracker()
        t.observe(response(None))
        assert not t.exhausted()
        assert not t.low()

    def test_en_tete_non_numerique_ignore(self) -> None:
        t = _RateLimitTracker()
        t.observe(response("unknown"))
        assert not t.exhausted()


class TestConfigSansJeton:
    def test_l_enrichissement_est_coupe_sans_jeton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """60 req/h : doubler le cout de chaque 404 rend le jeu de controle immesurable."""
        monkeypatch.setenv("ARTIFACT_ROT_CONTACT", "test@exemple.org")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert Settings.from_env().github_owner_check is False

    def test_l_enrichissement_est_actif_avec_jeton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTIFACT_ROT_CONTACT", "test@exemple.org")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_factice")
        assert Settings.from_env().github_owner_check is True
