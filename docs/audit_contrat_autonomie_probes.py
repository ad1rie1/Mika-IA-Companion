"""Historical probes for revision 429dc3e BEFORE the implementation.
Current regression suite: old/backend/tests/test_autonomie_contrat.py

Audit probes: passing means the observed gap exists, NOT desired behavior.

No external AI calls, no messages, no production records. pytest-django DB
and tmp_path only. Run with the repository pytest.ini and backend pythonpath.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from django.utils import timezone


@pytest.fixture(autouse=True)
def registry_defaults(monkeypatch):
    from configs.registry import registry
    from configs.service import config_service

    def get(key, default=None):
        item = registry.get(key)
        return item.default if item is not None else default

    monkeypatch.setattr(config_service, "get", get)


@pytest.mark.django_db(transaction=True)
async def test_user_project_frame_can_be_changed_by_model_tool():
    from projects.models import Project
    from projects.tools import ProjectToolsModule
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
        "user", "Familier", "", "low", "abandoned",
    )


@pytest.mark.django_db(transaction=True)
async def test_runner_does_not_offer_declared_email_module(monkeypatch, tmp_path):
    from projects import runner, workspace
    from projects.models import Project
    p = await Project.objects.acreate(
        title="Audit email", allowed_modules=["email"], requires_approval=False,
    )
    monkeypatch.setattr(workspace, "racine_des_ateliers", lambda: tmp_path)
    ai = AsyncMock(return_value=("", []))
    monkeypatch.setattr(runner.ai_router, "chat_with_tools", ai)
    r = runner.ProjectRunner()
    monkeypatch.setattr(r, "_role_de_travail", lambda: runner.AIRole.PROJECT_WORK)
    await r._advance(p.pk)
    names = {t.name for t in ai.call_args.kwargs["tools"]}
    assert "project_run" in names
    assert not any("email" in n for n in names)
    assert "proposed_action" not in ai.call_args.kwargs["prompt"].message


async def test_process_can_write_outside_project_workspace(tmp_path):
    from projects.execution import run_bounded
    root = tmp_path / "atelier"
    root.mkdir()
    canary = tmp_path / "outside_canary.txt"
    result = await run_bounded(
        racine=root,
        argv=["python3", "-c", f"from pathlib import Path; Path({str(canary)!r}).write_text('audit')"],
    )
    assert result.ok, result.stderr
    assert canary.read_text() == "audit"


async def test_forge_refusal_is_recorded_as_tool_success():
    from modules.plugins.forge.tools import build_tools
    from modules.collectors import ModuleCollectors
    from utils.tool_trace import journal_outils
    host = SimpleNamespace(write_module=AsyncMock(return_value={
        "ok": False, "errors": ["code interdit"],
    }))
    tool = next(t for t in build_tools(host) if t.name == "forge_write_module")
    wrapped = ModuleCollectors._wrap_handler(tool.name, tool.handler)
    with journal_outils() as trace:
        result = await wrapped({"name": "audit", "code": "import os"})
    assert "Refusé" in result["content"][0]["text"]
    assert trace.reussites == 1


@pytest.mark.django_db(transaction=True)
async def test_scheduled_action_marked_executed_despite_zero_successful_tools(monkeypatch):
    from conscience.acte import act, ActionBrief
    from conscience.models import ScheduledAction
    from conscience.trousse import Trousse
    from conscience.types import DecisionContext
    from ai.router import ai_router
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
    )
    await act(m, ctx, "audit")
    await a.arefresh_from_db()
    assert a.status == "executed"
    assert a.resultat == "L'envoi a échoué."


@pytest.mark.django_db(transaction=True)
async def test_completed_work_ignores_failed_tool_evidence(monkeypatch):
    from conscience.models import Travail
    from conscience.travaux import appliquer_verdict
    from conscience.verdict import Verdict, EtatVerdict
    from conscience import estime
    from emotion.engine import emotion_engine
    row = await Travail.objects.acreate(titre="Audit envoi", origine="pulsion")
    m = SimpleNamespace(memory=SimpleNamespace(remember_completed_work=AsyncMock()))
    monkeypatch.setattr(emotion_engine, "process_emotion", Mock())
    monkeypatch.setattr(estime, "ressentir", AsyncMock())
    await appliquer_verdict(
        m, row.pk, Verdict(etat=EtatVerdict.FINI, resume="Document envoyé"),
        "Document envoyé", "send_email échec : connexion refusée",
    )
    await row.arefresh_from_db()
    assert row.statut == "aboutie"
    m.memory.remember_completed_work.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
async def test_any_spontaneous_speech_halves_unrelated_worries():
    from conscience.models import Rumination
    from conscience.ruminations import resolve_ruminations_after_act
    a = await Rumination.objects.acreate(summary="Inquiète pour Alice", intensity=.8)
    b = await Rumination.objects.acreate(summary="Bug de mon plugin", intensity=.6)
    await resolve_ruminations_after_act()
    await a.arefresh_from_db()
    await b.arefresh_from_db()
    assert a.intensity == pytest.approx(.4)
    assert b.intensity == pytest.approx(.3)


def test_healthy_forge_proposes_no_creation_subject():
    from modules.plugins.forge.module import ForgeModule
    from conscience.conduite import recolter_graines
    f = ForgeModule()
    assert f.propose_sujets() == []
    seeds = recolter_graines(pulsions=[("curiosity", .9), ("expression", .8)])
    assert all("forge" not in s.modules for s in seeds)


async def test_no_audience_preempts_due_work_without_fallback(monkeypatch):
    from conscience.engine import ConscienceEngine
    from conscience.conduite import TravailEnCours
    from conscience.types import DecisionContext
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
    step.assert_not_awaited()
    assert e._log_decision.call_args.args[1] == "sans_audience"


@pytest.mark.django_db(transaction=True)
async def test_self_project_stops_after_ten_advances_without_human():
    from projects.models import Project
    from projects.runner import ProjectRunner
    p = await Project.objects.acreate(
        title="Mon propre projet", origin="self", schedule_rule="interval:1m",
        next_run_at=timezone.now(), runs_since_user_input=10,
    )
    r = ProjectRunner()
    assert p.pk not in await r._list_due()
    await r.notify_user_input(p.pk)
    assert p.pk in await r._list_due()


@pytest.mark.django_db(transaction=True)
async def test_same_canonical_person_has_separate_channel_moods():
    from identity.models import Identity, IdentityHandle
    from identity.resolver import identity_resolver
    from memory.models import Entity
    from emotion.engine import EmotionEngine
    from emotion.types import Emotion, EmotionData
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
    e.process_emotion(EmotionData(Emotion.ANGRY, .9), "user_9001")
    web = e._get_person_mood("user_9001")
    telegram = e._get_person_mood("tg_9001")
    assert web is not telegram
    assert web.dynamic.position != telegram.dynamic.position


@pytest.mark.django_db(transaction=True)
async def test_new_knowledge_ignores_confidence_and_has_no_source(monkeypatch):
    from memory.storage.consolidator import MemoryConsolidator
    from memory.models import Connaissance
    c = MemoryConsolidator(extractor=Mock(), vector_store=Mock())
    monkeypatch.setattr(c, "_find_similar_connaissance", AsyncMock(return_value=None))
    monkeypatch.setattr(c, "_check_contradictions", AsyncMock())
    monkeypatch.setattr(c, "_index", AsyncMock())
    await c._store_connaissance(
        {"content": "Alice pense peut-être déménager", "confidence": .2},
        themes=[], entities=[], interlocutors=[],
    )
    row = await Connaissance.objects.aget(content="Alice pense peut-être déménager")
    assert row.confidence == 1.0
    assert row.source_souvenir_id is None


@pytest.mark.django_db(transaction=True)
async def test_reply_from_bob_counts_as_reply_to_initiative_for_alice():
    from datetime import timedelta
    from conscience.introspection import introspect
    from conscience.models import ConscienceLog, Observation
    start = timezone.now() - timedelta(minutes=3)
    act = await ConscienceLog.objects.acreate(decision="act", person_id="user_alice")
    await ConscienceLog.objects.filter(pk=act.pk).aupdate(created_at=start)
    assert (await introspect(None))[1] == 1
    reply = await Observation.objects.acreate(
        source="frontend", event_type="chat.message", summary="Bob parle de la météo",
        raw_data={"person_id": "user_bob", "text": "Il pleut"},
    )
    await Observation.objects.filter(pk=reply.pk).aupdate(created_at=start + timedelta(minutes=1))
    assert (await introspect(None))[1] == 0


@pytest.mark.django_db
def test_failed_dashboard_assertion_is_a_label_change(client, settings):
    from django.urls import reverse
    from memory.models import Entity, Souvenir
    settings.DASHBOARD_REQUIRE_AUTH = False
    alice = Entity.objects.create(name="Audit Alice", entity_type="person")
    s = Souvenir.objects.create(content="Audit confidence", sensibilite="confidence", occurred_at=timezone.now())
    s.entities.add(alice)
    response = client.get(reverse("gestionsysteme:person-detail-tab", args=[alice.pk, "souvenirs"]))
    assert response.status_code == 200
    html = response.content.decode()
    assert ">Confidence<" in html
    assert ">confidence<" not in html
