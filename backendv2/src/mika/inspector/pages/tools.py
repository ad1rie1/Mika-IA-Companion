"""Ses outils : tout ce qu'elle peut faire, d'où ça vient, pour qui et quand (ADR 0064).

L'écran lit ce que le moteur exécute : le registre (ses outils, et ceux que des
sources dynamiques y ajoutent) et la porte d'offre du pipeline
(``runtime.tools.offer``), appliquée à des audiences de synthèse — jamais une
recopie de ses règles. Un outil défini dans le code se lit sur sa fiche ; un
opérateur ne règle que sa place, situation par situation (« Régler ses outils »,
ADR 0122) : le retirer, le mettre en main ou à la demande, jamais l'offrir là où
le code ne l'offre pas.
"""

from __future__ import annotations

import inspect
import secrets as _secrets
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector import mcp as console_mcp
from mika.inspector import names, render
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
    Code,
    Column,
    Disclosure,
    Fields,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Stat,
    Stats,
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
TOOLS_PAGE = 24
BASE = f"{PREFIX}/outils"
#: le contexte du catalogue qu'une fiche garde pour y revenir (plus le choix « Tableau », ``is_table_choice``)
CATALOG_PARAMS = ("q", "lot", "pour", "origine", "page")
#: ce qu'un opérateur choisit pour un outil dans une situation (ADR 0122) ; « » : ce que dit le code
CHOICES = (("", "Comme le code"), (HAND, "En main"), (ASK, "À la demande"), (OFF, "Retiré"))
#: le préfixe des champs du formulaire « Régler ses outils » : « r.<outil> »
RULE_FIELD = "r."
#: les adresses de ce qu'elle expose en MCP (``inspector.mcp``, ``app/lending.py``), et la machine qui les sert
CONSOLE_ADDRESS, LENT_ADDRESS, LOCAL_ORIGIN = console_mcp.PREFIX, "/mcp/pret", "http://127.0.0.1:8001"
#: ce que la console en MCP sert au-delà de ses pages, en mots
SERVED_PARTS = ((console_mcp.VIEWS, "Les vues de ses facultés (ses souvenirs, ses pensées, ses liens…)"),
                (console_mcp.SUBJECTS, "Les fiches (une personne, un but, une app…) et la recherche"),
                (console_mcp.WHY, "« Pourquoi a-t-elle dit ça ? »"))


@dataclass(frozen=True, slots=True)
class Situation:
    """Une audience type et la sorte d'épisode où elle se trouve : de quoi demander à la porte d'offre ce
    qu'elle y aurait en main."""

    key: str
    short: str
    label: str
    kind: str
    audience: Audience


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
    Situation("proprietaire", "propriétaire", "Sa propriétaire, en privé", Kind.REPLY,
              _person("proprietaire", trust=ChannelTrust.AUTHENTICATED.value, owner=True)),
    Situation("compte", "compte", "Une personne qui a un compte, en tête-à-tête", Kind.REPLY,
              _person("compte", trust=ChannelTrust.AUTHENTICATED.value)),
    Situation("inconnue", "inconnue", "Une inconnue, en tête-à-tête (une adresse sans compte)", Kind.REPLY,
              _person("inconnue", trust=ChannelTrust.ACCOUNT.value, channel="external")),
    Situation("salon", "salon", "Dans un salon (plusieurs personnes)", Kind.REPLY,
              _person("salon", trust=ChannelTrust.PUBLIC.value, public=True, room="salon")),
    Situation("initiative", "initiative", "Quand elle prend la parole, vers sa propriétaire", Kind.INITIATIVE,
              _person("initiative", trust=ChannelTrust.AUTHENTICATED.value, owner=True)),
    Situation("pas", "pas", "Un pas sur un but (personne n'écoute)", Kind.STEP, _NOBODY),
    Situation("projet", "projet", "Une exécution de projet (personne n'écoute)", Kind.WORK, _NOBODY),
    Situation("tache", "tâche", "Une tâche silencieuse (préparer un brouillon de mail)", Kind.TASK, _NOBODY),
)


def situations(ui: Any) -> list[Situation]:
    """Les situations dont la sorte d'épisode existe dans cette composition."""
    policies = ui.kernel.runner.policies
    return [s for s in SITUATIONS if s.kind in policies]


def rules(ui: Any, s: Situation) -> Mapping[str, str]:
    """Les règles d'un opérateur pour cette situation, telles que le pipeline les lit à chaque épisode."""
    return ui.kernel.runner.rules_of(s.kind, s.audience) or {}


def offered_in(ui: Any, s: Situation, ruled: bool = True) -> dict[str, ToolSpec]:
    """Ce que la porte d'offre du pipeline lui donnerait dans cette situation ; ``ruled`` faux : ce que le code lui
    offre, avant les règles d'un opérateur."""
    return offer(ui.kernel.registry.tools, ui.kernel.runner.policies[s.kind], s.kind, s.audience,
                 rules=rules(ui, s) if ruled else None)


def in_hand(ui: Any, policy: EpisodePolicy) -> frozenset[str] | None:
    """Les lots en main par défaut (``None`` : tout) — un fournisseur qui ne sait pas différer reçoit tout."""
    if policy.role is None or not defers_tools(ui.kernel.runner.gateway, policy.role):
        return None
    return policy.core_bundles


def why_not(spec: ToolSpec, policy: EpisodePolicy, s: Situation, ruled: Mapping[str, str] | None = None) -> str:
    """Pourquoi la porte ne l'offre pas ici, en mots (vide : elle l'offre). Un test vérifie que ce récit et la
    porte disent la même chose, situation par situation."""
    if s.kind not in spec.episodes:
        return "pas dans cette sorte d'épisode"
    if not admitted(policy.tool_bundles, spec.bundle):
        return "son lot n'y est pas offert"
    if spec.min_level is not None and s.audience.level < spec.min_level:
        return "niveau de confiance insuffisant"
    if spec.owner_only and not s.audience.owner:
        return "réservé à ses propriétaires"
    if spec.when is not None:
        try:
            ok = spec.when(s.audience) is True
        except Exception:  # noqa: BLE001 — la porte compte une panne comme un refus
            ok = False
        if not ok:
            return condition(spec) or "sa condition n'est pas remplie"
    if rule_of(spec, ruled) == OFF:
        return "retiré par un opérateur"
    return ""


def condition(spec: ToolSpec) -> str:
    """La condition d'offre d'un outil (``when=``), en mots : la première phrase de sa docstring."""
    if spec.when is None:
        return ""
    doc = inspect.getdoc(spec.when) or ""
    return " ".join(doc.split("\n\n")[0].split())


def origin(ui: Any, spec: ToolSpec) -> tuple[str, str]:
    """(libellé, ton) d'où vient un outil : défini dans le code, ou ajouté par une source dynamique."""
    if ui.kernel.registry.is_dynamic(spec.name):
        return "extérieur", "info"
    return "interne", "muted"


def _usage(ui: Any) -> Mapping[str, Any]:
    traces = getattr(ui.kernel, "traces", None)
    if traces is None:
        return {}
    return traces.tool_usage(ui.now() - USAGE_DAYS * DAY)


def _who(ui: Any, spec: ToolSpec, offers: Mapping[str, Mapping[str, ToolSpec]]) -> str:
    shorts = [s.short for s in situations(ui) if spec.name in offers.get(s.key, {})]
    return " · ".join(shorts) or "nulle part"


def _kinds(spec: ToolSpec) -> str:
    return ", ".join(names.kind(k) for k in sorted(spec.episodes)) or "—"


def _tool_ref(name: str, text: str | None = None, context: Mapping[str, str] | None = None) -> Ref:
    kept = tuple((k, v) for k, v in (context or {}).items() if k in CATALOG_PARAMS or is_table_choice(k, v))
    return Ref("local", f"{BASE}/tous", text or name, (*kept, ("outil", name)))


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _bundle_choices(ui: Any) -> tuple[tuple[str, str], ...]:
    bundles = sorted({s.bundle for s in ui.kernel.registry.tools.values()})
    return tuple((b, ui.names.faculty(b)) for b in bundles)


def _params(ui: Any) -> tuple[Param, ...]:
    return (Param("q", "Rechercher", "search", placeholder="un nom ou ce qu'il fait"),
            Param("lot", "Famille", "select", _bundle_choices(ui)),
            Param("pour", "Disponible pour", "select", tuple((s.key, s.label) for s in situations(ui))),
            Param("origine", "Origine", "select", (("interne", "Interne"), ("exterieur", "Extérieur"))))


@TABS.tab("outils.tous", title="Catalogue des outils",
          description="Trouver un outil, comprendre ce qu'il fait et vérifier dans quelles situations elle peut l'utiliser.")
async def all_tools(ui: Any, request: Request) -> Any:
    name = str(request.query_params.get("outil", "") or "")
    if name:
        return _fiche(ui, request, name)
    registry = ui.kernel.registry
    params = _params(ui)
    values, notes = read_params(params, request.query_params)
    offers = {s.key: offered_in(ui, s) for s in situations(ui)}
    usage = _usage(ui)
    query = _fold(str(values.get("q") or ""))
    specs = sorted(registry.tools.values(), key=lambda s: (s.bundle, s.name))
    if values.get("lot"):
        specs = [s for s in specs if s.bundle == values["lot"]]
    if values.get("pour"):
        specs = [s for s in specs if s.name in offers.get(values["pour"], {})]
    if values.get("origine"):
        dynamic = values["origine"] == "exterieur"
        specs = [s for s in specs if registry.is_dynamic(s.name) == dynamic]
    if query:
        specs = [s for s in specs if all(term in _fold(f"{s.name} {s.description} {s.bundle} "
                         f"{ui.names.faculty(s.bundle)} {registry.bundles.get(s.bundle, '')}") for term in query.split())]
    ctx = ui.inspection.context(request.query_params)
    page, pager = paginate(specs, ctx.pager(size=TOOLS_PAGE))
    rows = []
    for s in page:
        label, tone = origin(ui, s)
        used = usage.get(s.name)
        calls = Text(num_fr(used.calls), "num", "danger" if used.failures * 2 > used.calls else "",
                     hint=f"{used.failures} en échec") if used else Text("0", "num", "muted")
        rows.append(Row((Text(s.name, "mono"), Badge(label, tone),
                         Text(ui.names.faculty(s.bundle), hint=registry.bundles.get(s.bundle, "")),
                         Text(s.description, clamp=220), Text(_who(ui, s, offers)), Text(_kinds(s), "muted"),
                         calls), href=_tool_ref(s.name, context=request.query_params)))
    total = len(registry.tools)
    dynamic = sum(1 for n in registry.tools if registry.is_dynamic(n))
    used_now = sum(1 for n in registry.tools if n in usage)
    failing = sum(u.failures for n, u in usage.items() if n in registry.tools)
    blocks: list[Any] = [
        Stats((Stat("Outils", total, f"{total - dynamic} internes · {dynamic} extérieurs"),
               Stat("Familles", len({s.bundle for s in registry.tools.values()})),
               Stat(f"Appelés en {USAGE_DAYS} jours", used_now, "outils différents"),
               Stat("Appels en échec", failing, f"sur {USAGE_DAYS} jours", "warn" if failing else "")),
              title="Catalogue complet"),
        *[Note(n, "warn") for n in notes],
        Table((Column("Outil", "fit", role="title"), Column("Origine", "fit", role="badge"), Column("Famille", "fit"), Column("Ce qu'il fait", role="body"),
               Column("Disponible pour", hint="les situations où la porte d'offre le lui donne", detail=True),
               Column("Épisodes", detail=True), Column(f"Appels sur {USAGE_DAYS} j", "num")),
              tuple(rows), title="Ses outils", empty="Aucun outil ne correspond.", pager=pager,
              layout="cards", link_label="Comprendre cet outil",
              caption="Interne : défini dans le code, il se lit ici et ne se règle pas. Extérieur : branché depuis "
                      "un serveur, il se règle sur la fiche de son serveur."),
    ]
    return {"blocks": blocks, "filters": params}


def _fiche(ui: Any, request: Request, name: str) -> Any:
    registry = ui.kernel.registry
    context = {k: v for k, v in request.query_params.items() if k in CATALOG_PARAMS or is_table_choice(k, v)}
    back = [("Retour aux outils", f"{BASE}/tous" + ("?" + urlencode(context) if context else ""))]
    spec = registry.tools.get(name)
    if spec is None:
        return {"blocks": [Note(f"Aucun outil ne s'appelle « {name} ».", "warn")], "crumbs": back}
    label, tone = origin(ui, spec)
    policies = ui.kernel.runner.policies
    reserved = ("à ses propriétaires (et quand elle travaille, personne n'écoutant)" if spec.owner_only else "non")
    pairs: list[tuple[str, Any]] = [
        ("nom", Text(spec.name, "mono")),
        ("origine", Badge(label, tone)),
        ("faculté", ui.names.faculty(spec.owner)),
        ("lot", Text(spec.bundle, secondary=registry.bundles.get(spec.bundle, ""))),
        ("ce qu'il fait", Text(spec.description)),
        ("épisodes", _kinds(spec)),
        ("réservé", reserved),
        ("condition d'offre", condition(spec) or "—"),
        ("vérifié à l'exécution", spec.rule or "—"),
        ("appels par épisode", str(spec.max_calls_per_episode) if spec.max_calls_per_episode else "sans plafond"),
        ("conclut la boucle", "oui" if spec.ends_loop else "non"),
        ("modifiable", "non — défini dans le code (sa place se règle dans « Régler ses outils »)"
         if not registry.is_dynamic(spec.name) else "sur la fiche de son serveur"),
    ]
    argument_table = Table(("argument", Column("type", "fit"), Column("requis", "fit"), "ce que c'est",
                         Column("contraintes", "fit")), tuple(arguments(schema_of(spec))),
                        title="Ses arguments", empty="Aucun argument.")
    blocks: list[Any] = []
    rows = []
    for s in situations(ui):
        policy = policies[s.kind]
        ruled = rules(ui, s)
        reason = why_not(spec, policy, s, ruled)
        core = in_hand(ui, policy)
        if reason:
            rows.append(Row((s.label, Badge("non", "muted"), Text(reason, "muted"))))
        else:
            hand = not deferred(spec, core, ruled)
            rows.append(Row((s.label, Badge("en main" if hand else "à la demande", "ok" if hand else "info"),
                             Text("placé par un opérateur", "muted") if rule_of(spec, ruled) else "")))
    blocks.append(Table((Column("Situation", role="title"), Column("Disponible", "fit", role="badge"), "Pourquoi pas"), tuple(rows),
                        title="Qui le reçoit",
                        layout="list",
                        caption="Lu de la porte d'offre du pipeline, avec les règles des opérateurs (Régler ses "
                                "outils). Un pas ou une exécution qui a choisi ses lots les a tous en main."))
    traces = getattr(ui.kernel, "traces", None)
    uses = traces.tool_uses(spec.name, 20) if traces is not None else []
    blocks.append(Disclosure("Arguments et règles d’utilisation", (argument_table, Fields(tuple(pairs), title="Règles et provenance", columns=2))))
    blocks.append(Table((Column("quand", "fit"), Column("épisode", "fit"), Column("issue", "fit"), ""), tuple(
        Row((When(u.at), names.kind(u.kind),
             Badge("réussi" if u.ok else ("refusé" if not u.executed else "échec"),
                   "ok" if u.ok else "warn" if not u.executed else "danger"),
             Ref("episode", u.correlation, "relire", (("onglet", "outils"),))))
        for u in uses), title="Ses derniers appels", empty=f"Aucun appel depuis {USAGE_DAYS} jours."))
    return {"blocks": blocks, "crumbs": back, "panel": Panel("handmade/shared/outil.html", {
        "page_heading": spec.name, "page_subtitle": spec.description,
        "tool_origin": label, "tool_tone": tone, "tool_family": ui.names.faculty(spec.bundle),  # la famille du catalogue (son lot)
        "tool_reserved": spec.owner_only,
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


def _cell(offered: Sequence[ToolSpec], total: int, hand: bool) -> Text:
    if not offered:
        return Text("—", "muted")
    mark = "●" if hand else "○"
    count = "" if len(offered) == total else f" {len(offered)}/{total}"
    return Text(mark + count, tone="ok" if hand else "", hint=", ".join(sorted(s.name for s in offered)))


@TABS.tab("outils.qui", title="Qui reçoit quoi",
          description="Chaque lot d'outils, situation par situation : en main, à la demande, ou pas offert. Calculé "
                      "par la porte d'offre du pipeline, sur des audiences types.")
async def who_gets_what(ui: Any, request: Request) -> list[Any]:
    registry = ui.kernel.registry
    policies = ui.kernel.runner.policies
    sits = situations(ui)
    offers = {s.key: offered_in(ui, s) for s in sits}
    hands = {s.key: in_hand(ui, policies[s.kind]) for s in sits}
    ruled = {s.key: rules(ui, s) for s in sits}
    by_bundle: dict[str, list[ToolSpec]] = {}
    for spec in registry.tools.values():
        by_bundle.setdefault(spec.bundle, []).append(spec)
    rows = []
    for bundle, specs in sorted(by_bundle.items()):
        cells: list[Any] = [Text(bundle, hint=registry.bundles.get(bundle, ""), secondary=registry.bundles.get(
            bundle, ""))]
        for s in sits:
            got = [x for x in specs if x.name in offers[s.key]]
            cells.append(_cell(got, len(specs), any(not deferred(x, hands[s.key], ruled[s.key]) for x in got)))
        rows.append(Row(tuple(cells)))
    columns = ("lot", *[Column(s.short, "fit", hint=s.label) for s in sits])
    return [Table(columns, tuple(rows), title="Lots × situations",
                  caption="● en main · ○ à la demande (elle le cherche quand elle en a besoin) · — pas offert. "
                          "« 2/5 » : une partie du lot seulement (des outils réservés, ou une condition). Un pas ou "
                          "une exécution qui a choisi ses lots les a tous en main ; un fournisseur qui ne sait pas "
                          "différer reçoit tout en main.")]


@TABS.tab("outils.texte", title="Régler ses outils",
          description="Situation par situation : les outils que le code lui offre, ceux qu'un opérateur retire ou "
                      "range autrement (en main, à la demande), et le texte exact que son prompt en porte.")
async def what_she_reads(ui: Any, request: Request) -> Any:
    sits = situations(ui)
    choices = tuple((s.key, s.label) for s in sits)
    s = next((x for x in sits if x.key == request.query_params.get("situation")), sits[0] if sits else None)
    families = sorted({spec.bundle for spec in offered_in(ui, s, ruled=False).values()} if s else set())
    params = (Param("situation", "Situation", "select", choices, default=sits[0].key if sits else ""),
              Param("lot", "Famille", "select", tuple((b, ui.names.faculty(b)) for b in families)))
    values, notes = read_params(params, request.query_params)
    if s is None:
        return {"blocks": [Note("Aucune sorte d'épisode n'appelle de modèle.", "muted")], "filters": params}
    policy = ui.kernel.runner.policies[s.kind]
    ruled = rules(ui, s)
    offered = list(offered_in(ui, s).values())
    core = in_hand(ui, policy)
    text = "\n\n".join(filter(None, (acting(offered) if policy.visible else "",
                                     catalogue(offered, core, ui.kernel.registry.bundles, ruled))))
    blocks: list[Any] = [*[Note(n, "warn") for n in notes]]
    if policy.role is not None and core is None and policy.core_bundles is not None:
        blocks.append(Note("Le fournisseur de ce rôle ne sait pas différer des outils : il les reçoit tous en "
                           "main, et son prompt ne parle pas d'outils à chercher.", "info"))
    blocks.append(Code(text or "(rien : aucun outil offert, ou tous en main sans règle à dire)",
                       title=f"Ce que son prompt dit de ses outils — {s.label}"))
    return {"blocks": blocks, "filters": params,
            "panel": Panel("handmade/outils/regler.html", rule_table(ui, s, core, ruled, str(values.get("lot") or "")))}


def rule_table(ui: Any, s: Situation, core: frozenset[str] | None, ruled: Mapping[str, str],
               lot: str = "") -> dict[str, Any]:
    """Le tableau « Régler ses outils » d'une situation : chaque outil que le code y offre, par famille, sa place
    selon le code, et la règle d'un opérateur (aucune sur un outil qui clôt la boucle)."""
    by_code = offered_in(ui, s, ruled=False)
    families: dict[str, list[dict[str, Any]]] = {}
    for spec in sorted(by_code.values(), key=lambda x: x.name):
        if lot and spec.bundle != lot:
            continue
        rule = rule_of(spec, ruled) or ""
        code_ask = deferred(spec, core)
        now = "off" if rule == OFF else ("ask" if deferred(spec, core, ruled) else "hand")
        families.setdefault(spec.bundle, []).append({
            "name": spec.name, "description": spec.description, "rule": rule, "now": now,
            "code": "à la demande" if code_ask else "en main", "locked": spec.ends_loop,
            "href": f"{BASE}/tous?" + urlencode({"outil": spec.name}),
        })
    groups = [{"bundle": b, "label": ui.names.faculty(b), "rows": rows}
              for b, rows in sorted(families.items(), key=lambda kv: ui.names.faculty(kv[0]).casefold())]
    total = sum(len(g["rows"]) for g in groups)
    # tout est en main (un fournisseur qui ne sait pas différer, un pas qui a choisi ses lots) : seul « retiré » compte
    choices = CHOICES if core is not None else tuple(c for c in CHOICES if c[0] in ("", OFF))
    keep = {"situation": s.key, **({"lot": lot} if lot else {})}
    return {
        "situation": s, "groups": groups, "choices": choices, "flat": core is None, "lot": lot,
        "total": total, "ruled": sum(1 for r in ruled.values() if r), "off": sum(1 for r in ruled.values() if r == OFF),
        "back": f"{BASE}/texte?" + urlencode(keep), "action": f"{BASE}/regler",
        "pager": render._pager(Pager(size=max(1, total), total=total), {}),
    }


async def rules_post(ui: Any, request: Request) -> Response:
    """« Régler ses outils » : les règles d'une situation, enregistrées (``Settings.save_tool_rules``) et auditées.
    Un champ par outil (``r.<outil>``) : vide, l'outil reprend ce que dit le code ; un outil que le code n'offre pas
    dans cette situation, ou qui clôt la boucle, est ignoré — une règle ne fait que restreindre. « Tout remettre
    comme le code » efface les règles de la situation."""
    data = await ui.form(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    key = str((data or {}).get("situation", ""))
    lot = str((data or {}).get("lot", ""))
    s = next((x for x in situations(ui) if x.key == key), None)
    settings = getattr(ui.deps, "settings", None)
    back = f"{BASE}/texte?" + urlencode({"situation": key, **({"lot": lot} if lot else {})})
    if data is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif s is None or settings is None:
        ui.flash(token, "warn", "Cette situation n'existe pas : rien n'a été enregistré.")
    else:
        before = dict(rules(ui, s))
        core = in_hand(ui, ui.kernel.runner.policies[s.kind])
        allowed = {n: spec for n, spec in offered_in(ui, s, ruled=False).items() if not spec.ends_loop}
        changes: dict[str, str | None] = {}
        if data.get("faire") == "remettre":
            changes = dict.fromkeys(before)
        else:
            for field_, value in data.items():
                name, chosen = field_.removeprefix(RULE_FIELD), str(value)
                if not field_.startswith(RULE_FIELD) or name not in allowed or chosen not in ("", *RULES):
                    continue
                code = ASK if deferred(allowed[name], core) else HAND
                # ce que dit déjà le code n'est pas une règle ; tout en main, seul « retiré » en est une
                changes[name] = None if chosen in ("", code) or (core is None and chosen != OFF) else chosen
        kept = await settings.save_tool_rules(s.key, changes)
        changed = sorted(n for n in {*before, *kept} if before.get(n) != kept.get(n))
        if changed:
            await ops.audit(ui.kernel, "console.outils.regler", by=account.handle, subject_kind="situation",
                            subject=s.key)
            ui.flash(token, "ok", f"{s.label} : {', '.join(changed)} — vaut dès son prochain épisode.")
        else:
            ui.flash(token, "info", "Rien n'a changé.")
    return secure(RedirectResponse(f"{back}&flash={token}", status_code=303))


@TABS.tab("outils.expose", title="Ce qu'elle expose",
          description="Ce qu'elle sert elle-même en MCP : ses outils au moteur Claude Code le temps d'un épisode, la "
                      "console en lecture pour un agent de sa propriétaire, et les points qui prêtent certains de ses "
                      "outils à un agent.")
async def exposed(ui: Any, request: Request) -> Any:
    relay, settings, lending = ui.deps.relay, ui.deps.settings, getattr(ui.deps, "lending", None)
    account = ui.operator(request)
    try:
        token = bool(settings.console_mcp_token()) if settings is not None else False
        chosen = settings.console_mcp_served() if settings is not None else None
        entries = settings.lent() if settings is not None else {}
    except Exception:  # noqa: BLE001 — un réglage illisible : « absent », jamais une page cassée
        token, chosen, entries = False, None, {}
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


def _command(name: str, address: str, token: str) -> str:
    return (f"claude mcp add --transport http {name} {LOCAL_ORIGIN}{address} "
            f"--header \"Authorization: Bearer {token}\"")


async def expose_post(ui: Any, request: Request) -> Response:
    """Ce qu'elle expose : le jeton de la console en MCP et ce qu'elle sert ; ses points de prêt — déclarés,
    réglés, leur jeton, retirés. Tout est audité ; un jeton neuf se montre une seule fois, à qui l'a créé."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    settings, lending = ui.deps.settings, getattr(ui.deps, "lending", None)
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
                                                          "command": _command("mika", CONSOLE_ADDRESS, fresh)})
            ui.flash(token, "ok", "Jeton neuf : l'ancien ne vaut plus.")
            audit, subject = "console.mcp.jeton", "console"
        elif what == "console_fermer":
            closed = await settings.revoke_console_mcp_token()
            ui.flash(token, "ok" if closed else "info", "La console en MCP est fermée : son adresse répond 404."
                     if closed else "Elle n'avait pas de jeton.")
            audit, subject = ("console.mcp.fermer", "console") if closed else ("", "")
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
                                                              "command": _command(name, f"{LENT_ADDRESS}/{name}", fresh)})
            query["pret"] = name
            ui.flash(token, "ok", f"Le point « {name} » prête {len(tools)} outil{'s' if len(tools) > 1 else ''}"
                                  + (", et peut écrire dans sa vie." if data.get("ecrit") == "oui" else ", en lecture seule."))
            audit, subject = f"console.mcp.pret.{'declarer' if what == 'pret_declarer' else 'regler'}", name
        elif what == "pret_jeton":
            fresh = await settings.new_lent_token(name, by=account.handle, at=now)
            query.update(pret=name, montrer=ui.reveal(account.handle, {
                "title": f"Le jeton du point « {name} »", "token": fresh,
                "command": _command(name, f"{LENT_ADDRESS}/{name}", fresh)}))
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
