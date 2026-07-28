"""Read layer for the memory-owned pieces of Mika's inner state.

One function per *question*, returning rows — never formatted output. The
three consumers each format for their own audience: the system prompt wants
French prose, the WebSocket payload wants JSON for the InnerLifePanel, the
dashboard wants JSON for an admin table. Those are genuinely different, and
none of them is a reason to write the query three times.

Which is what was happening. "The most recent journal" existed twice,
byte-for-byte, in ``pipeline/broadcast.py`` and ``dashboard/views/api/
sleep.py`` — including the same explanatory comment, written twice. "Last
night's dream" existed three times and one of them silently asked a
different question (see ``dream_of_last_night``). The signature of that kind
of duplication is that a fix lands in one copy and not the others.

**Clock.** Everything here dates from the naive local wall clock
(``date.today()``), because that is what the *writer* uses:
``memory.sleep`` stamps journals and dreams from ``datetime.now()``. The
dashboard had drifted to ``timezone.localdate()``, which reads Django's
``TIME_ZONE`` instead of the OS one — identical on a box where the two agree
and quietly off by a day between midnight and dawn on a box where they do
not. A reader must share its writer's clock; see ``today()``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


def today() -> date:
    """Mika's current day, on the same clock the sleep cycle writes with.

    Deliberately naive-local rather than ``timezone.localdate()``. The
    circadian / sleep / journal logic all reasons in naive local time (that
    is why ``TIME_ZONE`` is pinned to match), so a reader that asks Django
    for the date is asking a different clock than the one that stamped the
    row it is looking for.
    """
    return date.today()


def yesterday() -> date:
    return today() - timedelta(days=1)


# ── Daily journal ─────────────────────────────────────────────────


async def latest_journal(*, within_days: int = 1):
    """The most recent journal, looking back ``within_days``.

    Distinct from ``journal_for(yesterday())``, and both are wanted: a
    journal is dated the day it *covers*, and light sleep writes it late on
    that same evening. So between ~23h and midnight the newest journal is
    today's — which is what a panel labelled "journal du jour" should show,
    and is exactly *not* what a prompt block labelled "ton fil d'hier"
    should. Matching strictly on today left the panel blank from midnight
    to 23h, which is the bug this signature exists to keep fixed.
    """
    from memory.models import DailyJournal

    return await sync_to_async(
        lambda: DailyJournal.objects
        .filter(date__gte=today() - timedelta(days=within_days))
        .order_by("-date")
        .first()
    )()


async def journal_for(day: date):
    """The journal covering a specific day, or None."""
    from memory.models import DailyJournal

    return await sync_to_async(
        lambda: DailyJournal.objects.filter(date=day).first()
    )()


# ── Dreams ────────────────────────────────────────────────────────


async def dream_of_last_night(
    *, unrecalled_only: bool = False, min_vividness: float = 0.0,
):
    """The most vivid dream from the night that just ended, or None.

    ``unrecalled_only`` + ``min_vividness`` are what the prompt needs (it
    injects a dream once, and only a memorable one); the panels pass
    neither, because they keep displaying a dream after Mika has mentioned
    it.

    Note what this is *not*: the dashboard used to answer this question with
    ``Dream.objects.order_by("-created_at").first()`` — the newest dream
    ever recorded, presented as "last night's". On a quiet week it showed a
    dream from a fortnight earlier. Scoping to ``night_of`` is the whole
    point of the field.
    """
    from memory.models import Dream

    last_night = yesterday()

    def _query():
        qs = Dream.objects.filter(night_of=last_night)
        if unrecalled_only:
            qs = qs.filter(recalled_at__isnull=True)
        if min_vividness > 0:
            qs = qs.filter(vividness__gte=min_vividness)
        return qs.order_by("-vividness").first()

    return await sync_to_async(_query)()


async def mark_dream_recalled(dream) -> bool:
    """Stamp ``recalled_at`` so a dream is injected into the prompt once.

    Returns whether the write landed. A failure here is acceptable and the
    caller should proceed: losing the recall trace is better than blocking
    the turn, and far better than double-injecting the same dream.
    """
    from django.utils import timezone as tz

    try:
        dream.recalled_at = tz.now()
        await sync_to_async(dream.save)(update_fields=["recalled_at"])
        return True
    except Exception:
        logger.debug("Dream recalled_at save failed", exc_info=True)
        return False


# ── Self-narrative ────────────────────────────────────────────────


async def latest_self_narrative():
    """The newest autobiographical paragraph, or None."""
    from memory.models import SelfNarrative

    return await sync_to_async(
        lambda: SelfNarrative.objects.order_by("-created_at").first()
    )()


# ── Per-person material ───────────────────────────────────────────
#
# Callers must have cleared the identity disclosure bar before asking. This
# layer answers "what does memory hold about this entity"; whether Mika may
# *use* it is identity.trust's decision and stays with the caller, which is
# the only place that knows the channel and the certainty.


async def person_profile_for(entity):
    """The theory-of-mind profile for an entity, or None.

    ``select_related("entity")`` because both consumers read
    ``profile.entity.name``, and a lazy relation traversed outside
    ``sync_to_async`` raises ``SynchronousOnlyOperation`` — which is the
    kind of failure that only shows up once the row exists.
    """
    from memory.models import PersonProfile

    return await sync_to_async(
        lambda: PersonProfile.objects
        .select_related("entity")
        .filter(entity=entity)
        .first()
    )()


async def pending_commitments_for(entity, *, limit: int = 5) -> list[str]:
    """Descriptions of what Mika still owes this person, newest first."""
    from memory.models import Commitment

    return await sync_to_async(
        lambda: list(
            Commitment.objects
            .filter(person=entity, status="pending")
            .order_by("-created_at")
            .values_list("description", flat=True)[:limit]
        )
    )()


async def recent_daily_summaries(person_id: str, *, days: int = 7) -> list:
    """Per-day emotional summaries for a person, newest first."""
    from memory.models import EmotionalSummary

    return await sync_to_async(
        lambda: list(
            EmotionalSummary.objects
            .filter(person_id=person_id, period_type="daily")
            .order_by("-period_start")[:days]
        )
    )()
