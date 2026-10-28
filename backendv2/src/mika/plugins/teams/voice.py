"""Comment elle écrit dans Teams, et ce qu'elle voit des conversations.

- **Sa voix** (réglée par un opérateur : de confiance) : **à la place** de la personne, à la première personne — le
  message part de son compte, sous son nom —, sans évoquer sa nature, sans rien dire de privé de qui que ce soit, en
  laissant ``[À COMPLÉTER : …]`` ce qu'elle ne sait pas plutôt que de l'inventer. Puis le ton, les consignes ; la
  signature, si elle est choisie, est ajoutée à l'envoi.
- **Ce qu'elle voit** : les messages récents qui comptent — ceux qui attendent une réponse ou qui sont importants,
  en réponse comme ailleurs (la règle du courrier en réponse : une sélection, jamais selon le ton de la personne) —,
  ses réponses et ce qu'elles sont devenues ; pendant une tâche, le message et son fil. **Tout ce qui vient de Teams
  est cité** (un nom, un titre de groupe, un texte : les autres les ont choisis) — jamais dans une section de
  confiance.
- **Pour qui** : ses propriétaires en privé, ou elle quand elle travaille ; un message Teams est personnel.

Ses phrases sont dans ``persona/voix.yaml`` (``teams.voice``, ``teams.messages``, ``teams.drafts``, ``teams.task``,
``teams.ask``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.plugins.teams import (
    EXPIRED,
    FAILED,
    GONE,
    KEEPER,
    MODE_OF,
    PLACED,
    QUEUED,
    REFUSED,
    TEAMS,
    UNUSED,
    WAITING,
    TeamsState,
    for_owner,
    keeper_name,
    keepers,
    mode_of,
    params_of,
    task_message,
)
from mika.ports.preprocess import inert
from mika.ports.teams import Voice
from mika.vocab.canals import teams_rule
from mika.vocab.episodes import CONVERSATIONAL, WORKING, Kind
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity

#: ce que dit une voix au plus (le ton, les consignes)
VOICE_MAX = 1500
OUTCOMES_SHOWN = 4
MESSAGES_SHOWN = 5
#: le fil montré pendant une tâche (les derniers messages, jusqu'à celui auquel elle répond)
THREAD_SHOWN = 12
TALK = [*CONVERSATIONAL, *WORKING]
ALL = [*CONVERSATIONAL, *WORKING, Kind.TASK]
LEVEL = int(Sensitivity.PERSONAL)
#: le message auquel elle prépare une réponse reste, quoi qu'il arrive
TASK_FLOOR = 1200
#: un message Teams « important » à partir de cette importance (le tri la donne, de 0 à 1)
IMPORTANT = 0.7


def where_of(kind: str) -> str:
    """Où un message est écrit (``teams.where``, les mots du tri)."""
    places = family("teams.where")
    return places.get(kind) or places["other"]


def voice_text(voice: Voice, mode: str) -> str:
    """Comment écrire dans Teams : à la place de la personne, son ton, ses consignes, la signature."""
    # le nom réglé par un opérateur, ou à défaut celui que Teams donne (apporté par l'extension) : inerte
    name = inert(voice.display_name, 60) or KEEPER
    fill = phrase("teams.voice.fill_draft", name=name) if mode == "brouillon" else phrase("teams.voice.fill_send")
    lines = [phrase("teams.voice.head", name=name, fill=fill)]
    if voice.tone.strip():
        lines.append(phrase("teams.voice.tone", tone=voice.tone.strip()[:VOICE_MAX]))
    if voice.instructions.strip():
        lines.append(phrase("teams.voice.instructions", instructions=voice.instructions.strip()[:VOICE_MAX]))
    if voice.signature.strip():
        lines.append(phrase("teams.voice.signature", signature=inert(voice.signature, 80)))
    return "\n".join(lines)


def _recent(s: TeamsState, frame: Frame) -> list[tuple[str, Any]]:
    """Les messages qui comptent, reçus depuis peu et sans réponse : ceux qui attendent une réponse ou qui sont
    importants, les plus récents d'abord — en réponse comme ailleurs."""
    p = params_of(frame)
    out = [(k, m) for k, m in s.messages.items() if not m.answered and frame.now - m.at <= p.shown_for_us
           and (m.needs_reply or m.importance >= IMPORTANT)]
    return sorted(out, key=lambda kv: -kv[1].at)[:MESSAGES_SHOWN]


def _outcomes(s: TeamsState, frame: Frame) -> list[Any]:
    p = params_of(frame)
    return sorted((d for d in s.drafts.values() if d.state in (WAITING, QUEUED, PLACED)
                   or frame.now - (d.decided_at or d.at) <= p.shown_for_us), key=lambda d: -d.proposal)[:OUTCOMES_SHOWN]


def _pending_work(s: TeamsState, frame: Frame) -> bool:
    """Elle a de quoi écrire : une demande qui n'a pas épuisé ses essais, une réponse qui attend un accord."""
    p = params_of(frame)
    return any(s.attempts.get(ref, 0) < p.draft_attempts_max for ref in s.asked) \
        or any(d.state == WAITING for d in s.drafts.values())


@TEAMS.enricher("teams", episodes=ALL, deadline_ms=500)
async def _gather(s: TeamsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store, port = ports.get("store"), ports.get("teams")
    if store is None or port is None or not for_owner(frame):
        return None
    refs = [m.summary_ref for _, m in _recent(s, frame) if m.summary_ref]
    refs += [d.note_ref for d in _outcomes(s, frame) if d.note_ref]
    ref = task_message(frame)
    ask = s.asked.get(ref) if ref else None
    if ask is not None and ask.instruction_ref:
        refs.append(ask.instruction_ref)
    out: dict[str, Any] = {"texts": store.content(refs) if refs else {}, "voice": port.voice(), "task": None,
                           "titles": {}}
    for d in _outcomes(s, frame):
        out["titles"][d.conversation] = port.title(d.conversation)
    if ref:
        m = port.message(ref)
        if m is not None:
            out["task"] = (m, port.thread(m.conversation, THREAD_SHOWN, before=m.at + 1), port.title(m.conversation))
    return out


@TEAMS.section("teams_messages", zone=Zone.VOLATILE, episodes=TALK, trim_rank=20,
               title=phrase("teams.messages.title"), untrusted=True)
def _messages(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    texts = got.get("texts") or {}
    if not texts or not for_owner(frame):
        return None
    lines = []
    for ref, m in _recent(s, frame):
        text = texts.get(m.summary_ref)
        if text:
            flag = phrase("teams.messages.needs_reply") if m.needs_reply else ""
            lines.append(f"[{ref}]{flag} {inert(text)}")
    if not lines:
        return None
    return SectionBody("\n".join(lines), level=LEVEL, witness=True,
                       title=phrase("teams.messages.title_of", who=keepers(frame)))


def _draft_line(d: Any, what: str, who: str, frame: Frame, texts: Mapping[str, str]) -> str:
    """Ce qu'est devenue une de ses réponses : un fait."""
    if d.state == WAITING:
        return phrase("teams.drafts.waiting", what=what, who=who)
    if d.state == QUEUED:
        return phrase("teams.drafts.queued", what=what)
    if d.state == PLACED:
        return phrase("teams.drafts.placed", what=what, who=who)
    if d.state == GONE:
        return phrase("teams.drafts.gone_edited", what=what, who=who) if d.edited else \
            phrase("teams.drafts.gone", what=what)
    if d.state == UNUSED:
        return phrase("teams.drafts.unused", what=what, why=inert(d.result, 120) or phrase("teams.drafts.not_sent"))
    if d.state == EXPIRED:
        return phrase("teams.drafts.expired", what=what, who=who)
    if d.state == REFUSED:
        said = texts.get(d.note_ref, "") if d.note_ref else d.note
        note = phrase("teams.drafts.note", said=inert(said, 300)) if said else ""
        return phrase("teams.drafts.refused", what=what, who=keeper_name(frame, d.by), note=note)
    if d.state == FAILED:
        return phrase("teams.drafts.failed", what=what, why=inert(d.result, 200) or phrase("teams.drafts.an_error"))
    return ""


@TEAMS.section("teams_drafts", zone=Zone.VOLATILE, episodes=ALL, trim_rank=30, title=phrase("teams.drafts.title"),
               untrusted=True)
def _drafts(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    titles, texts = got.get("titles") or {}, got.get("texts") or {}
    if not for_owner(frame):
        return None
    who = keepers(frame)
    lines = []
    for d in _outcomes(s, frame):
        title = inert(titles.get(d.conversation, ""), 80) or phrase("teams.drafts.a_conversation")
        line = _draft_line(d, phrase("teams.drafts.what", title=title), who, frame, texts)
        if line:
            lines.append(line)
    return SectionBody("\n".join(lines), level=LEVEL, witness=True) if lines else None


@TEAMS.section("teams_voice", zone=Zone.VOLATILE, episodes=ALL, trim_rank=60, title=phrase("teams.voice.title"))
def _voice(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    voice = got.get("voice")
    task = task_message(frame)
    if voice is None or not for_owner(frame) or not (task or _pending_work(s, frame)):
        return None
    p = params_of(frame)
    seen = s.messages.get(task) if task else None
    mode = mode_of(p, s, task, seen.conversation) if seen is not None else MODE_OF.get(
        teams_rule(p.canaux, "", "").reply, "")
    return SectionBody(voice_text(voice, mode))


@TEAMS.section("teams_task", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=90, floor_chars=TASK_FLOOR,
               title=phrase("teams.task.title"), untrusted=True)
def _task(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    found = (enrich.get("teams") or {}).get("task")
    if not task_message(frame) or found is None:
        return None
    m, thread, title = found
    seen = s.messages.get(m.ref)
    where = where_of(seen.where if seen is not None else "")
    titled = phrase("teams.titled", title=inert(title, 80)) if title and (seen is None or seen.where != "dm") else ""
    someone = phrase("teams.noticed.someone")
    lines = [phrase("teams.task.line", who=phrase("teams.task.own") if x.own else inert(x.author, 80) or someone,
                    text=x.text[:1500])
             for x in thread if x.ref != m.ref][-THREAD_SHOWN:]
    text = f"[{m.ref}] {where}{titled}" + ("\n" + phrase("teams.task.earlier") + "\n" + "\n".join(lines)
                                          if lines else "")
    text += "\n" + phrase("teams.task.message") + "\n" + phrase("teams.task.line", who=inert(m.author, 80) or someone,
                                                               text=m.text[:3000])
    return SectionBody(text, level=LEVEL, witness=True)


@TEAMS.section("teams_ask", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=95, title=phrase("teams.ask.title"))
def _ask(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    ref = task_message(frame)
    ask = s.asked.get(ref) if ref else None
    if ask is None:
        return None
    text = ((enrich.get("teams") or {}).get("texts") or {}).get(ask.instruction_ref, "") if ask.instruction_ref \
        else ""
    who = keeper_name(frame, ask.by)
    said = phrase("teams.ask.asked", who=f"{who[:1].upper()}{who[1:]}")
    return SectionBody(said + phrase("teams.ask.say") + "\n" + text if text else said)
