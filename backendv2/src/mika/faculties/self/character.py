"""Ce que son tempérament dit au modèle (ADR 0100) : dans sa persona, partout où elle est injectée.

La matrice de personnalité règle la physique de ses émotions (chaque faculté en dérive ses paramètres) ; mais c'est
le modèle qui écrit ses mots et choisit sa balise d'émotion. Sans le lui dire, une Mika anxieuse ou tsundere aurait
les balises et les répliques d'une Mika au milieu partout. Tous ses traits se disent donc, rangés par famille, chacun
avec sa mesure (« Introspection : 90 % — tu repenses longuement… ») : le modèle dose d'après elle, et une mesure de
75 % ne se lit pas comme une de 95 %. La phrase vient de ``persona/voix.yaml`` (``self.temperament``) : celle du bas
à 40 % ou moins, celle du haut à 60 % ou plus, « comme la plupart des gens » entre les deux ; très marqué, il le dit.
S'y ajoutent son humeur de fond, sa réaction quand on la blesse et sa défense quand on la touche. La précision que
l'opératrice a pu écrire pour un trait (« tu t'énerves quand on t'appelle poulet ») suit sa phrase, sans la remplacer.
Des tendances, jamais une obligation ; les mesures sont pour elle seule. Le bloc fait partie de sa persona
(``persona.render``, dans ses deux profondeurs) : ses répliques, ses initiatives, ses murmures, son travail, ses
brouillons, son journal, ses rêves et son récit le lisent tous.
"""

from __future__ import annotations

from mika.kernel import forms
from mika.vocab import temperament as T
from mika.vocab.affect import FR
from mika.vocab.phrasebook import phrase

#: un trait se dit avec sa phrase du bas à 40 % ou moins, du haut à 60 % ou plus ; entre les deux, comme la plupart
#: des gens. À 15 % ou moins, à 85 % ou plus, il est très marqué et le dit (le banc du tempérament : sans cela, le
#: modèle adoucissait les archétypes)
LOW, HIGH = 0.4, 0.6
VERY_LOW, VERY_HIGH = 0.15, 0.85
_EPS = 1e-9
#: les familles de la matrice et le nom de leur titre (``self.temperament.family.*``)
FAMILIES = {T.FEEL: "feel", T.SHOW: "show", T.ACT: "act", T.OTHERS: "others", T.SELF: "self", T.BODY: "body"}
#: ses traits dans l'ordre de la matrice (famille, puis rang dans la famille) — ses précisions mises à part
_FIELDS = tuple(f for f in forms.describe(T.Temperament) if f.group in FAMILIES)


def _lower(sentence: str) -> str:
    return sentence[:1].lower() + sentence[1:]


def _with(line: str, note: str) -> str:
    """Une ligne et la précision de son trait (« En particulier : … ») à sa suite."""
    note = note.strip().rstrip(".")
    return f"{line} {phrase('self.temperament.precisely', note=note)}" if note else line


def sentence(slider: str, value: float) -> str:
    """Ce que veut dire ce trait chez elle, à cette mesure."""
    if value <= LOW + _EPS:
        said = phrase(f"self.temperament.trait.{slider}.low")
    elif value >= HIGH - _EPS:
        said = phrase(f"self.temperament.trait.{slider}.high")
    else:
        return phrase("self.temperament.middle")
    if value <= VERY_LOW + _EPS or value >= VERY_HIGH - _EPS:
        said = f"{said} {phrase('self.temperament.marked')}"
    return said


def told(t: T.Temperament) -> list[str]:
    """Son tempérament ligne par ligne, dans l'ordre de la matrice : le titre de chaque famille, puis chacun de ses
    traits avec sa mesure et sa phrase, son humeur de fond, sa réaction, sa défense — chacun suivi de sa précision
    s'il y en a une (``notes``)."""
    out: list[str] = []
    family = ""
    for field in _FIELDS:
        if field.group != family:
            family = field.group
            out.append(phrase(f"self.temperament.family.{FAMILIES[family]}"))
        key = field.path
        value = getattr(t, key)
        if key == "background":
            line = phrase("self.temperament.background", feeling=FR[value])
        elif key in ("reaction", "defense"):
            line = phrase(f"self.temperament.trait.{key}.{value or 'none'}")
        else:
            line = phrase("self.temperament.line", name=phrase(f"self.temperament.name.{key}"),
                          pct=round(float(value) * 100), sentence=_lower(sentence(key, float(value))))
        out.append(f"- {_with(line, t.notes.get(key, ''))}")
    return out


def temperament_text(t: T.Temperament) -> str:
    """Le bloc de sa persona qui dit son tempérament : son titre, ce que veulent dire les mesures, chacun de ses
    traits, et que ce sont des tendances."""
    return "\n".join([phrase("self.temperament.title"), phrase("self.temperament.lead"), *told(t),
                      phrase("self.temperament.tail")])
