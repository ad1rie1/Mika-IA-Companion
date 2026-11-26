"""Une politique : le cadre d'``app`` ne nomme aucun domaine (ADR 0310).

Ce que la couche ``app`` sait d'un domaine (le courrier, Teams, l'agenda…) vit dans son dossier, ``app/domains/<nom>/``,
et sa fiche (``Domain``) dit ce qu'il apporte. Le **cadre** — tout le reste d'``app`` : le serveur, le schéma, la
sauvegarde, l'API par personne, la console, et sous ``domains/`` tout module posé à côté du registre et de la forme
d'une fiche — parcourt ``DOMAINS`` et ne nomme aucun domaine. Cette garde relit les imports de chaque source d'``app``
(``ast`` : jamais un commentaire ; un import relatif se résout par le chemin du fichier ; seules les révisions des
bases, ``migrations/<base>/versions/``, ne se lisent pas) :

- **un fichier du cadre n'importe rien d'un domaine** : ni son plugin ou sa faculté, ni son adaptateur, son contrat
  ou son port (``PACKAGES``), ni son dossier (``mika.app.domains.<nom>`` — seulement ``mika.app.domains``) ;
- **le cadre ne s'excuse pas** : le chantier qui a rangé ``app`` par domaine tenait la liste de ce qui restait à
  sortir, fichier par fichier ; elle est vide et n'existe plus. Seul ``FOREVER`` porte ce que le cadre nomme
  exprès, avec sa raison — une entrée qui ne sert plus (le fichier n'existe plus) fait échouer la garde ;
- **un domaine ne nomme un autre domaine que s'il le déclare** (``Domain.needs``), et un besoin déclaré qui ne sert
  plus se retire ;
- **le registre** (``app/domains/__init__.py``) liste les fiches et rien d'autre : il ne nomme aucun paquet du moteur ;
- **une fiche n'importe rien d'``app``** (``app/domains/<nom>/__init__.py`` : seulement la forme d'une fiche,
  ``mika.app.domains.domain`` ; aux couches du dessous elle ne prend que de quoi se dire — une ``Destination``, un
  ``MenuLink``) : elle nomme les modules de ses parts, que le cadre importe au moment d'assembler. Le
  registre est donc une feuille de l'arbre des imports, que tout module d'``app`` peut lire ; et **chaque part nommée
  existe** et porte son nom convenu (``wire``, ``SETTINGS``, ``routes``, ``LIVE``, ``SHARING``, ``ACCOUNTS``,
  ``OUTSIDE``, ``CONSOLE``, ``PORT``, ``preview``, ``add``) ; les méthodes que le port d'entrée mêle aux siennes
  ne s'y écrivent qu'une fois.

Le contrôle est une fonction du texte des sources (``offences``) : les derniers tests l'essaient sur de petits
sources factices, pour qu'il échoue vraiment quand on nomme un domaine.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest

from mika.app.backup import FOLDERS
from mika.app.composition import arbitration, faculties
from mika.app.console import NAVIGATION, PARAM_FAMILIES, PARAM_FAMILY, PARAM_FAMILY_NAMES, param_families
from mika.app.console_menu import MENU
from mika.app.domains import (
    DOMAINS,
    AccountsPart,
    ConsolePart,
    Domain,
    LivePart,
    OutsidePart,
    PersonPart,
    Place,
    PortPart,
    QueuePart,
    RightsSort,
    ShareWrite,
    SharingPart,
    gathered,
    part,
)
from mika.app.handmade.person import TABS as PERSON_TABS
from mika.app.handmade.person import account_tabs, every_tab
from mika.app.handmade.rights import SUBTABS, placed, share_consoles, sorts, subtabs
from mika.app.handmade.waiting import TABS as QUEUE_TABS
from mika.app.me.accounts import CHANNELS
from mika.app.me.outside import OUTSIDE
from mika.app.me.sharing import KINDS as SHARED_KINDS
from mika.app.mindport import MIXED, KernelPort
from mika.app.settings import SettingsPart
from mika.inspector.pages.approvals import HISTORY_ORDER
from mika.inspector.ui import QueueTab, static_roots
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mika"
APP = SRC / "app"
#: le dossier des domaines, sous ``app/``
HOME = "domains"
#: le module qui porte la forme d'une fiche : le seul qu'une fiche importe
FORM = "mika.app.domains.domain"
#: sous ``domains/``, à côté des dossiers : le registre et la forme d'une fiche — tout autre module y est du cadre
REGISTRY = ("__init__.py", "domain.py")

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

#: les couches dont chaque paquet est à un domaine (``PACKAGES``) ou au cadre (``FRAME_OWNED``) : une liste fermée
#: qu'un paquet neuf ne peut pas oublier sans bruit
CLAIMED_LAYERS = ("plugins", "adapters", "contracts", "ports")
CORE = "le cœur : le contrat d'une faculté qui n'est à aucun domaine (les facultés du cœur ne sont pas des domaines)"
MODELS = "la passerelle des modèles : elle sert tout le moteur"
STORAGE = "le stockage : le magasin, ses bases et leurs moteurs (ADR 0101)"
OFF_JOURNAL = "les octets hors du journal (ADR 0062) : les fichiers envoyés, les pièces reçues, la documentation"
DRAWINGS = "passerelle de fournisseurs, comme celle des modèles ; en faire un domaine reste à décider"

#: chaque paquet de ``CLAIMED_LAYERS`` qui n'est à aucun domaine, et pourquoi : le cadre peut le nommer
FRAME_OWNED: dict[str, str] = {
    # les dessins (ADR 0061, 0063)
    "plugins.imaging": DRAWINGS,
    "adapters.imaging": DRAWINGS,
    "contracts.imaging": DRAWINGS,
    "ports.imaging": DRAWINGS,
    # les adaptateurs
    "adapters.addresses": "la règle des adresses publiques (ADR 0228), que partagent plusieurs adaptateurs",
    "adapters.cage": "la cage bubblewrap commune (ADR 0020, 0039, 0064) : l'atelier, les apps, les serveurs MCP",
    "adapters.changes": "ce qu'une base tenue à côté du journal dit de ses écritures (ADR 0308) : la machinerie du "
                        "direct, commune à ces bases",
    "adapters.database": STORAGE,
    "adapters.listing": "ce que propose un fournisseur, lu par la passerelle des modèles et par celle des images",
    "adapters.llm": MODELS,
    "adapters.preprocess": "le prétraitement de ce qu'on lui envoie, au bord du cœur",
    "adapters.push": "les notifications du téléphone (ADR 0077), que le transport web envoie",
    "adapters.shares": OFF_JOURNAL,
    "adapters.store_sql": STORAGE,
    "adapters.system": "les sources réelles du temps et des identifiants",
    "adapters.vectors": "les plongements et leur index, que lit la mémoire",
    "adapters.web": "le transport web : le chat, les comptes, la session, les portes (ADR 0213)",
    "adapters.world": "le transport du monde (``mika.world/1``, ADR 0050)",
    # les contrats
    **dict.fromkeys(("contracts.affect", "contracts.agency", "contracts.attachments", "contracts.attention",
                     "contracts.body", "contracts.expression", "contracts.goals", "contracts.identity",
                     "contracts.memory", "contracts.needs", "contracts.others", "contracts.place", "contracts.presence",
                     "contracts.self_", "contracts.shares", "contracts.social", "contracts.transcript",
                     "contracts.world"), CORE),
    "contracts.entry": "le port d'entrée du cœur (``MindPort``), que parlent les transports web et monde",
    "contracts.runtime": "le contrat du runtime : perceptions, épisodes, effets",
    # les ports
    "ports.changes": "les sujets du direct (ADR 0308), que le cadre et les domaines partagent",
    "ports.delivery": "la livraison de sa parole vers les transports",
    "ports.drafts": "ce qui vaut pour un brouillon, quel que soit son canal",
    "ports.errors": "ce que veut dire une panne du dehors, pour un opérateur",
    "ports.gate": "les issues des portes à clé que le transport web appelle (ADR 0213)",
    "ports.journal": STORAGE,
    "ports.llm": MODELS,
    "ports.llm_budget": MODELS,
    "ports.paging": "une page de données, que les ports découpent",
    "ports.preprocess": "le prétraitement de ce qu'on lui envoie, au bord du cœur",
    "ports.shares": OFF_JOURNAL,
    "ports.sql": STORAGE,
    "ports.store": STORAGE,
    "ports.vectors": "les vecteurs, que lit la mémoire",
}

#: ce que le cadre nomme exprès, pour toujours, et pourquoi
FOREVER: dict[str, str] = {
    "composition.py": "la liste des facultés et des plugins, les lots d'outils de chaque sorte d'épisode et l'ordre "
                      "de son prompt : des décisions, pas de la plomberie (ADR 0151)",
    "preview/__init__.py": "la vie fictive de l'aperçu de la console : un scénario écrit à la main, où ses mails, ses "
                           "messages Teams, ses voyages et ses projets se mêlent dans l'ordre d'une vraie semaine ; "
                           "un domaine neuf y ajoute sa part par sa fiche (``Domain.preview``), sans y toucher",
}


def _package(where: str) -> list[str]:
    """Le paquet d'un fichier d'``app``, par son chemin sous ``app/`` : ``server.py`` est dans ``mika.app``,
    ``domains/mail/__init__.py`` et ``domains/mail/api.py`` dans ``mika.app.domains.mail``."""
    return ["mika", "app", *where.split("/")[:-1]]


def imported(text: str, where: str) -> Iterator[str]:
    """Les modules qu'un source importe, lus dans l'arbre : ``import a.b`` donne ``a.b`` ; ``from a.b import c`` donne
    ``a.b`` et ``a.b.c`` (``c`` peut être un module). Un import relatif se résout par le chemin du fichier lu sous
    ``app/`` (``where``) : ``from .domains.mail import api``, dans ``server.py``, importe ``mika.app.domains.mail``."""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            package = _package(where)  # ``.`` : son paquet ; ``..`` : celui du dessus…
            base = package[:max(0, len(package) - node.level + 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            if module:
                yield module
                yield from (f"{module}.{alias.name}" for alias in node.names)


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def named(text: str, packages: Mapping[str, tuple[str, ...]], *, where: str, folders: bool = True,
          shared: Mapping[str, str] = SHARED) -> set[str]:
    """Les domaines qu'un source nomme par ses imports (``where`` : son chemin sous ``app/``) : un de leurs paquets
    (``packages``), ou leur dossier sous ``app/domains/`` (``folders``). Un module logé dans le paquet d'un domaine sans
    être à lui (``shared``) ne le nomme pas."""
    out: set[str] = set()
    for module in imported(text, where):
        if not module.startswith("mika."):
            continue
        rest = module[len("mika."):]
        if any(_within(rest, own) for own in shared):
            continue
        for domain, owned in packages.items():
            if any(_within(rest, p) for p in owned) or (folders and _within(rest, f"app.{HOME}.{domain}")):
                out.add(domain)
    return out


def offences(sources: Mapping[str, str], *, packages: Mapping[str, tuple[str, ...]], forever: Mapping[str, str],
             needs: Mapping[str, tuple[str, ...]]) -> list[str]:
    """Ce qui enfreint la politique, en phrases. ``sources`` : le texte de chaque fichier d'``app``, par son chemin
    sous ``app/`` ; ``needs`` : ce que la fiche de chaque domaine déclare lire des autres."""
    out: list[str] = []
    used: dict[str, set[str]] = {}
    for path, text in sorted(sources.items()):
        parts = path.split("/")
        # le cadre : tout ce qui n'est pas sous ``domains/``, et sous ``domains/`` un module à côté du registre et de
        # la forme d'une fiche (``domains/pont.py``) — qui, sinon, prêterait au cadre ce qu'il importe d'un domaine
        if parts[0] != HOME or (len(parts) == 2 and parts[1] not in REGISTRY):
            if path in forever:
                continue
            out += [f"{path} nomme le domaine « {d} » : le cadre lit les fiches (DOMAINS), il ne nomme aucun domaine"
                    for d in sorted(named(text, packages, where=path))]
        elif len(parts) == 2:  # le registre et la forme d'une fiche
            out += [f"{path} nomme un paquet du domaine « {d} » : le registre liste les fiches, rien d'autre"
                    for d in sorted(named(text, packages, where=path, folders=False))]
        else:  # le dossier d'un domaine
            own = parts[1]
            if parts[2:] == ["__init__.py"]:  # sa fiche : elle nomme ses parts, elle n'importe rien
                out += [f"{path} importe {m} : d'``app``, une fiche n'importe que la forme d'une fiche ({FORM}) ; elle "
                        "nomme les modules de ses parts" for m in sorted(set(imported(text, path)))
                        if _within(m, "mika.app") and not _within(m, FORM)]
            if own not in packages:
                out.append(f"{path} : « {own} » n'est pas un domaine que cette garde connaît (PACKAGES)")
                continue
            others = named(text, packages, where=path) - {own}
            used.setdefault(own, set()).update(others)
            out += [f"{path} nomme le domaine « {d} », que la fiche de « {own} » ne déclare pas (Domain.needs)"
                    for d in sorted(others - set(needs.get(own, ())))]
    out += [f"{path} est excusé dans FOREVER mais n'existe plus" for path in sorted(set(forever) - set(sources))]
    out += [f"la fiche de « {own} » déclare le besoin « {d} », que son dossier ne nomme pas : le retirer"
            for own, declared in sorted(needs.items()) for d in sorted(set(declared) - used.get(own, set()))]
    return out


def _revision(parts: tuple[str, ...]) -> bool:
    """Une révision d'une base (``migrations/<base>/versions/…``), écrite par Alembic : son histoire, pas du cadre."""
    return len(parts) > 3 and parts[0] == "migrations" and parts[2] == "versions"


def _sources(root: Path = APP) -> dict[str, str]:
    """Le texte de chaque source d'``app``, par son chemin sous ``app/`` — tout, sauf les révisions des bases. Un
    dossier qui s'appellerait ``versions`` ailleurs se lit comme les autres."""
    found = ((p, p.relative_to(root).parts) for p in sorted(root.rglob("*.py")))
    return {"/".join(parts): p.read_text(encoding="utf-8") for p, parts in found
            if "__pycache__" not in parts and not _revision(parts)}


def _exists(module: str) -> bool:
    path = SRC.joinpath(*module.split("."))
    return path.is_dir() or path.with_suffix(".py").is_file()


def test_the_frame_names_no_domain():
    found = offences(_sources(), packages=PACKAGES, forever=FOREVER, needs={d.name: d.needs for d in DOMAINS})
    assert not found, "\n".join(found)


def test_every_package_of_a_domain_exists():
    """Un paquet renommé qui resterait dans la table ne garderait plus rien."""
    gone = sorted(f"{domain} : {module}" for domain, owned in PACKAGES.items() for module in owned
                  if not _exists(module))
    assert not gone, gone
    assert all(_exists(module) for module in SHARED), sorted(SHARED)
    assert all(any(_within(module, p) for owned in PACKAGES.values() for p in owned) for module in SHARED), \
        "ce qui n'est dans le paquet d'aucun domaine n'a pas à être excepté"


def layer_packages(src: Path = SRC, layers: tuple[str, ...] = CLAIMED_LAYERS) -> set[str]:
    """Chaque paquet de ces couches, par son nom sous ``mika`` : un dossier (``adapters.llm``) ou un module seul
    (``ports.sql``) — ni ``__init__.py`` ni ``__pycache__``."""
    return {f"{layer}.{p.stem}" for layer in layers for p in (src / layer).iterdir()
            if not p.name.startswith(("_", ".")) and (p.is_dir() or p.suffix == ".py")}


def unclaimed(found: set[str], packages: Mapping[str, tuple[str, ...]], frame_owned: Mapping[str, str]) -> list[str]:
    """Ce qui manque à la répartition des paquets entre les domaines et le cadre, en phrases (``found`` : les paquets
    de ``CLAIMED_LAYERS``) : un paquet à personne — le cadre pourrait le nommer sans que la garde le voie, s'il est à
    un domaine —, un paquet dit des deux côtés, une entrée du cadre qui ne sert plus ou sans raison."""
    claimed = {p for owned in packages.values() for p in owned}
    out = [f"{p} n'est à aucun domaine (PACKAGES) ni au cadre (FRAME_OWNED) : l'inscrire dans PACKAGES s'il est à "
           "un domaine (ARCHITECTURE.md, « Écrire un domaine », point 2), sinon dans FRAME_OWNED avec sa raison"
           for p in sorted(found - claimed - set(frame_owned))]
    out += [f"{p} est dans PACKAGES et dans FRAME_OWNED : il est à un domaine ou au cadre, pas aux deux"
            for p in sorted(claimed & set(frame_owned))]
    out += [f"{p} est dans FRAME_OWNED mais n'est pas un paquet de {', '.join(CLAIMED_LAYERS)} : l'en retirer"
            for p in sorted(set(frame_owned) - found)]
    out += [f"{p} est dans FRAME_OWNED sans sa raison" for p, why in sorted(frame_owned.items()) if not why.strip()]
    return out


def test_every_package_below_app_is_of_a_domain_or_of_the_frame():
    """Chaque paquet de ``plugins/``, ``adapters/``, ``contracts/`` et ``ports/`` est à un domaine (``PACKAGES`` :
    ce que le cadre n'a pas le droit de nommer) ou au cadre (``FRAME_OWNED``, avec sa raison). Un paquet neuf
    qu'on oublierait des deux côtés passerait pour du cadre : le cadre pourrait importer le domaine qu'il sert."""
    found = layer_packages()
    assert len(found) > 80  # la lecture trouve bien les paquets
    faults = unclaimed(found, PACKAGES, FRAME_OWNED)
    assert not faults, "\n".join(faults)


def test_the_claim_check_sees_each_fault(tmp_path):
    for written in ("plugins/__init__.py", "plugins/email/__init__.py", "plugins/vault/__init__.py",
                    "plugins/__pycache__/x.pyc", "ports/__init__.py", "ports/sql.py", "ports/vault.py", "ports/mail.py"):
        (tmp_path / written).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / written).write_text("")
    found = layer_packages(tmp_path, ("plugins", "ports"))
    assert found == {"plugins.email", "plugins.vault", "ports.sql", "ports.vault", "ports.mail"}
    packages = {"mail": ("plugins.email", "ports.mail"), "vault": ("plugins.vault", "ports.vault")}
    assert unclaimed(found, packages, {"ports.sql": "le stockage"}) == []
    assert unclaimed(found, {"mail": ("plugins.email", "ports.mail")}, {"ports.sql": "le stockage"}) == [
        f"{p} n'est à aucun domaine (PACKAGES) ni au cadre (FRAME_OWNED) : l'inscrire dans PACKAGES s'il est à un "
        "domaine (ARCHITECTURE.md, « Écrire un domaine », point 2), sinon dans FRAME_OWNED avec sa raison"
        for p in ("plugins.vault", "ports.vault")]
    assert unclaimed(found, packages, {"ports.sql": "le stockage", "ports.mail": "le courrier", "ports.gone": "x",
                                       "plugins.email": " "}) == [
        "plugins.email est dans PACKAGES et dans FRAME_OWNED : il est à un domaine ou au cadre, pas aux deux",
        "ports.mail est dans PACKAGES et dans FRAME_OWNED : il est à un domaine ou au cadre, pas aux deux",
        f"ports.gone est dans FRAME_OWNED mais n'est pas un paquet de {', '.join(CLAIMED_LAYERS)} : l'en retirer",
        "plugins.email est dans FRAME_OWNED sans sa raison"]


def test_the_listed_domains_are_the_folders_and_the_guard_knows_them():
    names = [d.name for d in DOMAINS]
    assert len(names) == len(set(names)), "un domaine inscrit deux fois"
    assert set(names) <= set(PACKAGES), sorted(set(names) - set(PACKAGES))
    folders = sorted(p.name for p in (APP / HOME).iterdir() if p.is_dir() and p.name != "__pycache__")
    assert folders == sorted(names), "chaque dossier de app/domains/ a sa fiche dans DOMAINS, et l'inverse"
    assert all((APP / HOME / n / "__init__.py").is_file() for n in names)
    unknown = sorted(f"{d.name} → {n}" for d in DOMAINS for n in d.needs if n not in PACKAGES or n == d.name)
    assert not unknown, unknown


def test_the_projects_come_last():
    """Le direct demande aux parts des domaines, dans l'ordre des fiches, à qui est un effet du moteur proposé, décidé
    ou parti (``app/me/changes.py::_effect`` : la première qui le reconnaît dit ses touches, les suivantes ne sont pas
    interrogées). La part des projets reconnaît tout effet dont l'événement a pour contexte un projet
    (``project:<n>``, ``app/domains/projects/live.py::effect``), quel qu'en soit le domaine : un domaine inscrit après
    elle ne verrait donc jamais ses effets nés dans un projet — sans bruit. Les projets restent la dernière fiche."""
    assert DOMAINS[-1].name == "projects", [d.name for d in DOMAINS]


def test_every_destination_and_menu_link_of_a_card_is_placed():
    """Une fiche dit sa destination et son lien de menu (``Domain.destination``, ``Domain.menu``) ; la carte de la
    console (``app/console.py::NAVIGATION``) et son menu (``app/console_menu.py::MENU``) disent où ils sont rangés, en
    les prenant par le nom du domaine. Un nom qu'ils ne citent pas, et la fiche aurait une destination sans page, un
    lien que personne ne montre — sans bruit."""
    placed = [destination for group in NAVIGATION for destination in group.items]
    links = [link for group in MENU for link in group.items]
    lost = [f"{d.name} : sa destination « {d.destination.key} »" for d in DOMAINS
            if d.destination is not None and not any(x is d.destination for x in placed)]
    lost += [f"{d.name} : son lien « {d.menu.label} »" for d in DOMAINS
             if d.menu is not None and not any(x is d.menu for x in links)]
    assert any(d.destination is not None for d in DOMAINS) and any(d.menu is not None for d in DOMAINS)
    assert not lost, lost


def test_each_tab_of_the_queue_has_its_place_and_its_link():
    """La file « À valider » range ses onglets — celui du cadre, puis ceux des fiches (``QueuePart.tabs``) — par leur
    ordre (``QueueTab.order``), après « Tout ce qui attend » et avant l'historique (``HISTORY_ORDER``), et son menu en
    tire un lien par onglet, sous son nom et son ``hint`` (``app/console_menu.py``). Un onglet sans mots aurait un lien
    muet ; rangé au-delà de l'historique, il viendrait après lui ; d'un nom déjà pris (un autre onglet, « en_attente »,
    « historique »), il remplacerait l'autre page — sans bruit."""
    queues = [c.queue for d in DOMAINS if d.console is not None if (c := part(d.console, "CONSOLE")).queue is not None]
    assert queues and all(isinstance(q, QueuePart) and all(isinstance(t, QueueTab) for t in q.tabs) for q in queues)
    assert {id(t) for q in queues for t in q.tabs} <= {id(t) for t in QUEUE_TABS}
    loose = [t.slug for t in QUEUE_TABS if not (t.slug and t.title and t.hint and t.order < HISTORY_ORDER)]
    assert not loose, loose
    slugs = [t.slug for t in QUEUE_TABS]
    assert len(slugs) == len(set(slugs)) and not {"en_attente", "historique"} & set(slugs), slugs
    links = next(g for g in MENU if g.label == "À valider").items
    assert [(x.target, x.label, x.hint) for x in links[1:-1]] == [
        (f"approbations/{t.slug}", t.title, t.hint) for t in QUEUE_TABS]


def _label_kinds_read(source: str) -> set[str]:
    """Les sortes de libellés que la carte de la console réunit : le premier argument de chaque ``_named(…)``."""
    return {node.args[0].value for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_named"
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}


def test_each_kind_of_label_a_card_says_is_read_by_the_console():
    """Les libellés d'une fiche (``Domain.labels``) se rangent par sorte, que la carte de la console réunit une à une
    (``app/console.py::_named``) : une sorte qu'elle ne lit pas — mal orthographiée (« faculty »), ou qu'aucune table
    n'y réunit — et ses noms ne seraient jamais montrés, sans bruit."""
    read = _label_kinds_read((APP / "console.py").read_text(encoding="utf-8"))
    assert {"faculties", "events", "owners", "signals"} <= read  # la lecture trouve bien les sortes
    unknown = sorted(f"{d.name} : {kind}" for d in DOMAINS for kind in d.labels if kind not in read)
    assert not unknown, unknown
    assert _label_kinds_read('A = _named("faculties", {})\nB = _named(KIND, {})\n') == {"faculties"}


def test_each_parameter_page_has_its_family():
    """Réglages › Paramètres avancés range les facultés et les plugins par famille (``app/console.py::param_families``) :
    la famille de chacun, dite par le cadre ou par la fiche de son domaine (``labels["parameters"]``), est une de
    ``PARAM_FAMILY_NAMES`` ; une fiche ne range que ce qu'elle nomme (``labels["faculties"]``), et ``PARAM_ORDER`` ne
    place que ce qui a sa famille, une fois. Sinon une page tomberait dans « Autres » ou dans une famille que la page
    ne montre pas, sans bruit — ici, avant. Le contrôle voit chaque faute."""
    assert [name for name, _ in PARAM_FAMILIES] == list(PARAM_FAMILY_NAMES)
    assert sorted(o for _name, owners in PARAM_FAMILIES for o in owners) == sorted(PARAM_FAMILY)
    assert any("parameters" in d.labels for d in DOMAINS)  # la lecture trouve bien ce que les fiches disent
    strays = sorted(f"{d.name} : {owner}" for d in DOMAINS for owner in d.labels.get("parameters", {})
                    if owner not in d.labels.get("faculties", {}))
    assert not strays, strays
    # ceux que l'ordre place, dans son ordre, puis les autres dans l'ordre où leur famille est dite
    assert param_families(("a", "b"), {"x": "b", "y": "a", "z": "b"}, ("z", "y")) == (("a", ("y",)), ("b", ("z", "x")))
    for told, order, why in (({"x": "c"}, (), r"familles inconnues : \['x → c'\]"),
                             ({"x": "a"}, ("x", "w"), r"sans famille : \['w'\]"),
                             ({"x": "a"}, ("x", "x"), r"placés deux fois : \['x'\]")):
        with pytest.raises(ValueError, match=why):
            param_families(("a", "b"), told, order)


def test_a_name_said_twice_is_refused_at_assembly():
    """Ce que les fiches disent par nom se réunit par ``gathered`` (les tables du direct, les compteurs, les fiches et
    les onglets de la console, les libellés, les ports) : un nom redit lève, en disant le nom et les deux qui le
    disent ; sinon, tout est gardé, dans l'ordre."""
    said = [("le cadre", {"a": 1, "b": 2}), ("le domaine « mail »", {"c": 3}), ("le domaine « teams »", {})]
    assert list(gathered("un sujet", said).items()) == [("a", 1), ("b", 2), ("c", 3)]
    with pytest.raises(ValueError, match=r"« b » est dit deux fois \(un sujet\) : par le cadre, puis par le domaine "
                                         r"« teams »"):
        gathered("un sujet", [*said[:2], ("le domaine « teams »", {"b": 9})])
    with pytest.raises(ValueError, match="par le domaine « mail », puis par le domaine « teams »"):
        gathered("un sujet", [*said[:2], ("le domaine « teams »", {"c": 3})])  # même redit à l'identique


def test_every_part_a_card_names_exists_and_carries_its_name():
    """Une fiche nomme les modules de ses parts au lieu de les importer : une faute de frappe ne se verrait qu'à
    l'assemblage. Chaque module nommé s'importe ici, et porte le nom que le cadre y lit."""
    for d in DOMAINS:
        for module in (d.wiring, d.settings, d.api, d.live, d.sharing, d.accounts, d.outside, d.console, d.port,
                       d.preview, d.cli):
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
            # l'article de son mot, qui le précède dans une phrase (« la boîte », « l'agenda »)
            assert shared.article.strip() and shared.article.endswith((" ", "'")), d.name
            assert callable(shared.every) and callable(shared.share), d.name
            assert all(f is None or callable(f) for f in (shared.write, shared.sharer, shared.names)), d.name
            # … son écriture prend, par position, ce que sa forme dit (``ShareWrite``) : le cadre l'appelle ainsi
            assert shared.write is None or takes_like(shared.write, ShareWrite), d.name
        held = part(d.accounts, "ACCOUNTS")
        assert held is None or isinstance(held, AccountsPart), d.name
        if held is not None:  # les comptes de son canal : un canal de CHANNELS, ses mots, ce qu'elle appelle
            assert held.canal in CHANNELS and held.kind and held.family and held.tab and held.label, d.name
            assert held.noun and all(isinstance(b, str) and b for b in held.badges), d.name
            assert all(callable(f) for f in (held.held, held.owned, held.shown, held.configured)), d.name
            # … le geste qui règle un de ses comptes (un geste de son espace : « moi.<…> ») et la sorte de son objet,
            # un compte dit à sa propriétaire, et, s'il n'a pas de brouillon, ce que la règle d'envoi en répond
            assert held.audit.startswith("moi.") and len(held.audit) > 4 and held.subject_kind.strip(), d.name
            assert held.yours.strip() and held.no_drafts == held.no_drafts.strip(), d.name
        elsewhere = part(d.outside, "OUTSIDE")
        assert elsewhere is None or isinstance(elsewhere, OutsidePart), d.name
        if elsewhere is not None:  # ce qui vient d'ailleurs chez lui : une sorte de OUTSIDE, ses mots, ce qu'elle appelle
            assert elsewhere.sort in OUTSIDE and elsewhere.bundle.endswith(".") and len(elsewhere.bundle) > 1, d.name
            assert elsewhere.title and elsewhere.why, d.name
            assert all(callable(f) for f in (elsewhere.seen, elsewhere.tool, elsewhere.allowance, elsewhere.name,
                                             elsewhere.about, elsewhere.row)), d.name
            # … et son sous-onglet dans Réglages › Droits : un nom de SUBTABS, son titre et son aide
            assert elsewhere.tab in SUBTABS and elsewhere.tab_title.strip() and elsewhere.tab_hint.strip(), d.name
        assert d.console is None or isinstance(part(d.console, "CONSOLE"), ConsolePart), d.name
        if d.console is not None:  # où mène, dans la console, la ressource d'un de ses partages, où il se retire
            console = part(d.console, "CONSOLE")
            assert all(f is None or callable(f) for f in (console.shared, console.unshared)), d.name
            assert console.shared is None or d.sharing is not None, f"{d.name} : un partage dans la console sans sorte"
            # la sorte de ressource qu'il apporte à Réglages › Droits : son sous-onglet (un nom de SUBTABS, ses mots),
            # le début de ses clés, sa sorte de droits ; et le tableau qu'il y fait régler — ce qu'il appelle et le lien
            # vers la fiche de sa ressource, en mots : les quatre, ou aucun
            sort = console.rights
            assert sort is None or isinstance(sort, RightsSort), d.name
            if sort is not None:
                assert sort.name in SUBTABS and sort.title.strip() and sort.hint.strip(), d.name
                assert sort.prefix.endswith(":") and len(sort.prefix) > 1 and sort.sort.strip(), d.name
                ruled = (sort.edit, sort.editor, sort.routes)
                assert (all(callable(f) for f in ruled) and sort.named.strip()) or \
                    (all(f is None for f in ruled) and not sort.named), d.name
        sheet = _person_part(d)
        assert sheet is None or isinstance(sheet, PersonPart), d.name
        if sheet is not None:  # sa part de la fiche d'une personne : ce qu'elle nomme est un onglet qu'elle dessine
            assert (sheet.tabs or sheet.owned) and all(callable(draw) for draw in sheet.tabs.values()), d.name
            # … ou, en sous-onglet de Comptes, ce qu'elle a chez lui : (son ancre, son nom, ce qui le lit)
            assert sheet.owned is None or (len(sheet.owned) == 3 and all(isinstance(x, str) and x for x in sheet.owned[:2])
                                           and callable(sheet.owned[2])), d.name
            # … qui reçoit toujours les formulaires de la console (``forms``), et ses feuilles, chacune servie
            assert all(takes_forms(draw) for draw in sheet.tabs.values()), \
                f"{d.name} : {sorted(tab for tab, draw in sheet.tabs.items() if not takes_forms(draw))}"
            assert all(isinstance(s, str) and s.endswith(".css") and served(s) for s in sheet.styles), \
                f"{d.name} : {sheet.styles}"
            # … ou, pour un compte qui s'ajoute à celui du cadre, un onglet du cadre
            unknown = set(sheet.counts) - {*sheet.tabs, *PERSON_TABS, *account_tabs()}
            assert not unknown and all(callable(count) for count in sheet.counts.values()), f"{d.name} : {sorted(unknown)}"
            assert sheet.hidden is None or callable(sheet.hidden), d.name
            assert sheet.routes is None or callable(sheet.routes), d.name
        entry = part(d.port, "PORT")
        assert entry is None or isinstance(entry, PortPart), d.name
        if entry is not None:  # sa part du port d'entrée : ses méthodes, ce qu'il dit du travail en cours
            assert entry.methods is not None or entry.work is not None, d.name
            assert entry.methods is None or isinstance(entry.methods, type), d.name
            assert entry.work is None or callable(entry.work), d.name
        assert d.preview is None or callable(part(d.preview, "preview")), d.name
        assert d.cli is None or callable(part(d.cli, "add")), d.name
        # ses dossiers du dossier de données : chacun une ``Place`` qui se tient
        assert all(isinstance(folder, Place) for folder in d.places.values()), d.name
        assert not [fault for name, folder in d.places.items() for fault in place_faults(name, folder)], d.name
        assert d.base is None or _exists(d.base.models.removeprefix("mika.")), d.name


def sealed_by_hand(text: str) -> list[int]:
    """Les lignes d'un source qui écrivent à la main le nom d'un champ scellé (``"password_sealed"``,
    ``f"{k}_sealed"``) : une chaîne (ou un morceau d'une f-chaîne) qui n'est que ce nom — jamais un commentaire ni
    une docstring."""
    return sorted({node.lineno for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and re.fullmatch(r"\w*_sealed", node.value)})


def test_a_domain_seals_its_secrets_through_its_settings_part():
    """Les réglages d'un domaine scellent les champs secrets d'une fiche, et les rouvrent, par l'aide de leur part
    (``app/settings.py::SettingsPart._sealed``, ``_opened``), qui seule écrit leur nom rangé (``<champ>_sealed``) :
    une copie à la main du motif est une copie qui peut dériver — un champ oublié resterait en clair dans
    ``mind.db``. Ce qui se scelle autrement (la Forge, sous le nom même du champ ; la clé d'un réveil signé) passe par
    ``box``."""
    found = [f"{path}:{line}" for path, text in _sources().items() if path.startswith(f"{HOME}/")
             for line in sealed_by_hand(text)]
    assert not found, found
    assert sealed_by_hand('A = "password_sealed"\nB = f"{k}_sealed"\n"""Le champ password_sealed."""\n') == [1, 2]


def place_faults(name: str, folder: Place) -> list[str]:
    """Ce qui ne se tient pas dans un dossier du dossier de données (``Place``), en phrases : la sauvegarde
    (``app/backup.py``) en tirerait des listes fausses — un dossier écarté sous un dossier qu'elle ne prend pas, un
    fichier gardé sous un dossier qu'elle prend déjà, une raison de le laisser à un dossier qu'elle garde, un dossier
    à elle seule qu'aucune restauration ne recrée."""
    out = []
    if not name or "/" in name or name.startswith(".") or not folder.what:
        out.append(f"{name!r} : un nom juste sous le dossier de données, non caché, et ce qu'il garde en mots")
    if folder.saved and (folder.left or folder.kept):
        out.append(f"{name} : sauvegardé — ni raison de le laisser (left) ni fichier gardé quand même (kept)")
    if not folder.saved and (folder.unsaved or folder.caged):
        out.append(f"{name} : jamais sauvegardé — rien à écarter sous lui (unsaved), aucun lien à garder (caged)")
    if any(not p or p.startswith("/") or ".." in p.split("/") for p in folder.kept):
        out.append(f"{name} : ce qu'il garde se dit par un chemin sous lui — {folder.kept}")
    if any(not p or "/" in p for p in folder.unsaved):
        out.append(f"{name} : ce qu'il écarte se dit par le nom d'un dossier juste sous lui — {folder.unsaved}")
    if folder.private and not folder.made:
        out.append(f"{name} : à elle seule, il faut qu'une restauration le recrée (made)")
    return out


def test_each_folder_of_the_data_holds_together():
    """Les dossiers du dossier de données — ceux du cadre et ceux des fiches (``Domain.places``), réunis par la
    sauvegarde (``app/backup.py::FOLDERS``) — se tiennent chacun, et le contrôle voit chaque faute."""
    assert any(d.places for d in DOMAINS) and set(FOLDERS) >= {name for d in DOMAINS for name in d.places}
    faults = [fault for name, folder in FOLDERS.items() for fault in place_faults(name, folder)]
    assert not faults, faults
    bad = {"a/b": Place("x"), ".cache": Place("x"), "vide": Place(""), "gardé": Place("x", left="réextrait"),
           "gardé2": Place("x", kept=("q.db",)), "laissé": Place("x", saved=False, unsaved=(".vues",)),
           "cage": Place("x", saved=False, caged=True), "loin": Place("x", saved=False, kept=("../q.db",)),
           "profond": Place("x", unsaved=("a/b",)), "seule": Place("x", private=True)}
    assert all(place_faults(name, folder) for name, folder in bad.items()), \
        [name for name, folder in bad.items() if not place_faults(name, folder)]
    assert place_faults("cartes", Place("x", saved=False, left="réextrait", kept=("quotas.db",))) == []


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


def test_a_resource_of_the_rights_page_has_one_sort():
    """Réglages › Droits range une ressource sous la sorte dont le début des clés est le sien (``RightsSort.prefix`` :
    son sous-onglet, ``app/handmade/rights.py::sections``) et y règle son tableau par la première qui convient
    (``table_of``) : deux sortes sur les mêmes clés — ou sur celles des canaux, que le cadre range lui-même —, et une
    ressource serait montrée deux fois, son tableau réglé par une seule, sans bruit. Deux sortes ne rangent pas non plus
    les mêmes droits (``RightsSort.sort``) : les droits exacts d'une personne n'en verraient qu'une."""
    found = [c.rights for d in DOMAINS if d.console is not None if (c := part(d.console, "CONSOLE")).rights is not None]
    prefixes = ["canal:", *(s.prefix for s in found)]  # les canaux : un sous-onglet du cadre, par le début de leurs clés
    twice = [(a, b) for i, a in enumerate(prefixes) for j, b in enumerate(prefixes) if i != j and b.startswith(a)]
    assert found and not twice, twice
    assert len({s.sort for s in found}) == len(found), [s.sort for s in found]


def test_each_subtab_of_the_rights_page_has_its_place_said_once():
    """Réglages › Droits range ses sous-onglets dans l'ordre de ``SUBTABS`` (``app/handmade/rights.py::subtabs``) :
    ceux du cadre, et ce que chaque part apporte — des outils venus d'ailleurs (``OutsidePart.tab``), une sorte réglée
    par son tableau (``RightsSort.name``). Un nom sans sous-onglet, un sous-onglet sans place ou dit deux fois ferait
    échouer la page à sa première lecture — ici, avant. Et chaque sorte de droits que les facultés déclarent y a sa
    part : sans elle, ses ressources n'auraient pas de sous-onglet, et ses droits passeraient pour des outils."""
    subtabs.cache_clear()
    assert list(subtabs()) == list(SUBTABS)
    declared = {spec.key.rsplit(".", 1)[-1] for spec in Registry([RUNTIME, *faculties()], arbitration=arbitration()).rights}
    homed = {*OUTSIDE, *(s.sort for s in sorts())}
    assert declared == homed, sorted(declared ^ homed)
    # le contrôle voit chaque faute : un nom sans sous-onglet, un sous-onglet sans place, un nom placé ou dit deux fois
    said = [("le cadre", {"a": 1}), ("le domaine « x »", {"b": 2})]
    assert list(placed(("b", "a"), said).items()) == [("b", 2), ("a", 1)]
    for order, told, why in ((("a", "b", "c"), said, r"sans sous-onglet : \['c'\], sans place : \[\]"),
                             (("a",), said, r"sans place : \['b'\]"),
                             (("a", "b", "a"), said, r"placés deux fois : \['a'\]"),
                             (("a", "b"), [*said, ("le domaine « y »", {"a": 3})],
                              "« a » est dit deux fois .*: par le cadre, puis par le domaine « y »")):
        with pytest.raises(ValueError, match=why):
            placed(order, told)


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
    pas le même onglet de la fiche d'une personne, et ne règlent pas leurs comptes sous le même geste audité."""
    found = [part(d.accounts, "ACCOUNTS") for d in DOMAINS if d.accounts is not None]
    assert sorted(p.canal for p in found) == sorted(CHANNELS), [p.canal for p in found]
    assert len({p.tab for p in found}) == len(found), [p.tab for p in found]
    # … ni le même geste : Gestes audités ne dirait plus lequel de leurs comptes a été réglé
    assert len({p.audit for p in found}) == len(found), [p.audit for p in found]


def test_a_pane_of_the_accounts_of_a_person_is_said_once():
    """L'onglet Comptes d'une personne a un sous-onglet par canal (``AccountsPart.tab``), puis un par part qui y montre
    ce qu'elle a chez elle (``PersonPart.owned``), puis Partages : leurs ancres sont des ``id`` de la page — une ancre
    dite deux fois ouvrirait le premier des deux sous-onglets, sans bruit."""
    anchors = [*account_tabs(), *(s.owned[0] for d in DOMAINS if (s := _person_part(d)) is not None and s.owned),
               "partages"]
    assert len(anchors) == len(set(anchors)), anchors


def takes_forms(draw: Callable[..., object]) -> bool:
    """Un onglet de la fiche d'une personne reçoit les formulaires de la console par leur nom
    (``draw(ui, key, blocks, query, forms=…)``, ``app/handmade/person/__init__.py::PersonOverview.render_tab``)."""
    params = inspect.signature(draw).parameters.values()
    return any(p.name == "forms" or p.kind is p.VAR_KEYWORD for p in params)


def takes_like(fn: Callable[..., object], form: type) -> bool:
    """Une part appelable prend, par position, les arguments que sa forme dit (un ``Protocol`` : son ``__call__``) :
    sinon elle n'échouerait qu'au premier appel, à la première page qui la lit."""
    wanted = [p for p in inspect.signature(form.__call__).parameters.values() if p.name != "self"]
    try:
        inspect.signature(fn).bind(*range(len(wanted)))
    except TypeError:
        return False
    return True


def test_a_part_takes_what_its_form_says():
    """Le contrôle de ``takes_like`` voit une part qui prend un argument de moins, ou qui en veut un par son nom."""
    assert takes_like(lambda a, b, c, d, e, f=None: None, ShareWrite) and takes_like(lambda *a: None, ShareWrite)
    assert not takes_like(lambda a, b, c, d, e: None, ShareWrite)
    assert not takes_like(lambda a, b, c, d, e, *, check: None, ShareWrite)


def served(sheet: str) -> bool:
    """Une feuille que la console sert : sous ``static/``, chez l'inspecteur ou dans le dossier de console d'un domaine."""
    return any((root / sheet).is_file() for root in static_roots())


def test_every_tab_of_the_sheet_of_a_person_takes_the_forms():
    """La fiche d'une personne passe toujours les formulaires de la console à l'onglet qu'elle dessine, le sien comme
    celui d'un domaine : un onglet qui ne les prendrait pas échouerait à son premier dessin."""
    refused = sorted(tab for tab, draw in every_tab().items() if not takes_forms(draw))
    assert not refused, refused
    assert takes_forms(lambda ui, key, blocks, query, forms=None: None) and takes_forms(lambda *a, **k: None)
    assert not takes_forms(lambda ui, key, blocks, query: None)
    assert served("handmade/person.css") and not served("handmade/absente.css")


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


class _Empty:
    pass


#: ce que Python pose lui-même dans le dictionnaire d'une classe : ce n'en est pas une méthode
MACHINERY = frozenset(vars(_Empty)) | {"__qualname__", "__annotations__", "__annotate__", "__annotate_func__"}


def _defined(cls: type, *, inherited: bool = True) -> set[str]:
    """Ce qu'une classe définit (ses méthodes, ses attributs), et ce qu'elle hérite d'une base autre que ``object``."""
    return {n for c in (cls.__mro__[:-1] if inherited else (cls,)) for n in vars(c) if n not in MACHINERY}


def clashes(frame: type, parts: Mapping[str, type]) -> list[str]:
    """Ce qu'une part du port d'entrée reprend, en phrases : une méthode que le port définit déjà (``frame`` : ce que
    son corps définit, sans ce qu'il mêle), ou qu'une part d'avant définit aussi (``parts`` : domaine → la classe de
    ses méthodes, dans l'ordre des fiches)."""
    out: list[str] = []
    held = dict.fromkeys(_defined(frame, inherited=False), "le port")
    for name, cls in parts.items():
        for n in sorted(_defined(cls)):
            if n in held:
                out.append(f"{n} : {held[n]} et {name}")
            held.setdefault(n, name)
    return out


def test_a_method_of_the_entry_port_is_written_by_one_hand():
    """``KernelPort`` mêle à ses méthodes celles des parts des domaines (``PortPart.methods``) : une méthode que deux
    parts définissent, ou qu'une part reprend au port, ne serait servie que par la première trouvée — sans bruit."""
    parts = {d.name: entry.methods for d in DOMAINS if d.port is not None
             if (entry := part(d.port, "PORT")).methods is not None}
    assert parts and tuple(parts.values()) == MIXED == KernelPort.__mro__[1:-1]
    assert clashes(KernelPort, parts) == []


def test_the_entry_port_check_sees_a_method_said_twice():
    class Frame:
        def perceive(self) -> None: ...

    class Maps:
        def locate(self) -> None: ...

    class Senses:
        def locate(self) -> None: ...

        def perceive(self) -> None: ...

    class Wakeup(Maps):  # ce qu'une part hérite compte aussi
        def wake(self) -> None: ...

    assert clashes(Frame, {"maps": Maps, "wakeup": Wakeup}) == ["locate : maps et wakeup"]
    assert clashes(Frame, {"maps": Maps, "senses": Senses}) == ["locate : maps et senses",
                                                                 "perceive : le port et senses"]
    assert clashes(Frame, {"maps": Maps}) == []


# ── le contrôle, essayé sur des sources factices ──

TOY_PACKAGES = {"mail": ("plugins.email", "adapters.mail"), "agenda": ("plugins.agenda",)}


def _toy(sources: Mapping[str, str], *, forever: Mapping[str, str] | None = None,
         needs: Mapping[str, tuple[str, ...]] | None = None) -> list[str]:
    return offences(sources, packages=TOY_PACKAGES, forever=forever or {}, needs=needs or {})


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
    assert named(sources["server.py"], TOY_PACKAGES, where="server.py",
                 shared={"adapters.mail.relay": "une pièce du cadre"}) == set()


def test_a_comment_or_a_string_names_nothing():
    assert _toy({"server.py": '"""Voir mika.plugins.email."""\n# from mika.adapters.mail import ImapSmtpMail\n'
                              'WHERE = "mika.plugins.agenda"\n'}) == []


def test_what_the_frame_names_on_purpose_passes_and_an_entry_that_no_longer_serves_fails():
    sources = {"composition.py": "from mika.adapters.mail import ImapSmtpMail\n"}
    assert _toy(sources, forever={"composition.py": "la liste de tout le monde"}) == []
    assert _toy(sources, forever={"composition.py": "la liste de tout le monde", "gone.py": "un reste"}) == [
        "gone.py est excusé dans FOREVER mais n'existe plus"]


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


FRAME_NAMES_MAIL = "nomme le domaine « mail » : le cadre lit les fiches (DOMAINS), il ne nomme aucun domaine"


def test_a_relative_import_is_read_where_it_stands():
    """Un import relatif se lit depuis le fichier qui l'écrit : ``.`` est son paquet, ``..`` celui du dessus."""
    assert _toy({"server.py": "from .domains.mail.api import boxes\n"}) == [f"server.py {FRAME_NAMES_MAIL}"]
    assert _toy({"server.py": "from .domains import mail\n"}) == [f"server.py {FRAME_NAMES_MAIL}"]
    assert _toy({"me/api.py": "from ...plugins.email import EMAIL\n"}) == [f"me/api.py {FRAME_NAMES_MAIL}"]
    assert _toy({"server.py": "from .domains import DOMAINS\nfrom . import schema\n"}) == []
    assert _toy({"domains/agenda/api.py": "from ..mail.api import boxes\n"}) == [
        "domains/agenda/api.py nomme le domaine « mail », que la fiche de « agenda » ne déclare pas (Domain.needs)"]
    assert _toy({"domains/mail/__init__.py": "from ..domain import Domain\n"}) == []
    assert _toy({"domains/mail/__init__.py": "from .api import routes\n"}) == [
        "domains/mail/__init__.py importe mika.app.domains.mail.api : d'``app``, une fiche n'importe que la forme d'une "
        "fiche (mika.app.domains.domain) ; elle nomme les modules de ses parts",
        "domains/mail/__init__.py importe mika.app.domains.mail.api.routes : d'``app``, une fiche n'importe que la "
        "forme d'une fiche (mika.app.domains.domain) ; elle nomme les modules de ses parts"]


def test_a_module_beside_the_registry_is_of_the_frame():
    """Sous ``domains/``, seuls le registre et la forme d'une fiche ne sont pas du cadre : un module posé à côté
    (``domains/pont.py``) en est, sinon le cadre importerait par lui ce qu'il n'a pas le droit de nommer."""
    assert _toy({"domains/pont.py": "from mika.app.domains.mail.api import boxes\n",
                 "server.py": "from mika.app.domains.pont import boxes\n"}) == [f"domains/pont.py {FRAME_NAMES_MAIL}"]
    assert _toy({"domains/pont.py": "from mika.plugins.email import EMAIL\n"}) == [f"domains/pont.py {FRAME_NAMES_MAIL}"]
    assert _toy({"domains/__init__.py": "from mika.app.domains.mail import MAIL\n",
                 "domains/domain.py": "import importlib\n"}) == []


def test_only_the_revisions_of_a_base_go_unread(tmp_path):
    """Les révisions des bases (``migrations/<base>/versions/``) ne se lisent pas ; un dossier ``versions`` ailleurs
    dans ``app``, si."""
    for written in ("server.py", "versions/a.py", "domains/mail/versions/b.py", "migrations/mail/env.py",
                    "migrations/mail/versions/0001_c.py", "migrations/views/versions/0002_d.py"):
        (tmp_path / written).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / written).write_text("from mika.plugins.email import EMAIL\n", encoding="utf-8")
    read = _sources(tmp_path)
    assert sorted(read) == ["domains/mail/versions/b.py", "migrations/mail/env.py", "server.py", "versions/a.py"]
    assert f"versions/a.py {FRAME_NAMES_MAIL}" in _toy(read)
