"""Parcours de gestion avec des collections dépassant réellement une page."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone

from GestionSysteme import tables

pytestmark = pytest.mark.django_db


def url(name, *args):
    return reverse(f"gestionsysteme:{name}", args=args)


@pytest.mark.parametrize("params,expected", [({}, "pending"), ({"statut": ""}, ""),
    ({"statut": "invalid"}, "pending"), ({"statut": "done"}, "done")])
def test_tous_est_distinct_du_filtre_par_defaut(rf, params, expected):
    f = tables.select_filter(rf.get("/gestion/", params), "statut", "État",
                             [("pending", "En attente"), ("done", "Fini")], default="pending")
    assert f.value == expected


def test_filtrer_une_liste_preserve_les_autres_et_les_valeurs_repetees(rf):
    request = rf.get("/gestion/?q=ancien&p_taches=2&p_journal=3&etat=&tag=a&tag=b")
    fs = tables.FilterSet(show_per_page=False)
    fs.add(tables.search_filter(request))
    fs.preserve(request, page_param="p_taches")
    assert fs.hidden == [("p_journal", "3"), ("etat", ""), ("tag", "a"), ("tag", "b")]
    assert fs.reset_url == "/gestion/?p_journal=3&etat=&tag=a&tag=b"
    assert 15 in tables.FilterSet(per_page=15).per_page_choices


def test_pagination_stable_sans_modifier_les_groupes(rf):
    from django.db.models import Count
    from conscience.models import Observation
    Observation.objects.bulk_create([Observation(summary=str(i), source="test", category=str(i % 2)) for i in range(31)])
    Observation.objects.update(created_at=timezone.now())
    qs = Observation.objects.order_by("-created_at")
    first = tables.paginate(rf.get("/"), qs, per_page=25)
    last = tables.paginate(rf.get("/?page=2"), qs, per_page=25)
    assert [r.pk for r in first.rows + last.rows] == list(qs.order_by("pk").values_list("pk", flat=True))
    grouped = qs.order_by("category").values("category").annotate(n=Count("pk"))
    page = tables.paginate(rf.get("/"), grouped)
    assert page.total == 2
    assert sorted(r["n"] for r in page.rows) == [15, 16]


def test_projet_pagination_independante_compteurs_et_retour(client):
    from projects.models import Project, ProjectTask, ProjectLog, ProjectPendingAction, ProjectPromptHistory
    project = Project.objects.create(title="Projet paginé")
    ProjectTask.objects.bulk_create([ProjectTask(project=project, description=f"Étape {i}", order=i,
        status="done" if i < 8 else "blocked" if i < 14 else "todo") for i in range(61)])
    ProjectLog.objects.bulk_create([ProjectLog(project=project, action="advanced", summary=f"Passage {i}") for i in range(54)])
    ProjectPromptHistory.objects.bulk_create([ProjectPromptHistory(project=project, system_prompt="système", raw_response="réponse") for _ in range(12)])
    ProjectPendingAction.objects.create(project=project, proposal="À valider")
    response = client.get(url("project-detail", project.pk), {"p_taches": 3, "p_journal": 2, "p_prompts": 2})
    ctx = response.context
    assert [t.order for t in ctx["tasks_page"].rows] == list(range(50, 61))
    assert ctx["logs_page"].number == 2 and len(ctx["logs_page"].rows) == 25
    assert len(ctx["prompts_page"].rows) == 2
    assert (ctx["task_count"], ctx["done_count"], ctx["blocked_count"], ctx["pending_count"]) == (61, 8, 6, 1)
    assert ctx["progress"] == 8 / 61
    assert f'?projet={project.pk}&amp;statut=pending' in response.content.decode()
    filtered = client.get(url("project-detail", project.pk), {"etat_tache": "blocked", "p_journal": 2}).context
    assert filtered["tasks_page"].total == 6 and filtered["task_count"] == 61
    assert filtered["logs_page"].number == 2
    task = ctx["tasks_page"].rows[0]
    back = url("project-detail", project.pk) + "?p_taches=3&p_journal=2"
    response = client.post(url("task-update", project.pk, task.pk), {"action": "etat", "status": "done", "retour": back})
    assert response.url == back
    hostile = client.post(url("task-update", project.pk, task.pk), {"action": "etat", "status": "todo", "retour": "https://example.org/"})
    assert hostile.url == url("project-detail", project.pk)


def test_projets_tous_et_actions_filtrees_par_projet(client):
    from projects.models import Project, ProjectPendingAction
    first = Project.objects.create(title="Actif")
    second = Project.objects.create(title="Terminé", status="completed")
    for project in (first, second):
        ProjectPendingAction.objects.create(project=project, proposal=project.title)
    assert client.get(url("projects")).context["page"].total == 1
    assert client.get(url("projects"), {"statut": ""}).context["page"].total == 2
    response = client.get(url("projects-tab", "attente"), {"projet": f"#{second.pk}"})
    assert [r.project_id for r in response.context["page"].rows] == [second.pk]


def test_liste_projets_utilise_le_plafond_configure(client, monkeypatch):
    from projects.models import Project
    from configs import runtime
    Project.objects.create(title="Au plafond", runs_since_user_input=4)
    original = runtime.cfg_int
    monkeypatch.setattr(runtime, "cfg_int", lambda key, *a, **kw: 4 if key == "projects.runs_since_input_cap" else original(key, *a, **kw))
    response = client.get(url("projects"))
    assert response.context["runs_cap"] == 4
    assert "4/4" in response.content.decode()


def test_trace_projet_expose_le_resultat_et_un_contenu_borne(client):
    from projects.models import Project, ProjectPromptHistory
    project = Project.objects.create(title="Diagnostic")
    trace = ProjectPromptHistory.objects.create(project=project, system_prompt="x" * 200_000 + "FIN_CACHEE",
        raw_response="<script>alert(1)</script>", parsed_output={"done": False}, outcome="json_miss")
    response = client.get(url("record-detail", "prompt-projet", trace.pk))
    html = response.content.decode()
    assert response.status_code == 200
    assert "tronqué" in html and "FIN_CACHEE" not in html
    assert "&lt;script&gt;" in html and "<script>alert(1)</script>" not in html
    assert url("project-detail", project.pk) in html
    assert "Résultat interprété" in html


def test_agenda_montre_la_prochaine_tentative_et_pas_un_vieux_succes(client):
    from conscience.models import ScheduledAction
    now = timezone.now()
    ScheduledAction.objects.create(prompt="Ancien succès", scheduled_at=now - timedelta(days=50), status="executed")
    retried = ScheduledAction.objects.create(prompt="Réessayer demain", scheduled_at=now - timedelta(days=2), reessayer_le=now + timedelta(days=1))
    due = ScheduledAction.objects.create(prompt="À traiter", scheduled_at=now - timedelta(minutes=5))
    response = client.get(url("conscience-tab", "planification"))
    assert [r.pk for r in response.context["page"].rows] == [due.pk, retried.pk]
    assert response.context["scheduled_counts"] == {"pending": 2, "due": 1, "failed": 0}
    assert "Prochaine tentative" in response.content.decode()
    assert client.get(url("conscience-tab", "planification"), {"statut": ""}).context["page"].total == 3


def test_theme_hors_des_200_premiers_reste_consultable(client):
    from memory.models import Theme, Souvenir
    Theme.objects.bulk_create([Theme(name=f"A{i:03}") for i in range(210)])
    theme = Theme.objects.create(name="Zèbre")
    souvenir = Souvenir.objects.create(content="Une rencontre", occurred_at=timezone.now())
    souvenir.themes.add(theme)
    response = client.get(url("memory-tab", "souvenirs"), {"theme": theme.name})
    assert [r.pk for r in response.context["page"].rows] == [souvenir.pk]
    assert client.get(url("memory-tab", "souvenirs"), {"theme": "Absent"}).context["page"].total == 0


def test_config_liste_paginee_compteur_et_recherche_sans_secret(client, monkeypatch):
    from configs.service import config_service
    rows = [{"row_id": str(i), "enabled": True, "payload": {"internal_name": f"modele-{i:02}", "provider": "openai", "model_id": "exemple"}} for i in range(57)]
    original = config_service.list_rows
    monkeypatch.setattr(config_service, "list_rows", lambda key, **kw: rows if key == "ai.models" else original(key, **kw))
    response = client.get(url("config-section", "ai_models"), {"panneau": "ai-models", "p_lignes": 3})
    panel = response.context["panneau_actif"]
    assert panel["compte"] == 57 and len(panel["liste"]["page"].rows) == 7
    assert 'name="retour"' in response.content.decode()
    filtered = client.get(url("config-section", "ai_models"), {"panneau": "ai-models", "ligne": "modele-56"}).context["panneau_actif"]
    assert filtered["compte"] == 57 and filtered["liste"]["page"].total == 1
    assert filtered["liste"]["page"].rows[0]["row"]["row_id"] == "56"


def test_config_retour_valide_conserve_l_onglet_et_la_page(client, monkeypatch):
    from configs.service import config_service
    monkeypatch.setattr(config_service, "add_row", lambda *a, **kw: None)
    back = url("config-section", "ai_models") + "?panneau=ai-models&p_lignes=2"
    payload = {"internal_name": "test", "provider": "openai", "model_id": "test", "retour": back}
    response = client.post(url("config-record-new", "ai_models", "ai.models"), payload)
    assert response.url == back
    payload["retour"] = "https://example.org/"
    response = client.post(url("config-record-new", "ai_models", "ai.models"), payload)
    assert response.url == url("config-section", "ai_models") + "?panneau=ai-models"


def test_routage_tous_les_fournisseurs_et_modeles_pagines(client, monkeypatch):
    from ai.config_schema import PROVIDERS
    from configs.service import config_service
    original = config_service.list_rows
    rows = [{"enabled": True, "payload": {"internal_name": str(i), "provider": "openai", "model_id": "m"}} for i in range(32)]
    monkeypatch.setattr(config_service, "list_rows", lambda key, **kw: rows if key == "ai.models" else original(key, **kw))
    response = client.get(url("system-tab", "routage"), {"page": 2})
    assert {r["name"] for r in response.context["providers"]} == {label for _, label in PROVIDERS}
    assert len(response.context["models_page"].rows) == 7
    assert response.context["models_page"].total == 32


def test_sante_paginations_independantes_et_compteurs_globaux(client, monkeypatch):
    from utils.eventbus import event_bus
    from utils.degradation import degradations
    subscriptions = [{"name": f"abonné-{i:03}", "pattern": "test.*", "failed": i + 1, "delivered": 3} for i in range(61)]
    monkeypatch.setattr(event_bus, "stats", lambda: {"emitted": 42, "subscriptions": subscriptions})
    monkeypatch.setattr(degradations, "snapshot", lambda: [{"site": str(i), "count": i + 1} for i in range(70)])
    response = client.get(url("system-tab", "sante"), {"p_bus": 3, "p_erreurs": 2, "p_sites": 2})
    ctx = response.context
    assert len(ctx["subscriptions_page"].rows) == 11
    assert len(ctx["failing_subscriptions"]) == 61 and ctx["failing_count"] == 61
    assert len(ctx["sites_page"].rows) == 20


def test_quota_projets_nommes_et_projets_supprimes_sans_lien_casse(client, monkeypatch):
    from ai.quota import quota_tracker
    from projects.models import Project
    project = Project.objects.create(title="Budget utile")
    usage = {"tokens_month": 100, "tokens_day": 10, "calls_month": 1, "cost_usd_month": 0, "limit_monthly": 90}
    snap = SimpleNamespace(today="2026-09-20", month="2026-09", roles={}, limits={}, projects={str(project.pk): usage, "99999": usage})
    monkeypatch.setattr(quota_tracker, "snapshot", lambda: snap)
    html = client.get(url("system-tab", "quota")).content.decode()
    assert "Budget utile" in html and "90 jetons" in html
    assert "Projet supprimé #99999" in html
    assert url("project-detail", 99999) not in html


def test_catalogue_modules_et_outils_se_filtrent_separement(client, monkeypatch):
    from modules.manager import module_manager
    from GestionSysteme.views import modules
    infos = [{"name": f"plugin{i:02}", "enabled": True, "available": True, "running": i % 2 == 0} for i in range(30)]
    monkeypatch.setattr(module_manager, "list_all", lambda: infos)
    monkeypatch.setattr(module_manager, "get_all_status", lambda: [])
    monkeypatch.setattr(module_manager, "collect_capabilities", lambda: {})
    monkeypatch.setattr(module_manager, "get_registered", lambda name: None)
    monkeypatch.setattr(modules, "_tool_rows", lambda: [{"name": f"tool{i:02}", "description": "Lire", "module": "plugin00", "params": []} for i in range(53)])
    response = client.get(url("modules"), {"p_modules": 2, "p_outils": 3})
    assert len(response.context["page"].rows) == 12 and len(response.context["tools_page"].rows) == 3
    assert response.context["running_count"] == 15
    filtered = client.get(url("modules"), {"etat": "stopped", "outil": "tool52"}).context
    assert filtered["page"].total == 15 and filtered["tools_page"].total == 1


def test_catalogue_forge_pagine_et_filtre(client, monkeypatch):
    from GestionSysteme.views import forge
    monkeypatch.setattr(forge, "_host", lambda: object())
    monkeypatch.setattr(forge, "_infos", lambda host: [{"name": f"app{i:02}", "title": f"Application {i:02}", "status": "actif" if i % 2 else "cassé"} for i in range(29)])
    monkeypatch.setattr(forge, "_panels_for", lambda *a: [])
    monkeypatch.setattr(forge, "has_config", lambda *a: False)
    response = client.get(url("forge-apps"), {"page": 3})
    assert response.context["page"].total == 29 and len(response.context["page"].rows) == 5
    filtered = client.get(url("forge-apps"), {"statut": "cassé"}).context
    assert filtered["page"].total == 15 and filtered["app_count"] == 29


def test_forge_atelier_et_journal_sans_limite_cachee(rf):
    from modules.plugins.forge.panels import modules_panel, journal_panel
    from modules.plugins.forge.models import ForgeLog
    host = SimpleNamespace(module_infos=lambda: [{"name": f"app{i:03}"} for i in range(35)])
    table = modules_panel(host)(rf.get("/gestion/", {"page": 2})).items[-1]
    assert table.page.total == 35 and len(table.rows) == 10
    ForgeLog.objects.bulk_create([ForgeLog(module_name=f"app{i:03}", level="info", message="trace") for i in range(110)])
    journal = journal_panel(host)(rf.get("/gestion/", {"module": "app109"}))
    assert journal.page.total == 1


def test_affect_personne_acces_aux_anciens_resumes_et_projets(client):
    from identity.models import Identity, IdentityHandle
    from memory.models import Entity, EmotionalSummary, EmotionSnapshot, Conversation
    from projects.models import Project
    entity = Entity.objects.create(name="Alex", entity_type="person")
    identity = Identity.objects.create(entity=entity)
    IdentityHandle.objects.create(identity=identity, person_id="test-alex", channel="web", trust="public")
    now = timezone.now()
    EmotionalSummary.objects.bulk_create([EmotionalSummary(person_id="test-alex", period_type="weekly", period_start=(now - timedelta(days=7*i)).date(), dominant_emotion="happy") for i in range(37)])
    Project.objects.bulk_create([Project(title=f"Mandat {i}", owner=entity) for i in range(14)])
    response = client.get(url("person-detail-tab", entity.pk, "affect"), {"resumes": 3})
    assert response.context["summaries_page"].total == 37 and len(response.context["summaries_page"].rows) == 7
    response = client.get(url("person-detail", entity.pk), {"p_projets": 2})
    assert len(response.context["projects_page"].rows) == 4
    conversation = Conversation.objects.create()
    EmotionSnapshot.objects.bulk_create([EmotionSnapshot(person_id="__global__", conversation=conversation, global_emotion="happy", primary_emotion="happy", primary_intensity=0.5) for _ in range(80)])
    response = client.get(url("inner-tab", "historique"), {"p_global": 4})
    assert response.context["global_page"].total == 80 and len(response.context["global_page"].rows) == 5


def test_commanditaire_recherche_sans_select_et_homonymes_explicites():
    from GestionSysteme.project_forms import ProjectForm
    from django.core.exceptions import ValidationError
    from memory.models import Entity
    alex = Entity.objects.create(name="Alex", entity_type="person")
    field = ProjectForm().fields["owner"]
    assert field.clean("Alex") == alex
    assert field.clean(f"#{alex.pk}") == alex
    assert "<select" not in str(ProjectForm()["owner"])
    Entity.objects.create(name="alex", entity_type="person")
    with pytest.raises(ValidationError, match="ambigu"):
        field.clean("Alex")
    assert field.clean(f"#{alex.pk}") == alex
    with pytest.raises(ValidationError):
        field.clean("#" + "9" * 110)


def test_texte_depliable_ne_cree_pas_de_lignes_vides_et_borne_le_contenu():
    from django.template.loader import render_to_string
    from html.parser import HTMLParser
    class Reader(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = ""
        def handle_data(self, data):
            self.text += data
    reader = Reader()
    reader.feed(render_to_string("gestion/partials/long_text.html", {"value": "Une étape\nsur deux lignes."}))
    assert reader.text == "Une étape\nsur deux lignes."
    html = render_to_string("gestion/partials/long_text.html", {"value": "x" * 150_000 + "FIN_CACHEE"})
    assert "tronqué" in html and "FIN_CACHEE" not in html


def test_camera_pagination_detail_et_duree_effective(rf, monkeypatch):
    import time
    from modules.manager import module_manager
    from modules.plugins.camera.panels import devices
    conf = SimpleNamespace(proactive_enabled=True, analysis_interval=30, idle_pause=300,
                           notify_enabled=False, notify_cooldown=60, device_stale_timeout=120)
    module = SimpleNamespace(is_running=True, _settings_sync=lambda: conf, _analysis_allowed=lambda c: True,
        _devices={str(i): SimpleNamespace(device_id=str(i), label=f"Caméra {i:02}", frame_ts=time.time(),
            last_analysis_ts=0, last_notify_ts=0, observation="Observation détaillée " * 30 + "FIN_OBSERVATION", notable_reason="Un mouvement") for i in range(32)})
    original = module_manager.get_registered
    monkeypatch.setattr(module_manager, "get_registered", lambda name: module if name == "camera" else original(name))
    table = next(block for block in devices(rf.get("/gestion/", {"page": 2})).items if block.block == "table")
    assert table.page.total == 32 and len(table.rows) == 7
    assert "2 min" in table.caption
    assert "FIN_OBSERVATION" in table.rows[0].detail.items[0].text
    assert "FIN_OBSERVATION" not in table.rows[0].cells[6].text


def test_journaux_reves_pages_independantes_et_sources(client):
    from conscience.models import Rumination
    from memory.models import DailyJournal, Dream, Souvenir
    today = timezone.localdate()
    sources = [Souvenir.objects.create(content=f"Source {i}", occurred_at=timezone.now()) for i in range(13)]
    journals = [DailyJournal.objects.create(date=today-timedelta(days=i), narrative=f"Journée {i}",
        key_moments=[s.pk for s in sources] + [999999, "invalide", "9" * 50]) for i in range(18)]
    thought = Rumination.objects.create(summary="Une pensée ouverte")
    dreams = [Dream.objects.create(night_of=today-timedelta(days=i), content=f"Rêve {i}",
        dream_type="pleasant", source_rumination=thought) for i in range(17)]
    dreams[0].source_souvenirs.add(*sources)
    response = client.get(url("memory-tab", "journaux"), {"p_journaux": 2, "p_reves": 2})
    assert len(response.context["journals_page"].rows) == 3
    assert len(response.context["dreams_page"].rows) == 2
    for kind, obj in [("journal", journals[0]), ("reve", dreams[0])]:
        back = url("memory-tab", "journaux") + "?p_journaux=2&p_reves=2"
        response = client.get(url("record-detail", kind, obj.pk), {"page": 2, "retour": back})
        assert response.status_code == 200
        blocks = response.context["main_blocks"]
        table = next(b for b in blocks if b.block == "table")
        assert table.page.total == 13 and len(table.rows) == 3
        assert all(row.href.startswith("/gestion/fiche/souvenir/") for row in table.rows)
        assert response.context["back_url"] == back
        html = response.content.decode()
        assert today.strftime("%d/%m/%Y") in html  # DateField, sans appel à timezone.is_aware.
        if kind == "journal":
            assert "1 souvenir(s) source ne sont plus conservés" in html
        else:
            assert url("record-detail", "rumination", thought.pk) in html
            assert "Agréable" in html


def test_engagements_attendus_avant_historique_et_echeances_nulles(client):
    from memory.models import Entity, Commitment
    person = Entity.objects.create(name="Alex", entity_type="person")
    old = Commitment.objects.create(person=person, description="Historique", status="dropped")
    later = Commitment.objects.create(person=person, description="Plus tard", due_at=timezone.now()+timedelta(days=3))
    undated = Commitment.objects.create(person=person, description="Sans échéance")
    first = Commitment.objects.create(person=person, description="Urgent", due_at=timezone.now()-timedelta(days=1))
    for destination in [url("social-tab", "engagements"), url("person-detail-tab", person.pk, "engagements")]:
        response = client.get(destination, {"statut": ""})
        assert [r.pk for r in response.context["page"].rows] == [first.pk, later.pk, undated.pk, old.pk]
        assert "Abandonné" in response.content.decode()


def test_identifiant_principal_visible_meme_avec_plus_de_25_handles(client):
    from identity.models import Identity, IdentityHandle
    identity = Identity.objects.create()
    primary = IdentityHandle.objects.create(identity=identity, person_id="primary", channel="web", trust="authenticated")
    IdentityHandle.objects.bulk_create([IdentityHandle(identity=identity, person_id=f"older-{i}", channel="telegram", trust="account") for i in range(32)])
    response = client.get(url("identity-detail-tab", identity.pk, "handles"))
    page = response.context["handles_page"]
    assert page.total == 33 and page.rows[0]["obj"] == primary
    assert page.rows[0]["is_primary"]


def test_humeurs_personne_paginees_et_synthese_bornee(client, monkeypatch):
    from GestionSysteme.views import social
    from identity.models import Identity, IdentityHandle
    from memory.models import Entity
    person = Entity.objects.create(name="Alex", entity_type="person")
    identity = Identity.objects.create(entity=person)
    IdentityHandle.objects.bulk_create([IdentityHandle(identity=identity, person_id=f"handle-{i}", channel="web") for i in range(32)])
    monkeypatch.setattr(social, "_live_affects", lambda ids: [{"person_id": p, "emotion": "happy", "intensity": .5} for p in ids])
    response = client.get(url("person-detail-tab", person.pk, "synthese"), {"p_humeurs": 2})
    assert response.context["affects_page"].total == 32
    assert len(response.context["affects_page"].rows) == 3
    verdict = response.context["verdicts_page"].rows[0]
    assert len(verdict["handles"]) == 3 and verdict["handle_count"] == 32
    response = client.get(url("person-detail-tab", person.pk, "affect"), {"p_humeurs": 3})
    assert len(response.context["affects_page"].rows) == 8


def test_messages_sociaux_exposent_pieces_jointes_et_conversation(client):
    from identity.models import Identity, IdentityHandle
    from memory.models import Entity, Message, Conversation
    person = Entity.objects.create(name="Alex", entity_type="person")
    identity = Identity.objects.create(entity=person)
    IdentityHandle.objects.create(identity=identity, person_id="alex-web", channel="web")
    conversation = Conversation.objects.create()
    message = Message.objects.create(conversation=conversation, person_id="alex-web", role="user", content="Une image", attachments_meta=[{"name": "image.png"}])
    for destination in [url("person-detail-tab", person.pk, "echanges"), url("identity-detail-tab", identity.pk, "echanges")]:
        response = client.get(destination)
        html = response.content.decode()
        assert "1 pièce(s) jointe(s)" in html
        assert f"?conversation={conversation.pk}" in html
        assert url("record-detail", "message", message.pk) in html


@pytest.mark.parametrize("plugin,param", [("email", "message"), ("rss", "article")])
@pytest.mark.parametrize("value", ["9" * 150, "²", "0", "-1", "9223372036854775808"])
def test_identifiants_de_fiche_plugin_invalides_sont_signales(rf, plugin, param, value):
    from modules.plugins.email.panels import _fiche_message
    from modules.plugins.rss.panels import _fiche_article
    handler = _fiche_message if plugin == "email" else _fiche_article
    blocks = handler(rf.get("/gestion/", {param: value}))
    assert len(blocks) == 1 and blocks[0].tone == "warn"
    assert "invalide" in blocks[0].text


def test_camera_arretee_ne_pretend_pas_analyser(rf, monkeypatch):
    from modules.plugins.camera.panels import _boucle
    conf = SimpleNamespace(proactive_enabled=True, analysis_interval=30, idle_pause=300,
                           notify_enabled=False, notify_cooldown=60)
    def should_not_run(conf):
        pytest.fail("La caméra arrêtée n'exécute pas son contrôle d'activité")
    block = _boucle(SimpleNamespace(is_running=False, _analysis_allowed=should_not_run), conf)
    assert block.items[0].value == "module arrêté"


def test_pulsions_decrivent_la_courbe_reelle(client):
    from drives.state import params_for, DriveKind
    response = client.get(url("inner-tab", "drives"))
    for row in response.context["drives"]:
        params = params_for(DriveKind(row["kind"]))
        assert row["growth_horizon"] == params.growth_horizon
        assert row["growth_tau"] == params.growth_tau
    html = response.content.decode()
    assert "Montée progressive" in html and "Horizon" in html
    assert "survit pas à un redémarrage" not in html
