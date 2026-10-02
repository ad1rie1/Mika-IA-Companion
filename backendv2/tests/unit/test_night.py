"""La nuit (M5, ADR 0036), par ses intentions.

- un journal par journée vécue ; une nuit manquée (serveur arrêté) se
  rattrape au matin ; une nuit blanche appartient encore à la veille ; une
  nuit coupée par une conversation fait réécrire le journal ; « [SILENCE] »
  n'est pas un journal ;
- le journal dit ce qu'elle a fait : un jour où elle a écrit sans réponse
  n'est pas « personne ne m'a parlé » ; une date en clair, aucun comptage ;
- le fil d'hier nomme les autres seulement pour qui peut entendre ce qui les
  concerne, et ne s'appelle « hier » que s'il l'était ;
- on se souvient d'un rêve une ou deux fois par semaine ; il revient le
  matin, une fois, et seulement à qui peut l'entendre ; un cauchemar demande
  une vraie menace ; ce que la nuit laisse se ressent au réveil ;
- la nuit fond les souvenirs du jour presque identiques ;
- rejouer la nuit redonne exactement le même état.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from types import SimpleNamespace

import pytest

from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.body import BodyParams
from mika.faculties.body import sleep as sl
from mika.faculties.self import SelfParams, days
from mika.faculties.self.night import CYCLE, JournalArgs, classify, recall_chance, self_journal, vividness_of
from mika.faculties.self.records import Dream
from mika.kernel.clock import DAY, MINUTE, US, instant
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.frame import Audience
from mika.kernel.inspect import Table
from mika.ports.llm import LLMResponse
from mika.runtime.inspection import find, run_view
from mika.sim.clock import run_virtual
from mika.vocab import circadian
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, said


class Script:
    def __init__(self) -> None:
        self.journal = "J'ai parlé avec Alice de son chagrin, et avec Bob de cuisine."
        self.dream = "Je vole au-dessus d'un marché où Alice vend des nuages."
        self.tag = "[EMOTION:happy:0.5]"

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role == "journal":
            return LLMResponse(self.journal)
        if req.role == "dream":
            return LLMResponse(self.dream)
        if req.role in ("murmur", "narrative"):
            return LLMResponse("hmm")
        return LLMResponse(f"d'accord {self.tag}")


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


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


def test_yesterdays_thread_names_others_only_for_those_who_may_hear(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Alice")
        p = await kernel.perceive(said("user_1", "je suis triste ce soir"))
        await p.reply
        await connect(kernel, "user_2", "Bob")
        p = await kernel.perceive(said("user_2", "tu cuisines quoi ?"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        for handle in ("user_1", "user_3"):
            p = await kernel.perceive(said(handle, "salut, bien dormi ?"))
            await p.reply

    _, llm = build_run(tmp_path, scenario)
    last = {c.meta.get("target"): c.messages[-1].content for c in llm.calls if c.role == "reply"}
    assert "Alice de son chagrin" in last["user_1"]  # elle-même : son nom
    stranger = last["user_3"]
    assert "TON FIL D'HIER" in stranger and "Alice" not in stranger and "quelqu'un de son chagrin" in stranger


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
    cycle, une chance d'y rêver (deux rêves au plus), leur vivacité, le
    souvenir au réveil."""
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
            cycle = (t - onset) // CYCLE
            if sl.phase(s, t, bp) is body_c.SleepPhase.REM and cycle not in tried:
                tried.add(cycle)
                if rng.random() < sp.dream_chance:
                    emotions = rng.choice(moods)
                    kind, emotion = classify(emotions)
                    tonight.append(Dream(len(tonight), "", "", kind, vividness_of(rng, kind, emotions), emotion,
                                         (), 1, t))
            t += 15 * MINUTE
        if tonight:
            best = max(tonight, key=lambda d: (d.vividness, -d.id))
            remembered += rng.random() < recall_chance(best, wake, recall, sp.dream_recent_us)
    return 7 * remembered / len(lived)


def test_she_remembers_a_dream_once_or_twice_a_week():
    assert 0.8 <= _remembered_per_week(SelfParams().dream_recall) <= 2.5
    assert _remembered_per_week(1.0) > 2.5  # contrôle : une mémoire des rêves à fond, presque chaque matin


def test_a_nightmare_needs_a_real_threat():
    assert classify(["sad"])[0] == self_c.MELANCHOLIC  # un souvenir triste : un rêve mélancolique
    assert classify(["sad", "lonely", "melancholic"])[0] == self_c.MELANCHOLIC  # même un deuil
    assert classify(["sad", "angry", "scared"])[0] == self_c.NIGHTMARE  # sombre et menaçant
    assert classify(["happy"], [("anxious", 0.7)])[0] == self_c.NIGHTMARE  # une angoisse qui la travaille
    assert classify(["happy"], [("anxious", 0.3)])[0] != self_c.NIGHTMARE  # une angoisse légère, non
    assert classify(["happy", "curious"])[0] == self_c.PLEASANT


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

    assert jump(woke[0].at) > 0.02  # au réveil, le soulagement se sent
    assert abs(jump(digested[0].at)) < 0.01  # pas en pleine nuit


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
    notes = [c.messages[-1].content for c in llm.calls if c.role == "journal"]
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
    assert "Tu lui as répondu, entre autres, « d'accord »." in notes


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
    assert "Ton humeur en parlant : le matin, plutôt contente ; l'après-midi, plutôt contente ; le soir, plutôt " \
        "triste." in tuesday


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
        return run_view(kernel, find(kernel, "self", "nuits"), {})

    blocks, _ = build_run(tmp_path, scenario, script=script)
    history = next(b for b in blocks if isinstance(b, Table) and b.title == "Toutes ses nuits")
    assert len(history.rows) == 14
    assert bool(history.pager.older) == (written > 14)


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
        aud = Audience(persons=("user_1",), channel="web", public=False, level=3, witness_level=3, private_ok=True)
        frame = kernel.mind.frame(audience=aud)
        ctx = SimpleNamespace(frame=frame, state=frame.state("self"), ports=kernel.ports)
        return await self_journal(JournalArgs(days_ago=3), ctx), await self_journal(JournalArgs(days_ago=2), ctx)

    (saturday, sunday), llm = build_run(tmp_path, scenario, script=script)
    assert "CANARI-SAMEDI" in saturday and "samedi 26 septembre" in saturday
    assert sunday == "Tu n'as rien écrit sur ta journée du dimanche 27 septembre."
    reply = next(c for c in llm.calls if c.role == "reply")
    offered = {t.name for t in reply.tools}
    assert not offered & {"self_read", "self_yesterday", "self_dream"}  # ils relisaient une section présente
    assert "self : relire ce que tu as écrit dans ton journal un jour passé" in reply.system_stable
    assert "CANARI-LUNDI" in reply.messages[-1].content  # hier, elle l'a déjà en tête



