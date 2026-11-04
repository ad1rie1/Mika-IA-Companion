"""Le plugin ``teams`` (ADR 0069, 0186) : les conversations Teams de chaque compte — le tien, le sien, celui d'une
personne qui a un compte.

Rien ici ne parle à Microsoft. L'extension de navigateur (``frontend/Extension``), dans l'onglet Teams de la personne
d'un compte, pousse ce que le client reçoit (``POST /api/teams/inbox``, avec la clé de ce compte) ; l'adaptateur le
range hors du journal (``teams.db``), sous ce compte ; ce plugin en fait ce qu'elle remarque et ce qu'elle y écrit.

- **Un compte sert à son propriétaire** (ADR 0186, comme une boîte aux lettres : ADR 0185) : les tiens là où sa
  famille d'outils le permet, les siens quand elle travaille, celui d'une personne avec elle seulement — reconnue, en
  tête-à-tête (``accounts_here``) ; ses outils et ce qu'elle en voit sont réduits à ces comptes. Elle remarque les
  messages de tous ; elle ne prépare d'elle-même une réponse que dans les tiens et les siens. Une réponse part du
  compte de la conversation, sous le nom de sa personne.

- **Remarquer** : chaque message reçu (pas les siens) est trié — un rôle utilitaire, borné par passage ; à défaut,
  une heuristique : son importance, et s'il pose une question **à laquelle elle peut aider**. Il devient un signal
  (``teams.noticed``) que l'attention dose et habitue.
- **Préparer une réponse d'elle-même** (une tâche silencieuse, ``Kind.TASK``) : au dernier message d'une conversation
  qui pose une telle question, s'il est récent, si la personne n'y a pas déjà répondu et si la ligne de Teams le veut
  (le tableau de son canal, Réglages › Canaux, ``vocab.canals``, ADR 0132, 0134).
  Elle écrit **à la place** de la personne (le message part de son compte, sous son nom), avec le fil de la
  conversation et ses consignes — jamais avec sa mémoire, qui contient la vie de la personne et ce que d'autres lui
  ont confié.
- **Partir** (capacité ``teams.send``) selon la règle d'envoi de la conversation : *brouillon* (posé dans la zone de
  saisie, la personne l'envoie ou pas — c'est son geste qui vaut accord), *ton accord* (sa carte, dans le chat et la
  console), *seule* (sans accord). La capacité ne fait que **mettre en file** ; l'extension relève la file et accuse
  (``teams.settled``) : posé, parti (retouché ou non), pas servi, échoué. Parti, elle le sait (``teams.sent``).
- **Lire** (outils) : ses conversations, un fil — réservé à ses propriétaires **en privé**, ou à elle quand elle
  travaille.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import teams as c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.teams import DEFAULT_ACCOUNT, conversation_key
from mika.vocab.access import (
    ACCOUNT,
    AT_OWNER,
    PERSON,
    SELF,
    SHARE_PREPARE,
    SHARE_READ,
    SHARE_USE,
    WORK,
    reaches,
    situation,
)
from mika.vocab.canals import Canals, teams_rule
from mika.vocab.episodes import Kind, task_of
from mika.vocab.people import clean_display_name
from mika.vocab.phrasebook import phrase
from mika.vocab.rights import here_allowed

BUNDLE = "teams"
#: les messages remarqués qu'elle garde en tête (le texte, lui, est dans l'adaptateur)
KEEP = 200
DRAFTS_KEPT = 100
#: les états d'une réponse proposée
WAITING, APPROVED, REFUSED, EXPIRED = "attend", "approuve", "refuse", "expire"
QUEUED, PLACED, GONE, UNUSED, FAILED = "en_file", "pose", "parti", "inutilise", "echec"
#: une réponse encore en chemin (une autre ne se prépare pas dans la même conversation)
UNDER_WAY = frozenset({WAITING, APPROVED, QUEUED, PLACED})
#: ce que l'adaptateur dit d'un brouillon en file → son état ici
FROM_PORT = {"pose": PLACED, "parti": GONE, "inutilise": UNUSED, "echec": FAILED}
#: qui refuse au nom du délai (une carte d'accord restée sans réponse)
EXPIRER = "teams.delai"


class TeamsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    per_run: Annotated[int, Knob(
        label="Messages lus par passage", group="Remarquer", lo=1, hi=200,
        help="Au plus autant de messages reçus pris à chaque passage ; les autres attendent le suivant.")] = 40
    triage_per_run: Annotated[int, Knob(
        label="Messages triés par le modèle", group="Remarquer", lo=0, hi=50,
        help="Parmi eux, au plus autant (ceux qu'on adresse à la personne) sont triés par un appel au modèle "
             "(importance, question à laquelle elle peut aider, ce que le message lui fait) ; les autres par une "
             "simple heuristique, qui ne lui fait rien ressentir.")] = 8
    shown_for_us: Annotated[int, Knob(
        label="Montrés pendant", group="Remarquer", lo=HOUR, hi=3 * DAY,
        help="Un message reçu reste sous ses yeux (« TES MESSAGES TEAMS ») au plus ce temps.")] = 12 * HOUR
    enabled: Annotated[bool, Knob(
        label="Teams actif", group="Écrire", readonly=True,
        help="Réglé dans Réglages › Plugins › Teams : désactivé, elle ne prépare ni ne propose plus rien.")] = True
    canaux: Annotated[Canals, Knob(
        label="Les tableaux de ses canaux", group="Écrire", readonly=True,
        help="Réglés dans Réglages › Canaux (ADR 0134) : le tableau de Teams, lu de haut en bas — qui écrit, préparer "
             "d'elle-même, comment ça part — puis sa ligne par défaut.")] = Canals()
    owners: Annotated[dict[str, str], Knob(
        label="À qui sont ses comptes Teams", group="Écrire", readonly=True,
        help="Réglé dans Réglages › Plugins › Teams (« À qui », ADR 0186) : un compte sert à son propriétaire — elle "
             "(« elle »), une personne (« personne:<clé> ») ; absent ou vide, à toi.")] = Field(default_factory=dict)
    shares: Annotated[dict[str, dict[str, str]], Knob(
        label="Avec qui ses comptes Teams sont partagés", group="Écrire", readonly=True,
        help="Réglé par le propriétaire d'un compte (Paramètres › Partages, ADR 0188) : par compte, chaque personne "
             "(« personne:<clé> ») et ce qu'elle en a — lire, lire et préparer, s'en servir.")] = \
        Field(default_factory=dict)
    accounts_off: Annotated[tuple[str, ...], Knob(
        label="Comptes Teams décochés", group="Écrire", readonly=True,
        help="Réglés dans Réglages › Plugins › Teams (« Actif ») : elle n'y prépare ni n'y propose plus rien.")] = ()
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
    #: ce que sa règle d'envoi en disait au tri (ADR 0132) : préparer d'elle-même, comment une réponse partirait
    prepare: bool = True
    send: str = ""
    #: le compte qui l'a reçu (ADR 0186)
    account: str = DEFAULT_ACCOUNT


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
    #: recopiés de la proposition : refuser au nom du délai sans relire l'état du moteur
    args_json: str = ""
    context: str = ""
    #: le compte d'où elle part (celui de la conversation)
    account: str = DEFAULT_ACCOUNT


@dataclass(frozen=True, slots=True)
class AskSeen:
    """Un opérateur lui a demandé de préparer une réponse à ce message."""

    seq: int
    message: str
    conversation: str
    by: str
    at: int
    instruction_ref: str = ""
    account: str = DEFAULT_ACCOUNT


@dataclass(frozen=True, slots=True)
class TeamsState:
    messages: FrozenDict[str, Seen] = field(default_factory=FrozenDict)
    drafts: FrozenDict[int, DraftSeen] = field(default_factory=FrozenDict)
    asked: FrozenDict[str, AskSeen] = field(default_factory=FrozenDict)
    attempts: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: conversation (``conversation_key`` : son compte et son identifiant) → le dernier message qu'y a écrit la
    #: personne du compte (µs)
    replied: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: le dernier lot reçu de l'extension (µs), et combien de lots en tout : le tri a de quoi lire
    received: int = 0
    receipts: int = 0


class Received(Payload):
    """L'extension d'un compte a poussé des messages : combien de neufs, et les conversations où la personne du
    compte a écrit, avec l'heure (Teams, µs) de son dernier message dans chacune (aucun texte : le monde reste dans
    l'adaptateur)."""

    new: int
    replied: tuple[tuple[str, int], ...] = ()
    account: str = DEFAULT_ACCOUNT


class Settled(Payload):
    """Ce qu'est devenue une réponse en file : posée dans Teams, partie (retouchée ou non), pas servie, échouée."""

    draft: str
    state: str
    edited: bool = False
    reason: str = ""


#: v2 : un message remarqué garde ce que sa règle d'envoi en disait (``Seen.prepare``, ``send``) ; v3 : chaque message,
#: réponse et demande garde son compte (ADR 0186)
TEAMS = Faculty("teams", state=TeamsState, init=lambda p: TeamsState(), params=TeamsParams, state_version=3)
TEAMS.declare(*c.ALL)
TEAMS.bundle(BUNDLE, "les conversations Teams de ses comptes (le tien, le sien, celui d'une personne) : les lister, "
                     "relire un fil, préparer une réponse à la place de la personne du compte")
RECEIVED = TEAMS.event("received", Received)
SETTLED = TEAMS.event("settled", Settled)


def params(p: TeamsParams | None) -> TeamsParams:
    return p if p is not None else TeamsParams()


#: ce qu'une règle d'envoi fait d'une réponse Teams : son mode (posée dans la zone de saisie, après ton accord, seule)
MODE_OF = {"brouillon": "brouillon", "accord": "validation", "seule": "autonome"}


def mode_of(p: TeamsParams, s: TeamsState, ref: str, conversation: str, account: str = DEFAULT_ACCOUNT) -> str:
    """Le mode d'une réponse à ce message, là où le nom de sa conversation n'est pas connu (le brief d'une tâche, sa
    voix) : ce que sa règle en disait au tri (un message qu'elle n'a pas en tête : la règle de son compte, de son
    identifiant et de qui écrit, ADR 0132). Ce qui part relit la règle d'aujourd'hui (``triage.rule_of``)."""
    seen = s.messages.get(ref)
    send = seen.send if seen is not None and seen.send else teams_rule(
        p.canaux, seen.account if seen is not None else account, conversation,
        seen.author if seen is not None else "").reply
    return MODE_OF.get(send, "validation")


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
    seen = Seen(e.seq, d.conversation, d.author, d.author_id, d.where, d.importance, d.needs_reply,
                d.mentions_me, at, d.summary.ref or "",
                answered="toi" if s.replied.get(conversation_key(d.account, d.conversation), 0) >= at else "",
                prepare=d.prepare, send=d.send, account=d.account)
    return replace(s, messages=_pruned(s.messages.set(d.message, seen), KEEP, lambda kv: kv[1].seq))


@TEAMS.reducer(RECEIVED)
def _received(s: TeamsState, e, cx) -> TeamsState:
    """La personne du compte a écrit dans ces conversations : ce qui y attendait une réponse **avant son message** en
    a une (la sienne). Les heures sont celles de Teams, comme celles des messages : un vieux message à elle qui
    arrive tard (un rattrapage) ne répond pas à une question posée après. Un autre compte dans la même conversation
    n'y a pas répondu, lui."""
    replied, messages, account = s.replied, s.messages, e.data.account
    for conv, at in e.data.replied:
        key = conversation_key(account, conv)
        replied = replied.set(key, max(replied.get(key, 0), at))
        for ref, m in messages.items():
            if m.account == account and m.conversation == conv and not m.answered and m.at <= at:
                messages = messages.set(ref, replace(m, answered="toi"))
    if len(replied) > KEEP:
        replied = FrozenDict(sorted(replied.items(), key=lambda kv: -kv[1])[:KEEP])
    return replace(s, replied=replied, messages=messages, received=e.at, receipts=s.receipts + 1)


@TEAMS.reducer(c.DRAFT_ASKED)
def _asked(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    ask = AskSeen(e.seq, d.message, d.conversation, d.by, e.at,
                  d.instruction.ref or "" if d.instruction else "", account=d.account)
    return replace(s, asked=_pruned(s.asked.set(d.message, ask), KEEP, lambda kv: kv[1].seq),
                   attempts=s.attempts.delete(d.message))


@TEAMS.reducer(rt.EPISODE_STARTED)
def _episode(s: TeamsState, e, cx) -> TeamsState:
    """Une tâche de rédaction compte ses essais."""
    d = e.data
    found = task_of(d.target) if d.kind == Kind.TASK else None
    if found is None or found[0] != "teams":
        return s
    attempts = s.attempts.set(found[1], s.attempts.get(found[1], 0) + 1)
    if len(attempts) > KEEP:  # on oublie les essais des messages qu'elle ne garde plus en tête (les plus anciens)
        attempts = FrozenDict({k: n for k, n in attempts.items() if k in s.messages or k in s.asked})
    return replace(s, attempts=attempts)


@TEAMS.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    if d.owner != c.OWNER or d.capability != c.SEND:
        return s
    args = draft_args(d.args_json)
    message = str(args.get("message") or "")
    try:
        expires = int(args.get(rt.EXPIRES) or 0)
    except (TypeError, ValueError):
        expires = 0
    seen = DraftSeen(e.seq, str(args.get("draft") or ""), str(args.get("conversation") or ""), message, e.at,
                     str(args.get("mode") or ""), WAITING if d.approval else APPROVED,
                     asked=bool(message) and message in s.asked, expires=expires,
                     args_json=d.args_json if d.approval else "", context=d.context,
                     account=str(args.get("account") or DEFAULT_ACCOUNT))
    drafts = _pruned(s.drafts.set(e.seq, seen), DRAFTS_KEPT, lambda kv: kv[0])
    return replace(s, drafts=drafts, asked=s.asked.delete(message) if message else s.asked)


@TEAMS.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: TeamsState, e, cx) -> TeamsState:
    d = e.data
    found = s.drafts.get(d.proposal)
    if found is None:
        return s
    state = APPROVED if d.approved else EXPIRED if d.by == EXPIRER else REFUSED
    decided = replace(found, state=state, by=d.by, note=d.legacy_note[:300],
                      note_ref=d.note.ref or "" if d.note is not None else "", decided_at=e.at)
    return replace(s, drafts=s.drafts.set(d.proposal, decided))


@TEAMS.reducer(rt.EFFECT_EXECUTED)
def _executed(s: TeamsState, e, cx) -> TeamsState:
    """Mise en file (ou non) : c'est l'extension qui la posera ou l'enverra."""
    d = e.data
    found = s.drafts.get(d.proposal)
    if found is None or found.state not in (WAITING, APPROVED):
        return s  # l'extension a déjà accusé (posée, partie) : ce qui a été journalisé après ne recule pas
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


def under_way(s: TeamsState, account: str, conversation: str) -> bool:
    """Une réponse est déjà en chemin dans cette conversation de ce compte (en attente d'accord, en file, posée)."""
    return any(d.account == account and d.conversation == conversation and d.state in UNDER_WAY
               for d in s.drafts.values())


def drafted(s: TeamsState, message: str) -> bool:
    """Une réponse à ce message a déjà été proposée (quel qu'en soit le sort : refusée, partie, laissée) : elle ne la
    repropose pas d'elle-même — seule une demande la relance."""
    return any(d.message == message for d in s.drafts.values())


# ── Pour qui ──────────────────────────────────────────────────────────────


def for_owner(frame: Frame) -> bool:
    """Tes conversations Teams : ce que ses droits en laissent (``vocab.rights.here_allowed``, ADR 0133, 0134 : le
    minimum vital de sa famille la réserve à sa propriétaire, une ligne peut l'ouvrir) — toi en privé, jamais devant
    un salon ; elle qui travaille, un projet ou un réveil seulement s'il a pris ce lot ; ses tâches à elle (une
    réponse à préparer)."""
    return here_allowed(frame, BUNDLE, tasks=lambda target: (task_of(target) or ("", ""))[0] == TEAMS.name)


def owner_of(frame: Frame, account: str) -> str:
    """À qui est un compte Teams (ADR 0186) : vide, ses propriétaires (toi) ; ``elle`` ; ``personne:<clé>``."""
    return params_of(frame).owners.get(account, "")


def _facing(audience: Any, kind: str) -> str:
    """Qui est en face, comme propriétaire possible d'un compte : ``personne:<clé>`` d'une personne reconnue en
    tête-à-tête ; vide sinon (toi, elle seule, un salon, une inconnue)."""
    person = getattr(audience, "person", "") or ""
    return PERSON + person if person and situation(audience, kind) == ACCOUNT else ""


def _shared_with(audience: Any, kind: str) -> str:
    """Qui est en face, comme personne à qui l'on partage un compte (ADR 0188) : une personne reconnue en tête-à-tête —
    une de ses propriétaires aussi ; vide sinon."""
    person = getattr(audience, "person", "") or ""
    return PERSON + person if person and situation(audience, kind) in (ACCOUNT, AT_OWNER) else ""


def task_account(frame: Frame, port: Any) -> str:
    """Le compte du message d'une tâche de rédaction en cours (vide : ce n'en est pas une, ou il n'est plus là)."""
    ref = task_message(frame)
    found = port.message(ref) if ref and port is not None else None
    return found.account if found is not None else ""


def accounts_here(frame: Frame, accounts: Iterable[str], port: Any = None, need: str = SHARE_USE) -> tuple[str, ...]:
    """Les comptes Teams dont elle peut se servir ici (ADR 0186) : un compte sert à son propriétaire.

    - les tiens (sans propriétaire nommé) : là où sa famille d'outils le permet (``for_owner``) — toi en privé,
      elle quand elle travaille, et qui une ligne de la famille ouvre ;
    - les siens : quand elle travaille, là où sa famille le permet ;
    - celui d'une personne : avec elle, reconnue, en tête-à-tête — et nulle part ailleurs ;
    - ceux qu'on lui partage (ADR 0188) : avec elle, reconnue, en tête-à-tête, si son partage atteint ce que l'outil
      demande (``need`` : lire, préparer, s'en servir — par défaut, s'en servir) ;
    - une tâche de rédaction : le compte de son message (``port`` le dit ; on la lui a demandée, ou elle l'a
      proposée dans un compte à toi ou à elle)."""
    kind = frame.episode.kind if frame.episode is not None else ""
    p = params_of(frame)
    owners, shares, family = p.owners, p.shares, for_owner(frame)
    alone = situation(frame.audience, kind) == WORK
    person, shared = _facing(frame.audience, kind), _shared_with(frame.audience, kind)
    task = task_account(frame, port) if alone and family else ""
    out = []
    for a in accounts:
        owner = owners.get(a, "")
        if (not owner and family) or (owner == SELF and alone and family) or (person and owner == person) \
                or (shared and reaches(shares.get(a, {}).get(shared, ""), need)) or (task and a == task):
            out.append(a)
    return tuple(out)


def owns_an_account(audience: Any, kind: str, frame: Frame | None, need: str = SHARE_READ) -> bool:
    """Qui est en face a un compte Teams à son nom, ou qu'on lui partage à ce niveau (``ToolSpec.owned``, ADR 0186,
    0188) : ses outils Teams lui sont offerts, réduits à ces comptes — un outil qui lit dès « lire », celui qui
    prépare dès « lire et préparer » ; sans ce qu'elle vit (une console qui juge sans lui), personne."""
    if frame is None:
        return False
    p = params_of(frame)
    person = _facing(audience, kind)
    if person and person in p.owners.values():
        return True
    shared = _shared_with(audience, kind)
    return bool(shared) and any(reaches(given.get(shared, ""), need) for given in p.shares.values())


def owns_an_account_to_prepare(audience: Any, kind: str, frame: Frame | None) -> bool:
    """``owns_an_account`` pour un outil qui prépare une réponse : un compte à elle, ou partagé pour préparer."""
    return owns_an_account(audience, kind, frame, SHARE_PREPARE)


def owner_must_approve(frame: Frame, account: str, asked_by: str = "") -> bool:
    """Ce qu'elle prépare dans ce compte attend l'accord de son propriétaire, quoi que dise la règle du compte
    (ADR 0188) : la personne pour qui elle l'écrit — en tête-à-tête, ou qui lui a demandé cette réponse
    (``asked_by``, une tâche) — n'atteint le compte que par un partage qui ne s'en sert pas (« lire et préparer »)."""
    p = params_of(frame)
    kind = frame.episode.kind if frame.episode is not None else ""
    person = _shared_with(frame.audience, kind)
    if not person and asked_by:
        person = PERSON + str(frame.get(identity_c.PERSON(asked_by)) or asked_by)
    owner = p.owners.get(account, "")
    if not person or owner == person or (not owner and person.removeprefix(PERSON) in set(
            frame.get(identity_c.OWNERS) or ())):
        return False  # son compte, ou un compte « à toi » quand elle est une de ses propriétaires
    level = p.shares.get(account, {}).get(person, "")
    return bool(level) and not reaches(level, SHARE_USE)


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


def writer_of(frame: Frame, account: str) -> str:
    """À la place de qui elle écrit dans ce compte : le prénom de ses propriétaires (« Adrien », un compte à toi ; sinon
    « la personne qui s'occupe de toi »), le sien (un compte à elle), celui de la personne du compte (sinon « la
    personne à qui est ce compte Teams »)."""
    owner = owner_of(frame, account)
    if owner == SELF:
        return her(frame) or phrase("teams.holder")
    if owner.startswith(PERSON):
        return person_name(frame, owner[len(PERSON):]) or phrase("teams.holder")
    return keepers(frame)


def decider(frame: Frame, account: str = DEFAULT_ACCOUNT) -> str:
    """À qui va la carte d'accord (mode validation) : pour le compte d'une personne, à elle (le message part sous son
    nom) — une de ses adresses présente, sinon une où l'on peut lui écrire, sinon la première ; pour les autres, une
    adresse qui parle en propriétaire — d'abord celle d'une propriétaire présente (n'importe laquelle), sinon une où
    l'on peut écrire absente, sinon la première. Vide : la console seulement."""
    here = set(frame.get(presence_c.PRESENT))
    owner = owner_of(frame, account)
    if owner.startswith(PERSON):
        person = owner[len(PERSON):]
        handles = list(frame.get(identity_c.HANDLES(person)) or (person,))
        reachable = set(frame.get(identity_c.REACHABLE(person)))
        return next((h for h in handles if h in here), None) or next((h for h in handles if h in reachable), None) \
            or (handles[0] if handles else "")
    owners = [(person, [h for h in (frame.get(identity_c.HANDLES(person)) or (person,))
                        if frame.get(identity_c.SPEAKS_AS_OWNER(h))]) for person in frame.get(identity_c.OWNERS)]
    for _, handles in owners:
        if found := [h for h in handles if h in here]:
            return found[0]
    for person, handles in owners:
        if found := [h for h in frame.get(identity_c.REACHABLE(person)) if h in handles]:
            return found[0]
    return next((handles[0] for _, handles in owners if handles), "")


def her(frame: Frame) -> str:
    """Son nom (celui de sa persona) : la signature peut le citer."""
    return self_c.name_of(frame.get(self_c.PERSONA))


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
