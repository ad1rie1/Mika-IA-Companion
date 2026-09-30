"""Ce que la Forge montre et permet à un opérateur, dans la console.

- **La fiche d'une app** (type d'objet ``app``, clé = son nom) : son en-tête
  (titre, version, état, agenda, dernier tour), et ses onglets — **État**,
  **Vues** (ses vues déclarées, rendues depuis le bac à sable), **Réglages**
  (ses réglages typés, les secrets jamais montrés), **Code**, **Journal**,
  **Vécu**. La recherche la trouve par son nom ou son titre.
- **Apps forgées** (la destination) : toutes ses apps, un lien vers chaque
  fiche ; le badge compte les apps cassées.
- **Les commandes** (``forge.*``) : recharger, activer, arrêter, promouvoir,
  rétrograder, revenir à la version précédente, vider le stockage, effacer
  (retaper le nom), tester une fonction ; et, en place dans une vue, **agir**
  (une action déclarée par l'app) et, dans ses réglages, **régler**.

Une vue d'app est une lecture : elle a 3 s et 256 Ko, n'est jamais journalisée
et n'est jamais comptée par le disjoncteur. Une action d'app est une décision
d'opérateur : ce qu'elle émet ou signale est journalisé avec l'origine
« extérieure » (par le moteur d'actions), jamais compté contre l'app non plus.
Seules les fonctions que le manifeste déclare peuvent être appelées.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Annotated, Any

from pydantic import BaseModel

from mika.contracts import forge as c
from mika.kernel.forms import FormField, Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Cell,
    Code,
    Column,
    Fields,
    Found,
    Head,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
)
from mika.kernel.operate import ActionContext, Done, Refused
from mika.plugins.forge import (
    EMITTED,
    FORGE,
    HANDLED,
    SWITCHED,
    TICKED,
    WRITTEN,
    App,
    ForgeState,
    NoArgs,
    _next_tick,
    outcomes,
    params,
    stale,
    written_draft,
)
from mika.plugins.forge.views import (
    ACTION_TIMEOUT_S,
    VIEW_MAX_BYTES,
    VIEW_TIMEOUT_S,
    decode_view,
    failure_note,
    find_view,
    fold,
    render,
    summary,
    view_params,
    without_forms,
)
from mika.ports.forge import AppInfo, AppUI, AppViewSpec, CallResult, ForgeRefused, form_field, ui_load

#: une page de ses apps, de ce qu'une app a vécu (au journal), des lignes de son journal
APPS_PAGE = 25
LIVED_PAGE = 25
LOGS_PAGE = 50
CODE_SHOWN = 20_000
#: l'ancienne page d'une app ne montre que ses dernières lignes (sa fiche les montre toutes, par pages)
LOGS_SHOWN = 50
#: le journal d'une app relu par la console : l'hôte n'en garde pas davantage
LOGS_READ = 500
MESSAGE_MAX = 500
APP_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL = re.compile(r"^https?://[^\s/?#@\\]+(?:[/?#][^\s\\]*)?$", re.IGNORECASE)
NOT_HERE = "La Forge n'est pas configurée ici."


# ── Petits outils ─────────────────────────────────────────────────────────


def _clip(text: str, n: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _latest(ctx: InspectContext, types: tuple[Any, ...], app: str, n: int) -> list[Any]:
    """Les ``n`` derniers événements de ces types pour cette app, du plus récent."""
    return ctx.events(types, n, where=("app", app))


def _fiche(name: str, text: str | None = None, tab: str = "") -> Ref | str:
    """Un lien vers la fiche d'une app (un nom invalide n'entre jamais dans un lien)."""
    if not APP_NAME.match(name):
        return text or name
    return Ref.subject("app", name, text or name, tab)


def _state(app: App | None, info: AppInfo | None, port: Any) -> tuple[str, str]:
    """(état en toutes lettres, ton)."""
    if app is None:
        text, tone = "sur le disque, pas encore dans sa vie", "muted"
    elif app.broken:
        text, tone = f"cassée : {_clip(app.broken, 200)}", "danger"
    elif not app.enabled:
        text, tone = "arrêtée", "muted"
    else:
        text, tone = "active", "ok"
    if port is not None and info is None:
        text += " (absente du disque)"
        tone = "warn"
    elif info is not None and info.error:
        text += f" ; manifeste : {_clip(info.error, 200)}"
        tone = "danger"
    return text, tone


def _status(app: App | None, info: AppInfo | None, port: Any) -> str:
    return _state(app, info, port)[0]


def _last_tick(name: str, ctx: InspectContext) -> str:
    last = _latest(ctx, (TICKED,), name, 1)
    if not last:
        return "jamais"
    e = last[0]
    return (f"ok, {ctx.when(e.at)}" if e.data.ok
            else f"échec, {ctx.when(e.at)} : {_clip(e.data.error or '?', 150)}")


def _shown(value: Any) -> str:
    if isinstance(value, bool):
        return "vrai" if value else "faux"
    if isinstance(value, list | tuple):
        return _clip(" · ".join(str(v) for v in value), 200) or "—"
    return _clip(str(value), 200)


def _ui(s: ForgeState, name: str) -> AppUI:
    app = s.apps.get(name)
    return ui_load(app.ui) if app is not None else AppUI()


def _subject(s: ForgeState, ctx: InspectContext) -> tuple[str, App | None, AppInfo | None, Any] | list[Block]:
    """L'app de la fiche, ou la note qui dit pourquoi il n'y en a pas."""
    name = ctx.subject
    if not name:
        return [Note("Cet onglet se lit sur la fiche d'une app : ouvre-la depuis « Apps forgées ».", tone="muted")]
    if not APP_NAME.match(name):
        return [Note("Donne le nom d'une app : des minuscules, chiffres et _, commençant par une lettre.",
                     tone="muted")]
    port = ctx.ports.get("forge")
    app = s.apps.get(name)
    info = port.info(name) if port is not None else None
    if app is None and info is None:
        return [Note(f"L'app « {name} » n'existe pas.", tone="muted")]
    return name, app, info, port


def _about(name: str, app: App | None, info: AppInfo | None, port: Any, frame: Frame,
           ctx: InspectContext) -> list[tuple[str, Cell]]:
    nxt = _next_tick(app, frame.env.tz_of(frame.root)) if app is not None else None
    title = app.title if app is not None else info.title if info is not None else name
    pairs: list[tuple[str, Cell]] = [
        ("nom", name), ("titre", title),
        ("description", _clip(info.description, 500) if info is not None and info.description else "—"),
        ("version", f"{app.version if app is not None else '—'} dans sa vie, "
                    f"{info.version if info is not None else '—'} sur le disque"),
        ("agenda", (app.schedule if app is not None else info.schedule if info is not None else "") or "manual"),
        ("prochain tour", ctx.when(nxt) if nxt is not None else "aucun"),
        ("état", _status(app, info, port)),
    ]
    if app is not None:
        pairs += [
            ("promue (ses outils servent en conversation)", "oui" if app.promoted else "non"),
            ("en vigueur depuis", ctx.when(app.since) if app.since else "—"),
            ("dernier tour", _last_tick(name, ctx)),
            ("échecs d'affilée", app.failures),
            ("événements en attente", len(app.inbox)),
            ("dernier signal", ctx.when(app.signaled_at) if app.signaled_at else "jamais"),
        ]
    if info is not None:
        pairs += [
            ("contexte en conversation", "oui" if info.context else "non"),
            ("événements voulus", ", ".join(info.events) or "—"),
            ("outils", ", ".join(t.name for t in info.tools) or "—"),
            ("vues", ", ".join(v.label for v in info.views) or "—"),
            ("fonctions", ", ".join(info.handlers) or "—"),
        ]
    return pairs


def _outcome(e: Any) -> tuple[str, str, str]:
    """(ce que c'est, issue, détail) d'un événement de la vie d'une app."""
    d = e.data
    if e.type.name == TICKED.name:
        return "tour", "ok" if d.ok else "échec", _clip(d.error or f"{d.duration_ms} ms", 300)
    if e.type.name == HANDLED.name:
        return "remise d'événements", "ok" if d.ok else "échec", _clip(d.error or f"jusqu'à l'événement {d.upto}", 300)
    if e.type.name == EMITTED.name:
        return "émission", "—", _clip(f"{d.type} : {d.data}", 300)
    if e.type.name == WRITTEN.name:
        return "version écrite", f"v{d.version}", _clip(d.title, 300)
    return "changement d'état", str(d.state or "—"), _clip(d.reason or "", 300) or "—"


def _lived(name: str, ctx: InspectContext, types: tuple[Any, ...]) -> Table:
    """Ce qu'une app a vécu, au journal : une page, puis « plus anciens » (un de plus pour savoir s'il y en a)."""
    before = ctx.int_param("avant", 0) or None
    found = ctx.events(types, LIVED_PAGE + 1, where=("app", name), before=before)
    lived = found[:LIVED_PAGE]
    older = (("avant", str(lived[-1].seq)),) if len(found) > LIVED_PAGE else ()
    return Table((Column("quand", "fit"), "quoi", "issue", "détail", Column("journal", "fit")),
                 tuple((When(e.at), *_outcome(e), Ref("event", str(e.seq), f"#{e.seq}")) for e in lived),
                 title="Ce qu'elle a vécu, du plus récent au plus ancien" + (" (plus anciens)" if before else ""),
                 empty="plus rien avant" if before else "rien pour l'instant",
                 pager=Pager(param="avant", size=LIVED_PAGE, older=older) if older or before else None)


# ── L'objet « app » : en-tête et recherche ────────────────────────────────


@FORGE.subject("app", label="App forgée", plural="Apps forgées", icon="⚒")
def _head(s: ForgeState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    if not APP_NAME.match(key):
        return None
    port = ctx.ports.get("forge")
    app = s.apps.get(key)
    info = port.info(key) if port is not None else None
    if app is None and info is None:
        return None
    text, tone = _state(app, info, port)
    badges = [Badge(text.split(" : ")[0].split(" ;")[0], tone)]
    if app is not None and app.promoted:
        badges.append(Badge("promue", "info"))
    if info is not None and info.error:
        badges.append(Badge("manifeste invalide", "danger"))
    if app is not None and info is not None and stale(app, info):
        badges.append(Badge("à recharger", "warn"))
    title = app.title if app is not None else info.title if info is not None else key
    facts: tuple[tuple[str, Cell], ...] = (
        ("version", app.version if app is not None else info.version if info is not None else 0),
        ("agenda", (app.schedule if app is not None else info.schedule if info is not None else "") or "manual"),
        ("dernier tour", _last_tick(key, ctx)),
    )
    return Head(key, title, subtitle=info.description if info is not None else "", badges=tuple(badges),
                facts=facts)


@FORGE.search("app")
def _search(s: ForgeState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("forge")
    disk = {i.name: i for i in port.apps()} if port is not None else {}
    wanted = fold(text)
    out: list[Found] = []
    for name in sorted(set(s.apps) | set(disk)):
        app, info = s.apps.get(name), disk.get(name)
        title = app.title if app is not None else info.title if info is not None else name
        if not wanted or wanted in fold(name) or wanted in fold(title):
            out.append(Found(name, title, _status(app, info, port)))
        if len(out) >= limit:
            break
    return out


# ── Apps forgées (la destination) ─────────────────────────────────────────


def _broken(s: ForgeState, frame: Frame) -> int:
    return sum(1 for a in s.apps.values() if a.broken)


@FORGE.inspect("apps", title="Apps forgées", section="apps", order=10, badge=_broken)
def _inspect(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("forge")
    on_disk = {i.name: i for i in port.apps()} if port is not None else {}
    blocks: list[Block] = []
    if port is None:
        blocks.append(Note("Forge non configurée : aucun hôte ne peut faire tourner ses apps.", tone="muted"))
    signals = {str(app): (count, last) for app, count, last in ctx.tally(c.SIGNALED, "app")}
    names, pager = paginate(sorted(set(s.apps) | set(on_disk)), ctx.pager(size=APPS_PAGE))
    out = []
    for name in names:
        app, info = s.apps.get(name), on_disk.get(name)
        title = app.title if app is not None else info.title if info is not None else name
        version = app.version if app is not None else info.version if info is not None else 0
        rule = app.schedule if app is not None else info.schedule if info is not None else ""
        count, last = signals.get(name, (0, 0))
        failures = f" ({app.failures} échec(s) d'affilée)" if app is not None and app.failures else ""
        text, tone = _state(app, info, port)
        link = _fiche(name)
        out.append(Row((link, _clip(title, 80), version, rule or "manual", Badge(text, tone),
                        "oui" if app is not None and app.promoted else "non", _last_tick(name, ctx) + failures,
                        f"{count} (le dernier : {ctx.when(last)})" if count else "0"),
                       href=link if isinstance(link, Ref) else None, tone="danger" if tone == "danger" else ""))
    blocks.append(Table(("app", "titre", Column("version", "num"), "agenda", "état", "promue", "dernier tour",
                         "signaux"), tuple(out), title="Ses apps", empty="elle n'a encore écrit aucune app",
                        pager=pager, caption="Un clic ouvre la fiche de l'app (état, vues, réglages, code, journal)."))
    return blocks


@FORGE.inspect("app", title="App forgée", hidden=True, params=[("app", "app")])
def _inspect_app(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """L'ancienne page d'une app (les liens anciens y mènent encore) : tout d'un coup, sans rien exécuter."""
    back = Fields((("retour", Ref("view", "forge/apps", "toutes ses apps")),))
    name = ctx.param("app")
    if not APP_NAME.match(name):
        return [back, Note("Donne le nom d'une app : des minuscules, chiffres et _, commençant par une lettre.",
                           tone="muted")]
    port = ctx.ports.get("forge")
    app = s.apps.get(name)
    info = port.info(name) if port is not None else None
    if app is None and info is None:
        return [back, Note(f"L'app « {name} » n'existe pas.", tone="muted")]
    blocks: list[Block] = [back, Fields((("sa fiche", _fiche(name, "ouvrir la fiche de l'app")),))]
    if port is None:
        blocks.append(Note("Forge non configurée : son manifeste, son code et son journal ne sont pas disponibles.",
                           tone="muted"))
    blocks.append(Fields(tuple(_about(name, app, info, port, frame, ctx)), title="L'app"))
    if info is not None:
        blocks.append(Table(("réglage", "défaut du manifeste"), tuple((k, _shown(v)) for k, v in info.config),
                            title="Réglages déclarés", empty="aucun réglage déclaré"))
    if port is not None:
        try:
            source = port.source(name)
        except ForgeRefused:
            source = None
        if source is not None:
            manifest, code = source
            blocks.append(Prose(manifest or "(vide)", title="manifest.yaml"))
            cut = len(code) > CODE_SHOWN
            blocks.append(Prose(code[:CODE_SHOWN] + (f"\n… (coupé : {len(code)} caractères en tout)" if cut else ""),
                                title="main.py"))
        logs = port.logs(name, LOGS_SHOWN)
        blocks.append(Prose("\n".join(logs), title=f"Son journal ({len(logs)} dernières lignes ; tout son journal, "
                                                   "par pages, dans l'onglet Journal de sa fiche)") if logs
                      else Note("Son journal est vide.", tone="muted"))
    blocks.append(_lived(name, ctx, (TICKED, HANDLED, EMITTED, SWITCHED)))
    return blocks


# ── Les onglets de la fiche ───────────────────────────────────────────────


@FORGE.inspect("etat", title="État", subject="app", order=10)
def _tab_state(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name, app, info, port = got
    blocks: list[Block] = []
    if port is None:
        blocks.append(Note(NOT_HERE + " Son code, ses vues et son journal ne sont pas disponibles.", tone="muted"))
    if app is not None and app.broken:
        blocks.append(Note(f"Le disjoncteur l'a arrêtée ({_clip(app.broken, 300)}). « Activer » la relance ; "
                           "Mika peut aussi la réparer.", tone="danger", title="Cassée"))
    if info is not None and info.error:
        blocks.append(Note(f"Son manifeste est invalide : {info.error}", tone="danger", title="Manifeste"))
    if app is not None and info is not None and stale(app, info):
        blocks.append(Note("Le disque porte une autre version que celle de sa vie : « Recharger » l'y fait entrer.",
                           tone="warn"))
    blocks.append(Fields(tuple(_about(name, app, info, port, frame, ctx)), title="L'app"))
    return blocks


def _choice_rows(name: str, spec: AppViewSpec, values: dict[str, Any]) -> list[Row]:
    """Les paramètres de la vue et leurs valeurs possibles, en liens (un texte ou un
    nombre se donne par les liens de la vue elle-même)."""
    rows: list[Row] = []
    base = [(p.key, _param_text(p.kind, values.get(p.key))) for p in spec.params]
    for p in spec.params:
        current = _param_text(p.kind, values.get(p.key))
        options = list(p.choices) if p.kind == "select" else [("oui", "oui"), ("non", "non")] if p.kind == "bool" \
            else []
        if not options:
            rows.append(Row((p.label, current or "—", Text("par les liens de la vue", kind="muted"))))
            continue
        for value, label in options:
            query = [(k, v) for k, v in base if k != p.key and v] + ([(p.key, value)] if value else [])
            ref = Ref("subject", f"app/{name}", label, (("onglet", "vues"), ("vue", spec.key), *query))
            on = value == current
            rows.append(Row((p.label, ref, Badge("actuel", "info") if on else ""), tone="info" if on else ""))
    return rows


def _param_text(kind: str, value: Any) -> str:
    if kind == "bool":
        return "oui" if value else "non"
    return "" if value is None else str(value)


@FORGE.inspect("vues", title="Vues", subject="app", order=20,
               params=[Param("vue", "Vue", placeholder="clé ou titre d'une vue")])
async def _tab_views(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name, app, info, port = got
    if port is None:
        return [Note(NOT_HERE + " Ses vues ne peuvent pas se rendre.", tone="muted")]
    if info is None:
        return [Note("Cette app n'est plus sur le disque : ses vues ne peuvent pas se rendre.", tone="warn")]
    if info.error:
        return [Note(f"Son manifeste est invalide : {info.error}", tone="danger", title="Manifeste")]
    if not info.views:
        return [Note("Cette app ne déclare aucune vue (views: dans son manifeste, view_<clé>(api, params) dans son "
                     "code).", tone="muted")]
    wanted = str(ctx.value("vue") or ctx.param("vue"))
    spec = find_view(info, wanted)
    blocks: list[Block] = []
    if spec is None:
        if wanted:
            known = ", ".join(v.key for v in info.views)
            blocks.append(Note(f"Vue « {_clip(wanted, 40)} » inconnue (au choix : {known}).", tone="warn"))
        spec = info.views[0]
    if len(info.views) > 1:
        blocks.append(Nav(tuple(NavItem(v.label, _fiche_view(name, v), active=v.key == spec.key)
                                for v in info.views), title="Ses vues"))
    values, notes = view_params(spec, ctx.params)
    blocks += [Note(n, tone="warn") for n in notes]
    if spec.description:
        blocks.append(Note(spec.description, tone="muted", title=spec.label))
    if spec.params:
        blocks.append(Table(("paramètre", "valeur", ""), tuple(_choice_rows(name, spec, values)),
                            title="Paramètres de la vue"))
    if app is not None and app.broken:
        blocks.append(Note(f"Cette app est cassée ({_clip(app.broken, 200)}) : ses vues ne se rendent plus. "
                           "« Activer » la relance.", tone="warn", title="Cassée"))
        return blocks
    return blocks + await render(port, name, info, spec, values)


def _fiche_view(name: str, v: AppViewSpec) -> Ref:
    return Ref("subject", f"app/{name}", v.label, (("onglet", "vues"), ("vue", v.key)))


def _secret_set(value: Any) -> bool:
    return bool(value)


@FORGE.inspect("reglages", title="Réglages", subject="app", order=30)
def _tab_settings(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name, app, info, port = got
    fields = info.config_fields if info is not None else _ui(s, name).config_fields
    if not fields:
        return [Note("Cette app ne déclare aucun réglage (config: dans son manifeste).", tone="muted")]
    store = ctx.ports.get("forge_settings")
    current = dict(store.values(name)) if store is not None else {}
    rows = []
    for f in fields:
        value = current.get(f.path)
        if f.kind == "secret":
            shown: Cell = Badge("défini", "ok") if _secret_set(value) else Badge("non défini", "muted")
            default: Cell = "—"
        else:
            shown = _shown(value) if f.path in current else Text(_shown(f.default) if f.default is not None else "—",
                                                                  kind="muted")
            default = _shown(f.default) if f.default is not None else "—"
        origin = "réglé par un opérateur" if f.path in current and (f.kind != "secret" or value) else "défaut"
        rows.append(Row((Text(f.label, hint=f.help) if f.help else f.label, f.group or "—", f.kind, shown, default,
                         origin)))
    blocks: list[Block] = [Table(("réglage", "groupe", "type", "valeur", "défaut du manifeste", "provenance"),
                                 tuple(rows), title="Ses réglages")]
    if store is None:
        blocks.append(Note("Les réglages ne sont pas modifiables ici (aucun magasin de réglages).", tone="muted"))
        return blocks
    if app is None:
        blocks.append(Note("Cette app n'est pas encore dans sa vie : « Recharger » l'y fait entrer, puis ses réglages "
                           "se règlent ici.", tone="muted"))
        return blocks
    initial = tuple((f.path, _initial(f, current[f.path])) for f in fields if f.path in current)
    blocks.append(ActionSlot("forge.regler", initial=initial, title="Régler"))
    return blocks


def _initial(f: FormField, value: Any) -> str:
    """La valeur réglée, telle que le formulaire l'affiche (jamais un secret : « défini »)."""
    if f.kind == "secret":
        return "1" if value else ""
    if f.kind == "bool":
        return "oui" if value else "non"
    if f.kind == "lines":
        return "\n".join(str(v) for v in value) if isinstance(value, list | tuple) else str(value or "")
    return "" if value is None else str(value)


@FORGE.inspect("code", title="Code", subject="app", order=40)
def _tab_code(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name, app, info, port = got
    if port is None:
        return [Note(NOT_HERE, tone="muted")]
    try:
        source = port.source(name)
    except ForgeRefused:
        source = None
    if source is None:
        return [Note("Cette app n'est plus sur le disque.", tone="warn")]
    manifest, code = source
    cut = len(code) > CODE_SHOWN
    blocks: list[Block] = [Code(manifest or "(vide)", title="manifest.yaml"),
                           Code(code[:CODE_SHOWN] + (f"\n… (coupé : {len(code)} caractères en tout)" if cut else ""),
                                title="main.py")]
    if info is not None and info.callable:
        blocks.append(ActionSlot("forge.tester", title="Tester une fonction"))
    return blocks


@FORGE.inspect("journal", title="Journal", subject="app", order=50)
def _tab_logs(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name, app, info, port = got
    if port is None:
        return [Note(NOT_HERE, tone="muted")]
    logs = port.logs(name, LOGS_READ)
    if not logs:
        return [Note("Son journal est vide.", tone="muted")]
    numbered = [(n, line) for n, line in enumerate(logs, start=1)][::-1]  # la plus récente d'abord
    page, pager = paginate(numbered, ctx.pager(size=LOGS_PAGE))
    return [Table((Column("n°", "num"), "ligne"), tuple((n, Text(line, kind="mono")) for n, line in page),
                  title=f"Son journal ({len(logs)} ligne(s), la plus récente d'abord ; une donnée)", pager=pager,
                  caption=f"L'hôte ne garde que ses {LOGS_READ} dernières lignes." if len(logs) >= LOGS_READ
                  else "")]


@FORGE.inspect("vecu", title="Vécu", subject="app", order=60)
def _tab_lived(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name = got[0]
    return [_lived(name, ctx, (TICKED, HANDLED, EMITTED, SWITCHED, WRITTEN))]


# ── Les commandes d'un opérateur ──────────────────────────────────────────


def _in_life(s: ForgeState, key: str) -> App | None:
    return s.apps.get(key)


def _port(ctx: ActionContext) -> Any:
    port = ctx.ports.get("forge")
    if port is None:
        raise Refused(NOT_HERE)
    return port


def _info(ctx: ActionContext, name: str) -> AppInfo:
    info = _port(ctx).info(name) if APP_NAME.match(name) else None
    if info is None:
        raise Refused("Cette app n'est pas sur le disque.")
    return info


def _switch(state: str, message: str):
    def act(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
        if ctx.subject not in s.apps:
            raise Refused("Cette app n'est pas (encore) dans sa vie : « Recharger » l'y fait entrer.")
        return Done(drafts=(SWITCHED.draft(app=ctx.subject, state=state, reason="opérateur"),), message=message)

    return act


FORGE.action("activer", title="Activer", args=NoArgs, emits=[SWITCHED], subject="app", order=10,
             description="Elle tournera de nouveau à son agenda (le disjoncteur se referme).",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and (not a.enabled or bool(a.broken)),
             )(_switch("enabled", "Activée : elle tournera à son agenda."))
FORGE.action("arreter", title="Arrêter", args=NoArgs, emits=[SWITCHED], subject="app", order=11,
             description="Elle ne tourne plus (ses vues et réglages restent).",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and a.enabled and not a.broken,
             )(_switch("disabled", "Arrêtée."))
FORGE.action("promouvoir", title="Promouvoir", args=NoArgs, emits=[SWITCHED], subject="app", order=20,
             description="Ses outils servent aussi en conversation, pas seulement quand elle travaille.",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and not a.promoted,
             )(_switch("promoted", "Promue : ses outils servent en conversation."))
FORGE.action("retrograder", title="Rétrograder", args=NoArgs, emits=[SWITCHED], subject="app", order=21,
             description="Ses outils ne servent plus que quand elle travaille.",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and a.promoted,
             )(_switch("demoted", "Rétrogradée."))


@FORGE.action("recharger", title="Recharger", args=NoArgs, emits=[WRITTEN], subject="app", order=5,
              description="Son processus repart du disque ; une version posée sur le disque entre dans sa vie.")
async def _reload(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    info = _info(ctx, name)
    await _port(ctx).reload(name)
    drafts = (written_draft(info),) if stale(s.apps.get(name), info) else ()
    return Done(drafts=drafts, message="Rechargée : le prochain appel repart du disque."
                + (f" La version {info.version} est dans sa vie." if drafts else ""))


@FORGE.action("revenir", title="Version précédente", args=NoArgs, emits=[WRITTEN], subject="app", order=30,
              description="Remet la version archivée précédente (l'actuelle est archivée à son tour).",
              confirm="Revenir à la version précédente de cette app ?")
async def _rollback(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    port = _port(ctx)
    try:
        version = await port.rollback(name)
    except (ForgeRefused, OSError) as exc:
        raise Refused(f"Impossible : {exc}") from exc
    info = port.info(name)
    draft = written_draft(info) if info is not None else WRITTEN.draft(app=name, version=version, title=name)
    return Done(drafts=(draft,), message=f"Revenue à la version précédente (désormais version {version}).")


@FORGE.action("vider", title="Vider le stockage", args=NoArgs, emits=[SWITCHED], subject="app", order=40,
              description="Efface tout ce qu'elle a rangé (api.kv_*). Son code et ses réglages restent.",
              danger=True, confirm="Vider tout le stockage de cette app ?")
async def _reset(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    _info(ctx, name)
    n = await _port(ctx).reset_storage(name)
    drafts = (SWITCHED.draft(app=name, state="reset", reason=f"opérateur : stockage vidé ({n} clés)"),) \
        if name in s.apps else ()
    return Done(drafts=drafts, message=f"Stockage vidé ({n} clés).")


@FORGE.action("effacer", title="Effacer", args=NoArgs, emits=[SWITCHED], subject="app", order=50,
              description="Met l'app à la corbeille (restaurable à la main) et la sort de sa vie.",
              danger=True, retype=True, confirm="Effacer cette app ?")
async def _erase(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    try:
        await _port(ctx).erase(name)
    except (ForgeRefused, OSError) as exc:
        raise Refused(f"Impossible : {exc}") from exc
    return Done(drafts=(SWITCHED.draft(app=name, state="erased", reason="opérateur"),),
                message=f"« {name} » est à la corbeille.", go=Ref("view", "forge/apps", "Apps forgées"))


# ── Tester une fonction ───────────────────────────────────────────────────


class TestForm(BaseModel):
    """Ce que la commande attend quand ses choix ne sont pas encore connus."""

    fonction: Annotated[str, Knob(label="Fonction", help="tick, context, view_<vue>, action_<vue>_<action>, "
                                  "tool_<nom>…", advanced=False)] = "tick"
    args: Annotated[str, Knob(label="Arguments (JSON)", widget="textarea", advanced=False,
                              help="un objet JSON : les paramètres d'une vue, les données d'une action…")] = "{}"


def _test_fields(s: ForgeState, frame: Frame, key: str, fixed: dict[str, str]) -> tuple[FormField, ...]:
    functions = _ui(s, key).functions
    return (form_field("fonction", "select", "Fonction", required=bool(functions),
                       choices=tuple((f, f) for f in functions), default=functions[0] if functions else None,
                       order=0) if functions else
            form_field("fonction", "text", "Fonction", required=True, default="tick", order=0),
            form_field("args", "textarea", "Arguments (JSON)", default="{}", order=1,
                       help="un objet JSON : les paramètres d'une vue, les données d'une action…"))


@FORGE.action("tester", title="Tester", args=TestForm, emits=[], subject="app", order=60, fields=_test_fields,
              description="Lance une de ses fonctions maintenant et montre ce qu'elle rend (sans rien journaliser, "
                          "sans compter contre elle ; une vue : son enveloppe est vérifiée).")
async def _test(s: ForgeState, frame: Frame, data: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    data = data.model_dump() if isinstance(data, BaseModel) else dict(data)
    info = _info(ctx, name)
    fn = str(data.get("fonction") or "")
    if fn not in info.callable:
        raise Refused("Fonction inconnue.", {"fonction": f"au choix : {', '.join(info.callable) or 'aucune'}"})
    try:
        args = json.loads(str(data.get("args") or "{}"))
    except ValueError as exc:
        raise Refused("Arguments illisibles.", {"args": f"JSON illisible : {exc}"}) from exc
    if not isinstance(args, dict):
        raise Refused("Arguments illisibles.", {"args": "un objet JSON {…} est attendu"})
    port = _port(ctx)
    spec = next((v for v in info.views if v.function == fn), None)
    if spec is not None:
        values, _ = view_params(spec, {k: str(v) for k, v in args.items()})
        r = await port.call(name, fn, {} if fn == "view" else values, timeout_s=VIEW_TIMEOUT_S,
                            max_result=VIEW_MAX_BYTES)
        if not r.ok:
            return Done(message=f"{fn} : échec en {r.duration_ms} ms", tone="danger",
                        show=(_facts(r), failure_note(spec.label, r), *_logs(r)))
        blocks = decode_view(r.value, name, info, spec)
        verdict = summary(blocks) if not _invalid(blocks) else "enveloppe invalide"
        return Done(message=f"{fn} : {verdict} ({r.duration_ms} ms)", tone="danger" if _invalid(blocks) else "ok",
                    show=(_facts(r), *without_forms(blocks), *_logs(r)))
    call_args = {"name": args.get("name", ""), "args": args.get("args", {})} if fn == "action" else args
    r = await port.call(name, fn, call_args, timeout_s=ACTION_TIMEOUT_S)
    shown: list[Block] = [_facts(r)]
    if r.ok:
        shown.append(Code(json.dumps(r.value, ensure_ascii=False, indent=2, default=str)[:20_000], title="Ce qu'elle rend"))
        if fn.startswith("action_") and not _is_answer(r.value):
            shown.append(Note("Une action doit rendre {\"ok\": vrai|faux, \"message\": \"…\"}.", tone="warn"))
    else:
        shown.append(Note(r.error, tone="danger", title="Échec"))
    return Done(message=f"{fn} : {'ok' if r.ok else 'échec'} en {r.duration_ms} ms", tone="ok" if r.ok else "danger",
                show=(*shown, *_logs(r)))


def _invalid(blocks: Sequence[Any]) -> bool:
    return len(blocks) == 1 and isinstance(blocks[0], Note) and blocks[0].tone == "danger"


def _is_answer(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("ok"), bool) and isinstance(value.get("message", ""), str)


def _facts(r: CallResult) -> Fields:
    pairs: list[tuple[str, Cell]] = [("issue", Badge("ok", "ok") if r.ok else Badge("échec", "danger")),
                                     ("durée", f"{r.duration_ms} ms"), ("tuée", "oui" if r.killed else "non")]
    if r.signals:
        pairs.append(("signaux (non journalisés)", "; ".join(f"{t} ({p:.1f})" for t, p, _ in r.signals)))
    if r.emits:
        pairs.append(("émissions (non journalisées)", "; ".join(t for t, _ in r.emits)))
    return Fields(tuple(pairs), title="L'appel")


def _logs(r: CallResult) -> tuple[Block, ...]:
    return (Code("\n".join(r.logs), title="Son journal pendant l'appel"),) if r.logs else ()


# ── Agir : une action déclarée par l'app, en place dans sa vue ────────────


def _declared(s: ForgeState, name: str, fixed: dict[str, str]) -> tuple[AppViewSpec, Any] | None:
    ui = _ui(s, name)
    view = ui.view(str(fixed.get("vue") or ""))
    action = view.action(str(fixed.get("action") or "")) if view is not None else None
    return (view, action) if view is not None and action is not None else None


def _act_fields(s: ForgeState, frame: Frame, key: str, fixed: dict[str, str]) -> tuple[FormField, ...]:
    got = _declared(s, key or str(fixed.get("app") or ""), fixed)
    if got is None:
        return ()
    _, action = got
    confirm = (form_field("confirmer", "bool", f"Je confirme : {action.confirm}", order=10_000),) if action.confirm \
        else ()
    return (*action.fields, *confirm)


def _check(action: Any, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Les données d'une action, vérifiées au-delà du contrôle : présence, longueur, forme."""
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    kinds = {f.path: f for f in action.fields}
    for rule in action.rules:
        value = data.get(rule.key)
        field = kinds.get(rule.key)
        if field is not None and field.kind == "bool":
            out[rule.key] = bool(value)
            continue
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            if rule.required:
                errors[rule.key] = "valeur requise"
            out[rule.key] = None if field is not None and field.kind in ("int", "float", "select") else ""
            continue
        if field is not None and isinstance(value, int | float) and not isinstance(value, bool) and (
                (field.lo is not None and value < field.lo) or (field.hi is not None and value > field.hi)):
            errors[rule.key] = f"doit être entre {field.lo:g} et {field.hi:g}" if field.lo is not None \
                and field.hi is not None else "hors de ses bornes"
        elif isinstance(value, str):
            if rule.max_length and len(value) > rule.max_length:
                errors[rule.key] = f"trop long : {rule.max_length} caractères au plus"
            elif rule.type == "email" and not EMAIL.match(value.strip()):
                errors[rule.key] = "une adresse e-mail est attendue (nom@exemple.fr)"
            elif rule.type == "url" and not URL.match(value.strip()):
                errors[rule.key] = "une adresse http(s)://… est attendue"
        out[rule.key] = value
    return out, errors


async def _act(s: ForgeState, frame: Frame, data: Any, ctx: ActionContext) -> Done:
    data = dict(data or {})
    name = ctx.subject or str(data.get("app") or "")
    if data.get("app") and data["app"] != name:
        raise Refused("Ce formulaire ne vient pas de cette app.")
    app = s.apps.get(name)
    if app is None:
        raise Refused("Cette app n'est pas (encore) dans sa vie.")
    if app.broken:
        raise Refused(f"Cette app est cassée ({_clip(app.broken, 200)}) : « Activer » la relance d'abord.")
    info = _info(ctx, name)
    view = next((v for v in info.views if v.key == data.get("vue")), None)
    action = view.action(str(data.get("action") or "")) if view is not None else None
    if view is None or action is None:
        raise Refused("Cette action n'existe plus (l'app a changé) : recharge la page.")
    if action.confirm and not data.get("confirmer"):
        raise Refused("Confirmation manquante.", {"confirmer": f"coche pour confirmer : {action.confirm}"})
    payload, errors = _check(action, data)
    if errors:
        raise Refused("Le formulaire a des erreurs.", errors)
    r = await _port(ctx).call(name, action.function, payload, timeout_s=ACTION_TIMEOUT_S)
    p = params(frame.env.params_of("forge", frame.root))
    drafts = tuple(outcomes(name, app, [r], ctx.now, p, breaker=False))  # jamais compté contre l'app
    if not r.ok:
        return Done(drafts=drafts, message=f"L'action de l'app a échoué : {r.error}"[:MESSAGE_MAX], tone="danger")
    if not _is_answer(r.value):
        return Done(drafts=drafts, message="L'app n'a pas rendu {ok, message} : rien à dire de plus.", tone="warn")
    ok = r.value["ok"]
    message = str(r.value.get("message") or ("Fait." if ok else "L'app a refusé."))[:MESSAGE_MAX]
    return Done(drafts=drafts, message=message, tone="ok" if ok else "warn")


FORGE.action("agir", title="Agir", args=NoArgs, emits=[EMITTED, c.SIGNALED], fields=_act_fields,
             description="Une action que l'app déclare dans sa vue ; elle s'exécute chez elle (5 s).")(_act)


# ── Régler : ses réglages typés ───────────────────────────────────────────

_YES_NO = (("oui", "oui"), ("non", "non"))


def _as_form(f: FormField) -> FormField:
    """Un réglage tel que le formulaire le montre : une liste en lignes, un oui/non en choix."""
    if f.kind == "lines":
        default = "\n".join(str(v) for v in f.default) if isinstance(f.default, list | tuple) else f.default
        return replace(f, kind="textarea", default=default, help=f"{f.help} (une valeur par ligne)".strip())
    if f.kind == "bool":
        default = None if f.default is None else ("oui" if f.default else "non")
        return replace(f, kind="select", choices=_YES_NO, default=default, nullable=True)
    return f


def _settings_fields(s: ForgeState, frame: Frame, key: str, fixed: dict[str, str]) -> tuple[FormField, ...]:
    return tuple(_as_form(f) for f in _ui(s, key).config_fields)


def _setting(f: FormField, value: Any) -> Any:
    """La valeur lue du formulaire, dans le type du réglage (``None`` : retour au défaut)."""
    if value is None:
        return None
    if f.kind == "lines":
        return [line.strip() for line in str(value).splitlines() if line.strip()]
    if f.kind == "bool":
        return value == "oui"
    return value


async def _settle(s: ForgeState, frame: Frame, data: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    store = ctx.ports.get("forge_settings")
    if store is None:
        raise Refused("Les réglages ne sont pas modifiables ici.")
    fields = {f.path: f for f in _info(ctx, name).config_fields}
    data = dict(data or {})
    current = dict(store.values(name))
    new: dict[str, Any] = {}
    for key, f in fields.items():
        if f.kind == "secret":
            value = data.get(key, current.get(key))  # absent : inchangé ; « » : effacé
            if value:
                new[key] = value
            continue
        if key not in data:
            if key in current:
                new[key] = current[key]
            continue
        value = _setting(f, data[key])
        if value is not None and value != f.default:
            new[key] = value
    await store.save(name, new)
    changed = sorted(k for k in set(new) | set(current) if new.get(k) != current.get(k))
    if not changed:
        return Done(message="Rien n'a changé.", tone="info")
    labels = ", ".join(fields[k].label for k in changed if k in fields)
    return Done(message=f"Réglages enregistrés ({labels}) : lus au prochain appel de l'app.")


FORGE.action("regler", title="Enregistrer les réglages", args=NoArgs, emits=[], fields=_settings_fields,
             description="Les secrets laissés vides restent inchangés ; un champ vidé revient au défaut du "
                         "manifeste.")(_settle)
