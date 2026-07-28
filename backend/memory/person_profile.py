"""Person profile generation — Mika's evolving theory of mind.

For each person-type Entity that has accumulated enough interaction material,
generate a paragraph synthesizing how Mika understands *them*: their style,
interests, topics to approach carefully, and the relational stance.

Design mirrors memory/narrative.py (self-concept) but per-person:
  - Runs inside the consolidator, same cadence.
  - Reuses AIRole.MEMORY_EXTRACTION.
  - Gated: regenerate per-person when ≥24h old AND ≥N new souvenirs
    mentioning that specific person.
  - Output is structural (closeness + topics) + free-text summary.
  - Only processes "recent" people — those seen in the last 14 days —
    so inactive contacts don't burn LLM budget.
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
from utils.parsing import strip_markdown_json

logger = logging.getLogger(__name__)


# Minimum age of an existing profile before it's worth regenerating.
PROFILE_MIN_AGE_HOURS = 24
# Minimum new souvenirs mentioning the person since the last profile
# before regeneration is worth it.
PROFILE_MIN_NEW_SOUVENIRS = 3
# A person is "active" if they've been mentioned in the last N days.
PROFILE_ACTIVITY_WINDOW_DAYS = 14
# Hard cap on LLM prompt size per person.
MAX_SOUVENIRS_PER_PROFILE = 15
MAX_CONNAISSANCES_PER_PROFILE = 10
# Timeout per-person — we process people sequentially in the loop.
PROFILE_TIMEOUT_SECONDS = 45
# Max persons processed per consolidation cycle — protects against
# burst cost if dozens of new people appeared at once.
MAX_PERSONS_PER_CYCLE = 3


PROFILE_PROMPT_TEMPLATE = """\
ROLE: Tu rediges le modele mental que {name} a de quelqu'un d'autre. Tu n'es PAS \
{name}, tu n'es PAS {target_name}. Tu synthetises comment {name} percoit \
{target_name} a partir de ses souvenirs et des faits qu'elle connait.

CONTEXTE sur qui est {name}: {description}.

TU DOIS ECRIRE: un paragraphe court (3 a 5 phrases) a la TROISIEME personne sur \
{target_name}, du point de vue de {name}. C'est ce que {name} sait et suppose, \
pas un fait verifie. Doit sonner comme "{target_name} est quelqu'un qui ..." \
pas comme un CV. Pas d'invention: base-toi uniquement sur les materiaux fournis.

TU DOIS AUSSI CLASSIFIER:
- closeness: 'stranger' (inconnu), 'acquaintance' (on s'est parle quelques fois), \
'friend' (complicite reelle), 'close' (tres proche, confidences)
- preferred_tone: 'direct' (va droit au but), 'gentle' (doux, tactile), \
'playful' (taquin, leger), 'formal' (distant, poli), 'unknown' (pas clair)
- topics_of_interest: les 3-5 sujets qui reviennent quand {target_name} parle
- sensitive_topics: les sujets que {target_name} aborde avec difficulte \
ou qu'il vaut mieux ne pas brusquer

SOUVENIRS (episodes avec {target_name}):
{souvenirs}

CONNAISSANCES (faits etablis sur {target_name}):
{connaissances}

Retourne UNIQUEMENT du JSON valide, pas de markdown:
{{
  "summary": "{target_name} est quelqu'un qui ...",
  "closeness": "acquaintance",
  "preferred_tone": "playful",
  "topics_of_interest": ["theme1", "theme2"],
  "sensitive_topics": ["sujet1"],
  "confidence": 0.7
}}

Si les materiaux sont trop maigres:
{{"summary": "", "closeness": "stranger", "preferred_tone": "unknown", \
"topics_of_interest": [], "sensitive_topics": [], "confidence": 0.0}}
"""


@dataclass
class ProfileInput:
    entity_name: str
    souvenirs: list[dict]
    connaissances: list[dict]


@dataclass
class ProfileResult:
    summary: str
    closeness: str
    preferred_tone: str
    topics_of_interest: list[str]
    sensitive_topics: list[str]
    confidence: float

    @property
    def is_grounded(self) -> bool:
        return bool(self.summary.strip()) and self.confidence >= 0.2


class PersonProfileGenerator:
    """Regenerates per-person profiles during consolidation cycles."""

    def __init__(self):
        self._system_prompt_header: str | None = None

    def _get_base_template(self) -> str:
        if self._system_prompt_header is None:
            from config.personality import personality
            self._system_prompt_header = PROFILE_PROMPT_TEMPLATE.replace(
                "{name}", personality.name,
            ).replace(
                "{description}", personality.description,
            )
        return self._system_prompt_header

    # ── Entity selection ──────────────────────────────────────────

    @staticmethod
    async def select_due_entities(limit: int = MAX_PERSONS_PER_CYCLE) -> list:
        """Pick person-entities that need a (re)generated profile.

        An entity is due when:
          - it's been mentioned in a souvenir within ACTIVITY_WINDOW_DAYS, AND
          - either has no profile yet, OR profile is >24h old AND has ≥N new
            mentioning souvenirs since last generation.
        """
        from memory.models import Entity, PersonProfile, Souvenir

        now = timezone.now()
        activity_cutoff = now - timedelta(days=PROFILE_ACTIVITY_WINDOW_DAYS)
        regen_cutoff = now - timedelta(hours=PROFILE_MIN_AGE_HOURS)

        def _collect():
            active = list(
                Entity.objects.filter(
                    entity_type="person",
                    souvenirs__occurred_at__gte=activity_cutoff,
                ).distinct()
            )

            due = []
            for e in active:
                profile = PersonProfile.objects.filter(entity=e).first()
                if profile is None:
                    # New profile — needs at least N souvenirs to bootstrap
                    count = Souvenir.objects.filter(
                        entities=e,
                        occurred_at__gte=activity_cutoff,
                    ).count()
                    if count >= PROFILE_MIN_NEW_SOUVENIRS:
                        due.append((e, None, count))
                    continue

                if profile.generated_at and profile.generated_at > regen_cutoff:
                    continue  # too recent

                new_count = Souvenir.objects.filter(
                    entities=e,
                    id__gt=profile.last_souvenir_id,
                ).count()
                if new_count >= PROFILE_MIN_NEW_SOUVENIRS:
                    due.append((e, profile, new_count))

            # Highest new-material count first
            due.sort(key=lambda x: -x[2])
            return due[:limit]

        return await sync_to_async(_collect)()

    # ── Gather material per entity ────────────────────────────────

    @staticmethod
    async def gather_for_entity(entity) -> tuple[ProfileInput, int]:
        """Pull souvenirs + connaissances linked to this entity."""
        from memory.models import Connaissance, Souvenir

        souvenir_rows = await sync_to_async(
            lambda: list(
                Souvenir.objects.filter(entities=entity)
                .order_by("-importance", "-occurred_at")[:MAX_SOUVENIRS_PER_PROFILE]
                .prefetch_related("themes")
            )
        )()

        souvenirs = await sync_to_async(lambda: [
            {
                "content": s.content,
                "emotion": s.emotion,
                "importance": round(s.importance, 2),
                "themes": [t.name for t in s.themes.all()],
            }
            for s in souvenir_rows
        ])()

        connaissance_rows = await sync_to_async(
            lambda: list(
                Connaissance.objects.filter(entities=entity, is_valid=True)
                .order_by("-confidence", "-updated_at")[:MAX_CONNAISSANCES_PER_PROFILE]
                .prefetch_related("themes")
            )
        )()

        connaissances = await sync_to_async(lambda: [
            {
                "content": c.content,
                "confidence": round(c.confidence, 2),
                "themes": [t.name for t in c.themes.all()],
            }
            for c in connaissance_rows
        ])()

        max_id = max((s.id for s in souvenir_rows), default=0)

        return ProfileInput(
            entity_name=entity.name,
            souvenirs=souvenirs,
            connaissances=connaissances,
        ), max_id

    # ── LLM call ──────────────────────────────────────────────────

    async def generate(self, pool: ProfileInput) -> ProfileResult | None:
        if not pool.souvenirs and not pool.connaissances:
            return None

        souvenirs_block = _format_souvenirs(pool.souvenirs)
        connaissances_block = _format_connaissances(pool.connaissances)

        user_prompt = (
            self._get_base_template()
            .replace("{target_name}", pool.entity_name)
            .replace("{souvenirs}", souvenirs_block)
            .replace("{connaissances}", connaissances_block)
        )

        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,
                    system_prompt="Tu modelises comment quelqu'un en percoit un autre.",
                    user_prompt=user_prompt,
                ),
                timeout=PROFILE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Profile generation timed out for %s", pool.entity_name)
            return None
        except UnconfiguredRoleError as exc:
            logger.warning(
                "Profil de %s ignoré — IA non configurée: %s", pool.entity_name, exc,
            )
            return None
        except Exception:
            logger.exception("Profile LLM call failed for %s", pool.entity_name)
            return None

        if not raw or not raw.strip():
            return None

        try:
            data = json.loads(strip_markdown_json(raw.strip()))
        except json.JSONDecodeError:
            logger.warning("Profile JSON parse failed for %s: %.200s", pool.entity_name, raw)
            return None

        return ProfileResult(
            summary=data.get("summary", "").strip(),
            closeness=_validate_choice(data.get("closeness", "stranger"),
                                       {"stranger", "acquaintance", "friend", "close"},
                                       "stranger"),
            preferred_tone=_validate_choice(data.get("preferred_tone", "unknown"),
                                            {"direct", "gentle", "playful", "formal", "unknown"},
                                            "unknown"),
            topics_of_interest=list(data.get("topics_of_interest", []))[:5],
            sensitive_topics=list(data.get("sensitive_topics", []))[:5],
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        )

    # ── Persist ───────────────────────────────────────────────────

    @staticmethod
    async def save(
        entity, result: ProfileResult, max_souvenir_id: int, interaction_count: int,
    ) -> None:
        from memory.models import PersonProfile

        now = timezone.now()

        defaults = {
            "summary": result.summary,
            "closeness": result.closeness,
            "preferred_tone": result.preferred_tone,
            "topics_of_interest": result.topics_of_interest,
            "sensitive_topics": result.sensitive_topics,
            "confidence": result.confidence,
            "interaction_count": interaction_count,
            "last_interaction_at": now,
            "last_souvenir_id": max_souvenir_id,
            "generated_at": now,
        }

        await sync_to_async(
            lambda: PersonProfile.objects.update_or_create(
                entity=entity, defaults=defaults,
            )
        )()

    # ── Full cycle ────────────────────────────────────────────────

    async def run_cycle(self) -> int:
        """Generate profiles for all due entities. Returns number processed."""
        due = await self.select_due_entities()
        if not due:
            logger.debug("PersonProfile: no entities due")
            return 0

        logger.info("PersonProfile: %d entity(ies) due for regeneration", len(due))
        processed = 0

        for entity, _existing, interaction_count in due:
            try:
                pool, max_id = await self.gather_for_entity(entity)
                result = await self.generate(pool)
                if result is None or not result.is_grounded:
                    logger.info(
                        "PersonProfile: ungrounded output for %s, skipping",
                        entity.name,
                    )
                    continue
                await self.save(entity, result, max_id, interaction_count)
                processed += 1
                logger.info(
                    "PersonProfile generated for %s: closeness=%s, tone=%s",
                    entity.name, result.closeness, result.preferred_tone,
                )
            except Exception:
                logger.exception("PersonProfile failed for %s", entity.name)

        return processed


# ── Helpers ───────────────────────────────────────────────────────


def _validate_choice(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def _format_souvenirs(items: list[dict]) -> str:
    if not items:
        return "(aucun souvenir avec cette personne)"
    return "\n".join(
        f"- [{s.get('emotion', 'neutral')}, imp={s.get('importance', 0):.1f}] "
        f"{s['content']} (themes: {', '.join(s.get('themes', [])) or '-'})"
        for s in items
    )


def _format_connaissances(items: list[dict]) -> str:
    if not items:
        return "(aucune connaissance sur cette personne)"
    return "\n".join(
        f"- [conf={c.get('confidence', 0):.1f}] {c['content']}"
        for c in items
    )


# Module-level singleton
person_profile_generator = PersonProfileGenerator()
