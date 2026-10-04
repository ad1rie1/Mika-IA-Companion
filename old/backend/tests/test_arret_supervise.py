"""Arrêt et démarrage supervisés (REF-09 : OPS-02, OPS-04, OPS-09, OPS-16).

Ce que ces tests pinent :

- l'arrêt du lifespan est une suite d'étapes **bornées** : une étape qui ne
  rend pas la main dans son budget est annulée, comptée, et la suivante
  s'exécute quand même (OPS-02) ;
- l'**ordre** : conscience et modules sont arrêtés avant les passes finales
  mémoire/émotion, sinon un `notify_ai` hors file modifiait l'état
  émotionnel après sa sauvegarde (OPS-04) ;
- le consolidateur pointe son checkpoint **par tranche**, et un arrêt entre
  deux tranches laisse le curseur sur la dernière stockée — jamais sous le
  courant, jamais au-delà de ce qui est stocké ;
- `consolidator.stop()` n'attend un tick que `STOP_GRACE_S` ;
- la mémoire longue se charge **après** que `initialize` a rendu la main, et
  un refus en mode différé passe par le crochet d'arrêt (OPS-09) ;
- `/health` dit `starting` (503) tant que ça charge, `ok` (200) quand tout y
  est, `degraded` (200) sur un rôle non mappé, `failed` (503) sur refus
  (OPS-16) ;
- le budget interne total tient sous le `TimeoutStopSec` de l'unit systemd.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import textwrap
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent


# ═══════════════════════════════════════════════════════════════════
# 1. L'arrêt du lifespan : borné, ordonné, jamais interrompu
# ═══════════════════════════════════════════════════════════════════


ORDRE_ATTENDU = [
    "telegram", "drain", "queue_stop",
    "conscience", "modules", "runner", "sleep", "emotion_sync",
    "memoire", "emotion", "broadcasts", "wal",
]


@pytest.fixture
def arret(monkeypatch):
    """Chaque singleton de l'arrêt remplacé par une coroutine qui note son
    nom — et dort ``retards[nom]`` secondes ou lève ``erreurs[nom]``."""
    import old.backend.config.asgi as asgi
    import old.backend.pipeline.processor as processor
    from old.backend.communication.channels import telegram_channel
    from old.backend.conscience.engine import conscience_engine
    from old.backend.emotion.engine import emotion_engine
    from old.backend.emotion.sync import emotion_sync
    from old.backend.memory.manager import memory_manager
    from old.backend.memory.sleep import sleep_cycle
    from old.backend.modules.manager import module_manager
    from old.backend.pipeline.turns import turn_queue
    from old.backend.projects.runner import project_runner

    appels: list[str] = []
    retards: dict[str, float] = {}
    erreurs: dict[str, Exception] = {}

    def _etape(nom):
        async def _f(*a, **k):
            appels.append(nom)
            if nom in erreurs:
                raise erreurs[nom]
            if nom in retards:
                await asyncio.sleep(retards[nom])
        return _f

    monkeypatch.setattr(telegram_channel, "stop", _etape("telegram"))
    monkeypatch.setattr(turn_queue, "drain", _etape("drain"))
    monkeypatch.setattr(turn_queue, "stop", _etape("queue_stop"))
    monkeypatch.setattr(conscience_engine, "shutdown", _etape("conscience"))
    monkeypatch.setattr(module_manager, "stop_all", _etape("modules"))
    monkeypatch.setattr(project_runner, "stop", _etape("runner"))
    monkeypatch.setattr(sleep_cycle, "stop", _etape("sleep"))
    monkeypatch.setattr(emotion_sync, "stop", _etape("emotion_sync"))
    monkeypatch.setattr(memory_manager, "shutdown", _etape("memoire"))
    monkeypatch.setattr(emotion_engine, "shutdown", _etape("emotion"))
    monkeypatch.setattr(processor, "flush_delayed_broadcasts", _etape("broadcasts"))
    monkeypatch.setattr(asgi, "_wal_checkpoint_sync", lambda: appels.append("wal"))
    monkeypatch.setattr(asgi, "BUDGETS_ARRET_S", dict(asgi.BUDGETS_ARRET_S))
    return asgi, appels, retards, erreurs


class TestArretBorne:

    async def test_l_ordre_des_etapes(self, arret):
        asgi, appels, _, _ = arret
        await asgi.LifespanWrapper(None)._shutdown()
        assert appels == ORDRE_ATTENDU

    async def test_conscience_et_modules_avant_les_passes_finales(self, arret):
        """OPS-04 : un `notify_ai` de module ou un acte de la conscience passe
        hors file et modifie l'état émotionnel ; après la sauvegarde, c'est
        perdu. Les deux doivent être morts avant que mémoire et émotion
        écrivent leur état final."""
        asgi, appels, _, _ = arret
        await asgi.LifespanWrapper(None)._shutdown()
        for vivant in ("conscience", "modules", "runner", "sleep"):
            assert appels.index(vivant) < appels.index("memoire")
            assert appels.index(vivant) < appels.index("emotion")
        # Et la file de tours est vidée avant qu'on coupe ce qui la sert.
        assert appels.index("drain") < appels.index("conscience")
        # Le checkpoint WAL en tout dernier : plus rien n'écrit.
        assert appels[-1] == "wal"

    async def test_une_etape_hors_budget_ne_bloque_pas_les_suivantes(self, arret):
        """OPS-02 : la passe mémoire qui ne rend pas la main (un tick de N
        tranches × 120 s) ne doit ni retarder la sauvegarde de l'état
        émotionnel ni faire tomber le SIGKILL de systemd dessus."""
        from old.backend.utils.degradation import degradations

        asgi, appels, retards, _ = arret
        asgi.BUDGETS_ARRET_S["memoire"] = 0.2
        retards["memoire"] = 5.0
        avant = degradations.count_for("arret: memoire hors budget")

        debut = time.monotonic()
        await asgi.LifespanWrapper(None)._shutdown()
        duree = time.monotonic() - debut

        assert duree < 2.0, f"l'arrêt a attendu l'étape hors budget ({duree:.1f}s)"
        assert appels[appels.index("memoire") + 1:] == ["emotion", "broadcasts", "wal"]
        assert degradations.count_for("arret: memoire hors budget") == avant + 1

    async def test_une_etape_en_erreur_est_comptee_et_n_arrete_rien(self, arret):
        from old.backend.utils.degradation import degradations

        asgi, appels, _, erreurs = arret
        erreurs["conscience"] = RuntimeError("bus déjà fermé")
        avant = degradations.count_for("arret: conscience")

        await asgi.LifespanWrapper(None)._shutdown()

        assert appels == ORDRE_ATTENDU
        assert degradations.count_for("arret: conscience") == avant + 1

    async def test_l_etat_du_processus_suit_l_arret(self, arret):
        from old.backend.config.readiness import etat_processus

        asgi, _, _, _ = arret
        phases = []
        original = etat_processus.passer_a
        phases_vues = lambda phase: (phases.append(phase), original(phase))  # noqa: E731
        with patch.object(etat_processus, "passer_a", side_effect=phases_vues):
            await asgi.LifespanWrapper(None)._shutdown()
        assert phases == ["stopping", "stopped"]
        etat_processus.passer_a("absent")

    def test_le_budget_total_tient_sous_l_unit_systemd(self):
        """`TimeoutStopSec` de deploy/mika.service doit rester au-dessus de la
        somme des budgets : sinon le SIGKILL tombe au milieu d'une étape, ce
        que tout le découpage existe pour éviter."""
        import old.backend.config.asgi as asgi

        unit = (RACINE / "deploy" / "mika.service").read_text()
        m = re.search(r"^TimeoutStopSec=(\d+)", unit, re.MULTILINE)
        assert m, "TimeoutStopSec absent de l'unit"
        assert asgi.BUDGET_ARRET_TOTAL_S == pytest.approx(sum(asgi.BUDGETS_ARRET_S.values()))
        assert asgi.BUDGET_ARRET_TOTAL_S < int(m.group(1))
        # Et un code 3 (mémoire refusée) ne relance pas en boucle.
        assert re.search(r"^RestartPreventExitStatus=3", unit, re.MULTILINE)

    def test_chaque_etape_de_l_arret_a_un_budget(self):
        """Toute étape passée à `_etape` dans `_shutdown` lit son budget dans
        `BUDGETS_ARRET_S` — par l'AST, pas par le texte."""
        import ast
        import inspect

        import old.backend.config.asgi as asgi

        arbre = ast.parse(textwrap.dedent(inspect.getsource(asgi.LifespanWrapper._shutdown)))
        noms = [
            n.args[0].value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_etape" and isinstance(n.args[0], ast.Constant)
        ]
        assert len(noms) == len(ORDRE_ATTENDU)
        assert set(noms) == set(asgi.BUDGETS_ARRET_S)


# ═══════════════════════════════════════════════════════════════════
# 2. Le consolidateur : checkpoint par tranche, arrêt borné
# ═══════════════════════════════════════════════════════════════════


def _msg(i, content, role="user"):
    return {
        "id": i, "role": role, "content": content, "created_at": None,
        "person_id": "web_a", "source": "frontend",
    }


def _chunk(cid, embedding, ts, first, last):
    return {
        "id": cid, "content": "x", "embedding": embedding,
        "metadata": {"ts": ts, "handle": "web_a", "conversation_id": 1,
                     "first_message_id": first, "last_message_id": last},
    }


def _reussite():
    return {"souvenirs": 1, "connaissances": 0, "commitments": 0,
            "tentees": 1, "echouees": 0}


def _conso(chunks=(), *, dernier_id=0):
    """Un consolidateur sans base : store simulé, checkpoint noté."""
    from old.backend.memory.storage.consolidator import MemoryConsolidator

    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c._last_processed_id = dernier_id
    c.vector_store = MagicMock()
    c.vector_store.get_exchanges_for_messages = MagicMock(return_value=list(chunks))
    c.extractor = MagicMock()
    c.extractor.analyze_messages = AsyncMock(
        side_effect=lambda msgs, **kw: [{"type": "souvenir", "content": msgs[0]["content"]}],
    )
    c.store_extractions = AsyncMock(side_effect=lambda *a, **k: _reussite())
    c._resolve_interlocutors = AsyncMock(return_value=[])
    c._noms_des_interlocuteurs = AsyncMock(return_value={})
    c._save_checkpoint = AsyncMock()
    return c


@pytest.fixture
def _tranche_de_100(monkeypatch):
    """Six messages de 30 caractères → deux tranches linéaires sans chunk."""
    import old.backend.memory.storage.consolidator as consolidator_mod
    from old.backend.memory.themes import ThemeTuning

    monkeypatch.setattr(consolidator_mod, "EXTRACTION_MAX_CHARS", 100)
    monkeypatch.setattr(
        consolidator_mod, "theme_tuning",
        lambda: ThemeTuning(similarity=0.8, max_clusters=20, min_cluster_chars=0),
    )


def _six_messages():
    return [_msg(i, f"M{i}" * 15) for i in range(1, 7)]


@pytest.mark.django_db
@pytest.mark.usefixtures("_tranche_de_100")
class TestCheckpointParTranche:

    async def test_chaque_tranche_stockee_est_pointee_aussitot(self):
        c = _conso()
        _counts, borne = await c._extract_and_store(_six_messages())

        assert borne == 6
        bornes = [a.args[0] for a in c._save_checkpoint.await_args_list]
        assert bornes == [3, 6]
        assert c._last_processed_id == 6
        # Les lignes comptent des DELTAS, pas des cumuls : 3 + 3 messages,
        # 1 + 1 souvenirs.
        assert [a.args[1] for a in c._save_checkpoint.await_args_list] == [3, 3]
        assert [a.args[2]["souvenirs"] for a in c._save_checkpoint.await_args_list] == [1, 1]

    async def test_un_arret_entre_deux_tranches_laisse_le_curseur_sur_la_derniere_stockee(self):
        """OPS-02, le cœur : `stop()` arrive pendant le stockage de la
        première tranche. La seconde n'est pas tentée, rien n'est stocké
        sans checkpoint, et le curseur est exactement sur ce qui l'est."""
        c = _conso()

        async def _stocke_puis_arret(*a, **k):
            c._arret_demande = True
            return _reussite()
        c.store_extractions = AsyncMock(side_effect=_stocke_puis_arret)

        _counts, borne = await c._extract_and_store(_six_messages())

        assert c.extractor.analyze_messages.await_count == 1
        assert borne == 3
        assert c._last_processed_id == 3
        assert [a.args[0] for a in c._save_checkpoint.await_args_list] == [3]

    async def test_la_regle_ensembliste_tient_par_tranche(self):
        """Thèmes non contigus : A (1, 3, 5) stocké, B (2, 4, 6) pas encore →
        la borne intermédiaire est min(B) − 1 = 1, jamais 5. Réussir A ne
        dit rien du message 2."""
        messages = [
            _msg(1, "A1" * 15), _msg(2, "B1" * 15), _msg(3, "A2" * 15),
            _msg(4, "B2" * 15), _msg(5, "A3" * 15), _msg(6, "B3" * 15),
        ]
        chunks = [
            _chunk("1", [1.0, 0.0], 1, 1, 1), _chunk("2", [0.0, 1.0], 2, 2, 2),
            _chunk("3", [1.0, 0.0], 3, 3, 3), _chunk("4", [0.0, 1.0], 4, 4, 4),
            _chunk("5", [1.0, 0.0], 5, 5, 5), _chunk("6", [0.0, 1.0], 6, 6, 6),
        ]
        c = _conso(chunks)

        async def _stocke_puis_arret(*a, **k):
            c._arret_demande = True
            return _reussite()
        c.store_extractions = AsyncMock(side_effect=_stocke_puis_arret)

        _counts, borne = await c._extract_and_store(messages)

        assert [m["content"][:2] for m in c.extractor.analyze_messages.await_args_list[0].args[0]] == ["A1", "A2", "A3"]
        assert borne == 1
        assert c._last_processed_id == 1

    async def test_le_checkpoint_par_tranche_ne_descend_jamais_sous_le_courant(self):
        c = _conso(dernier_id=4)
        async def _stocke_puis_arret(*a, **k):
            c._arret_demande = True
            return _reussite()
        c.store_extractions = AsyncMock(side_effect=_stocke_puis_arret)

        _counts, borne = await c._extract_and_store(_six_messages())

        # La première tranche (1, 2, 3) est sous le courant : rien n'est écrit.
        assert borne == 4
        assert c._last_processed_id == 4
        c._save_checkpoint.assert_not_awaited()

    async def test_une_tranche_toute_en_echec_n_est_pas_pointee(self):
        c = _conso()
        c.store_extractions = AsyncMock(return_value={
            "souvenirs": 0, "connaissances": 0, "commitments": 0,
            "tentees": 1, "echouees": 1,
        })

        _counts, borne = await c._extract_and_store(_six_messages())

        assert borne is None
        c._save_checkpoint.assert_not_awaited()
        assert c._last_processed_id == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_tranche_de_100")
class TestPasseAvecCheckpointParTranche:
    """Fenêtre réelle en base ; `transaction=True` parce que la passe lit et
    écrit par `sync_to_async` depuis le thread exécuteur."""

    @pytest.fixture(autouse=True)
    def _base_vierge(self):
        from old.backend.memory.models import ConsolidationLog, Conversation, Message, Souvenir
        for modele in (ConsolidationLog, Message, Souvenir, Conversation):
            modele.objects.all().delete()
        yield
        for modele in (ConsolidationLog, Message, Souvenir, Conversation):
            modele.objects.all().delete()

    async def test_la_passe_n_ecrit_pas_une_seconde_ligne_egale_a_la_derniere_tranche(self):
        """Après deux tranches pointées (3 puis 6), `_passe` ne réécrit pas
        une ligne à 6 — et saute la maintenance quand l'arrêt est demandé."""
        from asgiref.sync import sync_to_async

        from old.backend.memory.models import ConsolidationLog, Conversation, Message
        from old.backend.memory.storage.consolidator import MemoryConsolidator

        conv = await Conversation.objects.acreate()
        pks = []
        for i in range(1, 7):
            m = await Message.objects.acreate(
                conversation=conv, role="user", source="frontend",
                content=f"M{i}" * 15, person_id="web_a",
            )
            pks.append(m.pk)

        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c._last_processed_id = pks[0] - 1
        c.vector_store = MagicMock()
        c.vector_store.get_exchanges_for_messages = MagicMock(return_value=[])
        c.extractor = MagicMock()
        c.extractor.analyze_messages = AsyncMock(return_value=[{"type": "souvenir", "content": "x"}])
        c.store_extractions = AsyncMock(side_effect=lambda *a, **k: _reussite())
        c._resolve_interlocutors = AsyncMock(return_value=[])
        c._run_maintenance = AsyncMock()

        await c._consolidate()

        lignes = await sync_to_async(
            lambda: list(ConsolidationLog.objects.order_by("pk")
                         .values_list("last_message_id", "messages_processed"))
        )()
        assert lignes == [(pks[2], 3), (pks[5], 3)]
        assert c._last_processed_id == pks[5]
        c._run_maintenance.assert_awaited_once_with(regenerate=True)

        # Même fenêtre, arrêt demandé après la première tranche : pas de
        # maintenance, et la seconde tranche reste due.
        await sync_to_async(ConsolidationLog.objects.all().delete)()
        c._last_processed_id = pks[0] - 1
        c._run_maintenance.reset_mock()

        async def _stocke_puis_arret(*a, **k):
            c._arret_demande = True
            return _reussite()
        c.store_extractions = AsyncMock(side_effect=_stocke_puis_arret)

        await c._consolidate()

        assert c._last_processed_id == pks[2]
        c._run_maintenance.assert_not_awaited()


class TestArretDuConsolidateur:

    async def test_stop_n_attend_un_tick_que_le_delai_de_grace(self, monkeypatch):
        """Un tick qui tient le verrou au-delà de STOP_GRACE_S est annulé
        plutôt qu'attendu — et c'est compté."""
        import old.backend.memory.storage.consolidator as consolidator_mod
        from old.backend.memory.storage.consolidator import MemoryConsolidator
        from old.backend.utils.degradation import degradations

        monkeypatch.setattr(consolidator_mod, "STOP_GRACE_S", 0.2)
        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c._loop = MagicMock()
        c._loop.stop = AsyncMock()
        verrou = c._verrou()

        async def _tick_interminable():
            async with verrou:
                await asyncio.sleep(5)
        tick = asyncio.create_task(_tick_interminable())
        await asyncio.sleep(0.01)
        avant = degradations.count_for("consolidator: arret hors delai")

        debut = time.monotonic()
        await c.stop()
        duree = time.monotonic() - debut

        assert duree < 1.0
        assert c._arret_demande is True
        c._loop.stop.assert_awaited_once()
        assert degradations.count_for("consolidator: arret hors delai") == avant + 1
        tick.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tick

    async def test_stop_dans_le_delai_ne_compte_rien(self, monkeypatch):
        import old.backend.memory.storage.consolidator as consolidator_mod
        from old.backend.memory.storage.consolidator import MemoryConsolidator
        from old.backend.utils.degradation import degradations

        monkeypatch.setattr(consolidator_mod, "STOP_GRACE_S", 1.0)
        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c._loop = MagicMock()
        c._loop.stop = AsyncMock()
        verrou = c._verrou()

        async def _tick_court():
            async with verrou:
                await asyncio.sleep(0.05)
        tick = asyncio.create_task(_tick_court())
        await asyncio.sleep(0.01)
        avant = degradations.count_for("consolidator: arret hors delai")

        await c.stop()
        await tick

        c._loop.stop.assert_awaited_once()
        assert degradations.count_for("consolidator: arret hors delai") == avant
        assert not verrou.locked(), "stop() doit rendre le verrou"

    async def test_la_passe_forcee_leve_le_drapeau_d_arret(self):
        from old.backend.memory.storage.consolidator import MemoryConsolidator

        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c._arret_demande = True
        c._consolidate = AsyncMock()

        await c.force_consolidate()

        assert c._arret_demande is False
        c._consolidate.assert_awaited_once_with(force=True)


# ═══════════════════════════════════════════════════════════════════
# 3. Démarrage différé de la mémoire longue (OPS-09)
# ═══════════════════════════════════════════════════════════════════


class _StoreLent:
    """Un VectorStore dont la construction coûte du temps *bloquant* — comme
    le chargement réel de l'encodeur."""

    def __init__(self, *a, **k):
        time.sleep(0.3)


def _manager():
    from old.backend.memory.manager import MemoryManager

    m = MemoryManager()
    m._resume_or_open_conversation = AsyncMock()
    m._rehydrate_short_term = AsyncMock()
    return m


@pytest.fixture
def _sous_systemes_simules():
    """Tout ce que le chargement construit après le store, simulé."""
    consolidateur = MagicMock()
    consolidateur.start = AsyncMock()
    # Le store simulé est posé ICI, pas dans chaque test : un test qui échoue
    # avant d'attendre le chargement laisserait sinon la tâche de fond
    # construire le vrai VectorStore sur le dossier Chroma du développeur.
    with patch("memory.storage.VectorStore", _StoreLent), \
         patch("memory.storage.MemoryConsolidator", return_value=consolidateur), \
         patch("memory.retrieval.MemoryRetriever", return_value=MagicMock()), \
         patch("memory.extraction.MemoryExtractor", return_value=MagicMock()), \
         patch("memory.compaction.ConversationCompactor") as compacteur, \
         patch("configs.service.config_service.get", return_value=False):
        compacteur.return_value.start = AsyncMock()
        compacteur.return_value.stop = AsyncMock()
        yield consolidateur


@pytest.mark.usefixtures("_sous_systemes_simules")
class TestDemarrageDiffere:

    async def test_initialize_rend_la_main_avant_le_chargement(self):
        """Le port peut s'ouvrir pendant que l'encodeur charge : au retour
        d'`initialize`, le fil est prêt, la mémoire longue est `starting`."""
        m = _manager()
        with patch("memory.storage.VectorStore", _StoreLent):
            debut = time.monotonic()
            await m.initialize(differe=True)
            assert time.monotonic() - debut < 0.2
            assert m._initialized
            assert m.etat_memoire_longue == "starting"
            assert m.retriever is None

            assert await m.attendre_memoire_longue(timeout=5) == "ready"
        assert m.retriever is not None
        assert m.consolidator is not None

    async def test_un_tour_pendant_le_chargement_se_passe_de_rappel(self):
        """Pas d'exception, un bloc vide, et le drapeau qui le dit au prompt."""
        m = _manager()
        with patch("memory.storage.VectorStore", _StoreLent):
            await m.initialize(differe=True)
            assert await m.get_memory_context("coucou") == ""
            assert m.recall_unavailable is True
            await m.attendre_memoire_longue(timeout=5)

    async def test_un_refus_differe_passe_par_le_crochet(self):
        """Le refus ne peut plus remonter au lifespan (il a rendu la main) :
        l'état devient `failed` et le crochet reçoit le `MemoryUnavailable`."""
        from django.test import override_settings

        from old.backend.memory.manager import MemoryUnavailable

        crochet = MagicMock()
        m = _manager()
        with override_settings(MEMORY_REQUIRE_VECTOR_STORE=True), \
             patch("memory.storage.VectorStore", side_effect=RuntimeError("dossier corrompu")):
            await m.initialize(differe=True, sur_echec_fatal=crochet)
            assert await m.attendre_memoire_longue(timeout=5) == "failed"

        crochet.assert_called_once()
        assert isinstance(crochet.call_args.args[0], MemoryUnavailable)
        assert m.retriever is None

    async def test_le_repli_explicite_est_degrade_et_n_appelle_pas_le_crochet(self):
        from django.test import override_settings

        crochet = MagicMock()
        m = _manager()
        with override_settings(MEMORY_REQUIRE_VECTOR_STORE=False), \
             patch("memory.storage.VectorStore", side_effect=RuntimeError("boom")):
            await m.initialize(differe=True, sur_echec_fatal=crochet)
            assert await m.attendre_memoire_longue(timeout=5) == "degraded"
        crochet.assert_not_called()
        assert m._initialized

    async def test_le_mode_synchrone_leve_encore(self):
        """Tests et scripts : sans `differe`, le refus remonte comme avant."""
        from django.test import override_settings

        from old.backend.memory.manager import MemoryUnavailable

        m = _manager()
        with override_settings(MEMORY_REQUIRE_VECTOR_STORE=True), \
             patch("memory.storage.VectorStore", side_effect=RuntimeError("boom")):
            with pytest.raises(MemoryUnavailable):
                await m.initialize()
        assert m.etat_memoire_longue == "failed"
        assert not m._initialized

    async def test_l_arret_pendant_le_chargement_l_annule(self, _sous_systemes_simules):
        m = _manager()
        with patch("memory.storage.VectorStore", _StoreLent):
            await m.initialize(differe=True)
            tache = m._chargement
            await m.shutdown()
        assert tache.done()
        assert m._chargement is None

    def test_le_crochet_du_lifespan_marque_l_echec_avant_le_signal(self, monkeypatch):
        import signal

        import old.backend.config.asgi as asgi
        from old.backend.config.readiness import etat_processus

        signaux = []
        monkeypatch.setattr(signal, "raise_signal", lambda s: signaux.append(s))
        try:
            asgi._arreter_le_serveur(RuntimeError("Démarrage refusé : x.\nsuite"))
            assert etat_processus.echec_fatal == "Démarrage refusé : x."
            assert signaux == [signal.SIGTERM]
        finally:
            etat_processus.echec_fatal = ""


# ═══════════════════════════════════════════════════════════════════
# 4. /health : readiness (OPS-16)
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def sante(monkeypatch):
    """Un processus démarré et sain, que chaque test dégrade à sa façon."""
    from old.backend.ai.router import ai_router
    from old.backend.config.readiness import etat_processus
    from old.backend.memory.manager import memory_manager
    from old.backend.pipeline.turns import turn_queue

    etat_processus.passer_a("started")
    monkeypatch.setattr(memory_manager, "etat_memoire_longue", "ready")
    monkeypatch.setattr(type(turn_queue), "is_running", property(lambda self: True))
    monkeypatch.setattr(type(turn_queue), "pending", property(lambda self: 0))
    monkeypatch.setattr(ai_router, "get_model", lambda role: "claude-x")
    monkeypatch.setattr(ai_router, "get_provider_name", lambda role: "claude")
    import old.backend.utils.periodic as periodic
    monkeypatch.setattr(periodic, "active_loops", lambda: [])
    yield etat_processus
    etat_processus.passer_a("absent")
    etat_processus.echec_fatal = ""


@pytest.mark.django_db
class TestHealth:

    def test_pret_repond_200_ok(self, client, sante):
        r = client.get("/health")
        assert r.status_code == 200
        corps = r.json()
        assert corps["status"] == "ok" and corps["ready"] is True
        assert corps["checks"]["role_conversation"]["model"] == "claude-x"
        assert "vtuber" in corps

    def test_en_demarrage_repond_503_starting(self, client, sante):
        sante.passer_a("starting")
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json()["status"] == "starting"
        assert r.json()["ready"] is False

    def test_memoire_longue_en_chargement_repond_503_starting(self, client, sante, monkeypatch):
        from old.backend.memory.manager import memory_manager
        monkeypatch.setattr(memory_manager, "etat_memoire_longue", "starting")
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json()["status"] == "starting"

    def test_role_conversation_non_mappe_est_degrade_mais_pret(self, client, sante, monkeypatch):
        from old.backend.ai.router import AIRole, UnconfiguredRoleError, ai_router

        def _refuse(role):
            raise UnconfiguredRoleError("Aucun modèle", role=AIRole.CONVERSATION)
        monkeypatch.setattr(ai_router, "get_model", _refuse)
        monkeypatch.setattr(ai_router, "get_provider_name", _refuse)

        r = client.get("/health")
        assert r.status_code == 200
        corps = r.json()
        assert corps["status"] == "degraded" and corps["ready"] is True
        assert corps["checks"]["role_conversation"]["ok"] is False
        assert "Aucun modèle" in corps["checks"]["role_conversation"]["erreur"]

    def test_une_boucle_arretee_degrade(self, client, sante, monkeypatch):
        import old.backend.utils.periodic as periodic
        morte = MagicMock(is_running=False, name="Consolidator", interval=60, last_success_at=None)
        morte.name = "Consolidator"
        monkeypatch.setattr(periodic, "active_loops", lambda: [morte])
        corps = client.get("/health").json()
        assert corps["status"] == "degraded"
        assert corps["checks"]["boucles"]["arretees"] == ["Consolidator"]

    def test_memoire_refusee_repond_503_failed(self, client, sante, monkeypatch):
        from old.backend.memory.manager import memory_manager
        monkeypatch.setattr(memory_manager, "etat_memoire_longue", "failed")
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json()["status"] == "failed"

    def test_en_arret_repond_503_stopping(self, client, sante):
        sante.passer_a("stopping")
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json()["status"] == "stopping"

    def test_sans_lifespan_le_processus_reste_pret(self, client, sante):
        """Client de test, serveur WSGI de développement : aucun lifespan n'a
        tourné. Ce n'est pas « en démarrage » — le processus sert ce qu'il
        sait servir, au pire en `degraded`."""
        sante.passer_a("absent")
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ready"] is True
