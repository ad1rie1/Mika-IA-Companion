"""Qui peut quoi sur un projet et ses apps (ADR 0133, 0134) : ses lignes d'accès, lues de haut en bas comme celles
d'un service (``vocab.access``), puis sa ligne par défaut — après le tableau du canal par où ça arrive, sous le
plafond de qui est en face (``vocab.rights.project_allowance``).

``allowance`` : ce qu'il laisse à qui est en face, à ce moment — le voir, le piloter, ses fichiers ; pour un outil
d'une de ses apps, la première ligne qui le concerne aussi (sa colonne « Outils »). Sa fiche (l'onglet « Accès »,
l'action ``projects.acces``) et la page « Droits » : ``console_access``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import Project, access_of
from mika.kernel.frame import Frame
from mika.kernel.rights import Rights
from mika.vocab.access import AT_OWNER, STEER_WORDS, situation, who_words
from mika.vocab.rights import ProjectAllowance, closeness_of, project_allowance, rights_of

__all__ = ["STEER_WORDS", "allowance", "lines", "of_frame", "reads", "sees", "shares_files", "steering", "who_named"]


def lines(p: Project | c.ProjectView) -> tuple[tuple[c.ProjectAccess, ...], c.ProjectAccess]:
    """Ses lignes et sa ligne par défaut, d'un projet ou de sa vue (``projects.LIVE``)."""
    return access_of(p) if isinstance(p, Project) else (p.access, p.default_access)


def allowance(p: Project | c.ProjectView, audience: Any, kind: str, tool: str = "", *,
              rights: Rights | None = None, close: Callable[[str], bool] | None = None) -> ProjectAllowance | None:
    """Ce que ce projet laisse à qui est en face, dans cette sorte d'épisode (``rights`` : les tableaux réglés ;
    ``close`` : qui est proche d'elle) ; ``tool`` : pour un outil d'une de ses apps, la première ligne qui le concerne
    aussi. ``None`` : personne en face, hors du travail."""
    rows, default = lines(p)
    concerns = (lambda a: not a.tools or tool in a.tools) if tool else None
    return project_allowance(rows, default, audience, kind, rights or Rights(), concerns, close=close)


def of_frame(frame: Frame | None) -> tuple[Rights, Callable[[str], bool] | None]:
    """Ce que la règle lit de ce qu'elle vit : ses tableaux et qui est proche d'elle ; rien sans vie à lire."""
    if frame is None:
        return Rights(), None
    return rights_of(frame.env), closeness_of(frame.env, frame)


def sees(p: Project | c.ProjectView, audience: Any, kind: str, frame: Frame | None = None) -> bool:
    """Peut-elle en parler à qui est en face ? Sa confidentialité filtre encore ce qu'elle en dit. Dans un salon ou
    devant une inconnue, seules « tout le monde » et la ligne par défaut le disent : en parler n'est pas agir."""
    rights, close = of_frame(frame)
    got = allowance(p, audience, kind, rights=rights, close=close)
    return got is not None and got.see


def reads(p: Project | c.ProjectView, audience: Any, kind: str, frame: Frame | None = None) -> bool:
    """Peut-elle lui en dire le détail (son dernier compte rendu, ce qui vient) ? Le voir, et le piloter au moins en
    lecture seule. Sa confidentialité filtre encore."""
    rights, close = of_frame(frame)
    got = allowance(p, audience, kind, rights=rights, close=close)
    return got is not None and got.reads


def steering(p: Project | c.ProjectView, audience: Any, kind: str, frame: Frame | None = None) -> str:
    """Ce que qui est en face peut faire de ce projet en le pilotant (``STEERS``) — jamais sans le voir, ni y changer
    quoi que ce soit dans un salon ou devant une inconnue. Toi en face, l'accord du propriétaire, c'est le tien : ta
    demande s'applique aussitôt."""
    rights, close = of_frame(frame)
    got = allowance(p, audience, kind, rights=rights, close=close)
    level = got.steer if got is not None else c.STEER_NO
    return c.STEER_EDIT if level == c.STEER_ASK and situation(audience) == AT_OWNER else level


def shares_files(p: Project | c.ProjectView, audience: Any, kind: str, frame: Frame | None = None) -> bool:
    """Peut-elle lui envoyer les fichiers de ce projet ? Sa colonne « fichiers », jamais dans un salon ni à une
    inconnue."""
    rights, close = of_frame(frame)
    got = allowance(p, audience, kind, rights=rights, close=close)
    return got is not None and got.files


def who_named(frame: Frame | None, who: str | Sequence[str]) -> str:
    """Qui une ligne désigne, en mots (``vocab.access.who_words``), une personne par son nom."""
    def name(person: str) -> str:
        view = frame.get(identity_c.IDENTITY(person)) if frame is not None and person else None
        return str(getattr(view, "name", "") or person)

    return who_words(who, name)
