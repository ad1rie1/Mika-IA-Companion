"""La fiche d'un projet › Activité et Dépendances, calquées sur l'écran Projets (ADR 0290, 0297) : le fil jour par
jour lu par la même fonction que l'API (``feed``), ses filtres et sa pagination, chaque ligne vers ce qu'elle nomme ;
une exécution dans ses trois zones, ses pas, et les onglets de son épisode que seule la console a ; le carnet ; le
schéma de ses dépendances, un lien dans le panneau, et ses gestes — l'ajouter avec son pourquoi, changer ce mot, le
retirer — par l'action ``projects.liens`` ; ses demandes envoyées et reçues."""

from __future__ import annotations

import re

from mika.app.handmade.subjects import project_activity
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import actions, feed
from mika.faculties.projects.faculty import frame_subject, subject_of
from mika.kernel.events import Content
from mika.vocab.episodes import Kind, Outcome, project_target
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_moi_project_activity import _append, _run
from tests.protocol.test_moi_projects import _project
from tests.protocol.test_project_fiche_tabs import _chain, _create, _do
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

FICHE = "/admin/fiche/project/{}?onglet={}"


def _page(client, pid: int, tab: str, more: str = "") -> str:
    page = drawn(client, FICHE.format(pid, tab) + more)
    assert "Cette vue a échoué" not in page, tab
    return page


def _post(client, form: dict[str, list[str]], action: str, **values: str):
    data = {**form, "_champs": [*form.get("_champs", []), *values], **{k: [v] for k, v in values.items()}}
    return client.post(f"/admin/action/{action}", data=data, follow_redirects=False)


def _runs(client, live, pid: int) -> None:
    """Un cadrage, puis une exécution sur l'objectif n° 1 qui laisse un commit et demande quelque chose."""
    _run(client, live, pid, "ep-cadrage", frame_subject(pid), summary="Plan écrit en quatre temps.")
    _run(client, live, pid, "ep-1", subject_of(pid, 1), objective=1, summary="Le squelette est posé.",
         commit="a" * 40, need="Une clé de test")


def _form(page: str, having: str) -> dict[str, list[str]]:
    """Les champs cachés du formulaire de ``projects.liens`` qui porte ``having``."""
    forms = re.findall(r'<form method="post" action="/admin/action/projects.liens".*?</form>', page, re.S)
    found = next(f for f in forms if having in f)
    data: dict[str, list[str]] = {}
    for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', found):
        data.setdefault(name, []).append(value)
    return data


def test_the_feed_reads_day_by_day_and_each_line_leads_to_what_it_names(world):  # noqa: F811
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    _runs(client, live, pid)
    page = _page(client, pid, "executions")
    bar = page.split('aria-label="Son activité"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'aria-current="page">([^<]+)', bar) == ["Fil"] and "Exécutions" in bar and "Carnet" in bar
    lines = re.findall(r'<a class="pj-fline" href="([^"]+)"', page)
    assert lines and "Le squelette est posé." in page
    # une exécution mène à son détail ; un commit à Code ; un geste sur un objectif à lui
    assert any("vue=executions&execution=" in h for h in lines)
    assert any("onglet=git&vue=commits&sha=" in h for h in lines)
    assert "Trente derniers jours" in page and "<svg class=\"pj-chart\"" in page and "Qui a fait quoi" in page
    # ses filtres : une sorte, un objectif
    runs = _page(client, pid, "executions", f"&sorte={feed.RUN}")
    shown = runs.split('class="pj-vbody"', 1)[1].split("<aside", 1)[0]
    assert "Le squelette est posé." in shown and "Plan écrit" in shown and "Objectif n° 1 ajouté" not in shown
    one = _page(client, pid, "executions", "&objectif=1")
    assert "objectif n° 2" not in one.split('class="pj-vbody"', 1)[1].split('<aside', 1)[0]


def test_a_run_opens_in_three_zones_with_its_steps_and_its_episode(world):  # noqa: F811
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    _runs(client, live, pid)
    page = _page(client, pid, "executions", "&vue=executions")
    rows = re.findall(r'<a class="pj-row pj-rrow" href="([^"]+)"', page)
    assert len(rows) == 2 and "Exécution · travail" in page and "Ce qu'elle a fait, pas à pas" in page
    assert "Le squelette est posé." in page and "Une clé de test" in page and "aaaaaaa" in page
    assert re.findall(r'aria-label="Ce qu\'on en lit">(.*?)</nav>', page, re.S)[0].count("<a ") == 5
    for pane, said in (("prompt", "Prompt"), ("outils", "Outils"), ("appels", "Appels"), ("decision", "Décision")):
        shown = _page(client, pid, "executions", rows[0].split("?", 1)[1].replace("onglet=executions", "")
                      + f"&volet={pane}")
        assert re.search(r'aria-current="true">' + said, shown), pane
        assert 'class="pj-episode"' in shown or "ouvrir son épisode" in shown, pane
    # l'ancienne adresse du carnet mène au Carnet
    moved = client.get(f"/admin/fiche/project/{pid}?onglet=carnet", follow_redirects=False)
    assert moved.status_code == 303 and "vue=carnet" in moved.headers["location"]
    carnet = _page(client, pid, "executions", "&vue=carnet")
    assert all(x in carnet for x in ("Ses notes", "Consignes", "Ce qu'on en a fait", "Ce qui sort"))


def test_dependencies_draw_a_schema_and_a_link_is_added_explained_and_removed(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    other = _create(client, kernel, "Un troisième projet", "Exister")
    page = _page(client, rid, "liens")
    assert "Il dépend de" in page and "Dépendent de lui" in page and "lu par lui" in page
    assert "Outils réseau" in page.split('class="pj-col-deps"', 1)[1]
    side = page.split('<aside class="pj-side"', 1)[1].split("</aside>", 1)[0]
    assert "Ce que le lien lui donne" in side and "Le voir" in side and "Ses demandes" in side
    # ajouter une dépendance, avec son pourquoi
    adding = _page(client, rid, "liens", "&ajouter=1")
    forms = re.findall(r'<form method="post" action="/admin/action/projects.liens".*?</form>', adding, re.S)
    assert len(forms) == 1  # un projet qu'il peut lire de plus : le troisième (il lit déjà le produit)
    sent = _post(client, _form(adding, f'name="why_for" value="{other}"'), "projects.liens",
                 why="Pour reprendre son vocabulaire.")
    back = drawn(client, sent.headers["location"])
    assert "Il lit maintenant" in back
    page = _page(client, rid, "liens", f"&lien={other}")
    assert "Pour reprendre son vocabulaire." in page and "Un troisième projet" in page
    assert "Outils réseau" in page  # le lien d'avant est resté
    # le retirer : l'autre lien reste
    drop = _form(page, 'data-confirm="Ne plus lire')
    assert f"lit_{other}" not in drop and drop["_champs"]
    sent = _post(client, drop, "projects.liens")
    assert "Il lit maintenant" in drawn(client, sent.headers["location"])
    page = _page(client, rid, "liens")
    assert "Un troisième projet" not in page.split('class="pj-col-deps"', 1)[1].split('class="pj-center"', 1)[0]
    assert "Outils réseau" in page
    # ses demandes, envoyées et reçues, et leur ticket
    asks = _page(client, rid, "liens", "&vue=demandes")
    assert "Demandes entre projets" in asks
    received = _page(client, pid, "liens", "&vue=demandes")
    assert "Demandes entre projets" in received


def _failed(client, live, pid: int, correlation: str, objective: int, summary: str) -> None:
    """Une exécution qui a rendu son compte rendu (« continuer »), puis a mal fini (un délai dépassé, une panne)."""
    p = _project(live, pid)
    about = {"owner": p.owner, "about": p.about, "read_about": p.read_about}
    _append(client, live, [rt.EPISODE_STARTED.draft(kind=Kind.WORK, target=project_target(pid),
                                                    subject=subject_of(pid, objective))], correlation, "runtime")
    _append(client, live, [c.RUN_REPORTED.draft(project=pid, objective=objective, verdict=c.CONTINUE,
                                                summary=Content.of(summary, level=1), **about)], correlation)
    _append(client, live, [rt.EPISODE_ENDED.draft(kind=Kind.WORK, outcome=Outcome.FAILED, target=project_target(pid))],
            correlation, "runtime")


def test_lists_keep_their_page_and_runs_say_their_verdict_and_their_end(world, monkeypatch):  # noqa: F811
    """La relecture adverse de C0 à C3 (2026-11-22) : choisir une exécution d'une page plus ancienne garde cette page ;
    une exécution qui a mal fini après son compte rendu dit son verdict à sa couleur, et son échec à côté (plus de
    « continuer » en rouge) ; une page plus ancienne du fil ne relit pas ses trente jours ; le premier repère du
    graphique n'est pas coupé ; un compte rendu d'objectif mène à son exécution ; l'onglet Objectifs compte ce que
    « Ouverts » montre."""
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    _runs(client, live, pid)
    _failed(client, live, pid, "ep-2", 1, "L'hôte d'essai ne répond plus.")
    monkeypatch.setattr(project_activity, "RUNS_PAGE", 1)
    first = _page(client, pid, "executions", "&vue=executions")
    older = re.search(r'<a class="btn quiet" href="([^"]+)">Plus anciennes', first).group(1)
    second = drawn(client, older)
    rows = re.findall(r'<a class="pj-row pj-rrow" href="([^"]+)"', second)
    assert rows and all("avant=" in r for r in rows)
    chosen = drawn(client, rows[0])
    assert "avant=" in chosen.split('aria-label="Ce qu\'on en lit"', 1)[1].split("</nav>", 1)[0]  # ses volets aussi
    # l'exécution qui a mal fini : « continuer » à la couleur d'un verdict qui continue, « échec » à côté
    row = re.search(r'<a class="pj-row pj-rrow"[^>]*execution=ep-2.*?</a>', first, re.S).group(0)
    assert '<span class="pj-st work">continuer</span>' in row and '<span class="pj-st fail">' in row
    # le fil : sa première page a ses trente jours, une page plus ancienne non (le journal n'est pas relu deux fois)
    monkeypatch.setattr(project_activity, "PAGE", 1)
    feed_page = _page(client, pid, "executions")
    assert '<svg class="pj-chart"' in feed_page and '<text x="1.5" y="114" class="debut">' in feed_page
    back = re.search(r'<a class="btn quiet" href="([^"]+)">Plus anciens', feed_page).group(1)
    old = drawn(client, back)
    assert '<svg class="pj-chart"' not in old and "Ses trente derniers jours se lisent en tête du fil" in old
    # un compte rendu d'objectif mène à son exécution, pas au fil
    goal = drawn(client, f"/admin/fiche/project/{pid}?onglet=objectifs&objectif=1")
    told = goal.split('id="obj-rendus"', 1)[1]
    assert "vue=executions&execution=ep-1" in told or "vue=executions&execution=ep-2" in told
    # l'onglet Objectifs compte ses objectifs ouverts, comme la pastille « Ouverts »
    tab = re.search(r'onglet=objectifs[^"]*"[^>]*>Objectifs<span[^>]*>(\d+)<', goal)
    opened = re.search(r'>Ouverts<span[^>]*>(\d+)<', goal)
    assert tab and opened and tab.group(1) == opened.group(1) == "3"  # avant : ses ponctuels seuls


def test_a_link_gesture_returns_to_its_link_and_refuses_a_stale_state(world):  # noqa: F811
    """Changer le pourquoi d'un lien revient sur ce lien, pas sur le premier ; un geste préparé sur un état qui a bougé
    depuis (un autre onglet) est refusé au lieu de défaire ce qui a changé (``seen``) ; l'API, qui n'envoie que ce qui
    change, n'en pose pas."""
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    other = _create(client, kernel, "Un troisième projet", "Exister")
    third = _create(client, kernel, "Un quatrième projet", "Exister aussi")
    adding = _page(client, rid, "liens", "&ajouter=1")
    sent = _post(client, _form(adding, f'name="why_for" value="{other}"'), "projects.liens", why="Son vocabulaire.")
    assert f"lien={other}" in sent.headers["location"]  # ajouté, il s'ouvre
    page = _page(client, rid, "liens", f"&lien={other}")
    why = _form(page, 'class="form pj-why"')
    assert why["seen"] == [actions.links_seen(_project(live, rid))] and "seen" in why["_fixes"]
    sent = _post(client, why, "projects.liens", why="Son vocabulaire, et ses mots.")
    assert f"lien={other}" in sent.headers["location"] and "Son vocabulaire, et ses mots." in drawn(
        client, sent.headers["location"])
    # deux onglets : celui-ci prépare « ne plus le lire » ; l'autre fait lire un quatrième projet entre-temps
    page = _page(client, rid, "liens", f"&lien={other}")
    drop = _form(page, 'data-confirm="Ne plus lire')
    reads = {*_project(live, rid).reads, third}
    _do(client, kernel, rid, "liens", "autre-onglet", **{actions.link_knob(t): "on" for t in reads})
    sent = _post(client, drop, "projects.liens")
    assert actions.LINKS_MOVED in drawn(client, sent.headers["location"])
    assert {other, third} <= set(_project(live, rid).reads)  # rien n'a été défait
