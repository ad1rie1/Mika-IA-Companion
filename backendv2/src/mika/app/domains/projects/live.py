"""La part des projets dans le direct (ADR 0308, 0310) : ce que le journal y change, et qui le voit.

Un projet va à qui le voit par ce canal (``PROJECT``) : ses projets, ceux que les règles de ses routes lui ouvrent
(``api.projects.reaches``) ; une règle qui juge elle-même (``judge``). Ce qui change qui voit un projet (ses accès, ce
qu'il lit des autres, son propriétaire, son sujet ou son niveau, archivé ou rendu) part sans clé, à toutes. Un accord
d'un projet se reconnaît par le contexte de l'événement (``effect``) ; le départ et la fin d'une de ses exécutions,
par la cible de l'épisode (``episodes``).
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import LivePart
from mika.app.domains.projects.api import projects as projects_me
from mika.app.me.touches import EVERYONE, Touch
from mika.contracts import projects as projects_c
from mika.faculties.projects import links
from mika.faculties.projects.faculty import ACCESS_SET, AMENDED, ARCHIVED, LINKS_SET, RESTORED
from mika.ports.changes import ME, PROJECTS
from mika.vocab.episodes import project_of

#: à qui va une touche d'un projet : à qui le voit par ce canal (``api.projects.reaches`` : ``judge``)
PROJECT = "project"
#: ce qui, dans un projet, change qui le voit (ses accès, ce qu'il lit des autres, son propriétaire, son sujet ou son
#: niveau, archivé ou rendu) : le filtre lit l'état d'après — celle qui le perd doit le savoir aussi
PROJECT_REACH = frozenset(t.name for t in (ACCESS_SET, LINKS_SET, AMENDED, ARCHIVED, RESTORED))


def _projects(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    if e.type.name in PROJECT_REACH:  # qui le voit a peut-être changé : à toutes, sans clé
        return [Touch(PROJECTS, EVERYONE), Touch(ME, EVERYONE)]
    pid = e.seq if e.type.name == projects_c.PROJECT_CREATED.name else getattr(e.data, "project", None)
    return _project(pid)


def _project(pid: Any) -> list[Touch]:
    keys = (str(pid),) if isinstance(pid, int) and pid > 0 else ()
    return [Touch(PROJECTS, PROJECT, keys=keys), Touch(ME, PROJECT, owners=keys)]


def judge(reader: Any, t: Touch) -> tuple[bool, tuple[str, ...]]:
    """Ses projets, ceux qu'elle voit par ce canal (``api.projects.reaches``), lus une fois par personne et par envoi.
    Une touche qui nomme des projets lui dit ceux qu'elle voit ; qui nomme des propriétaires (des projets aussi), la
    concerne si elle en voit un ; qui ne nomme rien, si elle en voit un."""

    def read() -> frozenset[str]:
        frame = reader.call.frame
        sc = projects_me.Scene(reader.call, frame, frame.state(projects_c.OWNER), links.world_of(frame),
                               projects_me.audience_at(frame, reader.call.me, reader.channel), reader.call.me.person)
        return frozenset(str(pid) for pid in projects_me.reaches(sc))

    seen = reader.once(PROJECT, read, frozenset())
    if t.keys:
        kept = tuple(k for k in t.keys if k in seen)
        return bool(kept), kept
    return (bool(seen & set(t.owners)) if t.owners else bool(seen)), ()


def effect(proposal: int, frame: Any, kernel: Any, event: Any) -> list[Touch] | None:
    """Un effet du moteur est-il un accord d'un projet ? Il se reconnaît par le contexte de l'événement (son
    projet) : ses touches, ou ``None``."""
    pid = project_of(getattr(event.data, "context", "") or "")
    return _project(pid) if pid else None


def episodes(kind: str, target: str | None, frame: Any, kernel: Any) -> list[Touch]:
    """Le départ, la fin d'un épisode : celui d'une exécution d'un projet (sa cible) dit son projet."""
    pid = project_of(target)
    return [Touch(PROJECTS, PROJECT, keys=(str(pid),))] if pid else []


LIVE = LivePart(
    events={projects_c.OWNER: _projects},
    # ce que change le réglage des projets (``kernel.params_changed``) : qui voit quoi, ce qui se règle — à toutes
    params={projects_c.OWNER: (PROJECTS, ME)},
    judge={PROJECT: judge},
    effects=effect,
    episodes=episodes,
)
