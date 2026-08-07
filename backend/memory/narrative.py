"""Narrative generation — Mika's evolving self-concept.

The consolidator produces episodic (Souvenir) and semantic (Connaissance)
memory. This module produces the third layer: *narrative* memory — a
first-person paragraph that synthesizes "who she is becoming" from her
recent history. It is to memory what a diary summary is to a calendar.

Design choices:
  - Runs inside the consolidator, not on its own loop — narrative is a
    byproduct of consolidation, same cadence, same cache warmup.
  - Reuses `AIRole.MEMORY_EXTRACTION` (same genre of task: LLM reads
    text, returns structured output). Avoids adding an env var.
  - Output is a plain paragraph + a few metadata fields. No ManyToMany
    references — a narrative is a *snapshot*, not a canonical store.
  - Gated: only regenerates if enough new material has accumulated AND
    some time has passed. See `should_regenerate()`.
  - Keeps history: one row per regeneration, so evolution is auditable.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone

from ai.router import AIRole, UnconfiguredRoleError, ai_router
from utils.degradation import degradations
from utils.parsing import strip_markdown_json

logger = logging.getLogger(__name__)


# How long an already-generated narrative stays "fresh enough" to skip
# regeneration even if new material accumulated. Mika's self-concept
# shouldn't oscillate every 10 minutes.
NARRATIVE_MIN_AGE_HOURS = 24

# Minimum number of new souvenirs (since the last narrative's high-water
# mark) required before we bother regenerating. Below this threshold,
# there isn't enough new material for the self-concept to meaningfully
# shift.
NARRATIVE_MIN_NEW_SOUVENIRS = 5

# Hard cap on how many memories we feed the LLM, to keep prompt size
# bounded. Sampled by (importance DESC, recency DESC).
MAX_SOUVENIRS_IN_PROMPT = 25
MAX_CONNAISSANCES_IN_PROMPT = 20

# Timeout on the LLM call. This runs in the consolidation loop, so we
# don't want it stalling if the provider hangs.
NARRATIVE_TIMEOUT_SECONDS = 60


NARRATIVE_PROMPT_TEMPLATE = """\
ROLE: Tu rediges le self-concept de {name}. Tu n'es PAS {name}. Tu synthetises \
son auto-biographie a partir de ses souvenirs et de ses connaissances accumulees.

CONTEXTE sur qui est {name}: {description}. Style: {tone}. Traits de caractere: {traits}.

TU DOIS ECRIRE: un paragraphe court (4 a 6 phrases) a la PREMIERE PERSONNE \
(je, moi, mes), comme si {name} se racontait a elle-meme qui elle est en train \
de devenir. Base-toi UNIQUEMENT sur les souvenirs et connaissances fournis. \
Ne pas inventer. Ne pas paraphraser la personnalite de base — cherche ce qui a \
EMERGE de ses experiences recentes, pas ce qu'elle etait au depart.

LE PARAGRAPHE DOIT:
- Commencer par "Je" (pas "Elle", pas "Tu")
- Etre concret: mentionner les patterns observes, les gens recurrents, les sujets \
qui reviennent, les emotions dominantes
- Sonner comme de l'introspection, pas un rapport
- NE PAS repeter les traits de la personnalite de base — tu ajoutes, tu ne reproduis pas

SOUVENIRS RECENTS (episodique, du point de vue de {name}):
{souvenirs}

CONNAISSANCES (faits etablis sur le monde de {name}):
{connaissances}

TENDANCE EMOTIONNELLE RECENTE: {mood_trend}

Retourne UNIQUEMENT du JSON valide, pas de markdown:
{{
  "narrative": "Je ... (paragraphe 4-6 phrases, 1ere personne)",
  "key_themes": ["theme1", "theme2", "theme3"],
  "key_people": ["personne1", "personne2"],
  "dominant_mood": "emotion",
  "confidence": 0.8
}}

Si les materiaux sont trop maigres pour une synthese honnete:
{{"narrative": "", "key_themes": [], "key_people": [], "dominant_mood": "", "confidence": 0.0}}
"""


@dataclass
class NarrativeInput:
    """Material fed to the generator."""
    souvenirs: list[dict]          # [{content, emotion, importance, themes, people}, ...]
    connaissances: list[dict]      # [{content, confidence, themes, people}, ...]
    mood_trend: str                # human-readable trend summary


@dataclass
class NarrativeResult:
    """LLM output after parsing."""
    content: str
    key_themes: list[str]
    key_people: list[str]
    dominant_mood: str
    confidence: float

    @property
    def is_grounded(self) -> bool:
        """True if the generator claims a minimum of confidence and body."""
        return bool(self.content.strip()) and self.confidence >= 0.3


class NarrativeGenerator:
    """Produces Mika's self-concept paragraph from recent memory."""

    def __init__(self):
        self._system_prompt_cache: str | None = None

    def _get_system_prompt(self) -> str:
        if self._system_prompt_cache is None:
            from config.personality import personality
            self._system_prompt_cache = NARRATIVE_PROMPT_TEMPLATE.format(
                name=personality.name,
                description=personality.description,
                tone=personality.tone,
                traits=", ".join(personality.traits),
                # Placeholders — filled in at call time per-request.
                souvenirs="{souvenirs}",
                connaissances="{connaissances}",
                mood_trend="{mood_trend}",
            )
        return self._system_prompt_cache

    # ── Gating ────────────────────────────────────────────────────

    @staticmethod
    async def should_regenerate() -> tuple[bool, str]:
        """Return (should, reason). Pure-ish (reads DB, no writes).

        Regenerates when: no narrative yet, OR (age ≥ 24h AND ≥5 new souvenirs).
        """
        from memory.models import SelfNarrative, Souvenir

        latest = await sync_to_async(
            lambda: SelfNarrative.objects.order_by("-created_at").first()
        )()

        souvenir_count = await sync_to_async(Souvenir.objects.count)()

        if latest is None:
            if souvenir_count >= NARRATIVE_MIN_NEW_SOUVENIRS:
                return True, f"first_narrative (have {souvenir_count} souvenirs)"
            return False, f"not_enough_material ({souvenir_count} souvenirs)"

        age = timezone.now() - latest.created_at
        if age < timedelta(hours=NARRATIVE_MIN_AGE_HOURS):
            return False, f"too_recent (age={age})"

        new_since = await sync_to_async(
            lambda: Souvenir.objects.filter(id__gt=latest.last_souvenir_id).count()
        )()
        if new_since < NARRATIVE_MIN_NEW_SOUVENIRS:
            return False, f"not_enough_new ({new_since} new souvenirs)"

        return True, f"age={age}, new={new_since}"

    # ── Gather input ──────────────────────────────────────────────

    @staticmethod
    async def gather_input() -> tuple[NarrativeInput, int]:
        """Pull the recent high-importance memory pool. Returns (input, max_souvenir_id)."""
        from memory.models import Connaissance, EmotionalSummary, Souvenir

        souvenir_rows = await sync_to_async(
            lambda: list(
                Souvenir.objects
                .order_by("-importance", "-occurred_at")[:MAX_SOUVENIRS_IN_PROMPT]
                .prefetch_related("themes", "entities")
            )
        )()

        def _serialize_souvenir(s):
            return {
                "content": s.content,
                "emotion": s.emotion,
                "importance": round(s.importance, 2),
                "themes": [t.name for t in s.themes.all()],
                "people": [e.name for e in s.entities.all() if e.entity_type == "person"],
            }

        souvenirs = await sync_to_async(lambda: [_serialize_souvenir(s) for s in souvenir_rows])()

        connaissance_rows = await sync_to_async(
            lambda: list(
                Connaissance.objects.filter(is_valid=True)
                .order_by("-confidence", "-updated_at")[:MAX_CONNAISSANCES_IN_PROMPT]
                .prefetch_related("themes", "entities")
            )
        )()

        def _serialize_connaissance(c):
            return {
                "content": c.content,
                "confidence": round(c.confidence, 2),
                "themes": [t.name for t in c.themes.all()],
                "people": [e.name for e in c.entities.all() if e.entity_type == "person"],
            }

        connaissances = await sync_to_async(
            lambda: [_serialize_connaissance(c) for c in connaissance_rows]
        )()

        # Mood trend: most recent daily EmotionalSummary's dominant + trend.
        mood_trend = await sync_to_async(
            lambda: _summarize_mood_trend(
                list(EmotionalSummary.objects.filter(period_type="daily")
                     .order_by("-period_start")[:7])
            )
        )()

        max_id = souvenir_rows[0].id if souvenir_rows else 0
        # souvenirs are ordered by importance, not id — recompute true max.
        if souvenir_rows:
            max_id = max(s.id for s in souvenir_rows)

        return NarrativeInput(
            souvenirs=souvenirs,
            connaissances=connaissances,
            mood_trend=mood_trend,
        ), max_id

    # ── LLM call ──────────────────────────────────────────────────

    async def generate(self, pool: NarrativeInput) -> NarrativeResult | None:
        """Call the LLM to synthesize a narrative. Returns None on failure."""
        souvenirs_block = _format_souvenirs(pool.souvenirs)
        connaissances_block = _format_connaissances(pool.connaissances)

        if not souvenirs_block and not connaissances_block:
            logger.info("Narrative generation skipped: empty memory pool")
            return None

        user_prompt = (
            self._get_system_prompt()
            .replace("{souvenirs}", souvenirs_block)
            .replace("{connaissances}", connaissances_block)
            .replace("{mood_trend}", pool.mood_trend or "pas de tendance marquee")
        )

        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,
                    system_prompt="Tu synthetises une identite narrative.",
                    user_prompt=user_prompt,
                ),
                timeout=NARRATIVE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Narrative generation timed out after %ds", NARRATIVE_TIMEOUT_SECONDS)
            return None
        except UnconfiguredRoleError as exc:
            logger.warning("Narrative ignoré — IA non configurée: %s", exc)
            return None
        except Exception:
            logger.exception("Narrative LLM call failed")
            return None

        if not raw or not raw.strip():
            return None

        try:
            data = json.loads(strip_markdown_json(raw.strip()))
        except json.JSONDecodeError as exc:
            logger.warning("Narrative JSON parse failed: %.200s", raw)
            degradations.record("narrative: JSON de l'auto-narratif illisible", exc)
            return None

        return NarrativeResult(
            content=data.get("narrative", "").strip(),
            key_themes=list(data.get("key_themes", []))[:8],
            key_people=list(data.get("key_people", []))[:8],
            dominant_mood=data.get("dominant_mood", "")[:30],
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        )

    # ── Persist ───────────────────────────────────────────────────

    @staticmethod
    async def save(
        result: NarrativeResult,
        *,
        last_souvenir_id: int,
        source_souvenir_count: int,
        source_connaissance_count: int,
    ) -> None:
        from memory.models import SelfNarrative

        await sync_to_async(SelfNarrative.objects.create)(
            content=result.content,
            key_themes=result.key_themes,
            key_people=result.key_people,
            dominant_mood=result.dominant_mood,
            confidence=result.confidence,
            source_souvenir_count=source_souvenir_count,
            source_connaissance_count=source_connaissance_count,
            last_souvenir_id=last_souvenir_id,
        )

    # ── Full cycle ────────────────────────────────────────────────

    async def run_if_due(self) -> str | None:
        """Gate + gather + generate + save. Safe no-op if not due.

        Returns the generated content on success, None otherwise (skip/fail).
        """
        due, reason = await self.should_regenerate()
        logger.info("Narrative gate: due=%s (%s)", due, reason)
        if not due:
            return None

        pool, max_id = await self.gather_input()
        if not pool.souvenirs and not pool.connaissances:
            logger.info("Narrative generation: no source material, skipping")
            return None

        result = await self.generate(pool)
        if result is None or not result.is_grounded:
            logger.info(
                "Narrative generation produced no usable output (grounded=%s)",
                result.is_grounded if result else None,
            )
            return None

        await self.save(
            result,
            last_souvenir_id=max_id,
            source_souvenir_count=len(pool.souvenirs),
            source_connaissance_count=len(pool.connaissances),
        )
        logger.info(
            "Narrative generated: %s... (%d souvenirs, %d connaissances)",
            result.content[:80],
            len(pool.souvenirs),
            len(pool.connaissances),
        )
        return result.content


# ── Helpers ───────────────────────────────────────────────────────


def _format_souvenirs(items: list[dict]) -> str:
    if not items:
        return "(aucun souvenir significatif)"
    lines = []
    for s in items:
        people = ", ".join(s.get("people", [])) or "personne"
        themes = ", ".join(s.get("themes", [])) or "-"
        lines.append(
            f"- [{s.get('emotion', 'neutral')}, imp={s.get('importance', 0):.1f}] "
            f"{s['content']} (themes: {themes}; avec: {people})"
        )
    return "\n".join(lines)


def _format_connaissances(items: list[dict]) -> str:
    if not items:
        return "(aucune connaissance stable)"
    lines = []
    for c in items:
        themes = ", ".join(c.get("themes", [])) or "-"
        lines.append(f"- [conf={c.get('confidence', 0):.1f}] {c['content']} (themes: {themes})")
    return "\n".join(lines)


def _summarize_mood_trend(summaries: list) -> str:
    """Produce a short French description of the last week's emotional trend."""
    if not summaries:
        return ""

    # Most recent first. Look at the dominant emotion over the last N days.
    dominant_emotions = [s.dominant_emotion for s in summaries if s.dominant_emotion]
    if not dominant_emotions:
        return ""

    # Simple majority + most recent trend field.
    most_recent = summaries[0]
    if len(summaries) == 1:
        return f"{most_recent.dominant_emotion} ({most_recent.trend})"

    # Count emotion frequencies
    from collections import Counter
    counter = Counter(dominant_emotions)
    top, top_count = counter.most_common(1)[0]
    if top_count >= len(summaries) * 0.6:
        return f"majoritairement {top} sur les {len(summaries)} derniers jours ({most_recent.trend})"
    return (
        f"emotions variees ({', '.join(counter.keys())}), "
        f"tendance recente: {most_recent.dominant_emotion} ({most_recent.trend})"
    )


# Module-level singleton
narrative_generator = NarrativeGenerator()
