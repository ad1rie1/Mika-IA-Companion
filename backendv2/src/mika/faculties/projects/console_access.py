"""Les accès d'un projet dans la console (ADR 0133, 0134) : l'onglet « Accès » de sa fiche (``acces``, dessiné par la
composition), l'action ``projects.acces`` — chaque bouton (ajouter, monter, descendre, retirer, enregistrer) envoie
tout le tableau, journalisé (``access_set``) ; une ligne ajoutée est fermée : enregistrée dès le clic, elle n'ouvre rien
avant d'être réglée — et son type de règles sur la page « Droits »."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field

from mika.contracts import projects as c
from mika.faculties.projects.access import STEER_WORDS, allowance, of_frame, who_named
from mika.faculties.projects.faculty import ACCESS_SET, PROJECTS, ProjectsState, access_of, project_at
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.inspect import ActionSlot, Block, Column, InspectContext, Note, Ref, Row, Table
from mika.kernel.operate import ActionContext, Done, Refused
from mika.kernel.rights import Grant, RuleTable
from mika.vocab.access import (
    NO,
    OWNER,
    POLICIES,
    POLICY_WORDS,
    STEERS,
    TableArgs,
    canal_words,
    moved,
    when_words,
)

#: au plus tant de lignes (un tableau qu'on lit d'un regard)
MAX_ROWS = 40
#: la ligne qu'on ajoute : toi, par tous les canaux, toujours, fermée
NEW_ROW = c.ProjectAccess(who=(OWNER,))
#: un outil d'une de ses apps, tel qu'une ligne le nomme (``<app>_<outil>``)
TOOL = re.compile(r"[a-z][a-z0-9_]{0,120}")
COLUMNS = ("qui", "par où", "quand", "voir", "piloter projet", "fichiers", "apps : lecture", "apps : action", "outils")


# ── L'onglet « Accès » ────────────────────────────────────────────────────


def _row(frame: Frame, a: c.ProjectAccess) -> tuple[str, ...]:
    return (who_named(frame, a.who), canal_words(a.canal), when_words(a.when), "oui" if a.see else "non",
            STEER_WORDS.get(a.steer, a.steer), "oui" if a.files else "non", POLICY_WORDS.get(a.read, a.read),
            POLICY_WORDS.get(a.act, a.act), "tous" if not a.tools else ", ".join(a.tools))


@PROJECTS.inspect("acces", title="Accès", subject="project", order=75,
                  description="Qui peut le voir, le piloter, en recevoir les fichiers et se servir de ses apps, par "
                              "où et quand : des lignes lues de haut en bas, puis la ligne par défaut.")
def _tab_access(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = project_at(s, ctx.subject)
    if p is None:
        return [Note("Ce projet n'existe plus.", tone="muted")]
    rows, default = access_of(p)
    shown = [Row((str(i), *_row(frame, a))) for i, a in enumerate((*rows, default), start=1)]
    blocks: list[Block] = [
        Table((Column("#", "fit"), *COLUMNS), tuple(shown), title="Accès",
              caption="De haut en bas : pour qui est en face, par où, la première ligne qui le désigne décide (pour "
                      "un outil de ses apps, celle qui le concerne aussi) ; aucune, c'est la dernière, le comportement "
                      "par défaut — après le tableau du canal, sous le plafond de qui est en face : y changer quelque "
                      "chose, ses fichiers et ses apps, jamais dans un salon ni avec une inconnue."),
        ActionSlot("projects.acces", (), title="Enregistrer"),
    ]
    if p.access is None:
        blocks.insert(0, Note("Jamais réglés : toi et elle seule, tout ; les autres l'entendent selon sa "
                              "confidentialité, en lecture seule.", tone="info"))
    return blocks


# ── L'action ──────────────────────────────────────────────────────────────

_Steer = Literal["lecture", "accord", "modification", "non"]
_Policy = Literal["seule", "carte", "toi", "non"]


class AccessArgs(TableArgs):
    """Le tableau « Accès » d'un projet, d'un seul envoi (``vocab.access.TableArgs`` : ses lignes, qui, par où, quand,
    ses outils) et ses colonnes : le voir, le piloter, ses fichiers, ce qu'elle fait d'un outil de ses apps qui lit et
    d'un outil qui agit ; la ligne par défaut à part."""

    voir: Annotated[dict[str, bool], Knob(label="Le voir", advanced=False)] = Field(default_factory=dict)
    piloter: Annotated[dict[str, _Steer], Knob(label="Piloter projet", choices=STEERS, advanced=False)] = \
        Field(default_factory=dict)
    fichiers: Annotated[dict[str, bool], Knob(label="Ses fichiers", advanced=False)] = Field(default_factory=dict)
    lecture: Annotated[dict[str, _Policy], Knob(label="Apps : un outil qui lit", choices=POLICIES,
                                                advanced=False)] = Field(default_factory=dict)
    action: Annotated[dict[str, _Policy], Knob(label="Apps : un outil qui agit", choices=POLICIES,
                                               advanced=False)] = Field(default_factory=dict)
    defaut_voir: Annotated[bool, Knob(label="Par défaut, le voir", advanced=False)] = False
    defaut_piloter: Annotated[_Steer, Knob(label="Par défaut, piloter projet", choices=STEERS, advanced=False)] = \
        "non"
    defaut_fichiers: Annotated[bool, Knob(label="Par défaut, ses fichiers", advanced=False)] = False
    defaut_lecture: Annotated[_Policy, Knob(label="Par défaut, un outil qui lit", choices=POLICIES,
                                            advanced=False)] = "non"
    defaut_action: Annotated[_Policy, Knob(label="Par défaut, un outil qui agit", choices=POLICIES,
                                           advanced=False)] = "non"


def access_rows(args: AccessArgs) -> list[c.ProjectAccess]:
    """Les lignes du tableau envoyé, dans leur ordre ; refuse une ligne sans source lisible, sans moment ou sans
    outil (``vocab.access.rows_sent``), ou dont un outil est illisible."""
    try:
        sent = args.rows(tools=True, see=args.voir, steer=args.piloter, files=args.fichiers, read=args.lecture,
                         act=args.action)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    rows = []
    for n, r in enumerate(sent, start=1):
        if any(not TOOL.fullmatch(t) for t in r["tools"]):
            raise Refused(f"Ligne {n} : un outil illisible.")
        rows.append(c.ProjectAccess(who=r["who"], canal=r["canal"], when=r["when"], see=bool(r["see"]),
                                    steer=r["steer"] or c.STEER_NO, files=bool(r["files"]), read=r["read"] or NO,
                                    act=r["act"] or NO, tools=r["tools"]))
    return rows


def _exists(project: int) -> Guard:
    """Le tableau ne vaut que pour un projet qui existe toujours."""
    return Guard("projet inchangé", predicate=lambda view, p=project: view.get(c.STATUS(p)) in c.STATUSES)


@PROJECTS.action("acces", title="Accès au projet", args=AccessArgs, emits=[ACCESS_SET], subject="project", order=15,
                 inline=True, description="Ses lignes d'accès, lues de haut en bas, et la ligne par défaut : qui, "
                                          "par où, quand, le voir, le piloter, ses fichiers, ce qu'elle fait d'un "
                                          "outil de ses apps qui lit et d'un outil qui agit, à quels outils.")
def _access(s: ProjectsState, frame: Frame, args: AccessArgs, ctx: ActionContext) -> Done:
    p = project_at(s, ctx.subject)
    if p is None:
        raise Refused(f"Aucun projet « {ctx.subject} ».")
    try:
        rows, said = moved(access_rows(args), args.faire.strip(), NEW_ROW, MAX_ROWS)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    default = c.ProjectAccess(see=args.defaut_voir, steer=args.defaut_piloter, files=args.defaut_fichiers,
                              read=args.defaut_lecture, act=args.defaut_action)
    return Done(drafts=(ACCESS_SET.draft(project=p.id, rows=tuple(rows), default=default, by=ctx.by),),
                message=said, guard=_exists(p.id))


# ── Qui peut quoi, sur la page « Droits » ─────────────────────────────────

#: ce qu'aucune ligne d'un projet n'ouvre
FLOORS = ("y changer quelque chose, ses fichiers et ses apps : jamais dans un salon, avec une inconnue, ni sans "
          "personne", "son cadre (titre, outils, accord) reste à la console",
          "en parler, en dire le détail : sa confidentialité filtre encore")


def _titles(ctx: Any, s: ProjectsState) -> dict[int, str]:
    live = [p for p in s.projects.values() if p.status in (c.ACTIVE, c.PAUSED)]
    texts = ctx.store.content([p.title_ref for p in live if p.title_ref]) if ctx.store is not None else {}
    return {p.id: texts.get(p.title_ref) or f"n° {p.id}" for p in live}


def _project_grants(s: ProjectsState, frame: Frame, ctx: Any, audience: Any, kind: str) -> list[Grant]:
    """Pour chaque projet vivant : le voir, le piloter, ses fichiers, et les lignes qui en décident (les deux
    portes) ; ses apps, la Forge les dit."""
    rights, close = of_frame(frame)
    out = []
    for pid, title in sorted(_titles(ctx, s).items()):
        got = allowance(s.projects[pid], audience, kind, rights=rights, close=close)
        if got is None:
            continue
        out.append(Grant(f"project:{pid}", f"Le projet « {title} »",
                         (("le voir", "oui" if got.see else "non"),
                          ("piloter projet", STEER_WORDS.get(got.steer, got.steer)),
                          ("ses fichiers", "oui" if got.files else "non")),
                         got.why, href=Ref.subject("project", str(pid), title, "acces"), closed=not got.see))
    return out


@PROJECTS.rights("projets", title="Projets et leurs apps", order=30, grants=_project_grants,
                 description="Qui peut voir chaque projet, le piloter, en recevoir les fichiers et se servir de ses "
                             "apps, par où et quand (ADR 0133, 0134).")
def _project_tables(s: ProjectsState, frame: Frame, ctx: Any) -> list[RuleTable]:
    out = []
    for pid, title in sorted(_titles(ctx, s).items()):
        p = s.projects[pid]
        rows, default = access_of(p)
        out.append(RuleTable(f"project:{pid}", f"Le projet « {title} »", COLUMNS,
                             tuple(_row(frame, a) for a in rows), _row(frame, default),
                             href=Ref.subject("project", str(pid), title, "acces"), floors=FLOORS,
                             note="Jamais réglés : toi et elle seule, tout ; les autres l'entendent selon sa "
                                  "confidentialité, en lecture seule." if p.access is None else ""))
    return out
