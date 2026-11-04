"""Les serveurs qu'une personne fait joindre au moteur (une boîte, un service MCP) : sur Internet seulement, quand elle
n'est pas opératrice.

Une boîte ou un service branché par l'API par personne fait ouvrir au serveur une connexion vers l'hôte donné, et en
rend l'issue. Une personne qui n'est pas opératrice ne vise ni la machine elle-même ni le réseau privé où elle tourne
(la boucle locale, les réseaux privés, le lien local, les adresses réservées) : elle ne s'en sert pas pour sonder ce
qui n'est pas à elle. Un nom se résout au moment de l'enregistrer ; un nom qu'on ne résout pas passe (la connexion
échouera d'elle-même). Les opérateurs règlent tout depuis la console, comme avant.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

#: ce que dit un hôte refusé
LOCAL = "un serveur sur Internet : ni cette machine, ni le réseau privé où elle tourne"
#: les noms qui désignent la machine ou un réseau privé, sans même les résoudre
LOCAL_NAMES = ("localhost", ".localhost", ".local", ".internal", ".lan", ".home.arpa")


def _private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not ip.is_global or ip.is_multicast


async def local_host(host: str) -> bool:
    """Cet hôte désigne-t-il la machine ou son réseau privé (son adresse, son nom, ce qu'il résout) ?"""
    name = host.strip().strip("[]").rstrip(".").lower()
    if not name:
        return False
    if name == "localhost" or name.endswith(LOCAL_NAMES[1:]) or _private(name):
        return True
    try:
        found = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, name, None), timeout=3)
    except (OSError, TimeoutError, UnicodeError):
        return False
    return any(_private(str(info[4][0])) for info in found)


def url_host(url: str) -> str:
    try:
        return urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
