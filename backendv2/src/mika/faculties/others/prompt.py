"""Ce qu'``others`` met dans le prompt : ce qu'elle perçoit de l'état de la personne à qui elle répond (la section
``their_state``), en privé — ce qui tranche ces derniers temps avec son ton habituel, et des réponses réduites à
quelques mots (``curt_run``, sur ses derniers messages : l'enrichisseur ``their_last_words``).

Ce qu'elle a senti de chacun se tient dans ``faculty.py`` (le fait ``others.mind``) ; ce module le lit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import others as c
from mika.contracts import transcript as transcript_c
from mika.faculties.others.faculty import OTHERS, OthersState, params
from mika.faculties.others.initiative import capitalized
from mika.kernel.clock import MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase

#: les messages de la personne relus pour sentir qu'elle ne répond plus que par quelques mots
CURT_RUN = 3
#: … dans cette conversation (au-delà, une autre conversation a commencé)
CURT_SPAN_US = 30 * MINUTE


@OTHERS.enricher("their_last_words", episodes=[Kind.REPLY], deadline_ms=300)
async def _their_last_words(s: OthersState, frame: Frame, ports: Any) -> tuple[str, ...] | None:
    """Ses derniers messages dans cette conversation (de la même adresse, au même endroit), du plus ancien au plus
    récent, jusqu'au message auquel elle répond."""
    store, ep = ports.get("store"), frame.episode
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    if store is None or ep is None or not ep.target or reply_to is None:
        return None
    room = ep.attrs.get("room")
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.text).where(
        t.c.person == ep.target, t.c.role == "user", t.c.id <= reply_to, t.c.at >= frame.now - CURT_SPAN_US,
        t.c.room == room if room else t.c.room.is_(None)).order_by(t.c.id.desc()).limit(CURT_RUN))
    return tuple(str(r[0] or "") for r in reversed(rows))


def curt_run(words: tuple[str, ...]) -> bool:
    """Elle répond à peine, dans la conversation en cours : ses ``CURT_RUN`` derniers messages (l'enrichisseur
    ``their_last_words``), tous brefs (``c.few_words`` : « ouais », « bof », « je sais pas ») — elle ne dit plus
    grand-chose. Un bonjour ou une question parmi eux suffit à dire le contraire. L'échange passé d'où naît une pensée
    a sa propre fenêtre sur la même règle (``attention/watch.py::mostly_curt``)."""
    return len(words) >= CURT_RUN and all(c.few_words(w) for w in words[-CURT_RUN:])


@OTHERS.section("their_state", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=40,
                title=phrase("others.state.title"), reads=[identity_c.PERSON, identity_c.IDENTITY, c.MIND])
def _their_state(s: OthersState, frame: Frame, enrich: Any) -> SectionBody | None:
    """En privé, ce qui tranche ces derniers temps avec le ton habituel de la personne (ce qu'elle a senti de ses
    messages d'avant), et des réponses réduites à quelques mots. Le message auquel elle répond, c'est le modèle qui le
    lit (ADR 0093). Jamais un nombre."""
    ep, aud = frame.episode, frame.audience
    if ep is None or not ep.target or not is_identifiable(ep.target):
        return None
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    r = frame.get(c.MIND(person))
    lines: list[str] = []
    if aud is not None and aud.private_ok and r.confidence >= 1.0:
        name = frame.get(identity_c.IDENTITY(person)).name
        who = f"« {name} »" if name else phrase("others.state.someone")
        if r.usual_valence >= p.notable_deviation:
            lines.append(phrase("others.state.usual_light", who=who))
        elif r.usual_valence <= -p.notable_deviation:
            lines.append(phrase("others.state.usual_heavy", who=who))
        if r.deviation <= -p.notable_deviation:
            lines.append(phrase("others.state.darker", who=who))
        elif r.deviation >= p.notable_deviation:
            lines.append(phrase("others.state.lighter", who=capitalized(who)))
        if r.current_arousal - r.usual_arousal >= p.notable_deviation:
            lines.append(phrase("others.state.livelier"))
    if ep.kind == Kind.REPLY and curt_run(enrich.get("their_last_words") or ()):
        # sonde réelle du 2026-10-03 : à « ouais », « bof », « je sais pas », « laisse tomber », de longs messages
        # pleins de questions et d'idées pour se changer les idées
        name = frame.get(identity_c.IDENTITY(person)).name
        lines.append(phrase("others.state.curt", who=f"« {name} »" if name else phrase("others.state.someone")))
    if not lines:
        return None
    lines.append(phrase("others.state.hint"))
    return SectionBody("\n".join(lines))

