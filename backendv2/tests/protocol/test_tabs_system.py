"""Système, chaque onglet dans sa forme (``app/handmade/tabs/system.py``, ADR 0177), à travers le vrai serveur : ce qui
ne va pas d'abord, en un seul bandeau ; puis les chiffres et les données denses, chacune à sa place — et ce que chaque
page dit, vide. La vie est arrêtée (``stop``) : ses processus n'écrivent rien pendant qu'on lit."""

from __future__ import annotations

import re

from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import LLMTrace
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.kernel.clock import DAY, MINUTE
from mika.runtime import operations
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import ORIGIN, bootstrap, world  # noqa: F401 — fixture partagée


def _life(client, live):
    bootstrap(client)
    stop(client, live.kernel)
    return live.kernel


def _pane(page: str, pane: str) -> str:
    """Un sous-onglet (``<section id=… data-pane>``) jusqu'au suivant."""
    start = page.index(f'<section id="{pane}" data-pane')
    nxt = page.find(" data-pane", start + 30)
    return page[start:nxt if nxt > 0 else len(page)]


def test_anomalies_name_the_faculty_the_event_and_the_error(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    calm = drawn(client, "/inspecteur/systeme/anomalies")
    assert 'class="sys-band tone-ok"' in calm and "Aucune anomalie enregistrée depuis le démarrage" in calm
    assert "sys-an-list" not in calm and "Aucune trace depuis le démarrage" in calm
    monkeypatch.setattr(kernel.mind, "anomalies", ["affect@42: ValueError('intensité hors bornes')",
                                                   "Erreur de réduction à examiner"])
    monkeypatch.setattr(kernel.arbiter, "anomalies", ["attention : raison ou type non déclaré (INITIATIVE/x)"])
    kernel.mind.trace("forget", subject="user_2", events=3)
    kernel.mind.trace("rebuild_mismatch", owners=["memory"])
    page = drawn(client, "/inspecteur/systeme/anomalies")
    # un seul bandeau, avant les chiffres : trois anomalies, rien d'arrêté
    band = page.index('class="sys-band tone-warn"')
    assert "3 anomalies depuis le démarrage" in page and band < page.index("person-tiles")
    assert "Aucune anomalie enregistrée" not in page
    # la faculté par son nom, l'événement où c'est né, l'erreur en clair et telle quelle
    entry = page[page.rfind("<li>", 0, page.index("Humeur et postures")):]
    entry = entry[:entry.index("</li>")]
    assert "Humeur et postures" in entry and 'href="/inspecteur/evenement/42"' in entry
    assert "intensité hors bornes" in entry and "ValueError(" in entry
    assert "Erreur de réduction à examiner" in page  # ce qui ne se lit pas : tel quel
    assert "Anomalies de l'arbitre" in page and "raison ou type non déclaré" in page
    # les traces en mots ; une reconstruction qui diverge, marquée
    assert "oubli" in page and 'class="now-tag warn" title="rebuild_mismatch">reconstruction divergente' in page


def test_the_journal_reads_day_by_day_and_says_an_episode_once(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    chat(client, "raconte-moi ta journée")
    page = drawn(client, "/inspecteur/systeme/chronologie")
    assert "Aujourd'hui" in page
    feed = page[page.index('class="sys-jr-feed"'):]
    ended = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.ended"], 1))[0]
    link = f'href="/inspecteur/episode/{ended.correlation}"'
    events = client.portal.call(lambda: list(live.kernel.mind.store.read(types={"episode.started", "episode.utterance",
                                                                                "episode.ended"})))
    mine = [e for e in events if e.correlation == ended.correlation]
    # ses événements se suivent : le lien de l'épisode une fois, sous le plus récent
    assert len(mine) >= 3 and 1 <= feed.count(link) < len(mine)
    assert "episode.utterance" in feed and '<details class="sys-jr-data">' in feed
    # les familles de la page filtrent par type
    assert re.search(r'class="hm-chip" href="\?type=episode\.">episode <span class="hm-count">\d+', page)
    filtered = drawn(client, "/inspecteur/systeme/chronologie?type=episode.")
    assert "perception.received" not in filtered and 'class="hm-chip on"' in filtered and "tous les types" in filtered
    table = drawn(client, "/inspecteur/systeme/chronologie?vue_pg1=table")
    assert '<table class="hm-table">' in table and "sys-jr-feed" not in table


def test_world_screens_say_what_a_connected_host_lacks(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    empty = drawn(client, "/inspecteur/systeme/monde")
    assert "Aucun client du monde connecté" in empty and "sys-band" not in empty
    now = live.kernel.mind.clock.now()
    view = {"sessions": [
        {"session": "s1", "actor": "mika", "handle": "anon_1", "client": "Unity 6000.0", "roles": ["viewer", "host"],
         "waiting_host": False},
        {"session": "s2", "actor": "mika", "handle": "anon_2", "client": "Navigateur", "roles": ["viewer"],
         "waiting_host": True}],
        "host": "s1", "rev": 7,
        "loaded": [{"session": "s1", "client": "Unity 6000.0", "rev": 6, "at": now - MINUTE,
                    "missing_assets": ["tasse_bleue"], "missing_anchors": ["fenetre_salon"]},
                   {"session": "gone", "client": "Unity 2023", "rev": 7, "at": now - DAY, "missing_assets": [],
                    "missing_anchors": []}]}
    monkeypatch.setattr(live.world, "overview", lambda: view)
    page = drawn(client, "/inspecteur/systeme/monde")
    assert page.count('<p class="sys-band tone-') == 1 and "ancres manquantes : fenetre_salon" in page
    lacks = page[page.index('class="sys-wd-lacks"'):]
    lacks = lacks[:lacks.index("</dl>")]
    assert "fenetre_salon" in lacks and "tasse_bleue" in lacks and "révision 6 chargée, 7 en vigueur" in page
    assert "le tient" in page and "l'attend" in page
    assert "rien ne lui manque" in page and "parti" in page  # l'hôte d'avant, qui ne compte plus


def test_contributions_give_the_whole_then_one_faculty_per_subtab(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/inspecteur/systeme/contributions")
    faculties = live.kernel.registry.faculties
    assert page.index('id="ct-all"') < page.index('id="ct-memory"')
    matrix = page[page.index('class="sys-ct-matrix"'):page.index("</ul>", page.index('class="sys-ct-matrix"'))]
    assert matrix.count('<a href="#ct-') == len(faculties)
    memory = _pane(page, "ct-memory")
    assert "Publie" in memory and "memory.believed" in memory and "Fournit" in memory and "sys-ct-to" in memory
    assert 'href="/inspecteur/facultes/memory/' in memory  # ses vues mènent à elles


def test_simulations_put_the_reports_left_and_the_one_read_right(tmp_path):
    reports = tmp_path / "rapports"
    (reports / "semaine-1").mkdir(parents=True)
    (reports / "rapide.md").write_text("# Voie rapide\nS01 ✔", encoding="utf-8")
    (reports / "semaine-1" / "sonde.json").write_text("{}", encoding="utf-8")
    app, _ = build(tmp_path / "data", web=WebConfig(), gateway=LiveGateway(), embedder=HashEmbedder(), reports=reports)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        bootstrap(client)
        listing = drawn(client, "/inspecteur/systeme/simulations")
        assert "rapide.md" in listing and "semaine-1/" in listing and "Choisis un rapport" in listing
        read = drawn(client, "/inspecteur/systeme/simulations?fichier=rapide.md")
        reader = read[read.index('class="now-card sys-sim-reader"'):]
        assert "S01" in reader and 'aria-current="page"' in read[:read.index('class="now-card sys-sim-reader"')]
        unknown = drawn(client, "/inspecteur/systeme/simulations?fichier=../secret.txt")
        assert "Fichier inconnu" in unknown


def test_the_gateway_says_which_role_nobody_serves_and_how_full_each_provider_is(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    gateway = live.kernel.deps.gateway
    monkeypatch.setattr(gateway, "status", lambda: [
        {"name": "claude", "slots": 3, "busy": 2, "waiting": 1, "preempt": False, "extra": {"quota": {"5 h": 0.92}}}])
    monkeypatch.setattr(gateway, "resolution", lambda: {"reply": "claude", "extract": "claude", "polish": ""})
    page = drawn(client, "/inspecteur/systeme/passerelle")
    assert page.count('<p class="sys-band tone-') == 1 and 'class="sys-band tone-danger"' in page
    assert "1 rôle sans fournisseur : rendre naturel" in page
    assert page.count('class="sys-slot busy"') == 2 and page.count('class="sys-slot free"') == 1
    assert "1 en attente" in page and 'sys-gw-q danger' in page and "92" in page
    roles = page[page.index('id="sys-gw-roles"'):]
    assert roles.index("Personne") < roles.index("rendre naturel") < roles.index(">claude<")
    assert "répondre (voix)" in roles and "retenir (mémoire)" in roles


def _calls(client, live, failed_roles=("extract",)):
    now = live.kernel.mind.clock.now()

    async def seed():
        for i in range(60):
            role = ("reply", "extract", "journal")[i % 3]
            live.calls.record(LLMTrace(
                at=now - (i % 5) * DAY - i * MINUTE, role=role, backend="claude",
                model="claude-opus-5" if role == "journal" else "claude-haiku-5-5", lane="fg", priority=0,
                latency_us=1_500_000, wait_us=0, input_tokens=3000, output_tokens=200,
                outcome="timeout" if role in failed_roles and i % 2 else "ok", call_id=f"t-{i}",
                cost_usd=0.0 if role in failed_roles and i % 2 else 0.01))
        await live.calls.flush()

    client.portal.call(seed)


def test_calls_show_cost_and_failures_per_day_role_and_model(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    _calls(client, live)
    page = drawn(client, "/inspecteur/systeme/appels")
    # le bandeau des échecs, les rôles qui échouent surtout, avant les chiffres
    assert page.count('<p class="sys-band tone-') == 1 and "appels ont échoué en quatorze jours" in page
    assert "surtout : retenir (mémoire)" in page and page.index("sys-band") < page.index("person-tiles")
    # quatorze jours en barres : le coût, les appels, les échecs en rouge
    chart = page[page.index('class="sys-calls-svg with-cost"'):page.index("</svg>", page.index("sys-calls-svg"))]
    assert chart.count('class="cost"') >= 14 and 'class="fail"' in chart
    # où va le coût : par rôle, par modèle, par fournisseur ; le premier sous-onglet
    split = _pane(page, "calls-split")
    assert page.index('id="calls-split"') < page.index('id="calls-all"')
    assert "Par rôle" in split and "Par modèle" in split and "claude · claude-opus-5" in split
    assert re.search(r"retenir \(mémoire\).*?échecs", split, re.S)
    # une autre page de la liste ouvre la sienne, et ses liens y reviennent
    second = drawn(client, "/inspecteur/systeme/appels?page=2")
    assert second.index('id="calls-all"') < second.index('id="calls-split"')
    assert "#calls-all" in second[second.index('id="calls-all"'):] and "51–" in second
    assert '<li class="failed">' in second and "timeout" in second


def test_storage_flags_a_missing_backup_and_draws_a_bar_per_table(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/inspecteur/systeme/stockage")
    assert page.count('<p class="sys-band tone-') == 1 and "Sauvegardes : aucune sauvegarde notée" in page
    tables = page[page.index('class="sys-store-tables"'):page.index("</ul>", page.index("sys-store-tables"))]
    assert tables.count("<li>") == 5 and "events" in tables and "now-bar sys-store-bar" in tables
    assert "Dernière vérification" in page and "mika restore" in page


def test_operator_actions_read_day_by_day(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    assert "Aucune action d'opérateur encore" in drawn(client, "/inspecteur/systeme/operations")
    client.portal.call(lambda: operations.audit(kernel, "console.reglages.essai", by="user_1"))
    page = drawn(client, "/inspecteur/systeme/operations")
    feed = page[page.index('class="sys-ops-feed"'):]
    assert "console.reglages.essai" in feed and "faite" in feed and 'href="/inspecteur/evenement/' in feed
    assert "Sur cette page : <span class=\"now-num\">1</span> action" in page


def test_every_view_has_its_place(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/inspecteur/systeme/vues")
    views = live.kernel.registry.inspectors
    by_faculty = _pane(page, "views-faculty")
    assert all(v.title in by_faculty for v in views)
    assert by_faculty.count("<li>") == len(views)
    dest = _pane(page, "views-dest")
    assert '<a href="/inspecteur/memoire">' in dest and "Souvenirs" in dest
    if any(v.hidden for v in views):
        assert 'id="views-hidden"' in page


def test_the_state_gives_each_faculty_its_facts_and_its_slice_in_json(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/inspecteur/systeme/etat")
    assert page.index('id="st-all"') < page.index('id="st-affect"')
    affect = _pane(page, "st-affect")
    assert "Des familles, qui dépendent de leur argument" in affect and "affect.mood" in affect
    assert "Sa tranche en JSON" in affect
    code = re.search(r'<pre class="hm-code">(.*?)</pre>', affect, re.S).group(1)
    assert code.lstrip().startswith("{") and '"' in code
    slices = page[page.index('class="sys-state-slices"'):]
    assert slices.count('<a href="#st-') >= len(live.kernel.mind.root.slices)
