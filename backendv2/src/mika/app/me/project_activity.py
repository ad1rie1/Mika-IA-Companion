"""Ce qui s'est passé dans un projet, pour qui est connecté (ADR 0290) : son fil d'activité, ses exécutions et ce que
chacune a fait pas à pas, son carnet, et de quoi dessiner le diagramme de ses objectifs.

**Tout vient du journal**, relu à la demande — rien n'est gardé à côté :

- **le fil** mêle, dans l'ordre, ses exécutions (``projects.run_reported``), les commits qu'elles ont laissés, ce qui
  est arrivé à ses pull requests (l'hôte relu, les vérifications, une fusion demandée, ce qu'une personne y a écrit),
  à ses tickets, et **les gestes des personnes** (un objectif ajouté, un plan validé, une consigne, une pause…). Un
  geste est ce qu'une personne a fait, quel que soit l'objet ; le reste se range par objet. Il se filtre par sorte et
  par objectif, se pagine par curseur, et se compte par jour sur trente jours ;
- **une exécution** : son épisode (``episode.started``, ``episode.ended``), son compte rendu, et ses appels d'outils
  lus dans sa trace (``runtime.traces``, jetable : gardée quatorze jours) — le nom de l'outil en mots, ce qu'il
  visait en une ligne, jamais ce qu'il a rendu ; un outil dont le résultat vient d'ailleurs le marque ;
- **le diagramme** ne porte que de vraies dates : quand un objectif a été posé, sa première exécution, sa clôture ;
  pour un jalon, quand il a été posé, dit prêt, atteint, et — déduit de ses exécutions — quand elle s'y est mise et
  combien d'exécutions il a prises. Le moteur n'estime aucune durée.

**Qui lit.** Le détail du projet (``projects._opened``), au niveau de ce que le projet écrit (``written``) : un compte
rendu, une note de carnet, un pas d'une exécution portent ce niveau. Le titre d'un ticket ne se dit que si elle peut
le lire (``tracker.veiled``). Le contrat, route par route : ``docs/protocole-moi.md``, § 11.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from starlette.routing import Route

from mika.app.me.api import Call, Denied, MeApiBase, missing, person_of
from mika.app.me.common import millis, snippet
from mika.app.me.projects import (
    BY_HER,
    BY_HOST,
    BY_OTHER,
    BY_PROJECT,
    BY_YOU,
    CHECK_WORDS,
    HOST_WORDS,
    OTHER_WORDS,
    PAGE,
    PAGE_MAX,
    PATH,
    PROJECT_WORDS,
    TEXT_SHOWN,
    TEXT_VEILED,
    YOU_WORDS,
    Reach,
    Scene,
    _name,
    _nameable,
    _opened,
    _store,
    _texts,
    reach,
    reads_files,
)
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects import faculty as f
from mika.faculties.projects import managing, tracker
from mika.faculties.projects.faculty import (
    Objective,
    Project,
    frame_of,
    milestones_of,
    objective_of,
    review_of,
    written,
)
from mika.faculties.projects.inspect import CHECKS_FR, OBJ_FR, PULL_FR, VERDICT_FR
from mika.faculties.projects.inspect_manage import WRITE_WORDS
from mika.faculties.projects.inspect_milestones import STATE_FR as MILESTONE_FR
from mika.kernel.clock import DAY
from mika.ports.workshop import CHECKS_FAILED, CHECKS_PASSED
from mika.vocab.episodes import outcome_words, project_target

#: ce que le fil lit du journal, par lots, et combien de lots au plus pour remplir une page ou compter trente jours
SCAN, SCAN_BATCHES, COUNT_BATCHES = 200, 10, 25
#: les jours comptés ; les pas d'une exécution qu'on rend, au plus, et la borne de ce qu'un pas visait
DAYS, STEPS_SHOWN, STEP_SHOWN = 30, 200, 160
#: les passages d'une mission que le diagramme rend, au plus ; les épisodes relus pour lui
PASSES_SHOWN, EPISODES_READ = 60, 1000
NO_AIMS = ("Ce projet ne t'ouvre pas ses fichiers : tu lis ce qu'elle a fait, en mots, pas les chemins ni les "
           "commandes.")
#: un texte écrit à un niveau qu'elle n'entend pas ici (ADR 0292) ne se sert pas : la ligne dit ``TEXT_VEILED``
_VEILED_REF = "\x00veiled"
NO_WORK = "Ce que ce projet écrit est d'un niveau que tu n'entends pas ici : son activité ne t'est pas lue."

# ── Les sortes du fil ─────────────────────────────────────────────────────

RUN, COMMIT, PULL, TICKET, GESTURE = "run", "commit", "pull", "ticket", "gesture"
KINDS = (RUN, COMMIT, PULL, TICKET, GESTURE)
KIND_WORDS = {RUN: "exécution", COMMIT: "commit", PULL: "pull request", TICKET: "ticket", GESTURE: "geste"}
#: une exécution, par ce qu'elle était : une séance de cadrage, du travail, une relecture indépendante
SORT_WORDS = {"frame": "cadrage", "run": "travail", "review": "relecture"}
PEOPLE = ("operator", "owner", c.BY_OPERATOR, c.BY_PERSON)

_RUNS = (c.RUN_REPORTED,)
# une fusion demandée, ce qu'une personne écrit chez l'hôte : lus par leur nom — ces faits ne s'écrivent que par
# l'action d'une personne, et leurs gardes comptent qui les nomme (``tests/unit/test_project_merge.py``)
_PULLS = (f.PULL_SEEN, f.CHECKS_SEEN, "projects.merge_asked", "projects.merge_answered",
          "projects.pull_write_asked", "projects.pull_write_answered")
_TICKETS = tracker.MOVES
_GESTURES = (f.REFRAMED, f.PAUSED, f.RESUMED, f.ARCHIVED, f.RESTORED, f.NUDGED, f.OBJECTIVE_ADDED,
             f.OBJECTIVE_CHANGED, f.MILESTONE_ADDED, f.MILESTONE_CHANGED, f.DECIDED, f.DECISION_CHANGED,
             managing.DECISION_REVISED, f.AMENDED, f.PLAN_ANSWERED, f.LINKS_SET, f.DEPOSITED)
_ALL = (*_RUNS, *_PULLS, *_TICKETS, *_GESTURES)
#: ce qu'un filtre par sorte lit du journal : un geste peut porter sur tout sauf une exécution
READS = {RUN: _RUNS, COMMIT: _RUNS, PULL: _PULLS, TICKET: _TICKETS, GESTURE: (*_PULLS, *_TICKETS, *_GESTURES)}

STATE_WORDS = {"paused": "Projet mis en pause", "resumed": "Projet repris", "archived": "Projet archivé",
               "restored": "Projet restauré", "reframed": "Réglages du projet modifiés",
               "links_set": "Ce qu'il lit a changé", "decision_revised": "Décision n° {n} modifiée",
               "nudged": "« Vas-y maintenant »", "amended": "Consigne donnée", "deposited": "Fichier déposé"}
OBJECTIVE_WORDS = {c.OPEN: "rouvert", c.DONE: "dit terminé", c.BLOCKED: "dit bloqué", c.DROPPED: "retiré"}
DECISION_MOVES = {c.IN_FORCE: "remise en vigueur", c.WITHDRAWN: "retirée", c.SUPERSEDED: "remplacée"}
TICKET_MOVES = (("accepted", "accepté"), ("validated", "son plan validé"), ("refused", "son plan refusé"),
                ("taken", "pris"), ("dismissal", "elle propose de l'écarter"))
CLOSED_WORDS = {c.DONE: "fermé comme traité", c.DROPPED: "écarté", "": "rouvert"}
NOTE_WORDS = {c.NOTE_QUESTION: "sa question", c.NOTE_PLAN: "son plan"}
WRITE_KINDS = {managing.EDIT: "Titre et texte de la pull request n° {n}", managing.COMMENT: "Commentaire sur la "
               "pull request n° {n}"}


def _work(call: Call) -> tuple[Scene, Reach]:
    """Le projet, pour qui lit ce qu'il écrit : son détail, au niveau de ce que le projet écrit."""
    sc, r = _opened(call)
    if written(r.p) > r.reader.level:
        raise Denied(403, NO_WORK)
    return sc, r


def _journal(call: Call, types: Iterable[Any], limit: int, *, where: tuple[str, Any] | None = None,
             before: int | None = None, correlations: Any = None) -> list[Any]:
    """Les derniers événements de ces types, décodés, du plus récent au plus ancien."""
    mind = call.kernel.mind
    names = [getattr(t, "name", t) for t in types]
    return [mind.decode(x) for x in mind.store.latest(names, limit, where=where, before=before,
                                                      correlations=correlations)]


def _name_of(e: Any) -> str:
    return e.type.name.rsplit(".", 1)[-1]


class _Reader:
    """Ce qu'une page du fil relit une fois : les tickets nommés (et si elle peut les lire), qui a agi."""

    def __init__(self, sc: Scene, r: Reach) -> None:
        self.sc, self.r, self.level = sc, r, written(r.p)
        self._tickets: dict[str, Any] = {}

    def heard(self, content: Any) -> str:
        """La référence d'un texte, si elle l'entend. **Chaque texte servi se compare à son niveau, par le sien**
        (ADR 0292) — celui que son contenu porte au journal, pas celui que le détail du projet a aujourd'hui : le
        compte rendu d'un objectif né d'un ticket plus confidentiel garde son niveau quand ce ticket, fermé, est
        sorti de l'état."""
        return heard(self.r, content)

    def ticket(self, key: str) -> Any:
        if key not in self._tickets:
            self._tickets[key] = tracker.entry(_store(self.sc.call), self.r.p.id, c.TICKETS, key)
        return self._tickets[key]

    def who(self, author: str, by: str) -> dict[str, Any]:
        """Qui a fait ceci : elle ; la personne connectée ; une autre personne, nommée seulement si elle a le droit
        de le savoir ; un autre projet ; quelqu'un chez l'hôte."""
        sc = self.sc
        if author == c.BY_HOST:
            return {"author_kind": BY_HOST, "author": HOST_WORDS}
        if c.asking_project(author):
            return {"author_kind": BY_PROJECT, "author": PROJECT_WORDS}
        if author in (c.BY_SELF, "self") or (not by and author not in PEOPLE):
            return {"author_kind": BY_HER, "author": self_c.name_of(sc.frame.get(self_c.PERSONA))}
        if not by:  # une personne, sans qu'on sache laquelle (un geste de vive voix)
            return {"author_kind": BY_OTHER, "author": OTHER_WORDS}
        person = person_of(sc.frame, by)
        if person == sc.person:
            return {"author_kind": BY_YOU, "author": YOU_WORDS}
        name = _name(sc, person) if _nameable(sc, person, self.level) else ""
        return {"author_kind": BY_OTHER, "author": name or OTHER_WORDS}


def heard(r: Reach, content: Any) -> str:
    """La référence d'un contenu du journal si la personne entend son niveau ; ``_VEILED_REF`` s'il est au-dessus ;
    vide s'il n'y en a pas."""
    ref = getattr(content, "ref", None) if content is not None else None
    if not ref:
        return ""
    return ref if int(getattr(content, "level", 0) or 0) <= r.reader.level else _VEILED_REF


def _said(texts: Mapping[str, str], ref: str) -> str:
    """Le texte d'une référence rendue par ``heard`` : ses mots, ou ce qui dit qu'il ne s'entend pas d'ici."""
    return TEXT_VEILED if ref == _VEILED_REF else texts.get(ref, "") if ref else ""


def _entry(e: Any, kind: str, what: str, title: str, who: Mapping[str, Any], **more: Any) -> dict[str, Any]:
    out = {"seq": e.seq, "at": millis(e.at), "kind": kind, "kind_label": KIND_WORDS[kind], "what": what,
           "title": title, "text_ref": "", "sub": "", "objective": 0, "ticket": 0, "pull": 0, "sha": "",
           "verdict": "", "verdict_label": "", "run": "", "outside": False, **who}
    out.update(more)
    return out


def _person_did(d: Any) -> bool:
    """Est-ce le geste d'une personne ? Un événement qui dit son auteur le dit ; sinon, celui qui nomme qui l'a
    fait (``by``) — une pause pour pannes, sans personne, n'en est pas un."""
    if hasattr(d, "author"):
        return d.author in PEOPLE
    return bool(getattr(d, "by", ""))


def _entries(look: _Reader, e: Any) -> list[dict[str, Any]]:
    """Ce qu'un événement du journal donne au fil : rien, une ligne, ou deux (une exécution et son commit)."""
    d, name = e.data, _name_of(e)
    her = look.who(c.BY_SELF, "")
    if name == "run_reported":
        run = _entry(e, RUN, "report", "", her, text_ref=look.heard(d.summary), objective=d.objective,
                     verdict=d.verdict, verdict_label=VERDICT_FR.get(d.verdict, d.verdict), run=e.correlation,
                     sha=d.commit[:40])
        if not d.commit:
            return [run]
        return [run, _entry(e, COMMIT, "commit", f"Commit {d.commit[:7]}", her, sub=d.branch, objective=d.objective,
                            sha=d.commit[:40], run=e.correlation)]
    if name == "pull_seen":
        words = PULL_FR.get(d.state, d.state)
        return [_entry(e, PULL, f"pull_{d.state}", f"Pull request n° {d.number} : {words}", her, sub=d.branch,
                       objective=d.objective, pull=d.number, outside=True)] if d.number and d.state else []
    if name == "checks_seen":
        if d.state not in (CHECKS_FAILED, CHECKS_PASSED):
            return []
        return [_entry(e, PULL, f"checks_{d.state}", f"Vérifications : {CHECKS_FR.get(d.state, d.state)}", her,
                       objective=d.objective, sha=d.sha[:40], verdict=d.state,
                       verdict_label=CHECKS_FR.get(d.state, d.state), outside=True)]
    if name == "merge_asked":
        return [_entry(e, GESTURE, "merge", f"Fusion de la pull request n° {d.number} demandée",
                       look.who("operator", d.by), objective=d.objective, pull=d.number, sha=d.sha[:40])]
    if name == "merge_answered":
        said = "fusionnée par l'hôte" if d.merged else "l'hôte ne l'a pas fusionnée"
        return [_entry(e, PULL, "merged" if d.merged else "merge_refused", f"Pull request n° {d.number} : {said}",
                       her, objective=d.objective, pull=d.number, outside=True)]
    if name == "pull_write_asked":
        return [_entry(e, GESTURE, f"pull_{d.what}", WRITE_KINDS.get(d.what, "").format(n=d.number) + " : demandé",
                       look.who("operator", d.by), objective=d.objective, pull=d.number,
                       text_ref=look.heard(d.text))]
    if name == "pull_write_answered":
        said = "parti chez l'hôte" if d.ok else f"pas parti ({WRITE_WORDS.get(d.why, d.why)})"
        return [_entry(e, PULL, f"pull_{d.what}_{'sent' if d.ok else 'unsent'}",
                       WRITE_KINDS.get(d.what, "").format(n=d.number) + f" : {said}", her, objective=d.objective,
                       pull=d.number)]
    if name in ("item_added", "item_changed", "item_noted"):
        return _ticket_entries(look, e, name)
    by = getattr(d, "by", "")
    who = look.who(getattr(d, "author", "operator" if by else c.BY_SELF), by)
    if not _person_did(d) and hasattr(d, "author"):
        return []  # ce qu'elle pose elle-même pendant une exécution se lit dans son compte rendu, pas ici
    objective = getattr(d, "objective", 0) or 0
    if name == "objective_added":
        return [_entry(e, GESTURE, name, f"Objectif n° {d.objective} ajouté", who, text_ref=look.heard(d.text),
                       objective=objective)]
    if name == "objective_changed":
        said = OBJECTIVE_WORDS.get(d.status or "", "modifié")
        return [_entry(e, GESTURE, name, f"Objectif n° {d.objective} {said}", who, objective=objective)]
    if name == "milestone_added":
        return [_entry(e, GESTURE, name, f"Jalon n° {d.milestone} posé sur l'objectif n° {d.objective}", who,
                       text_ref=look.heard(d.text), objective=objective)]
    if name == "milestone_changed":
        said = "validé" if d.status == c.REACHED else "retiré" if d.status == c.DROPPED else "refusé" if d.refused \
            else "modifié"
        return [_entry(e, GESTURE, name, f"Jalon n° {d.milestone} de l'objectif n° {d.objective} {said}", who,
                       objective=objective)]
    if name == "decided":
        return [_entry(e, GESTURE, name, f"Décision n° {d.decision} consignée", who, text_ref=look.heard(d.title))]
    if name == "decision_changed":
        return [_entry(e, GESTURE, name, f"Décision n° {d.decision} {DECISION_MOVES.get(d.status, d.status)}", who)]
    if name == "plan_answered":
        said = "Plan du projet validé" if d.verdict == "approve" else "Révision du plan demandée"
        return [_entry(e, GESTURE, name, said, who)]
    title = STATE_WORDS.get(name, "")
    if not title:
        return []
    if name == "nudged" and objective:
        title += f" sur l'objectif n° {objective}"
    return [_entry(e, GESTURE, name, title.format(n=getattr(d, "decision", "")), who, objective=objective,
                   text_ref=look.heard(d.instruction) if name == "amended" else "")]


def _ticket_entries(look: _Reader, e: Any, name: str) -> list[dict[str, Any]]:
    """Ce qui arrive à un ticket. Son titre ne se dit que si elle peut le lire ; ce qui vient de l'hôte ou d'un autre
    projet est marqué."""
    d = e.data
    if d.list_name != c.TICKETS:
        return []
    found = look.ticket(d.key)
    if found is None:
        return []
    item = found.item
    veiled = bool(tracker.veiled(look.r.reader, item))
    who = look.who(d.author, d.by)
    outside = d.author == c.BY_HOST or bool(c.asking_project(d.author))
    kind = GESTURE if d.author in PEOPLE and d.by else TICKET
    handle = f"#{item.number}"
    named = handle if veiled else f"{handle} {found.title}"
    if name == "item_added":
        title, what = f"Ticket {named} ouvert", "ticket_opened"
    elif name == "item_noted":
        title, what = f"Ticket {handle} : {NOTE_WORDS.get(d.kind, 'une note dans son fil')}", "ticket_noted"
    else:
        moves = [words for field, words in TICKET_MOVES if getattr(d, field, False)]
        if d.closed is not None:
            moves.append(CLOSED_WORDS.get(d.closed, d.closed))
        if any(x is not None for x in (d.title, d.text, d.kind, d.priority)):
            moves.append("modifié")
        if not moves:
            return []  # ce que le moteur note pour lui (une mesure, l'état d'une pull request)
        title, what = f"Ticket {handle} : {', '.join(moves)}", "ticket_changed"
    return [_entry(e, kind, what, snippet(title, 240), who, ticket=item.number, objective=item.objective,
                   outside=outside)]


def _filled(call: Call, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les lignes, leur texte lu : un compte rendu est le titre de son exécution ; ailleurs il suit le titre."""
    texts = _texts(call, [x["text_ref"] for x in entries if x["text_ref"] != _VEILED_REF])
    for x in entries:
        ref = x.pop("text_ref")
        x["veiled"] = ref == _VEILED_REF  # un texte d'un niveau qu'elle n'entend pas : la ligne le dit, sans lui
        text = snippet(_said(texts, ref), 300)
        if x["kind"] == RUN:
            x["title"] = text
        elif text:
            x["sub"] = text
    return entries


def _about(call: Call, p: Project) -> tuple[int, int, frozenset[int]]:
    """Ce qu'une lecture du fil ne garde que : un objectif (``objective``), ou un ticket (``ticket`` : son numéro) —
    ce qui lui arrive, et ce qui arrive aux objectifs nés de lui (leurs exécutions, leurs commits, leur pull
    request)."""
    ticket = call.number("ticket", 0, 0)
    return call.number("objective", 0, 0), ticket, \
        frozenset(o.id for o in p.objectives if ticket and o.ticket == ticket)


def _kept(x: Mapping[str, Any], objective: int, ticket: int, born: frozenset[int]) -> bool:
    if objective and x["objective"] != objective:
        return False
    return not ticket or x["ticket"] == ticket or x["objective"] in born


async def activity(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/activite[?kind=&objective=&ticket=&before=&size=]`` : son fil d'activité, du plus récent
    au plus ancien. ``before`` : le curseur rendu par la page d'avant (``next`` ; 0 : il n'y a plus rien)."""
    sc, r = _work(call)
    kind = call.arg("kind", limit=12)
    if kind and kind not in KINDS:
        raise Denied(400, "« kind » : run, commit, pull, ticket ou gesture.", {"kind": ", ".join(KINDS)})
    objective, ticket, born = _about(call, r.p)
    size = call.number("size", PAGE, 1, PAGE_MAX)
    cursor: int | None = call.number("before", 0, 0) or None
    look, out, more = _Reader(sc, r), [], True
    for _ in range(SCAN_BATCHES):
        batch = _journal(call, READS.get(kind, _ALL), SCAN, where=("project", r.p.id), before=cursor)
        for e in batch:
            if len(out) >= size:
                break
            cursor = e.seq
            out += [x for x in _entries(look, e) if (not kind or x["kind"] == kind)
                    and _kept(x, objective, ticket, born)]
        else:
            if len(batch) < SCAN:
                more = False
                break
            continue
        break
    return {"kinds": [{"code": k, "label": KIND_WORDS[k]} for k in KINDS], "size": size,
            "next": cursor or 0 if more and out else 0, "items": _filled(call, out)}


def _count(call: Call, types: Iterable[Any], project: int, counted: Any) -> bool:
    """Passe à ``counted`` chaque événement de ces types pour ce projet, du plus récent au plus ancien, par lots ;
    vrai s'il y en a trop pour tout lire (``COUNT_BATCHES`` lots) : le compte est alors incomplet."""
    cursor: int | None = None
    for _ in range(COUNT_BATCHES):
        batch = _journal(call, types, SCAN, where=("project", project), before=cursor)
        for e in batch:
            cursor = e.seq
            counted(e)
        if len(batch) < SCAN:
            return False
    return True


async def activity_totals(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/activite/totaux[?objective=&ticket=]`` : les totaux du fil — par sorte, pour ce filtre,
    sur toute son histoire (pas seulement trente jours) —, de son carnet et de ses exécutions : de quoi poser un
    compte sur chaque pastille et chaque sous-onglet. ``cut`` : trop d'événements, le compte est incomplet."""
    sc, r = _work(call)
    objective, ticket, born = _about(call, r.p)
    look = _Reader(sc, r)
    totals = dict.fromkeys(KINDS, 0)
    notes = [0]

    def feed(e: Any) -> None:
        for x in _entries(look, e):
            if _kept(x, objective, ticket, born):
                totals[x["kind"]] += 1

    def noted(e: Any) -> None:
        if ticket:
            notes[0] += e.data.objective in born
        else:
            notes[0] += not objective or e.data.objective == objective

    cut = _count(call, _ALL, r.p.id, feed)
    notes_cut = _count(call, [f.NOTED], r.p.id, noted)
    return {"kinds": [{"code": k, "label": KIND_WORDS[k], "count": totals[k]} for k in KINDS], "totals": totals,
            "total": sum(totals.values()), "cut": cut, "notes": notes[0], "notes_cut": notes_cut, "runs": r.p.runs}


async def activity_days(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/activite/jours`` : le compte par jour des trente derniers jours, sorte par sorte — de
    quoi dessiner un graphique —, et qui a fait quoi."""
    sc, r = _work(call)
    frame = sc.frame
    today = frame.local().date()
    since = frame.now - (DAYS + 1) * DAY
    days = [today - timedelta(days=n) for n in range(DAYS - 1, -1, -1)]
    counts = {day: dict.fromkeys(KINDS, 0) for day in days}
    by = {BY_HER: 0, BY_YOU: 0, "others": 0}
    look, cursor, cut = _Reader(sc, r), None, False
    for _ in range(COUNT_BATCHES):
        batch = _journal(call, _ALL, SCAN, where=("project", r.p.id), before=cursor)
        for e in batch:
            cursor = e.seq
            if e.at < since:
                break
            day = frame.local(e.at).date()
            for x in _entries(look, e) if day in counts else ():
                counts[day][x["kind"]] += 1
                by[x["author_kind"] if x["author_kind"] in (BY_HER, BY_YOU) else "others"] += 1
        else:
            if len(batch) == SCAN:
                continue
        break
    else:
        cut = True  # trop d'événements pour tout compter : les jours les plus anciens sont incomplets
    totals = {k: sum(row[k] for row in counts.values()) for k in KINDS}
    return {"days": [{"day": day.isoformat(), **counts[day], "total": sum(counts[day].values())} for day in days],
            "totals": totals, "total": sum(totals.values()), "cut": cut,
            "kinds": [{"code": k, "label": KIND_WORDS[k]} for k in KINDS],
            "by": [{"who": "self", "label": self_c.name_of(frame.get(self_c.PERSONA)), "count": by[BY_HER]},
                   {"who": "you", "label": YOU_WORDS, "count": by[BY_YOU]},
                   {"who": "others", "label": "d'autres", "count": by["others"]}]}


# ── Ses exécutions ────────────────────────────────────────────────────────


def _sort(p: Project, subject: str | None) -> tuple[str, int] | None:
    """Ce qu'était un épisode de ce projet — une séance de cadrage, du travail, une relecture — et l'objectif qu'il
    visait ; ``None`` : une prise de parole sur lui (un récit, une demande), pas une exécution."""
    if frame_of(subject) == p.id:
        return "frame", 0
    reviewed = review_of(subject)
    if reviewed is not None and reviewed[0] == p.id:
        return "review", reviewed[1]
    aimed = objective_of(subject)
    return ("run", aimed[1]) if aimed is not None and aimed[0] == p.id else None


def _objective_ref(p: Project, oid: int, texts: Mapping[str, str]) -> dict[str, Any] | None:
    o = f.objective_at(p, oid) if oid else None
    if o is None:
        return None
    return {"id": o.id, "text": texts.get(o.text_ref, ""), "kind": o.kind, "ticket": o.ticket, "status": o.status,
            "status_label": OBJ_FR.get(o.status, o.status)}


def _run_json(r: Reach, e: Any, end: Any, report: Any, texts: Mapping[str, str], *, full: bool = False
              ) -> dict[str, Any] | None:
    p = r.p
    found = _sort(p, e.data.subject)
    if found is None:
        return None
    sort, oid = found
    d = report.data if report is not None else None
    outcome = str(end.data.outcome) if end is not None else ""
    # son compte rendu et ce qu'elle a demandé : chacun à son niveau, comparé à ce que la personne entend
    summary = _said(texts, heard(r, d.summary)) if d is not None else ""
    veiled = d is not None and _VEILED_REF in (heard(r, d.summary), heard(r, d.need))
    out = {"id": e.correlation, "at": millis(e.at), "sort": sort, "sort_label": SORT_WORDS[sort],
           "objective": _objective_ref(p, d.objective if d is not None and d.objective else oid, texts),
           "running": end is None, "outcome": outcome,
           "outcome_label": outcome_words(outcome, e.data.kind)[0] if outcome else "en cours",
           "seconds": max(1, (end.at - e.at) // 1_000_000) if end is not None else 0,
           "verdict": d.verdict if d is not None else "",
           "verdict_label": VERDICT_FR.get(d.verdict, d.verdict) if d is not None else "",
           "proven": bool(d.proven) if d is not None else False, "summary": snippet(summary, 300),
           "commit": d.commit[:40] if d is not None else "", "branch": d.branch if d is not None else "",
           "asked": bool(d is not None and d.need is not None and d.need.ref), "veiled": veiled}
    if full:
        out.update({"report": summary[:TEXT_SHOWN],
                    "need": _said(texts, heard(r, d.need))[:TEXT_SHOWN] if d is not None else ""})
    return out


def _runs(call: Call, p: Project, started: list[Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    corrs = [e.correlation for e in started]
    ended = {e.correlation: e for e in _journal(call, [rt.EPISODE_ENDED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    reports = {e.correlation: e for e in _journal(call, [c.RUN_REPORTED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    refs = [o.text_ref for o in p.objectives]
    for e in reports.values():
        refs += [e.data.summary.ref or "", (e.data.need.ref or "") if e.data.need is not None else ""]
    return ended, reports, _texts(call, refs)


async def executions(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/executions[?before=&size=]`` : ses exécutions, de la plus récente à la plus ancienne —
    cadrage, travail, relecture ; l'objectif ; l'issue et le verdict ; la durée."""
    sc, r = _work(call)
    size = call.number("size", PAGE, 1, PAGE_MAX)
    before = call.number("before", 0, 0) or None
    started = _journal(call, [rt.EPISODE_STARTED], size + 1, where=("target", project_target(r.p.id)), before=before)
    page = started[:size]
    ended, reports, texts = _runs(call, r.p, page)
    items = [x for e in page
             if (x := _run_json(r, e, ended.get(e.correlation), reports.get(e.correlation), texts)) is not None]
    return {"total": r.p.runs, "size": size, "next": page[-1].seq if len(started) > size else 0,
            "sorts": [{"code": k, "label": v} for k, v in SORT_WORDS.items()], "items": items}


#: ce qu'un pas visait, lu dans les arguments de l'outil : le premier de ces noms qu'ils portent. Un chemin, une
#: commande, une recherche, une adresse — **jamais un texte de contenu** (un titre, une note, un compte rendu, le
#: texte d'une page : ADR 0292)
STEP_KEYS = ("path", "argv", "command", "query", "url")


def _args(raw: Any) -> dict[str, Any]:
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return args if isinstance(args, dict) else {}


def _elsewhere(args: Mapping[str, Any], project: int) -> int | None:
    """Le projet lié que cet appel vise (un outil qui lit un autre projet le nomme par ``project``) : son numéro ;
    0, un projet qui ne se nomme pas par un numéro ; ``None`` : ce projet-ci."""
    raw = args.get("project")
    if raw in (None, "", 0, "0") or isinstance(raw, bool):
        return None
    try:
        other = int(raw)
    except (TypeError, ValueError):
        return 0
    return None if other == project else other


def _aim(args: Mapping[str, Any]) -> str:
    """Ce qu'un appel d'outil visait, en une ligne bornée — un chemin, une commande, une recherche — : jamais ce
    qu'il a rendu, jamais un texte qu'il portait."""
    for key in STEP_KEYS:
        value = args.get(key)
        if isinstance(value, list):
            value = " ".join(str(x) for x in value)
        if isinstance(value, str | int) and str(value).strip():
            return snippet(str(value), STEP_SHOWN)
    return ""


def _steps(call: Call, sc: Scene, r: Reach, correlation: str) -> tuple[bool, list[dict[str, Any]], bool]:
    """Les pas d'une exécution, lus dans sa trace : (la trace est gardée, ses pas, il y en avait davantage). **Ce
    qu'un pas visait** (un chemin, une commande) est l'arbre du dépôt par morceaux : il ne se dit qu'avec le droit sur
    ses fichiers (``reads_files``) ; sans lui, un pas ne dit que ce qu'elle a fait, en mots. Ce qui vise un projet
    lié ne se dit que si la personne lit aussi les fichiers de ce projet-là (ADR 0292)."""
    files = reads_files(sc, r)
    opened: dict[int, bool] = {}

    def shown(args: Mapping[str, Any]) -> bool:
        other = _elsewhere(args, r.p.id)
        if not files or other is None:
            return files
        if other not in opened:
            p = sc.s.projects.get(other)
            opened[other] = p is not None and reads_files(sc, reach(sc, p))
        return opened[other]

    traces = call.port("traces")
    trace = traces.get(correlation) if traces is not None else None
    if not isinstance(trace, dict):
        return False, [], False
    calls = [t for t in trace.get("tool_calls") or () if isinstance(t, dict)]
    tools = call.kernel.registry.tools
    out = []
    for t in calls[:STEPS_SHOWN]:
        name = str(t.get("name", ""))
        spec = tools.get(name)
        args = _args(t.get("args"))
        out.append({"tool": name, "label": (spec.label if spec is not None else "") or name,
                    "aim": _aim(args) if shown(args) else "", "ok": bool(t.get("ok")),
                    "ran": bool(t.get("executed", True)),
                    "ms": int(t.get("duration_us") or 0) // 1000,
                    "acts": bool(spec.acts) if spec is not None else False,
                    # ce que cet outil rend vient d'ailleurs, et ce qu'il porte en sort : le client le présente ainsi
                    "outside": bool(spec.outside) if spec is not None else True})
    return True, out, len(calls) > STEPS_SHOWN


async def execution(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/execution?id=`` : une exécution — son compte rendu, ce qu'elle a fait pas à pas, son
    commit, ce qu'elle a demandé."""
    sc, r = _work(call)
    wanted = call.arg("id", limit=120)
    started = [e for e in _journal(call, [rt.EPISODE_STARTED], 2, correlations=[wanted])
               if e.data.target == project_target(r.p.id)] if wanted else []
    if not started:
        raise missing()
    ended, reports, texts = _runs(call, r.p, started[:1])
    e = started[0]
    out = _run_json(r, e, ended.get(e.correlation), reports.get(e.correlation), texts, full=True)
    if out is None:
        raise missing()
    kept, steps, more = _steps(call, sc, r, e.correlation)
    aims = reads_files(sc, r)
    return {**out, "steps_kept": kept, "steps": steps, "steps_cut": more,
            # ce que chaque pas visait ne se dit qu'avec le droit sur ses fichiers ; sinon pourquoi, en mots
            "steps_aims": aims, "steps_aims_why": "" if aims else NO_AIMS}


# ── Son carnet ────────────────────────────────────────────────────────────


async def notebook(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/carnet[?objective=&before=&size=]`` : ses notes, les plus récentes d'abord, chacune avec
    l'objectif qu'elle visait en l'écrivant."""
    sc, r = _work(call)
    size = call.number("size", PAGE, 1, PAGE_MAX)
    objective = call.number("objective", 0, 0)
    cursor: int | None = call.number("before", 0, 0) or None
    found: list[Any] = []
    more = True
    for _ in range(SCAN_BATCHES):
        batch = _journal(call, [f.NOTED], SCAN, where=("project", r.p.id), before=cursor)
        for e in batch:
            if len(found) >= size:
                break
            cursor = e.seq
            if not objective or e.data.objective == objective:
                found.append(e)
        else:
            if len(batch) < SCAN:
                more = False
                break
            continue
        break
    texts = _texts(call, [*(e.data.text.ref or "" for e in found), *(o.text_ref for o in r.p.objectives)])
    counted = [0]

    def one(e: Any) -> None:
        counted[0] += not objective or e.data.objective == objective

    # son total, pour ce filtre (ADR 0293) : compté dans le journal, borné (``total_cut`` : incomplet)
    total_cut = _count(call, [f.NOTED], r.p.id, one)
    return {"size": size, "next": cursor or 0 if more and found else 0, "total": counted[0], "total_cut": total_cut,
            # une note garde le niveau où elle a été écrite : au-dessus de ce qu'elle entend, elle ne se sert pas
            "items": [{"seq": e.seq, "at": millis(e.at), "text": _said(texts, heard(r, e.data.text))[:TEXT_SHOWN],
                       "veiled": heard(r, e.data.text) == _VEILED_REF,
                       "objective": _objective_ref(r.p, e.data.objective, texts), "run": e.correlation}
                      for e in found]}


# ── Le diagramme de ses objectifs ─────────────────────────────────────────


def _spans(o: Objective, starts: list[int]) -> dict[int, tuple[int, int]]:
    """Pour chaque jalon vivant d'un objectif : quand elle s'y est mise, et combien d'exécutions il a prises —
    déduits de ses exécutions (``starts``, leurs départs, du plus ancien au plus récent). Elle se met à un jalon à la
    première exécution qui suit le jalon d'avant atteint ; atteint dans la même exécution que lui, il part de
    celle-là. Sans exécution depuis, il n'a pas commencé (0)."""
    out: dict[int, tuple[int, int]] = {}
    bound = 0
    for m in milestones_of(o):
        end = m.reached_at or 0
        later = [s for s in starts if s >= bound and (not end or s <= end)]
        start = later[0] if later else max((s for s in starts if end and s <= end), default=0)
        runs = sum(1 for s in starts if start and s >= start and (not end or s <= end))
        out[m.id] = (start, runs)
        if not end:
            break  # les suivants attendent celui-ci
        bound = end
    return out


async def diagram(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/diagramme`` : ses objectifs et ses missions dans l'ordre du plan, leurs jalons, et leurs
    dates — de quoi dessiner l'avancement et le temps. De vraies dates seulement ; 0 : pas encore arrivé."""
    sc, r = _work(call)
    p = r.p
    started = _journal(call, [rt.EPISODE_STARTED], EPISODES_READ, where=("target", project_target(p.id)))
    starts: dict[int, list[int]] = {}
    for e in reversed(started):
        found = _sort(p, e.data.subject)
        if found is not None and found[0] == "run" and found[1]:
            starts.setdefault(found[1], []).append(e.at)
    shown = sorted((o for o in p.objectives if o.status != c.DROPPED), key=lambda o: (o.rank or 10_000, o.id))
    texts = _texts(call, [ref for o in shown for ref in (o.text_ref, *(m.text_ref for m in milestones_of(o)))])
    rows = []
    for o in shown:
        mine = starts.get(o.id, [])
        spans = _spans(o, mine) if o.kind == c.ONCE else {}
        alive = milestones_of(o)
        rows.append({
            "id": o.id, "text": texts.get(o.text_ref, ""), "kind": o.kind, "status": o.status,
            "status_label": OBJ_FR.get(o.status, o.status), "after": o.after, "rank": o.rank, "ticket": o.ticket,
            "added_at": millis(o.at), "started_at": millis(mine[0]) if mine else 0,
            "last_run": millis(o.last_run_at), "closed_at": millis(o.closed_at), "runs": len(mine) or o.worked,
            "reached": sum(1 for m in alive if m.status == c.REACHED), "milestones_total": len(alive),
            "passes": [millis(s) for s in mine[-PASSES_SHOWN:]] if o.kind == c.CONSTANT else [],
            "milestones": [{
                "id": m.id, "text": texts.get(m.text_ref, ""), "status": m.status,
                "status_label": MILESTONE_FR.get(m.status, m.status), "check": m.check,
                "check_label": CHECK_WORDS.get(m.check, m.check), "ready": bool(m.ready_at and m.status == c.OPEN),
                "added_at": millis(m.at), "started_at": millis(spans.get(m.id, (0, 0))[0]),
                "ready_at": millis(m.ready_at), "reached_at": millis(m.reached_at),
                "runs": spans.get(m.id, (0, 0))[1]} for m in alive]})
    dated = [x for row in rows for x in (row["added_at"], row["started_at"]) if x]
    return {"now": millis(sc.frame.now), "from": min(dated, default=0), "cut": len(started) >= EPISODES_READ,
            "objectives": rows}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    one = PATH + "/{project:int}"
    return [r(one + "/activite", activity), r(one + "/activite/jours", activity_days),
            r(one + "/activite/totaux", activity_totals),
            r(one + "/executions", executions), r(one + "/execution", execution), r(one + "/carnet", notebook),
            r(one + "/diagramme", diagram)]
