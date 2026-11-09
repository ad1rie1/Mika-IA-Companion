"""Les adresses de la console mènent quelque part (K11-01, audit du 2026-11-05) : la fiche d'un compte Teams envoyait
vers « /inspecteur/envoi », une page fondue dans les canaux depuis l'ADR 0134 — « Page inconnue », 404. Chaque lien
d'une fiche se suit, et chaque adresse de la console écrite en toutes lettres dans le code répond autre chose que 404."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from mika.inspector import render
from mika.kernel.inspect import Ref
from mika.runtime import operations
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_teams import plugged
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

SRC = Path(operations.__file__).resolve().parents[1]
#: une adresse de la console écrite en entier (sans paramètre ni morceau calculé)
ADDRESS = re.compile(r"/inspecteur(/[a-z0-9_-]+)+")


def _content_links(page: str) -> set[str]:
    """Les liens de la console dans le contenu de la page (le menu, commun à toutes, est à part)."""
    main = page[page.index("<main"):]
    return {href for href in re.findall(r'href="(/inspecteur/[^"#]*)"', main)}


def test_every_link_of_a_teams_account_fiche_leads_somewhere(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    links = _content_links(drawn(client, "/inspecteur/teams/extension?compte=principal"))
    # comment partent ses réponses : le tableau de canal de ce compte (« teams:<clé> »), comme pour une boîte
    assert "/inspecteur/reglages/canaux?canal=teams%3Aprincipal" in links
    dead = sorted(href for href in links if client.get(href, follow_redirects=False).status_code == 404)
    assert not dead, dead


def _written_addresses() -> dict[str, str]:
    """Les adresses de la console écrites en toutes lettres dans le code (hors des f-strings), et où."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parts = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in parts
                    and ADDRESS.fullmatch(node.value)):
                found.setdefault(node.value, f"{path.relative_to(SRC)}:{node.lineno}")
    return found


def _literal(node: ast.expr, constants: dict[str, object]) -> object:
    """La valeur d'un argument : un littéral ou une constante du paquet ; sinon rien."""
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None


def _constants(tree: ast.Module) -> dict[str, object]:
    """Les constantes de tête d'un module, quand ce sont des littéraux."""
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _literal(node.value, found)
            if value is not None:
                found[node.targets[0].id] = value
    return found


def _relays(tree: ast.Module) -> dict[str, tuple[list[str], str]]:
    """Les aides qui donnent à ``view_link`` l'un de leurs paramètres pour nom de page (``tab(texte, page)``,
    ``workspace(…, view=page)``), car c'est à leur appel que le nom s'écrit : leur nom, leurs paramètres, celui-là."""
    found: dict[str, tuple[list[str], str]] = {}
    for func in ast.walk(tree):
        if isinstance(func, ast.FunctionDef):
            params = [a.arg for a in (*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs)]
            for call in ast.walk(func):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "view_link"
                        and call.args and isinstance(call.args[0], ast.Name) and call.args[0].id in params):
                    found[func.name] = (params, call.args[0].id)
    return found


def _given(call: ast.Call, params: list[str], name: str, constants: dict[str, object]) -> object:
    """Ce qu'un appel donne au paramètre ``name``, par son nom ou par sa place."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal(keyword.value, constants)
    at = params.index(name)
    return _literal(call.args[at], constants) if at < len(call.args) else None


def _named(call: ast.Call, owner: str, constants: dict[str, object],
           relays: dict[str, tuple[list[str], str]]) -> Ref | None:
    """La page qu'un appel nomme en toutes lettres : une vue, une page de réglages, un onglet de la file des accords."""
    values: list[object] = []
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            values.extend(_literal(arg.value, constants) or (None,))
        else:
            values.append(_literal(arg, constants))
    func = call.func
    if isinstance(func, ast.Name) and func.id in relays:  # l'aide d'un plugin pour ses propres vues, et ce qui s'y relaie
        page = _given(call, *relays[func.id], constants)
        return Ref.view(owner, page, "") if isinstance(page, str) else None
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "Ref"):
        return None
    if func.attr == "view":
        return Ref.view(values[0], values[1], "") if isinstance(values[0], str) and isinstance(values[1], str) else None
    if func.attr == "settings":
        return Ref.settings(values[0], "") if isinstance(values[0], str) else None
    if func.attr == "approvals" and len(values) > 1:
        return Ref.approvals("", values[1]) if isinstance(values[1], str) else None
    return None


def _named_pages() -> dict[str, str]:
    """Ce que facultés et plugins nomment en toutes lettres : son adresse générale, et où."""
    found: dict[str, str] = {}
    for root in ("faculties", "plugins"):
        files = {path: ast.parse(path.read_text(encoding="utf-8")) for path in sorted((SRC / root).rglob("*.py"))}
        for path, tree in files.items():
            owner = path.relative_to(SRC / root).parts[0].removesuffix(".py")
            family = [t for other, t in files.items()  # une constante ou une aide vient souvent d'un voisin
                      if other.relative_to(SRC / root).parts[0] == path.relative_to(SRC / root).parts[0]]
            constants = {k: v for t in family for k, v in _constants(t).items()}
            relays = {"view_link": (["view"], "view"), **{k: v for t in family for k, v in _relays(t).items()}}
            for node in ast.walk(tree):
                ref = _named(node, owner, constants, relays) if isinstance(node, ast.Call) else None
                if ref is not None:
                    found.setdefault(render.href(ref), f"{path.relative_to(SRC)}:{node.lineno}")
    return found


def test_every_page_a_faculty_or_a_plugin_names_leads_somewhere(world):  # noqa: F811
    """Un nom se trompe comme une adresse : chaque vue, page de réglages et file nommées répondent autre chose que 404
    (ADR 0216 ; sans carte, une vue passe par son adresse générale, qui mène à son onglet)."""
    client, _, _ = world
    bootstrap(client)
    named = _named_pages()
    assert len(named) > 15  # la recherche trouve bien ce que le code nomme
    assert render.href(Ref.view("email", "contacts", "")) in named  # y compris par une aide locale : tab(), workspace()

    def unknown(address: str) -> bool:
        """404, ou renvoyée à sa destination : un onglet qu'elle ne connaît pas y redirige."""
        got = client.get(address, follow_redirects=False)
        return got.status_code == 404 or got.headers.get("location") == address.rsplit("/", 1)[0]

    dead = sorted(f"{address} ({where})" for address, where in named.items() if unknown(address))
    assert not dead, dead


def test_every_written_console_address_leads_somewhere(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    written = _written_addresses()
    assert len(written) > 8  # la recherche trouve bien les adresses du code (celles de la console seule : ADR 0216)
    dead = sorted(f"{address} ({where})" for address, where in written.items()
                  if client.get(address, follow_redirects=False).status_code == 404)
    assert not dead, dead
