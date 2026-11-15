"""La nuit (M5, ADR 0036), par ses intentions.

- un journal par journée vécue ; une nuit manquée (serveur arrêté) se
  rattrape au matin ; une nuit blanche appartient encore à la veille ; une
  nuit coupée par une conversation fait réécrire le journal ; « [SILENCE] »
  n'est pas un journal ;
- le jour vécu se lit à un seul endroit (``self.faculty``), en clé comme en
  date ;
- le journal dit ce qu'elle a fait : un jour où elle a écrit sans réponse
  n'est pas « personne ne m'a parlé » ; une date en clair, aucun comptage ;
- le fil d'hier nomme les autres seulement pour qui peut entendre ce qui les
  concerne, et ne s'appelle « hier » que s'il l'était ;
- on se souvient d'un rêve une ou deux fois par semaine ; il revient le
  matin, une fois, et seulement à qui peut l'entendre ; un cauchemar demande
  une vraie menace ; ce que la nuit laisse se ressent au réveil ;
- le sommeil se lit de l'instant : un rêve tombe dans la première minute du
  sommeil paradoxal, et une nuit coupée finit, sans événement, dans la minute
  (ADR 0223) ; leurs échéances sont les instants que dit le corps (le début de
  la phase, la fin de la nuit coupée : ADR 0227) ; un tirage par cycle du
  corps, à son réglage : chaque phase paradoxale a le sien ;
- la nuit fond les souvenirs du jour presque identiques ;
- rejouer la nuit redonne exactement le même état.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import world as w
from mika.faculties.body import BodyParams
from mika.faculties.body import params as body_params
from mika.faculties.body import sleep as sl
from mika.faculties.goals.faculty import GoalsParams
from mika.faculties.self import SelfParams, days
from mika.faculties.self import night as self_night
from mika.faculties.self.faculty import day_of, lived_date, lived_day_of, night_of, starts_of
from mika.faculties.self.night import JournalArgs, dream_of, recall_chance, self_journal, vividness_of
from mika.faculties.self.records import Dream
from mika.faculties.world import WorldParams
from mika.faculties.world import plan as world_plan
from mika.faculties.world import timing as world_timing
from mika.kernel.clock import DAY, HOUR, MINUTE, US, instant
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.frame import Audience
from mika.kernel.inspect import Table
from mika.ports.llm import LLMResponse, ToolCall
from mika.runtime.bootstrap import ReadOnlyStore
from mika.runtime.inspection import Inspection
from mika.sim.clock import run_virtual
from mika.vocab import circadian
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, said


class Script:
    def __init__(self) -> None:
        self.journal = "J'ai parlé avec Alice de son chagrin, et avec Bob de cuisine."
        self.dream = "Je vole au-dessus d'un marché où Alice vend des nuages."
        self.tag = "[EMOTION:happy:0.5]"
        #: combien d'appels du journal échouent encore (une panne passagère)
        self.journal_fails = 0

    def __call__(self, req):
        if req.role == "extract":
            return LLMResponse("", tool_calls=(ToolCall("empty", "record_memories", {}),), stop="tool_use")
        if req.role in ("profile", "compact"):
            return LLMResponse("{}")
        if req.role == "journal":
            if self.journal_fails:
                self.journal_fails -= 1
                raise RuntimeError("panne passagère")
            return LLMResponse(self.journal)
        if req.role == "dream":
            return LLMResponse(self.dream)
        if req.role in ("murmur", "narrative"):
            return LLMResponse("hmm")
        return LLMResponse(f"d'accord {self.tag}")


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


def told_texts(kernel) -> dict[str, str]:
    """Ce qu'elle raconterait de chaque journée à n'importe qui (``self.journaled.shareable``), par journée."""
    journals = events(kernel, self_c.JOURNALED.name)
    refs = [j.data.shareable.ref for j in journals if j.data.shareable is not None]
    texts = kernel.mind.store.content(refs)
    return {j.data.day: texts.get(j.data.shareable.ref, "") for j in journals if j.data.shareable is not None}


async def until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


def souvenir(text, about=(), sensitivity=1, importance=0.6):
    return memory_c.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=about, sensitivity=sensitivity,
                                     importance=importance, emotion="happy")


async def genesis(kernel, *drafts):
    await kernel.mind.append(list(drafts), emitter="memory", correlation="genese", origin=Origin.GENESIS)


def build_run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 17, 0), script=None):
    script = script or Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm


def test_one_journal_per_lived_day(tmp_path):
    async def scenario(kernel):
        for d in range(3):
            await until(kernel, at_paris(2026, 9, 28, 18, 0) + d * DAY)
            p = await kernel.perceive(said("user_1", "coucou, bonne soirée"))
            await p.reply
        await until(kernel, at_paris(2026, 10, 1, 10, 0))
        return [e.data.day for e in events(kernel, self_c.JOURNALED.name)]

    days, _ = build_run(tmp_path, scenario)
    assert days == ["2026-09-28", "2026-09-29", "2026-09-30"]



def test_her_journal_keeps_no_tag_of_her_voice(tmp_path):
    """Sa voix pose parfois sa balise au bout de ce qu'elle écrit, par habitude : son journal se garde sans. Il se
    montre dans la console et lui revient quand elle le relit."""
    script = Script()
    script.journal = f"Une soirée tranquille, un mot de quelqu'un. {script.tag}\n[EN_FACE: rien]"

    async def scenario(kernel):
        await (await kernel.perceive(said("user_1", "coucou, bonne soirée"))).reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        journals = events(kernel, self_c.JOURNALED.name)
        return kernel.mind.store.content([j.data.text.ref for j in journals])

    texts, _ = build_run(tmp_path, scenario, script=script)
    assert list(texts.values()) == ["Une soirée tranquille, un mot de quelqu'un."]


def test_her_very_first_day_without_a_word_leaves_no_journal(tmp_path):
    """Une vie qui commence à 23 h 50 (une remise à zéro) : sa première « journée » a duré dix minutes et personne
    ne lui a rien dit. Un journal écrit sur ce vide s'inventait une attente (« je me demandais si quelqu'un allait se
    montrer »), et ses réponses du lendemain la reprenaient. Contre-exemple : le lendemain, on lui parle, et le
    journal de ce jour-là s'écrit."""
    async def scenario(kernel):
        await until(kernel, at_paris(2026, 9, 29, 18, 0))
        p = await kernel.perceive(said("user_1", "coucou, enfin un peu de temps"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 30, 10, 0))
        return [e.data.day for e in events(kernel, self_c.JOURNALED.name)]

    days, llm = build_run(tmp_path, scenario, start=at_paris(2026, 9, 28, 23, 50))
    assert days == ["2026-09-29"]
    assert len([c for c in llm.calls if c.role == "journal"]) == 1, "pas même un appel pour le jour vide"

def test_a_night_missed_with_the_server_off_is_written_in_the_morning(tmp_path):
    script = Script()
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 17, 0))

    async def first():
        await boot(kernel)
        p = await kernel.perceive(said("user_1", "coucou"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 18, 0))
        p = await kernel.perceive(said("user_1", "re-coucou"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 21, 0))
        await kernel.stop()  # le serveur s'arrête avant la nuit…

    run_virtual(clock, first)
    clock.advance_to(at_paris(2026, 9, 30, 9, 0))  # … et redémarre le lendemain matin
    kernel2, _, _, _ = build(tmp_path, script, clock=clock)

    async def second():
        await boot(kernel2)
        await asyncio.sleep(10 * MINUTE / US)
        days = [e.data.day for e in events(kernel2, self_c.JOURNALED.name)]
        await kernel2.stop()
        return days

    assert run_virtual(clock, second) == ["2026-09-28", "2026-09-29"]


def test_yesterdays_thread_tells_others_only_her_own_day(tmp_path):
    """Son journal intime parle de tout le monde : devant quelqu'un qui n'en est pas le seul concerné, elle a en
    tête sa journée à elle — ce qu'elle peut en raconter à n'importe qui, rendu d'après des faits où personne
    d'autre n'apparaît : jamais ce qu'Alice lui a dit, même prénom masqué (sonde réelle du 2026-10-02 : « il m'a
    demandé de ne rien dire à Chloé », lu à Chloé). Et ce n'est plus un modèle qui l'écrit : un appel par nuit, le
    journal intime (ADR 0053). Contre-exemple : un jour où seule Alice lui a parlé, Alice retrouve le journal
    entier."""
    async def scenario(kernel):
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "je suis triste ce soir"))).reply
        await connect(kernel, "user_2", "Bob")
        await (await kernel.perceive(said("user_2", "tu cuisines quoi ?"))).reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        for handle in ("user_1", "user_3"):
            await (await kernel.perceive(said(handle, "salut, bien dormi ?"))).reply
        await until(kernel, at_paris(2026, 9, 30, 18, 0))
        await (await kernel.perceive(said("user_1", "re ! ça va mieux"))).reply  # ce jour-là, seule Alice
        await until(kernel, at_paris(2026, 10, 1, 10, 0))
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        return told_texts(kernel)

    journals, llm = build_run(tmp_path, scenario)
    replies = [(c.meta.get("target"), c.messages[-1].content) for c in llm.calls if c.role == "reply"]
    told = journals["2026-09-28"]
    assert told.startswith("Tu as discuté avec deux personnes (")
    assert all(w not in told for w in ("Alice", "Bob", "triste", "cuisine")), "ce qu'elle raconte ne nomme personne"
    assert len([c for c in llm.calls if c.role == "journal"]) == len(journals)  # un appel par nuit : l'intime
    morning = {who: text for who, text in replies[2:4]}
    for who in ("user_1", "user_3"):
        assert "Tu as discuté avec deux personnes" in morning[who], who  # sa journée à elle…
        assert "chagrin" not in morning[who] and "cuisine" not in morning[who], who  # …jamais celle des autres
    assert "Alice de son chagrin" in replies[-1][1], "contre-exemple : seule concernée, Alice relit le journal"


def test_a_heavy_day_is_told_vaguely_but_truly(tmp_path):
    """Ce qu'elle raconte à n'importe qui d'une journée lourde (le chat d'un ami est mort, elle a été triste en lui
    répondant) : « un peu lourde », sans dire pourquoi — ni « rien de spécial », ni une activité qui n'a pas eu lieu,
    ni personne (sonde réelle du 2026-10-03 : « rien de spécial, des échanges tranquilles » le jour où Pixel est
    mort ; « j'ai bricolé un petit overlay pour mon stream », inventé). Contre-exemples : une journée légère est
    « bonne » ; une journée vide est calme, et se dit comme telle."""
    script = Script()
    script.tag = "[EMOTION:sad:0.8]"

    async def scenario(kernel):
        await kernel.set_params("goals", GoalsParams(musings_per_day=0))  # rien d'autre n'arrive de son côté
        await kernel.set_params("world", WorldParams(occupy_per_day=0))  # ni ne s'occupe d'elle-même (ADR 0098)
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Sam")
        for text in ["Pixel est parti cet après-midi", "on l'a endormi. j'étais avec lui jusqu'au bout",
                     "je vais essayer de dormir"]:
            await (await kernel.perceive(said("user_1", text))).reply
            await asyncio.sleep(2 * MINUTE / US)
        await until(kernel, at_paris(2026, 9, 29, 5, 30))
        script.tag = "[EMOTION:happy:0.7]"  # le mardi, tout ce qu'elle dit est léger
        await until(kernel, at_paris(2026, 9, 29, 18, 0))
        for text in ["coucou ! j'ai eu mon permis !!", "trop contente, on fête ça ce soir"]:
            await (await kernel.perceive(said("user_1", text))).reply
            await asyncio.sleep(2 * MINUTE / US)
        await until(kernel, at_paris(2026, 10, 1, 10, 0))  # le mercredi, personne
        await connect(kernel, "user_2", "Léo")
        await (await kernel.perceive(said("user_2", "salut, t'as fait quoi lundi ?"))).reply
        return told_texts(kernel)

    told, llm = build_run(tmp_path, scenario, start=at_paris(2026, 9, 28, 18, 0), script=script)
    monday, tuesday, wednesday = told["2026-09-28"], told["2026-09-29"], told["2026-09-30"]
    assert "Une journée un peu lourde." in monday
    assert "rien de spécial" not in monday and "rien de particulier" not in monday
    assert all(w not in monday for w in ("Sam", "Pixel", "endormi", "triste")), "ni qui, ni quoi, ni pourquoi"
    assert "de ton côté" not in monday and "vagabonder" not in monday, "aucune activité qui n'a pas eu lieu"
    assert "Une bonne journée." in tuesday and "lourde" not in tuesday
    assert wednesday == "Tu n'as parlé avec personne. Une journée calme, sans rien de particulier."
    to_leo = next(c.messages[-1].content for c in llm.calls if c.meta.get("target") == "user_2")
    assert "Pixel" not in to_leo and "Sam" not in to_leo


def test_her_own_day_tells_a_daydream_and_keeps_others_out(tmp_path):
    """Une journée où elle a rêvassé : ce qu'elle en raconte le dit (une rêverie, par son titre) — c'est sa vie à
    elle. Contre-exemple : ce à quoi elle a repensé pour quelqu'un, le même jour, n'y est pas (ça concerne Sam) ;
    son journal intime, lui, le sait."""
    title = "Rêvasser un peu autour du café"
    reflection = "Repenser à ce que « Sam » m'a confié"

    async def scenario(kernel):
        await kernel.set_params("goals", GoalsParams(musings_per_day=0))
        await connect(kernel, "user_1", "Sam")
        await (await kernel.perceive(said("user_1", "salut ! je file au boulot"))).reply
        mused = Content.of(title, level=0)
        mine = Content.of(reflection, level=2)
        await kernel.mind.append([
            goals_c.GOAL_CLOSED.draft(goal=1, status=goals_c.ACHIEVED, kind=goals_c.EXPLORATION,
                                      authority=goals_c.SELF, title=mused, reason=goals_c.MUSED, sensitivity=0),
            goals_c.GOAL_CLOSED.draft(goal=2, status=goals_c.ACHIEVED, kind=goals_c.EXPLORATION,
                                      authority=goals_c.SELF, title=mine, owner="user_1", about=("user_1",),
                                      sensitivity=2)], emitter="goals", correlation="buts", origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        return told_texts(kernel)

    told, llm = build_run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    monday = told["2026-09-28"]
    assert f"« {title} »" in monday and "rêverie" in monday
    assert "Sam" not in monday and "Repenser" not in monday
    notes = next(c.messages[-1].content for c in llm.calls if c.role == "journal")
    assert reflection in notes  # son journal intime, lui, sait ce qu'elle a fait pour Sam


async def intend(kernel, steps_of):
    """Elle se met à faire quelque chose dans sa chambre (comme si elle l'avait décidé)."""
    frame = kernel.mind.frame()
    s = frame.state("world")
    intent = world_plan.intent_of(w.MIKA, steps_of(s), frame.now, world_timing(None),
                                  w.Cause(source=w.Source.MIKA, actor=w.MIKA), f"i-{frame.now}")
    await kernel.mind.append([w.INTENDED.draft(intent=intent)], emitter="world", correlation="test:chambre",
                             origin=Origin.EXTERNAL)


def interacting(obj: str, action: str):
    return lambda s: world_plan.plan_interact(s.definition, world_timing(None), s.actors, s.objects, w.MIKA, obj,
                                              action)


def test_her_day_tells_what_she_did_in_her_room(tmp_path):
    """Un après-midi à dessiner à son bureau : ce qu'elle raconte de sa journée le dit, avec le moment (le fait
    ``world.lived``), et son journal intime le sait — de quoi raconter sa journée sans l'inventer (sonde réelle du
    2026-10-03 : un modèle comblait avec un stream qu'elle n'a jamais fait). Contre-exemple : une minute à regarder
    dehors ne se raconte pas."""

    async def scenario(kernel):
        await kernel.set_params("world", WorldParams(occupy_per_day=0))  # ce qu'on lui fait faire, rien d'elle-même
        await until(kernel, at_paris(2026, 9, 28, 15, 0))
        await intend(kernel, interacting("writing_desk", "dessiner"))
        await until(kernel, at_paris(2026, 9, 28, 16, 30))
        await intend(kernel, interacting("window_pane", "regarder_dehors"))
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        return told_texts(kernel)

    told, llm = build_run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    monday = told["2026-09-28"]
    assert "Dans ta chambre, tu as pris le temps de dessiner (ton bureau, l'après-midi, un long moment)." in monday, \
        monday
    assert "regarder dehors" not in monday, monday
    notes = next(c.messages[-1].content for c in llm.calls if c.role == "journal")
    assert "de dessiner (ton bureau" in notes


VOICE = VoiceProvenance(call_id="genese", persona_hash="-", role="dream", model="-")


@pytest.mark.parametrize("recall", [1.0, 0.0])
def test_a_remembered_dream_comes_back_once_in_the_morning(tmp_path, recall):
    """Un cauchemar très vif, et une mémoire des rêves réglée à fond : elle s'en
    souvient au réveil — il revient une fois, le matin. Réglée à zéro
    (contrôle) : il est oublié, rien ne revient."""

    async def scenario(kernel):
        await kernel.set_params("self", SelfParams(dream_chance=0.0, dream_recall=recall))
        await until(kernel, at_paris(2026, 9, 29, 2, 0))
        await kernel.mind.append([self_c.DREAMT.draft(
            night="2026-09-28", text=Content.of("CANARI-REVE je cours dans un couloir sans fin", level=1),
            voice=VOICE, kind=self_c.NIGHTMARE, vividness=1.0, emotion="scared")],
            emitter="self", correlation="rêve", origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        for text in ["salut !", "tu fais quoi ?"]:
            await (await kernel.perceive(said("user_1", text))).reply
        await until(kernel, at_paris(2026, 9, 29, 15, 0))
        await (await kernel.perceive(said("user_1", "et cet après-midi ?"))).reply
        return events(kernel, self_c.WOKE_WITH.name)

    woke, llm = build_run(tmp_path, scenario)
    replies = [c.messages[-1].content for c in llm.calls if c.role == "reply"]
    assert len(woke) == 1 and woke[0].data.night == "2026-09-28" and woke[0].data.vividness == 1.0
    assert woke[0].data.remembered == (recall > 0)
    if recall:
        assert "RÊVÉ CETTE NUIT" in replies[0] and "CANARI-REVE" in replies[0]  # le matin, il revient
        assert "RÊVÉ CETTE NUIT" not in replies[1]  # une fois : il s'est effacé en revenant
    assert all("CANARI-REVE" not in r for r in replies[(1 if recall else 0):])  # oublié, ou déjà raconté
    assert "RÊVÉ CETTE NUIT" not in replies[-1]  # l'après-midi, c'est passé


def _nights(n: int) -> list[tuple[int, int, sl.Sleep]]:
    p = BodyParams().sleep
    t0 = instant(datetime(2026, 1, 5, 9, 0, tzinfo=PARIS))
    out, start = [], None
    for kind, at, s in sl.transitions(sl.Sleep(), t0, t0 + (n + 1) * DAY, p, PARIS, limit=2 * n + 4):
        if kind == "fell_asleep":
            start = (at, s)
        elif start is not None:
            out.append((start[0], at, start[1]))
    return out[1:]


def _remembered_per_week(recall: float, nights: int = 210) -> float:
    """Ses nuits, avec les vraies fonctions : le sommeil paradoxal de chaque
    cycle du corps (``body.rem``), une chance d'y rêver (deux rêves au plus),
    leur vivacité, le souvenir au réveil."""
    sp, bp = SelfParams(), BodyParams().sleep
    rng = random.Random(7)
    moods = [["happy", "curious"], ["happy", "playful", "amused"], ["sad", "happy"], ["curious"],
             ["melancholic", "sad"], ["happy", "grateful"], ["anxious", "happy"], ["bored", "curious"]]
    remembered = 0
    lived = _nights(nights)
    for onset, wake, s in lived:
        tonight: list[Dream] = []
        tried: set[int] = set()
        t = onset
        while t < wake and len(tonight) < 2:
            rem = sl.rem_window(s, t, bp)
            if rem is not None and rem.start <= t < rem.end and rem.cycle not in tried:
                tried.add(rem.cycle)
                if rng.random() < sp.dream_chance:
                    emotions = rng.choice(moods)
                    # la sorte, c'est le modèle qui la dit (ADR 0153) : aucun de ces vécus n'en fait un cauchemar
                    kind = self_c.PLEASANT
                    tonight.append(Dream(len(tonight), "", "", kind, vividness_of(rng, kind, emotions), "dreamy",
                                         (), 1, t))
            t += 15 * MINUTE
        if tonight:
            best = max(tonight, key=lambda d: (d.vividness, -d.id))
            remembered += rng.random() < recall_chance(best, wake, recall, sp.dream_recent_us)
    return 7 * remembered / len(lived)


def test_she_remembers_a_dream_once_or_twice_a_week():
    assert 0.8 <= _remembered_per_week(SelfParams().dream_recall) <= 2.5
    assert _remembered_per_week(1.0) > 2.5  # contrôle : une mémoire des rêves à fond, presque chaque matin


def test_the_dream_says_its_own_kind():
    """La sorte d'un rêve, c'est le modèle qui la dit, sur sa dernière ligne (ADR 0153) : la balise est retirée du
    texte et colore le réveil ; absente ou inconnue, un rêve banal."""
    assert dream_of("Je cours dans un couloir sans fin.\n[RÊVE: nightmare]") == \
        ("Je cours dans un couloir sans fin.", self_c.NIGHTMARE, "scared")
    assert dream_of("Une plage, la nuit. [reve:Melancholic]")[1:] == (self_c.MELANCHOLIC, "melancholic")
    assert dream_of("Je vole.") == ("Je vole.", self_c.MUNDANE, "dreamy")
    assert dream_of("Je vole.\n[RÊVE: épique]")[:2] == ("Je vole.", self_c.MUNDANE)
    # une balise que sa voix ajoute par habitude part avec la sienne : le rêve se garde et se raconte sans
    assert dream_of("Je cours.\n[RÊVE: nightmare]\n[EMOTION: scared 0.6]")[:2] == ("Je cours.", self_c.NIGHTMARE)


def test_the_dreamer_sees_what_each_fragment_made_her_feel_and_names_the_kind(tmp_path):
    """Les fragments arrivent avec ce qu'ils lui ont fait ressentir — une information, aucun seuil ne choisit le ton ;
    le rêve gardé n'a plus sa balise, et sa sorte est celle que le modèle a dite."""
    script = Script()
    script.dream = "Je cherche Pixel dans une maison qui n'en finit pas.\n[RÊVE: melancholic]"

    async def scenario(kernel):
        await kernel.set_params("self", SelfParams(dream_chance=1.0))
        await genesis(kernel, memory_c.REMEMBERED.draft(
            text=Content.of("Adrien m'a dit que son chat Pixel est mort", level=2), about=("user_1",), sensitivity=2,
            importance=0.8, emotion="sad"))
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        dreams = events(kernel, self_c.DREAMT.name)
        return dreams, kernel.mind.store.content([d.data.text.ref for d in dreams])

    (dreams, texts), llm = build_run(tmp_path, scenario, script=script)
    asked = [c for c in llm.calls if c.role == "dream"]
    assert asked and "Pixel est mort (tristesse)" in asked[0].messages[-1].content
    assert "[RÊVE: …]" in asked[0].system_stable and "melancholic (" in asked[0].system_stable
    assert dreams and {d.data.kind for d in dreams} == {self_c.MELANCHOLIC}
    assert {d.data.emotion for d in dreams} == {"melancholic"}
    assert texts and all("RÊVE" not in t and "Pixel" in t for t in texts.values())


def test_a_dream_comes_in_the_first_minute_of_her_rem_sleep(tmp_path):
    """Le sommeil paradoxal se lit de l'instant, aucun événement ne l'annonce : le rêve tombe dans la première minute
    d'une phase, à l'instant que dit le corps (``body.rem``, ADR 0223, 0227). Relu « dans un quart d'heure », il venait
    jusqu'à quinze minutes plus tard dans la phase, ou la manquait."""

    async def scenario(kernel):
        await kernel.set_params("self", SelfParams(dream_chance=1.0))
        await genesis(kernel, souvenir("Alice m'a appris à pétrir le pain", about=("user_1",)))
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        frame = kernel.mind.frame()
        night = frame.state("body").sleep, body_params(frame.env.params_of("body", frame.root)).sleep
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        return night, events(kernel, self_c.DREAMT.name)

    ((sleep, bp), dreams), _ = build_run(tmp_path, scenario)
    assert sleep.asleep and dreams
    first = dreams[0].at
    assert sleep.since < first
    assert sl.phase(sleep, first, bp) is body_c.SleepPhase.REM
    assert sl.phase(sleep, first - MINUTE, bp) is not body_c.SleepPhase.REM, "la phase avait commencé plus tôt"


def test_her_dreams_count_the_cycles_of_her_body_as_it_is_set(tmp_path):
    """Un tirage par cycle, au réglage du corps (``body.rem``) : avec des cycles d'une heure, le sommeil paradoxal du
    deuxième cycle (118-120 min après l'endormissement) et celui du troisième (166-180 min) ont chacun le leur, et le
    second rêve vient au début du troisième. Compté sur une copie de 90 min, les deux tombaient au même index
    (166 // 90 = 1, déjà tiré) : le second rêve attendait le quatrième cycle (214 min)."""
    hourly = BodyParams(sleep=sl.SleepParams(cycle_us=60 * MINUTE))

    async def scenario(kernel):
        await kernel.set_params("body", hourly)
        await kernel.set_params("self", SelfParams(dream_chance=1.0))
        await genesis(kernel, souvenir("Alice m'a appris à pétrir le pain", about=("user_1",)))
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        sleep = kernel.mind.frame().state("body").sleep
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        return sleep, events(kernel, self_c.DREAMT.name)

    (sleep, dreams), _ = build_run(tmp_path, scenario)
    assert sleep.asleep and len(dreams) == 2
    windows = [sl.rem_window(sleep, d.at, hourly.sleep) for d in dreams]
    assert [w.cycle for w in windows] == [1, 2]
    assert all(w.start <= d.at < w.start + 2 * MINUTE for w, d in zip(windows, dreams, strict=True)), \
        "chacun dans la première minute de sa phase"
    assert 166 * MINUTE <= dreams[1].at - sleep.since < 168 * MINUTE


def test_her_dream_is_due_when_her_body_says_her_rem_sleep_begins(tmp_path):
    """L'échéance du rêve est l'instant que dit le corps (``body.rem``, ADR 0227), pas une relecture à la minute : en
    sommeil léger ou profond, le début de la prochaine phase paradoxale (relu chaque minute, il ne rendait rien) ;
    dedans, son début, déjà venu ; son cycle tiré, la fin de la phase, où ``body.rem`` dit la suivante. Après un rêve,
    la fin de l'écart (45 min) quand elle tombe dans la phase, sinon la fin de la phase ; ses deux rêves faits, rien."""
    dreaming = self_night.Dreaming

    async def scenario(kernel):
        await until(kernel, at_paris(2026, 9, 29, 1, 0))
        frame = kernel.mind.frame()
        since = frame.get(body_c.ASLEEP_SINCE)
        sleep, bp = frame.state("body").sleep, body_params(frame.env.params_of("body", frame.root)).sleep
        state, night = replace(frame.state("self"), dreams=()), night_of(frame, since)
        seen = []
        for t in range(since, since + 7 * HOUR, MINUTE):
            at = kernel.mind.frame(now=t)
            rem = at.get(body_c.REM)
            done = dreaming()
            done.tried.add((night, rem.cycle))
            seen.append((t, sl.phase(sleep, t, bp), rem, dreaming().next_due(state, at, None),
                         done.next_due(state, at, None)))

        def dreamt(*ats):
            return replace(state, dreams=tuple(
                Dream(id=i + 1, night=night, text_ref="", kind=self_c.PLEASANT, vividness=0.5, emotion="",
                      about=(), sensitivity=1, at=x) for i, x in enumerate(ats)))

        at = kernel.mind.frame(now=since + 95 * MINUTE)  # en sommeil léger, au début de son deuxième cycle
        w = at.get(body_c.REM)
        after = [dreaming().next_due(dreamt(*ats), at, None)
                 for ats in ((w.start - 30 * MINUTE,), (w.start - 5 * MINUTE,), (w.start - 3 * HOUR, w.start - HOUR))]
        return seen, at.now, w, after

    (seen, now, w, after), _ = build_run(tmp_path, scenario)
    resting = [x for x in seen if x[1] in (body_c.SleepPhase.LIGHT_SLEEP, body_c.SleepPhase.DEEP_SLEEP)]
    rem = [x for x in seen if x[1] is body_c.SleepPhase.REM]
    assert resting and rem and len(resting) + len(rem) == len(seen)
    assert all(t < r.start and due == r.start for t, _, r, due, _ in resting), "le début de la prochaine phase"
    assert all(r.start <= t < r.end and due == r.start for t, _, r, due, _ in rem), "la phase en cours : son début"
    assert all(done == r.end for _, _, r, _, done in seen), "son cycle tiré : la fin de la phase"
    assert w.cycle == 1 and now < w.start and 15 * MINUTE < w.end - w.start <= 40 * MINUTE
    spaced, late, both = after
    assert spaced == w.start + 15 * MINUTE, "45 min après le rêve, dans la phase"
    assert late == w.end, "l'écart passe la fin de la phase : la fin de la phase"
    assert both is None, "ses deux rêves de la nuit"


def test_a_night_cut_by_a_friend_ends_within_the_minute(tmp_path):
    """Une proche la tire du sommeil avant le matin et lui parle encore un peu : elle reste debout. Sa nuit finit au
    matin sans événement (``body.night_waking`` se lit de l'instant), et ce qu'elle en emporte (``self.woke_with``)
    vient dans la minute qui suit, à l'instant que dit le corps (``body.night_waking_until``, ADR 0223, 0227) — relu
    « dans un quart d'heure », jusqu'à quinze minutes plus tard."""

    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await until(kernel, at_paris(2026, 9, 29, 5, 30))
        for text in ["tu dors ?", "désolée, je n'arrive pas à dormir", "on se parle encore un peu ?"]:
            await (await kernel.perceive(said("user_1", text))).reply
            await asyncio.sleep(10 * MINUTE / US)
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        roused = events(kernel, body_c.ROUSED.name)
        asleep = [e for e in events(kernel, body_c.FELL_ASLEEP.name) if roused and e.at > roused[0].at]
        woke = [e.at for e in events(kernel, self_c.WOKE_WITH.name)]

        def waking(t):
            return kernel.mind.frame(now=t).get(body_c.NIGHT_WAKING)

        return roused, asleep, [(t, waking(t - MINUTE), waking(t)) for t in woke], waking(roused[0].at + US)

    (roused, asleep, woke, cut), _ = build_run(tmp_path, scenario)
    assert roused and cut, "tirée du sommeil pendant sa nuit"
    assert not asleep, "restée debout"
    assert len(woke) == 1
    [(at, before, after)] = woke
    assert before and not after, "dans la minute qui suit la fin de sa nuit"


def test_a_night_cut_short_is_due_at_the_end_her_body_says(tmp_path):
    """Tirée du sommeil puis debout, l'échéance de son réveil est la fin de sa nuit coupée, l'instant que dit le corps
    (``body.night_waking_until``, ADR 0227) : ``body.night_waking`` y tombe. Relue chaque minute, l'échéance ne
    rendait rien tant que la nuit n'était pas finie."""

    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await until(kernel, at_paris(2026, 9, 29, 5, 30))
        await (await kernel.perceive(said("user_1", "tu dors ?"))).reply
        frame = kernel.mind.frame()
        due = self_night.Wake().next_due(frame.state("self"), frame, None)

        def waking(t):
            return kernel.mind.frame(now=t).get(body_c.NIGHT_WAKING)

        return frame.now, frame.get(body_c.NIGHT_WAKING), frame.get(body_c.NIGHT_WAKING_UNTIL), due, \
            waking(due - 1) if due else None, waking(due) if due else None

    (now, cut, end, due, before, after), _ = build_run(tmp_path, scenario)
    assert cut and now < end, "tirée du sommeil, sa nuit pas finie"
    assert due == end
    assert before and not after, "sa nuit coupée finit à cet instant"


def test_what_the_night_leaves_is_felt_on_waking_not_at_three(tmp_path):
    """Une soirée triste : la nuit l'apaise ; ce soulagement (et la teinte d'un
    rêve) se pose au réveil — en pleine nuit, il se serait effacé avant le
    matin."""
    script = Script()
    script.tag = "[EMOTION:sad:0.85]"
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 20, 0))
    samples: list[tuple[int, float]] = []

    async def sampler():
        while True:
            m = kernel.mind.frame().get(affect_c.MOOD)
            samples.append((kernel.mind.clock.now(), m.position[0] - m.home[0]))
            await asyncio.sleep(MINUTE / US)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Alice")
            for text in ["ça va pas trop ce soir", "je me suis disputée avec ma mère", "je sais pas quoi faire"]:
                await (await kernel.perceive(said("user_1", text))).reply
                await asyncio.sleep(2 * MINUTE / US)
            await until(kernel, at_paris(2026, 9, 29, 1, 0))
            task = asyncio.ensure_future(sampler())
            await until(kernel, at_paris(2026, 9, 29, 9, 0))
            task.cancel()
            return events(kernel, "attention.digested"), events(kernel, self_c.WOKE_WITH.name)
        finally:
            await kernel.stop()

    digested, woke = run_virtual(clock, main)
    assert digested and digested[0].data.items and woke and woke[0].data.eased >= 1

    def jump(at: int) -> float:
        before = [v for t, v in samples if at - 2 * MINUTE <= t < at]
        after = [v for t, v in samples if at <= t <= at + 2 * MINUTE]
        return after[-1] - before[0]

    # au réveil, le soulagement se sent — une pensée apaisée (0,1), moins la teinte d'un rêve mélancolique oublié ;
    # avant l'ADR 0053, une seconde pensée (« Je bloque sur : Repenser à ce qu'Alice m'a confié », une réflexion
    # que le modèle laissait vide) s'apaisait aussi, et le saut dépassait 0,02
    assert jump(woke[0].at) > 0.005
    assert abs(jump(digested[0].at)) < 0.001  # pas en pleine nuit


def test_yesterday_is_only_called_yesterday_when_it_was(tmp_path):
    """Son journal du lundi : « hier » le mardi, « avant-hier » le mercredi, plus
    rien le vendredi (avant : « hier soir » même une semaine après)."""
    script = Script()
    script.journal = "[SILENCE]"  # elle n'écrit rien d'autre — et « [SILENCE] » n'est pas un journal

    async def scenario(kernel):
        await until(kernel, at_paris(2026, 9, 28, 23, 50))
        await kernel.mind.append([self_c.JOURNALED.draft(
            day="2026-09-28", text=Content.of("CANARI-JOURNAL une journée de pluie", level=2),
            voice=VOICE.model_copy(update={"role": "journal"}))],
            emitter="self", correlation="journal", origin=Origin.GENESIS)
        for day in (29, 30):
            await until(kernel, at_paris(2026, 9, day, 10, 0))
            await (await kernel.perceive(said("user_1", "salut"))).reply
        await until(kernel, at_paris(2026, 10, 2, 10, 0))
        await (await kernel.perceive(said("user_1", "salut"))).reply
        return events(kernel, self_c.JOURNALED.name)

    journals, llm = build_run(tmp_path, scenario, script=script)
    replies = [c.messages[-1].content for c in llm.calls if c.role == "reply"]
    assert "sur ta journée d'hier : CANARI-JOURNAL" in replies[0]
    assert "sur ta journée d'avant-hier (rien d'écrit pour hier) : CANARI-JOURNAL" in replies[1]
    assert "CANARI-JOURNAL" not in replies[2] and "TON FIL D'HIER" not in replies[2]
    assert [j.data.day for j in journals] == ["2026-09-28"]  # « [SILENCE] » n'a rien écrit
    assert any(c.role == "journal" for c in llm.calls)  # contrôle : elle a bien essayé


def test_a_white_night_belongs_to_the_day_before():
    profile = circadian.DEFAULT
    starts = days.day_starts(profile)
    assert starts == 5 * 60  # une heure avant son matin
    assert days.day_starts(profile.shifted(120)) == 7 * 60  # un oiseau de nuit commence plus tard
    tuesday = lambda h, m=0: instant(datetime(2026, 9, 29, h, m, tzinfo=PARIS))  # noqa: E731
    assert days.night_of(tuesday(6, 30), PARIS, starts).isoformat() == "2026-09-28"  # nuit blanche : la veille
    assert days.night_of(tuesday(1, 30), PARIS, starts).isoformat() == "2026-09-28"
    assert days.night_of(tuesday(23, 10), PARIS, starts).isoformat() == "2026-09-29"


def test_her_lived_day_is_read_in_one_place():
    """Dans un réducteur comme depuis un cadre, la même journée ; la nuit n'en garde pas de copie à elle."""
    tuesday = lambda h, m=0: instant(datetime(2026, 9, 29, h, m, tzinfo=PARIS))  # noqa: E731
    rhythm = circadian.DEFAULT
    frame = SimpleNamespace(now=tuesday(1, 30), root="mika", env=SimpleNamespace(tz_of=lambda _root: PARIS),
                            get=lambda key: rhythm if key == body_c.RHYTHM else None)
    cx = SimpleNamespace(tz=PARIS, facts={body_c.RHYTHM: rhythm})
    assert starts_of(frame) == days.day_starts(rhythm)
    assert lived_date(frame).isoformat() == lived_day_of(frame, frame.now) == day_of(cx, frame.now) == "2026-09-28"
    assert lived_date(frame, tuesday(9)).isoformat() == "2026-09-29"
    assert night_of(frame, tuesday(6, 30)) == "2026-09-28"  # une nuit blanche : la veille
    assert not any(hasattr(self_night, copy) for copy in ("_starts", "lived_day")) and self_night.night_of is night_of


def test_a_night_cut_by_a_conversation_rewrites_the_journal(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "coucou, bonne soirée"))).reply
        await until(kernel, at_paris(2026, 9, 29, 1, 0))
        for text in ["CANARI-NUIT tu dors ?", "j'arrive pas à dormir", "bon, j'essaie, bonne nuit"]:
            await (await kernel.perceive(said("user_1", text))).reply
            await asyncio.sleep(3 * MINUTE / US)
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        return events(kernel, self_c.JOURNALED.name)

    journals, llm = build_run(tmp_path, scenario)
    assert [j.data.day for j in journals] == ["2026-09-28", "2026-09-28"]  # écrit, puis réécrit
    notes = [c.messages[-1].content for c in llm.calls if c.role == "journal" and not c.meta.get("purpose")]
    assert "CANARI-NUIT" not in notes[0] and "CANARI-NUIT" in notes[-1]


def test_a_day_she_wrote_without_answer_is_not_a_day_nobody_spoke(tmp_path):
    """Adrien est là, silencieux : elle lui écrit, sans réponse. Ses notes du
    soir le disent — pas « personne ne t'a parlé » ; une date en clair, aucun
    comptage."""

    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Adrien")
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        return [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE"]

    initiatives, llm = build_run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert initiatives  # elle a bien écrit d'elle-même
    notes = next(c.messages[-1].content for c in llm.calls if c.role == "journal")
    assert notes.startswith("Ta journée du lundi 28 septembre.")
    assert "c'est toi qui as écrit" in notes and "« Adrien »" in notes and "pas de réponse" in notes
    assert "Personne ne t'a parlé" not in notes and "Tu n'as parlé avec personne" not in notes
    assert "2026-09-28" not in notes and "message)" not in notes and "messages)" not in notes


def test_a_day_with_answers_says_who_spoke_and_when(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Adrien")
        await until(kernel, at_paris(2026, 9, 28, 18, 30))
        await (await kernel.perceive(said("user_1", "salut mika, je suis crevé"))).reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))

    _, llm = build_run(tmp_path, scenario)
    notes = next(c.messages[-1].content for c in llm.calls if c.role == "journal")
    assert "Avec « Adrien » (le soir) : on t'a dit, entre autres, « salut mika, je suis crevé »." in notes
    # ce qu'elle a répondu, et sur quel ton — jamais ses phrases, qu'un modèle recopiait telles quelles (sonde réelle
    # du 2026-10-03 : « Hey Sam ! Je viens de penser à toi… prendre… ») ; ce qu'on lui a dit, oui (ci-dessus)
    assert "Tu lui as répondu, plutôt contente." in notes
    assert "d'accord" not in notes


def _goal(gid: int, title: str, status: str):
    content = Content.of(title, level=1)
    return [goals_c.GOAL_OPENED.draft(kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=content),
            goals_c.GOAL_CLOSED.draft(goal=gid, status=status, kind=goals_c.EXPLORATION, authority=goals_c.SELF,
                                      title=content)]


def test_her_journal_says_what_she_did_promised_and_how_her_mood_turned(tmp_path):
    """Ce qu'elle a fait de son côté (mené à bout, bloqué), ce qu'elle a promis
    et à qui, comment son humeur a tourné du matin au soir — de cette journée
    seulement : ce qu'elle a fait la veille n'y est pas."""
    script = Script()

    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Adrien")
        await kernel.mind.append(_goal(1, "CANARI-VEILLE ranger ses notes", goals_c.ACHIEVED), emitter="goals",
                                 correlation="veille", origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        await (await kernel.perceive(said("user_1", "coucou, bien dormi ?"))).reply
        await kernel.mind.append(_goal(2, "Comprendre les marées", goals_c.ACHIEVED)
                                 + _goal(3, "Réparer son vieux lecteur", goals_c.STUCK), emitter="goals",
                                 correlation="buts", origin=Origin.GENESIS)
        await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(text=Content.of("lui envoyer la recette", level=1),
                                                                 to="user_1")],
                                 emitter="memory", correlation="promesse", origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 17, 55))
        script.tag = "[EMOTION:sad:0.6]"  # le soir, tout ce qu'elle dit est triste
        await until(kernel, at_paris(2026, 9, 29, 19, 0))
        await (await kernel.perceive(said("user_1", "ma journée était nulle"))).reply
        await until(kernel, at_paris(2026, 9, 30, 10, 0))

    _, llm = build_run(tmp_path, scenario, start=at_paris(2026, 9, 28, 17, 0), script=script)
    notes = [c.messages[-1].content for c in llm.calls if c.role == "journal"]
    tuesday = next(n for n in notes if n.startswith("Ta journée du mardi 29 septembre."))
    assert "Ce que tu as fait de ton côté : " in tuesday
    assert "tu as mené à bout « Comprendre les marées »" in tuesday
    assert "tu as bloqué sur « Réparer son vieux lecteur »" in tuesday
    assert "CANARI-VEILLE" not in tuesday  # la veille n'est pas cette journée
    assert "Ce que tu as promis : « lui envoyer la recette » (à « Adrien »)." in tuesday
    # le soir, elle est triste ; si elle écrit encore à Adrien avant de s'endormir (vers 23 h, il est là et elle
    # est éveillée : une initiative ordinaire, qu'un murmure « sans suite » retient une fois sur cinq — un tirage),
    # ce dernier mot compte pour « la nuit », triste lui aussi
    mood = next(line for line in tuesday.splitlines() if line.startswith("Ton humeur en parlant : "))
    evening = "Ton humeur en parlant : le matin, plutôt contente ; l'après-midi, plutôt contente ; le soir, plutôt triste"
    assert mood in (evening + ".", evening + " ; la nuit, plutôt triste.")


def test_a_late_journal_tells_the_day_with_its_own_thoughts_and_counts_the_same_deed_once(tmp_path):
    """Un journal écrit en retard, le lendemain matin (nuit manquée, serveur arrêté) : une pensée née ce matin-là
    n'est pas « ce qui la travaillait » la veille ; trois explorations menées à bout sous un même titre se disent
    une fois, avec le compte — la liste répétait six fois la même phrase (2026-10-22, ADR 0127)."""
    script = Script()
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 17, 0))
    same = "En savoir plus sur ce que j'ai remarqué dans mes flux"

    async def first():
        await boot(kernel)
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        await kernel.mind.append(_goal(1, same, goals_c.ACHIEVED) + _goal(2, same, goals_c.ACHIEVED)
                                 + _goal(3, same, goals_c.ACHIEVED), emitter="goals", correlation="buts",
                                 origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 21, 0))
        await kernel.stop()  # le serveur s'arrête avant la nuit…

    run_virtual(clock, first)
    clock.advance_to(at_paris(2026, 9, 30, 9, 0))  # … et redémarre le lendemain matin
    script.journal_fails = 1  # le premier essai du matin échoue : elle réessaie une demi-heure plus tard
    kernel2, _, llm2, _ = build(tmp_path, script, clock=clock)

    async def second():
        await boot(kernel2)
        await asyncio.sleep(5 * MINUTE / US)
        assert script.journal_fails == 0, "le premier essai a eu lieu, avant la pensée du matin"
        # ce matin, entre deux essais du journal de la veille, elle lit autre chose
        await kernel2.mind.append([attention_c.THOUGHT_BORN.draft(
            text=Content.of("CANARI-MATIN la mort d'un écrivain", level=0), emotion="curious", intensity=0.9,
            origin=attention_c.SIGNAL, about=(), sensitivity=0)], emitter="attention", correlation="pensée",
            origin=Origin.GENESIS)
        await asyncio.sleep(40 * MINUTE / US)
        await kernel2.stop()

    run_virtual(clock, second)
    notes = [c.messages[-1].content for c in llm2.calls if c.role == "journal"]
    *_, tuesday = (n for n in notes if n.startswith("Ta journée du mardi 29 septembre."))  # l'essai qui a réussi
    morning = kernel2.mind.frame().get(attention_c.THOUGHTS)
    assert any(t.born_at > at_paris(2026, 9, 30, 0, 0) for t in morning)  # vivante au moment du journal
    assert "CANARI-MATIN" not in tuesday, tuesday
    done = f"tu as mené à bout « {same} »"
    assert f"{done} (3 fois)" in tuesday and tuesday.count(done) == 1, tuesday


def test_a_dream_made_of_a_confidence_is_not_told_to_someone_else(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("CANARI-REVE Alice m'a confié sa rechute", about=("user_9",), sensitivity=3,
                                       importance=0.9))
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        p = await kernel.perceive(said("user_2", "bien dormi ?"))
        await p.reply
        return events(kernel, self_c.DREAMT.name)

    dreams, llm = build_run(tmp_path, scenario)
    assert dreams and all(d.data.sensitivity == 3 for d in dreams)
    to_bob = [c.messages[-1].content for c in llm.calls if c.role == "reply"]
    assert to_bob and "RÊVÉ" not in to_bob[-1]


def test_the_night_merges_near_duplicate_memories_of_the_day(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("Alice m'a appris une recette de soupe au potiron", importance=0.4))
        await until(kernel, at_paris(2026, 9, 28, 19, 0))
        await genesis(kernel, souvenir("Alice m'a appris une recette de soupe au potiron", importance=0.8),
                      souvenir("Bob m'a parlé de son voyage au Japon"))
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        rows = kernel.mind.store.query_mind(f"SELECT text, status, importance FROM {memory_c.ITEMS_TABLE}")
        return rows, events(kernel, memory_c.NIGHT_SORTED.name)

    (rows, sorted_), _ = build_run(tmp_path, scenario)
    soup = [(status, importance) for text, status, importance in rows if "potiron" in text]
    assert sorted(soup) == [("active", 0.8), ("merged", 0.8)]
    assert len(sorted_) == 1 and len(sorted_[0].data.merges) == 1


def test_the_night_replays_to_the_same_state(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("J'ai ri d'une histoire de chats"))
        p = await kernel.perceive(said("user_1", "je suis triste ce soir, vraiment"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        owners = ["self", "attention", "affect", "memory", "body"]
        live = digest({o: kernel.mind.root.slices[o] for o in owners})
        await kernel.mind.rebuild(owners)
        return live, digest({o: kernel.mind.root.slices[o] for o in owners})

    (live, rebuilt), _ = build_run(tmp_path, scenario)
    assert live == rebuilt


def _journal(day: str, text: str):
    return self_c.JOURNALED.draft(day=day, text=Content.of(text, level=2),
                                  voice=VOICE.model_copy(update={"role": "journal"}))


@pytest.mark.parametrize("written", [14, 15])
def test_her_nights_page_only_offers_more_when_there_is_more(tmp_path, written):
    """Exactement une page de nuits : pas de « plus anciens » qui mènerait à une
    page vide ; une de plus : le lien, et la suite."""
    script = Script()
    script.journal = "[SILENCE]"

    async def scenario(kernel):
        await kernel.mind.append([_journal(f"2026-08-{d:02d}", f"journal {d}") for d in range(1, written + 1)],
                                 emitter="self", correlation="journaux", origin=Origin.GENESIS)
        ins = Inspection(kernel)
        return ins.run(ins.find("self", "nuits"), {})

    blocks, _ = build_run(tmp_path, scenario, script=script)
    history = next(b for b in blocks if isinstance(b, Table) and b.title == "Toutes ses nuits")
    assert len(history.rows) == 14
    assert bool(history.pager.older) == (written > 14)


def test_paging_through_her_nights_reads_no_preview_text(tmp_path, monkeypatch):
    """En feuilletant « Toutes ses nuits » (``?avant=``), la vue ne rend que
    l'historique : elle ne va pas chercher au magasin les textes de l'aperçu,
    qu'elle jetterait. La première page, elle, les lit."""
    script = Script()
    script.journal = "[SILENCE]"
    reads: list[list[str]] = []
    real = ReadOnlyStore.content

    def counted(self, refs):
        reads.append(list(refs))
        return real(self, refs)

    async def scenario(kernel):
        await kernel.mind.append([_journal(f"2026-08-{d:02d}", f"journal {d}") for d in range(1, 16)],
                                 emitter="self", correlation="journaux", origin=Origin.GENESIS)
        ins = Inspection(kernel)
        monkeypatch.setattr(ReadOnlyStore, "content", counted)
        first = ins.run(ins.find("self", "nuits"), {})
        read_first = len(reads)
        older = dict(next(b for b in first if isinstance(b, Table) and b.title == "Toutes ses nuits").pager.older)
        page = ins.run(ins.find("self", "nuits"), older)
        return read_first, len(reads) - read_first, page

    (read_first, read_paging, page), _ = build_run(tmp_path, scenario, script=script)
    assert read_first  # l'aperçu lit bien ses textes : la mesure n'est pas vide
    assert read_paging == 0
    assert [b.title for b in page] == ["Toutes ses nuits"] and len(page[0].rows) == 1


def test_she_rereads_an_older_journal_on_demand_not_yesterdays(tmp_path):
    """Les sections présentes ne se relisent pas par un outil (« attends, je
    vérifie ») ; un journal plus ancien, si."""
    script = Script()
    script.journal = "[SILENCE]"

    async def scenario(kernel):
        await kernel.mind.append([_journal("2026-09-26", "CANARI-SAMEDI la pluie"),
                                  _journal("2026-09-28", "CANARI-LUNDI le soleil")],
                                 emitter="self", correlation="journaux", origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        await (await kernel.perceive(said("user_1", "salut"))).reply
        # toi, connectée : sa condition (ni une inconnue, ni un salon) tient
        aud = Audience(persons=("user_1",), channel="web", public=False, level=3, witness_level=3, private_ok=True,
                       trust="authenticated", owner=True)
        frame = kernel.mind.frame(audience=aud)
        ctx = SimpleNamespace(frame=frame, state=frame.state("self"), ports=kernel.ports)
        # une inconnue : son gestionnaire revérifie la condition que l'offre a jugée (ADR 0148, 0226)
        stranger = kernel.mind.frame(audience=Audience(persons=("web_x",), channel="web", public=False, level=3,
                                                       witness_level=3, trust="public"))
        refused = await self_journal(JournalArgs(days_ago=3), SimpleNamespace(
            frame=stranger, state=stranger.state("self"), ports=kernel.ports))
        return (await self_journal(JournalArgs(days_ago=3), ctx), await self_journal(JournalArgs(days_ago=2), ctx),
                refused)

    (saturday, sunday, refused), llm = build_run(tmp_path, scenario, script=script)
    assert "CANARI-SAMEDI" in saturday and "samedi 26 septembre" in saturday
    assert sunday == "Tu n'as rien écrit sur ta journée du dimanche 27 septembre."
    assert refused == "Tu n'as rien écrit sur ta journée du samedi 26 septembre."
    reply = next(c for c in llm.calls if c.role == "reply")
    offered = {t.name for t in reply.tools}
    assert not offered & {"self_read", "self_yesterday", "self_dream"}  # ils relisaient une section présente
    assert "self : relire ce que tu as écrit dans ton journal un jour passé" in reply.system_stable
    assert "CANARI-LUNDI" in reply.messages[-1].content  # hier, elle l'a déjà en tête


