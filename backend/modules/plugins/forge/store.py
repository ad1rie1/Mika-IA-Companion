"""Couche disque de la Forge : l'espace confiné des modules forgés.

Arborescence (``settings.FORGE_DIR``, par défaut ``data/forge_modules/``,
gitignoré) :

    data/forge_modules/
      <slug>/
        manifest.yaml        ← déclaratif, écrit par l'IA (via les outils)
        module.py            ← code sandboxé
        state.json           ← état runtime géré par l'hôte (enabled, raison)
        _versions/<ts>/      ← snapshots automatiques avant chaque écriture
      _trash/<slug>-<ts>/    ← modules effacés (récupérables à la main)

Toutes les fonctions sont synchrones (I/O disque locale) — les appelants
async passent par ``sync_to_async``. Aucune fonction n'accepte de chemin :
tout est dérivé du slug validé, donc aucune traversée possible.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
RESERVED_NAMES = frozenset({
    "forge", "modules", "admin", "system", "trash", "versions",
    "email", "rss", "wake", "camera", "telegram", "files", "project_tools",
})
VIEW_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
CONFIG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
EVENT_PATTERN_RE = re.compile(r"^[\w.\-]+(\.\*)?$")

MAX_MANIFEST_BYTES = 16 * 1024
MAX_VERSIONS_KEPT = 10
# La corbeille est un filet de sécurité, pas une archive : sans plafond, une
# boucle write→erase la ferait grossir indéfiniment sur le disque.
MAX_TRASH_KEPT = 20

_CONFIG_TYPES = {"str", "text", "int", "float", "bool", "secret",
                 "select", "list", "record_list"}
_SCHEDULE_RE = re.compile(
    r"^$|^manual$|^interval:\d+\s*[smhd]$|^idle:\d+\s*[smhd]$|^cron:.+$",
    re.IGNORECASE,
)


class StoreError(Exception):
    """Erreur d'accès au store (nom invalide, module absent...)."""


@dataclass
class ManifestView:
    key: str
    label: str
    icon: str = "▦"
    order: int = 100


@dataclass
class ForgeManifest:
    """Vue structurée et validée du manifest.yaml d'un module forgé."""

    name: str
    title: str
    description: str = ""
    schedule: str = ""            # syntaxe projects/schedule.py (sans event:)
    events: list[str] = field(default_factory=list)
    views: list[ManifestView] = field(default_factory=list)
    config: list[dict] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    context: bool = False
    version: int = 1


def forge_dir() -> Path:
    from django.conf import settings
    return Path(settings.FORGE_DIR)


def _module_dir(name: str) -> Path:
    if not MODULE_NAME_RE.match(name or ""):
        raise StoreError(f"nom de module invalide: {name!r}")
    return forge_dir() / name


def _ts() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S%f")


# ── Validation du manifest ────────────────────────────────────────


def validate_manifest(data: dict, name: str) -> tuple[ForgeManifest | None, list[str]]:
    """Valide un dict manifest. Retourne (manifest, erreurs).

    Messages en français — c'est Mika qui les lit pour corriger.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return None, ["le manifest doit être un objet YAML (clé: valeur)"]

    if not MODULE_NAME_RE.match(name or ""):
        errors.append(
            f"nom invalide {name!r} — attendu: minuscules/chiffres/_ , "
            "3-32 caractères, commence par une lettre"
        )
    elif name in RESERVED_NAMES:
        errors.append(f"nom réservé: {name}")

    title = str(data.get("title") or "").strip()
    if not title:
        errors.append("champ 'title' requis")
    description = str(data.get("description") or "").strip()

    schedule = str(data.get("schedule") or "").strip()
    if schedule and not _SCHEDULE_RE.match(schedule):
        errors.append(
            f"schedule invalide {schedule!r} — formats: '' | manual | "
            "interval:30s|5m|2h | idle:15m | cron:0 9 * * MON-FRI"
        )

    events_raw = data.get("events") or []
    events: list[str] = []
    if not isinstance(events_raw, list):
        errors.append("'events' doit être une liste de motifs (ex: ['rss.new_entry', 'chat.*'])")
    else:
        for ev in events_raw:
            ev = str(ev).strip()
            if not EVENT_PATTERN_RE.match(ev):
                errors.append(f"motif d'événement invalide: {ev!r}")
            else:
                events.append(ev)

    views: list[ManifestView] = []
    views_raw = data.get("views") or []
    if not isinstance(views_raw, list):
        errors.append("'views' doit être une liste d'objets {key, label, icon}")
    else:
        seen_keys: set[str] = set()
        for i, v in enumerate(views_raw):
            if not isinstance(v, dict):
                errors.append(f"views[{i}] doit être un objet")
                continue
            key = str(v.get("key") or "").strip()
            if not VIEW_KEY_RE.match(key):
                errors.append(f"views[{i}].key invalide: {key!r}")
                continue
            if key in seen_keys:
                errors.append(f"views[{i}].key dupliquée: {key}")
                continue
            seen_keys.add(key)
            views.append(ManifestView(
                key=key,
                label=str(v.get("label") or key)[:48],
                icon=str(v.get("icon") or "▦")[:2],
                order=int(v.get("order") or 100),
            ))

    config: list[dict] = []
    config_raw = data.get("config") or []
    if not isinstance(config_raw, list):
        errors.append("'config' doit être une liste de champs "
                      "{key, label, type, default, ...}")
    else:
        seen_cfg: set[str] = set()
        for i, c in enumerate(config_raw):
            cleaned = _validate_config_field(c, i, seen_cfg, errors)
            if cleaned:
                config.append(cleaned)

    domains_raw = data.get("allowed_domains") or []
    allowed_domains: list[str] = []
    if not isinstance(domains_raw, list):
        errors.append("'allowed_domains' doit être une liste de noms d'hôtes")
    else:
        for d in domains_raw:
            d = str(d).strip().lower()
            if not re.match(r"^[a-z0-9]([a-z0-9\-.]{0,253})$", d) or "." not in d:
                errors.append(f"domaine invalide: {d!r} (ex: 'wttr.in')")
            else:
                allowed_domains.append(d)

    if errors:
        return None, errors

    return ForgeManifest(
        name=name,
        title=title[:64],
        description=description[:500],
        schedule=schedule,
        events=events,
        views=views,
        config=config,
        allowed_domains=allowed_domains,
        context=bool(data.get("context", False)),
        version=int(data.get("version") or 1),
    ), []


def _validate_config_field(c, i: int, seen: set[str], errors: list[str]) -> dict | None:
    if not isinstance(c, dict):
        errors.append(f"config[{i}] doit être un objet")
        return None
    key = str(c.get("key") or "").strip()
    if not CONFIG_KEY_RE.match(key):
        errors.append(f"config[{i}].key invalide: {key!r}")
        return None
    if key in seen:
        errors.append(f"config[{i}].key dupliquée: {key}")
        return None
    seen.add(key)
    ftype = str(c.get("type") or "str").strip()
    if ftype not in _CONFIG_TYPES:
        errors.append(
            f"config[{i}].type invalide: {ftype!r} — types: "
            + ", ".join(sorted(_CONFIG_TYPES))
        )
        return None
    cleaned = {
        "key": key,
        "type": ftype,
        "label": str(c.get("label") or key)[:64],
        "description": str(c.get("description") or "")[:200],
        "default": c.get("default"),
    }
    if ftype == "select":
        choices = c.get("choices") or []
        if not isinstance(choices, list) or not choices:
            errors.append(f"config[{i}]: 'select' requiert une liste 'choices'")
            return None
        cleaned["choices"] = [str(x) for x in choices][:20]
    if ftype == "record_list":
        fields_raw = c.get("fields") or []
        if not isinstance(fields_raw, list) or not fields_raw:
            errors.append(f"config[{i}]: 'record_list' requiert 'fields'")
            return None
        sub_seen: set[str] = set()
        sub_fields = []
        for j, f in enumerate(fields_raw):
            if isinstance(f, dict) and f.get("type") == "record_list":
                errors.append(f"config[{i}].fields[{j}]: record_list imbriqué interdit")
                continue
            sub = _validate_config_field(f, j, sub_seen, errors)
            if sub:
                sub_fields.append(sub)
        if not sub_fields:
            return None
        cleaned["fields"] = sub_fields
    for bound in ("min", "max"):
        if c.get(bound) is not None:
            try:
                cleaned[bound] = float(c[bound])
            except (TypeError, ValueError):
                errors.append(f"config[{i}].{bound} doit être numérique")
    if c.get("sensitive") or ftype == "secret":
        cleaned["sensitive"] = True
        if ftype == "str":
            cleaned["type"] = "secret"
    return cleaned


# ── Lecture ───────────────────────────────────────────────────────


def list_module_names() -> list[str]:
    root = forge_dir()
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and MODULE_NAME_RE.match(p.name)
    )


def module_exists(name: str) -> bool:
    return _module_dir(name).is_dir()


def read_module(name: str) -> dict:
    """Retourne {manifest_raw, code, state}. Lève StoreError si absent."""
    mdir = _module_dir(name)
    if not mdir.is_dir():
        raise StoreError(f"module inconnu: {name}")
    manifest_path = mdir / "manifest.yaml"
    code_path = mdir / "module.py"
    raw = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if len(raw.encode()) > MAX_MANIFEST_BYTES:
        raise StoreError(f"manifest trop long (max {MAX_MANIFEST_BYTES // 1024} Ko)")
    try:
        manifest_raw = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise StoreError(f"manifest.yaml illisible: {exc}")
    code = code_path.read_text(encoding="utf-8") if code_path.exists() else ""
    return {
        "manifest_raw": manifest_raw,
        "code": code,
        "state": read_state(name),
    }


def read_state(name: str) -> dict:
    path = _module_dir(name) / "state.json"
    if not path.exists():
        return {"enabled": True, "disabled_reason": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"enabled": True, "disabled_reason": None}
    data.setdefault("enabled", True)
    data.setdefault("disabled_reason", None)
    return data


# ── Écriture ──────────────────────────────────────────────────────


def write_state(name: str, *, enabled: bool, disabled_reason: str | None = None) -> None:
    mdir = _module_dir(name)
    mdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": enabled,
        "disabled_reason": disabled_reason,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (mdir / "state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_module(name: str, manifest_dict: dict, code: str) -> None:
    """Écrit manifest + code, en archivant la version précédente s'il y en a une.

    La validation (manifest + sandbox) est de la responsabilité de
    l'appelant — ici on ne fait que du disque.
    """
    mdir = _module_dir(name)
    if mdir.exists():
        _archive_current(name)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest_dict, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (mdir / "module.py").write_text(code, encoding="utf-8")
    if not (mdir / "state.json").exists():
        write_state(name, enabled=True)


def _archive_current(name: str) -> str | None:
    """Copie manifest+code actuels dans _versions/<ts>/. Retourne le ts."""
    mdir = _module_dir(name)
    manifest = mdir / "manifest.yaml"
    code = mdir / "module.py"
    if not manifest.exists() and not code.exists():
        return None
    ts = _ts()
    vdir = mdir / "_versions" / ts
    vdir.mkdir(parents=True, exist_ok=True)
    if manifest.exists():
        shutil.copy2(manifest, vdir / "manifest.yaml")
    if code.exists():
        shutil.copy2(code, vdir / "module.py")
    _prune_versions(name)
    return ts


def _prune_versions(name: str) -> None:
    vroot = _module_dir(name) / "_versions"
    if not vroot.exists():
        return
    versions = sorted((p for p in vroot.iterdir() if p.is_dir()),
                      key=lambda p: p.name)
    for old in versions[:-MAX_VERSIONS_KEPT]:
        shutil.rmtree(old, ignore_errors=True)


def list_versions(name: str) -> list[str]:
    vroot = _module_dir(name) / "_versions"
    if not vroot.exists():
        return []
    return sorted((p.name for p in vroot.iterdir() if p.is_dir()), reverse=True)


def rollback(name: str) -> str:
    """Restaure le snapshot le plus récent de _versions/.

    La version courante est archivée d'abord, donc un double rollback
    fait un aller-retour. Retourne le ts restauré.
    """
    versions = list_versions(name)
    if not versions:
        raise StoreError(f"aucune version archivée pour {name}")
    target = versions[0]
    mdir = _module_dir(name)
    vdir = mdir / "_versions" / target
    # Archive l'état courant AVANT d'écraser (le nouveau snapshot devient
    # versions[0], donc on restaure versions[1] au prochain rollback).
    _archive_current(name)
    for fname in ("manifest.yaml", "module.py"):
        src = vdir / fname
        if src.exists():
            shutil.copy2(src, mdir / fname)
    return target


def erase(name: str) -> str:
    """Déplace le module vers _trash/ (soft delete). Retourne le chemin."""
    mdir = _module_dir(name)
    if not mdir.is_dir():
        raise StoreError(f"module inconnu: {name}")
    trash = forge_dir() / "_trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{name}-{_ts()}"
    shutil.move(str(mdir), str(dest))
    _prune_trash()
    return str(dest)


def _prune_trash() -> None:
    """Ne garde que les MAX_TRASH_KEPT suppressions les plus récentes."""
    trash = forge_dir() / "_trash"
    if not trash.is_dir():
        return
    # Les noms sont "<slug>-<timestamp>" : trier par mtime évite de dépendre
    # de l'ordre alphabétique des slugs.
    entries = sorted(
        (p for p in trash.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    for old in entries[:-MAX_TRASH_KEPT]:
        shutil.rmtree(old, ignore_errors=True)
