"""Système › Gestes audités (C9-08, audit du 2026-11-05) : ce que les opérateurs font dans la console et ce que chacun
fait depuis son espace, chacun sous un titre en français — jamais une clé, jamais répétée —, et d'où il vient (la
console, son espace, la ligne de commande), filtrable d'un clic.

- Une action déclarée faite depuis l'espace d'une personne est auditée sous « moi.<action> » (``perform(via=…)``) :
  sa clé dit d'où elle vient, comme les gestes que la console et la ligne de commande auditent eux-mêmes. Tout chemin
  de cet espace le dit, même pris par une opératrice (relecture du lot L09 : le refus d'un brouillon après une réponse,
  la note d'un arrêt, la clé d'une extension Teams gardaient leur clé nue, lue « la console ») ; un test le garde.
- Toute clé que le code audite a son titre : une clé nouvelle sans titre fait échouer ce fichier.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from mika.app import cli
from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.pages.system import gesture_origin
from mika.runtime import operations
from mika.runtime.operations import CLI, CLI_BY, CONSOLE, SPACE, origin, perform
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build
from tests.protocol import test_moi_carte as on_map
from tests.protocol import test_moi_mail as on_mail
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée
from tests.unit.test_operations import BOARD, events, form

SRC = Path(operations.__file__).resolve().parents[1]
PAGE = "/inspecteur/systeme/operations"
#: Adrien (``bootstrap``) pilote aussi la console : un geste de son espace sous une clé nue s'y lirait « la console »
OPERATORS = frozenset({"user_1"})


def test_a_declared_action_says_where_it_was_done(tmp_path):
    kernel, clock, _ = build(tmp_path, [BOARD])

    async def main():
        await kernel.start()
        await perform(kernel, "board.epingler", form(text="console"), by="user_1", nonce="c1")
        await perform(kernel, "board.epingler", form(text="espace"), by="user_2", nonce="m1", via=SPACE)
        await perform(kernel, "board.epingler", form(text="interdit"), by="user_2", nonce="m2", via=SPACE)  # refusée
        with pytest.raises(ValueError):
            await perform(kernel, "board.epingler", form(text="x"), by="user_2", via="ailleurs")
        audit = events(kernel, rt.OPERATED.name)
        await kernel.stop()
        return audit

    audit = run_virtual(clock, main)
    said = [(e.data.action, e.data.by, e.data.outcome) for e in audit]
    assert ("board.epingler", "user_1", "done") in said  # la console : sa clé nue, comme avant
    assert ("moi.board.epingler", "user_2", "done") in said and ("moi.board.epingler", "user_2", "refused") in said
    assert [origin(e.data.action, e.data.by) for e in audit] == ["", SPACE, SPACE]


def test_the_origin_is_read_from_the_key_and_from_the_command_line():
    assert origin("console.comptes.creer", "user_1") == CONSOLE
    assert origin("moi.partage", "user_2") == SPACE
    assert origin("cli.oublier.person", "user_1") == CLI and origin("identity.relier", CLI_BY) == CLI
    assert origin("identity.relier", "user_1") == ""  # une action déclarée sous sa clé nue : à qui la lit de juger
    assert CLI_BY == cli.CLI_BY  # la ligne de commande se dit sous ce nom, des deux côtés


def test_a_gesture_has_a_french_title_never_its_key_twice(tmp_path):
    kernel, clock, _ = build(tmp_path, [BOARD])

    async def main():
        await kernel.start()
        said = names.Names(kernel)
        out = {key: said.action(key) for key in (
            "console.comptes.creer", "console.comptes.revoquer_jeton", "console.comptes.jeton",
            "console.comptes.sessions", "console.canaux.regler", "console.outils.familles", "console.mcp.fermer",
            "console.mcp.jeton", "console.mcp.pret.jeton", "console.mcp.pret.retirer", "console.mcp.servir",
            "moi.partage", "moi.service_branche", "moi.board.epingler", "cli.board.epingler", "board.epingler",
            "console.reglages.llm", "console.parametres.board", "console.inconnu.une_chose", "moi.inconnu")}
        await kernel.stop()
        return out

    out = run_virtual(clock, main)
    assert out["console.comptes.creer"] == "Compte créé"
    assert out["console.comptes.revoquer_jeton"] == "Application révoquée"
    assert out["console.comptes.jeton"] == "Jeton créé" and out["console.comptes.sessions"] == "Sessions fermées"
    assert out["moi.partage"] == "Partage modifié" and out["moi.service_branche"] == "Service branché"
    # une action déclarée garde son titre, d'où qu'elle vienne (la colonne « depuis » dit d'où)
    assert out["moi.board.epingler"] == out["cli.board.epingler"] == out["board.epingler"] == "Épingler"
    assert out["console.reglages.llm"] == "Réglages · llm" and out["console.parametres.board"] == "Paramètres · board"
    # une clé inconnue : sa forme générique, sans son origine et sans se répéter
    assert out["console.inconnu.une_chose"] == "inconnu · une chose" and out["moi.inconnu"] == "inconnu"
    for key, title in out.items():  # ni la clé, ni son origine, ni un tiret bas
        assert "_" not in title and not title.startswith(("console", "moi", "cli")), (key, title)


def _audited(tree: ast.AST) -> list[tuple[str, bool]]:
    """Les clés qu'un module audite : (clé, ``True`` si ce n'en est que le début, une f-string) — passées à
    ``audit(…)`` ou ``forget_subject(…, action=…)``, ou gardées dans une variable ``audit`` avant l'appel."""
    found: list[tuple[str, bool]] = []

    def take(node: ast.AST | None) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
            found.append((node.value, False))
        elif isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
            found.append((str(node.values[0].value), True))
        elif isinstance(node, ast.IfExp):
            take(node.body)
            take(node.orelse)
        elif isinstance(node, ast.Tuple) and node.elts:
            take(node.elts[0])

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name == "audit" and len(node.args) >= 2:
                take(node.args[1])
            if name == "forget_subject":
                take(next((k.value for k in node.keywords if k.arg == "action"), None))
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple):
            first = node.targets[0].elts[0]
            if isinstance(first, ast.Name) and first.id == "audit":
                take(node.value)
    return found


def test_every_audited_key_has_a_title(world):  # noqa: F811
    _, live, _ = world
    registry = live.kernel.registry
    keys = [(key, prefix, path) for path in sorted(SRC.rglob("*.py"))
            for key, prefix in _audited(ast.parse(path.read_text(encoding="utf-8")))]
    assert len(keys) > 30  # la recherche trouve bien ce que le code audite
    untitled = []
    for key, prefix, path in keys:
        head, _, rest = key.partition(".")
        what = rest.partition(".")[0]
        if prefix:
            titled = what in ("oublier", *names.GESTURE_FAMILIES) or any(k.startswith(key) for k in names.GESTURES)
        else:
            titled = key in names.GESTURES or key in registry.actions or (
                head in names.ORIGINS and (rest in registry.actions or what in ("oublier", *names.GESTURE_FAMILIES)))
        if not titled:
            untitled.append(f"{key} ({path.relative_to(SRC)})")
    assert not untitled, "des gestes audités sans titre (inspector/names.py, GESTURES) : " + ", ".join(untitled)


def test_the_page_says_who_did_what_and_from_where(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)  # user_1, opératrice
    kernel = live.kernel
    stop(client, kernel)

    async def gestures():
        await operations.audit(kernel, "console.comptes.creer", by="user_1", subject_kind="compte", subject="user_2")
        await operations.audit(kernel, "moi.partage", by="user_2", subject_kind="compte", subject="bea")
        await operations.audit(kernel, "teams.cle", by="user_2", subject_kind="compte_teams", subject="bea")
        await operations.audit(kernel, "cli.oublier.person", by=CLI_BY, subject_kind="person", subject="ext_1")

    client.portal.call(gestures)
    page = drawn(client, PAGE)
    shown = page[page.index("<main"):]  # le menu (son libellé) est à part : app/console_menu.py
    assert "Gestes audités" in shown and "et chacun depuis son espace" in shown
    assert "Ce que les opérateurs ont fait depuis la console" not in shown
    feed = page[page.index('class="sys-ops-feed"'):]
    assert "Compte créé" in feed and "Partage modifié" in feed and "Nouvelle clé" in feed
    assert "console · comptes" not in feed and "creer · creer" not in feed
    # d'où : la console (sa clé), son espace (sa clé, ou une action déclarée faite par qui n'est pas opératrice), la
    # ligne de commande
    assert feed.count("depuis la console") == 1 and feed.count("depuis son espace") == 2
    assert feed.count("depuis la ligne de commande") == 1
    # un filtre de petits choix, au bout de la barre d'onglets, appliqué d'un clic (ADR 0176)
    seg = page[page.index('<nav class="seg" aria-label="depuis">'):]
    seg = seg[:seg.index("</nav>")]
    assert all(f"depuis={k}" in seg for k in ("tout", CONSOLE, SPACE, CLI))
    mine = drawn(client, f"{PAGE}?depuis={SPACE}")
    mine = mine[mine.index('class="sys-ops-feed"'):]
    assert "Partage modifié" in mine and "Nouvelle clé" in mine and "Compte créé" not in mine
    typed = drawn(client, f"{PAGE}?depuis={CLI}")
    typed = typed[typed.index('class="sys-ops-feed"'):]
    assert "Oublier" in typed and "Compte créé" not in typed and "Partage modifié" not in typed


def test_a_gesture_links_only_a_sheet_that_opens(world):  # noqa: F811
    """« Sur quoi » mène à la fiche de l'objet si elle s'ouvre, et seulement alors (relecture du lot L03b). Le journal ne
    s'efface pas : il garde des objets retirés depuis, et des gestes audités sous une sorte que la console donne à autre
    chose — un partage sous « mail » (ses fiches sont des messages), un compte de connexion sous « compte » (ses fiches
    sont des boîtes)."""
    client, live, _ = on_mail.with_mail(world)
    kernel = live.kernel
    stop(client, kernel)

    async def gestures():
        await operations.audit(kernel, "moi.boite", by="user_1", subject_kind="compte", subject="pro")
        await operations.audit(kernel, "moi.boite_retiree", by="user_1", subject_kind="compte", subject="partie")
        await operations.audit(kernel, "console.comptes.creer", by="user_1", subject_kind="compte", subject="bea")
        await operations.audit(kernel, "moi.partage", by="user_1", subject_kind="mail", subject="pro")

    client.portal.call(gestures)
    page = drawn(client, PAGE)
    feed = page[page.index('class="sys-ops-feed"'):]
    feed = feed[:feed.index("</ol>")]
    links = re.findall(r'href="(/inspecteur/fiche/[^"]+)"', feed)
    assert links == ["/inspecteur/fiche/compte/pro"] and client.get(links[0]).status_code == 200
    assert ">Compte pro</a>" in feed
    # le reste dit sa clé, en texte, sa sorte en bulle
    assert all(f'title="{kind}">{key}</span>' in feed for kind, key in (("compte", "partie"), ("compte", "bea"),
                                                                        ("mail", "pro")))


# ── l'espace d'une personne : chaque geste y dit d'où il vient, même fait par une opératrice ──


def _gestures(live, part: str) -> list[tuple[str, str]]:
    """Les gestes audités (clé, qui) dont la clé contient ``part``, dans l'ordre du journal."""
    return [(e.data.action, e.data.by) for e in on_mail.journal(live, rt.OPERATED) if part in e.data.action]


def test_a_reply_from_her_space_and_the_draft_it_withdraws_say_so(world):  # noqa: F811
    client, live, box = on_mail.with_mail(world)
    on_mail.propose(client, live, box)
    r = on_mail.post(client, "/mail/reply", {"ref": on_mail.PROJET, "to": "lea@example.test",
                                             "subject": "Re: Maquettes", "body": "Je réponds moi-même.",
                                             "quote": False})
    assert r.status_code == 200, r.text
    # la réponse, et le refus de son brouillon qui attendait (un geste à part, ou celui de la réponse) : son espace
    done = _gestures(live, "email.")
    assert ("moi.email.repondre", "user_1") in done
    assert {gesture_origin(key, by, OPERATORS) for key, by in done} == {SPACE}  # rien n'y passe pour « la console »


def test_a_stop_noted_from_her_space_says_so(world):  # noqa: F811
    client, live, _ = on_map.plugged(world)
    trip = on_map.new_trip(client)
    stop_id = on_map.stop(client, trip, "Le Belvédère", 45.3, 6.3)
    noted = on_map.post(client, f"{on_map.VOYAGES}/{trip}/arrets/{stop_id}", {"note": "Au lever du soleil"})
    both = on_map.post(client, f"{on_map.VOYAGES}/{trip}/arrets/{stop_id}", {"day": 2, "index": 0, "note": "Le soir"},
                       key="geste-1")
    assert noted.status_code == both.status_code == 200, (noted.text, both.text)
    done = _gestures(live, "trips.")
    assert ("moi.trips.noter_arret", "user_1") in done and ("moi.trips.deplacer_arret", "user_1") in done
    assert {gesture_origin(key, by, OPERATORS) for key, by in done} == {SPACE}


def test_her_teams_extension_key_made_from_her_space_says_so(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    made = on_mail.post(client, "/teams/account/save", {"values": {"label": "Teams d'Adrien", "display_name": "Adrien"}})
    assert made.status_code == 200, made.text
    account = made.json()["account"]
    assert on_mail.post(client, "/teams/account/key", {"account": account}).status_code == 200
    assert on_mail.post(client, "/teams/account/revoke", {"account": account}).status_code == 200
    done = _gestures(live, "teams")
    assert ("moi.teams.cle", "user_1") in done and ("moi.teams.retirer_cle", "user_1") in done
    assert {gesture_origin(key, by, OPERATORS) for key, by in done} == {SPACE}
    # son titre est celui de l'action que la console déclare : rien à recopier dans ``GESTURES``
    said = names.Names(live.kernel)
    assert said.action("moi.teams.cle") == said.action("teams.cle") == "Nouvelle clé"
    assert said.action("moi.teams.retirer_cle") == "Retirer la clé"


def test_every_path_of_a_persons_space_says_where_it_comes_from():
    """Ce que l'espace d'une personne (``app/moi/``, et son chat : ``app/mindport.py``) fait par une action déclarée
    passe ``via=SPACE`` (``Call.act`` le fait), et ce qu'il audite lui-même a une clé « moi.… » : sinon Système ›
    Gestes audités range dans « la console » ce qu'une opératrice a fait depuis son espace."""
    unmarked: list[str] = []
    performs = audits = 0
    for path in [*sorted((SRC / "app" / "moi").glob("*.py")), SRC / "app" / "mindport.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            f = node.func if isinstance(node, ast.Call) else None
            if (f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else "") != "perform":
                continue
            performs += 1
            via = next((k.value for k in node.keywords if k.arg == "via"), None)
            if not ((isinstance(via, ast.Name) and via.id == "SPACE")
                    or (isinstance(via, ast.Attribute) and via.attr == "SPACE")):
                unmarked.append(f"{path.relative_to(SRC)}:{node.lineno} (perform sans via=SPACE)")
        for key, _ in _audited(tree):
            audits += 1
            if not key.startswith(f"{SPACE}."):
                unmarked.append(f"{path.relative_to(SRC)} (audite « {key} »)")
    assert performs >= 3 and audits >= 10  # la recherche trouve bien les chemins de cet espace (Call.act, le chat…)
    assert not unmarked, "un geste de l'espace d'une personne ne dit pas d'où il vient : " + ", ".join(unmarked)
