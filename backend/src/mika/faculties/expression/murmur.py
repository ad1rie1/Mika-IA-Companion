"""Le murmure : parfois, avant d'écrire d'elle-même à quelqu'un qui la regarde, une pensée à mi-voix — et parfois
elle se ravise (le prélude ``murmur``) ; pourquoi elle écrit, dit en clair, jamais le motif lui-même (``why``,
``why_fr``) ; et le réducteur qui retient à qui elle allait écrire (``_murmuring``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import expression as c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.expression.faculty import EXPRESSION, MURMURS_KEPT, ExpressionState, params
from mika.kernel.codec import h64
from mika.kernel.episode import Prelude
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.days import when_fr
from mika.vocab.episodes import Kind
from mika.vocab.people import is_internal
from mika.vocab.phrasebook import family, phrase
from mika.vocab.words import elided

#: ce qui pèse : une humeur qui déborde, une inquiétude, une peine — on se parle plus à soi-même
CHARGED = frozenset({affect_c.MOOD_OVERFLOW, others_c.CHECK_IN, social_c.COMFORT, attention_c.THOUGHT})
def why() -> Mapping[str, str]:
    """Pourquoi elle écrit, dit en clair, par raison d'initiative (``expression.murmur.why`` dans sa voix) — jamais
    le motif lui-même (ce qu'on lui a confié, un nom d'autrui, une citation) : le murmure se montre à l'écran de la
    personne, qui n'a pas à lire ce qui la travaille."""
    return family("expression.murmur.why")


def _draw(*parts: Any) -> float:
    """Un tirage uniforme dans [0, 1), dérivé de l'épisode (rejouable)."""
    return h64("murmure", *parts) / 2.0 ** 64


def _matter_why(frame: Frame, target: str, name: str) -> str | None:
    """Ce dont elle a envie de lui parler, quand ce sont ses envies qui la poussent
    (la sorte de chose, jamais son contenu)."""
    m = frame.get(needs_c.MATTER(target))
    if not isinstance(m, needs_c.Matter):
        return None
    if m.kind == needs_c.THOUGHT_MATTER:
        return phrase("expression.murmur.matter.read") if m.external else \
            phrase("expression.murmur.matter.thought")
    if m.kind == needs_c.DONE_MATTER:
        return phrase("expression.murmur.matter.done", when=when_fr(m.at, frame.now, frame.env.tz_of(frame.root)))
    if m.kind == needs_c.WORKING_MATTER:
        return phrase("expression.murmur.matter.working")
    if m.kind == needs_c.MOMENT_MATTER:
        return phrase("expression.murmur.matter.moment")
    if m.kind == needs_c.DREAM_MATTER:
        return phrase("expression.murmur.matter.dream")
    return phrase("expression.murmur.matter.told", que_name=elided(name, "que"))


def why_fr(frame: Frame, req: Any, target: str, name: str) -> str:
    """La raison la plus forte de l'initiative, dite en clair."""
    selected = getattr(req, "selected", None)
    parts = sorted(getattr(selected, "parts", ()) or (), key=lambda p: (-p[2], p[1]))
    said = why()
    for _source, reason, _evidence in parts:
        if reason in (needs_c.NEED_SOCIAL, needs_c.NEED_EXPRESSION, social_c.CHAT):
            matter = _matter_why(frame, target, name)
            if matter is not None:
                return matter
        if reason in said:
            return said[reason]
    return phrase("expression.murmur.anything")


def _mood(frame: Frame) -> str:
    m = frame.get(affect_c.MOOD)
    if m.felt_intensity < 0.1:
        return phrase("expression.murmur.as_usual")
    return f"{A.intensity_word(m.felt_intensity)} {A.FR.get(m.felt, '')}".strip()


@EXPRESSION.prelude(kinds=[Kind.INITIATIVE])
def murmur(frame: Frame, req: Any) -> Prelude | None:
    """Avant d'écrire d'elle-même à quelqu'un qui la regarde (un écran ouvert),
    elle se murmure parfois ce qui la traverse — une fois sur trois environ,
    plus souvent quand quelque chose pèse ; parfois elle se ravise. Réveillée,
    pas pour une salutation, pas plus d'une fois par heure. Le murmure se montre
    à la personne visée (persona voix intérieure), jamais en message, et ne dit
    jamais le motif lui-même."""
    reasons = set(str(getattr(req, "reason", "")).split(","))
    target = getattr(req, "target", None)
    if not target or is_internal(target) or social_c.GREETING in reasons:
        return None
    if target not in frame.get(presence_c.PRESENT):
        return None  # personne pour l'entendre (une messagerie : un murmure ne s'écrit pas)
    if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return None
    p = params(frame.env.params_of("expression", frame.root))
    if frame.now - frame.get(agency_c.AGENCY).murmured_at < p.murmur_spacing_us:
        return None
    trigger = str(getattr(req, "trigger", ""))
    chance = p.murmur_charged_chance if CHARGED & reasons else p.murmur_chance
    if _draw(trigger, target, frame.seq) >= chance:
        return None
    # on ne se ravise pas de tenir parole (un rappel promis), ni de prévenir de ce qui ne peut pas attendre (un mail
    # important, un projet confié qui bloque) : elle peut y penser à mi-voix, jamais « pas maintenant » (ADR 0044)
    firm = bool((agency_c.OWED | agency_c.INFORMS) & reasons)
    adrift = not firm and _draw("sans suite", trigger, target, frame.seq) < p.murmur_adrift
    known = frame.get(identity_c.IDENTITY(target)).name
    name = f"« {known} »" if known else phrase("expression.person.unnamed")
    reason = why_fr(frame, req, target, name)
    now = frame.local()
    scene = phrase("expression.murmur.scene", hour=now.hour, minute=f"{now.minute:02d}", mood=_mood(frame))
    if adrift:
        intent = phrase("expression.murmur.intent_adrift", name=name, why=reason)
        ask = phrase("expression.murmur.ask_adrift")
    else:
        intent = phrase("expression.murmur.intent", name=name, why=reason)
        ask = phrase("expression.murmur.ask")
    tail = phrase("expression.murmur.tail", ask=ask)
    tag = c.MURMUR_ADRIFT if adrift else c.MURMUR
    return Prelude(Kind.MURMUR, f"{scene} {intent} {tail}", reason=f"{tag}:{target}", instead=adrift)


@EXPRESSION.reducer(rt.EPISODE_STARTED)
def _murmuring(s: ExpressionState, e, cx) -> ExpressionState:
    """Un murmure commence : on retient à qui elle allait écrire (sa livraison ira
    là, et seulement là)."""
    d = e.data
    if d.kind != Kind.MURMUR:
        return s
    tag, _, target = d.reason.partition(":")
    if tag not in (c.MURMUR, c.MURMUR_ADRIFT) or not target:
        return s
    murmurs = s.murmurs.set(e.correlation, target)
    if len(murmurs) > MURMURS_KEPT:  # les identifiants d'épisode sont chronologiques
        murmurs = FrozenDict(sorted(murmurs.items())[-MURMURS_KEPT:])
    return replace(s, murmurs=murmurs)
