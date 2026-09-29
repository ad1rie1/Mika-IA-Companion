"""Réglages : les paramètres internes des facultés, le journal de
configuration, et la page encore à part des comptes. (Les réglages d'une app
forgée vivent sur sa fiche.)

Les autres onglets (modèles, personnalité, canaux, sens) sont des sections
déclarées par la composition et rendues par ``settings_form.py``.

Paramètres internes : tout se lit (valeur, provenance, bornes, sens, ce que
chaque curseur pilote) ; une surcharge se pose seulement dans le bloc
« avancé » replié d'une faculté, bornée, et journalisée avec l'opérateur.
"""

from __future__ import annotations

import json
import secrets as _secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.contracts import runtime as rt
from mika.inspector.catalog import Panel
from mika.inspector.formview import field_view
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel import forms
from mika.kernel.builtin import PARAMS_CHANGED
from mika.kernel.inspect import Badge, Column, Note, Pager, Ref, Row, Table, Text, When
from mika.runtime import operations

PARAMS_URL = f"{PREFIX}/reglages/parametres"
TONES = {"défaut": "muted", "tempérament": "info", "réglage": "ok", "surcharge": "warn"}
LEGACY = (("reglages.comptes", "Comptes", "/inspecteur/reglages/comptes"),)


def _register(key: str, title: str, href: str) -> None:
    async def page(ui: Any, request: Request) -> Any:
        return None

    TABS.tab(key, title=title, href=href)(page)


for _key, _title, _href in LEGACY:
    _register(_key, _title, _href)


def _faculty_url(owner: str, **more: str) -> str:
    return f"{PARAMS_URL}?{urlencode({'faculte': owner, **more})}"


def _value(f: forms.FormField, value: Any) -> str:
    if value is None:
        return "—"
    if f.kind == "bool":
        return "oui" if value else "non"
    if f.kind == "lines":
        return ", ".join(str(v) for v in value) or "—"
    if f.kind in ("yaml", "records", "mapping"):
        return json.dumps(forms.plain(value), ensure_ascii=False, default=str)
    text = f"{value:.4g}".replace(".", ",") if f.kind in ("float", "slider") and isinstance(value, float) \
        else forms.as_text(f, value)
    label = next((lbl for v, lbl in f.choices if v == text), "")
    unit = f" {f.unit}" if f.unit and f.kind in ("int", "float", "slider") else ""
    return (f"{label} ({text})" if label and label != text else text) + unit


def _bounds(f: forms.FormField) -> str:
    if f.lo is None and f.hi is None:
        return "—"

    def show(x: float) -> str:
        if f.kind == "duration":
            return forms.show_duration(round(x * forms.UNIT_US[f.unit]))
        return f"{x:g}".replace(".", ",")

    return f"{show(f.lo) if f.lo is not None else '…'} – {show(f.hi) if f.hi is not None else '…'}"


@TABS.tab("reglages.parametres", title="Paramètres internes")
async def parametres(ui: Any, request: Request, state: Mapping[str, Any] | None = None) -> Any:
    ps = ui.deps.parameters
    if ps is None:
        return [Note("Les paramètres internes ne sont pas disponibles ici.", "muted")]
    owner = request.query_params.get("faculte", "") or (state or {}).get("owner", "")
    if owner and ps.plan(owner) is not None:
        return _faculty(ui, request, ps, owner, state or {})
    return _overview(ps)


def _overview(ps: Any) -> list[Any]:
    overrides = ps.overrides()
    rows = []
    for fac in ps.faculties():
        p = ps.plan(fac.name)
        if p is None:
            continue
        counts = {s: sum(1 for v in p.sources.values() if v == s) for s in TONES}
        journaled = ps.journaled(fac.name) is not None
        rows.append(Row((
            Ref("local", _faculty_url(fac.name), fac.name),
            Text(str(len(p.sources)), "num"),
            Badge("oui", "info") if fac.derive is not None else Text("non", "muted"),
            Badge(str(len(overrides.get(fac.name) or {})), "warn") if overrides.get(fac.name) else Text("—", "muted"),
            Badge(str(counts["réglage"]), "ok") if counts["réglage"] else Text("—", "muted"),
            Badge(f"{len(p.refused)} refusée(s)", "danger") if p.refused else Text("—", "muted"),
            Badge("journalisés", "ok") if journaled else Text("défauts", "muted")),
            href=Ref("local", _faculty_url(fac.name), "")))
    labels = ps.slider_labels()
    drive = []
    for slider, moved in ps.influences().items():
        text = " · ".join(f"{owner} › {path} ({_num(lo)} → {_num(hi)})" for owner, path, lo, hi in moved)
        drive.append((Text(labels.get(slider, slider)), Text(text or "rien encore (non branché)",
                                                            "muted" if not moved else "text", clamp=400)))
    return [
        Note("Tout se lit ici. Le tempérament (Personnalité) est l'entrée principale ; une surcharge se pose "
             "dans le bloc « avancé » d'une faculté, bornée et journalisée.", "info"),
        Table((Column("faculté"), Column("paramètres", "num"), "dérive du tempérament", "surcharges",
               "réglages", "refus", "en vigueur"), tuple(rows), title="Les facultés",
              empty="Aucune faculté n'a de paramètres."),
        Table((Column("curseur", "fit"), "ce qu'il pilote (à 0 → à 1)"), tuple(drive),
              title="Ce que pilote chaque curseur du tempérament"),
    ]


def _num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3g}".replace(".", ",")
    return str(value)


def _faculty(ui: Any, request: Request, ps: Any, owner: str, state: Mapping[str, Any]) -> dict[str, Any]:
    p = ps.plan(owner)
    fields = [f for f in ps.fields(owner) if f.kind != "group"]
    flat, natural = forms.flatten(p.value), forms.flatten(p.natural)
    journaled = ps.journaled(owner)
    live = forms.flatten(journaled) if journaled is not None else None
    moved_by: dict[str, list[str]] = {}
    labels = ps.slider_labels()
    for slider, moved in ps.influence(owner).items():
        for path, _lo, _hi in moved:
            moved_by.setdefault(path, []).append(labels.get(slider, slider))
    rows = []
    for f in fields:
        source = p.sources.get(f.path, "défaut")
        detail = [Note(f"Sans surcharge : {_value(f, natural.get(f.path))}.", "muted")] if source == "surcharge" \
            else []
        if live is not None and live.get(f.path) != flat.get(f.path):
            detail.append(Note(f"En vigueur dans le journal : {_value(f, live.get(f.path))} (le plan n'est pas "
                               "encore journalisé).", "warn"))
        rows.append(Row((
            Text(f.label), Text(f.path, "mono"), Text(_value(f, flat.get(f.path)), clamp=200),
            Badge(source, TONES.get(source, "")), Text(", ".join(moved_by.get(f.path, ())) or "—", "muted"),
            Text(_bounds(f), "muted"), Text(f.help or "—", "muted", clamp=160)), detail=tuple(detail)))
    blocks: list[Any] = []
    if p.refused:
        blocks.append(Note("Des surcharges enregistrées sont refusées et ignorées : " + "; ".join(
            f"{k} ({v})" for k, v in p.refused.items()), "danger"))
    blocks.append(Table((Column("paramètre"), Column("chemin", "fit"), "valeur", "provenance", "piloté par",
                         "bornes", "sens"), tuple(rows), title=f"Paramètres de {owner}"))
    errors: Mapping[str, str] = state.get("errors") or {}
    typed: Mapping[str, Any] = state.get("values") or {}
    given = {**flat, **typed}
    editable = []
    for f in fields:
        if f.kind in ("records", "mapping"):
            continue
        view = field_view(f, given.get(f.path), error=_err(f.path, errors), prefix=f"p-{owner}")
        if view is not None:
            if f.kind == "duration":
                view["placeholder"] = "ex. 10 min, 1 h 30"
            view["source"] = p.sources.get(f.path, "")
            editable.append(view)
    overrides = ps.overrides().get(owner) or {}
    panel = Panel("params_form.html", {
        "owner": owner, "fields": editable, "open": bool(errors), "panel_messages": state.get("messages") or [],
        "action": PARAMS_URL, "overridden": sorted(overrides), "panel_after": True,
        "general": [m for k, m in errors.items() if not any(k == f.path or k.startswith(f.path + ".")
                                                            for f in fields)]})
    return {"blocks": blocks, "panel": panel, "crumbs": [("Paramètres internes", PARAMS_URL), (owner, "")]}


def _err(path: str, errors: Mapping[str, str]) -> str:
    return " ; ".join(m for k, m in errors.items() if k == path or k.startswith(path + "."))


async def parametres_post(ui: Any, request: Request) -> tuple[Response | None, dict[str, Any], int]:
    ps = ui.deps.parameters
    got = await ui.form_lists(request)
    account = ui.operator(request)
    if ps is None or got is None or account is None:
        return None, {"messages": [("danger", "Jeton de formulaire invalide : recharge la page.")]}, 403
    data, lists = got
    owner = data.get("_faculte", "")
    if ps.plan(owner) is None:
        return None, {"messages": [("danger", "Faculté inconnue.")]}, 400
    try:
        if data.get("_reinitialiser"):
            changed = await ps.reset(owner, data.get("_chemin", ""))
            errors: dict[str, str] = {}
        else:
            changed, errors = await ps.change(owner, lists)
    except ValueError as exc:
        return None, {"owner": owner, "messages": [("danger", f"Refusé : {exc}")]}, 400
    if errors:
        values, _ = forms.parse(ps.fields(owner), lists, current={})
        return None, {"owner": owner, "errors": errors, "values": values,
                      "messages": [("danger", "Rien n'a été enregistré : corrige les champs signalés.")]}, 400
    if changed:
        await operations.audit(ui.kernel, f"console.parametres.{owner}", by=account.handle,
                               subject_kind="faculté", subject=owner)
    token = _secrets.token_urlsafe(9)
    ui.flash(token, "ok" if changed else "info",
             f"Paramètres de {owner} : surcharges enregistrées et journalisées." if changed else "Rien n'a changé.")
    return secure(RedirectResponse(_faculty_url(owner, flash=token), status_code=303)), {}, 303


@TABS.tab("reglages.journal", title="Journal de configuration")
async def journal(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    before = ctx.int_param("avant", 0) or None
    ops = [e for e in ctx.events([rt.OPERATED], 300, before=before)
           if e.data.action.startswith("console.") and e.data.outcome == "done"]
    params = ctx.events([PARAMS_CHANGED], 100, before=before)
    merged = sorted([*ops, *params], key=lambda e: -e.seq)[:100]
    rows = []
    for e in merged:
        if e.type.name == PARAMS_CHANGED.name:
            rows.append(Row((When(e.at), Badge("paramètres", "info"),
                             Ref("local", _faculty_url(e.data.owner), e.data.owner), "—",
                             Text(e.correlation or "—", "muted")), href=Ref("event", str(e.seq), "")))
        else:
            what = e.data.action.removeprefix("console.")
            rows.append(Row((When(e.at), Badge("opérateur", "ok"), Text(what, "mono"), e.data.by,
                             Text(e.data.subject or "—", "muted")), href=Ref("event", str(e.seq), "")))
    pager = Pager(older=(("avant", str(merged[-1].seq)),)) if len(merged) == 100 else None
    return [Note("Chaque réglage enregistré depuis la console, et chaque journalisation de paramètres (au "
                 "démarrage, après un changement de persona, de tempérament ou de surcharge).", "muted"),
            Table((Column("quand", "fit"), "sorte", "quoi", "par", "sur / origine"), tuple(rows),
                  title="Journal de configuration", empty="Rien encore.", pager=pager)]
