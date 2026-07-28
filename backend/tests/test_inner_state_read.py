"""The single read layer for Mika's inner state (`memory.read`, `conscience.read`).

Three consumers ask about the same rows — the system prompt, the WebSocket
`inner_state` payload, and the dashboard — and each used to carry its own
copy of the query. "Most recent journal" was written twice byte-for-byte
(comment included); "last night's dream" was written three times, and one of
those had drifted into answering a *different question* without anyone
noticing, because nothing tested it.

So these tests do two jobs: pin the queries, and pin the distinction between
the two journal questions that legitimately differ — which is exactly the
kind of thing a later reader "simplifies" into one call.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async

from conscience import read as conscience_read
from memory import read


@pytest.fixture(autouse=True)
def _clean(db):
    from conscience.models import Rumination
    from memory.models import DailyJournal, Dream, SelfNarrative

    DailyJournal.objects.all().delete()
    Dream.objects.all().delete()
    SelfNarrative.objects.all().delete()
    Rumination.objects.all().delete()
    yield


def _journal(day, narrative="rien de special"):
    from memory.models import DailyJournal
    return DailyJournal.objects.create(date=day, narrative=narrative)


def _dream(night, *, content="un reve", vividness=0.8, recalled=False):
    from django.utils import timezone as tz
    from memory.models import Dream
    return Dream.objects.create(
        night_of=night, content=content, vividness=vividness,
        recalled_at=tz.now() if recalled else None,
    )


# ---------------------------------------------------------------------------
# 1. The two journal questions
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestJournalQuestions:
    """`latest_journal` and `journal_for(yesterday)` are NOT the same call.

    A journal is dated the day it *covers*, and light sleep writes it late on
    that same evening. So between ~23h and midnight the newest row is
    today's. A panel titled "journal du jour" should show it; a prompt block
    titled "ton fil d'hier" must not narrate the day still in progress.
    """

    @pytest.mark.asyncio
    async def test_latest_prefers_todays_journal_once_written(self):
        await sync_to_async(_journal)(read.yesterday(), "hier")
        await sync_to_async(_journal)(read.today(), "aujourd'hui")

        journal = await read.latest_journal()
        assert journal.narrative == "aujourd'hui"

    @pytest.mark.asyncio
    async def test_yesterday_stays_yesterday_even_then(self):
        """The regression that would follow from merging the two calls."""
        await sync_to_async(_journal)(read.yesterday(), "hier")
        await sync_to_async(_journal)(read.today(), "aujourd'hui")

        journal = await read.journal_for(read.yesterday())
        assert journal.narrative == "hier"

    @pytest.mark.asyncio
    async def test_latest_falls_back_to_yesterday(self):
        """The usual daytime case: today's has not been written yet.

        Matching strictly on today is what left the panel blank from
        midnight to 23h.
        """
        await sync_to_async(_journal)(read.yesterday(), "hier")

        journal = await read.latest_journal()
        assert journal.narrative == "hier"

    @pytest.mark.asyncio
    async def test_latest_ignores_a_stale_journal(self):
        await sync_to_async(_journal)(read.today() - timedelta(days=4), "vieux")
        assert await read.latest_journal() is None

    @pytest.mark.asyncio
    async def test_latest_window_is_adjustable(self):
        await sync_to_async(_journal)(read.today() - timedelta(days=4), "vieux")
        journal = await read.latest_journal(within_days=7)
        assert journal.narrative == "vieux"

    @pytest.mark.asyncio
    async def test_no_journal_at_all(self):
        assert await read.latest_journal() is None
        assert await read.journal_for(read.yesterday()) is None


# ---------------------------------------------------------------------------
# 2. Dreams — the query that had silently drifted
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDreamOfLastNight:

    @pytest.mark.asyncio
    async def test_it_is_scoped_to_last_night(self):
        """The dashboard used `order_by("-created_at").first()` — the newest
        dream *ever*, presented as last night's. On a quiet week it showed a
        dream from a fortnight earlier."""
        await sync_to_async(_dream)(
            read.today() - timedelta(days=14), content="vieux reve",
        )
        assert await read.dream_of_last_night() is None

    @pytest.mark.asyncio
    async def test_it_returns_the_most_vivid_of_the_night(self):
        await sync_to_async(_dream)(read.yesterday(), content="flou", vividness=0.3)
        await sync_to_async(_dream)(read.yesterday(), content="net", vividness=0.9)

        dream = await read.dream_of_last_night()
        assert dream.content == "net"

    @pytest.mark.asyncio
    async def test_unrecalled_only_skips_an_already_told_dream(self):
        """What the prompt needs: a dream is injected once, not every turn."""
        await sync_to_async(_dream)(read.yesterday(), recalled=True)
        assert await read.dream_of_last_night(unrecalled_only=True) is None

    @pytest.mark.asyncio
    async def test_the_panels_still_see_a_recalled_dream(self):
        """They keep displaying it after Mika has mentioned it."""
        await sync_to_async(_dream)(read.yesterday(), recalled=True)
        assert await read.dream_of_last_night() is not None

    @pytest.mark.asyncio
    async def test_min_vividness_filters_a_forgettable_dream(self):
        await sync_to_async(_dream)(read.yesterday(), vividness=0.2)
        assert await read.dream_of_last_night(min_vividness=0.6) is None

    @pytest.mark.asyncio
    async def test_mark_recalled_stamps_the_row(self):
        dream = await sync_to_async(_dream)(read.yesterday())
        assert await read.mark_dream_recalled(dream) is True

        assert await read.dream_of_last_night(unrecalled_only=True) is None


# ---------------------------------------------------------------------------
# 3. Self-narrative + ruminations
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestSelfNarrative:

    @pytest.mark.asyncio
    async def test_latest_wins(self):
        from memory.models import SelfNarrative

        await sync_to_async(SelfNarrative.objects.create)(content="ancienne")
        await sync_to_async(SelfNarrative.objects.create)(content="recente")

        narrative = await read.latest_self_narrative()
        assert narrative.content == "recente"

    @pytest.mark.asyncio
    async def test_none_when_empty(self):
        assert await read.latest_self_narrative() is None


@pytest.mark.django_db(transaction=True)
class TestActiveRuminations:
    """One query, two appetites: the prompt takes the top 3 above a floor (a
    thought too faint to notice should not be narrated as one), the panel
    takes 5 unfiltered (a fading thought is still worth showing)."""

    @staticmethod
    def _rum(summary, intensity, status="active"):
        from conscience.models import Rumination
        return Rumination.objects.create(
            summary=summary, intensity=intensity, status=status,
        )

    @pytest.mark.asyncio
    async def test_strongest_first(self):
        await sync_to_async(self._rum)("faible", 0.3)
        await sync_to_async(self._rum)("forte", 0.9)

        rows = await conscience_read.active_ruminations()
        assert [r.summary for r in rows] == ["forte", "faible"]

    @pytest.mark.asyncio
    async def test_intensity_floor_is_the_prompts_rule(self):
        await sync_to_async(self._rum)("murmure", 0.1)
        await sync_to_async(self._rum)("nette", 0.8)

        rows = await conscience_read.active_ruminations(limit=3, min_intensity=0.2)
        assert [r.summary for r in rows] == ["nette"]

    @pytest.mark.asyncio
    async def test_the_panel_sees_the_faint_one(self):
        await sync_to_async(self._rum)("murmure", 0.1)
        rows = await conscience_read.active_ruminations(limit=5)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_resolved_and_faded_are_excluded(self):
        await sync_to_async(self._rum)("réglée", 0.9, status="resolved")
        await sync_to_async(self._rum)("éteinte", 0.9, status="faded")

        assert await conscience_read.active_ruminations() == []

    @pytest.mark.asyncio
    async def test_limit_is_respected(self):
        for i in range(8):
            await sync_to_async(self._rum)(f"r{i}", 0.5)
        assert len(await conscience_read.active_ruminations(limit=3)) == 3


# ---------------------------------------------------------------------------
# 4. The consumers actually go through the layer
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestOverviewScreen:
    """End-to-end on the screen that carried the drifted query.

    C'était un point JSON du dashboard ; c'est maintenant la carte « Sommeil »
    de la vue d'ensemble. Elle passe par les mêmes fonctions de `memory.read`,
    ce qui est exactement ce que ces tests protègent : un seul endroit pose la
    question, trois consommateurs la formatent.
    """

    URL = "/gestion/"

    def test_a_fortnight_old_dream_is_not_last_nights(self, client):
        _dream(read.today() - timedelta(days=14), content="vieux reve")

        assert client.get(self.URL).context["sleep"]["dream"] is None

    def test_last_nights_dream_is_shown(self, client):
        _dream(read.yesterday(), content="reve de cette nuit")

        dream = client.get(self.URL).context["sleep"]["dream"]
        assert dream.content == "reve de cette nuit"

    def test_the_latest_journal_is_shown(self, client):
        _journal(read.yesterday(), "hier")

        journal = client.get(self.URL).context["sleep"]["journal"]
        assert journal.narrative == "hier"


class TestNoDuplicateQueries:
    """Guards against a fourth copy appearing. Each consumer is a formatter."""

    def test_broadcast_does_not_query_the_models_directly(self):
        import inspect

        from pipeline import broadcast

        src = inspect.getsource(broadcast)
        for symbol in ("DailyJournal.objects", "Dream.objects",
                       "SelfNarrative.objects", "Rumination.objects",
                       "PersonProfile.objects", "Commitment.objects"):
            assert symbol not in src, f"{symbol} should come from the read layer"

    def test_context_does_not_query_the_models_directly(self):
        import inspect

        from pipeline import context

        src = inspect.getsource(context)
        for symbol in ("DailyJournal.objects", "Dream.objects",
                       "SelfNarrative.objects", "Rumination.objects",
                       "PersonProfile.objects", "Commitment.objects",
                       "EmotionalSummary.objects"):
            assert symbol not in src, f"{symbol} should come from the read layer"

    def test_one_clock_convention(self):
        """The reader must share the writer's clock. `memory.sleep` stamps
        from a naive `datetime.now()`, so `timezone.localdate()` (Django's
        TIME_ZONE) is the wrong question — identical where the two agree,
        off by a day between midnight and dawn where they do not."""
        import inspect

        from GestionSysteme.views import overview

        assert "localdate()" not in inspect.getsource(overview)
