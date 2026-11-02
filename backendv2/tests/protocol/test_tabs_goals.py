"""Activité › Buts, chaque onglet dans sa forme (``app/handmade/tabs/goals.py``, ADR 0177), à travers le vrai serveur :
ses explorations et ses rappels côte à côte (les séances et l'envie d'une exploration, la date d'un rappel), ses buts
clos avec leur issue en marque et ce qu'ils ont donné — et ce qu'ils disent, vides."""

from __future__ import annotations

from mika.contracts import goals as c
from mika.kernel.clock import DAY, HOUR
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
