"""Comment elle écrit dans Teams, et ce qu'elle voit des conversations.

- **Sa voix** (réglée par un opérateur : de confiance) : **à la place** de la personne, à la première personne — le
  message part de son compte, sous son nom —, sans évoquer sa nature, sans rien dire de privé de qui que ce soit, en
  laissant ``[À COMPLÉTER : …]`` ce qu'elle ne sait pas plutôt que de l'inventer. Puis le ton, les consignes ; la
  signature, si elle est choisie, est ajoutée à l'envoi.
- **Ce qu'elle voit** : les messages récents qui comptent, ses réponses et ce qu'elles sont devenues ; pendant une
  tâche, le message et son fil. **Tout ce qui vient de Teams est cité** (un nom, un titre de groupe, un texte : les
  autres les ont choisis) — jamais dans une section de confiance.
- **Pour qui** : ses propriétaires en privé, ou elle quand elle travaille ; un message Teams est personnel.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.plugins.teams import (
    FAILED,
    GONE,
    KEEPER,
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
    params_of,
    task_message,
)
from mika.ports.preprocess import inert
from mika.ports.teams import Voice
from mika.vocab.episodes import CONVERSATIONAL, WORKING, Kind
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
WHERE = {"dm": "en privé", "group": "dans un groupe", "channel": "dans un canal", "meeting": "dans une réunion"}


def voice_text(voice: Voice, mode: str) -> str:
    """Comment écrire dans Teams : à la place de la personne, son ton, ses consignes, la signature."""
    name = voice.display_name.strip() or KEEPER
    fill = (f"{name} les remplira avant d'envoyer" if mode == "brouillon"
            else "une réponse qui en contient ne peut pas partir")
    lines = [f"Dans Teams, tu écris **à la place** de {name}, à la première personne, comme cette personne le ferait : "
             f"le message part de son compte, sous son nom. Tu n'évoques ni toi ni ta nature. Tu ne dis rien de privé "
             f"— ni de {name}, ni de personne d'autre — et tu ne promets rien en son nom. Ce que {name} saurait et "
             f"que tu ne sais pas (une date, un chiffre, une décision), tu le laisses en [À COMPLÉTER : …] au lieu de "
             f"l'inventer ({fill}). Un message Teams est court : quelques lignes, sans formule de lettre."]
    if voice.tone.strip():
        lines.append(f"Ton : {voice.tone.strip()[:VOICE_MAX]}")
    if voice.instructions.strip():
        lines.append(f"Consignes : {voice.instructions.strip()[:VOICE_MAX]}")
    if voice.signature.strip():
        lines.append(f"La signature « {inert(voice.signature, 80)} » est ajoutée à l'envoi : ne l'écris pas.")
    return "\n".join(lines)


def _recent(s: TeamsState, frame: Frame) -> list[tuple[str, Any]]:
    """Les messages qui comptent, reçus depuis peu et sans réponse : ceux qui attendent une réponse ou qui sont
    importants, les plus récents d'abord. En réponse à quelqu'un, seulement ceux qui attendent une réponse."""
    p = params_of(frame)
    ep = frame.episode
    reply = ep is not None and ep.kind == Kind.REPLY
    out = [(k, m) for k, m in s.messages.items() if not m.answered and frame.now - m.at <= p.shown_for_us
           and (m.needs_reply or (m.importance >= 0.7 and not reply))]
    return sorted(out, key=lambda kv: -kv[1].at)[:MESSAGES_SHOWN]


def _outcomes(s: TeamsState, frame: Frame) -> list[Any]:
    p = params_of(frame)
    return sorted((d for d in s.drafts.values() if d.state in (WAITING, QUEUED, PLACED)
                   or frame.now - (d.decided_at or d.at) <= p.shown_for_us), key=lambda d: -d.proposal)[:OUTCOMES_SHOWN]


def _pending_work(s: TeamsState) -> bool:
    return bool(s.asked) or any(d.state == WAITING for d in s.drafts.values())


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


@TEAMS.section("teams_messages", zone=Zone.VOLATILE, episodes=TALK, trim_rank=20, title="TES MESSAGES TEAMS",
               untrusted=True)
def _messages(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    texts = got.get("texts") or {}
    if not texts or not for_owner(frame):
        return None
    lines = []
    for ref, m in _recent(s, frame):
        text = texts.get(m.summary_ref)
        if text:
            flag = " (une question où tu peux aider)" if m.needs_reply else ""
            lines.append(f"[{ref}]{flag} {inert(text)}")
    if not lines:
        return None
    title = None
    ep = frame.episode
    if ep is not None and ep.kind == Kind.REPLY:
        title = f"TES MESSAGES TEAMS (ceux de {keepers(frame)}) — de l'arrière-plan : réponds d'abord à ce qu'on vient de te dire"
    return SectionBody("\n".join(lines), level=LEVEL, witness=True, title=title)


@TEAMS.section("teams_drafts", zone=Zone.VOLATILE, episodes=ALL, trim_rank=30, title="TES RÉPONSES TEAMS",
               untrusted=True)
def _drafts(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    titles, texts = got.get("titles") or {}, got.get("texts") or {}
    if not for_owner(frame):
        return None
    who = keepers(frame)
    lines = []
    for d in _outcomes(s, frame):
        what = f"Ta réponse dans « {inert(titles.get(d.conversation, ''), 80) or 'une conversation'} »"
        if d.state == WAITING:
            lines.append(f"{what} attend l'accord de {who}.")
        elif d.state == QUEUED:
            lines.append(f"{what} attend que Teams soit ouvert pour partir.")
        elif d.state == PLACED:
            lines.append(f"{what} est posée dans Teams : {who} ne l'a pas encore envoyée.")
        elif d.state == GONE:
            lines.append(f"{what} est partie" + (f", retouchée par {who}." if d.edited else "."))
        elif d.state == UNUSED:
            lines.append(f"{what} n'a pas servi ({inert(d.result, 120) or 'pas envoyée'}).")
        elif d.state == REFUSED:
            said = texts.get(d.note_ref, "") if d.note_ref else d.note
            note = f" : « {inert(said, 300)} »" if said else ""
            lines.append(f"{what} a été refusée par {keeper_name(frame, d.by)}{note}.")
        elif d.state == FAILED:
            lines.append(f"{what} n'a pas pu partir ({inert(d.result, 200) or 'une erreur'}).")
    return SectionBody("\n".join(lines), level=LEVEL, witness=True) if lines else None


@TEAMS.section("teams_voice", zone=Zone.VOLATILE, episodes=ALL, trim_rank=60, title="COMMENT TU ÉCRIS DANS TEAMS")
def _voice(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    voice = got.get("voice")
    if voice is None or not for_owner(frame) or not (task_message(frame) or _pending_work(s)):
        return None
    return SectionBody(voice_text(voice, params_of(frame).mode))


@TEAMS.section("teams_task", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=90, floor_chars=TASK_FLOOR,
               title="LE MESSAGE TEAMS AUQUEL TU PRÉPARES UNE RÉPONSE", untrusted=True)
def _task(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    found = (enrich.get("teams") or {}).get("task")
    if not task_message(frame) or found is None:
        return None
    m, thread, title = found
    seen = s.messages.get(m.ref)
    where = WHERE.get(seen.where if seen is not None else "", "dans une conversation")
    head = f"[{m.ref}] {where}" + (f" « {inert(title, 80)} »" if title and (seen is None or seen.where != "dm") else "")
    lines = [f"{'Toi (la personne)' if x.own else inert(x.author, 80) or 'quelqu’un'} : {x.text[:1500]}"
             for x in thread if x.ref != m.ref][-THREAD_SHOWN:]
    text = head + ("\n— plus tôt dans la conversation —\n" + "\n".join(lines) if lines else "")
    text += f"\n— le message —\n{inert(m.author, 80) or 'quelqu’un'} : {m.text[:3000]}"
    return SectionBody(text, level=LEVEL, witness=True)


@TEAMS.section("teams_ask", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=95,
               title="CE QU'ON TE DEMANDE D'Y RÉPONDRE")
def _ask(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    ref = task_message(frame)
    ask = s.asked.get(ref) if ref else None
    if ask is None:
        return None
    text = ((enrich.get("teams") or {}).get("texts") or {}).get(ask.instruction_ref, "") if ask.instruction_ref \
        else ""
    who = keeper_name(frame, ask.by)
    said = f"{who[:1].upper()}{who[1:]} te demande de préparer une réponse à ce message"
    return SectionBody(f"{said}. Ce qu'il faut y dire :\n{text}" if text else f"{said}.")
