"""L'annuaire dans la console (ADR 0298), à travers le vrai serveur : Personnes › Annuaire réunit qui lui parle et qui
elle connaît de loin (personnes et organisations), avec « Qui », une recherche et « Contacts de… » ; la fiche d'un
contact et celle d'une organisation ; « Ce qui l'identifie » et « Contacts » sur la fiche d'une personne ; À valider ›
Rapprochements ; et les gestes — réunir, relier, délier, détacher, écarter, oublier —, audités, qui ne font jamais
d'une personne connue de loin une interlocutrice."""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.app.domains.teams.settings import TeamsSettings
from mika.contracts import runtime as rt
from mika.ports.contacts import COMPANY, EMAIL, MAIL, PHONE, TEAMS, TEAMS_ID, Observation
from mika.vocab.access import SELF
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_console_files import _events
from tests.protocol.test_drawn_fiches import drawn, form_of
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ADRIEN = "user_1"
GILLES = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab"
HOUR = 3_600_000_000
ANNUAIRE = "/admin/personnes/personnes"


def fiche(cid: int, tab: str = "") -> str:
    return f"/admin/fiche/contact/{quote(f'contact:{cid}', safe='')}" + (f"?onglet={tab}" if tab else "")


def seed(client, live) -> dict[str, int]:
    """Un compte Teams à toi (« Équipe »), une boîte à elle (« Personnel ») ; Gilles, de Nordis, vu dans Teams et
    par son profil (e-mail, numéro, entreprise), une adresse générique de Nordis, et « G. Rousseau » dans sa boîte à
    elle (un rapprochement)."""
    client.portal.call(lambda: live.settings.of(TeamsSettings).save_teams(TeamsConfig(accounts={"equipe": TeamsAccount(label="Équipe")})))
    client.portal.call(lambda: live.settings.save_email(MailConfig(accounts={"perso": MailAccount(
        label="Personnel", address="mika@example.test", enabled=False, owner=SELF)})))
    store = live.kernel.ports["contacts"]
    now = live.kernel.mind.frame().now
    team, hers = (TEAMS, "equipe"), (MAIL, "perso")
    client.portal.call(lambda: store.observe([
        Observation(TEAMS_ID, GILLES, *team, "Gilles ROUSSEAU", 48, now - 40 * 24 * HOUR, now - 2 * HOUR,
                    title="Responsable réseau"),
        Observation(EMAIL, "gilles.rousseau@nordis.fr", *team, "Gilles ROUSSEAU", 0, now - HOUR, now - HOUR,
                    joins=(TEAMS_ID, GILLES), proof=True),
        Observation(PHONE, "+33612345678", *team, "Gilles ROUSSEAU", 0, now - HOUR, now - HOUR,
                    joins=(TEAMS_ID, GILLES)),
        Observation(COMPANY, "Nordis", *team, "Nordis", 0, now - HOUR, now - HOUR, joins=(TEAMS_ID, GILLES)),
        Observation(EMAIL, "support@nordis.fr", *hers, "Support Nordis", 5, now - 3 * HOUR, now - 3 * HOUR),
        Observation(EMAIL, "g.rousseau@gmail.com", *hers, "G. Rousseau", 3, now - 9 * HOUR, now - 4 * HOUR),
    ]))
    gilles = store.contact_of(TEAMS_ID, GILLES)
    other = store.contact_of(EMAIL, "g.rousseau@gmail.com")
    org = store.contact_of(EMAIL, "support@nordis.fr")
    assert gilles and other and org and gilles != other
    return {"gilles": gilles, "other": other, "org": org}


def _entry(page: str, name: str) -> str:
    """L'entrée d'une personne de l'annuaire : de son nom à la fin de son élément de liste."""
    return page.split(f">{name}</a></span>", 1)[1].split('class="pers-dir-item"', 1)[0]


def test_the_directory_lists_who_talks_to_her_and_who_she_knows_from_afar(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    ids = seed(client, live)
    page = drawn(client, ANNUAIRE)
    assert 'data-tab="personnes/personnes"' in page
    # « Qui » au bout de la barre d'onglets, ses quatre choix, « Tout » marqué
    seg = re.search(r'<nav class="seg" aria-label="Qui">(.*?)</nav>', page, re.S).group(1)
    assert [c for c in re.findall(r">([^<]+)</a>", seg)] == ["Tout", "Lui parlent", "Connues de loin",
                                                             "Organisations"]
    assert 'aria-current="true">Tout<' in seg and '<form class="filters"' not in page
    # qui lui parle, connue de loin, organisation : chacun une fois
    assert 'href="/admin/fiche/person/user_1"' in page
    gilles = _entry(page, "Gilles ROUSSEAU")
    assert "connue de loin" in gilles and f'href="{fiche(ids["org"])}"' in gilles and ">Nordis<" in gilles
    assert "Responsable réseau" in gilles  # ce qu'elle en sait, en une ligne
    assert "gilles.rousseau@nordis.fr" in gilles and "+33612345678" in gilles and "8:orgid:7c2e41d0" in gilles
    assert "Teams · <b>48</b>" in gilles  # d'où elle le connaît, combien
    assert re.search(r'contact de</span> <a href="/admin/fiche/person/user_1\?onglet=contacts">adrien</a>', gilles)
    nordis = _entry(page, "Nordis")
    assert "organisation" in nordis and "1 personne" in nordis and "nordis.fr" in nordis
    rousseau = _entry(page, "G. Rousseau")
    assert "contact de</span> tout le monde" in rousseau  # sa boîte à elle : à tout le monde
    assert "1 lui parle · 2 connues de loin · 1 organisation" in page
    # les puces « Contacts de… »
    assert ">Contacts d'adrien <span class=\"hm-count\">2</span>" in page
    assert ">À tout le monde <span class=\"hm-count\">2</span>" in page


def test_the_directory_filters_by_who_searches_and_by_whose_contacts(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    seed(client, live)
    far = drawn(client, f"{ANNUAIRE}?qui=loin")
    assert "Gilles ROUSSEAU" in far and "G. Rousseau" in far and 'href="/admin/fiche/person/user_1"' not in far
    assert ">Nordis</a></span>" not in far
    orgs = drawn(client, f"{ANNUAIRE}?qui=organisations")
    assert ">Nordis</a></span>" in orgs and "G. Rousseau" not in orgs
    talks = drawn(client, f"{ANNUAIRE}?qui=lui_parlent")
    assert 'href="/admin/fiche/person/user_1"' in talks and "Gilles ROUSSEAU" not in talks
    # une recherche par nom, e-mail, téléphone ou identifiant ; « Qui » la garde
    for q in ("nordis", "33612345678", "7c2e41d0", "rousseau@nordis"):
        found = drawn(client, f"{ANNUAIRE}?q={quote(q)}")
        assert "Gilles ROUSSEAU" in found and 'href="/admin/fiche/person/user_1"' not in found, q
    kept = drawn(client, f"{ANNUAIRE}?q=rousseau")
    seg = re.search(r'<nav class="seg" aria-label="Qui">(.*?)</nav>', kept, re.S).group(1)
    assert "q=rousseau" in seg
    # les contacts d'adrien : ceux de son Teams, pas ceux de sa boîte à elle
    mine = drawn(client, f"{ANNUAIRE}?de=user_1")
    assert "Gilles ROUSSEAU" in mine and "G. Rousseau" not in mine
    everyone = drawn(client, f"{ANNUAIRE}?de=tous")
    assert "G. Rousseau" in everyone and "Gilles ROUSSEAU" not in everyone
    # en tableau
    table = drawn(client, f"{ANNUAIRE}?affichage=tableau")
    assert 'class="hm-table"' in table and "Gilles ROUSSEAU" in table and "connue de loin" in table


def test_a_contact_sheet_says_where_she_sees_them_and_whose_contact_they_are(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    ids = seed(client, live)
    page = drawn(client, fiche(ids["gilles"]))
    assert "<h1>Gilles ROUSSEAU</h1>" in page and "connue de loin" in page and "ne lui a jamais écrit" in page
    # le bandeau unique : un rapprochement à valider, qui mène à la file
    assert "<b>« G. Rousseau »</b> (g.rousseau@gmail.com) porte presque le même nom" in page
    assert f'/admin/approbations/rapprochements?element=rapprochement%3A{min(ids["gilles"], ids["other"])}-' in page
    assert "Où elle voit Gilles ROUSSEAU" in page and "48 messages" in page
    assert "De qui Gilles ROUSSEAU est le contact" in page and "ne se dit qu'à adrien" in page
    assert "ce n'est pas quelqu'un à qui elle parle" in page
    assert "Responsable réseau" in page  # ce qu'elle en sait : ses profils, pas une mémoire inventée
    # ses gestes : « Réunir avec… » en vue, « Oublier » sous « ⋯ »
    assert 'action="/admin/action/contacts.reunir"' in page and "/admin/oublier/contact/" in page
    # ce qui l'identifie : une tuile par identifiant, « Détacher »
    tab = drawn(client, fiche(ids["gilles"], "identifiants"))
    assert tab.count('class="id-tile"') == 3 and "Identifiant Teams" in tab and "Téléphone" in tab
    assert "Réuni d'office : la même adresse sur son profil Teams." in tab
    assert form_of(tab, "contacts.detacher")["_sujet"] == [f"contact:{ids['gilles']}"]
    # une personne n'a pas l'onglet « Personnes » ; une organisation, si
    assert "onglet=membres" not in page
    org = drawn(client, fiche(ids["org"]))
    assert "organisation" in org and "Ses personnes" in org and "Gilles ROUSSEAU" in org
    assert "Ses adresses sans personne derrière" in org and "support@nordis.fr" in org
    assert "onglet=membres" in org


def test_rapprochements_wait_in_the_queue_and_are_decided_there(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    ids = seed(client, live)
    queue = drawn(client, "/admin/approbations/rapprochements")
    assert "« Gilles ROUSSEAU » et « G. Rousseau » : la même personne ?" in queue or \
        "« G. Rousseau » et « Gilles ROUSSEAU » : la même personne ?" in queue
    assert 'class="pair"' in queue and "Aucun identifiant en commun" in queue
    every = client.get("/admin/approbations").text
    assert "Rapprochement" in html.unescape(every)  # compté dans « Tout ce qui attend »
    apart = form_of(queue, "contacts.ecarter")
    done = client.post("/admin/action/contacts.ecarter", data=apart, follow_redirects=False)
    assert done.status_code == 303
    store = live.kernel.ports["contacts"]
    assert store.suggestions() == []
    assert "Aucune fiche n'en rappelle une autre" in drawn(client, "/admin/approbations/rapprochements")
    audit = [e.data for e in _events(client, live, rt.OPERATED)]
    assert [(a.action, a.outcome) for a in audit] == [("contacts.ecarter", "done")]
    assert ids["gilles"] != ids["other"]


def test_the_same_person_merges_from_the_queue(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    ids = seed(client, live)
    queue = drawn(client, "/admin/approbations/rapprochements")
    same = form_of(queue, "contacts.rapprocher")
    done = client.post("/admin/action/contacts.rapprocher", data=same, follow_redirects=False)
    assert done.status_code == 303
    store = live.kernel.ports["contacts"]
    # la plus vue garde l'autre : Gilles (48 fois) prend l'adresse de « G. Rousseau »
    assert store.contact_of(EMAIL, "g.rousseau@gmail.com") == ids["gilles"]
    assert store.sheet(ids["other"]) is None


def test_link_detach_unlink_from_a_contact_sheet(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    ids = seed(client, live)
    store = live.kernel.ports["contacts"]
    page = drawn(client, fiche(ids["gilles"], "identifiants"))
    # détacher le numéro : il fait une fiche à lui
    phone = next(i for i in store.sheet(ids["gilles"]).identifiers if i.kind == PHONE)
    form = form_of(page, "contacts.detacher", having=str(phone.id))
    done = client.post("/admin/action/contacts.detacher", data=form, follow_redirects=False)
    assert done.status_code == 303
    assert store.contact_of(PHONE, "+33612345678") not in (None, ids["gilles"])
    # relier Gilles à adrien (« Réunir avec… », la personne) : il paraît comme lui dans l'annuaire
    merge = form_of(drawn(client, fiche(ids["gilles"])), "contacts.reunir")
    done = client.post("/admin/action/contacts.reunir", data={**merge, "personne": ["user_1"], "fiche": [""]},
                       follow_redirects=False)
    assert done.status_code == 303
    assert store.sheet(ids["gilles"]).person == ADRIEN
    listed = drawn(client, ANNUAIRE)
    assert f'href="{fiche(ids["gilles"])}"' not in listed  # une seule entrée : adrien, ses identifiants ajoutés
    assert "gilles.rousseau@nordis.fr" in _entry(listed, "adrien")
    # sa fiche › Ce qui l'identifie : ses identifiants de l'annuaire, « Détacher » au nom de la fiche du contact
    mine = drawn(client, "/admin/fiche/person/user_1?onglet=adresses")
    assert "Identifiant de compte" in mine and "gilles.rousseau@nordis.fr" in mine
    assert form_of(mine, "contacts.detacher")["_sujet"] == [f"contact:{ids['gilles']}"]
    # délier
    unlink = form_of(drawn(client, fiche(ids["gilles"])), "contacts.delier")
    done = client.post("/admin/action/contacts.delier", data=unlink, follow_redirects=False)
    assert done.status_code == 303 and store.sheet(ids["gilles"]).person == ""
    audit = [(e.data.action, e.data.outcome) for e in _events(client, live, rt.OPERATED)]
    assert audit == [("contacts.detacher", "done"), ("contacts.reunir", "done"), ("contacts.delier", "done")]


def test_a_person_has_her_contacts_tab_shares_included(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    ids = seed(client, live)
    tab = drawn(client, "/admin/fiche/person/user_1?onglet=contacts")
    # ses contacts : son Teams, et la boîte à elle (à tout le monde)
    assert "Les contacts d'adrien" in tab and "Gilles ROUSSEAU" in tab and "G. Rousseau" in tab
    assert ">Nordis</a></span>" in tab
    head = client.get("/admin/fiche/person/user_1").text
    assert "Contacts" in head and "onglet=contacts" in head
    ConsoleHTML(head).check()
    assert ids


def test_forgetting_a_contact_reaches_what_teams_and_mail_kept(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    ids = seed(client, live)
    page = drawn(client, fiche(ids["gilles"]))
    form = re.search(r'<form[^>]+action="(/admin/oublier/contact/[^"]+)".*?</form>', page, re.S)
    data = {name: [html.unescape(value)] for name, value in
            re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(0))}
    reached: list[str] = []
    teams = live.kernel.ports["teams"]
    original = teams.forget

    async def spy(subject: str) -> int:
        reached.append(subject)
        return await original(subject)

    teams.forget = spy
    try:
        done = client.post(form.group(1), data={**data, "_confirmer": ["Gilles ROUSSEAU"]}, follow_redirects=False)
    finally:
        teams.forget = original
    assert done.status_code == 303
    store = live.kernel.ports["contacts"]
    assert store.sheet(ids["gilles"]) is None and store.contact_of(TEAMS_ID, GILLES) is None
    assert f"teams:{GILLES}" in reached and "mail:gilles.rousseau@nordis.fr" in reached
    audit = [(e.data.action, e.data.subject) for e in _events(client, live, rt.OPERATED)]
    assert audit == [("console.oublier.contact", f"contact:{ids['gilles']}")]


def test_a_contact_known_from_afar_is_never_an_interlocutor(world):  # noqa: F811
    """Connaître n'est pas parler : une fiche de l'annuaire ne paraît ni dans la vue d'ensemble des personnes, ni dans
    Liens, ni dans les conversations, ni parmi les personnes que la recherche des fiches trouve."""
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    seed(client, live)
    for url in ("/admin/personnes", "/admin/personnes/liens", "/admin/fil", "/admin/recherche?q=rousseau&sorte=person"):
        page = html.unescape(client.get(url, follow_redirects=True).text)
        assert "Gilles ROUSSEAU" not in page, url
    assert "Gilles ROUSSEAU" in html.unescape(client.get("/admin/recherche?q=rousseau").text)  # parmi les contacts
