"""Réglages, chaque onglet dans sa forme (``app/handmade/tabs/settings.py``, ADR 0177), à travers le vrai serveur : la
vue d'ensemble range les facultés par famille et dit d'où vient une valeur ; la page d'une faculté garde ses groupes
et son formulaire ; les comptes un par entrée, l'ajout dans la barre de titre, les pages d'ajout et de modification
au panneau seul ; le journal, jour par jour, réunit les journalisations d'un même moment."""

from __future__ import annotations

from tests.protocol.test_console_settings import post
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

BASE = "/inspecteur/reglages"


def test_the_overview_groups_faculties_by_family_and_says_where_a_value_comes_from(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, f"{BASE}/comportement")
    assert 'data-tab="reglages/comportement"' in page and "Les facultés" in page
    sources = page.split('class="regx-sources"', 1)[1].split("</p>", 1)[0]
    assert [w for w in ("défaut", "tempérament", "réglage", "surcharge") if f">{w}<" in sources] == [
        "défaut", "tempérament", "réglage", "surcharge"]
    emotions = page.split('aria-label="Émotions"', 1)[1].split("</section>", 1)[0]
    assert f'href="{BASE}/comportement-affect">Humeur et postures</a>' in emotions and "tempérament" in emotions
    assert page.index('aria-label="Émotions"') < page.index('aria-label="Plugins"')
    sliders = page.split('id="regx-sliders"', 1)[1]
    assert "Réactivité" in sliders and "person.mass" in sliders


def test_a_faculty_keeps_its_groups_and_its_form_after_its_figures(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, f"{BASE}/comportement-affect")
    body = page.split('data-tab="reglages/comportement-*"', 1)[1]
    # la bande, d'où vient une valeur, les groupes : enfants de la page, que base.css place autour du formulaire
    assert body.index('class="person-tiles"') < body.index('class="regx-sources"') < body.index('class="hm-chips"')
    assert "groupes" in body.split('class="regx-sources"', 1)[0] and f"{BASE}/temperament" in body
    assert body.index('class="hm-chips"') < body.index('class="form params-form"')
    one = drawn(client, f"{BASE}/comportement-camera")  # peu de paramètres : une seule page, sans groupes
    assert 'data-tab="reglages/comportement-*"' in one and 'class="hm-chips"' not in one.split("params-form")[0]


def test_accounts_one_per_entry_and_their_own_pages_stay_the_panel(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.portal.call(lambda: live.accounts.create("bea", "une-phrase-longue", operator=False, full_name="Béa"))
    page = drawn(client, f"{BASE}/comptes")
    assert 'data-tab="reglages/comptes"' in page
    head = page.split('class="page-head', 1)[1].split('data-tab=', 1)[0]
    assert "Ajouter un utilisateur" in head and "Ajouter un opérateur" in head
    bea = page.split(">Béa</a>", 1)[0].rsplit("<li", 1)[1] + page.split(">Béa</a>", 1)[1].split("</li>", 1)[0]
    assert "regx-acct" in bea and ">bea<" in bea and ">utilisateur<" in bea and "Sa fiche" in bea
    assert "compte=2" in bea
    for url in (f"{BASE}/comptes?compte=2", f"{BASE}/comptes?nouveau=utilisateur"):
        own = drawn(client, url)
        assert 'data-tab="reglages/comptes"' not in own and 'class="form now-card hm-form record-form"' in own


def test_the_journal_reads_day_by_day_and_gathers_one_moment(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    client.get(f"{BASE}/comportement-camera")
    saved = post(client, f"{BASE}/comportement-camera", {"_faculte": "camera", "_groupe": "", "_champs": [
        "look_every_us", "fresh_us", "shown_for_us"], "look_every_us": "2 min", "fresh_us": "3 min",
        "shown_for_us": "10 min"})
    assert saved.status_code in (200, 303)
    page = drawn(client, f"{BASE}/journal")
    assert 'data-tab="reglages/journal"' in page and "aujourd'hui" in page
    operator = page.split(">opérateur<", 1)[1].split("</li>", 1)[0]
    assert "Paramètres · Caméra" in operator and "par " in operator
    gathered = page.split("Paramètres journalisés pour ", 1)[1].split("</li>", 1)[0]
    assert gathered.count('href="/inspecteur/reglages/comportement-') > 1  # le démarrage, en une ligne
