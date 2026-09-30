"""Préparer une réponse d'elle-même : une tâche silencieuse (``Kind.TASK``).

Un mail remarqué qui attend une réponse (pas un envoi de masse, pas lu
ailleurs, pas trop vieux), sur une boîte où on le lui a permis et d'un
expéditeur qu'on n'a pas exclu, appelle une tâche : elle lit le mail et son
fil, écrit un brouillon dans la voix de la boîte (``email_draft``), et il
attend l'accord d'un opérateur. Au plus quelques-unes par jour ; une tâche
qui n'a rien donné n'est pas retentée sans fin. Quand un opérateur le lui
demande (``email.draft_asked``), la tâche passe devant, hors plafond — et
endormie, elle la fera au réveil.
"""

from __future__ import annotations

from mika.contracts import email as c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.plugins.email import EMAIL, WAITING, EmailState, account_of, params_of
from mika.vocab.episodes import Kind, task_target

BUNDLES = "email,memory,identity"
BRIEF_AUTO = ("Un mail attend une réponse (« LE MAIL AUQUEL TU PRÉPARES UNE RÉPONSE », plus haut). Prépare-la avec "
              "email_draft (mail=[{ref}]), dans la voix de cette boîte (« COMMENT TU ÉCRIS DEPUIS TES BOÎTES »). "
              "Elle ne partira qu'avec l'accord de ton opérateur. Si ce mail n'appelle finalement aucune réponse, "
              "n'écris rien et dis pourquoi en une phrase.")
BRIEF_ASKED = ("Ton opérateur te demande de préparer une réponse à ce mail (« LE MAIL AUQUEL TU PRÉPARES UNE RÉPONSE » "
               "et « CE QUE TON OPÉRATEUR VEUT Y RÉPONDRE », plus haut). Écris-la avec email_draft (mail=[{ref}]), "
               "dans la voix de cette boîte. Elle ne partira qu'avec son accord.")


def _skipped(address: str, skip: tuple[str, ...]) -> bool:
    address = address.lower()
    domain = "@" + address.split("@")[-1] if "@" in address else ""
    return any(s == address or (s.startswith("@") and s == domain) for s in skip)


def _pending(s: EmailState, ref: str) -> bool:
    return any(d.mail == ref and d.state == WAITING for d in s.drafts.values())


def _today(s: EmailState, now: int) -> int:
    """Les brouillons proposés d'elle-même dans les dernières vingt-quatre heures."""
    return sum(1 for d in s.drafts.values() if now - d.at < DAY and not d.asked)


@EMAIL.propose(kinds=[Kind.TASK], reasons={c.DRAFT: (0.0, 14.0)}, reads=[c.UNREAD])
def _prepare(s: EmailState, frame: Frame) -> list[Candidate]:
    p = params_of(frame)
    out: list[Candidate] = []
    # ce qu'un opérateur a demandé passe devant (et ne compte pas dans le plafond)
    for ref, ask in sorted(s.asked.items(), key=lambda kv: kv[1].seq):
        if _pending(s, ref) or s.attempts.get(ref, 0) >= p.draft_attempts_max:
            continue
        out.append(_candidate(ref, ask.account or account_of(ref), p.asked_evidence, BRIEF_ASKED))
    budget = p.drafts_per_day - _today(s, frame.now)
    if budget <= 0 or not p.autodraft:
        return out
    for m in frame.get(c.UNREAD):
        if budget <= 0:
            break
        seen = s.mails.get(m.mail)
        account = m.account or account_of(m.mail)
        if seen is None or not m.needs_reply or account not in p.autodraft or m.mail in s.asked:
            continue
        if frame.now - m.at > p.draft_within_us or _skipped(seen.address, p.autodraft_skip):
            continue
        if _pending(s, m.mail) or s.attempts.get(m.mail, 0) >= p.draft_attempts_max:
            continue
        out.append(_candidate(m.mail, account, p.draft_evidence, BRIEF_AUTO))
        budget -= 1
    return out


def _candidate(ref: str, account: str, evidence: float, brief: str) -> Candidate:
    return Candidate(Kind.TASK, task_target("email", ref), c.DRAFT, evidence,
                     resources=frozenset({f"mailbox:{account}"}),
                     args=FrozenDict({"bundles": BUNDLES, "brief:email": brief.format(ref=ref), "mail": ref,
                                      "account": account}))
