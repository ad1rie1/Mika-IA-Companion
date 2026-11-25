"""Relations & échanges › Agendas (ADR 0309, lot 5), à travers le vrai serveur composé : la semaine de tout le monde
(un événement privé d'une autre personne reste « Occupé · privé »), le mois, la liste, un événement ouvert ; les
comptes, dont un compte branché jamais relu, « à reconnecter » en un seul bandeau ; ce qu'elle propose d'ajouter,
hachuré, et ce qui en mène à « À valider » ; la fiche d'un agenda et ses gestes — retirer un partage, ne plus suivre un
agenda, déconnecter un compte —, aucun n'écrivant dans un agenda ; son tableau de droits réglé dans Réglages › Droits ;
l'onglet « Agendas » de la fiche d'une personne."""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from mika.adapters.agenda import AgendaAccount, AgendaConfig
from mika.app.domains.agenda.settings import AgendaSettings
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.kernel.inspect import Table
from mika.plugins.agenda import CAPABILITY, OWNER
from mika.ports.agenda import Calendar, Event, Span, us_of
from mika.runtime.inspection import Inspection
from tests.protocol.test_drawn_fiches import form_of
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_moi_agenda import create, mine
from tests.protocol.test_moi_mail import API, append, login, post, second_person
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _between(page: str, start: str, end: str) -> str:
    return page.split(start, 1)[1].split(end, 1)[0]


def _tomorrow() -> date:
    return date.today() + timedelta(days=1)


def _week(day: date) -> str:
    return (day - timedelta(days=day.weekday())).isoformat()


def _people(client, live) -> tuple[str, str]:
    """Adrien (l'opérateur) et Léa ; un rendez-vous à chacun demain, celui de Léa privé ; Adrien partage son agenda
    avec Léa. La session reste celle d'Adrien."""
    bootstrap(client)
    adrien = mine(client)
    assert create(client, adrien, "Revue du budget", hour=14, location="Bureau de Marc").status_code == 200
    lea = second_person(client, live)
    login(client, "lea")
    lea_cal = mine(client)
    assert create(client, lea_cal, "Entretien secret", hour=9, private=True).status_code == 200
    assert create(client, lea_cal, "Yoga", hour=19).status_code == 200
    login(client, "adrien")
    assert post(client, "/shares/set", {"kind": "agenda", "key": adrien, "person": lea, "level": "preparer"}) \
        .status_code == 200
    return adrien, lea_cal


def test_the_week_of_everyone_keeps_a_private_event_private(world):  # noqa: F811
    client, live, _ = world
    adrien, lea_cal = _people(client, live)
    page = drawn(client, "/admin/agendas/tous?du=" + _week(_tomorrow()))
    week = _between(page, 'class="agc-week"', '<aside') if "<aside" in page else _between(page, 'class="agc-week"',
                                                                                             "</main>")
    assert "Revue du budget" in week and "Yoga" in week
    assert "Occupé · privé" in week and "Entretien secret" not in page  # ni son titre, ni dans une info-bulle
    legend = _between(page, 'class="agc-side-body"', "</details>")
    assert legend.index("Toi") < legend.index("Léa") and 'data-agc-leg="mika"' in legend
    assert 'href="/admin/agendas/parametres"' in page  # la roue (ADR 0206)
    assert 'aria-label="Affichage"' in page and ">Mois</a>" in page  # le bouton à choix au bout de la barre
    # « Les agendas de » : une personne choisie ne montre que ses agendas
    lea_only = drawn(client, f"/admin/agendas/tous?du={_week(_tomorrow())}&qui=" + lea_cal.split(":")[1].split("~")[0])
    assert "Revue du budget" not in _between(lea_only, 'class="agc-week"', "</main>") and "Yoga" in lea_only
    # le mois, la liste
    month = drawn(client, f"/admin/agendas/tous?vue=mois&du={_tomorrow().isoformat()}")
    assert 'class="agc-month"' in month and "Revue du budget" in month
    listed = drawn(client, f"/admin/agendas/tous?vue=liste&du={_tomorrow().isoformat()}")
    assert 'class="agc-plan"' in listed and "Occupé · privé" in listed and "Entretien secret" not in listed
    # un événement ouvert : son agenda, à qui, son compte ; ce qu'elle en a fait (rien encore, ou son rappel prévu)
    ev = re.search(r'href="(\?[^"]*ev=[^"]+)"[^>]*title="Revue du budget', html.unescape(page))
    assert ev is not None
    opened = drawn(client, "/admin/agendas/tous" + ev.group(1))
    reader = _between(opened, 'class="now-card agc-reader"', "</aside>")
    assert "Revue du budget" in reader and "Mon agenda" in reader and "Bureau de Marc" in reader
    assert f'/admin/fiche/agenda/{quote(adrien, safe="")}' in reader


def test_an_operator_who_is_not_the_owner_reads_her_private_events_busy(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    adrien = mine(client)
    assert create(client, adrien, "Psy", hour=9, private=True).status_code == 200
    assert create(client, adrien, "Revue du budget", hour=14).status_code == 200
    client.portal.call(lambda: live.accounts.create("marc", "un-mot-de-passe-long", operator=True,
                                                    full_name="Marc Durand"))
    week = "/admin/agendas/tous?du=" + _week(_tomorrow())
    assert "Psy" in drawn(client, week)  # la propriétaire lit le sien
    login(client, "marc")  # un opérateur qui n'est pas elle : « à toi » est à elle, pas à lui
    for view in ("", "&vue=liste"):
        page = drawn(client, week + view)
        assert "Revue du budget" in page and "Occupé · privé" in page and "Psy" not in page, view
    [shown] = [c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["primary"]]
    assert create(client, shown["key"], "Kiné", hour=11, private=True).status_code == 200
    assert "Kiné" in drawn(client, week)  # le sien, il le lit


def test_the_week_lists_the_whole_days_of_its_own_days_only(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    monday = date.fromisoformat(_week(_tomorrow()))
    for title, day in (("Fête de la veille", monday - timedelta(days=1)), ("Grève du lundi", monday)):
        made = post(client, "/agenda/event/create", {"calendar": cal, "title": title, "start": day.isoformat(),
                                                     "end": day.isoformat(), "all_day": True})
        assert made.status_code == 200, made.text
    for view in ("", "&vue=liste"):
        page = drawn(client, f"/admin/agendas/tous?du={monday.isoformat()}{view}")
        assert "Grève du lundi" in page and "Fête de la veille" not in page, view
    inspection = Inspection(live.kernel)  # la vue de la console lue sans son dessin (son serveur MCP) : « Du … (N) »
    blocks = client.portal.call(lambda: inspection.run(inspection.find("agenda", "tous"), {"du": monday.isoformat()}))
    [listed] = [b for b in blocks if isinstance(b, Table)]
    assert listed.title.endswith("(1)") and len(listed.rows) == 1


def test_a_plugged_account_never_read_is_the_one_banner_and_its_line_says_so(world):  # noqa: F811
    client, live, _ = world
    _people(client, live)
    settings = live.settings
    cfg = _agenda(client, live)
    client.portal.call(settings.of(AgendaSettings).save_agenda, AgendaConfig(accounts={
        **cfg.accounts, "outlook": AgendaAccount(kind="microsoft", label="Outlook.com",
                                                 address="adrien@outlook.fr")}))
    client.portal.call(live.reconfigure)
    accounts = drawn(client, "/admin/agendas/comptes")
    assert "Outlook.com" in accounts and "à reconnecter" in accounts and "jamais été relu" in accounts
    assert 'class="agc-acc"' in accounts and "Ce serveur" in accounts
    tous = drawn(client, "/admin/agendas/tous")
    assert tous.count('class="note warn"') == 1 and "Outlook.com (à toi) est à reconnecter" in tous
    assert re.search(r'href="/admin/agendas/comptes"[^>]*>Comptes<span class="count"[^>]*>1</span>', tous)


def test_what_she_proposes_is_hatched_and_leads_to_the_queue(world):  # noqa: F811
    client, live, _ = world
    adrien, _lea = _people(client, live)
    start = us_of(datetime.combine(_tomorrow(), time(20)).astimezone())
    args = {"op": "ajouter", "calendar": adrien, "keep": "perso", "target": "user_1", "ref": "chat:user_1",
            "starts": start, rt.DECIDER: "user_1",
            "draft": {"title": "Dîner chez Léa", "span": {"start": start, "end": start + 3 * 3600 * 10**6,
                                                           "zone": "Europe/Paris", "all_day": False},
                      "location": "Chez Léa", "description": "", "rule": "", "invite": []}}
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability=CAPABILITY, owner=OWNER, args_json=json.dumps(args, sort_keys=True),
        summary=Content.of("Je l'ajoute à Mon agenda ?"), approval=True, context="user_1", about=("user_1",))])
    page = drawn(client, "/admin/agendas/tous?du=" + _week(_tomorrow()))
    hatched = re.search(r'<a class="agc-ev [^"]*\bprop\b[^"]*" href="([^"]+)"', page)
    assert hatched is not None and "Dîner chez Léa" in page
    opened = drawn(client, "/admin/agendas/tous" + html.unescape(hatched.group(1)))
    reader = _between(opened, 'class="now-card agc-reader"', "</aside>")
    assert "elle propose de l'ajouter" in reader and "/admin/approbations/en_attente?demande=" in reader
    done = drawn(client, "/admin/agendas/fait")
    assert "Dîner chez Léa" in _between(done, 'id="propositions"', "</section></section>")
    assert re.search(r">Ce qu'elle en fait<span class=\"count\"[^>]*>1</span>", done)
    queue = drawn(client, "/admin/approbations/en_attente")
    sources = _between(queue, 'class="apv-sources"', "</p>")
    assert "L'agenda « Mon agenda »" in sources and "Dans la semaine" in sources


def _agenda(client, live) -> AgendaConfig:
    """Les comptes d'agenda tels que les réglages les gardent, lus dans la boucle du serveur."""
    return client.portal.call(live.settings.of(AgendaSettings).agenda)


def _subscription(client, live) -> str:
    """Un abonnement à Adrien, déjà relu une fois : son agenda et un jour férié dans la base."""
    settings, store = live.settings, live.kernel.ports["agenda"]
    cfg = _agenda(client, live)
    client.portal.call(settings.of(AgendaSettings).save_agenda, AgendaConfig(accounts={
        **cfg.accounts, "feries": AgendaAccount(kind="ical", label="Jours fériés", url="https://example.test/f.ics")}))
    client.portal.call(live.reconfigure)
    store.keep_account("feries", "ical")
    store.add_calendar(Calendar("feries~fr", "feries", "f", "Jours fériés", primary=True))
    day = us_of(datetime.combine(_tomorrow(), time()).astimezone())
    store.save([Event("feries~fr", "ferie-1", Span(day, day + 24 * 3600 * 10**6, all_day=True), "Un jour férié")])
    return "feries~fr"


def test_the_fiche_of_a_calendar_and_what_the_operator_may_do(world):  # noqa: F811
    client, live, _ = world
    adrien, _lea = _people(client, live)
    fiche = drawn(client, f"/admin/fiche/agenda/{quote(adrien, safe='')}")
    assert "<h1>Mon agenda</h1>" in fiche and "partagé · 1" in fiche and "Revue du budget" in fiche
    assert 'data-tab="agenda/evenements"' in fiche
    # un agenda du système : rien à synchroniser, rien à déconnecter ni à retirer de Mika
    assert "/admin/action/agenda.relire" not in fiche and "/admin/action/agenda.retirer" not in fiche
    shares = drawn(client, f"/admin/fiche/agenda/{quote(adrien, safe='')}?onglet=partages")
    form = _between(shares, 'action="/admin/reglages/droits/partages"', "</form>")
    assert 'name="kind" value="agenda"' in form and "Lire et préparer" in shares
    rights = drawn(client, f"/admin/fiche/agenda/{quote(adrien, safe='')}?onglet=droits")
    assert "Qui peut quoi sur Mon agenda" in rights and "regler=1" in rights
    sync = drawn(client, f"/admin/fiche/agenda/{quote(adrien, safe='')}?onglet=synchro")
    assert "rien à relire" in sync
    # un abonnement : le retirer de Mika (sa copie part, rien chez lui), puis déconnecter son compte (décoché)
    feries = _subscription(client, live)
    page = drawn(client, f"/admin/fiche/agenda/{quote(feries, safe='')}")
    assert "Un jour férié" in page and "/admin/action/agenda.relire" in page
    before = sum(1 for e in live.kernel.ports["agenda"].period([adrien], 0, 2**62))
    data = form_of(page, "agenda.retirer")
    got = client.post("/admin/action/agenda.retirer", data=data)
    assert got.status_code in (200, 303), got.text
    assert _agenda(client, live).accounts["feries"].calendars["fr"].followed is False
    assert live.kernel.ports["agenda"].event_counts([feries])[feries] == 0
    page = drawn(client, f"/admin/fiche/agenda/{quote(feries, safe='')}")
    data = form_of(page, "agenda.deconnecter")
    assert client.post("/admin/action/agenda.deconnecter", data=data).status_code in (200, 303)
    assert _agenda(client, live).accounts["feries"].enabled is False
    # rien n'a été écrit dans un agenda : celui d'Adrien a toujours ses événements
    assert sum(1 for e in live.kernel.ports["agenda"].period([adrien], 0, 2**62)) == before
    audited = [json.loads(e.data).get("action", "") for e in client.portal.call(
        lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 50))]
    assert "agenda.retirer" in audited and "agenda.deconnecter" in audited


def test_an_operator_sets_the_table_of_a_calendar_in_rights(world):  # noqa: F811
    client, live, _ = world
    adrien, _lea = _people(client, live)
    detail = f"agenda:{adrien}"
    page = drawn(client, "/admin/reglages/droits?detail=" + quote(detail, safe="") + "&regler=1")
    form = _between(page, 'action="/admin/reglages/droits/agenda"', "</form>")
    csrf = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
    data = {"csrf": csrf, "cle": adrien, "ligne.1": "1", "qui.1|proprietaire": "on", "toujours.1": "on",
            "lire.1": "oui", "ecrire.1": "seule", "repondre.1": "accord", "garde.1": "rien",
            "defaut_lire": "non", "defaut_ecrire": "non", "defaut_repondre": "non", "defaut_garde": "rien",
            "faire": ""}
    got = client.post("/admin/reglages/droits/agenda", data=data, follow_redirects=False)
    assert got.status_code == 303 and "regler=1" in got.headers["location"]
    table = client.portal.call(live.settings.agenda_tables)[adrien]
    assert len(table.lines) == 1 and table.lines[0].write == "seule" and table.lines[0].respond == "accord"
    again = drawn(client, got.headers["location"])
    assert "Revenir au minimum vital" in again  # réglé : on peut revenir au tableau de départ
    data["faire"] = "remettre"
    client.post("/admin/reglages/droits/agenda", data=data, follow_redirects=False)
    assert adrien not in client.portal.call(live.settings.agenda_tables)


def test_the_agendas_tab_of_a_person(world):  # noqa: F811
    client, live, _ = world
    _adrien, _lea = _people(client, live)
    page = drawn(client, "/admin/fiche/person/user_2?onglet=agendas")
    assert 'data-tab="person/agendas"' in page
    received = _between(page, "Ce qu'on lui partage", "</section>")
    assert "Ses agendas" in page and "Mon agenda</a>, de toi" in received and 'name="kind" value="agenda"' in received
    assert re.search(r'>Agendas<span class="tab-n now-num">\d+</span>', page)


def test_her_agenda_tab_carries_her_name_from_her_persona(world):  # noqa: F811
    """L'onglet de son agenda porte son nom, lu dans sa persona au rendu (``self_.NAME_SLOT``, ADR 0070) : renommée
    dans Réglages › Identité, la barre d'onglets, le titre de la page et le menu la suivent ; le repère ne se voit
    jamais."""
    client, _live, _ = world
    bootstrap(client)
    tab = r'href="/admin/agendas/mika"[^>]*>(?:\s|<[^>]+>)*L\'agenda de {}'
    assert re.search(tab.format("Mika"), drawn(client, "/admin/agendas/tous"))
    renamed = client.post("/admin/reglages/identite", data={
        "csrf": client.cookies.get("csrftoken"), "_section": "personnage", "_champs": ["name"], "name": "Aya"})
    assert renamed.status_code == 200
    for url in ("/admin/agendas/tous", "/admin/agendas/mika"):
        page = drawn(client, url)
        assert re.search(tab.format("Aya"), page) and "L'agenda de Mika" not in page and "{nom}" not in page, url
    assert re.search(r"<h1[^>]*>\s*L'agenda de Aya", drawn(client, "/admin/agendas/mika"))
