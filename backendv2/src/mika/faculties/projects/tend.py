"""Les processus des projets.

**Tenir** (``projects.tend``) : un objectif qui n'a rien conclu trois
exécutions de suite bloque ; un ponctuel à bout d'exécutions aussi ; un projet
dont le modèle ne répond plus trois fois d'affilée se met en pause (« en
panne ») — sans reproche, et rien ne le relance avant qu'on le reprenne.

**Le dépôt distant** (``projects.remote``) : ce qu'un opérateur demande depuis
la console (pousser, récupérer) devient une proposition d'effet, exécutée
tout de suite par le runtime (c'est lui qui l'a demandé).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.atelier import remote_proposal
from mika.faculties.projects.faculty import (
    OBJECTIVE_CHANGED,
    PAUSED,
    PROJECTS,
    REMOTE_REQUESTED,
    Objective,
    Project,
    ProjectsState,
    busy,
    params,
)
from mika.faculties.projects.tools import closing
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard

#: l'écart minimal entre deux passes de « tenir » qui trouvent encore quelque chose à faire
RETRY_US = MINUTE


def closures(s: ProjectsState, frame: Frame) -> list[tuple[Project, Objective, str]]:
    """Les objectifs qui doivent bloquer maintenant : (projet, objectif, raison)."""
    pm = params(frame.env.params_of("projects", frame.root))
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status != c.ACTIVE or busy(s, p.id):
            continue
        for o in p.objectives:
            if o.status != c.OPEN:
                continue
            if o.silent >= pm.silent_before_blocked:
                out.append((p, o, f"{o.silent} exécutions de suite sans rien conclure"))
            elif o.kind == c.ONCE and o.runs >= pm.once_runs_max:
                out.append((p, o, f"à bout d'exécutions ({o.runs}) sans en venir à bout"))
    return out


def broken(s: ProjectsState, frame: Frame) -> list[Project]:
    """Les projets actifs dont le modèle a échoué trop de fois d'affilée."""
    pm = params(frame.env.params_of("projects", frame.root))
    return [p for p in sorted(s.projects.values(), key=lambda p: p.id)
            if p.status == c.ACTIVE and not busy(s, p.id) and p.failures >= pm.failures_before_pause]


@PROJECTS.process("projects.tend", wake_on=[*c.ALL, rt.EPISODE_STARTED, rt.EPISODE_ENDED], lane="background",
                  catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=40)
class Tend:
    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        if not (closures(s, frame) or broken(s, frame)):
            return None
        # par prudence : une passe qui vient d'avoir lieu sans rien changer (écriture dédoublonnée, garde) ne
        # repart pas aussitôt — au pire une minute de retard, jamais une boucle
        return frame.now if last_run is None else max(frame.now, last_run + RETRY_US)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        s: ProjectsState = ctx.state
        drafts: list[Any] = []
        closing_now = closures(s, frame)
        for p, o, why in closing_now:
            # une clé par exécution : rouvert puis rebloqué, l'objectif a eu d'autres exécutions depuis (la même
            # clé serait dédoublonnée, rien ne s'écrirait, et le processus repartirait aussitôt)
            key = f"blocage:{p.id}:{o.id}:{o.last_run_at}:{o.runs}:{o.silent}"
            if o.kind == c.ONCE:  # un ponctuel qui bloque : ce qu'il fait ressentir dépend du mode
                drafts.append(replace(closing(ctx, p, o, c.BLOCKED, why, 0.0), dedupe_key=key))
            else:  # un constant ne se clôt pas : il est mis de côté, sans ressenti, et l'opérateur le rouvre
                drafts.append(OBJECTIVE_CHANGED.draft(
                    project=p.id, objective=o.id, status=c.BLOCKED, note=Content.of(why, level=p.sensitivity),
                    owner=p.owner, about=p.about, dedupe_key=key))
        for p in broken(s, frame):
            drafts.append(PAUSED.draft(project=p.id, reason=f"en panne : {p.failures} exécutions de suite ont échoué "
                                                            "(le modèle n'a pas répondu, ou le délai d'une exécution "
                                                            "est passé)", owner=p.owner, about=p.about,
                                       dedupe_key=f"panne:{p.id}:{p.tried_at}"))
        if not drafts:
            return
        ids = tuple({p.id for p, _, _ in closing_now} | {p.id for p in broken(s, frame)})
        keys = tuple((p.id, o.id) for p, o, _ in closing_now)
        await ctx.emit(*drafts, guard=Guard("projets actifs, objectifs ouverts", predicate=lambda view, ids=ids,
                                            keys=keys: all(view.get(c.STATUS(i)) == c.ACTIVE for i in ids)
                                            and all(view.get(c.OBJECTIVE_STATUS(k)) == c.OPEN for k in keys)))


@PROJECTS.process("projects.remote", wake_on=[REMOTE_REQUESTED, rt.EFFECT_PROPOSED], lane="background",
                  catch_up=CatchUp.ONCE, max_quantum_s=60, priority=40)
class Remote:
    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if any(p.requests and p.remote for p in s.projects.values()) else None

    async def run(self, ctx: Any) -> None:
        s: ProjectsState = ctx.state
        port = ctx.ports.get("workshop")
        drafts = [await remote_proposal(p, what, seq, port) for p in sorted(s.projects.values(), key=lambda p: p.id)
                  if p.remote and p.status != c.ARCHIVED for seq, what in p.requests]
        if drafts:
            await ctx.emit(*drafts, emitter=rt.OWNER)
