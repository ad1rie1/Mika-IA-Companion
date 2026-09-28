"""Ce que le prompt lui dit de ses émotions — un ressenti, jamais un chiffre."""

from __future__ import annotations

from mika.contracts.affect import MoodReading, StanceReading
from mika.faculties.affect.params import AffectParams
from mika.vocab import affect as A
from mika.vocab.affect import FR, Emotion, intensity_word

ANCHORED_LINE = "Cette émotion envers cette personne est bien ancrée, elle ne va pas s'estomper facilement."


def _nuance(parts: list[tuple[Emotion, float]]) -> str:
    if len(parts) < 2 or parts[1][1] < 0.4 * parts[0][1]:
        return ""
    return f" Mais il y a aussi une nuance de {FR[parts[1][0]]} en sous-texte — ton humeur n'est pas mono-couleur."


def mood(m: MoodReading, p: AffectParams) -> str:
    default = p.background
    gap = A.distance(m.position, m.home)
    if gap < p.rest_tolerance:
        base = f"Ton humeur générale est {FR[default]}, comme d'habitude."
    elif m.felt is not default:
        base = (f"Ton humeur générale en ce moment est {intensity_word(m.felt_intensity)} {FR[m.felt]}, "
                f"alors que normalement tu es plutôt {FR[default]}.")
    elif m.felt_intensity >= p.marked_intensity:
        base = f"Ton humeur générale est {FR[m.felt]}, nettement plus que d'habitude."
    else:
        base = f"Ton humeur générale est {intensity_word(m.felt_intensity)} {FR[m.felt]}, dans ta pente naturelle."
    return base + _nuance(A.blend(m.position, top_k=2, home=m.home))


def fond(s: StanceReading, common: A.Vec3, p: AffectParams) -> str:
    """Le fond installé envers quelqu'un, s'il se distingue du repos commun."""
    if s.anchor is None:
        return ""
    label, intensity = A.felt(s.home, common)
    if intensity < p.fond_min or label is Emotion.NEUTRAL:
        return ""
    return (f"Envers cette personne, rien de particulier sur le moment, mais ton fond est plutôt {FR[label]} : "
            "c'est ce que vos échanges ont installé.")


def stance(s: StanceReading, common: A.Vec3, p: AffectParams) -> str:
    """Rien à dire d'une posture au repos (un inconnu n'a pas de « stance »),
    sauf un fond installé ; une déclaration fraîche parle pour elle-même."""
    if s.declared is None and s.at_rest:
        return fond(s, common, p)
    if s.declared is not None:
        label, intensity = s.declared.emotion, s.declared.intensity
    else:
        label, intensity = s.felt, s.felt_intensity
        if A.distance(s.position, s.home) < p.rest_tolerance:
            intensity = 0.0
        if intensity < 0.1:
            return fond(s, common, p) or "Tu n'as pas de sentiment particulier envers cette personne."
    line = f"Envers cette personne, tu te sens {intensity_word(intensity)} {FR[label]}."
    others = [(e, w) for e, w in A.blend(s.position, top_k=3, home=s.home) if e is not label]
    if s.declared is not None:
        if others and others[0][1] >= 0.25:
            line += f" Et en dessous, tu te sens aussi un peu {FR[others[0][0]]} — ton humeur n'est pas mono-couleur."
    else:
        line += _nuance(A.blend(s.position, top_k=2, home=s.home))
    if s.anchored:
        line += "\n" + ANCHORED_LINE
    return line
