"""Qui peut quoi sur un projet et ses apps (ADR 0133) : ses lignes d'accès, lues de haut en bas comme celles d'un
service (ADR 0131, ``vocab.access``), puis sa ligne par défaut.

- ``line_for`` : la ligne qui décide pour qui est en face, à ce moment — le voir, le piloter ; pour un outil d'une de
  ses apps, la première ligne qui le concerne aussi (sa colonne « Outils »). Jamais dans un salon, avec une
  inconnue, ni sans personne.
- L'onglet « Accès » de sa fiche (``acces``, dessiné par la composition) et l'action ``projects.acces`` : chaque
  bouton (ajouter, monter, descendre, retirer, enregistrer) envoie tout le tableau, journalisé (``access_set``).
  Une ligne ajoutée est fermée : enregistrée dès le clic, elle n'ouvre rien avant d'être réglée.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    ACCESS_SET,
    PROJECTS,
    Project,
    ProjectsState,
    access_of,
    project_at,
)
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.inspect import ActionSlot, Block, Column, InspectContext, Note, Row, Table
from mika.kernel.operate import ActionContext, Done, Refused
from mika.vocab.access import MOMENTS, NO, POLICIES, WHO_ACCOUNTS, WHO_OWNER, WHO_PERSON, first

#: au plus tant de lignes (un tableau qu'on lit d'un regard)
MAX_ROWS = 40
#: la ligne qu'on ajoute : toi, toujours, fermée
NEW_ROW = c.ProjectAccess(who=WHO_OWNER)
#: un outil d'une de ses apps, tel qu'une ligne le nomme (``<app>_<outil>``)
TOOL = re.compile(r"[a-z][a-z0-9_]{0,120}")
#: ce qu'une ligne fait, en mots courts
STEER_WORDS = {c.STEER_ALONE: "seule", c.STEER_ASK: "ton accord", c.STEER_NO: "non"}
POLICY_WORDS = {"seule": "seule", "carte": "demande à la personne", "toi": "ton accord", NO: "non"}
WHEN_WORDS = dict(MOMENTS)


def lines(p: Project | c.ProjectView) -> tuple[tuple[c.ProjectAccess, ...], c.ProjectAccess]:
    """Ses lignes et sa ligne par défaut, d'un projet ou de sa vue (``projects.LIVE``)."""
    return access_of(p) if isinstance(p, Project) else (p.access, p.default_access)


def line_for(p: Project | c.ProjectView, audience: Any, kind: str, tool: str = "") -> c.ProjectAccess | None:
    """La ligne qui décide pour qui est en face, dans cette sorte d'épisode ; ``tool`` : pour un outil d'une de ses
    apps, la première qui le concerne aussi. ``None`` : jamais ici (un salon, une inconnue, personne)."""
    rows, default = lines(p)
    concerns = (lambda a: not a.tools or tool in a.tools) if tool else None
    return first(rows, default, audience, kind, concerns)


def sees(p: Project | c.ProjectView, audience: Any, kind: str) -> bool:
    """Peut-elle en parler à qui est en face ? (Sa confidentialité filtre encore ce qu'elle en dit.)"""
    line = line_for(p, audience, kind)
    return line is not None and line.see


def steering(p: Project | c.ProjectView, audience: Any, kind: str) -> str:
    """Ce que qui est en face peut faire de ce projet en le pilotant : ``seule``, ``toi`` (ton accord) ou ``non`` —
    jamais sans le voir."""
    line = line_for(p, audience, kind)
    return line.steer if line is not None and line.see else c.STEER_NO


def who_words(frame: Frame | None, who: str) -> str:
    """Qui une ligne désigne, en mots : toi, les comptes, une personne par son nom ; la ligne par défaut."""
    if not who:
        return "Comportement par défaut"
    if who == WHO_OWNER:
        return "Toi"
    if who == WHO_ACCOUNTS:
        return "Les comptes"
    person = who[len(WHO_PERSON):] if who.startswith(WHO_PERSON) else who
    view = frame.get(identity_c.IDENTITY(person)) if frame is not None and person else None
    return str(getattr(view, "name", "") or person)


def when_words(when: Sequence[str]) -> str:
    if not when:
        return "toujours"
    words = [WHEN_WORDS.get(w, w) for w in when]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " ou " + words[-1]


# ── L'onglet « Accès » ────────────────────────────────────────────────────


@PROJECTS.inspect("acces", title="Accès", subject="project", order=75,
                  description="Qui peut le voir, le piloter et se servir de ses apps, et quand : des lignes lues de "
                              "haut en bas, puis la ligne par défaut.")
def _tab_access(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = project_at(s, ctx.subject)
    if p is None:
        return [Note("Ce projet n'existe plus.", tone="muted")]
    rows, default = access_of(p)
    shown = [Row((str(i), who_words(frame, a.who), when_words(a.when), "oui" if a.see else "non",
                  STEER_WORDS.get(a.steer, a.steer), POLICY_WORDS.get(a.read, a.read), POLICY_WORDS.get(a.act, a.act),
                  "tous" if not a.tools else ", ".join(a.tools)))
             for i, a in enumerate((*rows, default), start=1)]
    blocks: list[Block] = [
        Table((Column("#", "fit"), "qui", "quand", "voir", "piloter", "apps : lecture", "apps : action", "outils"),
              tuple(shown), title="Accès",
              caption="De haut en bas : pour qui est en face, la première ligne qui le désigne décide (pour un outil "
                      "de ses apps, celle qui le concerne aussi) ; aucune, c'est la dernière, le comportement par "
                      "défaut. Jamais dans un salon ni avec une inconnue."),
        ActionSlot("projects.acces", (), title="Enregistrer"),
    ]
    if p.access is None:
        blocks.insert(0, Note("Jamais réglés : ses accès font ce qu'il faisait avant (toi, tout ; les autres "
                              "l'entendent selon sa confidentialité, sans plus).", tone="info"))
    return blocks


# ── L'action ──────────────────────────────────────────────────────────────

_Steer = Literal["seule", "toi", "non"]
_Policy = Literal["seule", "carte", "toi", "non"]


class AccessArgs(BaseModel):
    """Le tableau « Accès », d'un seul envoi : une ligne par numéro (``<champ>.<numéro>``), ses moments cochés
    (``moments.<numéro>|<moment>``, ou ``toujours.<numéro>``), ses outils cochés (``prend.<numéro>|<outil>``, ou
    ``tous.<numéro>``), la ligne par défaut, et ce qu'un bouton demande en plus d'enregistrer (``faire``)."""

    qui: Annotated[dict[str, str], Knob(label="Qui", advanced=False)] = Field(default_factory=dict)
    toujours: Annotated[dict[str, bool], Knob(label="Toujours", advanced=False)] = Field(default_factory=dict)
    moments: Annotated[dict[str, bool], Knob(label="Quand", advanced=False)] = Field(default_factory=dict)
    voir: Annotated[dict[str, bool], Knob(label="Le voir", advanced=False)] = Field(default_factory=dict)
    piloter: Annotated[dict[str, _Steer], Knob(label="Le piloter", choices=c.STEERS, advanced=False)] = \
        Field(default_factory=dict)
    lecture: Annotated[dict[str, _Policy], Knob(label="Apps : un outil qui lit", choices=POLICIES,
                                                advanced=False)] = Field(default_factory=dict)
    action: Annotated[dict[str, _Policy], Knob(label="Apps : un outil qui agit", choices=POLICIES,
                                               advanced=False)] = Field(default_factory=dict)
    tous: Annotated[dict[str, bool], Knob(label="Tous ses outils", advanced=False)] = Field(default_factory=dict)
    prend: Annotated[dict[str, bool], Knob(label="Ses outils", advanced=False)] = Field(default_factory=dict)
    defaut_voir: Annotated[bool, Knob(label="Par défaut, le voir", advanced=False)] = False
    defaut_piloter: Annotated[_Steer, Knob(label="Par défaut, le piloter", choices=c.STEERS, advanced=False)] = "non"
    defaut_lecture: Annotated[_Policy, Knob(label="Par défaut, un outil qui lit", choices=POLICIES,
                                            advanced=False)] = "non"
    defaut_action: Annotated[_Policy, Knob(label="Par défaut, un outil qui agit", choices=POLICIES,
                                           advanced=False)] = "non"
    #: la valeur du bouton pressé (un champ ordinaire : un champ caché ne se lit que dans les valeurs fixées)
    faire: Annotated[str, Knob(label="Et", help="ajouter, monter:n, descendre:n ou retirer:n ; vide : enregistrer")] = \
        Field("", max_length=40)


def _number(key: str) -> int:
    return int(key) if key.isdigit() else 10**6


def access_rows(args: AccessArgs) -> list[c.ProjectAccess]:
    """Les lignes du tableau envoyé, dans leur ordre ; refuse une ligne sans « qui » lisible, sans moment ou sans
    outil."""
    rows = []
    for n, key in enumerate(sorted(args.qui, key=_number), start=1):
        who = args.qui[key].strip()
        named = who[len(WHO_PERSON):] if who.startswith(WHO_PERSON) else ""
        if not (who in (WHO_OWNER, WHO_ACCOUNTS) or (named and not any(ch.isspace() for ch in named))):
            raise Refused(f"Ligne {n} : choisis qui.")
        when = () if args.toujours.get(key) else tuple(m for m, _ in MOMENTS if args.moments.get(f"{key}|{m}"))
        if not args.toujours.get(key) and not when:
            raise Refused(f"Ligne {n} : coche au moins un moment, ou « toujours ».")
        picked = sorted(t for k, on in args.prend.items() if on and k.partition("|")[0] == key
                        for t in (k.partition("|")[2],))
        if any(not TOOL.fullmatch(t) for t in picked):
            raise Refused(f"Ligne {n} : un outil illisible.")
        if not args.tous.get(key) and not picked:
            raise Refused(f"Ligne {n} : coche au moins un outil, ou « tous ».")
        if len(when) == len(MOMENTS):
            when = ()
        rows.append(c.ProjectAccess(who=who, when=when, see=bool(args.voir.get(key)),
                                    steer=args.piloter.get(key, c.STEER_NO), read=args.lecture.get(key, NO),
                                    act=args.action.get(key, NO), tools=() if args.tous.get(key) else tuple(picked)))
    return rows


def moved(rows: list[c.ProjectAccess], faire: str) -> tuple[list[c.ProjectAccess], str]:
    """Ce qu'un bouton du tableau demande : ajouter une ligne (fermée, au-dessus de la ligne par défaut), monter,
    descendre ou retirer la ligne ``n`` ; et ce qu'on en dit."""
    op, _, at = faire.partition(":")
    i = int(at) - 1 if at.isdigit() else -1
    rows = list(rows)
    if op == "ajouter":
        if len(rows) >= MAX_ROWS:
            raise Refused(f"{MAX_ROWS} lignes au plus.")
        rows.append(NEW_ROW)
        return rows, f"Ligne {len(rows)} ajoutée, fermée : règle-la, puis enregistre."
    if op == "monter" and 0 < i < len(rows):
        rows[i - 1], rows[i] = rows[i], rows[i - 1]
        return rows, f"Ligne {i + 1} montée."
    if op == "descendre" and 0 <= i < len(rows) - 1:
        rows[i], rows[i + 1] = rows[i + 1], rows[i]
        return rows, f"Ligne {i + 1} descendue."
    if op == "retirer" and 0 <= i < len(rows):
        del rows[i]
        return rows, f"Ligne {i + 1} retirée."
    return rows, "Accès enregistrés."


def _exists(project: int) -> Guard:
    """Le tableau ne vaut que pour un projet qui existe toujours."""
    return Guard("projet inchangé", predicate=lambda view, p=project: view.get(c.STATUS(p)) in c.STATUSES)


@PROJECTS.action("acces", title="Accès au projet", args=AccessArgs, emits=[ACCESS_SET], subject="project", order=15,
                 inline=True, description="Ses lignes d'accès, lues de haut en bas, et la ligne par défaut : qui, "
                                          "quand, le voir, le piloter, ce qu'elle fait d'un outil de ses apps qui lit "
                                          "et d'un outil qui agit, à quels outils.")
def _access(s: ProjectsState, frame: Frame, args: AccessArgs, ctx: ActionContext) -> Done:
    p = project_at(s, ctx.subject)
    if p is None:
        raise Refused(f"Aucun projet « {ctx.subject} ».")
    rows, said = moved(access_rows(args), args.faire.strip())
    default = c.ProjectAccess(see=args.defaut_voir, steer=args.defaut_piloter, read=args.defaut_lecture,
                              act=args.defaut_action)
    return Done(drafts=(ACCESS_SET.draft(project=p.id, rows=tuple(rows), default=default, by=ctx.by),),
                message=said, guard=_exists(p.id))
