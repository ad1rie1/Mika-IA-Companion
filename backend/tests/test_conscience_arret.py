"""L'arrêt de la conscience, et l'index de son journal (OPS-03 / OPS-01).

`shutdown()` désabonnait et stoppait la boucle sans jamais toucher à
`_fastpath_tasks` : une décision détachée par un signal pertinent pouvait
faire `_act` → `process_message` → des écritures après l'instantané des
pulsions et la passe finale de la mémoire. Elle est désormais annulée et
attendue, borné, AVANT `drive_engine.save_state()`.

`ConscienceLog` n'avait aucun index alors qu'il est requis toutes les 30 s
(`filter(decision="act", created_at__gte=…).count()` +
`order_by("-created_at")[:5]`), au boot, par la rétention et le dashboard.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from utils.degradation import degradations

_LABEL = "conscience: fast-path non moissonnee a l'arret"


def _moteur():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._fastpath_tasks = set()
    e._loop = SimpleNamespace(stop=AsyncMock())
    e._decision_lock = asyncio.Lock()
    e._initialized = True
    e._arret_demande = False
    return e


@contextlib.contextmanager
def _arret_isole(ordre: list):
    """Le bus et les pulsions ne bougent pas ; `save_state` note son passage."""
    from drives.engine import drive_engine
    from utils.eventbus import event_bus

    async def _save():
        ordre.append("save")

    with patch.object(event_bus, "unsubscribe"), \
         patch.object(drive_engine, "save_state", new=AsyncMock(side_effect=_save)):
        yield


@pytest.fixture(autouse=True)
def _registre_propre():
    degradations.reset()
    yield
    degradations.reset()


# ===========================================================================
# 1. Une fast-path en vol est annulée, et rien ne s'écrit après
# ===========================================================================


class TestMoissonDesFastpaths:

    async def test_une_fastpath_en_vol_est_annulee_avant_l_instantane(self):
        e = _moteur()
        ordre: list = []

        async def decision():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                ordre.append("annulee")
                raise
            ordre.append("ecrit")  # jamais atteint

        tache = asyncio.create_task(decision())
        e._fastpath_tasks.add(tache)
        await asyncio.sleep(0)  # la tâche démarre et s'endort

        with _arret_isole(ordre):
            await e.shutdown()

        assert tache.cancelled()
        assert ordre == ["annulee", "save"], (
            "la décision doit être annulée AVANT l'instantané des pulsions, "
            f"et ne rien écrire ensuite : {ordre}"
        )
        assert e._initialized is False
        assert degradations.count_for(_LABEL) == 0

    async def test_une_fastpath_qui_resiste_ne_bloque_pas_l_arret(self):
        """Une tâche coincée (thread d'exécuteur, `except` trop large) ne
        rend pas la main sur `cancel()` : l'arrêt attend un temps borné,
        compte le dépassement, et continue."""
        e = _moteur()
        ordre: list = []

        async def zombie():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(30)  # survit à la première annulation

        tache = asyncio.create_task(zombie())
        e._fastpath_tasks.add(tache)
        await asyncio.sleep(0)

        debut = time.monotonic()
        with _arret_isole(ordre), \
             patch("conscience.engine._FASTPATH_ARRET_TIMEOUT_S", 0.2):
            await e.shutdown()
        duree = time.monotonic() - debut

        assert duree < 2.0, f"l'arrêt a attendu {duree:.1f} s un zombie"
        assert ordre == ["save"], "l'instantané des pulsions a bien eu lieu"
        assert degradations.count_for(_LABEL) == 1, "le dépassement se compte"

        # Nettoyage : la seconde annulation, elle, aboutit.
        tache.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tache

    async def test_sans_fastpath_l_arret_est_inchange(self):
        e = _moteur()
        ordre: list = []
        with _arret_isole(ordre):
            await e.shutdown()
        assert ordre == ["save"]
        assert degradations.count_for(_LABEL) == 0

    async def test_une_tache_deja_finie_n_est_pas_attendue(self):
        e = _moteur()
        ordre: list = []

        async def finie():
            return None

        tache = asyncio.create_task(finie())
        await tache
        e._fastpath_tasks.add(tache)
        with _arret_isole(ordre):
            await e.shutdown()
        assert ordre == ["save"]


# ===========================================================================
# 2. Plus rien ne part une fois l'arrêt demandé
# ===========================================================================


class TestSpawnPendantLArret:

    async def test_spawn_apres_la_demande_d_arret_ne_lance_rien(self):
        """`observe()` peut encore être en vol quand `shutdown()` se
        désabonne ; une décision lancée à cet instant survivrait à la
        moisson."""
        e = _moteur()
        e._arret_demande = True
        with patch.object(type(e), "_decide", new=AsyncMock()) as decide:
            e._spawn_decision()
            await asyncio.sleep(0)
        assert not e._fastpath_tasks
        decide.assert_not_called()

    async def test_spawn_avant_l_arret_lance_bien_la_decision(self):
        e = _moteur()
        with patch.object(type(e), "_decide", new=AsyncMock()) as decide:
            e._spawn_decision()
            assert len(e._fastpath_tasks) == 1
            await asyncio.gather(*e._fastpath_tasks)
        decide.assert_awaited_once_with(compter_les_sauts=False)
        assert not e._fastpath_tasks, "la référence est relâchée à la fin"

    async def test_l_arret_pose_le_drapeau_et_initialize_le_leve(self):
        from conscience.engine import ConscienceEngine

        # Attribut de CLASSE : lu sur des moteurs construits par `__new__`.
        assert ConscienceEngine._arret_demande is False
        e = _moteur()
        with _arret_isole([]):
            await e.shutdown()
        assert e._arret_demande is True


# ===========================================================================
# 3. OPS-01 — l'index du journal de décisions
# ===========================================================================


class TestIndexDuJournal:

    def test_les_index_declares_couvrent_les_deux_lectures(self):
        """`(decision, -created_at)` pour `filter(decision="act")…count()` et
        `order_by("-created_at")[:5]` ; `(-created_at)` pour la rétention et
        le tableau de bord."""
        from conscience.models import ConscienceLog

        champs = [list(index.fields) for index in ConscienceLog._meta.indexes]
        assert ["decision", "-created_at"] in champs, champs
        assert ["-created_at"] in champs, champs

    @pytest.mark.django_db
    def test_la_migration_est_a_jour(self):
        """`makemigrations --check` vide : l'index déclaré sur le modèle est
        bien celui que la migration `conscience/0019` crée."""
        from django.core.management import call_command

        # Lève `SystemExit(1)` quand une migration manque.
        call_command(
            "makemigrations", "conscience", "--check", "--dry-run",
            verbosity=0,
        )
