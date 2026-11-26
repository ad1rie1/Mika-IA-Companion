"""Les jalons d'un objectif (ADR 0273) : ce qui s'écrit, et ce qu'on en lit.

Un objectif ponctuel dit où il en est par ses jalons — cinq vivants au plus, sans sous-jalons. Leurs formes, leurs
événements et leurs réducteurs sont dans ``faculty.py`` (``Milestone``, ``milestone_stepped``). Ici, sans rien qui
agisse :

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

``tools.py`` (le plan, le compte rendu), ``tracker.py`` (le plan validé d'un ticket), ``prompt.py`` et
``reaching.py`` (ses outils) le lisent ; il ne lit que ``faculty.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    MILESTONE_ADDED,
    MILESTONE_CHANGED,
    ROUTINE_LINE_MAX,
    ROUTINE_LINES,
    Milestone,
    Objective,
    Project,
    awaiting,
    milestone_held,
    milestones_of,
    next_milestone,
)
from mika.kernel.events import Content, Draft
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
#: plus) ; sinon les codes de ``faculty.milestone_held``
SETTLED = "settled"


def undoing(m: Milestone, settles: bool) -> str:
    """Pourquoi cette personne ne modifie ni ne retire ce jalon (``SETTLED``, ou un code ``HELD_…``) ; vide : elle le
    peut. Un jalon atteint ou retiré ne bouge plus, pour personne. Un point d'arrêt, un jalon posé par une personne,
    fixé par un plan validé ou refusé par le propriétaire (``milestone_held``, ADR 0278) ne se défait que par qui
    tranche : le propriétaire du projet, ou qui s'occupe d'elle."""
    if m.status != c.OPEN:
        return SETTLED
    return "" if settles else milestone_held(m)


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
    vérification reste — la règle de ce qu'elle peut défaire (``faculty.milestone_guard``) juge ce qui est porté."""

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
