"""Les jalons d'un objectif (ADR 0273) : leurs faits, ce qui s'écrit, et ce qu'on en lit.

Un objectif ponctuel dit où il en est par ses jalons — cinq vivants au plus, sans sous-jalons. Leur forme
(``Milestone``) et les lectures que tous en font (``milestone_at``, ``milestones_of``, ``awaiting``…) sont dans
``faculty.py``. Ici, sans rien qui agisse :

- **leurs faits** (ADR 0313) : ``projects.milestone_added`` et ``projects.milestone_changed``, leurs charges utiles
  et leurs réducteurs — un jalon atteint ou retiré ne bouge plus, et la seule règle de ce qu'un changement en fait
  est ``milestone_stepped`` ;
- **ce qu'elle n'en défait pas en exécution** (``milestone_guard``, ADR 0278 ; ``milestone_held`` dit ce qui tient
  un jalon hors de sa seule main) : la règle pure que le réducteur applique et que l'outil lit pour refuser ;
- **ce qu'on demande** (``Spec``) et ce qui lui manque (``problem``) : un jalon se vérifie par une commande que
  l'outil lancera dans l'atelier, par un point d'arrêt que le propriétaire tranche, par un élément du registre dans
  un statut donné, ou par ce qu'elle en dit ;
- **ce qu'une personne n'en défait pas** (``undoing``, la règle de l'ADR 0278 dite pour une personne) : un jalon
  atteint ou retiré ne bouge plus ; un jalon tenu ne se défait que par qui tranche — les actions ``jalon_modifier``
  et ``jalon_retirer`` (``inspect_milestones.py``) et l'API par personne la lisent ;
- **les seuls endroits qui en font un brouillon** (``adding``, ``changing``) : chacun porte le niveau et les sujets
  qu'on lui donne — ceux de l'objectif, donc du ticket dont il est né (ADR 0272), et ceux que le projet a hérités de
  ses lectures (``read_about``, ADR 0262) ;
- **ce qu'une exécution en lit** (``lines``) : ses jalons, leur état, la preuve des atteints en une ligne, celui
  qui vient — borné ; pour un constant, sa liste de passage (``routine_lines``) ;
- **ce qu'une relecture ou une pull request en cite** (``cited``) : chaque jalon avec comment il a été rempli, sa
  preuve et le commit de l'atelier — une fonction pure des textes qu'on lui donne (``refs`` dit lesquels lire).

``framing_tools.py`` (le plan), ``tools.py`` (le compte rendu), ``tracker.py`` (le plan validé d'un ticket),
``prompt.py`` et ``reaching.py`` (ses outils) le lisent ; il ne lit que ``faculty.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    INHERITED,
    PROJECTS,
    ROUTINE_LINE_MAX,
    ROUTINE_LINES,
    Milestone,
    Objective,
    Project,
    ProjectsState,
    awaiting,
    milestone_at,
    milestones_of,
    next_milestone,
    objective_at,
    with_objective,
    with_project,
)
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.text import clipped
from mika.vocab.phrasebook import family, phrase

#: ce qu'on garde d'un jalon : son texte, comment elle dit l'avoir rempli, la raison d'une révision, sa preuve
TEXT_MAX, HOW_MAX, REASON_MAX, PROOF_MAX = 300, 600, 400, 600
#: sa commande : ses arguments, au plus, et chacun
ARGV_MAX, ARG_MAX = 40, 400
#: ce qu'une exécution en lit, par jalon : son texte, sa preuve (ou comment), la raison d'un refus
TEXT_SHOWN, PROOF_SHOWN, REASON_SHOWN = 200, 160, 200
#: ce qu'une relecture en cite : comment, et sa preuve
HOW_CITED, PROOF_CITED = 400, 600


@dataclass(frozen=True, slots=True)
class Spec:
    """Un jalon tel qu'on le demande : son texte, et comment il se vérifiera."""

    text: str
    check: str = c.CHECK_PROSE
    argv: tuple[str, ...] = ()
    item_list: str = ""
    item_key: str = ""
    item_status: str = ""


def problem(spec: Spec) -> str:
    """Ce qui manque à un jalon demandé — un code de ``projects.milestones.refused`` —, ou ``""``. Seule sa forme
    se juge ici : l'élément qu'il nomme n'existe peut-être pas encore ; il se relira quand elle dira le jalon
    atteint."""
    if not spec.text.strip():
        return "no_text"
    if spec.check not in c.CHECKS:
        return "bad_check"
    if spec.check == c.CHECK_COMMAND and not any(a.strip() for a in spec.argv):
        return "no_command"
    if spec.check == c.CHECK_ITEM and not (spec.item_list.strip() and spec.item_key.strip()
                                           and spec.item_status.strip()):
        return "no_item"
    return ""


def encoded(argv: Iterable[str]) -> str:
    """Une commande telle qu'elle se garde : ses arguments, exacts, en une liste JSON."""
    return json.dumps([a[:ARG_MAX] for a in argv][:ARGV_MAX], ensure_ascii=False)


def decoded(text: str | None) -> tuple[str, ...]:
    """Les arguments d'une commande gardée ; ``()`` : elle ne se lit plus (oubliée, ou pas une liste)."""
    try:
        got = json.loads(text or "")
    except ValueError:
        return ()
    return tuple(got) if isinstance(got, list) and got and all(isinstance(a, str) for a in got) else ()


def refining(o: Objective) -> bool:
    """Sa première exécution : elle a ouvert le code, elle affine les jalons que le plan a posés grossièrement —
    sans avoir à dire pourquoi. Ensuite une révision garde sa raison. La première depuis sa naissance
    (``Objective.worked``, ADR 0280), pas depuis qu'il s'est rouvert : ``runs`` repart alors de zéro, et un objectif
    que l'hôte renvoie — ses jalons déjà atteints — n'en est pas à sa première exécution."""
    return o.worked <= 1


def begun(o: Objective | None) -> frozenset[int]:
    """Les jalons auxquels elle s'est mise (ADR 0293), par leur numéro : ceux qu'elle a atteints, et le premier
    encore ouvert dès qu'une de ses exécutions est partie depuis que le jalon d'avant est atteint — ce que le
    diagramme déduit de ses exécutions, dit ici sans relire le journal. Les suivants attendent celui-là."""
    out: set[int] = set()
    bound = 0
    for m in milestones_of(o):
        if m.status == c.REACHED:
            out.add(m.id)
            bound = max(bound, m.reached_at)
            continue
        if o is not None and o.last_run_at and o.last_run_at >= bound:
            out.add(m.id)
        break
    return frozenset(out)


def routine_text(rows: Iterable[str]) -> str:
    """La liste de passage d'un constant telle qu'elle se garde : une ligne par chose, ``ROUTINE_LINES`` au plus."""
    kept = [" ".join(x.split())[:ROUTINE_LINE_MAX] for x in rows if x.strip()]
    return "\n".join(kept[:ROUTINE_LINES])


#: pourquoi une personne ne défait pas un jalon (``undoing``) : il n'est plus ouvert (atteint ou retiré, il ne bouge
#: plus) ; sinon les codes de ``milestone_held``
SETTLED = "settled"


def undoing(m: Milestone, settles: bool) -> str:
    """Pourquoi cette personne ne modifie ni ne retire ce jalon (``SETTLED``, ou un code ``HELD_…``) ; vide : elle le
    peut. Un jalon atteint ou retiré ne bouge plus, pour personne. Un point d'arrêt, un jalon posé par une personne,
    fixé par un plan validé ou refusé par le propriétaire (``milestone_held``, ADR 0278) ne se défait que par qui
    tranche : le propriétaire du projet, ou qui s'occupe d'elle."""
    if m.status != c.OPEN:
        return SETTLED
    return "" if settles else milestone_held(m)


# ── Ses faits et leurs réducteurs (ADR 0313) ──────────────────────────────

#: les jalons qu'un objectif garde en tout, retirés compris (les vivants : ``c.MILESTONES_MAX``) : au-delà, le plus
#: ancien retiré tombe — l'état reste borné
MILESTONES_KEPT = 12


class MilestoneAdded(Payload):
    """Un jalon posé sur un objectif ponctuel (ADR 0273) : par son plan, par l'exécution qui l'affine, par le plan
    validé d'un ticket, ou par le propriétaire dans la console."""

    project: int
    objective: int
    milestone: int
    text: Content
    #: comment il se vérifie (``c.CHECKS``) ; une commande : ses arguments (un contenu : une liste JSON) ; un élément
    #: du registre : sa liste, sa clé (ou le numéro d'un ticket), le statut attendu
    check: str = c.CHECK_PROSE
    command: Content | None = None
    item_list: str = ""
    item_key: str = ""
    item_status: str = ""
    #: ``operator`` | ``owner`` | ``self``
    author: str = "self"
    by: str = ""
    #: posé par un plan qu'une personne vient de valider (le plan d'un ticket, ADR 0278) : il est à cette personne
    agreed: bool = False
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class MilestoneChanged(Payload):
    """Ce qui arrive à un jalon (ADR 0273) : révisé (son texte, sa vérification — ``None`` : inchangés), dit prêt
    (un point d'arrêt : il attend le propriétaire), refusé par lui, atteint, retiré. ``how`` : comment elle dit l'avoir
    rempli ; ``proof`` : sa preuve, un fait arrivé et borné (le résumé de ce que sa commande a rendu, le statut de
    son élément à ce moment-là) — jamais un état recalculé ; ``reason`` : la raison d'une révision, d'un retrait,
    d'un refus, ou le mot de qui le valide ; ``commit`` : le commit de l'atelier à ce moment-là."""

    project: int
    objective: int
    milestone: int
    text: Content | None = None
    check: str | None = None
    command: Content | None = None
    item_list: str | None = None
    item_key: str | None = None
    item_status: str | None = None
    #: ``c.REACHED`` ou ``c.DROPPED`` (``None`` : inchangé) — un jalon atteint ne se défait pas
    status: str | None = None
    ready: bool = False
    refused: bool = False
    how: Content | None = None
    proof: Content | None = None
    reason: Content | None = None
    commit: str = ""
    #: qui l'écrit : ``self`` (elle, pendant une exécution), ``owner`` (une personne en conversation : ``by``),
    #: ``operator`` (la console)
    author: str = "self"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


MILESTONE_ADDED = PROJECTS.event("milestone_added", MilestoneAdded, content=("text", "command"),
                                 subjects=("owner", "about", "by", INHERITED))
MILESTONE_CHANGED = PROJECTS.event("milestone_changed", MilestoneChanged,
                                   content=("text", "command", "how", "proof", "reason"),
                                   subjects=("owner", "about", "by", INHERITED))


@PROJECTS.reducer(MILESTONE_ADDED)
def _milestone_added(s: ProjectsState, e, cx) -> ProjectsState:
    """Un jalon de plus sur un objectif ponctuel encore vivant (ADR 0273), ``c.MILESTONES_MAX`` vivants au plus :
    au-delà, ignoré. Ses tout premiers jalons — il n'en a jamais eu — font repartir de zéro le compte des exécutions
    sans jalon atteint ; aucune autre pose (ADR 0278) : retirer ses jalons ouverts puis en poser d'autres ne remet
    pas ce compte à zéro."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or o.kind != c.ONCE or o.status not in (c.OPEN, c.BLOCKED) or not d.text.ref:
        return s
    alive = milestones_of(o)
    if len(alive) >= c.MILESTONES_MAX:
        return s
    # deux ajouts du même numéro : le second prend le suivant ; un numéro déjà donné ne revient jamais
    number = d.milestone if d.milestone > o.milestone_seq else o.milestone_seq + 1
    check = d.check if d.check in c.CHECKS else c.CHECK_PROSE
    on_item = check == c.CHECK_ITEM
    m = Milestone(id=number, text_ref=d.text.ref, check=check,
                  command_ref=d.command.ref or "" if d.command is not None and check == c.CHECK_COMMAND else "",
                  item_list=d.item_list if on_item else "", item_key=d.item_key if on_item else "",
                  item_status=d.item_status if on_item else "", author=d.author, at=e.at, agreed=d.agreed)
    kept = (*o.milestones, m)
    while len(kept) > MILESTONES_KEPT:  # les retirés restent lisibles tant qu'il y a la place : le plus ancien tombe
        oldest = next(x for x in kept if x.status == c.DROPPED)
        kept = tuple(x for x in kept if x is not oldest)
    first = o.milestone_seq == 0  # jamais aucun jalon : la toute première pose
    return with_project(s, with_objective(p, replace(o, milestones=kept, milestone_seq=number, stale=0 if first else o.stale)))


#: pourquoi, en exécution, un jalon n'est pas à elle seule (ADR 0278 ; les clés de
#: ``projects.tools.milestones.held``) : le propriétaire l'a refusé, c'est un point d'arrêt, un autre qu'elle l'a
#: posé, le plan qui l'a posé a été validé par une personne
HELD_REFUSED, HELD_BREAKPOINT, HELD_OTHER, HELD_AGREED = "refused", "breakpoint", "other", "agreed"


def milestone_held(m: Milestone) -> str:
    """Ce qui tient ce jalon hors de sa seule main en exécution (ADR 0278), ou ``""`` : il est à elle."""
    if m.refused_at:
        return HELD_REFUSED
    if m.check == c.CHECK_OWNER:
        return HELD_BREAKPOINT
    if m.author != "self":
        return HELD_OTHER
    return HELD_AGREED if m.agreed else ""


def milestone_guard(m: Milestone, d: MilestoneChanged) -> str:
    """Pourquoi ce geste ne vaut pas quand c'est elle qui l'écrit, en exécution (ADR 0278) — un code ``HELD_…`` —,
    ou ``""``. Pure : la règle que le réducteur applique (``milestone_stepped``) et que l'outil lit pour refuser
    en disant pourquoi.

    - Elle ne **retire** pas un jalon tenu (``milestone_held``) : posé par un autre, fixé par un plan qu'une
      personne a validé, point d'arrêt, ou refusé par le propriétaire.
    - Elle n'en **change pas la vérification** (sa sorte, sa commande, son élément) — sauf pour en donner une à un
      jalon à elle, fixé par un plan validé, qui n'avait que sa parole : affiner n'est pas affaiblir.
    - Elle n'en **réécrit le texte** que s'il est d'elle, et que personne ne l'a validé.

    Dire un jalon atteint, ou un point d'arrêt prêt, n'est pas le défaire : ce n'est pas jugé ici. Ce que font le
    propriétaire et l'opérateur non plus."""
    if d.author != "self" or d.status == c.REACHED or d.ready or d.refused:
        return ""
    why = milestone_held(m)
    if d.status == c.DROPPED:
        return why
    rechecks = any(x is not None for x in (d.check, d.command, d.item_list, d.item_key, d.item_status))
    firms = why == HELD_AGREED and m.check == c.CHECK_PROSE and d.check in c.CHECKS and d.check != c.CHECK_PROSE
    if rechecks and why and not firms:
        return why
    if d.text is not None and (m.author != "self" or m.agreed):
        return HELD_AGREED if m.author == "self" else HELD_OTHER
    return ""


def milestone_stepped(m: Milestone, d: MilestoneChanged, at: int) -> tuple[Milestone, bool] | None:
    """Ce qu'un changement fait d'un jalon encore ouvert, et s'il fait avancer l'objectif (ADR 0273) ; ``None`` :
    rien. Pure : la seule règle, que lisent le réducteur et ce qui veut savoir d'avance si un geste vaudra.

    - **retiré**, avec sa raison ; **atteint** — un point d'arrêt ne l'est que par un autre qu'elle, et seulement
      quand elle l'a dit prêt ;
    - **refusé** par le propriétaire : il est de nouveau à elle, la raison gardée ;
    - **dit prêt** (un point d'arrêt seulement) : il attend le propriétaire — une avancée ;
    - sinon **révisé** : son texte, sa vérification, sa raison gardée.

    Tant qu'il attend le propriétaire, elle n'y touche plus ; et en exécution elle ne défait pas un jalon qui
    n'est pas à elle seule (``milestone_guard``, ADR 0278)."""
    hers = d.author == "self"
    reason = d.reason.ref or "" if d.reason is not None else ""
    how = d.how.ref or "" if d.how is not None else ""
    if milestone_guard(m, d):
        return None
    if d.status == c.DROPPED:
        if m.ready_at and hers:
            return None
        return replace(m, status=c.DROPPED, ready_at=0, reason_ref=reason or m.reason_ref), False
    if d.status == c.REACHED:
        if m.check == c.CHECK_OWNER and (hers or not m.ready_at):
            return None
        return replace(m, status=c.REACHED, reached_at=at, reached_by=d.by or d.author, ready_at=0,
                       how_ref=how or m.how_ref, proof_ref=d.proof.ref or "" if d.proof is not None else "",
                       commit=d.commit or m.commit, reason_ref=reason or m.reason_ref), True
    if d.refused:
        if hers or not m.ready_at:
            return None
        return replace(m, ready_at=0, refused_at=at, reason_ref=reason or m.reason_ref), False
    if d.ready:
        if m.check != c.CHECK_OWNER or m.ready_at:
            return None
        return replace(m, ready_at=at, refused_at=0, how_ref=how or m.how_ref, commit=d.commit or m.commit), True
    if m.ready_at and hers:
        return None
    check = d.check if d.check in c.CHECKS else m.check
    on_item = check == c.CHECK_ITEM
    new = replace(
        m, text_ref=d.text.ref if d.text is not None and d.text.ref else m.text_ref, check=check,
        command_ref=(d.command.ref if d.command is not None and d.command.ref else m.command_ref)
        if check == c.CHECK_COMMAND else "",
        item_list=(m.item_list if d.item_list is None else d.item_list) if on_item else "",
        item_key=(m.item_key if d.item_key is None else d.item_key) if on_item else "",
        item_status=(m.item_status if d.item_status is None else d.item_status) if on_item else "")
    if new == m:
        return None
    return replace(new, ready_at=0, revised=m.revised + 1, reason_ref=reason or m.reason_ref), False


@PROJECTS.reducer(MILESTONE_CHANGED)
def _milestone_changed(s: ProjectsState, e, cx) -> ProjectsState:
    """Un jalon atteint ou retiré ne bouge plus : il ne se défait ni ne se révise. Un jalon atteint, ou un point
    d'arrêt dit prêt, remet à zéro le compte des exécutions sans jalon atteint."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    m = milestone_at(o, d.milestone) if o is not None else None
    if p is None or o is None or m is None or m.status != c.OPEN:
        return s
    got = milestone_stepped(m, d, e.at)
    if got is None:
        return s
    new, progressed = got
    return with_project(s, with_objective(p, replace(o, milestones=tuple(new if x.id == m.id else x for x in o.milestones),
                                         stale=0 if progressed else o.stale)))


# ── Écrire : les seuls endroits qui font un brouillon ─────────────────────


def _who(p: Project, inherited: Iterable[str]) -> dict[str, Any]:
    return {"owner": p.owner, "about": p.about, "read_about": tuple(inherited)}


def adding(p: Project, objective: int, number: int, spec: Spec, *, level: int, inherited: Iterable[str],
           author: str = "self", by: str = "", agreed: bool = False) -> Draft[Any]:
    """Le brouillon d'un jalon posé sur l'objectif ``objective`` — qui naît peut-être dans le même lot (un plan, le
    plan validé d'un ticket). ``level`` et ``inherited`` : le niveau et les sujets hérités de ce qui s'écrit sur cet
    objectif. ``agreed`` : le plan qui le pose vient d'être validé par une personne — il est à elle (ADR 0278)."""
    on_item = spec.check == c.CHECK_ITEM
    command = Content.of(encoded(spec.argv), level=level) if spec.check == c.CHECK_COMMAND else None
    return MILESTONE_ADDED.draft(
        project=p.id, objective=objective, milestone=number,
        text=Content.of(clipped(" ".join(spec.text.split()), TEXT_MAX), level=level), check=spec.check,
        command=command, item_list=spec.item_list.strip() if on_item else "",
        item_key=spec.item_key.strip() if on_item else "", item_status=spec.item_status.strip() if on_item else "",
        author=author, by=by, agreed=agreed, **_who(p, inherited))


def posed(p: Project, objective: int, specs: Iterable[Spec], *, level: int, inherited: Iterable[str],
          author: str = "self", by: str = "", after: int = 0, agreed: bool = False) -> list[Draft[Any]]:
    """Les jalons d'un objectif, posés d'un coup dans leur ordre (``c.MILESTONES_MAX`` au plus), numérotés à la suite
    de ``after`` (le dernier numéro que l'objectif a donné)."""
    return [adding(p, objective, after + i, spec, level=level, inherited=inherited, author=author, by=by,
                   agreed=agreed)
            for i, spec in enumerate(list(specs)[:c.MILESTONES_MAX], start=1)]


def changing(p: Project, objective: int, m: Milestone, *, level: int, inherited: Iterable[str], author: str = "self",
             by: str = "", spec: Spec | None = None, status: str | None = None, ready: bool = False,
             refused: bool = False, how: str = "", proof: str = "", reason: str = "", commit: str = "",
             same_text: bool = False, same_check: bool = False) -> Draft[Any]:
    """Le brouillon de ce qui arrive à un jalon : révisé (``spec`` : ce qu'il devient), dit prêt, refusé, atteint,
    retiré — avec comment, sa preuve, sa raison et le commit de l'atelier. La preuve est un fait arrivé, borné.
    Une révision ne porte que ce qu'elle change (ADR 0278) : ``same_text``, son texte reste ; ``same_check``, sa
    vérification reste — la règle de ce qu'elle peut défaire (``milestone_guard``) juge ce qui est porté."""

    def opt(text: str, most: int) -> Content | None:
        return Content.of(clipped(text.strip(), most), level=level) if text.strip() else None

    revised: dict[str, Any] = {}
    if spec is not None:
        on_item = spec.check == c.CHECK_ITEM
        if not same_text:
            revised["text"] = opt(" ".join(spec.text.split()), TEXT_MAX)
        if not same_check:
            revised.update({
                "check": spec.check,
                "command": Content.of(encoded(spec.argv), level=level) if spec.check == c.CHECK_COMMAND else None,
                "item_list": spec.item_list.strip() if on_item else "",
                "item_key": spec.item_key.strip() if on_item else "",
                "item_status": spec.item_status.strip() if on_item else ""})
    return MILESTONE_CHANGED.draft(
        project=p.id, objective=objective, milestone=m.id, status=status, ready=ready, refused=refused,
        how=opt(how, HOW_MAX), proof=opt(proof, PROOF_MAX), reason=opt(reason, REASON_MAX), commit=commit,
        author=author, by=by, **revised, **_who(p, inherited))


# ── Lire ──────────────────────────────────────────────────────────────────


def refs(o: Objective | None) -> list[str]:
    """Les textes à lire pour dire les jalons d'un objectif (``lines``, ``cited``) et sa liste de passage."""
    if o is None:
        return []
    found = [r for m in o.milestones for r in (m.text_ref, m.command_ref, m.how_ref, m.proof_ref, m.reason_ref)]
    return [r for r in (*found, o.routine_ref) if r]


def check_words(m: Milestone, texts: Mapping[str, str], who: str = "") -> str:
    """Comment un jalon se vérifie, en mots."""
    if m.check == c.CHECK_COMMAND:
        argv = decoded(texts.get(m.command_ref))
        return phrase("projects.milestones.check.command", command=clipped(" ".join(argv), TEXT_SHOWN)) if argv \
            else phrase("projects.milestones.check.command_forgotten")
    if m.check == c.CHECK_ITEM:
        return phrase("projects.milestones.check.item", key=m.item_key, name=m.item_list, status=m.item_status)
    if m.check == c.CHECK_OWNER:
        return phrase("projects.milestones.check.owner", who=who or phrase("projects.milestones.someone"))
    return phrase("projects.milestones.check.prose")


def _text(m: Milestone, texts: Mapping[str, str], most: int = TEXT_SHOWN) -> str:
    return clipped(texts.get(m.text_ref) or phrase("projects.milestones.forgotten"), most)


def _flat(text: str, most: int) -> str:
    """Un texte en une ligne, coupé : une preuve, une raison — des données qu'on cite."""
    return clipped(" ".join((text or "").split()), most)


def line(m: Milestone, texts: Mapping[str, str], who: str = "", *, coming: bool = False) -> str:
    """Un jalon tel que le lit l'exécution qui vise son objectif : son état, son texte, comment il se vérifie, puis
    — atteint — sa preuve en une ligne (sinon comment elle a dit l'avoir rempli) ; refusé, la raison."""
    if m.status == c.OPEN and m.ready_at:
        state = phrase("projects.milestones.waiting", who=who or phrase("projects.milestones.someone"))
    elif coming:
        state = phrase("projects.milestones.coming")
    else:
        state = family("projects.milestones.states").get(m.status, m.status)
    more = ""
    if m.status == c.REACHED:
        proof = _flat(texts.get(m.proof_ref, ""), PROOF_SHOWN) or _flat(texts.get(m.how_ref, ""), PROOF_SHOWN)
        more = phrase("projects.milestones.proof", proof=proof) if proof else ""
    elif m.status == c.OPEN and m.refused_at and texts.get(m.reason_ref):
        more = phrase("projects.milestones.refused_why", reason=_flat(texts[m.reason_ref], REASON_SHOWN))
    return phrase("projects.milestones.line", id=m.id, state=state, text=_text(m, texts),
                  check=check_words(m, texts, who), more=more)


def lines(o: Objective, texts: Mapping[str, str], who: str = "") -> list[str]:
    """Ce que l'exécution qui vise un objectif ponctuel lit de ses jalons : chacun en une ligne, lequel vient, et —
    à sa première exécution — qu'elle peut les affiner. Sans jalon : qu'elle peut en poser. Cinq lignes au plus,
    chacune coupée."""
    alive = milestones_of(o)
    if o.kind != c.ONCE:
        return []
    if not alive:
        return [phrase("projects.milestones.none")] if refining(o) else []
    coming = next_milestone(o)
    out = [phrase("projects.milestones.head") + "\n" + "\n".join(
        "- " + line(m, texts, who, coming=coming is not None and m.id == coming.id) for m in alive)]
    held = awaiting(o)
    if held is not None:
        out.append(phrase("projects.milestones.held", id=held.id, who=who or phrase("projects.milestones.someone")))
    elif refining(o):
        out.append(phrase("projects.milestones.refine"))
    return out


def routine_lines(o: Objective, texts: Mapping[str, str]) -> list[str]:
    """Ce que chaque passage d'un constant doit faire, tel qu'il le lit (rien : il n'a pas de liste)."""
    rows = [x for x in (texts.get(o.routine_ref) or "").split("\n") if x.strip()] if o.kind == c.CONSTANT else []
    if not rows:
        return []
    return [phrase("projects.milestones.routine") + "\n" + "\n".join(f"- {x}" for x in rows[:ROUTINE_LINES])]


def cited_for_review(o: Objective | None, texts: Mapping[str, str]) -> tuple[list[str], list[str]]:
    """Les jalons d'un objectif pour la relecture indépendante (ADR 0277), en deux listes : ce qui est établi, et ce
    que l'exécution qui a travaillé en a écrit.

    - **Établi** (cité dans une section fiable) : le numéro du jalon, son état, comment il se vérifie ; atteint par
      une commande ou par un élément du registre, la preuve gardée — un fait arrivé, que l'outil a constaté
      lui-même — et le commit. Son texte n'y est que s'il vient du propriétaire ou de l'opérateur et n'a jamais été
      révisé.
    - **Son dire** (cité dans une section non fiable) : le texte d'un jalon qu'elle a posé, ou qu'elle a pu
      réécrire, et comment elle dit avoir rempli ceux qu'elle a dits atteints. Citer ces mots-là comme fiables en
      faisait un compte rendu par jalon, et un canal de l'exécution relue vers celle qui la juge.

    Pure : ``texts`` porte les textes de ``refs(o)``."""
    established, said = [], []
    states = family("projects.milestones.states")
    for m in milestones_of(o):
        hers = m.author == "self" or m.revised > 0
        more = ""
        if m.status == c.REACHED:
            verified = m.check in (c.CHECK_COMMAND, c.CHECK_ITEM)
            proof = _flat(texts.get(m.proof_ref, ""), PROOF_CITED) if verified else ""
            more = (phrase("projects.milestones.cited.proof", proof=proof) if proof else "") + \
                (phrase("projects.milestones.cited.commit", sha=m.commit[:12]) if m.commit else "")
        state, check = states.get(m.status, m.status), check_words(m, texts)
        established.append(
            phrase("projects.milestones.review.bare", id=m.id, state=state, check=check, more=more) if hers else
            phrase("projects.milestones.cited.line", id=m.id, text=_text(m, texts, TEXT_MAX), state=state,
                   check=check, more=more))
        how = _flat(texts.get(m.how_ref, ""), HOW_CITED) if m.status == c.REACHED else ""
        if hers or how:
            said.append(phrase("projects.milestones.review.said", id=m.id) + (
                phrase("projects.milestones.review.text", text=_text(m, texts, TEXT_MAX)) if hers else "") + (
                phrase("projects.milestones.review.how", how=how) if how else ""))
    return established, said


def cited(o: Objective | None, texts: Mapping[str, str]) -> list[str]:
    """Les jalons d'un objectif avec leur preuve, prêts à être cités à qui suit le projet (l'aperçu et le corps
    d'une pull request) : un jalon par ligne, dans leur ordre, sans les retirés — son texte, comment il se vérifie,
    son état ; atteint, comment elle a dit l'avoir rempli, sa preuve et le commit de l'atelier. Une relecture ne
    lit pas ceci (``cited_for_review``, ADR 0277). Pure : ``texts`` porte les textes de ``refs(o)`` ; un texte
    oublié se dit oublié."""
    out = []
    for m in milestones_of(o):
        state = family("projects.milestones.states").get(m.status, m.status)
        more = ""
        if m.status == c.REACHED:
            how, proof = _flat(texts.get(m.how_ref, ""), HOW_CITED), _flat(texts.get(m.proof_ref, ""), PROOF_CITED)
            more = (phrase("projects.milestones.cited.how", how=how) if how else "") + \
                (phrase("projects.milestones.cited.proof", proof=proof) if proof else "") + \
                (phrase("projects.milestones.cited.commit", sha=m.commit[:12]) if m.commit else "")
        out.append(phrase("projects.milestones.cited.line", id=m.id, text=_text(m, texts, TEXT_MAX), state=state,
                          check=check_words(m, texts), more=more))
    return out
