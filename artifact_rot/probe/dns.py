"""DNS resolution: distinguishing "this name does not exist" from a resolver failure.

**Classification decision, taken on 2026-09-21, before pass 3 and therefore before
seeing any final result.** That is when it must be taken: afterwards, any change to the
classification could be suspected of having been tuned to the result, and rightly so.

### The question

The plan's §4 defines `dead` as "positively confirmed non-existence" and `unknown` as
"the crawler failed". Where does a domain name that no longer resolves fall?

Measured on pass 1: of 521 hosts behind a connection failure or a timeout, **174 have no
DNS record at all** — one third.

### The answer adopted: `dead`

An NXDOMAIN **is not a crawler failure**. The domain name system answered, and it
answered that this name does not exist. The crawler worked perfectly; it is the resource
that disappeared, down to its address. From the point of view of a reader wanting to
reproduce, there is nothing left to try.

Three safeguards, because the consequence is heavy:

1. **Only `EAI_NONAME` counts.** `EAI_AGAIN` (temporary failure) and `EAI_FAIL` stay
   `unknown`. Checked on this platform: the codes are indeed distinct (11001, 11002,
   11003).
2. **The three-pass rule applies without exception.** A domain must fail to resolve on
   three dates at least ten days apart to be declared dead. A one-day resolver outage
   cannot produce a dead link.
3. **The count is reported separately.** E6 must publish the number of deaths obtained
   through `dns_nxdomain`, so that a reader who disagrees with this choice can subtract
   it and redo the computation. A classification decision that cannot be undone is a
   decision imposed on the reader.
"""

from __future__ import annotations

import socket
import threading
from typing import Literal

DnsVerdict = Literal["resolves", "nxdomain", "transient", "unknown"]

_NXDOMAIN_ERRNOS = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
_TRANSIENT_ERRNOS = {
    getattr(socket, "EAI_AGAIN", -3),
    getattr(socket, "EAI_FAIL", -4),
    11002,  # WSATRY_AGAIN
    11003,  # WSANO_RECOVERY
}

_cache: dict[str, DnsVerdict] = {}
_lock = threading.Lock()


def resolve(host: str) -> DnsVerdict:
    """Does the name resolve? Result memoised: a run touches 2,000 hosts, not 4,000 times.

    Never raises. An empty or aberrant name returns `unknown`, never an exception — same
    requirement as everywhere else for whatever comes out of a PDF.
    """
    if not host:
        return "unknown"
    with _lock:
        cached = _cache.get(host)
    if cached is not None:
        return cached

    verdict: DnsVerdict
    try:
        socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        verdict = "resolves"
    except socket.gaierror as exc:
        if exc.errno in _NXDOMAIN_ERRNOS:
            verdict = "nxdomain"
        elif exc.errno in _TRANSIENT_ERRNOS:
            verdict = "transient"
        else:
            verdict = "unknown"
    except Exception:  # noqa: BLE001 — nothing may bring down a probe
        verdict = "unknown"

    with _lock:
        _cache[host] = verdict
    return verdict


def reset_cache() -> None:
    """Clear the resolution memory. Useful between two passes: ten days separate one pass
    from the next, and a domain may have changed state."""
    with _lock:
        _cache.clear()
