"""Fusionner une pull request depuis la console ou l'espace d'une personne (ADR 0288) : l'action
``projects.fusionner``, et ce qu'elle dit. Des textes de console et d'écran, lus par qui décide — pas des phrases
qu'elle lit. La règle, le fait et l'effet qui part chez l'hôte sont dans ``merge.py``.

**Qui** : le propriétaire du projet, ou qui s'occupe d'elle (``tracker.settles``) — un opérateur qui n'est ni l'un ni
l'autre ne fusionne pas. **Quoi** : la pull request ouverte d'un objectif, au commit que la personne a vu
(``head``) ; si sa branche a bougé depuis, dans l'atelier ou chez l'hôte, la fusion se refuse.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, Field

from mika.faculties.projects import merge, tracker
from mika.faculties.projects.actions import can_edit
from mika.faculties.projects.faculty import MERGE_ASKED, MERGE_CUT, MERGE_STALE, PROJECTS, ProjectsState
from mika.faculties.projects.inspect_common import (
    LIVE,
    operator_person,
    target_objective,
    target_project,
    unchanged,
)
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import ActionContext, Done, Refused
from mika.ports.workshop import (
    CHECKS_STATES,
    MERGE_BLOCKED,
    MERGE_DENIED,
    MERGE_MOVED,
    MERGE_UNKNOWN,
    MERGE_UNREACHED,
    PULL_OPEN,
)

#: l'action, telle que la console et l'API la nomment
ACTION = "projects.fusionner"
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
#: pourquoi une pull request ne peut pas être fusionnée maintenant (``merge.blocked``)
BLOCK_WORDS = {
    merge.NO_PULL: "Cet objectif n'a pas de pull request ouverte chez l'hôte.",
    merge.PROPOSED: "Sa pull request n'est pas encore ouverte : sa proposition attend un accord.",
    merge.MERGED: "Elle est déjà fusionnée.",
    merge.CLOSED: "Elle est fermée sans fusion.",
    merge.UNREAD: "L'hôte ne l'a pas encore dite : elle se relit dans un instant.",
    merge.ASKED: "Sa fusion est déjà demandée : la pull request se relit chez l'hôte dans un instant.",
    merge.CONFLICTS: "L'hôte la dit en conflit avec la base : elle doit d'abord ramener la base dans sa branche.",
    merge.CHANGES: "Une relecture y demande des changements.",
    merge.RUNNING: "Ses vérifications tournent encore sur son dernier commit.",
    merge.FAILED: "Ses vérifications ont échoué.",
    merge.UNSENT: "Sa branche porte un commit qui n'est pas encore parti chez l'hôte.",
    merge.UNCHECKED: "Son dernier commit vient de partir : l'hôte n'a pas encore dit ses vérifications. Elles se "
                     "relisent dans un instant.",
}
#: pourquoi la dernière fusion demandée n'a pas eu lieu (``Objective.merge_refused``)
REFUSED_WORDS = {
    MERGE_MOVED: "La fusion demandée n'a pas eu lieu : sa branche avait bougé chez l'hôte. Relis-la, puis recommence.",
    MERGE_BLOCKED: "La fusion demandée n'a pas eu lieu : l'hôte la dit impossible à fusionner (un conflit, une règle "
                   "de la branche, ou elle n'est plus ouverte).",
    MERGE_DENIED: "La fusion demandée n'a pas eu lieu : l'hôte refuse le jeton, ou il n'a pas ce droit sur ce dépôt.",
    MERGE_UNREACHED: "La fusion demandée n'a pas eu lieu : l'hôte n'a pas été joint, rien n'est parti.",
    MERGE_UNKNOWN: "On ne sait pas si la fusion demandée a eu lieu : la réponse de l'hôte s'est perdue. La pull "
                   "request se relit chez lui dans un instant.",
    MERGE_STALE: "La fusion demandée n'a pas eu lieu : la pull request avait changé entre-temps.",
    MERGE_CUT: "La fusion demandée a été interrompue : la relecture de l'hôte dira si elle a eu lieu.",
}
NOT_YOURS = "Seul le propriétaire du projet, ou qui s'occupe d'elle, fusionne une pull request : elle, jamais."
HEAD_NEEDED = "Nomme le commit que tu as lu : « head », l'identifiant complet du commit au bout de sa branche."
MOVED_HERE = ("Sa branche a bougé depuis ce que tu as lu (elle est au commit {sha}) : relis la pull request, puis "
              "fusionne.")
MOVED_THERE = ("Chez l'hôte, sa branche n'est pas au commit que tu as lu (elle y est au commit {sha}) : relis la "
               "pull request, puis fusionne.")
NO_WORKSHOP = "L'atelier de ce projet ne se lit pas pour l'instant : rien n'est parti."
NO_HOST = "Aucun hôte ne sait fusionner une pull request sur ce dépôt."
HOST_SILENT = "L'hôte ne dit pas où en est cette pull request ({why}) : rien n'est parti."
NOT_OPEN_THERE = "Chez l'hôte, cette pull request n'est plus ouverte : elle se relit dans un instant."
WRONG_BASE = ("Chez l'hôte, cette pull request entre dans « {there} », pas dans la branche du projet (« {here} ») : "
              "rien n'est parti. Recible-la chez l'hôte, ou règle la branche du projet.")
CHECKS_SILENT = "L'hôte ne dit pas où en sont les vérifications de ce commit ({why}) : rien n'est parti."
ASKED = "Fusion demandée chez l'hôte, à ton nom : la pull request se relit dans un instant."
CONFIRM = ("Fusionner cette pull request dans la branche de base du dépôt distant ? C'est ton geste, chez l'hôte : "
           "il ne se défait pas d'ici.")


class MergeArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    head: Annotated[str, Knob(label="Le commit lu", widget="hidden")] = Field(default="", max_length=40)


def writer(frame: Frame, ctx: ActionContext) -> str:
    """La personne qui agit : celle de son compte, comme pour trancher un ticket."""
    return operator_person(frame, ctx) or ctx.by


@PROJECTS.action("fusionner", title="Fusionner la pull request", args=MergeArgs, emits=[MERGE_ASKED],
                 subject="project", order=66, available=can_edit, inline=True, danger=True, confirm=CONFIRM,
                 description="Fusionner chez l'hôte la pull request d'un objectif, au commit que tu as lu. Ton geste, "
                             "à toi seul : elle ne fusionne jamais.")
async def _fuse(s: ProjectsState, frame: Frame, args: MergeArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    o = target_objective(p, args.objective)
    person = writer(frame, ctx)
    if not tracker.settles(frame, p, person):
        raise Refused(NOT_YOURS)
    if why := merge.blocked(p, o, ctx.now):
        raise Refused(BLOCK_WORDS[why])
    if not _FULL_SHA.match(args.head):
        raise Refused(HEAD_NEEDED, {"head": "valeur requise"})
    # l'atelier d'abord : le commit au bout de sa branche est-il encore celui qu'elle a lu ?
    port, host = (ctx.ports or {}).get("workshop"), (ctx.ports or {}).get("repo_host")
    span = await port.span(p.id, o.branch) if port is not None and port.exists(p.id) else None
    if span is None:
        raise Refused(NO_WORKSHOP)
    if span.head != args.head:
        raise Refused(MOVED_HERE.format(sha=span.head[:12]))
    # puis l'hôte, relu maintenant : la pull request y est-elle ouverte, à ce commit, et fusionnable ?
    if host is None or not host.handles(p.remote):
        raise Refused(NO_HOST)
    seen = await host.pull(p.remote, o.branch)
    if seen.error:
        raise Refused(HOST_SILENT.format(why=seen.error[:200]))
    if seen.number != o.pull or seen.state != PULL_OPEN:
        raise Refused(NOT_OPEN_THERE)
    if seen.sha and seen.sha != args.head:
        raise Refused(MOVED_THERE.format(sha=seen.sha[:12]))
    if seen.mergeable is False:
        raise Refused(BLOCK_WORDS[merge.CONFLICTS])
    # la base où elle entre chez l'hôte est-elle celle du projet (ADR 0292) ? Reciblée là-bas, ou la branche du
    # projet changée depuis : l'écran annonçait une base, la fusion entrerait dans une autre
    if seen.base and seen.base != p.branch:
        raise Refused(WRONG_BASE.format(there=seen.base[:100], here=p.branch))
    # les vérifications du commit de tête, relues maintenant : le journal ne les relit qu'à son rythme, et juste
    # après un envoi l'hôte ne les a pas encore créées (« aucune »)
    read = getattr(host, "checks", None)
    if callable(read):
        got = await read(p.remote, args.head)
        if got.error or got.state not in CHECKS_STATES:
            raise Refused(CHECKS_SILENT.format(why=(got.error or "réponse illisible")[:200]))
        if held := merge.checks_block(o, got.state, seen.at, ctx.now):
            raise Refused(BLOCK_WORDS[held])
    return Done(drafts=(merge.asking(p, o, args.head, person),), message=ASKED,
                guard=unchanged(p.id, LIVE) & merge.alone(p.id, o.id))
