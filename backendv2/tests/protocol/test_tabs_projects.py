"""Activité › Projets, chaque onglet dans sa forme (``app/handmade/tabs/projects.py``, ADR 0177), à travers le vrai
serveur : une rangée par projet (où il en est, ses objectifs, sa prochaine exécution ; « Créer un projet » dans la
barre de titre), ses exécutions jour par jour (verdict, preuve, compte rendu, commit), ses décisions techniques
rangées par projet (ce qui est choisi, pourquoi), les objectifs d'un projet (en clair, leurs boutons sur leur ligne)
— et ce qu'ils disent, vides."""

from __future__ import annotations

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import DECIDED
from mika.kernel.events import Content
from mika.runtime.operations import perform
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _create(client, kernel, title: str, objectives: str) -> int:
    """Un projet créé comme un opérateur le ferait (l'action de la console)."""
    got = client.portal.call(lambda: perform(kernel, "projects.creer", {
        "_champs": ["title", "description", "objectives", "constants", "mode", "schedule", "days", "start", "end",
                    "cadence_hours", "runs_per_day", "priority", "branch", "tool_memory"],
        "title": [title], "description": ["Un projet de test."], "objectives": [objectives],
        "constants": ["Garder les tests verts"], "mode": ["persona"], "schedule": ["manual"], "days": ["weekdays"],
        "start": ["9:00"], "end": ["18:00"], "cadence_hours": ["24"], "runs_per_day": ["0"], "priority": ["normal"],
        "branch": ["main"], "tool_memory": ["on"]}, by="user_1", nonce=f"test-{title}"))
    assert got.ok, got
    return int(got.go.key.split("/", 1)[1])


def _life(client, live):
    bootstrap(client)
    stop(client, live.kernel)
    return live.kernel


def test_each_project_says_where_it_stands_and_creating_one_stays_in_the_title_bar(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    empty = drawn(client, "/inspecteur/projets/tous")
    assert "aucun projet : « Créer un projet » (en haut) en ouvre un" in empty
    assert "Créer un projet" in empty.split('data-tab="projets/tous"')[0]  # l'action de la destination, en haut
    pid = _create(client, kernel, "Outils réseau", "Créer un module RDP\nÉcrire sa documentation")
    append(client, kernel, [c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.CONTINUE,
                                                 summary=Content.of("Le squelette est posé.", level=0))], "projects")
    page = drawn(client, "/inspecteur/projets/tous")
    item = page.split('class="prj-item')[1].split("</li>")[0]
    assert f'href="/inspecteur/fiche/project/{pid}"' in item and "Outils réseau" in item
    assert "elle-même" in item and "actif" in item  # son mode, son état
    assert "Le squelette est posé." in item.split('class="prj-where"')[1]  # où il en est
    assert "0 / 2 ponctuel(s)" in item and 'class="now-bar goal' in item  # ses objectifs en jauge
    assert "Prochaine exécution" in item and "Son rythme, ses outils, son dépôt" in item  # le reste, replié
    assert "Plage de travail" in item.split("Son rythme, ses outils, son dépôt")[-1]  # replié sous la rangée
    table = drawn(client, "/inspecteur/projets/tous?vue_pg1=table")  # en tableau : la liste de la console
    assert 'class="hm-table"' in table and "prj-item" not in table and "Outils réseau" in table


def test_each_objective_reads_in_clear_with_its_buttons_on_its_line(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Carnet du ciel", "Recouper les dates\nÉcrire novembre")
    said = "Dates recoupées entre deux sources. " * 20  # assez long pour se replier en quatre lignes
    append(client, kernel, [c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.CONTINUE,
                                                 summary=Content.of(said, level=0))], "projects")
    page = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=objectifs")
    assert 'data-tab="project/objectifs"' in page and "Ponctuels faits" in page  # dessiné, ses chiffres en tête
    items = page.split('class="prj-obj-item')[1:]
    assert len(items) == 3 and "Garder les tests verts" in items[0]  # le constant d'abord, comme la faculté les range
    item = next(x.split("</li>")[0] for x in items if "Recouper les dates" in x)
    assert "ponctuel" in item and "ouvert" in item and "posé par toi" in item
    assert 'class="prj-obj-quote long"' in item and said.strip() in item and "lire la suite" in item  # en clair
    actions = item.split('class="toolbar prj-obj-actions"')[1]
    seen, more = actions.split('class="action-overflow"')
    assert "Lancer maintenant" in seen and "Marquer fait" in seen and "Modifier l'objectif" in seen
    assert "Retirer" in more and "Retirer" not in seen  # le reste sous « ⋯ »
    add = page.split('class="now-card prj-obj-add"')[1]
    assert "Ajouter un objectif" in add and 'name="text"' in add  # le formulaire, à côté de la liste


def test_runs_read_day_by_day_with_their_verdict_proof_and_commit(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    assert "aucune exécution encore" in drawn(client, "/inspecteur/projets/toutes_executions")
    pid = _create(client, kernel, "Préparer le stream", "Écrire le programme\nPréparer les visuels")
    append(client, kernel, [
        c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.DONE, proof="commit", proven=True,
                             summary=Content.of("Programme écrit.", level=0), commit="3f9a2c1e8b7d"),
        c.RUN_REPORTED.draft(project=pid, objective=2, verdict=c.BLOCKED,
                             summary=Content.of("Le dépôt distant refuse la poussée.", level=0)),
    ], "projects")
    page = drawn(client, "/inspecteur/projets/toutes_executions")
    feed = page.split("class=\"prj-day\">Aujourd'hui</h3>")[1]
    assert feed.index("Le dépôt distant refuse") < feed.index("Programme écrit.")  # la plus récente d'abord
    blocked = feed.split("Le dépôt distant refuse")[0].rsplit("<li", 1)[1]
    assert 'class="blocked"' in blocked and "bloqué" in blocked and "Préparer les visuels" in blocked
    done = feed.split("Programme écrit.")[0].rsplit("<li", 1)[1] + feed.split("Programme écrit.")[1].split("</li>")[0]
    assert "prouvé" in done and "commit=3f9a2c1e8b7d" in done and "L’épisode : prompt, outils, appels" in done


def test_technical_decisions_are_grouped_by_project_with_what_and_why(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    assert "aucune décision avec ces filtres" in drawn(client, "/inspecteur/projets/toutes_decisions")
    first = _create(client, kernel, "Outils réseau", "Créer un module RDP")
    second = _create(client, kernel, "Préparer le stream", "Écrire le programme")
    for d in (DECIDED.draft(project=first, decision=1, title=Content.of("Quel langage ?", level=0),
                            choice=Content.of("Python", level=0), reason=Content.of("Le reste est en Python.", level=0)),
              DECIDED.draft(project=first, decision=2, title=Content.of("Quel langage, vraiment ?", level=0),
                            choice=Content.of("Python 3.12, avec asyncio", level=0), replaces=1,
                            reason=Content.of("asyncio suffit pour les connexions.", level=0)),
              DECIDED.draft(project=second, decision=1, title=Content.of("Durée du stream", level=0),
                            choice=Content.of("Une heure et demie", level=0), author="operator")):
        append(client, kernel, [d], "projects")
    page = drawn(client, "/inspecteur/projets/toutes_decisions")
    groups = page.split('class="prj-dec-group"')[1:]
    assert len(groups) == 2 and "Préparer le stream" in groups[0] and "Outils réseau" in groups[1]
    network = groups[1]
    assert "Python 3.12, avec asyncio" in network.split('class="prj-dec-choice"')[1]
    assert "asyncio suffit pour les connexions." in network.split('class="prj-dec-why"')[1]
    assert "Quel langage ?" not in network  # remplacée : hors des décisions en vigueur
    assert "posée par toi" in groups[0]
    every = drawn(client, "/inspecteur/projets/toutes_decisions?statut=toutes")
    replaced = every.split("Quel langage ?")[0].rsplit("<li", 1)[1]
    assert 'class="faded"' in replaced and "remplacée par D2" in every


def test_a_project_page_reads_like_the_mockup(world):  # noqa: F811
    """La fiche d'un projet, la vue d'un objet de la maquette (ADR 0176, 0177) : « Activité / Projets / n° 61 », son
    état à côté de son nom, ses faits sur une ligne ; deux actions en vue (la principale à droite), le reste sous
    « ⋯ » ; ses onglets disent leur compte, Accès et Carnet sous « Plus » ; un seul bandeau — ce qui attend ton
    accord mène à la file des validations —, une bande de chiffres, des tuiles vers leurs onglets."""
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Labo de mesure", "Écrire le banc\nLire les résultats")
    append(client, kernel, [rt.EFFECT_PROPOSED.draft(capability="projects.networked", owner=c.OWNER,
                                                     args_json='{"argv": ["pip", "install", "requests"]}',
                                                     summary=Content.of("Installer requests avec le réseau"),
                                                     context=f"project:{pid}")])
    page = drawn(client, f"/inspecteur/fiche/project/{pid}")
    crumbs = page.split('<nav class="crumbs"', 1)[1].split("</nav>", 1)[0]
    assert crumbs.index("Activité") < crumbs.index(">Projets</a>") < crumbs.index(f"n° {pid}")
    title = page.split('class="page-title-row"', 1)[1].split("</div>", 1)[0]
    assert "<h1>Labo de mesure</h1>" in title and ">actif<" in title
    facts = page.split('class="head-facts"', 1)[1].split("</div>", 1)[0]
    assert "mode" in facts and "dernière exécution" in facts and "plage" in facts
    bar = page.split('class="action-bar"', 1)[1].split('class="toolbar action-overflow-panel"', 1)
    assert bar[0].index("Donner une consigne") < bar[0].index("Lancer maintenant")  # la principale à droite
    assert 'aria-label="Autres actions"' in bar[0] and "Mettre en pause" in bar[1]
    tabs = page.split('class="tabs-row"', 1)[1].split("</details>", 1)[0]
    assert 'Objectifs<span class="tab-n now-num">3</span>' in tabs  # deux ponctuels, un constant
    assert ">Plus <" in tabs and ">Accès</a>" in tabs and ">Carnet</a>" in tabs
    banner = page.split('class="prj-ov-banner', 1)[1].split("</p>", 1)[0]
    pending = [p.proposal for p in kernel.mind.frame().get(rt.PENDING_EFFECTS)]
    assert "1 demande attend ton accord" in banner and f"/approbations/en_attente?demande={pending[0]}" in banner
    assert page.count('<p class="prj-ov-banner ') == 1 and "À décider" not in page
    band = page.split('class="prj-ov-band"', 1)[1].split("</ul>", 1)[0]
    assert ">0/2<" in band and "ponctuels faits · 1 constant" in band
    assert f'href="/inspecteur/fiche/project/{pid}?onglet=objectifs">Objectifs →' in page
