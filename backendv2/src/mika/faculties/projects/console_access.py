"""Les accès d'un projet dans la console (ADR 0133) : l'onglet « Accès » de sa fiche (``acces``, dessiné par la
composition), l'action ``projects.acces`` — chaque bouton (ajouter, monter, descendre, retirer, enregistrer) envoie
tout le tableau, journalisé (``access_set``) ; une ligne ajoutée est fermée : enregistrée dès le clic, elle n'ouvre rien
avant d'être réglée — et son type de règles sur la page « Droits »."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.contracts import social as social_c
from mika.faculties.projects.access import STEER_WORDS, reads, steering, who_named
from mika.faculties.projects.faculty import ACCESS_SET, PROJECTS, ProjectsState, access_of, project_at
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.inspect import ActionSlot, Block, Column, InspectContext, Note, Ref, Row, Table
from mika.kernel.operate import ActionContext, Done, Refused
from mika.kernel.rights import Grant, RuleTable, why_words
from mika.vocab.access import (
    MOMENTS,
    NO,
    OWNER,
    POLICIES,
    POLICY_WORDS,
    WORK,
    checked,
    in_order,
    sources,
    verdict,
    when_words,
)

#: au plus tant de lignes (un tableau qu'on lit d'un regard)
MAX_ROWS = 40
#: la ligne qu'on ajoute : toi, toujours, fermée
NEW_ROW = c.ProjectAccess(who=(OWNER,))
#: un outil d'une de ses apps, tel qu'une ligne le nomme (``<app>_<outil>``)
TOOL = re.compile(r"[a-z][a-z0-9_]{0,120}")


# ── L'onglet « Accès » ────────────────────────────────────────────────────


@PROJECTS.inspect("acces", title="Accès", subject="project", order=75,
                  description="Qui peut le voir, le piloter et se servir de ses apps, et quand : des lignes lues de "
                              "haut en bas, puis la ligne par défaut.")
def _tab_access(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = project_at(s, ctx.subject)
    if p is None:
        return [Note("Ce projet n'existe plus.", tone="muted")]
    rows, default = access_of(p)
    shown = [Row((str(i), who_named(frame, a.who), when_words(a.when), "oui" if a.see else "non",
                  STEER_WORDS.get(a.steer, a.steer), POLICY_WORDS.get(a.read, a.read), POLICY_WORDS.get(a.act, a.act),
                  "tous" if not a.tools else ", ".join(a.tools)))
             for i, a in enumerate((*rows, default), start=1)]
    blocks: list[Block] = [
        Table((Column("#", "fit"), "qui", "quand", "voir", "piloter projet", "apps : lecture", "apps : action",
               "outils"),
              tuple(shown), title="Accès",
              caption="De haut en bas : pour qui est en face, la première ligne qui le désigne décide (pour un outil "
                      "de ses apps, celle qui le concerne aussi) ; aucune, c'est la dernière, le comportement par "
                      "défaut. Y changer quelque chose et ses apps : jamais dans un salon ni avec une inconnue ; "
                      "« tout le monde » ne les y laisse que le voir et le lire."),
        ActionSlot("projects.acces", (), title="Enregistrer"),
    ]
    if p.access is None:
        blocks.insert(0, Note("Jamais réglés : toi et elle qui travaille, tout ; les autres l'entendent selon sa "
                              "confidentialité, en lecture seule.", tone="info"))
    return blocks


# ── L'action ──────────────────────────────────────────────────────────────

_Steer = Literal["lecture", "accord", "modification", "non"]
_Policy = Literal["seule", "carte", "toi", "non"]


class AccessArgs(BaseModel):
    """Le tableau « Accès », d'un seul envoi : une ligne par numéro (``<champ>.<numéro>``), ses moments cochés
    (``moments.<numéro>|<moment>``, ou ``toujours.<numéro>``), ses outils cochés (``prend.<numéro>|<outil>``, ou
    ``tous.<numéro>``), la ligne par défaut, et ce qu'un bouton demande en plus d'enregistrer (``faire``)."""

    #: une entrée par ligne envoyée (``ligne.<numéro>``) : leur ordre ; ses sources et ses personnes cochées
    #: (``qui.<numéro>|<source>``, ``qui.<numéro>|personne:<clé>``)
    ligne: Annotated[dict[str, str], Knob(label="Ligne", advanced=False)] = Field(default_factory=dict)
    qui: Annotated[dict[str, bool], Knob(label="Qui", advanced=False)] = Field(default_factory=dict)
    toujours: Annotated[dict[str, bool], Knob(label="Toujours", advanced=False)] = Field(default_factory=dict)
    moments: Annotated[dict[str, bool], Knob(label="Quand", advanced=False)] = Field(default_factory=dict)
    voir: Annotated[dict[str, bool], Knob(label="Le voir", advanced=False)] = Field(default_factory=dict)
    piloter: Annotated[dict[str, _Steer], Knob(label="Piloter projet", choices=c.STEERS, advanced=False)] = \
        Field(default_factory=dict)
    lecture: Annotated[dict[str, _Policy], Knob(label="Apps : un outil qui lit", choices=POLICIES,
                                                advanced=False)] = Field(default_factory=dict)
    action: Annotated[dict[str, _Policy], Knob(label="Apps : un outil qui agit", choices=POLICIES,
                                               advanced=False)] = Field(default_factory=dict)
    tous: Annotated[dict[str, bool], Knob(label="Tous ses outils", advanced=False)] = Field(default_factory=dict)
    prend: Annotated[dict[str, bool], Knob(label="Ses outils", advanced=False)] = Field(default_factory=dict)
    defaut_voir: Annotated[bool, Knob(label="Par défaut, le voir", advanced=False)] = False
    defaut_piloter: Annotated[_Steer, Knob(label="Par défaut, piloter projet", choices=c.STEERS, advanced=False)] = \
        "non"
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
    """Les lignes du tableau envoyé, dans leur ordre ; refuse une ligne sans source lisible, sans moment (sauf au
    travail, qui n'en a pas) ou sans outil."""
    rows = []
    for n, key in enumerate(sorted(args.ligne, key=_number), start=1):
        try:
            who = in_order(sources(checked(args.qui, key)))
        except ValueError:
            raise Refused(f"Ligne {n} : coche qui.") from None
        talks = any(w != WORK for w in who)
        when = () if args.toujours.get(key) or not talks else tuple(m for m in checked(args.moments, key)
                                                                    if m in dict(MOMENTS))
        if talks and not args.toujours.get(key) and not when:
            raise Refused(f"Ligne {n} : coche au moins un moment, ou « toujours ».")
        picked = sorted(checked(args.prend, key))
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


# ── Qui peut quoi, sur la page « Droits » ─────────────────────────────────

#: ce qu'aucune ligne d'un projet n'ouvre
FLOORS = ("y changer quelque chose et se servir de ses apps : jamais dans un salon, avec une inconnue, ni sans "
          "personne", "son cadre (titre, outils, accord) reste à la console",
          "en parler, en dire le détail : sa confidentialité filtre encore")
COLUMNS = ("qui", "quand", "voir", "piloter projet", "apps : lecture", "apps : action", "outils")


def _row(frame: Frame, a: c.ProjectAccess) -> tuple[str, ...]:
    return (who_named(frame, a.who), when_words(a.when), "oui" if a.see else "non", STEER_WORDS.get(a.steer, a.steer),
            POLICY_WORDS.get(a.read, a.read), POLICY_WORDS.get(a.act, a.act),
            "tous" if not a.tools else ", ".join(a.tools))


def _titles(ctx: Any, s: ProjectsState) -> dict[int, str]:
    live = [p for p in s.projects.values() if p.status in (c.ACTIVE, c.PAUSED)]
    texts = ctx.store.content([p.title_ref for p in live if p.title_ref]) if ctx.store is not None else {}
    return {p.id: texts.get(p.title_ref) or f"n° {p.id}" for p in live}


def _project_grants(s: ProjectsState, frame: Frame, ctx: Any, audience: Any, kind: str) -> list[Grant]:
    """Pour chaque projet vivant : le voir (une parole : un salon ou une inconnue y compris), le piloter (une action :
    jamais là), et la ligne qui en décide ; ses apps, la Forge les dit."""
    close, out = social_c.is_close(frame), []
    for pid, title in sorted(_titles(ctx, s).items()):
        p = s.projects[pid]
        seen = verdict(*access_of(p), audience, kind, close=close, acting=False)
        if seen is None:
            continue
        acted = verdict(*access_of(p), audience, kind, close=close)
        # y changer quelque chose : jamais dans un salon ni devant une inconnue ; le lire, comme le voir
        steer = steering(p, audience, kind, close)
        if steer == c.STEER_NO and reads(p, audience, kind, close):
            steer = c.STEER_READ
        why = why_words(seen.index) if acted is None or acted.index == seen.index else \
            f"{why_words(seen.index)} ; piloter : {why_words(acted.index)}"
        out.append(Grant(f"project:{pid}", f"Le projet « {title} »",
                         (("le voir", "oui" if seen.line.see else "non"),
                          ("piloter projet", STEER_WORDS.get(steer, steer))),
                         why, href=Ref.subject("project", str(pid), title, "acces"), closed=not seen.line.see))
    return out


@PROJECTS.rights("projets", title="Projets et leurs apps", order=30, grants=_project_grants,
                 description="Qui peut voir chaque projet, le piloter et se servir de ses apps, et quand (ADR 0133).")
def _project_tables(s: ProjectsState, frame: Frame, ctx: Any) -> list[RuleTable]:
    out = []
    for pid, title in sorted(_titles(ctx, s).items()):
        p = s.projects[pid]
        rows, default = access_of(p)
        out.append(RuleTable(f"project:{pid}", f"Le projet « {title} »", COLUMNS,
                             tuple(_row(frame, a) for a in rows), _row(frame, default),
                             href=Ref.subject("project", str(pid), title, "acces"), floors=FLOORS,
                             note="Jamais réglés : toi et elle qui travaille, tout ; les autres l'entendent selon "
                                  "sa confidentialité, en lecture seule." if p.access is None else ""))
    return out
