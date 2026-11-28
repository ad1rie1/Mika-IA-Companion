"""Le port de la Forge : les petites apps qu'elle écrit elle-même, exécutées
**hors de son processus**.

Une app est un dossier (``manifest.yaml`` + ``main.py``) ; elle tourne dans
un processus isolé (bubblewrap : sans réseau, sans les bases, sans
l'environnement du serveur, mémoire et temps bornés — un délai dépassé tue le
processus). Elle ne parle au monde que par l'hôte : **sa base** (une base SQL à
elle, qu'elle seule atteint, et son stockage clé/valeur dedans — ADR 0101), sa
configuration, un journal, le réseau (``api.http``, ``api.http_get`` : tout
Internet, jamais la machine ni le réseau local — ADR 0105), et des **signaux**
(ce qu'elle veut porter à l'attention de Mika) que le plugin journalise. Ses
outils déclarent leurs arguments dans le vocabulaire des champs d'action
(``ArgSpec``) : un schéma pour le modèle, une vérification par l'hôte — ce
langage des arguments est dans ``ports/forge_args.py``.

Ce qu'une app **déclare** pour la console (ses vues, leurs paramètres et leurs
actions, ses réglages typés) est décrit ici en données : l'hôte le lit du
manifeste, le plugin le garde (en JSON canonique, ``AppInfo.ui``) dans sa
tranche pour rendre les formulaires sans relire le disque.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from mika.kernel.forms import FormField
from mika.ports.forge_args import ArgSpec, arg_specs, number_or_none


class ForgeRefused(ValueError):
    """Une écriture refusée (manifeste invalide, code qui ne passe pas la relecture)."""


@dataclass(frozen=True, slots=True)
class AppTool:
    """Un outil d'app : ``tool_<nom>(api, args)``, ses arguments déclarés (vérifiés par l'hôte avant l'appel) et
    son délai (0 : le défaut)."""

    name: str
    description: str
    args: tuple[ArgSpec, ...] = ()
    timeout: float = 0.0
    #: il lit, rien ne change ailleurs (``lit: true``) : la colonne « lecture » des lignes d'accès de son projet
    #: s'applique ; sinon « action » (ADR 0133)
    reads: bool = False


#: la file de signaux d'une app qui n'en dit rien (ADR 0105) : 20 signaux au plus, lus un par un, 12 appels par jour
SIGNAL_QUEUE, SIGNAL_PER_CALL, SIGNAL_QUOTA = 20, 1, 12


@dataclass(frozen=True, slots=True)
class SignalRules:
    """Ce qu'une app déclare de ses signaux (``signals`` de son manifeste) : la taille de sa file (au-delà, le plus
    ancien part), combien un appel en lit, combien d'appels par jour au plus, et ce qu'elle doit en faire."""

    queue: int = SIGNAL_QUEUE
    per_call: int = SIGNAL_PER_CALL
    quota: int = SIGNAL_QUOTA
    instructions: str = ""


@dataclass(frozen=True, slots=True)
class AppService:
    """Un de ses services : une tâche planifiée de l'app, ``service_<nom>(api)`` à son rythme (ADR 0104), et son
    délai (0 : le défaut, ADR 0105)."""

    name: str
    schedule: str
    description: str = ""
    timeout: float = 0.0


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
    #: ses champs dans le vocabulaire commun (``check_args`` les vérifie)
    specs: tuple[ArgSpec, ...] = ()


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
    #: ses services (plusieurs tâches planifiées), en plus du rythme principal (``schedule`` + ``tick``)
    services: tuple[AppService, ...] = ()
    #: le délai de son battement et de ses événements (0 : le défaut, ADR 0105)
    timeout: float = 0.0
    #: la file de ses signaux et ce qu'elle doit en faire (ADR 0105)
    signals: SignalRules = SignalRules()
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
    #: l'empreinte de cette version (son manifeste et son code)
    fingerprint: str = ""
    #: les domaines qu'elle dit appeler (``allowed_domains`` : une indication, son réseau est libre — ADR 0105)
    domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StagedVersion:
    """Une version relue mais pas installée : elle attend l'accord d'un opérateur."""

    manifest: str
    code: str
    domains: tuple[str, ...] = ()


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
    #: pas appelée : un autre appel tenait l'app — ce n'est pas un échec de l'app, il se refait
    busy: bool = False
    #: ses requêtes sur le réseau pendant l'appel, et celles qui ont échoué (« GET adresse → 429 ») : un appel qui
    #: rattrape tout « réussit » même quand rien n'a répondu (ADR 0161)
    requests: int = 0
    failed: tuple[str, ...] = ()


class ForgePort(Protocol):
    def apps(self) -> list[AppInfo]: ...

    def keep(self, request: str, result: CallResult) -> None:
        """Garder en mémoire, le temps qu'il soit journalisé comme un contenu, ce qu'a rendu un appel fait après
        accord (ADR 0133 : le résultat d'un effet n'est pas effaçable)."""
        ...

    def take(self, request: str) -> CallResult | None: ...

    def info(self, app: str) -> AppInfo | None: ...

    def source(self, app: str) -> tuple[str, str] | None:
        """(manifeste, code), ou ``None``."""
        ...

    async def write(self, app: str, manifest: str, code: str) -> tuple[int, list[str]]:
        """Écrit (en archivant la version précédente) ; rend (version, remarques).
        Lève ``ForgeRefused`` sans rien changer si c'est refusé."""
        ...

    async def rollback(self, app: str) -> int: ...

    async def stage(self, app: str, manifest: str, code: str) -> str:
        """Relit une version **sans l'installer** (elle attend un accord) ; rend son empreinte. Lève
        ``ForgeRefused`` comme ``write``."""
        ...

    def discard(self, app: str, fingerprint: str) -> None:
        """Oublier une version mise de côté (refusée par un opérateur)."""

    def on_change(self, fn: Callable[[], Any]) -> None:
        """Être prévenu quand l'offre change (une app écrite ou effacée : ses outils aussi)."""

    def staged(self, app: str, fingerprint: str) -> StagedVersion | None:
        """Une version mise de côté (si son contenu a toujours cette empreinte), ou ``None``."""
        ...

    async def install(self, app: str, fingerprint: str) -> int:
        """Installe la version mise de côté (en archivant l'actuelle) ; rend son numéro. ``ForgeRefused`` si elle
        n'existe plus."""
        ...

    async def erase(self, app: str) -> str: ...

    async def reset_storage(self, app: str) -> int:
        """Vide sa base (tables, vues, stockage clé/valeur) ; rend combien de lignes il y avait."""
        ...

    async def db_schema(self, app: str) -> dict[str, Any]:
        """Sa base : ``engine`` (``mariadb`` | ``sqlite``), ``size`` et ``max`` (octets), ``tables`` (``name``,
        ``rows``, ``columns`` : ``name``, ``type``, ``nullable``, ``key``) et ``views``. ``ForgeRefused`` : l'app
        n'existe pas, ou sa base ne répond pas."""
        ...

    async def db_query(self, app: str, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Une lecture de sa base, exécutée sous son utilisateur (une instruction, paramètres nommés) ; ses lignes.
        ``ForgeRefused`` : refusée (forme, résultat trop gros, erreur du moteur — le message le dit)."""
        ...

    async def db_execute(self, app: str, sql: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Une écriture dans sa base : ``{"rows": …, "id": …}``. ``ForgeRefused`` comme ``db_query`` (et base
        pleine)."""
        ...

    async def reload(self, app: str) -> None:
        """Arrête son processus chaud : l'appel suivant repart du disque."""
        ...

    async def call(self, app: str, method: str, args: dict[str, Any] | None = None, *,
                   timeout_s: float = 5.0, max_result: int = 64_000, cache_s: float = 0.0,
                   secrets: bool = True) -> CallResult:
        """Appelle une fonction **déclarée** (ou fixe) de l'app. ``cache_s`` : une vue
        déjà rendue avec les mêmes paramètres et réglages depuis moins que ça est resservie.
        ``secrets`` : l'app lit-elle ses réglages secrets (faux : ``api.config`` les rend vides) — l'appelant
        le décide d'après la version qu'un opérateur a validée."""
        ...

    def logs(self, app: str, n: int = 20) -> list[str]: ...

    def note(self, app: str, line: str) -> None:
        """Une vue qui ne s'est pas rendue dans la console (ADR 0161) : une ligne de son journal, gardée aussi dans
        ses problèmes récents (``problems``) jusqu'à sa prochaine version."""
        ...

    def problems(self, app: str) -> list[str]:
        """Ses problèmes récents vus hors de ses appels (une vue invalide dans la console), du plus ancien au plus
        récent : ce qu'une exécution de son projet doit savoir sans relire son journal."""
        ...


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
                                  "bool": "bool", "select": "select", "email": "text", "url": "text", "lines": "lines"}


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


def config_form(raw: Sequence[Mapping[str, Any]]) -> tuple[FormField, ...]:
    return tuple(form_field(str(c["key"]), CONFIG_KINDS.get(str(c.get("type")), "text"),
                            str(c.get("label") or c["key"]), help=str(c.get("description") or ""),
                            group=str(c.get("group") or ""), default=c.get("default"), lo=number_or_none(c.get("min")),
                            hi=number_or_none(c.get("max")), choices=_pairs(c.get("choices")), order=i)
                 for i, c in enumerate(raw))


def action_form(raw: Sequence[Mapping[str, Any]]) -> tuple[tuple[FormField, ...], tuple[FieldRule, ...]]:
    fields, rules = [], []
    for i, f in enumerate(raw):
        kind = str(f.get("type") or "text")
        required = bool(f.get("required"))
        fields.append(form_field(str(f["key"]), FIELD_KINDS.get(kind, "text"), str(f.get("label") or f["key"]),
                                 help=str(f.get("description") or ""), required=required, default=f.get("default"),
                                 lo=number_or_none(f.get("min")), hi=number_or_none(f.get("max")),
                                 choices=_pairs(f.get("choices")), order=i))
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
                                     bool(a.get("danger")), fields, rules, arg_specs(a.get("fields") or ())))
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
