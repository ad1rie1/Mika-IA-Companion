"""La mémoire de ce qui vient : les promesses qu'elle a faites, ce qui va
arriver dans la vie des autres, et ce qu'elle raconte de la sienne.

- « Je te demanderai comment ça s'est passé » est une promesse : à une
  personne (toutes ses adresses), notée une fois, qui finit par s'oublier si
  rien ne la règle — et qu'elle relit comme une phrase, pas comme une fiche
  technique ;
- « jeudi j'ai mon entretien chez Ubisoft » : elle y pense quand c'est
  proche, et le lendemain lui vient « alors, cet entretien ? » ;
- « j'ai ressorti mon fer à souder » : elle s'en souvient quelques jours,
  pour ne pas se contredire, puis ça s'efface.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.faculties.memory.faculty import MemoryParams
from mika.faculties.memory.salience import Item, dormant
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.events import Content, Origin
from mika.sim.clock import run_virtual
from tests.fixtures.harness import events_of
from tests.fixtures.memory import SIX, Script, chat, kept, section, seq_of, token
from tests.fixtures.mika import AFTERNOON, boot, build, connect, disconnect

LIFE = "CE QUI SE PASSE DANS SA VIE"
PROMISED = "CE QUE TU LUI AS PROMIS"


@pytest.mark.parametrize("asked", [True, False])
def test_a_coming_moment_comes_back_before_and_after(tmp_path, asked):
    """Lundi : « jeudi j'ai mon entretien chez Ubisoft ». Mardi, elle y pense
    (« jeudi, dans 2 jours ») ; vendredi, c'est passé : elle peut lui demander
    comment ça s'est passé — et quand elle l'a fait (« alors, cet entretien ? »),
    elle n'y revient plus. Contre-exemple (audit HUM-1) : l'avoir eu sous les
    yeux sans en parler ne l'éteint pas — le moment reste, pour qu'elle le
    demande. Bob, lui, n'en sait rien."""

    def extract(prompt):
        if "Ubisoft" not in prompt:
            return None
        return {"evenements": [{"texte": "son entretien chez Ubisoft", "personnes": [token(prompt, "Alice")],
                                "quand": "2026-10-01", "sensibilite": "personnel",
                                "messages": seq_of(prompt, "Ubisoft")}]}

    def reply(message):
        if asked and "hello" in message:
            return "Hello ! Alors, cet entretien, ça s'est passé comment ? [EMOTION:curious:0.5]"
        return None

    script = Script(extract, reply)
    kernel, clock, _, _out = build(tmp_path, script)
    assert AFTERNOON  # un lundi, 14 h

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["jeudi j'ai mon entretien chez Ubisoft, je stresse", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await asyncio.sleep(DAY / US)  # mardi
        await chat(kernel, "user_2", ["coucou, ça va ?"])
        await chat(kernel, "user_3", ["salut Mika"])
        await disconnect(kernel, "user_2")  # absente jusqu'à vendredi : rien ne le lui rappelle entre-temps
        await asyncio.sleep(3 * DAY / US)  # vendredi
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["hello Mika !"])
        facts = kernel.mind.frame().get(memory_c.LIFE_EVENTS("user_2"))
        await asyncio.sleep(3 * HOUR / US)
        await chat(kernel, "user_2", ["re !"])
        await kernel.stop()
        return facts

    facts = run_virtual(clock, main)
    tuesday, friday, later = (section(p, LIFE) for p in script.replies("user_2")[-3:])
    assert "son entretien chez Ubisoft" in tuesday and "jeudi" in tuesday and "dans 2 jours" in tuesday
    assert "hier" in friday and "comment ça s'est passé" in friday
    assert not any("Ubisoft" in p for p in script.prompts("user_3"))
    assert len(facts) == 1 and facts[0].about == ("user_2",)
    if asked:
        assert later == "", "elle lui a demandé : le moment n'est plus suivi"
        assert facts[0].followed_at > 0, "le fait le dit repris"
    else:
        # montré, pas dit : il reste — c'est encore la chose à lui demander
        assert "Ubisoft" in later and "c'est passé" in later
        assert facts[0].followed_at == 0


def test_a_promise_is_to_a_person_once_and_reads_like_a_sentence(tmp_path):
    """Sur son compte extérieur relié à son compte, Alice reçoit une promesse : la
    relecture suivante la voit (elle est à Alice, pas à une adresse), ne la
    note pas deux fois, et « ce que tu lui as promis » se lit comme une phrase."""
    calls: list[str] = []

    def extract(prompt):
        calls.append(prompt)
        if "concert" not in prompt.split("Les messages :")[1]:
            return None
        return {"promesses": [{"texte": "lui envoyer le lien du concert", "envers": token(prompt, "Alice")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await kernel.mind.append([identity_c.LINKED.draft(handle="ext_5", person="user_2")], emitter="identity",
                                 correlation="opérateur", origin=Origin.GENESIS)
        tg = {"channel": "external", "display_name": "Alice"}
        await chat(kernel, "ext_5", ["tu peux m'envoyer le lien du concert ?", *SIX[1:]], **tg)
        await asyncio.sleep(10 * 60)
        await chat(kernel, "ext_5", ["et le concert, tu as le lien ?", *SIX[1:]], **tg)
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_2", ["tu te souviens de ce que tu m'as promis ?"])
        promises = list(kernel.mind.root.slices["memory"].promises.values())
        await kernel.stop()
        return promises

    promises = run_virtual(clock, main)
    assert len(promises) == 1 and promises[0].to == "user_2", "une seule promesse, faite à Alice"
    assert "Promesses en cours" in calls[-1] and "lien du concert" in calls[-1], "la relecture suivante la voit"
    reply = script.replies("user_2")[-1]
    shown = section(reply, PROMISED)
    assert f"- lui envoyer le lien du concert — n° {promises[0].id}" in shown
    assert "memory_promise_done" not in shown and "[#" not in shown, "pas de mode d'emploi ni de fiche"
    tools = {t.name for r in script.calls if r.role == "reply" for t in r.tools}
    assert "memory_promise_done" in tools and "memory_promises" not in tools, "relire la section n'est pas un outil"


def test_a_vague_promise_fades_after_its_horizon(tmp_path):
    """« Je te dirai » n'a pas de date : elle reçoit l'horizon d'une promesse
    vague, puis, sans nouvelles, elle laisse filer — rien n'est dû pour toujours."""

    def extract(prompt):
        if "dirai" not in prompt.split("Les messages :")[1]:
            return None
        return {"promesses": [{"texte": "lui dire quel jeu elle a choisi", "envers": token(prompt, "Alice")}]}

    def reply(message):
        return "Je te dirai quel jeu je choisis, promis ! [EMOTION:happy:0.5]" if "jeu" in message else None

    script = Script(extract, reply)
    kernel, clock, _, _out = build(tmp_path, script)
    p = MemoryParams()

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["tu vas jouer à quel jeu ce soir ?", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        noted = list(kernel.mind.root.slices["memory"].promises.values())
        await asyncio.sleep((p.promise_horizon_days + p.promise_drop_days + 1) * DAY / US)
        left = list(kernel.mind.root.slices["memory"].promises.values())
        await kernel.stop()
        return noted, left

    noted, left = run_virtual(clock, main)
    assert len(noted) == 1 and noted[0].implicit_due
    assert abs(noted[0].due - noted[0].at - p.promise_horizon_days * DAY) < HOUR
    assert left == []
    resolved = [e.data for e in events_of(kernel, "memory.promise_resolved")]
    assert resolved and resolved[0].status == "dropped" and resolved[0].by == memory_c.EXPIRED_BY


def test_an_old_promise_without_a_date_is_not_owed_forever(tmp_path):
    """Une promesse notée sans échéance avant que les promesses vagues aient un
    horizon (le journal existant) reçoit le même en se rejouant : elle finit
    par s'oublier, elle aussi."""
    kernel, clock, _, _out = build(tmp_path, Script())
    p = MemoryParams()

    async def main():
        await boot(kernel)
        await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(text=Content.of("lui envoyer la recette", level=2),
                                                                  to="user_2", sensitivity=2)],
                                 emitter="memory", correlation="journal d'avant", origin=Origin.GENESIS)
        noted = list(kernel.mind.root.slices["memory"].promises.values())
        await asyncio.sleep((p.promise_horizon_days + p.promise_drop_days + 1) * DAY / US)
        left = list(kernel.mind.root.slices["memory"].promises.values())
        await kernel.stop()
        return noted, left

    noted, left = run_virtual(clock, main)
    assert len(noted) == 1 and noted[0].implicit_due
    assert abs(noted[0].due - noted[0].at - p.promise_horizon_days * DAY) < HOUR
    assert left == [], "rien n'est dû pour toujours"


def test_the_promises_shown_are_few_and_the_most_urgent(tmp_path):
    def extract(prompt):
        if "promets" not in prompt.split("Les messages :")[1]:
            return None
        who = token(prompt, "Alice")
        return {"promesses": [{"texte": f"lui envoyer la photo numéro {n}", "envers": who,
                               "echeance": f"2026-10-{n + 1:02d}"} for n in range(1, 8)]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["tu me promets de m'envoyer les photos ?", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_2", ["et ces photos alors ?"])
        await kernel.stop()

    run_virtual(clock, main)
    shown = section(script.replies("user_2")[-1], PROMISED)
    lines = [ln for ln in shown.splitlines() if ln.startswith("- ")]
    assert len(lines) == MemoryParams().max_promises
    assert "photo numéro 1 " in lines[0] and "photo numéro 7" not in shown, "les plus proches de leur échéance"


def test_what_she_says_of_her_own_life_is_kept_a_few_days(tmp_path):
    """« J'ai ressorti mon fer à souder » : le lendemain elle s'en souvient
    (anodin : à tout le monde), et ça ne la concerne qu'elle."""

    def extract(prompt):
        if "fer à souder" not in prompt:
            return None
        return {"croyances": [{"texte": "J'ai ressorti mon fer à souder pour réparer ma lampe", "sur_elle": True,
                               "personnes": ["Mika"], "sensibilite": "personnel", "importance": 3}]}

    def reply(message):
        return "J'ai ressorti mon fer à souder pour réparer ma lampe ! [EMOTION:happy:0.5]" if "fais" in message \
            else None

    script = Script(extract, reply)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["tu fais quoi de beau aujourd'hui ?", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await asyncio.sleep(DAY / US)
        await chat(kernel, "user_3", ["alors, tu as réparé ta lampe avec ton fer à souder ?"])
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    mine = next(r for r in rows if "fer à souder" in r["text"])
    assert mine["about"] == [] and mine["told_by"] == [] and mine["about_self"] and mine["sensitivity"] == 1
    assert "fer à souder" in section(script.replies("user_3")[-1], "CE QUI TE REVIENT")


def test_her_own_life_fades_in_days_not_months():
    p = MemoryParams()

    def belief(about_self):
        return Item(1, memory_c.BELIEF, "x", (), 1, 0.2, 0.8, "observed", None, None, 0, 0, 0, 0, "active",
                    about_self=about_self)

    week = 7 * DAY
    assert dormant(belief(True), week, p), "sa vie improvisée de la semaine dernière s'est effacée"
    assert not dormant(belief(False), week, p), "ce qu'on lui a appris, non"
    assert not dormant(belief(True), DAY, p), "mais le lendemain, elle s'en souvient"
