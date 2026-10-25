"""Qui peut quoi sur un projet et ses apps (ADR 0133) : ses lignes d'accès, lues de haut en bas comme celles d'un
service (ADR 0131, ``vocab.access``), puis sa ligne par défaut.

``line_for`` : la ligne qui décide pour qui est en face, à ce moment — le voir, le piloter ; pour un outil d'une de ses
apps, la première ligne qui le concerne aussi (sa colonne « Outils »). Y changer quelque chose : jamais dans un salon,
avec une inconnue, ni sans personne. Sa fiche (l'onglet « Accès », l'action ``projects.acces``) et la page « Droits » : ``console_access``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import Project, access_of
from mika.kernel.frame import Frame
from mika.vocab.access import OWNER, first, situation, who_words

#: ce que « piloter » permet, en mots courts
STEER_WORDS = {c.STEER_READ: "lecture seule", c.STEER_ASK: "accord du propriétaire", c.STEER_EDIT: "modification",
               c.STEER_NO: "aucun pilotage"}


def lines(p: Project | c.ProjectView) -> tuple[tuple[c.ProjectAccess, ...], c.ProjectAccess]:
    """Ses lignes et sa ligne par défaut, d'un projet ou de sa vue (``projects.LIVE``)."""
    return access_of(p) if isinstance(p, Project) else (p.access, p.default_access)


def line_for(p: Project | c.ProjectView, audience: Any, kind: str, tool: str = "", *,
             close: Callable[[str], bool] | None = None, acting: bool = True) -> c.ProjectAccess | None:
    """La ligne qui décide pour qui est en face, dans cette sorte d'épisode (``close`` : qui est proche d'elle) ;
    ``tool`` : pour un outil d'une de ses apps, la première qui le concerne aussi. ``None`` : jamais ici (personne ;
    pour agir, un salon ou une inconnue non plus)."""
    rows, default = lines(p)
    concerns = (lambda a: not a.tools or tool in a.tools) if tool else None
    return first(rows, default, audience, kind, concerns, close=close, acting=acting)


def sees(p: Project | c.ProjectView, audience: Any, kind: str, close: Callable[[str], bool] | None = None) -> bool:
    """Peut-elle en parler à qui est en face ? Sa confidentialité filtre encore ce qu'elle en dit. Dans un salon ou
    devant une inconnue, seules « tout le monde » et la ligne par défaut le disent : en parler n'est pas agir — rien ne
    s'y pilote ni ne s'y sert de ses apps."""
    line = line_for(p, audience, kind, close=close, acting=False)
    return line is not None and line.see


def reads(p: Project | c.ProjectView, audience: Any, kind: str, close: Callable[[str], bool] | None = None) -> bool:
    """Peut-elle lui en dire le détail (son dernier compte rendu, ce qui vient) ? Le voir, et le piloter au moins en
    lecture seule ; lire n'est pas agir (un salon, une inconnue : comme le voir). Sa confidentialité filtre encore."""
    line = line_for(p, audience, kind, close=close, acting=False)
    return line is not None and line.see and line.steer != c.STEER_NO


def steering(p: Project | c.ProjectView, audience: Any, kind: str, close: Callable[[str], bool] | None = None) -> str:
    """Ce que qui est en face peut faire de ce projet en le pilotant (``STEERS``) — jamais sans le voir, ni y changer
    quoi que ce soit dans un salon ou devant une inconnue. Toi en face, l'accord du propriétaire, c'est le tien : ta
    demande s'applique aussitôt."""
    line = line_for(p, audience, kind, close=close)
    level = line.steer if line is not None and line.see else c.STEER_NO
    return c.STEER_EDIT if level == c.STEER_ASK and situation(audience) == OWNER else level


def who_named(frame: Frame | None, who: str | Sequence[str]) -> str:
    """Qui une ligne désigne, en mots (``vocab.access.who_words``), une personne par son nom."""
    def name(person: str) -> str:
        view = frame.get(identity_c.IDENTITY(person)) if frame is not None and person else None
        return str(getattr(view, "name", "") or person)

    return who_words(who, name)


