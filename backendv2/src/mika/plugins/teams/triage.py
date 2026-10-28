"""Trier ce que l'extension a poussé : chaque message reçu devient un signal ; ceux qui posent une question à la
personne, à laquelle elle peut aider, appellent une réponse préparée."""

from __future__ import annotations

import json
import re
from typing import Any

from mika.contracts import body as body_c
from mika.contracts import self_ as self_c
from mika.contracts import teams as c
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.teams import BUNDLE, RECEIVED, TEAMS, TeamsParams, TeamsState, her, params_of
from mika.ports.llm import LLMRequest, Message
from mika.ports.preprocess import inert
from mika.ports.teams import person_handle
from mika.vocab.affect import Emotion, named_feeling
from mika.vocab.canals import CanalRule, teams_rule
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity

_JSON = re.compile(r"\{.*\}", re.S)
#: les conversations où un message s'adresse à la personne même sans la mentionner
ADDRESSED = frozenset({"dm", "group"})
#: le fil qu'on montre au tri, au plus (les derniers messages avant celui-ci)
CONTEXT = 3


def triage_system(owner: str, name: str, persona: str) -> str:
    """La consigne du tri : les messages de ``owner``, qu'elle lit pour l'aider (``name``, le nom de sa persona) ;
    les émotions qu'un message peut lui faire sont celles de son vocabulaire (ADR 0147), et ce qu'il lui fait se
    juge à qui elle est (``persona``, sa persona rendue : ``self.portrayed``, ADR 0153)."""
    return phrase("teams.triage.system", owner=owner, name=name,
                  names=", ".join(e.value for e in Emotion if e is not Emotion.NEUTRAL)) + "\n\n" + phrase(
        "self.portrayed.intro", name=name, persona=persona)


def place_of(kind: str, title: str) -> str:
    """Où un message est écrit, comme elle le dit (« dans le groupe « Projet » ») ; le nom d'une conversation est
    choisi par d'autres : rendu inerte."""
    places = family("teams.where")
    return (places.get(kind) or places["other"]) + (phrase("teams.titled", title=inert(title, 80)) if title else "")


def heuristic(text: str, addressed: bool, where: str) -> dict[str, Any]:
    """Sans tri (au-delà du passage, quota, panne) : l'importance et la question, devinées ; jamais une émotion —
    ce qu'un message lui fait, seul le modèle le dit (ADR 0147)."""
    asks = addressed and "?" in text
    importance = 0.6 if where == "dm" else 0.5 if addressed else 0.25
    return {"importance": importance, "resume": "", "question": asks, "aide": asks, "emotion": "", "intensite": 0.0}


def read_triage(text: str, fallback: dict[str, Any]) -> dict[str, Any]:
    found = _JSON.search(text or "")
    if not found:
        return fallback
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    try:
        importance = max(0.0, min(1.0, float(data.get("importance", fallback["importance"]))))
    except (TypeError, ValueError):
        importance = fallback["importance"]
    emotion, intensity = named_feeling(data.get("emotion"), data.get("intensite"))
    return {"importance": importance, "resume": str(data.get("resume") or "")[:300],
            "question": bool(data.get("question")), "aide": bool(data.get("aide")),
            "emotion": emotion, "intensite": intensity}


def where_of(port: Any, conversation: str) -> tuple[str, str]:
    """La nature d'une conversation et son nom (vide pour un tête-à-tête : c'est l'autre personne)."""
    found = port.conversation(conversation)
    kind = found.kind if found is not None else "other"
    if conversation.startswith("48:"):
        kind = "system"  # les notifications de Teams : pas une conversation
    return kind, (found.title if found is not None and kind != "dm" else "")


def rule_of(p: TeamsParams, port: Any, conversation: str, author: str) -> CanalRule:
    """La ligne de Teams pour un message (ADR 0132, 0134) : par un morceau de l'identifiant de sa conversation, de
    son nom ou du nom de qui écrit — la même au tri et quand elle écrit, qui la relit telle qu'elle est maintenant."""
    _kind, title = where_of(port, conversation)
    return teams_rule(p.canaux, "", conversation, title, author)


@TEAMS.process("teams.triage", wake_on=[*body_c.ALL, RECEIVED], lane="background", catch_up=CatchUp.ONCE,
               max_quantum_s=900, priority=70)
class Triage:
    def __init__(self) -> None:
        #: les lots déjà lus (``TeamsState.receipts`` au début du dernier passage ; ``None`` : pas encore passé)
        self.handled: int | None = None
        #: le dernier passage a lu tout ce qu'il pouvait : il en reste peut-être
        self.more = False

    def next_due(self, s: TeamsState, frame: Frame, last_run: int | None) -> int | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return None  # elle lira au réveil
        return frame.now if self.more or self.handled is None or s.receipts != self.handled else None

    async def run(self, ctx: Any) -> None:
        # les lots lus sont ceux d'avant ce passage (ce qui arrive pendant change ``receipts`` : un autre passage
        # suivra) ; comptés à la fin seulement : un passage qui échoue est repris (avec le recul de l'ordonnanceur)
        receipts = ctx.state.receipts
        self.more = await self._run(ctx)
        self.handled = receipts

    async def _run(self, ctx: Any) -> bool:
        """Un passage ; vrai s'il a lu tout ce qu'il pouvait (il en reste peut-être)."""
        port = ctx.ports.get("teams")
        if port is None:
            return False
        p = params_of(ctx.frame)
        known = ctx.state.messages
        fetched = await port.fetch_new(p.per_run)
        name = her(ctx.frame)
        owner = port.voice().display_name or phrase("teams.triage.caretaker", name=name)
        system = triage_system(inert(owner, 60), name, ctx.frame.get(self_c.PORTRAYED("compact")))
        drafts: list[Any] = []
        asked = 0
        for m in fetched:
            if m.ref in known:
                continue
            kind, title = where_of(port, m.conversation)
            if kind == "system":
                continue
            addressed = kind in ADDRESSED or m.mentions_me
            # sa règle d'envoi (ADR 0132), gardée pour ce qui ne connaît pas le nom de la conversation (ses tâches,
            # sa voix) : préparer d'elle-même, comment ça partirait — l'envoi, lui, la relit (``rule_of``)
            rule = rule_of(p, port, m.conversation, m.author)
            place = place_of(kind, title)
            triage = guess = heuristic(m.text, addressed, kind)
            if addressed and asked < p.triage_per_run:
                asked += 1
                before = [x for x in port.thread(m.conversation, CONTEXT + 1, before=m.at) if x.ref != m.ref]
                lines = [phrase("teams.triage.line", who=phrase("teams.triage.own") if x.own else inert(x.author, 60),
                                text=inert(x.text, 300)) for x in before[-CONTEXT:]]
                body = "\n".join([phrase("teams.triage.place", place=place),
                                  *([phrase("teams.triage.before"), *lines] if lines else []),
                                  phrase("teams.triage.message", who=inert(m.author, 80), text=m.text[:3000])])
                req = LLMRequest(role="triage", call_id=f"{ctx.run_id}#{m.ref}", system_stable=system,
                                 messages=(Message("user", body),), max_tokens=200, lane="background", priority=3)
                resp = await ctx.ask(req)  # un tri raté n'empêche pas de remarquer le message
                triage = read_triage(resp.text, guess) if resp is not None else guess
            summary = phrase("teams.noticed.line", who=inert(m.author, 80) or phrase("teams.noticed.someone"),
                             where=place, text=inert(m.text, 220))
            if triage["resume"]:
                summary += phrase("teams.noticed.summary", summary=inert(triage["resume"], 200))
            # ce qu'il lui fait, tel que le tri le dit : la veille le dose comme pour toute source (ADR 0147)
            drafts.append(c.NOTICED.draft(
                source="teams", kind=c.MESSAGE, summary=Content.of(summary[:400], level=int(Sensitivity.PERSONAL)),
                pertinence=triage["importance"], emotion=triage["emotion"], intensity=triage["intensite"],
                sensitivity=int(Sensitivity.PERSONAL),
                bundle=BUNDLE, message=m.ref, conversation=m.conversation,
                author=inert(m.author, 120), author_id=m.author_id[:200], sent_at=m.at, where=kind,
                importance=triage["importance"],
                needs_reply=bool(addressed and triage["question"] and triage["aide"]),
                mentions_me=m.mentions_me, prepare=rule.prepare, send=rule.reply,
                about=tuple(h for h in (person_handle(m.author_id),) if h), dedupe_key=f"teams:{m.ref}"))
        if drafts:
            await ctx.emit(*drafts)
        # remarqués (ou déjà connus, ou des notifications) : le prochain passage ne les rendra plus
        port.ack([m.ref for m in fetched])
        return len(fetched) >= p.per_run
