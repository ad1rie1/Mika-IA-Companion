"""Configuration › Comportement : les paramètres internes des facultés, une page
par faculté, un groupe à la fois ; et Configuration › Historique, le journal des
modifications. (Les réglages d'une app forgée vivent sur sa fiche ; les comptes,
dans ``accounts.py``.)

Tout se lit : chaque paramètre dit ce qu'il fait, sa valeur, d'où elle vient
(défaut ← tempérament ← réglage ← surcharge), ses bornes et ce qui le pilote.
Changer une valeur pose une surcharge, bornée et journalisée avec l'opérateur ;
une valeur égale à celle du tempérament la retire. Le rangement des facultés en
familles et leur nom lisible viennent de la composition (``app/console.py``) :
la console n'en nomme aucune.
"""

from __future__ import annotations

import json
import re
import secrets as _secrets
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.contracts import runtime as rt
from mika.inspector.catalog import Builtin, Panel
from mika.inspector.formview import field_view
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel import forms
from mika.kernel.builtin import PARAMS_CHANGED
from mika.kernel.inspect import (
    Badge,
    Column,
    Nav,
    NavItem,
    Note,
    Pager,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
)
from mika.runtime import operations
from mika.runtime.params import shown as params_shown

FACULTY_PAGE = "comportement-"
OVERVIEW_URL = f"{PREFIX}/reglages/comportement"
#: l'ancienne adresse (``?faculte=``) redirige vers la page de la faculté
PARAMS_URL = OVERVIEW_URL
TONES = {"défaut": "muted", "tempérament": "info", "réglage": "ok", "surcharge": "warn"}
SOURCES_FR = {"défaut": "valeur par défaut", "tempérament": "dérivée du tempérament",
              "réglage": "réglée ailleurs (canaux, courrier…)", "surcharge": "surchargée par un opérateur"}
#: au-delà, une faculté se lit un groupe à la fois
ONE_PAGE_MAX = 12
COMPORTEMENT_ORDER = 1000


def faculty_url(owner: str, **more: str) -> str:
    query = {k: v for k, v in more.items() if v}
    return f"{PREFIX}/reglages/{FACULTY_PAGE}{owner}" + (f"?{urlencode(query)}" if query else "")


def _slug(text: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "general"


def _value(f: forms.FormField, value: Any) -> str:
    if value is None:
        return "—"
    if f.kind == "bool":
        return "oui" if value else "non"
    if f.kind == "lines":
        return ", ".join(str(v) for v in value) or "—"
    if f.kind in ("yaml", "records", "mapping"):
        plain = forms.plain(value)
        if isinstance(plain, dict):
            return " · ".join(f"{k} : {v}" for k, v in plain.items()) or "—"
        if isinstance(plain, list | tuple):
            return ", ".join(str(v) for v in plain) or "—"
        return json.dumps(plain, ensure_ascii=False, default=str)
    text = f"{value:.4g}".replace(".", ",") if f.kind in ("float", "slider") and isinstance(value, float) \
        else forms.as_text(f, value)
    label = next((lbl for v, lbl in f.choices if v == text), "")
    unit = f" {f.unit}" if f.unit and f.kind in ("int", "float", "slider") else ""
    return (f"{label} ({text})" if label and label != text else text) + unit


def _bounds(f: forms.FormField) -> str:
    if f.lo is None and f.hi is None:
        return ""

    def show(x: float) -> str:
        if f.kind == "duration":
            return forms.show_duration(round(x * forms.UNIT_US[f.unit]))
        return f"{x:g}".replace(".", ",")

    return f"{show(f.lo) if f.lo is not None else '…'} – {show(f.hi) if f.hi is not None else '…'}"


def _num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3g}".replace(".", ",")
    return str(value)


def _label_of(ui: Any, owner: str) -> str:
    return dict(ui.deps.faculty_labels or {}).get(owner, owner)


def param_builtins(parameters: Any, families: Any, labels: Mapping[str, str]) -> dict[str, Builtin]:
    """Une page de Configuration › Comportement par faculté qui a des paramètres,
    rangée par famille (celle que la composition déclare, sinon « Autres »)."""
    if parameters is None:
        return {}
    family_of: dict[str, tuple[int, str]] = {}
    for i, (family, owners) in enumerate(families or ()):
        for j, owner in enumerate(owners):
            family_of[owner] = (i * 20 + j, family)
    out: dict[str, Builtin] = {}
    for n, fac in enumerate(parameters.faculties()):
        rank, family = family_of.get(fac.name, (300 + n, "Autres"))
        key = f"reglages.{FACULTY_PAGE}{fac.name}"
        label = labels.get(fac.name, fac.name)

        async def fn(ui: Any, request: Request, _owner: str = fac.name) -> Any:
            return await faculty_page(ui, request, _owner, {})

        out[key] = Builtin(key, label, fn, group=f"Comportement · {family}", order=COMPORTEMENT_ORDER + 1 + rank,
                           description=f"Les paramètres internes de « {label} » ({fac.name}) : ce que chacun fait, "
                                       "sa valeur, d'où elle vient. Changer une valeur pose une surcharge bornée et "
                                       "journalisée.")
    return out


@TABS.tab("reglages.comportement", title="Vue d'ensemble", group="Comportement", order=COMPORTEMENT_ORDER,
          description="Chaque faculté règle son comportement par des paramètres internes. Le tempérament "
                      "(Personnage › Tempérament) est l'entrée principale ; une surcharge se pose sur la page de la "
                      "faculté.")
async def comportement(ui: Any, request: Request) -> Any:
    owner = request.query_params.get("faculte", "")
    ps = ui.deps.parameters
    if owner and ps is not None and ps.plan(owner) is not None:
        return RedirectResponse(faculty_url(owner), status_code=301)
    return overview(ui)


def overview(ui: Any) -> list[Any]:
    ps = ui.deps.parameters
    if ps is None:
        return [Note("Les paramètres internes ne sont pas disponibles ici.", "muted")]
    overrides = ps.overrides()
    rows = []
    totals = {"params": 0, "surcharges": 0, "derive": 0, "refus": 0}
    for fac in ps.faculties():
        p = ps.plan(fac.name)
        if p is None:
            continue
        counts = {s: sum(1 for v in p.sources.values() if v == s) for s in TONES}
        journaled = ps.journaled(fac.name) is not None
        n_over = len(overrides.get(fac.name) or {})
        totals["params"] += len(p.sources)
        totals["surcharges"] += n_over
        totals["derive"] += fac.derive is not None
        totals["refus"] += len(p.refused)
        rows.append(Row((
            Ref("local", faculty_url(fac.name), _label_of(ui, fac.name)), Text(fac.name, "mono"),
            Text(str(len(p.sources)), "num"),
            Badge(f"{counts['tempérament']} dérivé(s)", "info") if fac.derive is not None else Text("non", "muted"),
            Badge(str(n_over), "warn") if n_over else Text("—", "muted"),
            Badge(str(counts["réglage"]), "ok") if counts["réglage"] else Text("—", "muted"),
            Badge(f"{len(p.refused)} refusée(s)", "danger") if p.refused else Text("—", "muted"),
            Badge("journalisés", "ok") if journaled else Text("défauts", "muted")),
            href=Ref("local", faculty_url(fac.name), "")))
    labels = ps.slider_labels()
    drive = []
    for slider, moved in ps.influences().items():
        text = " · ".join(f"{_label_of(ui, owner)} › {path} ({_num(lo)} → {_num(hi)})" for owner, path, lo, hi in moved)
        drive.append((Text(labels.get(slider, slider)), Text(text or "rien encore (non branché)",
                                                            "muted" if not moved else "text", clamp=400)))
    return [
        Stats((Stat("Paramètres", totals["params"], sub="dans toutes les facultés"),
               Stat("Facultés qui dérivent du tempérament", totals["derive"]),
               Stat("Surcharges posées", totals["surcharges"], tone="warn" if totals["surcharges"] else "",
                    sub="bornées et journalisées"),
               Stat("Surcharges refusées", totals["refus"], tone="danger" if totals["refus"] else "",
                    sub="ignorées : hors bornes ou devenues invalides"))),
        Note("D'où vient chaque valeur : le défaut de la faculté, puis ce que le tempérament en dérive, puis ce "
             "qu'un autre réglage fournit (les propriétaires Telegram, les boîtes où elle prépare des réponses), "
             "puis une surcharge d'opérateur. Ouvre une faculté pour lire et changer ses paramètres.", "info"),
        Table((Column("faculté"), Column("nom technique", "fit"), Column("paramètres", "num"),
               "dérive du tempérament", "surcharges", "réglés ailleurs", "refus", "en vigueur"), tuple(rows),
              title="Les facultés", empty="Aucune faculté n'a de paramètres."),
        Table((Column("curseur", "fit"), "ce qu'il pilote (à 0 → à 1)"), tuple(drive),
              title="Ce que pilote chaque curseur du tempérament"),
    ]


def _groups_of(fields: list[forms.FormField]) -> list[tuple[str, list[forms.FormField]]]:
    """Les groupes d'une faculté, dans l'ordre d'apparition (un groupe déclaré en deux
    morceaux est réuni)."""
    out: dict[str, list[forms.FormField]] = {}
    for f in fields:
        out.setdefault(f.group or "Général", []).append(f)
    return list(out.items())


async def faculty_page(ui: Any, request: Request, owner: str, state: Mapping[str, Any]) -> dict[str, Any]:
    ps = ui.deps.parameters
    p = ps.plan(owner) if ps is not None else None
    if p is None:
        return {"blocks": [Note("Faculté inconnue.", "warn")]}
    fields = [f for f in ps.fields(owner) if f.kind != "group"]
    flat, natural = forms.flatten(p.value), forms.flatten(p.natural)
    journaled = ps.journaled(owner)
    live = forms.flatten(journaled) if journaled is not None else None
    labels = ps.slider_labels()
    moved_by: dict[str, list[str]] = {}
    for slider, moved in ps.influence(owner).items():
        for path, _lo, _hi in moved:
            moved_by.setdefault(path, []).append(labels.get(slider, slider))
    groups = _groups_of(fields)
    one_page = len(fields) <= ONE_PAGE_MAX or len(groups) <= 1
    wanted = str(state.get("group") or request.query_params.get("groupe", "") or "")
    shown = groups if one_page else [next((g for g in groups if _slug(g[0]) == wanted), groups[0])]
    overrides = ps.overrides().get(owner) or {}
    counts = {s: sum(1 for v in p.sources.values() if v == s) for s in TONES}
    blocks: list[Any] = [Stats((
        Stat("Paramètres", len(fields)),
        Stat("Dérivés du tempérament", counts["tempérament"], tone="info" if counts["tempérament"] else ""),
        Stat("Surchargés", len(overrides), tone="warn" if overrides else ""),
        Stat("Réglés ailleurs", counts["réglage"], sub="en lecture seule ici"),
    ))]
    if p.refused:
        blocks.append(Note("Des surcharges enregistrées sont refusées et ignorées : " + "; ".join(
            f"{k} ({v})" for k, v in p.refused.items()), "danger"))
    if not one_page:
        current = _slug(shown[0][0])
        blocks.append(Nav(tuple(NavItem(title, Ref("local", faculty_url(owner, groupe=_slug(title)), title),
                                        count=len(fs), active=_slug(title) == current)
                                for title, fs in groups), title="Groupes"))
    errors: Mapping[str, str] = state.get("errors") or {}
    typed: Mapping[str, Any] = state.get("values") or {}
    given = {**flat, **typed}
    views = []
    for title, fs in shown:
        items = []
        for f in fs:
            source = p.sources.get(f.path, "défaut")
            meta = {"source": source, "source_label": SOURCES_FR.get(source, source), "tone": TONES.get(source, ""),
                    "drivers": ", ".join(moved_by.get(f.path, ())), "bounds": _bounds(f), "path": f.path,
                    "natural": _value(f, natural.get(f.path)) if source == "surcharge" else "",
                    "pending": _value(f, live.get(f.path)) if live is not None and live.get(f.path) != flat.get(
                        f.path) else "",
                    "overridden": any(k == f.path or k.startswith(f.path + ".") for k in overrides)}
            view = None
            if f.kind not in ("records", "mapping"):
                view = field_view(f, given.get(f.path), error=_err(f.path, errors), prefix=f"p-{owner}")
                raw = given.get(f.path)
                if view is not None and f.kind in ("float", "slider") and isinstance(raw, float) \
                        and f.path not in typed:
                    view["value"] = params_shown(raw)  # 6 chiffres : renvoyé sans y toucher, rien ne change
                if view is not None and f.kind == "duration":
                    view["placeholder"] = "ex. 10 min, 1 h 30"
            items.append({"field": view, "label": f.label, "help": f.help, "value": _value(f, flat.get(f.path)),
                          **meta})
        views.append({"title": title, "items": items})
    panel = Panel("params_form.html", {
        "owner": owner, "label": _label_of(ui, owner), "groups": views, "panel_messages": state.get("messages") or [],
        "action": faculty_url(owner), "group": _slug(shown[0][0]) if not one_page else "",
        "overridden": sorted(overrides), "panel_after": True,
        "general": [m for k, m in errors.items() if not any(k == f.path or k.startswith(f.path + ".")
                                                            for f in fields)]})
    return {"blocks": blocks, "panel": panel}


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
    group = data.get("_groupe", "")
    if ps.plan(owner) is None:
        return None, {"messages": [("danger", "Faculté inconnue.")]}, 400
    try:
        if data.get("_reinitialiser") or data.get("_reinitialiser_chemin"):
            changed = await ps.reset(owner, data.get("_reinitialiser_chemin", "") or data.get("_chemin", ""))
            errors: dict[str, str] = {}
        else:
            changed, errors = await ps.change(owner, lists)
    except ValueError as exc:
        return None, {"owner": owner, "group": group, "messages": [("danger", f"Refusé : {exc}")]}, 400
    if errors:
        values, _ = forms.parse(ps.fields(owner), lists, current={})
        return None, {"owner": owner, "group": group, "errors": errors, "values": values,
                      "messages": [("danger", "Rien n'a été enregistré : corrige les champs signalés.")]}, 400
    if changed:
        await operations.audit(ui.kernel, f"console.parametres.{owner}", by=account.handle,
                               subject_kind="faculté", subject=owner)
    token = _secrets.token_urlsafe(9)
    label = _label_of(ui, owner)
    ui.flash(token, "ok" if changed else "info",
             f"{label} : surcharges enregistrées et journalisées." if changed else "Rien n'a changé.")
    return secure(RedirectResponse(faculty_url(owner, groupe=group, flash=token), status_code=303)), {}, 303


@TABS.tab("reglages.journal", title="Journal des modifications", group="Historique", order=3000,
          description="Chaque réglage enregistré depuis la console (qui, quoi, sur quoi — jamais un contenu ni un "
                      "secret), et chaque journalisation des paramètres (au démarrage, après un changement de "
                      "persona, de tempérament ou de surcharge).")
async def journal(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    before = ctx.int_param("avant", 0) or None
    ops = [e for e in ctx.events([rt.OPERATED], 300, before=before)
           if e.data.action.startswith("console.") and e.data.outcome == "done"]
    params = ctx.events([PARAMS_CHANGED], 100, before=before)
    merged = sorted([*ops, *params], key=lambda e: -e.seq)[:50]
    rows = []
    for e in merged:
        if e.type.name == PARAMS_CHANGED.name:
            rows.append(Row((When(e.at), Badge("paramètres", "info"),
                             Ref("local", faculty_url(e.data.owner), _label_of(ui, e.data.owner)), "—",
                             Text(e.correlation or "—", "muted")), href=Ref("event", str(e.seq), "")))
        else:
            what = e.data.action.removeprefix("console.")
            rows.append(Row((When(e.at), Badge("opérateur", "ok"), Text(what, "mono"), e.data.by,
                             Text(e.data.subject or "—", "muted")), href=Ref("event", str(e.seq), "")))
    pager = Pager(older=(("avant", str(merged[-1].seq)),)) if len(merged) == 50 else None
    return [Table((Column("quand", "fit"), "sorte", "quoi", "par", "sur / origine"), tuple(rows),
                  title="Journal des modifications", empty="Rien encore.", pager=pager)]
