"""Ce que son tempérament dit au modèle (section ``temperament``, ADR 0100).

La matrice de personnalité règle la physique de ses émotions (chaque faculté en dérive ses paramètres) ; mais c'est
le modèle qui écrit ses mots et choisit sa balise d'émotion. Sans le lui dire, une Mika anxieuse ou tsundere aurait
les balises et les répliques d'une Mika au milieu partout. Les traits nettement loin du milieu se disent donc en une
phrase chacun (``persona/voix.yaml``, ``self.temperament``), avec sa réaction quand on la blesse et sa défense quand
on la touche — des tendances, jamais un chiffre ni une obligation —, chacune avec la précision que l'opératrice
a pu écrire pour ce trait (« tu t'énerves quand on t'appelle poulet »). Au milieu partout, sans précision : rien.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.faculties.self.faculty import SELF, SelfState
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.phrasebook import phrase
from mika.vocab.temperament import PERSONALITY, Temperament

#: un trait se dit à 0,3 ou moins (« low »), à 0,7 ou plus (« high ») ; à 0,15 ou moins, à 0,85 ou plus, il est très
#: marqué et le dit (le banc du tempérament : sans cela, le modèle adoucissait les archétypes)
LOW, HIGH = 0.3, 0.7
VERY_LOW, VERY_HIGH = 0.15, 0.85


def _with(line: str, note: str) -> str:
    """Une phrase de trait et sa précision (« En particulier : … ») ; une précision seule, sans trait marqué."""
    note = note.strip().rstrip(".")
    if not note:
        return line
    return f"{line} {phrase('self.temperament.precisely', note=note)}" if line else \
        phrase("self.temperament.particular", note=note)


def told(t: Temperament) -> list[str]:
    """Les phrases de son tempérament, dans l'ordre de la matrice, chacune avec sa précision s'il y en a une
    (``notes``) ; une précision se dit même quand le trait est au milieu. ``[]`` au milieu partout, sans précision."""
    out = []
    for slider in PERSONALITY:
        value = getattr(t, slider)
        line = phrase(f"self.temperament.trait.{slider}.low") if value <= LOW else \
            phrase(f"self.temperament.trait.{slider}.high") if value >= HIGH else ""
        if line and (value <= VERY_LOW or value >= VERY_HIGH):
            line = f"{line} {phrase('self.temperament.marked')}"
        if said := _with(line, t.notes.get(slider, "")):
            out.append(said)
    for choice in ("reaction", "defense"):
        value = getattr(t, choice)
        line = phrase(f"self.temperament.trait.{choice}.{value}") if value else ""
        if said := _with(line, t.notes.get(choice, "")):
            out.append(said)
    return out


@SELF.section("temperament", zone=Zone.STABLE, episodes=CONVERSATIONAL, trim_rank=88,
              title=phrase("self.temperament.title"))
def _temperament(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    lines = told(s.persona.temperament)
    return "\n".join([phrase("self.temperament.lead"), *lines, phrase("self.temperament.tail")]) if lines else None
