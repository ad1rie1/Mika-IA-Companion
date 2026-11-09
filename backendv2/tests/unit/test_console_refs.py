"""Une adresse de la console s'écrit d'une seule façon : le contrat ``Ref`` dit ce qu'on vise, ``render.href`` en fait
une adresse, ``subjects.fiche_url`` est la seule aide pour la fiche d'un objet — et une vue a une adresse, pas un
détour par ``/facultes/``."""

import ast
import html
from pathlib import Path

import pytest

import mika.app.handmade as handmade
from mika.app.handmade.tabs.identities import handle_of
from mika.app.handmade.tabs.people import person_of
from mika.inspector import render, text
from mika.inspector.pages.families import _tool_href
from mika.inspector.pages.subjects import fiche_key, fiche_url
from mika.kernel.inspect import Entry, Nav, NavItem, Ref, Row, Stat, Stats, Table, Timeline
from mika.vocab.people import EPHEMERAL_PREFIX
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

APP = Path(handmade.__file__).parents[1]
PLACES = {"rss/flux": "sens/flux"}
ENV = render.Env(when=str, now=0, views=PLACES, settings={"teams": "/inspecteur/teams/parametres"}.get)


# ── une vue : son onglet, tout droit ──


def test_a_view_goes_straight_to_its_tab():
    assert render.href(Ref.view("rss", "flux", "Flux", flux="a b"), ENV) == "/inspecteur/sens/flux?flux=a+b"


def test_a_view_keeps_a_parameter_named_like_an_argument():
    """Une vue relaie ce qu'il y a dans l'adresse : « ?name= » ne doit pas faire tomber la page."""
    got = render.href(Ref.view("rss", "flux", "Flux", **{"owner": "a", "name": "b", "text": "c"}), ENV)
    assert got == "/inspecteur/sens/flux?owner=a&name=b&text=c"


def test_a_link_says_where_to_come_back_and_the_console_writes_it():
    back = Ref.view("rss", "flux", "", flux="a b")
    got = Ref.settings("teams", "Modifier", cle="k").back_to(back)
    assert render.href(got, ENV) == "/inspecteur/teams/parametres?cle=k&retour=%2Finspecteur%2Fsens%2Fflux%3Fflux%3Da%2Bb"


def test_a_link_without_a_way_back_says_none():
    assert "retour" not in render.href(Ref.settings("teams", "Modifier", cle="k"), ENV)


@pytest.mark.parametrize("env", [ENV, None], ids=["cachée", "sans carte"])
def test_a_view_without_a_place_stays_under_its_general_address(env):
    assert render.href(Ref.view("rss", "cachee", "x"), env) == "/inspecteur/facultes/rss/cachee"


def test_every_block_finds_the_place_of_a_view():
    view = Ref.view("rss", "flux", "Flux")
    rendered = render.blocks([
        Table(("lien",), (Row((view,), href=view),)),
        Stats((Stat("flux", "3", href=view),)),
        Timeline((Entry(at=0, title="t", href=view),)),
        Nav((NavItem("Flux", view),)),
    ], ENV, {})
    assert "/sens/flux" in repr(rendered) and "/facultes/" not in repr(rendered)


def test_a_view_link_is_what_its_general_address_led_to(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    page = html.unescape(client.get("/inspecteur/systeme/vues").text)
    placed = [v for v in live.kernel.registry.inspectors if v.section and not v.hidden]
    assert placed
    for v in placed:
        old = f"/inspecteur/facultes/{v.owner}/{v.name}"
        moved = client.get(old, follow_redirects=False)
        assert moved.status_code == 303, old
        assert f'href="{moved.headers["location"]}"' in page, old
        assert f'href="{old}"' not in page, old


def test_the_vitals_of_every_page_take_no_detour(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    assert "/inspecteur/facultes/" not in client.get("/inspecteur/").text


# ── ce qui n'est ni une vue ni une fiche ──


def test_a_settings_page_is_named_and_the_console_knows_where_it_lives():
    assert render.href(Ref.settings("teams", "x", compte="b c"), ENV) == "/inspecteur/teams/parametres?compte=b+c"


def test_a_settings_page_without_the_map_goes_under_settings_which_redirects():
    assert render.href(Ref.settings("appareils", "x")) == "/inspecteur/reglages/appareils"


def test_the_queue_of_approvals_and_one_of_its_tabs():
    assert render.href(Ref.approvals("x")) == "/inspecteur/approbations"
    assert render.href(Ref.approvals("x", "identites", tri="age")) == "/inspecteur/approbations/identites?tri=age"


def test_a_download_encodes_its_key_and_says_which_file():
    got = render.href(Ref.download("mail", "INBOX/12 #3", "x", "pièce 1.pdf"))
    assert got == "/inspecteur/telecharger/mail/INBOX%2F12%20%233?fichier=pi%C3%A8ce+1.pdf"
    assert render.href(Ref.download("project", "7", "x")) == "/inspecteur/telecharger/project/7"


@pytest.mark.parametrize(("ref", "said"), [
    (Ref.settings("teams", "x", compte="a"), "settings:teams?compte=a"),
    (Ref.approvals("x", "identites"), "approvals:identites"),
    (Ref.download("mail", "k", "x", "f"), "download:mail/k?fichier=f"),
])
def test_a_tool_reads_where_these_links_lead(ref, said):
    assert text.target(ref) == said


# ── la fiche d'un objet : une aide ──


@pytest.mark.parametrize("key", ["adrien", "a b/c?d#e", "INBOX:12@x", "é&=%"])
def test_a_key_is_read_back_from_its_fiche(key):
    assert fiche_key(fiche_url("mail", key), "mail") == key
    assert fiche_key(fiche_url("mail", key, "voix") + "#plus", "mail") == key


def test_a_fiche_is_written_as_every_link_writes_it():
    assert fiche_url("compte", "a b/c", "etat") == render.href(Ref.subject("compte", "a b/c", "", "etat"))
    assert fiche_url("compte", "a b/c") == "/inspecteur/fiche/compte/a%20b%2Fc"


@pytest.mark.parametrize("href", ["", "/inspecteur/fiche/handle/x", "/inspecteur/sens/flux", "https://x.fr/fiche/mail/k"])
def test_another_address_has_no_key_of_this_kind(href):
    assert fiche_key(href, "mail") == ""


def test_a_drawn_page_reads_who_a_cell_names():
    assert person_of({"href": fiche_url("person", "user 3") + "?onglet=memoire"}) == "user 3"
    assert handle_of({"href": fiche_url("handle", "web:x#1")}) == "web:x#1"
    assert person_of({"href": fiche_url("handle", "web:x")}) == "" and person_of(None) == ""


def test_only_a_person_has_a_person_link():
    assert handmade.person_href("user 3") == "/inspecteur/fiche/person/user%203"
    assert handmade.person_href(EPHEMERAL_PREFIX + "x") == ""


def test_a_tool_name_is_encoded_in_its_link():
    assert _tool_href("a&b") == "/inspecteur/outils/tous?outil=a%26b"


def _strings(path: Path) -> list[tuple[int, str]]:
    """Les chaînes d'un module, ses docstrings écartées (l'AST : un commentaire n'est pas du code)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_no_drawn_page_writes_the_address_of_a_fiche_by_hand():
    written = [f"{path.relative_to(APP)}:{line}" for folder in ("handmade", "settings_sections")
               for path in APP.joinpath(folder).rglob("*.py")
               for line, s in _strings(path) if "/fiche/" in s]
    assert not written, written
