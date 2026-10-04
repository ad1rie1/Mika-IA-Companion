"""La nuit mentale : y entrer, la compter, ne pas la piétiner.

Tous ces tests portent sur des pannes qui ne se voyaient pas. Une soirée
calme supprimait la nuit entière (aucun journal, aucun rêve, aucune
digestion) parce que le gate exigeait une tension REST que le gate lui-même
rendait inatteignable ; les trois chemins de transport des appels LLM
nocturnes ne comptaient rien, donc un rôle IA non associé éteignait la vie
nocturne pour toujours, santé au vert ; la digestion rejouait un `status` lu
au début de la passe, ressuscitant une rumination résolue entre-temps ; et le
scoring de la conscience ne savait pas qu'elle dormait — dormir vidant REST,
la nuit la rendait mécaniquement plus bavarde que la veille au soir.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from old.backend.conscience.scoring import SLEEP_PENALTY, compute_decision_score
from old.backend.conscience.types import DecisionContext
from old.backend.memory.sleep import SLEEP_LLM_TIMEOUT, SleepCycle, SleepPhase
from old.backend.utils.degradation import degradations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_GREETED = frozenset({"morning", "evening", "night"})


def _score(ctx: DecisionContext):
    """Même isolation horaire que les autres tests de scoring : sans les
    salutations pré-marquées, un run entre 23 h et minuit ajoute +0.35."""
    return compute_decision_score(ctx, set(_ALL_GREETED), date.today())


def make_context(**kw) -> DecisionContext:
    base = dict(
        pending_observations=[],
        global_mood="happy",
        global_intensity=0.0,
        idle_seconds=0.0,
        in_cooldown=False,
        max_pertinence=0.0,
        weighted_urgency=0.0,
    )
    base.update(kw)
    return DecisionContext(**base)


class FakeScheduledAction:
    def __init__(self, priority: float = 0.5):
        self.priority = priority


def _fake_clock(moment: datetime):
    class _FakeDateTime:
        @staticmethod
        def now():
            return moment
    return _FakeDateTime


async def _run_night(cycle: SleepCycle, moment: datetime, *, idle: float = 1200.0):
    """Un tick complet de run_if_due à `moment`, phases déjà faites."""
    night = SleepCycle._night_of(moment)
    cycle._last_journal_date = night
    cycle._last_dream_night = night
    cycle._dreams_this_night = 99
    cycle._last_digestion_night = night
    cycle._last_reorg_night = night

    with patch("memory.sleep.datetime", _fake_clock(moment)), \
         patch("conscience.engine.conscience_engine") as cons, \
         patch.object(SleepCycle, "_set_phase", new=AsyncMock()) as set_phase:
        cons.get_idle_seconds.return_value = idle
        await cycle.run_if_due()
    return set_phase


# ===========================================================================
# B1 — entrer en sommeil ne dépend plus d'une tension volatile
# ===========================================================================

@pytest.mark.asyncio
class TestEntreeEnSommeil:

    async def test_soiree_calme_elle_dort_quand_meme(self):
        """Le scénario du constat : conversation jusqu'à 20h30, coucher.

        À 23h15 la tension REST est retombée à ~0.01. L'ancien gate sortait
        par AWAKE et la nuit mentale entière n'avait jamais lieu.
        """
        from old.backend.drives.engine import drive_engine
        from old.backend.drives.state import DriveKind

        drive_engine.reset()
        drive_engine.states[DriveKind.REST].tension = 0.01

        cycle = SleepCycle()
        moment = datetime(2026, 7, 27, 23, 15)
        set_phase = await _run_night(cycle, moment)

        assert cycle._asleep_night == date(2026, 7, 27)
        assert set_phase.await_args_list[-1].args[0] == SleepPhase.DEEP_SLEEP

    async def test_reboot_du_soir_ne_supprime_pas_la_nuit(self):
        """Un DriveEngine neuf, c'est exactement l'état d'après-boot."""
        from old.backend.drives.engine import DriveEngine
        from old.backend.drives.state import DriveKind

        neuf = DriveEngine()
        assert neuf.states[DriveKind.REST].tension == 0.0

        cycle = SleepCycle()
        with patch("drives.engine.drive_engine", neuf):
            await _run_night(cycle, datetime(2026, 7, 27, 23, 15))

        assert cycle._asleep_night == date(2026, 7, 27)

    async def test_la_fatigue_avance_le_coucher(self):
        """REST ne peut plus interdire la nuit, il peut l'ouvrir plus tôt."""
        from old.backend.drives.engine import drive_engine
        from old.backend.drives.state import DriveKind

        # Une heure d'avance au plus (deux couchaient un adulte à 21 h).
        moment = datetime(2026, 7, 27, 22, 30)

        drive_engine.reset()
        drive_engine.states[DriveKind.REST].tension = 0.9
        fatiguee = SleepCycle()
        await _run_night(fatiguee, moment)
        assert fatiguee._asleep_night == date(2026, 7, 27)

        drive_engine.reset()
        reposee = SleepCycle()
        await _run_night(reposee, moment)
        assert reposee._asleep_night is None
        assert reposee.phase == SleepPhase.AWAKE

    async def test_une_tension_illisible_ne_supprime_pas_la_nuit(self):
        """Fail-ouvert : l'ancien handler forçait 0.0 *après* avoir fait de
        REST une condition — donc pas de nuit du tout, et sans compteur."""
        degradations.reset()
        cycle = SleepCycle()

        boom = MagicMock()
        boom.update.side_effect = RuntimeError("drive engine down")
        with patch("drives.engine.drive_engine", boom):
            await _run_night(cycle, datetime(2026, 7, 27, 23, 15))

        assert cycle._asleep_night == date(2026, 7, 27)
        assert degradations.count_for("sommeil: tension REST illisible") == 1

    async def test_l_hysteresis_passe_par_l_heure_d_entree(self):
        """Endormie, l'heure nominale reprend : la tension qui fond pendant le
        sommeil ne doit pas refermer le gate et la réveiller à 22h."""
        from old.backend.drives.engine import drive_engine

        drive_engine.reset()
        cycle = SleepCycle()
        assert cycle._night_start_hour(already_asleep=True) == 22
        assert cycle._night_start_hour(already_asleep=False) == 23


# ===========================================================================
# S18 — les appels LLM nocturnes sont comptés, leur budget est un réglage
# ===========================================================================

@pytest.mark.asyncio
class TestComptageDesAppelsNocturnes:

    MATERIAL = {
        "souvenirs_serialized": [
            {"time": "18:00", "content": "un truc", "emotion": "happy", "importance": 0.5},
        ],
        "persons": [],
        "ruminations": [],
        "dominant_emotion": "happy",
    }

    FRAGMENTS = {"souvenirs": [], "rumination": None}

    async def _journal_avec(self, exc):
        degradations.reset()
        cycle = SleepCycle()
        with patch("memory.sleep.ai_router.complete", new=AsyncMock(side_effect=exc)):
            return await cycle._call_journal_llm(dict(self.MATERIAL))

    async def test_un_journal_qui_expire_est_compte(self):
        assert await self._journal_avec(asyncio.TimeoutError()) is None
        assert degradations.count_for("sommeil: journal, appel LLM expire") == 1

    async def test_un_journal_sans_ia_configuree_est_compte(self):
        from old.backend.ai.router import UnconfiguredRoleError

        assert await self._journal_avec(UnconfiguredRoleError("pas de modele")) is None
        assert degradations.count_for("sommeil: journal, IA non configuree") == 1

    async def test_un_journal_en_echec_generique_est_compte(self):
        assert await self._journal_avec(RuntimeError("provider mort")) is None
        assert degradations.count_for("sommeil: journal, appel LLM en echec") == 1

    async def _reve_avec(self, exc):
        degradations.reset()
        cycle = SleepCycle()
        souvenir = MagicMock()
        souvenir.emotion = "happy"
        souvenir.content = "un truc"
        souvenir.themes.all.return_value = []
        fragments = {"souvenirs": [souvenir], "rumination": None}
        with patch("memory.sleep.ai_router.complete", new=AsyncMock(side_effect=exc)):
            return await cycle._call_dream_llm(fragments, "associative")

    async def test_un_reve_qui_expire_est_compte(self):
        assert await self._reve_avec(asyncio.TimeoutError()) is None
        assert degradations.count_for("sommeil: reve, appel LLM expire") == 1

    async def test_un_reve_sans_ia_configuree_est_compte(self):
        from old.backend.ai.router import UnconfiguredRoleError

        assert await self._reve_avec(UnconfiguredRoleError("pas de modele")) is None
        assert degradations.count_for("sommeil: reve, IA non configuree") == 1


class TestBudgetNocturne:

    def test_le_budget_nocturne_est_un_reglage(self):
        from old.backend.configs.registry import registry

        item = registry.get("memory.sleep_llm_timeout")
        assert item is not None
        assert item.default >= 120

    def test_un_registre_illisible_ne_ramene_pas_45s(self):
        with patch("configs.service.config_service.get", side_effect=RuntimeError("no db")):
            assert SleepCycle._llm_timeout() == SLEEP_LLM_TIMEOUT
        assert SLEEP_LLM_TIMEOUT >= 120


# ===========================================================================
# M4 + M10 — la digestion compte ses pannes et n'écrase plus la conscience
# ===========================================================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestDigestionNocturne:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.conscience.models import Rumination
        Rumination.objects.all().delete()
        degradations.reset()
        yield
        Rumination.objects.all().delete()

    @staticmethod
    async def _vieille_rumination(**kw):
        from asgiref.sync import sync_to_async
        from django.utils import timezone as tz

        from old.backend.conscience.models import Rumination

        defaults = dict(
            summary="je me demande si j'ai ete trop seche",
            emotion="frustrated",
            intensity=0.6,
            status="active",
        )
        defaults.update(kw)
        r = await sync_to_async(Rumination.objects.create)(**defaults)
        await sync_to_async(
            lambda: Rumination.objects.filter(pk=r.pk).update(
                created_at=tz.now() - timedelta(hours=3)
            )
        )()
        return r

    async def test_une_selection_de_ruminations_en_echec_est_comptee(self):
        cycle = SleepCycle()
        with patch("conscience.models.Rumination.objects") as objs:
            objs.filter.side_effect = RuntimeError("database is locked")
            assert await cycle._digest_ruminations() == 0
        assert degradations.count_for("sommeil: ruminations a digerer illisibles") == 1

    async def test_une_ecriture_de_digestion_en_echec_est_comptee(self):
        from asgiref.sync import sync_to_async

        from old.backend.conscience.models import Rumination

        r = await self._vieille_rumination()
        cycle = SleepCycle()

        def _boom(self, *a, **kw):
            raise RuntimeError("disque plein")

        with patch.object(Rumination, "save", _boom):
            processed = await cycle._digest_ruminations()

        assert processed == 0
        assert degradations.count_for("sommeil: ecriture de la digestion") == 1
        frais = await sync_to_async(lambda: Rumination.objects.get(pk=r.pk))()
        assert frais.intensity == pytest.approx(0.6)

    async def test_une_rumination_resolue_pendant_la_digestion_n_est_pas_ressuscitee(self):
        """La fenêtre réelle : la conscience écrit pendant l'appel ChromaDB."""
        from asgiref.sync import sync_to_async

        from old.backend.conscience.models import Rumination

        r = await self._vieille_rumination(intensity=0.8)

        async def _resout_puis_rend(*a, **kw):
            await sync_to_async(
                lambda: Rumination.objects.filter(pk=r.pk).update(status="resolved")
            )()
            return None

        cycle = SleepCycle()
        with patch("memory.manager.memory_manager.create_souvenir",
                   new=AsyncMock(side_effect=_resout_puis_rend)):
            await cycle._digest_ruminations()

        frais = await sync_to_async(lambda: Rumination.objects.get(pk=r.pk))()
        assert frais.status == "resolved"

    async def test_une_rumination_toujours_active_est_bien_digeree(self):
        from asgiref.sync import sync_to_async

        from old.backend.conscience.models import Rumination

        r = await self._vieille_rumination(intensity=0.6, emotion="frustrated")

        cycle = SleepCycle()
        with patch("memory.manager.memory_manager.create_souvenir",
                   new=AsyncMock(return_value=None)):
            processed = await cycle._digest_ruminations()

        assert processed == 1
        frais = await sync_to_async(lambda: Rumination.objects.get(pk=r.pk))()
        assert frais.intensity < 0.6
        assert frais.emotion == "relieved"


# ===========================================================================
# P5 — la conscience sait qu'elle dort
# ===========================================================================

class TestScoringPendantLeSommeil:

    # Le contexte du constat, reproduit : 3 h du matin, quatre heures
    # d'inactivite, pulsions positives saturees, et REST vide *parce qu'elle
    # dort* — donc aucune penalite de fatigue.
    NUIT = dict(
        idle_seconds=4 * 3600,
        drive_bonus=0.90,
        drive_rest_penalty=0.0,
        energy=0.45,
    )

    def test_a_3h_endormie_elle_se_tait(self):
        score, reason, _, _ = _score(make_context(sleep_phase="deep_sleep", **self.NUIT))
        assert score < 0.5
        assert "asleep" in reason

    def test_le_meme_contexte_eveille_franchit_le_seuil(self):
        """Le contraste est ce qui pinne le constat : ce n'est pas « tout est
        bas la nuit », c'est bien la phase de sommeil qui décide."""
        score, _, _, _ = _score(make_context(sleep_phase="awake", **self.NUIT))
        assert score >= 0.5

    def test_un_signal_critique_reveille_quand_meme(self):
        score, reason, _, _ = _score(
            make_context(sleep_phase="rem", max_pertinence=0.95, **self.NUIT)
        )
        assert score > 0
        assert "sommeil(" in reason
        assert f"-{SLEEP_PENALTY:.2f}" in reason

    def test_une_action_programmee_reveille(self):
        score, reason, _, _ = _score(
            make_context(
                sleep_phase="deep_sleep",
                scheduled_actions=[FakeScheduledAction(0.9)],
                **self.NUIT,
            )
        )
        assert score > 0
        assert "asleep" not in reason

    def test_le_salut_n_est_pas_brule_par_une_nuit(self):
        """`check_time_trigger` marque la période dès la passe de scoring : le
        veto doit passer avant, ou le salut de 23 h est dépensé pendant qu'elle
        dort."""
        with patch("conscience.scoring.datetime") as horloge:
            horloge.now.return_value = datetime(2026, 7, 27, 23, 30)
            _, _, greeted, _ = compute_decision_score(
                make_context(sleep_phase="deep_sleep", **self.NUIT), set(), date.today()
            )
        assert "night" not in greeted


# ===========================================================================
# P6 — le réveil n'est plus un effet de bord d'une réponse réussie
# ===========================================================================

class TestNoteActivity:

    def test_note_activity_avance_l_horloge_d_inactivite(self):
        import time

        from old.backend.conscience.engine import ConscienceEngine

        e = ConscienceEngine()
        e._last_activity = time.time() - 3 * 3600
        e.note_activity()
        assert e.get_idle_seconds() < 1

    def test_note_activity_ignore_les_personnes_internes(self):
        import time

        from old.backend.conscience.engine import ConscienceEngine

        e = ConscienceEngine()
        passe = time.time() - 3 * 3600
        e._last_activity = passe
        e.note_activity("conscience_mika")
        assert e._last_activity == passe

    def test_note_activity_ne_fait_aucune_io(self):
        """Elle est appelée sur le chemin chaud, avant l'appel IA."""
        from old.backend.conscience.engine import ConscienceEngine

        assert not inspect.iscoroutinefunction(ConscienceEngine.note_activity)

    def test_un_socket_anonyme_est_bien_quelqu_un_qui_parle(self):
        import time

        from old.backend.conscience.engine import ConscienceEngine

        e = ConscienceEngine()
        e._last_activity = time.time() - 3 * 3600
        e.note_activity("anon_4f2e")
        assert e.get_idle_seconds() < 1


class TestNoteInteraction:

    @staticmethod
    def _endormie() -> SleepCycle:
        cycle = SleepCycle()
        cycle._phase = SleepPhase.DEEP_SLEEP
        cycle._asleep_night = date(2026, 7, 27)
        return cycle

    def test_note_interaction_reveille_immediatement(self):
        """Sans await : la frame `speech` du tour en cours lit la phase en
        plein milieu, et lisait `deep_sleep` pendant que le TTS parlait."""
        cycle = self._endormie()
        cycle.note_interaction()
        assert cycle.phase == SleepPhase.AWAKE
        assert cycle._asleep_night is None

    def test_note_interaction_ne_leve_pas_sans_boucle(self):
        cycle = self._endormie()
        cycle.note_interaction()  # contexte synchrone pur, pas de boucle
        assert cycle.phase == SleepPhase.AWAKE

    def test_note_interaction_ne_rejoue_pas_la_nuit(self):
        cycle = self._endormie()
        cycle._last_journal_date = date(2026, 7, 27)
        cycle._dreams_this_night = 2
        cycle._last_digestion_night = date(2026, 7, 27)
        cycle.note_interaction()
        assert cycle._last_journal_date == date(2026, 7, 27)
        assert cycle._dreams_this_night == 2
        assert cycle._last_digestion_night == date(2026, 7, 27)

    @pytest.mark.asyncio
    async def test_note_interaction_est_idempotente(self):
        cycle = self._endormie()
        with patch("pipeline.broadcast.broadcast_inner_state_update",
                   new=AsyncMock()) as diffusion:
            cycle.note_interaction()
            cycle.note_interaction()
            cycle.note_interaction()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert diffusion.await_count == 1

    def test_note_interaction_ne_fait_aucune_io(self):
        assert not inspect.iscoroutinefunction(SleepCycle.note_interaction)
