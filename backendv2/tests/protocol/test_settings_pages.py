"""Les pages de réglages de la console, lot L05 de l'audit du 2026-11-05 (ADR 0197) : des formulaires qui n'écrasent
rien, un annuaire complet, la vue des plugins, les actions dans la barre de titre, des renvois en liens, des nombres
lisibles.

- Une correspondance (Qui sert quoi, Où elles écrivent) garde son « — » : un rôle ou un flux laissé vide le reste à
  l'enregistrement — jamais la première option, figée (C7-02). Le formulaire est relu comme un navigateur l'enverrait.
- L'annuaire liste aussi les pages qui vivent ailleurs (Courrier › Paramètres), dit chaque page en une phrase entière et
  trouve un réglage par le nom de son champ (C7-07, C1-09) ; ses rubriques disent ce qu'elles contiennent (Q01).
- La vue des plugins a une ligne par paquet de ``plugins/`` (C9-09, C7-06).
- Un chemin de console écrit dans le code est le fil d'Ariane de sa page (K0-08).
"""

from __future__ import annotations

import ast
import html
import inspect
import pkgutil
import re
from html.parser import HTMLParser
from pathlib import Path

import mika
import mika.plugins
from mika.app import reglages
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

BASE = "/inspecteur/reglages"
#: un réel écrit en notation scientifique (« 5.55975e-06 », « 1e-08 »)
SCIENTIFIC = re.compile(r"\d[eE][-+]?\d")
#: les pages de réglages que le code cite par leur chemin, et leur adresse ; le chemin écrit, jusqu'à leur nom
CITED = {"Notifications du téléphone": "notifications", "Carte de sa position": "carte",
         "Lieux et adresses": "lieux", "Itinéraires": "itineraires", "Dépôts Git": "depots"}
WRITTEN_PATH = re.compile(r"(?:Réglages|Connexions(?: extérieures)?)(?: › [^›:;,.()«»]+?)*? › "
                          r"(?:Notifications du téléphone|Carte de sa position|Lieux et adresses|Itinéraires|"
                          r"Dépôts [Gg]it)")


class FormReader(HTMLParser):
    """Ce qu'un navigateur enverrait des formulaires d'une page dont l'action est ``action`` : chaque champ, sa valeur
    — une liste sans option choisie envoie sa première option ; une case non cochée, rien."""

    def __init__(self, page: str, action: str, form_class: str = "") -> None:
        super().__init__()
        self.action, self.form_class = action, form_class
        self.inside = False
        self.select: str | None = None
        self.options: list[tuple[str, bool]] = []
        self.textarea: str | None = None
        self.text = ""
        self.data: list[tuple[str, str]] = []
        self.feed(page)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self.inside = a.get("action") == self.action and self.form_class in a.get("class", "").split()
        if not self.inside:
            return
        if tag == "input" and a.get("name") and "disabled" not in a:
            if a.get("type") == "checkbox":
                if "checked" in a:
                    self.data.append((a["name"], a.get("value", "on")))
            elif a.get("type") not in ("submit", "button", "file"):
                self.data.append((a["name"], a.get("value", "")))
        elif tag == "select" and "disabled" not in a:
            self.select, self.options = a.get("name"), []
        elif tag == "option" and self.select is not None:
            self.options.append((a.get("value", ""), "selected" in a))
        elif tag == "textarea":
            self.textarea, self.text = a.get("name"), ""

    def handle_data(self, data: str) -> None:
        if self.textarea is not None:
            self.text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.inside = False
        elif tag == "select" and self.select is not None:
            chosen = next((v for v, on in self.options if on), self.options[0][0] if self.options else "")
            self.data.append((self.select, chosen))
            self.select = None
        elif tag == "textarea" and self.textarea is not None:
            self.data.append((self.textarea, self.text))
            self.textarea = None

    def posted(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name, value in self.data:
            out.setdefault(name, []).append(value)
        return out


def page_of(client, path: str) -> str:
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code)
    return r.text


def main_of(page: str) -> str:
    """Le contenu de la page, sans le menu (qui mène partout)."""
    return page.split("<main", 1)[1]


def post(client, path: str, data: dict) -> object:
    return client.post(path, data={**data, "csrf": client.cookies.get("csrftoken")})


def select(page: str, name: str) -> str:
    found = re.search(rf'<select name="{re.escape(name)}"[^>]*>(.*?)</select>', page, re.S)
    assert found, name
    return found.group(1)


def test_a_role_or_a_flow_left_empty_stays_empty_when_the_page_is_saved_unchanged(world):  # noqa: F811
    """C7-02 : chaque liste d'une correspondance propose « — », choisi quand la clé est absente ; enregistrer la page
    telle quelle ne fige aucun repli (avant : la première option de chaque liste, le premier fournisseur par ordre
    alphabétique, était envoyée et enregistrée)."""
    client, live, _ = world
    bootstrap(client)
    for name in ("a", "b"):
        r = post(client, f"{BASE}/fournisseurs", {"_section": "modeles", "_enregistrement": "backends",
                                                   "_ancienne": "", "_cle": name, "_champs": ["kind", "model", "host"],
                                                   "kind": "ollama", "model": "m", "host": "http://127.0.0.1:9"})
        assert r.status_code == 200, html.unescape(r.text)[:300]
    post(client, f"{BASE}/roles", {"_section": "modeles", "_champs": ["routes"], "routes.reply": "b"})
    assert client.portal.call(live.settings.llm).routes == {"reply": "b"}
    page = page_of(client, f"{BASE}/roles")
    assert '<option value="b" selected>' in select(page, "routes.reply")
    for role in ("initiative", "extract", "dream"):
        options = select(page, f"routes.{role}")
        assert options.lstrip().startswith('<option value="">—</option>') and " selected" not in options, role
    sent = FormReader(page, f"{BASE}/roles", "hm-form").posted()
    assert sent["routes.extract"] == [""]
    again = post(client, f"{BASE}/roles", sent)
    assert again.status_code == 200 and "Rien n'a changé" in html.unescape(again.text)
    assert client.portal.call(live.settings.llm).routes == {"reply": "b"}

    # Où elles écrivent : un flux sans autrice le reste
    url = f"{BASE}/autrices"
    post(client, url, {"_section": "autrices", "_champs": ["flows"], "flows.chat": "message", "flows.teams": "",
                       "flows.telephone": ""})
    assert dict(live.settings.authors().flows) == {"chat": "message"}
    page = page_of(client, url)
    assert " selected" not in select(page, "flows.teams")
    sent = FormReader(page, url, "hm-form").posted()
    assert sent["flows.teams"] == [""] and sent["flows.telephone"] == [""]
    post(client, url, sent)
    assert dict(live.settings.authors().flows) == {"chat": "message"}
    assert live.settings.author_for("teams") is None


def test_who_serves_what_is_one_table_where_each_role_is_chosen_beside_what_really_serves_it(world):  # noqa: F811
    """C7-09 : Qui sert quoi est une seule table — le rôle, sa famille, sa liste, ce qui le sert vraiment (le repli
    compris), comment ; Où elles écrivent est le formulaire des autrices ; l'exemple d'une autrice se lit."""
    client, _live, _ = world
    bootstrap(client)
    post(client, f"{BASE}/fournisseurs", {"_section": "modeles", "_enregistrement": "backends", "_ancienne": "",
                                          "_cle": "local", "_champs": ["kind", "model", "host"], "kind": "ollama",
                                          "model": "gemma", "host": "http://127.0.0.1:9"})
    page = html.unescape(page_of(client, f"{BASE}/roles"))
    assert page.count("<table") == 1
    table = page.split("<table", 1)[1].split("</table>", 1)[0]
    assert 'name="routes.reply"' in table and "Ce qui le sert vraiment" in table and "ollama · gemma" in table
    assert "par repli (répondre" in table and "Famille" in table
    authors = html.unescape(page_of(client, f"{BASE}/autrices"))
    table = authors.split("<table", 1)[1].split("</table>", 1)[0]
    assert 'name="flows.chat"' in table and "Ce qu'elle récrit" in table
    assert "Où elles écrivent" in authors and "caractères" not in authors and "(ADR" not in authors


def written_paths() -> set[str]:
    """Les chemins vers ces pages, dans toutes les chaînes du code : par l'AST, qui recolle une chaîne coupée sur deux
    lignes et ne lit pas les commentaires."""
    found: set[str] = set()
    for file in Path(mika.__file__).parent.rglob("*.py"):
        source = file.read_text(encoding="utf-8")
        if " › " in source:
            found.update(path for node in ast.walk(ast.parse(source))
                         if isinstance(node, ast.Constant) and isinstance(node.value, str)
                         for path in WRITTEN_PATH.findall(" ".join(node.value.split())))
    return found


def test_a_path_written_in_the_code_is_the_breadcrumb_of_its_page(world):  # noqa: F811
    """K0-08, Q01 : « Réglages › Canaux › Itinéraires » menait aux tableaux de droits, et « Canaux » ne nomme plus
    qu'eux. Ce qu'on écrit à une opératrice est ce qu'elle lit en haut de la page, sa rubrique, son lien et son titre."""
    client, _live, _ = world
    bootstrap(client)
    written = written_paths()
    assert {"Réglages › Carte et téléphone › Itinéraires", "Connexions › Dépôts Git"} <= written
    for path in sorted(written):
        page = html.unescape(page_of(client, f"{BASE}/{CITED.get(path.rsplit(' › ', 1)[-1], 'inconnue')}"))
        nav = re.search(r'<nav class="crumbs"[^>]*>(.*?)</nav>', page, re.S)
        title = re.search(r"<h1>(.*?)</h1>", page, re.S)
        assert nav is not None and title is not None
        levels = re.findall(r">([^<>/]+)<", nav.group(1))
        # le lien de la page n'y est que quand son titre ne le redit pas (Connexions / Dépôts Git)
        trail = levels if levels[-1] == title.group(1) else [*levels, title.group(1)]
        assert " › ".join(trail) == path


def test_the_directory_lists_every_settings_page_in_a_rubric_named_after_what_it_holds(world):  # noqa: F811
    """C7-07, C1-09, Q01 : Courrier › Paramètres est dans l'annuaire (sous Plugins) ; chaque page s'y dit en une
    phrase entière ; un réglage se trouve par le nom de son champ ; « Canaux » n'y est plus une rubrique — Carte et
    téléphone en a les quatre pages, Dépôts Git est sous Connexions extérieures."""
    client, _live, _ = world
    bootstrap(client)
    page = html.unescape(page_of(client, f"{BASE}/apercu"))
    directory = page.split('<div class="settings-directory stack">', 1)[1]
    groups = {m.group(1): m.group(2) for m in re.finditer(
        r'<h2 id="[^"]+">([^<]+)</h2>.*?<ul class="hm-dir-links">(.*?)</ul>', directory, re.S)}
    assert "Canaux" not in groups and "Carte et téléphone" in groups and "Connexions extérieures" in groups
    for slug in ("notifications", "carte", "lieux", "itineraires"):
        assert f'href="{BASE}/{slug}"' in groups["Carte et téléphone"], slug
    assert f'href="{BASE}/depots"' in groups["Connexions extérieures"] and "Dépôts Git" in directory
    assert 'href="/inspecteur/courrier/parametres"' in groups["Plugins"] and "Courrier › Paramètres" in directory
    descriptions = re.findall(r'<span class="hm-dir-desc">([^<]+)</span>', directory)
    assert descriptions and not [d for d in descriptions if d.endswith("…")]
    boxes = html.unescape(page_of(client, f"{BASE}/apercu?q=boîte"))
    assert 'href="/inspecteur/courrier/parametres"' in boxes
    zone = html.unescape(page_of(client, f"{BASE}/apercu?q=fuseau"))
    assert f'href="{BASE}/identite"' in zone and "Trouvé dans : Fuseau horaire" in zone


def test_the_plugins_overview_has_a_line_for_every_plugin(world):  # noqa: F811
    """C9-09, C7-06 : une ligne par paquet de ``plugins/`` (la table d'``app/reglages.py`` ne peut plus en oublier),
    chacune vers ses réglages, ses paramètres avancés et l'endroit où s'en servir ; la transcription y a sa ligne."""
    packages = {m.name for m in pkgutil.iter_modules(mika.plugins.__path__) if m.ispkg}
    assert set(reglages.PLUGINS) == packages
    client, live, _ = world
    bootstrap(client)
    page = html.unescape(page_of(client, f"{BASE}/plugins"))
    composed = live.kernel.registry.faculties
    for name in packages:
        assert name in composed, name
        if composed[name].params is not None:
            assert f'href="{BASE}/comportement-{name}"' in page, name
    for slug in ("carte", "lieux", "itineraires", "notifications"):
        assert f'href="{BASE}/{slug}"' in page, slug
    # la transcription vit dans Ses sens (ADR 0206) : la vue d'ensemble y mène, sous ce nom
    assert '<a href="/inspecteur/sens/parametres-transcription">Ses sens › Transcription vocale</a>' in page
    assert "Messages du téléphone" in page and "Recherche web" in page and "Carte et voyages" in page
    assert "Configurer la transcription vocale" not in page  # plus de bouton à part


def test_page_commands_are_title_bar_actions_and_a_dangerous_one_waits_under_more(world):  # noqa: F811
    """C7-10 : plus de carte « Commandes » ; « Nouveau jeton » est en vue dans la barre de titre, « Revenir au fichier »
    sous « ⋯ », avec sa confirmation."""
    client, _live, _ = world
    bootstrap(client)
    devices = page_of(client, f"{BASE}/appareils")
    bar = devices.split('class="action-bar"', 1)[1].split("</div>\n", 1)[0]
    assert "Nouveau jeton" in bar and "action-overflow" not in bar and "<h2>Commandes</h2>" not in devices
    document = html.unescape(page_of(client, f"{BASE}/document"))
    bar = document.split('class="action-bar"', 1)[1]
    more = bar.split('class="action-overflow"', 1)[1]
    assert "Revenir au fichier" in more and 'data-confirm="La persona rédigée ici sera oubliée' in more
    assert "<h2>Commandes</h2>" not in document


def test_an_entry_page_is_titled_by_the_entry_not_by_a_verb_and_its_list(world):  # noqa: F811
    """C7-12 (sa part) : « Fournisseur à ajouter », « Fournisseur « local » », « Autrice « Message » » — jamais
    « Ajouter · Fournisseurs »."""
    client, _live, _ = world
    bootstrap(client)
    new = html.unescape(page_of(client, f"{BASE}/fournisseurs?enregistrement=backends&cle=&nouveau=1"))
    assert "<h1>Fournisseur à ajouter</h1>" in new and "Ajouter · " not in new
    post(client, f"{BASE}/fournisseurs", {"_section": "modeles", "_enregistrement": "backends", "_ancienne": "",
                                          "_cle": "local", "_champs": ["kind", "model", "host"], "kind": "ollama",
                                          "model": "gemma", "host": "http://127.0.0.1:9"})
    edit = html.unescape(page_of(client, f"{BASE}/fournisseurs?enregistrement=backends&cle=local"))
    assert "<h1>Fournisseur « local »</h1>" in edit and "Modifier · " not in edit
    author = html.unescape(page_of(client, f"{BASE}/autrices?enregistrement=authors&cle=message"))
    assert "<h1>Autrice « Message »</h1>" in author


def test_a_page_says_where_the_rest_is_done_once_and_as_a_link(world):  # noqa: F811
    """C7-15 : les renvois de Teams sont des liens, chacun une fois ; l'introduction ne les répète pas."""
    client, _live, _ = world
    bootstrap(client)
    page = html.unescape(main_of(page_of(client, f"{BASE}/teams")))
    # la page vit dans Teams (ADR 0206) : Extension est l'onglet d'à côté, et un fait, une fois, dit que la clé y est
    facts = page.split('class="person-entry-facts hm-settings-facts"', 1)[1].split("</p>", 1)[0]
    assert facts.count('href="/inspecteur/teams/extension"') == 1 and 'href="/inspecteur/teams"' not in facts
    assert 'href="/inspecteur/reglages/canaux"' in facts
    subtitle = page.split("<h1>", 1)[1].split("</p>", 1)[0]
    assert "Relations & échanges" not in subtitle
    for path, target in (("flux", "/inspecteur/sens/flux"), ("reveils", "/inspecteur/reveils"),
                         ("serveurs-mcp", "/inspecteur/outils/serveurs"), ("depots", "/inspecteur/projets")):
        assert f'href="{target}"' in main_of(page_of(client, f"{BASE}/{path}")), path


def test_a_faculty_page_writes_values_and_bounds_in_french_decimals_and_saves_them_unchanged(world):  # noqa: F811
    """C7-16 : ni « 5.55975e-06 » ni « 1e-08 » sur la page d'une faculté — valeurs et bornes en notation décimale
    française ; renvoyées telles quelles, les valeurs ne changent rien."""
    client, _live, _ = world
    bootstrap(client)
    url = f"{BASE}/comportement-affect"
    first = page_of(client, url)
    groups = sorted(set(re.findall(rf'href="{re.escape(url)}\?groupe=([\w-]+)"', first))) or [""]
    seen_small = False
    for group in groups:
        page = page_of(client, f"{url}?groupe={group}" if group else url)
        form = page.split('class="form params-form"', 1)[1].split("</form>", 1)[0]
        assert not SCIENTIFIC.search(form), (group, SCIENTIFIC.search(form))
        seen_small |= bool(re.search(r'value="-?0,0000\d', form))
        decimals = re.findall(r'<input name="([\w.]+)" id="[^"]+"[^>]*value="([^"]*)" inputmode="decimal"', form)
        sent = {"_faculte": "affect", "_groupe": group, "_champs": [p for p, _v in decimals],
                **{p: v for p, v in decimals}}
        again = post(client, url, sent)
        assert again.status_code == 200 and "Rien n'a changé" in html.unescape(again.text), group
    assert seen_small  # une très petite valeur s'écrit « 0,0000… »


def test_a_section_saves_a_value_and_who_saved_it_is_for_the_audit_of_the_page(world):  # noqa: F811
    """K0-26 : le contrat ne promet plus un opérateur que personne ne lisait ; c'est l'audit de la page qui le garde
    (``tests/protocol/test_console_settings.py`` le lit au journal)."""
    _, live, _ = world
    saved = [s for s in reglages.sections(live) if s.save is not None]
    assert saved
    assert {s.key: list(inspect.signature(s.save).parameters) for s in saved
            if len(inspect.signature(s.save).parameters) != 1} == {}
