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
  existe** et porte son nom convenu (``wire``, ``routes``, ``LIVE``, ``CONSOLE``, ``preview``, ``add``).

Le contrôle est une fonction du texte des sources (``offences``) : les derniers tests l'essaient sur de petits
sources factices, pour qu'il échoue vraiment quand on nomme un domaine.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

from mika.app.domains import DOMAINS, ConsolePart, LivePart, part

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

#: les modules d'``app`` qui sont à un domaine et attendent leur déménagement dans son dossier : les importer, c'est
#: déjà le nommer. Un module déménagé sort de cette table (il n'existe plus : la garde le dit)
TO_MOVE: dict[str, tuple[str, ...]] = {
    "agenda": ("app.agenda_desk", "app.her_agenda", "app.me.agenda", "app.handmade.tabs.agendas",
               "app.handmade.subjects.agenda", "app.handmade.agenda_reads"),
    "mail": ("app.me.mail", "app.handmade.tabs.mail", "app.handmade.subjects.mail", "app.preview.mail"),
    "projects": ("app.me.projects", "app.me.project_activity", "app.me.project_code", "app.me.project_docs",
                 "app.me.project_manage", "app.me.docs_mcp", "app.handmade.tabs.projects",
                 "app.handmade.subjects.project", "app.handmade.subjects.project_activity",
                 "app.handmade.subjects.project_code", "app.handmade.subjects.project_diagram",
                 "app.handmade.subjects.project_docs", "app.handmade.subjects.project_git",
                 "app.handmade.subjects.project_goals", "app.handmade.subjects.project_links",
                 "app.handmade.subjects.project_tickets", "app.handmade.subjects.project_zones",
                 "app.preview.projects", "app.preview.git", "app.preview.activity"),
}

#: ce que le cadre nomme exprès, pour toujours, et pourquoi
FOREVER: dict[str, str] = {
    "composition.py": "la liste des facultés et des plugins, les lots d'outils de chaque sorte d'épisode et l'ordre "
                      "de son prompt : des décisions, pas de la plomberie (ADR 0151)",
}

#: ce qui reste à sortir du cadre : fichier d'``app`` → domaines qu'il nomme encore. Elle ne fait que rétrécir
STILL: dict[str, set[str]] = {
    "agenda_desk.py": {"agenda"},
    "authors.py": {"mail"},
    "backup.py": {"maps", "projects"},
    "cli/models.py": {"tools"},
    "cli/plugins.py": {"agenda", "mail"},
    "handmade/agenda_reads.py": {"agenda"},
    "handmade/approval_sources.py": {"agenda", "mail", "phone", "teams", "tools"},
    "handmade/directory.py": {"contacts"},
    "handmade/pages.py": {"agenda", "mail", "projects"},
    "handmade/person/__init__.py": {"agenda", "maps", "projects", "teams", "tools"},
    "handmade/person/agendas.py": {"agenda"},
    "handmade/person/identifies.py": {"contacts"},
    "handmade/person/senses.py": {"maps", "phone", "senses"},
    "handmade/person/voyages.py": {"maps"},
    "handmade/rights.py": {"agenda", "forge", "tools"},
    "handmade/subjects/agenda.py": {"agenda"},
    "handmade/subjects/mail.py": {"mail"},
    "handmade/subjects/project.py": {"forge", "projects"},
    "handmade/subjects/project_activity.py": {"projects"},
    "handmade/subjects/project_code.py": {"projects"},
    "handmade/subjects/project_diagram.py": {"projects"},
    "handmade/subjects/project_docs.py": {"projects"},
    "handmade/subjects/project_git.py": {"projects"},
    "handmade/subjects/project_goals.py": {"projects"},
    "handmade/subjects/project_links.py": {"projects"},
    "handmade/subjects/project_tickets.py": {"projects"},
    "handmade/subjects/project_zones.py": {"projects"},
    "handmade/tabs/agendas.py": {"agenda"},
    "handmade/tabs/mail.py": {"mail"},
    "handmade/tabs/people.py": {"contacts"},
    "handmade/tabs/thoughts.py": {"mail", "senses", "teams"},
    "handmade/waiting.py": {"contacts", "mail", "teams"},
    "me/agenda.py": {"agenda", "mail"},
    "me/api.py": {"mail"},
    "me/assembly.py": {"agenda", "mail", "projects"},
    "me/changes.py": {"agenda", "mail", "projects"},
    "me/docs_mcp.py": {"mail", "projects", "tools"},
    "me/mail.py": {"mail"},
    "me/project_activity.py": {"projects"},
    "me/project_code.py": {"projects"},
    "me/project_docs.py": {"projects"},
    "me/project_manage.py": {"projects"},
    "me/projects.py": {"forge", "projects"},
    "me/rights.py": {"forge", "mail", "teams", "tools"},
    "me/settings.py": {"mail", "teams"},
    "me/sharing.py": {"agenda", "mail", "teams", "tools"},
    "mindport.py": {"maps", "projects", "senses", "wakeup"},
    "preview/__init__.py": {"mail", "maps", "projects", "teams"},
    "preview/git.py": {"projects"},
    "preview/mail.py": {"mail"},
    "preview/projects.py": {"projects"},
    "server.py": {"agenda", "contacts", "mail", "projects", "tools"},
    "settings.py": {"agenda", "mail", "teams"},
    "settings_sections/plugins.py": {"agenda", "mail", "teams"},
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


def named(text: str, packages: Mapping[str, tuple[str, ...]], *, folders: bool = True) -> set[str]:
    """Les domaines qu'un source nomme par ses imports : un de leurs paquets (``packages``), ou leur dossier sous
    ``app/domains/`` (``folders``)."""
    out: set[str] = set()
    for module in imported(text):
        if not module.startswith("mika."):
            continue
        rest = module[len("mika."):]
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
        for module in (d.wiring, d.api, d.live, d.console, d.preview, d.cli):
            assert module is None or _within(module, f"mika.app.{HOME}.{d.name}"), f"{d.name} : {module} est hors de son dossier"
        assert d.wiring is None or callable(part(d.wiring, "wire")), d.name
        assert d.api is None or callable(part(d.api, "routes")), d.name
        assert all(callable(count) for count in part(d.api, "COUNTERS", {}).values()), d.name
        assert d.live is None or isinstance(part(d.live, "LIVE"), LivePart), d.name
        assert d.console is None or isinstance(part(d.console, "CONSOLE"), ConsolePart), d.name
        assert d.preview is None or callable(part(d.preview, "preview")), d.name
        assert d.cli is None or callable(part(d.cli, "add")), d.name
        assert d.base is None or _exists(d.base.models.removeprefix("mika.")), d.name


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
