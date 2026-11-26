"""Projet › Tickets et Projet › Listes (ADR 0297), calqués sur l'écran Projets : son registre (ADR 0268), lu dans sa
projection.

**Tickets** (``tickets_page``, ``tickets.html``) : les trois zones. La liste — la recherche, les filtres (ceux qui
attendent quelqu'un, ouverts, tous), « Nouveau ticket », une ligne par ticket (son numéro, son titre, son étape en
pastille, sa priorité, « ailleurs » pour ce qui vient de l'hôte ou d'un autre projet). Un ticket choisi
(``?element=#<n°>``) : au centre ses volets — Description, Plan, Fil, Historique —, « Modifier » dans le contenu ; à
droite son parcours en six étapes (``tickets.journey``), « En bref », et « Ce qui est lié » : son objectif, sa pull
request avec son statut, son issue et son lien chez l'hôte. Ses gestes sont ceux que son étape ouvre : l'accepter,
l'écarter, valider ou refuser son plan (la validation nomme le plan lu), le fermer, le rouvrir, écrire dans son fil,
le publier en issue. Un texte venu d'ailleurs se présente comme tel, en texte brut.

**Listes** (``lists_page``, ``listes.html``) : ses listes de suivi — par statut (des colonnes, chaque élément en
carte) ou en tableau ; un élément choisi ouvre le panneau : son statut et à qui il est (ils s'y changent), son texte,
son fil et de quoi y écrire, son historique ; « Ajouter » et « Régler la liste » y ouvrent leur formulaire.

**Ce qu'il lit** : ``tracker`` (la projection : une page, un élément, son fil, son histoire rejouée du journal) et
``tickets`` (le parcours, à qui est la main), que lit aussi l'API par personne ; la console lit tout
(``tracker.ALL``). **Ses gestes** sont les actions déclarées de la faculté (``Scene.form``).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.domains.projects.console.zones import (
    DONE,
    OBJECTIVE_TONES,
    WAIT,
    WORK,
    YOU,
    Scene,
    markdown,
    pull_card,
    pull_href,
    shown,
    tab_url,
)
from mika.contracts import projects as c
from mika.faculties.projects import issues, tickets, tracker
from mika.faculties.projects.faculty import MOVE_PUBLISH, by_pulls, issue_move, objective_at, reflected
from mika.faculties.projects.inspect_common import FORGOTTEN
from mika.faculties.projects.inspect_issues import ISSUE_FR
from mika.faculties.projects.inspect_tracker import (
    JOURNEY_WORDS,
    KIND_WORDS,
    NOTE_WORDS,
    PRIORITY_WORDS,
    shown_actor,
    shown_author,
    shown_changer,
    shown_hand,
)
from mika.faculties.projects.inspect_words import OBJ_FR
from mika.inspector import render
from mika.inspector.ui import env
from mika.kernel.inspect import Pager, plural

#: ses filtres : (la valeur de l'adresse, ses mots)
FILTERS = (("attente", "En attente"), ("ouverts", "Ouverts"), ("tous", "Tous"))
#: les tickets d'une page de la liste, au plus ; les éléments d'une liste de suivi qu'on dessine, au plus
SHOWN, ITEMS_SHOWN = 40, 200
#: les événements d'un ticket relus pour son histoire, au plus
HISTORY_READ = 2000
#: l'icône d'une étape du parcours, dans son histoire
STEP_ICONS = {tickets.STEP_UNREAD: "ticket", tickets.STEP_ANALYSIS: "eye", tickets.STEP_VALIDATION: "list",
              tickets.STEP_PULL: "pr", tickets.STEP_MERGE: "merge", tickets.STEP_TREATED: "check"}
PRIORITIES_HIGH = (c.HIGH, c.URGENT)
#: à qui est la main, dans une phrase (« la main est au propriétaire »)
HAND_TO = {c.ACTOR_OWNER: "au propriétaire", c.ACTOR_SELF: "à elle"}


def _store(sc: Scene) -> Any:
    return sc.ui.kernel.ports["store"]


def ticket_tone(item: Any) -> str:
    """La couleur d'un ticket : traité, écarté, la main au propriétaire, pas encore lu, sinon elle y travaille."""
    if item.status == c.STAGE_TREATED:
        return DONE
    if item.closed:
        return WAIT
    if tickets.hand(item) == c.ACTOR_OWNER:
        return YOU
    return WAIT if item.status in (c.STAGE_UNREAD, c.STAGE_PROPOSED) else WORK


def _filters(sc: Scene, wanted: str, q: str) -> list[dict[str, Any]]:
    b = sc.p.board
    counts = {"attente": sum(tracker.count(b, c.TICKETS, st) for st in tickets.OWNERS),
              "ouverts": tracker.open_tickets(b), "tous": tracker.count(b, c.TICKETS)}
    return [{"text": label, "count": counts[code], "on": code == wanted,
             "href": sc.url("tickets", filtre="" if code == "ouverts" else code, q=q)} for code, label in FILTERS]


def _journey(sc: Scene, item: Any) -> dict[str, Any]:
    """Son parcours en six étapes : chacune dans son état ; celle où il est, avec son étape fine et à qui la main."""
    j = tickets.journey(item, by_pulls(sc.p))
    fine = tracker.status_words(c.TICKETS, item.status)
    hand = "" if item.closed else HAND_TO.get(tickets.hand(item), "")
    steps = []
    for n, (step, state) in enumerate(j.steps, start=1):
        here = state == tickets.CURRENT
        label = JOURNEY_WORDS[step]
        sub = " · ".join(x for x in (fine if here and fine.lower() != label.lower() else "",
                                     f"la main est {hand}" if here and hand else "") if x)
        steps.append({"n": n, "label": label, "cls": "fait" if state == tickets.PASSED else
                      f"ici {ticket_tone(item)}" if here else "saute" if state == tickets.SKIPPED else "",
                      "icon": "check" if state == tickets.PASSED else "minus" if state == tickets.SKIPPED else "",
                      "sub": sub or ("sautée" if state == tickets.SKIPPED else ""), "here": here})
    return {"steps": steps, "ended": fine if j.ended == c.STAGE_DISMISSED else "",
            "skips": "" if j.through_pull else "Ce ticket ne passe pas par une pull request : il saute ces deux "
                                                "étapes."}


def _history(sc: Scene, item: Any) -> list[dict[str, Any]]:
    """L'histoire de ses étapes, rejouée de son journal par les règles de l'état (``tracker.passages``) : quand il
    est passé par chacune, par qui."""
    mind, flow = sc.ui.kernel.mind, by_pulls(sc.p)
    raw = mind.store.latest([t.name for t in tracker.MOVES], HISTORY_READ, where=("key", item.key))
    events = [d for d in (mind.decode(x) for x in reversed(raw))
              if d.data.project == sc.p.id and d.data.list_name == item.list_name]
    out = []
    for x in tracker.passages(events):
        status = tracker.status_words(item.list_name, x.stage)
        who = shown_author(sc.frame, x.author, x.by)
        out.append({"when": sc.when(x.at), "ago": sc.ago(x.at),
                    "text": f"{status[:1].upper()}{status[1:]} — par {who}" if x.was else f"Ouvert par {who} — {status}",
                    "title": f"{tracker.status_words(item.list_name, x.was)} → {status}" if x.was else "",
                    "tone": DONE if x.stage == c.STAGE_TREATED else WAIT if x.stage in (c.STAGE_DISMISSED,
                                                                                         c.STAGE_UNREAD) else
                    YOU if x.stage in tickets.OWNERS else WORK,
                    "icon": "x" if x.stage == c.STAGE_DISMISSED else
                    STEP_ICONS.get(tickets.step_of(x.stage, flow), "check"), "outside": c.from_outside(x.author)})
    return out


def _thread(sc: Scene, item: Any) -> list[dict[str, Any]]:
    """Son fil, de la plus ancienne note à la plus récente : qui (elle, l'opérateur, une personne, l'hôte), quand,
    sa sorte, ses mots ; un changement dit se lit dans son historique."""
    out = []
    for n in tracker.thread(_store(sc), sc.p.id, item.list_name, item.key):
        if n.kind == tracker.CHANGE:
            continue
        side = "elle" if n.author == c.BY_SELF else "moi" if n.author in (c.BY_OPERATOR, c.BY_PERSON) else "autre"
        kind = NOTE_WORDS.get(n.kind, "") if n.kind != tracker.NOTE else ""
        out.append({"seq": n.seq, "side": side, "who": shown_author(sc.frame, n.author, n.by), "kind": kind,
                    "plan": n.seq == item.plan_seq, "ago": sc.ago(n.at), "when": sc.when(n.at),
                    "text": n.text or FORGOTTEN, "outside": c.from_outside(n.author)})
    return out


def _linked(sc: Scene, item: Any) -> dict[str, Any]:
    """Ce qui lui est lié : l'objectif qui le tient, sa pull request avec son statut, son issue chez l'hôte, le
    projet qui l'a demandé."""
    p = sc.p
    held = objective_at(p, item.objective) if item.objective else None
    out: dict[str, Any] = {"objective": None, "pull": None, "issue": None, "asker": c.asking_project(item.author)}
    if held is not None:
        said = sc.texts([held.text_ref])
        out["objective"] = {"n": held.id, "title": said.get(held.text_ref, FORGOTTEN),
                            "tone": OBJECTIVE_TONES.get(held.status, WAIT), "state": OBJ_FR.get(held.status, ""),
                            "href": sc.url("objectifs", objectif=held.id)}
        out["pull"] = pull_card(p, held, sc.now, pull_href(sc.key, held))
    if item.issue:
        closed = item.issue_state == "closed"
        out["issue"] = {"n": item.issue, "state": ISSUE_FR.get(item.issue_state, item.issue_state),
                        "tone": DONE if closed else WAIT, "url": issues.issue_page(p, item.issue)}
    if out["asker"]:
        out["asker_href"] = tab_url(str(out["asker"]), "liens")
    return out


def _publishing(sc: Scene, item: Any, name: str, back: str) -> dict[str, Any] | None:
    """Ce qu'on fait partir d'un ticket chez l'hôte (ADR 0275) : le publier — une fois —, puis une note de son fil,
    par son numéro. Chaque geste est une demande, dont l'aperçu attend dans « À valider »."""
    if not reflected(sc.p):
        return None
    if item.issue:
        return {"note": shown(sc.form("note_publier", back, item=name), "note")}
    if issues.unpublishable(item):
        return None
    waiting = issue_move(sc.p, item.number, MOVE_PUBLISH)
    if waiting is not None and (waiting.proposal or waiting.sent_at):
        return {"asked": True}
    return {"publish": shown(sc.form("ticket_publier", back, item=name))}


def _gestures(sc: Scene, item: Any, name: str, back: str) -> list[dict[str, Any]]:
    """Les gestes du moment, ceux que son étape ouvre : (le formulaire, son mot, s'il est le principal, son icône,
    s'il demande un mot)."""
    def settle(verdict: str, *paths: str, **more: Any) -> dict[str, Any] | None:
        return shown(sc.form("ticket_trancher", back, item=name, plan=str(item.plan_seq), **more), *paths,
                     verdict=verdict)

    stage, out = item.status, []
    if stage == c.STAGE_VALIDATION:
        out += [{"form": settle("validate", "reason"), "label": "Valider le plan", "icon": "check", "main": True,
                 "title": f"Valider le plan n° {item.plan_seq} du ticket {name}", "submit": "Valider ce plan",
                 "ask": True},
                {"form": settle("refuse", "reason"), "label": "Refuser", "icon": "x", "ask": True,
                 "title": f"Refuser le plan du ticket {name}", "submit": "Refuser le plan"}]
    if stage == c.STAGE_PROPOSED:
        out.append({"form": settle("accept"), "label": "Accepter le ticket", "icon": "check", "main": True})
    if stage in c.STAGES_OPEN:
        out.append({"form": settle("dismiss", "reason"), "label": "Écarter", "icon": "x", "ask": True,
                    "title": f"Écarter le ticket {name}", "submit": "Écarter le ticket"})
        if stage != c.STAGE_PROPOSED:
            out.append({"form": settle("done"), "label": "Fermer", "icon": "check"})
    if stage in c.STAGES_CLOSED:
        out.append({"form": settle("reopen"), "label": "Rouvrir", "icon": "refresh"})
    return [g for g in out if g["form"] is not None]


def _ticket(sc: Scene, e: tracker.Entry, back: str) -> dict[str, Any]:
    """Un ticket, dans les trois zones : son en-tête et ses gestes, ses volets, son panneau."""
    item = e.item
    name = f"#{item.number}"
    thread = _thread(sc, item)
    plan = tracker.note_text(_store(sc), item.plan_seq) if item.plan_seq else ""
    asks = item.status == c.STAGE_DECISION
    waits_plan = item.status == c.STAGE_VALIDATION
    proposed = item.status == c.STAGE_PROPOSED
    first = "plan" if waits_plan else "fil" if asks or proposed else "description"
    by = shown_author(sc.frame, item.author, item.by)
    facts = [("La main", "—" if item.closed else shown_hand(item)),
             ("Priorité", PRIORITY_WORDS.get(item.priority, item.priority)),
             ("Sorte", KIND_WORDS.get(item.kind, item.kind)), ("Ouvert par", by),
             ("Mis à jour", sc.when(item.updated_at or item.at))]
    if item.accepted_at:
        facts.append(("Accepté par", shown_changer(sc.frame, item.accepted_by)))
    if item.validated_at:
        facts.append(("Plan validé par", shown_changer(sc.frame, item.validated_by) + (" (pris comme petit)" if item.small
                                                                                   else "")))
    if item.closed:
        facts.append(("Fermé par", shown_changer(sc.frame, item.closed_by)))
    if item.dismissal_at and not item.closed:
        facts.append(("Elle propose", "de l'écarter : confirme, ou réponds-lui dans son fil"))
    return {
        "name": name, "number": item.number, "title": e.title or FORGOTTEN, "tone": ticket_tone(item),
        "state": tracker.status_words(c.TICKETS, item.status), "kind": KIND_WORDS.get(item.kind, item.kind),
        "by": by, "ago": sc.ago(item.at), "outside": c.from_outside(item.author), "first": first,
        "high": item.priority in PRIORITIES_HIGH, "stuck": item.stuck,
        "body": e.body, "body_html": markdown(e.body) if e.body and not c.from_outside(item.author) else "",
        "link": e.link, "plan": {"seq": item.plan_seq, "html": markdown(plan), "waits": waits_plan,
                                 "state": tracker.status_words(c.TICKETS, item.status)} if plan else None,
        "no_plan": "Elle attend la réponse à sa question avant de l'écrire." if asks else
        "Elle n'y touche pas tant que le ticket n'est pas accepté." if proposed else
        tracker.status_words(c.TICKETS, item.status) if item.closed else "Elle l'écrira en analysant le ticket.",
        "thread": thread, "asks": asks, "proposed_outside": proposed and c.from_outside(item.author),
        "note": shown(sc.form("element_noter", back + "#t-fil", list_name=c.TICKETS, item=name), "text"),
        "history": _history(sc, item), "journey": _journey(sc, item), "facts": facts, "linked": _linked(sc, item),
        "gestures": _gestures(sc, item, name, back), "publishing": _publishing(sc, item, name, back),
        "edit": shown(sc.form("ticket_modifier", back + "#t-description", item=name, title=e.title, text=e.body, kind=item.kind,
                              priority=item.priority), "title", "kind", "priority", "text")
        if not item.closed else None}


def tickets_page(sc: Scene) -> Markup | None:
    """L'onglet Tickets : la liste et, à côté, le ticket choisi (le premier sinon), ou « Nouveau ticket »."""
    p = sc.p
    if p is None:
        return None
    wanted = sc.query.get("filtre") or "ouverts"
    wanted = wanted if wanted in dict(FILTERS) else "ouverts"
    q = (sc.query.get("q") or "").strip()[:120]
    lst = tracker.TICKET_LIST
    statuses = tickets.OWNERS if wanted == "attente" else lst.open if wanted == "ouverts" else ()
    store = _store(sc)
    found = tracker.page(store, p.id, c.TICKETS, statuses=statuses, search=q, limit=SHOWN)
    total = tracker.total(store, p.id, c.TICKETS, statuses=statuses, search=q)
    keep = {"filtre": "" if wanted == "ouverts" else wanted, "q": q}
    asked = sc.query.get("element") or ""
    adding = bool(sc.query.get("nouveau"))
    chosen = tracker.find(store, p.id, c.TICKETS, asked) if asked else None
    if chosen is None and not adding and not asked and found:
        chosen = found[0]
    rows = [{"n": e.item.number, "title": e.title or FORGOTTEN, "tone": ticket_tone(e.item),
             "state": tracker.status_words(c.TICKETS, e.item.status), "yours": tickets.hand(e.item) == c.ACTOR_OWNER
             and not e.item.closed, "high": e.item.priority in PRIORITIES_HIGH,
             "priority": PRIORITY_WORDS.get(e.item.priority, ""), "outside": c.from_outside(e.item.author),
             "ago": sc.ago(e.item.updated_at or e.item.at),
             "on": chosen is not None and chosen.item.number == e.item.number,
             "href": sc.url("tickets", element=f"#{e.item.number}", **keep)} for e in found]
    home = sc.url("tickets", **keep)
    back = sc.url("tickets", element=f"#{chosen.item.number}", **keep) if chosen is not None else home
    new = sc.form("ticket_ouvrir", home)
    return Markup(env.get_template("handmade/projets/tickets.html").render(
        rows=rows, more=max(0, total - len(found)), filters=_filters(sc, wanted, q), q=q, wanted=keep["filtre"],
        any=tracker.count(p.board, c.TICKETS) > 0, missing=asked if asked and chosen is None else "",
        detail=_ticket(sc, chosen, back) if chosen is not None and not adding else None,
        adding=shown(new, "title", "kind", "priority", "text") if adding else None, can_add=new is not None,
        lire=bool(asked) or adding, home=home, base=sc.url(), settings=sc.url("comportement", "cadre-tickets"),
        links={"nouveau": sc.url("tickets", nouveau=1, **keep)}))


# ── Ses listes de suivi ───────────────────────────────────────────────────────────────────────────────────────


def _status_tone(lst: Any, status: str) -> str:
    """La couleur d'un statut d'une liste : le premier ouvert attend, les autres ouverts avancent, un clos est fait."""
    if status in lst.closed:
        return DONE
    return WAIT if lst.open and status == lst.open[0] else WORK


def _element(sc: Scene, lst: Any, e: tracker.Entry, back: str) -> dict[str, Any]:
    """Un élément d'une liste, dans le panneau : son statut et à qui il est (ils s'y changent), son texte, son fil et
    de quoi y écrire, son historique."""
    item = e.item
    target = {"list_name": lst.name, "item": item.key}
    choices = [(tracker.status_words(lst.name, st), tracker.status_words(lst.name, st)) for st in
               (*lst.open, *lst.closed)]
    status = shown(sc.form("element_statut", back, status=tracker.status_words(lst.name, item.status), **target),
                   "status", "note")
    if status is not None:
        status["fields"] = [{**f, "kind": "select", "choices": choices} if f["path"] == "status" else f
                            for f in status["fields"]]
    history = [{"when": sc.when(x.at), "ago": sc.ago(x.at), "who": shown_changer(sc.frame, x.by),
                "text": tracker.change_words(lst.name, x.what)} for x in reversed(item.changes)]
    return {"key": item.key, "title": e.title or FORGOTTEN, "tone": _status_tone(lst, item.status),
            "state": tracker.status_words(lst.name, item.status), "actor": shown_actor(sc.frame, item),
            "added": sc.when(item.at), "touched": sc.when(item.updated_at), "body": e.body, "link": e.link,
            "objective": {"n": item.objective, "href": sc.url("objectifs", objectif=item.objective)}
            if item.objective else None,
            "by": shown_author(sc.frame, item.author, item.by), "thread": _thread(sc, item), "history": history,
            "status_form": status, "assign": shown(sc.form("element_confier", back, actor=item.actor
                                                           if item.actor != c.ACTOR_PERSON else c.ACTOR_SELF,
                                                           **target), "actor"),
            "note": shown(sc.form("element_noter", back, **target), "text")}


def lists_page(sc: Scene) -> Markup | None:
    """L'onglet Listes : ses listes de suivi, par statut ou en tableau, et dans le panneau l'élément choisi, « Ajouter
    un élément » ou « Régler la liste »."""
    p = sc.p
    if p is None:
        return None
    lists = p.board.lists
    asked = sc.query.get("liste") or ""
    lst = next((x for x in lists if x.name == asked), lists[0] if lists else None)
    table = sc.query.get("vue") == "tableau"
    said = sc.texts([x.title_ref for x in lists])
    setting = sc.form("liste_regler", sc.url("suivi", liste=lst.name if lst else ""),
                      **({"name": lst.name, "open": "\n".join(lst.open), "closed": "\n".join(lst.closed),
                          "actor": lst.actor} if lst is not None else {}))
    if lst is None:
        return Markup(env.get_template("handmade/projets/listes.html").render(lst=None, setting=setting, tabs=[]))
    keep = {"liste": lst.name, "vue": "tableau" if table else ""}
    store = _store(sc)
    found = tracker.page(store, p.id, lst.name, limit=ITEMS_SHOWN)
    total = tracker.count(p.board, lst.name)
    wanted = sc.query.get("element") or ""
    chosen = tracker.find(store, p.id, lst.name, wanted) if wanted else None
    mode = "ajouter" if sc.query.get("ajouter") else "regler" if sc.query.get("regler") else ""
    home = sc.url("suivi", **keep)
    back = sc.url("suivi", element=chosen.item.key, **keep) if chosen is not None else home

    def card(e: tracker.Entry) -> dict[str, Any]:
        item = e.item
        return {"key": item.key, "title": e.title or FORGOTTEN, "notes": plural(item.notes, "note", "notes")
                if item.notes else "", "actor": shown_actor(sc.frame, item), "ago": sc.ago(item.updated_at or item.at),
                "state": tracker.status_words(lst.name, item.status), "tone": _status_tone(lst, item.status),
                "yours": item.actor == c.ACTOR_OWNER and item.status not in lst.closed,
                "on": chosen is not None and chosen.item.key == item.key,
                "href": sc.url("suivi", element=item.key, **keep)}

    cards = [(e.item.status, card(e)) for e in found]
    known = tuple(dict.fromkeys((*lst.open, *lst.closed, *(st for st, _ in cards))))
    columns = [{"label": tracker.status_words(lst.name, st), "tone": _status_tone(lst, st),
                "count": tracker.count(p.board, lst.name, st), "items": [x for s, x in cards if s == st]}
               for st in known]
    add = sc.form("element_ajouter", home, list_name=lst.name)
    return Markup(env.get_template("handmade/projets/listes.html").render(
        lst={"name": lst.name, "title": said.get(lst.title_ref, "") or lst.name, "total": total,
             "living": tracker.living(p.board, lst)},
        tabs=[{"text": said.get(x.title_ref, "") or x.name, "count": tracker.count(p.board, x.name),
               "on": x.name == lst.name, "href": sc.url("suivi", liste=x.name, vue="tableau" if table else "")}
              for x in lists],
        table=table, columns=columns, rows=[x for _, x in cards], more=max(0, total - len(found)),
        # son tableau tient sur une page : sa pagination reste dans la page (la console l'exige), masquée
        pager=render.pager_ctx(Pager(size=max(1, len(cards)), total=max(1, len(cards))), {}),
        element=_element(sc, lst, chosen, back) if chosen is not None and not mode else None,
        missing=wanted if wanted and chosen is None else "",
        adding=shown(add, "title", "key", "text", "status", "actor", "link", list_name=lst.name)
        if mode == "ajouter" else None,
        setting=setting if mode == "regler" else None, can_add=add is not None, can_set=setting is not None,
        lire=chosen is not None or bool(mode), home=home,
        links={"colonnes": sc.url("suivi", liste=lst.name, element=wanted),
               "tableau": sc.url("suivi", liste=lst.name, vue="tableau", element=wanted),
               "ajouter": sc.url("suivi", ajouter=1, **keep), "regler": sc.url("suivi", regler=1, **keep)}))
