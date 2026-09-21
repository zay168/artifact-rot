"""Resolution DNS : distinguer « ce nom n'existe pas » d'un echec du resolveur.

**Decision de classification, prise le 2026-09-21, avant la passe 3 et donc avant
d'avoir vu le moindre resultat final.** C'est le moment ou elle doit etre prise : apres,
toute modification de la classification serait soupconnable d'avoir ete ajustee au
resultat, et le serait a juste titre.

### La question

Le §4 du plan definit `dead` comme « l'inexistence positivement confirmee » et `unknown`
comme « le crawler a echoue ». Ou tombe un nom de domaine qui ne resout plus ?

Mesure sur la passe 1 : sur 521 hotes derriere un echec de connexion ou une expiration
de delai, **174 n'ont aucun enregistrement DNS** — un tiers.

### La reponse retenue : `dead`

Un NXDOMAIN **n'est pas un echec du crawler**. Le systeme des noms de domaine a
repondu, et il a repondu que ce nom n'existe pas. Le crawler a parfaitement fonctionne ;
c'est la ressource qui a disparu, jusqu'a son adresse. Du point de vue du lecteur qui
veut reproduire, il n'y a rien a tenter.

Trois garde-fous, parce que la consequence est lourde :

1. **Seul `EAI_NONAME` compte.** `EAI_AGAIN` (echec temporaire) et `EAI_FAIL` restent
   `unknown`. Verifie sur cette plateforme : les codes sont bien distincts (11001,
   11002, 11003).
2. **La regle des trois passes s'applique sans exception.** Un domaine doit ne pas
   resoudre a trois dates espacees d'au moins dix jours pour etre declare mort. Une
   panne de resolveur d'un jour ne peut pas produire un lien mort.
3. **Le compte est reporte a part.** E6 doit publier le nombre de morts obtenues par
   `dns_nxdomain`, pour qu'un lecteur en desaccord avec ce choix puisse le soustraire
   et refaire le calcul. Une decision de classification qu'on ne peut pas defaire est
   une decision qu'on impose.
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
    """Le nom resout-il ? Resultat memorise : un run touche 2 000 hotes, pas 4 000 fois.

    Ne leve jamais. Un nom vide ou aberrant rend `unknown`, jamais une exception — meme
    exigence que partout ailleurs sur ce qui sort d'un PDF.
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
    except Exception:  # noqa: BLE001 — rien ne doit faire tomber une sonde
        verdict = "unknown"

    with _lock:
        _cache[host] = verdict
    return verdict


def reset_cache() -> None:
    """Vide la memoire des resolutions. Utile entre deux passes : dix jours separent
    une passe de la suivante, et un domaine peut avoir change d'etat."""
    with _lock:
        _cache.clear()
