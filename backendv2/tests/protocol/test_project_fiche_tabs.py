"""La fiche d'un projet rangée par ce qu'on y fait, et la page d'ensemble (ADR 0281), à travers le vrai serveur, sur
la chaîne d'exemple de l'aperçu (``app/preview/projects.py`` : un produit, un projet qui le lit, des tickets à chaque
étape où la main est au propriétaire, un point d'arrêt dit prêt, une liste à sa charge, un plan sans réponse).

- sa barre : Où il en est, Tickets, Suivi, Liens, Dépôt, Exécutions, Cadre ; le reste sous « Plus » ; les adresses
  d'avant (ses objectifs, ses accès) mènent à leur section ;
- « Où il en est » pose ce qui t'attend en tête, chaque ligne menant là où elle se règle, puis ses missions et ses
  objectifs en une ligne ; « Missions et objectifs » garde chaque objectif et ses boutons ;
- Liens, Dépôt et Cadre montrent ce que leurs lots avaient posé ailleurs ;
- l'inventaire : aucune action de la fiche n'a disparu, et chacune est là où il le dit ;
- la page d'ensemble : « À faire » pour tous les projets, ce qui attend dans chacun, les liens entre projets.
"""

from __future__ import annotations

import html
import re

from mika.app.preview.projects import chain
from mika.contracts import projects as c
from mika.kernel.events import Content
from mika.runtime.operations import perform
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

FICHE = "/admin/fiche/project/{}"


def _chain(client, live) -> tuple[object, int, int]:
    """La chaîne d'exemple : le produit (n° ``pid``) et le projet qui le lit (n° ``rid``)."""
    kernel = _life(client, live)
    pid = _create(client, kernel, "Outils réseau", "Créer un module RDP\nÉcrire sa documentation")
    rid = _create(client, kernel, "Faire connaître Outils réseau", "Écrire la page d'accueil")
    client.portal.call(lambda: chain(kernel, str(pid), str(rid)))
    return kernel, pid, rid


def _tab(client, pid: int, name: str, more: str = "") -> str:
    page = drawn(client, FICHE.format(pid) + f"?onglet={name}{more}")
    assert "Cette vue a échoué" not in page and "Action non déclarée" not in page, name
    return page


def _do(client, kernel, pid: int, action: str, nonce: str, **values: str) -> None:
    posted = {"_champs": list(values), **{k: [v] for k, v in values.items()}}
    got = client.portal.call(lambda: perform(kernel, f"projects.{action}", posted, by="user_1", subject=str(pid),
                                             nonce=nonce))
    assert got.ok, got


def _bar(page: str) -> list[str]:
    """Les onglets de la barre de la fiche, dans l'ordre, sans leurs comptes."""
    nav = re.search(r'<nav class="tabs[^"]*".*?</nav>', page, re.S)
    assert nav, "pas de barre d'onglets"
    return [re.sub(r"\s*\d+$", "", " ".join(re.sub(r"<[^>]+>", " ", a).split()))
            for a in re.findall(r"<a\b.*?</a>", nav.group(0), re.S)]


def _actions(page: str) -> set[str]:
    """Les actions dont la page porte un formulaire."""
    return set(re.findall(r'action="/admin/action/(projects\.[a-z_]+)"', page))


def test_the_fiche_is_arranged_by_what_one_does_there(world):  # noqa: F811
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    page = _tab(client, pid, "apercu")
    bar = _bar(page)
    assert bar[:7] == ["Où il en est", "Tickets", "Suivi", "Dépendances", "Dépôt", "Exécutions", "Cadre"]
    assert all(title in page for title in ("Décisions techniques", "Fichiers", "Carnet"))  # sous « Plus »
    assert "Missions et objectifs" not in bar and "Accès" not in bar  # réunis sous leur onglet
    # la fiche s'ouvre sur « Où il en est »
    assert 'data-tab="project/apercu"' in drawn(client, FICHE.format(pid))
    # les adresses d'avant mènent à leur section
    old = client.get(FICHE.format(pid) + "?onglet=objectifs&objectifs=tous", follow_redirects=False)
    assert old.status_code == 303 and "onglet=apercu" in old.headers["location"]
    assert "objectifs=tous" in old.headers["location"] and old.headers["location"].endswith("#objectifs")
    old = client.get(FICHE.format(pid) + "?onglet=acces", follow_redirects=False)
    assert old.status_code == 303 and old.headers["location"].endswith("onglet=comportement#acces")


def test_where_it_stands_says_first_what_awaits_and_where_to_settle_it(world):  # noqa: F811
    client, live, _ = world
    _, pid, rid = _chain(client, live)
    page = _tab(client, pid, "apercu")
    brief = page.split('id="bref"', 1)[1].split('id="objectifs"', 1)[0]
    waiting = brief.split('class="now-card prj-todo"', 1)[1].split("</section>", 1)[0]
    assert '<span class="person-count now-num">4</span>' in waiting  # quatre choses l'attendent
    # ce qui l'attend, dans l'ordre où s'en occuper : les tickets dont la main est à toi, puis le point d'arrêt
    said = re.findall(r'<p class="prj-todo-text">(.*?)</p>', waiting, re.S)
    assert [s.split(" — ")[0] for s in said] == [
        "#2 Exporter la liste des hôtes en CSV", "#3 Quel port par défaut pour RDP ?",
        "#4 Journaliser les connexions refusées", "Objectif n° 1, jalon n° 2"]
    assert "proposé : à accepter ou à écarter" in said[0] and "elle te pose une question" in said[1]
    assert "son plan attend ta validation" in said[2] and "elle le dit prêt" in said[3]
    # chaque ligne mène là où elle se règle : l'onglet ouvert sur l'objet
    go = dict(re.findall(r'<a class="btn quiet small prj-todo-go" href="([^"]+)"[^>]*>(.*?)</a>', waiting))
    assert {text: href.split("?", 1)[1] for href, text in go.items()} == {
        "Accepter ou écarter": "onglet=tickets&element=%232", "Répondre": "onglet=tickets&element=%233",
        "Valider ou refuser son plan": "onglet=tickets&element=%234", "Valider ou refuser": "onglet=objectifs"}
    for href in go:  # et ce lien ouvre bien l'objet, avec son geste
        assert client.get(href).status_code == 200
    opened = _tab(client, pid, "tickets", "&element=%234")
    assert "Journaliser les connexions refusées" in opened and "projects.ticket_trancher" in _actions(opened)
    # ses missions et ses objectifs en cours, une ligne chacun
    assert "Ses missions" in brief and "Garder les tests verts" in brief and "toutes les 24 h" in brief
    assert "Ses objectifs en cours" in brief and "Créer un module RDP" in brief
    assert "jalons 0/2" in brief and "un point d'arrêt t'attend" in brief
    assert "Ensuite" in brief and "Dernières exécutions" in brief and "Son dépôt" in brief
    # le projet qui le lit : son plan attend, en tête ; sa mission dit ce qui la déclenche ; sa liste est à ta charge
    reader = _tab(client, rid, "apercu")
    assert "Son plan attend une réponse" in reader and "Lire son plan et répondre" in reader
    assert {"projects.plan_valider", "projects.plan_reviser"} <= _actions(reader)
    assert "Garder le site cohérent avec le produit" in reader and "tous les 2 jours" in reader
    assert f"la base du projet n° {pid} qui avance" in reader  # ce qui la déclenche, en plus de sa cadence
    assert "Acme Réseaux (liste « entreprises »)" in reader and "Ouvrir la liste" in reader  # trois, puis le reste
    assert '<span class="person-count now-num">6</span>' in reader  # six attentes, en cinq lignes
    assert reader.count("Son plan attend une réponse") == 1  # dit une fois : ni bandeau ni note en plus
    assert "2 autres éléments" in reader
    # un projet qui avance seul le dit en une ligne, sans carte
    kernel = live.kernel
    alone = _create(client, kernel, "Seul", "Écrire")
    quiet = _tab(client, alone, "apercu")
    assert "Rien ne t'attend ici : il avance seul." in quiet and 'class="now-card prj-todo"' not in quiet


def test_missions_and_objectives_keep_each_objective_and_its_buttons(world):  # noqa: F811
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    page = _tab(client, pid, "objectifs")  # son ancienne adresse : la console y mène
    assert 'data-tab="project/objectifs"' in page
    pane = page.split('id="objectifs"', 1)[1]
    missions, once = pane.split("Ses objectifs <", 1)
    assert "Ses missions" in missions and "Garder les tests verts" in missions and "Créer un module RDP" in once
    assert {"projects.lancer_objectif", "projects.objectif_statut", "projects.objectif_modifier",
            "projects.objectif_ajouter", "projects.jalon_ajouter", "projects.jalon_trancher"} <= _actions(pane)
    assert "Valider ou refuser le point d'arrêt n° 2" in pane and "Tu as relu l'écran de connexion" in pane
    # son filtre : un bouton à choix, appliqué d'un clic
    seg = pane.split('class="seg prj-obj-seg"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'href="([^"]+)"', seg) == [f"?onglet=objectifs&objectifs={v}" for v in
                                                   ("vivants", c.DONE, c.DROPPED, "tous")]
    assert 'aria-current="true">Ouverts et bloqués<' in seg
    assert "aucun objectif ici (filtre)" in _tab(client, pid, "objectifs", f"&objectifs={c.DROPPED}")


def test_links_frame_and_repository_show_what_their_lots_had_put_elsewhere(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    # ── Liens : ce qu'il lit et ce que le lien donne, ce qu'il a demandé ; chez le projet lu, ce qu'on lui a demandé
    links = _tab(client, rid, "liens")
    assert 'data-tab="project/liens"' in links and "Il dépend de" in links and "Outils réseau" in links
    assert "la vue de son atelier" in links and "Ses demandes : envoyées" in links and "Dépendent de lui" in links
    assert "projects.liens" in _actions(links)
    asked = _tab(client, pid, "liens")
    assert "Ses demandes : reçues" in asked and "#2 Exporter la liste des hôtes en CSV" in asked
    assert f"projet n° {rid}" in asked and "Faire connaître Outils réseau" in asked  # qui le lit
    # ── Cadre : ses réglages, ses outils, ses accès, ses tickets — chacun dans son sous-onglet, avec son formulaire
    frame = _tab(client, pid, "comportement")
    assert 'data-tab="project/comportement"' in frame
    assert re.findall(r'<a href="#([a-z-]+)">', frame.split('aria-label="Son cadre"', 1)[1].split("</nav>", 1)[0]) == [
        "cadre-reglages", "cadre-outils", "acces", "cadre-tickets"]
    assert {"projects.modifier", "projects.outils", "projects.acces", "projects.tickets_regler"} <= _actions(frame)
    tickets = frame.split('id="cadre-tickets"', 1)[1]
    assert "validation du plan d'un ticket" in tickets and "toujours par toi" in tickets
    assert "3 fichiers et 40 lignes au plus" in tickets and "sans dépôt distant" in tickets
    assert "Relecture indépendante" in frame.split('id="cadre-reglages"', 1)[1].split('id="cadre-outils"', 1)[0]
    assert 'class="access-form"' in frame.split('id="acces"', 1)[1].split('id="cadre-tickets"', 1)[0]
    # l'onglet Tickets n'a plus ce réglage : il y mène
    listed = _tab(client, pid, "tickets")
    assert "projects.tickets_regler" not in _actions(listed) and "Les régler dans Cadre" in listed
    # ── Dépôt : ses branches de travail, une par objectif
    append(client, kernel, [c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.CONTINUE, commit="a" * 40,
                                                 branch="mika/objectif-1",
                                                 summary=Content.of("Le squelette est posé.", level=0))], "projects")
    git = _tab(client, pid, "git")
    assert 'data-tab="project/git"' in git and "Branches de travail" in git and "mika/objectif-1" in git


#: une action que la console n'a pas encore sur un onglet : elle se fait par l'API de la personne (ADR 0290,
#: ``tests/protocol/test_moi_project_manage.py``)
SPACE = "espace"
#: L'inventaire (ADR 0281) : chaque action de la fiche d'un projet, et l'onglet qui porte son formulaire — « tête » :
#: la barre de titre, sur tous ses onglets ; une action ajoutée à la faculté doit y prendre sa place.
INVENTORY = {
    "projects.lancer": "tête", "projects.pause": "tête", "projects.reprendre": "tête", "projects.consigne": "tête",
    "projects.archiver": "tête", "projects.restaurer": "tête",
    "projects.plan_valider": "apercu", "projects.plan_reviser": "apercu",
    "projects.lancer_objectif": "apercu", "projects.objectif_statut": "apercu", "projects.objectif_modifier": "apercu",
    "projects.objectif_ajouter": "apercu", "projects.jalon_ajouter": "apercu", "projects.jalon_trancher": "apercu",
    "projects.ticket_ouvrir": "tickets", "projects.ticket_trancher": "tickets", "projects.element_noter": "tickets",
    "projects.ticket_publier": "tickets", "projects.note_publier": "tickets",
    "projects.element_ajouter": "suivi", "projects.element_statut": "suivi", "projects.liste_regler": "suivi",
    "projects.liens": "liens",
    "projects.depot_distant": "git", "projects.pousser": "git", "projects.recuperer": "git",
    "projects.modifier": "comportement", "projects.outils": "comportement", "projects.acces": "comportement",
    "projects.tickets_regler": "comportement",
    "projects.decision_ajouter": "decisions", "projects.decision_statut": "decisions",
    "projects.deposer": "fichiers",
    "projects.fusionner": "git",
    # ADR 0290 : ce que seul l'écran Projets fait pour l'instant, par l'API de la personne
    "projects.jalon_modifier": SPACE, "projects.jalon_retirer": SPACE, "projects.ticket_modifier": SPACE,
    "projects.decision_modifier": SPACE, "projects.pull_modifier": SPACE, "projects.pull_commenter": SPACE,
    # ADR 0293 : changer à qui est un élément d'une liste de suivi
    "projects.element_confier": SPACE,
    # ADR 0289 : sa documentation s'écrit dans l'espace d'une personne et par MCP — la console n'y édite rien
    "projects.doc_ecrire": SPACE, "projects.doc_deplacer": SPACE, "projects.doc_supprimer": SPACE,
    "projects.doc_image": SPACE, "projects.doc_image_retirer": SPACE,
}
#: ce que seul un état particulier montre, et que ce test ne monte pas : une issue chez l'hôte (publier une note),
#: un atelier qui a quelque chose à pousser
NOT_STAGED = {"projects.note_publier", "projects.pousser", "projects.fusionner"}


def test_no_action_of_the_fiche_was_lost(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    declared = {a.key for a in kernel.registry.actions.values() if a.subject == "project" and a.owner == "projects"}
    assert declared == set(INVENTORY), "une action de la fiche d'un projet n'a pas sa place dans l'inventaire"
    _do(client, kernel, pid, "decision_ajouter", "d1", title="Quel protocole ?", choice="RDP d'abord",
        reason="C'est ce qui est demandé.")
    _do(client, kernel, pid, "depot_distant", "r1", remote="https://github.com/exemple/outils-reseau.git",
        branch="main")
    pages = {
        "apercu": _tab(client, pid, "apercu") + _tab(client, rid, "apercu"),  # le plan : chez le projet qui en a un
        "tickets": _tab(client, pid, "tickets") + _tab(client, pid, "tickets", "&element=%234"),
        "suivi": _tab(client, rid, "suivi", "&liste=entreprises&element=acme"),
        "liens": _tab(client, rid, "liens"), "git": _tab(client, pid, "git"),
        "comportement": _tab(client, pid, "comportement"), "decisions": _tab(client, pid, "decisions"),
        "fichiers": _tab(client, pid, "fichiers"),
    }
    found = {tab: _actions(page) for tab, page in pages.items()}
    head = page_head(pages["tickets"])
    for action, tab in INVENTORY.items():
        if action in NOT_STAGED or tab == SPACE or action in ("projects.reprendre", "projects.restaurer"):
            continue
        assert action in (head if tab == "tête" else found[tab]), f"{action} manque sur {tab}"
    # … et chaque onglet d'avant garde ce qu'il montrait
    assert "Ce qu'elle a en main pendant une exécution" in pages["comportement"]
    assert "Quel protocole ?" in pages["decisions"] and "Déposer un fichier" in pages["fichiers"]
    carnet = _tab(client, pid, "carnet")
    assert all(pane in carnet for pane in ("Consignes", "Ses notes", "Ce qu'on en a fait", "Ce qui sort"))
    assert 'data-tab="project/executions"' in _tab(client, pid, "executions")
    # en pause, « Reprendre » ; archivé, « Restaurer »
    _do(client, kernel, pid, "pause", "p1")
    assert "projects.reprendre" in page_head(_tab(client, pid, "apercu"))
    _do(client, kernel, pid, "archiver", "a1")
    assert "projects.restaurer" in page_head(_tab(client, pid, "apercu"))


def page_head(page: str) -> set[str]:
    """Les actions de la barre de titre : ce que la page porte avant sa barre d'onglets."""
    return _actions(page.split('<nav class="tabs', 1)[0])


def test_the_overview_page_says_what_awaits_in_every_project_and_how_they_are_linked(world):  # noqa: F811
    client, live, _ = world
    _, pid, rid = _chain(client, live)
    page = drawn(client, "/admin/projets/tous")
    assert 'data-tab="projets/tous"' in page
    todo = page.split('class="now-card prj-todo"', 1)[1].split("</section>", 1)[0]
    assert "À faire" in todo and page.index("À faire") < page.index('class="prj-list"')  # en tête, avant la liste
    said = [html.unescape(s) for s in re.findall(r'<p class="prj-todo-text">(.*?)</p>', todo, re.S)]
    # le plan d'abord, puis les tickets, le point d'arrêt, enfin ce qui est à ta charge — chacun avec son projet
    assert said[0].startswith("Son plan attend une réponse") and said[1].startswith("#2 Exporter la liste")
    assert said[4].startswith("Objectif n° 1, jalon n° 2") and said[5] == "Acme Réseaux (liste « entreprises »)"
    assert "2 autres éléments" in said[-1]
    projects = re.findall(r'<span class="prj-todo-project">(.*?)</span>', todo, re.S)
    assert "Faire connaître Outils réseau" in projects[0] and "Outils réseau" in projects[1]
    assert f'href="{FICHE.format(pid)}?onglet=tickets&element=%232"' in todo
    assert "Voir les" in todo  # au-delà de six lignes, le reste se déplie : la page tient dans un écran
    # chaque projet dit combien de choses t'y attendent ; ses chiffres le comptent en tête
    rows = page.split('class="prj-list"', 1)[1]
    assert "t’attend : 4 choses" in rows and "t’attend : 6 choses" in rows
    assert page.index("T'attendent") < page.index("Actifs")
    # les liens entre projets : qui lit qui, ce que le lien donne, la demande en cours
    linked = page.split("Dépendances entre projets", 1)[1]
    assert "Faire connaître Outils réseau" in linked and "son titre, son état" in linked
    assert "1 demande en cours (en attente d'accord)" in linked
    assert f'href="{FICHE.format(pid)}?onglet=tickets&element=%232"' in linked
