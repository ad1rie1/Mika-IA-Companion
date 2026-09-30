"""Ce que l'attention met dans le prompt, et l'envie d'en reparler.

**Ce qui te trotte dans la tête** : ses pensées vivantes, les plus fortes —
filtrées comme la mémoire : ce qui concerne quelqu'un d'autre ne se montre
qu'à une audience qui peut l'entendre.

**Une pensée qui insiste** sur quelqu'un — une inquiétude, une peine —
pousse à lui en reparler (preuve vers cette personne, si elle est joignable).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import attention as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.attention.faculty import ATTENTION, AttentionState, params
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, HOUR
from mika.kernel.faculty import Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody, readable
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.privacy import Sensitivity

SHOWN = 3


def admissible(t: c.ThoughtReading, interlocutor: str | None, aud: Audience | None) -> bool:
    """Les règles de la mémoire : ce qui ne concerne personne passe s'il est
    anodin (ou si l'audience peut l'entendre) ; ce qui ne concerne que l'interlocuteur, s'il est anodin ou si sa fiche est ouverte ;
    ce qui concerne d'autres, jusqu'au niveau de l'audience."""
    if aud is None:
        return not t.about and t.sensitivity <= Sensitivity.ANODYNE
    if not t.about:  # personne d'identifié (un mail, un signal) : anodin, ou ce que l'audience peut entendre
        return t.sensitivity <= max(Sensitivity.ANODYNE, aud.level)
    others = [a for a in t.about if a != interlocutor]
    if not others:
        return t.sensitivity <= Sensitivity.ANODYNE or aud.private_ok
    limit = aud.witness_level if interlocutor in t.about else aud.level
    return t.sensitivity <= limit


def _when(born: int, now: int) -> str:
    age = now - born
    if age < HOUR:
        return "tout à l'heure"
    if age < DAY:
        return "aujourd'hui"
    return "ces jours-ci"


@ATTENTION.enricher("thoughts", episodes=CONVERSATIONAL, deadline_ms=500)
async def _texts(s: AttentionState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    thoughts = frame.get(c.THOUGHTS)
    if store is None or not thoughts:
        return None
    return store.content([t.text_ref for t in thoughts[: SHOWN * 3] if t.text_ref])


@ATTENTION.section("thoughts", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["mood"], trim_rank=50,
                   tags=[Tag.AFFECTIVE], title="CE QUI TE TROTTE DANS LA TÊTE", reads=[c.THOUGHTS])
def _thoughts(s: AttentionState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts = enrich.get("thoughts") or {}
    ep, aud = frame.episode, frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    lines = []
    for t in frame.get(c.THOUGHTS):
        text = texts.get(t.text_ref)
        if not text or not admissible(t, person, aud):
            continue
        feeling = A.FR.get(A.emotion_of(t.emotion) or A.Emotion.THINKING, "")
        strength = "et ça te revient souvent" if t.intensity >= 0.5 else "de temps en temps"
        lines.append(f"- {_when(t.born_at, frame.now)} : {text} ({feeling}, {strength})")
        if len(lines) >= SHOWN:
            break
    if not lines:
        return None
    lines.append("Tu n'es pas obligée d'en parler ; ça colore juste ce que tu ressens.")
    return SectionBody("\n".join(lines))


def _insisting(origin: str, name: str, feeling: str) -> str:
    """Pourquoi elle a envie de lui en reparler, selon d'où vient la pensée."""
    if origin == c.PROMISE:
        return (f"Tu avais promis quelque chose à « {name} » et tu ne l'as pas fait à temps : tu as envie de le lui "
                "dire simplement, sans te justifier des heures, et de voir ce que tu peux faire maintenant.")
    if origin == c.CONCERN:
        return (f"« {name} » n'avait pas l'air comme d'habitude la dernière fois : tu t'inquiètes un peu, et tu as "
                "envie de prendre de ses nouvelles.")
    return (f"Tu repenses à ton dernier échange avec « {name} » ({feeling}) : tu as envie d'en reparler, "
            "ou simplement de prendre de ses nouvelles.")


def _address(frame: Frame, person: str) -> str | None:
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


@ATTENTION.propose(kinds=[Kind.INITIATIVE], reasons={c.THOUGHT: (0.0, 4.0)},
                   reads=[c.THOUGHTS, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                          presence_c.PRESENT, social_c.CLOSENESS, transcript_c.LAST_FROM])
def _insists(s: AttentionState, frame: Frame) -> list[Candidate]:
    """Une pensée forte sur quelqu'un : envie de lui en reparler."""
    p = params(frame.env.params_of("attention", frame.root))
    out: list[Candidate] = []
    seen: set[str] = set()
    for t in frame.get(c.THOUGHTS):
        if t.intensity < p.thought_from or t.origin == c.MISSING or len(t.about) != 1:
            continue
        if A.valence(A.emotion_of(t.emotion) or A.Emotion.THINKING) >= 0:
            continue  # un bel échange reste en tête sans devenir une relance ; une inquiétude, si
        person = t.about[0]
        if person in seen or frame.get(social_c.CLOSENESS(person)) == social_c.STRANGER:
            continue
        seen.add(person)
        address = _address(frame, person)
        if address is None:
            continue
        evidence = p.thought_evidence * min(1.0, (t.intensity - p.thought_from) / max(1e-9, 1.0 - p.thought_from) * 2)
        name = frame.get(identity_c.IDENTITY(person)).name or "cette personne"
        feeling = A.FR.get(A.emotion_of(t.emotion) or A.Emotion.THINKING, "")
        brief = _insisting(t.origin, name, feeling)
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        out.append(Candidate(Kind.INITIATIVE, address, c.THOUGHT, evidence, resources=frozenset({floor(address)}),
                             guards=(guard,), args=FrozenDict({"brief:attention": brief})))
    return out


# ── Outil : relire ce qui lui trotte dans la tête (même filtre que la section) ──

ATTENTION.bundle("attention", "ce qui te trotte dans la tête en ce moment")


class NoArgs(BaseModel):
    pass


@ATTENTION.tool("attention_thoughts", description="Ce qui te trotte dans la tête en ce moment.", args=NoArgs,
                bundle="attention", episodes=CONVERSATIONAL)
async def attention_thoughts(args: NoArgs, ctx: Any) -> str:
    enrich = {"thoughts": await _texts(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_thoughts(ctx.state, ctx.frame, enrich), ctx.frame.audience) or "Rien ne te trotte dans la tête."
