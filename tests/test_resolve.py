"""The resolution rule is where a bug becomes a falsification.

A crawl failure converted into a "dead link" would destroy the project (§4, pitfall 2).
These tests exist so that this conversion is impossible without breaking the suite.
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
    """(status, day) -> probes numbered in chronological order."""
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


class TestDeadRequiresThreeSpacedFailures:
    def test_three_failures_on_three_spaced_dates(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 7), (Status.DEAD, 14)), SETTINGS)
        assert out.status is Status.DEAD
        assert out.rule == "dead_three_failures_three_dates"

    def test_three_failures_on_the_same_day_are_not_enough(self) -> None:
        """"never in the same minute" — three close probes are only one."""
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 0), (Status.DEAD, 0)), SETTINGS)
        assert out.status is Status.UNKNOWN
        assert out.rule == "insufficient_evidence"

    def test_three_failures_too_close(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 1), (Status.DEAD, 2)), SETTINGS)
        assert out.status is Status.UNKNOWN

    def test_two_failures_are_not_enough(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 14)), SETTINGS)
        assert out.status is Status.UNKNOWN


class TestAliveWins:
    @pytest.mark.parametrize("day", [0, 7, 14])
    def test_a_single_live_observation_is_enough(self, day: int) -> None:
        specs = [(Status.DEAD, 0), (Status.DEAD, 7), (Status.DEAD, 14)]
        specs[[0, 7, 14].index(day)] = (Status.ALIVE, day)
        out = resolve("abc", probes(*specs), SETTINGS)
        assert out.status is Status.ALIVE
        assert out.rule == "alive_once_wins"

    def test_alive_is_right_censored(self) -> None:
        out = resolve("abc", probes((Status.ALIVE, 0)), SETTINGS)
        assert out.right_censored is True

    def test_dead_is_not_censored(self) -> None:
        out = resolve("abc", probes((Status.DEAD, 0), (Status.DEAD, 7), (Status.DEAD, 14)), SETTINGS)
        assert out.right_censored is False


class TestRestricted:
    def test_restricted_wins_over_dead(self) -> None:
        out = resolve(
            "abc", probes((Status.DEAD, 0), (Status.RESTRICTED, 7), (Status.DEAD, 14)), SETTINGS
        )
        assert out.status is Status.RESTRICTED
        assert out.rule == "restricted_over_dead"

    def test_alive_wins_over_restricted(self) -> None:
        out = resolve("abc", probes((Status.RESTRICTED, 0), (Status.ALIVE, 7)), SETTINGS)
        assert out.status is Status.ALIVE


class TestUnknownNeverBecomesDead:
    @pytest.mark.parametrize(
        "specs",
        [
            ((Status.UNKNOWN, 0), (Status.UNKNOWN, 7), (Status.UNKNOWN, 14)),
            ((Status.UNKNOWN, 0), (Status.DEAD, 7), (Status.DEAD, 14)),
            ((Status.DEAD, 0), (Status.UNKNOWN, 7), (Status.DEAD, 14)),
        ],
    )
    def test_stays_unknown(self, specs) -> None:
        out = resolve("abc", probes(*specs), SETTINGS)
        assert out.status is Status.UNKNOWN


def test_no_probe_is_an_error() -> None:
    with pytest.raises(ValueError):
        resolve("abc", [], SETTINGS)
