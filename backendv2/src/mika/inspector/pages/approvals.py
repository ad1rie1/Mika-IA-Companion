"""Approbations : ce qu'elle voudrait faire hors de la machine. Ce qui est
montré est exactement ce qui partira : quand la capacité le sait
(``preview``), l'aperçu du résultat, et c'est cet aperçu-là qu'on approuve ;
sinon, ses arguments un à un, le JSON replié. Les demandes en attente se lisent
comme un courrier : la file à gauche, la demande ouverte à droite, la suivante
après chaque décision. Ce qu'une demande concerne (une personne, un projet, un
service, une app, un canal) est lu par la composition (``queue.about``) :
l'inspecteur ne nomme aucun plugin. L'historique se pagine par demande tranchée
et se filtre par sorte et par issue."""

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
from mika.kernel.inspect import (
    Badge,
    Column,
    Nav,
    NavItem,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
    read_params,
)
from mika.runtime import decisions
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.operations import offered

#: la file des demandes, par page : une ligne chacune
QUEUE_PAGE = 50
#: la demande ouverte (``?demande=<n° de la proposition>``) et le filtre par sorte (``?sorte=<capacité>``)
OPEN, KIND = "demande", "sorte"
#: ce que la ligne d'une demande dit de ce qu'elle veut faire, au plus
LINE_TEXT = 160


def _concerns(ui: Any, context: str) -> tuple[str, str]:
    """Ce qu'une demande concerne, dit simplement, et la fiche où ça mène (vide : aucune). La composition le lit dans
    son contexte (``queue.about`` : une personne, un projet, un service, une app, un canal — jamais une personne pour
    un canal) ; sans elle, le nom que la console donne à toute cible."""
    if not context:
        return "", ""
    fn = getattr(_provider(ui), "about", None)
    got = call(fn, ui, context, label="file à valider : ce que concerne une demande") if fn is not None else None
    if got is None or isinstance(got, Failed):
        return ui.names.who(context).removeprefix("le "), ""
    text, link = got
    return str(text or ""), str(link or "")


#: ce que la ligne d'un argument montre d'une valeur, au plus (le JSON exact reste dans les détails techniques)
ARG_TEXT = 500


def _arguments(args_json: str) -> list[dict[str, str]] | None:
    """Les arguments d'une demande sans aperçu, un par ligne (« nom : valeur ») ; ``None`` s'ils ne se lisent pas."""
    try:
        args = json.loads(args_json or "{}")
    except ValueError:
        return None
    if not isinstance(args, dict):
        return None
    out = []
    for name, value in args.items():
        if name == decisions.SEEN_KEY:
            continue
        said = ("oui" if value else "non") if isinstance(value, bool) else "—" if value is None else \
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        out.append({"label": str(name), "value": said if len(said) <= ARG_TEXT else said[:ARG_TEXT] + "…"})
    return out


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
MESSAGES = {"oui": [("ok", "Approuvé.")], "non": [("ok", "Refusé.")],
            "inconnu": [("warn", "Action inconnue ou déjà décidée.")],
            "change": [("warn", decisions.MESSAGES[decisions.CHANGED])],
            "bloque": [("warn", "Ça ne peut pas partir tel quel : relis-le.")],
            "jeton": [("danger", "Jeton de formulaire invalide : recharge la page.")]}


def _provider(ui: Any) -> Any:
    return getattr(ui.deps, "queue", None)


def _keeps(tab: QueueTab | None, capability: str) -> bool:
    return tab is None or capability in tab.capabilities


def _covered(ui: Any) -> set[str]:
    """Les sortes qu'un onglet de la file garde déjà (ses capacités, ses sortes d'éléments) : leur onglet y mène, une
    puce de plus répéterait ce filtre."""
    return {k for t in getattr(_provider(ui), "tabs", ()) or () for k in (*t.capabilities, *t.kinds)}


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
        rows.append({"capability": ui.names.capability_short(p.capability) if p is not None else x.label,
                     "described": ui.names.capability(p.capability) if p is not None else "",
                     "context": _concerns(ui, p.context)[0] if p is not None else x.context,
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
            opened = {**base, "effect": True, "proposal": p.proposal,
                      "capability": ui.names.capability_phrase(p.capability),
                      "described": ui.names.capability(p.capability), "capability_key": p.capability,
                      "owner": p.owner, "context": _concerns(ui, p.context)[0], "summary": _summary(texts, p),
                      "args": args, "arguments": _arguments(full.args_json) if full else [],
                      "when": ui.when_long(p.at), "ago": render.relative(p.at, now),
                      "event": render.href(Ref("event", str(p.proposal), "")),
                      "preview": preview.text if preview is not None else "",
                      "seen": preview.digest if preview is not None else "",
                      "blocked": preview.blocked if preview is not None else "",
                      "follow": follow["id"] if follow is not None and follow["effect"] is not None else "",
                      "sources": _sources(ui, p, full.args_json if full else ""),
                      "history": _history(ui, ctx, p, now),
                      # tout l'historique de ce genre de demande : la même sorte, filtrée
                      "history_href": f"{PREFIX}/approbations/historique?" + urlencode({KIND: p.capability})}
    labels = {e["sort"]: (ui.names.capability_short(e["sort"]) if e["effect"] is not None else e["item"].label)
              for e in everything}
    hints = {e["sort"]: ui.names.capability(e["sort"]) for e in everything if e["effect"] is not None}
    # une puce par sorte, sauf celles qu'un onglet de la file garde déjà (sur « Tout ») : deux chemins ne mènent pas
    # au même filtre ; celle qui filtre reste, qu'on voie ce qui est filtré
    covered = _covered(ui) if tab is None else set()
    kinds = [{"text": labels[k], "hint": hints.get(k, ""), "count": n, "href": "?" + urlencode({KIND: k}),
              "on": k == sort}
             for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if k not in covered or k == sort]
    return {"panel": Panel("handmade/approbations/attente.html", {
                "items": rows, "opened": opened, "total": len(everything), "shown": len(shown),
                "kinds": kinds if len(counts) > 1 and kinds else [], "kind": sort, "all_href": "?",
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


#: l'historique, par page : des demandes tranchées, chacune avec son exécution — une décision et son exécution ne se
#: séparent jamais d'une page à l'autre
HISTORY_PAGE = 30
#: un filtre qui écarte beaucoup de décisions lit le journal par lots, au plus tant, puis dit que la recherche continue
HISTORY_SCAN = 200
HISTORY_SCAN_BATCHES = 10
#: l'issue d'une demande tranchée (``?issue=``) : un bouton à choix, toujours posé
ISSUE = "issue"
ALL, APPROVED, REFUSED, FAILED = "tout", "approuve", "refuse", "echec"
ISSUES = ((ALL, "Toutes"), (APPROVED, "Approuvées"), (REFUSED, "Refusées"), (FAILED, "En échec"))
#: ses filtres : la sorte (``?sorte=<capacité>``, en puces dans la page — gardée par le bouton à choix) et l'issue
HISTORY_PARAMS = (Param(KIND, "Sorte", "hidden"), Param(ISSUE, "Issue", "select", ISSUES, default=ALL))
#: la liste des demandes tranchées, et la rangée de puces de ses sortes
HISTORY_TABLE, HISTORY_SORTS = "Décisions et exécutions", "Sorte de demande"


#: les exécutions d'une demande qu'on relit avec sa décision, au plus (d'ordinaire une seule)
RUNS_SHOWN = 4


def _runs(ctx: Any, proposal: int) -> list[Any]:
    """Les exécutions d'une demande approuvée, la dernière d'abord (aucune : pas encore revenue)."""
    return ctx.events([rt.EFFECT_EXECUTED], RUNS_SHOWN, where=("proposal", proposal))


def _decided(ctx: Any, sort: str, issue: str, before: int | None) -> tuple[list[tuple[int, Any]], bool, int]:
    """Une page de demandes tranchées, du plus récent : ``(curseur, décision)`` — lues par leur décision, ou par leur
    exécution ratée (« en échec ») ; s'il en reste ; où reprendre quand le budget de lecture s'arrête avant d'avoir
    rempli la page (0 : il ne s'est pas arrêté). Lu par lots jusqu'à la remplir, et une de plus."""
    # le journal ne filtre que la sorte : un booléen (accordée, réussie) ne se lit pas pareil sous SQLite et MariaDB,
    # l'issue se lit ici ; « en échec » part des exécutions ratées, dont la décision se relit
    types = [rt.EFFECT_EXECUTED] if issue == FAILED else [rt.EFFECT_RESOLVED]
    where = ("capability", sort) if sort and issue != FAILED else None
    seen: set[int] = set()

    def keep(e: Any) -> Any:
        if e.data.proposal in seen:
            return None
        if issue == FAILED:
            if e.data.ok:
                return None
            found = ctx.events([rt.EFFECT_RESOLVED], 1, where=("proposal", e.data.proposal))
            d = found[0] if found else None
        else:
            d = e
        # une exécution sans décision (une demande qui n'en attendait pas) n'est pas une autorisation
        if d is None or (sort and d.data.capability != sort) or (issue == APPROVED and not d.data.approved) \
                or (issue == REFUSED and d.data.approved):
            return None
        seen.add(e.data.proposal)
        return d

    shown: list[tuple[int, Any]] = []
    cursor = before
    batch: list[Any] = []
    for _ in range(HISTORY_SCAN_BATCHES):
        batch = ctx.events(types, HISTORY_SCAN, where=where, before=cursor)
        for e in batch:
            if (got := keep(e)) is not None:
                shown.append((e.seq, got))
                if len(shown) > HISTORY_PAGE:
                    break
        if len(shown) > HISTORY_PAGE or len(batch) < HISTORY_SCAN:
            break
        cursor = batch[-1].seq
    more = len(shown) > HISTORY_PAGE
    stopped = not more and len(batch) == HISTORY_SCAN
    return shown[:HISTORY_PAGE], more, (cursor or 0) if stopped else 0


def _sorts(ui: Any, ctx: Any, sort: str, issue: str) -> Nav | None:
    """Les sortes de demandes déjà tranchées, en puces (les plus fréquentes d'abord) : chacune filtre l'historique,
    l'issue choisie gardée ; rien quand il n'y en a qu'une et qu'aucune ne filtre."""
    known = [str(c) for c, _, _ in sorted(ctx.tally(rt.EFFECT_RESOLVED, "capability"),
                                          key=lambda t: (-t[1], str(t[0]))) if c]
    if sort and sort not in known:
        known.append(sort)
    if len(known) < 2 and not sort:
        return None
    here = f"{PREFIX}/approbations/historique"
    kept = ((ISSUE, issue),) if issue != ALL else ()
    return Nav((NavItem("Toutes", Ref("local", here, "", kept), active=not sort),
                *(NavItem(ui.names.capability_short(c), Ref("local", here, "", ((KIND, c), *kept)), active=c == sort)
                  for c in known)), title=HISTORY_SORTS)


@TABS.tab("approbations.historique", title="Historique des autorisations",
          description="Chaque demande tranchée : ta décision (approuvée ou refusée, par qui, ta note) et son exécution "
                      "(réussie ou non, ce qu'elle a donné), à filtrer par sorte et par issue.")
async def history(ui: Any, request: Request) -> dict[str, Any]:
    ctx = ui.inspection.context(request.query_params)
    values, notes = read_params(HISTORY_PARAMS, request.query_params)
    sort, issue = values[KIND], values[ISSUE]
    before = ctx.int_param("avant", 0) or None
    page, more, stopped = _decided(ctx, sort, issue, before)
    entries = [(d, _runs(ctx, d.data.proposal) if d.data.approved else []) for _, d in page]
    # la plus récente d'abord : celle dont la dernière nouvelle (sa décision, ou son exécution) est la plus récente ;
    # chacune, sa décision et ses exécutions, la dernière en tête
    entries.sort(key=lambda dx: -max([dx[0].seq, *(x.seq for x in dx[1])]))
    rows = []
    for d, ran in entries:
        capability = d.data.capability
        about, link = _concerns(ui, d.data.context)
        said: tuple[Any, ...] = (Text(ui.names.capability_short(capability) if capability else "—", hint=capability),
                                 Ref("event", str(d.data.proposal), f"n° {d.data.proposal}"),
                                 Ref("local", link, about) if link else (about or "—"))
        for x in ran:
            rows.append(Row((When(x.at), Badge("exécuté", "ok"), *said, Text(_detail(ui, x), "muted", clamp=200),
                             Text(capability or "—", "mono")),
                            href=Ref("event", str(x.seq), ""), tone="ok" if x.data.ok else "danger"))
        rows.append(Row((When(d.at), Badge("décidé", "info"), *said, Text(_detail(ui, d), "muted", clamp=200),
                         Text(capability or "—", "mono")),
                        href=Ref("event", str(d.seq), ""), tone="" if d.data.approved else "muted"))
    if more:
        pager = Pager(older=(("avant", str(page[-1][0])),))
    elif stopped:
        pager = Pager(older=(("avant", str(stopped)),))
    elif not before:
        pager = Pager(param="avant", size=max(1, len(rows)), total=len(rows))
    else:
        pager = Pager(param="avant")
    out: list[Any] = [Note(n, "warn") for n in notes]
    if (chips := _sorts(ui, ctx, sort, issue)) is not None:
        out.append(chips)
    out.append(Table((Column("quand", "fit"), Column("quoi", "fit"), "capacité", Column("proposition", "fit"),
                      "concerne", "détail", Column("capacité (clé)", detail=True)), tuple(rows),
                     title=HISTORY_TABLE, pager=pager,
                     empty="Aucune demande tranchée ne correspond à ces filtres." if sort or issue != ALL
                     else "Rien n'a encore été décidé."))
    if stopped:
        out.append(Note("La recherche continue dans les décisions plus anciennes : utilise « Plus anciens ».", "info"))
    return {"blocks": out, "filters": HISTORY_PARAMS}


def _detail(ui: Any, e: Any) -> str:
    d = e.data
    if e.type.name == rt.EFFECT_RESOLVED.name:
        verdict = "approuvé" if d.approved else "refusé"
        return f"{verdict} par {ui.names.who(d.by) if d.by else '?'}" + (f" — {note}" if (note := d.said()) else "")
    return ("réussi" if d.ok else "échec") + (f" — {names.detail(d.result)}" if d.result else "")
