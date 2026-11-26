"""Ce que l'écran Projets lit sans rien recalculer (ADR 0293), à travers le vrai serveur, sur la chaîne d'exemple :

- la carte d'un projet dans la liste (ses objectifs, ses pull requests et ses tickets ouverts, ses dépendances, par
  qui il est mené) — rien pour qui ne fait que le voir, un projet lié nommé seulement à qui le voit ;
- la fiche : son prochain passage, son rythme, ses consignes en attente, son dernier commit, le titre d'une pull
  request, les tickets d'un objectif, un jalon commencé et ce qui le lie à un élément, de quoi remplir les
  formulaires ;
- un ticket : son parcours en six étapes, son histoire, le fil filtré par ticket, les totaux ;
- un accord : ce qu'il concerne, où il part, qui l'a demandé ;
- une dépendance : depuis quand, le mot de son propriétaire (un texte gardé, que l'oubli atteint), le commit de la
  vue, les demandes dans les deux sens, « lui demander quelque chose » ;
- une liste de suivi : y ajouter un élément, changer à qui il est.

Chaque point avec ses droits : qui pilote, qui ne fait que lire, qui ne fait que voir, qui ne voit pas.
"""

from __future__ import annotations

from mika.app.domains.projects.api import projects as moi
from mika.app.domains.projects.api import reach
from mika.contracts import projects as c
from mika.contracts import self_ as self_c
from mika.faculties.projects import tickets, tracker
from mika.faculties.projects.faculty import ACCESS_SET, BASE_SEEN, LINKS_SET, NOTED
from mika.kernel.events import Content
from mika.vocab.access import STEER_NO
from tests.protocol.test_moi_mail import API, append, journal, login, post
from tests.protocol.test_moi_project_code import repo  # noqa: F401 — fixture partagée
from tests.protocol.test_moi_projects import (
    _ask_pause,
    _chain,
    _get,
    _lea,
    _numbers,
    _project,
    _share,
    _ticket,
)
from tests.protocol.test_tabs_projects import _create
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée
from tests.unit.test_project_pulls import needs_bwrap

P = API + "/projets"


def _close(client, live, pid: int) -> None:
    """Plus aucune ligne d'accès ne désigne personne : le projet n'est plus ouvert qu'à qui il est."""
    append(client, live, [ACCESS_SET.draft(project=pid, rows=c.UNSET, default=c.UNSET_DEFAULT, by="user_1")],
           "projects")


def _card(client, pid: int) -> dict | None:
    return next(p for p in _get(client, "")["projects"] if p["id"] == pid)["card"]


# ── la liste ──


def test_the_list_fills_each_card_without_its_fiche(world):  # noqa: F811
    client, live, _ = world
    pid, rid = _chain(client, live)
    card = _card(client, pid)
    assert card["objectives"]["total"] == 2 == len(card["objectives"]["states"])
    assert card["objectives"]["todo"] == 2 and card["objectives"]["done"] == card["objectives"]["doing"] == 0
    assert {s["state_label"] for s in card["objectives"]["states"]} == {"à venir"}
    assert card["tickets_open"] == len(_get(client, f"/{pid}/elements", state="open")["items"]) > 0
    assert card["pulls_open"] == 0 and card["last_activity"] > 0
    assert card["led_by"] == self_c.name_of(live.kernel.mind.frame().get(self_c.PERSONA)) != ""
    assert card["reads"] == [] and card["readers"] == [{"project": rid, "title": "Faire connaître Outils réseau",
                                                       "visible": True}]
    assert _card(client, rid)["reads"] == [{"project": pid, "title": "Outils réseau", "visible": True}]
    # qui lit le lecteur sans voir le produit : la dépendance se dit, le projet non
    lea = _lea(client, live)
    _share(client, live, rid, lea, "lecture")
    login(client, "lea")
    assert [p["id"] for p in _get(client, "")["projects"]] == [rid]
    assert _card(client, rid)["reads"] == [{"project": None, "title": "", "visible": False}]
    # qui ne fait que le voir n'a pas de carte
    login(client, "adrien")
    _share(client, live, rid, lea, STEER_NO)
    login(client, "lea")
    assert _card(client, rid) is None


# ── la fiche ──


def test_the_fiche_says_its_next_pass_its_rhythm_and_the_instructions_that_wait(world):  # noqa: F811
    client, live, _ = world
    pid, _rid = _chain(client, live)
    fiche = _get(client, f"/{pid}")
    coming = fiche["next"]
    assert coming["state"] in moi.NEXT_WORDS and coming["state_label"] == moi.NEXT_WORDS[coming["state"]]
    if coming["at"]:  # daté : ce que ce sera, et sur quel objectif
        assert coming["state"] == "due" and coming["sort"] == "run" and coming["sort_label"]
        assert coming["objective"]["id"] in {o["id"] for o in fiche["objectives"]}
    rhythm = next(s for s in _get(client, f"/{pid}/reglages")["sections"] if s["name"] == "rythme")["summary"]
    assert fiche["rhythm"]["summary"] == rhythm == f"{fiche['rhythm']['schedule']} · {fiche['rhythm']['window']}"
    assert fiche["instructions"] == [] and fiche["repo"]["commit"] is None  # ni consigne, ni dépôt encore
    said = post(client, f"/projets/{pid}/piloter", {"what": "instruct", "text": "Commence par le module RDP."})
    assert said.status_code == 200, said.text
    waiting = _get(client, f"/{pid}")["instructions"]
    assert [(x["text"], x["author_kind"], x["author"], x["veiled"]) for x in waiting] == [
        ("Commence par le module RDP.", "you", "toi", False)]
    # en pause : rien n'est en vue, et la fiche dit pourquoi
    assert post(client, f"/projets/{pid}/piloter", {"what": "pause"}).status_code == 200
    paused = _get(client, f"/{pid}")["next"]
    assert (paused["at"], paused["state"], paused["objective"]) == (0, "paused", None)
    # qui ne fait que le lire lit la consigne, et qui l'a donnée (il s'occupe d'elle : sa voix le nomme)
    lea = _lea(client, live)
    _share(client, live, pid, lea, "lecture")
    login(client, "lea")
    hers = _get(client, f"/{pid}")
    assert hers["instructions"][0]["text"] == "Commence par le module RDP."
    assert hers["instructions"][0]["author_kind"] == "person" and hers["instructions"][0]["author"] not in ("", "toi")
    # qui ne fait que le voir ne reçoit rien de tout cela
    login(client, "adrien")
    _share(client, live, pid, lea, STEER_NO)
    login(client, "lea")
    seen = _get(client, f"/{pid}")
    assert not ({"next", "rhythm", "instructions", "forms", "repo"} & set(seen))


def test_an_objective_names_its_tickets_and_a_milestone_what_ties_it(world):  # noqa: F811
    client, live, _ = world
    pid, _rid = _chain(client, live)
    fiche = _get(client, f"/{pid}")
    o = next(x for x in fiche["objectives"] if x["milestones"])
    assert o["tickets"] == [] and all(not m["started"] for m in o["milestones"])  # aucune exécution encore
    assert all((m["item_list"], m["item"], m["item_status"], m["command"]) == ("", "", "", "")
               for m in o["milestones"])
    number = _numbers(client, pid)["Le pied de page est vide"]
    added = post(client, f"/projets/{pid}/jalon/ajouter", {
        "objective": o["id"], "text": "Le ticket du pied de page est traité", "check": "item",
        "item_list": "tickets", "item": f"#{number}", "item_status": "treated"})
    assert added.status_code == 200, added.text
    tied = _get(client, f"/{pid}")["objectives"]
    mark = next(m for x in tied for m in x["milestones"] if m["check"] == "item")
    assert (mark["item_list"], mark["item_status"], mark["item_status_label"]) == (
        "tickets", "treated", tracker.status_words(c.TICKETS, "treated"))
    assert mark["item"]  # la clé du ticket, telle que le jalon la garde
    # un plan validé : l'objectif qui en naît nomme son ticket, avec son étape du parcours
    planned = _numbers(client, pid)["Journaliser les connexions refusées"]
    seq = _ticket(client, pid, planned)["plan"]
    assert post(client, f"/projets/{pid}/ticket/trancher",
                {"item": f"#{planned}", "verdict": "validate", "plan": seq}).status_code == 200
    born = next(x for x in _get(client, f"/{pid}")["objectives"] if x["ticket"] == planned)
    assert [(t["number"], t["title"], t["status"], t["step"], t["step_label"]) for t in born["tickets"]] == [
        (planned, "Journaliser les connexions refusées", "working", "treated", "Traité")]


def test_the_fiche_serves_what_the_forms_need(world):  # noqa: F811
    client, live, _ = world
    pid, rid = _chain(client, live)
    forms = _get(client, f"/{rid}")["forms"]
    assert forms["can"] and forms["triggers_max"] == 4
    by_key = {t["key"]: t for t in forms["triggers"]}
    assert by_key[f"project:{pid}:commit"]["sort"] == "project" and by_key[f"project:{pid}:commit"]["label"]
    assert by_key[f"project:{pid}:commit"]["title"] == "Outils réseau" and f"project:{pid}:done" in by_key
    assert by_key["item:tickets"]["sort_label"] == by_key["item:entreprises"]["sort_label"] == "une de ses listes"
    checks = {x["code"]: x for x in forms["checks"]}
    assert list(checks) == list(c.CHECKS) and all(x["label"] and x["help"] for x in checks.values())
    assert [f["name"] for f in checks["command"]["fields"]] == ["command"]
    assert [f["name"] for f in checks["item"]["fields"]] == ["item_list", "item", "item_status"]
    assert checks["prose"]["fields"] == checks["owner"]["fields"] == []
    # un déclencheur servi est accepté tel quel
    made = post(client, f"/projets/{rid}/objectif", {"text": "Suivre les entreprises", "kind": "constant",
                                                     "on": ["item:entreprises"], "only_on_event": True})
    assert made.status_code == 200, made.text
    # qui lit le lecteur sans voir le produit ne reçoit pas un déclencheur qui le nomme, et ne peut rien y changer
    lea = _lea(client, live)
    _share(client, live, rid, lea, "lecture")
    login(client, "lea")
    hers = _get(client, f"/{rid}")["forms"]
    assert not hers["can"] and hers["why"] == reach.NOT_STEERED
    assert not any(t["sort"] == "project" for t in hers["triggers"])
    assert any(t["sort"] == "item" for t in hers["triggers"])


@needs_bwrap
def test_the_last_commit_and_a_pull_request_come_with_their_words(repo):  # noqa: F811
    client, live = repo.client, repo.live
    fiche = _get(client, f"/{repo.pid}")
    commit = fiche["repo"]["commit"]
    assert commit["sha"] == repo.head and commit["short"] == repo.head[:7] and commit["at"] > 0
    assert commit["title"] == "journal : écrire chaque refus" and commit["author_kind"] == "self"
    o = next(x for x in fiche["objectives"] if x["id"] == repo.oid)
    assert o["pull"]["number"] == 12 and o["pull"]["title"]
    assert [t["number"] for t in o["tickets"]] == [repo.ticket]
    assert o["tickets"][0]["step"] in ("pull", "merge")  # ce projet passe par des pull requests
    assert next(p for p in _get(client, "")["projects"] if p["id"] == repo.pid)["card"]["pulls_open"] == 1
    one = _ticket(client, repo.pid, repo.ticket)
    assert one["linked"]["objective"]["id"] == repo.oid and one["linked"]["pull"]["number"] == 12
    assert one["linked"]["pull"]["state"] == "open" and one["linked"]["pull"]["state_label"]
    assert one["journey"]["through_pull"] and one["journey"]["skips"] == []
    assert one["journey"]["current"] in ("pull", "merge")
    # le commit que montre la vue de l'atelier, sur la fiche de qui en dépend
    append(client, live, [BASE_SEEN.draft(project=repo.pid, commit=repo.base)], "projects")
    link = _get(client, f"/{repo.rid}")["links"]["reads"][0]
    assert link["commit"]["sha"] == repo.base and link["commit"]["title"] == "squelette : paquet et premiers tests"
    # qui lit le lecteur sans voir le produit n'en apprend ni le commit, ni le titre
    lea = _lea(client, live)
    _share(client, live, repo.rid, lea, "lecture")
    login(client, "lea")
    assert _get(client, f"/{repo.rid}")["links"]["reads"][0]["commit"] is None


# ── un ticket ──


def test_a_ticket_says_its_journey_in_six_steps_beside_its_fine_stage(world):  # noqa: F811
    client, live, _ = world
    pid, _rid = _chain(client, live)
    numbers = _numbers(client, pid)
    plan = _ticket(client, pid, numbers["Journaliser les connexions refusées"])
    j = plan["journey"]
    assert [s["code"] for s in j["steps"]] == list(tickets.JOURNEY)
    assert [s["label"] for s in j["steps"]] == ["Non lu", "En analyse", "Validation", "Pull request", "Fusion", "Traité"]
    # un projet au flux direct : ce ticket ne passera pas par une pull request, et le dit
    assert [s["state"] for s in j["steps"]] == ["done", "done", "current", "skipped", "skipped", "todo"]
    assert [s["state_label"] for s in j["steps"]][2:4] == ["en cours", "sautée"]
    assert (j["current"], j["current_label"], j["fine"], j["fine_label"]) == (
        "validation", "Validation", "validation", "en attente de validation")
    assert not j["through_pull"] and j["skips"] == ["pull", "merge"] and j["skips_label"] == moi.SKIPS_PULL
    assert (plan["status"], plan["step"], plan["step_label"]) == ("validation", "validation", "Validation")
    asked = _ticket(client, pid, numbers["Quel port par défaut pour RDP ?"])
    assert (asked["status"], asked["journey"]["current"], asked["journey"]["fine_label"]) == (
        "decision", "analysis", tracker.status_words(c.TICKETS, "decision"))
    # la liste dit l'étape de chaque ligne, et la fiche les compte par étape du parcours
    rows = {t["number"]: t for t in _get(client, f"/{pid}/elements", size=50)["items"]}
    assert rows[plan["number"]]["step"] == "validation" and "journey" not in rows[plan["number"]]
    counted = next(x for x in _get(client, f"/{pid}")["lists"] if x["tickets"])["journey"]
    assert [x["code"] for x in counted] == list(tickets.JOURNEY)
    assert sum(x["count"] for x in counted) == len(rows)
    assert next(x for x in counted if x["code"] == "validation")["count"] == 1
    # écarté : il n'est plus sur le parcours
    foot = numbers["Le pied de page est vide"]
    assert post(client, f"/projets/{pid}/ticket/trancher",
                {"item": f"#{foot}", "verdict": "dismiss", "reason": "Hors sujet."}).status_code == 200
    gone = _ticket(client, pid, foot)
    assert (gone["step"], gone["journey"]["current"], gone["journey"]["ended"]) == ("", "", "dismissed")
    assert gone["journey"]["ended_label"] and gone["journey"]["steps"][-1]["state"] == "skipped"
    # une liste de suivi n'a pas de parcours
    assert all(x["journey"] == [] for x in _get(client, f"/{_rid}")["lists"] if not x["tickets"])


def test_a_ticket_tells_when_it_went_through_each_stage_and_by_whom(world):  # noqa: F811
    client, live, _ = world
    pid, _rid = _chain(client, live)
    number = _numbers(client, pid)["Journaliser les connexions refusées"]
    item = {"list": "tickets", "item": f"#{number}"}
    before = _get(client, f"/{pid}/element/historique", **item)
    assert before["item"] == f"#{number}" and not before["cut"]
    assert [(x["was"], x["status"]) for x in before["items"]] == [("", "analysis"), ("analysis", "validation")]
    assert before["items"][0]["author_kind"] == "self" and before["items"][1]["step"] == "validation"
    seq = _ticket(client, pid, number)["plan"]
    assert post(client, f"/projets/{pid}/ticket/trancher",
                {**item, "verdict": "validate", "plan": seq}).status_code == 200
    after = _get(client, f"/{pid}/element/historique", **item)["items"]
    assert (after[-1]["was"], after[-1]["status"], after[-1]["status_label"]) == (
        "validation", "working", tracker.status_words(c.TICKETS, "working"))
    assert (after[-1]["author_kind"], after[-1]["author"]) == ("you", "toi")
    assert [x["at"] for x in after] == sorted(x["at"] for x in after) and after[-1]["step"] == "treated"
    assert client.get(f"{P}/{pid}/element/historique", params={"list": "inconnue", "item": "x"}).status_code == 404
    # qui ne fait que lire lit l'histoire, et le nom de qui a validé (il s'occupe d'elle)
    lea = _lea(client, live)
    _share(client, live, pid, lea, "lecture")
    login(client, "lea")
    hers = _get(client, f"/{pid}/element/historique", **item)["items"]
    assert hers[-1]["author_kind"] == "person" and hers[-1]["author"] not in ("", "toi")
    # une demande venue d'un autre projet, pas encore acceptée : ses étapes se disent, aucun nom
    asked = next(t for t in _get(client, f"/{pid}/elements", size=50)["items"] if t["veiled"])
    veiled = _get(client, f"/{pid}/element/historique", list="tickets", item=asked["handle"])["items"]
    assert [x["status"] for x in veiled] == ["proposed"] and veiled[0]["author"] == reach.PROJECT_WORDS
    # qui ne fait que voir, qui ne voit pas
    login(client, "adrien")
    _share(client, live, pid, lea, STEER_NO)
    login(client, "lea")
    assert client.get(f"{P}/{pid}/element/historique", params=item).status_code == 403
    login(client, "adrien")
    _close(client, live, pid)
    login(client, "lea")
    assert client.get(f"{P}/{pid}/element/historique", params=item).status_code == 404


def test_the_feed_filters_by_ticket_and_counts_its_totals(world):  # noqa: F811
    client, live, _ = world
    pid, _rid = _chain(client, live)
    number = _numbers(client, pid)["Journaliser les connexions refusées"]
    seq = _ticket(client, pid, number)["plan"]
    assert post(client, f"/projets/{pid}/ticket/trancher",
                {"item": f"#{number}", "verdict": "validate", "plan": seq}).status_code == 200
    everything = _get(client, f"/{pid}/activite", size=100)["items"]
    only = _get(client, f"/{pid}/activite", ticket=number, size=100)["items"]
    assert only and len(only) < len(everything)
    born = next(o["id"] for o in _get(client, f"/{pid}")["objectives"] if o["ticket"] == number)
    assert all(x["ticket"] == number or x["objective"] == born for x in only)
    totals = _get(client, f"/{pid}/activite/totaux")
    assert totals["total"] == len(everything) == sum(totals["totals"].values()) and not totals["cut"]
    assert {k["code"]: k["count"] for k in totals["kinds"]} == totals["totals"]
    assert totals["notes"] == 0 and not totals["notes_cut"] and totals["runs"] == _project(live, pid).runs
    assert _get(client, f"/{pid}/activite/totaux", ticket=number)["total"] == len(only)
    carnet = _get(client, f"/{pid}/carnet")
    assert carnet["total"] == 0 == len(carnet["items"]) and not carnet["total_cut"]
    p = _project(live, pid)
    append(client, live, [NOTED.draft(
        project=pid, text=Content.of("Le port 3389 est le standard.", level=1), objective=born, owner=p.owner,
        about=p.about, read_about=p.read_about)], "projects")
    assert _get(client, f"/{pid}/carnet")["total"] == 1 == _get(client, f"/{pid}/carnet", objective=born)["total"]
    assert _get(client, f"/{pid}/carnet", objective=born + 50)["total"] == 0
    assert _get(client, f"/{pid}/activite/totaux", ticket=number)["notes"] == 1
    # qui ne fait que voir n'en lit rien
    lea = _lea(client, live)
    _share(client, live, pid, lea, STEER_NO)
    login(client, "lea")
    assert client.get(f"{P}/{pid}/activite/totaux").status_code == 403


# ── un accord ──


def test_an_accord_says_what_it_concerns_and_where_it_goes(world):  # noqa: F811
    client, live, _ = world
    pid, _rid = _chain(client, live)
    lea = _lea(client, live)
    _share(client, live, pid, lea, "accord")
    _ask_pause(client, live, pid, lea)
    card = _get(client, "/accords")["items"][0]
    assert card["concerns"] == {"objective": 0, "ticket": None, "issue": 0, "pull": 0}
    assert (card["where"], card["where_url"]) == (moi.WHERE_PROJECT, "")
    assert card["asked_by_kind"] == "person" and card["asked_by"] not in ("", "toi")  # Léa, que sa voix lui nomme
    # qui ne peut pas le donner n'en lit rien
    login(client, "lea")
    assert _get(client, "/accords") == {"items": []}


# ── les dépendances ──


def test_a_link_keeps_since_when_and_the_word_of_its_owner(world):  # noqa: F811
    client, live, _ = world
    pid, rid = _chain(client, live)
    other = _create(client, live.kernel, "Journal de bord", "Tenir le journal")
    path = f"/projets/{rid}/liens"
    first = _get(client, f"/{rid}")["links"]["reads"][0]
    assert first["since"] > 0 and first["why"] == ""
    # le mot se dit en posant le lien, ou plus tard sur un lien posé
    posed = post(client, path, {"add": [other], "why": "Pour citer   ses entrées."})
    assert posed.status_code == 200, posed.text
    reads = {x["project"]: x for x in _get(client, f"/{rid}")["links"]["reads"]}
    assert reads[other]["why"] == "Pour citer ses entrées." and reads[other]["since"] >= reads[pid]["since"]
    assert post(client, path, {"why": "Pour citer ce que l'outil sait faire.", "why_for": pid}).status_code == 200
    again = {x["project"]: x for x in _get(client, f"/{rid}")["links"]["reads"]}
    assert again[pid]["why"] == "Pour citer ce que l'outil sait faire." and again[pid]["since"] == first["since"]
    assert again[other]["why"] == "Pour citer ses entrées."  # le mot d'un autre lien ne bouge pas
    # un texte gardé : au niveau de ce qu'écrivent les deux projets, avec leurs sujets — l'oubli l'atteint
    said = journal(live, LINKS_SET)[-1].data
    r, p = _project(live, rid), _project(live, pid)
    assert said.why.level >= 1 and said.why_for == pid and said.owner == r.owner
    assert set(said.read_about) >= {x for x in (p.owner, *p.about) if x}
    # du côté de qui est lu : depuis quand, et le mot — pour qui lit aussi le détail du lecteur
    reader = _get(client, f"/{pid}")["links"]["readers"][0]
    assert reader["project"] == rid and reader["since"] == first["since"]
    assert reader["why"] == "Pour citer ce que l'outil sait faire."
    # ce qui ne se dit pas : un mot sans projet, sur un projet qu'il ne lit pas, trop long
    assert post(client, path, {"why": "Sans projet."}).status_code == 400
    assert post(client, path, {"why": "Pas lu.", "why_for": 999}).json()["fields"] == {"why_for": "projet non lu"}
    assert post(client, path, {"why": "x" * 301, "why_for": pid}).status_code == 400
    # un lien retiré perd sa date et son mot ; reposé, il date de maintenant
    assert post(client, path, {"remove": [other]}).status_code == 200
    assert post(client, path, {"add": [other]}).status_code == 200
    back = next(x for x in _get(client, f"/{rid}")["links"]["reads"] if x["project"] == other)
    assert back["why"] == "" and back["since"] >= reads[other]["since"]
    # qui lit le produit sans lire le lecteur : qu'on le lit se dit, pas pourquoi ; et le mot n'est pas à elle
    lea = _lea(client, live)
    _share(client, live, pid, lea, "lecture")
    login(client, "lea")
    hidden = _get(client, f"/{pid}")["links"]["readers"][0]
    assert (hidden["project"], hidden["why"]) == (None, "") and hidden["since"] == first["since"]
    assert post(client, f"/projets/{pid}/liens", {"why": "À moi.", "why_for": rid}).status_code == 403


def test_demands_are_read_both_ways_and_she_may_ask_the_project_hers_depends_on(world):  # noqa: F811
    client, live, _ = world
    pid, rid = _chain(client, live)
    # reçues : la demande du lecteur, chez le produit — son titre à qui peut la trancher
    links = _get(client, f"/{pid}")["links"]
    got = links["received"]
    assert [(x["direction"], x["from"], x["project"], x["title"], x["status"], x["step"]) for x in got] == [
        ("received", "project", rid, "Exporter la liste des hôtes en CSV", "proposed", "unread")]
    assert got[0]["number"] and got[0]["step_label"] == "Non lu" and links["readers"][0]["asks"] == got
    # « lui demander quelque chose » : un ticket chez le projet dont le sien dépend, avec ses droits sur lui
    link = _get(client, f"/{rid}")["links"]["reads"][0]
    assert link["ask_here"] == {"can": True, "why": "", "born": "open", "project": pid, "route": "ticket"}
    opened = post(client, f"/projets/{pid}/ticket", {"title": "Une capture du scan pour la page d'accueil"})
    assert opened.status_code == 200, opened.text
    mine = {x["number"]: x for x in _get(client, f"/{rid}")["links"]["reads"][0]["asks"]}
    asked = mine[opened.json()["number"]]
    assert (asked["direction"], asked["from"], asked["title"], asked["step"], asked["project"]) == (
        "sent", "you", "Une capture du scan pour la page d'accueil", "unread", pid)
    assert mine[got[0]["number"]]["from"] == "project"  # la demande du projet, à côté de la sienne
    # qui pilote le produit sur accord : sa demande y naît proposée ; en lecture seule : elle ne peut pas
    lea = _lea(client, live)
    _share(client, live, rid, lea, "lecture")
    _share(client, live, pid, lea, "accord")
    login(client, "lea")
    hers = _get(client, f"/{rid}")["links"]["reads"][0]
    assert (hers["ask_here"]["can"], hers["ask_here"]["born"]) == (True, "proposed")
    # la demande du projet se compte ; son titre reste à qui peut la trancher, tant qu'elle est proposée
    assert [(x["from"], x["title"], x["veiled"]) for x in hers["asks"]] == [("project", "", True)]
    login(client, "adrien")
    _share(client, live, pid, lea, "lecture")
    login(client, "lea")
    assert _get(client, f"/{rid}")["links"]["reads"][0]["ask_here"] == {
        "can": False, "why": reach.NOT_STEERED, "born": "", "project": pid, "route": ""}
    # qui lit le produit sans le trancher : la demande reçue se compte, le ticket proposé par un autre projet ne
    # dit pas son titre
    seen = next(x for x in _get(client, f"/{pid}")["links"]["received"] if x["status"] == "proposed")
    assert (seen["project"], seen["title"], seen["veiled"]) == (rid, "", True)
    # qui ne voit pas le produit : rien de lui, ni demande ni droit
    login(client, "adrien")
    _close(client, live, pid)
    login(client, "lea")
    blind = _get(client, f"/{rid}")["links"]["reads"][0]
    assert blind["ask_here"] == {"can": False, "why": "", "born": "", "project": None, "route": ""}
    assert blind["asks"] == [] and blind["project"] is None


# ── les listes de suivi ──


def test_a_follow_up_list_takes_a_new_item_and_changes_whose_it_is(world):  # noqa: F811
    client, live, _ = world
    pid, rid = _chain(client, live)
    lists = {x["name"]: x for x in _get(client, f"/{rid}")["lists"]}
    assert lists["entreprises"]["can"] == {"add": True, "assign": True, "why": ""}
    assert [a["code"] for a in lists["entreprises"]["actors"]] == ["self", "owner"]
    assert lists["tickets"]["can"] == {"add": False, "assign": False, "why": ""} and lists["tickets"]["actors"] == []
    add = f"/projets/{rid}/element/ajouter"
    made = post(client, add, {"list": "entreprises", "title": "Garage Martin", "key": "martin", "actor": "self"})
    assert made.status_code == 200, made.text
    assert (made.json()["list"], made.json()["key"]) == ("entreprises", "martin")
    one = _get(client, f"/{rid}/element", list="entreprises", item="martin")
    assert (one["title"], one["status"], one["actor"], one["can"]["assign"]) == (
        "Garage Martin", "à contacter", "self", True)
    assert post(client, add, {"list": "entreprises", "title": "Garage Martin", "key": "martin"}).status_code == 400
    assert post(client, add, {"list": "tickets", "title": "Un ticket"}).status_code == 400  # il s'ouvre ailleurs
    assert post(client, add, {"list": "inconnue", "title": "Rien"}).status_code == 404
    give = f"/projets/{rid}/element/confier"
    martin = {"list": "entreprises", "item": "martin"}
    assert post(client, give, {**martin, "actor": "owner"}).status_code == 200
    assert _get(client, f"/{rid}/element", **martin)["actor"] == "owner"
    assert post(client, give, {**martin, "actor": "owner"}).status_code == 409  # il l'est déjà
    assert post(client, give, {**martin, "actor": "quelqu'un"}).status_code in (400, 409)
    number = _numbers(client, pid)["Le pied de page est vide"]
    assert post(client, f"/projets/{pid}/element/confier",
                {"list": "tickets", "item": f"#{number}", "actor": "owner"}).status_code == 409
    # sur accord : ni ajouter, ni confier, et la fiche dit pourquoi ; en lecture seule non plus
    lea = _lea(client, live)
    for steer, why in (("accord", reach.NEEDS_EDIT), ("lecture", reach.NOT_STEERED)):
        login(client, "adrien")
        _share(client, live, rid, lea, steer)
        login(client, "lea")
        can = next(x for x in _get(client, f"/{rid}")["lists"] if x["name"] == "entreprises")["can"]
        assert can == {"add": False, "assign": False, "why": why}
        refused = post(client, add, {"list": "entreprises", "title": "Atelier Brique"})
        assert refused.status_code == 403 and refused.json()["error"] == why
        assert post(client, give, {**martin, "actor": "self"}).status_code == 403
        assert not _get(client, f"/{rid}/element", **martin)["can"]["assign"]
    assert _get(client, f"/{rid}/element", **martin)["actor"] == "owner"
