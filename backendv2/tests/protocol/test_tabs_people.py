"""Relations & échanges › Personnes, chaque onglet dans sa forme (``app/handmade/tabs/people.py``, ADR 0177), à travers
le vrai serveur : l'annuaire dit chaque personne par ses moyens de communication, les liens se rangent par proximité
avec leur silence sur une jauge, les présents se lisent une personne à la fois, ses connexions sous elle."""

from __future__ import annotations

from mika.app.handmade.tabs import people
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.social import inspect as social_inspect
from mika.kernel.events import Content, Origin
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _between(page: str, start: str, end: str) -> str:
    return page.split(start, 1)[1].split(end, 1)[0]


def emit(client, live, owner: str, drafts, origin=Origin.GENESIS) -> None:
    client.portal.call(lambda: live.kernel.mind.append(drafts, emitter=owner, origin=origin, correlation="test-tabs"))


def stranger(client, live, handle: str, name: str, text: str = "salut Mika") -> None:
    """Quelqu'un écrit d'un canal extérieur (sans réponse : le message seul, au journal)."""
    emit(client, live, "runtime", [rt.PERCEPTION_RECEIVED.draft(handle=handle, channel="external", display_name=name,
                                                                text=Content.of(text))], Origin.EXTERNAL)


def test_a_cell_names_the_person_its_link_leads_to():
    assert people.person_of({"t": "link", "href": "/admin/fiche/person/user_2?onglet=lien"}) == "user_2"
    assert people.person_of({"t": "link", "href": "/admin/fiche/person/name%3Alea"}) == "name:lea"
    assert people.person_of({"t": "link", "href": "/admin/fiche/handle/user_2"}) == ""
    assert people.person_of(None) == ""


def test_the_directory_says_each_person_by_her_means_of_communication(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    stranger(client, live, "ext_12", "Adrien T")
    emit(client, live, "identity", [identity_c.LINKED.draft(handle="ext_12", person="user_1", by="operator")],
         Origin.EXTERNAL)
    page = drawn(client, "/admin/personnes/personnes")
    assert 'data-tab="personnes/personnes"' in page
    entry = _between(page, 'class="pers-dir-item"', "</li>\n")
    # dite comme sur la vue d'ensemble : son nom, propriétaire ; puis ses moyens de communication, le principal d'abord
    assert 'href="/admin/fiche/person/user_1"' in entry and "propriétaire" in entry
    handles = _between(entry, 'class="pers-handles"', "</ul>")
    assert handles.index("adrien · compte opérateur") < handles.index("compte extérieur")
    assert "authentifiée" in handles and "principal" in handles
    assert 'href="/admin/fiche/handle/ext_12"' in handles
    assert "lui a écrit" in entry and "certitude" in entry
    assert 'href="/admin/fiche/person/user_1?onglet=echanges"' in entry
    assert "1 avec plusieurs moyens de communication" in page
    assert 'href="?vue_pg1=table"' in page  # la bascule « Tableau » de la faculté
    # il se parcourt : on cherche quelqu'un depuis la vue d'ensemble, une ancienne recherche n'a plus d'effet
    assert '<form class="filters"' not in page
    old = drawn(client, "/admin/personnes/personnes?q=personne-inconnue")
    assert 'href="/admin/fiche/person/user_1"' in old and "ne correspond" not in old


def test_links_go_by_closeness_with_the_silence_on_a_gauge(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    stranger(client, live, "ext_7", "Léa Martin")
    emit(client, live, "social", [social_c.CLOSENESS_SET.draft(person="ext_7", closeness=social_c.CLOSE)])
    page = drawn(client, "/admin/personnes/liens")
    assert 'data-tab="personnes/liens"' in page
    groups = _between(page, 'id="pers-bonds-title"', "</section>\n</div>")
    # du plus proche au plus lointain : Léa (déclarée proche) avant Adrien (une amitié, son plancher de propriétaire)
    assert groups.index(">Proches") < groups.index("Léa Martin") < groups.index(">Amitiés") < groups.index("adrien")
    assert "déclarée par un opérateur" in groups and "au moins « amitié », car c'est sa propriétaire" in groups
    assert 'class="pers-gauge"' in groups and 'class="mid"' in groups  # la moitié de la jauge : elle lui manque
    assert 'href="/admin/fiche/person/ext_7?onglet=lien"' in groups
    band = _between(page, 'class="person-tiles pers-band"', "</section>")  # la bande de chiffres, puis la liste
    assert band.index("Personnes") < band.index("Qui lui manquent") < band.index("Dernier réconfort cherché")
    assert page.index('class="person-tiles pers-band"') < page.index('id="pers-bonds-title"')
    assert "Qui lui manque :" not in page  # personne ne lui manque : pas de bandeau
    # ils se parcourent : ni recherche ni proximité à choisir (ses groupes la disent), une ancienne adresse filtrée
    # montre tous les liens
    assert '<form class="filters"' not in page and 'name="proximite"' not in page
    old = drawn(client, "/admin/personnes/liens?q=lea&proximite=close")
    assert "Léa Martin" in old and "adrien" in _between(old, 'id="pers-bonds-title"', "</section>\n</div>")


def test_links_read_the_state_not_the_words_of_the_cells(world, monkeypatch):  # noqa: F811
    """Liens lit d'où vient une proximité et si un rythme est mesuré à l'état de la faculté (``closeness_origin``,
    ``rhythm_of``) : une cellule reformulée — ici, des mots qui n'ont plus rien à voir — ne change ni les groupes, ni
    l'origine, ni « mesuré » (C3-18)."""
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    stranger(client, live, "ext_7", "Léa Martin")
    emit(client, live, "social", [social_c.CLOSENESS_SET.draft(person="ext_7", closeness=social_c.CLOSE)])
    monkeypatch.setattr(social_inspect, "_closeness_text", lambda s, frame, person: "un tout autre libellé")
    monkeypatch.setattr(social_inspect, "_rhythm", lambda reading: "chaque semaine — mesuré")
    page = drawn(client, "/admin/personnes/liens")
    groups = _between(page, 'id="pers-bonds-title"', "</section>\n</div>")
    assert groups.index(">Proches") < groups.index("Léa Martin") < groups.index(">Amitiés") < groups.index("adrien")
    assert "déclarée par un opérateur" in groups and "au moins « amitié », car c'est sa propriétaire" in groups
    # une seule journée : son rythme n'est pas encore mesuré, quoi que dise la cellule
    assert "chaque semaine" not in groups and groups.count("pas encore mesuré") == 2


def test_who_is_here_one_entry_per_person_her_connections_under_her(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    assert "Personne n'est connecté en ce moment" in drawn(client, "/admin/personnes/presents")
    emit(client, live, "presence", [
        presence_c.CONNECTED.draft(handle="user_1", channel="web", connection=f"c-{n}", authenticated=True,
                                   account=1, operator=True, display_name="adrien") for n in (1, 2)],
         Origin.EXTERNAL)
    page = drawn(client, "/admin/personnes/presents")
    assert 'data-tab="personnes/presents"' in page and "2 connexions vivantes" in page
    here = page.split('class="pers-here"', 1)[1]
    assert here.count('class="pers-here-item"') == 1  # une personne, deux connexions
    links = _between(here, 'class="pers-links-list"', "</ul>")
    assert links.count("adrien · compte opérateur") == 2 and "c-1" in links and "c-2" in links
    # l'identifiant d'une connexion n'est plus écrit : il passe au survol de sa ligne
    assert 'title="connexion c-1"' in links and "pers-conn" not in links and "<code" not in links
    assert "le chat web" in links and "privée" in links and "en ligne" in here
