"""Ce qu'une personne fait d'une pull request chez l'hôte : la fusionner (ADR 0288), la modifier, y répondre
(ADR 0290) — son geste, et de personne d'autre. Les actions et leurs mots sont dans ``inspect_merge.py``.

**La fusionner.** « Elle ne fusionne jamais » (ADR 0274) reste vrai : aucun outil, aucune capacité qu'une exécution
pourrait proposer, aucun processus n'a de quoi fusionner. Il y a **une** porte :

- une personne — le propriétaire du projet, ou qui s'occupe d'elle (``tracker.settles``) — fait l'action
  ``projects.fusionner`` (``inspect_merge.py`` : dans la console, ou par l'API de sa personne). L'action pose un
  fait, ``projects.merge_asked`` : qui, quelle pull request, et le commit au bout de sa branche tel qu'elle l'a vu ;
- **après le commit du journal**, l'effet de ce fait (ici) demande la fusion à l'hôte par le port
  (``RepoHost.merge_pull``), pour ce commit-là : si la branche a bougé, l'hôte refuse. Ce qu'il répond devient un
  fait, ``projects.merge_answered``. Une demande interrompue n'est jamais rejouée : on ne sait pas si elle a eu lieu ;
- la fusion elle-même **s'apprend comme toute fusion** : le processus ``projects.pulls``, que la réponse réveille,
  relit la pull request chez l'hôte et pose ``projects.pull_seen``. La réponse ne clôt rien elle-même.

``blocked`` dit, de l'état seul, pourquoi une pull request ne peut pas être fusionnée maintenant : la règle que
l'action applique, et que l'écran lit d'avance.

Ce que la relecture adverse a fixé (ADR 0292) : **la fusion relit la CI** — juste après un envoi, l'hôte n'a pas
encore créé les vérifications du commit, qui se lisent « aucune » : tant que la pull request est fraîche
(``CHECKS_GRACE_US``), « aucune » ne laisse pas fusionner (``UNCHECKED``), et l'action relit chez l'hôte les
vérifications du commit de tête ; **une seule demande à la fois** (le fait ``projects.merging``, que garde l'action) ;
une réponse perdue se dit « on ne sait pas » (``MERGE_UNKNOWN``), jamais « n'a pas eu lieu ».

**La modifier, y répondre** (ADR 0290) — son titre et son texte, un commentaire. Comme la fusion : son action
(``projects.pull_modifier``, ``projects.pull_commenter``) pose un fait, ``projects.pull_write_asked`` (``writing``) ;
**après le commit du journal**, l'effet de ce fait appelle le port de l'hôte, et ce qu'il répond devient
``projects.pull_write_answered``. Aucun outil, aucune capacité qu'une exécution pourrait proposer : elle n'écrit pas
ainsi. ``writable`` dit, de l'état seul, si la pull request est ouverte chez l'hôte, numéro connu. Un commentaire part
du compte du jeton : son texte dit qui l'écrit (``signed``, la règle des notes publiées, ADR 0275). Une écriture
interrompue n'est jamais rejouée.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    INHERITED,
    MERGE_ANSWERED,
    MERGE_ASKED,
    MERGE_CUT,
    MERGE_STALE,
    PROJECTS,
    Objective,
    Project,
    ProjectsState,
    by_pulls,
    inherited_for,
    live,
    objective_at,
    written_for,
)
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import CAPABILITY_LANE
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_NONE,
    CHECKS_PENDING,
    MERGE_UNKNOWN,
    MERGE_UNREACHED,
    MERGE_WHYS,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
)
from mika.vocab.phrasebook import phrase

#: pourquoi une pull request ne peut pas être fusionnée maintenant (``blocked``) : cet objectif n'en a pas ; sa
#: proposition attend encore un accord ; elle est déjà fusionnée ; elle est fermée ; l'hôte ne l'a pas encore dite ;
#: une fusion est déjà demandée ; sa branche est en conflit avec la base ; une relecture de l'hôte demande des
#: changements ; ses vérifications tournent, ou ont échoué ; sa branche porte un commit que l'hôte n'a pas
NO_PULL, PROPOSED, MERGED, CLOSED, UNREAD = "no_pull", "proposed", "merged", "closed", "unread"
ASKED, CONFLICTS, CHANGES, RUNNING, FAILED, UNSENT = "asked", "conflicts", "changes", "running", "failed", "unsent"
#: son dernier envoi est tout frais et l'hôte ne dit encore aucune vérification pour son commit (ADR 0292)
UNCHECKED = "unchecked"
BLOCKS = (NO_PULL, PROPOSED, MERGED, CLOSED, UNREAD, ASKED, CONFLICTS, CHANGES, RUNNING, FAILED, UNSENT, UNCHECKED)
#: ce que l'hôte a, au plus, pour répondre (secondes) : à une fusion demandée, à une écriture
DEADLINE_S = 60.0
#: une pull request fraîche (ADR 0292) : le temps laissé à l'hôte, après ce qu'il en a dit de neuf (un envoi, son
#: ouverture), pour créer les vérifications de son commit. D'ici là, « aucune vérification » ne veut pas dire « rien
#: à vérifier » : la fusion attend, et l'hôte se relit à l'écart court. Passé ce délai, un dépôt sans CI fusionne
CHECKS_GRACE_US = 3 * MINUTE


def unchecked(o: Objective, now: int) -> bool:
    """Ses vérifications se lisent-elles « aucune » (ou pas encore) alors que la pull request est fraîche ? ``now`` à
    0 : on ne juge pas l'instant."""
    return bool(now) and o.checks in ("", CHECKS_NONE) and now - o.pull_at < CHECKS_GRACE_US


def blocked(p: Project, o: Objective, now: int = 0) -> str:
    """Pourquoi la pull request de cet objectif ne peut pas être fusionnée maintenant (``BLOCKS``) ; vide : elle le
    peut. De l'état seul : ce que le journal sait de l'hôte — l'action relit ensuite l'atelier et l'hôte. ``now`` :
    l'instant, pour juger une pull request fraîche (``UNCHECKED``)."""
    if not live(p) or not by_pulls(p):
        return NO_PULL
    if o.pull_state == PULL_MERGED:
        return MERGED
    if o.pull_state == PULL_CLOSED:
        return CLOSED
    if o.pull_state != PULL_OPEN:
        return PROPOSED if o.pull_proposal else NO_PULL
    if not o.pull or not o.pull_at:
        return UNREAD
    if merging(o):
        return ASKED
    if o.pull_conflicts:
        return CONFLICTS
    if o.pull_changes:
        return CHANGES
    if o.checks in (CHECKS_PENDING, CHECKS_FAILED):
        return RUNNING if o.checks == CHECKS_PENDING else FAILED
    if o.unsent:
        return UNSENT
    return UNCHECKED if unchecked(o, now) else ""


def checks_block(o: Objective, state: str, seen_at: int, now: int) -> str:
    """Ce que les vérifications du commit de tête, relues chez l'hôte (``state``), retiennent de la fusion ; vide :
    rien. La règle même de l'action, qui les relit au moment de fusionner — et que la fiche de la console applique à
    sa propre lecture de l'hôte (ADR 0297), pour ne pas offrir un geste que l'action refuserait."""
    if state in (CHECKS_PENDING, CHECKS_FAILED):
        return RUNNING if state == CHECKS_PENDING else FAILED
    if state == CHECKS_NONE and now - max(o.pull_at, seen_at) < CHECKS_GRACE_US:
        return UNCHECKED
    return ""


def merging(o: Objective) -> bool:
    """Une fusion demandée est-elle en route — l'hôte n'a pas encore répondu, ou il l'a faite et la pull request n'a
    pas encore été relue chez lui ?"""
    return bool(o.merge_asked_at) or (o.merge_answered_at > o.pull_at and not o.merge_refused)


def unsure(o: Objective) -> bool:
    """Ne sait-on pas si la fusion demandée a eu lieu (une réponse perdue, une demande interrompue) tant que l'hôte
    n'a pas été relu depuis ? Il se relit aussitôt (``projects.pulls``)."""
    return o.merge_refused in (MERGE_UNKNOWN, MERGE_CUT) and o.merge_answered_at > o.pull_at


@PROJECTS.fact(c.MERGING)
def _merging(s: ProjectsState, cx, key: tuple) -> bool:
    p = s.projects.get(key[0]) if len(key) == 2 else None
    o = objective_at(p, key[1]) if p is not None else None
    return o is not None and merging(o)


def alone(project: int, objective: int) -> Guard:
    """Une seule demande de fusion à la fois par pull request (ADR 0292) : jugée au commit du journal, sur la tête —
    de deux demandes parties ensemble, la seconde ne s'écrit pas."""
    return Guard("aucune fusion en route", predicate=lambda view, k=(project, objective): not view.get(c.MERGING(k)))


def asking(p: Project, o: Objective, sha: str, by: str) -> Draft[Any]:
    """Le fait qu'une personne demande la fusion : ce qu'elle a vu, et qui elle est. Écrit par l'action
    ``projects.fusionner``, et par elle seule."""
    return MERGE_ASKED.draft(project=p.id, objective=o.id, number=o.pull, branch=o.branch, sha=sha, by=by,
                             owner=p.owner, about=p.about)


def _answer(d: Any, p: Project | None, *, merged: bool = False, commit: str = "", why: str = "") -> list[Any]:
    return [MERGE_ANSWERED.draft(project=d.project, objective=d.objective, number=d.number, merged=merged,
                                 commit=commit, why=why, owner=p.owner if p is not None else None,
                                 about=p.about if p is not None else ())]


def _project(ev: Any, ports: Mapping[str, Any]) -> Project | None:
    frame_of = ports.get("frame")
    return frame_of().state("projects").projects.get(ev.data.project) if frame_of is not None else None


def _cut(ev: Any, ports: Mapping[str, Any], why: str = "") -> list[Any]:
    """Une fusion dont on n'a pas la réponse (un arrêt pendant qu'elle partait, son échéance) : elle n'est pas
    rejouée — on ne sait pas si elle a eu lieu. La relecture de l'hôte dira ce qu'il en est."""
    return _answer(ev.data, _project(ev, ports), why=MERGE_CUT)


@PROJECTS.effect(MERGE_ASKED, lane=CAPABILITY_LANE, deadline_s=DEADLINE_S, on_interrupted=_cut)
async def _merge(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Après le commit : la fusion demandée par une personne part chez l'hôte, pour le commit qu'elle a vu. La pull
    request doit être encore celle de la demande (son numéro, sa branche, ouverte) ; sinon rien ne part."""
    d = ev.data
    p = _project(ev, ports)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or not live(p) or not by_pulls(p) or \
            (o.pull, o.pull_state, o.branch) != (d.number, PULL_OPEN, d.branch):
        return _answer(d, p, why=MERGE_STALE)
    host = ports.get("repo_host")
    merge = getattr(host, "merge_pull", None)
    if host is None or not callable(merge) or not host.handles(p.remote):
        return _answer(d, p, why=MERGE_UNREACHED)
    got = await merge(p.remote, d.number, sha=d.sha)
    if got.merged:
        return _answer(d, p, merged=True, commit=got.sha)
    return _answer(d, p, why=got.why if got.why in MERGE_WHYS else MERGE_UNREACHED)


# ── Ce qu'une personne écrit chez l'hôte sur une pull request ─────────────

#: ce qu'elle y écrit : son titre et son texte, ou un commentaire
EDIT, COMMENT = "edit", "comment"
WRITES = (EDIT, COMMENT)
#: pourquoi rien n'est parti (``PullWriteAnswered.why``) : la pull request n'est plus celle de la demande ; aucun hôte
#: ne sait l'écrire sur ce dépôt ; le texte ne se lit plus (il a été oublié) ; l'hôte a refusé, ou n'a pas répondu ;
#: la demande a été interrompue — on ne sait pas si elle a eu lieu, et elle n'est pas rejouée
STALE, NO_HOST, FORGOTTEN, REFUSED, CUT = "stale", "no_host", "forgotten", "refused", "cut"
WHYS = (STALE, NO_HOST, FORGOTTEN, REFUSED, CUT)
#: les bornes d'un titre, d'un texte, d'un commentaire (l'hôte a ``DEADLINE_S`` pour répondre, comme à une fusion)
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


def _write_answer(ev: Any, p: Project | None, *, ok: bool = False, why: str = "") -> list[Any]:
    d = ev.data
    return [PULL_WRITE_ANSWERED.draft(project=d.project, objective=d.objective, number=d.number, what=d.what,
                                      asked=ev.seq, ok=ok, why=why, owner=p.owner if p is not None else None,
                                      about=p.about if p is not None else ())]


def _write_project(ev: Any, ports: Mapping[str, Any]) -> Project | None:
    frame = _frame(ports)
    return frame.state("projects").projects.get(ev.data.project) if frame is not None else None


def _write_cut(ev: Any, ports: Mapping[str, Any], why: str = "") -> list[Any]:
    """Une écriture dont on n'a pas la réponse (un arrêt pendant qu'elle partait, son échéance) : elle n'est pas
    rejouée — relire la pull request chez l'hôte dit ce qu'il en est."""
    return _write_answer(ev, _write_project(ev, ports), why=CUT)


@PROJECTS.effect(PULL_WRITE_ASKED, lane=CAPABILITY_LANE, deadline_s=DEADLINE_S, on_interrupted=_write_cut)
async def _write(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Après le commit : ce qu'une personne a écrit part chez l'hôte. La pull request doit être encore celle de la
    demande (son numéro, ouverte) ; un texte oublié depuis ne part pas."""
    d = ev.data
    p = _write_project(ev, ports)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or not writable(p, o) or o.pull != d.number or d.what not in WRITES:
        return _write_answer(ev, p, why=STALE)
    host, store = ports.get("repo_host"), ports.get("store")
    if host is None or store is None or not host.handles(p.remote):
        return _write_answer(ev, p, why=NO_HOST)
    given = [x for x in (d.title, d.body, d.text) if x is not None and x.ref]
    texts = store.content([x.ref for x in given])
    if not given or any(x.ref not in texts for x in given):
        return _write_answer(ev, p, why=FORGOTTEN)

    def said(x: Content | None) -> str | None:
        return texts[x.ref] if x is not None and x.ref else None

    if d.what == EDIT:
        edit = getattr(host, "edit_pull", None)
        if not callable(edit):
            return _write_answer(ev, p, why=NO_HOST)
        got = await edit(p.remote, d.number, title=said(d.title), body=said(d.body))
        return _write_answer(ev, p, ok=not got.error, why=REFUSED if got.error else "")
    got = await host.remark(p.remote, d.number, body=signed(_frame(ports), d.by, said(d.text) or ""),
                            mark=reply_mark(p.id, ev.seq))
    sent = bool(got.id) and not got.error
    return _write_answer(ev, p, ok=sent, why="" if sent else REFUSED)


__all__ = ["BLOCKS", "CHECKS_GRACE_US", "COMMENT", "EDIT", "PULL_WRITE_ANSWERED", "PULL_WRITE_ASKED", "WHYS", "alone",
           "asking", "blocked", "merging", "reply_mark", "signed", "unchecked", "unsure", "writable", "writing"]
