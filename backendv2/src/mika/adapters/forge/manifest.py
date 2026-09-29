"""La relecture d'une app forgée : son manifeste et son code.

Une politesse en français (c'est Mika qui lit ces messages pour corriger),
pas la défense — la défense est le bac à sable. Chaque message nomme le
champ fautif par son chemin (``views[0].actions[1].fields[2] (« ville »)``).

**Manifeste v2** (l'ancien reste lu : une ``config`` plate ``{clé: défaut}``
devient des réglages typés d'après leur défaut, une fonction ``view(api)``
devient la vue « principale ») :

.. code-block:: yaml

    title: Météo
    config:
      - {key: ville, type: str, label: Ville, group: Lieu, default: Paris}
      - {key: cle_api, type: secret, label: Clé d'API}
      - {key: n, type: int, min: 1, max: 20, default: 5}
    views:
      - key: jour
        label: Aujourd'hui
        params: [{key: ville, label: Ville, kind: search}]
        actions:
          - {key: rafraichir, label: Rafraîchir, fields: [{key: ville, type: text, required: true}]}

La vue ``jour`` s'écrit ``view_jour(api, params)`` ; l'action,
``action_jour_rafraichir(api, data)``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from typing import Any

import yaml

from mika.kernel import schedule

TOOL = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
EVENT = re.compile(r"^[a-z_]+\.[a-z_*]+$")
#: vues, actions, paramètres
KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
#: réglages, champs d'action
FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
HANDLERS = ("tick", "context", "view", "action", "on_event")
FORBIDDEN_IMPORTS = frozenset({"subprocess", "socket", "ctypes", "multiprocessing", "threading", "asyncio", "signal",
                               "pty", "fcntl", "resource", "mmap", "importlib", "sys"})
MAX_SOURCE = 200_000
MAX_MANIFEST = 16_000

CONFIG_TYPES = ("str", "text", "int", "float", "bool", "secret", "select", "lines")
FIELD_TYPES = ("text", "textarea", "int", "number", "bool", "select", "email", "url")
PARAM_KINDS = ("search", "select", "int", "bool")
#: les paramètres que la console garde pour elle (``page`` est donné à chaque vue)
RESERVED_PARAMS = frozenset({"page", "taille", "onglet", "vue", "fait", "avant", "q_global", "flash"})
#: les champs que le formulaire d'une action porte déjà
RESERVED_FIELDS = frozenset({"app", "vue", "action", "csrf", "confirmer"})
RESERVED_CONFIG = frozenset({"csrf"})
MAX_VIEWS, MAX_PARAMS, MAX_ACTIONS, MAX_FIELDS, MAX_CONFIG, MAX_CHOICES = 8, 10, 10, 30, 30, 20
MAX_LENGTH = 10_000

_VIEW_KEYS = frozenset({"key", "label", "description", "order", "params", "actions"})
_PARAM_KEYS = frozenset({"key", "label", "kind", "choices", "default"})
_ACTION_KEYS = frozenset({"key", "label", "description", "confirm", "danger", "fields"})
_FIELD_KEYS = frozenset({"key", "type", "label", "description", "required", "default", "choices", "min", "max",
                         "max_length"})
_CONFIG_KEYS = frozenset({"key", "type", "label", "description", "group", "default", "choices", "min", "max"})


class _Problems(list[str]):
    """Les problèmes, chacun préfixé du chemin du champ fautif."""

    def at(self, path: str, message: str) -> None:
        self.append(f"{path} : {message}")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _where(path: str, key: Any) -> str:
    return f"{path} (« {str(key)[:40]} »)" if key else path


def _unknown(p: _Problems, path: str, d: Mapping[Any, Any], allowed: frozenset[str]) -> bool:
    extra = sorted(str(k) for k in d if k not in allowed)
    if extra:
        p.at(path, f"option(s) inconnue(s) : {', '.join(extra)} (permises : {', '.join(sorted(allowed))})")
    return bool(extra)


def _choices(p: _Problems, path: str, raw: Any, required: bool) -> list[list[str]]:
    """``[a, b]`` ou ``[{value, label}]`` → ``[[valeur, libellé], …]``."""
    if raw is None or raw == []:
        if required:
            p.at(path, "« choices » est requis : une liste de 1 à 20 valeurs (ou {value, label})")
        return []
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CHOICES:
        p.at(path, f"« choices » : une liste de 1 à {MAX_CHOICES} valeurs (ou {{value, label}})")
        return []
    out: list[list[str]] = []
    for i, c in enumerate(raw):
        if isinstance(c, dict) and set(c) <= {"value", "label"} and "value" in c:
            value, label = c["value"], c.get("label", c["value"])
        elif isinstance(c, str | int | float) and not isinstance(c, bool):
            value = label = c
        else:
            p.at(f"{path}.choices[{i}]", "une valeur (texte, nombre) ou {value, label}")
            continue
        value, label = str(value)[:100], str(label)[:100]
        if not value or value in {v for v, _ in out}:
            p.at(f"{path}.choices[{i}]", f"valeur vide ou en double « {value} »")
            continue
        out.append([value, label])
    return out


def _bounds(p: _Problems, path: str, d: Mapping[str, Any], numeric: bool) -> tuple[float | None, float | None]:
    lo, hi = d.get("min"), d.get("max")
    if (lo is not None or hi is not None) and not numeric:
        p.at(path, "« min » et « max » ne vont qu'avec un nombre (int, float ou number)")
        return None, None
    for name, v in (("min", lo), ("max", hi)):
        if v is not None and not _is_num(v):
            p.at(path, f"« {name} » doit être un nombre")
            return None, None
    if lo is not None and hi is not None and lo > hi:
        p.at(path, "« min » est plus grand que « max »")
    return lo, hi


def _typed_default(p: _Problems, path: str, kind: str, value: Any, choices: list[list[str]],
                   lo: float | None, hi: float | None) -> Any:
    """Le défaut s'il a le bon type (et tient dans ses bornes, parmi ses choix), sinon ``None`` et un problème."""
    if value is None:
        return None
    ok = {"int": _is_int(value), "float": _is_num(value), "number": _is_num(value), "bool": isinstance(value, bool),
          "lines": isinstance(value, list) and all(isinstance(x, str | int | float) for x in value),
          }.get(kind, isinstance(value, str | int | float) and not isinstance(value, bool))
    if not ok:
        expected = {"int": "un entier", "float": "un nombre", "number": "un nombre", "bool": "vrai ou faux",
                    "lines": "une liste de textes"}.get(kind, "un texte")
        p.at(path, f"« default » doit être {expected}")
        return None
    if kind == "lines":
        return [str(x)[:500] for x in value][:100]
    if kind in ("int", "float", "number"):
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            p.at(path, "« default » est hors de [min, max]")
        return value
    if kind == "bool":
        return value
    text = str(value)[:MAX_LENGTH]
    if kind == "select" and choices and text not in {v for v, _ in choices}:
        p.at(path, f"« default » « {text[:40]} » n'est pas parmi les choix")
    return text


# ── Réglages ──────────────────────────────────────────────────────────────


def _config_entry(p: _Problems, i: int, c: Any, seen: set[str]) -> dict[str, Any] | None:
    path = f"config[{i}]"
    if not isinstance(c, dict):
        p.at(path, "un objet {key, type, label, default…} est attendu")
        return None
    key = str(c.get("key") or "")
    path = _where(path, key)
    if _unknown(p, path, c, _CONFIG_KEYS):
        return None
    if not FIELD_KEY.match(key):
        p.at(path, "« key » : des minuscules, chiffres et _, commençant par une lettre (40 au plus)")
        return None
    if key in seen or key in RESERVED_CONFIG:
        p.at(path, "clé en double" if key in seen else "clé réservée")
        return None
    seen.add(key)
    kind = str(c.get("type") or "str")
    if kind not in CONFIG_TYPES:
        p.at(path, f"type inconnu « {kind[:20]} » (au choix : {', '.join(CONFIG_TYPES)})")
        return None
    choices = _choices(p, path, c.get("choices"), kind == "select")
    if kind != "select" and choices:
        p.at(path, "« choices » ne va qu'avec le type select")
    lo, hi = _bounds(p, path, c, kind in ("int", "float"))
    if kind == "secret" and c.get("default") is not None:
        p.at(path, "un secret n'a jamais de valeur par défaut (l'opérateur la donne dans la console)")
        default = None
    else:
        default = _typed_default(p, path, kind, c.get("default"), choices, lo, hi)
    return {"key": key, "type": kind, "label": str(c.get("label") or key)[:64],
            "description": str(c.get("description") or "")[:300], "group": str(c.get("group") or "")[:48],
            "default": default, "choices": choices, "min": lo, "max": hi}


def _legacy_config(config: dict[Any, Any]) -> list[dict[str, Any]]:
    """L'ancienne ``config`` plate : un réglage typé par son défaut."""
    out = []
    for key, value in list(config.items())[:MAX_CONFIG]:
        key = str(key)
        if not FIELD_KEY.match(key):
            continue
        kind = ("bool" if isinstance(value, bool) else "int" if _is_int(value) else "float" if _is_num(value)
                else "str")
        out.append({"key": key, "type": kind, "label": key, "description": "", "group": "", "default": value,
                    "choices": [], "min": None, "max": None})
    return out


def _config(p: _Problems, raw: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(réglages typés, défauts simples) ; la forme plate reste comprise."""
    if raw is None or raw == {} or raw == []:
        return [], {}
    if isinstance(raw, dict):
        if not all(isinstance(v, str | int | float | bool) for v in raw.values()):
            p.at("config", "des valeurs simples (texte, nombre, vrai/faux), ou une liste de réglages typés")
            return [], {}
        return _legacy_config(raw), {str(k)[:40]: v for k, v in list(raw.items())[:MAX_CONFIG]}
    if not isinstance(raw, list) or len(raw) > MAX_CONFIG:
        p.at("config", f"une liste d'au plus {MAX_CONFIG} réglages {{key, type, label, default…}}")
        return [], {}
    seen: set[str] = set()
    fields = [x for x in (_config_entry(p, i, c, seen) for i, c in enumerate(raw)) if x is not None]
    simple = {f["key"]: f["default"] for f in fields
              if f["type"] not in ("secret", "lines") and isinstance(f["default"], str | int | float | bool)}
    return fields, simple


# ── Vues, paramètres, actions ─────────────────────────────────────────────


def _param(p: _Problems, path: str, raw: Any, seen: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        p.at(path, "un objet {key, label, kind, choices, default} est attendu")
        return None
    key = str(raw.get("key") or "")
    path = _where(path, key)
    if _unknown(p, path, raw, _PARAM_KEYS):
        return None
    if not KEY.match(key):
        p.at(path, "« key » : des minuscules, chiffres et _, commençant par une lettre (24 au plus)")
        return None
    if key in RESERVED_PARAMS:
        p.at(path, f"« {key} » est réservé à la console (« page » est toujours donné à la vue)")
        return None
    if key in seen:
        p.at(path, "paramètre en double")
        return None
    seen.add(key)
    kind = str(raw.get("kind") or "search")
    if kind not in PARAM_KINDS:
        p.at(path, f"kind inconnu « {kind[:20]} » (au choix : {', '.join(PARAM_KINDS)})")
        return None
    choices = _choices(p, path, raw.get("choices"), kind == "select")
    default = raw.get("default")
    text = ""
    if default is not None:
        if kind == "bool":
            if not isinstance(default, bool):
                p.at(path, "« default » doit être vrai ou faux")
            text = "1" if default is True else ""
        elif kind == "int":
            if not _is_int(default):
                p.at(path, "« default » doit être un entier")
            else:
                text = str(default)
        else:
            text = str(default)[:200]
            if kind == "select" and choices and text not in {v for v, _ in choices}:
                p.at(path, f"« default » « {text[:40]} » n'est pas parmi les choix")
    return {"key": key, "label": str(raw.get("label") or key)[:48], "kind": kind, "choices": choices,
            "default": text}


def _field(p: _Problems, path: str, raw: Any, seen: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        p.at(path, "un objet {key, type, label, required…} est attendu")
        return None
    key = str(raw.get("key") or "")
    path = _where(path, key)
    if _unknown(p, path, raw, _FIELD_KEYS):
        return None
    if not FIELD_KEY.match(key):
        p.at(path, "« key » : des minuscules, chiffres et _, commençant par une lettre (40 au plus)")
        return None
    if key in RESERVED_FIELDS or key in seen:
        p.at(path, "clé en double" if key in seen else
             f"« {key} » est réservé au formulaire (évite {', '.join(sorted(RESERVED_FIELDS))})")
        return None
    seen.add(key)
    kind = str(raw.get("type") or "text")
    if kind not in FIELD_TYPES:
        p.at(path, f"type inconnu « {kind[:20]} » (au choix : {', '.join(FIELD_TYPES)})")
        return None
    choices = _choices(p, path, raw.get("choices"), kind == "select")
    if kind != "select" and choices:
        p.at(path, "« choices » ne va qu'avec le type select")
    lo, hi = _bounds(p, path, raw, kind in ("int", "number"))
    required = raw.get("required", False)
    if not isinstance(required, bool):
        p.at(path, "« required » doit être vrai ou faux")
        required = False
    max_length = raw.get("max_length")
    if max_length is not None and (not _is_int(max_length) or not 1 <= max_length <= MAX_LENGTH
                                   or kind not in ("text", "textarea", "email", "url")):
        p.at(path, f"« max_length » : un entier de 1 à {MAX_LENGTH}, pour un texte seulement")
        max_length = None
    default = _typed_default(p, path, kind, raw.get("default"), choices, lo, hi)
    return {"key": key, "type": kind, "label": str(raw.get("label") or key)[:64],
            "description": str(raw.get("description") or "")[:300], "required": required, "default": default,
            "choices": choices, "min": lo, "max": hi, "max_length": max_length or 0}


def _action(p: _Problems, path: str, raw: Any, view: str, seen: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        p.at(path, "un objet {key, label, fields…} est attendu")
        return None
    key = str(raw.get("key") or "")
    path = _where(path, key)
    if _unknown(p, path, raw, _ACTION_KEYS):
        return None
    if not KEY.match(key):
        p.at(path, "« key » : des minuscules, chiffres et _, commençant par une lettre (24 au plus)")
        return None
    if key in seen:
        p.at(path, "action en double")
        return None
    seen.add(key)
    danger = raw.get("danger", False)
    if not isinstance(danger, bool):
        p.at(path, "« danger » doit être vrai ou faux")
        danger = False
    fields_raw = raw.get("fields") or []
    if not isinstance(fields_raw, list) or len(fields_raw) > MAX_FIELDS:
        p.at(path, f"« fields » : une liste d'au plus {MAX_FIELDS} champs")
        fields_raw = []
    keys: set[str] = set()
    fields = [x for x in (_field(p, f"{path}.fields[{i}]", f, keys) for i, f in enumerate(fields_raw))
              if x is not None]
    return {"key": key, "label": str(raw.get("label") or key)[:48],
            "description": str(raw.get("description") or "")[:300], "confirm": str(raw.get("confirm") or "")[:200],
            "danger": danger, "fields": fields, "function": f"action_{view}_{key}"}


def _views(p: _Problems, raw: Any) -> list[dict[str, Any]]:
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_VIEWS:
        p.at("views", f"une liste d'au plus {MAX_VIEWS} vues {{key, label, params, actions}}")
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, v in enumerate(raw):
        path = f"views[{i}]"
        if not isinstance(v, dict):
            p.at(path, "un objet {key, label, params, actions} est attendu")
            continue
        key = str(v.get("key") or "")
        path = _where(path, key)
        if _unknown(p, path, v, _VIEW_KEYS):
            continue
        if not KEY.match(key):
            p.at(path, "« key » : des minuscules, chiffres et _, commençant par une lettre (24 au plus)")
            continue
        if key in seen:
            p.at(path, "vue en double")
            continue
        seen.add(key)
        order = v.get("order", 100)
        if not _is_int(order):
            p.at(path, "« order » doit être un entier")
            order = 100
        params_raw, actions_raw = v.get("params") or [], v.get("actions") or []
        if not isinstance(params_raw, list) or len(params_raw) > MAX_PARAMS:
            p.at(path, f"« params » : une liste d'au plus {MAX_PARAMS} paramètres")
            params_raw = []
        if not isinstance(actions_raw, list) or len(actions_raw) > MAX_ACTIONS:
            p.at(path, f"« actions » : une liste d'au plus {MAX_ACTIONS} actions")
            actions_raw = []
        pkeys: set[str] = set()
        params = [x for x in (_param(p, f"{path}.params[{j}]", r, pkeys) for j, r in enumerate(params_raw))
                  if x is not None]
        akeys: set[str] = set()
        actions = [x for x in (_action(p, f"{path}.actions[{j}]", r, key, akeys) for j, r in enumerate(actions_raw))
                   if x is not None]
        out.append({"key": key, "label": str(v.get("label") or key)[:48],
                    "description": str(v.get("description") or "")[:300], "order": order, "params": params,
                    "actions": actions, "function": f"view_{key}"})
    functions: dict[str, str] = {}
    for v in out:
        for a in v["actions"]:
            other = functions.setdefault(a["function"], f"{v['key']}.{a['key']}")
            if other != f"{v['key']}.{a['key']}":
                p.at("views", f"les actions {other} et {v['key']}.{a['key']} donneraient la même fonction "
                              f"{a['function']} : renomme l'une d'elles")
    return out


# ── Le manifeste ──────────────────────────────────────────────────────────


def read_manifest(text: str) -> tuple[dict[str, Any], list[str]]:
    """(manifeste normalisé, problèmes en français)."""
    problems = _Problems()
    if len(text.encode()) > MAX_MANIFEST:
        return {}, [f"le manifeste dépasse {MAX_MANIFEST // 1000} Ko"]
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return {}, [f"manifeste illisible : {exc}"[:300]]
    if not isinstance(data, dict):
        return {}, ["le manifeste doit être un dictionnaire (title, description, schedule…)"]
    out: dict[str, Any] = {"title": str(data.get("title") or "")[:80], "description": str(data.get("description") or "")[:500],
                           "context": bool(data.get("context", False))}
    if not out["title"]:
        problems.append("il manque « title »")
    rule = str(data.get("schedule") or "manual").strip()
    try:
        schedule.parse(rule)
    except ValueError as exc:
        problems.append(str(exc))
    out["schedule"] = rule
    domains = data.get("allowed_domains") or []
    if not isinstance(domains, list) or not all(isinstance(d, str) and re.match(r"^[a-z0-9.-]+$", d) for d in domains):
        problems.append("« allowed_domains » : une liste de noms d'hôtes")
        domains = []
    out["allowed_domains"] = [d.lower() for d in domains][:10]
    out["config_fields"], out["config"] = _config(problems, data.get("config"))
    tools = []
    for t in data.get("tools") or []:
        if not isinstance(t, dict) or not TOOL.match(str(t.get("name") or "")):
            problems.append("« tools » : des entrées {name, description}, name en minuscules")
            continue
        tools.append({"name": str(t["name"]), "description": str(t.get("description") or "")[:300]})
    out["tools"] = tools[:8]
    events = data.get("events") or []
    if not isinstance(events, list) or not all(isinstance(e, str) and EVENT.match(e) for e in events):
        problems.append("« events » : une liste de types (« rss.noticed », « body.* »)")
        events = []
    out["events"] = [str(e) for e in events][:10]
    out["views"] = _views(problems, data.get("views"))
    return out, list(problems)


# ── Le code ───────────────────────────────────────────────────────────────


def signatures(code: str) -> tuple[list[str], dict[str, int]]:
    """(problèmes, fonctions de premier niveau → nombre d'arguments positionnels
    acceptés, 99 avec ``*args``)."""
    problems: list[str] = []
    if len(code.encode()) > MAX_SOURCE:
        problems.append(f"le code dépasse {MAX_SOURCE // 1000} Ko")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"erreur de syntaxe ligne {exc.lineno} : {exc.msg}"], {}
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for n in names:
            if n in FORBIDDEN_IMPORTS:
                problems.append(f"« import {n} » n'a pas de sens ici : l'app n'a ni réseau, ni processus, ni "
                                "système à piloter — passe par api.*")
    functions = {n.name: 99 if n.args.vararg else len(n.args.posonlyargs) + len(n.args.args)
                 for n in tree.body if isinstance(n, ast.FunctionDef)}
    if not set(functions) & {*HANDLERS} and not any(f.startswith(("tool_", "view_", "action_")) for f in functions):
        problems.append("aucune fonction attendue : tick(api), context(api), view_<vue>(api, params), "
                        "action_<vue>_<action>(api, data), tool_<nom>(api, args) ou on_event(api, événement)")
    return problems, functions


def lint(code: str) -> tuple[list[str], set[str]]:
    """(problèmes, fonctions trouvées). La défense est le bac à sable ; ceci
    refuse l'inutile et l'illisible, en français, pour qu'elle corrige."""
    problems, functions = signatures(code)
    return problems, set(functions)


def coherence(manifest: Mapping[str, Any], functions: Mapping[str, int]) -> list[str]:
    """Ce que le manifeste déclare et que le code doit fournir, signature comprise."""
    problems: list[str] = []

    def need(name: str, args: str, what: str) -> None:
        if name not in functions:
            problems.append(f"{what} sans fonction {name}({args})")
        elif functions[name] < args.count(",") + 1:
            problems.append(f"{name} doit accepter {args.count(',') + 1} arguments : {name}({args})")

    for t in manifest.get("tools", []):
        need(f"tool_{t['name']}", "api, args", f"l'outil « {t['name']} » est déclaré")
    for v in manifest.get("views", []):
        need(v["function"], "api, params", f"la vue « {v['key']} » est déclarée")
        for a in v["actions"]:
            need(a["function"], "api, data", f"l'action « {a['key']} » de la vue « {v['key']} » est déclarée")
    if manifest.get("context") and "context" not in functions:
        problems.append("« context: true » sans fonction context(api)")
    if manifest.get("events") and "on_event" not in functions:
        problems.append("« events » sans fonction on_event(api, événement)")
    return problems
