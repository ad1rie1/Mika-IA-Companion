"""La cage bubblewrap commune (ADR 0020 §8, 0039 §1, 0064 §10) : ce que voit un programme qu'on ne laisse pas
toucher à la machine — l'atelier d'un projet, un serveur MCP lancé ici.

- *Le système en lecture* : ``/usr``, ``/bin``, ``/sbin``, ``/lib``, ``/lib64`` (liens gardés), ``/proc``,
  ``/dev``, un ``/tmp`` éphémère, quelques fichiers de ``/etc`` (et, avec le réseau, ceux des certificats).
- *Le réseau à part* (``isolated``) : pasta, IPv4 seulement, aucun port relayé, une passerelle qui n'est pas l'hôte,
  un résolveur qui n'existe nulle part ailleurs, et des routes « unreachable » vers tout ce qui n'est pas Internet
  (le réseau local, l'hôte, les métadonnées d'un nuage) — posées avant d'entrer dans la cage, qui n'a plus aucune
  capacité pour les retirer.

Ce module ne lance rien : il construit des lignes de commande. Sans bubblewrap, rien ne se lance (pas de repli).
"""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
from pathlib import Path

SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
SYSTEM_FILES = ("/etc/passwd", "/etc/group", "/etc/nsswitch.conf", "/etc/ld.so.cache", "/etc/localtime")
NETWORK_FILES = ("/etc/hosts", "/etc/ssl", "/etc/pki", "/etc/ca-certificates")
#: le réseau à part : une adresse, une passerelle et un résolveur qui n'existent nulle part (TEST-NET-1, RFC 5737)
NET_ADDRESS, NET_GATEWAY, NET_DNS = "192.0.2.2", "192.0.2.1", "192.0.2.3"
#: ce que le réseau à part ne joint jamais : le réseau local, l'opérateur, les métadonnées d'un nuage, le réservé
#: (la boucle locale de la cage est la sienne : rien de l'hôte n'y est relayé)
UNREACHABLE = ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
               "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4",
               "240.0.0.0/4")
RESOLVER = f"nameserver {NET_DNS}\noptions timeout:3 attempts:2\n"


def system(network: str) -> list[str]:
    """Les montages du système, en lecture (``network`` non vide : aussi les fichiers du réseau)."""
    args: list[str] = []
    for d in SYSTEM_DIRS:
        p = Path(d)
        if p.is_symlink():
            args += ["--symlink", os.readlink(p), d]
        elif p.is_dir():
            args += ["--ro-bind", d, d]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for f in SYSTEM_FILES + (NETWORK_FILES if network else ()):
        if Path(f).exists():
            args += ["--ro-bind", f, f]
    return args


#: les dossiers des cages (``forge/``, ``ateliers/``, ``mcp/``) : à l'utilisateur de Mika seul — des bases d'apps, des
#: dépôts, des données personnelles
HOME_MODE = 0o700


def head(bwrap: str, network: str) -> list[str]:
    """Le début d'une cage : tout délié, aucune capacité, aucun espace d'utilisateur imbriqué (``--disable-userns`` :
    ce qui tient la cage ne se refait pas dedans — il exige ``--unshare-user`` dit explicitement, ``--unshare-all``
    ne fait qu'essayer) ; ``network`` non vide : le réseau de l'espace où elle entre (celui de pasta pour
    ``isolated``, où l'on est « root » : la cage reprend son utilisateur)."""
    args = [bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--unshare-user", "--disable-userns",
            "--cap-drop", "ALL"]
    if network:
        args.append("--share-net")
    if network == "isolated":
        args += ["--uid", str(os.getuid()), "--gid", str(os.getgid())]
    return args


def resolver(directory: Path) -> Path:
    """Le résolveur que voit le réseau à part (celui que relaie pasta), jamais celui de l'hôte."""
    directory.mkdir(parents=True, exist_ok=True)
    conf = directory / "resolv.conf"
    if not conf.exists() or conf.read_text(encoding="utf-8") != RESOLVER:
        conf.write_text(RESOLVER, encoding="utf-8")
    return conf


def isolated(inner: list[str], *, pasta: str, ip: str, sh: str,
             addresses: list[ipaddress.IPv4Address]) -> list[str]:
    """``inner`` (la cage) dans un réseau à part (voir l'en-tête du module)."""
    routes = list(UNREACHABLE)
    nets = [ipaddress.ip_network(r) for r in UNREACHABLE]
    for addr in addresses:
        if not any(addr in n for n in nets):
            routes.append(f"{addr}/32")
    script = "; ".join(f"{ip} route add unreachable {r} || exit 97" for r in dict.fromkeys(routes))
    return [pasta, "--config-net", "--quiet", "-4", "-a", NET_ADDRESS, "-n", "24", "-g", NET_GATEWAY,
            "--no-map-gw", "--dns-forward", NET_DNS, "-t", "none", "-u", "none", "-T", "none", "-U", "none",
            "--", sh, "-c", script + '; exec "$0" "$@"', *inner]


def private_root(root: Path) -> Path:
    """Le dossier racine d'une cage, créé au besoin et à son propriétaire seul (``HOME_MODE``, posé à chaque fois :
    un dossier né sous l'umask d'avant le devient aussi)."""
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, HOME_MODE)
    return root


def host_addresses(ip: str) -> list[ipaddress.IPv4Address]:
    """Les adresses IPv4 de la machine elle-même (celles que le réseau à part rend injoignables : pasta ne parle
    qu'IPv4) ; au mieux : sans réponse, la liste est vide."""
    return [a for a in all_host_addresses(ip) if isinstance(a, ipaddress.IPv4Address)]


def all_host_addresses(ip: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Toutes les adresses de la machine elle-même, v4 et v6 (l'adresse publique d'un serveur joindrait ses propres
    services) ; au mieux : sans réponse, la liste est vide."""
    try:
        r = subprocess.run([str(ip), "-o", "addr", "show"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_addresses(r.stdout)


def parse_addresses(listing: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Les adresses d'une sortie de ``ip -o addr show`` (``inet a.b.c.d/n``, ``inet6 x::y/n``) ; une adresse
    illisible est écartée."""
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for m in re.finditer(r"\binet6? ([0-9A-Fa-f.:]+)", listing):
        try:
            out.append(ipaddress.ip_address(m.group(1)))
        except ValueError:
            continue
    return out
