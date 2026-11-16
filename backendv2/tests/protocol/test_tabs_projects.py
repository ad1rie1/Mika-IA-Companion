"""Activité › Projets, chaque onglet dans sa forme (``app/handmade/tabs/projects.py``, ADR 0177), à travers le vrai
serveur : une rangée par projet (où il en est, ses objectifs, sa prochaine exécution ; « Créer un projet » dans la
barre de titre), ses exécutions jour par jour (verdict, preuve, compte rendu, commit), ses décisions techniques
rangées par projet (ce qui est choisi, pourquoi), les objectifs et les décisions d'un projet (en clair, leurs
boutons sur leur ligne) — et ce qu'ils disent, vides."""

from __future__ import annotations

import json

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import AMENDED, DECIDED, NOTED, OBJECTIVE_CHANGED
from mika.kernel.events import Content, Origin
from mika.runtime.operations import perform
from mika.vocab.episodes import Kind, project_target
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
    assert "0/2 ponctuels faits · 1 constant" in item and 'class="now-bar goal' in item  # en jauge, accordés
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
    items = page.split('<li class="prj-entry')[1:]
    assert len(items) == 3 and "Garder les tests verts" in items[0]  # le constant d'abord, comme la faculté les range
    item = next(x.split("</li>")[0] for x in items if "Recouper les dates" in x)
    assert "ponctuel" in item and "ouvert" in item and "posé par toi" in item
    assert 'class="prj-said-text long"' in item and said.strip() in item and "lire la suite" in item  # en clair
    actions = item.split('class="toolbar prj-entry-actions"')[1]
    seen, more = actions.split('class="action-overflow"')
    assert "Lancer maintenant" in seen and "Marquer fait" in seen and "Modifier l'objectif" in seen
    assert "Retirer" in more and "Retirer" not in seen  # le reste sous « ⋯ »
    add = page.split('class="now-card prj-side"')[1]
    assert "Ajouter un objectif" in add and 'name="text"' in add  # le formulaire, à côté de la liste


def _decide(client, kernel, pid: int, nonce: str, **values: str) -> None:
    """Une décision consignée comme un opérateur le ferait (l'action de l'onglet)."""
    fields = {"title": "", "choice": "", "reason": "", "context": "", "options": "", "replaces": "0", **values}
    got = client.portal.call(lambda: perform(kernel, "projects.decision_ajouter", {
        "_champs": list(fields), **{k: [v] for k, v in fields.items()}}, by="user_1", subject=str(pid), nonce=nonce))
    assert got.ok, got


def test_each_decision_reads_like_an_adr_with_its_buttons_on_its_line(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Carnet du ciel", "Recouper les dates")
    _decide(client, kernel, pid, "d1", title="Les sources des dates", choice="Une seule source", reason="plus simple")
    _decide(client, kernel, pid, "d2", title="Les sources des dates", choice="L'IMO et un magazine d'astronomie",
            reason="Deux sources se recoupent.", context="Une date fausse dans le carnet.", replaces="1")
    page = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=decisions&statut=toutes")
    assert 'data-tab="project/decisions"' in page and "Elle relit celles en vigueur" in page
    live_one, old = (x.split("</li>")[0] for x in page.split('<li class="prj-entry')[1:])
    assert "L'IMO et un magazine d'astronomie" in live_one and "en vigueur" in live_one  # la plus récente d'abord
    assert "Deux sources se recoupent." in live_one.split('class="prj-said-label">Pourquoi')[1]  # en clair
    assert "Une date fausse dans le carnet." in live_one.split('class="hm-subfold prj-entry-more"')[1]  # replié
    assert "posée par toi" in live_one and "remplace D1" in live_one
    actions = live_one.split('class="toolbar prj-entry-actions"')[1]
    assert "Retirer" in actions and "Remplacer cette décision" in actions  # sur sa ligne
    assert old.startswith(' faded"') and "remplacée par D2" in old and "prj-entry-actions" not in old
    add = page.split('class="now-card prj-side"')[1]
    assert "Consigner une décision" in add and 'name="choice"' in add  # le formulaire, à côté de la liste


def test_a_projects_runs_read_day_by_day_and_its_files_are_drawn(world):  # noqa: F811
    """C5-06 : sur la fiche d'un projet, Exécutions et Fichiers ne sont plus des blocs génériques. Exécutions se lit
    jour par jour, comme Projets › Exécutions : l'objectif visé (pas le projet : c'est lui), l'issue, le verdict et sa
    preuve, le compte rendu, le commit, la durée et les onglets de l'épisode, avec la légende qui les explique ; vide,
    il le dit une fois, sans chiffres à zéro ni pagination d'une seule page. Fichiers est une table d'exploitation,
    avec « Déposer un fichier » préparé par la console."""
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Préparer le stream", "Écrire le programme")
    empty = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=executions")
    assert 'class="now-page prj-fiche" data-tab="project/executions"' in empty
    body = empty.split('data-tab="project/executions"', 1)[1]
    assert body.lower().count("aucune exécution encore") == 1  # la majuscule : la feuille de style
    assert "Page 1 sur 1" not in body and ">aucun<" not in body and 'class="pager"' not in body
    assert "Pannes d'affilée" not in body and "« prompt »" not in body  # ni chiffres à zéro, ni légende sans rien
    assert 'class="person-count' not in body  # ni « 0 » à côté du titre : le vide se dit une fois

    def episode(drafts, emitter: str) -> None:
        client.portal.call(lambda: kernel.mind.append(drafts, emitter=emitter, correlation="run-1",
                                                      origin=Origin.GENESIS))

    episode([rt.EPISODE_STARTED.draft(kind=Kind.WORK, target=project_target(pid))], "runtime")
    episode([c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.DONE, proof="commit", proven=True,
                                  summary=Content.of("Programme écrit.", level=0), commit="3f9a2c1e8b7d")], "projects")
    episode([rt.EPISODE_ENDED.draft(kind=Kind.WORK, outcome="done", target=project_target(pid))], "runtime")
    page = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=executions")
    body = page.split('data-tab="project/executions"', 1)[1]
    assert "Pannes d'affilée" in body and "Sur 24 h" in body  # ses chiffres, en tuiles
    assert "« prompt » : ce qu'elle a vraiment reçu" in body  # la légende de la faculté, lisible
    run = body.split("class=\"prj-day\">Aujourd'hui</h3>", 1)[1].split("</li>", 1)[0]
    assert "Objectif n° 1 · Écrire le programme" in run and "Préparer le stream" not in run  # c'est lui
    assert "terminé" in run and ">fait<" in run and "prouvé" in run and "Programme écrit." in run
    assert "commit=3f9a2c1e8b7d" in run and "en 1 s" in run
    for tab in ("prompt", "outils", "appels", "decision"):  # les onglets de son épisode, un à un
        assert f'href="/inspecteur/episode/run-1?onglet={tab}"' in run, tab
    assert 'class="hm-table"' not in body and 'class="pager"' not in body  # le fil, pas le tableau générique
    # Fichiers : l'atelier pas encore ouvert le dit, et l'on peut y déposer un fichier
    closed = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=fichiers")
    root = closed.split('class="now-page person-tab" data-tab="project/fichiers"', 1)[1]
    assert "L'atelier n'est pas encore ouvert" in root and "Déposer un fichier" in root
    assert 'enctype="multipart/form-data"' in root  # le formulaire que la console a préparé
    client.portal.call(kernel.ports["workshop"].write, pid, "notes/plan.md", "# Le plan")
    files = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=fichiers")
    root = files.split('class="now-page person-tab" data-tab="project/fichiers"', 1)[1]
    assert 'class="hm-chips"' in root and "Dossier" in root  # la navigation dans ses dossiers
    table = root.split('<table class="hm-table">', 1)[1].split("</table>", 1)[0]  # une table d'exploitation
    assert "notes/" in table and "1 fichier" in table and "Déposer un fichier" in root


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
    # un objectif bloqué : la figure « Objectifs » de la bande de sa fiche passe en alerte (le ton de sa Stat)
    append(client, kernel, [OBJECTIVE_CHANGED.draft(project=pid, objective=2, status=c.BLOCKED)], "projects")
    band = drawn(client, f"/inspecteur/fiche/project/{pid}").split('class="prj-ov-band"', 1)[1].split("</ul>")[0]
    objectives = band.split("<li", 2)[1]
    assert objectives.startswith(' class="warn"') and "Objectifs" in objectives and "1 bloqué" in objectives


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
    # le statut, quatre choix toujours posés, en bouton à choix ; le projet (un titre ou un n°) garde son formulaire
    # (ADR 0176)
    seg = every.split('<nav class="seg" aria-label="Statut">', 1)[1].split("</nav>", 1)[0]
    assert 'aria-current="true">toutes</a>' in seg and '<select name="statut">' not in every
    form = every.split('<form class="filters"', 1)[1].split("</form>", 1)[0]
    assert 'name="projet"' in form and '<input type="hidden" name="statut" value="toutes">' in form
    assert 'placeholder="un titre ou un n°"' in form and "Projet n°" not in form


def test_runs_and_decisions_filter_by_a_word_of_the_title_or_by_the_number(world):  # noqa: F811
    """Exécutions et Décisions techniques se filtrent par le projet tel que la liste le nomme : un mot de son titre
    (sans tenir compte des accents ni de la casse) ou son n°, avec ou sans « # ». Un mot qui ne désigne aucun projet
    le dit, et la table reste vide ; plusieurs projets trouvés se montrent ensemble, le verdict s'ajoute."""
    client, live, _ = world
    kernel = _life(client, live)
    stream = _create(client, kernel, "Préparer le stream", "Écrire le programme")
    party = _create(client, kernel, "Préparer la fête", "Choisir la musique")
    network = _create(client, kernel, "Outils réseau", "Créer un module RDP")
    append(client, kernel, [
        c.RUN_REPORTED.draft(project=stream, objective=1, verdict=c.CONTINUE,
                             summary=Content.of("Programme esquissé.", level=0)),
        c.RUN_REPORTED.draft(project=party, objective=1, verdict=c.BLOCKED,
                             summary=Content.of("Le lecteur refuse le fichier.", level=0)),
        c.RUN_REPORTED.draft(project=network, objective=1, verdict=c.CONTINUE,
                             summary=Content.of("Le module démarre.", level=0)),
    ], "projects")
    runs = "/inspecteur/projets/toutes_executions"
    said = ("Programme esquissé.", "Le lecteur refuse le fichier.", "Le module démarre.")

    def shown(url: str) -> tuple[bool, ...]:
        page = drawn(client, url)
        return tuple(s in page for s in said)

    assert shown(f"{runs}?projet=RESEAU") == (False, False, True)  # un mot du titre, sans accent ni casse
    assert shown(f"{runs}?projet={network}") == shown(f"{runs}?projet=%23{network}") == (False, False, True)
    assert shown(f"{runs}?projet=préparer") == (True, True, False)  # deux projets trouvés, ensemble
    assert shown(f"{runs}?projet=preparer&verdict=blocked") == (False, True, False)
    nobody = drawn(client, f"{runs}?projet=licorne")
    assert "Aucun projet ne s'appelle « licorne »." in nobody and "aucune exécution avec ces filtres" in nobody
    assert not any(s in nobody for s in said)
    _decide(client, kernel, network, "d1", title="Le protocole", choice="RDP d'abord", reason="le plus demandé")
    _decide(client, kernel, stream, "d2", title="La durée", choice="Une heure et demie", reason="assez pour tout")
    decisions = "/inspecteur/projets/toutes_decisions"
    one = drawn(client, f"{decisions}?projet=réseau")
    assert "RDP d'abord" in one and "Une heure et demie" not in one
    absent = network + 1000  # aucun projet sous ce n°, ni dans un titre
    missing = drawn(client, f"{decisions}?projet={absent}")
    assert f"Aucun projet ne porte le n° {absent}." in missing and "aucune décision avec ces filtres" in missing


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


def test_a_project_page_sends_its_requests_to_the_approvals_queue(world):  # noqa: F811
    """La fiche d'un projet ne décide plus ses demandes sur place (ADR 0177) : son bandeau les compte — lues dans la
    section « À décider » de sa vue — et mène à la première dans « À valider » ; son Carnet garde la commande exacte et
    pose, sous chaque demande qui attend, le lien vers la file ; ni l'un ni l'autre n'a de quoi approuver ou refuser.
    Sa vue d'ensemble dit chaque fait une fois : ni le mode ni la plage dans « Prochaine exécution », le distant dans
    « Son dépôt » seulement."""
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Labo de mesure", "Écrire le banc")
    for argv, said in ((["pip", "install", "requests"], "Installer requests avec le réseau"),
                       (["curl", "-sS", "https://example.test/donnees.csv"], "Télécharger le jeu de mesures")):
        append(client, kernel, [rt.EFFECT_PROPOSED.draft(capability="projects.networked", owner=c.OWNER,
                                                         args_json=f'{{"project": {pid}, "argv": {json.dumps(argv)}}}',
                                                         summary=Content.of(said), context=f"project:{pid}")])
    pending = [p.proposal for p in kernel.mind.frame().get(rt.PENDING_EFFECTS)]
    assert len(pending) == 2
    page = drawn(client, f"/inspecteur/fiche/project/{pid}")
    banner = page.split('class="prj-ov-banner', 1)[1].split("</p>", 1)[0]
    assert "2 demandes attendent ton accord" in banner
    assert f'href="/inspecteur/approbations/en_attente?demande={pending[0]}"' in banner  # la première
    tiles = page.split('class="prj-ov-grid"', 1)[1]
    shown = [t.split("</dt>", 1)[0] for t in tiles.split("<dt>")[1:]]
    assert shown == ["quand", "sur quoi", "dépôt distant", "dernier échange"]  # l'en-tête, la bande disent le reste
    band = page.split('class="prj-ov-band"', 1)[1].split("</ul>", 1)[0]
    assert "Dernier commit" in band and "dépôt distant" not in band  # le distant, dans « Son dépôt » seulement
    carnet = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=carnet")
    for action in ("projects.approuver", "projects.refuser"):
        assert f'action="/inspecteur/action/{action}"' not in carnet and f'action="/inspecteur/action/{action}"' \
            not in page
    for n in pending:
        assert f'href="/inspecteur/approbations/en_attente?demande={n}"' in carnet
    # ni « » » ni « valider » seul à la ligne : des espaces insécables, fines dans les guillemets
    assert carnet.count("La décider dans «\u202fÀ\u00a0valider\u202f»") == 2
    assert "attend ton accord" in carnet and "https://example.test/donnees.csv" in carnet  # l'état, la commande


def test_a_projects_behaviour_is_a_settings_form_without_redoing_its_cards(world):  # noqa: F811
    """C5-06 : Comportement et outils est dessiné dans le gabarit du paramétrage — le formulaire « Modifier le projet »
    par groupes (dont l'Agenda en mots), une ligne par réglage, « Enregistrer » collé en bas, sans cadre dans une
    carte ; les cartes « Son mode » et « Son rythme » ne se redisent pas : leurs faits sont dans l'aide de leur réglage,
    sa prochaine exécution sur une ligne (« maintenant » n'existe plus). Ses outils : la table des lots et « Choisir ses
    outils ». Archivé, ses réglages se lisent, sans formulaire."""
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Outils réseau", "Créer un module RDP")
    page = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=comportement")
    assert 'data-tab="project/comportement"' in page
    body = page.split('data-tab="project/comportement"', 1)[1]
    form = body.split('action="/inspecteur/action/projects.modifier"', 1)[1].split("</form>", 1)[0]
    assert 'class="form hm-form prj-behaviour-form"' in body  # le paramétrage, pas la carte générique d'une action
    assert 'class="form action-card' not in body and "now-card" not in form  # ni carte ni cadre dans la carte
    legends = [x.split("</legend>", 1)[0] for x in form.split("<legend>")[1:]]
    assert legends == ["Le projet", "Son mode", "Son rythme", "Sa liberté"]
    for name in ("title", "description", "owner", "mode", "schedule", "schedule_rule", "days", "start", "end",
                 "runs_per_day", "priority", "approval"):
        assert f'name="{name}"' in form, name
    agenda = form.split('name="schedule"', 1)[1].split("</select>", 1)[0]
    assert "dès que possible" in agenda and "une autre règle…" in agenda  # l'Agenda en mots
    assert "sa fatigue dans son prompt" in form and "pendant son sommeil" in form  # ce que veut dire un mode
    cap = form.split('name="runs_per_day"', 1)[1].split("</div>", 1)[0]
    assert "En vigueur : " in cap and "au plus (par défaut)" in cap and "espacement : " in cap \
        and "par heure, tous projets : " in cap  # ses plafonds, dans l'aide de leur réglage
    assert form.rstrip().endswith('<div class="form-actions"><button class="btn">Enregistrer</button></div>')
    for card in ("Son mode", "Son rythme", "Sa liberté"):
        assert f"<h2>{card}</h2>" not in body and f">{card}</h3>" not in body, card
    assert "ce que ça veut dire" not in body and "son humeur dans le prompt" not in body
    assert "prochaine exécution" in body.split("<form", 1)[0] and ">maintenant<" not in body
    tools = body.split('id="prj-tools-title"', 1)[1]
    assert ">Ses outils</h2>" in tools and "son atelier" in tools and "ws_write" in tools  # les lots, leurs outils
    assert '<div class="hm-pager single">' in tools  # une page : ni « 1–4 sur 4 » ni « Page 1 sur 1 » en vue
    chooser = tools.split('action="/inspecteur/action/projects.outils"', 1)[1].split("</form>", 1)[0]
    assert "Choisir ses outils" in chooser and 'name="tool_memory"' in chooser and "Enregistrer ses outils" in chooser
    archived = client.portal.call(lambda: perform(kernel, "projects.archiver", {"_champs": []}, by="user_1",
                                                  subject=str(pid), nonce="a1"))
    assert archived.ok, archived
    shown = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=comportement")
    body = shown.split('data-tab="project/comportement"', 1)[1]
    assert "projects.modifier" not in body and "projects.outils" not in body  # le formulaire n'est plus offert
    assert "archivé ne se modifie plus" in body
    read = body.split('class="now-card prj-settings-ro"', 1)[1].split("</section>", 1)[0]
    for said in ("Son mode", "ce que ça veut dire", "Son rythme", "agenda", "prochaine exécution", "Sa liberté",
                 "ce qui sort de la machine"):
        assert said in read, said


def test_a_projects_notebook_reads_in_subtabs_and_sends_requests_to_the_queue(world):  # noqa: F811
    """C5-06 : le Carnet passe en sous-onglets — Consignes, Ses notes, Ce qu'on en a fait, Ce qui sort —, chacun avec
    sa pagination (ses liens reviennent à son ancre ; celui qu'on feuillette s'ouvre) ; une demande qui attend ton
    accord le dit, garde sa commande et mène à la file, sans formulaire de décision."""
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Labo de mesure", "Écrire le banc")
    append(client, kernel, [AMENDED.draft(project=pid, instruction=Content.of("Garde les mesures brutes.", level=0),
                                          by="user_1")], "projects")
    append(client, kernel, [NOTED.draft(project=pid, text=Content.of(f"Note n° {n}.", level=0))
                            for n in range(1, 28)], "projects")  # plus d'une page (25)
    append(client, kernel, [rt.EFFECT_PROPOSED.draft(capability="projects.networked", owner=c.OWNER,
                                                     args_json=f'{{"project": {pid}, "argv": ["pip", "install", '
                                                               '"requests"]}',
                                                     summary=Content.of("Installer requests avec le réseau"),
                                                     context=f"project:{pid}")])
    pending = [p.proposal for p in kernel.mind.frame().get(rt.PENDING_EFFECTS)]
    page = drawn(client, f"/inspecteur/fiche/project/{pid}?onglet=carnet")
    body = page.split('data-tab="project/carnet"', 1)[1]
    nav = body.split('<div class="hm-subtabs" data-subtabs>', 1)[1].split("</nav>", 1)[0]
    assert [x.split("</a>", 1)[0].rsplit(">", 1)[1] for x in nav.split("<a ")[1:]] == [
        "Consignes", "Ses notes", "Ce qu'on en a fait", "Ce qui sort"]
    assert '<a href="#carnet-sorties" class="warn">' in nav  # une demande y attend
    panes = [x.split('"', 1)[0] for x in body.split('<section id="')[1:]]
    assert panes == ["carnet-consignes", "carnet-notes", "carnet-faits", "carnet-sorties"]
    assert body.count(" data-pane ") == 4
    orders = body.split('id="carnet-consignes"', 1)[1].split("</section>", 1)[0]
    assert "Garde les mesures brutes." in orders and 'class="prj-notebook-meta"' in orders  # le texte, puis de qui
    notes = body.split('id="carnet-notes"', 1)[1].split("</section>", 1)[0]
    assert "Note n° 27." in notes and "Note n° 2." not in notes  # la plus récente d'abord, une page
    older = notes.split('class="hm-pager"', 1)[1].split('href="')
    link = next(x.split('"', 1)[0] for x in older[1:] if "avant_notes=" in x)
    assert link.endswith("#carnet-notes")  # la page suivante revient à son sous-onglet
    out = body.split('id="carnet-sorties"', 1)[1]  # le dernier sous-onglet (sa commande est une section à elle)
    assert "attend ton accord" in out and "Installer requests avec le réseau" in out and "requests" in out
    assert f'href="/inspecteur/approbations/en_attente?demande={pending[0]}"' in out  # mène à la file
    assert "projects.approuver" not in body and "projects.refuser" not in body and "<form" not in out
    paged = drawn(client, f"/inspecteur/fiche/project/{pid}{link.split('#', 1)[0]}")
    body = paged.split('data-tab="project/carnet"', 1)[1]
    first = body.split('<section id="', 1)[1].split('"', 1)[0]
    assert first == "carnet-notes" and "Note n° 2." in body  # le sous-onglet qu'on feuillette s'ouvre
