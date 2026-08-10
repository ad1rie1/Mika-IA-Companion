"""Compaction conversationnelle — le résumé roulant du fil, hors tour.

La fenêtre du modèle est un cache, jamais une archive : quand le fil vivant
dépasse sa part de budget (L3), les segments les plus anciens sont repliés
en résumé par un petit LLM (rôle ``COMPACTION``), en arrière-plan. Rien
n'est perdu : le verbatim reste en SQL (étage 0) et trouvable dans l'index
épisodique (étage 1), et **on ne replie jamais au-delà du checkpoint du
consolidateur** — l'extraction de souvenirs a toujours eu lieu avant qu'un
message quitte le contexte vif.

Garde-fous :
- plancher de récence : les ``memory.compaction_keep_last`` derniers
  messages restent toujours en clair ;
- hystérésis : déclenchement au watermark haut (part L3), repli jusqu'à la
  moitié — la réécriture du cache de la zone messages reste rare ;
- échec LLM = no-op (le buffer absorbe, retry au tick suivant) ; rôle non
  mappé = compaction désactivée, le garde-fou de comptage borne seul ;
- **aucun appel LLM dans le tour** : c'est une boucle de fond.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from configs.runtime import cfg_float, cfg_int
from utils.degradation import degradations
from utils.periodic import PeriodicLoop

logger = logging.getLogger(__name__)

# Les trois valeurs réglables ci-dessous (``memory.compaction_*``) restent
# écrites ici comme REPLI : la valeur servie quand le registre est hors
# d'atteinte (import avant `migrate`, base verrouillée, collecte des tests).
# Part du texte replié qui survit dans le résumé (estimation du repli).
SURVIVAL_FACTOR = 0.15
# Le résumé lui-même ne doit jamais manger la part du fil vivant.
SUMMARY_TARGET_CHARS = 6000
# Comptage du poids d'un message : aligné sur le clip de rendu de ChatPrompt.
_MSG_WEIGHT_CAP = 4000
_LLM_TIMEOUT_S = 45.0

# Plancher de sanité du nouveau résumé. « Non vide » ne suffisait pas : un
# refus d'une phrase du petit modèle REMPLACE des semaines de contexte
# compressé, et comme le curseur avance dans la foulée, la matière repliée
# n'est jamais re-résumée.
MIN_SUMMARY_CHARS = 120       # en dessous, ce n'est pas un résumé
MIN_PREVIOUS_RATIO = 0.35     # un nouveau résumé peut condenser, pas évaporer
MIN_FOLD_RATIO = 0.02         # très permissif face à SURVIVAL_FACTOR


class DegenerateSummary(RuntimeError):
    """Le modèle a rendu autre chose qu'un résumé."""


class ConversationCompactor:
    def __init__(self, interval_seconds: int | None = None):
        from configs.service import config_service

        if interval_seconds is None:
            try:
                interval_seconds = int(config_service.get("memory.compaction_interval"))
            except Exception:
                interval_seconds = 120
        self.interval = interval_seconds
        self._loop = PeriodicLoop("Compaction", self._tick, self.interval)

    async def start(self):
        await self._loop.start(self.interval)
        logger.info("ConversationCompactor démarré (période=%ds)", self.interval)

    async def stop(self):
        await self._loop.stop()

    # ── Tick ─────────────────────────────────────────────────────

    async def _tick(self):
        try:
            await self.compact_if_needed()
        except Exception as exc:
            degradations.record("compaction: tick", exc)

    async def compact_if_needed(self) -> bool:
        """Une passe : mesure → sélection → LLM → repli. False = rien fait."""
        from memory.manager import memory_manager

        if memory_manager.conversation is None:
            return False

        keep_last = self._keep_last()
        buffer = memory_manager.get_conversation_context()
        if len(buffer) < keep_last + 5:
            return False

        summary = memory_manager.get_conversation_summary()
        high = self._high_watermark_chars()
        measured = len(summary) + sum(self._weight(m) for m in buffer)
        if measured <= high:
            return False

        checkpoint = await self._extraction_checkpoint()
        fold = self._select_fold_slice(
            buffer, checkpoint=checkpoint, keep_last=keep_last,
            measured=measured, low=high // 2,
        )
        if not fold:
            # Checkpoint en retard ou plancher de récence : on réessaie plus
            # tard — ne jamais résumer ce qui n'a pas encore été extrait.
            return False

        try:
            new_summary = await self._summarize(summary, fold)
        except DegenerateSummary as exc:
            degradations.record("compaction: resume degenere", exc)
            return False
        if not new_summary:
            return False

        ok = await memory_manager.fold_into_summary(new_summary, fold[-1]["id"])
        if ok:
            logger.info(
                "Compaction: %d message(s) replié(s) (≈%d car.) → résumé %d car.",
                len(fold), sum(self._weight(m) for m in fold), len(new_summary),
            )
        return ok

    # ── Mesure & sélection (purs, testables) ─────────────────────

    @staticmethod
    def _weight(msg: dict) -> int:
        return min(len(msg.get("content") or ""), _MSG_WEIGHT_CAP)

    @staticmethod
    def _summary_floor(previous: str, folded_chars: int) -> int:
        """Longueur en dessous de laquelle la sortie n'est pas un résumé."""
        return max(
            MIN_SUMMARY_CHARS,
            int(MIN_PREVIOUS_RATIO * len(previous)),
            int(MIN_FOLD_RATIO * folded_chars),
        )

    def _select_fold_slice(
        self, buffer: list[dict], *, checkpoint: int, keep_last: int,
        measured: int, low: int,
    ) -> list[dict]:
        """Les plus anciens messages repliables, jusqu'à redescendre à ``low``.

        Repliable = porte un id ≤ checkpoint d'extraction, hors plancher de
        récence. Le buffer est chronologique : le premier message non
        repliable arrête la sélection (pas de trous dans le résumé).
        """
        survie = cfg_float(
            "memory.compaction_survival_factor", SURVIVAL_FACTOR,
            mini=0.01, maxi=1.0,
        )
        fold: list[dict] = []
        projected = measured
        for m in buffer[:-keep_last] if keep_last else buffer:
            mid = m.get("id")
            if not isinstance(mid, int) or mid > checkpoint:
                break
            fold.append(m)
            projected -= int((1 - survie) * self._weight(m))
            if projected <= low:
                break
        return fold

    def _high_watermark_chars(self) -> int:
        """Part L3 en caractères — la MÊME borne que le rendu de l'historique.

        Source unique (``ai.budget.conversation_l3_chars``) : le watermark qui
        décide *quand* replier et la borne qui décide *combien* de verbatim
        part sur le réseau ne doivent jamais diverger.
        """
        from ai.budget import conversation_l3_chars

        return conversation_l3_chars()

    def _keep_last(self) -> int:
        from configs.service import config_service

        try:
            return int(config_service.get("memory.compaction_keep_last"))
        except Exception:
            return 30

    @staticmethod
    async def _extraction_checkpoint() -> int:
        from memory.models import ConsolidationLog

        try:
            return await sync_to_async(
                lambda: ConsolidationLog.objects.order_by("-pk")
                .values_list("last_message_id", flat=True)
                .first()
                or 0
            )()
        except Exception as exc:
            degradations.record("compaction: lecture checkpoint", exc)
            return 0

    # ── L'appel LLM ──────────────────────────────────────────────

    _SYSTEM_PROMPT = (
        "Tu es le processus de condensation de la mémoire conversationnelle "
        "de {name}. On te donne (1) le résumé existant du début de la "
        "conversation, (2) une tranche de messages plus récents à y replier. "
        "Produis le NOUVEAU résumé complet qui REMPLACE l'ancien.\n"
        "Règles : conserve les faits, prénoms, dates, décisions, engagements "
        "pris ou reçus, la tonalité relationnelle et son évolution, les "
        "questions restées ouvertes ; garde l'ordre chronologique ; écris en "
        "français, « {name} » pour elle et « Lui » pour l'interlocuteur ; "
        "maximum {max_chars} caractères ; aucun commentaire, aucun en-tête — "
        "uniquement le résumé."
    )

    async def _summarize(self, prev_summary: str, fold: list[dict]) -> str | None:
        from ai.router import AIRole, UnconfiguredRoleError, ai_router
        from config.personality import personality

        cible = cfg_int(
            "memory.compaction_summary_target_chars", SUMMARY_TARGET_CHARS,
            mini=500, maxi=30000,
        )
        budget = cfg_float(
            "memory.compaction_llm_timeout", _LLM_TIMEOUT_S, mini=5.0, maxi=600.0,
        )

        lines = [
            "RÉSUMÉ EXISTANT :",
            prev_summary or "(aucun — début de conversation)",
            "",
            "MESSAGES À REPLIER :",
        ]
        for m in fold:
            label = "Mika" if m.get("role") == "assistant" else "Lui"
            lines.append(f"{label}: {(m.get('content') or '')[:_MSG_WEIGHT_CAP]}")

        try:
            raw = await ai_router.complete(
                role=AIRole.COMPACTION,
                system_prompt=self._SYSTEM_PROMPT.format(
                    name=getattr(personality, "name", "Mika"),
                    max_chars=cible,
                ),
                user_prompt="\n".join(lines),
                timeout=budget,
                max_tokens=2000,
            )
        except UnconfiguredRoleError:
            # Rôle non mappé = compaction désactivée, silencieusement : le
            # garde-fou de comptage du buffer borne seul.
            return None
        except Exception as exc:
            degradations.record("compaction: appel LLM", exc)
            return None

        text = (raw or "").strip()
        if not text:
            return None
        floor = self._summary_floor(
            prev_summary, sum(self._weight(m) for m in fold),
        )
        if len(text) < floor:
            raise DegenerateSummary(
                f"{len(text)} caracteres pour un plancher de {floor}"
            )
        if len(text) > cible:
            text = text[: cible - 1].rstrip() + "…"
        return text
