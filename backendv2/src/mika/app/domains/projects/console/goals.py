"""Projet › Objectifs (ADR 0297), calqué sur l'onglet Objectifs de l'écran Projets : la bascule Liste | Diagramme.

**La liste** (``goals``, ``objectifs.html``) : des lignes serrées — une par objectif : un point à la couleur de son
état, son texte, ses jalons en une barre, « 1/4 », son dernier passage ; une mission dit sa cadence à la place de la
barre —, groupées (en cours, missions, terminés, retirés) ; son filtre (ouverts, faits, retirés, tous) en pastilles,
« Ajouter un objectif » en tête, et son plan quand il n'attend rien (quand il attend sa réponse, il est en carte sur
la Vue d'ensemble).

**Un objectif choisi** (``?objectif=<n°>``) : les trois zones. Au centre, des volets — ses jalons (chacun avec
comment on le vérifie, sa preuve repliée, ses gestes : valider ou refuser un point d'arrêt, le modifier, le retirer ;
« Ajouter un jalon »), ses comptes rendus et sa relecture ; « Modifier » ouvre son formulaire dans le contenu. À
droite : ce qui le dit fini, où il en est, sa branche et sa pull request avec leur statut, ses tickets, et ce qui se
gère (le rouvrir, le dire terminé, le dire bloqué, le retirer). Une mission montre ce que chaque passage fait, ses
derniers passages, son rythme et ce qui la déclenche.

**Ce qu'il lit.** La tranche du projet (``project_at``) par les fonctions de la faculté que lit aussi l'API par
personne — ``glance.milestone_state``, ``milestones_of``, ``awaiting``, ``objective_tickets``, ``pulls`` — ; ses
comptes rendus, dans le journal (``projects.run_reported``). La console voit tout : rien n'est voilé. **Ses gestes**
sont les actions déclarées de la faculté, préparées par la console pour l'objet choisi (``Scene.form``).
"""

from __future__ import annotations

import shlex
from typing import Any

from markupsafe import Markup

from mika.app.domains.projects.console.zones import (
    DONE,
    FAIL,
    MARK_TONES,
    OBJECTIVE_TONES,
    WAIT,
    WORK,
    YOU,
    Scene,
    pull_card,
    pull_href,
    shown,
)
from mika.contracts import projects as c
from mika.faculties.projects import glance, milestones, tracker
from mika.faculties.projects.faculty import awaiting, by_pulls, milestones_of, objective_at, objective_tickets
from mika.faculties.projects.inspect import OBJ_FR, PLAN_FR, VERDICT_FR
from mika.faculties.projects.inspect_common import FORGOTTEN
from mika.faculties.projects.inspect_milestones import CHECK_CHOICES, CHECK_WORDS, STATE_FR
from mika.faculties.projects.inspect_reviews import REVIEW_WORDS
from mika.faculties.projects.triggers import trigger_words
from mika.inspector.ui import env
from mika.kernel.clock import HOUR
from mika.kernel.inspect import plural

#: un objectif est « vivant » tant qu'il est ouvert ou bloqué
LIVING = (c.OPEN, c.BLOCKED)
#: son filtre (celui de sa vue : ``inspect.OBJECTIVE_PARAM``) : la valeur de l'adresse, ses mots
FILTERS = (("vivants", "Ouverts"), (c.DONE, "Faits"), (c.DROPPED, "Retirés"), ("tous", "Tous"))
#: ses comptes rendus relus dans le journal, et ceux qu'on montre
REPORTS_READ, REPORTS_SHOWN = 400, 12
#: un verdict d'exécution → sa couleur
VERDICT_TONES = {c.CONTINUE: WORK, c.DONE: DONE, c.BLOCKED: FAIL, c.WAIT: YOU}
#: l'icône d'un jalon, par sa couleur
MARK_ICONS = {DONE: "check", YOU: "stop", WORK: "play", FAIL: "x", "": "minus"}
#: ce qu'un changement de statut s'appelle, sur son bouton : (statut visé, ses mots pour un objectif, pour une mission)
MOVES = ((c.OPEN, "Rouvrir l'objectif", "Rouvrir la mission"), (c.DONE, "Le dire terminé", ""),
         (c.BLOCKED, "Le dire bloqué", "La mettre de côté"), (c.DROPPED, "Retirer l'objectif", "Retirer la mission"))
#: les champs qu'un formulaire ne montre que pour certaines valeurs d'un autre (``data-only``, ``console.js``)
GOAL_ONLY = {"done_when": f"kind={c.ONCE}", **dict.fromkeys(("cadence_hours", "on", "only_on_event", "routine",
                                                               "at_once"), f"kind={c.CONSTANT}")}
CHECK_ONLY = {"command": f"check={c.CHECK_COMMAND}", **dict.fromkeys(("item_list", "item", "item_status"),
                                                                       f"check={c.CHECK_ITEM}")}


def conditional(form: dict[str, Any] | None, only: dict[str, str]) -> dict[str, Any] | None:
    """Un formulaire dont certains champs ne valent que pour une valeur d'un autre : la console les masque sinon."""
    if form is None:
        return None
    return {**form, "fields": [{**f, "only": only.get(f["path"], f.get("only", ""))} for f in form["fields"]]}


def _wanted(sc: Scene) -> str:
    asked = sc.query.get("objectifs") or "vivants"
    return asked if asked in dict(FILTERS) else "vivants"


def marks(o: Any) -> list[str]:
    """Ses jalons vivants en couleurs, un à un (``glance.milestone_state``)."""
    return [MARK_TONES[glance.milestone_state(o, m)] for m in milestones_of(o)]


def _row(sc: Scene, o: Any, said: dict[str, str], chosen: int, keep: dict[str, str]) -> dict[str, Any]:
    alive = milestones_of(o)
    mission = o.kind == c.CONSTANT
    return {"id": o.id, "text": said.get(o.text_ref, FORGOTTEN), "mission": mission, "on": o.id == chosen,
            "href": sc.url("objectifs", objectif=o.id, **keep),
            "tone": (WORK if o.status == c.OPEN else WAIT) if mission else OBJECTIVE_TONES.get(o.status, WAIT),
            "state": OBJ_FR.get(o.status, o.status), "awaits": awaiting(o) is not None, "marks": marks(o),
            "count": f"{sum(1 for m in alive if m.status == c.REACHED)}/{len(alive)}" if alive else "",
            "cadence": ("sur événement" if o.only_on_event else glance.cadence_words(o)) if mission else "",
            "age": sc.age(o.last_run_at)}


def _groups(sc: Scene, wanted: str, chosen: int, said: dict[str, str]) -> list[dict[str, Any]]:
    """Ses objectifs en groupes, selon le filtre : en cours (dans l'ordre du plan), missions, terminés, retirés."""
    p = sc.p
    keep = {"objectifs": wanted} if wanted != "vivants" else {}
    order = lambda o: (o.rank or 10_000, o.id)  # noqa: E731 — l'ordre du plan
    found = (
        ("En cours", wanted in ("vivants", "tous"),
         [o for o in p.objectives if o.kind == c.ONCE and o.status in LIVING]),
        ("Missions", wanted in ("vivants", "tous"),
         [o for o in p.objectives if o.kind == c.CONSTANT and o.status in LIVING]),
        ("Terminés", wanted in (c.DONE, "tous"), [o for o in p.objectives if o.status == c.DONE]),
        ("Retirés", wanted in (c.DROPPED, "tous"), [o for o in p.objectives if o.status == c.DROPPED]))
    return [{"title": title, "rows": [_row(sc, o, said, chosen, keep) for o in sorted(items, key=order)]}
            for title, seen, items in found if seen and items]


def _filters(sc: Scene, wanted: str) -> list[dict[str, Any]]:
    p = sc.p
    counts = {"vivants": sum(1 for o in p.objectives if o.status in LIVING),
              c.DONE: sum(1 for o in p.objectives if o.status == c.DONE),
              c.DROPPED: sum(1 for o in p.objectives if o.status == c.DROPPED), "tous": len(p.objectives)}
    return [{"text": label, "count": counts[code], "on": code == wanted,
             "href": sc.url("objectifs", objectifs="" if code == "vivants" else code)} for code, label in FILTERS]


def _verified(sc: Scene, m: Any, said: dict[str, str]) -> dict[str, Any]:
    """Comment un jalon se vérifie : par quoi, sa commande, l'élément de son registre et le statut attendu, ce
    qu'elle en dit."""
    command = shlex.join(milestones.decoded(said.get(m.command_ref))) if m.check == c.CHECK_COMMAND else ""
    item_href = ""
    if m.check == c.CHECK_ITEM and m.item_key:
        item_href = sc.url("tickets", element=m.item_key) if m.item_list == c.TICKETS else \
            sc.url("suivi", liste=m.item_list, element=m.item_key)
    return {"by": CHECK_WORDS.get(m.check, m.check), "command": command, "item": m.item_key if m.check == c.CHECK_ITEM
            else "", "item_href": item_href,
            "item_status": tracker.status_words(m.item_list, m.item_status) if m.item_status else "",
            "how": said.get(m.how_ref, "") if m.how_ref and (m.status == c.REACHED or m.ready_at) else ""}


def milestone(sc: Scene, o: Any, m: Any, said: dict[str, str], back: str, *, gestures: bool = True) -> dict[str, Any]:
    """Un jalon : son texte, son état, quand, comment on le vérifie, sa preuve, la raison d'un refus ou d'un
    retrait, et ses gestes — valider ou refuser un point d'arrêt dit prêt, le modifier, le retirer tant qu'il est
    ouvert."""
    state = glance.milestone_state(o, m)
    tone = MARK_TONES[state] if state != glance.M_DROPPED else WAIT
    ready = state == glance.M_READY
    words = {glance.M_READY: "prêt · à valider", glance.M_STARTED: "en cours", glance.M_REFUSED: "refusé"}
    target = {"objective": str(o.id), "milestone": str(m.id)}
    live = gestures and m.status == c.OPEN
    return {
        "id": m.id, "text": said.get(m.text_ref, FORGOTTEN), "tone": tone, "icon": MARK_ICONS.get(tone, "minus"),
        "dropped": m.status == c.DROPPED, "state": words.get(state, STATE_FR.get(m.status, m.status)),
        "at": sc.ago(m.reached_at or m.ready_at or m.refused_at), "verified": _verified(sc, m, said),
        "refused": said.get(m.reason_ref, "") if m.refused_at and m.status == c.OPEN else "",
        "why": said.get(m.reason_ref, "") if m.reason_ref and (m.status == c.DROPPED or m.revised) else "",
        "proof": said.get(m.proof_ref, "") if m.proof_ref else "", "commit": m.commit[:7], "ready": ready,
        "validate": shown(sc.form("jalon_trancher", back, **target), verdict="validate") if ready and gestures
        else None,
        "refuse": shown(sc.form("jalon_trancher", back, **target), "reason", verdict="refuse") if ready and gestures
        else None,
        "edit_href": sc.url("objectifs", "obj-jalon-modifier", objectif=o.id, jalon=m.id) if live else "",
        "drop": shown(sc.form("jalon_retirer", back, **target), "reason") if live else None}


def _milestone_edit(sc: Scene, o: Any, m: Any, said: dict[str, str], back: str) -> dict[str, Any] | None:
    """« Modifier le jalon » : son texte et comment on le vérifie, tels qu'ils sont."""
    form = sc.form("jalon_modifier", back, objective=str(o.id), milestone=str(m.id), text=said.get(m.text_ref, ""),
                   check=m.check, command=shlex.join(milestones.decoded(said.get(m.command_ref))),
                   item_list=m.item_list, item=m.item_key, item_status=m.item_status)
    if form is None:
        return None
    fields = [{**f, "kind": "select", "choices": list(CHECK_CHOICES)} if f["path"] == "check" else f
              for f in form["fields"]]
    return conditional({**form, "fields": fields}, CHECK_ONLY)


def reports(sc: Scene, o: Any) -> list[dict[str, Any]]:
    """Ses derniers comptes rendus, du plus récent au plus ancien, relus dans le journal : quand, le verdict, ses
    mots, le commit laissé."""
    mind = sc.ui.kernel.mind
    found = [e for e in (mind.decode(x) for x in mind.store.latest([c.RUN_REPORTED.name], REPORTS_READ,
                                                                    where=("project", sc.p.id)))
             if e.data.objective == o.id][:REPORTS_SHOWN]
    said = sc.texts([e.data.summary.ref for e in found if e.data.summary.ref])  # un texte oublié manque
    return [{"when": sc.when(e.at), "ago": sc.ago(e.at), "verdict": VERDICT_FR.get(e.data.verdict, e.data.verdict),
             "tone": VERDICT_TONES.get(e.data.verdict, WORK), "commit": e.data.commit[:7],
             "text": e.data.summary.text if e.data.summary.text is not None else
             said.get(e.data.summary.ref or "", FORGOTTEN),
             # un compte rendu mène à son exécution (Activité › Exécutions), pas au fil
             "href": sc.url("executions", vue="executions", execution=e.correlation)} for e in found]


def _moves(sc: Scene, o: Any, back: str) -> list[dict[str, Any]]:
    """Ce qui se gère : chaque changement de statut permis, en un bouton (``projects.objectif_statut``)."""
    out = []
    for status, once, mission in MOVES:
        label = mission if o.kind == c.CONSTANT else once
        if status == o.status or not label:
            continue
        form = shown(sc.form("objectif_statut", back, objective=str(o.id), status=status))
        if form is not None:
            out.append({"form": form, "label": label, "danger": status == c.DROPPED})
    return out


def _tickets(sc: Scene, o: Any, said: dict[str, str]) -> list[dict[str, Any]]:
    """Les tickets liés à un objectif, parmi ceux que l'état garde : celui dont il est né, ceux qu'il tient."""
    found = objective_tickets(sc.p, o)
    return [{"n": x.number, "title": said.get(x.title_ref, FORGOTTEN),
             "state": tracker.status_words(c.TICKETS, x.status), "tone": DONE if x.closed == c.DONE else
             WAIT if x.closed else WORK,
             "href": sc.url("tickets", element=f"#{x.number}")} for x in found]


def side(sc: Scene, o: Any, said: dict[str, str], back: str) -> dict[str, Any]:
    """Le panneau d'un objectif ou d'une mission (le diagramme le reprend) : ce qui le dit fini, où il en est, sa
    branche et sa pull request avec leur statut, ses tickets liés — ou le rythme d'une mission — et ce qui se gère."""
    p = sc.p
    alive = milestones_of(o)
    mission = o.kind == c.CONSTANT
    tone = (WORK if o.status == c.OPEN else WAIT) if mission else OBJECTIVE_TONES.get(o.status, WAIT)
    return {
        "mission": mission, "tone": tone, "state": OBJ_FR.get(o.status, o.status),
        "done_when": said.get(o.done_when_ref, "") if o.done_when_ref else "", "marks": marks(o) or [tone],
        "count": f"{sum(1 for m in alive if m.status == c.REACHED)} / {plural(len(alive), 'jalon', 'jalons')}"
        if alive else "pas de jalon",
        "runs": o.passes if mission else o.runs, "last": sc.when(o.last_run_at),
        "result": said.get(o.result_ref, "") if o.result_ref else "",
        "note": said.get(o.note_ref, "") if o.note_ref else "",
        "cadence": ("aucune : sur événement seulement" if o.only_on_event else glance.cadence_words(o)) if mission
        else "", "on": [trigger_words(k) for k in o.on],
        "branch": o.branch, "base": p.branch if o.branch else "",
        "pull": pull_card(p, o, sc.now, pull_href(sc.key, o)) if by_pulls(p) or o.pull_state else None,
        "tickets": [] if mission else _tickets(sc, o, said), "moves": _moves(sc, o, back)}


def refs(sc: Scene, o: Any) -> list[str]:
    """Les textes qu'un objectif choisi montre : les siens, ceux de ses jalons, de ses tickets liés."""
    out = [o.text_ref, o.done_when_ref, o.need_ref, o.note_ref, o.result_ref, o.routine_ref, o.pull_said_ref,
           o.checks_said_ref, o.review_ref, *o.review_refused[-1:]]
    for m in o.milestones:
        out += [m.text_ref, m.how_ref, m.proof_ref, m.reason_ref, m.command_ref]
    out += [x.title_ref for x in sc.p.board.items if x.list_name == c.TICKETS
            and (x.objective == o.id or x.number == o.ticket)]
    return out


def _detail(sc: Scene, o: Any, said: dict[str, str], back: str) -> dict[str, Any]:
    """Un objectif ou une mission, dans les trois zones."""
    mission = o.kind == c.CONSTANT
    alive = milestones_of(o)
    told = reports(sc, o)
    # après un formulaire du contenu, on revient à ce qu'il a changé : ses jalons (ses passages, pour une mission)
    seen = back + ("#obj-passages" if mission else "#obj-jalons")
    edit = sc.form("objectif_modifier", seen, objective=str(o.id), text=said.get(o.text_ref, ""), kind=o.kind,
                   cadence_hours=str(o.cadence_us // HOUR), on=o.on, only_on_event="on" if o.only_on_event else "",
                   routine=said.get(o.routine_ref, ""), at_once="on" if o.at_once else "",
                   done_when=said.get(o.done_when_ref, ""))
    fields = ("text", "cadence_hours", "on", "only_on_event", "routine", "at_once") if mission else \
        ("text", "done_when")
    asked = sc.query.get("jalon") or ""
    editing = next((m for m in alive if str(m.id) == asked and m.status == c.OPEN), None) if asked else None
    out: dict[str, Any] = {
        "sort": "mission" if mission else "goal", "n": o.id, "title": said.get(o.text_ref, FORGOTTEN),
        "over": "Mission" if mission else f"Objectif n° {o.id}", "icon": "refresh" if mission else "target",
        "facts": [plural(o.passes if mission else o.runs, "passage", "passages"),
                  *((f"le dernier {sc.ago(o.last_run_at)}",) if o.last_run_at else ())],
        "launch": shown(sc.form("lancer_objectif", back, objective=str(o.id))) if o.status == c.OPEN else None,
        "edit": shown(edit, *fields, kind=o.kind), "need": said.get(o.need_ref, "") if o.need_ref else "",
        "reports": told, "side": side(sc, o, said, back)}
    if mission:
        out["each_pass"] = said.get(o.routine_ref, "") if o.routine_ref else ""
        return out
    review = None
    if o.review_at:
        review = {"ok": o.review_ok, "label": REVIEW_WORDS[o.review_ok], "when": sc.when(o.review_at),
                  "text": said.get(o.review_ref, ""), "refused": len(o.review_refused),
                  "last_refusal": said.get(o.review_refused[-1], "") if o.review_refused else ""}
    can_add = o.status in LIVING and len(alive) < c.MILESTONES_MAX
    out.update({
        "milestones": [milestone(sc, o, m, said, seen) for m in alive],
        "dropped": [milestone(sc, o, m, said, back, gestures=False) for m in o.milestones if m.status == c.DROPPED],
        "reached": sum(1 for m in alive if m.status == c.REACHED), "total": len(alive),
        "add": conditional(sc.form("jalon_ajouter", seen, objective=str(o.id)), CHECK_ONLY) if can_add else None,
        "editing": {"n": editing.id, "form": _milestone_edit(sc, o, editing, said, seen)} if editing else None,
        "outside": [{"from": title, "text": said[ref]} for title, ref in
                    (("la fin du journal de la CI", o.checks_said_ref), ("le dernier mot de l'hôte", o.pull_said_ref))
                    if ref and said.get(ref)],
        "review": review})
    return out


def _plan(sc: Scene, said: dict[str, str], back: str) -> dict[str, Any] | None:
    """Son plan, quand il n'attend rien : où il en est, la demande et le plan en mots, et de quoi lui en faire écrire
    un autre. Quand il attend sa réponse, il est en carte sur la Vue d'ensemble."""
    p = sc.p
    if p.plan_state == c.UNPLANNED and not p.request_ref and p.status != c.ACTIVE:
        return None
    label, tone = PLAN_FR.get(p.plan_state, ("sans plan", "muted"))
    return {"state": label, "tone": YOU if tone == "warn" else DONE if tone == "ok" else WAIT,
            "waits": p.plan_state == c.PROPOSED, "version": p.plan_version,
            "texts": [{"title": title, "text": said[ref]} for title, ref in
                      (("La demande, ses mots tels quels", p.request_ref), ("Son plan", p.plan_ref)) if said.get(ref)],
            "revise": sc.form("plan_reviser", back) if p.plan_state != c.TO_FRAME and p.plan_state != c.PROPOSED
            else None, "button": "Demander une révision" if p.plan_state else "Lui faire écrire un plan",
            "href": sc.url("objectifs", plan=1), "overview": sc.url("apercu")}


def goals(sc: Scene) -> Markup | None:
    """L'onglet Objectifs en liste : la liste serrée et, à côté, l'objectif choisi (le premier sinon), le formulaire
    « Ajouter un objectif », ou son plan."""
    p = sc.p
    if p is None:
        return None
    wanted = _wanted(sc)
    asked = objective_at(p, sc.query.get("objectif"))
    adding, planning = bool(sc.query.get("ajouter")), bool(sc.query.get("plan"))
    said = sc.texts([o.text_ref for o in p.objectives] + [p.plan_ref, p.request_ref])
    groups = _groups(sc, wanted, asked.id if asked else 0, said)
    first = next((r["id"] for g in groups for r in g["rows"]), 0)
    o = asked or (objective_at(p, first) if not (adding or planning) else None)
    if o is not None and asked is None:
        for g in groups:
            for r in g["rows"]:
                r["on"] = r["id"] == o.id
    home = sc.url("objectifs", objectifs="" if wanted == "vivants" else wanted)
    back = sc.url("objectifs", objectif=o.id, objectifs="" if wanted == "vivants" else wanted) if o else home
    detail = None
    if o is not None and not (adding or planning):
        detail = _detail(sc, o, {**said, **sc.texts(refs(sc, o))}, back)
    add = conditional(sc.form("objectif_ajouter", home), GOAL_ONLY)
    plan = _plan(sc, said, sc.url("objectifs", plan=1))
    return Markup(env.get_template("handmade/projets/objectifs.html").render(
        key=sc.key, groups=groups, filters=_filters(sc, wanted), total=len(p.objectives), detail=detail,
        adding=add if adding else None, can_add=add is not None, planning=plan if planning else None, plan=plan,
        lire=asked is not None or adding or planning, home=home,
        links={"liste": home, "diagramme": sc.url("objectifs", vue="diagramme"),
               "ajouter": sc.url("objectifs", ajouter=1, objectifs="" if wanted == "vivants" else wanted)}))
