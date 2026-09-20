"""Contrat de gestion v2 : rendu réel, données complètes et frontières d'action."""
import json

import pytest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from GestionSysteme import panels as P
from GestionSysteme.panel_payload import decode, safe_href
from GestionSysteme.panel_forms import Input, InvalidAction


def document(*blocks):
    return {"version": 2, "blocks": list(blocks)}


def render(block, **context):
    return render_to_string("gestion/partials/block.html", {"block": block, **context})


def test_composition_recursive_et_details_ne_perdent_pas_les_types():
    block = decode(document({"type": "grid", "columns": 2, "items": [
        {"type": "stats", "items": [{"label": "Total", "value": 0}]},
        {"type": "disclosure", "title": "Contexte", "items": [
            {"type": "fields", "items": [{"label": "Avancement", "value": {"kind": "meter", "ratio": .4, "text": "40 %"}}]},
            {"type": "timeline", "items": [{"title": "Premier passage", "text": "Un compte rendu complet"}]},
            {"type": "code", "text": '<script>alert("x")</script>'},
        ]},
    ]}))
    html = render(block)
    assert "panel-grid-2" in html and 'width: 40.0%' in html
    assert "Premier passage" in html and '<details' in html
    assert "&lt;script&gt;" in html and '<script>' not in html


@pytest.mark.parametrize("payload", [
    {"columns": [], "rows": []}, {"tabs": []}, {"version": 1, "blocks": []},
    document({"type": "template", "name": "gestion/base.html"}),
    document({"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": [{"cells": [1, 2]}]}),
    document({"type": "grid", "items": "incorrect"}),
    document({"type": "stats", "items": [{"label": "Total", "values": 12}]}),
    document({"type": "timeline", "items": [{"title": "Passage", "html": "<b>Texte</b>"}]}),
])
def test_contrat_invalide_affiche_une_erreur(payload):
    block = decode(payload)
    assert isinstance(block, P.Note) and block.tone == "danger"


def test_profondeur_et_nombre_de_lignes_bornes():
    block = {"type": "prose", "text": "x"}
    for _ in range(10):
        block = {"type": "section", "items": [block]}
    assert isinstance(decode(document(block)), P.Note)
    assert isinstance(decode(document({"type": "table", "columns": [{"key": "x", "label": "X"}], "rows": [{"cells": [1]}] * 201})), P.Note)


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/html,x", "//evil.test", "/\\evil.test", "java\nscript:alert(1)"])
def test_aucun_lien_executable_meme_dans_un_panneau_natif(href):
    assert not safe_href(href)
    html = render(P.Fields([P.Field("Lien", "Visible", kind="link", href=href)]))
    assert 'href=' not in html and "Visible" in html


def test_un_lien_de_cellule_dans_une_ligne_ne_produit_pas_de_lien_imbrique():
    html = render(P.Table([P.Column("Lien")], [P.Row((P.link("Lire", "https://example.org"),), href="/gestion/")]))
    assert html.count('<a ') == 1


def test_pagination_unique_a_partir_de_un_et_filtres_independants(rf):
    block = decode(document({"type": "table", "columns": [{"key": "sujet", "label": "Sujet"}], "rows": [{"cells": ["Suite"]}],
        "pagination": {"total": 3, "page": 2, "per_page": 2, "param": "p_notes"},
        "filters": [{"kind": "search", "key": "q_notes", "label": "Chercher"}],
    }), request=rf.get('/gestion/', {"q_notes": "abc", "p_notes": 2, "p_logs": 4})).items[0]
    assert block.page.number == 2 and block.page.start_index == 3
    assert block.filters.filters[0].value == "abc"
    assert block.filters.hidden == [("p_logs", "4")]
    assert block.filters.reset_url == '/gestion/?p_logs=4'


def test_formulaire_valide_avant_appel_et_ne_transmet_que_les_champs_declares(rf):
    called = []
    def handler(request):
        called.append(request.panel_data)
    panel = P.ModulePanel("test", "Test", actions=(P.PanelAction("save", "Sauver", handler, fields=(
        Input("nombre", type="integer", minimum=1, maximum=5),
        Input("choix", type="select", choices=(("a", "A"),)),
    )),))
    with pytest.raises(InvalidAction):
        P.run_action(rf.post('/x', {"nombre": 7, "choix": "inconnu"}), "test", panel, "save")
    assert called == []
    P.run_action(rf.post('/x', {"nombre": 2, "choix": "a", "secret": "x"}), "test", panel, "save")
    assert called == [{"nombre": 2, "choix": "a"}]


def test_texte_long_integral_reste_disponible_sans_javascript():
    text = "Une très longue pensée. " * 30 + "DERNIER MOT"
    html = render(P.Table([P.Column("Texte")], [P.Row((P.text(text, clamp=True),))]))
    assert 'DERNIER MOT' in html and '<details' in html


def test_definition_action_manifest_validee():
    from modules.plugins.forge.store import validate_manifest
    _, errors = validate_manifest({"title": "Test", "views": [{"key": "stats", "actions": [
        {"key": "save", "fields": [{"key": "x", "type": "exec"}]},
    ]}]}, "demo_test")
    assert errors


@pytest.mark.parametrize("view", [
    {"key": "stats", "id_field": "id"},
    {"key": "stats", "actions": [{"key": "save", "fields": [{"key": "titre", "widget": "html"}]}]},
])
def test_manifest_refuse_les_options_obsoletes_ou_inconnues(view):
    from modules.plugins.forge.store import validate_manifest
    manifest, errors = validate_manifest({"title": "Test", "views": [view]}, "demo_test")
    assert manifest is None and errors


@pytest.mark.parametrize("params", ["p_logs", ["p_logs", "p_logs"], ["per_page"], ["page"], ["../x"], [["p_logs"]]])
def test_manifest_refuse_les_parametres_de_page_invalides(params):
    from modules.plugins.forge.store import validate_manifest
    manifest, errors = validate_manifest({"title": "Test", "views": [{"key": "stats", "page_params": params}]}, "demo_test")
    assert manifest is None and errors


@pytest.mark.django_db
def test_fiches_et_sources_ne_perdent_ni_contenu_ni_zero(client):
    from memory.models import Conversation, Message, Souvenir, Connaissance
    from conscience.models import ConscienceLog, Observation, Rumination, Travail, ScheduledAction
    from projects.models import Project, ProjectLog
    conversation = Conversation.objects.create()
    message = Message.objects.create(conversation=conversation, role="user", content="Début " * 100 + "FIN_COMPLETE", attachments_meta=[{"name": "notes.pdf"}])
    souvenir = Souvenir.objects.create(content="Souvenir", occurred_at=timezone.now(), conversation=conversation)
    knowledge = Connaissance.objects.create(content="Un fait", source_souvenir=souvenir)
    decision = ConscienceLog.objects.create(decision="wait", score=0, energie=0, texte="Paroles intégrales", outils="outil : résultat", acts_today=0)
    observation = Observation.objects.create(source="test", event_type="test.event", raw_data={"preuve": "visible"}, souvenir=souvenir)
    rumination = Rumination.objects.create(summary="Une pensée", observation=observation)
    work = Travail.objects.create(titre="Un travail", origine="pulsion")
    scheduled = ScheduledAction.objects.create(prompt="Un rappel", scheduled_at=timezone.now(), source="test")
    project = Project.objects.create(title="Projet")
    log = ProjectLog.objects.create(project=project, action="run", summary="Résultat")
    for kind, obj, visible in [("message", message, "FIN_COMPLETE"), ("souvenir", souvenir, "Conversation source"),
                              ("connaissance", knowledge, "Souvenir source"), ("decision", decision, "Paroles intégrales"),
                              ("observation", observation, "visible"), ("rumination", rumination, "Observation source"),
                              ("chantier", work, "Un travail"), ("planification", scheduled, "Un rappel"), ("execution", log, "Résultat")]:
        response = client.get(reverse("gestionsysteme:record-detail", args=[kind, obj.pk]))
        assert response.status_code == 200
        assert visible in response.content.decode()
    response = client.get(reverse("gestionsysteme:memory-tab", args=["messages"]), {"conversation": conversation.pk})
    assert "FIN_COMPLETE" in response.content.decode()
    assert "notes.pdf" in client.get(reverse("gestionsysteme:record-detail", args=["message", message.pk])).content.decode()
    assert client.get(reverse("gestionsysteme:record-detail", args=["secret", 1])).status_code == 404
    assert client.get(reverse("gestionsysteme:record-detail", args=["souvenir", 99999])).status_code == 404


@pytest.mark.django_db
def test_version_courante_du_recit_independante_de_la_page(client):
    from memory.models import SelfNarrative
    for i in range(13):
        SelfNarrative.objects.create(content=f"Version {i}")
    response = client.get(reverse("gestionsysteme:memory-tab", args=["recit"]), {"page": 2})
    assert response.context["current"].content == "Version 12"
    assert len(response.context["page"].rows) == 2


@pytest.mark.django_db
def test_nouvelles_routes_suivent_le_portail_operateur(client, settings):
    settings.DASHBOARD_REQUIRE_AUTH = True
    assert client.get(reverse("gestionsysteme:record-detail", args=["message", 1])).status_code == 302
    assert client.get(reverse("gestionsysteme:api-panel-schema")).status_code == 401


@pytest.mark.django_db
def test_schema_est_consultable(client):
    result = client.get(reverse("gestionsysteme:api-panel-schema"))
    assert result.status_code == 200
    assert result.json()["properties"]["version"] == {"const": 2}


@pytest.mark.parametrize('page,size,total,rows', [(0, 25, 1, 1), (1, -1, 1, 1), (1, 25, 3, 0), (3, 2, 3, 1)])
def test_une_pagination_incoherente_ne_pretend_pas_montrer_des_lignes(page, size, total, rows):
    block = decode(document({"type": "table", "columns": [{"key": "x", "label": "X"}],
        "rows": [{"cells": [1]}] * rows,
        "pagination": {"page": page, "per_page": size, "total": total},
    }))
    assert isinstance(block, P.Note) and block.tone == "danger"


def test_formulaire_dans_un_detail_reste_affichable_et_echappe(rf):
    from django.template import RequestContext, Template
    initial = {'id': 'abc', 'titre': '<img src=x onerror=alert(1)>'}
    form = P.ActionForm('edit', initial, 'Modifier')
    block = P.Table([P.Column('Titre')], [P.Row((P.text('Un titre'),), detail=form)])
    panel = P.ModulePanel('liste', 'Liste', actions=(P.PanelAction('edit', 'Enregistrer', lambda r: None,
        fields=(Input('id', type='hidden'), Input('titre'))),))
    request = rf.get('/gestion/modules/test/p/liste/')
    html = Template('{% include "gestion/partials/block.html" %}').render(RequestContext(request, {
        'block': block, 'panel': panel, 'module_name': 'test',
    }))
    assert 'name="id" value="abc"' in html
    assert '&lt;img' in html and '<img src=x' not in html
    assert 'csrfmiddlewaretoken' in html
    assert P.header_actions(panel, block) == []


@pytest.mark.django_db
def test_collection_forge_inspectable_sans_melanger_les_apps(rf):
    from modules.plugins.forge.models import ForgeRecord
    from modules.plugins.forge.panels import stockage_panel
    ForgeRecord.objects.create(module_name='demo_app', collection='notes', key='cle', value={'texte': 'VALEUR_VISIBLE'})
    ForgeRecord.objects.create(module_name='autre_app', collection='notes', key='cle', value={'texte': 'AUTRE_APP'})
    block = stockage_panel(None)(rf.get('/gestion/modules/forge/p/stockage/', {'module':'demo_app', 'collection':'notes'}))
    html = render(block)
    assert 'VALEUR_VISIBLE' in html and 'AUTRE_APP' not in html


def test_erreur_de_formulaire_ouvre_les_details_parents_sans_js(rf):
    from django.template import RequestContext, Template
    from GestionSysteme.panel_forms import action_instance, build_form
    initial = {"id": "42"}
    action = P.PanelAction('edit', 'Enregistrer', lambda r: None, fields=(Input('id', type='hidden'), Input('titre')))
    panel = P.ModulePanel('liste', 'Liste', actions=(action,))
    request = rf.post('/gestion/modules/test/p/liste/action/edit/', {'_panel_instance': action_instance('edit', initial), 'id':'42', 'titre':''})
    error = InvalidAction('edit', build_form(action, data=request.POST))
    block = P.Table([P.Column('Nom')], [P.Row((P.text('Une fiche'),), detail=P.Disclosure('Édition', [P.ActionForm('edit', initial)]))])
    html = Template('{% include "gestion/partials/block.html" %}').render(RequestContext(request, {
        'block':block, 'panel':panel, 'module_name':'test', 'action_error':error,
    }))
    assert '<details class="row-detail" open>' in html
    assert '<details class="card panel-disclosure mb-4" open>' in html
    assert 'class="errorlist"' in html


@pytest.mark.parametrize("kind,marker", [("badge", 'class="badge '), ("emotion", 'class="emo"'), ("mono", 'class="mono ')])
def test_premiere_cellule_cliquable_conserve_son_type_et_son_titre(kind, marker):
    import re
    cell = P.Cell("Lisible", kind=kind, title='Détail "précis"', emotion="happy")
    html = render(P.Table([P.Column("Valeur")], [P.Row((cell,), href="/gestion/")]))
    link = re.search(r'<a\b[^>]*>.*?</a>', html, re.S).group(0)
    assert marker in link and 'title="Détail &quot;précis&quot;"' in link
    assert "Lisible" in link


@pytest.mark.parametrize("length", [20, 400])
def test_cellule_repliee_garde_titre_et_navigation_sans_details_dans_le_lien(length):
    import re
    html = render(P.Table([P.Column("Texte")], [P.Row((
        P.text("X" * length, title="Contexte exact", clamp=True),), href="/gestion/")]))
    assert 'title="Contexte exact"' in html
    assert 'href="/gestion/"' in html
    for link in re.findall(r'<a\b[^>]*>.*?</a>', html, re.S):
        assert "<details" not in link and "<summary" not in link
    if length > 180:
        assert '<details class="read-more" title="Contexte exact">' in html


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["body_text", "body_html"])
def test_mail_volumineux_affiche_un_extrait_annonce_sans_modifier_la_source(rf, field):
    from modules.plugins.email.models import Email, EmailAccount
    from modules.plugins.email.panels import _fiche_message, MAX_CORPS
    source = "DÉBUT" + "x" * 2_000_000 + "FIN_HORS_PLAFOND"
    account = EmailAccount.objects.create(name="Test", email_address="test@example.org")
    mail = Email.objects.create(account=account, message_id="volumineux", **{field: source})
    block = P.Blocks(_fiche_message(rf.get('/gestion/modules/email/p/reception/', {"message": mail.pk})))
    html = render(block)
    assert "DÉBUT" in html and "FIN_HORS_PLAFOND" not in html
    assert "Affichage tronqué" in html and len(html) < MAX_CORPS + 10_000
    if field == "body_html":
        assert "Source HTML tronquée" in html
    mail.refresh_from_db()
    assert getattr(mail, field) == source


@pytest.mark.django_db
def test_resume_rss_volumineux_est_borne_et_signale(rf):
    from modules.plugins.rss.models import RSSFeed, RSSEntry
    from modules.plugins.rss.panels import _fiche_article, RESUME_MAX
    feed = RSSFeed.objects.create(name="Test", url="https://example.org/feed")
    article = RSSEntry.objects.create(feed=feed, entry_hash="test", title="Article",
        summary="x" * (RESUME_MAX + 100) + "FIN_HORS_PLAFOND")
    html = render(P.Blocks(_fiche_article(rf.get('/x', {"article": article.pk}))))
    assert "Affichage tronqué" in html and "FIN_HORS_PLAFOND" not in html
    assert len(html) < RESUME_MAX + 10_000


def test_sources_forgees_volumineuses_sont_bornees_et_signalees(monkeypatch):
    from modules.plugins.forge import store
    from modules.plugins.forge.panels import _source, MAX_SOURCE_DISPLAY
    source = "x" * (MAX_SOURCE_DISPLAY + 100) + "FIN_HORS_PLAFOND"
    monkeypatch.setattr(store, "read_module", lambda name: {"manifest_raw": {"texte": source}, "code": source})
    for text in _source("test"):
        assert "Affichage tronqué" in text and "FIN_HORS_PLAFOND" not in text
        assert len(text) < MAX_SOURCE_DISPLAY + 100


@pytest.mark.parametrize("result,error,tone", [({"message": "x" * 1000}, "", "ok"),
    ({"ok": False, "message": "x" * 1000}, "", "danger"), ("x" * 1000, "", "ok"), (None, "x" * 1000, "danger")])
async def test_notifications_forgees_bornees_avant_stockage(result, error, tone, rf):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from modules.plugins.forge.panels import _action_handler
    host = SimpleNamespace(_loaded={"test": SimpleNamespace(handlers={"action_vue_save"})},
                           _run_handler=AsyncMock(return_value=(not error, result, error)))
    request = rf.post('/x')
    request.panel_data = {}
    note = await _action_handler(host, "test", "vue", "save")(request)
    assert note.text == "x" * 500 and note.tone == tone


@pytest.mark.parametrize("json_spec", [True, False])
def test_case_action_facultative_par_defaut_et_consentement_explicite(json_spec):
    from GestionSysteme.panel_forms import input_from_spec, build_form
    factory = (lambda **kw: input_from_spec(kw)) if json_spec else Input
    fields = (factory(key="actif", type="boolean"), factory(key="titre"))
    form = build_form(P.PanelAction("save", "Sauver", lambda r: None, fields=fields), data={"titre": "Nom"})
    assert form.is_valid() and form.cleaned_data == {"actif": False, "titre": "Nom"}
    required = factory(key="accord", type="boolean", required=True)
    form = build_form(P.PanelAction("save", "Sauver", lambda r: None, fields=(required,)), data={})
    assert not form.is_valid() and "accord" in form.errors


def test_filtres_preservent_toutes_les_valeurs_des_parametres_exterieurs(rf):
    from urllib.parse import parse_qs, urlsplit
    request = rf.get('/gestion/test/?tag=alpha&tag=beta&q=mot&page=2')
    block = decode(document({"type": "table", "columns": [], "rows": [],
        "filters": [{"key": "q", "label": "Recherche", "kind": "search"}]}), request=request).items[0]
    html = render(block, request=request)
    assert 'name="tag" value="alpha"' in html and 'name="tag" value="beta"' in html
    assert parse_qs(urlsplit(block.filters.reset_url).query) == {"tag": ["alpha", "beta"]}


@pytest.mark.django_db
@pytest.mark.parametrize("candidate,allowed", [("/gestion/memoire/souvenirs/?q=mot&page=2", True),
    ("https://evil.test/gestion/", False), ("//evil.test/gestion/", False),
    ("/\\evil.test/gestion/", False), ("/admin/", False)])
def test_fiche_utilise_le_retour_local_valide(client, candidate, allowed):
    from memory.models import Souvenir
    souvenir = Souvenir.objects.create(content="Souvenir", occurred_at=timezone.now())
    response = client.get(reverse("gestionsysteme:record-detail", args=["souvenir", souvenir.pk]), {"retour": candidate})
    assert response.status_code == 200
    expected = candidate if allowed else reverse("gestionsysteme:memory-tab", args=["souvenirs"])
    assert response.context["back_url"] == expected


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["souvenirs", "connaissances"])
def test_filtre_entite_recherche_en_base_sans_select_exhaustif(client, tab):
    from memory.models import Entity, Souvenir, Connaissance
    Entity.objects.bulk_create([Entity(name=f"Entité {i}", entity_type="other") for i in range(250)])
    entity = Entity.objects.create(name="Cible unique", entity_type="other")
    record = (Souvenir.objects.create(content="Lié", occurred_at=timezone.now()) if tab == "souvenirs"
              else Connaissance.objects.create(content="Lié"))
    record.entities.add(entity)
    url = reverse("gestionsysteme:memory-tab", args=[tab])
    for value in ("Cible", str(entity.pk), f"#{entity.pk}"):
        response = client.get(url, {"entite": value})
        assert response.context["page"].total == 1
        assert '<select id="filtre-entite"' not in response.content.decode()
        assert "Entité 249" not in response.content.decode()
    assert client.get(url, {"entite": "#" + "9" * 60}).context["page"].total == 0
