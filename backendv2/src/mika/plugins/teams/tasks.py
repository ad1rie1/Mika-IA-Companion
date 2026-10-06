"""Préparer une réponse d'elle-même : une tâche silencieuse (``Kind.TASK``).

Le dernier message d'une conversation qui pose à la personne une question à laquelle elle peut aider, récent, sans
réponse de la personne depuis, dans une conversation qu'on n'a pas exclue et où aucune réponse n'est déjà en
chemin, appelle une tâche : elle lit le fil, écrit à la place de la personne (``teams_draft``), et la réponse part
selon le mode. Au plus quelques-unes par jour ; une tâche qui n'a rien donné n'est pas retentée sans fin. Quand un
opérateur le lui demande (``teams.draft_asked``), la tâche passe devant, hors plafond — et endormie, elle la fera au
réveil.

Ses outils : le lot ``teams`` seulement. Sa mémoire n'est pas de la partie (ses outils ne servent pas les tâches) : elle
contient la vie de la personne et ce que d'autres lui ont confié, et une réponse part chez des collègues.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
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
    drafted,
    keeper_name,
    keepers,
    params_of,
    under_way,
)
from mika.vocab.episodes import Kind, task_target

BRIEF_AUTO = ("Un message Teams pose à {who} une question à laquelle tu peux aider (« LE MESSAGE TEAMS AUQUEL TU "
              "PRÉPARES UNE RÉPONSE », plus haut). Prépare la réponse avec teams_draft (message=[{ref}]), à la place "
              "de {who}, comme le dit « COMMENT TU ÉCRIS DANS TEAMS ». {fate} S'il n'y a finalement rien d'utile à "
              "répondre, ou si la réponse demande ce que tu ne sais pas, n'écris rien et dis pourquoi en une phrase.")
BRIEF_ASKED = ("{Who} te demande de préparer une réponse à ce message Teams (« LE MESSAGE TEAMS AUQUEL TU PRÉPARES "
               "UNE RÉPONSE » et « CE QU'ON TE DEMANDE D'Y RÉPONDRE », plus haut). Écris-la avec teams_draft "
               "(message=[{ref}]), à sa place. {fate}")
FATE = {
    "brouillon": "Elle sera posée dans Teams : {who} l'enverra, la retouchera ou la laissera.",
    "validation": "Elle ne partira qu'avec l'accord de {who}.",
    "autonome": "Elle partira telle quelle, sous le nom de {who}, sans que personne la relise : n'écris que ce dont "
                "tu es sûre.",
}


def fate(mode: str, who: str) -> str:
    return FATE.get(mode, FATE["brouillon"]).replace("{who}", who)


def _today(s: TeamsState, now: int) -> int:
    """Les réponses proposées d'elle-même dans les dernières vingt-quatre heures."""
    return sum(1 for d in s.drafts.values() if now - d.at < DAY and not d.asked)


def _waiting(s: TeamsState, frame: Frame, p: TeamsParams) -> list[tuple[str, Seen]]:
    """Par conversation, le dernier message qui appelle une réponse (une conversation ne reçoit qu'une réponse à
    la fois : à sa dernière question)."""
    latest: dict[str, tuple[str, Seen]] = {}
    for ref, m in s.messages.items():
        if not m.needs_reply or m.answered or frame.now - m.at > p.draft_within_us:
            continue
        if s.replied.get(m.conversation, 0) >= m.at:
            continue  # la personne a écrit depuis
        if m.conversation not in latest or latest[m.conversation][1].at < m.at:
            latest[m.conversation] = (ref, m)
    return sorted(latest.values(), key=lambda kv: kv[1].at)


@TEAMS.propose(kinds=[Kind.TASK], reasons={c.DRAFT: (0.0, 14.0)}, reads=[identity_c.OWNERS, identity_c.IDENTITY])
def _prepare(s: TeamsState, frame: Frame) -> list[Candidate]:
    p = params_of(frame)
    if not p.enabled:
        return []
    who = keepers(frame)
    out: list[Candidate] = []
    for ref, ask in sorted(s.asked.items(), key=lambda kv: kv[1].seq):
        if under_way(s, ask.conversation) or s.attempts.get(ref, 0) >= p.draft_attempts_max:
            continue
        asker = keeper_name(frame, ask.by)
        brief = BRIEF_ASKED.replace("{Who}", asker[:1].upper() + asker[1:]).replace("{fate}", fate(p.mode, who))
        out.append(_candidate(ref, ask.conversation, p.asked_evidence, brief))
    budget = p.drafts_per_day - _today(s, frame.now)
    if budget <= 0 or not p.autodraft:
        return out
    for ref, m in _waiting(s, frame, p):
        if budget <= 0:
            break
        if ref in s.asked or under_way(s, m.conversation) or drafted(s, ref):
            continue
        if s.attempts.get(ref, 0) >= p.draft_attempts_max:
            continue
        brief = BRIEF_AUTO.replace("{who}", who).replace("{fate}", fate(p.mode, who))
        out.append(_candidate(ref, m.conversation, p.draft_evidence, brief))
        budget -= 1
    return out


def _candidate(ref: str, conversation: str, evidence: float, brief: str) -> Candidate:
    return Candidate(Kind.TASK, task_target("teams", ref), c.DRAFT, evidence,
                     resources=frozenset({f"teams:{conversation}"}),
                     args=FrozenDict({"bundles": "teams", "brief:teams": brief.replace("{ref}", ref), "message": ref,
                                      "conversation": conversation}))
