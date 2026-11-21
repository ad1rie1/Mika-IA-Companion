"""Ce qui déclenche un objectif (ADR 0265) : la grammaire, pure.

Un objectif constant dit ce qui le rend dû en plus de sa cadence : une liste de déclencheurs, écrits et vérifiés
comme l'agenda d'un projet (un texte court, normalisé avant d'entrer au journal) :

- ``project:<n>:commit`` — la base du projet n° n, qu'il lit, a avancé : ce qu'un lecteur en voit a changé (ADR
  0280). En flux direct, le commit d'une de ses exécutions ; en flux par pull request, la fusion acceptée, ou toute
  récupération qui ramène autre chose — jamais le commit d'une branche de travail ;
- ``project:<n>:done`` — un objectif de ce projet a abouti ;
- ``app:<nom>`` — une app de son projet a signalé quelque chose ;
- ``wake:<nom>`` — un réveil par API le vise ;
- ``item:<liste>`` — un élément de cette liste de son projet (``tickets``, une liste de suivi) a été ajouté,
  changé ou noté par un autre qu'elle (ADR 0268).

Une cause ne se déclare pas : ``ask:<n>``, la fermeture d'une demande faite au projet n° n (ADR 0271). Elle éveille
l'objectif qui a ouvert cette demande, sans qu'il l'écrive (``ask_key``, ``asked``) : ``parse`` la refuse.

``SORTS`` est le seul endroit qui dit les sortes connues. En ajouter une, c'est y ajouter une ligne : comment lire
ce qui suit son nom. Sa forme normalisée (``Trigger.key``) est ce que garde l'objectif (``Objective.on``) et ce que
porte une cause (``Stir.key``) : la même chaîne des deux côtés, rien à traduire.

Ce module ne juge aucun droit et ne connaît aucun état : qu'un projet soit lu se demande à ``refusal`` avec ce que
l'appelant en sait (ses liens) ; ce que le lien donne quand l'événement arrive se relit ailleurs (``links.py``, le
processus ``projects.stirs``). Qu'une app ou un réveil existe ne se vérifie pas ici non plus : un plan peut nommer
l'app qu'il va écrire, et un déclencheur sans rien pour le déclencher ne fait rien.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

#: les sortes
PROJECT, APP, WAKE, ITEM = "project", "app", "wake", "item"
#: ce qui se passe dans un projet lu
COMMIT, DONE = "commit", "done"
EVENTS = (COMMIT, DONE)
#: les déclencheurs d'un objectif, au plus
TRIGGERS_MAX = 4
#: le nom d'une app ou d'un réveil, tel qu'un déclencheur l'écrit (les deux règles de nom y tiennent)
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
#: ce qu'on cite d'un déclencheur refusé
SHOWN = 60

#: pourquoi un déclencheur est refusé (les clés de ``projects.triggers.refused`` dans sa voix : NE PAS RENOMMER) :
#: une sorte inconnue ; un projet mal écrit ; ce qui s'y passe, mal écrit ; un nom mal écrit ; trop de
#: déclencheurs ; le projet lui-même ; un projet qu'il ne lit pas ; un objectif qui n'est pas constant ; un constant
#: sans cadence ni déclencheur
SORT, NUMBER, EVENT, NAMED, TOO_MANY, ITSELF, UNREAD, NOT_CONSTANT, NOTHING = (
    "sort", "number", "event", "name", "too_many", "itself", "unread", "not_constant", "nothing")


class BadTrigger(ValueError):
    """Un déclencheur qui ne s'écrit pas ainsi : ``why`` (un code, que sa voix et la console disent en mots) et ce
    qui était écrit."""

    def __init__(self, why: str, text: str = "") -> None:
        super().__init__(f"{why}: {text[:SHOWN]}")
        self.why = why
        self.text = text[:SHOWN]


@dataclass(frozen=True, slots=True)
class Trigger:
    """Un déclencheur lu : sa sorte et ce qu'il désigne."""

    sort: str
    #: ``project`` : le numéro du projet lu (0 pour les autres sortes)
    project: int = 0
    #: ``project`` : ce qui s'y passe (``commit``, ``done``) ; ``app``, ``wake`` : leur nom
    name: str = ""

    @property
    def key(self) -> str:
        """Sa forme normalisée : ce que garde l'objectif, et ce que porte une cause."""
        return f"{self.sort}:{self.project}:{self.name}" if self.sort == PROJECT else f"{self.sort}:{self.name}"


def _project(tail: str, text: str) -> Trigger:
    number, _, event = tail.partition(":")
    number = number.strip().lstrip("#").strip()
    if not number.isdecimal() or int(number) <= 0:
        raise BadTrigger(NUMBER, text)
    if event.strip() not in EVENTS:
        raise BadTrigger(EVENT, text)
    return Trigger(PROJECT, int(number), event.strip())


def _named(sort: str) -> Callable[[str, str], Trigger]:
    def read(tail: str, text: str) -> Trigger:
        name = tail.strip()
        if not NAME.fullmatch(name):
            raise BadTrigger(NAMED, text)
        return Trigger(sort, name=name)

    return read


#: les sortes connues, et comment lire ce qui suit leur nom (``<sorte>:<suite>``) — le seul endroit qui les dit
SORTS: Mapping[str, Callable[[str, str], Trigger]] = {PROJECT: _project, APP: _named(APP), WAKE: _named(WAKE),
                                                       ITEM: _named(ITEM)}


def parse(text: str) -> Trigger:
    """Un déclencheur écrit à la main, lu (sans casse ni espaces autour) ; ``BadTrigger`` s'il ne s'écrit pas ainsi."""
    raw = (text or "").strip().lower()
    sort, _, tail = raw.partition(":")
    reader = SORTS.get(sort.strip())
    if reader is None:
        raise BadTrigger(SORT, raw)
    return reader(tail, raw)


def read(key: str) -> Trigger | None:
    """Un déclencheur gardé (sa forme normalisée), relu ; ``None`` pour ce qui ne se lit plus : total."""
    try:
        return parse(key)
    except BadTrigger:
        return None


def checked(texts: Iterable[str]) -> tuple[str, ...]:
    """Des déclencheurs acceptables, normalisés, chacun une fois, dans leur ordre ; ``BadTrigger`` au premier qui ne
    s'écrit pas ainsi, ou s'il y en a trop."""
    keys = tuple(dict.fromkeys(parse(t).key for t in texts if (t or "").strip()))
    if len(keys) > TRIGGERS_MAX:
        raise BadTrigger(TOO_MANY, ", ".join(keys))
    return keys


def kept(texts: Iterable[str]) -> tuple[str, ...]:
    """Ce qu'un objectif garde de ce qu'on lui donne : la règle du réducteur, qui reste total — ce qui ne se lit pas
    est ignoré, comme ce qui dépasse ``TRIGGERS_MAX``."""
    found = (read(t) for t in texts)
    return tuple(dict.fromkeys(t.key for t in found if t is not None))[:TRIGGERS_MAX]


def refusal(key: str, project: int, reads: Collection[int]) -> str:
    """Pourquoi ce projet ne peut pas se donner ce déclencheur (vide : il le peut). Un déclencheur entre projets suit
    le lien de lecture : jamais le projet lui-même (son propre commit le relancerait sans fin), jamais un projet
    qu'il ne lit pas (``reads`` : ses liens, et ceux que son plan demande). Les liens ne formant jamais de boucle,
    les déclencheurs non plus."""
    t = read(key)
    if t is None or t.sort != PROJECT:
        return ""
    if t.project == project:
        return ITSELF
    return "" if t.project in reads else UNREAD


def accepted(project: int, reads: Collection[int], constant: bool, on: Iterable[str],
             only_on_event: bool = False) -> tuple[str, ...]:
    """Les déclencheurs qu'on donne à un objectif, vérifiés et normalisés — ce que font ses outils et la console
    avant d'écrire, comme ``check_schedule`` pour un agenda ; ``BadTrigger`` sinon. ``project`` : son projet (0 : il
    n'existe pas encore) ; ``reads`` : les projets qu'il lit, ou que son plan demande à lire ; ``constant`` : seul un
    constant a des déclencheurs ; ``only_on_event`` : sans cadence, il lui en faut au moins un."""
    wanted = [text for text in on if (text or "").strip()]
    if not constant:
        if wanted or only_on_event:
            raise BadTrigger(NOT_CONSTANT, ", ".join(wanted))
        return ()
    keys = checked(wanted)
    for key in keys:
        why = refusal(key, project, reads)
        if why:
            raise BadTrigger(why, key)
    if only_on_event and not keys:
        raise BadTrigger(NOTHING)
    return keys


def commit_key(project: int) -> str:
    """Le déclencheur qu'éveille la base de ce projet quand elle avance (ADR 0280)."""
    return Trigger(PROJECT, project, COMMIT).key


def done_key(project: int) -> str:
    """Le déclencheur qu'éveille un objectif abouti de ce projet."""
    return Trigger(PROJECT, project, DONE).key


def app_key(name: str) -> str:
    """Le déclencheur qu'éveille un signal de cette app."""
    return Trigger(APP, name=name).key


def wake_key(name: str) -> str:
    """Le déclencheur d'un objectif que vise ce réveil par API."""
    return Trigger(WAKE, name=name).key


def item_key(name: str) -> str:
    """Le déclencheur qu'éveille ce qui bouge dans cette liste du projet (ADR 0268)."""
    return Trigger(ITEM, name=name).key


# ── Une cause qui ne se déclare pas ────────────────────────────────────────

#: une demande faite à un autre projet est fermée (ADR 0271) : ``ask:<n>``, n étant le projet visé. Ce n'est pas une
#: sorte (``SORTS``) : aucun objectif ne l'écrit — elle éveille l'objectif qui a ouvert la demande, et lui seul
ASK = "ask"


def ask_key(project: int) -> str:
    """La cause que pose la fermeture d'une demande faite à ce projet."""
    return f"{ASK}:{project}"


def asked(key: str) -> int:
    """Le projet visé par la demande dont la fermeture fait cette cause ; 0 : ce n'en est pas une."""
    sort, _, number = (key or "").partition(":")
    return int(number) if sort == ASK and number.isdecimal() else 0
