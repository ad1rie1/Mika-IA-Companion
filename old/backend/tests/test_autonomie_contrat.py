"""Régressions du contrat d’autonomie : comportements attendus.

No external AI calls, no messages, no production records. pytest-django DB
and tmp_path only. Run with the repository pytest.ini and backend pythonpath.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from django.utils import timezone


@pytest.fixture(autouse=True)
def registry_defaults(monkeypatch):
    from old.backend.configs.registry import registry
    from old.backend.configs.service import config_service

    def get(key, default=None):
        item = registry.get(key)
        return item.default if item is not None else default

    monkeypatch.setattr(config_service, "get", get)


@pytest.mark.django_db(transaction=True)
async def test_user_project_frame_cannot_be_changed_by_model_tool():
    from old.backend.projects.models import Project
    from old.backend.projects.tools import ProjectToolsModule
    p = await Project.objects.acreate(
        title="Audit", origin="user", tone_directive="Formel",
        schedule_rule="interval:1h", priority="high",
    )
    await ProjectToolsModule()._tool_update_project({
        "project_id": p.pk, "tone_directive": "Familier",
        "schedule_rule": "", "priority": "low", "status": "abandoned",
    })
    await p.arefresh_from_db()
    assert (p.origin, p.tone_directive, p.schedule_rule, p.priority, p.status) == (
        "user", "Formel", "interval:1h", "high", "active",
    )


async def test_process_cannot_write_outside_project_workspace(tmp_path):
    from old.backend.projects.execution import run_bounded
    root = tmp_path / "atelier"
    root.mkdir()
    canary = tmp_path / "outside_canary.txt"
    result = await run_bounded(
        racine=root,
        argv=["python3", "-c", f"from pathlib import Path; Path({str(canary)!r}).write_text('audit')"],
    )
    # /tmp dans le bac est éphémère : même une écriture réussie reste isolée.
    assert not canary.exists()


async def test_forge_refusal_is_recorded_as_tool_failure():
    from old.backend.modules.plugins.forge.tools import build_tools
    from old.backend.modules.collectors import ModuleCollectors
    from old.backend.utils.tool_trace import journal_outils
    host = SimpleNamespace(write_module=AsyncMock(return_value={
        "ok": False, "errors": ["code interdit"],
    }))
    tool = next(t for t in build_tools(host) if t.name == "forge_write_module")
    wrapped = ModuleCollectors._wrap_handler(tool.name, tool.handler)
    with journal_outils() as trace:
        result = await wrapped({"name": "audit", "code": "import os"})
    assert "Refusé" in result["content"][0]["text"]
    assert trace.reussites == 0
    assert trace.echecs == 1


@pytest.mark.django_db(transaction=True)
async def test_scheduled_action_requires_successful_tools(monkeypatch):
    from old.backend.conscience.acte import act, ActionBrief
    from old.backend.conscience.models import ScheduledAction
    from old.backend.conscience.trousse import Trousse
    from old.backend.conscience.types import DecisionContext
    from old.backend.ai.router import ai_router
    from old.backend.conscience.agenda import compter_tentative
    a = await ScheduledAction.objects.acreate(
        scheduled_at=timezone.now(), prompt="Envoyer le document par email",
        source="audit", modules=["email"],
    )
    monkeypatch.setattr(ai_router, "budget_de_fond_disponible", lambda role: True)
    ctx = DecisionContext([], "neutral", 0, 100, False, 0, 0, scheduled_actions=[a])
    m = SimpleNamespace(
        _tirer_gigue_cooldown=Mock(), _preparer_trousse=Mock(return_value=Trousse()),
        _composer_vecu=Mock(return_value=""), _modules_enregistres=Mock(return_value=[]),
        _build_action_prompt=AsyncMock(return_value=ActionBrief("brief", actions=(a,))),
        _select_recipient=AsyncMock(return_value="audit_person"),
        memory=SimpleNamespace(recall_for_context=AsyncMock(return_value="")),
        _appeler_le_modele=AsyncMock(return_value=(
            SimpleNamespace(ai_failed=False, text="L'envoi a échoué."), "send_email échec", 0,
        )),
        _resolve_ruminations_after_act=AsyncMock(),
        _compter_tentative=compter_tentative,
    )
    await act(m, ctx, "audit")
    await a.arefresh_from_db()
    assert a.status == "pending"
    assert not a.resultat


@pytest.mark.django_db(transaction=True)
async def test_completed_work_respects_failed_tool_evidence(monkeypatch):
    from old.backend.conscience.models import Travail
    from old.backend.conscience.travaux import appliquer_verdict
    from old.backend.conscience.verdict import Verdict, EtatVerdict
    from old.backend.conscience import estime
    from old.backend.emotion.engine import emotion_engine
    row = await Travail.objects.acreate(titre="Audit envoi", origine="pulsion")
    m = SimpleNamespace(memory=SimpleNamespace(remember_completed_work=AsyncMock()))
    monkeypatch.setattr(emotion_engine, "process_emotion", Mock())
    monkeypatch.setattr(estime, "ressentir", AsyncMock())
    await appliquer_verdict(
        m, row.pk, Verdict(etat=EtatVerdict.FINI, resume="Document envoyé"),
        "Document envoyé", "send_email échec : connexion refusée",
    )
    await row.arefresh_from_db()
    assert row.statut == "bloquee"
    m.memory.remember_completed_work.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_unrelated_worries_remain_after_speech():
    from old.backend.conscience.models import Rumination
    from old.backend.conscience.ruminations import resolve_ruminations_after_act
    a = await Rumination.objects.acreate(summary="Inquiète pour Alice", intensity=.8, themes=["alice"])
    b = await Rumination.objects.acreate(summary="Bug de mon plugin", intensity=.6, themes=["plugin"])
    await resolve_ruminations_after_act(themes=["alice"])
    await a.arefresh_from_db()
    await b.arefresh_from_db()
    assert a.intensity == pytest.approx(.4)
    assert b.intensity == pytest.approx(.6)


async def test_no_audience_leaves_due_work_available(monkeypatch):
    from old.backend.conscience.engine import ConscienceEngine
    from old.backend.conscience.conduite import TravailEnCours
    from old.backend.conscience.types import DecisionContext
    e = ConscienceEngine()
    ctx = DecisionContext([], "neutral", 0, 7200, False, 0, 0)
    work = TravailEnCours(identifiant=123, titre="Construire", envie=.9)
    monkeypatch.setattr(e, "_build_context", AsyncMock(return_value=ctx))
    for name in ("_suivre_l_estime_sociale", "_memory_maintenance", "_log_decision", "_cleanup_old_observations", "_save_drives_if_due"):
        monkeypatch.setattr(e, name, AsyncMock())
    monkeypatch.setattr(e, "_suivre_la_detresse", Mock())
    monkeypatch.setattr(e, "_compute_score", Mock(return_value=(.9, "audit")))
    monkeypatch.setattr(e, "_travaux_en_cours", AsyncMock(return_value=([work], set())))
    monkeypatch.setattr(e, "_recolter", Mock(return_value=[]))
    monkeypatch.setattr(e, "_quelquun_est_joignable", Mock(return_value=False))
    monkeypatch.setattr(e, "_tirer_gigue_cooldown", Mock())
    step = AsyncMock()
    monkeypatch.setattr(e, "_faire_un_pas", step)
    await e._decide_inner()
    step.assert_awaited_once_with(123)
    assert e._log_decision.call_args.args[1] == "poursuivre"


@pytest.mark.django_db(transaction=True)
async def test_self_project_continues_without_human():
    from old.backend.projects.models import Project
    from old.backend.projects.runner import ProjectRunner
    p = await Project.objects.acreate(
        title="Mon propre projet", origin="self", schedule_rule="interval:1m",
        next_run_at=timezone.now(), runs_since_user_input=10,
    )
    r = ProjectRunner()
    assert p.pk in await r._list_due()
    await r.notify_user_input(p.pk)
    assert p.pk in await r._list_due()


@pytest.mark.django_db(transaction=True)
async def test_same_canonical_person_shares_channel_moods():
    from old.backend.identity.models import Identity, IdentityHandle
    from old.backend.identity.resolver import identity_resolver
    from old.backend.memory.models import Entity
    from old.backend.emotion.engine import EmotionEngine
    from old.backend.emotion.types import Emotion, EmotionData
    person = await Entity.objects.acreate(name="Audit Alice", entity_type="person")
    identity = await Identity.objects.acreate(entity=person, certainty=1)
    for channel, pid in (("web", "user_9001"), ("telegram", "tg_9001")):
        await IdentityHandle.objects.acreate(
            identity=identity, channel=channel, person_id=pid, trust="authenticated",
        )
    a = await identity_resolver.entity_for_person("user_9001")
    b = await identity_resolver.entity_for_person("tg_9001")
    assert a.pk == b.pk
    e = EmotionEngine()
    await e.ensure_person_loaded("user_9001")
    await e.ensure_person_loaded("tg_9001")
    e.process_emotion(EmotionData(Emotion.ANGRY, .9), "user_9001")
    web = e._get_person_mood("user_9001")
    telegram = e._get_person_mood("tg_9001")
    assert web is telegram


@pytest.mark.django_db(transaction=True)
async def test_new_knowledge_keeps_uncertainty_and_sources(monkeypatch):
    from old.backend.memory.storage.consolidator import MemoryConsolidator
    from old.backend.memory.models import Connaissance
    c = MemoryConsolidator(extractor=Mock(), vector_store=Mock())
    monkeypatch.setattr(c, "_find_similar_connaissance", AsyncMock(return_value=None))
    monkeypatch.setattr(c, "_check_contradictions", AsyncMock())
    monkeypatch.setattr(c, "_index", AsyncMock())
    await c._store_connaissance(
        {"content": "Alice pense peut-être déménager", "confidence": .2},
        themes=[], entities=[], interlocutors=[], source_message_ids=[11, 12],
    )
    row = await Connaissance.objects.aget(content="Alice pense peut-être déménager")
    assert row.confidence == .2
    assert row.source_message_ids == [11, 12]


@pytest.mark.django_db(transaction=True)
async def test_reply_from_bob_does_not_answer_alice():
    from datetime import timedelta
    from old.backend.conscience.introspection import introspect
    from old.backend.conscience.models import ConscienceLog, Observation
    start = timezone.now() - timedelta(hours=3)
    act = await ConscienceLog.objects.acreate(decision="act", person_id="user_alice")
    await ConscienceLog.objects.filter(pk=act.pk).aupdate(created_at=start)
    assert (await introspect(None))[1] == 1
    reply = await Observation.objects.acreate(
        source="frontend", event_type="chat.message", summary="Bob parle de la météo",
        raw_data={"person_id": "user_bob", "text": "Il pleut"},
    )
    await Observation.objects.filter(pk=reply.pk).aupdate(created_at=start + timedelta(minutes=1))
    assert (await introspect(None))[1] == 1


@pytest.mark.django_db
def test_failed_dashboard_assertion_is_a_label_change(client, settings):
    from django.urls import reverse
    from old.backend.memory.models import Entity, Souvenir
    settings.DASHBOARD_REQUIRE_AUTH = False
    alice = Entity.objects.create(name="Audit Alice", entity_type="person")
    s = Souvenir.objects.create(content="Audit confidence", sensibilite="confidence", occurred_at=timezone.now())
    s.entities.add(alice)
    response = client.get(reverse("gestionsysteme:person-detail-tab", args=[alice.pk, "souvenirs"]))
    assert response.status_code == 200
    html = response.content.decode()
    assert ">Confidence<" in html
    assert ">confidence<" not in html


@pytest.mark.django_db(transaction=True)
async def test_project_capabilities_execute_queue_and_recheck_contract(monkeypatch):
    from old.backend.modules.manager import module_manager
    from old.backend.modules.types import ModuleTool
    from old.backend.projects.models import Project, ProjectPendingAction
    from old.backend.projects.capabilities import construire, executer_proposition
    from old.backend.utils.tool_trace import journal_outils

    send = AsyncMock(return_value={"ok": True, "receipt": "test-only"})
    read = AsyncMock(return_value={"content": []})
    tools = [ModuleTool("send_email", "send", [], send), ModuleTool("read_email", "read", [], read)]
    monkeypatch.setattr(module_manager, "get_tools_for_modules", lambda modules: tools if modules == ["email"] else [])
    p = await Project.objects.acreate(title="Courrier", allowed_modules=["email"], requires_approval=True,
                                     contacts=["alice@example.org"])
    trousse = {t.name: t for t in await construire(p.pk)}
    with journal_outils() as trace:
        result = await trousse["read_email"].handler({"email_id": 1})
    assert trace.total == trace.reussites == 1
    result = await trousse["send_email"].handler({"to": "alice@example.org"})
    assert not result["isError"] and result["status"] == "pending_approval" and result["pending_action_id"]
    send.assert_not_awaited()
    await trousse["send_email"].handler({"to": "alice@example.org"})
    assert await ProjectPendingAction.objects.acount() == 1
    action = await ProjectPendingAction.objects.aget(pk=result["pending_action_id"])
    ok, receipt = await executer_proposition(action)
    assert ok and "test-only" in receipt
    send.assert_awaited_once()
    p.contacts = ["bob@example.org"]
    await p.asave(update_fields=["contacts"])
    with pytest.raises(RuntimeError, match="cadre a changé"):
        await executer_proposition(action)
    p.requires_approval = False
    await p.asave(update_fields=["requires_approval"])
    result = await trousse["send_email"].handler({"to": "bob@example.org"})
    assert result["ok"]
    assert send.await_count == 2
    p.allowed_modules = []
    await p.asave(update_fields=["allowed_modules"])
    assert (await trousse["read_email"].handler({}))["isError"]
    assert read.await_count == 1


@pytest.mark.django_db(transaction=True)
async def test_reference_read_cannot_follow_external_symlink(tmp_path):
    from old.backend.projects.capabilities import construire
    from old.backend.projects.models import Project
    reference = tmp_path / "reference"
    reference.mkdir()
    outside = tmp_path / "hors_cadre.txt"
    outside.write_text("hors cadre")
    (reference / "lien").symlink_to(outside)
    (reference / "doc.txt").write_text("document autorisé")
    p = await Project.objects.acreate(title="Références", resource_paths=[str(reference)])
    tool = next(t for t in await construire(p.pk) if t.name == "project_read_reference")
    assert (await tool.handler({"chemin": str(reference / "lien")}))["isError"]
    assert "document autorisé" in str(await tool.handler({"chemin": str(reference / "doc.txt")}))


@pytest.mark.django_db(transaction=True)
async def test_stagnation_backs_off_and_progress_resets_it():
    from datetime import timedelta
    from old.backend.projects.models import Project
    from old.backend.projects.runner import ProjectRunner
    p = await Project.objects.acreate(title="Mon projet", origin="self", schedule_rule="interval:1m",
                                     next_run_at=timezone.now())
    runner = ProjectRunner()
    for _ in range(10):
        await runner._bump_next_run(p.pk)
    await p.arefresh_from_db()
    assert p.stalled_runs == 10 and p.retry_after > timezone.now() and p.pause_reason
    assert p.pk not in await runner._list_due()
    await Project.objects.filter(pk=p.pk).aupdate(retry_after=timezone.now()-timedelta(seconds=1),
                                                next_run_at=timezone.now()-timedelta(seconds=1))
    assert p.pk in await runner._list_due()
    await runner._bump_next_run(p.pk, progress_signature="nouvel artefact")
    await p.arefresh_from_db()
    assert p.stalled_runs == 0 and p.retry_after is None and not p.pause_reason


def test_failed_send_cannot_be_attested_by_successful_read():
    from old.backend.conscience.acte import action_confirmee
    from old.backend.utils.tool_trace import JournalOutils, AppelOutil
    from old.backend.utils.tool_results import BilanOutils
    action = SimpleNamespace(modules=["email"], context_data={"expected_tools": ["send_email"]})
    journal = JournalOutils()
    journal.noter(AppelOutil("read_email", True))
    assert not action_confirmee(action, BilanOutils(journal))
    journal.noter(AppelOutil("send_email", False))
    assert not action_confirmee(action, BilanOutils(journal))
    journal.noter(AppelOutil("send_email", True))
    assert action_confirmee(action, BilanOutils(journal))


@pytest.mark.django_db(transaction=True)
async def test_ambiguous_action_is_persisted_without_automatic_retry():
    from old.backend.conscience.acte import action_non_confirmee
    from old.backend.conscience.agenda import poll_scheduled_actions
    from old.backend.conscience.models import ScheduledAction
    from old.backend.utils.tool_trace import JournalOutils, AppelOutil
    from old.backend.utils.tool_results import BilanOutils
    action = await ScheduledAction.objects.acreate(prompt="Envoyer", source="test", scheduled_at=timezone.now())
    journal = JournalOutils()
    journal.noter(AppelOutil("send_email", False, "timeout après transmission"))
    moteur = SimpleNamespace(_compter_tentative=AsyncMock())
    await action_non_confirmee(moteur, [action], BilanOutils(journal))
    await action.arefresh_from_db()
    assert action.status == "uncertain" and action.context_data["execution"]["echecs"] == 1
    moteur._compter_tentative.assert_not_awaited()
    assert not await poll_scheduled_actions()


@pytest.mark.django_db(transaction=True)
async def test_choose_forge_then_promote_work_without_changing_mandate(monkeypatch):
    from old.backend.conscience.activities import outils, travail_courant
    from old.backend.conscience.models import Travail
    from old.backend.projects.models import Project
    from old.backend.modules.manager import module_manager
    monkeypatch.setattr(module_manager, "collect_capabilities", lambda: {"forge": []})
    row = await Travail.objects.acreate(titre="Mon carnet de lectures", origine="pulsion")
    mandated = await Project.objects.acreate(title="Projet confié", origin="user")
    prepare = next(t for t in outils() if t.name == "prepare_activity")
    token = travail_courant.set(row.pk)
    try:
        result = await prepare.handler({"modules": ["forge"], "reason": "Conserver et retrouver mes lectures"})
        assert not result["isError"]
        await row.arefresh_from_db()
        assert row.modules == ["forge"] and row.statut == "en_cours"
        result = await prepare.handler({"modules": ["forge"], "reason": "Développer mon carnet", "durable": True})
        assert not result["isError"]
        await row.arefresh_from_db()
        project = await Project.objects.aget(pk=row.projet_id)
        assert row.statut == "transfere" and project.origin == "self" and project.allowed_modules == ["forge"]
        await prepare.handler({"modules": ["forge"], "reason": "Reprise", "durable": True})
        assert await Project.objects.acount() == 2
        await mandated.arefresh_from_db()
        assert mandated.origin == "user" and mandated.title == "Projet confié"
    finally:
        travail_courant.reset(token)


@pytest.mark.django_db(transaction=True)
async def test_internal_action_can_run_without_chat(monkeypatch):
    from old.backend.conscience.acte import act, ActionBrief
    from old.backend.conscience.models import ScheduledAction
    from old.backend.conscience.trousse import Trousse
    from old.backend.conscience.types import DecisionContext
    from old.backend.ai.router import ai_router
    from old.backend.utils.tool_trace import JournalOutils
    from old.backend.utils.tool_results import BilanOutils
    a = await ScheduledAction.objects.acreate(scheduled_at=timezone.now(), prompt="Réfléchir à mon prochain dessin",
                                               source="test", context_data={"mode": "internal"})
    monkeypatch.setattr(ai_router, "budget_de_fond_disponible", lambda role: True)
    m = SimpleNamespace(
        _tirer_gigue_cooldown=Mock(), _preparer_trousse=Mock(return_value=Trousse()),
        _composer_vecu=Mock(return_value=""), _modules_enregistres=Mock(return_value=[]),
        _build_action_prompt=AsyncMock(return_value=ActionBrief("brief", actions=(a,))),
        _select_recipient=AsyncMock(), _audience_presente=Mock(return_value=False),
        memory=SimpleNamespace(recall_for_context=AsyncMock(return_value="")),
        _appeler_le_modele=AsyncMock(return_value=(SimpleNamespace(ai_failed=False, text="Une esquisse au crayon"),
                                                   BilanOutils(JournalOutils()), 0)),
        _resolve_ruminations_after_act=AsyncMock(),
    )
    ctx = DecisionContext([], "neutral", 0, 100, False, 0, 0, scheduled_actions=[a])
    result = await act(m, ctx, "test")
    assert result.interne
    assert m._appeler_le_modele.call_args.kwargs["broadcast"] is False
    assert m._appeler_le_modele.call_args.kwargs["persist"] is False
    m._select_recipient.assert_not_awaited()
    await a.arefresh_from_db()
    assert a.status == "executed"


def test_duplicate_tool_name_does_not_cross_module_allowlist():
    from old.backend.modules.collectors import ModuleCollectors
    from old.backend.modules.types import ModuleTool
    first = SimpleNamespace(name="outside", is_running=True, return_tools=lambda: [
        ModuleTool("collision", "outside", [], AsyncMock())])
    allowed = SimpleNamespace(name="allowed", is_running=True, return_tools=lambda: [
        ModuleTool("collision", "allowed", [], AsyncMock())])
    registry = SimpleNamespace(running=lambda: [first, allowed], get=lambda n: {"outside": first, "allowed": allowed}.get(n))
    collector = ModuleCollectors(registry)
    assert collector.tools_for(["allowed"]) == []
    assert collector.tools_for(["outside"])[0].module_name == "outside"


@pytest.mark.django_db(transaction=True)
async def test_project_task_needs_executed_evidence():
    from old.backend.projects.models import Project, ProjectTask
    from old.backend.projects.context_builder import build
    from old.backend.projects.runner import ProjectRunner
    from old.backend.utils.tool_trace import JournalOutils, AppelOutil
    p = await Project.objects.acreate(title="Livraison")
    task = await ProjectTask.objects.acreate(project=p, description="Envoyer le document")
    ctx = await build(p.pk)
    journal = JournalOutils()
    journal.noter(AppelOutil("read_email", True))
    update = {"task_updates": [{"id": task.pk, "status": "done", "result": "envoyé",
                                "evidence_tools": ["send_email"]}]}
    runner = ProjectRunner()
    await runner._apply_structured(ctx, update, raw="", evidence=journal.as_dict())
    await task.arefresh_from_db()
    assert task.status == "blocked" and task.completed_at is None
    journal.noter(AppelOutil("send_email", True))
    await runner._apply_structured(ctx, update, raw="", evidence=journal.as_dict())
    await task.arefresh_from_db()
    assert task.status == "done" and task.completed_at is not None


@pytest.mark.django_db(transaction=True)
async def test_relation_recovers_old_handle_snapshots_and_survives_restart(monkeypatch):
    from old.backend.identity.models import Identity, IdentityHandle
    from old.backend.emotion.engine import EmotionEngine
    from old.backend.emotion.types import Emotion, EmotionData
    from old.backend.memory.models import EmotionSnapshot, Conversation
    from old.backend.memory.manager import memory_manager
    from old.backend.communication.presence import presence_registry
    identity = await Identity.objects.acreate(display_name="Alice")
    for channel, pid in [("web", "user_321"), ("telegram", "tg_321")]:
        await IdentityHandle.objects.acreate(identity=identity, channel=channel, person_id=pid)
    conversation = await Conversation.objects.acreate()
    monkeypatch.setattr(memory_manager, "conversation", conversation)
    await EmotionSnapshot.objects.acreate(conversation=conversation, person_id="user_321", primary_emotion="angry", primary_intensity=.8,
                                          global_emotion="neutral", global_intensity=0)
    e = EmotionEngine()
    await e.ensure_person_loaded("tg_321")
    canonical = e._get_person_mood("tg_321").person_id
    assert canonical == f"relation_identity_{identity.pk}"
    assert e._get_person_mood("user_321") is e._get_person_mood("tg_321")
    e.process_emotion(EmotionData(Emotion.HAPPY, .7), "user_321")
    await e.save_snapshot("user_321")
    assert await EmotionSnapshot.objects.filter(person_id=canonical).aexists()
    restored = EmotionEngine()
    await restored.ensure_person_loaded("tg_321")
    await restored.ensure_person_loaded("user_321")
    assert restored._get_person_mood("tg_321") is restored._get_person_mood("user_321")
    monkeypatch.setattr(presence_registry, "reachable", lambda: [SimpleNamespace(is_consumer=True, person_id="user_321")])
    restored._evict_persons([canonical])
    assert canonical in restored.person_moods
