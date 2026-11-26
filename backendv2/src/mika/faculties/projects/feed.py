"""Le fil d'un projet et les pas d'une exécution (ADR 0290, 0297) — pur, lu par l'API par personne
(``app/domains/projects/api/activity.py``) et par la fiche de la console (``app/domains/projects/console/activity.py``).

- **Le fil** : ce qu'un événement de son journal donne à son fil d'activité — rien, une ligne, ou deux (une exécution
  et son commit) —, rangé par sorte (exécution, commit, pull request, ticket, geste). Un geste est ce qu'une personne
  a fait, quel que soit l'objet ; le reste se range par objet. Qui a fait quoi et si un texte s'entend se demandent à
  qui lit (``Look``) : l'API nomme selon ses règles (ADR 0292), la console voit tout.
- **Les pas d'une exécution**, lus dans sa trace : le nom de l'outil en mots, ce qu'il visait en une ligne — un
  chemin, une commande, une recherche —, jamais ce qu'il a rendu ni un texte qu'il portait.

Une ligne garde l'instant du moteur (``at``, en µs) : chacun le met à sa forme.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from mika.contracts import projects as c
from mika.faculties.projects import decisions, merge, tracker
from mika.faculties.projects import faculty as f
from mika.faculties.projects.inspect import CHECKS_FR, PULL_FR, VERDICT_FR
from mika.faculties.projects.inspect_merge import WRITE_WORDS
from mika.ports.workshop import CHECKS_FAILED, CHECKS_PASSED

# ── Les sortes du fil ─────────────────────────────────────────────────────

RUN, COMMIT, PULL, TICKET, GESTURE = "run", "commit", "pull", "ticket", "gesture"
KINDS = (RUN, COMMIT, PULL, TICKET, GESTURE)
KIND_WORDS = {RUN: "exécution", COMMIT: "commit", PULL: "pull request", TICKET: "ticket", GESTURE: "geste"}
#: une exécution, par ce qu'elle était : une séance de cadrage, du travail, une relecture indépendante
SORT_WORDS = {"frame": "cadrage", "run": "travail", "review": "relecture"}
PEOPLE = ("operator", "owner", c.BY_OPERATOR, c.BY_PERSON)

RUNS = (c.RUN_REPORTED,)
# une fusion demandée, ce qu'une personne écrit chez l'hôte : lus par leur nom — ces faits ne s'écrivent que par
# l'action d'une personne, et leurs gardes comptent qui les nomme (``tests/unit/test_project_merge.py``)
PULLS = (f.PULL_SEEN, f.CHECKS_SEEN, "projects.merge_asked", "projects.merge_answered",
         "projects.pull_write_asked", "projects.pull_write_answered")
TICKETS = tracker.MOVES
GESTURES = (f.REFRAMED, f.PAUSED, f.RESUMED, f.ARCHIVED, f.RESTORED, f.NUDGED, f.OBJECTIVE_ADDED,
            f.OBJECTIVE_CHANGED, f.MILESTONE_ADDED, f.MILESTONE_CHANGED, f.DECIDED, f.DECISION_CHANGED,
            decisions.DECISION_REVISED, f.AMENDED, f.PLAN_ANSWERED, f.LINKS_SET, f.DEPOSITED)
ALL = (*RUNS, *PULLS, *TICKETS, *GESTURES)
#: ce qu'un filtre par sorte lit du journal : un geste peut porter sur tout sauf une exécution
READS = {RUN: RUNS, COMMIT: RUNS, PULL: PULLS, TICKET: TICKETS, GESTURE: (*PULLS, *TICKETS, *GESTURES)}

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
WRITE_KINDS = {merge.EDIT: "Titre et texte de la pull request n° {n}", merge.COMMENT: "Commentaire sur la "
               "pull request n° {n}"}
#: les gestes qui portent sur une décision : leur numéro se lit dans leur fait (la console y mène)
DECISION_FACTS = ("decided", "decision_changed", "decision_revised")


class Look(Protocol):
    """Ce que le fil demande à qui le lit : qui a fait ceci (``author_kind``, ``author``), la référence d'un texte
    s'il l'entend, un ticket nommé par sa clé (``tracker.entry``), et si son titre lui est voilé."""

    def who(self, author: str, by: str) -> dict[str, Any]: ...

    def heard(self, content: Any) -> str: ...

    def ticket(self, key: str) -> Any: ...

    def veiled(self, item: Any) -> bool: ...


def clip(text: str, limit: int) -> str:
    """Le début d'un texte, sur une ligne : ``limit`` caractères au plus, ``…`` compris."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def name_of(e: Any) -> str:
    return e.type.name.rsplit(".", 1)[-1]


def entry(e: Any, kind: str, what: str, title: str, who: Mapping[str, Any], **more: Any) -> dict[str, Any]:
    out = {"seq": e.seq, "at": e.at, "kind": kind, "kind_label": KIND_WORDS[kind], "what": what,
           "title": title, "text_ref": "", "sub": "", "objective": 0, "ticket": 0, "pull": 0, "sha": "",
           "verdict": "", "verdict_label": "", "run": "", "outside": False, **who}
    out.update(more)
    return out


def person_did(d: Any) -> bool:
    """Est-ce le geste d'une personne ? Un événement qui dit son auteur le dit ; sinon, celui qui nomme qui l'a
    fait (``by``) — une pause pour pannes, sans personne, n'en est pas un."""
    if hasattr(d, "author"):
        return d.author in PEOPLE
    return bool(getattr(d, "by", ""))


def entries(look: Look, e: Any) -> list[dict[str, Any]]:
    """Ce qu'un événement du journal donne au fil : rien, une ligne, ou deux (une exécution et son commit)."""
    d, name = e.data, name_of(e)
    her = look.who(c.BY_SELF, "")
    if name == "run_reported":
        run = entry(e, RUN, "report", "", her, text_ref=look.heard(d.summary), objective=d.objective,
                    verdict=d.verdict, verdict_label=VERDICT_FR.get(d.verdict, d.verdict), run=e.correlation,
                    sha=d.commit[:40])
        if not d.commit:
            return [run]
        return [run, entry(e, COMMIT, "commit", f"Commit {d.commit[:7]}", her, sub=d.branch, objective=d.objective,
                           sha=d.commit[:40], run=e.correlation)]
    if name == "pull_seen":
        words = PULL_FR.get(d.state, d.state)
        return [entry(e, PULL, f"pull_{d.state}", f"Pull request n° {d.number} : {words}", her, sub=d.branch,
                      objective=d.objective, pull=d.number, outside=True)] if d.number and d.state else []
    if name == "checks_seen":
        if d.state not in (CHECKS_FAILED, CHECKS_PASSED):
            return []
        return [entry(e, PULL, f"checks_{d.state}", f"Vérifications : {CHECKS_FR.get(d.state, d.state)}", her,
                      objective=d.objective, sha=d.sha[:40], verdict=d.state,
                      verdict_label=CHECKS_FR.get(d.state, d.state), outside=True)]
    if name == "merge_asked":
        return [entry(e, GESTURE, "merge", f"Fusion de la pull request n° {d.number} demandée",
                      look.who("operator", d.by), objective=d.objective, pull=d.number, sha=d.sha[:40])]
    if name == "merge_answered":
        said = "fusionnée par l'hôte" if d.merged else "l'hôte ne l'a pas fusionnée"
        return [entry(e, PULL, "merged" if d.merged else "merge_refused", f"Pull request n° {d.number} : {said}",
                      her, objective=d.objective, pull=d.number, outside=True)]
    if name == "pull_write_asked":
        return [entry(e, GESTURE, f"pull_{d.what}", WRITE_KINDS.get(d.what, "").format(n=d.number) + " : demandé",
                      look.who("operator", d.by), objective=d.objective, pull=d.number,
                      text_ref=look.heard(d.text))]
    if name == "pull_write_answered":
        said = "parti chez l'hôte" if d.ok else f"pas parti ({WRITE_WORDS.get(d.why, d.why)})"
        return [entry(e, PULL, f"pull_{d.what}_{'sent' if d.ok else 'unsent'}",
                      WRITE_KINDS.get(d.what, "").format(n=d.number) + f" : {said}", her, objective=d.objective,
                      pull=d.number)]
    if name in ("item_added", "item_changed", "item_noted"):
        return ticket_entries(look, e, name)
    by = getattr(d, "by", "")
    who = look.who(getattr(d, "author", "operator" if by else c.BY_SELF), by)
    if not person_did(d) and hasattr(d, "author"):
        return []  # ce qu'elle pose elle-même pendant une exécution se lit dans son compte rendu, pas ici
    objective = getattr(d, "objective", 0) or 0
    if name == "objective_added":
        return [entry(e, GESTURE, name, f"Objectif n° {d.objective} ajouté", who, text_ref=look.heard(d.text),
                      objective=objective)]
    if name == "objective_changed":
        said = OBJECTIVE_WORDS.get(d.status or "", "modifié")
        return [entry(e, GESTURE, name, f"Objectif n° {d.objective} {said}", who, objective=objective)]
    if name == "milestone_added":
        return [entry(e, GESTURE, name, f"Jalon n° {d.milestone} posé sur l'objectif n° {d.objective}", who,
                      text_ref=look.heard(d.text), objective=objective)]
    if name == "milestone_changed":
        said = "validé" if d.status == c.REACHED else "retiré" if d.status == c.DROPPED else "refusé" if d.refused \
            else "modifié"
        return [entry(e, GESTURE, name, f"Jalon n° {d.milestone} de l'objectif n° {d.objective} {said}", who,
                      objective=objective)]
    if name == "decided":
        return [entry(e, GESTURE, name, f"Décision n° {d.decision} consignée", who, text_ref=look.heard(d.title))]
    if name == "decision_changed":
        return [entry(e, GESTURE, name, f"Décision n° {d.decision} {DECISION_MOVES.get(d.status, d.status)}", who)]
    if name == "plan_answered":
        said = "Plan du projet validé" if d.verdict == "approve" else "Révision du plan demandée"
        return [entry(e, GESTURE, name, said, who)]
    title = STATE_WORDS.get(name, "")
    if not title:
        return []
    if name == "nudged" and objective:
        title += f" sur l'objectif n° {objective}"
    return [entry(e, GESTURE, name, title.format(n=getattr(d, "decision", "")), who, objective=objective,
                  text_ref=look.heard(d.instruction) if name == "amended" else "")]


def ticket_entries(look: Look, e: Any, name: str) -> list[dict[str, Any]]:
    """Ce qui arrive à un ticket. Son titre ne se dit que si elle peut le lire ; ce qui vient de l'hôte ou d'un autre
    projet est marqué."""
    d = e.data
    if d.list_name != c.TICKETS:
        return []
    found = look.ticket(d.key)
    if found is None:
        return []
    item = found.item
    veiled = bool(look.veiled(item))
    who = look.who(d.author, d.by)
    outside = c.from_outside(d.author)
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
    return [entry(e, kind, what, clip(title, 240), who, ticket=item.number, objective=item.objective,
                  outside=outside)]


def kept(x: Mapping[str, Any], objective: int, ticket: int, born: frozenset[int]) -> bool:
    """Une ligne que garde une lecture filtrée : sur cet objectif ; sur ce ticket, ou sur un objectif né de lui."""
    if objective and x["objective"] != objective:
        return False
    return not ticket or x["ticket"] == ticket or x["objective"] in born


# ── Les pas d'une exécution ───────────────────────────────────────────────

#: les pas qu'on rend, au plus, et la borne de ce qu'un pas visait
STEPS_SHOWN, STEP_SHOWN = 200, 160
#: ce qu'un pas visait, lu dans les arguments de l'outil : le premier de ces noms qu'ils portent. Un chemin, une
#: commande, une recherche, une adresse — **jamais un texte de contenu** (un titre, une note, un compte rendu, le
#: texte d'une page : ADR 0292)
STEP_KEYS = ("path", "argv", "command", "query", "url")


def args_of(raw: Any) -> dict[str, Any]:
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return args if isinstance(args, dict) else {}


def elsewhere(args: Mapping[str, Any], project: int) -> int | None:
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


def aim(args: Mapping[str, Any]) -> str:
    """Ce qu'un appel d'outil visait, en une ligne bornée — un chemin, une commande, une recherche — : jamais ce
    qu'il a rendu, jamais un texte qu'il portait."""
    for key in STEP_KEYS:
        value = args.get(key)
        if isinstance(value, list):
            value = " ".join(str(x) for x in value)
        if isinstance(value, str | int) and str(value).strip():
            return clip(str(value), STEP_SHOWN)
    return ""


def steps(trace: Any, tools: Mapping[str, Any], shown: Callable[[Mapping[str, Any]], bool]
          ) -> tuple[bool, list[dict[str, Any]], bool]:
    """Les pas d'une exécution, lus dans sa trace : (la trace est gardée, ses pas, il y en avait davantage).
    ``tools`` : les outils déclarés (leur nom en mots, s'ils agissent, si ce qu'ils rendent vient d'ailleurs) ;
    ``shown(args)`` : ce qu'un pas visait se dit-il à qui lit ?"""
    if not isinstance(trace, dict):
        return False, [], False
    calls = [t for t in trace.get("tool_calls") or () if isinstance(t, dict)]
    out = []
    for t in calls[:STEPS_SHOWN]:
        name = str(t.get("name", ""))
        spec = tools.get(name)
        args = args_of(t.get("args"))
        out.append({"tool": name, "label": (spec.label if spec is not None else "") or name,
                    "aim": aim(args) if shown(args) else "", "ok": bool(t.get("ok")),
                    "ran": bool(t.get("executed", True)),
                    "ms": int(t.get("duration_us") or 0) // 1000,
                    "acts": bool(spec.acts) if spec is not None else False,
                    # ce que cet outil rend vient d'ailleurs, et ce qu'il porte en sort : le client le présente ainsi
                    "outside": bool(spec.outside) if spec is not None else True})
    return True, out, len(calls) > STEPS_SHOWN
