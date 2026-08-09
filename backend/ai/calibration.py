"""Calibration continue chars → tokens, par provider.

Pas de tokenizer embarqué (lourd, faux par modèle) : le routeur reçoit déjà
l'usage réel de chaque réponse, donc on entretient une moyenne mobile
exponentielle de ``caractères envoyés / tokens facturés`` par provider.
Auto-correcte en quelques appels après le boot ; RAM seule (la persister
n'achèterait rien). Le français tourne autour de 3,4–3,9 car./token selon le
modèle — l'écart avec l'heuristique fixe « 4 » justifie la mesure.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Aligné sur ai.quota.estimate_tokens_from_chars (chars // 4).
DEFAULT_CHARS_PER_TOKEN = 4.0
_ALPHA = 0.2
# Sous ce volume l'échantillon est du bruit (et le repli d'estimation du
# routeur serait circulaire).
_MIN_TOKENS_SAMPLE = 50


class TokenCalibration:
    def __init__(self):
        self._ratios: dict[str, float] = {}

    def record(self, provider: str, prompt_chars: int, tokens_in: int) -> None:
        if not provider or tokens_in < _MIN_TOKENS_SAMPLE or prompt_chars <= 0:
            return
        sample = prompt_chars / tokens_in
        # Un échantillon aberrant (usage incluant du cache multi-itérations
        # face à un prompt court, etc.) ne doit pas déformer la moyenne.
        if not (1.0 <= sample <= 12.0):
            return
        current = self._ratios.get(provider, DEFAULT_CHARS_PER_TOKEN)
        self._ratios[provider] = (1 - _ALPHA) * current + _ALPHA * sample

    def ratio(self, provider: str) -> float:
        return self._ratios.get(provider, DEFAULT_CHARS_PER_TOKEN)


calibration = TokenCalibration()
