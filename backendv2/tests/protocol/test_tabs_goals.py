"""Activité › Buts, chaque onglet dans sa forme (``app/handmade/tabs/goals.py``, ADR 0177), à travers le vrai serveur :
ses explorations et ses rappels côte à côte (les séances et l'envie d'une exploration, la date d'un rappel), ses buts
clos avec leur issue en marque et ce qu'ils ont donné — et ce qu'ils disent, vides ; « Programmer un rappel » dans
la barre de titre, sur sa page (ADR 0232)."""

from __future__ import annotations

import re

from mika.contracts import goals as c
from mika.kernel.clock import DAY, HOUR, local
from mika.kernel.events import Content
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _open(client, kernel, kind, title, **more):
    authority = more.pop("authority", c.SELF if kind == c.EXPLORATION else c.USER)
    return append(client, kernel, [c.GOAL_OPENED.draft(kind=kind, authority=authority, title=Content.of(title, level=0),
                                                       sensitivity=0, **more)], "goals").seqs[0]


def _life(client, live):
    bootstrap(client)
    stop(client, live.kernel)
    return live.kernel, live.kernel.mind.clock.now()


def test_living_goals_put_explorations_and_reminders_side_by_side(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    empty = drawn(client, "/inspecteur/buts/vivants")
    assert "aucun but en cours" in empty and 'class="person-tiles"' in empty  # ses chiffres, même vides
    _open(client, kernel, c.EXPLORATION, "Explorer : les jeux rétro", bundles=("goals",), max_steps=8, desire=0.9)
    _open(client, kernel, c.REMINDER, "Souhaiter bon courage à Béa", owner="user_1", due=now + 2 * DAY)
    _open(client, kernel, c.REMINDER, "Arroser les plantes", owner="user_1", due=now + 2 * HOUR)
    page = drawn(client, "/inspecteur/buts/vivants")
    explore = page.split('id="gl-explore-title"')[1].split('id="gl-remind-title"')[0]
    assert "Explorer : les jeux rétro" in explore and "Arroser" not in explore
    assert "Séances" in explore and "0 / 8" in explore and "Envie" in explore  # son plafond et son envie qui s'use
    remind = page.split('id="gl-remind-title"')[1]
    assert remind.index("Arroser les plantes") < remind.index("Souhaiter bon courage")  # le plus proche d'abord
    assert 'class="gl-cal"' in remind and 'class="gl-cal-d"' in remind  # sa date en pavé de calendrier
    assert "Vivants" in page and "Séances dans l'heure" in page
    # ce que l'onglet est se dit une fois, dans son introduction : la carte ne le redit pas en légende
    assert page.count("Ses projets ont leur menu à eux") == 1 and page.count("se propose de faire ensuite") == 1
    # un filtre qui écarte une sorte : sa colonne se tait
    only = drawn(client, f"/inspecteur/buts/vivants?sorte={c.REMINDER}")
    assert "Arroser les plantes" in only and 'id="gl-explore-title"' not in only


def test_closed_goals_show_their_issue_and_what_they_gave(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    assert "aucun but clos" in drawn(client, "/inspecteur/buts/clos")
    done = _open(client, kernel, c.EXPLORATION, "Lire sur la typographie", max_steps=4, desire=0.6)
    stuck = _open(client, kernel, c.EXPLORATION, "Trouver un hébergeur", max_steps=4, desire=0.5, authority=c.USER,
                  owner="user_1")
    dropped = _open(client, kernel, c.EXPLORATION, "Apprendre le solfège", max_steps=4, desire=0.3)
    append(client, kernel, [
        c.GOAL_CLOSED.draft(goal=done, status=c.ACHIEVED, kind=c.EXPLORATION, authority=c.SELF,
                            title=Content.of("Lire sur la typographie", level=0),
                            result=Content.of("Les polices pixel étaient dessinées lettre par lettre.", level=0)),
        c.GOAL_CLOSED.draft(goal=stuck, status=c.STUCK, kind=c.EXPLORATION, authority=c.USER, owner="user_1",
                            title=Content.of("Trouver un hébergeur", level=0), reason="trois séances sans verdict"),
        c.GOAL_CLOSED.draft(goal=dropped, status=c.ABANDONED, kind=c.EXPLORATION, authority=c.SELF,
                            title=Content.of("Apprendre le solfège", level=0), reason="son envie s'est usée"),
    ], "goals")
    page = drawn(client, "/inspecteur/buts/clos")

    def entry(title):
        return page.split(title)[0].rsplit("<li", 1)[1] + page.split(title)[1].split("</li>")[0]

    assert "m-done" in entry("Lire sur la typographie")
    assert "Les polices pixel étaient dessinées" in entry("Lire sur la typographie").split('class="gl-result"')[1]
    assert "m-stuck" in entry("Trouver un hébergeur") and "trois séances sans verdict" in entry("Trouver un hébergeur")
    assert "m-dropped" in entry("Apprendre le solfège")
    tally = page.split('class="gl-tally"')[1].split("</p>")[0]
    assert "1</span> abouti" in tally and "1</span> bloqué" in tally and "sur cette page" in tally
    assert "Un but clos depuis plus de sept jours n'a plus de fiche" in page
    # sa fiche dit, accordé, s'il l'a raconté : « non (0 essai) », jamais « essai(s) »
    fiche = drawn(client, f"/inspecteur/fiche/goal/{dropped}")
    assert "non (0 essai)" in fiche and "essai(s)" not in fiche


def test_a_reminder_is_programmed_from_the_title_bar_and_joins_the_reminders(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    for url in ("/inspecteur/buts/vivants", "/inspecteur/buts/clos"):  # l'action de la destination, en haut
        bar = drawn(client, url).split('class="page-head-side"')[1].split('data-tab="')[0]
        assert "Programmer un rappel" in bar, url
    page = drawn(client, "/inspecteur/buts/vivants")
    link = re.search(r'href="(/inspecteur/action/goals\.programmer\?[^"]+)"', page)
    assert link, "quatre champs : l'action a sa page"
    form = drawn(client, link.group(1))
    for label in ("Ce qu'il faudra rappeler", "Quand", "Pour qui", "Vide : toi.", "Urgent (même la nuit)"):
        assert label in form, label
    # « Pour qui » peut rester vide (toi) : « — » en tête, choisi d'office, la liste n'est pas exigée
    owner = re.search(r'(<select name="owner"[^>]*>)(.*?)</select>', form, re.S)
    assert owner and " required" not in owner.group(1)
    assert owner.group(2).strip().startswith('<option value="">—</option>') and " selected" not in owner.group(2)
    frame = kernel.mind.frame()
    when = f"{local(now + 2 * DAY, frame.env.tz_of(frame.root)):%Y-%m-%dT%H:%M}"
    base = {"csrf": client.cookies.get("csrftoken"), "_retour": "/inspecteur/buts/vivants", "_sujet": "",
            "_champs": ["what", "when", "owner", "urgent"]}
    refused = client.post("/inspecteur/action/goals.programmer", follow_redirects=False,
                          data={**base, "_op": "g1", "what": " ", "when": "hier", "owner": "personne_x"})
    assert refused.status_code == 400
    assert "valeur requise" in refused.text and "date illisible" in refused.text and "personne inconnue" in refused.text

    def reminders():
        return [g for g in kernel.mind.frame().state("goals").goals.values() if g.kind == c.REMINDER]

    assert not reminders()
    done = client.post("/inspecteur/action/goals.programmer", follow_redirects=False,
                       data={**base, "_op": "g2", "what": "Arroser les plantes du balcon", "when": when, "owner": "",
                             "urgent": "on"})
    assert done.status_code == 303 and done.headers["location"].startswith("/inspecteur/buts/vivants")
    [g] = reminders()
    assert (g.authority, g.source, g.urgent) == (c.USER, "operator", True) and g.owner
    remind = drawn(client, "/inspecteur/buts/vivants").split('id="gl-remind-title"')[1]
    assert "Arroser les plantes du balcon" in remind
