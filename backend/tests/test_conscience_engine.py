"""Tests for ConscienceEngine — feed_emotion, pick_relevant_modules, observe, compute_score."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from conscience.types import DecisionContext


def _make_engine():
    from conscience.engine import ConscienceEngine
    e = ConscienceEngine.__new__(ConscienceEngine)
    e._last_activity = time.time()
    e._last_action_time = 0.0
    e._greeted_periods = set()
    e._greeted_date = None
    e._threshold = 0.5
    e._consecutive_waits = 0
    e.interpreter = MagicMock()
    e.memory = MagicMock()
    return e


def _make_ctx(sources=None, has_scheduled=False, high_pertinence=False):
    obs = []
    for src in (sources or []):
        o = MagicMock()
        o.source = src
        o.pertinence = 0.7 if high_pertinence else 0.3
        obs.append(o)
    return DecisionContext(
        pending_observations=obs,
        global_mood="happy",
        global_intensity=0.5,
        idle_seconds=60,
        in_cooldown=False,
        max_pertinence=0.7 if high_pertinence else 0.3,
        weighted_urgency=0.5,
        scheduled_actions=[MagicMock()] if has_scheduled else [],
        consecutive_waits=0,
        acts_today=0,
        consecutive_ignored_acts=0,
    )


# ===================================================================
# _feed_emotion
# ===================================================================

class TestFeedEmotion:

    def test_valid_emotion_processed(self):
        from conscience.engine import ConscienceEngine
        from conscience.types import InterpretedSignal
        from emotion.types import Emotion

        signal = InterpretedSignal(
            summary="test", category="communication", pertinence=0.7,
            emotional_reaction="happy", emotional_intensity=0.8,
            themes=[], entities=[], should_remember=False,
        )
        mock_ee = MagicMock()
        with patch("conscience.perception.emotion_engine", mock_ee):
            ConscienceEngine._feed_emotion(signal)

        mock_ee.process_emotion.assert_called_once()
        ed, pid = mock_ee.process_emotion.call_args[0]
        assert ed.emotion == Emotion.HAPPY
        assert ed.intensity == pytest.approx(0.8)
        assert pid == "conscience_mika"

    def test_invalid_emotion_name_ignored(self):
        from conscience.engine import ConscienceEngine
        from conscience.types import InterpretedSignal

        signal = InterpretedSignal(
            summary="test", category="system", pertinence=0.5,
            emotional_reaction="unicorn_emotion", emotional_intensity=0.5,
            themes=[], entities=[], should_remember=False,
        )
        mock_ee = MagicMock()
        with patch("conscience.perception.emotion_engine", mock_ee):
            ConscienceEngine._feed_emotion(signal)  # should not raise

        mock_ee.process_emotion.assert_not_called()


# ===================================================================
# _pick_relevant_modules — SUPPRIMÉ, et le détail compte
# ===================================================================
#
# `TestPickRelevantModules` (5 cas) a disparu avec la fonction qu'il couvrait.
# Ce n'est pas un dommage collatéral : trois de ses cinq cas épinglaient un
# défaut, c'est-à-dire décrivaient le bug comme s'il était la spécification.
#
#   test_no_obs_returns_empty       affirmait qu'un acte SANS observation part
#                                   avec une trousse vide. C'était le défaut
#                                   bloquant n°1 : inactivité, salutation,
#                                   humeur, pulsions et ruminations ne créent
#                                   aucune Observation, donc le seul cas où
#                                   elle agissait d'elle-même était le seul où
#                                   elle n'avait aucune main. La propriété
#                                   INVERSE est désormais épinglée dans
#                                   `test_conscience_trousse.py`.
#   test_sources_included           affirmait `"telegram" in result`. Or
#                                   `TelegramChannel` n'est pas un module —
#                                   `collectors.tools_for` le jetait en
#                                   silence. Le test mesurait donc une liste
#                                   d'intentions, jamais une trousse réelle.
#   test_wake_added_for_high_...    testait une porte à 0.6 que le chemin
#                                   d'interprétation sans LLM ne pouvait pas
#                                   franchir (plafond 0.55) : mécanisme mort,
#                                   supprimé sans remplacement.
#
# Les deux derniers (`wake` ajouté pour une action programmée, non dupliqué)
# portaient un comportement voulu ; ils sont traduits sans perte dans la suite
# de la trousse, où le socle contient `conscience_tools` — lequel porte
# désormais tout le cycle de vie des actions différées.
#
# `_make_engine` et `_make_ctx` restent : les tests suivants les utilisent.


# ===================================================================
# La trousse, branchée pour de vrai
# ===================================================================

class TestTrousseBranchee:
    """La propriété pour laquelle tout le lot existe, mesurée sur le MOTEUR.

    `test_conscience_trousse.py` couvre la fonction pure ; ici on vérifie le
    câblage — que le moteur passe bien au calcul ce qu'il faut, et surtout
    qu'il lui passe `disponibles`. Sans cet argument le filtrage s'éteint en
    silence, les noms inconnus repartent vers `get_tools_for_modules` et sont
    jetés comme avant : le correctif serait à moitié mort sans qu'aucun test
    pur ne le voie.
    """

    def test_un_acte_sans_observation_part_avec_des_outils(self):
        """L'exact inverse de l'ancien `test_no_obs_returns_empty`.

        Inactivité, salutation, humeur, pulsions et ruminations ne créent
        aucune Observation. C'était donc le cas le plus fréquent d'initiative,
        et le seul où elle n'avait aucune main.
        """
        e = _make_engine()
        trousse = e._preparer_trousse(_make_ctx())
        assert trousse.modules, "un acte endogène doit avoir une trousse"
        from conscience.trousse import SOCLE
        for nom in SOCLE:
            assert nom in trousse.modules

    def test_le_socle_survit_a_un_plafond_absurde(self):
        """Le couper reviendrait au défaut d'origine par une autre porte."""
        from conscience.trousse import SOCLE, TrousseTuning

        e = _make_engine()
        e._trousse_tuning = lambda: TrousseTuning(plafond_caracteres=0)
        trousse = e._preparer_trousse(_make_ctx())
        assert set(SOCLE).issubset(set(trousse.modules))

    def test_une_source_qui_n_est_pas_un_module_ne_disparait_plus(self):
        """« frontend » et « telegram » sont les valeurs réelles de
        `Observation.source` pour un message de chat, et ne sont des modules ni
        l'un ni l'autre : `collectors.tools_for` les jetait sans un mot."""
        e = _make_engine()
        trousse = e._preparer_trousse(_make_ctx(sources=["frontend", "telegram"]))
        assert "frontend" not in trousse.modules
        assert "telegram" not in trousse.modules
        # …et la trousse n'est pas vide pour autant : le socle tient.
        assert trousse.modules

    def test_le_moteur_passe_bien_disponibles(self):
        """Sans `disponibles`, `inconnus` reste vide et le filtrage s'éteint."""
        import inspect

        from conscience import acte

        source = inspect.getsource(acte.preparer_trousse)
        assert "disponibles=" in source

    def test_l_inventaire_ne_lit_pas_la_base(self):
        """L'accesseur en mémoire, pas celui qui interroge `ModuleState`.

        Sur l'AST et non sur le texte : le commentaire du moteur cite
        l'accesseur à ne PAS employer, et une recherche textuelle prendrait la
        mise en garde pour l'infraction.
        """
        import ast
        import inspect
        import textwrap

        from conscience import acte

        source = textwrap.dedent(
            inspect.getsource(acte.modules_enregistres)
        )
        appels = {
            n.func.attr
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "all_registered" in appels
        assert "list_all" not in appels

    def test_le_prompt_ne_promet_plus_ce_qu_il_ne_donne_pas(self):
        """B3 : le catalogue annoncé et la trousse fournie sont le même fait.

        `collect_capabilities_summary()` énumérait tout ce qui tourne sous
        « ce que tu peux faire » pendant que la trousse était vide.
        """
        import inspect

        from conscience.engine import ConscienceEngine

        # Sur la SIGNATURE, pas sur le texte : la docstring explique le
        # remplacement et cite donc l'ancien nom.
        parametres = inspect.signature(
            ConscienceEngine._build_action_prompt
        ).parameters
        assert "capabilities_summary" not in parametres, (
            "le bloc unique doit avoir cédé la place aux deux blocs "
            "« en main » / « ailleurs »"
        )
        assert "en_main" in parametres and "a_demander" in parametres
        # Et ils sont keyword-only : les inverser à l'appel donnerait un prompt
        # qui promet ce qu'il fournit et fournit ce qu'il promet, à l'envers.
        for nom in ("en_main", "a_demander"):
            assert parametres[nom].kind is inspect.Parameter.KEYWORD_ONLY


# ===================================================================
# get_idle_seconds
# ===================================================================

class TestGetIdleSeconds:

    def test_returns_time_since_last_activity(self):
        e = _make_engine()
        e._last_activity = time.time() - 120
        idle = e.get_idle_seconds()
        assert 115 < idle < 125


# ===================================================================
# observe — activity tracking
# ===================================================================

class TestObserve:

    @pytest.mark.asyncio
    async def test_chat_message_updates_last_activity(self):
        from modules.types import ModuleEvent
        e = _make_engine()
        e._last_activity = time.time() - 3600

        signal = MagicMock()
        signal.emotional_reaction = ""
        signal.emotional_intensity = 0.0
        signal.should_remember = False
        signal.pertinence = 0.3
        e.interpreter.interpret = AsyncMock(return_value=signal)
        e._store_observation = AsyncMock(return_value=None)

        await e.observe(ModuleEvent(event_type="chat.message", source_module="frontend", data={}))
        assert time.time() - e._last_activity < 5

    @pytest.mark.asyncio
    async def test_non_chat_does_not_update_activity(self):
        from modules.types import ModuleEvent
        e = _make_engine()
        past = time.time() - 3600
        e._last_activity = past

        signal = MagicMock()
        signal.emotional_reaction = ""
        signal.emotional_intensity = 0.0
        signal.should_remember = False
        signal.pertinence = 0.3
        e.interpreter.interpret = AsyncMock(return_value=signal)
        e._store_observation = AsyncMock(return_value=None)

        await e.observe(ModuleEvent(event_type="email.received", source_module="email", data={}))
        assert e._last_activity == past


# ===================================================================
# Instantané des pulsions
# ===================================================================

class TestSauvegardeDesPulsions:
    """La conscience est déjà l'horloge du DriveEngine — c'est elle qui appelle
    `update()`. La sauvegarde s'accroche donc là plutôt que dans une septième
    boucle de fond, et elle est étranglée : un `kill -9` est précisément le
    scénario où la fatigue de la soirée disparaissait avec la nuit."""

    @pytest.mark.asyncio
    async def test_la_sauvegarde_est_etranglee(self):
        e = _make_engine()
        e._last_drive_save = 0.0

        with patch("drives.engine.drive_engine.save_state", new=AsyncMock()) as save:
            await e._save_drives_if_due()
            await e._save_drives_if_due()
            await e._save_drives_if_due()

        assert save.await_count == 1

    @pytest.mark.asyncio
    async def test_la_sauvegarde_repasse_apres_l_intervalle(self):
        from conscience.engine import ConscienceEngine

        e = _make_engine()
        e._last_drive_save = time.time() - ConscienceEngine._DRIVE_SAVE_INTERVAL_S - 1

        with patch("drives.engine.drive_engine.save_state", new=AsyncMock()) as save:
            await e._save_drives_if_due()

        assert save.await_count == 1


# ===================================================================
# _compute_score
# ===================================================================

class TestComputeScore:

    def test_delegates_to_scoring_module(self):
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score", return_value=(0.3, "idle", set(), None)) as mock_score:
            score, reason = e._compute_score(ctx)
        mock_score.assert_called_once()
        assert score == pytest.approx(0.3)
        assert reason == "idle"

    def test_greeting_not_committed_when_deciding_to_wait(self):
        # Scoring marks the period greeted, but a "wait" decision must not
        # spend it — otherwise the day's greeting is consumed silently.
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score",
                   return_value=(0.35, "time(morning)", {"morning"}, "2026-07-26")):
            e._compute_score(ctx)
        assert e._greeted_periods == set()
        assert e._greeted_date is None

    def test_greeting_committed_on_act(self):
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score",
                   return_value=(0.8, "time(morning)", {"morning"}, "2026-07-26")):
            e._compute_score(ctx)
        e._commit_greeting()
        assert e._greeted_periods == {"morning"}
        assert e._greeted_date == "2026-07-26"

    def test_commit_is_idempotent(self):
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score",
                   return_value=(0.8, "time(morning)", {"morning"}, "2026-07-26")):
            e._compute_score(ctx)
        e._commit_greeting()
        e._greeted_periods = {"morning", "evening"}
        e._commit_greeting()  # nothing pending → must not roll back
        assert e._greeted_periods == {"morning", "evening"}


# ===================================================================
# Un outil qui plante n'assouvit plus rien (M2)
# ===================================================================

class TestIssueDesOutils:
    """`output.tool_calls` est une liste de NOMS, remplie par la boucle avant
    même de savoir ce que le handler a rendu (`claude.py` fait
    `calls.append(block.name)`). `had_tools=bool(output.tool_calls)` récompensait
    donc trois échecs exactement comme trois réussites — et la curiosité est la
    pulsion la plus difficile à satisfaire du moteur.
    """

    def test_le_moteur_lit_les_reussites_et_non_les_noms(self):
        import ast
        import inspect
        import textwrap

        from conscience import acte

        source = textwrap.dedent(inspect.getsource(acte.act))
        arbre = ast.parse(source)
        appels = [
            n for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "on_act"
        ]
        assert len(appels) == 1, "un seul site doit assouvir les pulsions"
        had = next(k for k in appels[0].keywords if k.arg == "had_tools")
        rendu = ast.unparse(had.value)
        assert "tool_calls" not in rendu, (
            f"had_tools se lit encore sur les noms d'outils : {rendu}"
        )
        assert "reussi" in rendu.lower()

    def test_un_handler_qui_leve_est_compte_en_echec(self):
        import asyncio

        from modules.collectors import ModuleCollectors
        from utils.tool_trace import journal_outils

        async def _boom(params):
            raise RuntimeError("indisponible")

        enveloppe = ModuleCollectors._wrap_handler("outil_casse", _boom)

        async def _run():
            with journal_outils() as carnet:
                with pytest.raises(RuntimeError):
                    await enveloppe({})
                return carnet.reussites, carnet.echecs

        reussites, echecs = asyncio.run(_run())
        assert (reussites, echecs) == (0, 1)

    def test_un_echec_annonce_a_la_facon_mcp_compte_aussi(self):
        """Un handler qui rend `{"isError": True}` n'a jamais levé.

        C'est la forme que `claude.py` relit déjà pour poser `is_error` sur le
        `tool_result` : sans cette lecture, la moitié des échecs resterait
        comptée comme des succès.
        """
        import asyncio

        from modules.collectors import ModuleCollectors
        from utils.tool_trace import journal_outils

        async def _poli(params):
            return {"isError": True, "content": "quota depasse"}

        enveloppe = ModuleCollectors._wrap_handler("outil_poli", _poli)

        async def _run():
            with journal_outils() as carnet:
                await enveloppe({})
                return carnet.reussites, carnet.echecs

        assert asyncio.run(_run()) == (0, 1)

    def test_un_succes_reste_un_succes(self):
        import asyncio

        from modules.collectors import ModuleCollectors
        from utils.tool_trace import journal_outils

        async def _ok(params):
            return {"content": "trois articles"}

        enveloppe = ModuleCollectors._wrap_handler("outil_ok", _ok)

        async def _run():
            with journal_outils() as carnet:
                await enveloppe({})
                return carnet.reussites, carnet.echecs

        assert asyncio.run(_run()) == (1, 0)
