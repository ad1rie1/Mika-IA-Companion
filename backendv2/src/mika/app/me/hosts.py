"""Les serveurs qu'une personne fait joindre au moteur (une boîte, un service MCP) : sur Internet seulement, quand elle
n'est pas opératrice.

Une boîte ou un service branché par l'API par personne fait ouvrir au serveur une connexion vers l'hôte donné, et en
rend l'issue. Une personne qui n'est pas opératrice ne vise ni la machine elle-même (ses adresses, v4 et v6) ni le
réseau privé où elle tourne (la boucle locale, les réseaux privés, le lien local, les adresses réservées, une adresse
privée déguisée en IPv6, NAT64 compris) : elle ne s'en sert pas pour sonder ce qui n'est pas à elle. C'est la règle
d'``adapters/addresses.py`` (ADR 0228), celle de la Forge et des articles d'un flux, sur les adresses (un hôte se
donne ici sans le port). Un nom se résout au moment de l'enregistrer ; un nom qu'on ne résout pas passe (la connexion
échouera d'elle-même). Les opérateurs règlent tout depuis la console, comme avant.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from mika.adapters import addresses

#: ce que dit un hôte refusé
LOCAL = "un serveur sur Internet : ni cette machine, ni le réseau privé où elle tourne"
#: les noms qui désignent la machine ou un réseau privé, sans même les résoudre
LOCAL_NAMES = ("localhost", ".localhost", ".local", ".internal", ".lan", ".home.arpa")


def _private(address: str, mine: frozenset[addresses.IP]) -> bool:
    """Une adresse qui n'est pas d'Internet, ou une de la machine (``mine``) : la règle d'``adapters/addresses.py`` ;
    ce qui n'est pas une adresse ne l'est pas."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not addresses.is_global(ip) or ip in mine


async def local_host(host: str) -> bool:
    """Cet hôte désigne-t-il la machine ou son réseau privé (son adresse, son nom, ce qu'il résout) ?"""
    name = host.strip().strip("[]").rstrip(".").lower()
    if not name:
        return False
    if name == "localhost" or name.endswith(LOCAL_NAMES[1:]):
        return True
    mine = await asyncio.to_thread(addresses.LOCAL.get)  # relues au plus toutes les cinq minutes, hors de la boucle
    if _private(name, mine):
        return True
    try:
        found = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, name, None), timeout=3)
    except (OSError, TimeoutError, UnicodeError):
        return False
    return any(_private(str(info[4][0]), mine) for info in found)


def url_host(url: str) -> str:
    try:
        return urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
