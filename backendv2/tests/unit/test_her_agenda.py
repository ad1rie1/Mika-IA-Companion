"""« L'agenda de Mika » (ADR 0309, lot 3b) : ses promesses datées et les moments qu'elle voit venir, lus dans sa
mémoire par sa porte et montrés comme un agenda (``app/her_agenda.py``), sur le vrai noyau composé.

- vu par Léa : ce qu'elle lui a promis, et les moments de sa vie qu'elle lui a racontés elle-même — rien de ce
  qu'Adrien a confié (sur elle comme sur lui), rien de secret, rien sans date ;
- vu de la console : tout, chaque date avec qui elle concerne, et d'où elle vient.
"""

from __future__ import annotations

from mika.app.her_agenda import MOMENT, PROMISE, her_agenda, title_of
from mika.contracts import memory as memory_c
from mika.kernel.clock import DAY, HOUR
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build, connect


async def _remembered(kernel, *drafts) -> None:
    await kernel.mind.append(list(drafts), emitter="memory", correlation="souvenirs", origin=Origin.GENESIS)


def _live(tmp_path, scenario):
    kernel, clock, _llm, _ = build(tmp_path, lambda req: LLMResponse("{}"))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Léa")
            return await scenario(kernel, clock.now())
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_her_agenda_seen_by_lea_shows_nothing_adrien_confided(tmp_path):
    async def scenario(kernel, now):
        await _remembered(
            kernel,
            memory_c.PROMISE_NOTICED.draft(text=Content.of("relire tes slides", level=2), to="user_2",
                                           due=now + DAY, all_day=True),
            memory_c.PROMISE_NOTICED.draft(text=Content.of("lui rappeler le contrôle technique", level=2),
                                           to="user_1", due=now + 2 * DAY),
            memory_c.PROMISE_NOTICED.draft(text=Content.of("lui envoyer la recette un jour", level=2), to="user_2",
                                           due=now + 9 * DAY, implicit_due=True),
            memory_c.EVENT_NOTED.draft(text=Content.of("son rendez-vous à la banque", level=2), when=now + 3 * DAY,
                                       all_day=False, about=("user_2",), told_by=("user_2",)),
            memory_c.EVENT_NOTED.draft(text=Content.of("la fête surprise pour Léa", level=2), when=now + 4 * DAY,
                                       about=("user_2",), told_by=("user_1",)),
            memory_c.EVENT_NOTED.draft(text=Content.of("son entretien d'embauche", level=2), when=now + 2 * DAY,
                                       about=("user_1",), told_by=("user_1",)),
            memory_c.EVENT_NOTED.draft(text=Content.of("sa prise de sang", level=3), when=now + 5 * DAY,
                                       about=("user_2",), told_by=("user_2",), secret=True),
            memory_c.EVENT_NOTED.draft(text=Content.of("son déménagement", level=2), when=now - DAY,
                                       about=("user_2",), told_by=("user_2",), ongoing=True))
        return her_agenda(kernel, person="user_2"), her_agenda(kernel), title_of(kernel), now

    lea, console, title, now = _live(tmp_path, scenario)
    assert title == "L'agenda de Mika"
    assert [d.title for d in lea] == ["relire tes slides", "son rendez-vous à la banque"]
    slides, bank = lea
    assert slides.kind == PROMISE and slides.all_day and slides.day and slides.ref.startswith("memory:")
    assert slides.source.startswith("Elle te l'a promis ")
    assert bank.kind == MOMENT and not bank.all_day and bank.start == now + 3 * DAY and bank.end == bank.start + HOUR
    assert bank.source.startswith("Tu le lui as raconté ")
    assert not any(d.secret for d in lea)
    # la console voit tout ce qui est daté, et pour qui ; ni la promesse vague, ni la situation qui dure
    assert {d.title for d in console} == {"relire tes slides", "lui rappeler le contrôle technique",
                                         "son rendez-vous à la banque", "la fête surprise pour Léa",
                                         "son entretien d'embauche", "sa prise de sang"}
    surprise = next(d for d in console if d.title == "la fête surprise pour Léa")
    assert surprise.persons == ("user_2",) and surprise.source.startswith("Adrien le lui a raconté")
    assert next(d for d in console if d.title == "sa prise de sang").secret
    assert next(d for d in console if d.title == "lui rappeler le contrôle technique").source.startswith(
        "Elle l'a promis à Adrien ")
    assert [d.start for d in console] == sorted(d.start for d in console)
