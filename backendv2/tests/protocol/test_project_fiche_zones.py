"""Les onglets en liste et détail de la fiche d'un projet (ADR 0297) — Objectifs (sa liste, son diagramme), Tickets,
Listes —, à travers le vrai serveur, sur la chaîne d'exemple de l'aperçu (``app/preview/projects.py``).

- Objectifs : des lignes serrées par groupes, le filtre en pastilles, et un objectif choisi dans les trois zones —
  ses jalons avec leurs gestes (valider ou refuser un point d'arrêt, modifier, retirer, ajouter), ses comptes rendus,
  son panneau ; une mission ; « Ajouter un objectif » dans le contenu ; son plan quand il n'attend rien ;
- son diagramme, dessiné côté serveur en SVG, dans ses deux modes ; choisir un jalon dit ce qu'il est ;
- Tickets : la recherche et les filtres ; un ticket choisi en volets — celui qui attend s'ouvre —, son parcours en
  six étapes, ce qui lui est lié, ses gestes (la validation nomme le plan lu) ; un texte venu d'ailleurs en texte
  brut ;
- Listes : par statut et en tableau ; un élément choisi dans le panneau, avec son fil et son historique ;
- un formulaire repris du dessin s'envoie tel quel, et ramène à la section qu'il a changée ;
- aucun style en ligne (la CSP).
"""

from __future__ import annotations

import re

from mika.contracts import projects as c
from mika.faculties.projects.faculty import milestone_at, objective_at
from mika.kernel.events import Content
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_fiches import form_of
from tests.protocol.test_project_fiche_tabs import FICHE, _actions, _chain, _tab
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée


def _zone(page: str, start: str, end: str = "</aside>") -> str:
    return page.split(start, 1)[1].split(end, 1)[0]


def _post(client, form: dict[str, list[str]], action: str, **values: str):
    """Un formulaire de la page, envoyé tel quel (ses champs cachés), avec ce qu'on y saisit."""
    data = {**form, "_champs": [*form.get("_champs", []), *values], **{k: [v] for k, v in values.items()}}
    return client.post(f"/admin/action/{action}", data=data, follow_redirects=False)


def _project(live, pid: int):
    return live.kernel.mind.frame().state("projects").projects[pid]


def test_objectives_read_in_dense_lines_and_one_opens_in_three_zones(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    append(client, kernel, [c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.CONTINUE, commit="a" * 40,
                                                 summary=Content.of("Le squelette est posé.", level=0))], "projects")
    page = _tab(client, pid, "objectifs")
    assert 'data-tab="project/objectifs"' in page and 'class="pj-split pj-obj"' in page
    assert "style=" not in page.split('class="pj-split', 1)[1]
    assert page.index('class="pj-list"') < page.index('class="pj-main"') < page.index('class="pj-side"')
    listed = _zone(page, '<aside class="pj-list"')
    # la bascule, « Ajouter un objectif », le filtre en pastilles (celui de sa vue), puis ses lignes par groupes
    assert ">Liste</a>" in listed and "vue=diagramme" in listed and "ajouter=1" in listed
    pills = re.findall(r'<a href="[^"]*?(?:objectifs=(\w+))?"(?: aria-current="true")?>(\w+)<span class="pj-cnt">(\d+)',
                       _zone(listed, 'class="pj-filters"', "</nav>"))
    assert pills == [("", "Ouverts", "3"), (c.DONE, "Faits", "0"), (c.DROPPED, "Retirés", "0"), ("tous", "Tous", "3")]
    assert re.findall(r'<div class="pj-group">([^<]+)', listed) == ["En cours", "Missions", "Son plan"]
    rows = re.findall(r'<a class="pj-orow([^"]*)" href="([^"]+)"( aria-current="true")?.*?</a>', listed, re.S)
    assert [cls.strip() for cls, _, _ in rows] == ["atoi", "", "mission", "plan"]  # son point d'arrêt attend
    assert [bool(on) for _, _, on in rows] == [True, False, False, False]  # le premier s'ouvre
    first = _zone(listed, '<a class="pj-orow atoi"', "</a>")
    assert "Créer un module RDP" in first and '<span class="num">0/2</span>' in first
    assert re.findall(r"<i(?: class=\"(\w+)\")?></i>", first.split('class="pj-seg"', 1)[1]) == ["", "you"]
    assert "toutes les 24 h" in _zone(listed, '<a class="pj-orow mission"', "</a>")
    # l'objectif choisi : son en-tête et ses gestes, ses volets, son panneau
    head = _zone(page, '<header class="pj-dh"', "</header>")
    assert "Objectif n° 1" in head and "Créer un module RDP" in head and "passage" in head
    assert "Lancer maintenant" in head and 'href="#obj-modifier"' in head
    assert re.findall(r'<a href="#(obj-\w+)"', _zone(page, 'class="pj-volets"', "</nav>")) == ["obj-jalons", "obj-rendus"]
    marks = _zone(page, 'id="obj-jalons"', "</section>")
    assert "Le module se connecte à un hôte de test" in marks and "Vérifié par sa parole" in marks
    stop = marks.split("Tu as relu l'écran de connexion", 1)[1].split("</li>", 1)[0]
    assert "prêt · à valider" in stop and "Vérifié par un point d'arrêt — L'écran est dans « ui/connexion.py »" in stop
    assert "Valider le jalon" in stop and "Refuser" in stop and 'name="verdict" value="validate"' in stop
    assert 'name="verdict" value="refuse"' in stop and 'name="reason"' in stop  # refuser demande sa raison
    assert 'title="Modifier le jalon"' in stop and "Retirer le jalon" in stop and 'href="#obj-jalon"' in marks
    assert "Le squelette est posé." in _zone(page, 'id="obj-rendus"', "</section>")
    side = _zone(page, '<aside class="pj-side"')
    assert [h.strip() for h in re.findall(r"<h3>([^<]+)</h3>", side)] == ["Fini quand", "Où il en est", "Gérer"]
    assert "0 / 2 jalons" in side and all(x in side for x in ("Le dire terminé", "Le dire bloqué", "Retirer l'objectif"))
    assert {"projects.lancer_objectif", "projects.objectif_modifier", "projects.objectif_statut",
            "projects.jalon_ajouter", "projects.jalon_trancher", "projects.jalon_retirer"} <= _actions(page)
    # « Modifier le jalon » repart de ce qu'il est ; « Modifier l'objectif » ne montre que ce qui vaut pour sa sorte
    editing = _tab(client, pid, "objectifs", "&objectif=1&jalon=1")
    form = _zone(editing, 'id="obj-jalon-modifier"', "</section>")
    assert "Le module se connecte à un hôte de test</textarea>" in form and '<option value="prose" selected>' in form
    assert 'data-only="check=command"' in form and 'action="/admin/action/projects.jalon_modifier"' in form
    edit = _zone(page, 'id="obj-modifier"', "</section>")
    assert 'name="done_when"' in edit and 'name="cadence_hours"' not in edit and 'name="kind" value="once"' in edit
    # un formulaire repris du dessin s'envoie tel quel, et ramène à ses jalons
    sent = _post(client, form_of(page, "projects.jalon_trancher", having="validate"), "projects.jalon_trancher")
    assert sent.status_code == 303 and sent.headers["location"].endswith("#obj-jalons"), sent.text[:300]
    assert "flash=" in sent.headers["location"].split("#", 1)[0]
    assert milestone_at(objective_at(_project(live, pid), 1), 2).status == c.REACHED
    after = _tab(client, pid, "objectifs", "&objectif=1")
    assert "projects.jalon_trancher" not in _actions(after) and '<span class="num">1/2</span>' in after
    # une mission : ce que chaque passage fait, son rythme ; « Ajouter un objectif » dans le contenu ; son plan
    mission = _tab(client, pid, "objectifs", "&objectif=3")
    assert 'class="pj-split pj-obj lire"' in mission and "Garder les tests verts" in _zone(mission, 'class="pj-dh"', "</header>")
    assert "À chaque passage" in mission and "Son rythme" in mission and "Retirer la mission" in mission
    adding = _tab(client, pid, "objectifs", "&ajouter=1")
    add = _zone(adding, 'action="/admin/action/projects.objectif_ajouter"', "</form>")
    assert 'name="text"' in add and f'data-only="kind={c.CONSTANT}"' in add and f'data-only="kind={c.ONCE}"' in add
    assert "Déclenché par" in add and "Fini quand" in add
    plan = _tab(client, pid, "objectifs", "&plan=1")
    assert "La demande et son plan" in plan and "projects.plan_reviser" in _actions(plan)
    # le projet lecteur : son plan attend — il se tranche sur la Vue d'ensemble, l'onglet y mène
    waiting = _tab(client, rid, "objectifs", "&plan=1")
    assert "il se lit et se tranche sur la Vue d'ensemble" in waiting and "projects.plan_reviser" not in _actions(waiting)
    # son filtre : un autre groupe
    two = _tab(client, pid, "objectifs", "&objectif=2")
    gone = _post(client, form_of(two, "projects.objectif_statut", having=c.DROPPED), "projects.objectif_statut")
    assert gone.status_code == 303, gone.text[:300]
    dropped = _tab(client, pid, "objectifs", f"&objectifs={c.DROPPED}")
    assert re.findall(r'<div class="pj-group">([^<]+)', dropped)[0] == "Retirés" and "Rouvrir l'objectif" in dropped


def test_the_diagram_is_drawn_on_the_server_in_both_modes(world):  # noqa: F811
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    page = _tab(client, pid, "objectifs", "&vue=diagramme")
    assert 'class="pj-gantt avancement"' in page and "style=" not in page.split('class="pj-split', 1)[1]
    names = re.findall(r'<a class="pj-g-nom (\w+)" href="([^"]+)"( aria-current="true")?', page)
    assert [sort for sort, _, _ in names] == ["goal", "mark", "mark", "goal", "mission"]  # ses jalons en retrait
    assert [bool(on) for _, _, on in names] == [True, False, False, False, False]  # le premier en cours est choisi
    assert "objectif=1&jalon=2" in names[2][1] and "vue=diagramme" in names[2][1]
    # « Avancement » : la part faite en SVG (le point d'arrêt dit prêt : entier, hachuré), puis un mot
    bars = re.findall(r'<svg class="pj-g-part[^"]*" viewBox="0 0 1000 10".*?</svg>', page, re.S)
    assert len(bars) == 4 and '<rect class="you" x="0" y="0" width="1000"' in bars[2] and "url(#pj-hache-av)" in bars[2]
    assert '<rect class="you" x="0" y="0" width="500"' in bars[0]  # un jalon sur deux, à valider
    assert "attend sa validation" in page and "0 / 2 jalons atteints" in page
    side = _zone(page, '<aside class="pj-side"')
    assert "Créer un module RDP" in side and "L'ouvrir" in side and "Ajouter un jalon" in side and "Fini quand" in side
    # « Dans le temps » : un seul dessin, son axe, le trait d'aujourd'hui, ce qui n'a pas commencé en fantôme
    timed = _tab(client, pid, "objectifs", "&vue=diagramme&mode=temps&echelle=jours")
    assert 'class="pj-gantt temps"' in timed and "style=" not in timed.split('class="pj-split', 1)[1]
    svg = _zone(timed, '<svg class="pj-g-svg"', "</svg>")
    assert '<line class="auj"' in svg and 'class="b obj fantome"' in svg and "à suivre · sans date" in svg
    assert svg.count('<rect class="rang') == 5 and 'class="auj-n"' in svg
    assert re.search(r'<nav class="seg" aria-label="L\'échelle">.*?aria-current="true">Jours</a>', timed, re.S)
    weeks = _tab(client, pid, "objectifs", "&vue=diagramme&mode=temps&echelle=semaines")
    assert 'class="sem"' in weeks and "sem. du" in weeks
    # choisir un jalon dit ce qu'il est, avec ses gestes
    mark = _tab(client, pid, "objectifs", "&vue=diagramme&objectif=1&jalon=2")
    panel = _zone(mark, '<aside class="pj-side"')
    assert "Tu as relu l'écran de connexion" in panel and "jalon de l'objectif n° 1" in panel
    assert "Comment on le vérifie" in panel and "Dans le temps" in panel and "pas encore : sans date" in panel
    assert "Valider le jalon" in panel and "projects.jalon_trancher" in _actions(panel)
    assert "Modifier le jalon" in panel and "jalon=2#obj-jalon-modifier" in panel


def test_a_ticket_opens_in_tabs_with_its_journey_and_its_gestures(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    page = _tab(client, pid, "tickets")
    assert 'class="pj-split pj-tic"' in page and "style=" not in page.split('class="pj-split', 1)[1]
    listed = _zone(page, '<aside class="pj-list"')
    assert 'name="q"' in listed and 'name="onglet" value="tickets"' in listed and "nouveau=1" in listed
    pills = re.findall(r'(?: aria-current="true")?>([\w ]+)<span class="pj-cnt">(\d+)',
                       _zone(listed, 'class="pj-filters"', "</nav>"))
    assert [(text, n) for text, n in pills] == [("En attente", "3"), ("Ouverts", "4"), ("Tous", "4")]
    assert len(re.findall(r'<a class="pj-row pj-trow', listed)) == 4 and "les régler dans Administration" in listed
    asked = _tab(client, pid, "tickets", "&filtre=attente")
    assert len(re.findall(r'<a class="pj-row pj-trow atoi"', asked)) == 3 and "Le pied de page est vide" not in \
        _zone(asked, '<aside class="pj-list"')
    found = _zone(_tab(client, pid, "tickets", "&q=RDP&filtre=tous"), '<aside class="pj-list"')
    assert "Quel port par défaut pour RDP" in found and len(re.findall(r'<a class="pj-row pj-trow', found)) == 1
    # son plan attend : il s'ouvre le premier ; sa validation nomme le plan lu
    opened = _tab(client, pid, "tickets", "&element=%234")
    assert 'class="pj-split pj-tic lire"' in opened
    head = _zone(opened, '<header class="pj-dh"', "</header>")
    assert "#4" in head and "Journaliser les connexions refusées" in head and "Valider le plan" in head
    assert all(x in head for x in ("Refuser", "Écarter", "Fermer", 'href="#t-modifier"'))
    assert re.findall(r'<a href="#(t-\w+)"', _zone(opened, 'class="pj-volets"', "</nav>")) == [
        "t-description", "t-plan", "t-fil", "t-historique"]
    panes = re.findall(r'<section id="(t-[\w-]+)"', opened)
    assert panes[0] == "t-plan" and set(panes) == {"t-description", "t-plan", "t-fil", "t-historique", "t-modifier"}
    plan = _zone(opened, 'id="t-plan"', "</section>")
    number = next(x for x in _project(live, pid).board.items if x.number == 4).plan_seq
    assert f"n° {number}" in plan and "un journal tournant de 7 jours" in plan and 'class="pj-plancard you"' in plan
    validate = form_of(opened, "projects.ticket_trancher", having="validate")
    assert validate["plan"] == [str(number)] and validate["item"] == ["#4"] and validate["verdict"] == ["validate"]
    side = _zone(opened, '<aside class="pj-side"')
    assert [h.strip() for h in re.findall(r"<h3>([^<]+)</h3>", side)] == ["Son parcours", "En bref", "Ce qui est lié"]
    steps = re.findall(r'<li class="([^"]*)"(?: aria-current="step")?><i>.*?</i><span>([^<]+)</span>', side, re.S)
    assert [label for _, label in steps] == ["Non lu", "En analyse", "Validation", "Pull request", "Fusion", "Traité"]
    assert [cls for cls, _ in steps] == ["fait", "fait", "ici you", "saute", "saute", ""]
    assert "la main est au propriétaire" in side and "il saute ces deux étapes" in side
    assert "Ouvert par" in side and "Mis à jour" in side
    assert {"projects.ticket_trancher", "projects.ticket_modifier", "projects.element_noter"} <= _actions(opened)
    # valider part tel quel : il crée l'objectif qui le tient, que « Ce qui est lié » montre
    sent = _post(client, validate, "projects.ticket_trancher")
    assert sent.status_code == 303, sent.text[:300]
    linked = _zone(_tab(client, pid, "tickets", "&element=%234"), '<aside class="pj-side"')
    assert "objectif n° " in linked and "onglet=objectifs&objectif=" in linked
    # sa question : son fil s'ouvre, et la note s'appelle « Répondre »
    question = _tab(client, pid, "tickets", "&element=%233")
    assert re.findall(r'<section id="(t-[\w-]+)"', question)[0] == "t-fil"
    thread = _zone(question, 'id="t-fil"', "</section>")
    assert "Je garde 3389 par défaut" in thread and "sa question" in thread and ">Répondre</button>" in thread
    answer = _post(client, form_of(question, "projects.element_noter"), "projects.element_noter", text="3389.")
    assert answer.status_code == 303 and answer.headers["location"].endswith("#t-fil")
    assert "3389." in _zone(_tab(client, pid, "tickets", "&element=%233"), 'id="t-fil"', "</section>")
    # une demande d'un autre projet : venue d'ailleurs, en texte brut, à accepter ou à écarter
    outside = _tab(client, pid, "tickets", "&element=%232")
    assert "venu d'ailleurs" in _zone(outside, '<header class="pj-dh"', "</header>")
    assert "Accepter le ticket" in outside and f"Demande du projet n° {rid}" in outside
    body = _zone(outside, 'id="t-description"', "</section>")
    assert '<figure class="pj-out">' in body and "<blockquote>Le site doit montrer un exemple d'export." in body
    assert "Ticket proposé depuis ailleurs" in _zone(outside, 'id="t-fil"', "</section>")
    # « Nouveau ticket » dans le contenu ; modifier repart de ce qu'il est
    new = _tab(client, pid, "tickets", "&nouveau=1")
    assert "projects.ticket_ouvrir" in _actions(new) and 'name="title"' in new and 'name="priority"' in new
    edit = _zone(_tab(client, pid, "tickets", "&element=%231"), 'id="t-modifier"', "</section>")
    assert 'value="Le pied de page est vide"' in edit and '<option value="high" selected>' in edit
    assert "Aucun ticket « #99 »" in _tab(client, pid, "tickets", "&element=%2399")


def test_lists_read_by_status_or_in_a_table_and_an_item_opens_in_the_panel(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    page = _tab(client, rid, "suivi")
    assert 'data-tab="project/suivi"' in page and "style=" not in page.split('class="pj-split', 1)[1]
    assert "Entreprises à contacter" in page and "5 en cours sur 5" in page and 'class="pj-side"' not in page
    columns = re.findall(r'<section class="pj-col" aria-label="([^"]+)">.*?<span class="pj-cnt">(\d+)</span>', page, re.S)
    assert columns == [("à contacter", "5"), ("contactée", "0"), ("a répondu", "0"), ("sans suite", "0")]
    assert len(re.findall(r'<a class="pj-kcard atoi"', page)) == 5 and "Acme Réseaux" in page  # à la charge du propriétaire
    table = _tab(client, rid, "suivi", "&vue=tableau")
    assert 'class="pj-table"' in table and 'class="pj-board"' not in table and table.count("<tr") == 6
    # un élément choisi : le panneau — son statut et à qui il est s'y changent, son fil, son historique
    one = _tab(client, rid, "suivi", "&liste=entreprises&element=acme")
    side = _zone(one, '<aside class="pj-side"')
    assert "Acme Réseaux" in side and "À la charge de" in side and "Son fil" in side and "Son historique" in side
    assert {"projects.element_statut", "projects.element_confier", "projects.element_noter"} <= _actions(side)
    status = _zone(side, 'action="/admin/action/projects.element_statut"', "</form>")
    assert 'name="list_name" value="entreprises"' in status and 'name="item" value="acme"' in status
    assert re.findall(r'<option value="([^"]+)"', status) == ["à contacter", "contactée", "a répondu", "sans suite"]
    moved = _post(client, form_of(one, "projects.element_statut"), "projects.element_statut", status="contactée")
    assert moved.status_code == 303, moved.text[:300]
    after = _tab(client, rid, "suivi", "&liste=entreprises&element=acme")
    assert "à contacter → contactée" in _zone(after, 'id="e-historique"', "</div>") or "contactée" in _zone(
        after, 'id="e-historique"', "</div>")
    assert re.findall(r'<section class="pj-col" aria-label="contactée">.*?<span class="pj-cnt">(\d+)</span>', after, re.S) == ["1"]
    # « Ajouter » et « Régler » ouvrent leur formulaire dans le panneau ; régler repart de ce qu'elle est
    add = _zone(_tab(client, rid, "suivi", "&ajouter=1"), '<aside class="pj-side"')
    assert "projects.element_ajouter" in _actions(add) and 'name="list_name" value="entreprises"' in add
    setting = _zone(_tab(client, rid, "suivi", "&regler=1"), '<aside class="pj-side"')
    assert "projects.liste_regler" in _actions(setting) and "à contacter\ncontactée" in setting
    # un projet sans liste : de quoi en créer une
    empty = _tab(client, pid, "suivi")
    assert "Pas encore de liste" in empty and "projects.liste_regler" in _actions(empty)
    assert client.get(FICHE.format(rid) + "?onglet=suivi&element=inconnu").status_code == 200


def test_the_views_of_the_faculty_keep_their_blocks(world):  # noqa: F811
    """Le repli (et la console lue en MCP) : la vue de la faculté reste la source — demandée en tableau, la page rend
    ses blocs, pas le dessin ; son filtre, que les pastilles de la liste remplacent sur le dessin, y est toujours."""
    client, live, _ = world
    _, pid, rid = _chain(client, live)
    for tab, pidx, said in (("objectifs", pid, "Ses objectifs"), ("tickets", pid, "Le pied de page est vide"),
                            ("suivi", rid, "Acme Réseaux")):
        page = client.get(FICHE.format(pidx) + f"?onglet={tab}&vue_pg1=table")
        assert page.status_code == 200 and "Cette vue a échoué" not in page.text, tab
        assert 'class="pj-split' not in page.text and said in page.text, tab
    drawn_ = _tab(client, pid, "objectifs")
    assert 'class="tabs-tail"' in drawn_ and "objectifs=tous" in drawn_.split('class="tabs-tail"', 1)[1].split("</nav>", 1)[0]
