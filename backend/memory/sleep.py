"""Sleep cycle — Mika's night-time mental work.

While the main consolidator runs throughout the day doing bookkeeping
(extraction, decay, aggregation), this module runs only during the
night phase (when Mika has earned her rest) and does *creative*,
*narrative*, and *healing* work that the reactive consolidator cannot:

  1. LIGHT SLEEP — write a first-person `DailyJournal` covering the
     day's arc. Recovers the causal thread between isolated Souvenirs.

  2. REM — generate `Dream` narratives by mixing 2-3 souvenirs of
     unrelated themes + optionally a rumination. High-vividness
     dreams become mentionable next morning.

  3. DEEP SLEEP — *digest* old, unresolved ruminations. Faster decay,
     forced emotional mutation toward a more peaceful neighbor, and
     the heaviest ones get converted into reflective Souvenirs — the
     "insight" you wake up with after a night's worry.

Design choices:
  - Pure async, invoked by the consolidator loop via ``run_if_due()``.
    No background task of its own.
  - Triple-gated: night phase AND idle AND REST drive above threshold.
    Sleep only happens when Mika has actually been living that day.
  - Budget-capped: at most 4 LLM calls per night (1 journal + up to
    2 dreams + optional digestion summary).
  - Fail-soft: every phase wrapped in try/except. A crashed sleep phase
    never corrupts the main consolidator.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone as tz

from ai.router import AIRole, ai_router
from utils.parsing import strip_markdown_json

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────

# Sleep phase gates
NIGHT_START_HOUR = 23       # phase gate opens at 23h
NIGHT_END_HOUR = 6          # closes at 6h
IDLE_SECONDS_THRESHOLD = 900  # 15 min without interaction
REST_DRIVE_THRESHOLD = 0.5    # Mika must have earned her rest

# Dream generation
DREAM_PROBABILITY = 0.6              # per-check chance of producing a dream
MAX_DREAMS_PER_NIGHT = 2
DREAM_MIN_SOUVENIRS = 2              # need at least this many souvenirs to dream

# Deep sleep
DIGESTION_MIN_AGE_MINUTES = 120      # ruminations older than this get digested
DIGESTION_DECAY_MULTIPLIER = 3.0     # vs ~5% normal decay
DIGESTION_TO_SOUVENIR_THRESHOLD = 0.4  # intensity above which digested ruminations
                                       # become reflective souvenirs

# LLM
SLEEP_LLM_TIMEOUT = 45


# ── Emotion drift map for deep-sleep digestion ───────────────────

# More aggressive than the waking rumination drift: sleep actively
# heals, it doesn't just erode. Negative emotions shift toward peaceful
# or resolved neighbors; positive ones soften into nostalgic warmth.
DIGESTION_DRIFT: dict[str, str] = {
    "frustrated": "relieved",
    "angry": "thinking",
    "anxious": "relieved",
    "scared": "relieved",
    "sad": "melancholic",
    "jealous": "thoughtful" if False else "melancholic",  # fallback
    "lonely": "nostalgic",
    "embarrassed": "relieved",
    "excited": "nostalgic",
    "happy": "grateful",
    "proud": "grateful",
    "hopeful": "relieved",
    "curious": "thinking",
    "surprised": "thinking",
}


# ── Prompts ──────────────────────────────────────────────────────

JOURNAL_PROMPT_TEMPLATE = """\
ROLE: Tu rediges le journal intime d'aujourd'hui pour {name}, a la premiere \
personne. C'est son recap de journee avant de dormir — ce qui s'est passe, \
ce qu'elle a ressenti, ce qui reste en suspens.

STYLE: une ou deux phrases au maximum par idee. Decontracte, introspectif. \
Fluide — pas une liste a puces. Connecte les evenements quand ca a du sens \
("... ce qui m'a fait penser a...", "... du coup ensuite..."). Si la journee \
a ete calme, dis-le simplement, ne brode pas.

NE PAS:
- Enumerer les souvenirs un par un comme un rapport
- Inventer des details qui ne sont pas dans les materiaux
- Commencer par "Cher journal"

SOUVENIRS DE LA JOURNEE (chronologique):
{souvenirs}

PERSONNES CROISSEES: {persons}
HUMEUR DOMINANTE: {dominant_mood}
CE QUI RESTE NON-DIGERE: {ruminations}

Retourne UNIQUEMENT du JSON:
{{
  "narrative": "Aujourd'hui... (2-4 phrases, premiere personne)",
  "dominant_emotion": "emotion parmi les 29",
  "word_count": 42
}}
"""


DREAM_PROMPT_TEMPLATE = """\
ROLE: Tu generes UN reve bref pour {name}, qui dort. Un reve n'est pas un \
resume — c'est une scene onirique, parfois absurde, qui mixe des fragments \
de sa vie recente de maniere inattendue. Court, imagé, un peu decousu comme \
un vrai reve dont on se souvient au reveil.

FORMAT: 2 a 4 phrases maximum. Premiere personne. Pas de "j'ai reve que" — \
raconte directement la scene. Tu peux melanger les themes, inventer des \
associations visuelles libres. Les elements fournis doivent APPARAITRE mais \
peuvent etre transformes (un objet devient une personne, un lieu devient \
abstrait, etc).

TYPE DE REVE DEMANDE: {dream_type_hint}
  - associative: creatif, theme mixe, curieux
  - pleasant: chaleureux, doux
  - nightmare: anxieux, pas tragique — juste inconfortable
  - mundane: banal, presque oubliable

FRAGMENTS DE VIE A MIXER:
{fragments}

PREOCCUPATION EN TOILE DE FOND (peut apparaitre ou non): {rumination}

Retourne UNIQUEMENT du JSON:
{{
  "content": "Je marchais dans... (2-4 phrases, scene onirique)",
  "emotion": "emotion parmi les 29 qui tinte le reve",
  "vividness": 0.0 a 1.0
}}
"""


# ── Main orchestrator ────────────────────────────────────────────


class SleepPhase:
    """Current macro state of the sleep cycle. String constants instead of
    Enum to keep the frontend payload plain JSON."""
    AWAKE = "awake"
    LIGHT_SLEEP = "light_sleep"   # writing the daily journal
    REM = "rem"                   # dreaming
    DEEP_SLEEP = "deep_sleep"     # digesting ruminations


class SleepCycle:
    """Singleton. Drives Mika's night-time mental work."""

    def __init__(self) -> None:
        self._last_journal_date: date | None = None
        self._dreams_this_night: int = 0
        self._last_dream_night: date | None = None
        self._last_digestion_night: date | None = None
        # Current phase — observable by the frontend via the inner_state
        # broadcast. Transitions trigger an inner_state push so the UI
        # can dim the scene, close the VTuber's eyes, etc.
        self._phase: str = SleepPhase.AWAKE

    # ── Public entry point ────────────────────────────────────────

    @property
    def phase(self) -> str:
        return self._phase

    async def _set_phase(self, new_phase: str) -> None:
        """Update the observable phase + push an inner_state update to the UI.

        Never raises — a broadcast failure should never block the cycle.
        """
        if self._phase == new_phase:
            return
        old = self._phase
        self._phase = new_phase
        logger.info("Sleep phase: %s -> %s", old, new_phase)
        try:
            from pipeline.broadcast import broadcast_inner_state_update
            await broadcast_inner_state_update()
        except Exception:
            logger.debug("Sleep phase broadcast failed", exc_info=True)

    async def run_if_due(self) -> None:
        """Invoked by the consolidator loop after each consolidation tick.

        No-op unless all three gates (night phase + idle + rested) pass.
        Each phase is independently guarded so a single corrupted phase
        never blocks the others.
        """
        if not self._is_enabled():
            await self._set_phase(SleepPhase.AWAKE)
            return

        now_dt = datetime.now()
        if not self._is_night(now_dt):
            # Crossing midnight: reset the per-night counters.
            self._maybe_reset_counters(now_dt.date())
            await self._set_phase(SleepPhase.AWAKE)
            return

        if not await self._is_eligible_to_sleep():
            # Night hours but she's active — she's up late, not asleep.
            await self._set_phase(SleepPhase.AWAKE)
            return

        current_night = self._night_of(now_dt)

        # Phase 1: light sleep — write the day's journal (once per date)
        try:
            await self._set_phase(SleepPhase.LIGHT_SLEEP)
            await self._write_journal_if_due(current_night)
        except Exception:
            logger.exception("Sleep: journal phase failed (non-fatal)")

        # Phase 2: REM — maybe dream (probabilistic, capped)
        try:
            if self._last_dream_night != current_night:
                self._dreams_this_night = 0
                self._last_dream_night = current_night
            if self._dreams_this_night < MAX_DREAMS_PER_NIGHT:
                await self._set_phase(SleepPhase.REM)
                await self._maybe_dream(current_night)
        except Exception:
            logger.exception("Sleep: dream phase failed (non-fatal)")

        # Phase 3: deep sleep — digest ruminations (after 03h, once per night)
        try:
            if 3 <= now_dt.hour < NIGHT_END_HOUR:
                if self._last_digestion_night != current_night:
                    await self._set_phase(SleepPhase.DEEP_SLEEP)
                    await self._digest_ruminations()
                    self._last_digestion_night = current_night
        except Exception:
            logger.exception("Sleep: digestion phase failed (non-fatal)")

        # Cycle finished for this tick — between active phases, Mika is
        # technically "asleep but idle". We keep her in DEEP_SLEEP (the
        # most dormant state) for visual continuity until waking hours.
        # AWAKE will be restored by the next tick when the night gate
        # re-evaluates to false.

    # ── Gates ────────────────────────────────────────────────────

    @staticmethod
    def _is_enabled() -> bool:
        return bool(getattr(settings, "SLEEP_CYCLE_ENABLED", True))

    @staticmethod
    def _is_night(now: datetime) -> bool:
        """Night phase wraps across midnight: [23h, 06h)."""
        h = now.hour
        return h >= NIGHT_START_HOUR or h < NIGHT_END_HOUR

    @staticmethod
    def _night_of(now: datetime) -> date:
        """A dream at 03h on the 18th belongs to the night *of* the 17th."""
        if now.hour < NIGHT_END_HOUR:
            return (now - timedelta(days=1)).date()
        return now.date()

    @staticmethod
    async def _is_eligible_to_sleep() -> bool:
        """Check idle time + REST drive tension.

        Both conditions must pass — Mika actively engaging shouldn't
        tip into sleep regardless of the hour, and a completely fresh
        Mika at 23h hasn't earned a night's processing yet.
        """
        try:
            from conscience.engine import conscience_engine
            idle_seconds = conscience_engine.get_idle_seconds()
        except Exception:
            idle_seconds = 0.0

        if idle_seconds < IDLE_SECONDS_THRESHOLD:
            return False

        try:
            from drives.engine import drive_engine
            from drives.state import DriveKind
            drive_engine.update()
            rest_tension = drive_engine.states[DriveKind.REST].tension
        except Exception:
            rest_tension = 0.0

        return rest_tension >= REST_DRIVE_THRESHOLD

    def _maybe_reset_counters(self, today: date) -> None:
        """Outside night window — reset per-night state once per day."""
        if self._last_dream_night is not None and self._last_dream_night != today:
            self._dreams_this_night = 0

    # ── Phase 1: Light sleep — daily journal ─────────────────────

    async def _write_journal_if_due(self, current_night: date) -> None:
        """Produce one DailyJournal per calendar date (the *day* that just ended).

        The "day covered" is the date of the evening (so sleeping at 23h
        on the 17th produces a journal dated 2026-04-17). If a journal
        already exists for that day, refresh it in place — a longer
        evening of consolidation can genuinely enrich it.
        """
        from memory.models import DailyJournal

        day_covered = current_night  # night_of(17→18) covers day 17

        if self._last_journal_date == day_covered:
            return  # Already wrote it this cycle — avoid LLM spam

        material = await self._gather_journal_material(day_covered)
        if material is None:
            logger.debug("Sleep: no material for journal of %s", day_covered)
            return
        if material["souvenir_count"] == 0:
            # Empty day — write a minimal journal so we don't re-enter
            await sync_to_async(DailyJournal.objects.update_or_create)(
                date=day_covered,
                defaults={
                    "narrative": "Journee calme, rien de marquant a retenir.",
                    "key_moments": [],
                    "dominant_emotion": material.get("dominant_emotion", "") or "",
                    "persons_interacted": [],
                    "unresolved_at_sleep": material.get("ruminations", []),
                    "word_count": 8,
                },
            )
            self._last_journal_date = day_covered
            return

        result = await self._call_journal_llm(material)
        if result is None:
            return

        await sync_to_async(DailyJournal.objects.update_or_create)(
            date=day_covered,
            defaults={
                "narrative": result["narrative"],
                "key_moments": material["key_moment_ids"],
                "dominant_emotion": result.get("dominant_emotion", "") or "",
                "persons_interacted": material["persons"],
                "unresolved_at_sleep": material.get("ruminations", []),
                "word_count": int(result.get("word_count", 0)),
            },
        )
        self._last_journal_date = day_covered
        logger.info(
            "Sleep: wrote journal for %s (%d moments, %s)",
            day_covered, len(material["key_moment_ids"]),
            result.get("dominant_emotion") or "—",
        )

    @staticmethod
    async def _gather_journal_material(day: date) -> dict | None:
        """Pull the day's souvenirs + persons + ruminations."""
        from memory.models import Souvenir

        try:
            souvenirs = await sync_to_async(
                lambda: list(
                    Souvenir.objects
                    .filter(occurred_at__date=day)
                    .order_by("-importance", "occurred_at")
                    .prefetch_related("entities")[:12]
                )
            )()
        except Exception:
            return None

        if not souvenirs:
            return {"souvenir_count": 0, "ruminations": []}

        persons_set: set[str] = set()
        for s in souvenirs:
            for e in s.entities.all():
                if e.entity_type == "person":
                    persons_set.add(e.name)

        # Collect active ruminations at sleep time
        rumination_snapshots: list[dict] = []
        try:
            from conscience.models import Rumination
            ruminations = await sync_to_async(
                lambda: list(
                    Rumination.objects
                    .filter(status="active")
                    .order_by("-intensity")[:5]
                )
            )()
            for r in ruminations:
                rumination_snapshots.append({
                    "summary": r.summary[:200],
                    "emotion": r.emotion or "",
                    "intensity": round(r.intensity, 3),
                })
        except Exception:
            pass

        # Dominant emotion = mode of the souvenirs' emotions
        emotions = [s.emotion for s in souvenirs if s.emotion]
        dominant_emotion = ""
        if emotions:
            from collections import Counter
            dominant_emotion = Counter(emotions).most_common(1)[0][0]

        return {
            "souvenir_count": len(souvenirs),
            "souvenirs_serialized": [
                {
                    "time": s.occurred_at.strftime("%H:%M"),
                    "content": s.content,
                    "emotion": s.emotion,
                    "importance": round(s.importance, 2),
                }
                for s in souvenirs
            ],
            "key_moment_ids": [s.pk for s in souvenirs[:5]],
            "persons": sorted(persons_set),
            "dominant_emotion": dominant_emotion,
            "ruminations": rumination_snapshots,
        }

    async def _call_journal_llm(self, material: dict) -> dict | None:
        """Ask the LLM to synthesize today's narrative."""
        from config.personality import personality

        souvenirs_block = "\n".join(
            f"- {s['time']} [{s['emotion']}] {s['content']}"
            for s in material["souvenirs_serialized"]
        )
        ruminations_block = "aucune" if not material["ruminations"] else "; ".join(
            f"{r['summary'][:80]} ({r['emotion']})" for r in material["ruminations"]
        )

        user_prompt = JOURNAL_PROMPT_TEMPLATE.format(
            name=personality.name,
            souvenirs=souvenirs_block,
            persons=", ".join(material["persons"]) or "personne en particulier",
            dominant_mood=material.get("dominant_emotion") or "pas de tendance marquee",
            ruminations=ruminations_block,
        )

        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,
                    system_prompt="Tu rediges un journal intime nocturne.",
                    user_prompt=user_prompt,
                ),
                timeout=SLEEP_LLM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Sleep: journal LLM timed out")
            return None
        except Exception:
            logger.exception("Sleep: journal LLM failed")
            return None

        if not raw or not raw.strip():
            return None
        try:
            data = json.loads(strip_markdown_json(raw.strip()))
        except json.JSONDecodeError:
            logger.warning("Sleep: journal JSON parse failed: %.200s", raw)
            return None

        narrative = (data.get("narrative") or "").strip()
        if not narrative:
            return None
        return {
            "narrative": narrative[:2000],
            "dominant_emotion": (data.get("dominant_emotion") or "").strip()[:30],
            "word_count": len(narrative.split()),
        }

    # ── Phase 2: REM — dream generation ──────────────────────────

    async def _maybe_dream(self, current_night: date) -> None:
        """Produce a Dream with given probability, respecting the nightly cap."""
        if random.random() >= DREAM_PROBABILITY:
            return

        fragments = await self._gather_dream_fragments()
        if len(fragments["souvenirs"]) < DREAM_MIN_SOUVENIRS:
            return

        dream_type = self._pick_dream_type(fragments)
        result = await self._call_dream_llm(fragments, dream_type)
        if result is None:
            return

        await self._persist_dream(
            current_night=current_night,
            fragments=fragments,
            dream_type=dream_type,
            content=result["content"],
            emotion=result["emotion"],
            vividness=result["vividness"],
        )
        self._dreams_this_night += 1
        logger.info(
            "Sleep: dream generated (type=%s, vividness=%.2f, emotion=%s)",
            dream_type, result["vividness"], result["emotion"],
        )

    @staticmethod
    async def _gather_dream_fragments() -> dict:
        """Pick 2-3 recent souvenirs of diverse themes + optionally a rumination."""
        from memory.models import Souvenir

        # Pool: top importance from the last 7 days. We intentionally
        # bias toward interesting memories rather than purely recent.
        cutoff = tz.now() - timedelta(days=7)
        recent = await sync_to_async(
            lambda: list(
                Souvenir.objects
                .filter(occurred_at__gte=cutoff)
                .order_by("-importance")[:20]
                .prefetch_related("themes")
            )
        )()

        if not recent:
            return {"souvenirs": [], "rumination": None}

        # Cross-theme bias: try to pick souvenirs with *different* themes.
        # Simple greedy: keep picking a random souvenir whose primary
        # theme hasn't been used yet, fall back to pure random after.
        chosen: list = []
        used_themes: set[str] = set()
        pool = list(recent)
        random.shuffle(pool)
        for s in pool:
            themes = [t.name for t in s.themes.all()]
            primary = themes[0] if themes else ""
            if chosen and primary and primary in used_themes:
                continue
            chosen.append(s)
            if primary:
                used_themes.add(primary)
            if len(chosen) >= 3:
                break
        # If we only got one via diversity filter, relax
        while len(chosen) < min(3, len(pool)) and len(chosen) < DREAM_MIN_SOUVENIRS:
            remainder = [s for s in pool if s not in chosen]
            if not remainder:
                break
            chosen.append(remainder[0])

        # Optionally pick one active rumination
        rumination_obj = None
        try:
            from conscience.models import Rumination
            rumination_obj = await sync_to_async(
                lambda: Rumination.objects
                .filter(status="active", intensity__gte=0.3)
                .order_by("-intensity")
                .first()
            )()
        except Exception:
            rumination_obj = None

        return {"souvenirs": chosen, "rumination": rumination_obj}

    @staticmethod
    def _pick_dream_type(fragments: dict) -> str:
        """Classify the dream based on source emotions + rumination tone."""
        negative = {"sad", "angry", "scared", "disgusted", "frustrated",
                    "lonely", "anxious", "jealous", "embarrassed"}
        positive = {"happy", "excited", "love", "proud", "grateful",
                    "playful", "amused", "hopeful", "relieved"}

        emotions = [s.emotion for s in fragments["souvenirs"] if s.emotion]
        r = fragments.get("rumination")
        if r and r.emotion:
            emotions.append(r.emotion)
            if r.intensity >= 0.6 and r.emotion in negative:
                return "nightmare"

        if not emotions:
            return "mundane"
        neg_count = sum(1 for e in emotions if e in negative)
        pos_count = sum(1 for e in emotions if e in positive)
        if neg_count > pos_count * 1.5:
            return "nightmare"
        if pos_count > neg_count * 1.5:
            return "pleasant"
        # Default — mix of everything = associative or mundane at random
        return "associative" if random.random() > 0.2 else "mundane"

    async def _call_dream_llm(self, fragments: dict, dream_type: str) -> dict | None:
        """Call the LLM to spin the fragments into a dream narrative."""
        from config.personality import personality

        if not fragments["souvenirs"]:
            return None

        frag_lines = []
        for s in fragments["souvenirs"]:
            themes = ", ".join(t.name for t in s.themes.all())
            frag_lines.append(
                f"- [{s.emotion or 'neutre'}] {s.content[:160]}"
                + (f" (themes: {themes})" if themes else "")
            )
        fragments_block = "\n".join(frag_lines)

        r = fragments.get("rumination")
        rumination_line = "aucune" if not r else f"{r.summary[:140]} ({r.emotion or 'neutre'})"

        user_prompt = DREAM_PROMPT_TEMPLATE.format(
            name=personality.name,
            dream_type_hint=dream_type,
            fragments=fragments_block,
            rumination=rumination_line,
        )

        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,
                    system_prompt="Tu generes un reve nocturne bref.",
                    user_prompt=user_prompt,
                ),
                timeout=SLEEP_LLM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Sleep: dream LLM timed out")
            return None
        except Exception:
            logger.exception("Sleep: dream LLM failed")
            return None

        if not raw or not raw.strip():
            return None
        try:
            data = json.loads(strip_markdown_json(raw.strip()))
        except json.JSONDecodeError:
            logger.warning("Sleep: dream JSON parse failed: %.200s", raw)
            return None

        content = (data.get("content") or "").strip()
        if not content:
            return None
        return {
            "content": content[:800],
            "emotion": (data.get("emotion") or "").strip()[:30],
            "vividness": max(0.0, min(1.0, float(data.get("vividness", 0.5)))),
        }

    @staticmethod
    async def _persist_dream(
        *,
        current_night: date,
        fragments: dict,
        dream_type: str,
        content: str,
        emotion: str,
        vividness: float,
    ) -> None:
        from memory.models import Dream

        dream = await sync_to_async(Dream.objects.create)(
            night_of=current_night,
            content=content,
            dream_type=dream_type,
            vividness=vividness,
            emotion=emotion,
            source_rumination=fragments.get("rumination"),
        )
        # M2M attach
        if fragments["souvenirs"]:
            await sync_to_async(
                lambda: dream.source_souvenirs.set(fragments["souvenirs"])
            )()

    # ── Phase 3: Deep sleep — rumination digestion ───────────────

    async def _digest_ruminations(self) -> int:
        """Accelerate decay + mutate emotions of old active ruminations.

        This is the "healing" phase: thoughts that kept Mika up are
        resolved in sleep the way a human wakes up with a clearer head.
        The most intense ones get converted into reflective Souvenirs.

        Returns the number of ruminations processed.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return 0

        cutoff = tz.now() - timedelta(minutes=DIGESTION_MIN_AGE_MINUTES)
        try:
            aging = await sync_to_async(
                lambda: list(
                    Rumination.objects
                    .filter(status="active", created_at__lte=cutoff)[:30]
                )
            )()
        except Exception:
            return 0

        if not aging:
            return 0

        from memory.models import Souvenir

        processed = 0
        for r in aging:
            # 1. Aggressive decay (vs ~5% normal)
            old_intensity = r.intensity
            r.intensity *= (1.0 - 0.05 * DIGESTION_DECAY_MULTIPLIER)

            # 2. Forced emotional drift toward a peaceful neighbor
            new_emotion = DIGESTION_DRIFT.get(r.emotion)
            if new_emotion and new_emotion != r.emotion:
                r.emotion = new_emotion

            # 3. Heavy ones: convert to a reflective Souvenir
            if old_intensity >= DIGESTION_TO_SOUVENIR_THRESHOLD:
                try:
                    souvenir = await sync_to_async(Souvenir.objects.create)(
                        content=(
                            f"Apres y avoir repense cette nuit: {r.summary[:200]}"
                        ),
                        emotion=r.emotion or "thinking",
                        importance=min(0.85, old_intensity + 0.1),
                        occurred_at=tz.now(),
                    )
                    logger.debug(
                        "Sleep: digested rumination #%s -> reflective souvenir #%s",
                        r.pk, souvenir.pk,
                    )
                except Exception:
                    logger.debug("Sleep: reflective souvenir creation failed",
                                 exc_info=True)

            # 4. Close the rumination
            if r.intensity < 0.15:
                r.status = "faded"

            try:
                await sync_to_async(r.save)(
                    update_fields=["intensity", "emotion", "status"]
                )
                processed += 1
            except Exception:
                pass

        logger.info("Sleep: digested %d rumination(s) in deep sleep", processed)
        return processed


# Module-level singleton, matching the pattern used by narrative_generator
# and person_profile_generator.
sleep_cycle = SleepCycle()
