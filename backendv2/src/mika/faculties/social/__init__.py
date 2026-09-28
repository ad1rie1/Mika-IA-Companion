"""``social`` : les liens. En M1 : saluer quelqu'un qui arrive.

On salue à l'arrivée (dans les dix minutes), une fois par heure et par
personne, jamais quelqu'un qui a déjà écrit depuis son arrivée — à celui-là,
on répond — ni quelqu'un avec qui on parlait il y a moins d'une demi-heure
(une reconnexion n'est pas une arrivée). Une personne présente offre aussi une cible aux autres
raisons de parler (une humeur qui déborde cherche quelqu'un à qui parler).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.contracts import transcript as transcript_c
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind
from mika.vocab.people import is_internal

GREETING_WINDOW = 10 * MINUTE
GREETING_SPACING = HOUR
GREETING_EVIDENCE = 11.0
RECENT_CONVERSATION = 30 * MINUTE
#: Après un échange, parler de soi-même à la même personne attend un peu.
CONVERSATION_COOLDOWN = 5 * MINUTE
CONVERSATION_SHIFT = -4.0


@dataclass(frozen=True, slots=True)
class SocialState:
    greeted: FrozenDict[str, int] = field(default_factory=FrozenDict)


SOCIAL = Faculty("social", state=SocialState, init=lambda p: SocialState())


@SOCIAL.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _started(s: SocialState, e, cx) -> SocialState:
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.target or c.GREETING not in d.reason.split(","):
        return s
    return replace(s, greeted=s.greeted.set(cx.facts.get(identity_c.PERSON(d.target)), e.at))


@SOCIAL.fact(c.GREETED)
def _greeted(s: SocialState, cx, person: str) -> int:
    return s.greeted.get(person, 0)


@SOCIAL.propose(kinds=[Kind.INITIATIVE], reasons={c.GREETING: (0.0, GREETING_EVIDENCE), c.PRESENT_PERSON: (0.0, 0.0)},
                reads=[presence_c.PRESENT, presence_c.SINCE, identity_c.PERSON, identity_c.IDENTITY,
                       transcript_c.LAST_FROM, transcript_c.LAST_TO])
def _propose(s: SocialState, frame: Frame) -> list[Candidate]:
    out: list[Candidate] = []
    now = frame.now
    for handle in frame.get(presence_c.PRESENT):
        if is_internal(handle):
            continue
        resources = frozenset({floor(handle)})
        guard = Guard("personne-présente", reads=(transcript_c.LAST_FROM(handle),),
                      predicate=lambda view, h=handle: h in view.get(presence_c.PRESENT))
        out.append(Candidate(Kind.INITIATIVE, handle, c.PRESENT_PERSON, 0.0, resources=resources, guards=(guard,)))
        since = frame.get(presence_c.SINCE(handle))
        if since is None or now - since > GREETING_WINDOW:
            continue
        # une reconnexion n'est pas une arrivée : on ne re-salue pas quelqu'un
        # avec qui on parlait encore il y a peu (ni quelqu'un qui a déjà écrit)
        last = max(frame.get(transcript_c.LAST_FROM(handle)), frame.get(transcript_c.LAST_TO(handle)))
        if last >= since - RECENT_CONVERSATION:
            continue
        person = frame.get(identity_c.PERSON(handle))
        if now - s.greeted.get(person, -GREETING_SPACING) < GREETING_SPACING:
            continue
        name = frame.get(identity_c.IDENTITY(handle)).name
        who = f"« {name} »" if name else "Quelqu'un"
        brief = f"{who} vient d'arriver : salue-le ou salue-la, en une phrase ou deux, à ta façon."
        out.append(Candidate(Kind.INITIATIVE, handle, c.GREETING, GREETING_EVIDENCE, resources=resources,
                             guards=(guard,), args=FrozenDict({"brief:social": brief})))
    return out


@SOCIAL.modulate(kinds=[Kind.INITIATIVE], reads=[transcript_c.LAST_FROM, transcript_c.LAST_TO])
def _in_conversation(s: SocialState, frame: Frame, row: RowView) -> Modulation:
    """Pendant un échange, c'est la réponse qui parle, pas l'initiative."""
    if row.target in ("any", "none") or c.GREETING in row.reasons:
        return Modulation()
    last = max(frame.get(transcript_c.LAST_FROM(row.target)), frame.get(transcript_c.LAST_TO(row.target)))
    if last and frame.now - last < CONVERSATION_COOLDOWN:
        return Modulation(shift=CONVERSATION_SHIFT)
    return Modulation()
