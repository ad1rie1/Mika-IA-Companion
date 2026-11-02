"""Approbations : ce qu'elle voudrait faire hors de la machine. Ce qui est
montré est exactement ce qui partira : quand la capacité le sait
(``preview``), l'aperçu du résultat, et c'est cet aperçu-là qu'on approuve.
Les demandes en attente se lisent comme un courrier : la file à gauche, la
demande ouverte à droite, la suivante après chaque décision."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.catalog import Builtin, Panel
from mika.inspector.formview import action_view
from mika.inspector.pages.tabs import TABS
from mika.inspector.render import PREFIX
from mika.inspector.ui import QueueItem, QueueTab
from mika.kernel.inspect import Badge, Column, Ref, Row, Table, Text, When, paginate
from mika.runtime import decisions
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.operations import offered

#: la file des demandes, par page : une ligne chacune
QUEUE_PAGE = 50
#: la demande ouverte (``?demande=<n° de la proposition>``) et le filtre par sorte (``?sorte=<capacité>``)
OPEN, KIND = "demande", "sorte"
#: ce que la ligne d'une demande dit de ce qu'elle veut faire, au plus
LINE_TEXT = 160


def _kind(ui: Any, capability: str) -> str:
    """Le nom court d'une sorte de demande : la description de sa capacité, sans sa parenthèse (« Envoyer un mail »)."""
    said = ui.names.capability(capability)
    return said.split(" (", 1)[0].rstrip(" .") or said


#: d'où vient une demande qui ne concerne pas une personne : un service, une app, un canal
SOURCES = {"mcp": "service « {} »", "forge": "app « {} »"}
CHANNELS = {"teams": "Teams", "email": "courrier", "phone": "téléphone"}


def _about(ui: Any, context: str) -> str:
    """Ce qu'une demande concerne, dit simplement : une personne (son nom), un projet (« projet n° 61 »), un service
    (« service « agenda » »), une app, un canal."""
    if not context:
        return ""
    head, _, rest = context.partition(":")
    if rest and head in SOURCES:
        return SOURCES[head].format(rest)
    if context in CHANNELS:
        return CHANNELS[context]
    return ui.names.who(context).removeprefix("le ")


#: les dernières décisions de la même sorte, dans l'historique d'une demande
PRECEDENTS = 5


def _sources(ui: Any, current: Any, args_json: str) -> list[dict[str, str]]:
    """Les liens vers la source d'une demande (la boîte, la conversation, le service, la personne), que la composition
    fournit (``InspectorDeps.approval_sources``) ; rien si elle ne les connaît pas."""
    fn = getattr(ui.deps, "approval_sources", None)
    if fn is None:
        return []
    try:
        args = json.loads(args_json or "{}")
    except ValueError:
        args = {}
    got = call(fn, ui, current.capability, current.context or "", args if isinstance(args, dict) else {},
               label="sources d'une demande")
    return [] if isinstance(got, Failed) else [{"text": t, "href": h} for t, h in got]


def _history(ui: Any, ctx: Any, current: Any, now: int) -> dict[str, Any]:
    """L'histoire d'une demande : l'épisode pendant lequel elle a été proposée, puis les dernières décisions sur des
    demandes de la même sorte — accordées ou refusées, par qui, avec quelle note, et comment elles ont tourné."""
    origin = None
    found = ui.kernel.mind.store.get_events([current.proposal])
    corr = found[0].correlation if found else ""
    ended = ctx.events([rt.EPISODE_ENDED], 1, correlations=[corr]) if corr else []
    if ended:
        e = ended[0]
        origin = {"text": f"{names.kind(e.data.kind)} · {ui.names.who(e.data.target)}" if e.data.target
                  not in (None, "", "none") else names.kind(e.data.kind),
                  "href": render.href(Ref("episode", corr, "")), "ago": render.relative(e.at, now)}
    elif corr in ui.kernel.mind.frame().state("runtime").open:
        origin = {"text": "un épisode en cours", "href": render.href(Ref("episode", corr, "")), "ago": ""}
    past = []
    for d in ctx.events([rt.EFFECT_RESOLVED], PRECEDENTS, where=("capability", current.capability)):
        ran = ctx.events([rt.EFFECT_EXECUTED], 1, where=("proposal", d.data.proposal))
        past.append({"approved": d.data.approved, "by": ui.names.who(d.data.by) if d.data.by else "",
                     "note": d.data.said(), "ago": render.relative(d.at, now), "exact": ui.when_long(d.at),
                     "href": render.href(Ref("event", str(d.data.proposal), "")), "proposal": d.data.proposal,
                     "ran": None if not ran else {"ok": ran[0].data.ok, "result": names.detail(ran[0].data.result)
                                                  if ran[0].data.result else ""}})
    return {"origin": origin, "past": past}


def _summary(texts: Any, p: Any) -> str:
    return texts.get(p.summary_ref, "(oublié)") if p.summary_ref else ""


#: un élément de la file qui n'est pas une demande d'envoi (``QueueItem``) : ``?element=<sorte>:<clé>``
ELEMENT = "element"
#: l'onglet de la file d'où l'on décide (le retour d'une décision y ramène)
FROM_TAB = "file"
MESSAGES = {"oui": [("ok", "Approuvé.")], "non": [("ok", "Refusé.")],
            "inconnu": [("warn", "Action inconnue ou déjà décidée.")],
            "change": [("warn", decisions.MESSAGES[decisions.CHANGED])],
            "bloque": [("warn", "Ça ne peut pas partir tel quel : relis-le.")],
            "jeton": [("danger", "Jeton de formulaire invalide : recharge la page.")]}


def _provider(ui: Any) -> Any:
    return getattr(ui.deps, "queue", None)


def _keeps(tab: QueueTab | None, capability: str) -> bool:
    return tab is None or capability in tab.capabilities


def _count(ui: Any, tab: QueueTab | None) -> int:
    """Combien attendent dans cet onglet de la file (toute la file : ``tab`` vide)."""
    effects = sum(1 for p in ui.kernel.mind.frame().get(rt.PENDING_EFFECTS) if _keeps(tab, p.capability))
    provider = _provider(ui)
    if provider is None or (tab is not None and not tab.kinds):
        return effects
    got = call(provider.count, ui, tab.kinds if tab is not None else None, label="file à valider : compte")
    return effects + (0 if isinstance(got, Failed) else int(got or 0))


async def _entries(ui: Any, tab: QueueTab | None) -> list[dict[str, Any]]:
    """La file d'un onglet, la plus ancienne d'abord : les demandes d'envoi qu'il garde, puis ce que la composition
    fournit (une identité à confirmer, un nom à relier)."""
    out = [{"sort": p.capability, "id": str(p.proposal), "effect": p, "item": None, "at": p.at}
           for p in ui.kernel.mind.frame().get(rt.PENDING_EFFECTS) if _keeps(tab, p.capability)]
    provider = _provider(ui)
    if provider is not None and (tab is None or tab.kinds):
        got = await acall(provider.items, ui, label="file à valider")
        for x in [] if isinstance(got, Failed) else got:
            if tab is None or x.kind in tab.kinds:
                out.append({"sort": x.kind, "id": f"{x.kind}:{x.key}", "effect": None, "item": x, "at": x.at})
    return sorted(out, key=lambda e: (e["at"], e["id"]))


def _back(href: str, back: str) -> str:
    """Une action sur sa propre page, qui ramène à la file (la suivante ouverte) plutôt qu'à sa page d'origine."""
    parts = urlsplit(href)
    if not parts.path.startswith(f"{PREFIX}/action/"):
        return href
    query = {k: v for k, v in parse_qsl(parts.query) if k != "retour"}
    return urlunsplit(("", "", parts.path, urlencode({**query, "retour": back}), ""))


def _item_view(ui: Any, request: Request, x: QueueItem, back: str) -> dict[str, Any]:
    """Un élément ouvert qui n'est pas une demande d'envoi : ses faits, sa source, ses actions (sur leur page, ou en
    boutons que la console prépare, avec leur jeton)."""
    forms = []
    for key, initial, title in x.actions:
        spec = ui.inspection.action(key)
        if spec is None or not offered(ui.kernel, spec, ""):
            continue
        view = action_view(spec, csrf=ui.csrf(request), back=back, subject="", initial=dict(initial))
        view["title"] = view["button"] = title or view["title"]
        forms.append(view)
    env = ui.env()
    return {"label": x.label, "summary": x.summary, "context": x.context, "note": x.note, "warn": x.warn,
            "ago": render.relative(x.at, ui.kernel.mind.frame().now) if x.at else "",
            "when": ui.when_long(x.at) if x.at else "",
            "facts": [{"label": k, "cell": v if isinstance(v, dict) else render.cell(v, env)} for k, v in x.facts],
            "sources": [{"text": t, "href": h} for t, h in x.sources],
            "links": [{"text": t, "href": _back(h, back)} for t, h in x.links], "forms": forms}


async def _queue(ui: Any, request: Request, tab: QueueTab | None) -> Any:
    """La file à gauche, une ligne par élément ; l'élément ouvert à droite (le gabarit « client », comme le courrier).
    Une demande d'envoi : ce qui partira tel quel, sa source, son historique, approuver ou refuser — la suivante
    s'ouvre après. Un autre élément (une identité à confirmer, un nom à relier) : ses faits, sa source, ses actions.
    Seule la demande ouverte calcule son aperçu."""
    kernel = ui.kernel
    frame = kernel.mind.frame()
    effects = frame.state("runtime").effects
    query = request.query_params
    everything = await _entries(ui, tab)
    counts = Counter(e["sort"] for e in everything)
    sort = query.get(KIND, "") if query.get(KIND, "") in counts else ""
    shown = [e for e in everything if not sort or e["sort"] == sort]
    ctx = ui.inspection.context(query)
    page, pager = paginate(shown, ctx.pager(size=QUEUE_PAGE))
    wanted = query.get(OPEN, "") or query.get(ELEMENT, "")
    current = next((e for e in shown if wanted and e["id"] == wanted), None) or (page[0] if page else None)
    refs = [e["effect"].summary_ref for e in [*page, current] if e is not None and e["effect"] is not None
            and e["effect"].summary_ref]
    texts = kernel.mind.store.content(refs)
    keep = {k: v for k, v in query.items() if k in (KIND, "page") and v}

    def href(e: Mapping[str, Any] | None) -> str:
        if e is None:
            return ""
        return "?" + urlencode({**keep, (OPEN if e["effect"] is not None else ELEMENT): e["id"]})

    now = frame.now
    rows = []
    for e in page:
        p, x = e["effect"], e["item"]
        rows.append({"capability": _kind(ui, p.capability) if p is not None else x.label,
                     "context": _about(ui, p.context) if p is not None else x.context,
                     "summary": " ".join((_summary(texts, p) if p is not None else x.summary).split())[:LINE_TEXT],
                     "ago": render.relative(e["at"], now) if e["at"] else "",
                     "exact": ui.when_long(e["at"]) if e["at"] else "", "href": href(e),
                     "on": current is not None and e["id"] == current["id"]})
    opened = None
    if current is not None:
        at = next(i for i, e in enumerate(shown) if e["id"] == current["id"])
        before = shown[at - 1] if at > 0 else None
        after = shown[at + 1] if at + 1 < len(shown) else None
        follow = after or before  # après une décision, la suivante ; la dernière décidée, la précédente
        base = {"position": at + 1, "total": len(shown), "previous": href(before), "next": href(after),
                "kind": sort, "tab": tab.slug if tab is not None else ""}
        back = request.url.path + (href(follow) if follow else "?" + urlencode(keep) if keep else "")
        p = current["effect"]
        if p is None:
            opened = {**base, "effect": False, **_item_view(ui, request, current["item"], back)}
        else:
            full = effects.get(p.proposal)
            try:
                args = json.dumps(json.loads(full.args_json), ensure_ascii=False, indent=1) if full else ""
            except ValueError:
                args = full.args_json if full else ""
            preview = await decisions.preview(kernel.mind, kernel.ports, p.capability, full.args_json) \
                if full else None
            opened = {**base, "effect": True, "proposal": p.proposal, "capability": _kind(ui, p.capability),
                      "described": ui.names.capability(p.capability), "capability_key": p.capability,
                      "owner": p.owner, "context": _about(ui, p.context), "summary": _summary(texts, p),
                      "args": args, "when": ui.when_long(p.at), "ago": render.relative(p.at, now),
                      "event": render.href(Ref("event", str(p.proposal), "")),
                      "preview": preview.text if preview is not None else "",
                      "seen": preview.digest if preview is not None else "",
                      "blocked": preview.blocked if preview is not None else "",
                      "follow": follow["id"] if follow is not None and follow["effect"] is not None else "",
                      "sources": _sources(ui, p, full.args_json if full else ""),
                      "history": _history(ui, ctx, p, now), "history_href": f"{PREFIX}/approbations/historique"}
    labels = {e["sort"]: (_kind(ui, e["sort"]) if e["effect"] is not None else e["item"].label) for e in everything}
    kinds = [{"text": labels[k], "count": n, "href": "?" + urlencode({KIND: k}), "on": k == sort}
             for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"panel": Panel("handmade/approbations/attente.html", {
                "items": rows, "opened": opened, "total": len(everything), "shown": len(shown),
                "kinds": kinds if len(kinds) > 1 else [], "kind": sort, "all_href": "?",
                "explicit": bool(wanted) and opened is not None and current["id"] == wanted,
                "empty": tab.empty if tab is not None else "",
                "pending_pager": render._pager(pager, query)}, styles=("handmade/approbations.css",)),
            "blocks": [], "messages": MESSAGES.get(query.get("fait", ""), [])}


@TABS.tab("approbations.en_attente", title="Tout ce qui attend", badge=lambda ui: _count(ui, None),
          description="Ce qui attend ta décision : ce qu'elle voudrait faire sortir de la machine (ce qui est montré "
                      "est exactement ce qui partira), les identités à confirmer, les noms à relier.")
async def pending(ui: Any, request: Request) -> Any:
    return await _queue(ui, request, None)


def queue_builtins(provider: Any) -> dict[str, Builtin]:
    """Les onglets de la file que la composition déclare (``QueueTab``) : la même file, filtrée."""
    out: dict[str, Builtin] = {}
    for tab in getattr(provider, "tabs", ()) or ():
        async def fn(ui: Any, request: Request, tab: QueueTab = tab) -> Any:
            return await _queue(ui, request, tab)
        key = f"approbations.{tab.slug}"
        out[key] = Builtin(key, tab.title, fn, badge=lambda ui, tab=tab: _count(ui, tab), order=tab.order,
                           description=tab.description)
    return out


#: l'historique, par page
HISTORY_PAGE = 30


@TABS.tab("approbations.historique", title="Historique des autorisations",
          description="Chaque décision (approuvé, refusé, par qui) et chaque exécution (réussie ou non), avec la "
                      "capacité concernée.")
async def history(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    done, pager = ctx.older([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], HISTORY_PAGE)
    # la capacité d'une exécution se lit sur sa décision
    proposals = {e.data.proposal for e in done if e.type.name == rt.EFFECT_EXECUTED.name}
    resolved = {p: found[0].data for p in proposals
                if (found := ctx.events([rt.EFFECT_RESOLVED], 1, where=("proposal", p)))}
    rows = []
    for e in done:
        is_decision = e.type.name == rt.EFFECT_RESOLVED.name
        capability = e.data.capability if is_decision else getattr(resolved.get(e.data.proposal), "capability", "")
        tone = "" if is_decision and e.data.approved else "muted" if is_decision else \
            ("ok" if e.data.ok else "danger")
        rows.append(Row((When(e.at), Badge("décidé" if is_decision else "exécuté", "info" if is_decision else "ok"),
                         Text(ui.names.capability(capability) if capability else "—", hint=capability),
                         Ref("event", str(e.data.proposal), f"n° {e.data.proposal}"),
                         Text(_detail(ui, e), "muted", clamp=200), Text(capability or "—", "mono")),
                        href=Ref("event", str(e.seq), ""), tone=tone))
    return [Table((Column("quand", "fit"), Column("quoi", "fit"), "capacité", Column("proposition", "fit"),
                   "détail", Column("capacité (clé)", detail=True)), tuple(rows), title="Décisions et exécutions",
                  empty="Rien n'a encore été décidé.", pager=pager)]


def _detail(ui: Any, e: Any) -> str:
    d = e.data
    if e.type.name == rt.EFFECT_RESOLVED.name:
        verdict = "approuvé" if d.approved else "refusé"
        return f"{verdict} par {ui.names.who(d.by) if d.by else '?'}" + (f" — {note}" if (note := d.said()) else "")
    return ("réussi" if d.ok else "échec") + (f" — {names.detail(d.result)}" if d.result else "")
