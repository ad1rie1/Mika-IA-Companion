"""Ce que le prompt lui dit de ses émotions — un ressenti, jamais un chiffre.

Trois choses qu'on ne confond pas : ce qu'elle ressent (son humeur), ce
qu'elle était en écrivant son dernier message à quelqu'un (sa balise, qui
s'estompe), et ce que la relation a installé (« Envers … » : le fond, réservé
à ce qui est chaleureux ou hostile, et l'attachement). Une cause se dit quand
elle est connue, en termes génériques (jamais le nom d'un tiers) ; sinon
« sans trop savoir pourquoi ».
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from mika.contracts.affect import MoodReading, StanceReading
from mika.faculties.affect.params import AffectParams
from mika.faculties.affect.physics import HOSTILE
from mika.kernel.clock import HOUR, MINUTE
from mika.vocab import affect as A
from mika.vocab.affect import FR, Emotion, intensity_word, partitive
from mika.vocab.phrasebook import phrase

#: La cause d'une humeur, par code (``Mark.cause``) → sa phrase dans sa voix (``affect.cause.…``). Générique : la
#: section se montre à n'importe qui. Deux codes peuvent dire la même chose (une seule phrase).
CAUSES: Mapping[str, str] = MappingProxyType({
    "retour": "came_back",
    "réponse": "answered",
    "attente comblée": "awaited",
    "digestion": "digestion",
    "promesse non tenue": "broken_promise",
    "sans réponse": "unanswered",
    "abouti": "achieved",
    "bloquée": "stuck",
    "abandon": "gave_up",
    "objectif de projet abouti": "objective_achieved",
    "objectif de projet bloqué": "objective_stuck",
    "surprise": "surprised",
    "inquiétude": "worried",
    "rêve": "dream",
    "lonely": "lonely",
    "bored": "bored",
    "elle y repense": "thought_back",
    "exchange": "exchange",
    "revision": "revision",
    "missing": "missing",
    "concern": "worried",
    "promise": "promise",
    "blocked": "stuck",
    "signal": "signal",
    "email": "email",
    "rss": "rss",
    "camera": "camera",
    "compagnie": "company",
    "une rêverie écrite": "daydream",
})
#: Une cause qui est un état, dite quand cet état a pris fin (quelqu'un est venu te parler depuis) : au passé, et
#: ce qui en reste au présent — jamais « personne ne t'a parlé » en pleine conversation (HUM-5) ; ``affect.cause_over``.
CAUSES_OVER = frozenset({"lonely", "bored"})
#: Combien de temps elle se dit que quelqu'un s'est excusé (la posture), après.
APOLOGY_SAID_US = 6 * HOUR
#: En deçà, sa dernière balise date d'« à l'instant ».
JUST_NOW_US = 3 * MINUTE


def unknown_cause() -> str:
    """« sans trop savoir pourquoi » (``affect.cause.unknown``)."""
    return phrase("affect.cause.unknown")


def cause_line(cause: str, person: str = "", current: str = "", ended: bool = False) -> str:
    """La cause, dite sans nommer personne : « votre échange » seulement si c'est
    avec la personne à qui elle parle maintenant ; un état qui a pris fin, au passé."""
    if ended and cause in CAUSES_OVER:
        return phrase(f"affect.cause_over.{cause}")
    if cause == "talk":
        if not person:
            return ""
        return phrase("affect.cause.talk_here") if person == current else phrase("affect.cause.talk_elsewhere")
    if cause.startswith("forge:"):
        return phrase("affect.cause.forge")
    key = CAUSES.get(cause)
    return phrase(f"affect.cause.{key}") if key else ""


def _under(parts: list[tuple[Emotion, float]], main: Emotion, *, ratio: float = 0.0, floor: float = 0.0) -> str:
    """La deuxième couleur, si elle compte : « Et en dessous, il y a un peu de colère. »"""
    others = [(e, w) for e, w in parts if e is not main]
    if not parts or not others or others[0][1] < floor or others[0][1] < ratio * parts[0][1]:
        return ""
    return " " + phrase("affect.under", what=partitive(others[0][0]))


def mood(m: MoodReading, p: AffectParams, current: str = "") -> str:
    default = p.background
    gap = A.distance(m.position, m.home)
    if gap < p.rest_tolerance:
        if A.norm(m.fond) >= p.fond_said:
            # le reste d'une journée : trop peu pour la changer, assez pour la colorer
            residue = m.fond_emotion
            if residue is not default and residue is not Emotion.NEUTRAL:
                return phrase("affect.mood_line.residue", usual=FR[default], what=partitive(residue))
        return phrase("affect.mood_line.usual", usual=FR[default])
    word, adj = intensity_word(m.felt_intensity), FR[m.felt]
    cause = cause_line(m.cause, m.cause_person, current, m.cause_over)
    if m.felt is default:
        if m.felt_intensity >= p.marked_intensity:
            base = phrase("affect.mood_line.marked", feeling=adj)
        else:
            base = phrase("affect.mood_line.slope", intensity=word, feeling=adj)
        cause = ""  # sa pente naturelle n'a pas besoin de cause
    elif cause:
        base = phrase("affect.mood_line.caused", intensity=word, feeling=adj, usual=FR[default])
    else:
        base = phrase("affect.mood_line.unexplained", intensity=word, feeling=adj, unknown=unknown_cause(),
                      usual=FR[default])
    lingering = A.norm(m.fond) >= 0.6 * gap
    tail = " " + phrase("affect.mood_line.lingering") if lingering else ""
    under = _under(A.blend(m.position, top_k=2, home=m.home), m.felt, ratio=0.4)
    return base + (f" {cause}" if cause else "") + tail + under


def _who(name: str) -> str:
    return f"« {name} »" if name else phrase("expression.person.unnamed")


def _tenderness(regard: float) -> str:
    if regard >= 0.5:
        return phrase("affect.stance.tenderness.much")
    return phrase("affect.stance.tenderness.some") if regard >= 0.25 else phrase("affect.stance.tenderness.little")


def fond(s: StanceReading, p: AffectParams, name: str = "") -> str:
    """Ce que la relation a installé, s'il est chaleureux ou hostile (un chagrin
    partagé n'installe pas de froid), et l'attachement."""
    who = _who(name)
    attached = s.bond >= p.bond_said
    if s.anchor is not None:
        label, intensity = A.felt(s.anchor, s.reference)
        if intensity >= p.fond_min and label in HOSTILE:
            line = phrase("affect.stance.hostile", who=who, feeling=FR[label])
            return line + (" " + phrase("affect.stance.but_attached", who=who) if attached else "")
        if intensity >= p.fond_min and A.valence(label) > 0 and s.regard > 0:
            if attached:
                return phrase("affect.stance.attached_warm", who=who, tenderness=_tenderness(s.regard))
            return phrase("affect.stance.warm", who=who, tenderness=_tenderness(s.regard))
    return phrase("affect.stance.attached", who=who) if attached else ""


def _capital(text: str) -> str:
    """En tête de phrase : la première lettre en majuscule (« À l'instant », « Cette personne »)."""
    return text[:1].upper() + text[1:]


def stance(s: StanceReading, p: AffectParams, *, name: str = "", now: int = 0) -> str:
    """Ce qu'elle était en lui écrivant (sa balise, qui s'estompe), ce qu'elle
    ressent encore avec cette personne, ce qui s'installe, ce qui est installé.
    Rien à dire d'une posture au repos sans fond : un inconnu n'a pas de
    « posture »."""
    lines: list[str] = []
    who = _who(name)
    under = A.blend(s.position, top_k=3, home=s.home)
    shown: Emotion | None = None
    if s.declared is not None:
        shown = s.declared.emotion
        how = phrase("affect.stance.replying") if s.declared_reply else phrase("affect.stance.writing")
        when = phrase("affect.stance.just_now") if now and now - s.declared_at < JUST_NOW_US else \
            phrase("affect.stance.earlier")
        word = intensity_word(s.declared.intensity)
        lines.append(phrase("affect.stance.declared", when=_capital(when), how=how, intensity=word, feeling=FR[shown])
                     + _under(under, shown, floor=0.25))
    elif not s.at_rest and s.felt_intensity >= 0.1 and s.felt is not Emotion.NEUTRAL:
        shown = s.felt
        lines.append(phrase("affect.stance.felt", who=who, intensity=intensity_word(s.felt_intensity),
                            feeling=FR[shown]) + _under(under, shown, ratio=0.4))
    if s.anchored and shown is not None:
        lines.append(phrase("affect.stance.lasting", feeling=FR[shown], who=who) if s.lasting else
                     phrase("affect.stance.repeated", feeling=FR[shown], who=who))
    if s.apologized_at and now and now - s.apologized_at < APOLOGY_SAID_US:
        when = phrase("affect.stance.just_now") if now - s.apologized_at < JUST_NOW_US else \
            phrase("affect.stance.earlier")
        lines.append(phrase("affect.stance.apologized", who=_capital(who), when=when))
    installed = fond(s, p, name)
    if installed:
        lines.append(installed)
    return "\n".join(lines)
