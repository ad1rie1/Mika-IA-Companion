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
from django.test import Client
from django.urls import reverse

from GestionSysteme import forms, panels, tables
from GestionSysteme.formatting import emotion_var
from GestionSysteme.nav import NAV, item_for


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


def test_l_adaptateur_convertit_une_vue_historique_en_tableau():
    payload = {
        "columns": [{"key": "id", "label": "#"}, {"key": "sujet", "label": "Sujet"}],
        "rows": [{"id": 1, "sujet": "Bonjour"}],
        "total": 1, "page": 0, "limit": 25,
    }
    block = panels._blocks_from_legacy_payload(payload)
    assert isinstance(block, panels.Table)
    assert [c.label for c in block.columns] == ["#", "Sujet"]
    assert block.rows[0].cells[1].text == "Bonjour"
    # Le contrat historique compte les pages à partir de zéro, l'interface à
    # partir de un : la conversion se fait à l'unique endroit qui sait les deux.
    assert block.page.number == 1


def test_une_charge_utile_html_ne_peut_plus_rien_rendre():
    """La classe de vulnérabilité a disparu, elle n'est plus filtrée.

    Avant, un module qui relayait un corps d'e-mail via une clé ``html``
    obtenait du XSS stocké sur l'interface qui édite les clés d'API. Ici le
    rendu ne connaît que des cellules typées : la clé n'est pas « nettoyée »,
    elle n'est jamais lue.
    """
    block = panels._blocks_from_legacy_payload(
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
