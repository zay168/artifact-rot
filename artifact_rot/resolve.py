"""A link's final status = a deterministic function of its probes (§5).

No case-by-case judgement. The rule applied is named in the result so that every line of
the report can be audited down to the probe that produced it.

Order of priority, from most to least informative:

1. ALIVE wins over everything. A resource observed alive once, on any date, existed:
   declaring it dead would be false. This is asymmetric by design — a false death
   destroys the project (§4 pitfall 2), a false life only makes it conservative.
2. RESTRICTED wins over DEAD. Controlled access is confirmed existence.
3. DEAD requires three failures on three distinct dates, at least
   `min_probe_span_days` apart. A link that has not gone through these three probes is
   not dead: it is UNKNOWN.
4. UNKNOWN otherwise. It is counted and reported separately, never in a denominator.
"""

from __future__ import annotations

from .config import Settings
from .models import LinkOutcome, Probe, Status


def resolve(link_id: str, probes: list[Probe], settings: Settings) -> LinkOutcome:
    if not probes:
        raise ValueError(f"{link_id}: no probe, nothing to resolve")

    ordered = sorted(probes, key=lambda p: p.probed_at)
    first, last = ordered[0].probed_at, ordered[-1].probed_at
    statuses = [p.status for p in ordered]

    if Status.ALIVE in statuses:
        status, rule = Status.ALIVE, "alive_once_wins"
    elif Status.RESTRICTED in statuses:
        status, rule = Status.RESTRICTED, "restricted_over_dead"
    else:
        dead = [p for p in ordered if p.status is Status.DEAD]
        distinct_dates = {p.probed_at.date() for p in dead}
        span_days = (last - first).days
        if (
            len(dead) >= 3
            and len(distinct_dates) >= 3
            and span_days >= settings.min_probe_span_days
        ):
            status, rule = Status.DEAD, "dead_three_failures_three_dates"
        else:
            status, rule = Status.UNKNOWN, "insufficient_evidence"

    return LinkOutcome(
        link_id=link_id,
        status=status,
        rule=rule,
        probes=ordered,
        first_probe_at=first,
        last_probe_at=last,
        right_censored=status is Status.ALIVE,
    )
