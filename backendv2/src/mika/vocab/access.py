"""Qui peut quoi, en lignes lues de haut en bas comme les règles d'un pare-feu (ADR 0131, 0133) : ce qu'en partagent
les services MCP, les projets et leurs apps.

Une ligne coche ses **sources** — toi (sa propriétaire), elle quand elle travaille seule, tes proches en privé, tout
le monde, et des personnes par leur nom (reconnues seulement authentifiées) — et **quand** (quand elle répond, quand
elle prend la parole ; aucun : toujours) ; ce qu'elle accorde est à son propriétaire (un service : ce qu'elle fait
d'un outil, ce qu'elle en garde ; un projet : le voir, le piloter, se servir de ses apps). Pour quelqu'un, à un
moment, la première ligne qui le désigne décide ; aucune : la ligne par défaut.

Le moteur est un seul (``decide``) : pour un tableau, la première ligne qui correspond, sinon la ligne par défaut —
et sa place, qui dit pourquoi. Ce qui correspond dépend du type de règle : la personne en face et le moment
(``facing`` : les services, les projets et leurs apps), le destinataire d'un envoi (``vocab.sending``).

Des planchers qu'aucune ligne n'ouvre : agir (un outil, piloter) jamais dans un salon, avec une inconnue, ni sans
personne — « tout le monde » n'y ouvre qu'en parler (``acting``) ; ce que le code réserve à sa propriétaire
(``owner_here``).

Une valeur partagée, sans faculté : les lignes sont ce que chaque propriétaire range (``who``, ``when``, le reste à
lui), lues ici par leurs champs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from mika.vocab.episodes import PROJECT_KINDS, WAKE_KINDS, WORKING, Kind
from mika.vocab.privacy import ChannelTrust

#: les sources qu'une ligne coche (plusieurs à la fois) : toi ; elle quand elle travaille seule (pour toi) ; tes
#: proches (un lien « proche »), en privé, authentifiés ; tout le monde ; une personne par son nom (``personne:<clé>``,
#: reconnue seulement authentifiée)
OWNER, WORK, CLOSE, EVERYONE, PERSON = "proprietaire", "travail", "proches", "tous", "personne:"
SOURCES = ((OWNER, "Toi"), (WORK, "Elle, quand elle travaille seule"), (CLOSE, "Tes proches, en privé"),
           (EVERYONE, "Tout le monde"))
#: d'avant (ADR 0131) : « toi » (toi, et elle quand elle travaille pour toi) et « comptes » (toute personne
#: authentifiée en tête-à-tête) — lus encore, traduits (``upgrade``) ; « comptes » reste lisible tant qu'on ne l'a pas
#: changé
WHO_OWNER, WHO_ACCOUNTS, WHO_PERSON = "toi", "comptes", PERSON
#: une source telle qu'une ligne la range (« comptes » : d'avant, encore lisible)
SOURCE = re.compile(rf"(?:{OWNER}|{WORK}|{CLOSE}|{EVERYONE}|{WHO_ACCOUNTS}|{PERSON}\S{{1,200}})")
#: où elle est : avec toi, avec une personne authentifiée en tête-à-tête, quand elle travaille seule, dans un salon,
#: avec une inconnue
ACCOUNT, ROOM, STRANGER = "compte", "salon", "inconnue"
#: les moments où une ligne vaut, à qui est en face (plusieurs à la fois ; aucun : toujours) ; le travail est une
#: source, plus un moment
MOMENTS = (("conversation", "quand elle répond"), ("initiative", "quand elle prend la parole"))
#: les sortes d'épisode de chaque moment, et du travail
KINDS_OF: Mapping[str, frozenset[str]] = {
    "conversation": frozenset({Kind.REPLY}),
    "initiative": frozenset({Kind.INITIATIVE}),
    # une tâche aussi (lire la file d'une app, ADR 0105 ; un brouillon) : ses lots sont ceux que la tâche choisit
    WORK: frozenset({Kind.STEP, Kind.WORK, Kind.JOB, Kind.WAKE, Kind.WAKE_JOB, Kind.TASK}),
}
#: ce qu'une ligne laisse faire d'un outil : seule, l'appel part aussitôt ; sur accord de la personne en face (une
#: carte dans son chat ; sans personne en face, l'opérateur) ; sur ton accord à toi (une carte dans ton chat quand
#: c'est toi en face, sinon la console) ; ou non : l'outil ne lui est pas offert
NO, ALONE, CARD, OWNER_OK = "non", "seule", "carte", "toi"
POLICIES = ((ALONE, "seule — sans demander"), (CARD, "demande à la personne en face"),
            (OWNER_OK, "demande ton accord"), (NO, "non"))
#: une ligne, en mots courts (la console) : ce qu'elle fait d'un outil, quand elle vaut, qui elle désigne
POLICY_WORDS = {ALONE: "seule", CARD: "demande à la personne", OWNER_OK: "ton accord", NO: "non"}
WHEN_WORDS = dict(MOMENTS)
SOURCE_WORDS = {OWNER: "toi", WORK: "elle quand elle travaille seule", CLOSE: "tes proches en privé",
                EVERYONE: "tout le monde", WHO_ACCOUNTS: "les comptes (ancien)"}

L = TypeVar("L")


@dataclass(frozen=True, slots=True)
class Verdict(Generic[L]):
    """La ligne qui décide, et sa place dans son tableau : à partir de 1 ; 0, la ligne par défaut."""

    line: L
    index: int

    @property
    def by_default(self) -> bool:
        return self.index == 0


def decide(lines: Iterable[L], default: L, matches: Callable[[L], bool]) -> Verdict[L]:
    """Le moteur : la première ligne qui correspond (``matches``), sinon la ligne par défaut, qui correspond toujours."""
    for i, line in enumerate(lines, start=1):
        if matches(line):
            return Verdict(line, i)
    return Verdict(default, 0)


def upgrade(who: str | Iterable[str], when: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Une ligne d'avant en sources et moments qui font la même chose : « toi » devient toi et elle qui travaille,
    selon ses moments, et le moment « travail » quitte « quand » ; une ligne qui ne valait qu'au travail pour qui n'y
    est jamais garde ce moment, qui ne correspond à rien."""
    when = tuple(dict.fromkeys(when or ()))
    talks = tuple(w for w in when if w != WORK)
    if isinstance(who, str):
        if who == WHO_OWNER:
            return ((OWNER,) if not when or talks else ()) + ((WORK,) if not when or WORK in when else ()), talks
        who = (who,) if who else ()
    sources = tuple(dict.fromkeys(w for w in who if w))
    if when and not talks and WORK not in sources:
        return sources, (WORK,)
    return sources, talks


def sources(who: Iterable[str]) -> tuple[str, ...]:
    """Les sources d'une ligne, vérifiées et sans doublon ; une source inconnue est refusée (``ValueError``)."""
    got = tuple(dict.fromkeys(str(w).strip() for w in who if str(w).strip()))
    bad = [w for w in got if not SOURCE.fullmatch(w)]
    if bad:
        raise ValueError(f"source inconnue : « {bad[0][:40]} »")
    if not got:
        raise ValueError("une ligne désigne au moins une source")
    return got


def checked(boxes: Mapping[str, bool], row: str) -> list[str]:
    """Ce qu'une ligne d'un tableau envoyé a coché (``<ligne>|<valeur>`` : ses sources, ses moments, ses outils)."""
    return [k.partition("|")[2] for k, on in boxes.items() if on and k.partition("|")[0] == row]


def in_order(who: Iterable[str]) -> tuple[str, ...]:
    """Des sources dans l'ordre où la console les montre : les siennes, puis les personnes par leur clé."""
    got = set(who)
    return (*(k for k, _ in SOURCES if k in got), *(k for k in (WHO_ACCOUNTS,) if k in got),
            *sorted(k for k in got if k.startswith(PERSON)))


def who_words(who: str | Iterable[str], name: Callable[[str], str]) -> str:
    """Qui une ligne désigne, en mots : ses sources, ses personnes par leur nom (``name`` : sa clé → son nom) ; la ligne
    par défaut."""
    who = ((who,) if who else ()) if isinstance(who, str) else tuple(who)
    if not who:
        return "Comportement par défaut"
    parts = [SOURCE_WORDS.get(w) or (name(w[len(PERSON):]) if w.startswith(PERSON) else w) for w in who]
    said = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " et " + parts[-1]
    return said[:1].upper() + said[1:]


def when_words(when: Iterable[str]) -> str:
    """Quand une ligne vaut, en mots : « toujours », ou ses moments."""
    words = [WHEN_WORDS.get(w, w) for w in when]
    if not words:
        return "toujours"
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " ou " + words[-1]


def situation(audience: Any) -> str | None:
    """Où elle est : avec sa propriétaire (``proprietaire``), avec une personne authentifiée en tête-à-tête
    (``compte``), quand elle travaille seule (``travail``), dans un salon (``salon``), avec une inconnue
    (``inconnue``) ; ``None`` sans personne."""
    if audience is None:
        return None
    if audience.trust == ChannelTrust.INTERNAL.value:
        return WORK
    if not audience.persons:
        return None
    if audience.public or audience.room:
        return ROOM
    if audience.owner:
        return OWNER
    return ACCOUNT if audience.trust == ChannelTrust.AUTHENTICATED.value else STRANGER


def can_approve(audience: Any) -> bool:
    """Quelqu'un en face qui peut accepter une carte : en tête-à-tête, sa propriétaire ou une personne authentifiée —
    jamais dans un salon, jamais personne."""
    if audience is None or not audience.persons or audience.public or audience.room:
        return False
    return bool(audience.owner) or audience.trust == ChannelTrust.AUTHENTICATED.value


def designates(who: str | Iterable[str], where: str, person: str, close: Callable[[str], bool] | None = None) -> bool:
    """Une ligne désigne-t-elle qui est en face ? Elle qui travaille, toi, tes proches (``close`` : cette personne
    est-elle proche ?), une personne par son nom — ces deux-là authentifiées, en privé —, tout le monde (sauf elle,
    seule au travail) ; la ligne par défaut (``who`` vide) : tout le monde."""
    who = ((who,) if who else ()) if isinstance(who, str) else tuple(who)
    if not who:
        return True
    if where == WORK:
        return WORK in who
    if EVERYONE in who:
        return True
    if where == OWNER:
        return OWNER in who
    if where != ACCOUNT:
        return False  # un salon, une inconnue : seulement « tout le monde »
    if WHO_ACCOUNTS in who:
        return True
    return bool(person) and (PERSON + person in who or (CLOSE in who and close is not None and bool(close(person))))


def moment(when: Iterable[str], kind: str) -> bool:
    """Une ligne vaut-elle dans cette sorte d'épisode ? Sans moment : toujours."""
    when = tuple(when)
    return not when or any(kind in KINDS_OF.get(w, frozenset()) for w in when)


def facing(audience: Any, kind: str, concerns: Callable[[Any], bool] | None = None, *,
           close: Callable[[str], bool] | None = None, acting: bool = True) -> Callable[[Any], bool] | None:
    """Ce qui fait correspondre une ligne à qui est en face, à ce moment : elle le désigne (``who`` ; ``close`` dit
    qui est proche), elle vaut à ce moment (``when``, sauf au travail) et le concerne (``concerns`` : un outil dans sa
    colonne). ``None`` sans personne ; pour agir (``acting``), jamais non plus dans un salon ni avec une inconnue,
    quelles que soient les lignes."""
    where = situation(audience)
    if where is None or (acting and where in (ROOM, STRANGER)):
        return None
    person = (audience.person or "") if where == ACCOUNT else ""

    def matches(line: Any) -> bool:
        if concerns is not None and not concerns(line):
            return False
        if not designates(getattr(line, "who", ()), where, person, close):
            return False
        return where == WORK or moment(getattr(line, "when", ()), kind)

    return matches


def verdict(lines: Iterable[L], default: L, audience: Any, kind: str, concerns: Callable[[L], bool] | None = None,
            *, close: Callable[[str], bool] | None = None, acting: bool = True) -> Verdict[L] | None:
    """La ligne qui décide pour qui est en face, à ce moment, et sa place ; ``None`` hors de toute situation."""
    matches = facing(audience, kind, concerns, close=close, acting=acting)
    return decide(lines, default, matches) if matches is not None else None


def first(lines: Iterable[L], default: L, audience: Any, kind: str, concerns: Callable[[L], bool] | None = None,
          *, close: Callable[[str], bool] | None = None, acting: bool = True) -> L | None:
    """La ligne qui décide pour qui est en face (``verdict``, sans sa place)."""
    got = verdict(lines, default, audience, kind, concerns, close=close, acting=acting)
    return got.line if got is not None else None


def families(who: Iterable[str], when: Iterable[str]) -> frozenset[str]:
    """Les familles d'épisodes (``KINDS_OF``) où une ligne peut valoir : ce qu'on offre au plus — qui l'a vraiment se
    décide devant chaque audience."""
    who, when = tuple(who), tuple(w for w in when if w != WORK)
    out: set[str] = set()
    if not who or WORK in who:
        out.add(WORK)
    if not who or any(w != WORK for w in who):
        out |= set(when) or {k for k, _ in MOMENTS}
    return frozenset(out)


def owner_here(frame: Any, bundle: str, tasks: Callable[[str], bool] | None = None) -> bool:
    """Ce que le code réserve à sa propriétaire (ADR 0133), le même plancher partout : toi, en privé — jamais dans un
    salon, même quand c'est toi qui y parles —, ou elle qui travaille pour toi ; un projet ou un réveil seulement s'il
    a pris ce lot (``bundle``), une tâche seulement si c'est l'une des siennes (``tasks``)."""
    ep = frame.episode
    if ep is None:
        return False
    if ep.kind in PROJECT_KINDS | WAKE_KINDS:
        args = ep.attrs.get("args") or {}
        return bundle in {b.strip() for b in str(args.get("bundles") or "").split(",")}
    if ep.kind == Kind.TASK:
        return tasks is not None and bool(tasks(ep.target or ""))
    if ep.kind in WORKING:
        return True
    return bool(ep.target) and situation(frame.audience) == OWNER
