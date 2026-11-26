"""Ce que partagent les capacités des projets (``atelier.py``, ``issues.py``, ``pulls.py``) : ce qui part de la
machine après l'accord, par les ports, jamais d'un outil.

Le projet qu'un effet concerne (``effect_project``), pourquoi il ne s'exécute plus pour lui (``project_refusal`` :
il n'existe plus, il est archivé), l'empreinte de ce qu'un aperçu montre (``pin_of``) et ce que l'hôte du dépôt
distant en dit (``hosted_remote``).

Ce que partagent les outils est dans ``tool_common.py``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from mika.contracts import projects as c
from mika.ports.workshop import Hosted
from mika.vocab.episodes import project_of


def effect_project(args: Mapping[str, Any], context: str) -> int | None:
    pid = project_of(context)
    return pid if pid is not None and args.get("project") == pid else None


def project_refusal(ports: Mapping[str, Any], pid: int) -> str:
    """Pourquoi un effet ne s'exécute plus pour ce projet (vide : il peut) : archivé, il ne sort plus rien,
    même approuvé avant."""
    frame = ports["frame"]() if "frame" in ports else None
    p = frame.state("projects").projects.get(pid) if frame is not None else None
    if frame is not None and p is None:
        return "refusé : ce projet n'existe plus"
    if p is not None and p.status == c.ARCHIVED:
        return "refusé : ce projet est archivé"
    return ""


def pin_of(**what: Any) -> str:
    raw = json.dumps(what, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def hosted_remote(ports: Mapping[str, Any], url: str, branch: str) -> Hosted | None:
    """Ce que l'hôte du dépôt distant en dit (GitHub), ou rien : pas d'hôte qui le lise, ou il n'a pas répondu."""
    host = ports.get("repo_host")
    if host is None or not url or not host.handles(url):
        return None
    got = await host.read(url, branch)
    return None if got.error else got
