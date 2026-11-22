"""Gérer un projet depuis l'espace d'une personne (ADR 0290) : ce que l'écran Projets montre s'y modifie — le projet
(le confier, le modifier, l'archiver, le restaurer), ses objectifs, ses jalons, un ticket, une pull request (son
titre, son texte, un commentaire), ses décisions techniques.

**Aucune règle n'est d'ici.** Chaque geste passe par l'action que la console déclare pour lui (``Call.act`` : au nom
de la personne, journalisée, dédoublonnée, auditée ``moi.projects.<action>``), après une garde du moteur :

- **le cadre** — le modifier, ses outils, son dépôt, l'archiver, le restaurer : qui le pilote en modification **et**
  en est le propriétaire, ou s'occupe d'elle (``managing.frames``, la règle de qui tranche). Le confier : qui s'occupe
  d'elle, comme ``create_project`` en conversation. **Ce qui ouvre autre chose que le projet** — le courrier, la
  caméra, ses flux, la Forge, un service, l'accord de ce qui sort, le dépôt distant, la publication en issues — est
  réservé à qui s'occupe d'elle (ADR 0292) : la garde est dans les actions (``actions.reserved_field``), et chaque
  champ servi dit d'avance si la personne peut le changer (``can``, ``why``) ;
- **ses objectifs, ses jalons, ses tickets, ses décisions** : qui le pilote en modification ; un point d'arrêt et un
  jalon tenu ne se défont que par qui tranche (``managing.undoing``, ADR 0278) ;
- **écrire chez l'hôte sur une pull request** : qui tranche — le geste d'une personne, qui pose un fait ; l'effet part
  après le commit du journal (``faculties/projects/managing.py``) ;
- sur l'accord du propriétaire, rien de tout cela d'ici : la demande se fait dans le chat.

Les réglages d'un projet se servent en sections, tels que les actions de la console les décrivent (``kernel.forms`` :
le libellé, l'aide, les choix et la valeur actuelle de chaque champ) : l'écran n'écrit aucun mot. Le contrat, route par
route : ``docs/protocole-moi.md``, § 11.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from starlette.routing import Route

from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing
from mika.app.me.common import millis
from mika.app.me.projects import (
    NOT_FRAMER,
    PATH,
    TEXT_SHOWN,
    Reach,
    Scene,
    _found,
    _name,
    _nameable,
    _opened,
    _steers,
    _subject,
    _texts,
    edit_refusal,
    frame_refusal,
    reach,
    scene,
)
from mika.contracts import projects as c
from mika.faculties.projects import managing, milestones, tracker
from mika.faculties.projects.actions import (
    KEEPER_FIELD,
    KEEPER_ONLY,
    SERVICE_KNOB,
    TOOLS_ACTION,
    reserved_field,
    schedule_words,
)
from mika.faculties.projects.faculty import (
    Decision,
    Objective,
    Project,
    decision_at,
    milestone_at,
    objective_at,
)
from mika.faculties.projects.inspect import AUTHOR_FR, window_words
from mika.faculties.projects.inspect_manage import HELD_WORDS, NOT_KEEPER, NOT_WRITABLE, NOT_WRITER
from mika.kernel.clock import HOUR
from mika.kernel.forms import describe
from mika.runtime.operations import dynamic_fields, initial_values

# ── Les refus, en mots ────────────────────────────────────────────────────

NOTHING = "Rien n'a changé."
NO_SUCH_SECTION = "« section » : general, rythme, accords, depot ou outils."
DECISION_WORDS = {c.IN_FORCE: "en vigueur", c.WITHDRAWN: "retirée", c.SUPERSEDED: "remplacée"}
#: ce qu'on fait du statut d'un objectif ici : le rouvrir, le dire terminé, le retirer
OBJECTIVE_MOVES = {c.OPEN: "Rouvrir", c.DONE: "Dire terminé", c.DROPPED: "Retirer"}


# ── Qui ───────────────────────────────────────────────────────────────────


def _frames(r: Reach) -> None:
    _steers(r, edit=True)
    if not r.reader.settles:
        raise Denied(403, NOT_FRAMER)


# ── Un formulaire, tel que la console le décrit ───────────────────────────


def _spec(call: Call, key: str) -> Any:
    return call.kernel.registry.actions[key]


def _fields(call: Call, key: str, subject: str = "") -> tuple[list[Any], dict[str, Any]]:
    """Les champs d'une action (ceux qu'on remplit) et leurs valeurs de départ, lues dans l'état."""
    spec = _spec(call, key)
    fields = dynamic_fields(call.kernel, spec, subject, {}) if spec.fields is not None else describe(spec.args)
    return [f for f in fields if f.kind not in ("hidden", "group")], initial_values(call.kernel, spec, subject) \
        if subject else {}


def _field_json(f: Any, value: Any) -> dict[str, Any]:
    return {"name": f.path, "label": f.label, "help": f.help, "kind": f.kind, "required": bool(f.required),
            "choices": [{"code": code, "label": label} for code, label in f.choices],
            "value": value if value is not None else f.default, "min": f.lo, "max": f.hi,
            "only": [{"field": name, "values": list(values)} for name, values in f.only]}


#: les réglages d'un projet, en sections (celles de l'écran) : son nom, son titre, et les actions qui la règlent, avec
#: les champs que chacune y porte (``None`` : tous)
SECTIONS: tuple[tuple[str, str, tuple[tuple[str, tuple[str, ...] | None], ...]], ...] = (
    ("general", "Général", (("projects.modifier", ("title", "description", "mode")),)),
    ("rythme", "Rythme", (("projects.modifier", ("schedule", "schedule_rule", "days", "start", "end", "runs_per_day",
                                               "priority")),)),
    ("accords", "Accords et relecture", (("projects.modifier", ("approval", "reread")),
                                         ("projects.tickets_regler", None))),
    ("depot", "Dépôt", (("projects.depot_distant", None),)),
    ("outils", "Outils et services", (("projects.outils", None),)),
)


def _summary(p: Project, name: str, fields: list[dict[str, Any]]) -> str:
    """Une section en une ligne, pour la liste de gauche."""
    by_name = {f["name"]: f for f in fields}

    def chosen(field: str) -> str:
        f = by_name.get(field) or {}
        return next((x["label"] for x in f.get("choices", ()) if x["code"] == f.get("value")), "")

    if name == "general":
        return chosen("mode")
    if name == "rythme":
        return f"{schedule_words(p.schedule)} · {window_words(p)}"
    if name == "accords":
        out = "ce qui sort attend ton accord" if p.approval else "ce qui sort part sans accord"
        return f"{out} · relecture : {chosen('reread')}"
    if name == "depot":
        return "par pull request" if p.remote and p.flow == c.FLOW_PR else "direct" if p.remote else \
            "pas de dépôt distant"
    ticked = sum(1 for f in fields if f["value"] is True)
    return f"{ticked} en main, en plus de son atelier"


def _sections(call: Call, sc: Scene, r: Reach) -> list[dict[str, Any]]:
    """Ses réglages, section par section. Chaque champ dit si la personne peut le changer (``can``) et sinon pourquoi
    (``why``) : la garde de l'enregistrement, dite d'avance — elle ne change pas son cadre, ou ce champ est réservé à
    qui s'occupe d'elle (ADR 0292). Les services branchés sur l'instance ne se servent qu'à qui peut les cocher : les
    autres voient ceux que le projet a, pas le catalogue."""
    p, out = r.p, []
    no_frame = frame_refusal(r)
    for name, title, parts in SECTIONS:
        fields: list[dict[str, Any]] = []
        for key, names in parts:
            found, initial = _fields(call, key, _subject(r))
            for f in found:
                if names is not None and f.path not in names:
                    continue
                value = initial.get(f.path)
                why = no_frame or (KEEPER_ONLY if reserved_field(key, f.path) and not sc.keeper else "")
                if why and key == TOOLS_ACTION and f.path.startswith(SERVICE_KNOB) and value is not True:
                    continue
                fields.append({**_field_json(f, value), "can": not why, "why": why})
        if name == "depot" and not r.own:  # l'adresse du dépôt distant ne se dit qu'à qui le projet est
            fields = [f for f in fields if f["name"] != "remote"]
        can = any(f["can"] for f in fields)
        out.append({"name": name, "title": title, "summary": _summary(p, name, fields), "can": can,
                    "why": "" if can else no_frame or KEEPER_ONLY, "fields": fields})
    return out


async def settings(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/reglages`` : ses réglages en sections — pour chaque champ son libellé, son aide, ses choix
    et sa valeur actuelle —, et si elle peut les changer."""
    sc, r = _opened(call)
    why = frame_refusal(r)
    hers = r.p.authority == c.SELF
    return {"project": r.p.id, "can": not why, "why": why, "sections": _sections(call, sc, r),
            # un projet qu'elle a ouvert d'elle-même se pilote, il ne se renomme pas
            "renamable": not hers, "archive": {"can": not why, "why": why}}


def _sent(call: Call) -> dict[str, Any]:
    values = call.data.get("values")
    if not isinstance(values, dict) or not values or len(values) > 40 or \
            not all(isinstance(k, str) and isinstance(v, str | bool | int | list) or v is None
                    for k, v in values.items()):
        raise Denied(400, "« values » : les champs qui changent, par leur nom.", {"values": "valeur requise"})
    return values


async def set_settings(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/reglages/enregistrer`` : une section de ses réglages (``section``), les champs qui changent
    (``values``). Le reste garde sa valeur : l'action de la console reçoit tout le formulaire, celui de maintenant."""
    sc, r = _opened(call)
    _frames(r)
    name = call.arg("section", limit=20)
    parts = next((parts for known, _, parts in SECTIONS if known == name), None)
    if parts is None:
        raise Denied(400, NO_SUCH_SECTION, {"section": "section inconnue"})
    sent = _sent(call)
    plans: list[tuple[str, dict[str, Any]]] = []
    known: set[str] = set()
    for key, names in parts:
        found, initial = _fields(call, key, _subject(r))
        kinds = {f.path: f.kind for f in found if names is None or f.path in names}
        known |= set(kinds)
        mine = {k: v for k, v in sent.items() if k in kinds}
        wrong = [k for k, v in mine.items() if (kinds[k] == "bool") != isinstance(v, bool)]
        if wrong:
            raise Denied(400, "Un champ n'a pas la bonne forme.", {k: "vrai ou faux" if kinds[k] == "bool" else
                                                                   "une valeur, pas vrai ou faux" for k in wrong})
        whole = {f.path: initial.get(f.path, f.default) for f in found}
        # ce qui ouvre autre chose que le projet est réservé à qui s'occupe d'elle (ADR 0292) : le refus de l'action,
        # dit ici champ par champ
        held = [k for k, v in mine.items() if whole.get(k) != v and reserved_field(key, k)]
        if held and not sc.keeper:
            raise Denied(403, KEEPER_ONLY, {k: KEEPER_FIELD for k in held})
        if any(whole.get(k) != v for k, v in mine.items()):
            plans.append((key, {**whole, **{k: v for k, v in initial.items() if k not in whole}, **mine}))
    unknown = [k for k in sent if k not in known]
    if unknown:
        raise Denied(400, "Ce champ n'est pas de cette section.", {k: "champ inconnu" for k in unknown})
    if not plans:
        raise Denied(409, NOTHING)
    got: dict[str, Any] = {}
    for key, values in plans:  # une clé d'envoi par action : la seconde n'est pas une redite de la première
        got = done(await call.act(key, form(**values), subject=_subject(r), part=key))
    return got


# ── Le projet : le confier, l'archiver, le restaurer ──────────────────────


async def new_project(call: Call) -> dict[str, Any]:
    """``GET …/projets/nouveau`` : ce qu'il faut pour confier un projet — ses champs, leurs choix —, et si elle le
    peut."""
    sc = scene(call)
    found, _ = _fields(call, "projects.projet_confier")
    return {"can": sc.keeper, "why": "" if sc.keeper else NOT_KEEPER, "fields": [_field_json(f, None) for f in found]}


async def entrust(call: Call) -> dict[str, Any]:
    """``POST …/projets/nouveau/creer`` : lui confier un projet — il naît à cadrer, pour qui le demande."""
    sc = scene(call)
    if not sc.keeper:
        raise Denied(403, NOT_KEEPER)
    got = await call.act("projects.projet_confier", form(
        title=call.arg("title", limit=200), request=call.arg("request", limit=2000),
        mode=call.arg("mode", c.PERSONA, limit=20), schedule=call.arg("schedule", "manual", limit=120),
        schedule_rule=call.arg("schedule_rule", limit=120)))
    return {**done(got), "project": got.seqs[0] if got.seqs else 0}


def _restorable(sc: Scene, p: Project | None) -> Reach | None:
    """Ce qu'elle aurait de ce projet archivé une fois restauré (il revient en pause), si elle peut le restaurer ;
    sinon rien. **Les mêmes règles que le reste** (ADR 0292) : sa portée (``reach`` — ses lignes d'accès, le canal de
    son client, le niveau qu'elle entend), puis la garde de son cadre. Un propriétaire que ses lignes laissent en
    lecture seule ne le restaure pas."""
    if p is None or p.status != c.ARCHIVED:
        return None
    r = reach(sc, replace(p, status=c.PAUSED))
    return r if r.see and r.detail and not frame_refusal(r) else None


async def archived(call: Call) -> dict[str, Any]:
    """``GET …/projets/archives`` : les projets archivés qu'elle peut restaurer — les siens, et tous pour qui
    s'occupe d'elle —, sous sa portée. Le nom de son propriétaire ne se dit que si elle a le droit de le savoir."""
    sc = scene(call)
    found = sorted((r for r in (_restorable(sc, p) for p in sc.s.projects.values()) if r is not None),
                   key=lambda r: -r.p.archived_at)
    texts = _texts(call, [r.p.title_ref for r in found])

    def owner_name(r: Reach) -> str:
        owner = r.p.owner or ""
        return _name(sc, owner) if owner and not r.own and _nameable(sc, owner, r.p.sensitivity) else ""

    return {"items": [{"id": r.p.id, "title": texts.get(r.p.title_ref, ""), "archived_at": millis(r.p.archived_at),
                       "owner_name": owner_name(r)} for r in found]}


async def archive(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/archiver`` : il ne travaille plus ; rien n'est effacé."""
    sc, r = _opened(call)
    _frames(r)
    return done(await call.act("projects.archiver", form(), subject=_subject(r)))


async def restore(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/restaurer`` : un projet archivé revient, en pause."""
    sc = scene(call)
    p = sc.s.projects.get(int(call.request.path_params["project"]))
    if p is None or _restorable(sc, p) is None:
        raise missing()
    return done(await call.act("projects.restaurer", form(), subject=str(p.id)))


# ── Ses objectifs ─────────────────────────────────────────────────────────

OBJECTIVE_FIELDS = ("text", "kind", "cadence_hours", "on", "only_on_event", "each_pass", "at_once", "done_when")


def _edits(r: Reach) -> None:
    _steers(r, edit=True)


def _objective(call: Call, r: Reach) -> Objective:
    o = objective_at(r.p, call.number("objective", 0, 0))
    if o is None or o.status == c.DROPPED and call.request.url.path.rsplit("/", 1)[-1] != "statut":
        raise missing()
    return o


def _objective_values(call: Call, known: Mapping[str, Any]) -> dict[str, Any]:
    """Les champs d'un objectif tels que l'envoi les dit, sur ce qu'il est déjà (``known``)."""
    data = call.data
    out = dict(known)
    for name, limit in (("text", 500), ("kind", 12), ("done_when", 1500)):
        if name in data:
            out[name] = call.arg(name, limit=limit)
    if "cadence_hours" in data:
        out["cadence_hours"] = call.number("cadence_hours", 0, 0, 720)
    if "on" in data:
        out["on"] = call.strings("on", limit=8, size=120)
    for name in ("only_on_event", "at_once"):
        if name in data:
            out[name] = call.flag(name)
    if "each_pass" in data:  # ce que chaque passage doit faire : une ligne par chose
        out["routine"] = call.arg("each_pass", limit=1200)
    return out


async def add_objective(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/objectif`` : un objectif ponctuel, ou une mission (``kind: constant``)."""
    sc, r = _opened(call)
    _edits(r)
    values = _objective_values(call, {"text": "", "kind": c.ONCE})
    before = r.p.objective_seq
    got = done(await call.act("projects.objectif_ajouter", form(**values), subject=_subject(r)))
    return {**got, "objective": before + 1}


async def edit_objective(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/objectif/modifier`` : ce qui change d'un objectif ; le reste garde sa valeur."""
    sc, r = _opened(call)
    _edits(r)
    o = _objective(call, r)
    texts = _texts(call, [o.text_ref, o.routine_ref])
    known = {"text": texts.get(o.text_ref, ""), "kind": o.kind, "cadence_hours": o.cadence_us // HOUR,
             "on": list(o.on), "only_on_event": o.only_on_event, "routine": texts.get(o.routine_ref, ""),
             "at_once": o.at_once}
    return done(await call.act("projects.objectif_modifier", form(
        fixed={"objective": str(o.id)}, **_objective_values(call, known)), subject=_subject(r)))


async def move_objective(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/objectif/statut`` : le rouvrir (``open``), le dire terminé (``done``), le retirer
    (``dropped``)."""
    sc, r = _opened(call)
    _edits(r)
    o = _objective(call, r)
    status = call.arg("status", limit=12)
    if status not in OBJECTIVE_MOVES:
        raise Denied(400, "« status » : open, done ou dropped.", {"status": ", ".join(OBJECTIVE_MOVES)})
    return done(await call.act("projects.objectif_statut", form(
        fixed={"objective": str(o.id), "status": status}), subject=_subject(r)))


# ── Ses jalons ────────────────────────────────────────────────────────────

MILESTONE_FIELDS = ("text", "check", "command", "item_list", "item", "item_status")


def _milestone_values(call: Call, known: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(known)
    for name, limit in (("text", milestones.TEXT_MAX), ("check", 12), ("command", 2000), ("item_list", 40),
                        ("item", 61), ("item_status", 24)):
        if name in call.data:
            out[name] = call.arg(name, limit=limit)
    return out


async def add_milestone(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/jalon/ajouter`` : un jalon de plus sur un objectif ponctuel."""
    sc, r = _opened(call)
    _edits(r)
    o = _objective(call, r)
    return done(await call.act("projects.jalon_ajouter", form(
        fixed={"objective": str(o.id)}, **_milestone_values(call, {"text": "", "check": c.CHECK_PROSE})),
        subject=_subject(r)))


def _milestone(call: Call, r: Reach) -> tuple[Objective, Any]:
    """Le jalon que nomme l'envoi, s'il peut encore être défait par elle : atteint ou retiré, il ne bouge plus
    (409) ; tenu — un point d'arrêt, un jalon du propriétaire —, il reste à qui tranche (403)."""
    o = _objective(call, r)
    m = milestone_at(o, call.number("milestone", 0, 0))
    if m is None:
        raise missing()
    held = managing.undoing(m, r.reader.settles)
    if held:
        raise Denied(409 if held == managing.SETTLED else 403, HELD_WORDS.get(held, HELD_WORDS["other"]))
    return o, m


async def edit_milestone(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/jalon/modifier`` : le texte d'un jalon ouvert, et comment on le vérifie."""
    sc, r = _opened(call)
    _edits(r)
    o, m = _milestone(call, r)
    texts = _texts(call, [m.text_ref, m.command_ref])
    known = {"text": texts.get(m.text_ref, ""), "check": m.check,
             "command": shlex.join(milestones.decoded(texts.get(m.command_ref))), "item_list": m.item_list,
             "item": m.item_key, "item_status": m.item_status}
    return done(await call.act("projects.jalon_modifier", form(
        fixed={"objective": str(o.id), "milestone": str(m.id)}, **_milestone_values(call, known),
        reason=call.arg("reason", limit=milestones.REASON_MAX)), subject=_subject(r)))


async def drop_milestone(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/jalon/retirer`` : un jalon ouvert n'a plus lieu d'être."""
    sc, r = _opened(call)
    _edits(r)
    o, m = _milestone(call, r)
    return done(await call.act("projects.jalon_retirer", form(
        fixed={"objective": str(o.id), "milestone": str(m.id)},
        reason=call.arg("reason", limit=milestones.REASON_MAX)), subject=_subject(r)))


# ── Un ticket ─────────────────────────────────────────────────────────────


async def edit_ticket(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/ticket/modifier`` : son titre, son détail, sa sorte, sa priorité — ce qui change."""
    sc, r = _opened(call)
    _edits(r)
    call.data.setdefault("list", c.TICKETS)
    lst, e = _found(sc, r)
    if lst.name != c.TICKETS:
        raise Denied(400, "Seul un ticket se modifie ainsi.", {"list": "tickets"})
    item = e.item
    data = call.data
    return done(await call.act("projects.ticket_modifier", form(
        fixed={"item": tracker.handle(item)},
        title=call.arg("title", limit=tracker.TITLE_MAX) if "title" in data else e.title,
        text=call.arg("text", limit=tracker.TEXT_MAX) if "text" in data else e.body,
        kind=call.arg("kind", limit=20) if "kind" in data else item.kind,
        priority=call.arg("priority", limit=20) if "priority" in data else item.priority), subject=_subject(r)))


# ── Une pull request : son titre, son texte, un commentaire ───────────────


def pull_write_refusal(r: Reach, o: Objective | None) -> str:
    """Pourquoi elle n'écrit pas chez l'hôte sur la pull request de cet objectif (vide : elle le peut)."""
    if why := edit_refusal(r):
        return why
    if not r.reader.settles:
        return NOT_WRITER
    return "" if managing.writable(r.p, o) else NOT_WRITABLE


def _pull(call: Call, r: Reach) -> Objective:
    _steers(r, edit=True)
    if not r.reader.settles:
        raise Denied(403, NOT_WRITER)
    number = call.number("number", 0, 0)
    o = next((x for x in r.p.objectives if number and x.pull == number), None)
    if o is None:
        raise missing()
    if not managing.writable(r.p, o):
        raise Denied(409, NOT_WRITABLE)
    return o


async def edit_pull(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/code/pull/modifier`` : le titre et le texte d'une pull request, chez l'hôte."""
    sc, r = _opened(call)
    o = _pull(call, r)
    got = done(await call.act("projects.pull_modifier", form(
        fixed={"objective": str(o.id)}, title=call.arg("title", limit=managing.TITLE_MAX),
        body=call.arg("body", limit=managing.BODY_MAX)), subject=_subject(r)))
    return {**got, "asked": True, "number": o.pull}


async def comment_pull(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/code/pull/commenter`` : un commentaire sur une pull request, signé de son nom."""
    sc, r = _opened(call)
    o = _pull(call, r)
    got = done(await call.act("projects.pull_commenter", form(
        fixed={"objective": str(o.id)}, text=call.arg("text", limit=managing.COMMENT_MAX)), subject=_subject(r)))
    return {**got, "asked": True, "number": o.pull}


# ── Ses décisions techniques ──────────────────────────────────────────────

DECISION_TEXTS = (("title", 200), ("choice", 1500), ("reason", 1500), ("context", 2000), ("options", 2000))


def _decision_refs(d: Decision) -> dict[str, str]:
    return {"title": d.title_ref, "choice": d.choice_ref, "context": d.context_ref, "options": d.options_ref,
            "reason": d.reason_ref}


def _decision_json(sc: Scene, r: Reach, d: Decision, texts: Mapping[str, str], *, full: bool = False
                   ) -> dict[str, Any]:
    refs = _decision_refs(d)
    why = edit_refusal(r)
    can = not why
    out = {"number": d.id, "title": texts.get(refs["title"], ""), "choice": texts.get(refs["choice"], "")[:TEXT_SHOWN],
           "status": d.status, "status_label": DECISION_WORDS.get(d.status, d.status),
           "author_kind": "self" if d.author == "self" else "person", "author": AUTHOR_FR.get(d.author, d.author),
           "at": millis(d.at), "replaces": d.replaces, "replaced_by": d.replaced_by, "objective": d.objective,
           "can": {"modify": can and d.status != c.SUPERSEDED, "replace": can and d.status == c.IN_FORCE,
                   "withdraw": can and d.status == c.IN_FORCE, "restore": can and d.status == c.WITHDRAWN,
                   "why": why}}
    if full:
        out.update({name: texts.get(refs[name], "")[:TEXT_SHOWN] for name in ("context", "options", "reason")})
    return out


async def decisions(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/decisions[?status=]`` : ses décisions techniques, les plus récentes d'abord (celles en
    vigueur sans ``status`` ; ``all`` : toutes)."""
    sc, r = _opened(call)
    wanted = call.arg("status", c.IN_FORCE, limit=20)
    if wanted not in (*DECISION_WORDS, "all"):
        raise Denied(400, "« status » : in_force, withdrawn, superseded ou all.", {"status": "statut inconnu"})
    found = [d for d in reversed(r.p.decisions) if wanted == "all" or d.status == wanted]
    texts = _texts(call, [ref for d in found for ref in (d.title_ref, d.choice_ref)])
    why = edit_refusal(r)
    return {"total": len(found), "in_force": sum(1 for d in r.p.decisions if d.status == c.IN_FORCE),
            "can": not why, "why": why, "items": [_decision_json(sc, r, d, texts) for d in found]}


def _decision(call: Call, r: Reach) -> Decision:
    d = decision_at(r.p, call.number("number", 0, 0))
    if d is None:
        raise missing()
    return d


async def decision(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/decision?number=`` : une décision — le choix, le contexte, les options écartées, la
    raison, ce qu'elle remplace."""
    sc, r = _opened(call)
    d = _decision(call, r)
    return _decision_json(sc, r, d, _texts(call, list(_decision_refs(d).values())), full=True)


async def add_decision(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/decision/ajouter`` : consigner une décision ; ``replaces`` : celle en vigueur qu'elle
    remplace."""
    sc, r = _opened(call)
    _edits(r)
    before = r.p.decision_seq
    got = done(await call.act("projects.decision_ajouter", form(
        **{name: call.arg(name, limit=limit) for name, limit in DECISION_TEXTS},
        replaces=call.number("replaces", 0, 0)), subject=_subject(r)))
    return {**got, "number": before + 1}


async def edit_decision(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/decision/modifier`` : les textes d'une décision qui n'est pas remplacée — ce qui
    change."""
    sc, r = _opened(call)
    _edits(r)
    d = _decision(call, r)
    refs = _decision_refs(d)
    texts = _texts(call, list(refs.values()))
    values = {name: call.arg(name, limit=limit) if name in call.data else texts.get(refs[name], "")
              for name, limit in DECISION_TEXTS}
    return done(await call.act("projects.decision_modifier", form(fixed={"decision": str(d.id)}, **values),
                               subject=_subject(r)))


async def move_decision(call: Call) -> dict[str, Any]:
    """``POST …/projets/<id>/decision/statut`` : la retirer (``withdrawn``), ou la remettre en vigueur
    (``in_force``)."""
    sc, r = _opened(call)
    _edits(r)
    d = _decision(call, r)
    status = call.arg("status", limit=12)
    if status not in (c.IN_FORCE, c.WITHDRAWN):
        raise Denied(400, "« status » : withdrawn ou in_force.", {"status": "withdrawn ou in_force"})
    return done(await call.act("projects.decision_statut", form(
        fixed={"decision": str(d.id), "status": status}), subject=_subject(r)))


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    one = PATH + "/{project:int}"
    return [r(PATH + "/nouveau", new_project), r(PATH + "/nouveau/creer", entrust, write=True),
            r(PATH + "/archives", archived),
            r(one + "/reglages", settings), r(one + "/reglages/enregistrer", set_settings, write=True),
            r(one + "/archiver", archive, write=True), r(one + "/restaurer", restore, write=True),
            r(one + "/objectif", add_objective, write=True), r(one + "/objectif/modifier", edit_objective, write=True),
            r(one + "/objectif/statut", move_objective, write=True),
            r(one + "/jalon/ajouter", add_milestone, write=True), r(one + "/jalon/modifier", edit_milestone, write=True),
            r(one + "/jalon/retirer", drop_milestone, write=True),
            r(one + "/ticket/modifier", edit_ticket, write=True),
            r(one + "/code/pull/modifier", edit_pull, write=True),
            r(one + "/code/pull/commenter", comment_pull, write=True),
            r(one + "/decisions", decisions), r(one + "/decision", decision),
            r(one + "/decision/ajouter", add_decision, write=True),
            r(one + "/decision/modifier", edit_decision, write=True),
            r(one + "/decision/statut", move_decision, write=True)]
