"""Ce que la Forge montre et permet à un opérateur, dans la console.

- **La fiche d'une app** (type d'objet ``app``, clé = son nom) : son en-tête
  (titre, version, état, agenda, dernier tour), et ses onglets — **État**,
  **Vues** (ses vues déclarées, rendues depuis le bac à sable), **Réglages**
  (ses réglages typés, les secrets jamais montrés), **Code**, **Base** (son
  schéma, et une lecture : rien ne s'y écrit d'ici — la console en MCP la sert
  comme toute fiche), **Journal**, **Vécu**. La recherche la trouve par son nom ou son titre.
- **Apps forgées** (la destination) : toutes ses apps, un lien vers chaque
  fiche ; le badge compte les apps cassées.
- **Les commandes** (``forge.*``) : recharger, activer, arrêter, promouvoir,
  rétrograder, revenir à la version précédente, vider sa base, effacer
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
from mika.contracts import social as social_c
from mika.kernel.forms import FormField, Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Cell,
    Code,
    Column,
    Disclosure,
    Fields,
    Filters,
    Found,
    Head,
    InspectContext,
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
from mika.kernel.rights import Grant, RuleTable, why_words
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
    app_lines,
    calls_today,
    concerns,
    has_secrets,
    outcomes,
    params,
    rules_of,
    stale,
    trusted,
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
from mika.ports.forge import (
    AppInfo,
    AppUI,
    AppViewSpec,
    CallResult,
    ForgeRefused,
    check_args,
    form_field,
    said_args,
    ui_load,
)
from mika.vocab.access import NO, POLICY_WORDS, verdict

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


def _queue_words(app: App, now: int) -> str:
    """Sa file de signaux en une ligne : ce qui attend, ce que l'app déclare, ses lectures du jour, ses pertes."""
    r = rules_of(app)
    text = (f"{len(app.queue)} en attente sur {r.queue} ; lue par {r.per_call}, {calls_today(app, now)} lecture(s) "
            f"sur {r.quota} aujourd'hui")
    if app.dropped:
        text += f" ; {app.dropped} parti(s) sans être lus (file pleine)"
    return text + (f" — consigne : {_clip(r.instructions, 200)}" if r.instructions else "")


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
            ("validée (ses secrets lui sont lisibles, ses versions s'installent sans accord)",
             "oui" if trusted(app) else "non — « Lui faire confiance » après avoir lu son code"),
            ("arrêtée par un opérateur", "oui" if app.held else "non"),
            ("en vigueur depuis", ctx.when(app.since) if app.since else "—"),
            ("dernier tour", _last_tick(name, ctx)),
            ("échecs d'affilée", app.failures),
            ("événements en attente", len(app.inbox)),
            ("sa file de signaux (ADR 0105)", _queue_words(app, frame.now)),
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
    pages = tuple(_fiche_view(key, v) for v in info.views) if info is not None and not info.error else ()
    # ses pages en onglets ; ses réglages et ce qui est technique derrière la roue (ADR 0104)
    return Head(key, title, subtitle=info.description if info is not None else "", badges=tuple(badges),
                facts=facts, default_tab="vues" if pages else "etat", action_tabs=("etat", "code"),
                back=Ref("local", "/inspecteur/apps", "Toutes les apps"), pages=pages, pages_tab="vues",
                gear=("reglages", "etat", "code", "base", "journal", "vecu"))


@FORGE.search("app")
def _search(s: ForgeState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("forge")
    disk = {i.name: i for i in port.apps()} if port is not None else {}
    wanted = fold(text)
    out: list[Found] = []
    skip = max(0, ctx.int_param("_offset", 0))
    for name in sorted(set(s.apps) | set(disk)):
        app, info = s.apps.get(name), disk.get(name)
        title = app.title if app is not None else info.title if info is not None else name
        if not wanted or wanted in fold(name) or wanted in fold(title):
            if skip:
                skip -= 1
                continue
            out.append(Found(name, title, _status(app, info, port)))
        if len(out) >= limit:
            break
    return out


# ── Apps forgées (la destination) ─────────────────────────────────────────


def _broken(s: ForgeState, frame: Frame) -> int:
    return sum(1 for a in s.apps.values() if a.broken)


@FORGE.inspect("apps", title="Apps forgées", section="apps", order=10, badge=_broken,
               description="Ouvre une app pour l'utiliser, consulter son état ou modifier ses réglages dans la Forge.",
               params=[Param("q", "Rechercher une app", placeholder="Nom ou titre")])
def _inspect(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("forge")
    on_disk = {i.name: i for i in port.apps()} if port is not None else {}
    blocks: list[Block] = []
    if port is None:
        blocks.append(Note("Forge non configurée : aucun hôte ne peut faire tourner ses apps.", tone="muted"))
    # ce qu'elle a signalé : ses signaux mis en file (api.signal, ADR 0105), et ceux qui passent droit à son attention
    # (une panne, ce qu'elle garde en tête d'un tri)
    signals: dict[str, tuple[int, int]] = {}
    for kind in (c.QUEUED, c.SIGNALED):
        for app_name, count, last in ctx.tally(kind, "app"):
            had = signals.get(str(app_name), (0, 0))
            signals[str(app_name)] = (had[0] + count, max(had[1], last))
    names = sorted(set(s.apps) | set(on_disk))
    query = fold(str(ctx.value("q") or ""))
    if query:
        names = [n for n in names if query in fold(n + " " + (
            s.apps[n].title if n in s.apps else on_disk[n].title))]
    names, pager = paginate(names, ctx.pager(size=APPS_PAGE))
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
    blocks.append(Table(("app", "titre", Column("version", "num", detail=True), Column("agenda", detail=True), "état",
                         Column("promue", detail=True), "dernier tour", Column("signaux", detail=True)),
                        tuple(out), title="Ses apps", empty="Aucune app ne correspond à cette recherche." if query else "Elle n’a encore écrit aucune app.",
                        pager=pager, caption="Un clic ouvre l'app : ses pages en onglets, ses réglages et le reste "
                                             "derrière la roue, en haut à droite."))
    return blocks


@FORGE.inspect("outils_apps", title="Les outils de ses apps", hidden=True,
               description="Ce que ses apps lui donnent à faire : les outils qu'une app déclare, et de quoi lire ses "
                           "pages si elle en a (ADR 0104). La console les montre sous les services branchés (Outils › "
                           "Venus d'ailleurs) ; ils se règlent sur la fiche de l'app (sa promotion).")
def _inspect_app_tools(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("forge")
    if port is None:
        return [Note("Forge non configurée : aucune app ne peut servir.", tone="muted")]
    rows = []
    for info in sorted(port.apps(), key=lambda i: i.name):
        app = s.apps.get(info.name)
        if not info.tools and not info.views:
            continue
        if app is None or not app.enabled or app.broken:
            state, tone = ("en panne : elle ne s'en sert pas", "danger") if app is not None and app.broken else \
                ("arrêtée : elle ne s'en sert pas", "muted")
        elif app.promoted or not has_secrets(ctx.ports, info):
            state, tone = "avec sa propriétaire et quand elle travaille", "ok"
        else:
            state, tone = "quand elle travaille ; avec sa propriétaire une fois promue (elle a des secrets)", "info"
        given = [(f"{info.name}_{tool.name}", _clip(tool.description, 300), said_args(tool.args) or "aucun")
                 for tool in info.tools]
        if info.views:
            given.append((f"{info.name}_pages", f"Lire ses pages : {', '.join(v.label for v in info.views)}.",
                          "view, params"))
        for name, what, args in given:
            rows.append(Row((_fiche(info.name, info.title or info.name), Text(name, "mono"), Text(what),
                             Text(args, "mono"), Badge(state, tone)),
                            href=_fiche(info.name) if APP_NAME.match(info.name) else None))
    return [Table(("app", Column("outil", "fit"), "ce qu'il fait", "arguments", "quand il sert"), tuple(rows),
                  title="Les outils de ses apps", empty="Aucune de ses apps ne lui donne d'outil.",
                  caption="Une app qui a des secrets ne sert en conversation qu'une fois promue ; tu la promeus "
                          "depuis sa fiche (Apps forgées).")]


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


@FORGE.inspect("etat", title="État", subject="app", order=10,
               description="L'état de fonctionnement, la version chargée, le rythme d'exécution et les éventuels problèmes de cette app.")
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
                           "elle peut aussi la réparer.", tone="danger", title="Cassée"))
    if info is not None and info.error:
        blocks.append(Note(f"Son manifeste est invalide : {info.error}", tone="danger", title="Manifeste"))
    if app is not None and info is not None and stale(app, info):
        blocks.append(Note("Le disque porte une autre version que celle de sa vie : « Recharger » l'y fait entrer.",
                           tone="warn"))
    blocks.append(Fields(tuple(_about(name, app, info, port, frame, ctx)), title="L'app"))
    return blocks


def _param_text(kind: str, value: Any) -> str:
    if kind == "bool":
        return "oui" if value else "non"
    return "" if value is None else str(value)


@FORGE.inspect("vues", title="Vues", subject="app", order=20,
               description="Utilise les vues de cette app et leurs actions. Les filtres ne modifient aucune donnée.")
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
    wanted = ctx.param("vue")
    spec = find_view(info, wanted)
    blocks: list[Block] = []
    if spec is None:
        if wanted:
            known = ", ".join(v.key for v in info.views)
            blocks.append(Note(f"Vue « {_clip(wanted, 40)} » inconnue (au choix : {known}).", tone="warn"))
        spec = info.views[0]
    # ses pages sont les onglets de sa fiche (ADR 0104) : plus de second menu ici
    values, notes = view_params(spec, ctx.params)
    blocks += [Note(n, tone="warn") for n in notes]
    if spec.description:
        blocks.append(Note(spec.description, tone="muted", title=spec.label))
    if spec.params:
        blocks.append(Filters(
            tuple(Param(p.key, p.label, p.kind, p.choices, p.default) for p in spec.params),
            values=tuple((p.key, _param_text(p.kind, values.get(p.key))) for p in spec.params),
            keep=(("onglet", "vues"), ("vue", spec.key)), title="Appliquer les filtres"))
    if app is not None and app.broken:
        blocks.append(Note(f"Cette app est cassée ({_clip(app.broken, 200)}) : ses vues ne se rendent plus. "
                           "« Activer » la relance.", tone="warn", title="Cassée"))
        return blocks
    return blocks + await render(port, name, info, spec, values, secrets=trusted(app))


def _fiche_view(name: str, v: AppViewSpec) -> Ref:
    return Ref("subject", f"app/{name}", v.label, (("onglet", "vues"), ("vue", v.key)))


def _secret_set(value: Any) -> bool:
    return bool(value)


@FORGE.inspect("reglages", title="Réglages", subject="app", order=30,
               description="Les réglages propres à cette app restent ici. Ils prennent effet lors de son prochain appel.")
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
    effective = Disclosure("Valeurs effectives et valeurs par défaut", (
        Table(("réglage", "groupe", "type", "valeur", "défaut du manifeste", "provenance"),
              tuple(rows), title="Ses réglages"),))
    blocks: list[Block] = []
    if store is None:
        blocks.append(Note("Les réglages ne sont pas modifiables ici (aucun magasin de réglages).", tone="muted"))
        return [*blocks, effective]
    if app is None:
        blocks.append(Note("Cette app n'est pas encore dans sa vie : « Recharger » l'y fait entrer, puis ses réglages "
                           "se règlent ici.", tone="muted"))
        return [*blocks, effective]
    initial = tuple((f.path, _initial(f, current[f.path])) for f in fields if f.path in current)
    blocks.append(ActionSlot("forge.regler", initial=initial, title="Régler"))
    return [*blocks, effective]


def _initial(f: FormField, value: Any) -> str:
    """La valeur réglée, telle que le formulaire l'affiche (jamais un secret : « défini »)."""
    if f.kind == "secret":
        return "1" if value else ""
    if f.kind == "bool":
        return "oui" if value else "non"
    if f.kind == "lines":
        return "\n".join(str(v) for v in value) if isinstance(value, list | tuple) else str(value or "")
    return "" if value is None else str(value)


@FORGE.inspect("code", title="Code", subject="app", order=40,
               description="Le manifeste et le code de l'app. Le test d'une fonction affiche son résultat ici.")
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


@FORGE.inspect("base", title="Base", subject="app", order=45,
               params=(Param("requete", "Lecture", "search", placeholder="SELECT … FROM … LIMIT 50"),),
               description="Sa base à elle : ses tables, leurs colonnes et leurs lignes, sa taille. Une lecture "
                           "(SELECT) pour y regarder ; rien ne s'y écrit d'ici.")
async def _tab_base(s: ForgeState, frame: Frame, ctx: InspectContext) -> list[Block]:
    got = _subject(s, ctx)
    if isinstance(got, list):
        return got
    name, app, info, port = got
    if port is None:
        return [Note(NOT_HERE, tone="muted")]
    try:
        schema = await port.db_schema(name)
    except ForgeRefused as exc:
        return [Note(f"Sa base ne répond pas : {_clip(str(exc), 300)}", tone="warn")]
    rows = tuple((Text(t["name"], kind="mono"), t["rows"],
                  ", ".join(f"{c['name']} {c['type']}" + (" (clé)" if c.get("key") else "") for c in t["columns"]))
                 for t in schema["tables"])
    blocks: list[Block] = [
        Fields((("moteur", schema["engine"]), ("taille", _octets(schema["size"])),
                ("plafond", _octets(schema["max"])), ("vues", ", ".join(schema["views"]) or "aucune")),
               title="Sa base"),
        Table(("table", Column("lignes", "num"), "colonnes"), rows, title="Ses tables",
              caption="_kv : le stockage de api.kv_*."),
    ]
    wanted = (ctx.param("requete") or "").strip()
    if not wanted:
        return blocks
    try:
        found = await port.db_query(name, wanted)
    except ForgeRefused as exc:
        return [*blocks, Note(f"Refusée : {_clip(str(exc), 300)}", tone="warn")]
    columns = tuple(dict.fromkeys(k for r in found for k in r)) or ("(aucune colonne)",)
    page, pager = paginate(found, ctx.pager(size=LOGS_PAGE))
    return [*blocks, Table(columns, tuple(tuple(_shown(r.get(c)) for c in columns) for r in page),
                           title=f"{len(found)} ligne(s)", pager=pager, empty="aucune ligne")]


def _octets(n: int) -> str:
    return f"{n / 1_000_000:.1f} Mo".replace(".", ",") if n >= 100_000 else f"{max(1, n // 1000)} Ko"


@FORGE.inspect("journal", title="Journal", subject="app", order=50,
               description="Les sorties techniques de l'app, de la ligne la plus récente à la plus ancienne.")
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
                  title="Journal de l’app", pager=pager,
                  caption=f"L'hôte ne garde que ses {LOGS_READ} dernières lignes." if len(logs) >= LOGS_READ
                  else "")]


@FORGE.inspect("vecu", title="Vécu", subject="app", order=60,
               description="Les exécutions, changements d'état et signaux de cette app conservés dans son journal.")
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


def _switch(state: str, message: str, *, vouch: bool = False):
    def act(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
        if ctx.subject not in s.apps:
            raise Refused("Cette app n'est pas (encore) dans sa vie : « Recharger » l'y fait entrer.")
        drafts = [SWITCHED.draft(app=ctx.subject, state=state, reason="opérateur")]
        if vouch:  # un opérateur qui promeut a lu la version qu'il promeut
            drafts.append(_vouch(s, ctx))
        return Done(drafts=tuple(drafts), message=message)

    return act


def _vouch(s: ForgeState, ctx: ActionContext) -> Any:
    """« Cette app, je la valide » : ses secrets lui deviennent lisibles, pour cette version et les suivantes (ADR
    0105) — jusqu'à ce qu'un opérateur lui retire sa confiance."""
    app = s.apps.get(ctx.subject)
    return SWITCHED.draft(app=ctx.subject, state="trusted", reason="opérateur",
                          fingerprint=app.fingerprint if app is not None else "")


@FORGE.action("valider", title="Lui faire confiance", args=NoArgs, emits=[SWITCHED], subject="app",
              order=12, description="Ses réglages secrets ne se lisent que par une app qu'un opérateur a validée "
              "une fois, après avoir lu son code (onglet Code). Ensuite, ses nouvelles versions s'installent sans "
              "te redemander.",
              available=lambda s, frame, key: (a := _in_life(s, key)) is not None and not trusted(a),
              confirm="Faire confiance à cette app ? Elle lira ses réglages secrets, ses versions suivantes aussi, "
                      "et pourra les envoyer sur Internet.")
def _validate(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    if ctx.subject not in s.apps:
        raise Refused("Cette app n'est pas (encore) dans sa vie : « Recharger » l'y fait entrer.")
    return Done(drafts=(_vouch(s, ctx),), message="Validée : elle lit ses réglages secrets, et ses prochaines "
                                                  "versions s'installeront sans accord.")


@FORGE.action("mefiance", title="Ne plus lui faire confiance", args=NoArgs, emits=[SWITCHED], subject="app",
              order=13, description="Ses secrets ne lui sont plus lisibles et sa promotion tombe ; sa prochaine "
              "version attendra de nouveau ton accord.",
              available=lambda s, frame, key: (a := _in_life(s, key)) is not None and trusted(a),
              confirm="Retirer ta confiance à cette app ?")
def _distrust(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    if ctx.subject not in s.apps:
        raise Refused("Cette app n'est pas (encore) dans sa vie.")
    return Done(drafts=(SWITCHED.draft(app=ctx.subject, state="untrusted", reason="opérateur"),),
                message="Confiance retirée : ses secrets ne lui sont plus lisibles.")


FORGE.action("activer", title="Activer", args=NoArgs, emits=[SWITCHED], subject="app", order=10,
             description="Elle tournera de nouveau à son agenda (le disjoncteur se referme).",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and (not a.enabled or bool(a.broken)),
             )(_switch("enabled", "Activée : elle tournera à son agenda."))
FORGE.action("arreter", title="Arrêter", args=NoArgs, emits=[SWITCHED], subject="app", order=11,
             description="Elle ne tourne plus (ses vues et réglages restent).",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and a.enabled and not a.broken,
             )(_switch("disabled", "Arrêtée."))
FORGE.action("promouvoir", title="Promouvoir", args=NoArgs, emits=[SWITCHED], subject="app", order=20,
             description="Ses outils servent aussi en conversation, pas seulement quand elle travaille (ses "
                         "versions suivantes gardent la promotion).",
             available=lambda s, frame, key: (a := _in_life(s, key)) is not None and not a.promoted,
             confirm="Promouvoir cette app ? Ses outils serviront en conversation, et ses secrets lui seront "
                     "lisibles (ses versions suivantes comprises).",
             )(_switch("promoted", "Promue : ses outils servent en conversation.", vouch=True))
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
    drafts = (written_draft(info, vouched=True),) if stale(s.apps.get(name), info) else ()
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
    draft = written_draft(info, vouched=True) if info is not None else \
        WRITTEN.draft(app=name, version=version, title=name)
    return Done(drafts=(draft,), message=f"Revenue à la version précédente (désormais version {version}).")


@FORGE.action("vider", title="Vider sa base", args=NoArgs, emits=[SWITCHED], subject="app", order=40,
              description="Efface tout ce qu'elle a rangé : les tables de sa base et api.kv_*. Son code et ses "
                          "réglages restent.",
              danger=True, confirm="Vider toute la base de cette app ?")
async def _reset(s: ForgeState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    name = ctx.subject
    _info(ctx, name)
    try:
        n = await _port(ctx).reset_storage(name)
    except ForgeRefused as exc:
        raise Refused(f"Impossible : {exc}") from exc
    drafts = (SWITCHED.draft(app=name, state="reset", reason=f"opérateur : base vidée ({n} lignes)"),) \
        if name in s.apps else ()
    return Done(drafts=drafts, message=f"Base vidée ({n} lignes).")


@FORGE.action("effacer", title="Effacer", args=NoArgs, emits=[SWITCHED], subject="app", order=50,
              description="Met l'app à la corbeille avec un export de sa base (restaurable à la main), supprime "
                          "sa base et la sort de sa vie.",
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


@FORGE.action("tester", title="Tester", args=TestForm, emits=[EMITTED, c.QUEUED], subject="app", order=60,
              fields=_test_fields,
              description="Lance une de ses fonctions maintenant et montre ce qu'elle rend (sans compter contre "
                          "elle ; une vue : son enveloppe est vérifiée). C'est un vrai passage : ce qu'elle range "
                          "reste dans sa base, ce qu'elle signale part dans sa file — sauf un événement d'exemple "
                          "(on_event), inventé.")
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
                            max_result=VIEW_MAX_BYTES, secrets=trusted(s.apps.get(name)))
        if not r.ok:
            return Done(message=f"{fn} : échec en {r.duration_ms} ms", tone="danger",
                        show=(_facts(r), failure_note(spec.label, r), *_logs(r)))
        blocks = decode_view(r.value, name, info, spec)
        verdict = summary(blocks) if not _invalid(blocks) else "enveloppe invalide"
        return Done(message=f"{fn} : {verdict} ({r.duration_ms} ms)", tone="danger" if _invalid(blocks) else "ok",
                    show=(_facts(r), *without_forms(blocks), *_logs(r)))
    call_args = {"name": args.get("name", ""), "args": args.get("args", {})} if fn == "action" else args
    app = s.apps.get(name)
    r = await port.call(name, fn, call_args, timeout_s=ACTION_TIMEOUT_S, secrets=trusted(app))
    # un vrai passage (ce qu'il range reste) : ce qu'il signale part aussi, sinon la nouveauté se perd en silence ;
    # un événement d'exemple est inventé (ADR 0105)
    p = params(frame.env.params_of("forge", frame.root))
    drafts = tuple(outcomes(name, app, [r], ctx.now, p, breaker=False, concern=concerns(frame, app))) \
        if app is not None and fn != "on_event" else ()
    shown: list[Block] = [_facts(r, sent=bool(drafts))]
    if r.ok:
        shown.append(Code(json.dumps(r.value, ensure_ascii=False, indent=2, default=str)[:20_000], title="Ce qu'elle rend"))
        if fn.startswith("action_") and not _is_answer(r.value):
            shown.append(Note("Une action doit rendre {\"ok\": vrai|faux, \"message\": \"…\"}.", tone="warn"))
    else:
        shown.append(Note(r.error, tone="danger", title="Échec"))
    return Done(drafts=drafts, message=f"{fn} : {'ok' if r.ok else 'échec'} en {r.duration_ms} ms",
                tone="ok" if r.ok else "danger", show=(*shown, *_logs(r)))


def _invalid(blocks: Sequence[Any]) -> bool:
    return len(blocks) == 1 and isinstance(blocks[0], Note) and blocks[0].tone == "danger"


def _is_answer(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("ok"), bool) and isinstance(value.get("message", ""), str)


def _facts(r: CallResult, *, sent: bool = False) -> Fields:
    """Ce qu'a donné l'appel ; ``sent`` : ses signaux et émissions sont partis (un vrai passage)."""
    pairs: list[tuple[str, Cell]] = [("issue", Badge("ok", "ok") if r.ok else Badge("échec", "danger")),
                                     ("durée", f"{r.duration_ms} ms"), ("tuée", "oui" if r.killed else "non")]
    if r.signals:
        pairs.append(("signaux (dans sa file)" if sent else "signaux (non journalisés)",
                      "; ".join(f"{t} ({p:.1f})" for t, p, _ in r.signals)))
    if r.emits:
        pairs.append(("émissions (journalisées)" if sent else "émissions (non journalisées)",
                      "; ".join(t for t, _ in r.emits)))
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
    """Les données d'une action, vérifiées au-delà du contrôle : présence, longueur, forme — la même vérification que
    les arguments d'un outil d'app (``ports.forge.check_args``, ADR 0105). Un formulaire envoie ce qu'on y a laissé :
    pas de défaut pour un champ vide, et les champs de la console (app, vue, action…) passent."""
    return check_args(action.specs, data, defaults=False, strict=False)


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
    r = await _port(ctx).call(name, action.function, payload, timeout_s=ACTION_TIMEOUT_S, secrets=trusted(app))
    p = params(frame.env.params_of("forge", frame.root))
    drafts = tuple(outcomes(name, app, [r], ctx.now, p, breaker=False,  # jamais compté contre l'app
                            concern=concerns(frame, app)))
    if not r.ok:
        return Done(drafts=drafts, message=f"L'action de l'app a échoué : {r.error}"[:MESSAGE_MAX], tone="danger")
    if not _is_answer(r.value):
        return Done(drafts=drafts, message="L'app n'a pas rendu {ok, message} : rien à dire de plus.", tone="warn")
    ok = r.value["ok"]
    message = str(r.value.get("message") or ("Fait." if ok else "L'app a refusé."))[:MESSAGE_MAX]
    return Done(drafts=drafts, message=message, tone="ok" if ok else "warn")


FORGE.action("agir", title="Agir", args=NoArgs, emits=[EMITTED, c.SIGNALED, c.QUEUED], fields=_act_fields,
             description="Renseigne les champs puis valide pour appliquer cette action dans l'app.")(_act)


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
    secret = any(fields[k].kind == "secret" for k in changed if k in fields)
    app = s.apps.get(name)
    drafts = (_vouch(s, ctx),) if secret and app is not None and not trusted(app) else ()
    return Done(drafts=drafts, message=f"Réglages enregistrés ({labels}) : lus au prochain appel de l'app."
                + (" Ses secrets lui sont confiés : elle est validée, ses versions suivantes aussi." if drafts else ""))


FORGE.action("regler", title="Enregistrer les réglages", args=NoArgs, emits=[SWITCHED], fields=_settings_fields,
             description="Les secrets laissés vides restent inchangés ; un champ vidé revient au défaut du "
                         "manifeste.")(_settle)


# ── Qui peut quoi, sur la page « Droits » (ADR 0133) ──────────────────────

#: une app sans projet, en mots : à toi seule, sans demander
ALONE_ROW = ("Toi et elle quand elle travaille seule", "toujours", "seule", "seule", "tous")
APP_COLUMNS = ("qui", "quand", "lecture", "action", "outils")
#: ce qu'aucune ligne n'ouvre pour une app
APP_FLOORS = ("jamais dans un salon, avec une inconnue, ni sans personne",
              "arrêtée, désactivée ou cassée : elle ne sert à personne",
              "en conversation, une app qui a des secrets seulement promue")


def _app_tools(port: Any, name: str) -> list[tuple[str, bool]]:
    info = port.info(name) if port is not None else None
    if info is None:
        return []
    return [*((f"{name}_{t.name}", t.reads) for t in info.tools), *(((f"{name}_pages", True),) if info.views else ())]


def _app_grants(s: ForgeState, frame: Frame, ctx: Any, audience: Any, kind: str) -> list[Grant]:
    """Ce qu'elle fait de chaque outil de ses apps devant cette audience, à ce moment : la ligne de son projet qui le
    concerne (ou, sans projet, toi seule)."""
    port = ctx.ports.get("forge")
    out = []
    for name, app in sorted(s.apps.items()):
        if app.held or not app.enabled or app.broken:
            continue
        rows, default = app_lines(frame, app)
        for tool, reads in _app_tools(port, name):
            got = verdict(rows, default, audience, kind, lambda a, t=tool: not a.tools or t in a.tools,
                          close=social_c.is_close(frame))
            if got is None:
                continue
            level = got.line.read if reads else got.line.act
            where = f"de son projet n° {app.project}" if app.project else "(une app sans projet)"
            out.append(Grant(f"project:{app.project}" if app.project else "forge:sans-projet", tool,
                             (("lit" if reads else "agit", POLICY_WORDS.get(level, level)),),
                             f"{why_words(got.index)} {where}",
                             href=Ref.subject("project", str(app.project), str(app.project), "acces")
                             if app.project else Ref.subject("app", name, app.title), closed=level == NO))
    return out


@FORGE.rights("apps", title="Apps sans projet", order=35, grants=_app_grants,
              description="Une app suit les lignes d'accès de son projet ; sans projet, elle est à toi seule "
                          "(ADR 0133).")
def _app_tables(s: ForgeState, frame: Frame, ctx: Any) -> list[RuleTable]:
    alone = sorted(app.title or name for name, app in s.apps.items() if not app.project)
    if not alone:
        return []
    return [RuleTable("forge:sans-projet", "Apps sans projet", APP_COLUMNS, (ALONE_ROW,),
                      ("Comportement par défaut", "toujours", "non", "non", "tous"), floors=APP_FLOORS,
                      note="Fixé : une app sans projet n'a pas de lignes à elle. " + ", ".join(alone) + ".")]
