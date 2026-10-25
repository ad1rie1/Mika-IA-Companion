"""Qui peut quoi, en lignes lues de haut en bas comme les règles d'un pare-feu (ADR 0131, 0133, 0134) : le cadre
de toute règle, et le moteur qui les lit.

Une ligne dit **qui** est en face (toi, tes proches, une personne par son nom, tout le monde — pour un canal de
messagerie, une adresse ou un @domaine), **par où** ça arrive (un canal : le chat web, l'app Android, Teams, le
courrier, Internet, elle seule ; un type, ou une instance ``type:clé`` pour une exception ; rien : tous) et
**quand** (elle répond, elle prend la parole ; rien : toujours). Ce qu'elle accorde est à son propriétaire (un
service : ce qu'elle fait d'un outil, ce qu'elle en garde ; un projet : le voir, le piloter, ses fichiers, ses apps ;
un canal : des plafonds). Pour qui est en face, à un moment, la première ligne qui correspond décide ; aucune : la
ligne par défaut.

Le moteur est un seul (``decide``) ; ce qui correspond, c'est ``facing`` : la personne (``designates``), le canal
(``via``), le moment (``moment``). Une demande passe **deux portes** — le tableau du canal, puis celui de la
ressource — et la plus stricte gagne (``tighten``). Des **plafonds** dans le code, que la console montre en cases
grisées (``ceiling``) : une inconnue n'obtient au plus que des outils qui lisent, jamais une action ; à plusieurs, un
des siens qui lit au plus, rien venu d'ailleurs (``vocab.rights``), un projet en lecture seule au plus ; sans personne
en face hors du travail, rien.

Une valeur partagée, sans faculté : les lignes sont ce que chaque propriétaire range (``Rule`` et ses colonnes),
lues ici par leurs champs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mika.kernel.forms import Knob
from mika.vocab.episodes import PROJECT_KINDS, WAKE_KINDS, WORKING, Kind
from mika.vocab.privacy import ChannelTrust, normalize_channel

# ── qui ─────────────────────────────────────────────────────────────────────

#: les sources qu'une ligne coche (plusieurs à la fois) : toi ; tes proches (un lien « proche »), reconnus ; tout le
#: monde ; une personne par son nom (``personne:<clé>``), reconnue ; pour un canal de messagerie, une adresse ou un
#: @domaine (``adresse:<motif>``)
OWNER, CLOSE, EVERYONE, PERSON, ADDRESS = "proprietaire", "proches", "tous", "personne:", "adresse:"
SOURCES = ((OWNER, "Toi"), (CLOSE, "Tes proches"), (EVERYONE, "Tout le monde"))
SOURCE = re.compile(rf"(?:{OWNER}|{CLOSE}|{EVERYONE}|{PERSON}\S{{1,200}}|{ADDRESS}\S{{1,200}})")
SOURCE_WORDS = {OWNER: "toi", CLOSE: "tes proches", EVERYONE: "tout le monde"}

# ── par où ──────────────────────────────────────────────────────────────────

#: les canaux : un type, et pour une exception une instance ``type:clé`` (le chat web : en privé ou en salon ; Teams :
#: un compte ; le courrier : une boîte ; Internet : un réseau) ; « elle seule » : personne en face, elle travaille
WEB, MOBILE, TEAMS, MAIL, INTERNET, INTERNAL = "web", "mobile", "teams", "courrier", "internet", "interne"
CANALS = ((WEB, "Chat web"), (MOBILE, "App Android"), (TEAMS, "Teams"), (MAIL, "Courrier"),
          (INTERNET, "Internet"), (INTERNAL, "Elle seule"))
CANAL_WORDS = dict(CANALS)
#: « tous » : tous les canaux (ce que vaut aussi une ligne sans canal)
ANY = "tous"
CANAL = re.compile(rf"(?:{ANY}|(?:{WEB}|{MOBILE}|{TEAMS}|{MAIL}|{INTERNET}|{INTERNAL})(?::[a-z0-9_@.-]{{1,60}})?)")
#: les instances du chat web : en tête-à-tête, ou dans un salon
PRIVATE, TOGETHER = "prive", "salon"
#: les types de canal où elle parle en son nom à qui est en face (les autres, tes comptes : elle écrit à ta place)
TALKING = frozenset({WEB, MOBILE, INTERNET, INTERNAL})


@dataclass(frozen=True, slots=True)
class Canal:
    """Par où une audience arrive : son type, et son instance (``prive`` ou ``salon`` pour le chat web ; un
    réseau pour Internet ; vide sinon)."""

    type: str
    instance: str = ""

    @property
    def key(self) -> str:
        return f"{self.type}:{self.instance}" if self.instance else self.type

    @property
    def together(self) -> bool:
        return self.instance == TOGETHER


def canal_of(audience: Any, kind: str = "") -> Canal | None:
    """Le canal d'une audience : elle seule (rien n'écoute — ou une sorte d'épisode de travail sans personne), le chat
    web (en privé ou en salon), l'app Android, le courrier, Teams, ou Internet (tout autre moyen : son réseau pour
    instance) ; ``None`` sans audience."""
    if audience is None:
        return None
    if audience.trust == ChannelTrust.INTERNAL.value or (not audience.persons and kind in WORK_KINDS):
        return Canal(INTERNAL)
    name = normalize_channel(audience.channel)
    together = bool(audience.public or audience.room)
    if name == WEB:
        return Canal(WEB, TOGETHER if together else PRIVATE)
    if name == MOBILE:
        return Canal(MOBILE)
    if name == TEAMS:
        return Canal(TEAMS)
    if name == "email":
        return Canal(MAIL)
    return Canal(INTERNET, "" if name in ("", "external") else name)


def canal_key(value: str) -> tuple[str, str]:
    """(type, instance) d'un canal tel qu'une ligne le coche."""
    kind, _, instance = value.partition(":")
    return kind, instance


def via(canals: Iterable[str], canal: Canal | None) -> bool:
    """Une ligne vaut-elle par ce canal ? Sans canal (ou « tous ») : par tous ; sinon son type, ou son instance."""
    wanted = tuple(canals)
    if not wanted or ANY in wanted:
        return True
    return canal is not None and any(c == canal.type or c == canal.key for c in wanted)


def canal_words(canals: Iterable[str], name: Callable[[str, str], str] | None = None) -> str:
    """Par où une ligne vaut, en mots : « tous », ou ses canaux (``name(type, instance)`` nomme une instance)."""
    out = []
    for c in canals:
        kind, instance = canal_key(c)
        if c == ANY:
            return "tous"
        if not instance:
            out.append(CANAL_WORDS.get(kind, kind))
        elif kind == WEB:
            out.append(f"{CANAL_WORDS[WEB]} · {'en salon' if instance == TOGETHER else 'en privé'}")
        else:
            out.append(f"{CANAL_WORDS.get(kind, kind)} · {name(kind, instance) if name else instance}")
    if not out:
        return "tous"
    return out[0] if len(out) == 1 else ", ".join(out[:-1]) + " ou " + out[-1]


# ── quand ───────────────────────────────────────────────────────────────────

MOMENTS = (("conversation", "quand elle répond"), ("initiative", "quand elle prend la parole"))
WHEN_WORDS = dict(MOMENTS)
#: les sortes d'épisode où elle travaille seule : un pas, une exécution, un réveil, une tâche (la lecture de la file
#: d'une app, un brouillon)
WORK_KINDS = frozenset({Kind.STEP, Kind.WORK, Kind.JOB, Kind.WAKE, Kind.WAKE_JOB, Kind.TASK})
#: les sortes d'épisode de chaque famille : les deux moments, et le travail (elle seule, où les moments ne comptent
#: pas : ``families``)
KINDS_OF: Mapping[str, frozenset[str]] = {
    "conversation": frozenset({Kind.REPLY}),
    "initiative": frozenset({Kind.INITIATIVE}),
    "travail": WORK_KINDS,
}

# ── où elle est ─────────────────────────────────────────────────────────────

#: avec sa propriétaire ; avec une personne reconnue en tête-à-tête ; avec une inconnue ; dans un salon (à
#: plusieurs) ; elle seule, au travail
AT_OWNER, ACCOUNT, STRANGER, ROOM, WORK = "proprietaire", "compte", "inconnue", "salon", "travail"


def situation(audience: Any, kind: str = "") -> str | None:
    """Où elle est ; ``None`` sans personne en face hors du travail (une sorte d'épisode de travail sans personne :
    elle seule, quoi que dise l'audience)."""
    if audience is None:
        return None
    if audience.trust == ChannelTrust.INTERNAL.value:
        return WORK
    if not audience.persons:
        return WORK if kind in WORK_KINDS else None
    if audience.public or audience.room:
        return ROOM
    if audience.owner:
        return AT_OWNER
    return ACCOUNT if audience.trust == ChannelTrust.AUTHENTICATED.value else STRANGER


def can_approve(audience: Any) -> bool:
    """Quelqu'un en face qui peut accepter une carte : reconnu, en tête-à-tête — jamais dans un salon, jamais
    personne."""
    return situation(audience) in (AT_OWNER, ACCOUNT)


# ── ce qu'une ligne accorde, et les rangs ───────────────────────────────────

#: ce qu'une ligne laisse faire d'un outil : seule ; sur accord de la personne en face (une carte dans son chat) ; sur
#: ton accord (une carte dans ton chat quand c'est toi en face, sinon la console) ; non
NO, ALONE, CARD, OWNER_OK = "non", "seule", "carte", "toi"
POLICIES = ((ALONE, "seule — sans demander"), (CARD, "demande à la personne en face"),
            (OWNER_OK, "demande ton accord"), (NO, "non"))
POLICY_WORDS = {ALONE: "seule", CARD: "demande à la personne", OWNER_OK: "ton accord", NO: "non"}
POLICY_RANK = {NO: 0, OWNER_OK: 1, CARD: 2, ALONE: 3}
Policy = Literal["seule", "carte", "toi", "non"]

#: ce qu'elle garde de ce qu'un outil rend : un savoir, un souvenir personnel, une confidence, rien
KEEPS = (("public", "public — un savoir"), ("perso", "personnel — un souvenir"),
         ("prive", "privé — une confidence"), ("rien", "rien"))
KEEP_WORDS = {"public": "un savoir", "perso": "un souvenir", "prive": "une confidence", "rien": "rien"}
KEEP_RANK = {"rien": 0, "prive": 1, "perso": 2, "public": 3}
Keep = Literal["public", "perso", "prive", "rien"]

#: piloter un projet : en lecture seule (son détail, sans rien y changer) ; ses demandes sur l'accord du propriétaire ;
#: appliquées aussitôt (modification) ; aucun pilotage
STEER_READ, STEER_ASK, STEER_EDIT, STEER_NO = "lecture", "accord", "modification", "non"
STEERS = ((STEER_READ, "Lecture seule"), (STEER_ASK, "Accord du propriétaire"), (STEER_EDIT, "Modification"),
          (STEER_NO, "Aucun pilotage"))
STEER_WORDS = {STEER_READ: "lecture seule", STEER_ASK: "accord du propriétaire", STEER_EDIT: "modification",
               STEER_NO: "aucun pilotage"}
STEER_RANK = {STEER_NO: 0, STEER_READ: 1, STEER_ASK: 2, STEER_EDIT: 3}
#: ce qui laisse y changer quelque chose
CHANGES = frozenset({STEER_ASK, STEER_EDIT})
Steer = Literal["lecture", "accord", "modification", "non"]

#: comment ce qu'elle écrit part par un canal : seule ; sur ton accord ; en brouillon (sur tes comptes : posé, c'est
#: toi qui l'envoies) ; non
REPLIES = (("seule", "seule"), ("accord", "ton accord"), ("brouillon", "brouillon — c'est toi qui l'envoies"),
           ("non", "non"))
REPLY_WORDS = dict(REPLIES)
REPLY_RANK = {"non": 0, "brouillon": 1, "accord": 2, "seule": 3}
Reply = Literal["seule", "accord", "brouillon", "non"]


def tighten(a: str, b: str, rank: Mapping[str, int]) -> str:
    """La plus stricte de deux valeurs d'un même rang (ce que les deux portes laissent passer)."""
    return a if rank.get(a, 0) <= rank.get(b, 0) else b


# ── les plafonds ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Ceiling:
    """Ce que le code laisse au plus à qui est en face, quelles que soient les lignes ; ``why`` : sa raison, celle
    des cases grisées."""

    read: str = ALONE
    act: str = ALONE
    keep: str = "public"
    steer: str = STEER_EDIT
    files: bool = True
    reply: str = "seule"
    why: str = ""


OPEN = Ceiling()
CEILINGS: Mapping[str, Ceiling] = {
    AT_OWNER: OPEN, ACCOUNT: OPEN, WORK: OPEN,
    STRANGER: Ceiling(act=NO, keep="rien", steer=STEER_READ, files=False, why="rien ne prouve qui parle"),
    ROOM: Ceiling(act=NO, keep="rien", steer=STEER_READ, files=False, why="à plusieurs : des témoins"),
}


def ceiling(audience: Any, kind: str = "") -> Ceiling | None:
    """Le plafond de qui est en face ; ``None`` sans personne hors du travail (rien, jamais)."""
    where = situation(audience, kind)
    return CEILINGS.get(where) if where is not None else None


# ── les lignes ──────────────────────────────────────────────────────────────

_Moment = Literal["conversation", "initiative"]


def sources(who: Iterable[str]) -> tuple[str, ...]:
    """Les sources d'une ligne, vérifiées et sans doublon ; une source inconnue est refusée (``ValueError``)."""
    got = tuple(dict.fromkeys(str(w).strip() for w in who if str(w).strip()))
    bad = [w for w in got if not SOURCE.fullmatch(w)]
    if bad:
        raise ValueError(f"source inconnue : « {bad[0][:40]} »")
    return got


def canals(values: Iterable[str]) -> tuple[str, ...]:
    """Les canaux d'une ligne, vérifiés et sans doublon ; « tous » vaut rien ; un canal inconnu est refusé."""
    got = tuple(dict.fromkeys(str(c).strip() for c in values if str(c).strip()))
    bad = [c for c in got if not CANAL.fullmatch(c)]
    if bad:
        raise ValueError(f"canal inconnu : « {bad[0][:40]} »")
    return () if ANY in got else got


def moments(when: Iterable[str]) -> tuple[str, ...]:
    """Les moments d'une ligne ; tous : rien (toujours)."""
    got = tuple(dict.fromkeys(str(w).strip() for w in when if str(w).strip()))
    return () if {k for k, _ in MOMENTS} <= set(got) else got


class Rule(BaseModel):
    """Le cadre d'une ligne : qui, par où, quand. Ce qu'elle accorde est à chaque sorte de tableau."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    who: Annotated[tuple[str, ...], Knob(label="Qui", advanced=False)] = ()
    canal: Annotated[tuple[str, ...], Knob(label="Par où", advanced=False)] = ()
    when: Annotated[tuple[_Moment, ...], Knob(label="Quand", advanced=False)] = ()

    @field_validator("who")
    @classmethod
    def _who(cls, who: tuple[str, ...]) -> tuple[str, ...]:
        return sources(who)

    @field_validator("canal")
    @classmethod
    def _canal(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return canals(value)

    @field_validator("when", mode="before")
    @classmethod
    def _when(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = () if value == "toujours" else (value,)
        return moments(value or ())

    @property
    def alone(self) -> bool:
        """Une ligne d'elle seule : sans personne, par le seul canal « elle seule »."""
        return not self.who and self.canal == (INTERNAL,)


class ToolRule(Rule):
    """Une ligne d'accès à des outils (un service, une app sans projet, une famille de ses propres outils) : ce
    qu'elle fait d'un outil qui lit et d'un outil qui agit, ce qu'elle en garde, et ses outils (vide : tous)."""

    read: Annotated[Policy, Knob(label="Un outil qui lit", choices=POLICIES, advanced=False)] = NO
    act: Annotated[Policy, Knob(label="Un outil qui agit", choices=POLICIES, advanced=False)] = NO
    keep: Annotated[Keep, Knob(label="Ce qu'elle en garde", choices=KEEPS, advanced=False)] = "rien"
    tools: Annotated[tuple[str, ...], Knob(label="Ses outils", advanced=False)] = ()

    def concerns(self, tool: str) -> bool:
        return not self.tools or tool in self.tools

    def level(self, acts: bool) -> str:
        """Ce qu'elle fait d'un outil qui agit (``acts``) ou qui lit."""
        return self.act if acts else self.read


#: une ligne d'outils fermée (la ligne par défaut d'un tableau qu'on n'a pas réglé)
CLOSED_TOOLS = ToolRule()

R = TypeVar("R", bound=Rule)


class Table(BaseModel, Generic[R]):
    """Un tableau : ses lignes dans leur ordre, puis la ligne par défaut, obligatoire."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[R, ...] = ()
    default: R


# ── le moteur ───────────────────────────────────────────────────────────────

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


def designates(who: Iterable[str], where: str, person: str, close: Callable[[str], bool] | None = None) -> bool:
    """Une ligne désigne-t-elle qui est en face ? Sans personne (``who`` vide) : seulement elle seule, et la ligne
    par défaut ; toi ; tes proches (``close`` : cette personne est-elle proche ?) et une personne par son nom,
    reconnus ; tout le monde (qui est aussi le seul à désigner une inconnue, ou un salon — jamais elle seule)."""
    who = tuple(who)
    if where == WORK:
        return not who
    if not who:
        return True
    if EVERYONE in who:
        return True
    if where == AT_OWNER:
        return OWNER in who
    if where != ACCOUNT:
        return False
    return bool(person) and (PERSON + person in who or (CLOSE in who and close is not None and bool(close(person))))


def moment(when: Iterable[str], kind: str) -> bool:
    """Une ligne vaut-elle dans cette sorte d'épisode ? Sans moment : toujours (le travail, lui, n'a pas de moment)."""
    when = tuple(when)
    return not when or any(kind in KINDS_OF.get(w, frozenset()) for w in when if w in WHEN_WORDS)


def facing(audience: Any, kind: str, concerns: Callable[[Any], bool] | None = None, *,
           close: Callable[[str], bool] | None = None) -> Callable[[Any], bool] | None:
    """Ce qui fait correspondre une ligne à qui est en face, par où, à ce moment : elle le désigne (``who``), elle
    vaut par ce canal (``canal``), à ce moment (``when``, sauf au travail), et le concerne (``concerns`` : un outil
    dans sa colonne). ``None`` sans personne hors du travail. Les plafonds sont à part (``ceiling``)."""
    where = situation(audience, kind)
    if where is None:
        return None
    here = canal_of(audience, kind)
    person = (audience.person or "") if where == ACCOUNT else ""

    def matches(line: Any) -> bool:
        if concerns is not None and not concerns(line):
            return False
        if not designates(getattr(line, "who", ()), where, person, close):
            return False
        if not via(getattr(line, "canal", ()), here):
            return False
        return where == WORK or moment(getattr(line, "when", ()), kind)

    return matches


def verdict(lines: Iterable[L], default: L, audience: Any, kind: str, concerns: Callable[[L], bool] | None = None,
            *, close: Callable[[str], bool] | None = None) -> Verdict[L] | None:
    """La ligne qui décide pour qui est en face, à ce moment, et sa place ; ``None`` hors de toute situation."""
    matches = facing(audience, kind, concerns, close=close)
    return decide(lines, default, matches) if matches is not None else None


def first(lines: Iterable[L], default: L, audience: Any, kind: str, concerns: Callable[[L], bool] | None = None,
          *, close: Callable[[str], bool] | None = None) -> L | None:
    """La ligne qui décide pour qui est en face (``verdict``, sans sa place)."""
    got = verdict(lines, default, audience, kind, concerns, close=close)
    return got.line if got is not None else None


def families(rule: Any) -> frozenset[str]:
    """Les familles d'épisodes où une ligne peut valoir — ce qu'on offre au plus ; qui l'a vraiment se décide devant
    chaque audience. Elle seule (``WORK``) quand la ligne n'a personne ; les moments cochés (ou tous) sinon."""
    who, canal, when = tuple(getattr(rule, "who", ())), tuple(getattr(rule, "canal", ())), tuple(rule.when)
    out: set[str] = set()
    if not who and via(canal, Canal(INTERNAL)):
        out.add(WORK)
    if who or not canal or any(canal_key(c)[0] != INTERNAL for c in canal):
        out |= set(when) or {k for k, _ in MOMENTS}
    return frozenset(out)


# ── au travail : le lot ─────────────────────────────────────────────────────


def at_work_with(frame: Any, bundle: str, tasks: Callable[[str], bool] | None = None) -> bool | None:
    """Elle seule, avec ce lot ? Un projet ou un réveil seulement s'il a pris ce lot (``bundle``), une tâche seulement
    si c'est l'une des siennes (``tasks``), un pas ou un réveil sans lot déclaré : oui ; ``None`` quand quelqu'un est
    en face (ce n'est pas elle seule : les lignes décident)."""
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
    return None


# ── en mots ─────────────────────────────────────────────────────────────────


def checked(boxes: Mapping[str, bool], row: str) -> list[str]:
    """Ce qu'une ligne d'un tableau envoyé a coché (``<ligne>|<valeur>`` : ses sources, ses canaux, ses moments, ses
    outils)."""
    return [k.partition("|")[2] for k, on in boxes.items() if on and k.partition("|")[0] == row]


def in_order(who: Iterable[str]) -> tuple[str, ...]:
    """Des sources dans l'ordre où la console les montre : les siennes, puis les personnes et les adresses."""
    got = set(who)
    return (*(k for k, _ in SOURCES if k in got), *sorted(k for k in got if k.startswith(PERSON)),
            *sorted(k for k in got if k.startswith(ADDRESS)))


def who_words(who: str | Iterable[str], name: Callable[[str], str]) -> str:
    """Qui une ligne désigne, en mots : ses sources, ses personnes par leur nom (``name`` : sa clé → son nom), ses
    adresses ; personne (elle seule) ; la ligne par défaut."""
    who = ((who,) if who else ()) if isinstance(who, str) else tuple(who)
    if not who:
        return "—"
    parts = [SOURCE_WORDS.get(w) or (name(w[len(PERSON):]) if w.startswith(PERSON)
                                     else w[len(ADDRESS):] if w.startswith(ADDRESS) else w) for w in who]
    said = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " et " + parts[-1]
    return said[:1].upper() + said[1:]


def when_words(when: Iterable[str]) -> str:
    """Quand une ligne vaut, en mots : « toujours », ou ses moments."""
    words = [WHEN_WORDS.get(w, w) for w in when]
    if not words:
        return "toujours"
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " ou " + words[-1]


def why_words(index: int) -> str:
    """La ligne qui décide, en mots : « ligne 2 », ou le comportement par défaut (``index`` 0)."""
    return f"ligne {index}" if index else "comportement par défaut"


#: une ligne telle qu'un formulaire l'envoie : ses sources, canaux et moments cochés, et ses colonnes
FormRow = Mapping[str, Any]


def rows_sent(ligne: Mapping[str, str], boxes: Mapping[str, Mapping[str, bool]], fields: Mapping[str, Mapping[str, Any]],
              always: Mapping[str, bool] | None = None, every: Mapping[str, bool] | None = None,
              tools: bool = False) -> list[FormRow]:
    """Les lignes d'un tableau envoyé, dans leur ordre (``ligne.<n>``) : ce que chaque case à cocher
    (``boxes`` : « qui », « canal », « moments », « prend ») et chaque champ (``fields``) en disent, « toujours » et
    « tous » (les outils) à part. Refuse une ligne sans source lisible, sans moment, ou sans outil, par un
    ``ValueError`` qui nomme la ligne."""

    def number(key: str) -> int:
        return int(key) if key.isdigit() else 10**6

    always, every = always or {}, every or {}
    out: list[FormRow] = []
    for n, key in enumerate(sorted(ligne, key=number), start=1):
        try:
            who = in_order(sources(checked(boxes.get("qui", {}), key)))
            canal = canals(checked(boxes.get("canal", {}), key))
        except ValueError as exc:
            raise ValueError(f"Ligne {n} : {exc}.") from None
        if not who and canal != (INTERNAL,):
            raise ValueError(f"Ligne {n} : coche qui (ou le seul canal « elle seule »).")
        if who and canal == (INTERNAL,):
            raise ValueError(f"Ligne {n} : « elle seule » n'a personne en face — décoche qui, ou choisis un autre canal.")
        talks = canal != (INTERNAL,)
        when = () if always.get(key) or not talks else moments(m for m in checked(boxes.get("moments", {}), key)
                                                                  if m in WHEN_WORDS)
        if talks and not always.get(key) and not when:
            raise ValueError(f"Ligne {n} : coche au moins un moment, ou « toujours ».")
        picked = sorted(checked(boxes.get("prend", {}), key))
        if tools and not every.get(key) and not picked:
            raise ValueError(f"Ligne {n} : coche au moins un outil, ou « tous ».")
        row = {"who": who, "canal": canal, "when": when}
        if tools:
            row["tools"] = () if every.get(key) else tuple(picked)
        row.update({f: v.get(key) for f, v in fields.items()})
        out.append(row)
    return out


def moved(rows: list[Any], faire: str, new: Any, at_most: int = 40) -> tuple[list[Any], str]:
    """Ce qu'un bouton du tableau demande : ajouter une ligne (``new``, fermée, au-dessus de la ligne par défaut),
    monter, descendre ou retirer la ligne ``n`` ; et ce qu'on en dit."""
    op, _, at = faire.partition(":")
    i = int(at) - 1 if at.isdigit() else -1
    rows = list(rows)
    if op == "ajouter":
        if len(rows) >= at_most:
            raise ValueError(f"{at_most} lignes au plus.")
        rows.append(new)
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


#: un formulaire de tableau : ses champs communs (``Knob`` : la console les connaît) — chaque sorte de tableau
#: ajoute ses colonnes
class TableArgs(BaseModel):
    """Le tableau tel qu'une page l'envoie, d'un seul coup : une entrée par ligne (``ligne.<n>``, leur ordre), ses
    sources, canaux et moments cochés (``qui.<n>|<source>``, ``canal.<n>|<canal>``, ``moments.<n>|<moment>`` ou
    ``toujours.<n>``), ses outils (``prend.<n>|<outil>`` ou ``tous.<n>``), et ce qu'un bouton demande en plus
    d'enregistrer (``faire``)."""

    ligne: Annotated[dict[str, str], Knob(label="Ligne", advanced=False)] = Field(default_factory=dict)
    qui: Annotated[dict[str, bool], Knob(label="Qui", advanced=False)] = Field(default_factory=dict)
    canal: Annotated[dict[str, bool], Knob(label="Par où", advanced=False)] = Field(default_factory=dict)
    toujours: Annotated[dict[str, bool], Knob(label="Toujours", advanced=False)] = Field(default_factory=dict)
    moments: Annotated[dict[str, bool], Knob(label="Quand", advanced=False)] = Field(default_factory=dict)
    tous: Annotated[dict[str, bool], Knob(label="Tous ses outils", advanced=False)] = Field(default_factory=dict)
    prend: Annotated[dict[str, bool], Knob(label="Ses outils", advanced=False)] = Field(default_factory=dict)
    #: la valeur du bouton pressé (un champ ordinaire : un champ caché ne se lit que dans les valeurs fixées)
    faire: Annotated[str, Knob(label="Et", help="ajouter, monter:n, descendre:n ou retirer:n ; vide : enregistrer")] = \
        Field("", max_length=40)

    def rows(self, tools: bool = False, **fields: Mapping[str, Any]) -> list[FormRow]:
        """Ses lignes (``rows_sent``), avec les colonnes propres à la sorte de tableau (``fields``) ; ``tools`` : le
        tableau a une colonne d'outils."""
        boxes = {"qui": self.qui, "canal": self.canal, "moments": self.moments, "prend": self.prend}
        return rows_sent(self.ligne, boxes, fields, self.toujours, self.tous, tools=tools)
