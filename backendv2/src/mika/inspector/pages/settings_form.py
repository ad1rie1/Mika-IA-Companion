"""Les réglages d'exploitation, rendus depuis leurs modèles, une sous-page à la fois.

Une section (``catalog.SettingsSection``) apporte un modèle pydantic, sa valeur
actuelle et de quoi l'enregistrer ; elle se découpe en **sous-pages**
(``SettingsPage``) qui ne montrent chacune qu'un sujet — jamais toute la
section d'un coup. ``kernel/forms.py`` en tire les champs. Rien ici ne connaît
un réglage en particulier :

- une page rend ses champs rangés par groupe, les « options avancées » repliées
  (ouvertes si elles portent une erreur), l'aide de chaque champ sous lui ;
- un secret ne redescend jamais (vide = inchangé, « effacer » pour le vider) ;
- un champ ``records`` (des fournisseurs, des boîtes) devient une table paginée
  dont chaque entrée se modifie sur sa propre page ; un champ ``mapping``
  (rôle → fournisseur) devient une ligne par clé ;
- un choix limité est un sélecteur : les choix d'un chargeur (les modèles d'un
  fournisseur) se chargent d'eux-mêmes sur la page d'une entrée existante, ceux
  d'un autre champ (``choices_from`` : le repli parmi les fournisseurs) et ceux
  que la section fournit (``choices`` : les fuseaux) sont posés au rendu ;
- une commande qui porte une valeur (``Command.argument`` : revenir à une
  révision) se pose en place dans les blocs de sa section, avec sa confirmation ;
- une soumission refusée remontre la page avec les valeurs tapées et une erreur
  à côté de chaque champ (400) ; acceptée, elle est auditée (``runtime.operated``,
  sans contenu) et la page revient avec un message ;
- une section qui le déclare (``preview``) a un bouton « Voir l'effet » : la
  soumission, relue et validée comme pour l'enregistrer, revient avec ce qu'elle
  changerait — rien n'est enregistré ni audité.
"""

from __future__ import annotations

import dataclasses
import math
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
from mika.inspector.catalog import Builtin, Panel, SettingsPage, SettingsSection, SettingsTab
from mika.inspector.formview import field_view
from mika.inspector.ui import PREFIX, secure
from mika.kernel import forms
from mika.kernel.clock import US
from mika.kernel.inspect import Pager
from mika.runtime import operations

SECTION = "_section"
LOAD = "_charger"
RECORD = "_enregistrement"
#: la page de la console où revenir après avoir enregistré un enregistrement
BACK = "_retour"
RECORD_KEY = "_cle"
RECORD_OLD = "_ancienne"
DELETE = "_supprimer"
COMMAND = "_commande"
YAML = "_yaml"
YAML_TEXT = "_texte"
#: « Voir l'effet » : le formulaire relu et validé, montré avec ce qu'il changerait, rien d'écrit
PREVIEW = "_apercu"
BAD_TOKEN = "Jeton de formulaire invalide : recharge la page."
#: les entrées d'une liste par page
RECORDS_PAGE = 25
#: les colonnes d'une liste d'entrées (hors nom et secrets)
RECORD_COLUMNS = 4
#: un choix chargé à la demande n'en garde pas plus
LOADED_MAX = 500
#: une entrée neuve : les secrets tapés avant de charger une liste sont gardés côté serveur (jamais
#: renvoyés dans la page), sous un jeton, le temps de finir le formulaire
STASH = "_reserve"
STASH_TTL_S = 900
STASH_MAX = 64


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
    #: la page de la console d'où l'on vient (vide : les réglages)
    back: str = ""
    #: les choix chargés pour une entrée neuve (chemin → choix), et le jeton de ses secrets gardés
    loaded: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    stash: str = ""
    stashed: tuple[str, ...] = ()
    #: « Voir l'effet » : ce que changeraient les valeurs tapées (des blocs)
    preview: list[Any] = field(default_factory=list)


def page_url(page: str, **query: str) -> str:
    base = f"{PREFIX}/reglages/{page}"
    query = {k: v for k, v in query.items() if v}
    return base + (f"?{urlencode(query)}" if query else "")


#: l'ancien nom (un onglet par section)
tab_url = page_url


def _error_for(path: str, errors: Mapping[str, str]) -> str:
    """L'erreur d'un champ, y compris celles de ses éléments (« owners.0 »)."""
    found = [msg for p, msg in errors.items() if p == path or p.startswith(path + ".")]
    return " ; ".join(dict.fromkeys(found))


def _placed(paths: Sequence[str], errors: Mapping[str, str]) -> list[str]:
    """Les erreurs qu'aucun champ affiché ne porte (une règle du modèle entier)."""
    return [msg for p, msg in errors.items() if not any(p == q or p.startswith(q + ".") for q in paths)]


def _excluded(path: str, exclude: Sequence[str]) -> bool:
    return any(path == e or path.startswith(e + ".") for e in exclude)


def _within(path: str, wanted: Sequence[str]) -> bool:
    return not wanted or any(path == w or path.startswith(w + ".") for w in wanted)


def _defaults(fields: Sequence[forms.FormField]) -> dict[str, Any]:
    return {f.path: f.default for f in fields if f.kind != "group" and f.default is not None}


def _with_kept(fields: Sequence[forms.FormField], lists: Mapping[str, list[str]],
               kept: Mapping[str, str]) -> dict[str, list[str]]:
    """La soumission, où un secret gardé dans la réserve (tapé avant de charger une liste, ou lors d'un envoi
    refusé) remplace le même secret laissé vide."""
    out = dict(lists)
    for f in fields:
        if f.secret and f.path in kept and not "".join(out.get(f.path) or []).strip():
            out[f.path] = [kept[f.path]]
    return out


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


def _with_choices(f: forms.FormField, choices: Sequence[tuple[str, str]], value: Any) -> forms.FormField:
    """Un champ texte dont les choix sont connus au rendu devient un sélecteur (la
    valeur actuelle, même hors liste, reste proposée)."""
    pairs = tuple(choices)
    if value not in (None, "") and str(value) not in {v for v, _ in pairs}:
        pairs = ((str(value), f"{value} (actuel)"), *pairs)
    return dataclasses.replace(f, kind="select", choices=pairs)


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
    """Les pages de configuration de la composition, et ce qu'elles savent faire.

    ``tabs`` sont les rubriques du sous-menu (Intelligence, Personnage…) ; chaque
    section y appartient par ``SettingsSection.tab`` et y apporte ses pages."""

    def __init__(self, sections: Sequence[SettingsSection], tabs: Sequence[SettingsTab]) -> None:
        self.sections = {s.key: s for s in sections}
        self.rubrics = {t.key: t for t in tabs}
        #: jeton → (échéance, {chemin: secret}) : les secrets d'une entrée neuve, le temps de la finir
        self._stash: dict[str, tuple[int, dict[str, str]]] = {}
        self._rubric_order = [t.key for t in tabs]
        #: page → (section, page), dans l'ordre du sous-menu
        self.pages: dict[str, tuple[SettingsSection, SettingsPage]] = {}
        problems = [f"réglages : la section {s.key} vise une rubrique inconnue {s.tab}" for s in sections
                    if s.tab not in self.rubrics]
        problems += [f"réglages : la rubrique {t.key} n'a aucune section" for t in tabs
                     if not any(s.tab == t.key for s in sections)]
        if len(self.sections) != len(sections):
            problems.append("réglages : deux sections portent la même clé")
        for s in self._ordered():
            for pg in self.pages_of(s):
                if pg.key in self.pages:
                    problems.append(f"réglages : la page {pg.key} est déclarée deux fois")
                self.pages[pg.key] = (s, pg)
                if s.model is not None and pg.fields:
                    known = {f.path for f in forms.describe(s.model)}
                    problems += [f"réglages : la page {pg.key} montre un champ inconnu {p}" for p in pg.fields
                                 if p not in known]
        if problems:
            from mika.kernel.registry import CompositionError  # noqa: PLC0415

            raise CompositionError(problems)

    #: l'ancien nom (une page par onglet) : ce que connaît la route d'enregistrement
    @property
    def tabs(self) -> dict[str, tuple[SettingsSection, SettingsPage]]:
        return self.pages

    def _ordered(self) -> list[SettingsSection]:
        rank = {k: i for i, k in enumerate(self._rubric_order)}
        return sorted(self.sections.values(), key=lambda s: (rank.get(s.tab, 99), s.order, s.label))

    @staticmethod
    def pages_of(s: SettingsSection) -> tuple[SettingsPage, ...]:
        return s.pages or (SettingsPage(s.key, s.label, (), s.description, commands=True, blocks=True,
                                        yaml=s.yaml),)

    def page_for(self, section: str, path: str = "") -> str:
        """La page d'une section qui montre ce chemin (ou sa première page)."""
        s = self.sections.get(section)
        if s is None:
            return ""
        pages = self.pages_of(s)
        return next((p.key for p in pages if path and _within(path, p.fields) and p.fields), pages[0].key)

    def builtins(self) -> dict[str, Builtin]:
        out: dict[str, Builtin] = {}
        rank = {k: i for i, k in enumerate(self._rubric_order)}
        n = 0
        for s in self._ordered():
            rubric = self.rubrics.get(s.tab)
            for pg in self.pages_of(s):
                n += 1
                key = f"reglages.{pg.key}"

                async def fn(ui: Any, request: Request, _page: str = pg.key) -> Any:
                    return await self.panel(ui, request, _page, {})

                out[key] = Builtin(key, pg.title, fn, group=rubric.title if rubric else "",
                                   order=(rank.get(s.tab, 50) + 1) * 100 + n,
                                   description=pg.description or s.description)
        return out

    # ── rendre ──
    async def panel(self, ui: Any, request: Request, page: str, states: Mapping[str, State]) -> Panel:
        s, pg = self.pages[page]
        csrf = ui.csrf(request)
        env = ui.env()
        query = request.query_params
        state = states.get(s.key) or State()
        editing: tuple[str, str] | None = state.record
        loaded: dict[str, list[tuple[str, str]]] = dict(state.loaded)
        if editing is None and query.get("enregistrement") and (query.get("section") in ("", None, s.key)):
            editing = (query["enregistrement"], query.get("cle", ""))
            state.back = back_to(query.get("retour", ""))
        wanted = query.get("charger", "")
        if editing is not None and editing[1] and wanted:
            # un fournisseur n'est interrogé que quand on le demande (« Charger la liste », ou un lien qui
            # porte ``charger=``) : afficher sa page ne coûte jamais un appel réseau de plusieurs secondes
            for path in self._loader_paths(s, editing[0]):
                if path != wanted:
                    continue
                got = await self._load_choices(s, editing, path)
                if isinstance(got, str):
                    state.messages.append(("warn", got))
                else:
                    loaded[path] = got
        view = self._section_view(s, pg, state, csrf, page, env, editing, loaded, query)
        record = view.get("record")
        heading = (("Ajouter · " + record["label"]) if record["new"] else
                   "Modifier · " + (record["key"] or record["label"])) if record else ""
        return Panel("settings.html", {"sections": [view], "action": page_url(page), "page_heading": heading})

    def _fields(self, s: SettingsSection, pg: SettingsPage) -> list[forms.FormField]:
        assert s.model is not None
        return [f for f in forms.describe(s.model) if not _excluded(f.path, s.exclude) and _within(f.path, pg.fields)]

    def _section_view(self, s: SettingsSection, pg: SettingsPage, state: State, csrf: str, page: str, env: Any,
                      editing: tuple[str, str] | None, loaded: Mapping[str, list[tuple[str, str]]],
                      query: Mapping[str, str]) -> dict[str, Any]:
        prefix = f"s-{s.key}"
        current = s.load() if s.model is not None else None
        blocks = render.blocks([*(s.blocks() if s.blocks and pg.blocks else ()), *(pg.extra() if pg.extra else ())],
                               env, query)
        out: dict[str, Any] = {"key": s.key, "label": pg.title, "description": "", "csrf": csrf,
                               "messages": list(state.messages), "form": None, "records": [], "record": None,
                               "commands": [{"key": c.key, "title": c.title, "confirm": c.confirm,
                                             "danger": c.danger} for c in s.commands
                                            if not c.argument] if pg.commands else [],
                               "facts": list(s.facts()) if s.facts and pg.facts else [], "yaml": None,
                               "blocks": blocks, "forms": self._command_forms(s, blocks, csrf, page),
                               "preview": render.blocks(state.preview, env, query) if state.preview else []}
        if s.model is None:
            return out
        fields = self._fields(s, pg) if pg.form else []
        flat = forms.flatten(current) if isinstance(current, BaseModel) else _defaults(fields)
        given = {**flat, **state.values}
        if editing is not None:
            out["record"] = self._record_view(s, current, editing, state, loaded, page)
            if out["record"] is not None:
                out["commands"], out["blocks"], out["facts"] = [], [], []
                return out
        placed: list[tuple[forms.FormField, dict[str, Any]]] = []
        for f in fields:
            if f.kind == "group":
                continue
            if f.kind == "records":
                if "." not in f.path:
                    out["records"].append(self._records_view(s, f, current, page, query))
                continue
            if f.kind == "mapping":
                placed.append((f, _mapping_view(f, given, state.errors, prefix)))
                continue
            if f.path in s.choices:
                f = _with_choices(f, s.choices[f.path](), given.get(f.path))
            view = _view(f, given.get(f.path), _error_for(f.path, state.errors), prefix)
            if view is not None:
                if f.secret and f.path in state.stashed:
                    view["has_value"] = True  # tapé, gardé côté serveur : vide = le garder
                view["hidden"] = bool(f.only or f.only_any) and not forms.visible(f, given)
                placed.append((f, view))
        if placed:
            groups, advanced = _grouped(placed)
            out["form"] = {"groups": groups, "advanced": advanced,
                           "open": any(v.get("error") for f, v in placed if f.advanced),
                           "general": _placed([f.path for f in fields], state.errors), "stash": state.stash,
                           "preview": s.preview is not None}
        if pg.yaml and s.yaml:
            text = state.yaml_text
            if text is None and isinstance(current, BaseModel):
                text = yaml.safe_dump(_without_secrets(s.model, current), allow_unicode=True, sort_keys=False,
                                      width=100)
            out["yaml"] = {"text": text or ""}
        return out

    @staticmethod
    def _command_forms(s: SettingsSection, blocks: Sequence[Mapping[str, Any]], csrf: str,
                       page: str) -> dict[str, Any]:
        """Les boutons qu'une section pose dans ses blocs (``ActionSlot("<section>.<clé>")``, même dans le
        détail d'une ligne) : une commande qui porte une valeur (``Command.argument``), envoyée à cette page
        comme les autres commandes, avec sa confirmation."""
        commands = {f"{s.key}.{c.key}": c for c in s.commands if c.argument}
        out: dict[str, Any] = {}
        if not commands:
            return out

        def walk(items: Sequence[Mapping[str, Any]]) -> None:
            for b in items:
                if b["t"] == "action" and b["key"] in commands:
                    c = commands[b["key"]]
                    title = b["title"] or c.title
                    out[b["slot"]] = {
                        "url": page_url(page), "csrf": csrf, "nonce": "", "back": "", "title": title,
                        "button": title, "description": "", "fields": [], "retype": False, "subject": "",
                        "confirm": c.confirm, "danger": c.danger, "errors": {}, "id": f"c-{s.key}-{len(out)}",
                        "fixed": [(SECTION, s.key), (COMMAND, c.key),
                                  (c.argument, str(b["initial"].get(c.argument, "")))]}
                elif b["t"] in ("grid", "section", "disclosure", "workspace", "toolbar"):
                    walk([*b.get("sidebar", []), *b["items"]])
                elif b["t"] == "table":
                    walk([x for r in b["rows"] for x in r["detail"]])

        walk(blocks)
        return out

    def _records_view(self, s: SettingsSection, f: forms.FormField, current: Any, page: str,
                      query: Mapping[str, str]) -> dict[str, Any]:
        found = forms.record_model(s.model, f.path)
        keyed = found[1] if found else True
        entries = getattr(current, f.path, None) or ({} if keyed else ())
        items = list(entries.items()) if keyed else [(str(i), e) for i, e in enumerate(entries)]
        shown = [i for i in f.item if not i.secret and not i.advanced
                 and i.kind in ("select", "text", "int", "bool")][:RECORD_COLUMNS]
        secrets_ = [i for i in f.item if i.secret and not i.advanced]
        try:
            number = max(1, int(query.get("page", "1") or 1))
        except ValueError:
            number = 1
        pages = max(1, math.ceil(len(items) / RECORDS_PAGE))
        number = min(number, pages)
        window = items[(number - 1) * RECORDS_PAGE:number * RECORDS_PAGE]
        section_flat = forms.flatten(current) if isinstance(current, BaseModel) else {}
        rows = []
        for key, entry in window:
            flat = forms.flatten(entry) if isinstance(entry, BaseModel) else {}
            # un champ qui ne sert pas à cette entrée (la connexion d'un abonnement, pour un Ollama) ne s'affiche
            # pas plus dans la liste que sur sa page
            cells = [_shown(i, flat.get(i.path)) if forms.visible(i, flat) else "—" for i in shown]
            cells += [("défini" if flat.get(i.path) else "—") if forms.visible(i, flat) else "—" for i in secrets_]
            # retirer annonce ce qui le désignait (ces rôles retomberont sur leur repli)
            refs = [label for _p, label in forms.references(s.model, section_flat, f.path, key)] if keyed else []
            confirm = f"Retirer « {key} » ?" + (f" Ce qui le désigne ne le pourra plus : {', '.join(refs)}."
                                                 if refs else "")
            rows.append({"key": key, "cells": cells, "edit": page_url(page, enregistrement=f.path, cle=key),
                         "confirm": confirm[:600]})
        return {"path": f.path, "label": f.label, "help": f.help, "keyed": keyed,
                "columns": [i.label for i in shown] + [i.label for i in secrets_], "rows": rows,
                "total": len(items),
                "pager": render._pager(Pager(number=number, size=RECORDS_PAGE, total=len(items)), query),
                "add": page_url(page, enregistrement=f.path, cle="", nouveau="1")}

    def _record_view(self, s: SettingsSection, current: Any, editing: tuple[str, str], state: State,
                     loaded: Mapping[str, list[tuple[str, str]]], page: str) -> dict[str, Any] | None:
        path, key = editing
        found = forms.record_model(s.model, path)
        if found is None:
            return None
        model, keyed = found
        fields = forms.describe(model)
        entry = _entry(current, path, key, keyed)
        flat = forms.flatten(entry) if entry is not None else _defaults(fields)
        given = {**flat, **state.record_values}
        siblings = forms.flatten(current) if isinstance(current, BaseModel) else {}
        prefix = f"r-{s.key}-{path}"
        placed = []
        for f in fields:
            if f.kind in ("group", "records", "mapping"):
                continue
            if f.choices_from:
                # un choix parmi les autres entrées d'un champ de la section (le repli d'un fournisseur)
                source = siblings.get(f.choices_from)
                others = [(str(k), str(k)) for k in sorted(source) if str(k) != key] if isinstance(source, Mapping) \
                    else []
                f = _with_choices(f, others, given.get(f.path))
            qualified = f"{path}.{f.path}"
            if qualified in s.choices:
                # des choix connus au rendu pour un champ d'enregistrement (le projet d'un réveil) : un sélecteur ;
                # la section les vérifie à l'enregistrement
                f = _with_choices(f, s.choices[qualified](), given.get(f.path))
            view = _view(f, given.get(f.path), _error_for(f.path, state.record_errors), prefix, loaded.get(f.path))
            if view is not None:
                view["load_button"] = view.get("loader", False)
                view["load_label"] = "Charger la liste"
                # charger n'enregistre rien : un champ vide qu'on vient remplir ne doit pas bloquer l'envoi
                # (le navigateur refuse un « required » vide)
                view["load_novalidate"] = True
                if f.secret and f.path in state.stashed:
                    view["has_value"] = True  # tapé, gardé côté serveur : vide = le garder
                # ce qui ne sert pas au type choisi n'apparaît pas (le script suit les changements)
                view["hidden"] = bool(f.only or f.only_any) and not forms.visible(f, given)
                placed.append((f, view))
        groups, advanced = _grouped(placed)
        label = next((f.label for f in forms.describe(s.model) if f.path == path), path)
        name = state.record_values.get(RECORD_KEY, key)
        return {"path": path, "label": label, "key": key, "keyed": keyed, "new": entry is None, "stash": state.stash,
                "name": name, "name_error": state.record_errors.get(RECORD_KEY, ""), "groups": groups,
                "advanced": advanced, "open": any(v.get("error") for f, v in placed if f.advanced),
                "general": _placed([f.path for f in fields] + [RECORD_KEY], state.record_errors),
                "back": state.back, "cancel": state.back or page_url(page)}

    def _loader_paths(self, s: SettingsSection, path: str) -> list[str]:
        found = forms.record_model(s.model, path) if s.model is not None else None
        if found is None:
            return []
        return [f.path for f in forms.describe(found[0]) if f.loader and not f.choices and f.loader in s.loaders]

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
            return list(await loader(forms.flatten(entry)))[:LOADED_MAX]
        except ValueError as exc:
            return f"Liste indisponible : {exc} — le champ reste modifiable à la main."[:300]

    # ── enregistrer ──
    async def post(self, ui: Any, request: Request, page: str) -> tuple[Response | None, dict[str, State], int]:
        """Une soumission : une réponse (redirection) si elle a abouti, sinon les états
        à remontrer et le statut."""
        got = await ui.form_lists(request)
        account = ui.operator(request)
        if got is None or account is None:
            return None, {"": State(messages=[("danger", BAD_TOKEN)])}, 403
        data, lists = got
        found = self.pages.get(page)
        s = self.sections.get(data.get(SECTION, ""))
        if found is None or s is None or found[0].key != s.key:
            return None, {"": State(messages=[("danger", "Section inconnue.")])}, 400
        pg = found[1]
        by = account.handle
        if data.get(COMMAND):
            return await self._command(ui, s, data[COMMAND], by, page, data)
        if s.model is None or s.save is None:
            return None, {s.key: State(messages=[("danger", "Rien à enregistrer ici.")])}, 400
        current = s.load()
        if data.get(DELETE):
            return await self._delete(ui, s, current, data[DELETE], data.get(RECORD_KEY, ""), by, page)
        if data.get(RECORD):
            return await self._save_record(ui, s, current, data, lists, by, page)
        if data.get(YAML) and s.yaml:
            return await self._save_yaml(ui, s, data.get(YAML_TEXT, ""), by, page)
        if not pg.form:
            return None, {s.key: State(messages=[("danger", "Rien à enregistrer sur cette page.")])}, 400
        fields = self._fields(s, pg)
        flat = forms.flatten(current)
        token = data.get(STASH, "")
        now = ui.now()
        lists = _with_kept(fields, lists, self._stash_get(token, now))
        values, errors = forms.parse(fields, lists, current=flat, load=_yaml_load)
        errors = {**errors, **forms.within(fields, values)}
        new = None
        if not errors:
            new, errors = forms.validate(s.model, current, values)
        if new is not None and not errors:
            errors = _choice_errors(s, current, new)
        if errors or new is None:
            return None, {s.key: self._hold(State(values=values, errors=errors, messages=[
                ("danger", "Rien n'a été enregistré : corrige les champs signalés.")]), fields, token, now)}, 400
        if data.get(PREVIEW) and s.preview is not None:
            return None, {s.key: self._hold(State(values=values, preview=list(s.preview(ui, new))), fields, token,
                                            now)}, 200
        if new == current:
            self._stash.pop(token, None)
            return self._done(ui, page, "info", "Rien n'a changé."), {}, 303
        response, states, status = await self._commit(ui, s, new, by, page, s.key, State(values=values),
                                                      f"{pg.title} : enregistré." if s.pages else "")
        if response is None:
            self._hold(states[s.key], fields, token, now)
        else:
            self._stash.pop(token, None)
        return response, states, status

    async def _commit(self, ui: Any, s: SettingsSection, new: Any, by: str, page: str, subject: str,
                      state: State, message: str = "", back: str = "") -> tuple[Response | None, dict[str, State], int]:
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
        return self._done(ui, page, "ok", message or f"{s.label} : enregistré.", back), {}, 303

    async def _save_record(self, ui: Any, s: SettingsSection, current: Any, data: Mapping[str, str],
                           lists: Mapping[str, list[str]], by: str,
                           page: str) -> tuple[Response | None, dict[str, State], int]:
        path, old = data.get(RECORD, ""), data.get(RECORD_OLD, "")
        found = forms.record_model(s.model, path)
        if found is None:
            return None, {s.key: State(messages=[("danger", "Liste inconnue.")])}, 400
        model, keyed = found
        fields = forms.describe(model)
        entry = _entry(current, path, old, keyed)
        flat = forms.flatten(entry) if entry is not None else _defaults(fields)
        token = data.get(STASH, "")
        now = ui.now()
        lists = _with_kept(fields, lists, self._stash_get(token, now))
        values, errors = forms.parse(fields, lists, current=flat, load=_yaml_load)
        wanted = data.get(LOAD, "")
        if wanted:
            # charger une liste (les modèles d'un fournisseur) n'enregistre rien, entrée neuve ou non : le
            # fournisseur n'est interrogé que sur ce bouton, avec ce qui vient d'être tapé
            return await self._load_new(s, path, old, data, fields, flat, values, errors, wanted, now)
        errors = {**errors, **forms.within(fields, values)}
        name = data.get(RECORD_KEY, old).strip()[:60] if keyed else old
        collection = getattr(current, path)
        renamed = keyed and entry is not None and name != old
        if keyed and not name:
            errors[RECORD_KEY] = "Donne un nom."
        elif keyed and name != old and name in collection:
            errors[RECORD_KEY] = "Ce nom existe déjà."
        elif renamed and path in s.fixed_names:
            errors[RECORD_KEY] = (f"Le nom « {old} » ne change pas : des données rangées ailleurs le portent. "
                                  "Ajoute une entrée sous le nouveau nom, puis retire l'ancienne.")
        record = None
        if not errors:
            record, errors = _record_from(model, entry, flat, values)
        state = State(record=(path, old), record_values={**values, RECORD_KEY: name}, record_errors=errors,
                      back=back_to(data.get(BACK, "")))
        if errors or record is None:
            state.messages = [("danger", "Rien n'a été enregistré : corrige les champs signalés.")]
            return None, {s.key: self._hold(state, fields, token, now)}, 400
        section_flat = forms.flatten(current)
        plain = section_flat[path]
        if keyed:
            updated = {k: v for k, v in dict(plain).items() if k != old}
            updated[name] = record.model_dump(mode="python")
        else:
            updated = list(plain)
            if old.isdigit() and int(old) < len(updated):
                updated[int(old)] = record.model_dump(mode="python")
            else:
                updated.append(record.model_dump(mode="python"))
        changes: dict[str, Any] = {path: updated}
        followed: list[str] = []
        if renamed:
            # renommer emporte ce qui le désignait (les rôles, le repli d'un autre fournisseur) : rien ne
            # retombe en silence sur un repli parce qu'un nom a changé
            more, followed = forms.rename_references(s.model, {**section_flat, path: updated}, path, old, name)
            changes.update(more)
        new, errors = forms.validate(s.model, current, changes)
        if new is not None and keyed and name != old and not forms.RECORD_NAME.fullmatch(name):
            # la règle commune des noms, après celle du modèle (qui dit mieux ce qu'il attend, s'il en a une)
            new, errors = None, {RECORD_KEY: f"Nom refusé : {forms.RECORD_NAME_RULE}."}
        if new is None:
            state.record_errors = errors
            state.messages = [("danger", " ; ".join(errors.values()) or "Refusé.")]
            return None, {s.key: self._hold(state, fields, token, now)}, 400
        subject = f"{s.key}/{path}/{name}"
        message = f"« {name} » enregistré." if keyed else "Enregistré."
        if renamed:
            message = f"« {old} » s'appelle désormais « {name} »" + (
                f" ; ce qui le désignait suit : {', '.join(followed)}." if followed else
                " ; rien d'autre ne le désignait.")
        response, states, status = await self._commit(ui, s, new, by, page, subject, state, message,
                                                      back_to(data.get(BACK, "")))
        if response is None:
            self._hold(states[s.key], fields, token, now)
        else:
            self._stash.pop(token, None)
        return response, states, status

    async def _load_new(self, s: SettingsSection, path: str, old: str, data: Mapping[str, str],
                        fields: Sequence[forms.FormField], flat: Mapping[str, Any], values: dict[str, Any],
                        errors: Mapping[str, str], wanted: str, now: int
                        ) -> tuple[Response | None, dict[str, State], int]:
        """Une entrée neuve : charger une liste (les modèles du fournisseur) avec ce qui vient d'être tapé,
        sans rien enregistrer. Les secrets tapés sont gardés côté serveur sous un jeton ; la page revient
        avec le sélecteur rempli et les autres valeurs telles qu'on les a tapées."""
        name = data.get(RECORD_KEY, old).strip()[:60]
        spec = next((f for f in fields if f.path == wanted), None)
        loader = s.loaders.get(spec.loader) if spec is not None else None
        secrets_ = {f.path: str(values[f.path]) for f in fields if f.secret and values.get(f.path)}
        token = self._stash_put(secrets_, now) if secrets_ else ""
        shown = {k: v for k, v in values.items() if k not in secrets_}
        state = State(record=(path, old), record_values={**shown, RECORD_KEY: name},
                      record_errors={k: v for k, v in errors.items() if k != wanted}, back=back_to(data.get(BACK, "")),
                      stash=token, stashed=tuple(secrets_))
        if loader is None:
            state.messages = [("warn", "Rien à charger ici.")]
            return None, {s.key: state}, 200
        try:
            got = list(await loader({**flat, **values, wanted: values.get(wanted) or ""}))[:LOADED_MAX]
        except ValueError as exc:
            state.messages = [("warn", f"Liste indisponible : {exc} — le champ reste modifiable à la main.")]
            return None, {s.key: state}, 200
        state.loaded = {wanted: got}
        state.messages = [("info", f"{len(got)} choix chargés : choisis, puis enregistre. Rien n'est encore "
                                   "enregistré.")]
        return None, {s.key: state}, 200

    def _stash_put(self, secrets_: Mapping[str, str], now: int) -> str:
        self._stash = {k: v for k, v in self._stash.items() if v[0] > now}
        while len(self._stash) >= STASH_MAX:
            self._stash.pop(next(iter(self._stash)))
        token = _secrets.token_urlsafe(18)
        self._stash[token] = (now + STASH_TTL_S * US, dict(secrets_))
        return token

    def _stash_get(self, token: str, now: int) -> dict[str, str]:
        got = self._stash.get(token) if token else None
        if got is None or got[0] <= now:
            return {}
        return dict(got[1])

    def _hold(self, state: State, fields: Sequence[forms.FormField], token: str, now: int) -> State:
        """Un envoi refusé : les secrets tapés passent dans la réserve, sous un nouveau jeton, et sortent des
        valeurs remontrées (un secret ne redescend jamais dans la page). Renvoyer le formulaire corrigé, le
        secret laissé vide, reprend celui tapé — sans quoi « vide : inchangé » garderait l'ancien."""
        values = state.values if state.record is None else state.record_values
        typed = {f.path: str(values[f.path]) for f in fields if f.secret and values.get(f.path)}
        self._stash.pop(token, None)
        for path in typed:
            del values[path]
        state.stash = self._stash_put(typed, now) if typed else ""
        state.stashed = tuple(typed)
        return state

    async def _delete(self, ui: Any, s: SettingsSection, current: Any, path: str, key: str, by: str,
                      page: str) -> tuple[Response | None, dict[str, State], int]:
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
        refs = [label for _p, label in forms.references(s.model, forms.flatten(current), path, key)] \
            if found[1] else []
        return await self._commit(ui, s, new, by, page, f"{s.key}/{path}/{key}", State(),
                                  f"« {key} » retiré." + (f" Ne le désignent plus : {', '.join(refs)}." if refs else ""))

    async def _save_yaml(self, ui: Any, s: SettingsSection, text: str, by: str,
                         page: str) -> tuple[Response | None, dict[str, State], int]:
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
        # un import passe par les mêmes choix que le formulaire (un fuseau inventé aurait mis toute la console
        # et la conversation en panne)
        refused = _choice_errors(s, s.load(), new)
        if refused:
            labels = {f.path: f.label for f in forms.describe(s.model)}
            state.messages = [("danger", f"{labels.get(p, p)} : {m}") for p, m in refused.items()]
            return None, {s.key: state}, 400
        return await self._commit(ui, s, new, by, page, s.key, state, f"{s.label} : importée.")

    async def _command(self, ui: Any, s: SettingsSection, key: str, by: str, page: str,
                       data: Mapping[str, str]) -> tuple[Response | None, dict[str, State], int]:
        command = next((c for c in s.commands if c.key == key), None)
        if command is None:
            return None, {s.key: State(messages=[("danger", "Commande inconnue.")])}, 400
        value = str(data.get(command.argument, "") or "").strip()[:200] if command.argument else ""
        if command.argument and not value:
            return None, {s.key: State(messages=[("danger", "Commande incomplète : recharge la page.")])}, 400
        try:
            tone, message = await (command.run(by, value) if command.argument else command.run(by))
        except ValueError as exc:
            return None, {s.key: State(messages=[("danger", str(exc))])}, 400
        await operations.audit(ui.kernel, f"console.reglages.{s.key}.{command.key}", by=by,
                               subject_kind="reglage", subject=f"{s.key}/{value}" if value else s.key)
        return self._done(ui, page, tone, message), {}, 303

    def _done(self, ui: Any, page: str, tone: str, message: str, back: str = "") -> Response:
        token = _secrets.token_urlsafe(9)
        ui.flash(token, tone, message)
        if back:  # revenir d'où l'on venait (une page de la console : le courrier, ses comptes)
            sep = "&" if "?" in back else "?"
            return secure(RedirectResponse(f"{back}{sep}flash={token}", status_code=303))
        return secure(RedirectResponse(page_url(page, flash=token), status_code=303))


def _choice_errors(s: SettingsSection, current: Any, new: BaseModel) -> dict[str, str]:
    """Les champs dont la section connaît les choix (``SettingsSection.choices`` : les fuseaux) : une
    valeur hors de la liste est refusée — sauf celle déjà en place (elle reste proposée au rendu)."""
    if not s.choices:
        return {}
    before = forms.flatten(current) if isinstance(current, BaseModel) else {}
    after = forms.flatten(new)
    errors: dict[str, str] = {}
    for path, choices in s.choices.items():
        value = after.get(path)
        if value in (None, "") or value == before.get(path):
            continue
        if str(value) not in {v for v, _ in choices()}:
            errors[path] = f"choix inconnu : « {str(value)[:80]} »"
    return errors


def back_to(target: str) -> str:
    """Un retour dans la console seulement (jamais une autre adresse) ; vide sinon."""
    target = target.strip()
    if target.startswith(PREFIX + "/") and "//" not in target and "\\" not in target and len(target) < 2000 \
            and all(ord(ch) >= 32 for ch in target):
        return target
    return ""


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
    if f.kind == "bool":
        return "oui" if value else "non"
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
