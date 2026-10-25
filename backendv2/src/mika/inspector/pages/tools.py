"""Ses outils : ce qu'elle peut faire et avec qui, ce que tu prêtes à un agent (ADR 0064, 0122).

L'écran lit ce que le moteur exécute : le registre (ses outils, et ceux que des
sources dynamiques y ajoutent) et la porte d'offre du pipeline
(``runtime.tools.offer``), appliquée à des audiences de synthèse — jamais une
recopie de ses règles. « Ce qu'elle peut faire » est une grille : ses familles
d'outils en lignes, leurs outils dessous, les situations en colonnes. Un
opérateur y décoche un outil pour le lui retirer dans une situation ; sa fiche
le règle plus finement (sous la main ou à chercher, quand le fournisseur sait
différer). Jamais une règle ne l'offre là où le code ne l'offre pas.
"""

from __future__ import annotations

import inspect
import re
import secrets as _secrets
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector import mcp as console_mcp
from mika.inspector import names
from mika.inspector.catalog import Panel
from mika.inspector.mcp import TOOLS as CONSOLE_TOOLS
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.clock import DAY
from mika.kernel.episode import EpisodePolicy
from mika.kernel.faculty import ToolSpec
from mika.kernel.frame import Audience
from mika.kernel.inspect import (
    Badge,
    Column,
    Disclosure,
    Fields,
    Note,
    Param,
    Ref,
    Row,
    Table,
    Text,
    When,
    is_table_choice,
    num_fr,
    paginate,
    read_params,
)
from mika.runtime import operations as ops
from mika.runtime.tools import (
    ASK,
    HAND,
    OFF,
    RULES,
    acting,
    admitted,
    catalogue,
    declare,
    deferred,
    defers_tools,
    offer,
    rule_of,
)
from mika.vocab.episodes import Kind
from mika.vocab.privacy import EVERYTHING, ChannelTrust

#: ce qui est compté comme récent (les traces d'épisode ne gardent pas plus)
USAGE_DAYS = 14
#: la liste que lit la console en MCP, par pages (la grille, elle, tient en une page)
TOOLS_PAGE = 24
BASE = f"{PREFIX}/outils"
#: ce que la fiche d'un outil garde de la grille pour y revenir (plus le choix « Tableau », ``is_table_choice``)
CATALOG_PARAMS = ("q", "lot", "page")
#: la règle d'un outil sur sa fiche, situation par situation : « r.<situation> » ; « » : ce que prévoit le code
RULE_FIELD = "r."
#: dans la grille, la case d'un outil dans une situation (« <situation>:<outil> », cochée s'il y est offert), et les
#: outils que la grille montrait (une recherche en cache : ceux-là seuls changent)
CELL_FIELD, SEEN_FIELD = "o", "vu"
#: ce qu'a fait une règle, dans le message qui suit l'enregistrement
DONE = {None: "rendu comme prévu", OFF: "retiré", HAND: "mis sous la main", ASK: "mis à chercher"}
#: les situations rangées par ce qui se passe, en tête de la grille ; les autres : elle travaille seule
MOMENTS = {Kind.REPLY: "Elle répond à…", Kind.INITIATIVE: "D'elle-même"}
ALONE = "Elle travaille seule sur…"
#: les adresses de ce qu'elle expose en MCP (``inspector.mcp``, ``app/lending.py``), et la machine qui les sert
CONSOLE_ADDRESS, LENT_ADDRESS, LOCAL_ORIGIN = console_mcp.PREFIX, "/mcp/pret", "http://127.0.0.1:8001"
#: ce que la console en MCP sert au-delà de ses pages, en mots
SERVED_PARTS = ((console_mcp.VIEWS, "Les vues de ses facultés (ses souvenirs, ses pensées, ses liens…)"),
                (console_mcp.SUBJECTS, "Les fiches (une personne, un but, une app…) et la recherche"),
                (console_mcp.WHY, "« Pourquoi a-t-elle dit ça ? »"))


@dataclass(frozen=True, slots=True)
class Situation:
    """Une audience type et la sorte d'épisode où elle se trouve : de quoi demander à la porte d'offre ce
    qu'elle y aurait en main. ``short`` : son nom sous l'en-tête de la grille (« Elle répond à… » « un salon »)."""

    key: str
    short: str
    label: str
    kind: str
    audience: Audience
    #: ce qu'elle vit maintenant, pour une condition qui lit son journal (``fits`` : les lignes d'un projet, ADR
    #: 0133) ; ``None`` : une situation type, hors de toute vie
    frame: Any = None


def _person(key: str, *, trust: str, owner: bool = False, public: bool = False, room: str | None = None,
            channel: str = "web") -> Audience:
    level = int(EVERYTHING.level) if owner else 0
    return Audience(persons=(f"situation:{key}",), channel=channel, room=room, public=public, level=level,
                    witness_level=level, private_ok=owner, trust=trust, certainty=1.0 if owner else 0.0,
                    owner=owner, tied_level=level, untied_level=level)


#: personne n'écoute (un pas, une exécution, une tâche) : l'audience que le moteur leur donne
_NOBODY = Audience(persons=(), channel="internal", public=False, level=int(EVERYTHING.level),
                   witness_level=int(EVERYTHING.witness_level), private_ok=True,
                   trust=ChannelTrust.INTERNAL.value, owner=True, tied_level=int(EVERYTHING.tied_level),
                   untied_level=int(EVERYTHING.untied_level))

SITUATIONS: tuple[Situation, ...] = (
    Situation("proprietaire", "sa propriétaire", "Elle répond à sa propriétaire, en privé", Kind.REPLY,
              _person("proprietaire", trust=ChannelTrust.AUTHENTICATED.value, owner=True)),
    Situation("compte", "un compte", "Elle répond à une personne qui a un compte, en tête-à-tête", Kind.REPLY,
              _person("compte", trust=ChannelTrust.AUTHENTICATED.value)),
    Situation("inconnue", "une inconnue", "Elle répond à une inconnue (un moyen de communication sans compte)", Kind.REPLY,
              _person("inconnue", trust=ChannelTrust.ACCOUNT.value, channel="external")),
    Situation("salon", "un salon", "Elle répond dans un salon, devant plusieurs personnes", Kind.REPLY,
              _person("salon", trust=ChannelTrust.PUBLIC.value, public=True, room="salon")),
    Situation("initiative", "à sa propriétaire", "Elle écrit d'elle-même à sa propriétaire", Kind.INITIATIVE,
              _person("initiative", trust=ChannelTrust.AUTHENTICATED.value, owner=True)),
    Situation("pas", "un but", "Elle avance seule sur un de ses buts", Kind.STEP, _NOBODY),
    Situation("projet", "un projet", "Elle travaille seule sur un projet", Kind.WORK, _NOBODY),
    Situation("tache", "un brouillon", "Elle prépare seule un brouillon de mail", Kind.TASK, _NOBODY),
)


def situations(ui: Any) -> list[Situation]:
    """Les situations dont la sorte d'épisode existe dans cette composition, avec ce qu'elle vit maintenant."""
    policies, frame = ui.kernel.runner.policies, ui.kernel.mind.frame()
    return [replace(s, frame=frame) for s in SITUATIONS if s.kind in policies]


def rules(ui: Any, s: Situation) -> Mapping[str, str]:
    """Les règles d'un opérateur pour cette situation, telles que le pipeline les lit à chaque épisode."""
    return ui.kernel.runner.rules_of(s.kind, s.audience) or {}


def offered_in(ui: Any, s: Situation, ruled: bool = True) -> dict[str, ToolSpec]:
    """Ce que la porte d'offre du pipeline lui donnerait dans cette situation ; ``ruled`` faux : ce que le code lui
    offre, avant les règles d'un opérateur."""
    return offer(ui.kernel.registry.tools, ui.kernel.runner.policies[s.kind], s.kind, s.audience,
                 rules=rules(ui, s) if ruled else None, frame=s.frame)


def in_hand(ui: Any, policy: EpisodePolicy) -> frozenset[str] | None:
    """Les lots en main par défaut (``None`` : tout) — un fournisseur qui ne sait pas différer reçoit tout."""
    if policy.role is None or not defers_tools(ui.kernel.runner.gateway, policy.role):
        return None
    return policy.core_bundles


def why_not(spec: ToolSpec, policy: EpisodePolicy, s: Situation, ruled: Mapping[str, str] | None = None) -> str:
    """Pourquoi la porte ne l'offre pas ici, en mots (vide : elle l'offre). Un test vérifie que ce récit et la
    porte disent la même chose, situation par situation."""
    if s.kind not in spec.episodes:
        return "pas prévu dans cette situation"
    if not admitted(policy.tool_bundles, spec.bundle):
        return "sa famille n'est pas prévue dans cette situation"
    if spec.owner_only and not s.audience.owner:
        return "réservé à sa propriétaire"
    if spec.when is not None or spec.fits is not None:
        try:
            ok = (spec.when is None or spec.when(s.audience) is True) and (
                spec.fits is None or spec.fits(s.audience, s.kind, s.frame) is True)
        except Exception:  # noqa: BLE001 — la porte compte une panne comme un refus
            ok = False
        if not ok:
            return condition(spec) or "sa condition n'est pas remplie"
    if rule_of(spec, ruled) == OFF:
        return "retiré par un opérateur"
    return ""


def condition(spec: ToolSpec) -> str:
    """La condition d'offre d'un outil (``when=``, ou ``fits=``), en mots : la première phrase de sa docstring."""
    gate = spec.when if spec.when is not None else spec.fits
    if gate is None:
        return ""
    doc = inspect.getdoc(gate) or ""
    return " ".join(doc.split("\n\n")[0].split())


def origin(ui: Any, spec: ToolSpec) -> tuple[str, str]:
    """(libellé, ton) d'où vient un outil : défini dans le code, ou ajouté par une source dynamique."""
    if ui.kernel.registry.is_dynamic(spec.name):
        return "venu d'ailleurs", "info"
    return "dans son code", "muted"


def _usage(ui: Any) -> Mapping[str, Any]:
    traces = getattr(ui.kernel, "traces", None)
    if traces is None:
        return {}
    return traces.tool_usage(ui.now() - USAGE_DAYS * DAY)


def _kinds(spec: ToolSpec) -> str:
    return ", ".join(names.kind(k) for k in sorted(spec.episodes)) or "—"


def _tool_ref(name: str, text: str | None = None, context: Mapping[str, str] | None = None) -> Ref:
    kept = tuple((k, v) for k, v in (context or {}).items() if k in CATALOG_PARAMS or is_table_choice(k, v))
    return Ref("local", f"{BASE}/tous", text or name, (*kept, ("outil", name)))


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _lead(text: str, limit: int = 150) -> str:
    """Ce qu'il fait, en une phrase : la première de sa description, coupée à un mot."""
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def _params(ui: Any) -> tuple[Param, ...]:
    return (Param("q", "Chercher un outil", "search", placeholder="un nom, ce qu'il fait…"),)


def _prompt(ui: Any, s: Situation) -> str:
    """Ce que son prompt dit de ses outils dans cette situation, mot pour mot."""
    policy = ui.kernel.runner.policies[s.kind]
    offered = list(offered_in(ui, s).values())
    return "\n\n".join(filter(None, (acting(offered) if policy.visible else "",
                                     catalogue(offered, in_hand(ui, policy), ui.kernel.registry.bundles,
                                               rules(ui, s)))))


def _summary(s: Situation, cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """La case d'une famille dans une situation : tous ses outils, une partie, aucun — et ce qu'un opérateur a
    retiré."""
    total = len(cells)
    usable = sum(1 for c in cells if c["state"] in ("on", "ask", "fixed"))
    off = sum(1 for c in cells if c["state"] == "off")
    asked = usable > 0 and all(c["state"] == "ask" for c in cells if c["state"] in ("on", "ask", "fixed"))
    removed = f", {off} retiré{'s' if off > 1 else ''} par un opérateur" if off else ""
    if usable == total:
        state, text, title = "on", "✓", f"{s.label} : tous ses outils"
    elif usable:
        state, text, title = "part", f"{usable}/{total}", f"{s.label} : {usable} de ses {total} outils{removed}"
    elif off:
        state, text, title = "off", "✕", f"{s.label} : retiré par un opérateur"
    else:
        state, text, title = "none", "—", f"{s.label} : pas prévu"
    return {"state": state, "text": text, "title": title, "ask": asked, "off": bool(off) and usable > 0}


def can_do(ui: Any, query: str = "", lot: str = "") -> dict[str, Any]:
    """La grille « Ce qu'elle peut faire » : ses familles d'outils en lignes (leurs outils dessous), les situations
    en colonnes. Une case dit ce que la porte d'offre lui donne : offert (coché ; à chercher, si le fournisseur
    diffère), retiré par un opérateur (décoché), pas prévu par le code (un tiret, et pourquoi) ; un outil qui clôt
    sa boucle ne se retire pas. ``query`` : une recherche ; ``lot`` : une seule famille."""
    registry, policies = ui.kernel.registry, ui.kernel.runner.policies
    sits = situations(ui)
    by_code = {s.key: offered_in(ui, s, ruled=False) for s in sits}
    ruled = {s.key: rules(ui, s) for s in sits}
    cores = {s.key: in_hand(ui, policies[s.kind]) for s in sits}
    usage = _usage(ui)
    terms = _fold(query).split()
    specs = [spec for spec in sorted(registry.tools.values(), key=lambda x: x.name)
             if (not lot or spec.bundle == lot)
             and all(t in _fold(f"{spec.name} {spec.description} {ui.names.bundle(spec.bundle)}") for t in terms)]
    keep = {k: v for k, v in (("q", query), ("lot", lot)) if v}
    where: dict[str, str] = {}
    families: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        cells: list[dict[str, Any]] = []
        for s in sits:
            rule = rule_of(spec, ruled[s.key])
            if spec.name not in by_code[s.key]:
                cell: dict[str, Any] = {"state": "none", "why": why_not(spec, policies[s.kind], s)}
            elif spec.ends_loop:
                cell = {"state": "fixed"}
            elif rule == OFF:
                cell = {"state": "off"}
            else:
                cell = {"state": "ask" if deferred(spec, cores[s.key], ruled[s.key]) else "on", "set": bool(rule)}
            cells.append({**cell, "situation": s.label, "value": f"{s.key}:{spec.name}"})
        where[spec.name] = "; ".join(s.label for s, c in zip(sits, cells, strict=True)
                                     if c["state"] not in ("none", "off")) or "nulle part"
        used = usage.get(spec.name)
        families.setdefault(spec.bundle, []).append({
            "name": spec.name, "lead": _lead(spec.description), "description": spec.description, "cells": cells,
            "href": f"{BASE}/tous?" + urlencode({**keep, "outil": spec.name}),
            "calls": used.calls if used else 0, "failures": used.failures if used else 0})
    rows = []
    for bundle, tools in families.items():
        summary = [_summary(s, [t["cells"][i] for t in tools]) for i, s in enumerate(sits)]
        rows.append({"bundle": bundle, "label": ui.names.bundle(bundle), "tools": tools, "cells": summary,
                     "open": bool(terms or lot), "external": any(registry.is_dynamic(t["name"]) for t in tools)})
    rows.sort(key=lambda r: _fold(r["label"]))
    groups: list[dict[str, Any]] = []
    starts = set()  # la première colonne de chaque groupe : un filet la sépare de la précédente
    for i, s in enumerate(sits):
        label = MOMENTS.get(s.kind, ALONE)
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "count": 0})
            starts.add(i)
        groups[-1]["count"] += 1
    removed = sum(1 for s in sits for name, r in ruled[s.key].items()
                  if r == OFF and name in by_code[s.key] and not by_code[s.key][name].ends_loop)
    return {
        "situations": sits, "groups": groups, "starts": starts, "rows": rows, "specs": specs, "where": where,
        "query": query, "lot": lot, "lot_label": ui.names.bundle(lot) if lot else "",
        "total": len(registry.tools), "families": len({x.bundle for x in registry.tools.values()}),
        "shown": len(specs), "removed": removed, "ruled": sum(len(r) for r in ruled.values()),
        "failures": sum(u.failures for n, u in usage.items() if n in registry.tools),
        "any_ask": any(c["state"] == "ask" for r in rows for t in r["tools"] for c in t["cells"]),
        "prompts": [{"label": s.label, "text": _prompt(ui, s)} for s in sits],
        "action": f"{BASE}/regler", "cell_field": CELL_FIELD, "seen_field": SEEN_FIELD,
    }


@TABS.tab("outils.tous", title="Ce qu'elle peut faire",
          description="Ses outils famille par famille, et les situations où elle peut s'en servir. Décoche une case "
                      "pour lui retirer un outil dans cette situation ; un outil ouvre sa fiche.")
async def all_tools(ui: Any, request: Request) -> Any:
    name = str(request.query_params.get("outil", "") or "")
    if name:
        return _fiche(ui, request, name)
    params = _params(ui)
    values, notes = read_params(params, request.query_params)
    grid = can_do(ui, str(values.get("q") or ""), str(request.query_params.get("lot", "") or ""))
    # la même chose en liste, pour qui lit sans panneau (la console en MCP) : la grille est le panneau
    usage = _usage(ui)
    ctx = ui.inspection.context(request.query_params)
    page, pager = paginate(grid["specs"], ctx.pager(size=TOOLS_PAGE))
    rows = []
    for s in page:
        used = usage.get(s.name)
        calls = Text(num_fr(used.calls), "num", "danger" if used.failures * 2 > used.calls else "",
                     hint=f"{used.failures} en échec") if used else Text("0", "num", "muted")
        rows.append(Row((Text(s.name, "mono"), Text(ui.names.bundle(s.bundle)), Text(s.description, clamp=220),
                         Text(grid["where"][s.name]), calls), href=_tool_ref(s.name, context=request.query_params)))
    blocks: list[Any] = [
        *[Note(n, "warn") for n in notes],
        Table((Column("Outil", "fit", role="title"), Column("Famille", "fit"), Column("Ce qu'il fait", role="body"),
               Column("Où elle peut s'en servir"), Column(f"Appels sur {USAGE_DAYS} j", "num")),
              tuple(rows), title="Ses outils", empty="Aucun outil ne correspond.", pager=pager),
    ]
    return {"blocks": blocks, "filters": params, "panel": Panel("handmade/outils/peut.html", grid)}


def _fiche(ui: Any, request: Request, name: str) -> Any:
    registry = ui.kernel.registry
    context = {k: v for k, v in request.query_params.items() if k in CATALOG_PARAMS or is_table_choice(k, v)}
    back = [("Ce qu'elle peut faire", f"{BASE}/tous" + ("?" + urlencode(context) if context else ""))]
    spec = registry.tools.get(name)
    if spec is None:
        return {"blocks": [Note(f"Aucun outil ne s'appelle « {name} ».", "warn")], "crumbs": back}
    label, tone = origin(ui, spec)
    policies = ui.kernel.runner.policies
    where = []
    for s in situations(ui):
        policy, ruled = policies[s.kind], rules(ui, s)
        if spec.name not in offered_in(ui, s, ruled=False):
            where.append({"key": s.key, "label": s.label, "state": "none", "why": why_not(spec, policy, s)})
            continue
        core = in_hand(ui, policy)
        rule = rule_of(spec, ruled)
        planned = f" ({'à chercher' if deferred(spec, core) else 'sous la main'})" if core is not None else ""
        choices = [("", f"Oui, comme prévu{planned}")]
        if core is not None:
            choices += [(HAND, "Oui, toujours sous la main"), (ASK, "Oui, à chercher quand il lui faut")]
        choices.append((OFF, "Non, retiré"))
        where.append({"key": s.key, "label": s.label, "locked": spec.ends_loop, "rule": rule or "",
                      "state": "off" if rule == OFF else ("ask" if deferred(spec, core, ruled) else "on"),
                      "choices": choices, "field": f"{RULE_FIELD}{s.key}"})
    reserved = ("à sa propriétaire (et quand elle travaille, personne n'écoutant)" if spec.owner_only else "non")
    dynamic = registry.is_dynamic(spec.name)
    pairs: list[tuple[str, Any]] = [
        ("nom", Text(spec.name, "mono")),
        ("d'où il vient", Badge(label, tone)),
        ("faculté", ui.names.faculty(spec.owner)),
        ("famille", Text(ui.names.bundle(spec.bundle), secondary=registry.bundles.get(spec.bundle, ""))),
        ("ce qu'il fait", Text(spec.description)),
        ("sortes d'épisodes", _kinds(spec)),
        ("réservé", reserved),
        ("condition d'offre", condition(spec) or "—"),
        ("vérifié à l'exécution", spec.rule or "—"),
        ("appels par épisode", str(spec.max_calls_per_episode) if spec.max_calls_per_episode else "sans plafond"),
        ("conclut la boucle", "oui" if spec.ends_loop else "non"),
        ("ce qui se règle", "où elle s'en sert (plus haut) ; il vient d'un service ou d'une app, qui se règle sur sa "
                            "fiche (Venus d'ailleurs)" if dynamic else
                            "où elle s'en sert (plus haut) ; son code, non"),
    ]
    argument_table = Table(("argument", Column("type", "fit"), Column("requis", "fit"), "ce que c'est",
                            Column("contraintes", "fit")), tuple(arguments(schema_of(spec))),
                           title="Ses arguments", empty="Aucun argument.")
    traces = getattr(ui.kernel, "traces", None)
    uses = traces.tool_uses(spec.name, 20) if traces is not None else []
    blocks: list[Any] = [
        Table((Column("quand", "fit"), Column("épisode", "fit"), Column("issue", "fit"), ""), tuple(
            Row((When(u.at), names.kind(u.kind),
                 Badge("réussi" if u.ok else ("refusé" if not u.executed else "échec"),
                       "ok" if u.ok else "warn" if not u.executed else "danger"),
                 Ref("episode", u.correlation, "relire", (("onglet", "outils"),))))
            for u in uses), title="Ses derniers appels", empty=f"Aucun appel depuis {USAGE_DAYS} jours."),
        Disclosure("Arguments et règles d’utilisation", (argument_table, Fields(tuple(pairs), title="Règles et provenance",
                                                                               columns=2))),
    ]
    return {"blocks": blocks, "crumbs": back, "panel": Panel("handmade/outils/outil.html", {
        "page_heading": spec.name, "page_subtitle": spec.description,
        "tool_name": spec.name, "tool_origin": label, "tool_tone": tone, "tool_dynamic": dynamic,
        "tool_family": ui.names.bundle(spec.bundle), "tool_reserved": spec.owner_only,
        "where": where, "editable": any(w["state"] != "none" and not w.get("locked") for w in where),
        "fine": any(len(w.get("choices", ())) > 2 for w in where),
        "context": context, "action": f"{BASE}/regler",
    })}


def schema_of(spec: ToolSpec) -> Mapping[str, Any]:
    """Le schéma de ses arguments, tel que le modèle le reçoit."""
    decl = declare([spec])
    return decl[0].schema if decl else {}


def _type(prop: Mapping[str, Any]) -> str:
    if "type" in prop:
        t = prop["type"]
        return " ou ".join(t) if isinstance(t, list) else str(t)
    for key in ("anyOf", "oneOf"):
        if isinstance(prop.get(key), list):
            return " ou ".join(sorted({_type(p) for p in prop[key] if isinstance(p, Mapping)}))
    if "$ref" in prop:
        return "objet"
    if "enum" in prop:
        return "choix"
    return "—"


def _constraints(prop: Mapping[str, Any]) -> str:
    out = []
    if isinstance(prop.get("enum"), list):
        out.append("parmi " + ", ".join(str(v) for v in prop["enum"][:8]))
    for key, word in (("minimum", "≥"), ("maximum", "≤"), ("minLength", "≥ car."), ("maxLength", "≤ car."),
                      ("minItems", "≥ él."), ("maxItems", "≤ él.")):
        if key in prop:
            out.append(f"{word} {prop[key]}")
    if "default" in prop:
        out.append(f"défaut {prop['default']!r}")
    return " · ".join(out)


def arguments(schema: Mapping[str, Any]) -> list[Row]:
    """Une ligne par argument de premier niveau : nom, type, requis, description, contraintes."""
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    if not isinstance(props, Mapping):
        return []
    required = set(schema.get("required") or ())
    rows = []
    for key, prop in props.items():
        if not isinstance(prop, Mapping):
            continue
        rows.append(Row((Text(str(key), "mono"), _type(prop), "oui" if key in required else "non",
                         Text(str(prop.get("description") or prop.get("title") or ""), clamp=200),
                         _constraints(prop))))
    return rows


def _grid_changes(ui: Any, lists: Mapping[str, Sequence[Any]]) -> dict[str, dict[str, str | None]]:
    """Ce que la grille change : un outil montré (``vu``) et décoché est retiré ; recoché, il revient (sa place
    choisie sur sa fiche reste). Seuls comptent les outils que le code offre ici et qui ne closent pas la boucle."""
    seen = {str(x) for x in lists.get(SEEN_FIELD, [])}
    on = {str(x) for x in lists.get(CELL_FIELD, [])}
    changes: dict[str, dict[str, str | None]] = {}
    for s in situations(ui):
        ruled = rules(ui, s)
        for name, spec in offered_in(ui, s, ruled=False).items():
            if name not in seen or spec.ends_loop:
                continue
            kept, off = f"{s.key}:{name}" in on, rule_of(spec, ruled) == OFF
            if kept == off:
                changes.setdefault(s.key, {})[name] = None if kept else OFF
    return changes


def _fiche_changes(ui: Any, name: str, data: Mapping[str, Any]) -> dict[str, dict[str, str | None]]:
    """Ce que la fiche d'un outil change, situation par situation (« r.<situation> ») : ce que prévoit le code
    n'est pas une règle ; tout en main (un fournisseur qui ne diffère pas), seul « retiré » en est une."""
    spec = ui.kernel.registry.tools.get(name)
    changes: dict[str, dict[str, str | None]] = {}
    if spec is None or spec.ends_loop:
        return changes
    for s in situations(ui):
        chosen = str(data.get(f"{RULE_FIELD}{s.key}", "\0"))
        if chosen not in ("", *RULES) or name not in offered_in(ui, s, ruled=False):
            continue
        core = in_hand(ui, ui.kernel.runner.policies[s.kind])
        code = ASK if deferred(spec, core) else HAND
        changes[s.key] = {name: None if chosen in ("", code) or (core is None and chosen != OFF) else chosen}
    return changes


async def rules_post(ui: Any, request: Request) -> Response:
    """Ses outils réglés (``Settings.save_tool_rules``), audités situation par situation. Depuis la grille : ses
    cases ; depuis la fiche d'un outil (``outil``) : sa place dans chaque situation ; « Tout remettre comme prévu »
    efface toutes les règles. Un outil que le code n'offre pas dans une situation, ou qui clôt la boucle, est
    ignoré : une règle ne fait que restreindre."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    data, lists = got if got is not None else ({}, {})
    tool = str(data.get("outil", ""))
    keep = {k: str(data[k]) for k in ("q", "lot") if data.get(k)}
    back = {**keep, **({"outil": tool} if tool else {})}
    settings = ui.deps.settings
    if got is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif settings is None:
        ui.flash(token, "warn", "Les réglages ne sont pas joignables : rien n'a été enregistré.")
    else:
        sits = {s.key: s for s in situations(ui)}
        if data.get("faire") == "remettre":
            changes = {k: dict.fromkeys(rules(ui, s)) for k, s in sits.items()}
        elif tool:
            changes = _fiche_changes(ui, tool, data)
        else:
            changes = _grid_changes(ui, lists)
        done: list[str] = []
        for key, wanted in changes.items():
            before = dict(rules(ui, sits[key]))
            kept = await settings.save_tool_rules(key, wanted)
            moved = sorted(n for n in {*before, *kept} if before.get(n) != kept.get(n))
            if moved:
                await ops.audit(ui.kernel, "console.outils.regler", by=account.handle, subject_kind="situation",
                                subject=key)
                said = sits[key].label[0].lower() + sits[key].label[1:]
                done += [f"{n} {DONE[kept.get(n)]} ({said})" for n in moved]
        if done:
            more = f", et {len(done) - 6} autres" if len(done) > 6 else ""
            ui.flash(token, "ok", "; ".join(done[:6]) + more + ". Vaut dès son prochain épisode.")
        else:
            ui.flash(token, "info", "Rien n'a changé.")
    return secure(RedirectResponse(f"{BASE}/tous?" + urlencode({**back, "flash": token}), status_code=303))


@TABS.tab("outils.expose", title="Prêter à un agent",
          description="Ce que tu laisses voir ou faire à un agent (ton Claude Code, par exemple) : la console en "
                      "lecture, et des points qui lui prêtent quelques-uns de ses outils. Rien ne s'ouvre sans jeton, "
                      "et seulement depuis cette machine, sauf la console si tu l'ouvres au réseau.")
async def exposed(ui: Any, request: Request) -> Any:
    relay, settings, lending = ui.deps.relay, ui.deps.settings, ui.deps.lending
    account = ui.operator(request)
    try:
        token = bool(settings.console_mcp_token()) if settings is not None else False
        network = token and settings.console_mcp_network()
        chosen = settings.console_mcp_served() if settings is not None else None
        entries = settings.lent() if settings is not None else {}
    except Exception:  # noqa: BLE001 — un réglage illisible : « absent », jamais une page cassée
        token, network, chosen, entries = False, False, None, {}
    served = set(console_mcp.DEFAULT_SERVED if chosen is None else chosen)
    pages = [{"key": k, "title": ui.builtins[k].title if k in ui.builtins else k, "on": k in served,
              "default": k in console_mcp.PAGES} for k in console_mcp.SERVABLE]
    parts = [{"key": k, "title": title, "on": k in served} for k, title in SERVED_PARTS]
    points = []
    for name, entry in sorted(entries.items()):
        offered = lending.offered(entry) if lending is not None else {}
        recent = lending.recent(name) if lending is not None else []
        points.append({
            "name": name, "address": f"{LENT_ADDRESS}/{name}", "writes": bool(entry.get("writes")),
            "tools": sorted(entry.get("tools") or ()), "served": sorted(offered), "hint": entry.get("hint") or "",
            "by": entry.get("by") or "", "at": ui.when(int(entry.get("created_at") or 0)) if entry.get("created_at") else "",
            "token_at": ui.when(int(entry["token_at"])) if entry.get("token_at") else "",
            "last": {"at": ui.when(recent[0].at), "tool": recent[0].tool, "ok": recent[0].ok} if recent else None,
            "href": f"{BASE}/expose?" + urlencode({"pret": name}),
        })
    editing = _editor(ui, request, entries, lending, account)
    shown = ui.pop_reveal(str(request.query_params.get("montrer", "")), account.handle if account else "")
    return {"blocks": [], "panel": Panel("handmade/outils/expose.html", {
        "relay_sessions": len(relay) if relay is not None else 0, "console_token": token, "served_pages": pages,
        "console_network": network, "console_url": _console_url(request, network),
        "parts": parts, "console_tools": CONSOLE_TOOLS, "points": points, "editing": editing, "shown": shown,
        "action": f"{BASE}/exposer", "console_address": CONSOLE_ADDRESS, "lent_address": LENT_ADDRESS,
    })}


def _editor(ui: Any, request: Request, entries: Mapping[str, Mapping[str, Any]], lending: Any,
            account: Any) -> dict[str, Any] | None:
    """Le point qu'on règle (``?pret=<nom>``) ou qu'on déclare (``?pret=`` vide, ``?nouveau``) : ce qu'il peut
    prêter, par famille, coché s'il le prête."""
    query = request.query_params
    name = str(query.get("pret", "") or "")
    if lending is None or (not name and "nouveau" not in query) or (name and name not in entries):
        return None
    entry = entries.get(name, {})
    by = str(entry.get("by") or (account.handle if account else ""))
    chosen = set(entry.get("tools") or ())
    families: dict[str, list[dict[str, Any]]] = {}
    for spec in sorted(lending.candidates(by).values(), key=lambda x: x.name):
        families.setdefault(spec.bundle, []).append({"name": spec.name, "description": spec.description,
                                                     "on": spec.name in chosen})
    gone = sorted(chosen - {t["name"] for rows in families.values() for t in rows})
    return {"name": name, "new": not name, "writes": bool(entry.get("writes")), "by": by, "gone": gone,
            "families": [{"label": ui.names.faculty(b), "bundle": b, "tools": rows}
                         for b, rows in sorted(families.items(), key=lambda kv: ui.names.faculty(kv[0]).casefold())],
            "recent": [{"at": ui.when(c.at), "tool": c.tool, "ok": c.ok} for c in lending.recent(name)] if name else []}


def _console_url(request: Request, network: bool) -> str:
    """Où un agent joint la console : par l'adresse où on la lit si elle est ouverte au réseau (ADR 0127), sinon
    sur cette machine. La barre finale évite la redirection vers ``/mcp/console/``."""
    origin = f"{request.url.scheme}://{request.url.netloc}" if network else LOCAL_ORIGIN
    return f"{origin}{CONSOLE_ADDRESS}/"


def _lent_url(name: str) -> str:
    """Un point de prêt ne sert que cette machine (ADR 0122)."""
    return f"{LOCAL_ORIGIN}{LENT_ADDRESS}/{name}"


def _command(name: str, url: str, token: str) -> str:
    return f"claude mcp add --transport http {name} {url} --header \"Authorization: Bearer {token}\""


async def expose_post(ui: Any, request: Request) -> Response:
    """Prêter à un agent : le jeton de la console en MCP et ce qu'elle sert ; ses points de prêt — déclarés,
    réglés, leur jeton, retirés. Tout est audité ; un jeton neuf se montre une seule fois, à qui l'a créé."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    settings, lending = ui.deps.settings, ui.deps.lending
    back = f"{BASE}/expose"
    query: dict[str, str] = {}
    if got is None or account is None or settings is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
        return secure(RedirectResponse(f"{back}?flash={token}", status_code=303))
    data, lists = got
    what, name = str(data.get("faire", "")), str(data.get("nom", "")).strip().lower()
    now = ui.now()
    audit, subject = "", ""
    try:
        if what == "console_jeton":
            fresh = await settings.new_console_mcp_token()
            query["montrer"] = ui.reveal(account.handle, {"title": "Le jeton de la console en MCP", "token": fresh,
                                                          "command": _command("mika", _console_url(
                                                              request, settings.console_mcp_network()), fresh)})
            ui.flash(token, "ok", "Jeton neuf : l'ancien ne vaut plus.")
            audit, subject = "console.mcp.jeton", "console"
        elif what == "console_fermer":
            closed = await settings.revoke_console_mcp_token()
            ui.flash(token, "ok" if closed else "info", "La console en MCP est fermée : son adresse répond 404."
                     if closed else "Elle n'avait pas de jeton.")
            audit, subject = ("console.mcp.fermer", "console") if closed else ("", "")
        elif what in ("console_reseau_ouvrir", "console_reseau_fermer"):
            opened = what == "console_reseau_ouvrir"
            await settings.save_console_mcp_network(opened)
            ui.flash(token, "ok", f"La console en MCP répond au réseau : {_console_url(request, True)}, avec son jeton."
                     if opened else "La console en MCP ne répond plus qu'à cette machine.")
            audit, subject = f"console.mcp.reseau.{'ouvrir' if opened else 'fermer'}", "console"
        elif what == "console_servir":
            picked = [str(k) for k in lists.get("servi", [])]
            default = set(picked) == set(console_mcp.DEFAULT_SERVED)
            await settings.save_console_mcp_served(None if default else picked)
            ui.flash(token, "ok", "Ce que sert la console en MCP est enregistré : l'agent le voit à sa requête suivante.")
            audit, subject = "console.mcp.servir", "console"
        elif what in ("pret_declarer", "pret_regler"):
            entries = settings.lent()
            if what == "pret_declarer" and name in entries:
                raise ValueError(f"un point s'appelle déjà « {name} »")
            if what == "pret_regler" and name not in entries:
                raise ValueError("ce point n'existe plus")
            by = str(entries.get(name, {}).get("by") or account.handle)
            allowed = lending.candidates(by) if lending is not None else {}
            tools = [t for t in (str(x) for x in lists.get("outil", [])) if t in allowed]
            await settings.save_lent(name, tools=tools, writes=data.get("ecrit") == "oui", by=by, at=now)
            if what == "pret_declarer":
                fresh = await settings.new_lent_token(name, by=account.handle, at=now)
                query["montrer"] = ui.reveal(account.handle, {"title": f"Le jeton du point « {name} »",
                                                              "token": fresh,
                                                              "command": _command(name, _lent_url(name), fresh)})
            query["pret"] = name
            ui.flash(token, "ok", f"Le point « {name} » prête {len(tools)} outil{'s' if len(tools) > 1 else ''}"
                                  + (", et peut écrire dans sa vie." if data.get("ecrit") == "oui" else ", en lecture seule."))
            audit, subject = f"console.mcp.pret.{'declarer' if what == 'pret_declarer' else 'regler'}", name
        elif what == "pret_jeton":
            fresh = await settings.new_lent_token(name, by=account.handle, at=now)
            query.update(pret=name, montrer=ui.reveal(account.handle, {
                "title": f"Le jeton du point « {name} »", "token": fresh,
                "command": _command(name, _lent_url(name), fresh)}))
            ui.flash(token, "ok", "Jeton neuf : l'ancien ne vaut plus.")
            audit, subject = "console.mcp.pret.jeton", name
        elif what == "pret_supprimer":
            removed = await settings.remove_lent(name)
            ui.flash(token, "ok" if removed else "info", f"Le point « {name} » est retiré : son adresse répond 404."
                     if removed else "Ce point n'existait plus.")
            audit, subject = ("console.mcp.pret.retirer", name) if removed else ("", "")
        else:
            ui.flash(token, "warn", "Rien à faire.")
    except ValueError as exc:
        ui.flash(token, "warn", f"Pas enregistré : {exc}.")
        if name and what == "pret_regler":
            query["pret"] = name
        elif what == "pret_declarer":
            query["nouveau"] = "1"
    if audit:
        await ops.audit(ui.kernel, audit, by=account.handle, subject_kind="mcp", subject=subject)
    query["flash"] = token
    return secure(RedirectResponse(f"{back}?{urlencode(query)}", status_code=303))
