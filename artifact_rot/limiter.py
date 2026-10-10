"""Per-host rate limiter, for concurrent execution.

The first version of the scheduler probed **one link at a time** across the whole run.
Yet the queue holds over 2,000 distinct hosts: waiting eighteen seconds between two NCBI
requests in no way requires doing nothing at the others in the meantime.

A pass therefore goes from the **sum** of per-host times to their **maximum**. Three
hours become about fifteen minutes, without any host receiving a single extra request,
or receiving one faster: each host keeps exactly its rate.

That is the important point, worth stating plainly because "speeding up a crawler"
usually suggests the opposite: **hosts are not sped up, they stop waiting for each
other.**
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class HostRateLimiter:
    """A minimum interval between two requests to the same host.

    Safe under concurrency: each host has its own lock, and a thread that must wait for
    host A does not block a thread working on host B.
    """

    def __init__(self, interval_for: callable) -> None:
        self._interval_for = interval_for
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._next_free: dict[str, float] = {}
        self._guard = threading.Lock()

    def acquire(self, host: str) -> float:
        """Wait as long as needed, then book the slot. Returns the time waited.

        The booking happens **before** sleeping: two threads targeting the same host are
        serialised properly instead of leaving together after the same wait.
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
