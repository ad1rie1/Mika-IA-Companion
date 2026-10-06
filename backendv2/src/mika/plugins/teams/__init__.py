"""Le plugin ``teams`` (ADR 0069) : les conversations Teams de la personne qui s'occupe d'elle.

Rien ici ne parle à Microsoft. L'extension de navigateur (``frontend/Extension``), dans l'onglet Teams de cette
personne, pousse ce que le client reçoit (``POST /api/teams/inbox``) ; l'adaptateur le range hors du journal
(``teams.db``) ; ce plugin en fait ce qu'elle remarque et ce qu'elle y écrit.

- **Remarquer** : chaque message reçu (pas les siens) est trié — un rôle utilitaire, borné par passage ; à défaut,
  une heuristique : son importance, et s'il pose une question **à laquelle elle peut aider**. Il devient un signal
  (``teams.noticed``) que l'attention dose et habitue.
- **Préparer une réponse d'elle-même** (une tâche silencieuse, ``Kind.TASK``) : au dernier message d'une conversation
  qui pose une telle question, s'il est récent, si la personne n'y a pas déjà répondu et si on ne l'a pas exclue.
  Elle écrit **à la place** de la personne (le message part de son compte, sous son nom), avec le fil de la
  conversation et ses consignes — jamais avec sa mémoire, qui contient la vie de la personne et ce que d'autres lui
  ont confié.
- **Partir** (capacité ``teams.send``) selon le mode réglé : *brouillon* (posé dans la zone de saisie, la personne
  l'envoie ou pas — c'est son geste qui vaut accord), *validation* (sa carte d'accord, dans le chat et la console),
  *autonome* (sans accord). La capacité ne fait que **mettre en file** ; l'extension relève la file et accuse
  (``teams.settled``) : posé, parti (retouché ou non), pas servi, échoué. Parti, elle le sait (``teams.sent``).
- **Lire** (outils) : ses conversations, un fil — réservé à ses propriétaires **en privé**, ou à elle quand elle
  travaille.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import teams as c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.teams import MODES
from mika.vocab.episodes import PROJECT_KINDS, WAKE_KINDS, WORKING, Kind, task_of
from mika.vocab.people import clean_display_name

BUNDLE = "teams"
#: les messages remarqués qu'elle garde en tête (le texte, lui, est dans l'adaptateur)
KEEP = 200
DRAFTS_KEPT = 100
#: les états d'une réponse proposée
WAITING, APPROVED, REFUSED = "attend", "approuve", "refuse"
QUEUED, PLACED, GONE, UNUSED, FAILED = "en_file", "pose", "parti", "inutilise", "echec"
#: une réponse encore en chemin (une autre ne se prépare pas dans la même conversation)
UNDER_WAY = frozenset({WAITING, APPROVED, QUEUED, PLACED})
#: ce que l'adaptateur dit d'un brouillon en file → son état ici
FROM_PORT = {"pose": PLACED, "parti": GONE, "inutilise": UNUSED, "echec": FAILED}


class TeamsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    per_run: Annotated[int, Knob(
        label="Messages lus par passage", group="Remarquer", lo=1, hi=200,
        help="Au plus autant de messages reçus pris à chaque passage ; les autres attendent le suivant.")] = 40
    triage_per_run: Annotated[int, Knob(
        label="Messages triés par le modèle", group="Remarquer", lo=0, hi=50,
        help="Parmi eux, au plus autant (ceux qu'on adresse à la personne) sont triés par un appel au modèle "
             "(importance, question à laquelle elle peut aider) ; les autres par une simple heuristique.")] = 8
    shown_for_us: Annotated[int, Knob(
        label="Montrés pendant", group="Remarquer", lo=HOUR, hi=3 * DAY,
        help="Un message reçu reste sous ses yeux (« TES MESSAGES TEAMS ») au plus ce temps.")] = 12 * HOUR
    mode: Annotated[Literal["brouillon", "validation", "autonome"], Knob(
        label="Ce qu'elle fait de ses réponses", group="Écrire", choices=MODES, readonly=True,
        help="Réglé dans Configuration › Sens › Teams.")] = "brouillon"
    autodraft: Annotated[bool, Knob(
        label="Préparer des réponses d'elle-même", group="Brouillons", readonly=True,
        help="Réglé dans Configuration › Sens › Teams.")] = False
    skip: Annotated[tuple[str, ...], Knob(
        label="Jamais pour", group="Brouillons", readonly=True,
        help="Les conversations (un morceau de leur nom ou de leur identifiant) où elle ne prépare jamais de "
             "réponse d'elle-même (réglé dans Configuration › Sens › Teams).")] = ()
    drafts_per_day: Annotated[int, Knob(
        label="Réponses d'elle-même par jour", group="Brouillons", lo=0, hi=50,
        help="Au plus autant de réponses préparées d'elle-même en vingt-quatre heures (chacune coûte un appel au "
             "modèle) ; celles qu'un opérateur demande ne comptent pas.")] = 8
    draft_evidence: Annotated[float, Knob(
        label="Envie de préparer une réponse", group="Brouillons", lo=0.0, hi=12.0, step=0.5,
        help="La preuve (log-odds) qu'une question à laquelle elle peut aider apporte à la tâche d'y répondre, face "
             "au seuil des tâches (8).")] = 8.5
    asked_evidence: Annotated[float, Knob(
        label="Quand on le lui demande", group="Brouillons", lo=8.0, hi=14.0, step=0.5,
        help="La preuve d'une réponse qu'un opérateur lui demande de préparer (endormie, elle la fera au "
             "réveil).")] = 12.0
    draft_attempts_max: Annotated[int, Knob(
        label="Essais par message", group="Brouillons", lo=1, hi=5,
        help="Si une tâche ne donne pas de réponse, elle ne réessaie pas plus que ceci pour le même message.")] = 2
    draft_within_us: Annotated[int, Knob(
        label="Préparer dans les", group="Brouillons", lo=10 * MINUTE, hi=DAY,
        help="Passé ce délai après son arrivée, un message n'appelle plus de réponse préparée d'elle-même (une "
             "conversation Teams va vite).")] = 2 * HOUR
    approval_within_us: Annotated[int, Knob(
        label="Accord à donner dans les", group="Partir", lo=10 * MINUTE, hi=DAY,
        help="En mode « après ton accord » : passé ce délai, la carte ne vaut plus et la réponse ne part pas (elle "
             "le saura comme un refus).")] = 2 * HOUR
    queue_ttl_us: Annotated[int, Knob(
        label="En file pendant", group="Partir", lo=10 * MINUTE, hi=3 * DAY,
        help="Une réponse en file que l'extension n'a pas posée ou envoyée dans ce délai (Teams fermé), ou un "
             "brouillon posé que personne n'a envoyé, ne part plus.")] = 8 * HOUR


@dataclass(frozen=True, slots=True)
class Seen:
    """Un message reçu qu'elle a remarqué."""

    seq: int
    conversation: str
    title: str
    author: str
    author_id: str
    where: str
    importance: float
    needs_reply: bool
    mentions_me: bool
    at: int
    summary_ref: str
    #: qui y a répondu (« toi » : la personne elle-même ; « elle » : sa réponse est partie)
    answered: str = ""


@dataclass(frozen=True, slots=True)
class DraftSeen:
    """Une réponse qu'elle a proposée (``effect.proposed``) et ce qu'elle est devenue."""

    proposal: int
    draft: str
    conversation: str
    message: str
    at: int
    mode: str
    state: str = WAITING
    by: str = ""
    note: str = ""
    note_ref: str = ""
    result: str = ""
    decided_at: int = 0
    asked: bool = False
    edited: bool = False
    #: µs : la carte d'accord ne vaut plus (mode validation) ; 0 : pas d'accord attendu
    expires: int = 0
    #: µs : en file au-delà, elle ne part plus
    queued_until: int = 0


@dataclass(frozen=True, slots=True)
class AskSeen:
    """Un opérateur lui a demandé de préparer une réponse à ce message."""

    seq: int
    message: str
    conversation: str
    by: str
    at: int
    instruction_ref: str = ""


@dataclass(frozen=True, slots=True)
class TeamsState:
    messages: FrozenDict[str, Seen] = field(default_factory=FrozenDict)
    drafts: FrozenDict[int, DraftSeen] = field(default_factory=FrozenDict)
    asked: FrozenDict[str, AskSeen] = field(default_factory=FrozenDict)
    attempts: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: conversation → le dernier message qu'y a écrit la personne (µs)
    replied: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: le dernier lot reçu de l'extension (µs), et combien de lots en tout : le tri a de quoi lire
    received: int = 0
    receipts: int = 0


class Received(Payload):
    """L'extension a poussé des messages : combien de neufs, et les conversations où la personne a écrit (aucun
    texte : le monde reste dans l'adaptateur)."""

    new: int
    replied: tuple[str, ...] = ()


class Settled(Payload):
    """Ce qu'est devenue une réponse en file : posée dans Teams, partie (retouchée ou non), pas servie, échouée."""

    draft: str
    state: str
    edited: bool = False
    reason: str = ""


TEAMS = Faculty("teams", state=TeamsState, init=lambda p: TeamsState(), params=TeamsParams)
TEAMS.declare(*c.ALL)
TEAMS.bundle(BUNDLE, "les conversations Teams de la personne qui s'occupe de toi : les lister, relire un fil, "
                     "préparer une réponse à sa place")
RECEIVED = TEAMS.event("received", Received)
SETTLED = TEAMS.event("settled", Settled)


def params(p: TeamsParams | None) -> TeamsParams:
    return p if p is not None else TeamsParams()


def params_of(frame: Frame) -> TeamsParams:
    return params(frame.env.params_of("teams", frame.root))


def _pruned(items: FrozenDict[Any, Any], keep: int, key: Any) -> FrozenDict[Any, Any]:
    if len(items) <= keep:
        return items
    for k, _ in sorted(items.items(), key=key)[: len(items) - keep]:
        items = items.delete(k)
    return items


def draft_args(args_json: str) -> dict[str, Any]:
    try:
        data = json.loads(args_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# ── Réducteurs ────────────────────────────────────────────────────────────


@TEAMS.reducer(c.NOTICED)
def _noticed(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    at = d.sent_at or e.at
    seen = Seen(e.seq, d.conversation, d.title, d.author, d.author_id, d.where, d.importance, d.needs_reply,
                d.mentions_me, at, d.summary.ref or "",
                answered="toi" if s.replied.get(d.conversation, 0) >= at else "")
    return replace(s, messages=_pruned(s.messages.set(d.message, seen), KEEP, lambda kv: kv[1].seq))


@TEAMS.reducer(RECEIVED)
def _received(s: TeamsState, e, cx) -> TeamsState:
    """La personne a écrit dans ces conversations : ce qui y attendait une réponse en a une (la sienne)."""
    replied, messages = s.replied, s.messages
    for conv in e.data.replied:
        replied = replied.set(conv, e.at)
        for ref, m in messages.items():
            if m.conversation == conv and not m.answered:
                messages = messages.set(ref, replace(m, answered="toi"))
    if len(replied) > KEEP:
        replied = FrozenDict(sorted(replied.items(), key=lambda kv: -kv[1])[:KEEP])
    return replace(s, replied=replied, messages=messages, received=e.at, receipts=s.receipts + 1)


@TEAMS.reducer(c.DRAFT_ASKED)
def _asked(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    ask = AskSeen(e.seq, d.message, d.conversation, d.by, e.at,
                  d.instruction.ref or "" if d.instruction else "")
    return replace(s, asked=_pruned(s.asked.set(d.message, ask), KEEP, lambda kv: kv[1].seq),
                   attempts=s.attempts.delete(d.message))


@TEAMS.reducer(rt.EPISODE_STARTED)
def _episode(s: TeamsState, e, cx) -> TeamsState:
    """Une tâche de rédaction compte ses essais."""
    d = e.data
    found = task_of(d.target) if d.kind == Kind.TASK else None
    if found is None or found[0] != "teams":
        return s
    return replace(s, attempts=_pruned(s.attempts.set(found[1], s.attempts.get(found[1], 0) + 1), KEEP,
                                       lambda kv: kv[0]))


@TEAMS.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    if d.owner != c.OWNER or d.capability != c.SEND:
        return s
    args = draft_args(d.args_json)
    message = str(args.get("message") or "")
    seen = DraftSeen(e.seq, str(args.get("draft") or ""), str(args.get("conversation") or ""), message, e.at,
                     str(args.get("mode") or ""), WAITING if d.approval else APPROVED,
                     asked=bool(message) and message in s.asked, expires=int(args.get(rt.EXPIRES) or 0))
    drafts = _pruned(s.drafts.set(e.seq, seen), DRAFTS_KEPT, lambda kv: kv[0])
    return replace(s, drafts=drafts, asked=s.asked.delete(message) if message else s.asked)


@TEAMS.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    found = s.drafts.get(d.proposal)
    if found is None:
        return s
    decided = replace(found, state=APPROVED if d.approved else REFUSED, by=d.by, note=d.legacy_note[:300],
                      note_ref=d.note.ref or "" if d.note is not None else "", decided_at=e.at)
    return replace(s, drafts=s.drafts.set(d.proposal, decided))


@TEAMS.reducer(rt.EFFECT_EXECUTED)
def _executed(s: TeamsState, e, cx) -> TeamsState:
    """Mise en file (ou non) : c'est l'extension qui la posera ou l'enverra."""
    d = e.data
    found = s.drafts.get(d.proposal)
    if found is None:
        return s
    queued = replace(found, state=QUEUED if d.ok else FAILED, result=d.result[:300],
                     queued_until=e.at + params(cx.params).queue_ttl_us if d.ok else 0)
    return replace(s, drafts=s.drafts.set(d.proposal, queued))


@TEAMS.reducer(SETTLED)
def _settled(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    found = latest(s, d.draft)
    state = FROM_PORT.get(d.state)
    if found is None or state is None:
        return s
    s = replace(s, drafts=s.drafts.set(found.proposal, replace(found, state=state, edited=d.edited,
                                                               result=d.reason[:300] or found.result)))
    m = s.messages.get(found.message) if found.message else None
    if state == GONE and m is not None and m.answered != "toi":
        s = replace(s, messages=s.messages.set(found.message, replace(m, answered="elle")))
    return s


def latest(s: TeamsState, draft_id: str) -> DraftSeen | None:
    """La dernière proposition de ce brouillon."""
    found = [d for d in s.drafts.values() if d.draft == draft_id]
    return max(found, key=lambda d: d.proposal) if found else None


def under_way(s: TeamsState, conversation: str) -> bool:
    """Une réponse est déjà en chemin dans cette conversation (en attente d'accord, en file, posée)."""
    return any(d.conversation == conversation and d.state in UNDER_WAY for d in s.drafts.values())


# ── Pour qui ──────────────────────────────────────────────────────────────


def for_owner(frame: Frame) -> bool:
    """Ses conversations Teams : pour ses propriétaires **en privé**, et pour elle quand elle travaille (une
    tâche, un pas). Devant un salon, jamais."""
    ep = frame.episode
    if ep is None:
        return False
    if ep.kind in PROJECT_KINDS | WAKE_KINDS:
        args = ep.attrs.get("args") or {}
        return BUNDLE in {b.strip() for b in str(args.get("bundles") or "").split(",")}
    if ep.kind in WORKING or ep.kind == Kind.TASK:
        return True
    if not ep.target:
        return False
    audience = frame.audience
    if audience is None or audience.public or audience.room:
        return False
    return bool(audience.owner)


#: comment elle dit qui s'occupe d'elle quand elle ne sait pas son prénom (jamais « ton opérateur »)
KEEPER = "la personne qui s'occupe de toi"


def person_name(frame: Frame, handle: str) -> str:
    view = frame.get(identity_c.IDENTITY(handle)) if handle else None
    return clean_display_name(getattr(view, "name", "") or "")


def keeper_name(frame: Frame, handle: str) -> str:
    return person_name(frame, handle) or KEEPER


def keepers(frame: Frame) -> str:
    """Le prénom de ses propriétaires (« Adrien »), sinon « la personne qui s'occupe de toi »."""
    names = [n for n in dict.fromkeys(person_name(frame, o) for o in frame.get(identity_c.OWNERS)) if n]
    if not names:
        return KEEPER
    return names[0] if len(names) == 1 else " ou ".join(names[:3])


def decider(frame: Frame) -> str:
    """À qui va la carte d'accord (mode validation) : l'adresse d'une propriétaire qui parle en propriétaire — celle
    où elle est, sinon celle où l'on peut lui écrire absente, sinon la première. Vide : la console seulement."""
    here = set(frame.get(presence_c.PRESENT))
    for person in frame.get(identity_c.OWNERS):
        handles = [h for h in (frame.get(identity_c.HANDLES(person)) or (person,))
                   if frame.get(identity_c.SPEAKS_AS_OWNER(h))]
        for pick in ([h for h in handles if h in here],
                     [h for h in frame.get(identity_c.REACHABLE(person)) if h in handles], handles):
            if pick:
                return pick[0]
    return ""


def task_message(frame: Frame) -> str:
    """Le message d'une tâche de rédaction en cours (vide : ce n'en est pas une)."""
    ep = frame.episode
    found = task_of(ep.target) if ep is not None and ep.kind == Kind.TASK else None
    return found[1] if found is not None and found[0] == "teams" else ""


# les contributions : le tri, ses tâches, ses outils, sa voix, l'échéance, la console
from mika.plugins.teams import console as console  # noqa: E402
from mika.plugins.teams import expire as expire  # noqa: E402
from mika.plugins.teams import tasks as tasks  # noqa: E402
from mika.plugins.teams import tools as tools  # noqa: E402
from mika.plugins.teams import triage as triage  # noqa: E402
from mika.plugins.teams import voice as voice  # noqa: E402
