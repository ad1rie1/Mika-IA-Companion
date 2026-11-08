"""Qui peut quoi dans la console (ADR 0133), le parcours d'un opérateur : la page « Droits » lit chaque type de règles
par personne et par ressource ; l'onglet « Accès » d'un projet se dessine, et son tableau s'enregistre d'un envoi. Un
tableau de droits (Réglages › Canaux, les familles d'Outils) montre sur chaque ligne ce qui est enregistré, et
l'enregistrer tel que la page le montre le laisse identique. Sa vie interne se décrit à l'opératrice, pas au modèle."""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from functools import partial
from html.parser import HTMLParser
from pathlib import Path

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.teams.config import TeamsAccount, TeamsConfig
from mika.app.handmade.rights import FAMILY_ABOUT
from mika.contracts import projects as c
from mika.faculties.identity.faculty import IdentityParams
from mika.faculties.projects.tools import opened
from mika.inspector import ui as console_ui
from mika.inspector.pages import droits_tables, families
from mika.kernel.events import Origin
from mika.vocab.access import EVERYONE, INTERNAL, OWNER, PERSON, SELF, Table, ToolRule
from mika.vocab.canals import CanalRule, CanalTable
from tests.protocol.test_console_mcp import html_of, submit
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/inspecteur/reglages/droits"
CANALS = "/inspecteur/reglages/canaux"
FAMILIES = "/inspecteur/outils/tous"


class _Sent(HTMLParser):
    """Ce que le navigateur envoie d'un formulaire tel que la page le dessine : ses champs cachés, ses cases cochées,
    et pour chaque liste l'option marquée « selected » — sans elle, la première qui n'est pas grisée (la règle du
    navigateur). Rien de grisé ne part."""

    def __init__(self, form_id: str) -> None:
        super().__init__()
        self.form_id, self.inside, self.data = form_id, False, {}
        self.select: str | None = None
        self.options: list[tuple[str, bool, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "form":
            self.inside = a.get("id") == self.form_id
        elif not self.inside:
            return
        elif tag == "input" and "disabled" not in a:
            kind = a.get("type") or "text"
            if kind == "hidden" or (kind == "checkbox" and "checked" in a):
                self.data.setdefault(a["name"], []).append(a.get("value") or ("on" if kind == "checkbox" else ""))
        elif tag == "select":
            self.select, self.options = (None if "disabled" in a else a["name"]), []
        elif tag == "option" and self.select is not None:
            self.options.append((a.get("value") or "", "selected" in a, "disabled" in a))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.inside = False
        elif tag == "select" and self.select is not None:
            chosen = [v for v, on, _ in self.options if on][-1:] or [v for v, _, off in self.options if not off][:1]
            self.data.setdefault(self.select, []).extend(chosen)
            self.select = None


def sent(page: str, form_id: str) -> dict[str, list[str]]:
    """Ce qu'un clic sur « Enregistrer » envoie du formulaire ``form_id``, sans rien y toucher."""
    parser = _Sent(form_id)
    parser.feed(page)
    assert parser.data, f"pas de formulaire {form_id}"
    return {**parser.data, "faire": [""]}


def form_of(page: str, form_id: str) -> str:
    return page.split(f'id="{form_id}"', 1)[1].split("</form>", 1)[0]


def test_the_rights_page_and_a_projects_access_tab(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    created = client.portal.call(partial(live.kernel.mind.append, [opened(
        title="Le site", description="", authority=c.USER, mode=c.PERSONA, owner=None, address=None, about=(),
        level=0, source="operator")], emitter="projects", correlation="genese", origin=Origin.GENESIS))
    pid = created.seqs[-1]
    page = html_of(client.get(PAGE))
    for part in ("Qui peut quoi", "Vie interne", "Apps de la Forge", "Services MCP", "Projets", "Canaux",
                 "Le projet « Le site »", "détail des accès", "<code>memory_search</code>", "Ce que le code fixe"):
        assert part in page, part
    assert "Droits exacts" not in page  # sans qui ni canal choisis, pas de droits exacts
    # une sorte de ressource par sous-onglet (ADR 0176), ce que le code fixe au bout
    for pane in ("d-vie", "d-forge", "d-services", "d-projets", "d-canaux", "d-code"):
        assert f'href="#{pane}"' in page and f'id="{pane}" data-pane' in page, pane
    assert 'id="r-memory"' in page and 'id="r-project-' in page
    home = html_of(client.get("/inspecteur"))
    assert 'href="/inspecteur/reglages/droits"' in home and "/inspecteur/outils/droits" not in home  # menu Réglages
    # les droits exacts : toi par le chat web — jamais réglé : toi, tout, par sa ligne
    mine = html_of(client.get(PAGE, params={"qui": "toi", "canal": "web:prive"}))
    assert "Droits exacts" in mine and "piloter projet : modification" in mine and "ligne 1" in mine
    assert "memory_search" in mine and "lit : seule" in mine
    # un autre compte : il l'entend selon sa confidentialité, en lecture seule ; dans un salon, pas plus
    other = html_of(client.get(PAGE, params={"qui": "compte", "canal": "web:prive"}))
    assert "piloter projet : lecture seule" in other and "comportement par défaut" in other
    assert "piloter projet : lecture seule" in html_of(client.get(PAGE, params={"qui": "compte", "canal": "web:salon"}))
    # le détail des accès d'un projet : son tableau, « Modifier » vers sa fiche, « Retour »
    shown = html_of(client.get(PAGE, params={"detail": f"project:{pid}"}))
    assert "Le projet « Le site »" in shown and "Comportement par défaut" in shown and "← Retour" in shown
    assert f'href="/inspecteur/fiche/project/{pid}?onglet=acces"' in shown and "Modifier" in shown
    assert f'href="?#r-project-{pid}"' in shown  # « Retour » ramène à sa ligne, dans son sous-onglet
    # l'onglet « Accès » du projet, dessiné, sa ligne d'avant réglage cochée comme elle vaut ; ajouter : une ligne
    # fermée, enregistrée (le navigateur envoie ce qui est coché, le test le dit)
    tab = html_of(client.get(f"/inspecteur/fiche/project/{pid}", params={"onglet": "acces"}))
    assert "Accès au projet" in tab and "+ Ajouter un accès" in tab and "Jamais réglés" in tab
    assert 'name="qui.1|proprietaire" checked' in tab and 'name="canal.2|interne" checked' in tab
    assert 'name="qui.2|elle" checked' in tab  # elle seule : elle, cochée par son nom (ADR 0184), plus un « qui » caché
    assert 'name="fichiers.1" checked' in tab and "Par où" in tab
    shown = {"qui.1|proprietaire": "on", "toujours.1": "on", "voir.1": "on", "piloter.1": "modification",
             "fichiers.1": "on", "lecture.1": "seule", "action.1": "seule", "tous.1": "on",
             "qui.2|elle": "on", "canal.2|interne": "on", "voir.2": "on", "piloter.2": "modification", "fichiers.2": "on",
             "lecture.2": "seule", "action.2": "seule", "tous.2": "on",
             "defaut_piloter": "non", "defaut_lecture": "non", "defaut_action": "non"}
    added = submit(client, tab, "projects.acces", faire="ajouter", **shown)
    assert added.status_code == 200 and "Ligne 3 ajoutée, fermée" in html_of(added)
    view = next(v for v in live.kernel.mind.frame().get(c.LIVE) if v.id == pid)
    assert view.access == (*c.UNSET, c.ProjectAccess(who=(OWNER,))) and view.default_access == c.CLOSED
    # retirer la première : restent elle seule, et la ligne fermée
    tab = html_of(client.get(f"/inspecteur/fiche/project/{pid}", params={"onglet": "acces"}))
    closed_row = {"qui.3|proprietaire": "on", "toujours.3": "on", "piloter.3": "non", "lecture.3": "non",
                  "action.3": "non", "tous.3": "on"}
    removed = submit(client, tab, "projects.acces", faire="retirer:1", **shown, **closed_row)
    assert "Ligne 1 retirée." in html_of(removed)
    view = next(v for v in live.kernel.mind.frame().get(c.LIVE) if v.id == pid)
    assert view.access == (c.UNSET[1], c.ProjectAccess(who=(OWNER,)))
    # la page le lit aussitôt : pour toi, plus rien (la ligne fermée) ; elle seule garde tout — chaque case le dit,
    # avec les deux lignes qui en décident (la ressource, le canal)
    after = html_of(client.get(PAGE, params={"qui": "toi", "canal": "web:prive"}))
    assert "le voir : non · piloter projet : aucun pilotage · ses fichiers : non — ligne 2" in after
    alone = html_of(client.get(PAGE, params={"qui": "seule", "canal": "interne"}))
    assert "le voir : oui · piloter projet : modification · ses fichiers : oui — ligne 1" in alone


def test_a_rights_table_shows_what_is_saved_and_saving_it_unchanged_keeps_it(world):  # noqa: F811
    """Chaque ligne d'un tableau de droits montre ce qui est enregistré : l'option choisie, la case cochée, même une
    option verrouillée qu'elle porte encore ; « Enregistrer » sans rien changer laisse le tableau identique. Avant,
    le gabarit lisait ``r.values`` — la méthode ``dict.values`` pour Jinja, pas la clé : chaque liste montrait sa
    première option, chaque case était décochée, et l'envoi les écrivait (un courrier « seule » au lieu de « ton
    accord », les fichiers fermés)."""
    client, live, _ = world
    bootstrap(client)
    web = CanalTable(lines=(
        CanalRule(who=(OWNER,), canal=("web",), reply="accord", read="carte", act="toi", steer="modification",
                  files=True, keep="perso"),
        CanalRule(who=(EVERYONE,), canal=("web",), reply="non", read="seule", act="non", steer="lecture", keep="rien")),
        default=CanalRule(canal=("web",), reply="seule", read="toi", steer="accord", files=True, keep="prive"))
    mail = CanalTable(lines=(CanalRule(who=(EVERYONE,), canal=("courrier",), prepare=True, reply="brouillon"),),
                      default=CanalRule(canal=("courrier",), reply="accord"))
    for key, table in (("web", web), ("courrier", mail)):
        client.portal.call(live.settings.save_canal, key, table)
    page = html_of(client.get(CANALS))
    shown = form_of(page, "t-web")
    assert '<option value="accord" selected>' in shown and 'name="fichiers.1" checked' in shown
    assert 'name="fichiers.2" checked' not in shown and '<option value="modification" selected>' in shown
    assert 'class="access-select perso"' in shown  # sa classe dit sa valeur
    # le courrier n'a plus de brouillon (verrouillé), mais une ligne qui le porte le montre, choisi et pas grisé
    assert '<option value="brouillon" selected>' in form_of(page, "t-courrier")
    for key, table in (("web", web), ("courrier", mail)):
        assert client.post(f"{CANALS}/regler", data=sent(page, f"t-{key}")).status_code == 200
        assert client.portal.call(live.settings.canals).tables[key] == table, key
    # le même gabarit dessine les tableaux des familles d'outils
    memory = Table[ToolRule](lines=(
        ToolRule(who=(OWNER,), read="non", act="non", keep="public", tools=("memory_search",)),
        ToolRule(who=(SELF,), canal=(INTERNAL,), read="seule", act="seule", keep="public")),
        default=ToolRule(read="non", act="non", keep="rien"))
    client.portal.call(live.settings.save_family, "memory", memory)
    page = html_of(client.get(FAMILIES, params={"famille": "memory"}))
    assert '<option value="non" selected>' in form_of(page, "t-memory")
    assert client.post("/inspecteur/outils/familles/regler", data=sent(page, "t-memory")).status_code == 200
    assert client.portal.call(live.settings.families)["memory"] == memory


def test_her_inner_life_is_described_to_the_operator_and_tool_names_wait_for_someone(world):  # noqa: F811
    """Droits › Vie interne : chaque famille se décrit à l'opératrice, à la troisième personne — jamais la phrase de sa
    voix, écrite pour le modèle (« fouiller tes souvenirs… ») ; sur la ligne, le nombre de ses outils, leurs noms dans
    le repli ; une étiquette par outil (ouvert, fermé) seulement quand on a choisi qui et par quel canal."""
    client, live, _ = world
    bootstrap(client)
    registry = live.kernel.registry
    families: dict[str, list[str]] = {}
    for spec in registry.tools.values():
        families.setdefault(spec.bundle, []).append(spec.name)
    inner = {b for b, names in families.items() if not any(registry.is_dynamic(n) for n in names)}
    assert inner and inner <= set(FAMILY_ABOUT), sorted(inner - set(FAMILY_ABOUT))
    second = re.compile(r"\b(tu|te|tes|ton|ta|toi|tien|tiens|tienne)\b|\bt'", re.I)
    assert not [k for k, text in FAMILY_ABOUT.items() if second.search(text)]
    page = html_of(client.get(PAGE))
    vie = page.split('id="d-vie" data-pane', 1)[1].split("data-pane", 1)[0]
    assert FAMILY_ABOUT["memory"] in vie and registry.bundles["memory"] not in vie
    assert "rights-chip" not in vie and "<code>memory_search</code>" in vie and "2 outils" in vie
    mine = html_of(client.get(PAGE, params={"qui": "toi", "canal": "web:prive"}))
    assert '<span class="rights-chip on">memory_search</span>' in mine.split('id="d-vie" data-pane', 1)[1]


def test_a_declared_owner_is_never_offered_as_a_person(world):  # noqa: F811
    """Une propriétaire déclarée sans compte opérateur, « Toi » la désigne déjà : pas plus dans les tableaux des canaux
    et des familles que dans ceux des services et des projets, une seule liste pour tous (K0-16)."""
    client, live, _ = world
    bootstrap(client)
    lea = client.portal.call(partial(live.accounts.create, "lea", "un-mot-de-passe-long", operator=False))
    bea = client.portal.call(partial(live.accounts.create, "bea", "un-mot-de-passe-long", operator=False))
    client.portal.call(live.kernel.set_params, "identity", IdentityParams(owners=(bea.handle,)))
    for url in (CANALS, FAMILIES):
        page = html_of(client.get(url))
        assert f"|{PERSON}{lea.handle}" in page, url
        assert f"{PERSON}{bea.handle}" not in page, url


def test_the_composition_gives_the_tables_what_they_show(world, monkeypatch):  # noqa: F811
    """Les instances d'un canal (chaque boîte, chaque compte Teams, sous leur nom) et l'adresse de la fiche d'une famille
    venue d'ailleurs viennent de la composition ; une famille qui n'a pas de fiche n'a pas de lien (K0-17)."""
    client, live, _ = world
    bootstrap(client)
    client.portal.call(live.settings.save_email, MailConfig(accounts={
        "perso": MailAccount(label="Personnel", address="adrien@example.test")}))
    client.portal.call(live.settings.save_teams, TeamsConfig(accounts={"bureau": TeamsAccount(label="Au bureau")}))
    page = html_of(client.get(CANALS))
    assert "Courrier · Personnel" in page and "Teams · Au bureau" in page and "Chat web · en salon" in page
    registry = live.kernel.registry
    model = next(iter(registry.tools.values()))
    monkeypatch.setattr(registry, "set_dynamic", lambda *a, **k: [])  # ses sources ne le remplacent pas pendant le test
    monkeypatch.setattr(registry, "tools", {
        **registry.tools, **{bundle: replace(model, name=bundle, bundle=bundle)
                             for bundle in ("mcp.meteo", "forge_apps.recettes", "ailleurs.rien")}})
    for lot, href in (("mcp.meteo", "/inspecteur/fiche/serveur/meteo?onglet=fait"),
                      ("forge_apps.recettes", "/inspecteur/fiche/app/recettes?onglet=acces")):
        assert f'<a href="{href}">' in html_of(client.get(FAMILIES, params={"lot": lot})), lot
    assert "ses droits se règlent sur sa fiche —" in html_of(client.get(FAMILIES, params={"lot": "ailleurs.rien"}))


def test_the_inspector_guesses_nothing_of_the_plugins() -> None:
    """Ni les tableaux de droits ni les familles n'écrivent le nom d'un plugin ou l'adresse de sa fiche, ni ne lisent
    ses réglages : ce qu'import-linter ne voit pas (K0-17)."""
    for module in (droits_tables, families):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        written = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not written & {"mcp", "forge", "forge_apps", "teams", "email", "phone"}, module.__name__
        assert not [w for w in written if "/fiche/" in w], module.__name__
        assert not {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} & {"email", "teams"}, module.__name__


def test_the_console_does_not_write_the_session_cookies_again() -> None:
    """Le nom des deux cookies de session s'écrit une fois, dans ``adapters/web/session.py`` (K0-18)."""
    tree = ast.parse(Path(console_ui.__file__).read_text(encoding="utf-8"))
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert not assigned & {"SESSION_COOKIE", "CSRF_COOKIE"}


def test_a_search_among_her_tools_unfolds_a_ligature(world, monkeypatch):  # noqa: F811
    """« soeur » trouve « sœur » : la recherche des outils replie comme les autres (``kernel.text.fold``, K0-15)."""
    client, _, _ = world
    bootstrap(client)
    real = families.entries

    def with_a_ligature(ui):
        out = real(ui)
        out[0]["tools"][0]["description"] = "Écrire à sa sœur"
        return out

    monkeypatch.setattr(families, "entries", with_a_ligature)
    assert "Écrire à sa sœur" in html_of(client.get(FAMILIES, params={"q": "soeur"}))
