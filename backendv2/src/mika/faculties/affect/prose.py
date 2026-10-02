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
from mika.kernel.clock import MINUTE
from mika.vocab import affect as A
from mika.vocab.affect import FR, Emotion, intensity_word, partitive

#: Ce qu'elle se dit de la cause d'une humeur, par code (``Mark.cause``).
#: Générique : la section se montre à n'importe qui.
CAUSES: Mapping[str, str] = MappingProxyType({
    "retour": "Ça vient du retour de quelqu'un qui t'avait manqué.",
    "réponse": "Ça vient d'une réponse que tu attendais.",
    "attente comblée": "Ça vient d'une attente enfin comblée.",
    "digestion": "La nuit a apaisé des choses.",
    "promesse non tenue": "Ça vient d'une promesse que tu n'as pas tenue à temps.",
    "sans réponse": "Ça vient d'un message resté sans réponse.",
    "abouti": "Ça vient de quelque chose que tu as mené à bout.",
    "bloquée": "Ça vient de quelque chose sur quoi tu bloques.",
    "abandon": "Ça vient de quelque chose que tu as laissé tomber.",
    "objectif de projet abouti": "Ça vient d'un objectif de projet que tu as atteint.",
    "objectif de projet bloqué": "Ça vient d'un objectif de projet qui bloque.",
    "surprise": "Ça vient de quelqu'un qui t'a surprise.",
    "inquiétude": "Tu t'inquiètes pour quelqu'un.",
    "rêve": "Ça vient de ton rêve de cette nuit.",
    "lonely": "Personne ne t'a parlé depuis un moment.",
    "bored": "Il ne se passe pas grand-chose.",
    "elle y repense": "Ça vient d'une pensée qui te revient.",
    "exchange": "Ça vient de quelque chose qu'on t'a dit.",
    "revision": "Ça vient de quelque chose que tu croyais, et qui n'est plus vrai.",
    "missing": "Ça vient de quelqu'un qui te manque.",
    "concern": "Tu t'inquiètes pour quelqu'un.",
    "promise": "Ça vient d'une promesse à tenir.",
    "blocked": "Ça vient de quelque chose sur quoi tu bloques.",
    "signal": "Ça vient de quelque chose que tu as remarqué.",
    "email": "Ça vient d'un mail.",
    "rss": "Ça vient de quelque chose que tu as lu.",
    "camera": "Ça vient de quelque chose que tu as vu.",
})
UNKNOWN_CAUSE = "sans trop savoir pourquoi"
#: En deçà, sa dernière balise date d'« à l'instant ».
JUST_NOW_US = 3 * MINUTE


def cause_line(cause: str, person: str = "", current: str = "") -> str:
    """La cause, dite sans nommer personne : « votre échange » seulement si c'est
    avec la personne à qui elle parle maintenant."""
    if cause == "talk":
        if not person:
            return ""
        return "Ça vient de votre échange." if person == current else "Ça vient d'une autre conversation, tout à l'heure."
    if cause.startswith("forge:"):
        return "Ça vient d'une de tes apps."
    return CAUSES.get(cause, "")


def _under(parts: list[tuple[Emotion, float]], main: Emotion, *, ratio: float = 0.0, floor: float = 0.0) -> str:
    """La deuxième couleur, si elle compte : « Et en dessous, il y a un peu de colère. »"""
    others = [(e, w) for e, w in parts if e is not main]
    if not parts or not others or others[0][1] < floor or others[0][1] < ratio * parts[0][1]:
        return ""
    return f" Et en dessous, il y a un peu {partitive(others[0][0])}."


def mood(m: MoodReading, p: AffectParams, current: str = "") -> str:
    default = p.background
    gap = A.distance(m.position, m.home)
    if gap < p.rest_tolerance:
        if A.norm(m.fond) >= p.fond_said:
            # le reste d'une journée : trop peu pour la changer, assez pour la colorer
            residue = m.fond_emotion
            if residue is not default and residue is not Emotion.NEUTRAL:
                return (f"Ton humeur générale est à peu près comme d'habitude ({FR[default]}), avec un petit reste "
                        f"{partitive(residue)} de tout à l'heure.")
        return f"Ton humeur générale est {FR[default]}, comme d'habitude."
    word, adj = intensity_word(m.felt_intensity), FR[m.felt]
    cause = cause_line(m.cause, m.cause_person, current)
    if m.felt is default:
        if m.felt_intensity >= p.marked_intensity:
            base = f"Ton humeur générale est {adj}, nettement plus que d'habitude."
        else:
            base = f"Ton humeur générale est {word} {adj}, dans ta pente naturelle."
        cause = ""  # sa pente naturelle n'a pas besoin de cause
    elif cause:
        base = f"Ton humeur générale en ce moment est {word} {adj}, alors que normalement tu es plutôt {FR[default]}."
    else:
        base = (f"Ton humeur générale en ce moment est {word} {adj}, {UNKNOWN_CAUSE} — normalement tu es plutôt "
                f"{FR[default]}.")
    lingering = A.norm(m.fond) >= 0.6 * gap
    tail = " Ce n'est pas l'émotion d'un instant : ça traîne depuis un moment." if lingering else ""
    under = _under(A.blend(m.position, top_k=2, home=m.home), m.felt, ratio=0.4)
    return base + (f" {cause}" if cause else "") + tail + under


def _who(name: str) -> str:
    return f"« {name} »" if name else "cette personne"


def _tenderness(regard: float) -> str:
    return "beaucoup de tendresse" if regard >= 0.5 else "de la tendresse" if regard >= 0.25 else "de la sympathie"


def fond(s: StanceReading, p: AffectParams, name: str = "") -> str:
    """Ce que la relation a installé, s'il est chaleureux ou hostile (un chagrin
    partagé n'installe pas de froid), et l'attachement."""
    who = _who(name)
    attached = s.bond >= p.bond_said
    if s.anchor is not None:
        label, intensity = A.felt(s.anchor, s.reference)
        if intensity >= p.fond_min and label in HOSTILE:
            line = f"Envers {who}, au fond, tu restes plutôt {FR[label]} : c'est ce que vos échanges ont installé."
            return line + (f" Mais tu tiens à {who}." if attached else "")
        if intensity >= p.fond_min and A.valence(label) > 0 and s.regard > 0:
            if attached:
                return f"Tu tiens à {who}, et vos échanges ont installé {_tenderness(s.regard)}."
            return f"Envers {who}, vos échanges ont installé {_tenderness(s.regard)}."
    return f"Tu tiens à {who}." if attached else ""


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
        how = "en lui répondant" if s.declared_reply else "en lui écrivant"
        when = "À l'instant" if now and now - s.declared_at < JUST_NOW_US else "Tout à l'heure"
        word = intensity_word(s.declared.intensity)
        lines.append(f"{when}, {how}, tu étais {word} {FR[shown]}." + _under(under, shown, floor=0.25))
    elif not s.at_rest and s.felt_intensity >= 0.1 and s.felt is not Emotion.NEUTRAL:
        shown = s.felt
        lines.append(f"Avec {who}, en ce moment, tu te sens {intensity_word(s.felt_intensity)} {FR[shown]}."
                     + _under(under, shown, ratio=0.4))
    if s.anchored and shown is not None:
        lasting = " : ça ne passera pas en deux minutes." if s.lasting else "."
        lines.append(f"Ça fait plusieurs échanges de suite que tu te sens {FR[shown]} avec {who}{lasting}")
    installed = fond(s, p, name)
    if installed:
        lines.append(installed)
    return "\n".join(lines)
