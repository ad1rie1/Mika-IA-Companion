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

from configs.runtime import cfg_float

logger = logging.getLogger(__name__)

# Aligné sur ai.quota.estimate_tokens_from_chars (chars // 4).
# Configurables (``ai.calibration.*``) ; ces constantes restent le repli.
DEFAULT_CHARS_PER_TOKEN = 4.0
_ALPHA = 0.2
# Sous ce volume l'échantillon est du bruit (et le repli d'estimation du
# routeur serait circulaire). PAS un réglage : une mauvaise valeur ici est un
# bug de justesse de l'estimateur, pas une préférence.
_MIN_TOKENS_SAMPLE = 50


def _default_ratio() -> float:
    return cfg_float(
        "ai.calibration.default_chars_per_token", DEFAULT_CHARS_PER_TOKEN,
        mini=1.0, maxi=12.0,
    )


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
        alpha = cfg_float("ai.calibration.alpha", _ALPHA, mini=0.01, maxi=1.0)
        current = self._ratios.get(provider, _default_ratio())
        self._ratios[provider] = (1 - alpha) * current + alpha * sample

    def ratio(self, provider: str) -> float:
        return self._ratios.get(provider, _default_ratio())


calibration = TokenCalibration()
