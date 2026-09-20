"""La regle de resolution est le point ou un bug devient une falsification.

Un echec de crawl converti en « lien mort » detruirait le projet (§4, piege 2). Ces
tests existent pour que cette conversion soit impossible sans casser la suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from artifact_rot.config import Settings
from artifact_rot.models import Probe, Status
from artifact_rot.resolve import resolve

SETTINGS = Settings(contact="test@exemple.org")
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def probes(*specs: tuple[Status, int]) -> list[Probe]:
    """(statut, jour) -> sondes numerotees dans l'ordre chronologique."""
    return [
        Probe(
            link_id="abc",
            probed_at=T0 + timedelta(days=day),
            method="api",
            status=status,
            attempt=i + 1,
        )
        for i, (status, day) in enumerate(specs)
    ]


class TestDeadExigeTroisEchecsEspaces:
    def test_trois_echecs_sur_trois_dates_espacees(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 7), (Status.DEAD, 14)), SETTINGS)
        assert out.status is Status.DEAD
        assert out.rule == "dead_three_failures_three_dates"

    def test_trois_echecs_le_meme_jour_ne_suffisent_pas(self) -> None:
        """« jamais dans la meme minute » — trois sondes rapprochees ne sont qu'une."""
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 0), (Status.DEAD, 0)), SETTINGS)
        assert out.status is Status.UNKNOWN
        assert out.rule == "insufficient_evidence"

    def test_trois_echecs_trop_rapproches(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 1), (Status.DEAD, 2)), SETTINGS)
        assert out.status is Status.UNKNOWN

    def test_deux_echecs_ne_suffisent_pas(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 14)), SETTINGS)
        assert out.status is Status.UNKNOWN


class TestAliveLEmportre:
    @pytest.mark.parametrize("day", [0, 7, 14])
    def test_une_seule_observation_vivante_suffit(self, day: int) -> None:
        specs = [(Status.DEAD, 0), (Status.DEAD, 7), (Status.DEAD, 14)]
        specs[[0, 7, 14].index(day)] = (Status.ALIVE, day)
        out = resolve("abc", probes(*specs), SETTINGS)
        assert out.status is Status.ALIVE
        assert out.rule == "alive_once_wins"

    def test_alive_est_censure_a_droite(self) -> None:
        out = resolve("abc", probes((Status.ALIVE, 0)), SETTINGS)
        assert out.right_censored is True

    def test_dead_n_est_pas_censure(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 7), (Status.DEAD, 14)), SETTINGS)
        assert out.right_censored is False


class TestRestricted:
    def test_restricted_l_emporte_sur_dead(self) -> None:
        out = resolve(
            "abc", probes((Status.DEAD, 0), (Status.RESTRICTED, 7), (Status.DEAD, 14)), SETTINGS
        )
        assert out.status is Status.RESTRICTED
        assert out.rule == "restricted_over_dead"

    def test_alive_l_emporte_sur_restricted(self) -> None:
        out = resolve("abc", probes((Status.RESTRICTED, 0), (Status.ALIVE, 7)), SETTINGS)
        assert out.status is Status.ALIVE


class TestUnknownNeDevientJamaisDead:
    @pytest.mark.parametrize(
        "specs",
        [
            ((Status.UNKNOWN, 0), (Status.UNKNOWN, 7), (Status.UNKNOWN, 14)),
            ((Status.UNKNOWN, 0), (Status.DEAD, 7), (Status.DEAD, 14)),
            ((Status.DEAD, 0), (Status.UNKNOWN, 7), (Status.DEAD, 14)),
        ],
    )
    def test_reste_unknown(self, specs) -> None:
        out = resolve("abc", probes(*specs), SETTINGS)
        assert out.status is Status.UNKNOWN


def test_aucune_sonde_est_une_erreur() -> None:
    with pytest.raises(ValueError):
        resolve("abc", [], SETTINGS)
