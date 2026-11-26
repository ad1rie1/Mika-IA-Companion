"""L'API par personne, gérer un projet (ADR 0290), à travers le vrai serveur : ce que l'écran Projets montre s'y
modifie.

Ce que ces tests gardent, geste par geste : **il réussit**, puis **il se refuse à qui n'a pas le droit** — qui ne fait
que voir le projet (403, son détail lui est fermé), qui le pilote sur accord (403 : la demande se fait dans le chat),
qui le pilote en modification sans en être le propriétaire (403 pour son cadre, et pour écrire chez l'hôte) ; qui ne le
voit pas a un 404. Et aussi : un point d'arrêt et un jalon atteint qui ne se défont pas ; ce qu'une personne écrit sur
une pull request part après le commit du journal, par le port de l'hôte, signé de son nom — et n'est jamais écrit par
elle ; les réglages se servent avec leurs libellés, leurs choix et leur valeur ; « Dépendances » dans les mots servis.

Et ce que la relecture adverse a fixé (ADR 0292) : **le propriétaire d'un projet qui ne s'occupe pas d'elle** change
son cadre, jamais ce qui ouvre autre chose que le projet — le courrier, la caméra, ses flux, la Forge, ses apps, un
service, l'accord de ce qui sort, le dépôt distant, la publication en issues : refusé par l'action elle-même, dit
champ par champ dans les réglages ; un projet qui n'est pour personne le reste ; restaurer passe par la portée.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from mika.app.domains.projects.api import manage, reach
from mika.app.me.api import form as api_form
from mika.contracts import projects as c
from mika.faculties.projects import actions, inspect_manage, managing
from mika.faculties.projects.faculty import ACCESS_SET, EXTRA_BUNDLES, MILESTONE_CHANGED, REFRAMED, Milestone
from mika.ports.workshop import Pull, Remark
from mika.runtime.operations import perform
from mika.vocab.access import PERSON
from tests.protocol.test_moi_mail import API, append, journal, login, post
from tests.protocol.test_moi_project_code import FakeHost, Repo
from tests.protocol.test_moi_projects import _chain, _get, _lea, _numbers, _project, _share, _ticket
from tests.protocol.test_web import csrf, world  # noqa: F401 — fixture partagée
from tests.unit.test_project_pulls import needs_bwrap

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"


def _post(client, pid: int, route: str, body: dict | None = None):
    return post(client, f"/projets/{pid}/{route}", body or {})


def _ok(client, pid: int, route: str, body: dict | None = None) -> dict:
    got = _post(client, pid, route, body)
    assert got.status_code == 200, (route, got.status_code, got.text)
    return got.json()


def _objective(client, pid: int, oid: int) -> dict:
    fiche = _get(client, f"/{pid}")
    return next(o for o in (*fiche["objectives"], *fiche["missions"]) if o["id"] == oid)


#: chaque geste de ce lot, avec de quoi l'envoyer : (route, corps) — ceux du cadre, puis les autres
FRAME = [("reglages/enregistrer", {"section": "rythme", "values": {"runs_per_day": 3}}),
         ("reglages/enregistrer", {"section": "outils", "values": {"tool_rss": True}}),
         ("archiver", {})]
EDITS = [("objectif", {"text": "Ajouter un mode sombre"}),
         ("objectif/modifier", {"objective": 1, "text": "Créer un module RDP, testé"}),
         ("objectif/statut", {"objective": 2, "status": "dropped"}),
         ("jalon/ajouter", {"objective": 1, "text": "Les tests passent", "check": "prose"}),
         ("ticket/modifier", {"item": "#1", "title": "Un titre retouché"}),
         ("decision/ajouter", {"title": "Le format du journal", "choice": "JSON Lines"})]


# ── Le projet ──


def test_the_keeper_entrusts_a_project_that_is_born_to_frame(world):  # noqa: F811
    client, live, _ = world
    _chain(client, live)
    form = _get(client, "/nouveau")
    assert form["can"] and form["why"] == ""
    names = {f["name"]: f for f in form["fields"]}
    assert {"title", "request", "mode", "schedule"} <= set(names)
    assert names["mode"]["choices"][0]["code"] == c.PERSONA and names["mode"]["choices"][0]["label"]
    assert _get(client, "")["create"] == {"can": True, "why": ""}
    made = post(client, "/projets/nouveau/creer", {"title": "Tableau de bord des scans",
                                                   "request": "Je veux voir les scans de la semaine d'un coup d'œil."})
    assert made.status_code == 200, made.text
    pid = made.json()["project"]
    p = _project(live, pid)
    assert p.plan_state == c.TO_FRAME and p.asked_by and p.owner == p.asked_by and p.request_ref
    fiche = _get(client, f"/{pid}")
    assert fiche["project"]["title"] == "Tableau de bord des scans" and fiche["project"]["plan"] == "to_frame"
    assert fiche["project"]["mine"] and fiche["rights"]["frame"] and fiche["rights"]["edit"]
    assert post(client, "/projets/nouveau/creer", {"title": ""}).status_code == 400
    # une personne qui ne s'occupe pas d'elle ne lui confie rien d'ici, et l'écran le sait d'avance
    _lea(client, live)
    login(client, "lea")
    assert _get(client, "/nouveau")["can"] is False and _get(client, "/nouveau")["why"] == inspect_manage.NOT_KEEPER
    refused = post(client, "/projets/nouveau/creer", {"title": "Le mien"})
    assert refused.status_code == 403 and refused.json()["error"] == inspect_manage.NOT_KEEPER


def test_its_settings_come_in_sections_with_their_words_and_are_changed_field_by_field(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    got = _get(client, f"/{pid}/reglages")
    assert got["can"] and got["why"] == "" and got["archive"]["can"]
    assert [(s["name"], s["title"]) for s in got["sections"]] == [
        ("general", "Général"), ("rythme", "Rythme"), ("accords", "Accords et relecture"), ("depot", "Dépôt"),
        ("outils", "Outils et services")]
    sections = {s["name"]: {f["name"]: f for f in s["fields"]} for s in got["sections"]}
    assert all(s["summary"] for s in got["sections"])
    # chaque champ : son libellé, ses choix avec leurs mots, sa valeur actuelle
    mode = sections["general"]["mode"]
    assert mode["label"] and mode["value"] == _project(live, pid).mode
    assert {x["code"] for x in mode["choices"]} == set(c.MODES) and all(x["label"] for x in mode["choices"])
    assert {"schedule", "days", "start", "end", "runs_per_day", "priority"} <= set(sections["rythme"])
    assert {"approval", "reread", "issues", "ticket_review"} <= set(sections["accords"])
    assert {"remote", "branch", "auto_push", "flow"} <= set(sections["depot"])
    assert sections["outils"]["tool_web"]["value"] is True and sections["outils"]["tool_rss"]["value"] is False
    # un champ change, le reste garde sa valeur
    before = _project(live, pid)
    saved = _ok(client, pid, "reglages/enregistrer", {"section": "rythme", "values": {
        "days": c.WEEKDAYS, "start": "08:00", "end": "20:00"}})
    assert saved["ok"] and saved["message"]
    p = _project(live, pid)
    assert (p.days, p.start_min, p.end_min) == (c.WEEKDAYS, 480, 1200)
    assert (p.owner, p.mode, p.title_ref, p.priority, p.approval) == (
        before.owner, before.mode, before.title_ref, before.priority, before.approval)
    _ok(client, pid, "reglages/enregistrer", {"section": "accords", "values": {
        "approval": False, "reread": c.REREAD_EACH, "issues": c.ISSUES_NEVER}})
    p = _project(live, pid)
    assert (p.approval, p.reread, p.issues) == (False, c.REREAD_EACH, c.ISSUES_NEVER)
    _ok(client, pid, "reglages/enregistrer", {"section": "outils", "values": {"tool_rss": True}})
    assert "rss" in _project(live, pid).bundles and "memory" in _project(live, pid).bundles
    _ok(client, pid, "reglages/enregistrer", {"section": "depot", "values": {
        "remote": "https://example.org/exemple/outils.git", "branch": "main"}})
    assert _project(live, pid).remote == "https://example.org/exemple/outils.git"
    # rien de changé, un champ d'une autre section, une valeur refusée par l'action, une section inconnue
    again = _post(client, pid, "reglages/enregistrer", {"section": "outils", "values": {"tool_rss": True}})
    assert again.status_code == 409 and again.json()["error"] == manage.NOTHING
    wrong = _post(client, pid, "reglages/enregistrer", {"section": "rythme", "values": {"approval": False}})
    assert wrong.status_code == 400 and wrong.json()["fields"] == {"approval": "champ inconnu"}
    assert _post(client, pid, "reglages/enregistrer", {"section": "outils", "values": {"tool_rss": "oui"}}
                 ).status_code == 400
    bad = _post(client, pid, "reglages/enregistrer", {"section": "rythme", "values": {"start": "25:00"}})
    assert bad.status_code == 400 and "start" in bad.json()["fields"]
    assert _post(client, pid, "reglages/enregistrer", {"section": "acces", "values": {"x": 1}}).status_code == 400
    # son nom et sa description : un projet qu'on lui a confié se renomme (un projet à elle, non : ``renamable``)
    assert got["renamable"] is True
    _ok(client, pid, "reglages/enregistrer", {"section": "general", "values": {"title": "Outils réseau, v2"}})
    assert _get(client, f"/{pid}")["project"]["title"] == "Outils réseau, v2"
    assert _project(live, pid).owner == before.owner  # le modifier ne change pas pour qui il est
    empty = _post(client, pid, "reglages/enregistrer", {"section": "general", "values": {"title": ""}})
    assert empty.status_code == 400 and "title" in empty.json()["fields"]


def test_a_section_shared_by_two_actions_is_saved_whole_under_one_send_key(world):  # noqa: F811
    """« Accords et relecture » tient à deux actions (modifier le projet, régler ses tickets). Envoyée avec une clé
    d'envoi, comme le font les deux clients, la seconde action se voyait répondre « déjà envoyé » : la moitié de
    l'enregistrement était perdue sans qu'on le dise. Chacune a sa clé, tirée de celle de l'envoi ; la redite du même
    envoi ne refait rien."""
    client, live, _ = world
    pid, _ = _chain(client, live)
    before = _project(live, pid)
    assert before.approval and before.issues != c.ISSUES_NEVER
    body = {"section": "accords", "values": {"approval": False, "issues": c.ISSUES_NEVER}}
    headers = {**csrf(client), "Idempotency-Key": "envoi-accords-1"}
    got = client.post(f"{API}/projets/{pid}/reglages/enregistrer", json=body, headers=headers)
    assert got.status_code == 200, got.text
    assert not got.json()["deduped"]
    p = _project(live, pid)
    assert (p.approval, p.issues) == (False, c.ISSUES_NEVER)
    # la redite du même envoi (une coupure, un double appui) : rien de plus, et rien de défait
    again = client.post(f"{API}/projets/{pid}/reglages/enregistrer", json=body, headers=headers)
    assert again.status_code in (200, 409), again.text
    p = _project(live, pid)
    assert (p.approval, p.issues) == (False, c.ISSUES_NEVER)


def test_a_project_is_archived_then_restored_by_who_frames_it(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    lea = _lea(client, live)
    _share(client, live, pid, lea, "modification")
    assert _get(client, "/archives") == {"items": []}
    assert _ok(client, pid, "archiver")["ok"]
    assert client.get(f"/api/moi/projets/{pid}").status_code == 404  # archivé : il n'existe plus ici
    listed = _get(client, "/archives")["items"]
    assert [(x["id"], x["title"]) for x in listed] == [(pid, "Outils réseau")] and listed[0]["archived_at"]
    # qui le pilotait sans en être le propriétaire ne le voit pas archivé, et ne le restaure pas
    login(client, "lea")
    assert _get(client, "/archives") == {"items": []} and _post(client, pid, "restaurer").status_code == 404
    login(client, "adrien")
    assert _ok(client, pid, "restaurer")["ok"]
    assert _get(client, f"/{pid}")["project"]["status"] == "paused" and _get(client, "/archives") == {"items": []}
    assert _post(client, pid, "restaurer").status_code == 404


# ── Ce que le cadre réserve à qui s'occupe d'elle (ADR 0292) ──

#: chaque réglage réservé, tel qu'un propriétaire qui ne s'occupe pas d'elle l'enverrait : (section, champ, valeur)
RESERVED = [("outils", "tool_email", True), ("outils", "tool_camera", True), ("outils", "tool_rss", True),
            ("outils", "tool_forge", True), ("outils", "tool_forge_apps", True), ("outils", "service_meteo", True),
            ("accords", "approval", False), ("accords", "issues", c.ISSUES_ALWAYS),
            ("depot", "remote", "https://github.com/lea/prive.git"), ("depot", "branch", "prod"),
            ("depot", "auto_push", True), ("depot", "flow", c.FLOW_DIRECT)]


def _hers(client, live, pid: int, person: str) -> None:
    """Le projet devient celui de cette personne, qui ne s'occupe pas d'elle : confié à elle, avec une ligne qui le
    lui laisse voir et modifier."""
    before = _project(live, pid)
    rows = (*c.UNSET, c.ProjectAccess(who=(PERSON + person,), see=True, steer=c.STEER_EDIT, files=True))
    append(client, live, [
        REFRAMED.draft(project=pid, set_owner=True, owner=person, about=(person,), read_about=before.read_about,
                       by="user_1"),
        ACCESS_SET.draft(project=pid, rows=rows, default=c.UNSET_DEFAULT, by="user_1")], "projects")


def _frame_of(live, pid: int) -> tuple:
    p = _project(live, pid)
    return (p.owner, tuple(sorted(p.bundles)), p.approval, p.issues, p.remote, p.branch, p.auto_push, p.flow)


def test_the_owner_of_a_project_who_does_not_keep_her_gets_nothing_beyond_the_project(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    lea = _lea(client, live)
    live.kernel.registry.bundles["mcp.meteo"] = "Le temps qu'il fait, par ville"  # un service branché sur l'instance
    _hers(client, live, pid, lea)
    before, reframed = _frame_of(live, pid), len(journal(live, REFRAMED))
    assert before[0] == lea and not managing.keeps(live.kernel.mind.frame(), lea)
    login(client, "lea")
    rights = _get(client, f"/{pid}")["rights"]
    assert rights["frame"] and rights["settle"] and _get(client, f"/{pid}")["project"]["mine"]
    # ses réglages disent, champ par champ, ce qu'elle peut changer — et pourquoi pas
    settings = _get(client, f"/{pid}/reglages")
    assert settings["can"] and settings["archive"]["can"]
    fields = {(sec["name"], f["name"]): f for sec in settings["sections"] for f in sec["fields"]}
    held = {key for key, f in fields.items() if not f["can"]}
    assert held == {(section, name) for section, name, _ in RESERVED if name != "service_meteo"}
    assert all(fields[key]["why"] == actions.KEEPER_ONLY for key in held)
    assert all(f["why"] == "" for key, f in fields.items() if key not in held)
    for key in (("general", "title"), ("general", "mode"), ("rythme", "runs_per_day"), ("accords", "reread"),
                ("accords", "ticket_review"), ("outils", "tool_memory"), ("outils", "tool_web")):
        assert fields[key]["can"], key
    by_name = {sec["name"]: sec for sec in settings["sections"]}
    assert (by_name["depot"]["can"], by_name["depot"]["why"]) == (False, actions.KEEPER_ONLY)
    assert by_name["outils"]["can"] and by_name["accords"]["can"]
    # le catalogue des services de l'instance ne lui est pas servi : elle ne peut pas les cocher
    assert not [name for _, name in fields if name.startswith("service_")]
    # chaque réglage réservé est refusé, en mots, sur son champ — et rien ne change
    for section, name, value in RESERVED:
        got = _post(client, pid, "reglages/enregistrer", {"section": section, "values": {name: value}})
        assert got.status_code == 403, (name, got.text)
        assert got.json() == {"error": actions.KEEPER_ONLY, "fields": {name: actions.KEEPER_FIELD}}, name
    mixed = _post(client, pid, "reglages/enregistrer", {"section": "outils", "values": {
        "tool_web": False, "tool_email": True}})
    assert mixed.status_code == 403 and mixed.json()["fields"] == {"tool_email": actions.KEEPER_FIELD}
    assert _frame_of(live, pid) == before and len(journal(live, REFRAMED)) == reframed
    # la garde est dans l'action, pas seulement dans la route : la même demande faite sans passer par elle (la
    # console, au nom de cette personne) est refusée de même
    account = client.portal.call(lambda: next(a for a in live.accounts.all() if a.username == "lea"))
    for key, values in (("projects.outils", {"tool_memory": True, "tool_web": True, "tool_email": True}),
                        ("projects.outils", {"tool_memory": True, "tool_web": True, "service_meteo": True}),
                        ("projects.depot_distant", {"remote": "https://github.com/lea/prive.git", "branch": "main",
                                                    "flow": "auto"}),
                        ("projects.tickets_regler", {"ticket_review": c.REVIEW_ALWAYS, "small_files": 3,
                                                     "small_lines": 40, "issues": c.ISSUES_ALWAYS})):
        direct = client.portal.call(lambda key=key, values=values: perform(
            live.kernel, key, api_form(**values), by=account.handle, subject=str(pid)))
        assert not direct.ok and direct.message == actions.KEEPER_ONLY, (key, direct)
    assert _frame_of(live, pid) == before and len(journal(live, REFRAMED)) == reframed
    # le reste de son cadre est à elle : son titre, son rythme, sa relecture, la validation des plans, le web
    _ok(client, pid, "reglages/enregistrer", {"section": "general", "values": {"title": "Les outils de Léa"}})
    _ok(client, pid, "reglages/enregistrer", {"section": "rythme", "values": {"runs_per_day": 3}})
    _ok(client, pid, "reglages/enregistrer", {"section": "accords", "values": {"reread": c.REREAD_EACH}})
    _ok(client, pid, "reglages/enregistrer", {"section": "outils", "values": {"tool_web": False}})
    p = _project(live, pid)
    assert (p.owner, p.runs_per_day, p.reread, p.approval) == (lea, 3, c.REREAD_EACH, True)
    assert "mcp.web" not in p.bundles and not [b for b in p.bundles if managing.beyond(b)]
    # qui s'occupe d'elle, lui, donne ce qui est réservé — et voit le service branché
    login(client, "adrien")
    theirs = {f["name"]: f for sec in _get(client, f"/{pid}/reglages")["sections"] for f in sec["fields"]}
    assert theirs["service_meteo"]["can"] and theirs["tool_email"]["can"] and theirs["approval"]["can"]
    _ok(client, pid, "reglages/enregistrer", {"section": "outils", "values": {"tool_email": True,
                                                                               "service_meteo": True}})
    assert {"email", "mcp.meteo"} <= set(_project(live, pid).bundles)
    # ce que le projet a, sa propriétaire le voit — coché, sans pouvoir y toucher — ; pas le reste du catalogue
    live.kernel.registry.bundles["mcp.cms"] = "Publier une page"
    login(client, "lea")
    hers = {f["name"]: f for sec in _get(client, f"/{pid}/reglages")["sections"] for f in sec["fields"]}
    assert (hers["service_meteo"]["value"], hers["service_meteo"]["can"]) == (True, False)
    assert "service_cms" not in hers and (hers["tool_email"]["value"], hers["tool_email"]["can"]) == (True, False)
    off = _post(client, pid, "reglages/enregistrer", {"section": "outils", "values": {"tool_email": False}})
    assert off.status_code == 403 and "email" in _project(live, pid).bundles


def test_the_rule_of_what_a_frame_reserves_is_pure():
    assert [b for b in EXTRA_BUNDLES if not managing.beyond(b)] == list(managing.OWN_BUNDLES) == ["memory", "mcp.web"]
    assert managing.beyond("mcp.meteo") and not managing.beyond("projects") and not managing.beyond("workshop")
    held = {"projects.outils": ["tool_email", "tool_rss", "tool_forge", "tool_forge_apps", "tool_camera",
                                "service_meteo"],
            "projects.modifier": ["owner", "approval"], "projects.depot_distant": ["remote", "branch", "auto_push",
                                                                                   "flow"],
            "projects.tickets_regler": ["issues"]}
    for action, names in held.items():
        assert all(actions.reserved_field(action, name) for name in names), action
    free = {"projects.outils": ["tool_memory", "tool_web"], "projects.modifier": ["title", "description", "mode",
                                                                                 "schedule", "runs_per_day",
                                                                                 "priority", "reread"],
            "projects.tickets_regler": ["ticket_review", "small_files", "small_lines", "protected"]}
    for action, names in free.items():
        assert not any(actions.reserved_field(action, name) for name in names), action


def test_saving_the_settings_of_a_project_for_no_one_does_not_make_the_caller_its_owner(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    before = _project(live, pid)
    append(client, live, [REFRAMED.draft(project=pid, set_owner=True, owner=None, about=(), by="user_1",
                                         read_about=before.read_about)], "projects")
    assert _project(live, pid).owner is None and _project(live, pid).authority == c.USER
    _ok(client, pid, "reglages/enregistrer", {"section": "rythme", "values": {"runs_per_day": 4}})
    _ok(client, pid, "reglages/enregistrer", {"section": "general", "values": {"title": "Sans personne"}})
    p = _project(live, pid)
    assert (p.owner, p.about, p.runs_per_day) == (None, (), 4)  # il reste pour personne tant qu'on ne nomme personne


def test_restoring_goes_through_what_the_person_has_of_the_project(world):  # noqa: F811
    """Un propriétaire que ses lignes d'accès laissent en lecture seule ne restaure pas son projet archivé par qui
    s'occupe d'elle, et ne le voit pas parmi les archives ; avec une ligne en modification, si."""
    client, live, _ = world
    pid, _ = _chain(client, live)
    lea = _lea(client, live)
    _hers(client, live, pid, lea)

    def line(steer: str) -> None:
        rows = (*c.UNSET, c.ProjectAccess(who=(PERSON + lea,), see=True, steer=steer))
        append(client, live, [ACCESS_SET.draft(project=pid, rows=rows, default=c.UNSET_DEFAULT, by="user_1")],
               "projects")

    line(c.STEER_READ)  # c'est son projet, mais ses lignes ne lui laissent que la lecture
    login(client, "lea")
    rights = _get(client, f"/{pid}")["rights"]
    assert _get(client, f"/{pid}")["project"]["mine"] and not rights["frame"] and rights["steer"] == c.STEER_READ
    assert _post(client, pid, "archiver").status_code == 403
    login(client, "adrien")
    assert _ok(client, pid, "archiver")["ok"]
    # archivé par qui s'occupe d'elle : sa propriétaire en lecture seule ne le voit pas archivé, et ne le restaure pas
    login(client, "lea")
    assert _get(client, "/archives") == {"items": []} and _post(client, pid, "restaurer").status_code == 404
    assert _project(live, pid).status == c.ARCHIVED
    # qui s'occupe d'elle le voit, avec le nom de sa propriétaire
    login(client, "adrien")
    assert [(x["id"], x["owner_name"]) for x in _get(client, "/archives")["items"]] == [(pid, "Léa Martin")]
    line(c.STEER_EDIT)
    # en modification : il est parmi ses archives — sans son propre nom —, et elle le restaure
    login(client, "lea")
    assert [(x["id"], x["owner_name"]) for x in _get(client, "/archives")["items"]] == [(pid, "")]
    assert _ok(client, pid, "restaurer")["ok"] and _project(live, pid).status == c.PAUSED


# ── Ses objectifs et ses jalons ──


def test_objectives_and_missions_are_added_changed_closed_reopened_and_dropped(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    added = _ok(client, pid, "objectif", {"text": "Exporter en CSV", "done_when": "Le fichier s'ouvre dans un tableur."})
    oid = added["objective"]
    shown = _objective(client, pid, oid)
    assert (shown["text"], shown["done_when"], shown["status"]) == (
        "Exporter en CSV", "Le fichier s'ouvre dans un tableur.", "open")
    assert shown["can"] == {"modify": True, "reopen": False, "done": True, "drop": True, "milestone": True, "why": ""}
    # une mission : sa cadence, ce que chaque passage doit faire, son premier passage tout de suite
    mission = _ok(client, pid, "objectif", {"text": "Relire les résultats", "kind": "constant", "cadence_hours": 24,
                                            "each_pass": "Relire les sorties\nNoter ce qui est douteux",
                                            "at_once": True})["objective"]
    seen = _objective(client, pid, mission)
    assert seen["cadence_hours"] == 24 and "Relire les sorties" in seen["each_pass"] and seen["cadence_label"]
    assert seen["can"]["modify"] and not seen["can"]["done"] and not seen["can"]["milestone"]
    assert next(o for o in _project(live, pid).objectives if o.id == mission).at_once
    bad = _post(client, pid, "objectif", {"text": "Écouter", "kind": "constant", "on": ["project:999:commit"]})
    assert bad.status_code == 400 and "on" in bad.json()["fields"]
    # le modifier : seul ce qui est dit change
    _ok(client, pid, "objectif/modifier", {"objective": oid, "done_when": "Le fichier s'ouvre dans Excel."})
    changed = _objective(client, pid, oid)
    assert (changed["text"], changed["done_when"]) == ("Exporter en CSV", "Le fichier s'ouvre dans Excel.")
    _ok(client, pid, "objectif/modifier", {"objective": mission, "cadence_hours": 12})
    kept = _objective(client, pid, mission)
    assert kept["cadence_hours"] == 12 and "Relire les sorties" in kept["each_pass"]
    assert _post(client, pid, "objectif/modifier", {"objective": oid}).status_code == 409  # rien n'a changé
    assert _post(client, pid, "objectif/modifier", {"objective": 99, "text": "x"}).status_code == 404
    # le dire terminé, le rouvrir, le retirer
    _ok(client, pid, "objectif/statut", {"objective": oid, "status": "done"})
    done = _objective(client, pid, oid)
    assert done["status"] == "done" and done["can"]["reopen"] and not done["can"]["done"]
    _ok(client, pid, "objectif/statut", {"objective": oid, "status": "open"})
    assert _objective(client, pid, oid)["status"] == "open"
    assert _post(client, pid, "objectif/statut", {"objective": mission, "status": "done"}).status_code == 409
    assert _post(client, pid, "objectif/statut", {"objective": oid, "status": "blocked"}).status_code == 400
    _ok(client, pid, "objectif/statut", {"objective": oid, "status": "dropped"})
    fiche = _get(client, f"/{pid}")
    assert oid not in [o["id"] for o in fiche["objectives"]]
    # retiré, il se rouvre encore (par son numéro), mais ne se modifie plus
    assert _post(client, pid, "objectif/modifier", {"objective": oid, "text": "x"}).status_code == 404
    _ok(client, pid, "objectif/statut", {"objective": oid, "status": "open"})
    assert _objective(client, pid, oid)["status"] == "open"


def test_milestones_are_added_changed_and_dropped_and_a_checkpoint_is_not_undone(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    lea = _lea(client, live)
    _share(client, live, pid, lea, "modification")
    oid = _ok(client, pid, "objectif", {"text": "Exporter en CSV"})["objective"]
    _ok(client, pid, "jalon/ajouter", {"objective": oid, "text": "Les tests passent", "check": "command",
                                       "command": "pytest -q tests"})
    _ok(client, pid, "jalon/ajouter", {"objective": oid, "text": "Tu as relu l'export", "check": "owner"})
    assert _post(client, pid, "jalon/ajouter", {"objective": oid, "text": "Sans commande", "check": "command"}
                 ).status_code == 400
    first, stop = _objective(client, pid, oid)["milestones"]
    assert (first["check"], first["check_label"], stop["check"]) == ("command", "une commande", "owner")
    assert first["can"] == {"modify": True, "drop": True, "why": ""} == stop["can"]
    # le propriétaire modifie le texte et la vérification d'un jalon ouvert
    _ok(client, pid, "jalon/modifier", {"objective": oid, "milestone": first["id"], "text": "Tous les tests passent",
                                        "reason": "Plus clair."})
    m = next(x for x in _project(live, pid).objectives if x.id == oid).milestones[0]
    assert m.check == c.CHECK_COMMAND and m.command_ref and m.revised == 1  # sa commande est restée
    assert _objective(client, pid, oid)["milestones"][0]["text"] == "Tous les tests passent"
    _ok(client, pid, "jalon/modifier", {"objective": oid, "milestone": first["id"], "check": "prose"})
    assert _objective(client, pid, oid)["milestones"][0]["check"] == "prose"
    assert _post(client, pid, "jalon/modifier", {"objective": oid, "milestone": 9, "text": "x"}).status_code == 404
    # **un point d'arrêt et un jalon posé par le propriétaire ne se défont pas** par qui pilote sans l'être
    login(client, "lea")
    seen = _objective(client, pid, oid)["milestones"]
    assert not seen[1]["can"]["drop"] and seen[1]["can"]["why"] == inspect_manage.HELD_WORDS["breakpoint"]
    assert not seen[0]["can"]["modify"] and seen[0]["can"]["why"] == inspect_manage.HELD_WORDS["other"]
    for route, body in (("jalon/retirer", {"milestone": stop["id"]}),
                        ("jalon/modifier", {"milestone": stop["id"], "check": "prose"}),
                        ("jalon/retirer", {"milestone": first["id"]})):
        refused = _post(client, pid, route, {"objective": oid, **body})
        assert refused.status_code == 403, (route, refused.text)
    assert [x["status"] for x in _objective(client, pid, oid)["milestones"]] == ["open", "open"]
    # … mais elle en ajoute un, puisqu'elle le pilote en modification
    _ok(client, pid, "jalon/ajouter", {"objective": oid, "text": "La page est écrite"})
    login(client, "adrien")
    # un jalon atteint ne bouge plus, pour personne
    p = _project(live, pid)
    append(client, live, [MILESTONE_CHANGED.draft(project=pid, objective=oid, milestone=first["id"],
                                                  status=c.REACHED, author="operator", by="user_1", owner=p.owner,
                                                  about=p.about)], "projects")
    reached = _objective(client, pid, oid)["milestones"][0]
    assert reached["status"] == "reached" and not reached["can"]["modify"]
    assert reached["can"]["why"] == inspect_manage.HELD_WORDS[managing.SETTLED]
    assert _post(client, pid, "jalon/retirer", {"objective": oid, "milestone": first["id"]}).status_code == 409
    # le propriétaire retire le point d'arrêt : il reste lisible, retiré
    _ok(client, pid, "jalon/retirer", {"objective": oid, "milestone": stop["id"], "reason": "Plus besoin."})
    dropped = next(x for x in _project(live, pid).objectives if x.id == oid).milestones[1]
    assert dropped.status == c.DROPPED and dropped.reason_ref


def test_the_rule_of_a_held_milestone_is_pure():
    hers = Milestone(1, "t")
    assert managing.undoing(hers, False) == "" == managing.undoing(hers, True)
    for held in (replace(hers, check=c.CHECK_OWNER), replace(hers, author="operator"), replace(hers, agreed=True),
                 replace(hers, refused_at=5)):
        assert managing.undoing(held, False) and managing.undoing(held, True) == ""
    for status in (c.REACHED, c.DROPPED):
        assert managing.undoing(replace(hers, status=status), True) == managing.SETTLED


# ── Un ticket, une décision ──


def test_a_ticket_is_edited_by_who_pilots_and_closed_by_who_settles(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    lea = _lea(client, live)
    _share(client, live, pid, lea, "modification")
    number = _numbers(client, pid)["Journaliser les connexions refusées"]
    before = _ticket(client, pid, number)
    assert before["can"]["modify"] and before["can"]["close"] and not before["can"]["reopen"]
    _ok(client, pid, "ticket/modifier", {"item": f"#{number}", "title": "Journaliser chaque refus",
                                         "priority": "urgent", "kind": "bug"})
    after = _ticket(client, pid, number)
    assert (after["title"], after["priority"], after["priority_label"], after["kind"]) == (
        "Journaliser chaque refus", "urgent", "urgente", "bug")
    assert (after["status"], after["body"], after["plan"]) == (before["status"], before["body"], before["plan"])
    _ok(client, pid, "ticket/modifier", {"item": f"#{number}", "text": "Une ligne par refus, en JSON."})
    assert _ticket(client, pid, number)["body"] == "Une ligne par refus, en JSON."
    assert _post(client, pid, "ticket/modifier", {"item": f"#{number}"}).status_code == 409  # rien n'a changé
    assert _post(client, pid, "ticket/modifier", {"item": f"#{number}", "kind": "roman"}).status_code == 400
    assert _post(client, pid, "ticket/modifier", {"item": "#99", "title": "x"}).status_code == 404
    # qui le pilote en modification le modifie aussi ; le fermer et le rouvrir restent à qui tranche
    login(client, "lea")
    hers = _ticket(client, pid, number)["can"]
    assert hers["modify"] and not hers["close"] and not hers["reopen"]
    _ok(client, pid, "ticket/modifier", {"item": f"#{number}", "priority": "normal"})
    closing = _post(client, pid, "ticket/trancher", {"item": f"#{number}", "verdict": "done"})
    assert closing.status_code == 403 and closing.json()["error"] == reach.NOT_SETTLER
    login(client, "adrien")
    _ok(client, pid, "ticket/trancher", {"item": f"#{number}", "verdict": "done"})
    closed = _ticket(client, pid, number)
    assert closed["status"] == "treated" and closed["can"]["reopen"] and not closed["can"]["close"]
    _ok(client, pid, "ticket/trancher", {"item": f"#{number}", "verdict": "reopen"})
    assert _ticket(client, pid, number)["open"]


def test_decisions_are_recorded_read_edited_replaced_and_withdrawn(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    assert _get(client, f"/{pid}/decisions")["can"]
    first = _ok(client, pid, "decision/ajouter", {
        "title": "Le format du journal", "choice": "Un fichier texte libre.", "reason": "Le plus simple.",
        "context": "Il faut une trace.", "options": "SQLite ; syslog"})["number"]
    listed = _get(client, f"/{pid}/decisions")
    assert (listed["total"], listed["in_force"]) == (1, 1)
    row = listed["items"][0]
    assert (row["number"], row["title"], row["status"], row["status_label"]) == (
        first, "Le format du journal", c.IN_FORCE, "en vigueur")
    assert row["can"] == {"modify": True, "replace": True, "withdraw": True, "restore": False, "why": ""}
    one = _get(client, f"/{pid}/decision", number=first)
    assert (one["choice"], one["context"], one["options"], one["reason"]) == (
        "Un fichier texte libre.", "Il faut une trace.", "SQLite ; syslog", "Le plus simple.")
    # la modifier : ses textes changent, son numéro et son statut restent ; un texte facultatif se vide
    _ok(client, pid, "decision/modifier", {"number": first, "choice": "Un fichier texte, une ligne par refus.",
                                           "options": ""})
    edited = _get(client, f"/{pid}/decision", number=first)
    assert (edited["choice"], edited["options"], edited["reason"], edited["status"]) == (
        "Un fichier texte, une ligne par refus.", "", "Le plus simple.", c.IN_FORCE)
    assert _post(client, pid, "decision/modifier", {"number": first}).status_code == 409
    assert _post(client, pid, "decision/modifier", {"number": first, "title": ""}).status_code == 400
    # la remplacer : l'ancienne reste lisible, remplacée, et ne se modifie plus
    second = _ok(client, pid, "decision/ajouter", {"title": "Le format du journal", "choice": "JSON Lines.",
                                                   "replaces": first})["number"]
    old = _get(client, f"/{pid}/decision", number=first)
    assert (old["status"], old["status_label"], old["replaced_by"]) == (c.SUPERSEDED, "remplacée", second)
    assert not old["can"]["modify"] and _get(client, f"/{pid}/decision", number=second)["replaces"] == first
    assert _post(client, pid, "decision/modifier", {"number": first, "choice": "Autre"}).status_code == 409
    assert [d["number"] for d in _get(client, f"/{pid}/decisions")["items"]] == [second]
    assert [d["number"] for d in _get(client, f"/{pid}/decisions", status="all")["items"]] == [second, first]
    # la retirer, la remettre en vigueur
    _ok(client, pid, "decision/statut", {"number": second, "status": c.WITHDRAWN})
    gone = _get(client, f"/{pid}/decision", number=second)
    assert gone["status"] == c.WITHDRAWN and gone["can"]["restore"] and not gone["can"]["withdraw"]
    _ok(client, pid, "decision/statut", {"number": second, "status": c.IN_FORCE})
    assert _post(client, pid, "decision/statut", {"number": second, "status": c.SUPERSEDED}).status_code == 400
    assert client.get(f"/api/moi/projets/{pid}/decision", params={"number": 99}).status_code == 404


# ── Qui a le droit ──


def test_every_gesture_is_refused_to_who_may_not(world):  # noqa: F811
    client, live, _ = world
    pid, _ = _chain(client, live)
    lea = _lea(client, live)
    numbers = _numbers(client, pid)
    edits = [(route, {**body, "item": f"#{min(numbers.values())}"} if "item" in body else body) for route, body in EDITS]
    login(client, "lea")
    # sans accès : le projet n'existe pas
    for route, body in (*FRAME, *edits):
        assert _post(client, pid, route, body).status_code == 404, route
    assert client.get(f"/api/moi/projets/{pid}/reglages").status_code == 404
    # qui ne fait que le voir : son détail lui est fermé
    login(client, "adrien")
    _share(client, live, pid, lea, "non")
    login(client, "lea")
    for route, body in (*FRAME, *edits):
        seen = _post(client, pid, route, body)
        assert seen.status_code == 403 and seen.json()["error"] == reach.ONLY_SEEN, route
    assert client.get(f"/api/moi/projets/{pid}/reglages").status_code == 403
    # sur l'accord du propriétaire : rien de tout cela d'ici
    login(client, "adrien")
    _share(client, live, pid, lea, "accord")
    login(client, "lea")
    rights = _get(client, f"/{pid}")["rights"]
    assert not rights["frame"] and not rights["edit"] and not rights["pull_write"]
    for route, body in (*FRAME, *edits):
        asked = _post(client, pid, route, body)
        assert asked.status_code == 403 and asked.json()["error"] == reach.NEEDS_EDIT, route
    settings = _get(client, f"/{pid}/reglages")
    assert not settings["can"] and settings["why"] == reach.NEEDS_EDIT and not settings["archive"]["can"]
    assert _objective(client, pid, 1)["can"]["why"] == reach.NEEDS_EDIT
    # en modification, sans en être le propriétaire : ses objectifs, ses jalons, ses tickets, ses décisions — pas
    # son cadre
    login(client, "adrien")
    _share(client, live, pid, lea, "modification")
    login(client, "lea")
    rights = _get(client, f"/{pid}")["rights"]
    assert rights["edit"] and not rights["frame"] and not rights["pull_write"]
    for route, body in FRAME:
        framed = _post(client, pid, route, body)
        assert framed.status_code == 403 and framed.json()["error"] == reach.NOT_FRAMER, route
    settings = _get(client, f"/{pid}/reglages")
    assert not settings["can"] and settings["why"] == reach.NOT_FRAMER
    assert "remote" not in {f["name"] for s in settings["sections"] for f in s["fields"]}  # l'adresse du dépôt
    for route, body in edits:
        assert _post(client, pid, route, body).status_code == 200, route
    assert _project(live, pid).status == c.ACTIVE and _project(live, pid).runs_per_day == 0


def test_dependances_is_the_word_served(world):  # noqa: F811
    client, live, _ = world
    pid, rid = _chain(client, live)
    assert _get(client, f"/{rid}")["links"]["labels"] == {
        "title": "Dépendances", "reads": "Il dépend de", "readers": "Dépendent de lui", "asks": "Ses demandes"}
    page = client.get(f"/admin/fiche/project/{rid}?onglet=liens").text
    assert "Dépendances" in page and "Il dépend de" in page and "Dépendent de lui" in page
    assert "Ses demandes" in page and "Ses liens de lecture" not in page
    assert "Dépendances entre projets" in client.get("/admin/projets/tous").text


# ── Une pull request : son titre, son texte, un commentaire ──


class WritingHost(FakeHost):
    """Un hôte qui garde ce qu'on lui écrit."""

    def __init__(self) -> None:
        super().__init__()
        self.edits: list[tuple[int, str | None, str | None]] = []
        self.remarks: list[tuple[int, str, str]] = []

    async def edit_pull(self, url: str, number: int, *, title: str | None = None, body: str | None = None) -> Pull:
        self.edits.append((number, title, body))
        return replace(self.says, title=title or self.says.title)

    async def remark(self, url: str, number: int, *, body: str, mark: str) -> Remark:
        self.remarks.append((number, body, mark))
        return Remark(id=900 + len(self.remarks), issue=number, body=body, mark=mark)


def _writing(client, live) -> tuple[Repo, WritingHost]:
    r = Repo(client, live)
    host = WritingHost()
    host.says, host.checked = r.host.says, r.host.checked
    for ports in (live.kernel.ports, live.kernel.scheduler.ports, live.kernel.effects.ports):
        ports["repo_host"] = host
    return r, host


def _settled(client, live) -> None:
    """Les effets partis après le commit du journal ont répondu."""
    client.portal.call(live.kernel.lanes.join)


@needs_bwrap
def test_a_person_edits_a_pull_request_and_comments_it_signed(world):  # noqa: F811
    client, live, _ = world
    r, host = _writing(client, live)
    pid = r.pid
    assert _get(client, f"/{pid}")["rights"]["pull_write"]
    edited = _ok(client, pid, "code/pull/modifier", {"number": 12, "title": "Journaliser chaque refus",
                                                     "body": "Une ligne par refus."})
    assert edited["asked"] and edited["number"] == 12
    said = _ok(client, pid, "code/pull/commenter", {"number": 12, "text": "Vu, ça me va."})
    assert said["asked"]
    _settled(client, live)
    # partis par le port, après le commit : le titre et le texte ; le commentaire, signé de son nom, avec son repère
    assert host.edits == [(12, "Journaliser chaque refus", "Une ligne par refus.")]
    [(number, body, mark)] = host.remarks
    assert number == 12 and body.endswith("Vu, ça me va.") and "adrien" in body.lower() and body != "Vu, ça me va."
    asked = journal(live, managing.PULL_WRITE_ASKED)
    assert [e.data.what for e in asked] == [managing.EDIT, managing.COMMENT] and all(e.data.by for e in asked)
    assert mark == managing.reply_mark(pid, asked[1].seq)
    answers = journal(live, managing.PULL_WRITE_ANSWERED)
    assert [(e.data.what, e.data.ok, e.data.asked) for e in answers] == [
        (managing.EDIT, True, asked[0].seq), (managing.COMMENT, True, asked[1].seq)]
    # rien à changer, un commentaire vide, une pull request inconnue
    assert _post(client, pid, "code/pull/modifier", {"number": 12}).status_code == 400
    assert _post(client, pid, "code/pull/commenter", {"number": 12, "text": "  "}).status_code == 400
    assert _post(client, pid, "code/pull/commenter", {"number": 99, "text": "x"}).status_code == 404
    # l'hôte refuse : la réponse le dit, rien n'est rejoué
    host.says = replace(host.says, error="")

    async def no(url, number, *, body, mark):
        return Remark(issue=number, error="403")

    host.remark = no
    _ok(client, pid, "code/pull/commenter", {"number": 12, "text": "Encore un mot."})
    _settled(client, live)
    last = journal(live, managing.PULL_WRITE_ANSWERED)[-1].data
    assert (last.ok, last.why) == (False, managing.REFUSED)
    # une personne seulement : qui pilote sans être le propriétaire n'écrit pas chez l'hôte
    lea = _lea(client, live)
    _share(client, live, pid, lea, "modification")
    login(client, "lea")
    for route, body in (("code/pull/modifier", {"title": "Autre"}), ("code/pull/commenter", {"text": "Moi aussi."})):
        refused = _post(client, pid, route, {"number": 12, **body})
        assert refused.status_code == 403 and refused.json()["error"] == inspect_manage.NOT_WRITER, route
    assert len(journal(live, managing.PULL_WRITE_ASKED)) == 3 and len(host.edits) == 1


def test_only_the_gesture_of_a_person_writes_on_a_pull_request():
    """``pull_write_asked`` n'est écrit que par ses deux actions, ``edit_pull`` n'est appelé que par son effet : ni
    un outil, ni un processus, ni une capacité qu'une exécution pourrait proposer. Par l'AST, jamais par le texte."""
    def mentions(word: str) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)} | {
                    n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
                    n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value == word}
                if word in names or fn.name == word:
                    found.setdefault(str(path.relative_to(SRC)), set()).add(fn.name)
        return found

    assert mentions("edit_pull") == {
        "adapters/workshop/github.py": {"edit_pull"}, "app/domains/projects/demo_git.py": {"edit_pull"},
        "ports/workshop.py": {"edit_pull"}, "faculties/projects/managing.py": {"_write"},
        "app/domains/projects/api/manage.py": {"edit_pull", "routes"}}  # la route de ce nom : elle passe par l'action
    assert mentions("PULL_WRITE_ASKED") == {
        "faculties/projects/managing.py": {"writing", "_write"},  # le fait, et l'effet qui l'attend
        "faculties/projects/inspect_manage.py": {"_pull_edit", "_pull_comment"}}  # les deux actions qui l'émettent
    # le commentaire d'une personne est signé à son départ : son nom quand il se sait, sinon sans nom
    assert managing.signed(None, "", "Vu.").endswith("Vu.") and managing.signed(None, "", "Vu.") != "Vu."
