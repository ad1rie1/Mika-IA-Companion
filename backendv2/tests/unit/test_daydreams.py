"""Une rêverie n'est ni une nouvelle ni un exploit (ADR 0047, HUM-3 / HUM-19), par ses intentions.

Sans flux où chercher du neuf, sa curiosité la fait rêvasser autour d'un de ses centres d'intérêt : elle l'écrit,
et c'est tout. Rien n'est arrivé :

- ce n'est pas une matière d'initiative (« Ce que tu as fini, cet après-midi : Rêvasser… ») ;
- ce n'est pas « mené à bout » dans ce qu'elle a en train, ni dans son journal (qui la dit une fois, comme une
  rêverie) ;
- ce n'est pas un exploit : une semaine de rêveries laisse son estime où elle était.

Contre-exemple : une exploration qui a vraiment lu ses flux, prouvée, reste une matière et la relève un peu.
"""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from mika.contracts import goals as goals_c
from mika.contracts import needs as needs_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.goals.faculty import GoalsParams
from mika.faculties.goals.tend import lowered, of_words, short
from mika.kernel.clock import DAY, HOUR, US, local
from mika.kernel.events import Content, Origin
from mika.sim.llm.persona import _section
from tests.fixtures.mika import DOC, PARIS, at_paris, befriend, connect, said
from tests.unit.test_goals import run

MONDAY_8H = at_paris(2026, 9, 28, 8, 0)


def _musings(r):
    return [e for e in r.of(goals_c.GOAL_CLOSED) if e.data.reason == goals_c.MUSED]


@pytest.mark.slow
def test_a_week_of_daydreams_is_neither_news_nor_pride(tmp_path):
    async def scenario(kernel, llm):
        await kernel.set_params("goals", GoalsParams(seed_curiosity_from=0.0))
        await asyncio.sleep(7 * DAY / US)
        frame = kernel.mind.frame()
        return frame.get(self_c.ESTEEM), kernel.mind.root.slices["self"].deeds

    r = run(tmp_path, scenario, start=MONDAY_8H)
    esteem, deeds = r.result
    mused = _musings(r)
    assert len(mused) >= 5, "elle a rêvassé toute la semaine (sinon le test ne prouve rien)"
    assert abs(esteem - 0.5) <= 0.02, esteem  # avant : +0,02 par rêverie, « prouvée »
    kinds = {d.what for d in deeds}
    assert "mused" in kinds and not {"done", "opened"} & kinds  # ni « mené à bout », ni « tu t'es lancée dans »
    journals = [c.messages[-1].content for c in r.llm.calls if c.role == "journal"]
    assert journals
    for notes in journals:
        assert "mené à bout" not in notes and "t'es lancée" not in notes
        assert notes.count("esprit vagabonder") <= 1  # dite une fois, comme une rêverie
    assert any("esprit vagabonder" in n for n in journals)


def test_an_evening_greeting_after_a_day_of_daydreams_has_nothing_finished_to_tell(tmp_path):
    async def scenario(kernel, llm):
        await kernel.set_params("goals", GoalsParams(seed_curiosity_from=0.0))
        await asyncio.sleep(11 * HOUR / US)  # 8 h → 19 h : elle rêvasse
        await befriend(kernel, "user_1", social_c.FRIEND)
        matter = kernel.mind.frame().get(needs_c.MATTER("user_1"))
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(HOUR / US)
        return matter

    r = run(tmp_path, scenario, start=MONDAY_8H)
    assert _musings(r), "elle a rêvassé dans la journée"
    assert r.result is None or r.result.kind != needs_c.DONE_MATTER  # pas « Ce que tu as fini »
    greetings = [c.messages[-1].content for c in r.llm.calls if c.role == "initiative"]
    assert greetings, "elle salue Adrien qui arrive"
    for prompt in greetings:
        assert "mené à bout" not in prompt and "Ce que tu as fini" not in prompt
        assert "Rêvasser" not in prompt  # en initiative, ses rêveries ne sont même pas montrées


def test_a_real_exploration_stays_something_to_tell_and_lifts_her_a_little(tmp_path):
    """Contre-exemple : elle a vraiment lu ses flux (un outil qui produit), c'est prouvé — une matière, un peu
    d'estime."""
    async def scenario(kernel, llm):
        title = Content.of("Fouiller un peu du côté du café", level=0)
        await kernel.mind.append([
            goals_c.GOAL_OPENED.draft(kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=title,
                                      bundles=("goals", "memory", "projects", "rss"), source="interest:Le café",
                                      sensitivity=0, origin=goals_c.FROM_INTEREST, desire=1.0, max_steps=3),
            goals_c.STEP_REPORTED.draft(goal=1, verdict=goals_c.DONE, summary=Content.of("lu un article", level=0),
                                        proven=True, tools=("rss_read",)),
            goals_c.GOAL_CLOSED.draft(goal=1, status=goals_c.ACHIEVED, kind=goals_c.EXPLORATION,
                                      authority=goals_c.SELF, title=title, source="interest:Le café", sensitivity=0)],
            emitter="goals", correlation="genese", origin=Origin.GENESIS)
        await befriend(kernel, "user_1", social_c.FRIEND)
        frame = kernel.mind.frame()
        return frame.get(needs_c.MATTER("user_1")), frame.get(self_c.ESTEEM)

    matter, esteem = run(tmp_path, scenario, start=MONDAY_8H).result
    assert matter is not None and matter.kind == needs_c.DONE_MATTER
    assert esteem > 0.505


def _musings(r) -> list:
    return [o.at for o in r.of(goals_c.GOAL_OPENED) if o.data.origin in goals_c.MUSING_ORIGINS]


@pytest.mark.parametrize(("cap", "most"), [(2, 2), (6, 3)])
def test_she_daydreams_a_few_times_a_day_not_every_two_hours(tmp_path, cap, most):
    """Une personne rêvasse moins souvent (sonde réelle du 2026-10-03 : quatre à cinq rêveries par jour, trois
    appels chacune) : au plus ``musings_per_day`` par jour, même quand sa curiosité ne retombe jamais — et étalées
    sur sa journée, pas deux d'affilée le matin puis plus rien. Contre-exemple : réglé plus haut, la même curiosité
    en ouvre davantage."""
    async def scenario(kernel, llm):
        await kernel.set_params("goals", GoalsParams(seed_curiosity_from=0.0, musings_per_day=cap))
        await asyncio.sleep(3 * DAY / US)

    opened = _musings(run(tmp_path, scenario, start=MONDAY_8H))
    days = Counter(local(t, PARIS).date() for t in opened)
    if cap == 2:
        assert len(days) >= 3, "elle a rêvassé chaque jour (sinon le test ne prouve rien)"
        assert max(days.values()) <= 2
        same_day = [b - a for a, b in zip(opened, opened[1:], strict=False)
                    if local(a, PARIS).date() == local(b, PARIS).date()]
        assert same_day and min(same_day) >= 5 * HOUR  # une le matin, une l'après-midi
    else:  # sans plafond serré, ses cinq centres d'intérêt y passent dès le premier jour
        assert max(days.values()) >= most


def test_what_a_friend_made_her_discover_is_the_seed_of_her_next_daydream(tmp_path):
    """Ce qu'une amie lui a fait découvrir la fait rêvasser avant ses centres d'intérêt de toujours (sonde réelle du
    2026-10-03 : Inès lui parle de city pop japonaise, elle rêvasse ensuite à la cuisine, au café, à la bidouille).
    Une rêverie dit « j'aimerais », pas « je fais ». Contre-exemple : « je le note, merci » ne porte aucun sujet."""
    async def scenario(kernel, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Inès")
        await (await kernel.perceive(said("user_1", "je le note, merci"))).reply
        await (await kernel.perceive(said("user_1", "tu devrais écouter de la city pop japonaise, Mariya Takeuchi "
                                                    "c'est trop beau"))).reply
        await kernel.set_params("goals", GoalsParams(seed_curiosity_from=0.0))
        await asyncio.sleep(3 * HOUR / US)

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 10, 0))
    musings = [o for o in r.of(goals_c.GOAL_OPENED) if o.data.origin in goals_c.MUSING_ORIGINS]
    first = musings[0].data
    assert first.origin == goals_c.FROM_TALK and first.musing and first.about == ("user_1",)
    assert first.title.text == "Rêvasser à ce dont « Inès » m'a parlé" and "city pop" in first.details.text
    assert not [m for m in musings if "je le note" in (m.data.details.text or "")]
    step = next(c for c in r.llm.calls if c.role == "step")
    assert "city pop" in _section(step, "CE QUI L'A FAIT NAÎTRE")
    assert "pas ce que tu fais" in _section(step, "CE À QUOI TU TRAVAILLES")


def test_her_daydreams_are_titled_by_their_subject_in_good_french():
    """Le titre d'une exploration ne recopie plus la phrase de sa persona (« …sans être une hardcore ») : le sujet
    seul, avec l'article contracté."""
    titles = [f"Rêvasser un peu autour {of_words(lowered(short(i)))}" for i in DOC.interests]
    assert "Rêvasser un peu autour du café" in titles and "Rêvasser un peu autour de la cuisine" in titles
    assert not any("hardcore" in t or "théorie" in t or " de le " in t or " de les " in t for t in titles)
    assert of_words("les jeux rétro") == "des jeux rétro" and of_words("Outer Wilds") == "d'Outer Wilds"
    assert of_words("Hollow Knight") == "de Hollow Knight"
