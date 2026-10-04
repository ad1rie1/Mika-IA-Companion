"""Choisir, agir et comprendre un écran vide — au-delà du seul rendu HTTP."""
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def url(name, *args):
    return reverse(f"gestionsysteme:{name}", args=args)


def project_data(owner):
    return dict(title="Veille", origin="user", status="active", priority="normal",
                emotion_policy="off", monthly_token_budget="0", owner=owner)


@pytest.mark.parametrize("by_id", [False, True])
def test_commanditaire_refuse_un_lieu_dans_le_champ_et_le_formulaire(by_id):
    from old.backend.GestionSysteme.project_forms import ProjectForm
    from old.backend.memory.models import Entity
    place = Entity.objects.create(name="Paris", entity_type="place")
    value = f"#{place.pk}" if by_id else place.name
    form = ProjectForm(project_data(value))
    with pytest.raises(ValidationError):
        form.fields["owner"].clean(value)
    assert not form.is_valid() and "owner" in form.errors


def test_commanditaire_lisible_en_edition_et_suggestion_non_ambigue():
    from old.backend.GestionSysteme.project_forms import ProjectForm
    from old.backend.memory.models import Entity
    from old.backend.projects.models import Project
    person = Entity.objects.create(name="Alex", entity_type="person")
    Entity.objects.create(name="Alex", entity_type="place")
    form = ProjectForm(project_data("alex"))
    assert form.is_valid(), form.errors
    project = form.save()
    assert project.owner == person
    label = ProjectForm(instance=project)["owner"].value()
    assert label == f"Alex (#{person.pk})"
    Entity.objects.create(name="alex", entity_type="person")
    edited = ProjectForm(project_data(label), instance=project)
    assert edited.is_valid(), edited.errors
    assert edited.save().owner == person
    assert Project.objects.count() == 1


def test_suggestions_personnes_excluent_les_autres_entites(client):
    from old.backend.memory.models import Entity
    person = Entity.objects.create(name="Alex", entity_type="person")
    Entity.objects.create(name="Alex", entity_type="place")
    response = client.get(url("api-suggestions", "personnes"), {"q": "al"})
    assert response.json() == {"results": [{"value": f"Alex (#{person.pk})", "label": f"Alex (#{person.pk})"}], "more": False}
    assert "no-store" in response.headers["Cache-Control"]
    assert client.get(url("api-suggestions", "personnes"), {"q": "#" + "9" * 100}).json()["results"] == []


def test_suggestions_bornees_mais_recherche_au_dela_des_premieres(client):
    from old.backend.memory.models import Theme
    Theme.objects.bulk_create([Theme(name=f"Sujet {i:03}") for i in range(230)])
    first = client.get(url("api-suggestions", "themes")).json()
    assert len(first["results"]) == 20 and first["more"]
    found = client.get(url("api-suggestions", "themes"), {"q": "229"}).json()
    assert found == {"results": [{"value": "Sujet 229", "label": "Sujet 229"}], "more": False}


@pytest.mark.parametrize("tab", ["souvenirs", "connaissances"])
def test_theme_suggere_filtre_sans_sensibilite_a_la_casse(client, tab):
    from old.backend.memory.models import Theme, Souvenir, Connaissance
    theme = Theme.objects.create(name="Prototypage")
    item = (Souvenir.objects.create(content="Une idée", occurred_at=timezone.now()) if tab == "souvenirs"
            else Connaissance.objects.create(content="Un fait"))
    item.themes.add(theme)
    response = client.get(url("memory-tab", tab), {"theme": "pRoToTyPaGe"})
    assert response.context["page"].rows == [item]
    assert 'data-suggestions="' + url("api-suggestions", "themes") in response.content.decode()


def test_suggestions_handles_par_nom_et_apres_disparition_des_instantanes(client):
    from old.backend.memory.models import Entity, Conversation, EmotionSnapshot, EmotionalSummary
    from old.backend.identity.models import Identity, IdentityHandle
    identity = Identity.objects.create(entity=Entity.objects.create(name="Alex", entity_type="person"))
    IdentityHandle.objects.create(identity=identity, channel="telegram", person_id="tg_123")
    conversation = Conversation.objects.create()
    EmotionSnapshot.objects.create(conversation=conversation, person_id="tg_123", primary_emotion="happy", primary_intensity=.5)
    for handle in ("tg_123", "ancien_handle", "__global__"):
        EmotionalSummary.objects.create(person_id=handle, period_type="weekly", period_start=timezone.localdate(), dominant_emotion="happy")
    found = client.get(url("api-suggestions", "handles"), {"q": "Alex"}).json()["results"]
    assert found == [{"value": "tg_123", "label": "Alex · tg_123"}]
    EmotionSnapshot.objects.all().delete()
    values = [r["value"] for r in client.get(url("api-suggestions", "handles")).json()["results"]]
    assert values == ["ancien_handle", "tg_123"]


def test_suggestions_forge_et_filtre_insensible_a_la_casse(client, rf):
    from old.backend.modules.plugins.forge.models import ForgeLog
    from old.backend.modules.plugins.forge.panels import journal_panel
    ForgeLog.objects.bulk_create([ForgeLog(module_name=f"app_{i:03}", message="Passage") for i in range(110)])
    found = client.get(url("api-suggestions", "forge-modules"), {"q": "109"}).json()
    assert found["results"] == [{"value": "app_109", "label": "app_109"}]
    panel = journal_panel(None)(rf.get("/gestion/", {"module": "APP_109"}))
    assert panel.page.total == 1


def test_suggestions_sources_fermees_et_authentification(client, settings, django_user_model):
    endpoint = url("api-suggestions", "themes")
    settings.DASHBOARD_REQUIRE_AUTH = True
    assert client.get(endpoint).status_code == 401
    user = django_user_model.objects.create(username="lecteur")
    client.force_login(user)
    assert client.get(endpoint).status_code == 401
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    assert client.get(endpoint).status_code == 200
    assert client.post(endpoint).status_code == 405
    assert client.get(url("api-suggestions", "users")).status_code == 404


def test_categories_sont_une_liste_fermee_complete(client):
    from old.backend.conscience.models import Observation
    Observation.objects.create(source="test", category="external", summary="Article")
    response = client.get(url("conscience-tab", "observations"), {"categorie": "categorie-inconnue"})
    category = next(f for f in response.context["filterset"].filters if f.param == "categorie")
    assert category.kind == "select" and category.value == ""
    assert {c.value for c in category.choices} == {"", *Observation.Category.values}
    assert response.context["page"].total == 1


def test_description_et_changement_etat_de_tache_accessibles_sans_deplier(client):
    from old.backend.projects.models import Project, ProjectTask
    from old.backend.GestionSysteme.project_forms import TASK_STATUSES
    project = Project.objects.create(title="Veille", description="Le mandat qui identifie ce projet")
    task = ProjectTask.objects.create(project=project, description="Comparer les pistes")
    html = client.get(url("project-detail", project.pk)).content.decode()
    assert html.index(project.description) < html.index("Avancement")

    class Controls(HTMLParser):
        depth = 0
        actions = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "details":
                self.depth += 1
            if tag == "button" and attributes.get("name") == "status":
                self.actions.append((attributes["value"], self.depth))

        def handle_endtag(self, tag):
            if tag == "details":
                self.depth -= 1

    parser = Controls()
    parser.feed(html)
    assert set(parser.actions) == {(value, 0) for value in ProjectTask.Status.values if value != task.status}
    assert [value for value, label in TASK_STATUSES] == list(ProjectTask.Status.values)
    back = url("project-detail", project.pk) + "?p_journal=2"
    response = client.post(url("task-update", project.pk, task.pk), {"action": "etat", "status": "done", "retour": back})
    assert response.url == back
    task.refresh_from_db()
    assert task.status == ProjectTask.Status.DONE


@pytest.mark.parametrize("name,tab,plain,filtered", [
    ("projects-tab", "attente", "Aucune action ne demande ton accord", "Aucune action pour cette sélection"),
    ("conscience-tab", "planification", "Rien de prévu", "Aucune intention pour ces filtres"),
    ("memory-tab", "souvenirs", "Aucun souvenir enregistré", "Aucun souvenir ne correspond"),
])
def test_etats_vides_distinguent_attente_normale_et_recherche(client, name, tab, plain, filtered):
    assert plain in client.get(url(name, tab)).content.decode()
    params = {"statut": "failed"} if tab == "attente" else {"q": "introuvable"}
    assert filtered in client.get(url(name, tab), params).content.decode()


def test_agenda_affiche_le_delai_effectif_et_la_date_initiale(client, monkeypatch):
    from old.backend.conscience.models import ScheduledAction
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    ScheduledAction.objects.create(prompt="Reprendre", scheduled_at=now - timedelta(days=1), reessayer_le=now + timedelta(hours=2))
    html = client.get(url("conscience-tab", "planification")).content.decode()
    assert "dans 2 h" in html and "échéance initiale" in html and "schedule_action" in html


def test_sante_conserve_ordre_du_bus_et_tous_les_incidents(client, monkeypatch):
    from old.backend.utils.eventbus import event_bus
    subscriptions = [{"name": "Z prioritaire", "pattern": "*", "priority": 0, "failed": 1, "delivered": 0}] + [
        {"name": f"A suivant {i:02}", "pattern": "*", "priority": i + 1, "failed": 1, "delivered": 0} for i in range(30)]
    monkeypatch.setattr(event_bus, "stats", lambda: {"emitted": 31, "subscriptions": subscriptions})
    response = client.get(url("system-tab", "sante"))
    assert response.context["subscriptions_page"].rows[0]["name"] == "Z prioritaire"
    assert len(response.context["failing_subscriptions"]) == 31
    assert "p_erreurs" not in response.content.decode()
