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
    """Ce qu'elle doit encore à cette personne — les plus PRESSANTS d'abord.

    Le tri était `-created_at` : à partir de la sixième promesse, les trois
    premières — les plus vieilles, donc celles qu'on attend le plus —
    disparaissaient définitivement du prompt, puis basculaient en `dropped` à
    trente jours sans avoir jamais été mentionnées ni proposées à résolution.
    « Et le premier truc dont je t'avais parlé ? » n'avait aucune réponse
    possible. C'est l'inverse exact de la façon dont une personne porte une
    promesse : ce qui traîne pèse plus, pas moins.

    L'ordre est donc : d'abord ce qui a une échéance (la plus proche en tête),
    puis le reste du plus ancien au plus récent. Chaque ligne porte son âge,
    pour qu'elle puisse dire « ça fait trois semaines » plutôt que de réciter
    une liste hors du temps.
    """
    from django.db.models import F
    from django.utils import timezone

    from memory.models import Commitment

    def _lire() -> list[str]:
        maintenant = timezone.now()
        lignes = list(
            Commitment.objects
            .filter(person=entity, status="pending")
            # `F(...).asc(nulls_last=True)` : une échéance datée passe devant
            # tout le reste, et l'absence d'échéance ne se trie pas comme une
            # échéance à l'époque zéro.
            .order_by(F("due_at").asc(nulls_last=True), "created_at")
            .values_list("description", "created_at", "due_at")[:limit]
        )
        rendues = []
        for description, cree_le, echeance in lignes:
            marque = _anciennete_engagement(maintenant, cree_le, echeance)
            rendues.append(f"{description}{marque}" if marque else description)
        return rendues

    return await sync_to_async(_lire)()


def _anciennete_engagement(maintenant, cree_le, echeance) -> str:
    """« (promis il y a trois semaines) », « (échéance dépassée) », ou ''."""
    if echeance is not None:
        jours = (echeance - maintenant).days
        if jours < 0:
            return " (echeance depassee)"
        if jours == 0:
            return " (c'est pour aujourd'hui)"
        if jours <= 7:
            return f" (echeance dans {jours} j)"
    if cree_le is None:
        return ""
    jours = (maintenant - cree_le).days
    if jours >= 14:
        return f" (promis il y a {jours // 7} semaines)"
    if jours >= 2:
        return f" (promis il y a {jours} jours)"
    return ""


async def rows_mentioning_others(model, pks, *, entity_id) -> set[int]:
    """Parmi ``pks``, ceux rattachés à une personne AUTRE que ``entity_id``.

    Le filtrage est fait côté Python et non en ORM parce que la forme ORM
    naturelle est fausse dans le sens dangereux :
    ``.filter(entities__entity_type="person").exclude(entities__id=<pk>)``
    écarte toute ligne ayant *au moins une* entité égale, donc un souvenir
    liant l'interlocuteur ET un tiers sort de l'exclusion et se retrouve
    servi. ``entity_id=None`` (personne non liée) : toute entité-personne
    compte comme autrui.
    """
    pks = [pk for pk in (pks or ()) if pk is not None]
    if not pks:
        return set()

    def _query() -> set[int]:
        rows = model.objects.filter(pk__in=pks).prefetch_related("entities")
        return {
            r.pk for r in rows
            if any(
                e.entity_type == "person" and e.pk != entity_id
                for e in r.entities.all()
            )
        }

    return await sync_to_async(_query)()


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
