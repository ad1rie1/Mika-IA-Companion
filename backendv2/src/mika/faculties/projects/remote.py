"""L'envoi d'un projet à son dépôt distant (ADR 0274, 0276, 0277) : ce qui part, quel commit, vers quelle branche.

Un envoi ne part jamais d'un outil : il se propose (``propose_push`` : un ``effect.proposed`` de la capacité
``projects.push``), exécuté tout de suite ou après accord selon le projet.

- **Le commit est épinglé** au moment de proposer (``pinned``) : l'accord vaut pour ce qui a été montré, pas pour ce
  que l'atelier deviendra d'ici là ; son résumé (``push_summary``) dit le commit, son titre, le dépôt et la branche.
- **Un seul envoi attend un accord à la fois** (``pending_push``) : les suivants le suivront, rien ne s'empile.
- **Sur un projet qui passe par des pull requests**, c'est la branche de travail où l'atelier se trouve qui part,
  jamais la base (``push_branch``) ; **sur un projet qui demande une relecture**, rien ne part sans un verdict
  favorable pour ce commit-là (``faculty.push_reviewed``).

Le lisent ``report_run`` (``tools.py`` : l'envoi automatique), ``project_push`` et l'aperçu de la capacité
``projects.push`` (``atelier.py``, où elle vit), et la relecture qui vient de dire un commit bon (``review.py``).
"""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    PROJECTS,
    PUSH_CAPABILITY,
    Project,
    by_pulls,
    push_reviewed,
    subjects_of,
    written,
)
from mika.kernel.events import Content
from mika.kernel.frame import Frame
from mika.ports.workshop import BASE_BRANCH
from mika.vocab.episodes import project_of, project_target


async def pinned(port: Any, project: int) -> tuple[str, str]:
    """Le commit courant de l'atelier et son titre : ce qu'un envoi approuvé enverra, et rien d'autre."""
    sha = await port.head(project) if port is not None and port.exists(project) else ""
    commits = await port.commits(project, 1) if sha else []
    return sha, commits[0].title if commits else ""


def push_summary(p: Project, sha: str, title: str, why: str, branch: str = "") -> str:
    return (f"Pousser le commit {sha[:12]} (« {title[:120]} ») vers {p.remote}, branche {branch or p.branch} — "
            f"{why}")[:600]


async def push_branch(port: Any, p: Project, branch: str = "") -> str:
    """La branche du dépôt distant qu'un envoi de ce projet vise : la sienne (``Project.branch``) ; sur un projet qui
    passe par des pull requests (ADR 0274), la branche de travail où l'atelier se trouve (``branch`` : celle qu'on
    sait déjà) — et rien (``""``) s'il est sur sa base : elle ne se pousse pas."""
    if not by_pulls(p):
        return p.branch
    current = branch or (await port.branch(p.id) if port is not None and port.exists(p.id) else "")
    return "" if not current or current in (BASE_BRANCH, p.branch) else current


def pending_push(frame: Frame, project: int) -> bool:
    """Un envoi de ce projet attend-il déjà un accord ?"""
    return any(v.capability == PUSH_CAPABILITY and project_of(v.context) == project
               for v in frame.get(rt.PENDING_EFFECTS))


async def propose_push(ctx: Any, p: Project, why: str, *, branch: str = "", reviewed: str = "") -> str:
    """Proposer d'envoyer l'atelier au dépôt distant (exécuté tout de suite ou après accord, selon le projet) :
    le commit est épinglé au moment de proposer — l'accord vaut pour ce qui a été montré, pas pour ce que
    l'atelier deviendra d'ici là. Un seul envoi attend un accord à la fois : les suivants le suivront (rien ne
    s'empile). Sur un projet qui passe par des pull requests, c'est sa branche de travail qui part (``branch`` :
    celle de l'exécution), jamais sa base (ADR 0274). Sur un projet qui demande une relecture (ADR 0276), rien ne
    part d'elle-même sans verdict favorable pour ce commit-là, au flux direct comme pour une branche de travail
    (ADR 0277 ; ``reviewed`` : le commit que la relecture qui propose vient de dire bon). Rend ``proposed``, ``sent``, ``pending`` (un envoi attend déjà),
    ``nothing``, ``base`` (l'atelier est sur sa base : rien ne s'y pousse) ou ``unreviewed``."""
    if p.approval and pending_push(ctx.frame, p.id):
        return "pending"
    port = ctx.ports.get("workshop")
    target = await push_branch(port, p, branch)
    if not target:
        return "base"
    sha, title = await pinned(port, p.id)
    if not sha:
        return "nothing"
    if sha != reviewed and not push_reviewed(p, sha):
        return "unreviewed"
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=PUSH_CAPABILITY, owner=PROJECTS.name, context=project_target(p.id), approval=p.approval,
        args_json=json.dumps({"project": p.id, "url": p.remote, "branch": target, "sha": sha}),
        # ses raisons sont ses mots, écrits pendant une exécution : au niveau de ce qu'elle y lit (ADR 0262)
        summary=Content.of(push_summary(p, sha, title, why, target), level=written(p)), about=subjects_of(p)))
    return "proposed" if p.approval else "sent"
