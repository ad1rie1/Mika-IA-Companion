"""Section CONS de l'audit du 2026-09-16 (docs/audit-2026-09-16.md).

- CONS-01 : percevoir n'est pas de l'activité — une observation ne fatigue pas.
- CONS-02 : l'habituation amortit l'affect, et une source a un budget d'affect.
- CONS-03 : les sujets déjà semés sont écartés AVANT la troncature.
- CONS-04 : le fast-path ne compte pas un cycle sauté.
- CONS-05 : les salutations du jour survivent à un redémarrage.
- CONS-06 : `conscience.inactivite_restauree_max_seconds` est déclarée.
- CONS-08 : la porte F1 est franchissable par un signal qui résonne (0,6).
- CONS-09 : un rendez-vous à la priorité par défaut fait espérer.
- CONS-11 : sans destinataire ni public, l'acte n'a pas lieu — et n'échoue pas.
- CONS-12 : budget horaire de pas de chantier.
- CONS-13 : la fenêtre d'ignorée dépend du canal (Telegram ×3).
- CONS-14 : un pas de chantier ne meut pas l'humeur.
- CONS-16 : l'interpréteur suit la personnalité à chaud.
- CONS-17/18 : l'origine d'une pensée est un champ, plus une déduction de forme.
- DEF-09 / DEF-16 : les défauts revus.
"""
from __future__ import annotations

import time as _t
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as tz

from conscience.trousse import Trousse
from conscience.types import DecisionContext, InterpretedSignal


def _engine():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    e._last_action_time = 0.0
    e._salutation_en_attente = None
    e.memory = None
    return e


def _ctx(**kw) -> DecisionContext:
    base = dict(
        pending_observations=[], global_mood="curious", global_intensity=0.3,
        idle_seconds=600, in_cooldown=False, max_pertinence=0.0,
        weighted_urgency=0.0, rumination_lignes=[], rumination_pressure=0.0,
    )
    base.update(kw)
    return DecisionContext(**base)


class _Sortie:
    def __init__(self, text="j'ai regardé", ai_failed=False):
        self.text = text
        self.ai_failed = ai_failed
        self.tool_calls = []


class _MemoireMuette:
    async def recall_for_context(self, queries, **kw):
        return ""


# ===================================================================
# CONS-01 — percevoir ne fatigue pas
# ===================================================================


class TestPercevoirNeFatiguePas:

    def test_une_releve_rss_entiere_laisse_rest_a_zero(self):
        from drives.engine import DriveEngine
        from drives.state import DriveKind

        e = DriveEngine()
        for _ in range(15):
            e.on_observation(0.55)
        e.update()
        assert e.states[DriveKind.REST].tension == 0.0

    def test_parler_fatigue_toujours(self):
        from drives.engine import DriveEngine
        from drives.state import DriveKind

        e = DriveEngine()
        e.on_reply(word_count=60)
        e.update()
        assert e.states[DriveKind.REST].tension > 0.0


# ===================================================================
# CONS-02 — l'affect est habitué et dosé par source
# ===================================================================


def _signal(intensite=0.25, pertinence=0.55) -> InterpretedSignal:
    return InterpretedSignal(
        summary="un titre", category="information", pertinence=pertinence,
        emotional_reaction="curious", emotional_intensity=intensite,
    )


class TestAffectHabitueEtDose:

    def test_le_dosage_borne_une_source_sur_la_fenetre(self):
        e = _engine()
        total = sum(e._doser_l_affect("rss", 0.25) for _ in range(20))
        assert total == pytest.approx(e._AFFECT_BUDGET_PAR_SOURCE, abs=1e-9)
        # Une autre source a son propre budget.
        assert e._doser_l_affect("email", 0.25) == 0.25

    def test_une_demande_refusee_ne_consomme_rien(self):
        e = _engine()
        for _ in range(3):
            e._doser_l_affect("rss", 0.2)
        assert e._doser_l_affect("rss", 0.5) == pytest.approx(0.0)
        # Le budget n'est pas entamé par la demande refusée : il se libère
        # au rythme de la fenêtre, pas plus tard.
        memo = e._affect_par_source["rss"]
        assert sum(i for _, i in memo) == pytest.approx(0.6)

    async def test_quinze_titres_ne_font_pas_deborder_l_humeur(self):
        """Mesuré avant : dix impulsions `curious 0.25` → overflow 0,82, au-
        dessus de la porte d'humeur 0,7 ; elle parlait « par curiosité »."""
        from conscience import engine as engine_module
        from modules.types import ModuleEvent

        e = _engine()
        fed: list[float] = []
        e.interpreter = SimpleNamespace(
            interpret=AsyncMock(side_effect=lambda ev: _signal()),
        )
        with patch.object(type(e), "_store_observation", new=AsyncMock(return_value=None)), \
             patch.object(engine_module.emotion_engine, "process_emotion",
                          side_effect=lambda data, pid: fed.append(data.intensity)), \
             patch.object(engine_module.drive_engine, "on_observation"):
            for i in range(15):
                await e.observe(ModuleEvent(
                    event_type="rss.new_entry", source_module="rss",
                    data={"title": f"t{i}"},
                ))
        assert fed, "l'affect d'un premier titre passe"
        assert fed[0] == pytest.approx(0.25)
        # Le second est habitué (×0,85), et le total est borné par le budget.
        assert fed[1] == pytest.approx(0.25 * 0.85)
        assert sum(fed) <= e._AFFECT_BUDGET_PAR_SOURCE + 1e-9


# ===================================================================
# CONS-03 — dédupliquer AVANT de tronquer
# ===================================================================


class TestSujetsDejaSemes:

    def test_les_sujets_semes_laissent_la_place_aux_suivants(self):
        from conscience.travaux import graines_des_modules
        from drives.state import DriveKind

        sujets = [("rss", f"titre {i}") for i in range(6)]
        semees = {("pulsion", f"rss:titre {i}") for i in range(3)}
        with patch("modules.manager.module_manager.collect_sujets", return_value=sujets):
            graines = graines_des_modules(
                DriveKind.CURIOSITY, [("curiosity", 0.9)], semees,
            )
        assert [g.intitule for g in graines] == ["titre 3", "titre 4", "titre 5"]

    def test_sans_semis_le_plafond_s_applique_tel_quel(self):
        from conscience.travaux import graines_des_modules
        from drives.state import DriveKind

        sujets = [("rss", f"titre {i}") for i in range(6)]
        with patch("modules.manager.module_manager.collect_sujets", return_value=sujets):
            graines = graines_des_modules(DriveKind.CURIOSITY, [("curiosity", 0.9)])
        assert [g.intitule for g in graines] == ["titre 0", "titre 1", "titre 2"]


# ===================================================================
# CONS-04 — le fast-path ne compte pas un saut
# ===================================================================


class TestFastPathSansFauxBlocage:

    async def test_un_fast_path_sous_verrou_ne_compte_pas(self):
        import asyncio

        e = _engine()
        e._decision_lock = asyncio.Lock()
        e._cycles_sautes = 0
        async with e._decision_lock:
            await e._decide(compter_les_sauts=False)
            assert e._cycles_sautes == 0
            await e._decide()  # le tick périodique, lui, compte
            assert e._cycles_sautes == 1


# ===================================================================
# CONS-05 — les salutations survivent au redémarrage
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestSalutationsRestaurees:

    async def test_une_salutation_du_matin_est_relue_au_boot(self):
        from conscience.models import ConscienceLog

        await sync_to_async(ConscienceLog.objects.create)(
            decision="act", reason="time(morning) idle(30m)", person_id="",
        )
        e = _engine()
        e._greeted_periods = set()
        e._greeted_date = None
        await e._restaurer_salutations()
        assert e._greeted_periods == {"morning"}
        assert e._greeted_date is not None

    async def test_un_acte_d_hier_ne_compte_pas(self):
        from conscience.models import ConscienceLog

        row = await sync_to_async(ConscienceLog.objects.create)(
            decision="act", reason="time(evening)", person_id="",
        )
        await sync_to_async(
            lambda: ConscienceLog.objects.filter(pk=row.pk).update(
                created_at=tz.now() - timedelta(days=1),
            )
        )()
        e = _engine()
        e._greeted_periods = set()
        await e._restaurer_salutations()
        assert e._greeted_periods == set()


# ===================================================================
# CONS-06 / DEF-09 / DEF-16 — clés et défauts
# ===================================================================


def _item(key):
    from conscience.config_schema import CONFIG_SCHEMA
    from configs.types import ConfigItem

    return next(i for i in CONFIG_SCHEMA if isinstance(i, ConfigItem) and i.key == key)


class TestClesEtDefauts:

    def test_l_inactivite_restauree_est_declaree(self):
        from conscience.engine import ConscienceEngine

        item = _item("conscience.inactivite_restauree_max_seconds")
        assert item.default == ConscienceEngine._INACTIVITE_RESTAUREE_MAX_S == 72 * 3600

    def test_les_chantiers_menes_de_front_et_l_espacement(self):
        from conscience import conduite

        assert _item("conscience.travail.travaux_actifs_max").default == 2 == conduite.TRAVAUX_ACTIFS_MAX
        assert _item("conscience.travail.pas_intervalle_min_s").default == 1800.0 == conduite.PAS_INTERVALLE_MIN_S

    def test_le_budget_horaire_de_pas_est_declare(self):
        from conscience.engine import ConscienceEngine

        assert _item("conscience.travail.pas_par_heure_max").default == 4 == ConscienceEngine._PAS_PAR_HEURE_MAX

    def test_la_fenetre_d_ignoree_et_son_facteur_telegram(self):
        from conscience.engine import ConscienceEngine

        assert _item("conscience.ignored_reply_window_minutes").default == 20 == ConscienceEngine._IGNORED_REPLY_WINDOW_MIN
        assert _item("conscience.ignored_reply_window_telegram_factor").default == 3.0 == ConscienceEngine._IGNORED_TELEGRAM_FACTOR

    def test_la_porte_f1_a_0_6(self):
        from conscience.scoring import DEFAULT_TUNING

        assert _item("conscience.factor.pertinence_gate").default == 0.6 == DEFAULT_TUNING.pertinence_gate
        assert 0.55 * 1.15 > 0.6 > 0.55


# ===================================================================
# CONS-09 — un rendez-vous ordinaire fait espérer
# ===================================================================


class TestEspoirDuRendezVousOrdinaire:

    async def test_la_priorite_par_defaut_de_schedule_action_suffit(self):
        from conscience import engine as engine_module

        e = _engine()
        e._dernier_espoir = 0.0
        pulses: list = []
        with patch.object(type(e), "_get_upcoming_actions", new=AsyncMock(
                 return_value=[(SimpleNamespace(priority=0.5, prompt="rappel"), 30)])), \
             patch.object(engine_module.emotion_engine, "process_emotion",
                          side_effect=lambda d, p: pulses.append(d.emotion.value)):
            await e._peut_etre_esperer(_ctx(sleep_phase="awake"), [])
        assert pulses == ["hopeful"]

    async def test_un_rendez_vous_tiede_ne_fait_toujours_pas_esperer(self):
        from conscience import engine as engine_module

        e = _engine()
        e._dernier_espoir = 0.0
        pulses: list = []
        with patch.object(type(e), "_get_upcoming_actions", new=AsyncMock(
                 return_value=[(SimpleNamespace(priority=0.3, prompt="tiède"), 30)])), \
             patch.object(engine_module.emotion_engine, "process_emotion",
                          side_effect=lambda d, p: pulses.append(d.emotion.value)):
            await e._peut_etre_esperer(_ctx(sleep_phase="awake"), [])
        assert pulses == []


# ===================================================================
# CONS-11 — sans destinataire ni public, pas d'acte
# ===================================================================


def _patches_acte(e, sortie):
    return (
        patch.object(type(e), "_appeler_le_modele", return_value=(sortie, "", 0)),
        patch.object(type(e), "_select_recipient", return_value=None),
        patch.object(type(e), "_preparer_trousse", return_value=Trousse()),
        patch.object(type(e), "_composer_vecu", return_value=""),
        patch.object(type(e), "_resolve_ruminations_after_act"),
    )


@pytest.mark.django_db(transaction=True)
class TestActeSansAudience:

    async def test_personne_pour_entendre_retient_l_acte_sans_echec(self):
        e = _engine()
        e.memory = _MemoireMuette()
        a, b, c, d, f = _patches_acte(e, _Sortie("coucou"))
        with a as appel, b, c, d, f, \
             patch.object(type(e), "_audience_presente", return_value=False):
            resultat = await e._act(_ctx(), "test")
        assert resultat.sans_audience is True
        assert resultat.dit == "" and resultat.ai_failed is False
        appel.assert_not_called()

    async def test_un_navigateur_ouvert_laisse_l_acte_partir(self):
        e = _engine()
        e.memory = _MemoireMuette()
        a, b, c, d, f = _patches_acte(e, _Sortie("coucou"))
        with a as appel, b, c, d, f, \
             patch.object(type(e), "_audience_presente", return_value=True):
            resultat = await e._act(_ctx(), "test")
        assert resultat.dit == "coucou"
        appel.assert_called_once()

    async def test_un_destinataire_joignable_n_a_pas_besoin_de_public(self):
        """Une personne joignable (Telegram) est un public à elle seule."""
        e = _engine()
        e.memory = _MemoireMuette()
        a, b, c, d, f = _patches_acte(e, _Sortie("coucou"))
        with a as appel, patch.object(type(e), "_select_recipient", return_value="tg_42"), \
             c, d, f, patch.object(type(e), "_audience_presente", return_value=False):
            resultat = await e._act(_ctx(), "test")
        assert resultat.dit == "coucou" and resultat.person_id == "tg_42"
        appel.assert_called_once()


# ===================================================================
# CONS-12 — budget horaire de pas
# ===================================================================


class TestBudgetDePas:

    def test_quatre_pas_puis_plus_rien_dans_l_heure(self):
        e = _engine()
        assert e._budget_de_pas_disponible()
        for _ in range(4):
            e._pas_recents().append(_t.monotonic())
        assert not e._budget_de_pas_disponible()

    def test_un_pas_vieux_d_une_heure_libere_la_place(self):
        e = _engine()
        e._pas_faits = [_t.monotonic() - 3601.0] + [_t.monotonic()] * 3
        assert e._budget_de_pas_disponible()

    async def test_un_pas_fait_est_compte_un_pas_refuse_non(self):
        from conscience import travaux

        e = _engine()
        with patch.object(travaux, "faire_un_pas", new=AsyncMock(return_value=True)):
            assert await e._faire_un_pas(1)
        with patch.object(travaux, "faire_un_pas", new=AsyncMock(return_value=False)):
            assert not await e._faire_un_pas(2)
        assert len(e._pas_recents()) == 1


# ===================================================================
# CONS-13 — la fenêtre d'ignorée suit le canal
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestFenetreDIgnoreeParCanal:

    async def _acte_et_reponse(self, person_id, acte_il_y_a_min, reponse_il_y_a_min):
        from conscience.models import ConscienceLog, Observation

        acte = await sync_to_async(ConscienceLog.objects.create)(
            decision="act", reason="x", person_id=person_id,
        )
        await sync_to_async(
            lambda: ConscienceLog.objects.filter(pk=acte.pk).update(
                created_at=tz.now() - timedelta(minutes=acte_il_y_a_min),
            )
        )()
        rep = await sync_to_async(Observation.objects.create)(
            source="telegram", event_type="telegram.message", summary="oui",
        )
        await sync_to_async(
            lambda: Observation.objects.filter(pk=rep.pk).update(
                created_at=tz.now() - timedelta(minutes=reponse_il_y_a_min),
            )
        )()

    async def test_une_reponse_telegram_a_quarante_minutes_n_est_pas_une_ignoree(self):
        from conscience.models import ConscienceLog, Observation

        await sync_to_async(ConscienceLog.objects.all().delete)()
        await sync_to_async(Observation.objects.all().delete)()
        await self._acte_et_reponse("tg_7", acte_il_y_a_min=60, reponse_il_y_a_min=20)
        _, ignorees = await _engine()._introspect()
        assert ignorees == 0  # 40 min < 20 × 3

    async def test_la_meme_attente_sur_le_web_compte_comme_ignoree(self):
        from conscience.models import ConscienceLog, Observation

        await sync_to_async(ConscienceLog.objects.all().delete)()
        await sync_to_async(Observation.objects.all().delete)()
        await self._acte_et_reponse("web_7", acte_il_y_a_min=60, reponse_il_y_a_min=20)
        _, ignorees = await _engine()._introspect()
        assert ignorees == 1  # 40 min > 20


# ===================================================================
# CONS-14 — un pas de chantier ne meut pas l'humeur
# ===================================================================


class TestPasMuetSansImpulsion:

    async def test_faire_un_pas_demande_a_ne_pas_ressentir(self):
        from conscience import travaux

        e = _engine()
        vu: dict = {}

        async def faux_appel(prompt, **kw):
            vu.update(kw)
            return _Sortie("[VERDICT] etat: continue", ai_failed=True), "", 0

        row = SimpleNamespace(pk=1, titre="t", themes=[], modules=[])
        with patch.object(travaux, "sync_to_async") as s2a, \
             patch.object(type(e), "_build_work_prompt", new=AsyncMock(return_value="p")), \
             patch.object(type(e), "_preparer_trousse_travail", return_value=Trousse()), \
             patch.object(type(e), "_rendre_le_pas", new=AsyncMock()):
            # Sur l'INSTANCE : posée sur la classe, la fonction deviendrait
            # une méthode et recevrait le moteur en premier argument.
            e._appeler_le_modele = faux_appel
            s2a.return_value = AsyncMock(return_value=row)
            await travaux.faire_un_pas(e, 1)
        assert vu.get("ressentir") is False

    async def test_le_processeur_n_applique_pas_l_impulsion_quand_on_le_lui_dit(self):
        from configs.service import config_service
        from emotion.types import Emotion, EmotionData
        from pipeline import processor
        from pipeline.context import ConversationContext
        from pipeline.perception import Perception

        tag = EmotionData(Emotion.EXCITED, 0.9)
        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=("je bosse", tag, []))), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=ConversationContext())), \
             patch.object(processor.emotion_engine, "ensure_person_loaded", new=AsyncMock()), \
             patch.object(processor.emotion_engine, "process_emotion") as impulse, \
             patch.object(processor.emotion_engine, "save_snapshot", new=AsyncMock()) as snap, \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()):
            out = await processor.process_message(
                Perception.from_internal_trigger("pas", source="conscience",
                                                 person_id="conscience_mika"),
                broadcast=False, persist=False, emit_event=False,
                emotion_impulse=False,
            )
        assert out.text == "je bosse"
        impulse.assert_not_called()
        snap.assert_not_called()


# ===================================================================
# CONS-16 — l'interpréteur suit la personnalité
# ===================================================================


class TestInterpreteurACHaud:

    def test_le_prompt_systeme_suit_le_nom_courant(self):
        from config import personality as personality_module
        from conscience.interpreter import SignalInterpreter

        i = SignalInterpreter()
        with patch.object(type(personality_module.personality), "name",
                          new_callable=lambda: property(lambda self: "Nova")):
            avant = i._get_system_prompt()
        with patch.object(type(personality_module.personality), "name",
                          new_callable=lambda: property(lambda self: "Lyra")):
            apres = i._get_system_prompt()
        assert "Nova" in avant and "Lyra" in apres


# ===================================================================
# CONS-17 / CONS-18 — l'origine est un champ
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestOrigineDesPensees:

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination

        Rumination.objects.all().delete()
        yield
        Rumination.objects.all().delete()

    async def test_une_pensee_promue_orpheline_n_est_pas_prise_pour_un_audit(self):
        """Une observation purgée (FK SET_NULL) laissait sa pensée « sans
        observation et sans thème » : la forme même d'un audit, donc fanée par
        le plafond des audits. Avec l'origine, elle reste."""
        from conscience.models import Rumination

        creer = sync_to_async(Rumination.objects.create)
        orpheline = await creer(
            summary="un article resté sans suite", themes=[], intensity=0.6,
            emotion="curious", observation=None,
            origine=Rumination.Origine.OBSERVATION,
        )
        for i in range(3):
            await creer(
                summary=f"audit {i}", themes=[], intensity=0.2 + i * 0.01,
                emotion="anxious", origine=Rumination.Origine.AUDIT,
            )
        e = _engine()
        with patch.object(type(e), "_audit_trop_recent", return_value=False), \
             patch("conscience.engine.estime.lire", new=AsyncMock(return_value=0.5)):
            await e.post_action_audit(
                response_text="je crois que je me suis emportée",
                emotion_name="angry", intensity=0.9, person_id="web_x",
            )
        await sync_to_async(orpheline.refresh_from_db)()
        assert orpheline.status == "active"
        audits = await sync_to_async(list)(
            Rumination.objects.filter(origine="audit").values_list("status", flat=True)
        )
        assert audits.count("faded") == 1 and len(audits) == 4

    async def test_une_derive_nostalgique_d_audit_n_est_pas_le_retour_d_un_absent(self):
        from conscience.models import Rumination
        from memory.models import Conversation, Message

        creer = sync_to_async(Rumination.objects.create)
        derive = await creer(
            summary="je repense à ce que j'ai dit", themes=["Alice"], intensity=0.4,
            emotion="nostalgic", origine=Rumination.Origine.AUDIT,
        )
        manque = await creer(
            summary="j'aimerais des nouvelles d'Alice", themes=["Alice"], intensity=0.3,
            emotion="nostalgic", origine=Rumination.Origine.MANQUE,
        )
        conv = await sync_to_async(Conversation.objects.create)()
        await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="coucou", person_id="web_alice",
        )
        e = _engine()
        e._dernier_retour_scan = 0.0
        with patch("identity.resolver.identity_resolver.handles_for_entity_names",
                   new=AsyncMock(return_value={"Alice": [{"person_id": "web_alice"}]})), \
             patch("conscience.engine.emotion_engine.process_emotion"):
            await e._le_retour_d_un_absent()
        await sync_to_async(derive.refresh_from_db)()
        await sync_to_async(manque.refresh_from_db)()
        assert manque.status == "resolved"
        assert derive.status == "active"

    def test_chaque_ecrivain_pose_une_origine(self):
        """AST : chaque `Rumination.objects.create(` du code de production
        porte `origine=`. Un écrivain oublié retomberait dans les déductions
        de forme — celles que le champ existe pour remplacer."""
        import ast
        import pathlib

        racine = pathlib.Path(__file__).resolve().parents[1]
        oublis = []
        for fichier in (
            racine / "conscience" / "engine.py",
            racine / "conscience" / "memory_bridge.py",
            racine / "conscience" / "travaux.py",
        ):
            tree = ast.parse(fichier.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if (
                    isinstance(f, ast.Attribute) and f.attr == "create"
                    and isinstance(f.value, ast.Attribute) and f.value.attr == "objects"
                    and isinstance(f.value.value, ast.Name) and f.value.value.id == "Rumination"
                ):
                    if not any(k.arg == "origine" for k in node.keywords):
                        oublis.append(f"{fichier.name}:{node.lineno}")
        assert oublis == []


# ===================================================================
# CONS-11 (suite) — personne de joignable : ni réveil ni murmure
# ===================================================================


class TestPersonneDeJoignable:

    def test_un_handle_module_joignable_suffit(self):
        from communication.presence import presence_registry

        e = _engine()
        with patch.object(type(e), "_audience_presente", return_value=False), \
             patch.object(presence_registry, "reachable",
                          return_value=[SimpleNamespace(is_module=True, is_consumer=False)]):
            assert e._quelquun_est_joignable()

    def test_personne_nulle_part(self):
        from communication.presence import presence_registry

        e = _engine()
        with patch.object(type(e), "_audience_presente", return_value=False), \
             patch.object(presence_registry, "reachable", return_value=[]):
            assert not e._quelquun_est_joignable()

    async def test_sans_personne_de_joignable_ni_reveil_ni_murmure_ni_acte(self):
        """Le contrôle précède `note_interaction()` et le murmure : un
        rendez-vous prioritaire à 3 h ne la réveille plus pour parler dans le
        vide."""
        from conscience import engine as engine_module
        from conscience.conduite import Conduite

        e = _engine()
        e._decision_lock = None
        e._consecutive_waits = 0
        e._pending_greeted = None
        journal: dict = {}

        async def _log(self, ctx, decision, reason, score, memory_actions, **kw):
            journal["decision"] = decision

        with patch.object(type(e), "_build_context", new=AsyncMock(return_value=_ctx())), \
             patch.object(type(e), "_suivre_la_detresse"), \
             patch.object(type(e), "_suivre_l_estime_sociale", new=AsyncMock()), \
             patch.object(type(e), "_memory_maintenance", new=AsyncMock(return_value=[])), \
             patch.object(type(e), "_compute_score", return_value=(0.9, "test")), \
             patch.object(type(e), "_travaux_en_cours", new=AsyncMock(return_value=([], set()))), \
             patch.object(type(e), "_recolter", return_value=[]), \
             patch.object(type(e), "_quelquun_est_joignable", return_value=False), \
             patch.object(type(e), "_act", new=AsyncMock()) as acte, \
             patch.object(type(e), "_log_decision", new=_log), \
             patch.object(type(e), "_cleanup_old_observations", new=AsyncMock()), \
             patch.object(type(e), "_save_drives_if_due", new=AsyncMock()), \
             patch.object(type(e), "_tirer_gigue_cooldown"), \
             patch.object(engine_module, "murmurer", new=AsyncMock()) as murmure, \
             patch("memory.sleep.sleep_cycle.note_interaction") as reveil:
            await e._decide_inner()
        assert journal["decision"] == "sans_audience"
        acte.assert_not_called()
        murmure.assert_not_called()
        reveil.assert_not_called()
