"""Système, chaque onglet dans sa forme (``app/handmade/tabs/system.py``, ADR 0177), à travers le vrai serveur : ce qui
ne va pas d'abord, en un seul bandeau ; puis les chiffres et les données denses, chacune à sa place — et ce que chaque
page dit, vide. La vie est arrêtée (``stop``) : ses processus n'écrivent rien pendant qu'on lit."""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import replace
from types import SimpleNamespace

from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import LLMTrace
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app import backup
from mika.app.console import FACULTY_LABELS, LABELS
from mika.app.handmade.tabs.system import ENGINE_FAMILIES
from mika.app.server import build
from mika.inspector.names import Names
from mika.inspector.pages import system as system_pages
from mika.kernel.clock import DAY, MINUTE, US
from mika.kernel.state import FrozenDict
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
    calm = drawn(client, "/admin/systeme/anomalies")
    assert 'class="sys-band tone-ok"' in calm and "Aucune anomalie enregistrée depuis le démarrage" in calm
    assert "sys-an-list" not in calm and "Aucune trace depuis le démarrage" in calm
    monkeypatch.setattr(kernel.mind, "anomalies", ["affect@42: ValueError('intensité hors bornes')",
                                                   "Erreur de réduction à examiner"])
    monkeypatch.setattr(kernel.arbiter, "anomalies", ["attention : raison ou type non déclaré (INITIATIVE/x)"])
    kernel.mind.trace("forget", subject="user_2", events=3)
    kernel.mind.trace("rebuild_mismatch", owners=["memory"])
    page = drawn(client, "/admin/systeme/anomalies")
    # un seul bandeau, avant les chiffres : trois anomalies, rien d'arrêté
    band = page.index('class="sys-band tone-warn"')
    assert "3 anomalies depuis le démarrage" in page and band < page.index("person-tiles")
    assert "Aucune anomalie enregistrée" not in page
    # la faculté par son nom, l'événement où c'est né, l'erreur en clair et telle quelle
    entry = page[page.rfind("<li>", 0, page.index("Humeur et postures")):]
    entry = entry[:entry.index("</li>")]
    assert "Humeur et postures" in entry and 'href="/admin/evenement/42"' in entry
    assert "intensité hors bornes" in entry and "ValueError(" in entry
    assert "Erreur de réduction à examiner" in page  # ce qui ne se lit pas : tel quel
    assert "Anomalies de l'arbitre" in page and "raison ou type non déclaré" in page
    # les traces en mots ; une reconstruction qui diverge, marquée
    assert "oubli" in page and 'class="now-tag warn" title="rebuild_mismatch">reconstruction divergente' in page


def test_the_journal_reads_day_by_day_and_says_an_episode_once(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    chat(client, "raconte-moi ta journée")
    client.portal.call(lambda: operations.audit(kernel, "console.comptes.creer", by="user_1", subject_kind="compte",
                                                subject="user_2"))
    page = drawn(client, "/admin/systeme/chronologie")
    assert "Aujourd'hui" in page
    feed = page[page.index('class="sys-jr-feed"'):]
    ended = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.ended"], 1))[0]
    link = f'href="/admin/episode/{ended.correlation}"'
    events = client.portal.call(lambda: list(live.kernel.mind.store.read(types={"episode.started", "episode.utterance",
                                                                                "episode.ended"})))
    mine = [e for e in events if e.correlation == ended.correlation]
    # ses événements se suivent : le lien de l'épisode une fois, sous le plus récent
    assert len(mine) >= 3 and 1 <= feed.count(link) < len(mine)
    assert "episode.utterance" in feed and '<details class="sys-jr-data">' in feed
    # les familles de la page filtrent par type, chacune sous le nom de la faculté qui possède ses types — celles du
    # moteur sous leur sens —, son préfixe au survol (C8-08)
    assert re.search(r'class="hm-chip" href="\?type=episode\." title="episode">Épisodes <span class="hm-count">\d+',
                     page)
    chips = dict(re.findall(r'href="\?type=([a-z_]+)\." title="\1">([^<]+) <span class="hm-count">', page))
    assert {"episode", "runtime"} <= set(chips) and any(p not in ENGINE_FAMILIES for p in chips)
    assert all(chips[p] == ENGINE_FAMILIES[p] for p in chips if p in ENGINE_FAMILIES)
    assert all(chips[p] == FACULTY_LABELS[p] for p in chips if p not in ENGINE_FAMILIES)
    # un geste audité dit lequel, et qui l'a fait ; son lien, « un geste audité » (C8-08, C8-R1)
    assert re.search(r">Geste audité : Compte créé, par [^<]+</a>", feed) and "lié à <a" in feed
    assert "un geste audité" in feed and "action d'opérateur" not in feed.lower()
    filtered = drawn(client, "/admin/systeme/chronologie?type=episode.")
    assert "perception.received" not in filtered and 'class="hm-chip on"' in filtered and "tous les types" in filtered
    table = drawn(client, "/admin/systeme/chronologie?vue_pg1=table")
    assert '<table class="hm-table">' in table and "sys-jr-feed" not in table
    # la vue le dit elle-même (le repli, la console en MCP) : le geste, sa faculté en colonne repliée
    assert "Geste audité : Compte créé, par " in table and "faculté" in table


def test_world_screens_say_what_a_connected_host_lacks(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    empty = drawn(client, "/admin/systeme/monde")
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
    page = drawn(client, "/admin/systeme/monde")
    assert page.count('<p class="sys-band tone-') == 1 and "ancres manquantes : fenetre_salon" in page
    lacks = page[page.index('class="sys-wd-lacks"'):]
    lacks = lacks[:lacks.index("</dl>")]
    assert "fenetre_salon" in lacks and "tasse_bleue" in lacks and "révision 6 chargée, 7 en vigueur" in page
    assert "le tient" in page and "l'attend" in page
    assert "rien ne lui manque" in page and "parti" in page  # l'hôte d'avant, qui ne compte plus


def test_contributions_give_the_whole_then_one_faculty_per_subtab(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/admin/systeme/contributions")
    faculties = live.kernel.registry.faculties
    assert page.index('id="ct-all"') < page.index('id="ct-memory"')
    matrix = page[page.index('class="sys-ct-matrix"'):page.index("</ul>", page.index('class="sys-ct-matrix"'))]
    assert matrix.count('<a href="#ct-') == len(faculties)
    memory = _pane(page, "ct-memory")
    assert "Publie" in memory and "memory.believed" in memory and "Fournit" in memory and "sys-ct-to" in memory
    # ses vues ne s'y relistent pas : un lien vers Toutes les vues › Par faculté, ouverte sur elle (C8-12)
    own = [v for v in live.kernel.registry.inspectors if v.owner == "memory"]
    assert f'<a href="/admin/systeme/vues#vues-de-memory">Ses vues ({len(own)}) →</a>' in memory
    assert 'href="/admin/memoire/souvenirs"' not in memory and "/facultes/memory/souvenirs" not in memory
    # l'ancre est là, dans « Par faculté » : son groupe a toutes ses vues, chacune vers elle
    group = _pane(drawn(client, "/admin/systeme/vues"), "views-faculty")
    group = group[group.index('id="vues-de-memory"'):]
    group = group[:group.index("</section>")]
    assert group.count("<li>") == len(own) and 'href="/admin/memoire/souvenirs"' in group


def test_contributions_count_the_processes_of_the_scheduler_the_kernel_included(world):  # noqa: F811
    """Contributions compte les processus comme Système › Processus : ceux de l'ordonnanceur, par propriétaire. La
    fiche « Noyau » a les siens, nés hors du registre (l'arbitre, le relevé des courbes) ; la vue, en MCP, aussi."""
    client, live, _ = world
    kernel = _life(client, live)
    specs = kernel.scheduler.specs
    assert {s.name for s in specs if s.owner == "kernel"} >= {"arbitre", "séries"}
    page = drawn(client, "/admin/systeme/contributions")
    tile = page[page.index('person-tile-label">Processus<'):]
    assert re.match(r'person-tile-label">Processus</span><span class="person-tile-value"><span class="num">(\d+)<',
                    tile).group(1) == str(len(specs))
    core = _pane(page, "ct-kernel")
    assert 'aria-label="Processus"' in core and 'title="arbitre"' in core and "Décider d" in core
    assert 'title="séries"' in core
    ui = SimpleNamespace(kernel=kernel, names=Names(kernel, LABELS))
    blocks = asyncio.run(system_pages.contributions(ui, None))
    said = dict(next(b for b in blocks if getattr(b, "title", "") == "Noyau (kernel)").items[0].pairs)
    assert "arbitre" in said["processus"] and "séries" in said["processus"]


def test_simulations_put_the_reports_left_and_the_one_read_right(tmp_path):
    reports = tmp_path / "rapports"
    (reports / "semaine-1").mkdir(parents=True)
    (reports / "rapide.md").write_text("# Voie rapide\nS01 ✔", encoding="utf-8")
    (reports / "semaine-1" / "sonde.json").write_text("{}", encoding="utf-8")
    app, _ = build(tmp_path / "data", web=WebConfig(), gateway=LiveGateway(), embedder=HashEmbedder(), reports=reports)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        bootstrap(client)
        listing = drawn(client, "/admin/systeme/simulations")
        assert "rapide.md" in listing and "semaine-1/" in listing and "Choisis un rapport" in listing
        read = drawn(client, "/admin/systeme/simulations?fichier=rapide.md")
        reader = read[read.index('class="now-card sys-sim-reader"'):]
        assert "S01" in reader and 'aria-current="page"' in read[:read.index('class="now-card sys-sim-reader"')]
        unknown = drawn(client, "/admin/systeme/simulations?fichier=../secret.txt")
        assert "Fichier inconnu" in unknown


def test_simulations_without_a_reports_folder_say_once_how_to_make_one(world):  # noqa: F811
    """C8-12 : sans dossier de rapports, la page dit une seule fois comment en faire — la carte « Faire un rapport »
    et ses deux commandes ; la note de la vue, qui disait la même chose, s'y tait, mais reste à la vue (le repli, la
    console en MCP)."""
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/admin/systeme/simulations")
    tab = page[page.index('data-tab="systeme/simulations"'):]
    assert "sys-band" not in tab and tab.count("Faire un rapport") == 1
    assert tab.count("--report DOSSIER") == 1 and tab.count("--reports DOSSIER") == 1
    assert "Aucun dossier de rapports" not in tab
    blocks = asyncio.run(system_pages.simulations(SimpleNamespace(deps=SimpleNamespace(reports=None)), None))
    assert [b.text for b in blocks] == ["Aucun dossier de rapports (lance le serveur avec --reports DOSSIER, et "
                                        "« mika sim run --report DOSSIER »)."]


def test_the_gateway_says_which_role_nobody_serves_and_how_full_each_provider_is(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    gateway = live.kernel.deps.gateway
    monkeypatch.setattr(gateway, "status", lambda: [
        {"name": "claude", "slots": 3, "busy": 2, "waiting": 1, "preempt": False, "extra": {"quota": {"5 h": 0.92}}}])
    # un vrai rôle que personne ne sert (« retenir ») : l'alarme ; la seconde passe sans modèle n'en est pas une
    monkeypatch.setattr(gateway, "resolution", lambda: {"reply": "claude", "extract": "", "polish": ""})
    page = drawn(client, "/admin/systeme/passerelle")
    assert page.count('<p class="sys-band tone-') == 1 and 'class="sys-band tone-danger"' in page
    band = page[page.index('class="sys-band tone-danger"'):]
    band = band[:band.index("</p>")]
    assert "1 rôle sans fournisseur : retenir (mémoire). Chaque appel de ce rôle échoue." in band
    assert "rendre naturel" not in band
    assert page.count('class="sys-slot busy"') == 2 and page.count('class="sys-slot free"') == 1
    assert "1 en attente" in page and 'sys-gw-q danger' in page and "92" in page
    roles = page[page.index('id="sys-gw-roles"'):]
    assert roles.index("Personne") < roles.index("retenir (mémoire)") < roles.index(">claude<")
    assert roles.index(">claude<") < roles.index("Sans modèle, par choix") < roles.index("rendre naturel")
    assert "répondre (voix)" in roles


def test_the_second_pass_without_a_model_is_cut_by_choice_not_a_red_alarm(world, monkeypatch):  # noqa: F811
    """C8-02 : « rendre naturel » (``OPTIONAL_ROLES``) n'a pas de repli ; sans modèle, la seconde passe ne se fait pas
    et aucun appel n'échoue (ADR 0140). La page disait en rouge « 1 rôle sans fournisseur : rendre naturel (voix,
    seconde passe). Chaque appel de ce rôle échoue. », sous « Personne », et comptait un rôle sans fournisseur."""
    client, live, _ = world
    _life(client, live)
    gateway = live.kernel.deps.gateway
    monkeypatch.setattr(gateway, "status", lambda: [
        {"name": "claude", "slots": 3, "busy": 0, "waiting": 0, "preempt": False, "extra": {}}])
    monkeypatch.setattr(gateway, "resolution", lambda: {"reply": "claude", "extract": "claude", "polish": ""})
    page = drawn(client, "/admin/systeme/passerelle")
    assert "tone-danger" not in page and "sys-band" not in page and "chaque appel" not in page.lower()
    assert "<h3>Personne" not in page and "sans fournisseur :" not in page
    at = page.index("Rôles sans fournisseur")
    assert page[page.rfind("<li", 0, at):at].startswith('<li class="">')  # sans ton danger
    assert re.match(r'Rôles sans fournisseur</span><span class="person-tile-value">(?:<[^>]+>)*0<', page[at:]), \
        page[at:at + 200]
    roles = page[page.index('id="sys-gw-roles"'):]
    assert roles.index(">claude<") < roles.index("Sans modèle, par choix") < roles.index("rendre naturel")
    assert "coupée : aucun modèle, la seconde passe ne se fait pas" in roles


def _gateway_view(resolution: dict[str, str]) -> list:
    """Les blocs de la vue Moteur des modèles (que lisent la console en MCP et le repli du dessin), sur une
    passerelle qui dit qui sert quoi."""
    gateway = SimpleNamespace(configured=True, status=lambda: [], resolution=lambda: resolution)
    ui = SimpleNamespace(kernel=SimpleNamespace(deps=SimpleNamespace(gateway=gateway)))
    return asyncio.run(system_pages.passerelle(ui, None))


def test_the_gateway_says_at_what_effort_each_role_really_thinks(world, monkeypatch):  # noqa: F811
    """ADR 0285 : la vue (celle que lit la console en MCP) dit pour chaque rôle servi l'effort auquel partent ses
    appels et d'où il vient — réglé pour ce rôle, celui de la fiche, ou le défaut du modèle ; la page dessinée le dit
    sur la pastille du rôle qui a le sien."""
    efforts = {"polish": ("low", True), "reply": ("high", False)}
    gateway = SimpleNamespace(configured=True, status=lambda: [],
                              resolution=lambda: {"reply": "claude", "polish": "claude", "extract": "claude",
                                                  "dream": ""},
                              effort_of=lambda role: efforts.get(role, ("", False)))
    ui = SimpleNamespace(kernel=SimpleNamespace(deps=SimpleNamespace(gateway=gateway)))
    _stats, _providers, roles = asyncio.run(system_pages.passerelle(ui, None))
    said = {r.cells[1].text: getattr(r.cells[3], "text", r.cells[3]) for r in roles.rows}
    assert said == {"reply": "élevé — celui de sa fiche", "polish": "faible — réglé pour ce rôle",
                    "extract": "défaut du modèle", "dream": ""}
    assert "sinon celui de la fiche de son fournisseur" in roles.caption

    client, live, _ = world
    _life(client, live)
    served = live.kernel.deps.gateway
    monkeypatch.setattr(served, "status", lambda: [
        {"name": "claude", "slots": 3, "busy": 0, "waiting": 0, "preempt": False, "extra": {}}])
    monkeypatch.setattr(served, "resolution", lambda: {"reply": "claude", "polish": "claude"})
    monkeypatch.setattr(served, "effort_of", lambda role: efforts.get(role, ("", False)))
    page = drawn(client, "/admin/systeme/passerelle")
    chips = page[page.index('id="sys-gw-roles"'):]
    assert "rendre naturel (voix, seconde passe) · faible</span>" in chips
    assert "répondre (voix)</span>" in chips and "répondre (voix) · " not in chips


def test_the_gateway_view_keeps_its_alarm_for_a_real_role_only():
    """C8-02, la vue : la seconde passe coupée ne compte pas parmi les rôles sans fournisseur, sa ligne est neutre et
    dit « coupée » ; un vrai rôle que personne ne sert garde son chiffre en danger et sa ligne rouge."""
    stats, _providers, roles = _gateway_view({"reply": "claude", "polish": ""})
    unserved = next(x for x in stats.items if x.label == "Rôles sans fournisseur")
    assert (unserved.value, unserved.sub, unserved.tone) == (0, "aucun", "")
    polish = next(r for r in roles.rows if r.cells[1].text == "polish")
    assert polish.tone == "" and polish.cells[2].text == "coupée : aucun modèle, la seconde passe ne se fait pas"
    assert "« rendre naturel (voix, seconde passe) » n'a pas de repli" in roles.caption
    stats, _providers, roles = _gateway_view({"reply": "claude", "extract": "", "polish": ""})
    unserved = next(x for x in stats.items if x.label == "Rôles sans fournisseur")
    assert (unserved.value, unserved.sub, unserved.tone) == (1, "retenir (mémoire)", "danger")
    extract = next(r for r in roles.rows if r.cells[1].text == "extract")
    assert extract.tone == "danger" and extract.cells[2].text == "aucun : chaque appel échoue"



def test_the_gateway_says_how_many_calls_wait_with_the_word_agreed(world, monkeypatch):  # noqa: F811
    # chaque rôle servi : le bandeau dit les appels en file, le nom et le verbe accordés au compte (``plural``)
    client, live, _ = world
    _life(client, live)
    gateway = live.kernel.deps.gateway
    monkeypatch.setattr(gateway, "resolution", lambda: {"reply": "claude", "extract": "claude"})
    for waiting, said in ((1, "1 appel attend un créneau libre."), (2, "2 appels attendent un créneau libre.")):
        monkeypatch.setattr(gateway, "status", lambda w=waiting: [
            {"name": "claude", "slots": 3, "busy": 3, "waiting": w, "preempt": False, "extra": {}}])
        page = drawn(client, "/admin/systeme/passerelle")
        assert page.count('<p class="sys-band tone-') == 1 and 'class="sys-band tone-warn"' in page
        band = page[page.index('class="sys-band tone-warn"'):]
        assert band[:band.index("</p>")].count(said) == 1


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
    page = drawn(client, "/admin/systeme/appels")
    # le bandeau des échecs, les rôles qui échouent surtout, avant les chiffres
    assert page.count('<p class="sys-band tone-') == 1 and "appels ont échoué en 14 jours" in page
    assert "surtout : retenir (mémoire)" in page and page.index("sys-band") < page.index("person-tiles")
    # la période par défaut, 14 jours, en barres : le coût, les appels, les échecs en rouge
    chart = page[page.index('class="sys-calls-svg with-cost"'):page.index("</svg>", page.index("sys-calls-svg"))]
    assert chart.count('class="cost"') >= 14 and 'class="fail"' in chart
    # où va le coût : par rôle, par modèle, par fournisseur ; le premier sous-onglet
    split = _pane(page, "calls-split")
    assert page.index('id="calls-split"') < page.index('id="calls-all"')
    assert "Par rôle" in split and "Par modèle" in split and "claude · claude-opus-5" in split
    assert re.search(r"retenir \(mémoire\).*?échecs", split, re.S)
    # une autre page de la liste ouvre la sienne, et ses liens y reviennent
    second = drawn(client, "/admin/systeme/appels?page=2")
    assert second.index('id="calls-all"') < second.index('id="calls-split"')
    assert "#calls-all" in second[second.index('id="calls-all"'):] and "51–" in second
    assert '<li class="failed">' in second and "timeout" in second


def _bars(page: str) -> int:
    """Les barres du graphe des jours (une par jour)."""
    start = page.index('class="sys-calls-svg')
    return page[start:page.index("</svg>", start)].count("<g ")


def test_calls_apply_one_chosen_period_to_the_whole_page(world):  # noqa: F811
    """Une période choisie (7, 14 ou 30 jours, 14 posé), d'un bouton à choix au bout de la barre d'onglets, vaut pour
    toute la page : ses chiffres, son graphe (une barre par jour, le premier entamé compris), où va le coût, le
    bandeau ; la liste de tous les appels reste paginée sans période, ses pages gardent le choix (audit du
    2026-11-05, C8-13 et C8-05)."""
    client, live, _ = world
    _life(client, live)
    _calls(client, live)
    now = live.kernel.mind.clock.now()

    async def older():  # dix jours : dans 14, pas dans 7 ; vingt jours : dans 30 seulement
        for i, (age, role, cost) in enumerate([(10, "journal", 0.5)] * 4 + [(20, "reply", 0.25)] * 2):
            live.calls.record(LLMTrace(
                at=now - age * DAY, role=role, backend="claude", model="claude-opus-5", lane="bg", priority=0,
                latency_us=1_000_000, wait_us=0, input_tokens=100, output_tokens=10,
                outcome="timeout" if age == 10 and i == 0 else "ok", call_id=f"old-{i}", cost_usd=cost))
        await live.calls.flush()

    client.portal.call(older)
    frame = live.kernel.mind.frame()

    def days(n: int) -> int:  # le premier jour entamé compris : 8, 15 ou 31 (à un près autour d'un changement d'heure)
        return (frame.local(now).date() - frame.local(now - n * DAY).date()).days + 1

    def journal(page: str) -> str:
        roles = page[page.index('aria-labelledby="calls-roles"'):]
        return roles[roles.index("tenir son journal (voix)"):roles.index("</li>", roles.index("tenir son journal"))]

    page = drawn(client, "/admin/systeme/appels")
    # le bouton à choix au bout de la barre d'onglets : trois choix, 14 jours posé
    seg = page[page.index('<nav class="seg" aria-label="période">'):]
    seg = seg[:seg.index("</nav>")]
    assert all(f"periode={k}" in seg for k in ("7", "14", "30"))
    assert re.search(r'aria-current="true">14 jours<', seg) and seg.count("aria-current") == 1
    assert "Sur 14 jours" in page and "Échecs (14 jours)" in page and "Part du cache (14 jours)" in page
    assert _bars(page) == days(14) and '<span class="now-num">64</span> appels' in page
    assert "appels ont échoué en 14 jours" in page and "Par rôle <span class=\"now-muted\">· 14 jours" in page
    assert '<span class="now-num">24</span> appels' in journal(page)
    # sept jours : les chiffres, le graphe, où va le coût, le bandeau, d'un seul choix
    week = drawn(client, "/admin/systeme/appels?periode=7")
    seg = week[week.index('<nav class="seg" aria-label="période">'):]
    assert re.search(r'aria-current="true">7 jours<', seg[:seg.index("</nav>")])
    assert "Sur 7 jours" in week and "Échecs (7 jours)" in week and "Part du cache (7 jours)" in week
    assert "14 jours" not in week[week.index('data-tab="systeme/appels"'):]
    assert _bars(week) == days(7) and '<span class="now-num">60</span> appels' in week
    assert "appels ont échoué en 7 jours" in week and "Par rôle <span class=\"now-muted\">· 7 jours" in week
    assert '<span class="now-num">20</span> appels' in journal(week)
    # trente jours : tout ce que le registre garde, une barre par jour, resserrée
    month = drawn(client, "/admin/systeme/appels?periode=30")
    assert _bars(month) == days(30) and '<span class="now-num">66</span> appels' in month
    assert 'class="sys-calls-days-axis dense"' in month and 'class="sys-calls-days-axis dense"' not in week
    # la liste de tous les appels ne suit pas la période ; une autre de ses pages garde le choix
    second = drawn(client, "/admin/systeme/appels?periode=7&page=2")
    pager = second[second.index('id="calls-all"'):]
    assert "51–" in pager and "periode=7" in pager and "page=1" in pager
    assert '<span class="now-num">60</span> appels' in second
    # le repli sur les blocs de la vue (que lit aussi la console en MCP) : la même période, dite dans ses titres
    blocks = drawn(client, "/admin/systeme/appels?periode=7&vue_pg1=table")
    assert 'class="sys-calls-svg' not in blocks and '<nav class="seg" aria-label="période">' in blocks
    assert all(f"{t} (7 jours)" in blocks for t in ("Coût par jour", "Par jour", "Par rôle", "Par fournisseur",
                                                      "Par modèle", "Échecs", "Part du cache"))


def test_calls_page_computes_each_aggregate_once_over_one_period(world, monkeypatch):  # noqa: F811
    """La vue calcule chaque agrégat une fois, sur la même période ; la page dessinée les lit dans ses blocs, sans
    relire le registre (audit du 2026-11-05, C8-05)."""
    client, live, _ = world
    _life(client, live)
    _calls(client, live)
    seen: list[tuple[int, str]] = []
    usage = live.calls.usage

    def counted(since, **kw):
        seen.append((since, kw.get("by", "role")))
        return usage(since, **kw)

    monkeypatch.setattr(live.calls, "usage", counted)
    page = drawn(client, "/admin/systeme/appels?periode=30")
    assert 'class="sys-calls-svg' in page and "Par modèle" in page
    assert sorted(by for _since, by in seen) == ["backend", "day", "model", "role"]
    assert len({since for since, _by in seen}) == 1


def test_storage_flags_a_missing_backup_and_draws_a_bar_per_table(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/admin/systeme/stockage")
    # une phrase, un point : jamais « aucune sauvegarde notée : « mika backup ». » (audit du 2026-11-05, C8-14)
    assert page.count('<p class="sys-band tone-') == 1 and "Sauvegardes : aucune sauvegarde notée.</span>" in page
    tables = page[page.index('class="sys-store-tables"'):page.index("</ul>", page.index("sys-store-tables"))]
    assert tables.count("<li>") == 5 and "events" in tables and "now-bar sys-store-bar" in tables
    assert "Dernière vérification" in page and "restore <archive> --force" in page
    # les nombres accordés, le numéro d'un événement en « n° » (C8-14)
    assert "1 démarrage<" in page and "démarrage(s)" not in page and "événement(s)" not in page
    assert "seq " not in page and not re.search(r"\b(DOSSIER|ARCHIVES?)\b", page)
    snap = client.portal.call(live.kernel.mind.store.latest_snapshot)  # dans le fil de sa base
    assert snap is not None and f"n° {snap.seq}<" in page  # « Dernier instantané : n° 1 », plus « seq 1 »


def test_storage_gives_backup_commands_one_can_type(world, tmp_path):  # noqa: F811
    """Les commandes de la note, avec les vrais dossiers : le dossier de données, celui de la dernière archive, la
    dernière archive à vérifier ; un mot entre chevrons à la place de ce qu'on ne connaît pas, jamais « DOSSIER » ni
    « ARCHIVES » à remplir ; là où l'unité de sauvegarde est installée pour ce dossier, on sauvegarde par elle (audit du
    2026-11-05, C8-04)."""
    client, live, _ = world
    _life(client, live)
    data = tmp_path / "PROJET IA" / "data"
    never = system_pages.backup_note({"donnees": str(data)})
    assert f"« mika --data '{data}' backup <dossier des archives> --keep 14 »" in never
    assert f"« mika --data '{data}' verify <dernière archive> »" in never
    assert f"« mika --data '{data}' restore <archive> --force »" in never
    assert not re.search(r"\b(DOSSIER|ARCHIVES?)\b", never)
    last = {"archive": "/var/backups/mika/mika-20261116-033000.tar.gz", "dossier": "/var/backups/mika", "garde": 14}
    served = system_pages.backup_note({"donnees": "/var/lib/mika", "unite": "mika-backup.service", "sauvegarde": last})
    assert "« sudo systemctl start mika-backup.service »" in served
    assert "« mika --data /var/lib/mika verify /var/backups/mika/mika-20261116-033000.tar.gz »" in served
    assert "« mika --data /var/lib/mika restore <archive> --force »" in served
    by_hand = system_pages.backup_note({"donnees": "/srv/mika", "sauvegarde": {**last, "garde": 0}})
    assert "« mika --data /srv/mika backup /var/backups/mika »" in by_hand  # elle les gardait toutes
    # la page : les dossiers de ce serveur, la vérification nomme la dernière archive
    archives = tmp_path / "archives"
    backup.backup(live.data, archives, keep=3)  # sans risque serveur en marche, comme la ligne de commande
    page = drawn(client, "/admin/systeme/stockage")
    made = next(archives.glob("mika-*.tar.gz"))
    assert f"backup {shlex.quote(str(archives.resolve()))} --keep 3 »" in page
    assert f"verify {shlex.quote(str(made.resolve()))} »" in page
    assert f"la vérification rejoue la dernière archive, {made.name}, sans rien toucher" in page


def test_operator_actions_read_day_by_day(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    assert "Aucun geste audité encore" in drawn(client, "/admin/systeme/operations")
    client.portal.call(lambda: operations.audit(kernel, "console.reglages.essai", by="user_1"))
    page = drawn(client, "/admin/systeme/operations")
    feed = page[page.index('class="sys-ops-feed"'):]
    assert "console.reglages.essai" in feed and "faite" in feed and 'href="/admin/evenement/' in feed
    assert "Sur cette page : <span class=\"now-num\">1</span> geste" in page and "depuis la console" in feed


def test_every_view_has_its_place(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/admin/systeme/vues")
    views = live.kernel.registry.inspectors
    by_faculty = _pane(page, "views-faculty")
    assert all(v.title in by_faculty for v in views)
    assert by_faculty.count("<li>") == len(views)
    dest = _pane(page, "views-dest")
    assert '<a href="/admin/memoire">' in dest and "Souvenirs" in dest
    if any(v.hidden for v in views):
        assert 'id="views-hidden"' in page


def test_a_tainted_slice_says_its_event_and_the_exact_command_that_rebuilds_it(world, monkeypatch):  # noqa: F811
    """Une tranche corrompue, dans Anomalies et dans Diagnostic avancé : l'événement en « n° », la commande exacte avec
    les clés des facultés en cause, le serveur arrêté, le geste en ligne à côté, et qu'elle ne sert qu'une fois le
    réducteur corrigé ; le titre
    des replis (« modifiée au n° N ») reste lu par le dessin, qui ne retombe pas sur le repli (audit du 2026-11-05,
    C8-14)."""
    client, live, _ = world
    kernel = _life(client, live)
    mind = kernel.mind
    monkeypatch.setattr(mind, "_root", replace(mind.root, tainted=FrozenDict({"memory": 42, "social": 58})))
    for url in ("/admin/systeme/anomalies", "/admin/systeme/etat"):
        page = drawn(client, url)
        band = page[page.index('class="sys-band tone-danger"'):]
        band = band[:band.index("</p>")]
        assert "memory (au n° 42), social (au n° 58)" in band and "« mika rebuild memory social »" in band
        assert "serveur arrêté" in band and "corriger d'abord le réducteur" in band
        # et le geste en ligne, à côté de la commande (ADR 0234)
        assert "le serveur relancé sur ce code, « Reconstruire » dans la console (en ligne" in band
        assert "seq" not in band and "(« mika rebuild »)" not in page
    assert 'id="st-all"' in page and 'class="now-tag danger">corrompue au n° 42' in page  # dessinée
    # le titre des replis, relu par ``SLICE_TITLE`` : chaque tranche dit l'événement qui l'a modifiée en dernier
    assert re.search(r'modifiée au <a href="/admin/evenement/(\d+)">n° \1</a>', page)
    one = system_pages.tainted_said({"memory": 42})
    assert one.startswith("Tranche corrompue") and "Son état est figé" in one and "« mika rebuild memory »" in one


def test_the_state_gives_each_faculty_its_facts_and_its_slice_in_json(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    page = drawn(client, "/admin/systeme/etat")
    assert page.index('id="st-all"') < page.index('id="st-affect"')
    affect = _pane(page, "st-affect")
    assert "Des familles, qui dépendent de leur argument" in affect and "affect.mood" in affect
    assert "Sa tranche en JSON" in affect
    code = re.search(r'<pre class="hm-code">(.*?)</pre>', affect, re.S).group(1)
    assert code.lstrip().startswith("{") and '"' in code
    slices = page[page.index('class="sys-state-slices"'):]
    assert slices.count('<a href="#st-') >= len(live.kernel.mind.root.slices)


def test_processes_read_the_deadline_the_scheduler_kept_and_never_draw_for_the_arbiter(world, monkeypatch):  # noqa: F811
    """Seul l'ordonnanceur appelle ``next_due`` : la page lit l'échéance qu'il a retenue (``Scheduler.due``, recul
    après un échec et garde des passages à vide compris). La rendre ne fait pas le tirage de l'arbitre, que son
    ``next_due`` fait dès qu'un événement l'a invalidé."""
    client, live, _ = world
    kernel = _life(client, live)
    sched, arbiter = kernel.scheduler, kernel.arbiter
    arbiter.invalidate()
    draws = arbiter.draws
    drawn(client, "/admin/systeme/processus")
    assert (arbiter.draws, arbiter.next_at) == (draws, None), "une page de lecture ne tire rien"
    # un processus qui a échoué deux fois et attend son recul : la page dit son prochain essai, retenu par l'ordonnanceur
    # (et un processus retenu à jamais, ``2**62``, comme l'aperçu les retient : ce n'est pas une date)
    late, held = sched.specs[-1].name, sched.specs[0].name
    at = kernel.mind.clock.now() + 20 * MINUTE + 30 * US
    monkeypatch.setattr(sched, "due", {late: at, held: 2**62}.get)
    monkeypatch.setitem(sched.consecutive, late, 2)
    page = drawn(client, "/admin/systeme/processus")
    trouble = page.split('class="now-card sys-trouble"')[1].split("Par faculté")[0]
    entry = trouble[trouble.rfind("<li", 0, trouble.index(f"<code>{late}</code>")):]
    assert "prochain essai dans 20 min" in entry[:entry.index("</li>")]
    assert _title(page, late).endswith("prochaine fois : dans 20 min")
    # ce que l'ordonnanceur n'a pas daté attend un événement, ou rien
    waiting = next(s.name for s in sched.specs if s.name not in (late, held) and s.wake_on)
    assert _title(page, waiting).endswith("prochaine fois : à un événement")
    never = "à un événement" if sched.specs[0].wake_on else "rien de prévu"
    assert _title(page, held).endswith(f"prochaine fois : {never}")


def test_processes_show_a_lane_only_when_it_says_something(world, monkeypatch):  # noqa: F811
    """La voie d'un processus ne borne rien hors de la nuit (exclusive : un passage à la fois) : la page ne la montre
    que là, ni « voie fond » ni « arbitre » ailleurs — sur les cartes de ce qui ne va pas, dans la bulle de chaque
    processus, ni dans le détail de la vue en tableau."""
    client, live, _ = world
    kernel = _life(client, live)
    sched = kernel.scheduler
    night = "self.dream"
    plain = next(s.name for s in sched.specs if not s.lane or s.lane == "background")
    for name in (night, plain):  # deux processus en échec : leurs cartes montrent leurs faits
        monkeypatch.setitem(sched.consecutive, name, 2)
    page = drawn(client, "/admin/systeme/processus")
    assert "voie fond" not in page and "voie arbitre" not in page and "voie</span> fond" not in page
    assert " · voie nuit (une à la fois) · " in _title(page, night)
    assert "voie" not in _title(page, plain) and "voie" not in _title(page, "arbitre")
    trouble = page.split('class="now-card sys-trouble"')[1].split("Par faculté")[0]

    def card(name: str) -> str:
        code = trouble.index(f"<code>{name}</code>")
        return trouble[trouble.rfind("<li", 0, code):code]

    assert '<span class="k">voie</span> nuit (une à la fois)' in card(night)
    assert '<span class="k">voie</span>' not in card(plain)
    # la vue en tableau : la voie, repliée dans le détail, ne dit « fond » pour personne
    table = drawn(client, "/admin/systeme/processus?vue_pg1=table")
    assert "nuit (une à la fois)" in table and not re.search(r"<dt>voie</dt><dd>(<[^>]+>)*(fond|arbitre)<", table)
    # son état, accordé : « 2 échecs d’affilée », jamais « échec(s) » (audit du 2026-11-05, C8-14)
    assert "2 échecs d’affilée" in table and "échec(s)" not in table


def _title(page: str, process: str) -> str:
    """La bulle d'un processus dans sa carte de faculté (« nom · voie · passages · prochaine fois : … »)."""
    start = page.index(f'title="{process} · ') + len('title="')
    return page[start:page.index('"', start)]
