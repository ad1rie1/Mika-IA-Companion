"""La faculté interne du runtime : épisodes ouverts, questions en attente,
effets en attente d'approbation. Sert à la reprise après un arrêt brutal.

**Le tour de conversation.** Les messages d'une même adresse en un même lieu
(son fil privé, ou un salon) qui attendent encore une réponse forment son
*tour* (``TURN((adresse, salon))``). Une réponse règle le tour entier
(``Utterance.answers``) : une rafale de trois messages reçoit une seule
réponse, qui les a tous lus. Une fin sans parole (elle se tait, la réponse
échoue, il est trop tard) dit quels messages restent sans réponse pour de bon
(``EpisodeEnded.unanswered``) — une intention journalisée, jamais un état
recalculé au rejeu.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from mika.contracts import runtime as rt
from mika.kernel.events import Draft
from mika.kernel.faculty import CAPABILITY_LANE, Faculty
from mika.kernel.state import FrozenDict
from mika.ports.delivery import REPLY_ABSTAINED, REPLY_FAILED, Delivery, EmotionView
from mika.runtime.boundary import Failed, acall
from mika.runtime.effects import STOPPED
from mika.vocab import voice

REPLY = "REPLY"
MAX_REPLY_ATTEMPTS = 2
#: Issues qui ne règlent pas la question : elle reste en attente (dans la
#: limite des tentatives). Un arrêt, une panne, une supplantation ou une
#: préemption ne sont pas des réponses.
UNSETTLED = frozenset({"interrupted", "cancelled", "superseded", "preempted"})
#: Celles qui appellent une reprise immédiate (le processus tourne encore).
RETRY_NOW = frozenset({"superseded", "preempted"})
RESULT_MAX = 4000
#: Une capacité (une commande réseau, un envoi) a tant de temps pour aboutir ; au-delà elle est coupée.
CAPABILITY_DEADLINE_S = 900.0
#: Ce qu'on dit d'une capacité interrompue par un arrêt brutal et qu'on ne relance pas seule.
INTERRUPTED = ("interrompue par un arrêt pendant son exécution : pas relancée automatiquement (elle n'est pas "
               "rejouable sans risque) — à relancer si besoin")


@dataclass(frozen=True, slots=True)
class OpenEpisode:
    kind: str
    started_at: int
    target: str | None = None
    reply_to: int | None = None


@dataclass(frozen=True, slots=True)
class Pending:
    handle: str
    at: int
    attempts: int = 0
    #: le salon du message (``None`` en privé) : avec l'adresse, il dit à quel tour il appartient
    room: str | None = None


@dataclass(frozen=True, slots=True)
class PendingEffect:
    capability: str
    owner: str
    at: int
    args_json: str = "{}"
    context: str = ""
    summary_ref: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeState:
    open: FrozenDict[str, OpenEpisode] = FrozenDict()
    pending: FrozenDict[int, Pending] = FrozenDict()
    effects: FrozenDict[int, PendingEffect] = FrozenDict()


# version 2 : une question en attente sait son salon (le tour de conversation)
RUNTIME = Faculty("runtime", state=RuntimeState, init=lambda p: RuntimeState(), namespaces=rt.NAMESPACES,
                  state_version=2)
RUNTIME.declare(*rt.ALL)


# ── Le tour de conversation (fonctions pures de la tranche) ───────────────


def turn_of(s: RuntimeState, handle: str, room: str | None) -> tuple[int, ...]:
    """Les messages sans réponse de ``handle`` en ``room``, du plus ancien au plus récent."""
    return tuple(seq for seq, p in s.pending.items() if p.handle == handle and p.room == room)


def turn_upto(s: RuntimeState, reply_to: int) -> tuple[int, ...]:
    """Le tour auquel appartient ``reply_to``, jusqu'à lui compris (vide s'il n'attend plus)."""
    p = s.pending.get(reply_to)
    if p is None:
        return ()
    return tuple(seq for seq in turn_of(s, p.handle, p.room) if seq <= reply_to)


def unanswered_at_end(s: RuntimeState, reply_to: int | None, outcome: str) -> tuple[int, ...]:
    """Ce qu'une fin d'épisode laisse sans réponse pour de bon : le tour jusqu'à
    ``reply_to`` quand l'issue le règle (elle s'est tue, la réponse a échoué ou
    expiré) ou quand ses tentatives sont épuisées ; rien quand la question
    attend encore (une supplantation, une préemption, un arrêt)."""
    if reply_to is None or reply_to not in s.pending:
        return ()
    if outcome in UNSETTLED and s.pending[reply_to].attempts < MAX_REPLY_ATTEMPTS:
        return ()
    return turn_upto(s, reply_to)


# ── Réducteurs ────────────────────────────────────────────────────────────


@RUNTIME.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: RuntimeState, e, cx) -> RuntimeState:
    if not e.data.addressed:
        return s  # entendu, pas adressé : personne n'attend de réponse
    return replace(s, pending=s.pending.set(e.seq, Pending(e.data.handle, e.at, room=e.data.room)))


@RUNTIME.reducer(rt.EPISODE_STARTED)
def _started(s: RuntimeState, e, cx) -> RuntimeState:
    d = e.data
    s = replace(s, open=s.open.set(e.correlation, OpenEpisode(d.kind, e.at, d.target, d.reply_to)))
    if d.reply_to is not None and d.reply_to in s.pending:
        p = s.pending[d.reply_to]
        s = replace(s, pending=s.pending.set(d.reply_to, replace(p, attempts=p.attempts + 1)))
    return s


@RUNTIME.reducer(rt.UTTERANCE)
def _uttered(s: RuntimeState, e, cx) -> RuntimeState:
    d = e.data
    settled = d.answers or ((d.reply_to,) if d.reply_to is not None else ())
    pending = s.pending
    for seq in settled:
        pending = pending.delete(seq)
    return s if pending is s.pending else replace(s, pending=pending)


@RUNTIME.reducer(rt.EPISODE_ENDED)
def _ended(s: RuntimeState, e, cx) -> RuntimeState:
    s = replace(s, open=s.open.delete(e.correlation))
    d = e.data
    if d.unanswered is not None:
        pending = s.pending
        for seq in d.unanswered:
            pending = pending.delete(seq)
        return replace(s, pending=pending)
    # un journal plus ancien : la fin ne disait pas ce qu'elle laissait sans réponse
    if d.reply_to is not None and d.reply_to in s.pending:
        attempts = s.pending[d.reply_to].attempts
        keep = d.outcome in UNSETTLED and attempts < MAX_REPLY_ATTEMPTS
        if not keep:
            s = replace(s, pending=s.pending.delete(d.reply_to))
    return s


@RUNTIME.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: RuntimeState, e, cx) -> RuntimeState:
    if not e.data.approval:
        return s
    d = e.data
    return replace(s, effects=s.effects.set(e.seq, PendingEffect(d.capability, d.owner, e.at, d.args_json, d.context,
                                                                 d.summary.ref or "")))


@RUNTIME.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: RuntimeState, e, cx) -> RuntimeState:
    return replace(s, effects=s.effects.delete(e.data.proposal))


@RUNTIME.fact(rt.AWAITING)
def _awaiting(s: RuntimeState, cx) -> tuple[int, ...]:
    return tuple(s.pending.keys())


@RUNTIME.fact(rt.TURN)
def _turn(s: RuntimeState, cx, key: tuple[str, str | None]) -> tuple[int, ...]:
    handle, room = key
    return turn_of(s, handle, room)


@RUNTIME.fact(rt.PENDING_EFFECTS)
def _pending_effects(s: RuntimeState, cx) -> tuple[rt.PendingEffectView, ...]:
    return tuple(rt.PendingEffectView(seq, p.capability, p.owner, p.context, p.summary_ref, p.at)
                 for seq, p in sorted(s.effects.items()))


# ── Effets externes : exécutés après commit, jamais depuis un outil ───────


async def _execute(proposal: int, capability: str, args_json: str, context: str,
                   ports: Mapping[str, Any]) -> list[Any]:
    lookup = ports.get("capabilities")
    spec = lookup(capability) if lookup is not None else None
    if spec is None:
        return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result=f"capacité inconnue : {capability}")]
    try:
        args = json.loads(args_json or "{}")
    except ValueError:
        return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result="arguments illisibles")]
    out = await acall(spec.fn, args if isinstance(args, dict) else {}, context, ports, label=f"capacité {capability}")
    if isinstance(out, Failed):
        return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result=f"échec : {out.error!r}"[:RESULT_MAX])]
    ok, result = out
    return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=bool(ok), result=str(result)[:RESULT_MAX])]


def _what_runs(ev: Any) -> tuple[int, str] | None:
    """La capacité qu'un événement fait exécuter, ``(proposition, capacité)`` — ``None`` s'il n'exécute rien
    (une proposition qui attend un accord, un refus)."""
    d = ev.data
    if ev.type.name == rt.EFFECT_PROPOSED.name:
        return None if d.approval else (ev.seq, d.capability)
    return (d.proposal, d.capability) if d.approved else None


def _cut(why: str) -> str:
    """Ce qu'on dit d'une capacité dont on ne sait pas si elle a eu lieu, selon ce qui l'a coupée : un arrêt
    brutal (au démarrage), ou son échéance — jamais « un arrêt » quand il n'y en a pas eu."""
    if not why or why == STOPPED:
        return INTERRUPTED
    head = why if why.startswith("délai dépassé") else f"interrompue ({why})"
    return (f"{head} — on ne sait pas si elle a eu lieu : pas relancée automatiquement (elle n'est pas rejouable "
            "sans risque), à relancer si besoin")[:RESULT_MAX]


def _interrupted(ev: Any, ports: Mapping[str, Any], why: str = "") -> list[Draft[Any]] | None:
    """Une exécution dont on n'a pas le compte rendu : le processus est mort pendant qu'elle tournait (trouvée
    « en cours » au démarrage), ou elle a dépassé son échéance. Une capacité qui se rejoue sans risque repart
    (``None``) ; une autre (un envoi, une commande réseau) n'est pas relancée en silence : son échec est
    journalisé, avec ce qui l'a coupée, et la décision revient à qui l'avait voulue."""
    running = _what_runs(ev)
    if running is None:
        return None  # rien n'était exécuté : rejouer ne coûte rien
    proposal, capability = running
    lookup = ports.get("capabilities")
    spec = lookup(capability) if lookup is not None else None
    if spec is not None and spec.idempotent:
        return None
    return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result=_cut(why))]


@RUNTIME.effect(rt.EFFECT_PROPOSED, lane=CAPABILITY_LANE, deadline_s=CAPABILITY_DEADLINE_S,
                when=lambda d: not d.approval, on_interrupted=_interrupted)
async def _auto(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une proposition sans accord requis part tout de suite."""
    d = ev.data
    if d.approval:
        return None
    return await _execute(ev.seq, d.capability, d.args_json, d.context, ports)


@RUNTIME.effect(rt.EFFECT_RESOLVED, lane=CAPABILITY_LANE, deadline_s=CAPABILITY_DEADLINE_S,
                when=lambda d: d.approved, on_interrupted=_interrupted)
async def _approved(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    d = ev.data
    if not d.approved:
        return None
    return await _execute(d.proposal, d.capability, d.args_json, d.context, ports)


# ── Une question qui restera sans réponse : le transport le dit ───────────


@RUNTIME.effect(rt.EPISODE_ENDED, when=lambda d: bool(d.unanswered))
async def _no_reply(ev: Any, ports: Mapping[str, Any]) -> None:
    """Un tour qu'une fin laisse sans réponse (``unanswered``) part au transport comme une livraison sans
    parole ni voix — ``reply_abstained`` quand elle a choisi de se taire, ``reply_failed`` sinon (la réponse a
    échoué, expiré, ses tentatives sont épuisées, une reprise au démarrage arrive trop tard ; ``text`` porte
    le détail technique, jamais montré tel quel). Une livraison par tour, pour son dernier message : les
    précédents étaient lus avec lui (le web passe sa bulle en échec et éteint « Mika écrit… » ; une
    messagerie ne l'écrit qu'une fois). Personne ne reste devant « Mika écrit… », même pour une réponse reprise que
    personne n'attend plus. Un transport qui ne peut pas la prendre rend ``False`` : la file de sortie
    réessaiera."""
    d = ev.data
    port, store = ports.get("delivery"), ports.get("store")
    if not d.unanswered or port is None or store is None:
        return
    last: dict[tuple[str, str | None], tuple[int, rt.PerceptionReceived]] = {}
    for stored in store.get_events(sorted(d.unanswered)):
        if stored.type != rt.PERCEPTION_RECEIVED.name:
            continue
        p = rt.PerceptionReceived.model_validate_json(stored.data)
        last[(p.handle, p.room)] = (stored.seq, p)
    abstained = d.outcome == "abstained"
    for seq, p in sorted(last.values(), key=lambda x: x[0]):
        await port.deliver(Delivery(
            key=f"{ev.id}:{seq}", target=p.handle, channel=p.channel, room=p.room,
            text="" if abstained else (d.detail or d.outcome), persona=voice.SPEAKING,
            emotion=EmotionView("neutral", 0.0), message_id=0, reply_to=seq, client_msg_id=p.client_msg_id,
            source=d.outcome, kind=REPLY_ABSTAINED if abstained else REPLY_FAILED))
