"""Budget de contexte — la fenêtre du modèle déclaré dimensionne les couches.

Remplace la logique « plafonds fixes » par une allocation relative : chaque
couche du contexte reçoit une part de la fenêtre *utilisable* du modèle
résolu pour un rôle. Les plafonds fixes historiques deviennent des
**planchers** — le budget les dépasse, il ne les remplace pas.

    utilisable = fenêtre × usage_ratio − max_tokens (sortie) − outils − 5 %

``usage_ratio`` (défaut 0.5) existe parce que la fenêtre est un plafond, pas
une cible : viser la moitié borne le coût du pire tour et laisse l'autre
moitié comme marge de croissance intra-session avant compaction.

``budget_for`` renvoie ``None`` quand le rôle n'est pas configuré ou que le
modèle n'a pas de ``context_window`` déclaré : tous les consommateurs
retombent alors exactement sur les planchers d'aujourd'hui. Un helper de
dimensionnement ne lève jamais.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Parts de la fenêtre utilisable, par couche (voir docs/evolution-contexte.md).
L3_HISTORY_SHARE = 0.60      # fil de conversation (verbatim + résumé roulant)
L2_RELATIONAL_SHARE = 0.04   # profil, engagements, historique émotionnel
L5_RECALL_SHARE = 0.06       # rappel sémantique (souvenirs, connaissances, échanges)

_SAFETY_MARGIN = 0.05
_DEFAULT_MAX_TOKENS = 4096

# Plancher L3 en caractères — le cap historique du fil vivant, jamais franchi
# vers le bas (fenêtre minuscule ou config illisible).
_L3_FLOOR_CHARS = 4000
# Repli quand le CALCUL lui-même casse : généreux à dessein — un budget
# illisible ne doit ni élaguer l'historique ni déclencher une compaction à tort.
_L3_ERROR_CHARS = 40_000


@dataclass(frozen=True)
class ContextBudget:
    window_tokens: int
    usable_tokens: int
    chars_per_token: float

    @property
    def l3_history_tokens(self) -> int:
        return int(self.usable_tokens * L3_HISTORY_SHARE)

    @property
    def l2_relational_tokens(self) -> int:
        return int(self.usable_tokens * L2_RELATIONAL_SHARE)

    @property
    def l5_recall_tokens(self) -> int:
        return int(self.usable_tokens * L5_RECALL_SHARE)

    def l3_chars(self) -> int:
        return int(self.l3_history_tokens * self.chars_per_token)

    def l5_chars(self, floor: int = 4000) -> int:
        """Plafond du bloc mémoire — jamais sous le plancher historique."""
        return max(floor, int(self.l5_recall_tokens * self.chars_per_token))


def _usage_ratio() -> float:
    from configs.service import config_service

    try:
        value = float(config_service.get("ai.context.usage_ratio"))
        if 0.0 < value <= 1.0:
            return value
    except Exception:
        pass
    return 0.5


def default_window_tokens() -> int:
    """Fenêtre de repli quand le modèle déclaré n'en porte pas.

    Sert au compactor : sans elle, « pas de fenêtre déclarée » signifierait
    « pas de watermark », et le garde-fou de comptage (500 messages) pourrait
    laisser grossir le prompt sans limite de taille.
    """
    from configs.service import config_service

    try:
        value = int(config_service.get("ai.context.default_window"))
        if value > 0:
            return value
    except Exception:
        pass
    return 16384


def build_budget(
    window_tokens: int,
    *,
    max_tokens: int | None = None,
    tools_chars: int = 0,
    chars_per_token: float | None = None,
) -> ContextBudget:
    """Construit un budget à partir d'une fenêtre connue. Pur, testable."""
    ratio = chars_per_token or 4.0
    usable = int(window_tokens * _usage_ratio())
    usable -= max_tokens or _DEFAULT_MAX_TOKENS
    usable -= int(tools_chars / ratio)
    usable -= int(window_tokens * _SAFETY_MARGIN)
    return ContextBudget(
        window_tokens=window_tokens,
        usable_tokens=max(0, usable),
        chars_per_token=ratio,
    )


def conversation_l3_chars() -> int:
    """Budget L3 (fil de conversation) en caractères, pour le rôle CONVERSATION.

    **Une seule source pour deux consommateurs qui doivent s'accorder** : le
    watermark de la compaction (``memory/compaction.py``, qui décide *quand*
    replier le fil) et la borne de rendu de l'historique
    (``pipeline/prompt.py``, qui décide *combien* de verbatim part sur le
    réseau). S'ils divergeaient, la compaction viserait une taille et le
    rendu en enverrait une autre.

    Sans ``context_window`` déclaré, repli sur ``default_window_tokens()`` —
    jamais sous ``_L3_FLOOR_CHARS``. Ne lève jamais : un budget illisible
    rend un repli généreux (ne pas élaguer ni compacter à tort).
    """
    try:
        from ai.router import AIRole

        budget = budget_for(AIRole.CONVERSATION)
        if budget is None:
            budget = build_budget(default_window_tokens())
        return max(_L3_FLOOR_CHARS, budget.l3_chars())
    except Exception as exc:
        degradations.record("budget: L3 conversation", exc)
        return _L3_ERROR_CHARS


def budget_for(role, *, tools_chars: int = 0) -> ContextBudget | None:
    """Budget du modèle résolu pour ``role`` — None = planchers seuls.

    ``None`` dans deux cas légitimes (rôle non mappé, fenêtre non déclarée)
    et sur toute erreur : un helper de dimensionnement ne casse jamais un
    tour.
    """
    try:
        from ai.calibration import calibration
        from ai.router import UnconfiguredRoleError, ai_router

        try:
            provider_name, _, _, internal_name = ai_router.resolve(role)
        except UnconfiguredRoleError:
            return None
        entry = ai_router._get_declared_models().get(internal_name) or {}
        window = entry.get("context_window")
        if not window:
            return None
        return build_budget(
            int(window),
            max_tokens=entry.get("max_tokens"),
            tools_chars=tools_chars,
            chars_per_token=calibration.ratio(provider_name),
        )
    except Exception as exc:
        degradations.record("budget: resolution", exc)
        return None
