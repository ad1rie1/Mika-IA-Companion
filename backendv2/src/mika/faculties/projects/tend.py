"""Les processus des projets.

**Tenir** (``projects.tend``) : un objectif qui n'a rien conclu trois
exécutions de suite bloque ; un ponctuel à bout d'exécutions aussi ; un projet
dont le modèle ne répond plus trois fois d'affilée se met en pause (« en
panne ») — sans reproche, et rien ne le relance avant qu'on le reprenne. Un
projet **à elle** qui n'a plus rien d'ouvert depuis quelques jours, elle le
clôt (soulagée s'il a abouti, un peu mélancolique sinon) : il ne reste pas
« en cours » pour toujours.

**Reprendre** : une demande d'aide dite (« j'ai besoin de toi pour… ») attend
la réponse de la personne à qui elle l'a dite ; dès qu'elle écrit, l'objectif
n'attend plus — sans attendre l'échéance de son « wait ».

**Ce qui sort** (``projects.remote``) : ce qu'un opérateur demande depuis la
console (pousser, récupérer) devient une proposition d'effet, exécutée tout de
suite par le runtime (c'est lui qui l'a demandé) ; une commande réseau qu'elle a
demandée sur un projet sans accord part quand l'exécution qui l'a demandée a
fini. Un projet archivé n'a plus rien en file : rien ne tourne en boucle.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from mika.contracts import forge as forge_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.projects.atelier import network_proposal, remote_proposal
from mika.faculties.projects.faculty import (
    ANSWERED,
    ARCHIVED,
    NETWORK_QUEUED,
    NUDGED,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PAUSED,
    PROJECTS,
    REMOTE_REQUESTED,
    Objective,
    Project,
    ProjectsState,
    busy,
    living,
    params,
)
from mika.faculties.projects.tools import closing, written
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.inspect import describe_error
from mika.vocab.phrasebook import phrase

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
                out.append((p, o, phrase("projects.stuck.silent", n=o.silent)))
            elif o.kind == c.ONCE and o.runs >= pm.once_runs_max:
                out.append((p, o, phrase("projects.stuck.spent", n=o.runs)))
    return out


def finished_at(p: Project, pm: Any) -> int | None:
    """Quand elle clôt un projet à elle qui n'a plus rien d'ouvert (``None`` : il n'en est pas là)."""
    if p.authority != c.SELF or p.status != c.ACTIVE or not p.objectives:
        return None
    if any(o.status == c.OPEN for o in p.objectives):
        return None
    return max(o.closed_at for o in p.objectives) + pm.self_done_after_us


def finished(s: ProjectsState, frame: Frame) -> list[Project]:
    """Ses projets à elle, finis depuis assez longtemps pour qu'elle les close."""
    pm = params(frame.env.params_of("projects", frame.root))
    return [p for p in sorted(s.projects.values(), key=lambda p: p.id)
            if not busy(s, p.id) and (at := finished_at(p, pm)) is not None and at <= frame.now]


def broken(s: ProjectsState, frame: Frame) -> list[Project]:
    """Les projets actifs dont le modèle a échoué trop de fois d'affilée."""
    pm = params(frame.env.params_of("projects", frame.root))
    return [p for p in sorted(s.projects.values(), key=lambda p: p.id)
            if p.status == c.ACTIVE and not busy(s, p.id) and p.failures >= pm.failures_before_pause]


def replied(s: ProjectsState, frame: Frame) -> list[tuple[Project, Objective]]:
    """Les objectifs ouverts dont la personne à qui elle a dit son besoin a écrit depuis — elle seule (une autre
    personne ne lève rien), après la demande (pas avant). Pas pendant une exécution : celle-ci ne verrait pas la
    réponse, et le « wait » qu'elle conclurait reposerait l'attente ; elle tombera à la fin."""
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status != c.ACTIVE or busy(s, p.id):
            continue
        for o in p.objectives:
            if o.status != c.OPEN or not o.asked or not o.asked_to or not o.need_ref or o.answered_at >= o.asked_at:
                continue
            handles = frame.get(identity_c.HANDLES(o.asked_to)) or (o.asked_to,)
            if max(frame.get(transcript_c.LAST_FROM(h)) for h in handles) > o.asked_at:
                out.append((p, o))
    return out


def pause_reason(p: Project) -> str:
    """Pourquoi un projet en panne se met en pause : combien d'échecs, et la cause du dernier telle qu'elle a été
    (un prompt trop long n'est ni un modèle muet ni un délai passé : ADR 0142)."""
    cause = describe_error(p.last_failure) if p.last_failure else "le modèle n'a pas répondu"
    return f"en panne : {p.failures} exécutions de suite ont échoué (la dernière : {cause})"


@PROJECTS.process("projects.tend", wake_on=[*c.ALL, rt.EPISODE_STARTED, rt.EPISODE_ENDED, rt.PERCEPTION_RECEIVED],
                  lane="background",
                  catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=40)
class Tend:
    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        if not (closures(s, frame) or broken(s, frame) or finished(s, frame) or replied(s, frame)):
            pm = params(frame.env.params_of("projects", frame.root))
            later = [at for p in s.projects.values() if (at := finished_at(p, pm)) is not None]
            return min(later) if later else None
        # par prudence : une passe qui vient d'avoir lieu sans rien changer (écriture dédoublonnée, garde) ne
        # repart pas aussitôt — au pire une minute de retard, jamais une boucle
        return frame.now if last_run is None else max(frame.now, last_run + RETRY_US)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        s: ProjectsState = ctx.state
        released = [ANSWERED.draft(project=p.id, objective=o.id, person=o.asked_to, owner=p.owner, about=p.about,
                                   dedupe_key=f"réponse:{p.id}:{o.id}:{o.asked_at}") for p, o in replied(s, frame)]
        if released:
            await ctx.emit(*released)
            frame = ctx.frame
            s = frame.state("projects")
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
            drafts.append(PAUSED.draft(project=p.id, reason=pause_reason(p), owner=p.owner, about=p.about,
                                       dedupe_key=f"panne:{p.id}:{p.tried_at}"))
        done_now = finished(s, frame)
        for p in done_now:  # elle le clôt elle-même : il a fait son temps (ou elle y renonce, rien n'a abouti)
            ending = "done" if any(o.status == c.DONE for o in p.objectives) else "dropped"
            drafts.append(ARCHIVED.draft(project=p.id, reason="clos par elle : plus rien d'ouvert depuis quelques "
                                                              "jours", by="self", ending=ending, owner=p.owner,
                                         about=p.about, dedupe_key=f"fini:{p.id}:{max(o.closed_at for o in p.objectives)}"))
        if not drafts:
            return
        ids = tuple({p.id for p, _, _ in closing_now} | {p.id for p in broken(s, frame)} | {p.id for p in done_now})
        keys = tuple((p.id, o.id) for p, o, _ in closing_now)
        await ctx.emit(*drafts, guard=Guard("projets actifs, objectifs ouverts", predicate=lambda view, ids=ids,
                                            keys=keys: all(view.get(c.STATUS(i)) == c.ACTIVE for i in ids)
                                            and all(view.get(c.OBJECTIVE_STATUS(k)) == c.OPEN for k in keys)))


def to_repair(s: ProjectsState, frame: Frame) -> list[tuple[Project, Any]]:
    """Les apps d'un projet actif tombées en panne — pas arrêtées par un opérateur, c'est à lui de les relancer —
    dont la version cassée n'a pas encore son objectif « Réparer » (ADR 0104). Une panne n'attend plus qu'une pensée
    assez forte, à une heure assez libre, ouvre une exploration : le projet qui l'a fait naître la répare."""
    out = []
    for a in frame.get(forge_c.APPS) or ():
        p = s.projects.get(a.project) if a.project else None
        if p is None or p.status != c.ACTIVE or not forge_c.failure(a) or a.held or living(p) >= OBJECTIVES_KEPT:
            continue
        if not any(o.app == f"{a.name}@{a.version}" for o in p.objectives):
            out.append((p, a))
    return out


@PROJECTS.process("projects.apps", wake_on=[forge_c.SIGNALED, *c.ALL], lane="background", catch_up=CatchUp.ONCE,
                  max_quantum_s=3600, priority=40)
class Apps:
    """La panne d'une app rattachée : un objectif « Réparer » sur son projet, et une exécution tout de suite."""

    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        if not to_repair(s, frame):
            return None
        return frame.now if last_run is None else max(frame.now, last_run + RETRY_US)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        for p, a in to_repair(ctx.state, frame):
            number = p.objective_seq + 1
            text = phrase("projects.repair.objective", title=a.title, app=a.name, error=forge_c.failure(a)[:200])
            await ctx.emit(
                OBJECTIVE_ADDED.draft(project=p.id, objective=number, text=Content.of(text, level=written(p)),
                                      kind=c.ONCE, author="self", app=f"{a.name}@{a.version}", owner=p.owner,
                                      about=p.about, dedupe_key=f"réparer:{p.id}:{a.name}:{a.version}"),
                NUDGED.draft(project=p.id, objective=number, owner=p.owner, about=p.about,
                             dedupe_key=f"réparer:maintenant:{p.id}:{a.name}:{a.version}"))


def waiting(s: ProjectsState) -> list[tuple[Project, str, int, Any]]:
    """Ce qui est prêt à sortir : (projet, sorte, demande, détail) — les demandes de l'opérateur (pousser,
    récupérer) d'un projet qui a un dépôt distant, et ses commandes réseau en file d'un projet actif dont aucune
    exécution n'occupe l'atelier. Le même filtre décide de l'échéance et de ce qui part : jamais une échéance
    sans rien à faire."""
    out: list[tuple[Project, str, int, Any]] = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status == c.ARCHIVED:
            continue
        if p.remote:
            out += [(p, what, seq, None) for seq, what in p.requests]
        if p.status == c.ACTIVE and not busy(s, p.id):
            out += [(p, "network", seq, (argv, why)) for seq, argv, why in p.network]
    return out


@PROJECTS.process("projects.remote", wake_on=[REMOTE_REQUESTED, NETWORK_QUEUED, rt.EFFECT_PROPOSED, rt.EPISODE_ENDED,
                                              *c.ALL], lane="background", catch_up=CatchUp.ONCE, max_quantum_s=60,
                  priority=40)
class Remote:
    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        if not waiting(s):
            return None
        # une passe qui n'a rien pu écrire (dédoublonnée) ne repart pas aussitôt : au pire une minute, jamais une boucle
        return frame.now if last_run is None else max(frame.now, last_run + RETRY_US)

    async def run(self, ctx: Any) -> None:
        s: ProjectsState = ctx.state
        port, store = ctx.ports.get("workshop"), ctx.ports.get("store")
        drafts = []
        for p, what, seq, detail in waiting(s):
            if what == "network":
                argv, why_ref = detail
                why = store.content([why_ref]).get(why_ref, "") if store is not None and why_ref else ""
                drafts.append(network_proposal(p, seq, argv, why))
            else:
                drafts.append(await remote_proposal(p, what, seq, port))
        if drafts:
            await ctx.emit(*drafts, emitter=rt.OWNER)
