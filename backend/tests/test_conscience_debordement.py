"""Les portes de la conscience lisent l'intensité de débordement.

``GlobalMood.intensity`` rapporte la norme de la position à celle de
l'ancre la plus longue (``excited``, 1,245) : ``sad`` à son ancre pleine
valait 0,73, sous la porte 0,7 du facteur 3 et sous le plancher 0,55 de la
détresse — deux portes que seule l'excitation franchissait. Le contexte de
décision porte désormais ``overflow_intensity``, normalisée sur l'ancre la
plus proche.
"""

from __future__ import annotations

from types import SimpleNamespace

from conscience.engine import _intensite_de_debordement
from emotion.dynamics import OscillatorState
from emotion.pad import EMOTION_ANCHORS
from emotion.state import GlobalMood
from emotion.types import Emotion


def _humeur(emotion: Emotion, fraction: float = 1.0) -> GlobalMood:
    ancre = EMOTION_ANCHORS[emotion]
    position = tuple(c * fraction for c in ancre)
    return GlobalMood(dynamic=OscillatorState(position=position))


class TestIntensiteDeDebordement:

    def test_la_tristesse_pleine_franchit_la_porte(self):
        glob = _humeur(Emotion.SAD)
        assert glob.intensity < 0.75            # l'ancienne lecture, sous 0,7 ? non : 0,73
        assert _intensite_de_debordement(glob) >= 0.99

    def test_la_frustration_pleine_franchit_aussi(self):
        glob = _humeur(Emotion.FRUSTRATED)
        assert glob.intensity < 0.7             # l'ancienne lecture ne passait pas
        assert _intensite_de_debordement(glob) >= 0.7

    def test_une_tristesse_moyenne_atteint_le_plancher_de_detresse(self):
        glob = _humeur(Emotion.SAD, fraction=0.6)
        assert _intensite_de_debordement(glob) >= 0.55

    def test_un_double_sans_overflow_retombe_sur_l_intensite(self):
        """Les doubles de test construisent une humeur minimale."""
        assert _intensite_de_debordement(SimpleNamespace(intensity=0.42)) == 0.42
        assert _intensite_de_debordement(SimpleNamespace()) == 0.0

    def test_un_overflow_non_numerique_est_ignore(self):
        faux = SimpleNamespace(intensity=0.3, overflow_intensity="n/a")
        assert _intensite_de_debordement(faux) == 0.3
