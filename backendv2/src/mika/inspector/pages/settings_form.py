"""Les réglages d'exploitation, rendus depuis leurs modèles.

Une section (``catalog.SettingsSection``) apporte un modèle pydantic, sa valeur
actuelle et de quoi l'enregistrer ; ``kernel/forms.py`` en tire les champs.
Rien ici ne connaît un réglage en particulier :

- les champs se rangent par groupe, le bloc « avancé » replié (ouvert s'il porte
  une erreur) ;
- un secret ne redescend jamais (vide = inchangé, « effacer » pour le vider) ;
- un champ ``records`` (des fournisseurs, par exemple) devient une liste dont
  chaque entrée se modifie, s'ajoute ou se retire à part ; un champ ``mapping``
  (rôle → fournisseur) devient une ligne par clé ;
- un choix chargé à la demande (les modèles d'un fournisseur) passe par
  « enregistrer et charger la liste » : le secret tapé n'est jamais renvoyé ;
- une soumission refusée remontre le formulaire avec les valeurs tapées et une
  erreur à côté de chaque champ (400) ; acceptée, elle est auditée
  (``runtime.operated``, sans contenu) et la page revient avec un message.
"""

from __future__ import annotations

import dataclasses
import secrets as _secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import yaml
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector import render
from mika.inspector.catalog import Builtin, Panel, SettingsSection, SettingsTab
from mika.inspector.formview import field_view
from mika.inspector.ui import PREFIX, secure
from mika.kernel import forms
from mika.runtime import operations

SECTION = "_section"
LOAD = "_charger"
RECORD = "_enregistrement"
RECORD_KEY = "_cle"
RECORD_OLD = "_ancienne"
DELETE = "_supprimer"
COMMAND = "_commande"
YAML = "_yaml"
YAML_TEXT = "_texte"
BAD_TOKEN = "Jeton de formulaire invalide : recharge la page."


@dataclass(slots=True)
class State:
    """Ce qu'une soumission refusée remontre (valeurs tapées, erreurs)."""

    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    messages: list[tuple[str, str]] = field(default_factory=list)
    #: une entrée en cours d'édition : (chemin, clé d'origine), ses valeurs et erreurs
    record: tuple[str, str] | None = None
    record_values: dict[str, Any] = field(default_factory=dict)
    record_errors: dict[str, str] = field(default_factory=dict)
    yaml_text: str | None = None


def tab_url(tab: str, **query: str) -> str:
    base = f"{PREFIX}/reglages/{tab}"
    query = {k: v for k, v in query.items() if v}
    return base + (f"?{urlencode(query)}" if query else "")


def _error_for(path: str, errors: Mapping[str, str]) -> str:
    """L'erreur d'un champ, y compris celles de ses éléments (« owners.0 »)."""
    found = [msg for p, msg in errors.items() if p == path or p.startswith(path + ".")]
    return " ; ".join(dict.fromkeys(found))


def _placed(paths: Sequence[str], errors: Mapping[str, str]) -> list[str]:
    """Les erreurs qu'aucun champ affiché ne porte (une règle du modèle entier)."""
    return [msg for p, msg in errors.items() if not any(p == q or p.startswith(q + ".") for q in paths)]


def _excluded(path: str, exclude: Sequence[str]) -> bool:
    return any(path == e or path.startswith(e + ".") for e in exclude)


def _defaults(fields: Sequence[forms.FormField]) -> dict[str, Any]:
    return {f.path: f.default for f in fields if f.kind != "group" and f.default is not None}


def _view(f: forms.FormField, value: Any, error: str, prefix: str,
          loaded: Sequence[tuple[str, str]] | None = None) -> dict[str, Any] | None:
    if f.loader and not f.choices:
        if loaded:
            choices = tuple(loaded)
            if value and str(value) not in {v for v, _ in choices}:
                choices = ((str(value), f"{value} (actuel)"), *choices)
            f = dataclasses.replace(f, kind="select", choices=choices)
        else:
            f = dataclasses.replace(f, kind="text")
    v = field_view(f, value, error=error, prefix=prefix)
    if v is not None:
        v["loader"] = bool(f.loader) and not loaded
        if f.kind == "duration":
            v["placeholder"] = "ex. 10 min, 1 h 30"
    return v


def _mapping_view(f: forms.FormField, given: Mapping[str, Any], errors: Mapping[str, str],
                  prefix: str) -> dict[str, Any]:
    item = f.item[0] if f.item else None
    current = given.get(f.path) or {}
    keys = f.keys or tuple((k, k) for k in sorted(current))
    choices: tuple[tuple[str, str], ...] = item.choices if item is not None else ()
    if f.choices_from:
        source = given.get(f.choices_from)
        choices = tuple((str(k), str(k)) for k in sorted(source)) if isinstance(source, Mapping) else ()
    rows = []
    for key, label in keys:
        base = item or dataclasses.replace(f, kind="text", item=())
        sub = dataclasses.replace(base, path=f"{f.path}.{key}", label=label, required=False,
                                  readonly=f.readonly or base.readonly,
                                  kind="select" if (choices or f.choices_from) else base.kind, choices=choices)
        view = field_view(sub, current.get(key), error=errors.get(sub.path, ""), prefix=prefix)
        if view is not None:
            view["nochamp"] = True
            rows.append(view)
    return {"kind": "mapping", "path": f.path, "label": f.label, "help": f.help, "rows": rows,
            "readonly": f.readonly, "error": _error_for(f.path, {k: v for k, v in errors.items() if k == f.path})}


def _grouped(views: Sequence[tuple[forms.FormField, dict[str, Any]]]) -> tuple[list[dict[str, Any]],
                                                                                 list[dict[str, Any]]]:
    """(groupes ouverts, groupes avancés), dans l'ordre d'apparition."""
    plain: dict[str, list[dict[str, Any]]] = {}
    advanced: dict[str, list[dict[str, Any]]] = {}
    for f, view in views:
        (advanced if f.advanced else plain).setdefault(f.group, []).append(view)
    return ([{"title": t, "fields": fs} for t, fs in plain.items()],
            [{"title": t, "fields": fs} for t, fs in advanced.items()])


class SettingsForms:
    """Les onglets de réglages de la composition, et ce qu'ils savent faire."""

    def __init__(self, sections: Sequence[SettingsSection], tabs: Sequence[SettingsTab]) -> None:
        self.sections = {s.key: s for s in sections}
        self.tabs = {t.key: t for t in tabs}
        problems = [f"réglages : la section {s.key} vise un onglet inconnu {s.tab}" for s in sections
                    if s.tab not in self.tabs]
        problems += [f"réglages : l'onglet {t.key} n'a aucune section" for t in tabs
                     if not any(s.tab == t.key for s in sections)]
        if len(self.sections) != len(sections):
            problems.append("réglages : deux sections portent la même clé")
        if problems:
            from mika.kernel.registry import CompositionError  # noqa: PLC0415

            raise CompositionError(problems)

    def of_tab(self, tab: str) -> list[SettingsSection]:
        return sorted((s for s in self.sections.values() if s.tab == tab), key=lambda s: (s.order, s.label))

    def builtins(self) -> dict[str, Builtin]:
        out = {}
        for t in self.tabs.values():
            key = f"reglages.{t.key}"

            async def fn(ui: Any, request: Request, _tab: str = t.key) -> Any:
                return await self.panel(ui, request, _tab, {})

            out[key] = Builtin(key, t.title, fn)
        return out

    # ── rendre ──
    async def panel(self, ui: Any, request: Request, tab: str, states: Mapping[str, State]) -> Panel:
        csrf = ui.csrf(request)
        env = ui.env()
        query = request.query_params
        views = []
        for s in self.of_tab(tab):
            state = states.get(s.key) or State()
            editing: tuple[str, str] | None = state.record
            loaded: dict[str, list[tuple[str, str]]] = {}
            if editing is None and query.get("section") == s.key and query.get("enregistrement"):
                editing = (query["enregistrement"], query.get("cle", ""))
                wanted = query.get("charger", "")
                if wanted:
                    got = await self._load_choices(s, editing, wanted)
                    if isinstance(got, str):
                        state.messages.append(("warn", got))
                    else:
                        loaded[wanted] = got
            views.append(self._section_view(s, state, csrf, tab, env, editing, loaded))
        return Panel("settings.html", {"sections": views, "action": tab_url(tab)})

    def _section_view(self, s: SettingsSection, state: State, csrf: str, tab: str, env: Any,
                      editing: tuple[str, str] | None, loaded: Mapping[str, list[tuple[str, str]]]
                      ) -> dict[str, Any]:
        prefix = f"s-{s.key}"
        current = s.load() if s.model is not None else None
        out: dict[str, Any] = {"key": s.key, "label": s.label, "description": s.description, "csrf": csrf,
                               "messages": list(state.messages), "form": None, "records": [], "record": None,
                               "commands": [{"key": c.key, "title": c.title, "confirm": c.confirm,
                                             "danger": c.danger} for c in s.commands],
                               "facts": list(s.facts()) if s.facts else [], "yaml": None,
                               "blocks": render.blocks(list(s.blocks()), env, {}) if s.blocks else []}
        if s.model is None:
            return out
        fields = [f for f in forms.describe(s.model) if not _excluded(f.path, s.exclude)]
        flat = forms.flatten(current) if isinstance(current, BaseModel) else _defaults(fields)
        given = {**flat, **state.values}
        placed: list[tuple[forms.FormField, dict[str, Any]]] = []
        for f in fields:
            if f.kind == "group":
                continue
            if f.kind == "records":
                if "." not in f.path:
                    out["records"].append(self._records_view(s, f, current, tab))
                continue
            if f.kind == "mapping":
                placed.append((f, _mapping_view(f, given, state.errors, prefix)))
                continue
            view = _view(f, given.get(f.path), _error_for(f.path, state.errors), prefix)
            if view is not None:
                placed.append((f, view))
        if placed:
            groups, advanced = _grouped(placed)
            out["form"] = {"groups": groups, "advanced": advanced,
                           "open": any(v.get("error") for f, v in placed if f.advanced),
                           "general": _placed([f.path for f in fields], state.errors)}
        if editing is not None:
            out["record"] = self._record_view(s, current, editing, state, loaded, tab)
        if s.yaml:
            text = state.yaml_text
            if text is None and isinstance(current, BaseModel):
                text = yaml.safe_dump(_without_secrets(s.model, current), allow_unicode=True, sort_keys=False,
                                      width=100)
            out["yaml"] = {"text": text or ""}
        return out

    def _records_view(self, s: SettingsSection, f: forms.FormField, current: Any, tab: str) -> dict[str, Any]:
        found = forms.record_model(s.model, f.path)
        keyed = found[1] if found else True
        entries = getattr(current, f.path, None) or ({} if keyed else ())
        items = list(entries.items()) if keyed else [(str(i), e) for i, e in enumerate(entries)]
        shown = [i for i in f.item if not i.secret and not i.advanced and i.kind in ("select", "text", "int")][:3]
        secrets_ = [i for i in f.item if i.secret]
        rows = []
        for key, entry in items:
            flat = forms.flatten(entry) if isinstance(entry, BaseModel) else {}
            cells = [_shown(i, flat.get(i.path)) for i in shown]
            cells += ["défini" if flat.get(i.path) else "—" for i in secrets_]
            rows.append({"key": key, "cells": cells,
                         "edit": tab_url(tab, section=s.key, enregistrement=f.path, cle=key)})
        return {"path": f.path, "label": f.label, "help": f.help, "keyed": keyed,
                "columns": [i.label for i in shown] + [i.label for i in secrets_], "rows": rows,
                "add": tab_url(tab, section=s.key, enregistrement=f.path, cle="") + "&nouveau=1"}

    def _record_view(self, s: SettingsSection, current: Any, editing: tuple[str, str], state: State,
                     loaded: Mapping[str, list[tuple[str, str]]], tab: str) -> dict[str, Any] | None:
        path, key = editing
        found = forms.record_model(s.model, path)
        if found is None:
            return None
        model, keyed = found
        fields = forms.describe(model)
        entry = _entry(current, path, key, keyed)
        flat = forms.flatten(entry) if entry is not None else _defaults(fields)
        given = {**flat, **state.record_values}
        prefix = f"r-{s.key}-{path}"
        placed = []
        for f in fields:
            if f.kind in ("group", "records", "mapping"):
                continue
            view = _view(f, given.get(f.path), _error_for(f.path, state.record_errors), prefix, loaded.get(f.path))
            if view is not None:
                view["load_button"] = view.get("loader", False)
                placed.append((f, view))
        groups, advanced = _grouped(placed)
        label = next((f.label for f in forms.describe(s.model) if f.path == path), path)
        name = state.record_values.get(RECORD_KEY, key)
        return {"path": path, "label": label, "key": key, "keyed": keyed, "new": entry is None,
                "name": name, "name_error": state.record_errors.get(RECORD_KEY, ""), "groups": groups,
                "advanced": advanced, "open": any(v.get("error") for f, v in placed if f.advanced),
                "general": _placed([f.path for f in fields] + [RECORD_KEY], state.record_errors),
                "cancel": tab_url(tab)}

    async def _load_choices(self, s: SettingsSection, editing: tuple[str, str],
                            wanted: str) -> list[tuple[str, str]] | str:
        path, key = editing
        found = forms.record_model(s.model, path) if s.model is not None else None
        entry = _entry(s.load(), path, key, found[1]) if found else None
        fields = forms.describe(found[0]) if found else ()
        spec = next((f for f in fields if f.path == wanted), None)
        loader = s.loaders.get(spec.loader) if spec is not None else None
        if loader is None or entry is None:
            return "Rien à charger ici."
        try:
            return list(await loader(forms.flatten(entry)))[:500]
        except ValueError as exc:
            return f"Liste indisponible : {exc}"[:300]

    # ── enregistrer ──
    async def post(self, ui: Any, request: Request, tab: str) -> tuple[Response | None, dict[str, State], int]:
        """Une soumission : une réponse (redirection) si elle a abouti, sinon les états
        à remontrer et le statut."""
        got = await ui.form_lists(request)
        account = ui.operator(request)
        if got is None or account is None:
            return None, {"": State(messages=[("danger", BAD_TOKEN)])}, 403
        data, lists = got
        s = self.sections.get(data.get(SECTION, ""))
        if s is None or s.tab != tab:
            return None, {"": State(messages=[("danger", "Section inconnue.")])}, 400
        by = account.handle
        if data.get(COMMAND):
            return await self._command(ui, s, data[COMMAND], by, tab)
        if s.model is None or s.save is None:
            return None, {s.key: State(messages=[("danger", "Rien à enregistrer ici.")])}, 400
        current = s.load()
        if data.get(DELETE):
            return await self._delete(ui, s, current, data[DELETE], data.get(RECORD_KEY, ""), by, tab)
        if data.get(RECORD):
            return await self._save_record(ui, s, current, data, lists, by, tab)
        if data.get(YAML) and s.yaml:
            return await self._save_yaml(ui, s, data.get(YAML_TEXT, ""), by, tab)
        fields = [f for f in forms.describe(s.model) if not _excluded(f.path, s.exclude)]
        flat = forms.flatten(current)
        values, errors = forms.parse(fields, lists, current=flat, load=_yaml_load)
        errors = {**errors, **forms.within(fields, values)}
        new = None
        if not errors:
            new, errors = forms.validate(s.model, current, values)
        if errors or new is None:
            return None, {s.key: State(values=values, errors=errors, messages=[
                ("danger", "Rien n'a été enregistré : corrige les champs signalés.")])}, 400
        if new == current:
            return self._done(ui, tab, "info", "Rien n'a changé."), {}, 303
        return await self._commit(ui, s, new, by, tab, s.key, State(values=values))

    async def _commit(self, ui: Any, s: SettingsSection, new: Any, by: str, tab: str, subject: str,
                      state: State, message: str = "") -> tuple[Response | None, dict[str, State], int]:
        assert s.save is not None
        try:
            problems = await s.save(new, by)
        except ValueError as exc:
            problems = [str(exc)]
        if problems:
            state.messages = [("danger", p) for p in problems]
            return None, {s.key: state}, 400
        await operations.audit(ui.kernel, f"console.reglages.{s.key}", by=by, subject_kind="reglage",
                               subject=subject)
        return self._done(ui, tab, "ok", message or f"{s.label} : enregistré."), {}, 303

    async def _save_record(self, ui: Any, s: SettingsSection, current: Any, data: Mapping[str, str],
                           lists: Mapping[str, list[str]], by: str,
                           tab: str) -> tuple[Response | None, dict[str, State], int]:
        path, old = data.get(RECORD, ""), data.get(RECORD_OLD, "")
        found = forms.record_model(s.model, path)
        if found is None:
            return None, {s.key: State(messages=[("danger", "Liste inconnue.")])}, 400
        model, keyed = found
        fields = forms.describe(model)
        entry = _entry(current, path, old, keyed)
        flat = forms.flatten(entry) if entry is not None else _defaults(fields)
        values, errors = forms.parse(fields, lists, current=flat, load=_yaml_load)
        errors = {**errors, **forms.within(fields, values)}
        name = data.get(RECORD_KEY, old).strip()[:60] if keyed else old
        collection = getattr(current, path)
        if keyed and not name:
            errors[RECORD_KEY] = "Donne un nom."
        elif keyed and name != old and name in collection:
            errors[RECORD_KEY] = "Ce nom existe déjà."
        record = None
        if not errors:
            record, errors = _record_from(model, entry, flat, values)
        state = State(record=(path, old), record_values={**values, RECORD_KEY: name}, record_errors=errors)
        if errors or record is None:
            state.messages = [("danger", "Rien n'a été enregistré : corrige les champs signalés.")]
            return None, {s.key: state}, 400
        plain = forms.flatten(current)[path]
        if keyed:
            updated = {k: v for k, v in dict(plain).items() if k != old}
            updated[name] = record.model_dump(mode="python")
        else:
            updated = list(plain)
            if old.isdigit() and int(old) < len(updated):
                updated[int(old)] = record.model_dump(mode="python")
            else:
                updated.append(record.model_dump(mode="python"))
        new, errors = forms.validate(s.model, current, {path: updated})
        if new is None:
            state.record_errors = errors
            state.messages = [("danger", " ; ".join(errors.values()) or "Refusé.")]
            return None, {s.key: state}, 400
        subject = f"{s.key}/{path}/{name}"
        response, states, status = await self._commit(ui, s, new, by, tab, subject, state,
                                                      f"« {name} » enregistré." if keyed else "Enregistré.")
        wanted = data.get(LOAD, "")
        if response is not None and wanted:
            target = tab_url(tab, section=s.key, enregistrement=path, cle=name, charger=wanted)
            return secure(RedirectResponse(target, status_code=303)), {}, 303
        return response, states, status

    async def _delete(self, ui: Any, s: SettingsSection, current: Any, path: str, key: str, by: str,
                      tab: str) -> tuple[Response | None, dict[str, State], int]:
        found = forms.record_model(s.model, path)
        if found is None or _entry(current, path, key, found[1]) is None:
            return None, {s.key: State(messages=[("danger", "Entrée inconnue.")])}, 400
        plain = forms.flatten(current)[path]
        if found[1]:
            updated: Any = {k: v for k, v in dict(plain).items() if k != key}
        else:
            updated = [v for i, v in enumerate(plain) if str(i) != key]
        new, errors = forms.validate(s.model, current, {path: updated})
        if new is None:
            return None, {s.key: State(messages=[("danger", " ; ".join(errors.values()))])}, 400
        return await self._commit(ui, s, new, by, tab, f"{s.key}/{path}/{key}", State(),
                                  f"« {key} » retiré.")

    async def _save_yaml(self, ui: Any, s: SettingsSection, text: str, by: str,
                         tab: str) -> tuple[Response | None, dict[str, State], int]:
        state = State(yaml_text=text)
        try:
            data = yaml.safe_load(text) or {}
            if not isinstance(data, dict):
                raise ValueError("attendu : une table « clé: valeur »")
            assert s.model is not None
            new = s.model.model_validate(data)
        except yaml.YAMLError as exc:
            state.messages = [("danger", f"YAML illisible : {exc}"[:400])]
            return None, {s.key: state}, 400
        except ValidationError as exc:
            state.messages = [("danger", f"{p or 'document'} : {m}") for p, m in forms.errors_fr(exc).items()]
            return None, {s.key: state}, 400
        except ValueError as exc:
            state.messages = [("danger", str(exc))]
            return None, {s.key: state}, 400
        return await self._commit(ui, s, new, by, tab, s.key, state, f"{s.label} : importée.")

    async def _command(self, ui: Any, s: SettingsSection, key: str, by: str,
                       tab: str) -> tuple[Response | None, dict[str, State], int]:
        command = next((c for c in s.commands if c.key == key), None)
        if command is None:
            return None, {s.key: State(messages=[("danger", "Commande inconnue.")])}, 400
        try:
            tone, message = await command.run(by)
        except ValueError as exc:
            return None, {s.key: State(messages=[("danger", str(exc))])}, 400
        await operations.audit(ui.kernel, f"console.reglages.{s.key}.{command.key}", by=by,
                               subject_kind="reglage", subject=s.key)
        return self._done(ui, tab, tone, message), {}, 303

    def _done(self, ui: Any, tab: str, tone: str, message: str) -> Response:
        token = _secrets.token_urlsafe(9)
        ui.flash(token, tone, message)
        return secure(RedirectResponse(tab_url(tab, flash=token), status_code=303))


def _entry(current: Any, path: str, key: str, keyed: bool) -> BaseModel | None:
    entries = getattr(current, path, None)
    if entries is None:
        return None
    if keyed:
        found = entries.get(key) if key else None
    else:
        found = entries[int(key)] if key.isdigit() and int(key) < len(entries) else None
    return found if isinstance(found, BaseModel) else None


def _record_from(model: type[BaseModel], entry: BaseModel | None, flat: Mapping[str, Any],
                 values: Mapping[str, Any]) -> tuple[BaseModel | None, dict[str, str]]:
    if entry is not None:
        return forms.validate(model, entry, values)
    try:
        return model.model_validate(forms.nest({**flat, **values})), {}
    except ValidationError as exc:
        return None, forms.errors_fr(exc)


def _shown(f: forms.FormField, value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = forms.as_text(f, value)
    return next((label for v, label in f.choices if v == text), text)[:80]


def _without_secrets(model: type[BaseModel], value: BaseModel) -> dict[str, Any]:
    secret = {f.path for f in forms.describe(model) if f.secret}
    data = value.model_dump(mode="json")
    for path in secret:
        node: Any = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return data


def _yaml_load(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(str(exc)[:200]) from None
