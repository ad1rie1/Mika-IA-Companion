"""Cas de comportement relevés après l'audit : aucun service extérieur appelé."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from django.utils import timezone


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    from configs.registry import registry
    from configs.service import config_service

    def get(key, default=None):
        item = registry.get(key)
        return item.default if item else default

    monkeypatch.setattr(config_service, "get", get)


@pytest.mark.django_db(transaction=True)
async def test_ancre_et_affect_lus_apres_canonicalisation(monkeypatch):
    from emotion import engine
    from GestionSysteme.views.social import _divulgation_graduee, _live_affects
    from identity.models import Identity, IdentityHandle
    from identity.trust import ChannelTrust
    from memory.models import Entity
    from memory.retrieval.retriever import MemoryRetriever

    entity = await Entity.objects.acreate(name="Alice", entity_type="person")
    identite = await Identity.objects.acreate(entity=entity, certainty=1)
    for canal, pid in [("web", "user_81"), ("telegram", "tg_81")]:
        await IdentityHandle.objects.acreate(identity=identite, channel=canal, person_id=pid)
    moteur = engine.EmotionEngine()
    monkeypatch.setattr(engine, "emotion_engine", moteur)
    await moteur.ensure_person_loaded("user_81")
    mood = moteur._get_person_mood("user_81")
    mood.anchor = (0.8, 0.2, 0.1)
    mood.dynamic.position = (0.6, 0.2, 0.1)
    assert "user_81" not in moteur.person_moods
    assert await moteur.chaleur_envers("tg_81") == pytest.approx(0.8)
    assert await moteur.chaleur_envers("user_81") == pytest.approx(0.8)
    assert len(_live_affects(["user_81", "tg_81"])) == 1
    decision = SimpleNamespace(certainty=1, trust=ChannelTrust.AUTHENTICATED, may_disclose=True)
    vue = _divulgation_graduee(SimpleNamespace(profile=None), [{"decision": decision}], ["tg_81"])
    assert vue["ancre_lue"] and vue["chaleur"] == pytest.approx(0.8)
    assert MemoryRetriever._mood_pad_for("tg_81") == mood.dynamic.position


@pytest.mark.django_db(transaction=True)
async def test_rumination_seule_est_soulagee_si_evoquee(monkeypatch):
    from ai.router import ai_router
    from conscience.acte import act, build_action_prompt
    from conscience.models import Rumination
    from conscience.ruminations import resolve_ruminations_after_act, rumination_snapshot
    from conscience.trousse import Trousse
    from conscience.types import DecisionContext
    from utils.tool_results import BilanOutils
    from utils.tool_trace import JournalOutils

    alice = await Rumination.objects.acreate(summary="Alice me manque", themes=["Alice"], intensity=.8)
    plugin = await Rumination.objects.acreate(summary="Mon plugin", themes=["plugin"], intensity=.6)
    pression, compte, lignes = await rumination_snapshot()
    ctx = DecisionContext([], "neutral", 0, 100, False, 0, 0,
                          rumination_lignes=lignes, rumination_pressure=pression)
    moteur = SimpleNamespace(
        _tirer_gigue_cooldown=Mock(), _preparer_trousse=Mock(return_value=Trousse()),
        _composer_vecu=Mock(return_value=""), _modules_enregistres=Mock(return_value=[]),
        _get_upcoming_actions=AsyncMock(return_value=[]),
        _select_recipient=AsyncMock(return_value="user_81"),
        memory=SimpleNamespace(recall_for_context=AsyncMock(return_value="")),
        _resolve_ruminations_after_act=resolve_ruminations_after_act,
        _appeler_le_modele=AsyncMock(return_value=(
            SimpleNamespace(ai_failed=False, text="Alice, comment vas-tu ?"), BilanOutils(JournalOutils()), 0,
        )),
    )
    async def brief(context, **kwargs):
        return await build_action_prompt(moteur, context, **kwargs)
    moteur._build_action_prompt = brief
    monkeypatch.setattr(ai_router, "budget_de_fond_disponible", lambda role: True)
    await act(moteur, ctx, "rumination")
    await alice.arefresh_from_db()
    await plugin.arefresh_from_db()
    assert alice.intensity == pytest.approx(.4)
    assert plugin.intensity == pytest.approx(.6)
    assert moteur._appeler_le_modele.call_args.kwargs["metadata"]["ruminations"] == lignes


@pytest.mark.django_db
@pytest.mark.parametrize("choix,statut", [("retry", "pending"), ("close", "cancelled")])
def test_operateur_resout_une_tentative_incertaine(client, settings, choix, statut):
    from conscience.models import ScheduledAction
    from django.urls import reverse

    settings.DASHBOARD_REQUIRE_AUTH = False
    action = ScheduledAction.objects.create(
        prompt="Envoyer le document", source="test", scheduled_at=timezone.now(), status="uncertain",
        context_data={"attempt_token": "ancien", "execution": {"echecs": 1}},
    )
    url = reverse("gestionsysteme:scheduled-action", args=[action.pk])
    assert client.get(url).status_code == 405
    assert client.post(url, {"action": choix, "attempt_token": "ancien"}).status_code == 302
    action.refresh_from_db()
    assert action.status == statut
    assert action.context_data["execution"] == {"echecs": 1}
    assert action.context_data["operator_resolution"] == choix
    # Un deuxième formulaire de l'ancienne tentative ne clôt pas la relance.
    client.post(url, {"action": "close", "attempt_token": "ancien"})
    action.refresh_from_db()
    assert action.status == statut


@pytest.mark.django_db
def test_operateur_ne_relance_pas_un_appel_encore_en_vol(client, settings):
    from conscience.models import ScheduledAction
    from django.urls import reverse

    settings.DASHBOARD_REQUIRE_AUTH = False
    action = ScheduledAction.objects.create(
        prompt="Envoi", source="test", scheduled_at=timezone.now(), status="uncertain",
        context_data={"attempt_token": "courant",
                      "reserved_until": (timezone.now() + timedelta(minutes=5)).isoformat()},
    )
    client.post(reverse("gestionsysteme:scheduled-action", args=[action.pk]),
                {"action": "retry", "attempt_token": "courant"})
    action.refresh_from_db()
    assert action.status == "uncertain"


@pytest.mark.django_db(transaction=True)
async def test_mika_peut_relire_les_actions_incertaines():
    from conscience.models import ScheduledAction
    from conscience.module import ConscienceToolsModule

    action = await ScheduledAction.objects.acreate(
        prompt="Courrier important", source="test", scheduled_at=timezone.now(), status="uncertain",
    )
    resultat = await ConscienceToolsModule()._tool_list_scheduled({})
    assert str(action.pk) in str(resultat) and "À VÉRIFIER" in str(resultat)


@pytest.mark.django_db(transaction=True)
async def test_discussion_projet_conserve_les_outils_de_vie_et_verifie_le_proprietaire(monkeypatch, tmp_path):
    from identity.resolver import IdentityContext
    from identity.trust import ChannelTrust
    from memory.models import Entity
    from modules.types import ModuleTool
    from projects import workspace, context_builder
    from projects.capabilities import completer_conversation
    from projects.models import Project

    owner = await Entity.objects.acreate(name="Alice", entity_type="person")
    project = await Project.objects.acreate(title="Atelier", owner=owner)
    identite = IdentityContext("user_81", entity_id=owner.pk, may_disclose=True,
                               certainty=1, trust=ChannelTrust.AUTHENTICATED)
    outils = [ModuleTool(n, n, [], AsyncMock()) for n in
              ["memory_search", "identify_person", "schedule_action", "add_project_task"]]
    atelier = workspace.Atelier(project.pk, tmp_path)
    ouverture = Mock(return_value=atelier)
    monkeypatch.setattr(workspace, "atelier_de", ouverture)
    build = AsyncMock(side_effect=AssertionError("Pas de contexte runner à construire"))
    monkeypatch.setattr(context_builder, "build", build)
    enrichis = await completer_conversation(project.pk, identite, outils)
    noms = {t.name for t in enrichis}
    assert {t.name for t in outils}.issubset(noms)
    assert "project_write_file" in noms
    ouverture.assert_called_once()
    ouverture.reset_mock()
    identite.entity_id = owner.pk + 1
    assert await completer_conversation(project.pk, identite, outils) == outils
    identite.entity_id = owner.pk
    identite.trust = ChannelTrust.PUBLIC
    assert await completer_conversation(project.pk, identite, outils) == outils
    ouverture.assert_not_called()
    build.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_projet_confie_peut_etre_mis_en_pause():
    from projects.models import Project
    from projects.tools import ProjectToolsModule

    project = await Project.objects.acreate(title="Mission", instructions=["Rapport hebdomadaire"])
    resultat = await ProjectToolsModule()._tool_update_project({
        "project_id": project.pk, "status": "paused", "priority": "low", "schedule_rule": "interval:1h",
    })
    await project.arefresh_from_db()
    assert not resultat.get("isError")
    assert (project.status, project.priority, project.schedule_rule) == ("paused", "low", "interval:1h")
    assert project.instructions == ["Rapport hebdomadaire"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("nom", ["memory_recent_souvenirs", "memory_read_journal", "memory_list_commitments",
                                   "list_rss_entries", "read_rss_entry", "search_rss", "list_rss_feeds",
                                   "refresh_rss_feeds", "files_list", "files_read"])
async def test_lectures_ne_creent_pas_de_demande_approbation(monkeypatch, nom):
    from modules.manager import module_manager
    from modules.types import ModuleTool
    from projects.capabilities import executer
    from projects.models import Project, ProjectPendingAction

    handler = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(module_manager, "get_tools_for_modules", lambda modules: [ModuleTool(nom, nom, [], handler)])
    project = await Project.objects.acreate(title="Lire", allowed_modules=["lecture"], requires_approval=True)
    assert (await executer(project.pk, "lecture", nom, {}))["ok"]
    assert not await ProjectPendingAction.objects.aexists()
    handler.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
async def test_approbation_attendue_ni_succes_ni_echec_et_ne_temporise_pas(monkeypatch):
    from modules.manager import module_manager
    from modules.types import ModuleTool
    from projects.capabilities import construire
    from projects.models import Project
    from projects.runner import ProjectRunner
    from utils.tool_trace import journal_outils
    from utils.tool_results import BilanOutils

    handler = AsyncMock(return_value={"ok": True})
    outil = ModuleTool("send_email", "Envoyer", [], handler)
    monkeypatch.setattr(module_manager, "get_tools_for_modules", lambda modules: [outil])
    project = await Project.objects.acreate(title="Courrier", allowed_modules=["email"], requires_approval=True,
                                          schedule_rule="interval:30s", next_run_at=timezone.now())
    trousse = await construire(project.pk)
    with journal_outils() as trace:
        result = await trousse[0].handler({"to": "alice@example.org"})
    assert not result["isError"]
    assert trace.total == 1 and trace.reussites == trace.echecs == 0
    assert trace.as_dict()["attentes"] == 1
    assert not BilanOutils(trace).permet_aboutissement()
    runner = ProjectRunner()
    for _ in range(12):
        await runner._bump_next_run(project.pk)
    await project.arefresh_from_db()
    assert project.stalled_runs == 0 and project.retry_after is None
    assert project.pk not in await runner._list_due()
    handler.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_budget_survit_aux_progres_redemarrage_et_suppression(monkeypatch):
    from projects.models import Project, ProjectRunReservation
    from projects import runner

    original = runner.cfg_int
    monkeypatch.setattr(runner, "cfg_int", lambda key, *a, **kw:
                        2 if key in {"projects.daily_runs_per_project", "projects.daily_runs_total"}
                        else original(key, *a, **kw))
    project = await Project.objects.acreate(title="Très actif", schedule_rule="interval:30s")
    moteur = runner.ProjectRunner()
    for numero in range(2):
        assert await moteur._reserve_background_run(project.pk)
        await moteur._bump_next_run(project.pk, progress_signature=str(numero))
    assert not await runner.ProjectRunner()._reserve_background_run(project.pk)
    await moteur.notify_user_input(project.pk)
    assert not await moteur._reserve_background_run(project.pk)
    await project.adelete()
    nouveau = await Project.objects.acreate(title="Autre projet")
    assert not await moteur._reserve_background_run(nouveau.pk)
    await ProjectRunReservation.objects.aupdate(created_at=timezone.now() - timedelta(days=1))
    assert await moteur._reserve_background_run(nouveau.pk)


async def test_executable_du_serveur_absent_du_bac_est_explique(tmp_path, monkeypatch):
    from projects import execution

    serveur = tmp_path / "serveur"
    serveur.mkdir()
    executable = serveur / "pytest"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    atelier = tmp_path / "atelier"
    atelier.mkdir()
    monkeypatch.setenv("PATH", str(serveur))
    result = await execution.run_bounded(racine=atelier, argv=[str(executable)])
    assert result.refused and "environnement isolé" in result.refused


@pytest.mark.django_db(transaction=True)
async def test_repetition_entretient_le_rappel_sans_augmenter_la_certitude(monkeypatch):
    from memory.models import Connaissance
    from memory.storage.consolidator import MemoryConsolidator

    ancre = timezone.now() - timedelta(days=30)
    row = await Connaissance.objects.acreate(content="Alice aime dessiner", confidence=.35,
                                           epistemic_kind="uncertain", source_message_ids=[10], decayed_at=ancre)
    consolidator = MemoryConsolidator(extractor=Mock(), vector_store=Mock())
    monkeypatch.setattr(consolidator, "_find_similar_connaissance", AsyncMock(return_value=row))
    monkeypatch.setattr(consolidator, "_index", AsyncMock())
    kwargs = dict(themes=[], entities=[], interlocutors=[])
    await consolidator._store_connaissance({"content": row.content}, source_message_ids=[10], **kwargs)
    await row.arefresh_from_db()
    assert row.decayed_at == ancre
    await consolidator._store_connaissance({"content": row.content}, source_message_ids=[11], **kwargs)
    await row.arefresh_from_db()
    assert row.decayed_at > ancre and row.confidence == .35


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("preuves,statut", [(["project_list_files"], "blocked"), ([], "in_progress")])
async def test_inventaire_ou_preuve_oubliee_ne_termine_pas_une_tache(preuves, statut):
    from projects.context_builder import build
    from projects.models import Project, ProjectTask
    from projects.runner import ProjectRunner
    from utils.tool_trace import AppelOutil, JournalOutils

    project = await Project.objects.acreate(title="Mission")
    task = await ProjectTask.objects.acreate(project=project, description="Livrer le document")
    journal = JournalOutils()
    journal.noter(AppelOutil("project_list_files"))
    data = {"task_updates": [{"id": task.pk, "status": "done", "result": "Fait", "evidence_tools": preuves}]}
    await ProjectRunner()._apply_structured(await build(project.pk), data, raw="", evidence=journal.as_dict())
    await task.arefresh_from_db()
    assert task.status == statut and task.completed_at is None


@pytest.mark.django_db(transaction=True)
async def test_credit_reserve_avant_l_appel_et_non_renouvele_par_tick(monkeypatch):
    from projects import runner
    from projects.models import Project, ProjectRunReservation

    project = await Project.objects.acreate(title="Travail")
    moteur = runner.ProjectRunner()
    original = runner.cfg_int
    monkeypatch.setattr(runner, "cfg_int", lambda key, *a, **kw:
                        1 if key == "projects.daily_runs_per_project" else original(key, *a, **kw))
    monkeypatch.setattr(moteur, "_list_due", AsyncMock(return_value=[project.pk]))

    async def avancer(pid):
        assert await ProjectRunReservation.objects.filter(project_id=pid).acount() == 1
        return True

    appel = AsyncMock(side_effect=avancer)
    monkeypatch.setattr(moteur, "_advance", appel)
    assert await moteur.tick() == 1
    assert await moteur.tick() == 0
    appel.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
async def test_reprise_libere_l_echeance_reportee_par_stagnation():
    from projects.models import Project
    from projects.runner import ProjectRunner

    demain = timezone.now() + timedelta(days=1)
    project = await Project.objects.acreate(title="Reprendre", schedule_rule="interval:30s",
                                          retry_after=demain, next_run_at=demain)
    moteur = ProjectRunner()
    await moteur.notify_user_input(project.pk)
    assert project.pk in await moteur._list_due()


@pytest.mark.django_db
def test_fin_tardive_necrase_pas_la_resolution_operateur():
    from conscience.agenda import enregistrer_tentative
    from conscience.models import ScheduledAction

    action = ScheduledAction.objects.create(prompt="Envoi", scheduled_at=timezone.now(), status="uncertain",
                                            context_data={"attempt_token": "ancien"})
    ScheduledAction.objects.filter(pk=action.pk).update(status="pending", context_data={})
    action.status = "executed"
    enregistrer_tentative(action, ["status"])
    action.refresh_from_db()
    assert action.status == "pending"


async def test_intention_interne_ne_declenche_pas_de_murmure(monkeypatch):
    from conscience import engine
    from conscience.acte import ActeResultat
    from conscience.types import DecisionContext
    from memory.sleep import sleep_cycle

    moteur = engine.ConscienceEngine()
    monkeypatch.setattr(sleep_cycle, "note_interaction", Mock())
    action = SimpleNamespace(context_data={"mode": "internal"})
    ctx = DecisionContext([], "neutral", 0, 7200, False, 0, 0, scheduled_actions=[action])
    monkeypatch.setattr(moteur, "_build_context", AsyncMock(return_value=ctx))
    for nom in ("_suivre_l_estime_sociale", "_memory_maintenance", "_log_decision",
                "_cleanup_old_observations", "_save_drives_if_due"):
        monkeypatch.setattr(moteur, nom, AsyncMock())
    monkeypatch.setattr(moteur, "_suivre_la_detresse", Mock())
    monkeypatch.setattr(moteur, "_compute_score", Mock(return_value=(.9, "rappel interne")))
    monkeypatch.setattr(moteur, "_travaux_en_cours", AsyncMock(return_value=([], set())))
    monkeypatch.setattr(moteur, "_recolter", Mock(return_value=[]))
    monkeypatch.setattr(moteur, "_quelquun_est_joignable", Mock(return_value=False))
    monkeypatch.setattr(moteur, "_act", AsyncMock(return_value=ActeResultat(dit="Réflexion", interne=True)))
    murmure = AsyncMock()
    monkeypatch.setattr(engine, "murmurer", murmure)
    await moteur._decide_inner()
    moteur._act.assert_awaited_once()
    murmure.assert_not_awaited()
