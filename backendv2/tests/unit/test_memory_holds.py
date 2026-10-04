"""Ce qui tient dans sa mémoire (ADR 0046), par ses intentions.

- ce qu'elle a dit de ses goûts tient : son plat préféré du jour 1 est encore
  là le jour 20 ; une anecdote (« j'ai ressorti mon fer à souder »), non ; et
  quand elle change d'avis, la nouvelle croyance remplace l'ancienne, sans la
  confusion d'une croyance démentie (HUM-6) ;
- une croyance apprise il y a trois semaines dit depuis quand ; le modèle de la
  mémoire est prié d'écrire les dates en absolu (HUM-13) ;
- un souvenir vécu avec une proche s'endort moins vite qu'avec une inconnue
  (HUM-17).
"""

from __future__ import annotations

import asyncio
import re

from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.faculties.memory.faculty import MemoryParams
from mika.faculties.memory.salience import Item, dormant
from mika.kernel.clock import DAY, US
from mika.kernel.events import Content, Origin
from mika.sim.clock import run_virtual
from tests.fixtures.harness import events_of
from tests.fixtures.memory import SIX, Script, chat, kept, section
from tests.fixtures.mika import boot, build, connect

SAID = "CE QUE TU AS DÉJÀ DIT DE TOI"


def _known(prompt: str, needle: str) -> int | None:
    """Le numéro d'une croyance déjà connue montrée au modèle de la mémoire."""
    m = re.search(rf"^\[#(\d+)\] [^\n]*{re.escape(needle)}", prompt, re.M)
    return int(m.group(1)) if m else None


def test_what_she_said_she_likes_holds_an_anecdote_fades_and_a_change_of_mind_replaces(tmp_path):
    """Jour 1, Alice : « c'est quoi ton plat préféré ? » — « Les ramen, sans hésiter ! » ; et elle raconte qu'elle
    a ressorti son fer à souder. Jour 20 : « c'était quoi déjà ton plat préféré ? » — les ramen sont sous ses
    yeux (audit HUM-6 : elles s'endormaient en 3,7 jours) ; le fer à souder s'est effacé. Jour 21, elle change
    d'avis : les lasagnes remplacent les ramen, sans « je croyais que… »."""

    def extract(prompt):
        out = []
        if "Les ramen" in prompt:
            out.append({"texte": "Mon plat préféré, c'est les ramen", "sur_elle": True, "genre": "gout",
                        "importance": 3})
        if "fer à souder" in prompt:
            out.append({"texte": "J'ai ressorti mon fer à souder pour réparer ma lampe", "sur_elle": True,
                        "genre": "anecdote", "importance": 1})
        if "lasagnes" in prompt:
            out.append({"texte": "Mon plat préféré, ce sont les lasagnes maintenant", "sur_elle": True,
                        "genre": "gout", "importance": 3, "remplace": _known(prompt, "ramen")})
        return {"croyances": out} if out else None

    def reply(message):
        if "plat préféré" in message and "déjà" not in message:
            return "Les ramen, sans hésiter ! [EMOTION:happy:0.5]"
        if "fais quoi" in message:
            return "J'ai ressorti mon fer à souder pour réparer ma lampe ! [EMOTION:happy:0.5]"
        if "toujours" in message:
            return "Au fond, je préfère les lasagnes maintenant ! [EMOTION:playful:0.5]"
        return None

    script = Script(extract, reply)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["c'est quoi ton plat préféré ?", "et tu fais quoi de beau ?", *SIX[2:]])
        await asyncio.sleep(10 * 60)
        await asyncio.sleep(20 * DAY / US)
        await chat(kernel, "user_2", ["c'était quoi déjà ton plat préféré ?"])
        day20 = script.replies("user_2")[-1]
        await chat(kernel, "user_2", ["et c'est toujours les ramen ?", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        rows = kept(kernel)
        revisions = [e for e in events_of(kernel, attention_c.THOUGHT_BORN.name)
                     if e.data.origin == attention_c.REVISION]
        await kernel.stop()
        return day20, rows, revisions

    day20, rows, revisions = run_virtual(clock, main)
    said = section(day20, SAID)
    assert "ramen" in said, "ce qu'elle a dit aimer, vingt jours plus tard"
    assert "fer à souder" not in said + section(day20, "CE QUI TE REVIENT"), "une anecdote s'est effacée"
    ramen = next(r for r in rows if "ramen" in r["text"])
    lasagnes = next(r for r in rows if "lasagnes" in r["text"])
    soldering = next(r for r in rows if "fer à souder" in r["text"])
    assert ramen["about_self"] == 2 and soldering["about_self"] == 1
    assert ramen["status"] == "superseded" and lasagnes["status"] == "active" and lasagnes["about_self"] == 2
    assert revisions == [], "changer d'avis n'est pas une confusion"


def test_an_old_belief_says_since_when_and_the_memory_is_told_to_write_absolute_dates(tmp_path):
    """Trois semaines plus tard, « la sœur d'Alice, Léa, vient le week-end » se lit avec « appris il y a 3
    semaines » : elle ne le croit plus vrai pour ce week-end-ci (audit HUM-13). Contre-exemple : ce qu'elle a
    appris avant-hier ne porte pas de date."""
    script = Script()
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await kernel.mind.append([memory_c.BELIEVED.draft(
            text=Content.of("Alice m'a dit que sa sœur Léa vient la voir le week-end", level=2), about=("user_2",),
            sensitivity=2, told_by=("user_2",), heard_by=("user_2",))],
            emitter="memory", correlation="genese:vieille", origin=Origin.GENESIS)
        await asyncio.sleep(19 * DAY / US)
        await kernel.mind.append([memory_c.BELIEVED.draft(
            text=Content.of("Alice m'a dit que sa sœur Léa adore le théâtre", level=2), about=("user_2",),
            sensitivity=2, told_by=("user_2",), heard_by=("user_2",))],
            emitter="memory", correlation="genese:recente", origin=Origin.GENESIS)
        await asyncio.sleep(2 * DAY / US)
        await chat(kernel, "user_2", ["au fait, Léa vient la voir le week-end ?", "et Léa adore le théâtre ?",
                                      *SIX[2:]])
        await asyncio.sleep(10 * 60)
        await kernel.stop()

    run_virtual(clock, main)
    first, second = (section(r, "CE QUI TE REVIENT") for r in script.replies("user_2")[:2])
    old = next(line for line in first.splitlines() if "week-end" in line)
    recent = next(line for line in second.splitlines() if "théâtre" in line)
    assert "appris il y a 3 semaines" in old, first
    assert "appris" not in recent
    system = next(r.system_stable for r in script.calls if r.role == "extract")
    assert "Écris toute date en absolu" in system and "jamais « ce week-end »" in system


def test_a_memory_with_someone_she_holds_dear_sleeps_later():
    """Un souvenir notable (0,45), quatre mois plus tard : avec une inconnue, il dort ; avec une proche (lien
    1), il revient encore sur un indice moyen (audit HUM-17)."""
    p = MemoryParams()
    souvenir = Item(1, memory_c.SOUVENIR, "notre première soirée jeux", ("ext_1",), 1, 0.45, None, None, None, "happy",
                    0, 0, 0, 0, "active")
    four_months = 120 * DAY
    assert dormant(souvenir, four_months, p, bond=0.0), "avec une inconnue : endormi"
    assert not dormant(souvenir, four_months, p, bond=1.0), "avec une proche : encore là"
    assert dormant(souvenir, 2 * 365 * DAY, p, bond=1.0), "pas éternel pour autant"
