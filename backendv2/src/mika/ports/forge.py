"""Le port de la Forge : les petites apps qu'elle écrit elle-même, exécutées
**hors de son processus**.

Une app est un dossier (``manifest.yaml`` + ``main.py``) ; elle tourne dans
un processus isolé (bubblewrap : sans réseau, sans les bases, sans
l'environnement du serveur, mémoire et temps bornés — un délai dépassé tue le
processus). Elle ne parle au monde que par l'hôte : un stockage clé/valeur à
elle, sa configuration, un journal, ``http_get`` vers les seuls domaines
qu'elle déclare, et des **signaux** (ce qu'elle veut porter à l'attention de
Mika) que le plugin journalise.

Ce qu'une app **déclare** pour la console (ses vues, leurs paramètres et leurs
actions, ses réglages typés) est décrit ici en données : l'hôte le lit du
manifeste, le plugin le garde (en JSON canonique, ``AppInfo.ui``) dans sa
tranche pour rendre les formulaires sans relire le disque.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from mika.kernel.forms import FormField


class ForgeRefused(ValueError):
    """Une écriture refusée (manifeste invalide, code qui ne passe pas la relecture)."""


@dataclass(frozen=True, slots=True)
class AppTool:
    name: str
    description: str


# ── Ce qu'une app déclare pour la console ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class AppParam:
    """Un paramètre d'une vue : ``search`` | ``select`` | ``int`` | ``bool``."""

    key: str
    label: str
    kind: str = "search"
    choices: tuple[tuple[str, str], ...] = ()
    default: str = ""


@dataclass(frozen=True, slots=True)
class FieldRule:
    """Ce qu'un champ d'action exige au-delà de son contrôle : présence,
    longueur, forme (``email``, ``url``)."""

    key: str
    type: str
    required: bool = False
    max_length: int = 0


@dataclass(frozen=True, slots=True)
class AppAction:
    """Une action d'une vue : ``action_<vue>_<clé>(api, data)`` rend ``{ok, message}``."""

    key: str
    label: str
    function: str
    description: str = ""
    confirm: str = ""
    danger: bool = False
    fields: tuple[FormField, ...] = ()
    rules: tuple[FieldRule, ...] = ()


@dataclass(frozen=True, slots=True)
class AppViewSpec:
    """Une vue : ``view_<clé>(api, params)`` rend une enveloppe ``{"version": 2, "blocks": [...]}``
    (l'ancienne ``view(api)`` devient la vue « principale »)."""

    key: str
    label: str
    function: str
    description: str = ""
    order: int = 100
    params: tuple[AppParam, ...] = ()
    actions: tuple[AppAction, ...] = ()

    def action(self, key: str) -> AppAction | None:
        return next((a for a in self.actions if a.key == key), None)


@dataclass(frozen=True, slots=True)
class AppUI:
    """La surface déclarée d'une app, relue de son JSON canonique."""

    views: tuple[AppViewSpec, ...] = ()
    config_fields: tuple[FormField, ...] = ()
    tools: tuple[str, ...] = ()
    #: les fonctions que l'hôte accepte d'appeler (fixes présentes, et déclarées)
    functions: tuple[str, ...] = ()

    def view(self, key: str) -> AppViewSpec | None:
        return next((v for v in self.views if v.key == key), None)


@dataclass(frozen=True, slots=True)
class AppInfo:
    name: str
    title: str
    description: str = ""
    version: int = 0
    schedule: str = ""
    context: bool = False
    tools: tuple[AppTool, ...] = ()
    handlers: tuple[str, ...] = ()
    #: un manifeste illisible (l'app existe mais ne peut pas tourner)
    error: str = ""
    #: les événements qu'elle veut recevoir (``on_event``)
    events: tuple[str, ...] = ()
    #: les réglages simples que déclare son manifeste, avec leur valeur par défaut
    #: (compatibilité : les secrets et les listes n'y sont pas)
    config: tuple[tuple[str, str | int | float | bool], ...] = ()
    #: ses vues (et leurs actions), déclarées
    views: tuple[AppViewSpec, ...] = ()
    #: ses réglages typés (un secret n'a jamais de valeur par défaut)
    config_fields: tuple[FormField, ...] = ()
    #: le JSON canonique de sa surface déclarée (``ui_load`` le relit)
    ui: str = ""
    #: les fonctions que l'hôte accepte d'appeler
    callable: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CallResult:
    ok: bool
    value: Any = None
    error: str = ""
    killed: bool = False  # tuée à son délai, ou morte (mémoire, CPU)
    duration_ms: int = 0
    logs: tuple[str, ...] = ()
    #: ce que l'app a voulu signaler : (résumé, pertinence, émotion)
    signals: tuple[tuple[str, float, str], ...] = ()
    #: ce qu'elle a émis : (type, données JSON)
    emits: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class ForgePort(Protocol):
    def apps(self) -> list[AppInfo]: ...

    def info(self, app: str) -> AppInfo | None: ...

    def source(self, app: str) -> tuple[str, str] | None:
        """(manifeste, code), ou ``None``."""
        ...

    async def write(self, app: str, manifest: str, code: str) -> tuple[int, list[str]]:
        """Écrit (en archivant la version précédente) ; rend (version, remarques).
        Lève ``ForgeRefused`` sans rien changer si c'est refusé."""
        ...

    async def rollback(self, app: str) -> int: ...

    async def erase(self, app: str) -> str: ...

    async def reset_storage(self, app: str) -> int: ...

    async def reload(self, app: str) -> None:
        """Arrête son processus chaud : l'appel suivant repart du disque."""
        ...

    async def call(self, app: str, method: str, args: dict[str, Any] | None = None, *,
                   timeout_s: float = 5.0, max_result: int = 64_000, cache_s: float = 0.0) -> CallResult:
        """Appelle une fonction **déclarée** (ou fixe) de l'app. ``cache_s`` : une vue
        déjà rendue avec les mêmes paramètres et réglages depuis moins que ça est resservie."""
        ...

    def logs(self, app: str, n: int = 20) -> list[str]: ...


class ForgeSettings(Protocol):
    """Les réglages qu'un opérateur donne à une app (ils surchargent les défauts
    de son manifeste). Les secrets sont scellés au repos par l'implémentation ;
    ``values`` les rend en clair (l'app les lit par ``api.config``) — la console
    n'en montre jamais que « défini » ou « non défini »."""

    def values(self, app: str) -> dict[str, Any]: ...

    def save(self, app: str, values: Mapping[str, Any]) -> Awaitable[None]: ...


# ── De la surface normalisée (JSON) aux champs ────────────────────────────

#: types de réglage → sorte de champ de la console
CONFIG_KINDS: Mapping[str, str] = {"str": "text", "text": "textarea", "int": "int", "float": "float",
                                   "bool": "bool", "secret": "secret", "select": "select", "lines": "lines"}
#: types de champ d'action → sorte de champ de la console
FIELD_KINDS: Mapping[str, str] = {"text": "text", "textarea": "textarea", "int": "int", "number": "float",
                                  "bool": "bool", "select": "select", "email": "text", "url": "text"}


def form_field(key: str, kind: str, label: str, *, help: str = "", group: str = "", required: bool = False,
               default: Any = None, lo: float | None = None, hi: float | None = None,
               choices: tuple[tuple[str, str], ...] = (), order: int = 100) -> FormField:
    """Un champ de la console, construit directement (sans modèle pydantic). Un nombre
    ou un choix facultatif laissé vide vaut ``None`` (pas une erreur) ; un texte vide, ``""``."""
    return FormField(path=key, label=label, help=help, group=group, kind=kind, advanced=False,
                     secret=kind == "secret", readonly=False, required=required and kind != "bool",
                     default=default, lo=lo, hi=hi, step=None, unit="", choices=choices, loader="", subject="",
                     only=(), order=order, nullable=not required and kind in ("int", "float", "select"))


def _pairs(raw: Any) -> tuple[tuple[str, str], ...]:
    return tuple((str(v), str(label)) for v, label in (raw or ()))


def _num(raw: Any) -> float | None:
    return float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None


def config_form(raw: Sequence[Mapping[str, Any]]) -> tuple[FormField, ...]:
    return tuple(form_field(str(c["key"]), CONFIG_KINDS.get(str(c.get("type")), "text"),
                            str(c.get("label") or c["key"]), help=str(c.get("description") or ""),
                            group=str(c.get("group") or ""), default=c.get("default"), lo=_num(c.get("min")),
                            hi=_num(c.get("max")), choices=_pairs(c.get("choices")), order=i)
                 for i, c in enumerate(raw))


def action_form(raw: Sequence[Mapping[str, Any]]) -> tuple[tuple[FormField, ...], tuple[FieldRule, ...]]:
    fields, rules = [], []
    for i, f in enumerate(raw):
        kind = str(f.get("type") or "text")
        required = bool(f.get("required"))
        fields.append(form_field(str(f["key"]), FIELD_KINDS.get(kind, "text"), str(f.get("label") or f["key"]),
                                 help=str(f.get("description") or ""), required=required, default=f.get("default"),
                                 lo=_num(f.get("min")), hi=_num(f.get("max")), choices=_pairs(f.get("choices")),
                                 order=i))
        rules.append(FieldRule(str(f["key"]), kind, required, int(f.get("max_length") or 0)))
    return tuple(fields), tuple(rules)


def view_specs(raw: Sequence[Mapping[str, Any]]) -> tuple[AppViewSpec, ...]:
    out = []
    for v in raw:
        actions = []
        for a in v.get("actions") or ():
            fields, rules = action_form(a.get("fields") or ())
            actions.append(AppAction(str(a["key"]), str(a.get("label") or a["key"]), str(a["function"]),
                                     str(a.get("description") or ""), str(a.get("confirm") or ""),
                                     bool(a.get("danger")), fields, rules))
        params = tuple(AppParam(str(p["key"]), str(p.get("label") or p["key"]), str(p.get("kind") or "search"),
                                _pairs(p.get("choices")), str(p.get("default") or ""))
                       for p in v.get("params") or ())
        out.append(AppViewSpec(str(v["key"]), str(v.get("label") or v["key"]), str(v["function"]),
                               str(v.get("description") or ""), int(v.get("order") or 100), params, tuple(actions)))
    return tuple(sorted(out, key=lambda v: (v.order, v.key)))


def ui_dump(views: Sequence[Mapping[str, Any]], config: Sequence[Mapping[str, Any]], tools: Sequence[str] = (),
            functions: Sequence[str] = ()) -> str:
    """Le JSON canonique d'une surface normalisée (ce que l'hôte a validé)."""
    return json.dumps({"views": list(views), "config": list(config), "tools": list(tools),
                       "functions": sorted(functions)}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@functools.lru_cache(maxsize=128)
def ui_load(text: str) -> AppUI:
    """La surface d'une app relue de son JSON (jamais d'exception : illisible → vide)."""
    if not text:
        return AppUI()
    try:
        data = json.loads(text)
        return AppUI(view_specs(data.get("views") or ()), config_form(data.get("config") or ()),
                     tuple(str(t) for t in data.get("tools") or ()),
                     tuple(str(f) for f in data.get("functions") or ()))
    except (ValueError, TypeError, KeyError, AttributeError):
        return AppUI()
