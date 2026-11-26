"""La fiche d'un projet › Dépendances, calquée sur l'écran Projets (ADR 0257, 0271, 0293, 0297) : ses sous-onglets en
adresses (``?vue=``) — Schéma, Demandes.

- **Schéma** : le projet au centre, ce qu'il lit d'un côté (« Il dépend de »), ce qui le lit de l'autre (« Dépendent
  de lui ») ; chaque lien dit son pourquoi (le mot de son propriétaire), ce qu'il donne (``links.Grant`` : le voir, son
  détail, ses fichiers, sa documentation), le commit que montre la vue de son atelier et ses demandes. Un lien choisi
  (``lien=<n>``) ouvre le panneau : ce que le lien donne, sa vue, ses demandes et leur mode (direct ou sur accord), et
  ses gestes — changer son mot, le mode direct, le retirer. « Ajouter une dépendance » (``ajouter=1``) propose les
  projets qu'il peut lire, chacun avec son pourquoi.
- **Demandes** : celles qu'il a envoyées (un ticket chez le projet lu) et celles qu'il a reçues (un ticket chez lui),
  une liste et le détail de l'une, avec son ticket.

Tout geste est l'action déclarée ``projects.liens``, qui prend tout l'état (ce qu'il lit, le mode direct de chaque
lien) : la page le prépare avec ce qui ne change pas posé, comme l'API (``app/domains/projects/api/projects.py::set_links``), et le mot
d'un lien en valeurs fixées (``why``, ``why_for``), avec l'état qu'elle a lu (``seen``) : s'il a bougé depuis (un autre
onglet), l'action refuse au lieu de défaire ce qui a changé. Un geste sur un lien revient sur lui. Les règles (qui peut être lu, la boucle, la borne, le mode
direct) restent celles de l'action.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from markupsafe import Markup

from mika.app.domains.projects.console.zones import DONE, FAIL, WAIT, WORK, YOU, Scene, shown, tab_url
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import asks, links, tickets, tracker
from mika.faculties.projects.actions import (
    DIRECT_REFUSALS,
    LINK_WHY_MAX,
    direct_knob,
    link_knob,
    link_options,
    links_seen,
)
from mika.faculties.projects.faculty import tie_of
from mika.faculties.projects.inspect import ASK_MODES, ASK_WORDS, STATUS_FR
from mika.faculties.projects.inspect_common import FORGOTTEN
from mika.inspector.ui import env
from mika.vocab.access import STEER_NO

TAB = "liens"
SCHEMA, ASKS = "", "demandes"
#: l'état d'un projet → sa couleur ; où en est une demande → la sienne
STATE_TONES = {c.ACTIVE: WORK, c.PAUSED: YOU, c.ARCHIVED: WAIT}
ASK_TONES = {asks.PENDING: YOU, asks.ACCEPTED: WORK, asks.WORKING: WORK, asks.DONE: DONE, asks.DROPPED: WAIT}
#: ce qu'un lien peut donner, dans l'ordre de l'écran : (son nom, ce qu'il ouvre, s'il le donne)
GIVES = (("Le voir", "le minimum : son nom, son état, où il en est", lambda g: g.see),
         ("Son détail", "ses objectifs, ses tickets, son activité", lambda g: g.detail),
         ("Ses fichiers", "le dépôt, en lecture, par la vue de son atelier", lambda g: g.view),
         ("Sa documentation", "ses pages, en lecture", lambda g: g.documentation))


def _owner(sc: Scene, p: Any) -> str:
    owner = links.owner_of(p)
    return f"à {identity_c.person_name(sc.frame, owner) or owner}" if owner else f"à {sc.ui.her_name()}"


def _card(sc: Scene, t: Any, grant: Any, names: Mapping[str, str], why_ref: str, since: int, *, reading: bool,
          suspended: bool = False) -> dict[str, Any]:
    """Un projet lié, sur le schéma : son nom, son état, à qui, le pourquoi du lien, ce qu'il donne, sa vue, ses
    demandes."""
    sent = [a for a in sc.p.asks if a.target == t.id] if reading else \
        asks.received(sc.p, t.id)
    return {"n": t.id, "title": names.get(t.title_ref, FORGOTTEN), "state": STATUS_FR.get(t.status, t.status),
            "tone": STATE_TONES.get(t.status, WAIT), "owner": _owner(sc, t), "why": names.get(why_ref, ""),
            "since": sc.day(since) if since else "", "suspended": suspended,
            "gives": [{"label": label, "said": said, "on": bool(on(grant))} for label, said, on in GIVES],
            "commit": t.base_commit[:7] if grant.view and t.base_commit else "", "asks": len(sent),
            "mode": ASK_MODES[asks.mode(sc.p, t, grant) if reading else asks.mode(t, sc.p, grant)],
            "direct": reading and t.id in sc.p.direct, "href": sc.url(TAB, lien=t.id), "reading": reading,
            "fiche": tab_url(str(t.id), "apercu")}


def links_page(sc: Scene) -> Markup | None:
    """L'onglet Dépendances : sa barre (Schéma, Demandes ; à son bout, « Ajouter une dépendance »), puis la sous-vue."""
    p = sc.p
    if p is None:
        return None
    world = links.world_of(sc.frame)
    read, readers = links.readings(sc.s, p, world), links.readers(sc.s, p, world)
    received = asks.received(p)
    view = sc.query.get("vue", "")
    view = view if view == ASKS else SCHEMA
    form = sc.form("liens", sc.url(TAB))
    options = link_options(sc.s, sc.frame, p) if form is not None else []
    candidates = [t for t, _ in options if t.id not in p.reads]
    context: dict[str, Any] = {
        "view": view, "bar": [{"label": "Schéma", "on": view == SCHEMA, "count": len(read) + len(readers),
                               "href": sc.url(TAB)},
                              {"label": "Demandes", "on": view == ASKS, "count": len(p.asks) + len(received),
                               "href": sc.url(TAB, vue=ASKS)}],
        "add_href": sc.url(TAB, ajouter=1) if candidates else "", "adding": bool(sc.query.get("ajouter"))}
    if view == ASKS:
        context.update(_asks_view(sc, received))
    else:
        context.update(_schema(sc, read, readers, form, candidates))
    return Markup(env.get_template("handmade/projets/dependances.html").render(**context))


def _posed(p: Any, reads: Iterable[int], direct: Iterable[int]) -> dict[str, str]:
    """Tout l'état de ``projects.liens`` posé sans se montrer : ce qu'il lit, le mode direct de chaque lien."""
    return {**{link_knob(t): "on" for t in reads}, **{direct_knob(t): "on" for t in direct if t in reads}}


def _gesture(form: Mapping[str, Any] | None, reads: Iterable[int], direct: Iterable[int], p: Any,
             why_for: int = 0, why: bool = False, back: str = "") -> dict[str, Any] | None:
    """Le formulaire de ``projects.liens`` pour un geste : l'état voulu posé, et — pour dire le pourquoi d'un lien —
    son mot en valeur fixée, comme l'API la passe (``why``, ``why_for``). L'état que la page a lu part avec lui
    (``seen``, ``actions.links_seen``) : s'il a bougé depuis, l'action refuse plutôt que de défaire ce qui a changé.
    ``back`` : où l'on revient (le lien visé)."""
    got = shown(form, **_posed(p, list(reads), list(direct)))
    if got is None:
        return None
    return {**got, "fixed": [*(got.get("fixed") or ()), ("seen", links_seen(p))], "why_for": why_for if why else 0,
            "why_max": LINK_WHY_MAX, **({"back": back} if back else {})}


def _schema(sc: Scene, read: Any, readers: Any, form: Any, candidates: list[Any]) -> dict[str, Any]:
    p = sc.p
    ties = {r.id: tie_of(p, r.id) for r in read}
    reader_ties = {x.id: tie_of(x, p.id) for x, _ in readers}
    named = [*(r.project for r in read if r.project is not None), *(x for x, _ in readers), *candidates]
    names = sc.texts([*(t.title_ref for t in named), *(t.why_ref for t in ties.values()),
                      *(t.why_ref for t in reader_ties.values()), p.title_ref, p.summary_ref])
    deps = [_card(sc, r.project, r.grant, names, ties[r.id].why_ref, ties[r.id].since, reading=True,
                  suspended=r.suspended) for r in read if r.project is not None]
    gone = [r.id for r in read if r.project is None]
    users = [_card(sc, x, grant, names, reader_ties[x.id].why_ref, reader_ties[x.id].since, reading=False)
             for x, grant in readers]
    g_open = sum(1 for o in p.objectives if o.status == c.OPEN)
    center = {"title": names.get(p.title_ref, FORGOTTEN), "state": STATUS_FR.get(p.status, p.status),
              "tone": STATE_TONES.get(p.status, WAIT), "summary": names.get(p.summary_ref, ""),
              "objectives": g_open, "tickets": sum(1 for x in p.board.items if x.list_name == c.TICKETS
                                                  and x.status in c.STAGES_OPEN),
              "asks": len(p.asks)}
    wanted = sc.query.get("lien", "")
    chosen = next((x for x in [*deps, *users] if wanted.isdecimal() and x["n"] == int(wanted)), None) \
        if wanted else (deps[0] if deps else users[0] if users else None)
    for x in [*deps, *users]:
        x["on"] = chosen is not None and x is chosen
    reads, direct = list(p.reads), list(p.direct)
    adding = [] if form is None else [
        {"n": t.id, "title": names.get(t.title_ref, FORGOTTEN), "state": STATUS_FR.get(t.status, t.status),
         "tone": STATE_TONES.get(t.status, WAIT), "owner": _owner(sc, t),
         "planned": t.id in p.plan_reads,
         "gives": [label for label, _, on in GIVES if on(links.grant(p, t, links.world_of(sc.frame)))],
         "form": _gesture(form, [*reads, t.id], direct, p, t.id, why=True, back=sc.url(TAB, lien=t.id))}
        for t in candidates]
    out: dict[str, Any] = {"deps": deps, "users": users, "center": center, "gone": gone, "panel": None,
                           "candidates": adding, "plan_asks": [t for t in p.plan_reads if t not in p.reads]}
    if chosen is None:
        return out
    panel = dict(chosen)
    t = sc.s.projects.get(chosen["n"])
    if chosen["reading"] and form is not None:
        others = [x for x in reads if x != t.id]
        here = sc.url(TAB, lien=t.id)  # changer son mot ou son mode revient sur ce lien, pas sur le premier
        panel["why_form"] = _gesture(form, reads, direct, p, t.id, why=True, back=here)
        panel["drop"] = {**_gesture(form, others, [x for x in direct if x != t.id], p),
                         "confirm": f"Ne plus lire « {chosen['title']} » ? Ses demandes déjà faites restent chez lui."}
        why_not = asks.indirect(p, t, links.grant(p, t, links.world_of(sc.frame)))
        panel["direct_form"] = _gesture(form, reads, [x for x in direct if x != t.id] if t.id in direct
                                        else [*direct, t.id], p, back=here) if t.id in direct or not why_not else None
        panel["direct_why"] = "" if t.id in direct or not why_not else DIRECT_REFUSALS.get(why_not, why_not)
    panel["requests"] = _requests(sc, t, chosen["reading"])
    panel["ask_href"] = tab_url(str(t.id), "tickets", nouveau=1) \
        if chosen["reading"] and links.grant(p, t, links.world_of(sc.frame)).ask != STEER_NO else ""
    out["panel"] = panel
    return out


def _requests(sc: Scene, t: Any, reading: bool) -> list[dict[str, Any]]:
    """Les demandes entre lui et ce projet : celles qu'il lui a faites (lu) ou qu'il en a reçues (lecteur)."""
    store = sc.ui.kernel.mind.store
    if reading:
        found = [(a, tracker.entry(store, a.target, c.TICKETS, a.key)) for a in sc.p.asks if a.target == t.id]
        return [{"n": a.number, "title": e.title if e is not None else f"Ticket #{a.number}",
                 "state": ASK_WORDS[asks.state(a.status)], "tone": ASK_TONES[asks.state(a.status)],
                 "href": sc.url(TAB, vue=ASKS, demande=f"{t.id}-{a.number}")} for a, e in found]
    got = asks.received(sc.p, t.id)
    words = sc.texts(x.title_ref for x in got)
    return [{"n": x.number, "title": words.get(x.title_ref, FORGOTTEN), "state": ASK_WORDS[asks.state(x.status)],
             "tone": ASK_TONES[asks.state(x.status)], "href": sc.url(TAB, vue=ASKS, demande=f"r-{x.number}")}
            for x in got]


def _asks_view(sc: Scene, received: list[Any]) -> dict[str, Any]:
    """Ses demandes : envoyées (un ticket chez le projet lu) et reçues (un ticket chez lui), les plus récentes
    d'abord ; l'une choisie (``demande=<projet>-<n>`` ou ``r-<n>``) avec son ticket."""
    p, store = sc.p, sc.ui.kernel.mind.store
    rows = []
    for a in sorted(p.asks, key=lambda a: -a.at):
        t = sc.s.projects.get(a.target)
        e = tracker.entry(store, a.target, c.TICKETS, a.key)
        rows.append({"key": f"{a.target}-{a.number}", "sent": True, "n": a.number, "title": e.title if e else
                     f"Ticket #{a.number}", "state": ASK_WORDS[asks.state(a.status)],
                     "tone": ASK_TONES[asks.state(a.status)], "project": t, "at": a.at, "closed": a.closed_at,
                     "objective": a.objective, "item": e.item if e is not None else None,
                     "ticket_href": tab_url(str(a.target), "tickets", element=f"#{a.number}")})
    words = sc.texts(x.title_ref for x in received)
    for x in sorted(received, key=lambda x: -x.at):
        t = sc.s.projects.get(c.asking_project(x.author))
        rows.append({"key": f"r-{x.number}", "sent": False, "n": x.number,
                     "title": words.get(x.title_ref, FORGOTTEN), "state": ASK_WORDS[asks.state(x.status)],
                     "tone": ASK_TONES[asks.state(x.status)], "project": t, "at": x.at, "closed": 0, "objective": 0,
                     "item": x, "ticket_href": sc.url("tickets", element=f"#{x.number}")})
    names = sc.texts(r["project"].title_ref for r in rows if r["project"] is not None)
    wanted = sc.query.get("demande", "")
    chosen = next((r for r in rows if r["key"] == wanted), rows[0] if rows and not wanted else None)
    items = [{**{k: v for k, v in r.items() if k not in ("project", "item")},
              "to": names.get(r["project"].title_ref, FORGOTTEN) if r["project"] is not None else "un projet effacé",
              "ago": sc.age(r["at"]), "on": r is chosen, "href": sc.url(TAB, vue=ASKS, demande=r["key"])}
             for r in rows]
    out: dict[str, Any] = {"rows": items, "lire": bool(wanted), "ask": None, "home": sc.url(TAB, vue=ASKS)}
    if chosen is None:
        return out
    t, item = chosen["project"], chosen["item"]
    hand = {c.ACTOR_OWNER: "son propriétaire", c.ACTOR_SELF: "elle"}.get(tickets.hand(item), "—") \
        if item is not None else "—"
    out["ask"] = {**next(x for x in items if x["on"]), "since": sc.when(chosen["at"]),
                  "closed": sc.when(chosen["closed"]) if chosen["closed"] else "", "hand": hand,
                  "stage": tracker.status_words(c.TICKETS, item.status) if item is not None else "",
                  "project_href": tab_url(str(t.id), "apercu") if t is not None else "",
                  "link_href": sc.url(TAB, lien=t.id) if t is not None else "",
                  "objective_href": sc.url("objectifs", objectif=chosen["objective"]) if chosen["objective"] else "",
                  "read": item is not None, "tones": (DONE, FAIL)}
    return out
