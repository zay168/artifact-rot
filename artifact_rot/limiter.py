"""Limiteur de debit par hote, pour une execution concurrente.

La premiere version de l'ordonnanceur sondait **un lien a la fois**, dans tout le run.
Or la file porte 2 230 hotes distincts : attendre dix-huit secondes entre deux requetes
au NCBI n'oblige en rien a ne rien faire pendant ce temps chez les 2 229 autres.

La duree d'une passe passe donc de la **somme** des temps par hote a leur **maximum**.
Trois heures deviennent une quinzaine de minutes, sans qu'aucun hote ne recoive une
seule requete de plus ni plus vite : chaque hote garde exactement son debit.

C'est le point important, et il vaut d'etre ecrit noir sur blanc parce que « accelerer
un crawler » evoque generalement le contraire : **on n'accelere pas les hotes, on cesse
de les faire attendre les uns pour les autres.**
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class HostRateLimiter:
    """Un intervalle minimal entre deux requetes vers un meme hote.

    Sur, en concurrence : chaque hote a son propre verrou, et un thread qui doit
    patienter pour l'hote A ne bloque pas un thread qui travaille sur l'hote B.
    """

    def __init__(self, interval_for: callable) -> None:
        self._interval_for = interval_for
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._next_free: dict[str, float] = {}
        self._guard = threading.Lock()

    def acquire(self, host: str) -> float:
        """Attend le temps qu'il faut, puis reserve le creneau. Rend le temps attendu.

        La reservation est faite **avant** de dormir : deux threads vises sur le meme
        hote se serialisent proprement au lieu de partir ensemble apres la meme attente.
        """
        with self._guard:
            lock = self._locks[host]
        with lock:
            interval = self._interval_for(host)
            now = time.monotonic()
            due_at = self._next_free.get(host, now)
            wait = max(0.0, due_at - now)
            self._next_free[host] = max(now, due_at) + interval
        if wait:
            time.sleep(wait)
        return wait
