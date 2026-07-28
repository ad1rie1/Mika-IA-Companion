"""Tests de GestionSystème — l'interface d'administration rendue par le serveur.

Ce que ces tests protègent en priorité, par ordre de coût d'une régression :

1. **Chaque page répond.** L'ancienne interface n'avait aucun test côté client :
   4 284 lignes de JavaScript sans build, sans typage et sans suite. Une page
   cassée ne se voyait qu'en l'ouvrant. Ici un gabarit mal formé fait rougir la
   suite — c'est le filet qui manquait.
2. **Aucun module ne peut injecter de balisage.** C'était une vulnérabilité
   réelle (XSS stocké sur la page qui édite les clés d'API), rattrapée par une
   couche d'assainissement. Les cellules typées la suppriment ; ces tests
   vérifient qu'elle ne peut pas revenir.
3. **Aucun secret ne descend au navigateur.** Une page de configuration doit
   pouvoir s'afficher sans exposer une clé.
4. **Aucune valeur d'URL n'atteint l'ORM sans passer par une liste fermée.**
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from asgiref.sync import sync_to_async
from django.test import Client
from django.urls import reverse

from GestionSysteme import forms, panels, tables
from GestionSysteme.formatting import emotion_var
from GestionSysteme.nav import IDENTITY_TABS, NAV, PERSON_TABS, item_for


# ── Couverture des routes ───────────────────────────────────────────────

def _all_pages() -> list[tuple[str, list]]:
    """Toutes les destinations et tous leurs onglets, dérivés de la nav.

    Dérivé plutôt que recopié : un onglet ajouté à ``nav.py`` sans gabarit
    correspondant fait échouer ce test au lieu de produire une 500 découverte
    en production.
    """
    out: list[tuple[str, list]] = []
    for group in NAV:
        for item in group.items:
            out.append((f"gestionsysteme:{item.url_name}", []))
            for tab in item.tabs:
                out.append((f"gestionsysteme:{item.url_name}-tab", [tab.key]))
    return out


@pytest.mark.django_db
@pytest.mark.parametrize("route,args", _all_pages())
def test_chaque_page_repond(client, route, args):
    response = client.get(reverse(route, args=args), follow=True)
    assert response.status_code == 200, f"{route} {args}"


@pytest.mark.django_db
def test_toutes_les_sections_de_configuration_repondent(client):
    from GestionSysteme.views import config as config_view

    sections = config_view.core_sections()
    assert sections, "le registre doit exposer au moins une section"
    for section in sections:
        url = reverse("gestionsysteme:config-section", args=[section.key])
        assert client.get(url).status_code == 200, section.key


@pytest.mark.django_db
def test_formulaire_de_creation_de_chaque_liste_repond(client):
    from configs.registry import registry
    from GestionSysteme.views import config as config_view

    seen = 0
    for section in config_view.core_sections():
        for item in registry.all_items():
            if item.section != section.key or item.type != "record_list":
                continue
            seen += 1
            url = reverse(
                "gestionsysteme:config-record-new", args=[section.key, item.key],
            )
            assert client.get(url).status_code == 200, item.key
    assert seen, "aucune liste d'enregistrements trouvée — le test serait vide"


@pytest.mark.django_db
def test_le_point_json_des_vitaux_repond(client):
    response = client.get(reverse("gestionsysteme:api-vitals"))
    assert response.status_code == 200
    assert set(response.json()) >= {"status", "phase", "energy", "mood", "sleep"}


# ── Navigation ──────────────────────────────────────────────────────────

def test_un_onglet_inconnu_retombe_sur_le_premier():
    """Une URL périmée doit ouvrir la page, pas casser un favori."""
    item = item_for("memory")
    assert item.tab("nexistepas").key == item.tabs[0].key
    assert item.tab(None).key == item.tabs[0].key
    assert item.tab("souvenirs").key == "souvenirs"


def test_la_navigation_reste_courte():
    """Garde-fou contre le retour du menu-miroir-de-la-base.

    L'ancienne interface alignait 23 entrées de premier niveau. Le regroupement
    par onglets est la correction ; ce test la rend difficile à défaire par
    inadvertance.
    """
    destinations = sum(len(group.items) for group in NAV)
    assert destinations <= 12, f"{destinations} entrées de menu"


# ── Pagination ──────────────────────────────────────────────────────────

def test_ellipse_de_pagination():
    from GestionSysteme.tables import _elided_range

    assert _elided_range(1, 1) == []
    assert _elided_range(1, 3) == [1, 2, 3]
    # Première et dernière toujours présentes, ellipse au milieu.
    links = _elided_range(10, 40)
    assert links[0] == 1 and links[-1] == 40
    assert None in links
    assert 10 in links


@pytest.mark.django_db
def test_une_page_hors_bornes_retombe_sur_la_derniere(rf):
    """Un favori pointant « page 12 » après suppression de lignes doit
    afficher quelque chose d'utile plutôt qu'une 404."""
    request = rf.get("/x/", {"page": "999"})
    result = tables.paginate(request, list(range(30)), per_page=10)
    assert result.number == 3
    assert result.rows == list(range(20, 30))


@pytest.mark.django_db
def test_un_numero_de_page_absurde_ne_leve_pas(rf):
    request = rf.get("/x/", {"page": "abc"})
    assert tables.paginate(request, list(range(5)), per_page=10).number == 1


def test_deux_paginations_independantes_sur_un_ecran(rf):
    """Les instantanés et leurs résumés ne doivent pas se déplacer ensemble."""
    request = rf.get("/x/", {"p_instantanes": "2", "p_resumes": "1"})
    a = tables.paginate(request, list(range(50)), per_page=10, page_param="p_instantanes")
    b = tables.paginate(request, list(range(50)), per_page=10, page_param="p_resumes")
    assert (a.number, b.number) == (2, 1)


# ── Filtres : rien n'atteint l'ORM sans liste fermée ────────────────────

def test_un_choix_hors_liste_est_ignore(rf):
    """Ce qui empêche un ``?tri=`` bricolé de devenir un tri arbitraire."""
    request = rf.get("/x/", {"tri": "-souvenirs__entities__name"})
    assert tables.read_choice(request, "tri", ["-occurred_at", "-importance"]) == ""
    request = rf.get("/x/", {"tri": "-importance"})
    assert tables.read_choice(request, "tri", ["-occurred_at", "-importance"]) == "-importance"


def test_la_recherche_libre_est_bornee(rf):
    request = rf.get("/x/", {"q": "a" * 500})
    assert len(tables.read_text(request, "q")) == 120


def test_la_taille_de_page_est_bornee(rf):
    assert tables.read_per_page(rf.get("/x/", {"per_page": "99999"})) == tables.MAX_PER_PAGE
    assert tables.read_per_page(rf.get("/x/", {"per_page": "-3"})) == 5
    assert tables.read_per_page(rf.get("/x/", {"per_page": "zzz"})) == tables.DEFAULT_PER_PAGE


# ── Émotions : pas d'injection par l'attribut style ─────────────────────

def test_une_emotion_inconnue_ne_fuite_pas_dans_le_style():
    """``emotion_var`` compose un nom de variable CSS ; une chaîne venue de la
    base ne doit jamais y arriver telle quelle."""
    assert emotion_var("happy") == "var(--emo-happy)"
    assert emotion_var("red; background:url(x)") == "var(--emo-neutral)"
    assert emotion_var("") == "var(--emo-neutral)"
    assert emotion_var(None) == "var(--emo-neutral)"


def test_les_29_emotions_ont_une_variable():
    from emotion.types import Emotion
    from GestionSysteme.formatting import EMOTION_NAMES

    declarees = {e.value for e in Emotion}
    assert declarees <= EMOTION_NAMES, declarees - EMOTION_NAMES


# ── Panneaux : un module déclare, il ne rend jamais ─────────────────────

def test_un_type_de_cellule_inconnu_retombe_sur_du_texte():
    cell = panels.Cell(text="x", kind="script")
    assert cell.render_kind == "text"


def test_une_charge_utile_de_module_devient_un_tableau_type():
    # C'est la forme que produisent les modules **forgés** : du code écrit par
    # l'IA à l'exécution, sans type statique. La conversion en cellules typées
    # est ce qui l'empêche de produire du balisage.
    payload = {
        "columns": [{"key": "id", "label": "#"}, {"key": "sujet", "label": "Sujet"}],
        "rows": [{"id": 1, "sujet": "Bonjour"}],
        "total": 1, "page": 0, "limit": 25,
    }
    block = panels.blocks_from_payload(payload)
    assert isinstance(block, panels.Table)
    assert [c.label for c in block.columns] == ["#", "Sujet"]
    assert block.rows[0].cells[1].text == "Bonjour"
    # Ces charges utiles comptent les pages à partir de zéro, l'interface à
    # partir de un : la conversion se fait à l'unique endroit qui sait les deux.
    assert block.page.number == 1


def test_une_charge_utile_html_ne_peut_plus_rien_rendre():
    """La classe de vulnérabilité a disparu, elle n'est plus filtrée.

    Avant, un module qui relayait un corps d'e-mail via une clé ``html``
    obtenait du XSS stocké sur l'interface qui édite les clés d'API. Ici le
    rendu ne connaît que des cellules typées : la clé n'est pas « nettoyée »,
    elle n'est jamais lue.
    """
    block = panels.blocks_from_payload(
        {"html": "<script>alert(1)</script>", "js": "x", "template": "y", "ok": "1"},
    )
    assert isinstance(block, panels.Fields)
    etiquettes = {f.label for f in block.items}
    assert etiquettes == {"ok"}


def test_le_balisage_d_un_module_est_echappe_dans_le_rendu(client):
    """Vérifié sur le HTML réellement produit, pas sur la structure."""
    from django.template.loader import render_to_string

    table = panels.Table(
        columns=[panels.Column("Sujet")],
        rows=[panels.Row(cells=(panels.text("<script>alert(1)</script>"),))],
    )
    html = render_to_string("gestion/partials/block.html", {"block": table})
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_un_panneau_qui_leve_devient_un_bloc_d_erreur(rf):
    """L'espace du module doit rester navigable quand un panneau casse —
    c'est là qu'on vient chercher pourquoi."""
    def explose(request):
        raise RuntimeError("boum")

    panel = panels.ModulePanel(key="k", label="K", handler=explose)
    block = panels.run_panel(rf.get("/x/"), "test", panel)
    assert isinstance(block, panels.Note)
    assert block.tone == "danger"
    assert "boum" in block.text


def test_un_gestionnaire_asynchrone_est_accepte(rf):
    """Les modules historiques déclarent des coroutines ; le nouveau contrat
    accepte les deux."""
    async def handler(request):
        return panels.Note("ok", tone="ok")

    panel = panels.ModulePanel(key="k", label="K", handler=handler)
    block = panels.run_panel(rf.get("/x/"), "test", panel)
    assert isinstance(block, panels.Note) and block.text == "ok"


@pytest.mark.django_db
def test_un_module_arrete_garde_son_espace_de_configuration(client):
    """La correction qui compte : l'ancienne interface ne montrait les pages
    d'un module que s'il **tournait**, donc les réglages d'un module en panne
    étaient inatteignables — précisément quand on en a besoin."""
    from modules.manager import module_manager

    arretes = [
        info["name"] for info in module_manager.list_all()
        if not info.get("system") and not info.get("running")
        and panels.has_config_section(info["name"])
    ]
    if not arretes:
        pytest.skip("aucun module arrêté et configurable sur cette installation")

    nom = arretes[0]
    assert client.get(reverse("gestionsysteme:module-space", args=[nom])).status_code == 200
    assert client.get(
        reverse("gestionsysteme:module-panel", args=[nom, "configuration"]),
    ).status_code == 200


@pytest.mark.django_db
def test_un_module_inconnu_donne_une_404(client):
    assert client.get(
        reverse("gestionsysteme:module-space", args=["nexistepas"]),
    ).status_code == 404


# ── Projets : création et édition ───────────────────────────────────────

def _donnees_projet(**extra) -> dict:
    base = {
        "title": "Veille technique",
        "description": "",
        "keywords": "",
        "origin": "user",
        "status": "active",
        "priority": "normal",
        "owner": "",
        "tone_directive": "",
        "emotion_policy": "off",
        "instructions": "",
        "out_of_scope": "",
        "allowed_modules": [],
        "resource_paths": "",
        "contacts": "",
        "schedule_rule": "",
        "monthly_token_budget": "0",
    }
    base.update(extra)
    return base


@pytest.mark.django_db
def test_la_liste_des_projets_propose_de_creer(client):
    html = client.get(
        reverse("gestionsysteme:projects-tab", args=["actifs"]),
    ).content.decode()
    assert reverse("gestionsysteme:project-new") in html


@pytest.mark.django_db
def test_creation_d_un_projet(client):
    from projects.models import Project

    response = client.post(
        reverse("gestionsysteme:project-new"),
        _donnees_projet(title="Veille IA", schedule_rule="interval:30m"),
    )
    assert response.status_code == 302

    projet = Project.objects.get(title="Veille IA")
    assert projet.schedule_rule == "interval:30m"
    # Recalculée à l'enregistrement : sans cela le projet resterait en
    # attente jusqu'au passage suivant du lanceur.
    assert projet.next_run_at is not None


@pytest.mark.django_db
def test_un_projet_cree_ici_est_en_mode_professionnel(client):
    """Le défaut du modèle doit survivre au passage par le formulaire."""
    from projects.models import Project

    client.post(reverse("gestionsysteme:project-new"), _donnees_projet(title="Sobre"))
    assert Project.objects.get(title="Sobre").emotion_policy == "off"


@pytest.mark.django_db
def test_une_cadence_invalide_est_refusee(client):
    """``schedule.parse_rule`` ne lève jamais : une règle qu'il ne reconnaît
    pas devient « manuel ». Depuis un formulaire, cela donnerait un projet qui
    n'avance plus jamais sans que rien ne le signale."""
    from projects.models import Project

    response = client.post(
        reverse("gestionsysteme:project-new"),
        # « 5min » n'est pas une unité reconnue — c'est « 5m ».
        _donnees_projet(title="Mal réglé", schedule_rule="interval:5min"),
    )
    assert response.status_code == 200
    assert "Cadence non reconnue" in response.content.decode()
    assert not Project.objects.filter(title="Mal réglé").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("regle", [
    "", "manual", "interval:30m", "interval:45s", "cron:0 9 * * MON-FRI",
    "idle:30m", "event:email.received",
])
def test_les_cadences_documentees_sont_acceptees(regle):
    from GestionSysteme.project_forms import ProjectForm

    form = ProjectForm(_donnees_projet(schedule_rule=regle))
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_un_titre_vide_est_refuse(client):
    from projects.models import Project

    avant = Project.objects.count()
    response = client.post(reverse("gestionsysteme:project-new"), _donnees_projet(title=""))
    assert response.status_code == 200
    assert Project.objects.count() == avant


@pytest.mark.django_db
def test_les_listes_se_saisissent_une_valeur_par_ligne(client):
    from projects.models import Project

    client.post(reverse("gestionsysteme:project-new"), _donnees_projet(
        title="Avec consignes",
        instructions="Demander accord avant envoi\nCiter les sources",
        keywords="veille\nIA",
    ))
    projet = Project.objects.get(title="Avec consignes")
    assert projet.instructions == ["Demander accord avant envoi", "Citer les sources"]
    assert projet.keywords == ["veille", "IA"]


@pytest.mark.django_db
def test_les_modules_autorises_sont_une_liste_fermee():
    """Liste blanche stricte : un nom mal tapé ne doit pas être accepté — il
    fermerait un accès silencieusement plutôt que d'en ouvrir un."""
    from GestionSysteme.project_forms import ProjectForm

    form = ProjectForm(_donnees_projet(allowed_modules=["module-qui-nexiste-pas"]))
    assert not form.is_valid()
    assert "allowed_modules" in form.errors


@pytest.mark.django_db
def test_edition_d_un_projet(client):
    from projects.models import Project

    projet = Project.objects.create(title="Avant")
    response = client.post(
        reverse("gestionsysteme:project-edit", args=[projet.pk]),
        _donnees_projet(title="Après", status="paused"),
    )
    assert response.status_code == 302
    projet.refresh_from_db()
    assert (projet.title, projet.status) == ("Après", "paused")


@pytest.mark.django_db
def test_ajout_et_suppression_d_une_tache(client):
    from projects.models import Project, ProjectTask

    projet = Project.objects.create(title="Avec tâches")

    client.post(reverse("gestionsysteme:task-create", args=[projet.pk]), {
        "description": "Lire les flux", "status": "todo", "order": "",
        "result": "", "blocked_reason": "",
    })
    tache = ProjectTask.objects.get(project=projet)
    assert tache.description == "Lire les flux"
    assert tache.order == 1  # numérotée automatiquement

    client.post(reverse("gestionsysteme:task-update", args=[projet.pk, tache.pk]), {
        "action": "etat", "status": "done",
    })
    tache.refresh_from_db()
    assert tache.status == "done"

    client.post(reverse("gestionsysteme:task-update", args=[projet.pk, tache.pk]), {
        "action": "supprimer",
    })
    assert not ProjectTask.objects.filter(pk=tache.pk).exists()


@pytest.mark.django_db
def test_un_etat_de_tache_inconnu_est_refuse(client):
    from projects.models import Project, ProjectTask

    projet = Project.objects.create(title="P")
    tache = ProjectTask.objects.create(project=projet, description="T", status="todo")

    client.post(reverse("gestionsysteme:task-update", args=[projet.pk, tache.pk]), {
        "action": "etat", "status": "n_importe_quoi",
    })
    tache.refresh_from_db()
    assert tache.status == "todo"


@pytest.mark.django_db
def test_une_tache_d_un_autre_projet_est_refusee(client):
    """L'identifiant de tâche vient de l'URL : il doit être vérifié contre le
    projet, sinon on peut modifier la tâche de n'importe quel projet."""
    from projects.models import Project, ProjectTask

    a = Project.objects.create(title="A")
    b = Project.objects.create(title="B")
    tache = ProjectTask.objects.create(project=b, description="T", status="todo")

    response = client.post(
        reverse("gestionsysteme:task-update", args=[a.pk, tache.pk]),
        {"action": "supprimer"},
    )
    assert response.status_code == 404
    assert ProjectTask.objects.filter(pk=tache.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("route", [
    "gestionsysteme:project-delete", "gestionsysteme:task-create",
])
def test_les_ecritures_de_projet_refusent_le_get(client, route):
    from projects.models import Project

    projet = Project.objects.create(title="P")
    assert client.get(reverse(route, args=[projet.pk])).status_code == 405


# ── Fiche personne : onglets, et le pont entité ↔ handle ────────────────

@pytest.fixture
def personne(db):
    from memory.models import Entity

    return Entity.objects.create(name="Thomas", entity_type="person")


def _lie_un_handle(entity, person_id="web_abc123", *, trust="account"):
    """Lie un handle de transport à cette entité mémoire.

    C'est le pont que la couche identité existe pour faire : les messages,
    les instantanés d'émotion et l'humeur vive sont gardés par identifiant de
    transport, l'entité n'apparaît dans aucun d'eux.
    """
    from identity.models import Identity, IdentityHandle

    identity = Identity.objects.create(
        display_name=entity.name, entity=entity, certainty=0.85,
    )
    return IdentityHandle.objects.create(
        identity=identity, person_id=person_id, channel="web", trust=trust,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("onglet", [t.key for t in PERSON_TABS])
def test_chaque_onglet_de_la_fiche_personne_repond(client, personne, onglet):
    """Dérivé de PERSON_TABS : un onglet sans gabarit fait rougir la suite."""
    url = reverse("gestionsysteme:person-detail-tab", args=[personne.pk, onglet])
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_la_fiche_personne_sans_onglet_ouvre_la_synthese(client, personne):
    from GestionSysteme.nav import PERSON_TABS

    response = client.get(
        reverse("gestionsysteme:person-detail", args=[personne.pk]),
    )
    assert response.status_code == 200
    assert response.context["active_person_tab"] == PERSON_TABS[0].key


@pytest.mark.django_db
def test_un_onglet_de_fiche_inconnu_retombe_sur_le_premier(client, personne):
    """Même règle de repli que les onglets du menu — une seule fonction."""
    from GestionSysteme.nav import PERSON_TABS

    response = client.get(
        reverse("gestionsysteme:person-detail-tab", args=[personne.pk, "nexistepas"]),
    )
    assert response.status_code == 200
    assert response.context["active_person_tab"] == PERSON_TABS[0].key


@pytest.mark.django_db
def test_une_personne_inconnue_donne_une_404(client):
    url = reverse("gestionsysteme:person-detail-tab", args=[999999, "souvenirs"])
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_les_echanges_se_resolvent_par_handle_pas_par_entite(client, personne):
    """Le pont, testé de bout en bout.

    Un ``Message`` porte ``person_id="web_abc123"`` et rien d'autre : aucune
    colonne ne le relie à l'entité « Thomas ». Sans la résolution par la
    couche identité, l'onglet reste vide en affichant « aucun message » — le
    silence exact que cette couche a été écrite pour supprimer.
    """
    from memory.models import Conversation, Message

    conversation = Conversation.objects.create()
    Message.objects.create(
        conversation=conversation, role="user", content="salut c'est moi",
        person_id="web_abc123",
    )
    url = reverse("gestionsysteme:person-detail-tab", args=[personne.pk, "echanges"])

    sans_liaison = client.get(url)
    assert sans_liaison.context["no_handle"] is True
    assert sans_liaison.context["page"] is None

    _lie_un_handle(personne)
    avec_liaison = client.get(url)
    assert avec_liaison.context["no_handle"] is False
    assert [m.content for m in avec_liaison.context["page"].rows] == ["salut c'est moi"]


@pytest.mark.django_db
def test_sans_handle_l_onglet_le_dit_au_lieu_de_paraitre_vide(client, personne):
    """« Jamais parlé » et « handle non lié » ne doivent pas se ressembler."""
    for onglet in ("echanges", "affect"):
        response = client.get(
            reverse("gestionsysteme:person-detail-tab", args=[personne.pk, onglet]),
        )
        assert response.context["no_handle"] is True
        assert "Aucun handle lié" in response.content.decode()


@pytest.mark.django_db
def test_un_handle_homonyme_est_nomme_sans_etre_utilise_pour_resoudre(client):
    """Le cas réel : l'entité porte le handle pour nom, rien n'est lié.

    Le consolidateur nomme d'après le ``person_id`` tant que personne ne s'est
    présenté, si bien que l'entité s'appelle ``web_abc123`` — le nom du handle.
    La page doit **nommer** cette liaison manquante sans la faire : résoudre
    par égalité de nom est exactement le bug que la couche identité remplace.
    """
    from identity.models import Identity, IdentityHandle
    from memory.models import Conversation, Entity, Message

    entity = Entity.objects.create(name="web_abc123", entity_type="person")
    identity = Identity.objects.create(display_name="web_abc123")  # non liée
    IdentityHandle.objects.create(
        identity=identity, person_id="web_abc123", channel="web", trust="public",
    )
    conversation = Conversation.objects.create()
    Message.objects.create(
        conversation=conversation, role="user", content="coucou",
        person_id="web_abc123",
    )

    response = client.get(
        reverse("gestionsysteme:person-detail-tab", args=[entity.pk, "echanges"]),
    )
    # Le handle homonyme n'a pas servi à résoudre : l'onglet reste fermé…
    assert response.context["no_handle"] is True
    orphan = response.context["orphan"]
    assert orphan["person_id"] == "web_abc123"
    assert orphan["bound_elsewhere"] is None
    # …mais la page dit précisément ce qui manque, chiffres à l'appui.
    corps = response.content.decode()
    assert "web_abc123" in corps
    assert str(orphan["messages"]) == "1"


@pytest.mark.django_db
def test_l_humeur_vive_se_lit_sur_le_handle_pas_sur_la_cle_primaire(client, personne):
    """L'oscillateur PAD est indexé par identifiant de transport.

    La fiche l'interrogeait avec ``str(entity_id)`` : « Ce qu'elle ressent »
    ne pouvait rien afficher, jamais, sans que rien ne le signale. Ce test
    échoue si la clé redevient celle de l'entité.
    """
    from emotion.engine import emotion_engine
    from emotion.state import PersonMood

    _lie_un_handle(personne, "web_abc123")
    emotion_engine.person_moods.pop(str(personne.pk), None)
    emotion_engine.person_moods["web_abc123"] = PersonMood(person_id="web_abc123")
    try:
        response = client.get(
            reverse("gestionsysteme:person-detail-tab", args=[personne.pk, "synthese"]),
        )
        affects = response.context["affects"]
        assert [a["person_id"] for a in affects] == ["web_abc123"]
    finally:
        emotion_engine.person_moods.pop("web_abc123", None)


@pytest.mark.django_db
def test_la_synthese_annonce_une_fiche_fermee_au_prompt(client, personne):
    """La divulgation est ce qui décide si tout le reste atteint le prompt.

    Une personne sans identité liée a beau avoir un profil complet, il n'est
    jamais injecté — et rien d'autre sur la page ne le dit.
    """
    url = reverse("gestionsysteme:person-detail-tab", args=[personne.pk, "synthese"])

    fermee = client.get(url)
    assert fermee.context["may_disclose"] is False
    assert "Fiche fermée au prompt" in fermee.content.decode()

    # Une session authentifiée : le plancher du canal suffit à ouvrir.
    _lie_un_handle(personne, "user_1", trust="authenticated")
    ouverte = client.get(url)
    assert ouverte.context["may_disclose"] is True
    assert "Fiche fermée au prompt" not in ouverte.content.decode()


@pytest.mark.django_db
def test_les_pastilles_comptent_ce_que_l_onglet_montre(client, personne):
    from memory.models import Commitment, Connaissance, Souvenir
    from django.utils import timezone

    souvenir = Souvenir.objects.create(content="on a parlé", occurred_at=timezone.now())
    souvenir.entities.add(personne)
    fait = Connaissance.objects.create(content="Thomas aime le thé")
    fait.entities.add(personne)
    Commitment.objects.create(description="lui envoyer la playlist", person=personne)

    response = client.get(
        reverse("gestionsysteme:person-detail-tab", args=[personne.pk, "synthese"]),
    )
    counts = response.context["person_counts"]
    assert counts["souvenirs"] == 1
    assert counts["connaissances"] == 1
    assert counts["engagements"] == 1

    for onglet, attendu in (
        ("souvenirs", "on a parlé"),
        ("connaissances", "Thomas aime le thé"),
        ("engagements", "lui envoyer la playlist"),
    ):
        page = client.get(
            reverse("gestionsysteme:person-detail-tab", args=[personne.pk, onglet]),
        ).context["page"]
        assert page.total == 1, onglet
        assert attendu in str(page.rows[0])


@pytest.mark.django_db
@pytest.mark.parametrize("onglet,param,valeur", [
    ("souvenirs", "tri", "'; DROP TABLE"),
    ("connaissances", "validite", "../etc"),
    ("engagements", "statut", "pending' OR 1=1"),
    ("echanges", "role", "assistant; --"),
    ("echanges", "handle", "web_autre"),
    ("affect", "periode", "monthly"),
])
def test_aucun_parametre_d_onglet_n_atteint_l_orm_hors_liste(
    client, personne, onglet, param, valeur,
):
    """Toute valeur d'URL qui touche l'ORM passe par une liste fermée.

    Le filtre ``handle`` est le plus tentant : il porte un identifiant de
    transport et servirait, non contraint, à lire les messages de n'importe
    qui depuis la fiche de quelqu'un d'autre.
    """
    _lie_un_handle(personne)
    url = reverse("gestionsysteme:person-detail-tab", args=[personne.pk, onglet])
    assert client.get(url, {param: valeur}).status_code == 200


@pytest.mark.django_db
def test_le_filtre_handle_ne_lit_que_les_handles_de_la_personne(client, personne):
    """Un handle étranger passé dans l'URL ne doit rien ouvrir de plus."""
    from memory.models import Conversation, Message

    conversation = Conversation.objects.create()
    Message.objects.create(
        conversation=conversation, role="user", content="à moi",
        person_id="web_abc123",
    )
    Message.objects.create(
        conversation=conversation, role="user", content="à quelqu'un d'autre",
        person_id="web_etranger",
    )
    _lie_un_handle(personne, "web_abc123")

    response = client.get(
        reverse("gestionsysteme:person-detail-tab", args=[personne.pk, "echanges"]),
        {"handle": "web_etranger"},
    )
    contenus = [m.content for m in response.context["page"].rows]
    assert contenus == ["à moi"]


# ── Historique affectif : une frise, des personnes, des résumés ─────────
#
# La page listait à plat tout ``EmotionSnapshot``. Or le moteur écrit une
# ligne **par personne suivie plus une pour ``__global__``**, au même instant :
# on y lisait la mécanique d'écriture, pas une évolution. Ces tests tiennent
# la séparation qui rend l'écran lisible, plus le piège ORM qui l'a mordue.

@pytest.fixture
def releves(db):
    """Deux instants de relevés : un global, deux handles, un id interne."""
    from memory.models import Conversation, EmotionSnapshot

    conversation = Conversation.objects.create()
    for emotion, intensite in (("happy", 0.8), ("sad", 0.3)):
        EmotionSnapshot.objects.create(
            conversation=conversation, person_id="__global__",
            primary_emotion=emotion, primary_intensity=intensite,
            global_emotion=emotion, global_intensity=intensite,
        )
        for person_id in ("web_abc123", "conscience_mika"):
            EmotionSnapshot.objects.create(
                conversation=conversation, person_id=person_id,
                primary_emotion="excited", primary_intensity=0.6,
                global_emotion=emotion, global_intensity=intensite,
            )
    return conversation


def _historique(client, **params):
    return client.get(
        reverse("gestionsysteme:inner-tab", args=["historique"]), params,
    )


@pytest.mark.django_db
def test_la_frise_globale_est_chronologique_et_exclut_les_personnes(client, releves):
    """``__global__`` a sa propre carte : c'est son humeur à elle, pas un tiers."""
    reponse = _historique(client)
    frise = reponse.context["global_timeline"]

    assert [p["emotion"] for p in frise["points"]] == ["happy", "sad"]
    assert frise["points"][0]["at"] <= frise["points"][-1]["at"], (
        "la base sert du plus récent au plus ancien ; la frise doit être remise "
        "dans l'ordre du temps, sinon elle se lit à l'envers"
    )
    assert frise["current"]["emotion"] == "sad"


@pytest.mark.django_db
def test_le_tableau_des_personnes_ne_contient_jamais_le_global(client, releves):
    reponse = _historique(client)
    handles = {r["person_id"] for r in reponse.context["snapshot_rows"]}

    assert handles == {"web_abc123", "conscience_mika"}
    assert "__global__" not in handles


@pytest.mark.django_db
def test_la_liste_des_handles_est_dedoublonnee(client, releves):
    """``Meta.ordering`` entre dans la clé de ``distinct()``.

    ``EmotionSnapshot`` trie par ``created_at`` : sans ``order_by()`` vide, la
    colonne de tri rejoint le SELECT et chaque relevé ressort comme un handle
    distinct — la liste déroulante affichait le même handle une fois par ligne
    en base.
    """
    reponse = _historique(client)
    choix = [
        c.value
        for f in reponse.context["filterset"].filters
        if f.param == "personne"
        for c in f.choices if c.value
    ]

    assert choix == sorted(set(choix)), f"doublons dans la liste : {choix}"
    assert set(choix) == {"web_abc123", "conscience_mika"}


@pytest.mark.django_db
def test_un_handle_hors_liste_est_ignore(client, releves):
    """Le filtre est une liste close — aucune valeur d'URL n'atteint l'ORM."""
    reponse = _historique(client, personne="' OR 1=1")

    assert reponse.status_code == 200
    assert {r["person_id"] for r in reponse.context["snapshot_rows"]} == {
        "web_abc123", "conscience_mika",
    }


@pytest.mark.django_db
def test_le_filtre_personne_restreint_les_deux_tableaux(client, releves):
    from memory.models import EmotionalSummary

    EmotionalSummary.objects.create(
        person_id="web_abc123", period_type="daily",
        period_start="2026-07-28", dominant_emotion="excited",
        dominant_intensity=0.6, emotion_distribution={"excited": 1.0},
        trend="warming", snapshot_count=2,
    )
    EmotionalSummary.objects.create(
        person_id="conscience_mika", period_type="daily",
        period_start="2026-07-28", dominant_emotion="sad",
        dominant_intensity=0.4, emotion_distribution={"sad": 1.0},
        trend="cooling", snapshot_count=2,
    )

    reponse = _historique(client, personne="web_abc123")

    assert {r["person_id"] for r in reponse.context["snapshot_rows"]} == {"web_abc123"}
    assert {r["person_id"] for r in reponse.context["summary_rows"]} == {"web_abc123"}


@pytest.mark.django_db
def test_un_releve_porte_son_ecart_a_l_humeur_globale(client, releves):
    """La comparaison utile, à la place de deux colonnes « Intensité » muettes.

    Les deux colonnes d'avant ne disaient pas laquelle était laquelle, et la
    seconde répétait la même valeur sur toutes les lignes d'un même instant.
    """
    reponse = _historique(client, personne="web_abc123")
    ligne = reponse.context["snapshot_rows"][0]

    assert ligne["emotion"] == "excited"
    assert ligne["same_as_global"] is False
    assert ligne["global_emotion"] in ("happy", "sad")
    assert ligne["delta"] == pytest.approx(
        ligne["intensity"] - ligne["global_intensity"],
    )


@pytest.mark.django_db
def test_un_id_interne_est_nomme_comme_tel(client, releves):
    """``conscience_mika`` n'est pas une personne sans fiche : c'est sa propre
    boucle. Servi par ``identity/trust.py``, jamais par une liste recopiée."""
    reponse = _historique(client)
    par_handle = {r["person_id"]: r for r in reponse.context["snapshot_rows"]}

    assert par_handle["conscience_mika"]["kind"] == "interne"
    assert par_handle["web_abc123"]["kind"] == ""


@pytest.mark.django_db
def test_un_handle_lie_renvoie_vers_sa_fiche_personne(client, releves, personne):
    """Le lien passe par la couche identité, jamais par l'égalité de noms."""
    avant = _historique(client).context["snapshot_rows"]
    assert all(r["entity_id"] is None for r in avant)

    _lie_un_handle(personne, "web_abc123")

    apres = {r["person_id"]: r for r in _historique(client).context["snapshot_rows"]}
    assert apres["web_abc123"]["entity_id"] == personne.pk
    assert apres["web_abc123"]["entity_name"] == "Thomas"
    assert apres["conscience_mika"]["entity_id"] is None


@pytest.mark.django_db
def test_un_resume_expose_sa_repartition_et_sa_tendance_en_francais(client, releves):
    """``emotion_distribution`` est le champ le plus riche du modèle et n'était
    pas affiché ; ``trend`` sortait tel quel, en anglais."""
    from memory.models import EmotionalSummary

    EmotionalSummary.objects.create(
        person_id="web_abc123", period_type="daily",
        period_start="2026-07-28", dominant_emotion="excited",
        dominant_intensity=0.6,
        emotion_distribution={"excited": 0.7, "happy": 0.3},
        trend="warming", snapshot_count=4,
    )

    ligne = _historique(client).context["summary_rows"][0]

    assert ligne["trend_fr"] == "se réchauffe"
    assert ligne["trend_tone"] == "ok"
    assert ligne["period_fr"] == "jour"
    assert [d["emotion"] for d in ligne["distribution"]] == ["excited", "happy"], (
        "la répartition doit descendre triée par poids"
    )


@pytest.mark.django_db
def test_les_deux_paginations_sont_independantes(client, releves):
    """Naviguer dans une liste ne doit pas déplacer l'autre."""
    reponse = _historique(client)

    assert reponse.context["snapshots_page"].param == "p_instantanes"
    assert reponse.context["summaries_page"].param == "p_resumes"


# ── Fiche identité : le verdict, et l'arithmétique qui le produit ───────

@pytest.fixture
def identite(db):
    """Une identité sur un canal ``account`` (Telegram : plancher 0.25, plafond 0.85)."""
    from identity.models import Identity, IdentityHandle

    identity = Identity.objects.create(display_name="tg_42", certainty=0.45)
    IdentityHandle.objects.create(
        identity=identity, person_id="tg_42", channel="telegram", trust="account",
    )
    return identity


@pytest.mark.django_db
@pytest.mark.parametrize("onglet", [t.key for t in IDENTITY_TABS])
def test_chaque_onglet_de_la_fiche_identite_repond(client, identite, onglet):
    """Dérivé d'IDENTITY_TABS : un onglet sans gabarit fait rougir la suite."""
    url = reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, onglet])
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_la_fiche_identite_sans_onglet_ouvre_le_verdict(client, identite):
    response = client.get(
        reverse("gestionsysteme:identity-detail", args=[identite.pk]),
    )
    assert response.status_code == 200
    assert response.context["active_identity_tab"] == IDENTITY_TABS[0].key


@pytest.mark.django_db
def test_un_onglet_d_identite_inconnu_retombe_sur_le_premier(client, identite):
    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "nexistepas"]),
    )
    assert response.context["active_identity_tab"] == IDENTITY_TABS[0].key


@pytest.mark.django_db
def test_l_ecriture_d_identite_n_est_pas_capturee_comme_un_onglet(client, identite):
    """``/action/`` est un POST, pas un segment d'onglet.

    ``<slug:tab>`` le capturerait s'il était déclaré avant : l'écriture
    rendrait silencieusement la fiche au lieu de s'appliquer.
    """
    url = reverse("gestionsysteme:identity-action", args=[identite.pk])
    assert url.endswith("/action/")
    assert client.get(url).status_code == 405  # require_POST, donc bien la vue d'écriture


@pytest.mark.django_db
def test_une_identite_inconnue_donne_une_404(client):
    url = reverse("gestionsysteme:identity-detail-tab", args=[999999, "preuves"])
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_le_verdict_expose_le_plancher_et_le_plafond_du_canal(client, identite):
    """L'écart entre valeur stockée et verdict n'est pas du bruit.

    C'est le plancher et le plafond du canal — la seule règle qui fasse qu'une
    revendication en salon public ne vaudra jamais un login. La page l'affichait
    sans jamais dire d'où il venait.
    """
    from identity import trust as trust_policy
    from identity.trust import ChannelTrust

    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "verdict"]),
    )
    ctx = response.context
    assert ctx["channel_trust"] is ChannelTrust.ACCOUNT
    assert ctx["floor"] == trust_policy.floor_for(ChannelTrust.ACCOUNT)
    assert ctx["ceiling"] == trust_policy.ceiling_for(ChannelTrust.ACCOUNT)
    assert ctx["stored"] == pytest.approx(0.45)
    # 0.45 est entre plancher et plafond : ni relevé, ni borné.
    assert ctx["raised_by_floor"] is False
    assert ctx["capped_by_ceiling"] is False


@pytest.mark.django_db
def test_le_verdict_dit_quand_le_plafond_mord(client, identite):
    """« J'enregistre des preuves et rien ne bouge » doit avoir une réponse.

    Sur un canal ``public`` le plafond est CORROBORATED : au-delà, toute
    preuve supplémentaire est délibérément sans effet, et rien ne le disait.
    """
    identite.certainty = 0.95
    identite.save(update_fields=["certainty"])
    identite.handles.update(channel="web", trust="public")

    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "verdict"]),
    )
    assert response.context["capped_by_ceiling"] is True
    assert "Le plafond mord" in response.content.decode()


@pytest.mark.django_db
def test_le_verdict_dit_quand_le_plancher_releve(client):
    """Une session authentifiée n'est pas « inconnue », même à 0 en base."""
    from identity.models import Identity, IdentityHandle

    identity = Identity.objects.create(display_name="user_1", certainty=0.0)
    IdentityHandle.objects.create(
        identity=identity, person_id="user_1", channel="web", trust="authenticated",
    )
    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identity.pk, "verdict"]),
    )
    assert response.context["raised_by_floor"] is True
    assert response.context["decision"].certainty == pytest.approx(1.0)
    assert response.context["decision"].may_disclose is True


@pytest.mark.django_db
def test_le_handle_principal_est_celui_au_plafond_le_plus_haut(client, identite):
    """Pas le plus récent : c'est le plafond qui fixe le verdict de l'identité."""
    from identity.models import IdentityHandle

    recent = IdentityHandle.objects.create(
        identity=identite, person_id="web_tard", channel="web", trust="public",
    )
    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "handles"]),
    )
    principaux = [r["obj"].person_id for r in response.context["handle_rows"] if r["is_primary"]]
    assert principaux == ["tg_42"], "le handle public le plus récent ne doit pas primer"
    assert recent.person_id in [r["obj"].person_id for r in response.context["handle_rows"]]


@pytest.mark.django_db
def test_le_registre_de_preuves_est_pagine_et_filtrable(client, identite):
    """Il était tronqué à cent lignes sans le dire, et sans aucun filtre."""
    from identity.models import IdentityClaim

    for i in range(30):
        IdentityClaim.objects.create(
            identity=identite, claimed_name=f"Nom {i}",
            kind="self_declared",
            status="pending" if i % 2 else "accepted",
        )
    url = reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "preuves"])

    tout = client.get(url).context["page"]
    assert tout.total == 30
    assert len(tout.rows) == tables.DEFAULT_PER_PAGE

    en_attente = client.get(url, {"statut": "pending"}).context["page"]
    assert en_attente.total == 15
    assert {c.status for c in en_attente.rows} == {"pending"}


@pytest.mark.django_db
def test_une_revendication_se_resout_depuis_la_fiche(client, identite):
    """On lit le motif du doute ici ; aller cliquer ailleurs était une
    navigation de trop."""
    from identity.models import IdentityClaim

    claim = IdentityClaim.objects.create(
        identity=identite, claimed_name="Thomas", kind="self_declared",
        handle=identite.handles.first(),
    )
    retour = reverse(
        "gestionsysteme:identity-detail-tab", args=[identite.pk, "preuves"],
    ) + "?statut=pending"

    response = client.post(
        reverse("gestionsysteme:claim-action", args=[claim.pk]),
        {"action": "rejeter", "reason": "pas convaincue", "retour": retour},
    )
    assert response.status_code == 302
    assert response["Location"] == retour, "l'onglet et ses filtres doivent être préservés"
    claim.refresh_from_db()
    assert claim.status == "rejected"


@pytest.mark.django_db
@pytest.mark.parametrize("hostile", [
    "https://evil.test/phishing",
    "//evil.test/phishing",
    "http://evil.test",
])
def test_le_retour_apres_ecriture_ne_sort_jamais_du_site(client, identite, hostile):
    """``retour`` venait du POST et allait droit dans ``redirect()``.

    Une redirection ouverte renvoie un opérateur *déjà authentifié* sur un
    domaine tiers, qui n'a plus qu'à imiter l'écran de connexion. Le contrôle
    est celui de Django, pas une liste d'URL en dur : onglets, filtres et
    numéros de page font partie de la valeur légitime.
    """
    from identity.models import IdentityClaim

    claim = IdentityClaim.objects.create(
        identity=identite, claimed_name="Thomas", kind="self_declared",
    )
    for url, defaut in (
        (reverse("gestionsysteme:claim-action", args=[claim.pk]),
         reverse("gestionsysteme:social-tab", args=["demandes"])),
        (reverse("gestionsysteme:identity-action", args=[identite.pk]),
         reverse("gestionsysteme:identity-detail", args=[identite.pk])),
    ):
        response = client.post(url, {"action": "rejeter", "retour": hostile})
        assert response.status_code == 302
        assert response["Location"] == defaut, f"{url} a suivi {hostile}"


@pytest.mark.django_db
def test_une_identite_orpheline_reste_consultable_et_ses_ecritures_refusees(client):
    """Une ligne sans handle est un fait sur la base, pas une 404.

    Toutes les écritures passent par un identifiant de transport : il n'y a
    rien à manipuler, et la page doit le dire plutôt que d'offrir trois
    formulaires qui échoueront.
    """
    from identity.models import Identity

    identity = Identity.objects.create(display_name="orpheline")
    for onglet in [t.key for t in IDENTITY_TABS]:
        url = reverse("gestionsysteme:identity-detail-tab", args=[identity.pk, onglet])
        assert client.get(url).status_code == 200, onglet

    actions = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identity.pk, "actions"]),
    )
    assert actions.context["acting_person_id"] == ""
    assert "Aucun handle à manipuler" in actions.content.decode()

    ecriture = client.post(
        reverse("gestionsysteme:identity-action", args=[identity.pk]),
        {"action": "lier", "entity_name": "Thomas"}, follow=True,
    )
    assert "aucun handle" in ecriture.content.decode().lower()


@pytest.mark.django_db
def test_le_verdict_signale_les_revendications_en_attente(client, identite):
    """Une revendication non tranchée ne compte pour rien — donc elle se voit."""
    from identity.models import IdentityClaim

    IdentityClaim.objects.create(
        identity=identite, claimed_name="Thomas", kind="self_declared",
        handle=identite.handles.first(),
    )
    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "verdict"]),
    )
    assert len(response.context["pending_claims"]) == 1
    assert "En attente de décision" in response.content.decode()


@pytest.mark.django_db
def test_les_deux_fiches_se_pointent_l_une_l_autre(client, identite):
    """Les deux côtés de la même question : le handle et l'entité mémoire."""
    from memory.models import Entity

    entity = Entity.objects.create(name="Thomas", entity_type="person")
    identite.entity = entity
    identite.save(update_fields=["entity"])

    fiche_identite = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "verdict"]),
    ).content.decode()
    assert reverse("gestionsysteme:person-detail", args=[entity.pk]) in fiche_identite

    fiche_personne = client.get(
        reverse("gestionsysteme:person-detail-tab", args=[entity.pk, "synthese"]),
    ).content.decode()
    assert reverse("gestionsysteme:identity-detail", args=[identite.pk]) in fiche_personne


@pytest.mark.django_db
@pytest.mark.parametrize("onglet,param,valeur", [
    ("preuves", "statut", "pending' OR 1=1"),
    ("preuves", "type", "../etc"),
    ("echanges", "role", "assistant; --"),
    ("echanges", "handle", "tg_inconnu"),
])
def test_aucun_parametre_de_fiche_identite_n_atteint_l_orm_hors_liste(
    client, identite, onglet, param, valeur,
):
    url = reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, onglet])
    assert client.get(url, {param: valeur}).status_code == 200


@pytest.mark.django_db
def test_le_filtre_handle_d_identite_ne_lit_que_ses_propres_handles(client, identite):
    from memory.models import Conversation, Message

    conversation = Conversation.objects.create()
    Message.objects.create(
        conversation=conversation, role="user", content="à moi", person_id="tg_42",
    )
    Message.objects.create(
        conversation=conversation, role="user", content="ailleurs",
        person_id="tg_etranger",
    )
    response = client.get(
        reverse("gestionsysteme:identity-detail-tab", args=[identite.pk, "echanges"]),
        {"handle": "tg_etranger"},
    )
    assert [m.content for m in response.context["page"].rows] == ["à moi"]


# ── Espace du module email : panneaux natifs + sélecteur de compte ──────

@pytest.fixture
def deux_comptes_email(db):
    from modules.plugins.email.models import EmailAccount

    a = EmailAccount.objects.create(
        name="Perso", email_address="perso@test.invalid",
        imap_host="imap.test", imap_user="p", imap_password="x",
    )
    b = EmailAccount.objects.create(
        name="Pro", email_address="pro@test.invalid",
        imap_host="imap.test", imap_user="q", imap_password="x",
    )
    return a, b


@pytest.mark.django_db
def test_le_module_email_declare_des_panneaux_natifs():
    """Et le panneau « Comptes » historique n'est plus affiché : les comptes
    s'éditent dans l'onglet Configuration, qui écrit dans la même table. En
    montrer une copie en lecture seule donnait deux entrées « Comptes » côte
    à côte pour une seule chose."""
    cles = {p.key for p in panels.panels_for("email")}
    assert cles == {"reception", "contacts"}
    assert "accounts" not in cles


@pytest.mark.django_db
def test_le_selecteur_de_compte_apparait_a_partir_de_deux_comptes(
    client, deux_comptes_email,
):
    url = reverse("gestionsysteme:module-panel", args=["email", "reception"])
    html = client.get(url).content.decode()
    assert 'name="compte"' in html
    assert "Perso" in html and "Pro" in html


@pytest.mark.django_db
def test_le_selecteur_de_compte_est_absent_avec_un_seul_compte(client):
    """Proposer de filtrer sur l'unique valeur possible est du bruit."""
    from modules.plugins.email.models import EmailAccount

    EmailAccount.objects.create(
        name="Unique", email_address="seul@test.invalid",
        imap_host="imap.test", imap_user="u", imap_password="x",
    )
    url = reverse("gestionsysteme:module-panel", args=["email", "reception"])
    assert 'name="compte"' not in client.get(url).content.decode()


@pytest.mark.django_db
def test_le_filtre_de_compte_filtre_vraiment(client, deux_comptes_email):
    from modules.plugins.email.models import Email

    perso, pro = deux_comptes_email
    Email.objects.create(
        account=perso, message_id="1", from_address="a@test.invalid",
        to_addresses="perso@test.invalid", subject="SUJET-PERSO",
        direction="inbound",
    )
    Email.objects.create(
        account=pro, message_id="2", from_address="b@test.invalid",
        to_addresses="pro@test.invalid", subject="SUJET-PRO",
        direction="inbound",
    )

    url = reverse("gestionsysteme:module-panel", args=["email", "reception"])
    tout = client.get(url).content.decode()
    assert "SUJET-PERSO" in tout and "SUJET-PRO" in tout

    filtre = client.get(url, {"compte": str(perso.pk)}).content.decode()
    assert "SUJET-PERSO" in filtre
    assert "SUJET-PRO" not in filtre


@pytest.mark.django_db
def test_un_corps_d_email_hostile_est_echappe(client, deux_comptes_email):
    """Le contenu qui motivait toute la refonte : un corps d'e-mail est du
    contenu hostile par défaut, et l'ancien rendu l'injectait via innerHTML."""
    from modules.plugins.email.models import Email

    perso, _ = deux_comptes_email
    message = Email.objects.create(
        account=perso, message_id="3", from_address="attaquant@test.invalid",
        to_addresses="perso@test.invalid", subject="<img src=x onerror=alert(1)>",
        body_text="<script>alert('xss')</script>", direction="inbound",
    )

    url = reverse("gestionsysteme:module-panel", args=["email", "reception"])
    html = client.get(url, {"message": str(message.pk)}).content.decode()
    assert "<script>alert('xss')</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.django_db
def test_le_corps_html_n_est_jamais_rendu(client, deux_comptes_email):
    from modules.plugins.email.models import Email

    perso, _ = deux_comptes_email
    message = Email.objects.create(
        account=perso, message_id="4", from_address="x@test.invalid",
        to_addresses="perso@test.invalid", subject="html seul",
        body_text="", body_html="<b>gras</b><script>alert(1)</script>",
        direction="inbound",
    )
    url = reverse("gestionsysteme:module-panel", args=["email", "reception"])
    html = client.get(url, {"message": str(message.pk)}).content.decode()
    # Le contenu ne doit pas apparaître **du tout** — pas même échappé. Ne
    # vérifier que l'absence de `<b>gras</b>` littéral testerait seulement
    # l'échappement de Django, qui est couvert ailleurs, et laisserait passer
    # un rendu de `body_html` en texte.
    assert "gras" not in html
    # Sans apostrophe : Django l'échappe en &#x27; dans la sortie.
    assert "version HTML" in html


def test_url_with_retire_un_parametre(rf):
    """Ce qui permet au lien « fermer la fiche » de ramener exactement la
    liste filtrée qu'on regardait."""
    from GestionSysteme.tables import url_with

    request = rf.get("/p/reception/", {"compte": "3", "etat": "non_lus", "message": "7"})
    ferme = url_with(request, message=None)
    assert "message=" not in ferme
    assert "compte=3" in ferme and "etat=non_lus" in ferme


# ── Configuration : les secrets ne descendent jamais ────────────────────

@pytest.mark.django_db
def test_un_secret_n_est_jamais_renvoye_au_navigateur(client):
    """Une page de configuration doit pouvoir s'afficher sans exposer une clé."""
    from configs.registry import registry
    from configs.service import config_service
    from GestionSysteme.views import config as config_view

    secrets = [
        i for i in registry.all_items()
        if i.type == "secret" and not config_view.is_module_section(i.section)
    ]
    if not secrets:
        pytest.skip("aucun réglage sensible déclaré")

    item = secrets[0]
    valeur = "sk-ant-secret-a-ne-pas-afficher-42"
    config_service.set(item.key, valeur, actor="test")
    try:
        html = client.get(
            reverse("gestionsysteme:config-section", args=[item.section]),
        ).content.decode()
        assert valeur not in html
        # L'état « défini » doit rester lisible sans révéler la valeur.
        assert "laisser vide pour conserver" in html
    finally:
        config_service.unset(item.key, actor="test")


@pytest.mark.django_db
def test_un_champ_secret_vide_conserve_la_valeur():
    """Un envoi vide vaut « inchangé », jamais « effacer »."""
    from configs.registry import registry
    from configs.service import config_service

    secrets = [i for i in registry.all_items() if i.type == "secret"]
    if not secrets:
        pytest.skip("aucun réglage sensible déclaré")

    item = secrets[0]
    config_service.set(item.key, "valeur-initiale", actor="test")
    try:
        config_service.set(item.key, "", actor="test")
        assert config_service.get(item.key) == "valeur-initiale"
    finally:
        config_service.unset(item.key, actor="test")


@pytest.fixture
def reglage_booleen():
    """Un réglage booléen jetable, enregistré le temps du test.

    Le registre n'en déclare **aucun** aujourd'hui. Faire dépendre ces tests
    de son contenu les faisait se sauter en silence — donc ne rien protéger,
    alors que la logique du marqueur ``__champ`` est précisément la partie
    subtile du moteur de formulaires.
    """
    from configs.registry import registry
    from configs.service import config_service
    from configs.types import ConfigItem, ConfigSection

    cle = "test_gestion.interrupteur"
    registry.register_replace([
        ConfigSection(key="test_gestion", label="Test", order=9999),
        ConfigItem(key=cle, type="bool", section="test_gestion",
                   label="Interrupteur", default=False),
    ])
    item = registry.get(cle)
    try:
        yield item
    finally:
        config_service.unset(cle, actor="test")
        registry.unregister(key_prefix="test_gestion.", section_key="test_gestion")
        config_service.invalidate_cache(cle)


@pytest.mark.django_db
def test_une_case_decochee_est_enregistree_comme_faux(rf, reglage_booleen):
    """Le marqueur ``__champ`` est ce qui distingue une case décochée (absente
    du POST, mais bien affichée) d'un réglage absent du formulaire."""
    from configs.service import config_service

    item = reglage_booleen
    config_service.set(item.key, True, actor="test")
    assert config_service.get(item.key) is True

    # Case décochée : le marqueur est là, la valeur ne l'est pas.
    forms.save_form(
        rf.post("/x/", {forms.FIELD_MARKER: item.key}), [item], actor="test",
    )
    assert config_service.get(item.key) is False

    # Case cochée.
    forms.save_form(
        rf.post("/x/", {forms.FIELD_MARKER: item.key, item.key: "1"}),
        [item], actor="test",
    )
    assert config_service.get(item.key) is True


@pytest.mark.django_db
def test_un_reglage_absent_du_formulaire_n_est_pas_touche(rf, reglage_booleen):
    from configs.service import config_service

    item = reglage_booleen
    config_service.set(item.key, True, actor="test")

    # Aucun marqueur : le réglage n'était pas à l'écran, on n'y touche pas.
    forms.save_form(rf.post("/x/", {}), [item], actor="test")
    assert config_service.get(item.key) is True


@pytest.mark.django_db
def test_une_valeur_refusee_n_annule_pas_les_autres(rf):
    """Refuser tout un lot parce qu'un nombre est hors bornes obligerait à
    ressaisir des réglages corrects."""
    from configs.registry import registry
    from configs.service import config_service

    bornes = [
        i for i in registry.all_items()
        if i.type in ("int", "float") and i.max is not None and not i.readonly
    ]
    texte = [i for i in registry.all_items() if i.type == "str" and not i.readonly]
    if not bornes or not texte:
        pytest.skip("pas de couple borné/libre déclaré")

    mauvais, bon = bornes[0], texte[0]
    request = rf.post("/x/", {
        forms.FIELD_MARKER: [mauvais.key, bon.key],
        mauvais.key: str(mauvais.max + 1000),
        bon.key: "valeur-acceptee",
    })
    try:
        form = forms.save_form(request, [mauvais, bon], actor="test")
        assert bon.key in form.saved
        assert mauvais.key in form.errors_by_key
        assert config_service.get(bon.key) == "valeur-acceptee"
    finally:
        config_service.unset(bon.key, actor="test")


# ── Choix dynamiques : les modèles d'un fournisseur ─────────────────────

@pytest.fixture
def chargeur_bidon(monkeypatch):
    """Remplace l'appel réseau au fournisseur par une liste fixe.

    Sans cela le test dépendrait d'une clé d'API valide et d'un service tiers
    joignable — donc passerait ou échouerait pour des raisons sans rapport
    avec le code testé.
    """
    from GestionSysteme import choices

    appels = []

    def faux(payload):
        appels.append(payload)
        if payload.get("provider") == "casse":
            raise RuntimeError("502 depuis le fournisseur")
        return [("m-rapide", "Modèle rapide"), ("m-lent", "Modèle lent")], ""

    original = choices.for_list("ai.models")
    monkeypatch.setitem(
        choices._REGISTRY, "ai.models",
        choices.DynamicField(
            parent_key=original.parent_key,
            field_key=original.field_key,
            depends_on=original.depends_on,
            button_label=original.button_label,
            empty_message=original.empty_message,
            loader=faux,
        ),
    )
    return appels


def _url_modele_nouveau() -> str:
    return reverse(
        "gestionsysteme:config-record-new", args=["ai_models", "ai.models"],
    )


@pytest.mark.django_db
def test_le_formulaire_propose_de_charger_la_liste(client):
    """Le schéma le dit lui-même : « l'utilisateur ne tape jamais un nom de
    modèle ». Le bouton doit donc être là dès l'ouverture."""
    html = client.get(_url_modele_nouveau()).content.decode()
    assert "Charger les modèles du fournisseur" in html
    assert "Choisis d&#x27;abord un fournisseur" in html or "Choisis d'abord un fournisseur" in html


@pytest.mark.django_db
def test_charger_sans_fournisseur_ne_charge_rien(client, chargeur_bidon):
    response = client.post(_url_modele_nouveau(), {
        "internal_name": "", "provider": "", "model_id": "", "temperature": "0.7",
        "__charger": "1",
    })
    assert response.status_code == 200
    assert not chargeur_bidon, "le fournisseur ne doit pas être interrogé sans sélection"


@pytest.mark.django_db
def test_charger_transforme_le_champ_en_liste_deroulante(client, chargeur_bidon):
    response = client.post(_url_modele_nouveau(), {
        "internal_name": "chat-rapide", "provider": "ollama",
        "model_id": "", "temperature": "0.7", "__charger": "1",
    })
    html = response.content.decode()
    assert response.status_code == 200
    assert chargeur_bidon and chargeur_bidon[0]["provider"] == "ollama"
    assert '<option value="m-rapide"' in html
    assert "Modèle lent" in html
    # La saisie déjà faite repart dans le POST : rien n'est perdu.
    assert 'value="chat-rapide"' in html


@pytest.mark.django_db
def test_charger_n_enregistre_jamais(client, chargeur_bidon):
    """Le bouton recharge des options, il ne crée pas la ligne."""
    from configs.service import config_service

    avant = len(config_service.list_rows("ai.models"))
    client.post(_url_modele_nouveau(), {
        "internal_name": "ne-doit-pas-exister", "provider": "ollama",
        "model_id": "m-rapide", "temperature": "0.7", "__charger": "1",
    })
    assert len(config_service.list_rows("ai.models")) == avant


@pytest.mark.django_db
def test_un_fournisseur_injoignable_laisse_le_champ_saisissable(client, chargeur_bidon):
    """C'est précisément quand un fournisseur ne répond pas qu'on vient
    réparer la configuration : le formulaire doit rester utilisable."""
    response = client.post(_url_modele_nouveau(), {
        "internal_name": "x", "provider": "casse",
        "model_id": "modele-tape-a-la-main", "temperature": "0.7", "__charger": "1",
    })
    html = response.content.decode()
    assert response.status_code == 200
    assert "Chargement impossible" in html
    # Champ texte, pas une liste vide dans laquelle on ne pourrait rien choisir.
    assert 'name="model_id"' in html
    assert '<select id="c-model_id"' not in html
    assert "modele-tape-a-la-main" in html


@pytest.mark.django_db
def test_une_valeur_absente_de_la_liste_chargee_est_conservee():
    """Modifier une ligne ne doit pas lui faire perdre silencieusement son
    modèle parce que le fournisseur ne le liste plus."""
    from GestionSysteme.forms import build_record_form, require_record_list

    item = require_record_list("ai.models")
    form = build_record_form(
        item, {"payload": {"provider": "ollama", "model_id": "modele-retire"}},
        options=[("m-rapide", "Modèle rapide")],
    )
    champ = next(f for f in form.fields if f.name == "model_id")
    valeurs = [v for v, _ in champ.options]
    assert "modele-retire" in valeurs
    assert champ.widget == "select"


@pytest.mark.django_db
def test_les_sections_de_modules_ne_sont_pas_dans_la_config_du_coeur():
    """Elles vivent dans l'espace de leur module, à côté de son état."""
    from GestionSysteme.views import config as config_view

    for section in config_view.core_sections():
        assert not section.key.startswith("module_"), section.key


@pytest.mark.django_db
def test_une_section_de_module_redirige_vers_son_espace(client):
    from configs.registry import registry

    modules = [s for s in registry.sections() if s.key.startswith("module_")]
    if not modules:
        pytest.skip("aucune section de module déclarée")

    section = modules[0]
    response = client.get(reverse("gestionsysteme:config-section", args=[section.key]))
    assert response.status_code == 302
    assert "/gestion/modules/" in response["Location"]


# ── Écritures : CSRF et méthode ─────────────────────────────────────────

@pytest.mark.django_db
def test_une_ecriture_de_configuration_exige_un_jeton_csrf():
    """Le client de test désactive CSRF par défaut : une suite écrite sans
    ``enforce_csrf_checks`` passerait contre une application non protégée."""
    from GestionSysteme.views import config as config_view

    strict = Client(enforce_csrf_checks=True)
    url = reverse(
        "gestionsysteme:config-section", args=[config_view.core_sections()[0].key],
    )
    assert strict.post(url, {}).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("route,args", [
    ("gestionsysteme:module-lifecycle", ["email"]),
    ("gestionsysteme:project-pending-action", [1]),
    ("gestionsysteme:identity-action", [1]),
    ("gestionsysteme:claim-action", [1]),
])
def test_aucune_action_destructrice_derriere_un_get(client, route, args):
    """Un préchargement de navigateur ne doit rien pouvoir déclencher."""
    assert client.get(reverse(route, args=args)).status_code == 405


# ── Portail d'authentification ──────────────────────────────────────────

@pytest.mark.django_db
def test_le_portail_est_desactive_par_defaut(client, settings):
    settings.DASHBOARD_REQUIRE_AUTH = False
    assert client.get(reverse("gestionsysteme:overview")).status_code == 200


@pytest.mark.django_db
def test_le_portail_actif_redirige_un_anonyme(client, settings):
    settings.DASHBOARD_REQUIRE_AUTH = True
    response = client.get(reverse("gestionsysteme:overview"))
    assert response.status_code == 302
    assert settings.LOGIN_URL in response["Location"]


@pytest.mark.django_db
def test_le_portail_refuse_un_compte_non_membre_du_personnel(client, settings):
    """Un compte créé pour le frontend de conversation ne doit pas hériter de
    l'éditeur de configuration."""
    settings.DASHBOARD_REQUIRE_AUTH = True
    User = get_user_model()
    User.objects.create_user(username="simple", password="Motdepasse-Long-42")
    client.login(username="simple", password="Motdepasse-Long-42")
    assert client.get(reverse("gestionsysteme:overview")).status_code == 302


@pytest.mark.django_db
def test_le_portail_laisse_passer_le_personnel(client, settings):
    settings.DASHBOARD_REQUIRE_AUTH = True
    User = get_user_model()
    User.objects.create_user(
        username="admin2", password="Motdepasse-Long-42", is_staff=True,
    )
    client.login(username="admin2", password="Motdepasse-Long-42")
    assert client.get(reverse("gestionsysteme:overview")).status_code == 200


@pytest.mark.django_db
def test_le_portail_ne_couvre_pas_les_autres_chemins(client, settings):
    settings.DASHBOARD_REQUIRE_AUTH = True
    from GestionSysteme.middleware import GestionAuthMiddleware

    class FauxRequete:
        path = "/api/health"
        user = None

    assert GestionAuthMiddleware._is_blocked(FauxRequete()) is False


# ── Aucun rendu de données par le navigateur ────────────────────────────

def test_l_entete_de_tableau_n_est_pas_collant_dans_un_conteneur_defilant():
    """Régression : en-tête de tableau affiché au milieu des lignes.

    ``.table-scroll`` porte ``overflow-x: auto`` ; CSS interdit alors à
    ``overflow-y`` de rester ``visible``. Le conteneur devient un contexte de
    défilement, donc un ``position: sticky`` sur le ``<thead>`` s'y rattache au
    lieu de la fenêtre — et un ``top`` calé sur la barre supérieure décale
    l'en-tête vers le bas *à l'intérieur du tableau*, par-dessus les premières
    lignes.
    """
    import re
    from pathlib import Path

    import GestionSysteme

    css = (
        Path(GestionSysteme.__file__).parent
        / "static" / "gestion" / "css" / "components.css"
    ).read_text()

    # Le conteneur défilant est bien la cause : si un jour il perd son
    # overflow, ce test doit être reconsidéré plutôt que contourné.
    scroll = re.search(r"\.table-scroll\s*\{([^}]*)\}", css)
    assert scroll and "overflow-x" in scroll.group(1)

    entete = re.search(r"table\.table thead th\s*\{([^}]*)\}", css)
    assert entete, "règle d'en-tête introuvable"
    assert "position: sticky" not in entete.group(1)
    assert "var(--topbar-h)" not in css.split(".table-scroll")[-1][:800]


def test_aucun_commentaire_de_gabarit_multiligne():
    """``{# … #}`` ne fonctionne **que sur une ligne**.

    L'expression régulière du lexer Django n'active pas ``re.DOTALL`` : un
    ``{#`` non refermé sur sa propre ligne n'est pas reconnu comme un
    commentaire du tout. Deux conséquences, la seconde bien pire que la
    première :

    - le texte du « commentaire » s'affiche tel quel dans la page ;
    - toute balise ``{% … %}`` citée à l'intérieur est **compilée pour de
      vrai**. C'est ce qui a cassé ``pager.html`` : un ``{% qs_set %}`` donné
      en exemple dans un commentaire était analysé comme un appel sans
      argument, et faisait échouer chaque page paginée.

    Un commentaire sur plusieurs lignes s'écrit ``{% comment %}`` …
    ``{% endcomment %}``, dont le contenu est ignoré par l'analyseur.
    """
    from pathlib import Path

    import GestionSysteme

    racine = Path(GestionSysteme.__file__).parent / "templates"
    fautes = []
    for gabarit in sorted(racine.rglob("*.html")):
        for numero, ligne in enumerate(gabarit.read_text().splitlines(), 1):
            if "{#" in ligne and "#}" not in ligne.split("{#", 1)[1]:
                fautes.append(f"{gabarit.relative_to(racine)}:{numero}")
    assert not fautes, (
        "commentaire {# #} ouvert sur plusieurs lignes — utiliser "
        "{% comment %} … {% endcomment %} : " + ", ".join(fautes)
    )


def test_tous_les_gabarits_compilent():
    """Attrape une erreur de syntaxe dans un gabarit jamais atteint par les
    tests de page — un partiel inclus seulement quand une liste est non vide,
    par exemple, ce qui est exactement le cas qui avait échappé."""
    from pathlib import Path

    from django.template.loader import get_template

    import GestionSysteme

    racine = Path(GestionSysteme.__file__).parent / "templates"
    erreurs = []
    for gabarit in sorted(racine.rglob("*.html")):
        nom = str(gabarit.relative_to(racine))
        try:
            get_template(nom)
        except Exception as exc:
            erreurs.append(f"{nom}: {type(exc).__name__}: {exc}")
    assert not erreurs, erreurs


def test_aucune_jauge_dans_une_cellule_alignee_a_droite():
    """Régression : en-tête de colonne décalé par rapport à son contenu.

    ``.num`` aligne à droite ; une jauge se remplit depuis la gauche. Mettre
    les deux ensemble fait flotter le libellé à l'autre bout de la colonne,
    sans rien casser d'assez visible pour être remarqué à la relecture.
    """
    import re
    from pathlib import Path

    import GestionSysteme

    racine = Path(GestionSysteme.__file__).parent / "templates"
    fautes = []
    for gabarit in racine.rglob("*.html"):
        src = gabarit.read_text()
        for m in re.finditer(
            r'<td[^>]*class="[^"]*\bnum\b[^"]*"[^>]*>(.*?)</td>', src, re.DOTALL,
        ):
            if 'class="meter' in m.group(1):
                fautes.append(f"{gabarit.name}:{src[:m.start()].count(chr(10)) + 1}")
    assert not fautes, fautes


def test_l_ancien_dashboard_a_disparu():
    """L'application ``dashboard`` est supprimée, pas seulement démontée.

    Un import résiduel ne casserait rien tant que le paquet traîne sur le
    disque d'un développeur : c'est exactement ainsi qu'une suppression se
    transforme en dette silencieuse. Ce test échoue sur la référence, pas sur
    l'absence du fichier.
    """
    import re
    from pathlib import Path

    import GestionSysteme

    racine = Path(GestionSysteme.__file__).parent.parent   # backend/
    motif = re.compile(r"\b(from|import)\s+dashboard\b|\bdashboard\.(views|urls|middleware|sanitize|config_)")

    fautes = []
    for source in racine.rglob("*.py"):
        if "__pycache__" in source.parts or source.parts[-2:] == ("tests", __file__):
            continue
        for numero, ligne in enumerate(source.read_text().splitlines(), 1):
            if motif.search(ligne):
                fautes.append(f"{source.relative_to(racine)}:{numero}")
    assert not fautes, fautes

    assert not (racine / "dashboard").exists()

    from django.conf import settings
    assert not any("dashboard" in app for app in settings.INSTALLED_APPS)
    assert not any("dashboard" in m for m in settings.MIDDLEWARE)


def test_aucune_url_ne_pointe_vers_l_ancien_prefixe(client):
    """``/dashboard/`` ne doit plus être routé : une redirection silencieuse
    laisserait croire que les deux interfaces coexistent encore."""
    assert client.get("/dashboard/").status_code == 404


def test_le_contrat_moduleview_est_supprime():
    """Retiré avec le dashboard plutôt que gardé en compatibilité.

    Les deux modules livrés déclarent des panneaux ; une capacité sans
    déclarant est une capacité dont le défaut est la seule réponse que
    quiconque reçoit — le motif que ce dépôt documente déjà pour ``deliver()``.
    """
    import modules.types as types
    from modules.base import BaseModule
    from modules.manager import module_manager

    assert not hasattr(types, "ModuleView")
    assert not hasattr(types, "ModuleViewAction")
    assert not hasattr(BaseModule, "get_views")
    assert not hasattr(module_manager, "collect_views")
    assert not hasattr(panels, "_adapt_legacy_view")


def test_le_javascript_ne_rend_aucune_donnee():
    """Garde-fou contre le retour du modèle qu'on remplace.

    L'ancienne interface assemblait ses pages par concaténation de chaînes :
    125 ``innerHTML`` contre 260 appels manuels d'échappement, sans outil pour
    vérifier qu'aucun n'était oublié. Le script d'amélioration progressive ne
    doit jamais reprendre ce rôle.
    """
    import re
    from pathlib import Path

    import GestionSysteme

    source = (
        Path(GestionSysteme.__file__).parent / "static" / "gestion" / "js" / "gestion.js"
    ).read_text()
    # Les commentaires du fichier *nomment* ces API pour expliquer qu'elles ne
    # sont pas utilisées — les retirer est ce qui rend l'assertion vraie sur le
    # code plutôt que sur la prose.
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)

    for interdit in ("innerHTML", "insertAdjacentHTML", "document.write", "outerHTML"):
        assert interdit not in code, interdit
    # Et le garde-fou reste non vide : le fichier existe et contient du code.
    assert "textContent" in code
