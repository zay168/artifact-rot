"""Statut final d'un lien = fonction deterministe de ses sondes (§5).

Aucun jugement au cas par cas. La regle appliquee est nommee dans le resultat pour que
chaque ligne du rapport soit auditable jusqu'a la sonde qui l'a produite.

Ordre de priorite, du plus informatif au moins informatif :

1. ALIVE l'emporte sur tout. Une ressource observee vivante une seule fois a une date
   quelconque a existe : la declarer morte serait faux. C'est asymetrique a dessein —
   un faux positif de mort detruit le projet (§4 piege 2), un faux negatif le rend
   seulement conservateur.
2. RESTRICTED l'emporte sur DEAD. Un acces controle est une existence confirmee.
3. DEAD exige trois echecs sur trois dates distinctes, espacees d'au moins
   `min_probe_span_days`. Un lien qui n'a pas subi ces trois sondes n'est pas mort :
   il est UNKNOWN.
4. UNKNOWN sinon. Il est compte et reporte a part, jamais au denominateur.
"""

from __future__ import annotations

from .config import Settings
from .models import LinkOutcome, Probe, Status


def resolve(link_id: str, probes: list[Probe], settings: Settings) -> LinkOutcome:
    if not probes:
        raise ValueError(f"{link_id}: aucune sonde, rien a resoudre")

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
