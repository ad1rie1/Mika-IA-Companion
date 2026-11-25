"""Une politique : un port déclare ce qu'on lui demande (ADR 0222).

Les Protocols de ``ports/`` et le port d'entrée (``MindPort``, ``contracts/entry.py``) ne typent rien à l'exécution :
un port se prend par son nom dans une table typée ``Any``, et aucun vérificateur de types ne tourne. Rien ne voyait
donc l'écart entre ce qu'ils disent et ce que font les adaptateurs : la passerelle en service avait perdu
``output_tokens``, et le transport web lisait par ``getattr`` des méthodes que le port d'entrée ne déclarait pas
(audit du 2026-11-05, K2-01 à K2-03). Cette garde confronte chaque Protocol à ses implémentations :

- chaque membre public déclaré (méthode, propriété, attribut annoté) existe chez chaque implémentation : une méthode
  ou une propriété de sa classe ou d'une base de src/ dont elle hérite, un attribut de classe, ou un
  ``self.<nom> = …`` de son ``__init__`` ; une enveloppe qui délègue par ``__getattr__`` a ce qu'elle délègue ;
  le port d'entrée a aussi les méthodes des parts des domaines, qu'il mêle aux siennes (``ASSEMBLED``) ;
- une méthode déclarée garde chez elle chaque paramètre sous son nom (sauf ``**kwargs``), ceux qu'elle ajoute ont un
  défaut ; une propriété n'y devient pas une méthode, ni l'inverse, et ce qu'on attend (``async``) reste à attendre ;
- chaque ``getattr(<objet>, "<nom>", …)`` de src/ (hors adapters/llm/, qui lit ses propres fournisseurs, et sim/)
  vise un membre déclaré du Protocol de l'objet : ``LLMGateway`` pour un objet dont le dernier nom est ``gateway``,
  ``llm`` ou ``_llm`` ; ``MindPort`` pour ``self.port`` dans adapters/web/ et adapters/world/ ; pour tout autre
  ``port``, un Protocol de ``ports/`` ou l'un des quatre crochets que le runtime cherche sur chaque port
  (``ports/__init__.py``).

Ce qui est voulu est dans ``EXCUSED``, avec sa raison ; une excuse qui ne sert plus fait échouer la garde. Le
contrôle lit l'arbre du code (``ast``), sans importer mika. Il est écrit comme une fonction du texte des sources
(``offences``), que les derniers tests essaient sur un petit source factice et sur le vrai code privé d'un membre.
"""

from __future__ import annotations

import ast
import copy
import fnmatch
import functools
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mika"

#: chaque Protocol (fichier sous src/mika, classe) → ses implémentations : les adaptateurs, et les doublures du
#: simulateur (sim/) et de l'aperçu (app/preview), qui en tiennent lieu dans une vraie vie ; pas celles des tests. Un
#: Protocol nouveau de ``ports/`` s'inscrit ici (``test_each_port_is_in_the_table``).
IMPLEMENTATIONS: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    ("contracts/entry.py", "MindPort"): (("app/mindport.py", "KernelPort"),),
    ("ports/agenda.py", "AgendaPort"): (("adapters/agenda/store.py", "AgendaStore"),),
    ("ports/agenda.py", "AgendaDesk"): (("app/domains/agenda/desk.py", "AgendaSettingsDesk"),),
    ("ports/agenda.py", "AgendaProviders"): (("adapters/agenda/__init__.py", "Providers"),),
    ("ports/agenda.py", "CalendarProvider"): (("adapters/agenda/system.py", "SystemProvider"),
                                              ("adapters/agenda/google.py", "GoogleProvider"),
                                              ("adapters/agenda/graph.py", "MicrosoftProvider")),
    ("ports/camera.py", "CameraPort"): (("adapters/camera/__init__.py", "CameraBuffer"),),
    ("ports/contacts.py", "ContactsPort"): (("adapters/contacts/store.py", "ContactsStore"),),
    ("ports/delivery.py", "DeliveryPort"): (
        ("adapters/web/hub.py", "Hub"),
        ("sim/world.py", "Transport"),
        # le port de livraison vu d'un gestionnaire (il retient un refus du transport), ce qu'il reçoit vraiment
        ("runtime/effects.py", "_Watched"),
    ),
    ("ports/delivery.py", "ActivityPort"): (("adapters/web/hub.py", "Hub"),),
    ("ports/feeds.py", "FeedPort"): (("adapters/feeds/__init__.py", "HttpFeeds"), ("sim/outside.py", "FakeFeeds")),
    ("ports/forge.py", "ForgePort"): (("adapters/forge/__init__.py", "ForgeHost"),),
    ("ports/forge.py", "ForgeSettings"): (("app/domains/forge/store.py", "ForgeSettingsStore"),),
    ("ports/imaging.py", "ImageBackend"): (
        ("adapters/imaging/sdcpp.py", "SdCppBackend"),
        ("adapters/imaging/openai_images.py", "OpenAIImagesBackend"),
    ),
    ("ports/imaging.py", "ImagingPort"): (("adapters/imaging/config.py", "LiveImaging"),),
    ("ports/llm.py", "LLMBackend"): (
        ("adapters/llm/claude.py", "ClaudeBackend"),
        ("adapters/llm/claude_code.py", "ClaudeCodeBackend"),
        ("adapters/llm/ollama.py", "OllamaBackend"),
        ("adapters/llm/openai_compat.py", "OpenAICompatBackend"),
        ("sim/llm/scripted.py", "ScriptedLLM"),
        ("sim/llm/persona.py", "PersonaSimLLM"),
        ("sim/sonde.py", "Blocking"),
        ("app/preview/__init__.py", "_Model"),
    ),
    ("ports/llm.py", "LLMGateway"): (
        ("adapters/llm/config.py", "LiveGateway"),
        ("adapters/llm/gateway.py", "Gateway"),
        # la passerelle vue d'un processus (``ctx.llm``), qui délègue le reste
        ("runtime/scheduler.py", "_BoundedLLM"),
    ),
    ("ports/mail.py", "MailPort"): (("adapters/mail/client.py", "ImapSmtpMail"), ("sim/outside.py", "FakeMail")),
    ("ports/maps.py", "MapsPort"): (("adapters/maps/desk.py", "MapsDesk"),),
    ("ports/mcp.py", "ExternalTools"): (("adapters/mcp/hub.py", "McpHub"),),
    ("ports/phone.py", "PhoneGate"): (("app/domains/phone/desk.py", "PhoneDesk"),),
    ("ports/preprocess.py", "Preprocessor"): (("adapters/preprocess/__init__.py", "LocalPreprocessor"),),
    ("ports/shares.py", "ShareStore"): (
        ("adapters/shares/__init__.py", "MemoryShares"),
        ("adapters/shares/__init__.py", "DiskShares"),
    ),
    ("ports/store.py", "EventStore"): (("adapters/store_sql/store.py", "SqlStore"),),
    ("ports/store.py", "Sql"): (("adapters/store_sql/store.py", "SqlConn"),),
    ("ports/teams.py", "TeamsPort"): (("adapters/teams/store.py", "TeamsStore"),),
    ("ports/teams.py", "TeamsGate"): (("app/domains/teams/desk.py", "TeamsDesk"),),
    ("ports/teams.py", "TeamsKeys"): (("app/domains/teams/desk.py", "TeamsDesk"),),
    ("ports/vectors.py", "Embedder"): (
        ("adapters/vectors/embedders.py", "HashEmbedder"),
        ("adapters/vectors/embedders.py", "SentenceEmbedder"),
    ),
    ("ports/vectors.py", "VectorIndex"): (("adapters/vectors/index.py", "SqliteVectorIndex"),),
    ("ports/wakeup.py", "WakeDesk"): (("app/domains/wakeup/desk.py", "WakeupDesk"),),
    ("ports/workshop.py", "Workshop"): (("adapters/workshop/__init__.py", "BwrapWorkshop"),),
    ("ports/workshop.py", "RepoHost"): (
        ("adapters/workshop/github.py", "GitHubRepos"),
        ("app/domains/projects/demo_git.py", "DemoHost"),
    ),
}

#: une implémentation que le cadre assemble des parts des domaines (ADR 0310) : ses bases dépliées (``*MIXED``) sont
#: les classes que les modules de ce motif donnent à leur part (``PortPart(methods=…)``)
ASSEMBLED: dict[tuple[str, str], str] = {("app/mindport.py", "KernelPort"): "app/domains/*/port.py"}

#: les quatre crochets que le runtime cherche sur chaque port, écrits dans ``ports/__init__.py`` (K2-L1)
HOOKS = ("open", "shutdown", "forget", "failing")

#: où un ``getattr`` n'est pas contrôlé : la passerelle lit ses propres fournisseurs (``LLMBackend`` et ses membres
#: facultatifs, dits dans sa docstring), le simulateur ses doublures
UNCHECKED = ("adapters/llm/", "sim/")

#: ce que la garde trouve et qui est voulu, chaque entrée avec sa raison ; une entrée qui ne sert plus fait échouer
#: la garde (``test_each_excuse_still_serves``)
EXCUSED: frozenset[tuple[str, ...]] = frozenset({
    # seule la passerelle en service garde des traces à relire ; la nue (celle du simulateur) n'a ni l'une ni
    # l'autre, ce que dit la docstring de LLMGateway, et chaque appelant les lit par getattr avec un repli (K2-L1)
    ("missing", "adapters/llm/gateway.py", "Gateway", "configured"),
    ("missing", "adapters/llm/gateway.py", "Gateway", "failing"),
    # le simulateur n'oublie pas de courrier : le runtime prend ce crochet par getattr (ports/__init__.py), et le
    # compléter changerait ce que fait une vie simulée, le compte rendu d'un oubli
    ("missing", "sim/outside.py", "FakeMail", "forget"),
    # les flux simulés n'ont pas de relevé à montrer : la console du plugin rss lit la santé par getattr et, sans
    # elle, montre les flux suivis sans état connu ; la compléter changerait ce que montre une vie simulée
    ("missing", "sim/outside.py", "FakeFeeds", "health"),
})


@dataclass(frozen=True)
class Member:
    """Un membre de classe tel que la garde le lit : sa forme, et pour une méthode ses paramètres."""

    kind: str  # "method", "property" ou "attribute"
    #: on l'attend : ``async def``, ou un ``def`` qui rend un ``Awaitable`` (``ForgeSettings.save``)
    awaited: bool = False
    positional: tuple[str, ...] = ()  # ``self`` exclu
    keywords: tuple[str, ...] = ()  # après ``*``
    optional: frozenset[str] = frozenset()  # ceux qui ont un défaut
    varkw: bool = False  # elle prend ``**kwargs``

    @property
    def params(self) -> tuple[str, ...]:
        return self.positional + self.keywords


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {ast.unparse(d).split("(")[0] for d in node.decorator_list}


def _awaited(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if isinstance(node, ast.AsyncFunctionDef):
        return True
    returns = ast.unparse(node.returns).split("[")[0].rsplit(".", 1)[-1] if node.returns is not None else ""
    return returns in {"Awaitable", "Coroutine"}


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Member | None:
    """Une méthode ou une propriété ; ``None`` pour un setter, qui ne définit rien de plus."""
    marks = _decorators(node)
    if any(m.endswith((".setter", ".deleter")) for m in marks):
        return None
    if marks & {"property", "functools.cached_property", "cached_property"}:
        return Member("property")
    a = node.args
    positional = [x.arg for x in a.posonlyargs + a.args]
    if "staticmethod" not in marks:
        positional = positional[1:]
    defaults = set(positional[len(positional) - len(a.defaults):]) if a.defaults else set()
    defaults |= {x.arg for x, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d is not None}
    return Member("method", _awaited(node), tuple(positional), tuple(x.arg for x in a.kwonlyargs),
                  frozenset(defaults), a.kwarg is not None)


def _own_members(cls: ast.ClassDef) -> dict[str, Member]:
    """Ce que le corps de la classe définit, et les ``self.<nom> = …`` de son ``__init__``."""
    out: dict[str, Member] = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            got = _function(node)
            if got is not None:
                out[node.name] = got
            if node.name == "__init__":
                for sub in ast.walk(node):
                    targets = sub.targets if isinstance(sub, ast.Assign) else (
                        [sub.target] if isinstance(sub, ast.AnnAssign) else [])
                    for t in targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                            out.setdefault(t.attr, Member("attribute"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = Member("attribute")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = Member("attribute")
    return out


def _declared(cls: ast.ClassDef) -> dict[str, Member]:
    """Les membres publics d'un Protocol."""
    return {name: m for name, m in _own_members(cls).items() if not name.startswith("_")}


def _is_protocol(cls: ast.ClassDef) -> bool:
    return any(ast.unparse(b).split("[")[0] in {"Protocol", "typing.Protocol"} for b in cls.bases)


def _module_of(dotted: str, sources: Mapping[str, str]) -> str | None:
    """Le fichier (sous src/mika) d'un module ``mika.…``, s'il est parmi les sources."""
    if not dotted.startswith("mika."):
        return None
    base = dotted.removeprefix("mika.").replace(".", "/")
    for rel in (f"{base}.py", f"{base}/__init__.py"):
        if rel in sources:
            return rel
    return None


class _Tree:
    """Les sources lues une fois : leurs classes, et pour chaque module d'où viennent ses noms importés."""

    def __init__(self, sources: Mapping[str, str]) -> None:
        self.sources = sources
        self.trees = {rel: ast.parse(text, filename=rel) for rel, text in sources.items()}
        self.classes: dict[tuple[str, str], ast.ClassDef] = {}
        self.names: dict[str, dict[str, tuple[str, str]]] = {}  # module → nom local → (module, nom)
        for rel, tree in self.trees.items():
            imported: dict[str, tuple[str, str]] = {}
            # les imports sont en tête de module (ruff, PLC0415), parfois sous un ``if TYPE_CHECKING:``
            for node in [*tree.body, *(n for top in tree.body if isinstance(top, ast.If) for n in top.body)]:
                if isinstance(node, ast.ClassDef):
                    self.classes[(rel, node.name)] = node
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        target = _module_of(alias.name, sources)
                        if target is not None and alias.asname:  # ``import mika.x.y as y``
                            imported[alias.asname] = (target, "")
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    for alias in node.names:
                        target = _module_of(f"{node.module}.{alias.name}", sources)
                        if target is not None:  # un module importé par son nom : ``from mika.x import y``
                            imported[alias.asname or alias.name] = (target, "")
                        else:
                            home = _module_of(node.module, sources)
                            if home is not None:
                                imported[alias.asname or alias.name] = (home, alias.name)
            self.names[rel] = imported

    def base(self, rel: str, node: ast.expr) -> tuple[str, str] | None:
        """La classe de src/ que nomme une base, ou ``None`` (une base du dehors)."""
        if isinstance(node, ast.Subscript):
            node = node.value
        if isinstance(node, ast.Name):
            if (rel, node.id) in self.classes:
                return rel, node.id
            got = self.names[rel].get(node.id)
            return got if got is not None and got[1] else None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            got = self.names[rel].get(node.value.id)
            if got is not None and not got[1]:
                return got[0], node.attr
        return None

    def parts(self, pattern: str) -> list[tuple[str, str]]:
        """Les classes que les modules de ``pattern`` donnent à leur part du port d'entrée (``PortPart(methods=…)``)."""
        found: list[tuple[str, str]] = []
        for rel in sorted(r for r in self.trees if fnmatch.fnmatch(r, pattern)):
            for node in ast.walk(self.trees[rel]):
                if isinstance(node, ast.Call) and _tail(node.func) == "PortPart":
                    found += [(rel, k.value.id) for k in node.keywords if k.arg == "methods"
                              and isinstance(k.value, ast.Name) and (rel, k.value.id) in self.classes]
        return found

    def members(self, key: tuple[str, str]) -> tuple[dict[str, Member], bool]:
        """Ce qu'a la classe, hérité de ses bases de src/ compris (pour une classe assemblée, ``ASSEMBLED`` : les
        classes des parts), et si elle délègue le reste (``__getattr__``)."""
        cls = self.classes[key]
        out: dict[str, Member] = {}
        delegates = False
        for b in reversed(cls.bases):
            assembled = isinstance(b, ast.Starred) and key in ASSEMBLED
            for parent in reversed(self.parts(ASSEMBLED[key])) if assembled else (self.base(key[0], b),):
                if parent is not None and parent in self.classes:
                    got, more = self.members(parent)
                    out.update(got)
                    delegates = delegates or more
        own = _own_members(cls)
        out.update(own)
        return out, delegates or "__getattr__" in own


#: (déclaré, implémenté) : une propriété ou un attribut devenu méthode (toujours vraie dans un ``if``), une méthode
#: devenue propriété ; un attribut qui tient l'appelable d'une méthode déclarée ne dit pas sa forme
RESHAPED = frozenset({("property", "method"), ("attribute", "method"), ("method", "property")})


def _method_offences(impl: tuple[str, str], name: str, want: Member, got: Member) -> Iterator[tuple[str, ...]]:
    """Une méthode déclarée face à celle de l'implémentation. Un paramètre déclaré qu'elle nomme autrement, à la même
    place, est un renommage, dit une fois pour toute la classe (``renamed``, déclaré → le sien) : chaque appelant qui
    le passe par son nom tomberait."""
    if want.awaited != got.awaited:
        yield "async", *impl, name
    renamed: set[str] = set()
    if not got.varkw:
        for i, p in enumerate(want.params):
            if p in got.params:
                continue
            if i < len(want.positional) and i < len(got.positional) and got.positional[i] not in want.params:
                renamed.add(got.positional[i])
                yield "renamed", *impl, p, got.positional[i]
            else:
                yield "param", *impl, name, p
    for p in got.params:
        if p not in want.params and p not in got.optional and p not in renamed:
            yield "required", *impl, name, p


def _implementation_offences(tree: _Tree, table: Mapping[tuple[str, str], tuple[tuple[str, str], ...]]
                             ) -> Iterator[tuple[str, ...]]:
    for proto, impls in table.items():
        if proto not in tree.classes:
            yield "unknown", *proto
            continue
        declared = _declared(tree.classes[proto])
        for impl in impls:
            if impl not in tree.classes:
                yield "unknown", *impl
                continue
            has, delegates = tree.members(impl)
            for name, want in declared.items():
                got = has.get(name)
                if got is None:
                    if not delegates:
                        yield "missing", *impl, name
                elif (want.kind, got.kind) in RESHAPED:
                    yield "kind", *impl, name
                elif want.kind == got.kind == "method":
                    yield from _method_offences(impl, name, want, got)


def _tail(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _getattr_offences(tree: _Tree, table: Mapping[tuple[str, str], tuple[tuple[str, str], ...]]
                      ) -> Iterator[tuple[str, ...]]:
    declared = {key: set(_declared(tree.classes[key])) for key in table if key in tree.classes}
    gateway = declared.get(("ports/llm.py", "LLMGateway"), set())
    entry = declared.get(("contracts/entry.py", "MindPort"), set())
    ports = {name for key, names in declared.items() if key[0].startswith("ports/") for name in names} | set(HOOKS)
    for rel, module in tree.trees.items():
        if rel.startswith(UNCHECKED) or "getattr" not in tree.sources[rel]:
            continue
        for node in ast.walk(module):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                continue
            obj, name = node.args[0], node.args[1].value
            tail = _tail(obj)
            if tail in {"gateway", "llm", "_llm"}:
                allowed = gateway
            elif tail == "port" and ast.unparse(obj) == "self.port" and rel.startswith(("adapters/web/",
                                                                                         "adapters/world/")):
                allowed = entry
            elif tail == "port":
                allowed = ports
            else:
                continue
            if name not in allowed:
                yield "getattr", rel, ast.unparse(obj), name


def offences(sources: Mapping[str, str],
             table: Mapping[tuple[str, str], tuple[tuple[str, str], ...]] = IMPLEMENTATIONS) -> set[tuple[str, ...]]:
    """Chaque écart entre les Protocols de ``table`` et leurs implémentations, et chaque ``getattr`` sur une
    passerelle ou un port qui vise un membre non déclaré. ``sources`` : chemin sous src/mika → texte."""
    return _offences_in(_Tree(sources), table)


def _offences_in(tree: _Tree, table: Mapping[tuple[str, str], tuple[tuple[str, str], ...]]) -> set[tuple[str, ...]]:
    return {*_implementation_offences(tree, table), *_getattr_offences(tree, table)}


@functools.cache
def _sources() -> dict[str, str]:
    return {str(p.relative_to(SRC)): p.read_text(encoding="utf-8")
            for p in sorted(SRC.rglob("*.py")) if "__pycache__" not in p.parts}


@functools.cache
def _tree() -> _Tree:
    return _Tree(_sources())


@functools.cache
def _found() -> frozenset[tuple[str, ...]]:
    return frozenset(_offences_in(_tree(), IMPLEMENTATIONS))


def _say(found: set[tuple[str, ...]] | frozenset[tuple[str, ...]]) -> str:
    return "\n".join(" ".join(o) for o in sorted(found))


def test_each_implementation_has_what_its_port_declares():
    unexcused = _found() - EXCUSED
    assert not unexcused, (
        "un port déclare ce qu'on lui demande (ADR 0222) ; à corriger, ou à excuser dans EXCUSED avec sa raison :\n"
        + _say(unexcused))


def test_each_excuse_still_serves():
    stale = EXCUSED - _found()
    assert not stale, "ces excuses ne servent plus, retire-les d'EXCUSED :\n" + _say(stale)


def test_an_excused_member_says_it_is_optional():
    """Un membre qu'une implémentation n'a pas exprès est facultatif, et son Protocol le dit (ADR 0222) : dans la
    docstring du membre (« Facultatif »), ou dans celle du Protocol, qui le nomme."""
    silent = []
    for excuse in EXCUSED:
        if excuse[0] != "missing":
            continue
        impl, member = excuse[1:3], excuse[3]
        for proto, impls in IMPLEMENTATIONS.items():
            cls = _tree().classes[proto]
            node = next((n for n in cls.body if getattr(n, "name", "") == member), None)
            if impl not in impls or node is None:
                continue
            said = ast.get_docstring(node) or "" if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) else ""
            if "facultati" not in said.lower() and f"``{member}``" not in (ast.get_docstring(cls) or ""):
                silent.append(f"{proto[0]}::{proto[1]}.{member}")
    assert not silent, "un membre facultatif le dit dans sa docstring :\n" + "\n".join(sorted(silent))


def test_each_port_is_in_the_table():
    protocols = {key for key, cls in _tree().classes.items()
                 if (key[0].startswith("ports/") or key[0] == "contracts/entry.py") and _is_protocol(cls)}
    assert protocols - IMPLEMENTATIONS.keys() == set(), "un Protocol nouveau s'inscrit dans IMPLEMENTATIONS"
    assert IMPLEMENTATIONS.keys() - protocols == set(), "la table nomme un Protocol qui n'existe plus"


def test_the_hooks_are_written_where_the_runtime_reads_them():
    doc = ast.get_docstring(_tree().trees["ports/__init__.py"]) or ""
    for hook in HOOKS:
        assert re.search(rf"``(?:async )?{hook}\(", doc), f"le crochet {hook!r} n'est plus décrit dans ports/"


FAKE = {
    "ports/llm.py": (
        "from typing import Protocol\n"
        "class LLMGateway(Protocol):\n"
        "    def is_voice(self, role: str) -> bool: ...\n"
        "    async def call(self, req) -> object: ...\n"
    ),
    "ports/box.py": (
        "from collections.abc import Awaitable\n"
        "from typing import Protocol\n"
        "class BoxPort(Protocol):\n"
        "    name: str\n"
        "    @property\n"
        "    def configured(self) -> bool: ...\n"
        "    async def put(self, key: str, data: bytes) -> None: ...\n"
        "    def read(self, key: str) -> bytes: ...\n"
        "    def drop(self, key: str, force: bool = False) -> None: ...\n"
        "    def flush(self) -> Awaitable[None]: ...\n"
    ),
    "contracts/entry.py": (
        "from typing import Protocol\n"
        "class MindPort(Protocol):\n"
        "    def strands(self, handle: str) -> list: ...\n"
    ),
    "adapters/box/base.py": "class Base:\n    def read(self, key, *, fresh=False):\n        return b''\n",
    "adapters/box/__init__.py": (
        "from mika.adapters.box import base as base_m\n"
        "from mika.adapters.box.base import Base\n"
        "class Box(base_m.Base):\n"
        "    def __init__(self):\n"
        "        self.name = 'box'\n"
        "    @property\n"
        "    def configured(self):\n"
        "        return True\n"
        "    async def put(self, key, data):\n"
        "        pass\n"
        "    def drop(self, key, force=False, *, quiet=False):\n"
        "        pass\n"
        "    async def flush(self):\n"
        "        pass\n"
        "class Short(Base):\n"
        "    name: str\n"
        "    async def put(self, key, **kwargs):\n"
        "        pass\n"
        "class Broken:\n"
        "    name = 'broken'\n"
        "    def configured(self):\n"
        "        return True\n"
        "    def put(self, key, blob):\n"
        "        pass\n"
        "    def read(self, key, mode):\n"
        "        return b''\n"
        "    def drop(self, key):\n"
        "        pass\n"
        "    def flush(self):\n"
        "        pass\n"
        "class Envelope:\n"
        "    def __init__(self, inner):\n"
        "        self._inner = inner\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(self._inner, name)\n"
    ),
    "app/mindport.py": "class KernelPort:\n    def strands(self, who):\n        return []\n",
    "runtime/reader.py": (
        "def look(port, gateway, self):\n"
        "    getattr(port, 'read', None)\n"
        "    getattr(port, 'shutdown', None)\n"
        "    getattr(port, 'peek', None)\n"
        "    getattr(gateway, 'is_voice', None)\n"
        "    getattr(gateway, 'configured', None)\n"
        "    getattr(self.deps.gateway, 'status', None)\n"
        "    getattr(self.port, 'strands', None)\n"
    ),
    "adapters/web/hub.py": "def push(self):\n    getattr(self.port, 'strands', None)\n    getattr(self.port, 'read')\n",
    "sim/outside.py": "def fake(port):\n    getattr(port, 'whatever', None)\n",
}
FAKE_TABLE = {
    ("ports/llm.py", "LLMGateway"): (),
    ("ports/box.py", "BoxPort"): (
        ("adapters/box/__init__.py", "Box"),
        ("adapters/box/__init__.py", "Short"),
        ("adapters/box/__init__.py", "Broken"),
        ("adapters/box/__init__.py", "Envelope"),
        ("adapters/box/__init__.py", "Gone"),
    ),
    ("contracts/entry.py", "MindPort"): (("app/mindport.py", "KernelPort"),),
}


def test_the_check_sees_what_a_port_does_not_declare():
    """Le contrôle n'est pas vide : sur un petit source factice, il voit un membre qui manque, une forme changée, un
    ``async`` perdu, un paramètre renommé, oublié ou ajouté sans défaut, une classe disparue, et un ``getattr`` sur un
    nom que le Protocol de l'objet ne déclare pas. Il laisse passer ce qui est hérité (par son nom ou par son module),
    posé dans ``__init__``, délégué par ``__getattr__``, pris par ``**kwargs``, un crochet, et ce que lit le
    simulateur."""
    box = "adapters/box/__init__.py"
    assert offences(FAKE, FAKE_TABLE) == {
        ("missing", box, "Short", "configured"),
        ("missing", box, "Short", "drop"),
        ("missing", box, "Short", "flush"),
        ("kind", box, "Broken", "configured"),
        ("async", box, "Broken", "put"),
        ("renamed", box, "Broken", "data", "blob"),
        ("required", box, "Broken", "read", "mode"),
        ("param", box, "Broken", "drop", "force"),
        ("async", box, "Broken", "flush"),
        ("unknown", box, "Gone"),
        ("renamed", "app/mindport.py", "KernelPort", "handle", "who"),
        ("getattr", "runtime/reader.py", "port", "peek"),
        ("getattr", "runtime/reader.py", "gateway", "configured"),
        ("getattr", "runtime/reader.py", "self.deps.gateway", "status"),
        ("getattr", "runtime/reader.py", "self.port", "strands"),  # le port d'entrée n'est que celui du transport
        ("getattr", "adapters/web/hub.py", "self.port", "read"),
    }


def test_the_entry_port_has_the_methods_of_the_parts_it_mixes():
    """Le port d'entrée mêle à ses méthodes celles des parts des domaines (``class KernelPort(*MIXED)``, ADR 0310) :
    la garde les lit dans leurs modules, et y voit ce qu'elle verrait dans le port — une méthode qui manque, un
    paramètre renommé."""
    entry = {"contracts/entry.py": ("from typing import Protocol\n"
                                    "class MindPort(Protocol):\n"
                                    "    def strands(self, handle: str) -> list: ...\n"
                                    "    def where(self, handle: str) -> str: ...\n"),
             "app/mindport.py": "MIXED = ()\nclass KernelPort(*MIXED):\n    def strands(self, handle):\n        return []\n"}
    table = {("contracts/entry.py", "MindPort"): (("app/mindport.py", "KernelPort"),)}
    part = "class MapsPort:\n    def where(self, who):\n        return ''\nPORT = PortPart(methods=MapsPort)\n"
    assert offences(entry, table) == {("missing", "app/mindport.py", "KernelPort", "where")}
    assert offences({**entry, "app/domains/maps/port.py": part}, table) == {
        ("renamed", "app/mindport.py", "KernelPort", "handle", "who")}
    # et sur le vrai code : ce que le contrat déclare et que les parts écrivent
    has, _ = _tree().members(("app/mindport.py", "KernelPort"))
    assert {"sense", "locate", "unlocate", "notes", "wake_seen", "wake", "_work", "person_panel"} <= set(has)


def test_the_check_would_have_seen_the_lost_output_tokens():
    """Sur le vrai code : la passerelle en service sans ``output_tokens`` (avant K2-L1) est vue."""
    tree = copy.copy(_tree())
    tree.classes = dict(tree.classes)
    key = ("adapters/llm/config.py", "LiveGateway")
    live = copy.copy(tree.classes[key])
    live.body = [n for n in live.body if getattr(n, "name", "") != "output_tokens"]
    tree.classes[key] = live
    assert _offences_in(tree, IMPLEMENTATIONS) - _found() == {("missing", *key, "output_tokens")}
