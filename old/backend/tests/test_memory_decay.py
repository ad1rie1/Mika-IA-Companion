"""Tests for souvenir importance decay.

The decay pass must be *relative* (multiply the stored importance by
rate^elapsed) and not *absolute* (recompute rate^age from scratch): the
conscience boosts souvenirs it finds pertinent, the sleep cycle writes
reflective souvenirs with a hand-set importance, and both must survive the
next consolidator tick.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


def _make_consolidator():
    from old.backend.memory.storage.consolidator import MemoryConsolidator
    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    return c


async def _run_decay():
    await _make_consolidator()._decay_souvenirs()


def _boost_pendant_la_passe(monkeypatch, pk, valeur):
    """Sceau déterministe : la Conscience booste juste après la lecture du lot.

    Le lot est matérialisé à T0 puis traité avec des ``await`` — c'est
    exactement la fenêtre dans laquelle ``boost_souvenirs_by_themes`` écrit
    ``save(update_fields=["importance"])``. Le premier appel à
    ``sync_to_async`` du passage EST cette lecture.
    """
    from asgiref.sync import sync_to_async as vrai

    import old.backend.memory.storage.consolidator as consolidator_mod

    etat = {"appels": 0}

    def spy(fn, *args, **kwargs):
        enveloppe = vrai(fn, *args, **kwargs)

        async def _appel(*a, **kw):
            resultat = await enveloppe(*a, **kw)
            etat["appels"] += 1
            if etat["appels"] == 1:
                from old.backend.memory.models import Souvenir

                await vrai(
                    lambda: Souvenir.objects.filter(pk=pk).update(importance=valeur)
                )()
            return resultat

        return _appel

    monkeypatch.setattr(consolidator_mod, "sync_to_async", spy)


@pytest.mark.django_db(transaction=True)
class TestSouvenirDecay:

    @pytest.mark.asyncio
    async def test_boost_is_not_wiped_by_next_pass(self):
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="quelque chose d'important",
            importance=0.9,          # boosted by the conscience
            occurred_at=now - timedelta(days=3),
            decayed_at=now,          # just decayed
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        # No elapsed time since the anchor → importance untouched, and in
        # particular NOT recomputed down to rate**3.
        assert s.importance == pytest.approx(0.9, abs=0.01)

    @pytest.mark.asyncio
    async def test_fresh_low_importance_is_not_inflated(self):
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="détail mineur",
            importance=0.3,
            occurred_at=now,
            decayed_at=now,
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_elapsed_time_actually_decays(self):
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir vieillissant",
            importance=1.0,
            occurred_at=now - timedelta(days=10),
            decayed_at=now - timedelta(days=10),
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance < 1.0
        assert s.decayed_at is not None and s.decayed_at > now - timedelta(minutes=1)

    @pytest.mark.asyncio
    async def test_decay_is_not_applied_twice_for_the_same_elapsed_time(self):
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir vieillissant",
            importance=1.0,
            occurred_at=now - timedelta(days=10),
            decayed_at=now - timedelta(days=10),
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        after_first = s.importance
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        # The anchor moved with the first pass, so an immediate second pass
        # is a no-op instead of re-applying ten days of decay.
        assert s.importance == pytest.approx(after_first, abs=0.01)

    @pytest.mark.asyncio
    async def test_missing_anchor_falls_back_to_occurred_at(self):
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir hérité sans ancre",
            importance=1.0,
            occurred_at=now - timedelta(days=5),
            decayed_at=None,
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance < 1.0
        assert s.decayed_at is not None

    @pytest.mark.asyncio
    async def test_souvenir_sous_le_seuil_s_endort_au_lieu_d_etre_efface(self):
        """L'oubli déplace, il ne détruit pas.

        Un souvenir qui passe sous le seuil sort du rappel spontané et cesse
        d'y décroître — mais la ligne reste, avec son vecteur, donc une
        recherche délibérée le retrouve et un boost le ranime. Auparavant
        c'était un DELETE : la mémoire *interprétée* avait un horizon de six
        semaines pendant que la transcription brute était éternelle.
        """
        from old.backend.memory.models import Souvenir
        from old.backend.memory.storage.consolidator import _dormant_floor

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir mourant",
            importance=0.11,
            occurred_at=now - timedelta(days=400),
            decayed_at=now - timedelta(days=400),
        )
        await _run_decay()

        exists = await sync_to_async(Souvenir.objects.filter(pk=s.pk).exists)()
        assert exists, "la décroissance ne doit plus jamais supprimer une ligne"

        await sync_to_async(s.refresh_from_db)()
        plancher = _dormant_floor(0.1)
        assert s.importance == pytest.approx(plancher)
        assert s.importance < 0.1, "il est bien sorti du rappel spontané"

    @pytest.mark.asyncio
    async def test_un_souvenir_endormi_n_est_plus_reecrit(self):
        """Une fois au plancher, il ne coûte plus ni écriture ni ré-index."""
        from old.backend.memory.models import Souvenir
        from old.backend.memory.storage.consolidator import _dormant_floor

        now = timezone.now()
        plancher = _dormant_floor(0.1)
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir endormi de longue date",
            importance=plancher,
            occurred_at=now - timedelta(days=400),
            decayed_at=now - timedelta(days=400),
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance == pytest.approx(plancher)
        assert s.decayed_at == now - timedelta(days=400), "ancre inchangée"

    @pytest.mark.asyncio
    async def test_un_boost_tombe_pendant_la_passe_n_est_pas_detruit(self, monkeypatch):
        """C'est précisément le vieux souvenir que le boost existe pour ranimer."""
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir que la Conscience vient de retrouver",
            importance=0.11,
            occurred_at=now - timedelta(days=400),
            decayed_at=now - timedelta(days=400),
        )
        _boost_pendant_la_passe(monkeypatch, s.pk, 0.61)

        await _run_decay()

        assert await sync_to_async(Souvenir.objects.filter(pk=s.pk).exists)()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance == pytest.approx(0.61)

    @pytest.mark.asyncio
    async def test_un_boost_tombe_pendant_la_passe_n_est_pas_ecrase(self, monkeypatch):
        from old.backend.memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir vieillissant mais pertinent",
            importance=0.5,
            occurred_at=now - timedelta(days=10),
            decayed_at=now - timedelta(days=10),
        )
        _boost_pendant_la_passe(monkeypatch, s.pk, 1.0)

        await _run_decay()

        await sync_to_async(s.refresh_from_db)()
        assert s.importance == pytest.approx(1.0)
