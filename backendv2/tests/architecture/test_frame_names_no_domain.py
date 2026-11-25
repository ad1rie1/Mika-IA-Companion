"""Une politique : le cadre d'``app`` ne nomme aucun domaine (ADR 0310).

Ce que la couche ``app`` sait d'un domaine (le courrier, Teams, l'agenda…) vit dans son dossier, ``app/domains/<nom>/``,
et sa fiche (``Domain``) dit ce qu'il apporte. Le **cadre** — tout le reste d'``app`` : le serveur, le schéma, la
sauvegarde, l'API par personne, la console — parcourt ``DOMAINS`` et ne nomme aucun domaine. Cette garde relit les
imports de chaque source d'``app`` (``ast`` : jamais un commentaire) :

- **un fichier du cadre n'importe rien d'un domaine** : ni son plugin ou sa faculté, ni son adaptateur, son contrat
  ou son port (``PACKAGES``), ni son dossier (``mika.app.domains.<nom>`` — seulement ``mika.app.domains``), ni un
  module d'``app`` qui est à lui et attend son déménagement (``TO_MOVE``) ;
- **ce qui reste à sortir du cadre est excusé nommément** (``STILL`` : fichier → domaines encore nommés). Cette
  table ne fait que rétrécir : on n'y ajoute rien, et une excuse qui ne sert plus — le fichier ne nomme plus ce
  domaine, ou n'existe plus — fait échouer la garde. ``FOREVER`` porte ce que le cadre nomme exprès, avec sa raison ;
- **un domaine ne nomme un autre domaine que s'il le déclare** (``Domain.needs``), et un besoin déclaré qui ne sert
  plus se retire ;
- **le registre** (``app/domains/__init__.py``) liste les fiches et rien d'autre : il ne nomme aucun paquet du moteur ;
- **une fiche n'importe rien d'``app``** (``app/domains/<nom>/__init__.py`` : seulement la forme d'une fiche,
  ``mika.app.domains.domain`` ; aux couches du dessous elle ne prend que de quoi se dire — une ``Destination``, un
  ``MenuLink``) : elle nomme les modules de ses parts, que le cadre importe au moment d'assembler. Le
  registre est donc une feuille de l'arbre des imports, que tout module d'``app`` peut lire ; et **chaque part nommée
  existe** et porte son nom convenu (``wire``, ``SETTINGS``, ``routes``, ``LIVE``, ``SHARING``, ``ACCOUNTS``,
  ``OUTSIDE``, ``CONSOLE``, ``preview``, ``add``).

Le contrôle est une fonction du texte des sources (``offences``) : les derniers tests l'essaient sur de petits
sources factices, pour qu'il échoue vraiment quand on nomme un domaine.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

from mika.app.domains import (
    DOMAINS,
    AccountsPart,
    ConsolePart,
    Domain,
    LivePart,
    OutsidePart,
    PersonPart,
    SharingPart,
    TablePart,
    part,
)
from mika.app.handmade.person import TABS as PERSON_TABS
from mika.app.handmade.person import account_tabs
from mika.app.handmade.rights import share_consoles
from mika.app.me.accounts import CHANNELS
from mika.app.me.outside import OUTSIDE
from mika.app.me.sharing import KINDS as SHARED_KINDS
from mika.app.settings import SettingsPart

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mika"
APP = SRC / "app"
#: le dossier des domaines, sous ``app/``
HOME = "domains"
#: le module qui porte la forme d'une fiche : le seul qu'une fiche importe
FORM = "mika.app.domains.domain"

#: chaque domaine et ses paquets hors d'``app`` : son plugin ou sa faculté, son adaptateur, son contrat, son port
PACKAGES: dict[str, tuple[str, ...]] = {
    "contacts": ("adapters.contacts", "plugins.contacts", "ports.contacts"),
    "wakeup": ("plugins.wakeup", "contracts.wakeup", "ports.wakeup"),
    "phone": ("plugins.phone", "contracts.phone", "ports.phone"),
    "forge": ("adapters.forge", "plugins.forge", "contracts.forge", "ports.forge", "ports.forge_args"),
    "senses": ("adapters.feeds", "adapters.camera", "plugins.rss", "plugins.camera", "plugins.sensors",
               "contracts.rss", "contracts.camera", "contracts.sensors", "ports.feeds", "ports.camera"),
    "tools": ("adapters.mcp", "plugins.mcp", "plugins.web", "contracts.mcp", "contracts.web", "ports.mcp"),
    "maps": ("adapters.maps", "plugins.trips", "plugins.location", "contracts.trips", "contracts.location",
             "ports.maps"),
    "teams": ("adapters.teams", "plugins.teams", "contracts.teams", "ports.teams"),
    "agenda": ("adapters.agenda", "plugins.agenda", "contracts.agenda", "ports.agenda"),
    "mail": ("adapters.mail", "plugins.email", "contracts.email", "ports.mail"),
    "projects": ("faculties.projects", "contracts.projects", "adapters.workshop", "ports.workshop"),
}

#: ce qui loge dans le paquet d'un domaine sans être à lui : le nommer, ce n'est pas nommer le domaine
SHARED: dict[str, str] = {
    "adapters.mcp.relay": "le relais MCP par lequel la CLI de Claude Code appelle ses outils (ADR 0072) : une pièce de "
                          "la passerelle des modèles (``adapters/llm/claude_code.py``), pas de ses outils venus "
                          "d'ailleurs",
}

#: les modules d'``app`` qui sont à un domaine et attendent leur déménagement dans son dossier : les importer, c'est
#: déjà le nommer. Un module déménagé sort de cette table (il n'existe plus : la garde le dit)
TO_MOVE: dict[str, tuple[str, ...]] = {}

#: ce que le cadre nomme exprès, pour toujours, et pourquoi
FOREVER: dict[str, str] = {
    "composition.py": "la liste des facultés et des plugins, les lots d'outils de chaque sorte d'épisode et l'ordre "
                      "de son prompt : des décisions, pas de la plomberie (ADR 0151)",
}

#: ce qui reste à sortir du cadre : fichier d'``app`` → domaines qu'il nomme encore. Elle ne fait que rétrécir
STILL: dict[str, set[str]] = {
    "handmade/directory.py": {"contacts"},
    "handmade/tabs/people.py": {"contacts"},
    "handmade/tabs/thoughts.py": {"mail", "senses", "teams"},
    "mindport.py": {"maps", "projects", "senses", "wakeup"},
    "preview/__init__.py": {"mail", "maps", "projects", "teams"},
}


def imported(text: str) -> Iterator[str]:
    """Les modules qu'un source importe, lus dans l'arbre : ``import a.b`` donne ``a.b`` ; ``from a.b import c`` donne
    ``a.b`` et ``a.b.c`` (``c`` peut être un module)."""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def named(text: str, packages: Mapping[str, tuple[str, ...]], *, folders: bool = True,
          shared: Mapping[str, str] = SHARED) -> set[str]:
    """Les domaines qu'un source nomme par ses imports : un de leurs paquets (``packages``), ou leur dossier sous
    ``app/domains/`` (``folders``). Un module logé dans le paquet d'un domaine sans être à lui (``shared``) ne le
    nomme pas."""
    out: set[str] = set()
    for module in imported(text):
        if not module.startswith("mika."):
            continue
        rest = module[len("mika."):]
        if any(_within(rest, own) for own in shared):
            continue
        for domain, owned in packages.items():
            if any(_within(rest, p) for p in owned) or (folders and _within(rest, f"app.{HOME}.{domain}")):
                out.add(domain)
    return out


def offences(sources: Mapping[str, str], *, packages: Mapping[str, tuple[str, ...]],
             still: Mapping[str, set[str]], forever: Mapping[str, str],
             needs: Mapping[str, tuple[str, ...]]) -> list[str]:
    """Ce qui enfreint la politique, en phrases. ``sources`` : le texte de chaque fichier d'``app``, par son chemin
    sous ``app/`` ; ``needs`` : ce que la fiche de chaque domaine déclare lire des autres."""
    out: list[str] = []
    used: dict[str, set[str]] = {}
    for path, text in sorted(sources.items()):
        parts = path.split("/")
        if parts[0] != HOME:  # le cadre
            if path in forever:
                continue
            got, excused = named(text, packages), still.get(path, set())
            out += [f"{path} nomme le domaine « {d} » : le cadre lit les fiches (DOMAINS), il ne nomme aucun domaine"
                    for d in sorted(got - excused)]
            out += [f"{path} est excusé pour « {d} » dans STILL mais ne le nomme plus : retirer l'excuse"
                    for d in sorted(excused - got)]
        elif len(parts) == 2:  # le registre et la forme d'une fiche
            out += [f"{path} nomme un paquet du domaine « {d} » : le registre liste les fiches, rien d'autre"
                    for d in sorted(named(text, packages, folders=False))]
        else:  # le dossier d'un domaine
            own = parts[1]
            if parts[2:] == ["__init__.py"]:  # sa fiche : elle nomme ses parts, elle n'importe rien
                out += [f"{path} importe {m} : d'``app``, une fiche n'importe que la forme d'une fiche ({FORM}) ; elle "
                        "nomme les modules de ses parts" for m in sorted(set(imported(text)))
                        if _within(m, "mika.app") and not _within(m, FORM)]
            if own not in packages:
                out.append(f"{path} : « {own} » n'est pas un domaine que cette garde connaît (PACKAGES)")
                continue
            others = named(text, packages) - {own}
            used.setdefault(own, set()).update(others)
            out += [f"{path} nomme le domaine « {d} », que la fiche de « {own} » ne déclare pas (Domain.needs)"
                    for d in sorted(others - set(needs.get(own, ())))]
    out += [f"{path} est excusé dans STILL mais n'existe plus" for path in sorted(set(still) - set(sources))]
    out += [f"{path} est excusé dans FOREVER mais n'existe plus" for path in sorted(set(forever) - set(sources))]
    out += [f"la fiche de « {own} » déclare le besoin « {d} », que son dossier ne nomme pas : le retirer"
            for own, declared in sorted(needs.items()) for d in sorted(set(declared) - used.get(own, set()))]
    return out


def _sources() -> dict[str, str]:
    return {p.relative_to(APP).as_posix(): p.read_text(encoding="utf-8") for p in sorted(APP.rglob("*.py"))
            if "__pycache__" not in p.parts and "versions" not in p.parts}


def _exists(module: str) -> bool:
    path = SRC.joinpath(*module.split("."))
    return path.is_dir() or path.with_suffix(".py").is_file()


def _all(packages: Mapping[str, tuple[str, ...]], moving: Mapping[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    return {domain: (*owned, *moving.get(domain, ())) for domain, owned in packages.items()}


def test_the_frame_names_no_domain_beyond_what_is_still_excused():
    found = offences(_sources(), packages=_all(PACKAGES, TO_MOVE), still=STILL, forever=FOREVER,
                     needs={d.name: d.needs for d in DOMAINS})
    assert not found, "\n".join(found)


def test_every_package_of_a_domain_exists():
    """Un paquet renommé ou un module déménagé qui resterait dans les tables ne garderait plus rien."""
    gone = sorted(f"{domain} : {module}" for table in (PACKAGES, TO_MOVE) for domain, owned in table.items()
                  for module in owned if not _exists(module))
    assert not gone, gone
    assert all(_exists(module) for module in SHARED), sorted(SHARED)
    assert all(any(_within(module, p) for owned in PACKAGES.values() for p in owned) for module in SHARED), \
        "ce qui n'est dans le paquet d'aucun domaine n'a pas à être excepté"
    assert set(TO_MOVE) <= set(PACKAGES)


def test_the_listed_domains_are_the_folders_and_the_guard_knows_them():
    names = [d.name for d in DOMAINS]
    assert len(names) == len(set(names)), "un domaine inscrit deux fois"
    assert set(names) <= set(PACKAGES), sorted(set(names) - set(PACKAGES))
    folders = sorted(p.name for p in (APP / HOME).iterdir() if p.is_dir() and p.name != "__pycache__")
    assert folders == sorted(names), "chaque dossier de app/domains/ a sa fiche dans DOMAINS, et l'inverse"
    assert all((APP / HOME / n / "__init__.py").is_file() for n in names)
    unknown = sorted(f"{d.name} → {n}" for d in DOMAINS for n in d.needs if n not in PACKAGES or n == d.name)
    assert not unknown, unknown


def test_every_part_a_card_names_exists_and_carries_its_name():
    """Une fiche nomme les modules de ses parts au lieu de les importer : une faute de frappe ne se verrait qu'à
    l'assemblage. Chaque module nommé s'importe ici, et porte le nom que le cadre y lit."""
    for d in DOMAINS:
        for module in (d.wiring, d.settings, d.api, d.live, d.sharing, d.accounts, d.outside, d.console, d.preview,
                       d.cli, d.backup):
            assert module is None or _within(module, f"mika.app.{HOME}.{d.name}"), f"{d.name} : {module} est hors de son dossier"
        assert d.wiring is None or callable(part(d.wiring, "wire")), d.name
        assert d.settings is None or issubclass(part(d.settings, "SETTINGS"), SettingsPart), d.name
        assert d.api is None or callable(part(d.api, "routes")), d.name
        assert all(callable(count) for count in part(d.api, "COUNTERS", {}).values()), d.name
        assert d.live is None or isinstance(part(d.live, "LIVE"), LivePart), d.name
        shared = part(d.sharing, "SHARING")
        assert shared is None or isinstance(shared, SharingPart), d.name
        if shared is not None:  # sa part des partages : une sorte de KINDS, ses mots, ce qu'elle appelle
            assert shared.kind in SHARED_KINDS and shared.word and shared.key_limit > 0, d.name
            assert callable(shared.every) and callable(shared.share), d.name
            assert all(f is None or callable(f) for f in (shared.write, shared.sharer, shared.names)), d.name
        held = part(d.accounts, "ACCOUNTS")
        assert held is None or isinstance(held, AccountsPart), d.name
        if held is not None:  # les comptes de son canal : un canal de CHANNELS, ses mots, ce qu'elle appelle
            assert held.canal in CHANNELS and held.kind and held.family and held.tab and held.label, d.name
            assert held.noun and all(isinstance(b, str) and b for b in held.badges), d.name
            assert all(callable(f) for f in (held.held, held.owned, held.shown, held.configured)), d.name
        elsewhere = part(d.outside, "OUTSIDE")
        assert elsewhere is None or isinstance(elsewhere, OutsidePart), d.name
        if elsewhere is not None:  # ce qui vient d'ailleurs chez lui : une sorte de OUTSIDE, ses mots, ce qu'elle appelle
            assert elsewhere.sort in OUTSIDE and elsewhere.bundle.endswith(".") and len(elsewhere.bundle) > 1, d.name
            assert elsewhere.title and elsewhere.why, d.name
            assert all(callable(f) for f in (elsewhere.seen, elsewhere.tool, elsewhere.allowance, elsewhere.name,
                                             elsewhere.about, elsewhere.row)), d.name
        assert d.console is None or isinstance(part(d.console, "CONSOLE"), ConsolePart), d.name
        if d.console is not None:  # où mène, dans la console, la ressource d'un de ses partages, où il se retire
            console = part(d.console, "CONSOLE")
            assert all(f is None or callable(f) for f in (console.shared, console.unshared)), d.name
            assert console.shared is None or d.sharing is not None, f"{d.name} : un partage dans la console sans sorte"
            # le tableau de droits qu'il règle dans Réglages › Droits : le début de ses clés, ce qu'il appelle
            assert console.table is None or isinstance(console.table, TablePart), d.name
            if console.table is not None:
                assert console.table.prefix.endswith(":") and len(console.table.prefix) > 1, d.name
                assert all(callable(f) for f in (console.table.edit, console.table.editor, console.table.routes)), d.name
        sheet = _person_part(d)
        assert sheet is None or isinstance(sheet, PersonPart), d.name
        if sheet is not None:  # sa part de la fiche d'une personne : ce qu'elle nomme est un onglet qu'elle dessine
            assert (sheet.tabs or sheet.owned) and all(callable(draw) for draw in sheet.tabs.values()), d.name
            # … ou, en sous-onglet de Comptes, ce qu'elle a chez lui : (son ancre, son nom, ce qui le lit)
            assert sheet.owned is None or (len(sheet.owned) == 3 and all(isinstance(x, str) and x for x in sheet.owned[:2])
                                           and callable(sheet.owned[2])), d.name
            assert set(sheet.formed) <= set(sheet.tabs), f"{d.name} : {sorted(set(sheet.formed) - set(sheet.tabs))}"
            # … ou, pour un compte qui s'ajoute à celui du cadre, un onglet du cadre
            unknown = set(sheet.counts) - {*sheet.tabs, *PERSON_TABS, *account_tabs()}
            assert not unknown and all(callable(count) for count in sheet.counts.values()), f"{d.name} : {sorted(unknown)}"
            assert sheet.hidden is None or callable(sheet.hidden), d.name
            assert sheet.routes is None or callable(sheet.routes), d.name
        assert d.preview is None or callable(part(d.preview, "preview")), d.name
        assert d.cli is None or callable(part(d.cli, "add")), d.name
        kept = (*part(d.backup, "UNSAVED", ()), *part(d.backup, "SAVED", ()))
        assert d.backup is None or (kept and all(isinstance(path, str) and path for path in kept)), d.name
        assert d.base is None or _exists(d.base.models.removeprefix("mika.")), d.name


def test_each_kind_of_share_has_its_part_said_once():
    """Les partages lisent les sortes dans l'ordre de ``KINDS`` (``app/me/sharing.py``) : une sorte sans part, ou
    dite par deux, ferait échouer le premier partage lu — ici, avant."""
    kinds = [part(d.sharing, "SHARING").kind for d in DOMAINS if d.sharing is not None]
    assert sorted(kinds) == sorted(SHARED_KINDS), kinds


def test_each_kind_of_share_says_where_it_leads_in_the_console():
    """Réglages › Droits › Partages et l'onglet Comptes d'une personne mènent à la ressource d'un partage, et à ses
    lignes d'accès quand la console ne le retire pas (``app/handmade/rights.py::share_consoles``) : la part de console
    du domaine qui partage le dit, pour chaque sorte — sinon la première page qui en montre un échouerait, ici avant."""
    share_consoles.cache_clear()
    assert list(share_consoles()) == list(SHARED_KINDS)


def test_a_table_set_in_the_rights_page_has_one_hand():
    """Réglages › Droits règle ici le tableau d'une ressource par la part dont le début des clés est le sien
    (``app/handmade/rights.py::table_of``, la première qui convient) : deux parts sur les mêmes clés, et la seconde ne
    réglerait jamais rien — sans bruit."""
    prefixes = [c.table.prefix for d in DOMAINS if d.console is not None
                if (c := part(d.console, "CONSOLE")).table is not None]
    twice = [(a, b) for i, a in enumerate(prefixes) for j, b in enumerate(prefixes) if i != j and b.startswith(a)]
    assert prefixes and not twice, twice


def test_each_sort_from_elsewhere_has_its_part_said_once():
    """L'écran Outils lit ce qui vient d'ailleurs sorte par sorte, dans l'ordre de ``OUTSIDE`` (``app/me/outside.py``),
    et Réglages › Droits par leur sorte : une sorte sans part, ou dite par deux, ferait échouer la première lecture —
    ici, avant. Leurs familles d'outils ne se recouvrent pas : sinon un outil serait rangé sous deux sortes."""
    found = [part(d.outside, "OUTSIDE") for d in DOMAINS if d.outside is not None]
    assert sorted(p.sort for p in found) == sorted(OUTSIDE), [p.sort for p in found]
    bundles = [p.bundle for p in found]
    twice = [(a, b) for i, a in enumerate(bundles) for j, b in enumerate(bundles) if i != j and b.startswith(a)]
    assert not twice, twice


def test_each_channel_has_its_accounts_said_once():
    """Les comptes se lisent canal par canal, dans l'ordre de ``CHANNELS`` (``app/me/accounts.py``) : un canal sans
    part, ou dit par deux, ferait échouer la première lecture de ses comptes — ici, avant. Deux canaux ne remplissent
    pas le même onglet de la fiche d'une personne."""
    found = [part(d.accounts, "ACCOUNTS") for d in DOMAINS if d.accounts is not None]
    assert sorted(p.canal for p in found) == sorted(CHANNELS), [p.canal for p in found]
    assert len({p.tab for p in found}) == len(found), [p.tab for p in found]


def test_a_pane_of_the_accounts_of_a_person_is_said_once():
    """L'onglet Comptes d'une personne a un sous-onglet par canal (``AccountsPart.tab``), puis un par part qui y montre
    ce qu'elle a chez elle (``PersonPart.owned``), puis Partages : leurs ancres sont des ``id`` de la page — une ancre
    dite deux fois ouvrirait le premier des deux sous-onglets, sans bruit."""
    anchors = [*account_tabs(), *(s.owned[0] for d in DOMAINS if (s := _person_part(d)) is not None and s.owned),
               "partages"]
    assert len(anchors) == len(set(anchors)), anchors


def _person_part(d: Domain) -> PersonPart | None:
    return part(d.console, "CONSOLE").person if d.console is not None else None


def test_a_tab_of_the_sheet_of_a_person_is_drawn_by_one_hand():
    """La fiche d'une personne réunit les onglets du cadre, puis ceux des parts (``every_tab``) : un onglet que deux
    parts dessinent, ou qu'une part reprend au cadre, ne serait dessiné que par la dernière — sans bruit."""
    seen = dict.fromkeys({**PERSON_TABS, **account_tabs()}, "le cadre")
    twice = []
    for d in DOMAINS:
        sheet = _person_part(d)
        for tab in sheet.tabs if sheet is not None else ():
            if tab in seen:
                twice.append(f"{tab} : {seen[tab]} et {d.name}")
            seen.setdefault(tab, d.name)
    assert not twice, twice


# ── le contrôle, essayé sur des sources factices ──

TOY_PACKAGES = {"mail": ("plugins.email", "adapters.mail"), "agenda": ("plugins.agenda",)}


def _toy(sources: Mapping[str, str], *, still: Mapping[str, set[str]] | None = None,
         needs: Mapping[str, tuple[str, ...]] | None = None) -> list[str]:
    return offences(sources, packages=TOY_PACKAGES, still=still or {}, forever={}, needs=needs or {})


def test_the_guard_passes_a_frame_that_reads_the_registry():
    assert _toy({"server.py": "from mika.app.domains import DOMAINS\nfrom mika.adapters.web.hub import Hub\n",
                 "domains/__init__.py": "from mika.app.domains.mail import MAIL\n",
                 "domains/mail/__init__.py": "from mika.app.domains.domain import Domain\n",
                 "domains/mail/api.py": "from mika.plugins.email import EMAIL\n"}) == []


def test_the_guard_fails_when_the_frame_names_a_domain():
    assert _toy({"server.py": "from mika.adapters.mail import ImapSmtpMail\n"}) == [
        "server.py nomme le domaine « mail » : le cadre lit les fiches (DOMAINS), il ne nomme aucun domaine"]
    # son dossier aussi : le cadre n'importe que le registre
    assert _toy({"server.py": "from mika.app.domains.mail.api import routes\n"}) == [
        "server.py nomme le domaine « mail » : le cadre lit les fiches (DOMAINS), il ne nomme aucun domaine"]
    assert _toy({"server.py": "from mika.app.domains import mail\n"}) == [
        "server.py nomme le domaine « mail » : le cadre lit les fiches (DOMAINS), il ne nomme aucun domaine"]


def test_what_lodges_in_a_package_of_a_domain_without_being_its_own_names_nothing():
    sources = {"server.py": "from mika.adapters.mail.relay import Relay\n"}
    assert _toy(sources) == ["server.py nomme le domaine « mail » : le cadre lit les fiches (DOMAINS), il ne nomme "
                             "aucun domaine"]
    assert named(sources["server.py"], TOY_PACKAGES, shared={"adapters.mail.relay": "une pièce du cadre"}) == set()


def test_a_comment_or_a_string_names_nothing():
    assert _toy({"server.py": '"""Voir mika.plugins.email."""\n# from mika.adapters.mail import ImapSmtpMail\n'
                              'WHERE = "mika.plugins.agenda"\n'}) == []


def test_what_is_still_excused_passes_and_an_excuse_that_no_longer_serves_fails():
    sources = {"server.py": "from mika.adapters.mail import ImapSmtpMail\n"}
    assert _toy(sources, still={"server.py": {"mail"}}) == []
    assert _toy(sources, still={"server.py": {"mail", "agenda"}, "gone.py": {"mail"}}) == [
        "server.py est excusé pour « agenda » dans STILL mais ne le nomme plus : retirer l'excuse",
        "gone.py est excusé dans STILL mais n'existe plus"]


def test_a_domain_names_another_only_if_its_card_says_so():
    sources = {"domains/agenda/api.py": "from mika.plugins.agenda import AGENDA\nfrom mika.adapters.mail import x\n"}
    assert _toy(sources) == [
        "domains/agenda/api.py nomme le domaine « mail », que la fiche de « agenda » ne déclare pas (Domain.needs)"]
    assert _toy(sources, needs={"agenda": ("mail",)}) == []
    assert _toy({"domains/agenda/api.py": "from mika.plugins.agenda import AGENDA\n"}, needs={"agenda": ("mail",)}) == [
        "la fiche de « agenda » déclare le besoin « mail », que son dossier ne nomme pas : le retirer"]


def test_a_card_imports_nothing_but_its_form():
    assert _toy({"domains/mail/__init__.py": "from mika.app.domains.domain import Domain\n"}) == []
    assert _toy({"domains/mail/__init__.py": "from mika.app.domains.mail.api import routes\n"}) == [
        "domains/mail/__init__.py importe mika.app.domains.mail.api : d'``app``, une fiche n'importe que la forme d'une "
        "fiche (mika.app.domains.domain) ; elle nomme les modules de ses parts",
        "domains/mail/__init__.py importe mika.app.domains.mail.api.routes : d'``app``, une fiche n'importe que la "
        "forme d'une fiche (mika.app.domains.domain) ; elle nomme les modules de ses parts"]
    # aux couches du dessous, elle prend de quoi se dire
    assert _toy({"domains/mail/__init__.py": "from mika.inspector.catalog import Destination\n"}) == []


def test_the_registry_lists_cards_and_a_folder_must_be_a_known_domain():
    assert _toy({"domains/__init__.py": "from mika.plugins.email import EMAIL\n"}) == [
        "domains/__init__.py nomme un paquet du domaine « mail » : le registre liste les fiches, rien d'autre"]
    assert _toy({"domains/drive/api.py": "X = 1\n"}) == [
        "domains/drive/api.py : « drive » n'est pas un domaine que cette garde connaît (PACKAGES)"]
