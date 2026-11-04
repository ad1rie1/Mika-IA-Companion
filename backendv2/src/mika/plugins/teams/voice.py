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
- **Pour qui** : un compte sert à son propriétaire (ADR 0186, ``accounts_here``) — les tiens à toi en privé et à
  elle quand elle travaille, les siens quand elle travaille, celui d'une personne à elle seule, en tête-à-tête.
  L'enrichisseur calcule ces comptes une fois (``accounts``) ; chaque section n'en montre que ce qui leur appartient.
  Un message Teams est personnel.

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
    accounts_here,
    keeper_name,
    mode_of,
    owner_of,
    params_of,
    task_message,
    writer_of,
)
from mika.ports.preprocess import inert
from mika.ports.teams import Voice, conversation_key
from mika.vocab.access import SELF
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


def voice_text(voice: Voice, mode: str, *, own: bool = False) -> str:
    """Comment écrire dans Teams : à la place de la personne — ou en son nom, dans son propre compte (``own``, ADR
    0186) —, son ton, ses consignes, la signature."""
    # le nom réglé par un opérateur, ou à défaut celui que Teams donne (apporté par l'extension) : inerte
    name = inert(voice.display_name, 60) or KEEPER
    if own:
        lines = [phrase("teams.voice.own")]
    else:
        fill = phrase("teams.voice.fill_draft", name=name) if mode == "brouillon" else phrase("teams.voice.fill_send")
        lines = [phrase("teams.voice.head", name=name, fill=fill)]
    if voice.tone.strip():
        lines.append(phrase("teams.voice.tone", tone=voice.tone.strip()[:VOICE_MAX]))
    if voice.instructions.strip():
        lines.append(phrase("teams.voice.instructions", instructions=voice.instructions.strip()[:VOICE_MAX]))
    if voice.signature.strip():
        lines.append(phrase("teams.voice.signature", signature=inert(voice.signature, 80)))
    return "\n".join(lines)


def _recent(s: TeamsState, frame: Frame, accounts: Any = None) -> list[tuple[str, Any]]:
    """Les messages qui comptent, reçus depuis peu et sans réponse : ceux qui attendent une réponse ou qui sont
    importants, les plus récents d'abord — en réponse comme ailleurs ; de ces comptes (``None`` : de tous)."""
    p = params_of(frame)
    out = [(k, m) for k, m in s.messages.items() if not m.answered and frame.now - m.at <= p.shown_for_us
           and (m.needs_reply or m.importance >= IMPORTANT) and (accounts is None or m.account in accounts)]
    return sorted(out, key=lambda kv: -kv[1].at)[:MESSAGES_SHOWN]


def _outcomes(s: TeamsState, frame: Frame, accounts: Any = None) -> list[Any]:
    p = params_of(frame)
    return sorted((d for d in s.drafts.values() if (accounts is None or d.account in accounts)
                   and (d.state in (WAITING, QUEUED, PLACED) or frame.now - (d.decided_at or d.at) <= p.shown_for_us)),
                  key=lambda d: -d.proposal)[:OUTCOMES_SHOWN]


def _pending_work(s: TeamsState, frame: Frame, account: str) -> bool:
    """Elle a de quoi écrire dans ce compte : une demande qui n'a pas épuisé ses essais, une réponse qui attend un
    accord."""
    p = params_of(frame)
    return any(a.account == account and s.attempts.get(ref, 0) < p.draft_attempts_max for ref, a in s.asked.items()) \
        or any(d.account == account and d.state == WAITING for d in s.drafts.values())


@TEAMS.enricher("teams", episodes=ALL, deadline_ms=500)
async def _gather(s: TeamsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce que ses sections lisent de Teams, réduit aux comptes dont elle peut se servir ici (``accounts``, ADR 0186) :
    ce qui est dans un autre n'est ni lu ni montré."""
    store, port = ports.get("store"), ports.get("teams")
    accounts = accounts_here(frame, [a.key for a in port.accounts()], port) if port is not None else ()
    if store is None or port is None or not accounts:
        return None
    refs = [m.summary_ref for _, m in _recent(s, frame, accounts) if m.summary_ref]
    refs += [d.note_ref for d in _outcomes(s, frame, accounts) if d.note_ref]
    ref = task_message(frame)
    ask = s.asked.get(ref) if ref else None
    if ask is not None and ask.account in accounts and ask.instruction_ref:
        refs.append(ask.instruction_ref)
    # sa voix : celle du compte de sa tâche, sinon du premier compte où elle a de quoi écrire
    m = port.message(ref) if ref else None
    if m is not None and m.account not in accounts:
        m = None
    voiced = m.account if m is not None else next((a for a in accounts if _pending_work(s, frame, a)), "")
    out: dict[str, Any] = {"texts": store.content(refs) if refs else {}, "accounts": accounts,
                           "voice": port.voice(voiced) if voiced else None, "voiced": voiced, "task": None,
                           "titles": {}}
    for d in _outcomes(s, frame, accounts):
        out["titles"][conversation_key(d.account, d.conversation)] = port.title(d.account, d.conversation)
    if m is not None:
        out["task"] = (m, port.thread(m.account, m.conversation, THREAD_SHOWN, before=m.at + 1),
                       port.title(m.account, m.conversation))
    return out


@TEAMS.section("teams_messages", zone=Zone.VOLATILE, episodes=TALK, trim_rank=20,
               title=phrase("teams.messages.title"), untrusted=True)
def _messages(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    texts, accounts = got.get("texts") or {}, got.get("accounts") or ()
    if not texts or not accounts:
        return None
    lines = []
    for ref, m in _recent(s, frame, accounts):
        text = texts.get(m.summary_ref)
        if text:
            flag = phrase("teams.messages.needs_reply") if m.needs_reply else ""
            lines.append(f"[{ref}]{flag} {inert(text)}")
    if not lines:
        return None
    # à qui sont ces messages : la personne de chaque compte qu'ils viennent
    who = " et ".join(dict.fromkeys(writer_of(frame, m.account) for _, m in _recent(s, frame, accounts)))
    return SectionBody("\n".join(lines), level=LEVEL, witness=True,
                       title=phrase("teams.messages.title_of", who=who))


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
    titles, texts, accounts = got.get("titles") or {}, got.get("texts") or {}, got.get("accounts") or ()
    if not accounts:
        return None
    lines = []
    for d in _outcomes(s, frame, accounts):
        title = inert(titles.get(conversation_key(d.account, d.conversation), ""), 80) \
            or phrase("teams.drafts.a_conversation")
        line = _draft_line(d, phrase("teams.drafts.what", title=title), writer_of(frame, d.account), frame, texts)
        if line:
            lines.append(line)
    return SectionBody("\n".join(lines), level=LEVEL, witness=True) if lines else None


@TEAMS.section("teams_voice", zone=Zone.VOLATILE, episodes=ALL, trim_rank=60, title=phrase("teams.voice.title"))
def _voice(s: TeamsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("teams") or {}
    voice, account = got.get("voice"), got.get("voiced") or ""
    task = task_message(frame)
    if voice is None or not account or not (task or _pending_work(s, frame, account)):
        return None
    p = params_of(frame)
    seen = s.messages.get(task) if task else None
    mode = mode_of(p, s, task, seen.conversation, seen.account) if seen is not None else MODE_OF.get(
        teams_rule(p.canaux, account, "").reply, "")
    return SectionBody(voice_text(voice, mode, own=owner_of(frame, account) == SELF))


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
    if ask is None or ask.account not in ((enrich.get("teams") or {}).get("accounts") or ()):
        return None
    text = ((enrich.get("teams") or {}).get("texts") or {}).get(ask.instruction_ref, "") if ask.instruction_ref \
        else ""
    who = keeper_name(frame, ask.by)
    said = phrase("teams.ask.asked", who=f"{who[:1].upper()}{who[1:]}")
    return SectionBody(said + phrase("teams.ask.say") + "\n" + text if text else said)
