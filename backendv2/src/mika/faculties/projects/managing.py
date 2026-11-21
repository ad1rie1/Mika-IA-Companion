"""Gérer un projet depuis l'espace d'une personne (ADR 0290) : les règles qui manquaient, et ce qui en sort.

Trois choses, sans un mot d'écran (ils sont dans ``inspect_manage.py``) :

- **des règles pures** : qui change le cadre d'un projet (``frames``), ce que ce cadre réserve à qui s'occupe d'elle
  (``keeps``, ``beyond`` : ce qui ouvre autre chose que le projet lui-même, ADR 0292), ce qu'une personne qui le
  pilote sans en être le propriétaire ne défait pas d'un jalon (``undoing`` : la règle de l'ADR 0278, dite pour une
  personne) ;
- **une décision révisée** (``projects.decision_revised``) : ses textes changent, son numéro et son statut restent ;
- **ce qu'une personne écrit chez l'hôte sur une pull request** — son titre et son texte, un commentaire. Comme la
  fusion (``merge.py``, ADR 0288) : son action pose un fait, ``projects.pull_write_asked`` ; **après le commit du
  journal**, l'effet de ce fait appelle le port de l'hôte, et ce qu'il répond devient ``projects.pull_write_answered``.
  Aucun outil, aucune capacité qu'une exécution pourrait proposer : elle n'écrit pas ainsi. Un commentaire part du
  compte du jeton : son texte dit qui l'écrit (la règle des notes publiées, ADR 0275). Une écriture interrompue
  n'est jamais rejouée.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import tracker
from mika.faculties.projects.faculty import (
    BASE_BUNDLES,
    INHERITED,
    PROJECTS,
    WEB,
    Milestone,
    Objective,
    Project,
    ProjectsState,
    by_pulls,
    decision_at,
    inherited_for,
    live,
    milestone_held,
    objective_at,
    written_for,
)
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import CAPABILITY_LANE
from mika.kernel.frame import Frame
from mika.ports.workshop import PULL_OPEN
from mika.vocab.phrasebook import phrase

# ── Qui ───────────────────────────────────────────────────────────────────


def frames(frame: Frame, p: Project, person: str) -> bool:
    """Qui change le cadre d'un projet — son titre, son mode, son rythme, ce qui sort, ses outils, son dépôt,
    l'archiver, le restaurer : son propriétaire (la personne pour qui il est fait), ou qui s'occupe d'elle. La règle de
    qui tranche (``tracker.settles``) : piloter un projet ne suffit pas."""
    return tracker.settles(frame, p, person)


# ── Ce que le cadre d'un projet réserve à qui s'occupe d'elle (ADR 0292) ───

#: les lots que le propriétaire d'un projet lui donne lui-même : sa mémoire et le web. Tout autre — le courrier, la
#: caméra, ses flux, la Forge, ses apps, un service branché — ouvre autre chose que le projet : ce que le code réserve
#: à sa propriétaire (ADR 0104, 0133), et qu'un projet n'a en main que s'il a pris le lot
OWN_BUNDLES = ("memory", WEB)


def keeps(frame: Frame, person: str) -> bool:
    """Cette personne s'occupe-t-elle d'elle (l'une de ses propriétaires) ? Être le propriétaire d'un projet n'y
    suffit pas."""
    return bool(person) and bool(frame.get(identity_c.IS_OWNER(person)))


def beyond(bundle: str) -> bool:
    """Ce lot ouvre-t-il autre chose que le projet lui-même ? Seul qui s'occupe d'elle le donne ou le retire : le
    propriétaire d'un projet qui ne s'occupe pas d'elle ne se donne ni son courrier, ni sa caméra, ni ses services."""
    return bundle not in BASE_BUNDLES and bundle not in OWN_BUNDLES


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


# ── Une décision révisée ──────────────────────────────────────────────────

#: les textes facultatifs d'une décision, qu'une révision peut vider
OPTIONAL = ("context", "options", "reason")


class DecisionRevised(Payload):
    """Les textes d'une décision technique changent (``None`` : inchangé ; ``cleared`` : ceux qu'on vide, parmi
    ``OPTIONAL``). Son numéro, son statut et ce qu'elle remplace restent."""

    project: int
    decision: int
    title: Content | None = None
    choice: Content | None = None
    context: Content | None = None
    options: Content | None = None
    reason: Content | None = None
    cleared: tuple[str, ...] = ()
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


DECISION_REVISED = PROJECTS.event("decision_revised", DecisionRevised,
                                  content=("title", "choice", "context", "options", "reason"),
                                  subjects=("owner", "about", "by", INHERITED))


@PROJECTS.reducer(DECISION_REVISED)
def _decision_revised(s: ProjectsState, e, cx) -> ProjectsState:
    """Une décision remplacée ne se révise pas : c'est celle qui la remplace qu'on change."""
    d = e.data
    p = s.projects.get(d.project)
    x = decision_at(p, d.decision) if p is not None else None
    if p is None or x is None or x.status == c.SUPERSEDED:
        return s

    def ref(name: str, old: str) -> str:
        new = getattr(d, name)
        if new is not None and new.ref:
            return new.ref
        return "" if name in d.cleared and name in OPTIONAL else old

    new = replace(x, title_ref=ref("title", x.title_ref), choice_ref=ref("choice", x.choice_ref),
                  context_ref=ref("context", x.context_ref), options_ref=ref("options", x.options_ref),
                  reason_ref=ref("reason", x.reason_ref))
    if new == x:
        return s
    return replace(s, projects=s.projects.set(p.id, replace(
        p, decisions=tuple(new if y.id == x.id else y for y in p.decisions))))


# ── Ce qu'une personne écrit chez l'hôte sur une pull request ─────────────

#: ce qu'elle y écrit : son titre et son texte, ou un commentaire
EDIT, COMMENT = "edit", "comment"
WRITES = (EDIT, COMMENT)
#: pourquoi rien n'est parti (``PullWriteAnswered.why``) : la pull request n'est plus celle de la demande ; aucun hôte
#: ne sait l'écrire sur ce dépôt ; le texte ne se lit plus (il a été oublié) ; l'hôte a refusé, ou n'a pas répondu ;
#: la demande a été interrompue — on ne sait pas si elle a eu lieu, et elle n'est pas rejouée
STALE, NO_HOST, FORGOTTEN, REFUSED, CUT = "stale", "no_host", "forgotten", "refused", "cut"
WHYS = (STALE, NO_HOST, FORGOTTEN, REFUSED, CUT)
#: ce que l'hôte a, au plus, pour répondre (secondes) ; les bornes d'un titre, d'un texte, d'un commentaire
DEADLINE_S = 60.0
TITLE_MAX, BODY_MAX, COMMENT_MAX = 200, 8000, 4000


class PullWriteAsked(Payload):
    """Une personne écrit chez l'hôte sur la pull request d'un objectif (ADR 0290) : le propriétaire du projet, ou
    qui s'occupe d'elle — jamais elle. ``what`` : ``EDIT`` (son titre, son texte : ``None``, inchangé) ou ``COMMENT``
    (``text`` : ses mots, tels qu'elle les a écrits — la signature se compose au départ)."""

    project: int
    objective: int
    number: int
    what: str
    title: Content | None = None
    body: Content | None = None
    text: Content | None = None
    #: qui l'écrit : la clé de sa personne
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class PullWriteAnswered(Payload):
    """Ce que l'hôte a répondu à une écriture demandée : partie (``ok``), ou pourquoi non (``WHYS``). ``asked`` : la
    demande. Aucun texte."""

    project: int
    objective: int
    number: int
    what: str
    asked: int = 0
    ok: bool = False
    why: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


PULL_WRITE_ASKED = PROJECTS.event("pull_write_asked", PullWriteAsked, content=("title", "body", "text"),
                                  subjects=("owner", "about", "by", INHERITED))
PULL_WRITE_ANSWERED = PROJECTS.event("pull_write_answered", PullWriteAnswered, subjects=("owner", "about"))


def writable(p: Project, o: Objective | None) -> bool:
    """La pull request de cet objectif est-elle ouverte chez l'hôte, numéro connu — de quoi y écrire ?"""
    return o is not None and live(p) and by_pulls(p) and bool(o.pull) and o.pull_state == PULL_OPEN


def writing(p: Project, o: Objective, by: str, *, title: str | None = None, body: str | None = None,
            comment: str = "") -> Draft[Any]:
    """Le fait qu'une personne écrit sur cette pull request. Écrit par les actions ``projects.pull_modifier`` et
    ``projects.pull_commenter``, et par elles seules. Ses textes sont du niveau de ce qui s'écrit sur l'objectif, et
    portent ses sujets hérités : l'oubli les atteint."""
    level = written_for(p, o)

    def opt(text: str | None, most: int) -> Content | None:
        return Content.of(text.strip()[:most], level=level) if text is not None and text.strip() else None

    return PULL_WRITE_ASKED.draft(
        project=p.id, objective=o.id, number=o.pull, what=COMMENT if comment.strip() else EDIT,
        title=opt(title, TITLE_MAX), body=opt(body, BODY_MAX), text=opt(comment, COMMENT_MAX), by=by, owner=p.owner,
        about=p.about, read_about=inherited_for(p, o))


def reply_mark(project: int, seq: int) -> str:
    """Le repère que porte un commentaire écrit d'ici : il ne se publie pas deux fois."""
    return f"p{project}-r{seq}"


def signed(frame: Frame | None, by: str, text: str) -> str:
    """Le texte d'un commentaire tel qu'il part : il dit qui l'écrit — chez l'hôte, tout part du compte du jeton. Le
    nom de la personne y figure parce que c'est elle qui publie ses propres mots (ADR 0275) ; sans nom connu, il part
    sans nom."""
    name = (identity_c.person_name(frame, by) or "") if frame is not None and by else ""
    return phrase("projects.issues.text.reply_named", name=name, text=text) if name else \
        phrase("projects.issues.text.reply_bare", text=text)


def _frame(ports: Mapping[str, Any]) -> Frame | None:
    frame_of = ports.get("frame")
    return frame_of() if frame_of is not None else None


def _answer(ev: Any, p: Project | None, *, ok: bool = False, why: str = "") -> list[Any]:
    d = ev.data
    return [PULL_WRITE_ANSWERED.draft(project=d.project, objective=d.objective, number=d.number, what=d.what,
                                      asked=ev.seq, ok=ok, why=why, owner=p.owner if p is not None else None,
                                      about=p.about if p is not None else ())]


def _project(ev: Any, ports: Mapping[str, Any]) -> Project | None:
    frame = _frame(ports)
    return frame.state("projects").projects.get(ev.data.project) if frame is not None else None


def _cut(ev: Any, ports: Mapping[str, Any], why: str = "") -> list[Any]:
    """Une écriture dont on n'a pas la réponse (un arrêt pendant qu'elle partait, son échéance) : elle n'est pas
    rejouée — relire la pull request chez l'hôte dit ce qu'il en est."""
    return _answer(ev, _project(ev, ports), why=CUT)


@PROJECTS.effect(PULL_WRITE_ASKED, lane=CAPABILITY_LANE, deadline_s=DEADLINE_S, on_interrupted=_cut)
async def _write(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Après le commit : ce qu'une personne a écrit part chez l'hôte. La pull request doit être encore celle de la
    demande (son numéro, ouverte) ; un texte oublié depuis ne part pas."""
    d = ev.data
    p = _project(ev, ports)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or not writable(p, o) or o.pull != d.number or d.what not in WRITES:
        return _answer(ev, p, why=STALE)
    host, store = ports.get("repo_host"), ports.get("store")
    if host is None or store is None or not host.handles(p.remote):
        return _answer(ev, p, why=NO_HOST)
    given = [x for x in (d.title, d.body, d.text) if x is not None and x.ref]
    texts = store.content([x.ref for x in given])
    if not given or any(x.ref not in texts for x in given):
        return _answer(ev, p, why=FORGOTTEN)

    def said(x: Content | None) -> str | None:
        return texts[x.ref] if x is not None and x.ref else None

    if d.what == EDIT:
        edit = getattr(host, "edit_pull", None)
        if not callable(edit):
            return _answer(ev, p, why=NO_HOST)
        got = await edit(p.remote, d.number, title=said(d.title), body=said(d.body))
        return _answer(ev, p, ok=not got.error, why=REFUSED if got.error else "")
    got = await host.remark(p.remote, d.number, body=signed(_frame(ports), d.by, said(d.text) or ""),
                            mark=reply_mark(p.id, ev.seq))
    sent = bool(got.id) and not got.error
    return _answer(ev, p, ok=sent, why="" if sent else REFUSED)


__all__ = ["COMMENT", "DECISION_REVISED", "EDIT", "OWN_BUNDLES", "PULL_WRITE_ANSWERED", "PULL_WRITE_ASKED", "WHYS",
           "beyond", "frames", "keeps", "reply_mark", "signed", "undoing", "writable", "writing"]
