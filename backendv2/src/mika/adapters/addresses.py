"""Une adresse publique : la seule règle qui dit où peut aller une requête dont l'adresse vient du dehors (ADR 0228).

**Internet seulement** : ni la machine elle-même — ses adresses v4 et v6, relues au plus toutes les
``LOCAL_REFRESH_S`` secondes —, ni le port où Mika écoute (même sous une adresse qui n'est pas la sienne : une box qui
relaie ce port vers elle), ni le réseau local (la boucle locale, les réseaux privés, le lien local, l'espace partagé
d'un opérateur, les plages réservées, la multidiffusion), ni une adresse privée déguisée en IPv6 (correspondance,
6to4, Teredo, NAT64). Toutes les adresses d'un nom doivent passer ; on se connecte ensuite à l'une d'elles, jamais à
une seconde résolution (qui pourrait répondre autre chose).

Qui la lit :

- la Forge, à chaque saut d'une requête d'une app (``resolve_public``, ADR 0105) ;
- les flux, pour l'adresse d'un article (à chaque saut) et pour la redirection qui quitte l'hôte d'un flux : ils
  résolvent eux-mêmes, en asynchrone, et jugent ce qu'ils ont obtenu (``refusal``, qui dit pourquoi sans
  l'adresse) ;
- l'API par personne, pour les serveurs qu'une personne qui n'est pas opératrice fait joindre — une boîte, un service
  MCP (``app/me/hosts.py`` : ``is_global`` et ``LOCAL`` ; un hôte s'y donne sans le port).

Gardent leur règle à part : le serveur de recherche du plugin web, un programme lancé dans sa cage, et la règle
inverse des services MCP en http (``mcp/config.py``, ``private_host`` : du http seulement vers la machine ou le réseau
local, pour que le jeton ne passe pas en clair).
"""

from __future__ import annotations

import ipaddress
import shutil
import socket
import threading
import time
from collections.abc import Callable, Collection, Iterable

from mika.adapters import cage

#: le préfixe NAT64 bien connu : l'adresse IPv4 qu'il porte compte, pas lui
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
#: les adresses de la machine elle-même sont relues au plus toutes les tant de secondes (une adresse qui apparaît —
#: un câble branché, un VPN — est refusée au plus tard un peu après)
LOCAL_REFRESH_S = 300.0

IP = ipaddress.IPv4Address | ipaddress.IPv6Address


class LocalAddresses:
    """Les adresses de la machine elle-même (v4 et v6, ``cage.all_host_addresses``), relues au plus toutes les
    ``ttl_s`` secondes : une app ne joint ni Mika, ni MariaDB, ni SSH par l'adresse publique de l'hôte — pasta les
    rend injoignables à l'atelier, ``resolve_public`` les refuse aux apps, qui n'ont pas de réseau à elles."""

    def __init__(self, read: Callable[[], Iterable[IP]], *, ttl_s: float = LOCAL_REFRESH_S,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._read = read
        self._ttl = ttl_s
        self._now = monotonic
        self._at: float | None = None
        self._got: frozenset[IP] = frozenset()
        self._lock = threading.Lock()

    def get(self) -> frozenset[IP]:
        with self._lock:
            now = self._now()
            if self._at is None or now - self._at >= self._ttl:
                self._got = frozenset(self._read())
                self._at = now
            return self._got


def _host_addresses() -> list[IP]:
    ip = shutil.which("ip")
    return cage.all_host_addresses(ip) if ip else []


#: les adresses de l'hôte, et les ports où Mika écoute elle-même (``serving_on``, posé par ``serve``) : refusés
LOCAL = LocalAddresses(_host_addresses)
SERVER_PORTS: set[int] = set()


def serving_on(port: int) -> None:
    """Le serveur dit le port où il écoute : une app ne le joint pas, même sous une adresse qui n'est pas celle de la
    machine (une box qui relaie ce port vers elle)."""
    SERVER_PORTS.add(int(port))


def is_global(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Une adresse joignable d'Internet et rien d'autre : ni la machine, ni le réseau local, ni l'espace partagé
    d'un opérateur (100.64/10), ni une adresse IPv4 privée déguisée en IPv6 (correspondance, 6to4, Teredo,
    NAT64)."""
    if ip.is_multicast or not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return is_global(embedded)
    return True


#: les trois raisons d'un refus (``refusal``)
PORT, PRIVATE, MACHINE = "port", "private", "machine"


def _serves(port: int, server_ports: Collection[int] | None) -> bool:
    return int(port) in (SERVER_PORTS if server_ports is None else set(server_ports))


def _refused(why: str, host: str, port: int) -> ValueError:
    """Le refus tel que la Forge l'a toujours dit : une ``ValueError`` simple, que son journal nomme ainsi."""
    said = {PORT: f"le port {port} est celui du serveur lui-même : refusé",
            PRIVATE: f"« {host} » est une adresse privée : refusée",
            MACHINE: f"« {host} » est cette machine : refusée"}
    return ValueError(said[why])


def refusal(ips: Collection[IP], port: int, *, local: Collection[IP] | None = None,
            server_ports: Collection[int] | None = None) -> str | None:
    """Pourquoi la règle refuse ces adresses déjà résolues, ou ``None`` : ``PORT`` si ``port`` est un de ceux où
    Mika écoute (``server_ports`` ; sinon ``SERVER_PORTS``), ``PRIVATE`` s'il n'y en a aucune ou si l'une n'est pas
    publique (``is_global``), ``MACHINE`` si l'une est celle de la machine (``local`` ; sinon ``LOCAL``, relues au
    plus toutes les ``LOCAL_REFRESH_S`` secondes). Les flux la lisent pour redire le refus sans l'adresse."""
    if _serves(port, server_ports):
        return PORT
    if not ips or not all(is_global(ip) for ip in ips):
        return PRIVATE
    mine = LOCAL.get() if local is None else frozenset(local)
    if any(ip in mine for ip in ips):
        return MACHINE
    return None


def check_public(host: str, ips: Collection[IP], port: int, *, local: Collection[IP] | None = None,
                 server_ports: Collection[int] | None = None) -> None:
    """Juge les adresses déjà résolues de ``host`` (``refusal``) : un refus lève une ``ValueError`` qui le dit avec
    l'hôte ou le port, aux mots de la Forge."""
    why = refusal(ips, port, local=local, server_ports=server_ports)
    if why is not None:
        raise _refused(why, host, port)


def resolve_public(host: str, port: int = 443, *, local: Collection[IP] | None = None,
                   server_ports: Collection[int] | None = None) -> list[IP]:
    """Résout ``host`` **une fois** et juge ses adresses (``check_public``) : toutes doivent être publiques **et** ne
    pas être celles de la machine (``local`` ; sinon ``LOCAL``, relues au plus toutes les ``LOCAL_REFRESH_S``
    secondes), et ``port`` ne doit pas être un de ceux où Mika écoute (``server_ports`` ; sinon ``SERVER_PORTS`` :
    refusé avant même de résoudre) — sinon ``ValueError``. On se connecte ensuite à l'une d'elles, jamais à une
    seconde résolution (qui pourrait répondre autre chose)."""
    if _serves(port, server_ports):
        raise _refused(PORT, host, port)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"« {host} » ne se résout pas") from exc
    ips = list(dict.fromkeys(ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos))
    check_public(host, ips, port, local=local, server_ports=server_ports)
    return ips


def public_host(host: str) -> bool:
    """Ce nom mène-t-il à Internet seulement (``resolve_public`` sur le port 443) ? Le défaut de ``ForgeHost``
    (``public=``) quand un faux réseau qui ne sait que lire tient lieu du vrai."""
    try:
        resolve_public(host)
    except ValueError:
        return False
    return True
