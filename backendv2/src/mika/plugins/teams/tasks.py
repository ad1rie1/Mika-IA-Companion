"""Préparer une réponse d'elle-même : une tâche silencieuse (``Kind.TASK``).

Le dernier message d'une conversation qui pose à la personne une question à laquelle elle peut aider, récent, sans
réponse de la personne depuis, dans une conversation qu'on n'a pas exclue et où aucune réponse n'est déjà en
chemin, appelle une tâche : elle lit le fil, écrit à la place de la personne (``teams_draft``), et la réponse part
selon le mode. Au plus quelques-unes par jour ; une tâche qui n'a rien donné n'est pas retentée sans fin. Quand un
opérateur le lui demande (``teams.draft_asked``), la tâche passe devant, hors plafond — et endormie, elle la fera au
réveil.

Ses outils : le lot ``teams`` seulement. Sa mémoire n'est pas de la partie (ses outils ne servent pas les tâches) : elle
contient la vie de la personne et ce que d'autres lui ont confié, et une réponse part chez des collègues.

D'elle-même, elle ne prépare que dans les comptes à toi et les siens (ADR 0186) ; dans celui d'une personne, seulement
quand on le lui demande. La réponse s'écrit à la place de la personne du compte, et part de ce compte.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.contracts import teams as c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.plugins.teams import (
    TEAMS,
    Seen,
    TeamsParams,
    TeamsState,
    asked_still,
    drafted,
    keeper_name,
    mode_of,
    params_of,
    under_way,
    writer_of,
)
from mika.ports.teams import conversation_key
from mika.vocab.access import SELF
from mika.vocab.episodes import Kind, task_target
from mika.vocab.phrasebook import phrase


def fate(mode: str, who: str) -> str:
    """Ce que devient sa réponse selon le mode (``teams.task.fate.*`` : une clé écrite en entier, une clé construite
    n'aurait pas droit au trou ``who``) ; un mode inconnu est un brouillon."""
    if mode == "validation":
        return phrase("teams.task.fate.validation", who=who)
    if mode == "autonome":
        return phrase("teams.task.fate.autonome", who=who)
    return phrase("teams.task.fate.brouillon", who=who)


def _today(s: TeamsState, now: int) -> int:
    """Les réponses proposées d'elle-même dans les dernières vingt-quatre heures."""
    return sum(1 for d in s.drafts.values() if now - d.at < DAY and not d.asked)


def _waiting(s: TeamsState, frame: Frame, p: TeamsParams) -> list[tuple[str, Seen]]:
    """Par conversation (de chaque compte), le dernier message qui appelle une réponse (une conversation ne reçoit
    qu'une réponse à la fois : à sa dernière question)."""
    latest: dict[str, tuple[str, Seen]] = {}
    for ref, m in s.messages.items():
        if not m.needs_reply or m.answered or frame.now - m.at > p.draft_within_us:
            continue
        key = conversation_key(m.account, m.conversation)
        if s.replied.get(key, 0) >= m.at:
            continue  # la personne a écrit depuis
        if key not in latest or latest[key][1].at < m.at:
            latest[key] = (ref, m)
    return sorted(latest.values(), key=lambda kv: kv[1].at)


@TEAMS.propose(kinds=[Kind.TASK], reasons={c.DRAFT: (0.0, 14.0)},
               reads=[identity_c.OWNERS, identity_c.IDENTITY, self_c.PERSONA])
def _prepare(s: TeamsState, frame: Frame) -> list[Candidate]:
    p = params_of(frame)
    if not p.enabled:
        return []
    out: list[Candidate] = []
    for ref, ask in sorted(s.asked.items(), key=lambda kv: kv[1].seq):
        if under_way(s, ask.account, ask.conversation) or not asked_still(s, ref, p) \
                or ask.account in p.accounts_off:
            continue
        asker = keeper_name(frame, ask.by)
        brief = phrase("teams.task.asked", who=asker[:1].upper() + asker[1:], ref=ref,
                       fate=fate(mode_of(p, s, ref, ask.conversation, ask.account), writer_of(frame, ask.account)))
        out.append(_candidate(ref, ask.account, ask.conversation, p.asked_evidence, brief))
    budget = p.drafts_per_day - _today(s, frame.now)
    if budget <= 0:
        return out
    for ref, m in _waiting(s, frame, p):
        if budget <= 0:
            break
        if ref in s.asked or under_way(s, m.account, m.conversation) or drafted(s, ref):
            continue
        if s.attempts.get(ref, 0) >= p.draft_attempts_max or not m.prepare:
            continue  # sa règle d'envoi (ADR 0132) ne lui fait pas préparer de réponse ici
        if m.account in p.accounts_off:  # un compte décoché : rien
            continue
        if p.owners.get(m.account, "") not in ("", SELF):  # le compte d'une personne : rien d'elle-même (ADR 0186)
            continue
        who = writer_of(frame, m.account)
        brief = phrase("teams.task.auto", who=who, ref=ref,
                       fate=fate(mode_of(p, s, ref, m.conversation, m.account), who))
        out.append(_candidate(ref, m.account, m.conversation, p.draft_evidence, brief))
        budget -= 1
    return out


def _candidate(ref: str, account: str, conversation: str, evidence: float, brief: str) -> Candidate:
    return Candidate(Kind.TASK, task_target("teams", ref), c.DRAFT, evidence,
                     resources=frozenset({f"teams:{conversation_key(account, conversation)}"}),
                     args=FrozenDict({"bundles": "teams", "brief:teams": brief, "message": ref,
                                      "conversation": conversation, "account": account}))
