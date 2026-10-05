"""Ses outils : tout ce qu'elle peut faire, d'où ça vient, pour qui et quand (ADR 0064).

L'écran lit ce que le moteur exécute : le registre (ses outils, et ceux que des
sources dynamiques y ajoutent) et la porte d'offre du pipeline
(``runtime.tools.offer``), appliquée à des audiences de synthèse — jamais une
recopie de ses règles. Un outil défini dans le code se lit ici, il ne se règle
pas : aucune action, aucun formulaire.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request

from mika.inspector import names
from mika.inspector.mcp import TOOLS as CONSOLE_TOOLS
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX
from mika.kernel.clock import DAY
from mika.kernel.episode import EpisodePolicy
from mika.kernel.faculty import ToolSpec
from mika.kernel.frame import Audience
from mika.kernel.inspect import (
    Badge,
    Code,
    Column,
    Fields,
    Note,
    Param,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    num_fr,
    paginate,
    read_params,
)
from mika.runtime.tools import acting, admitted, catalogue, declare, defers_tools, offer
from mika.vocab.episodes import Kind
from mika.vocab.privacy import EVERYTHING, ChannelTrust

#: ce qui est compté comme récent (les traces d'épisode ne gardent pas plus)
USAGE_DAYS = 14
TOOLS_PAGE = 60
BASE = f"{PREFIX}/outils"


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
                    owner=owner, tied_level=level)


#: personne n'écoute (un pas, une exécution, une tâche) : l'audience que le moteur leur donne
_NOBODY = Audience(persons=(), channel="internal", public=False, level=int(EVERYTHING.level),
                   witness_level=int(EVERYTHING.witness_level), private_ok=True,
                   trust=ChannelTrust.INTERNAL.value, owner=True, tied_level=int(EVERYTHING.tied_level))

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


def offered_in(ui: Any, s: Situation) -> dict[str, ToolSpec]:
    """Ce que la porte d'offre du pipeline lui donnerait dans cette situation."""
    return offer(ui.kernel.registry.tools, ui.kernel.runner.policies[s.kind], s.kind, s.audience)


def in_hand(ui: Any, policy: EpisodePolicy) -> frozenset[str] | None:
    """Les lots en main par défaut (``None`` : tout) — un fournisseur qui ne sait pas différer reçoit tout."""
    if policy.role is None or not defers_tools(ui.kernel.runner.gateway, policy.role):
        return None
    return policy.core_bundles


def why_not(spec: ToolSpec, policy: EpisodePolicy, s: Situation) -> str:
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


def _tool_ref(name: str, text: str | None = None) -> Ref:
    return Ref("local", f"{BASE}/tous", text or name, (("outil", name),))


def _bundle_choices(ui: Any) -> tuple[tuple[str, str], ...]:
    bundles = sorted({s.bundle for s in ui.kernel.registry.tools.values()})
    return tuple((b, b) for b in bundles)


def _params(ui: Any) -> tuple[Param, ...]:
    return (Param("q", "chercher", "search", placeholder="un nom ou ce qu'il fait"),
            Param("lot", "lot", "select", _bundle_choices(ui)),
            Param("pour", "offert à", "select", tuple((s.key, s.label) for s in situations(ui))),
            Param("origine", "origine", "select", (("interne", "interne"), ("exterieur", "extérieur"))))


@TABS.tab("outils.tous", title="Tous ses outils",
          description="Chaque outil qu'elle peut appeler : d'où il vient, son lot et ce qu'il permet, pour qui et "
                      "dans quelles situations, combien il a servi. Ceux définis dans le code se lisent ici, ils ne "
                      "se règlent pas.")
async def all_tools(ui: Any, request: Request) -> Any:
    name = str(request.query_params.get("outil", "") or "")
    if name:
        return _fiche(ui, request, name)
    registry = ui.kernel.registry
    params = _params(ui)
    values, notes = read_params(params, request.query_params)
    offers = {s.key: offered_in(ui, s) for s in situations(ui)}
    usage = _usage(ui)
    query = str(values.get("q") or "").casefold()
    specs = sorted(registry.tools.values(), key=lambda s: (s.bundle, s.name))
    if values.get("lot"):
        specs = [s for s in specs if s.bundle == values["lot"]]
    if values.get("pour"):
        specs = [s for s in specs if s.name in offers.get(values["pour"], {})]
    if values.get("origine"):
        dynamic = values["origine"] == "exterieur"
        specs = [s for s in specs if registry.is_dynamic(s.name) == dynamic]
    if query:
        specs = [s for s in specs if query in f"{s.name} {s.description} {s.bundle} "
                                              f"{registry.bundles.get(s.bundle, '')}".casefold()]
    ctx = ui.inspection.context(request.query_params)
    page, pager = paginate(specs, ctx.pager(size=TOOLS_PAGE))
    rows = []
    for s in page:
        label, tone = origin(ui, s)
        used = usage.get(s.name)
        calls = Text(num_fr(used.calls), "num", "danger" if used.failures * 2 > used.calls else "",
                     hint=f"{used.failures} en échec") if used else Text("0", "num", "muted")
        rows.append(Row((Text(s.name, "mono"), Badge(label, tone),
                         Text(s.bundle, hint=registry.bundles.get(s.bundle, "")),
                         Text(s.description, clamp=140), Text(_who(ui, s, offers)), Text(_kinds(s), "muted"),
                         calls), href=_tool_ref(s.name)))
    total = len(registry.tools)
    dynamic = sum(1 for n in registry.tools if registry.is_dynamic(n))
    used_now = sum(1 for n in registry.tools if n in usage)
    failing = sum(u.failures for n, u in usage.items() if n in registry.tools)
    blocks: list[Any] = [
        Stats((Stat("Outils", total, f"{total - dynamic} internes · {dynamic} extérieurs"),
               Stat("Lots", len({s.bundle for s in registry.tools.values()})),
               Stat(f"Appelés en {USAGE_DAYS} jours", used_now, "outils différents"),
               Stat("Appels en échec", failing, f"sur {USAGE_DAYS} jours", "warn" if failing else ""))),
        *[Note(n, "warn") for n in notes],
        Table((Column("outil", "fit"), Column("origine", "fit"), Column("lot", "fit"), "ce qu'il fait",
               Column("offert à", hint="les situations où la porte d'offre le lui donne"),
               Column("épisodes", detail=True), Column(f"appels {USAGE_DAYS} j", "num")),
              tuple(rows), title="Ses outils", empty="Aucun outil ne correspond.", pager=pager,
              caption="Interne : défini dans le code, il se lit ici et ne se règle pas. Extérieur : branché depuis "
                      "un serveur, il se règle sur la fiche de son serveur."),
    ]
    return {"blocks": blocks, "filters": params}


def _fiche(ui: Any, request: Request, name: str) -> Any:
    registry = ui.kernel.registry
    back = [("Tous ses outils", f"{BASE}/tous")]
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
        ("modifiable", "non — défini dans le code" if not registry.is_dynamic(spec.name)
         else "sur la fiche de son serveur"),
    ]
    blocks: list[Any] = [Fields(tuple(pairs), title=spec.name)]
    blocks.append(Table(("argument", Column("type", "fit"), Column("requis", "fit"), "ce que c'est",
                         Column("contraintes", "fit")), tuple(arguments(schema_of(spec))),
                        title="Ses arguments", empty="Aucun argument."))
    rows = []
    for s in situations(ui):
        policy = policies[s.kind]
        reason = why_not(spec, policy, s)
        core = in_hand(ui, policy)
        if reason:
            rows.append(Row((s.label, Badge("non", "muted"), Text(reason, "muted"))))
        else:
            hand = core is None or spec.bundle in core or spec.in_hand
            rows.append(Row((s.label, Badge("en main" if hand else "à la demande", "ok" if hand else "info"),
                             "")))
    blocks.append(Table(("situation", Column("offert", "fit"), "pourquoi pas"), tuple(rows),
                        title="Qui le reçoit",
                        caption="Lu de la porte d'offre du pipeline. Un pas ou une exécution qui a choisi ses lots les "
                                "a tous en main."))
    traces = getattr(ui.kernel, "traces", None)
    uses = traces.tool_uses(spec.name, 20) if traces is not None else []
    blocks.append(Table((Column("quand", "fit"), Column("épisode", "fit"), Column("issue", "fit"), ""), tuple(
        Row((When(u.at), names.kind(u.kind),
             Badge("réussi" if u.ok else ("refusé" if not u.executed else "échec"),
                   "ok" if u.ok else "warn" if not u.executed else "danger"),
             Ref("episode", u.correlation, "relire", (("onglet", "outils"),))))
        for u in uses), title="Ses derniers appels", empty=f"Aucun appel depuis {USAGE_DAYS} jours."))
    return {"blocks": blocks, "crumbs": back}


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
    by_bundle: dict[str, list[ToolSpec]] = {}
    for spec in registry.tools.values():
        by_bundle.setdefault(spec.bundle, []).append(spec)
    rows = []
    for bundle, specs in sorted(by_bundle.items()):
        cells: list[Any] = [Text(bundle, hint=registry.bundles.get(bundle, ""), secondary=registry.bundles.get(
            bundle, ""))]
        for s in sits:
            got = [x for x in specs if x.name in offers[s.key]]
            core = hands[s.key]
            cells.append(_cell(got, len(specs), core is None or bundle in core or any(x.in_hand for x in got)))
        rows.append(Row(tuple(cells)))
    columns = ("lot", *[Column(s.short, "fit", hint=s.label) for s in sits])
    return [Table(columns, tuple(rows), title="Lots × situations",
                  caption="● en main · ○ à la demande (elle le cherche quand elle en a besoin) · — pas offert. "
                          "« 2/5 » : une partie du lot seulement (des outils réservés, ou une condition). Un pas ou "
                          "une exécution qui a choisi ses lots les a tous en main ; un fournisseur qui ne sait pas "
                          "différer reçoit tout en main.")]


@TABS.tab("outils.texte", title="Ce qu'elle lit",
          description="Le texte exact que son prompt porte sur ses outils dans une situation : la règle de ses "
                      "mains, le catalogue de ce qu'elle peut aller chercher, et les outils qu'elle a en main.")
async def what_she_reads(ui: Any, request: Request) -> Any:
    sits = situations(ui)
    params = (Param("situation", "situation", "select", tuple((s.key, s.label) for s in sits),
                    default=sits[0].key if sits else ""),)
    values, notes = read_params(params, request.query_params)
    s = next((x for x in sits if x.key == values.get("situation")), sits[0] if sits else None)
    if s is None:
        return {"blocks": [Note("Aucune sorte d'épisode n'appelle de modèle.", "muted")], "filters": params}
    policy = ui.kernel.runner.policies[s.kind]
    tools = offered_in(ui, s)
    offered = list(tools.values())
    core = in_hand(ui, policy)
    text = "\n\n".join(filter(None, (acting(offered) if policy.visible else "",
                                     catalogue(offered, core, ui.kernel.registry.bundles))))
    decl = declare(offered, core)
    blocks: list[Any] = [*[Note(n, "warn") for n in notes]]
    if policy.role is not None and core is None and policy.core_bundles is not None:
        blocks.append(Note("Le fournisseur de ce rôle ne sait pas différer des outils : il les reçoit tous en "
                           "main, et son prompt ne parle pas d'outils à chercher.", "info"))
    blocks.append(Code(text or "(rien : aucun outil offert, ou tous en main sans règle à dire)",
                       title=f"Ce que son prompt dit de ses outils — {s.label}"))
    blocks.append(Table((Column("outil", "fit"), Column("lot", "fit"), "ce qu'il fait"), tuple(
        Row((Text(d.name, "mono"), tools[d.name].bundle, Text(d.description, clamp=200)), href=_tool_ref(d.name))
        for d in decl if not d.deferred), title="En main", empty="Aucun outil en main."))
    blocks.append(Table((Column("outil", "fit"), Column("lot", "fit"), "ce qu'il fait"), tuple(
        Row((Text(d.name, "mono"), tools[d.name].bundle, Text(d.description, clamp=200)), href=_tool_ref(d.name))
        for d in decl if d.deferred), title="À la demande",
        empty="Rien à la demande.", caption="Déclarés au modèle, chargés seulement quand elle les cherche."))
    return {"blocks": blocks, "filters": params}


@TABS.tab("outils.expose", title="Ce que Mika expose",
          description="Ce qu'elle sert elle-même en MCP : ses outils prêtés à la CLI Claude Code le temps d'un "
                      "épisode, et la console en lecture seule pour un agent de sa propriétaire.")
async def exposed(ui: Any, request: Request) -> list[Any]:
    relay = ui.deps.relay
    sessions = len(relay) if relay is not None else 0
    settings = ui.deps.settings
    try:
        token = bool(settings.console_mcp_token()) if settings is not None else False
    except Exception:  # noqa: BLE001 — un réglage illisible : « absent », jamais une page cassée
        token = False
    blocks: list[Any] = [
        Fields((
            ("adresse", Text("/mcp/relais/<session>/mika · …/plus", "mono")),
            ("ce qu'il sert", "les outils de l'épisode en cours — en main sous « mika », à la demande sous "
                              "« mika_plus » —, exécutés par la boucle du runtime avec toutes ses gardes"),
            ("à qui", "la CLI Claude Code que le moteur lance, et elle seule"),
            ("accès", "cette machine seulement, un jeton par épisode ; une session fermée répond 404"),
            ("sessions ouvertes", str(sessions)),
        ), title="Le relais (moteur Claude Code)"),
        Fields((
            ("adresse", Text("/mcp/console", "mono")),
            ("ce qu'il sert", "la console en lecture seule : ses vues, ses fiches, la recherche, « pourquoi a-t-elle "
                              "dit ça ? », et des pages de la console (santé, processus, anomalies, sorties, coûts, "
                              "chronologie, épisodes, ses choix, « que ferait-elle ? », « à traiter ») — aucune "
                              "action, aucune page à formulaires"),
            ("à qui", "un agent de sa propriétaire (son Claude Code, par exemple)"),
            ("accès", "cette machine seulement, derrière un jeton d'opérateur"),
            ("jeton", Badge("défini", "ok") if token else Badge("absent — « mika mcp token » en crée un", "muted")),
        ), title="La console en MCP"),
        Table((Column("outil", "fit"), "ce qu'il fait", Column("lecture seule", "fit")), tuple(
            Row((Text(t.name, "mono"), Text(t.description, clamp=200), "oui" if t.read_only else "non"))
            for t in CONSOLE_TOOLS), title="Les outils de la console en MCP"),
    ]
    return blocks
