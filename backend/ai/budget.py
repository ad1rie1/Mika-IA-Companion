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

Le terme « outils » n'apparaît dans aucun des deux prompts mais part quand
même sur le réseau (~6 500 tokens pour les neuf modules embarqués). Il est
relevé passivement par ``tool_weight``, sur le modèle de ``ai.calibration``
— sans lui la soustraction était un terme mort et le budget L3 promettait
une place déjà occupée.

Enfin ``fit_turn`` est la dernière borne : chaque bloc porte son propre
plafond, mais leur SOMME n'était mesurée nulle part et un dépassement de la
fenêtre fait tronquer le provider **par la tête**, c'est-à-dire le préfixe
stable — la personnalité.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from configs.runtime import cfg_float, cfg_int
from utils.degradation import degradations

if TYPE_CHECKING:
    from ai.chat import ChatPrompt

logger = logging.getLogger(__name__)

# Parts de la fenêtre utilisable, par couche (voir docs/evolution-contexte.md).
# Configurables (``ai.context.*``) ; ces constantes restent le repli exact
# lorsque le registre est hors d'atteinte. Elles sont COUPLÉES : c'est leur
# somme qui engage la fenêtre, et un dépassement de 1.0 fait tronquer le
# provider par la tête — le hint de chacune le dit.
L3_HISTORY_SHARE = 0.60      # fil de conversation (verbatim + résumé roulant)
L2_RELATIONAL_SHARE = 0.04   # profil, engagements, historique émotionnel
# Rappel sémantique (souvenirs, connaissances, échanges). 0,06 → 0,04 : derrière
# un 200 k, la part donnait ~27 000 caractères (~7 k tokens) rendus dans le
# tour user, donc JAMAIS cachés — le poste non caché dominant d'un tour, plus
# que le préfixe entier relu depuis le cache. 0,04 laisse ~12 000 caractères,
# six fois ce qu'un petit modèle recevait, et un rappel reste un rappel.
L5_RECALL_SHARE = 0.04

_SAFETY_MARGIN = 0.05
# Sert à DEUX titres : défaut du champ de dataclass (évalué à l'import, donc
# non configurable — une valeur par défaut de champ est figée à la définition
# de la classe) et sortie réservée au moment du calcul (configurable).
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
    max_tokens: int = _DEFAULT_MAX_TOKENS
    tools_tokens: int = 0

    @property
    def l3_history_tokens(self) -> int:
        return int(self.usable_tokens * cfg_float(
            "ai.context.l3_history_share", L3_HISTORY_SHARE, mini=0.0, maxi=1.0,
        ))

    @property
    def l2_relational_tokens(self) -> int:
        return int(self.usable_tokens * cfg_float(
            "ai.context.l2_relational_share", L2_RELATIONAL_SHARE,
            mini=0.0, maxi=1.0,
        ))

    @property
    def l5_recall_tokens(self) -> int:
        return int(self.usable_tokens * cfg_float(
            "ai.context.l5_recall_share", L5_RECALL_SHARE, mini=0.0, maxi=1.0,
        ))

    def l3_chars(self) -> int:
        return int(self.l3_history_tokens * self.chars_per_token)

    def l5_chars(self, floor: int = 4000) -> int:
        """Plafond du bloc mémoire — jamais sous le plancher historique."""
        return max(floor, int(self.l5_recall_tokens * self.chars_per_token))

    def window_room(self) -> int:
        """Place physique restante pour le TEXTE du prompt, en tokens.

        Distinct de ``usable_tokens``, et c'est délibéré : ``usage_ratio``
        (0.5) dit « la fenêtre est un plafond, pas une cible » et dimensionne
        les parts L3/L5/L2. Le franchir coûte des tokens ; franchir *ceci*
        fait tronquer le provider par la tête. Une coupe visant
        ``usable_tokens`` viderait le prompt à chaque tour sur une install
        par défaut (fenêtre de repli 16 384 : ``usable_tokens`` tombe à 0 dès
        que les outils sont comptés), y compris derrière un modèle 200k dont
        l'opérateur n'a simplement pas déclaré la fenêtre.
        """
        margin = int(self.window_tokens * _safety_margin())
        return max(0, self.window_tokens - self.max_tokens - self.tools_tokens - margin)

    def window_overflow(self, prompt_tokens: int) -> int:
        return max(0, prompt_tokens - self.window_room())


def _safety_margin() -> float:
    return cfg_float("ai.context.safety_margin", _SAFETY_MARGIN, mini=0.0, maxi=0.5)


def _usage_ratio() -> float:
    from configs.service import config_service

    try:
        value = float(config_service.get("ai.context.usage_ratio"))
        if 0.0 < value <= 1.0:
            return value
    except Exception:
        pass
    return 0.5


# Fenêtres connues, par PRÉFIXE d'identifiant de modèle.
#
# `context_window` est un champ facultatif de la ligne modèle, et une install
# réelle le laisse vide : le budget rendait alors `None` et TOUT retombait sur
# les planchers de 16 384 tokens — un modèle à 256 k était piloté comme un
# modèle à 16 k, l'historique élagué, le rappel bridé à cinq souvenirs. Comme
# rien ne le signalait, la capacité payée n'était simplement jamais utilisée.
#
# Les valeurs sont volontairement PRUDENTES (au niveau ou en dessous de la
# fenêtre annoncée) : sous-estimer ne coûte que du contexte inutilisé, alors
# que surestimer fait tronquer le provider PAR LA TÊTE, c'est-à-dire par la
# personnalité. Une valeur déclarée sur la ligne modèle gagne toujours.
_KNOWN_WINDOWS: tuple[tuple[str, int], ...] = (
    ("gemma4", 262_144),
    ("claude-", 200_000),
    ("gpt-oss", 131_072),
    ("kimi-k", 131_072),
    ("glm-", 131_072),
    ("qwen3", 131_072),
    ("deepseek-v4", 131_072),
    ("deepseek-r1", 65_536),
    ("llama3", 131_072),
    ("mistral", 32_768),
)


def known_window_for(model_id: str) -> int | None:
    """Fenêtre connue pour cet identifiant de modèle, ou ``None``.

    Repli seulement : la ligne modèle reste la source de vérité, et un
    identifiant inconnu ne se voit rien inventer.
    """
    identifiant = (model_id or "").strip().lower()
    if not identifiant:
        return None
    for prefixe, fenetre in _KNOWN_WINDOWS:
        if identifiant.startswith(prefixe):
            return fenetre
    return None


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
    output_tokens = max_tokens or cfg_int(
        "ai.context.default_max_tokens", _DEFAULT_MAX_TOKENS, mini=1,
    )
    tools_tokens = int(tools_chars / ratio)
    usable = int(window_tokens * _usage_ratio())
    usable -= output_tokens
    usable -= tools_tokens
    usable -= int(window_tokens * _safety_margin())
    return ContextBudget(
        window_tokens=window_tokens,
        usable_tokens=max(0, usable),
        chars_per_token=ratio,
        max_tokens=output_tokens,
        tools_tokens=tools_tokens,
    )


def tools_prompt_chars(tools: list) -> int:
    """Poids en caractères des déclarations d'outils, telles qu'envoyées.

    Nom + description + schéma JSON sérialisé — la charge que chaque provider
    re-poste à chaque tour de la boucle d'outils. Défensif : un objet outil
    exotique ne compte simplement pas, il ne casse jamais un dimensionnement.
    """
    total = 0
    for t in tools or []:
        try:
            total += len(getattr(t, "name", "") or "")
            total += len(getattr(t, "description", "") or "")
            total += len(json.dumps(t.to_json_schema(), ensure_ascii=False))
        except Exception:
            continue
    return total


class ToolWeight:
    """Relevé passif du poids des déclarations d'outils, par rôle.

    Même parti que ``ai.calibration`` : le routeur connaît déjà la valeur à
    chaque appel outillé (il la passe au contrôle de quota), donc on la
    retient plutôt que de la recalculer ailleurs. RAM seule, portée process.
    Un rôle jamais mesuré vaut 0, c'est-à-dire le comportement d'avant.
    """

    def __init__(self):
        self._chars: dict[str, int] = {}

    def note(self, role_value: str, chars: int) -> None:
        if not role_value or chars is None or chars < 0:
            return
        self._chars[str(role_value)] = int(chars)

    def chars_for(self, role_value: str) -> int:
        return self._chars.get(str(role_value), 0)


tool_weight = ToolWeight()


def conversation_l3_chars(tools_chars: int | None = None, role=None) -> int:
    """Budget L3 (fil de conversation) en caractères, pour le rôle du tour.

    ``role`` à ``None`` = ``CONVERSATION`` (le compactor, qui ne sait pas si
    le prochain tour sera outillé) ; le constructeur du prompt passe le rôle
    qui servira réellement (``CONVERSATION_TOOLS`` dès qu'il y a des outils).

    **Une seule source pour deux consommateurs qui doivent s'accorder** : le
    watermark de la compaction (``memory/compaction.py``, qui décide *quand*
    replier le fil) et la borne de rendu de l'historique
    (``pipeline/prompt.py``, qui décide *combien* de verbatim part sur le
    réseau). S'ils divergeaient, la compaction viserait une taille et le
    rendu en enverrait une autre.

    Sans ``context_window`` déclaré, repli sur ``default_window_tokens()`` —
    jamais sous ``_L3_FLOOR_CHARS``. Ne lève jamais : un budget illisible
    rend un repli généreux (ne pas élaguer ni compacter à tort).

    ``tools_chars`` à ``None`` (défaut) consulte le relevé du rôle ; un ``0``
    explicite dit « ce tour ne porte pas d'outils ».
    """
    try:
        from ai.router import AIRole

        role = role or AIRole.CONVERSATION
        if tools_chars is None:
            tools_chars = tool_weight.chars_for(getattr(role, "value", str(role)))
        budget = budget_for(role, tools_chars=tools_chars)
        if budget is None:
            budget = build_budget(default_window_tokens(), tools_chars=tools_chars)
        plancher = cfg_int("ai.context.l3_floor_chars", _L3_FLOOR_CHARS, mini=1)
        return max(plancher, budget.l3_chars())
    except Exception as exc:
        degradations.record("budget: L3 conversation", exc)
        return _L3_ERROR_CHARS


def budget_for(role, *, tools_chars: int | None = None) -> ContextBudget | None:
    """Budget du modèle résolu pour ``role`` — None = planchers seuls.

    ``None`` dans deux cas légitimes (rôle non mappé, fenêtre non déclarée)
    et sur toute erreur : un helper de dimensionnement ne casse jamais un
    tour.

    ``tools_chars=None`` (défaut) prend le poids relevé pour ce rôle ; un
    ``0`` explicite reste « pas d'outils ».
    """
    try:
        from ai.calibration import calibration
        from ai.router import UnconfiguredRoleError, ai_router

        if tools_chars is None:
            tools_chars = tool_weight.chars_for(getattr(role, "value", str(role)))
        try:
            provider_name, _, _, internal_name = ai_router.resolve(role)
        except UnconfiguredRoleError:
            return None
        entry = ai_router._get_declared_models().get(internal_name) or {}
        window = entry.get("context_window") or known_window_for(
            entry.get("model_id") or "",
        )
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


# Ordre de sacrifice des couches volatiles, du plus jetable au plus cher, avec
# le plancher en caractères sous lequel une couche n'est plus coupée (0 = le
# bloc disparaît). La mémoire ferme la marche : c'est la couche que la
# personne en face a des chances de tester au tour suivant. Jamais touchés :
# ``system_stable`` (personnalité + self-concept + identité, exactement ce que
# la troncature par la tête détruit), le message courant, et l'historique —
# déjà borné une fois par ``conversation_l3_chars`` au build, et une seconde
# autorité sur la même couche casserait la source unique documentée plus haut.
_TRIM_ORDER: tuple[tuple[str, int], ...] = (
    ("module_context", 0),
    ("journal_context", 0),
    ("dream_context", 0),
    ("rumination_context", 0),
    ("travaux_context", 0),
    ("circadian_context", 0),
    ("fatigue_fog", 0),
    ("user_mood_hint", 0),
    ("emotion_context", 0),
    ("note_de_focus", 0),
    ("conversation_summary", 2000),
    ("person_context", 400),
    ("project_context", 600),
    ("memory_context", 1200),
)

_TRIM_MARK = " …[coupé faute de place]"


@dataclass(frozen=True)
class TurnFit:
    prompt_tokens_before: int
    prompt_tokens_after: int
    window_room: int
    # 0 = le tour tient dans la fenêtre.
    overflow_tokens: int
    # Dépassement de ``usable_tokens`` : rapporté, jamais agi (voir
    # ``ContextBudget.window_room``).
    soft_overflow_tokens: int
    trimmed: tuple[str, ...]


def measure_turn(prompt: "ChatPrompt", *, chars_per_token: float = 4.0) -> int:
    """Poids en tokens de ce qu'un tour envoie réellement.

    Mesuré sur le rendu, pas sur les champs : le clip par message, le
    marqueur de reprise, l'en-tête de résumé, l'enveloppe ETAT INTERNE et
    l'étiquette de locuteur sont alors comptés sans deuxième comptabilité à
    tenir à jour.
    """
    chars = len(prompt.system_stable)
    for m in prompt.chat_messages():
        chars += len(m["content"])
    return int(chars / (chars_per_token or 4.0))


def _clip_block(value: str, floor: int) -> str:
    if floor <= 0:
        return ""
    if len(value) <= floor:
        return value
    return value[: max(0, floor - len(_TRIM_MARK))].rstrip() + _TRIM_MARK


def _rendered_volatile(blocks) -> str:
    return "\n\n".join(b.render() for b in blocks if b.value)


def fit_turn(
    prompt: "ChatPrompt", budget: ContextBudget | None,
) -> tuple["ChatPrompt", TurnFit]:
    """Dernière borne avant l'envoi : ramène le tour dans la fenêtre.

    Pure et sans effet de bord — le ``ChatPrompt`` d'entrée n'est jamais muté,
    une copie coupée est renvoyée. Ne lève jamais : sur incident le tour part
    tel quel, un dimensionnement ne casse pas une conversation.

    Sans ``volatile_blocks`` (appelant pas encore câblé), seul le résumé peut
    bouger : couper à l'aveugle dans ``system_volatile`` déjà rendu laisserait
    un en-tête sans sa fin.
    """
    ratio = getattr(budget, "chars_per_token", 4.0) or 4.0
    try:
        before = measure_turn(prompt, chars_per_token=ratio)
        if budget is None:
            return prompt, TurnFit(before, before, 0, 0, 0, ())

        room = budget.window_room()
        summary = prompt.conversation_summary
        blocks = list(prompt.volatile_blocks or [])
        index_of = {b.field: i for i, b in enumerate(blocks)}
        has_blocks = bool(blocks)

        def rebuild() -> "ChatPrompt":
            changes = {"conversation_summary": summary}
            if has_blocks:
                changes["volatile_blocks"] = blocks
                changes["system_volatile"] = _rendered_volatile(blocks)
            return dataclasses.replace(prompt, **changes)

        current = before
        trimmed: list[str] = []
        result = prompt
        for name, floor in _TRIM_ORDER:
            if current <= room:
                break
            if name == "conversation_summary":
                if not summary or len(summary) <= floor:
                    continue
                summary = _clip_block(summary, floor)
            else:
                position = index_of.get(name)
                if position is None:
                    continue
                block = blocks[position]
                if not block.value or len(block.value) <= floor:
                    continue
                blocks[position] = dataclasses.replace(
                    block, value=_clip_block(block.value, floor),
                )
            trimmed.append(name)
            result = rebuild()
            current = measure_turn(result, chars_per_token=ratio)

        fit = TurnFit(
            prompt_tokens_before=before,
            prompt_tokens_after=current,
            window_room=room,
            overflow_tokens=max(0, current - room),
            soft_overflow_tokens=max(0, current - budget.usable_tokens),
            trimmed=tuple(trimmed),
        )
        if trimmed or fit.overflow_tokens:
            # Pas `degradations.record` : c'est un état attendu (contexte trop
            # gros pour la fenêtre déclarée), pas une exception avalée, et le
            # registre est réservé aux except.
            logger.warning(
                "Tour trop large pour la fenêtre : %d tokens pour %d de place "
                "(couches réduites : %s). Leviers : réduire "
                "`ai.conversation_tool_modules`, ou déclarer un `context_window` "
                "plus grand sur le modèle du rôle conversation.",
                before, room, ", ".join(trimmed) or "aucune",
            )
        return result, fit
    except Exception as exc:
        degradations.record("budget: borne globale du tour", exc)
        return prompt, TurnFit(0, 0, 0, 0, 0, ())
