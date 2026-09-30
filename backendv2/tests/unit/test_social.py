"""Les liens, par leurs intentions.

- la proximité se vit (jours, messages, chaleur) : dix minutes d'insultes ne
  font pas une connaissance, et une rancune ne fait jamais une amie ;
- le rythme d'une relation est le sien ;
- elle relance une amie joignable, jamais une connaissance, jamais la nuit,
  jamais quelqu'un qu'elle ne peut pas joindre ;
- sous la détresse, elle va vers la personne auprès de qui elle se sent bien ;
- sa fiche d'une personne n'entre dans le prompt que pour elle, en privé ;
- un souvenir qui touche un sujet délicat de quelqu'un devient une confidence.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.contracts import memory as memory_c
from mika.contracts import social as social_c
from mika.faculties.others.tone import read_tone
from mika.faculties.social.faculty import Contact, SocialParams, lived, rhythm
from mika.kernel.clock import DAY, HOUR, US, local
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, disconnect, said

P = SocialParams()


def contact(days: int, messages: int) -> Contact:
    return Contact(days=tuple(range(1000, 1000 + days)), inbound=messages, first_in=1, last_in=1)


# (jours, messages, regard, hostilité, attendu, pourquoi)
LIVED = [
    (0, 0, 0.0, 0.0, "stranger", "jamais parlé"),
    (1, 12, -0.5, 0.5, "stranger", "dix minutes d'insultes ne font pas une connaissance"),
    (1, 25, 0.2, 0.0, "acquaintance", "une longue première conversation"),
    (2, 4, 0.0, 0.0, "acquaintance", "se reparler un autre jour"),
    (3, 15, 0.0, 0.0, "friend", "trois jours, quinze messages : une amie"),
    (3, 15, -0.1, 0.0, "friend", "une curiosité banale, sans chaleur particulière, suffit"),
    (3, 15, -0.4, 0.0, "friend", "un chagrin partagé n'éloigne pas"),
    (3, 15, -0.3, 0.3, "acquaintance", "une rancune ne fait jamais une amie"),
    (30, 6, 0.4, 0.0, "acquaintance", "un contact rare reste une connaissance"),
    (7, 50, 0.3, 0.0, "close", "une semaine de conversations chaleureuses"),
    (7, 50, 0.0, 0.0, "friend", "beaucoup d'échanges sans chaleur : amie, pas proche"),
    (14, 100, -0.3, 0.0, "close", "une longue histoire, même dans une mauvaise passe"),
]


@pytest.mark.parametrize("days,messages,regard,hostility,expected,why", LIVED)
def test_closeness_is_lived(days, messages, regard, hostility, expected, why):
    assert lived(contact(days, messages), regard, P, hostility) == expected, why


def test_the_rhythm_of_a_relationship_is_its_own():
    daily = Contact(days=tuple(range(100, 108)))
    every_three = Contact(days=(100, 103, 106, 109, 112))
    irregular = Contact(days=(100, 101, 105, 106, 113))
    young = Contact(days=(100, 101))
    rare = Contact(days=(100, 160, 220))
    assert rhythm(daily, 110, "friend", P) == (1.0, True)
    assert rhythm(every_three, 115, "friend", P) == (3.0, True)
    assert rhythm(irregular, 115, "friend", P) == (2.5, True)  # la médiane, pas la moyenne
    assert rhythm(young, 102, "close", P) == (P.fallback_close_days, False)
    assert rhythm(young, 102, "friend", P) == (P.fallback_friend_days, False)
    assert rhythm(rare, 225, "friend", P)[0] <= P.rhythm_max_days


@pytest.mark.parametrize("text,expected", [
    ("JE SUIS TROP CONTENTE", "majuscules"),
    ("non mais sérieux !!", "exclamation"),
    ("bon... je sais pas... enfin bref", "suspension"),
    ("ok", "très court"),
    ("j'en ai marre, je suis épuisée", "lourds"),
    ("trop bien, j'ai hâte !", "entrain"),
    ("ça va 😭", "émoji triste"),
])
def test_reading_the_tone_of_a_message(text, expected):
    assert any(expected in cue for cue in read_tone(text)), read_tone(text)


def test_an_ordinary_message_has_no_cue():
    assert read_tone("On se voit demain à la bibliothèque pour réviser ?") == []


# ── De bout en bout ───────────────────────────────────────────────────────


class Script:
    def __init__(self) -> None:
        self.tag = "[EMOTION:happy:0.5]"

    def __call__(self, req):
        if req.role in ("extract", "profile"):
            return LLMResponse("{}")
        if req.role == "initiative":
            return LLMResponse(f"coucou, ça fait un moment ! {self.tag}")
        return LLMResponse(f"ah oui ? {self.tag}")


def run(tmp_path, scenario, start=at_paris(2026, 9, 28, 18, 0), *, with_llm=False):
    script = Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, clock, script)
        finally:
            await kernel.stop()

    got = run_virtual(clock, main)
    return (got, llm) if with_llm else got


def prompts(llm, target, containing=""):
    return ["\n".join(m.content for m in c.messages) for c in llm.calls
            if c.meta.get("target") == target and containing in c.messages[-1].content]


async def evening(kernel, handle, *, channel="telegram", per_day=4):
    for i in range(per_day):
        p = await kernel.perceive(said(handle, f"message {i} du soir", channel=channel))
        await p.reply
        await asyncio.sleep(60)


async def daily(kernel, handle, days, *, channel="telegram", per_day=4, start_hour=None):
    """Une relation qui vit : quelques messages chaque soir."""
    del start_hour  # l'heure de départ est celle de la course
    for _ in range(days):
        await evening(kernel, handle, channel=channel, per_day=per_day)
        await asyncio.sleep(DAY / US - per_day * 60)


def started(kernel):
    from mika.contracts import runtime as rt

    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == rt.EPISODE_STARTED.name]


def test_she_misses_a_reachable_friend_but_not_an_acquaintance_nor_someone_unreachable(tmp_path):
    async def scenario(kernel, clock, script):
        await daily(kernel, "tg_1", 5)  # une amie, sur Telegram (joignable)
        await daily(kernel, "tg_2", 1, per_day=5)  # une connaissance d'un soir
        await connect(kernel, "user_3", "Chloé")
        await daily(kernel, "user_3", 5, channel="web")  # une amie, mais seulement dans le navigateur
        await disconnect(kernel, "user_3")
        await asyncio.sleep(4 * DAY / US)
        return [(e.data.target, e.data.reason) for e in started(kernel) if e.data.kind == "INITIATIVE"]

    fired = run(tmp_path, scenario)
    outreach = {t for t, reason in fired if {social_c.RECONTACT, social_c.CHAT} & set(reason.split(","))}
    assert outreach == {"tg_1"}, fired


def test_she_never_writes_to_an_absent_friend_at_night(tmp_path):
    async def scenario(kernel, clock, script):
        await daily(kernel, "tg_1", 5, start_hour=23)
        await asyncio.sleep(3 * DAY / US)
        return [(local(e.at, PARIS), e.data.reason) for e in started(kernel) if e.data.kind == "INITIATIVE"]

    fired = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 23, 0))
    hours = [t.hour + t.minute / 60 for t, reason in fired
             if {social_c.RECONTACT, social_c.CHAT} & set(reason.split(","))]
    assert hours and all(10 <= h <= 20.5 for h in hours), fired  # elle écrit habituellement vers 23 h


def test_in_distress_she_turns_to_the_friend_she_feels_good_with(tmp_path):
    async def scenario(kernel, clock, script):
        for _ in range(4):  # deux amies qui écrivent chaque jour
            script.tag = "[EMOTION:love:0.8]"
            await evening(kernel, "tg_1")  # celle qui lui fait du bien
            script.tag = "[EMOTION:curious:0.4]"
            await evening(kernel, "tg_2")  # l'autre, sans plus
            await asyncio.sleep(DAY / US - 8 * 60)
        await befriend(kernel, "user_9", "close")
        script.tag = "[EMOTION:sad:0.9]"  # quelqu'un de proche va très mal : elle aussi
        await connect(kernel, "user_9", "Sam")
        for _ in range(8):
            p = await kernel.perceive(said("user_9", "ça va vraiment pas"))
            await p.reply
            await asyncio.sleep(60)
        await asyncio.sleep(HOUR / US)
        return [(e.data.target, e.data.reason) for e in started(kernel) if e.data.kind == "INITIATIVE"]

    fired = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 11, 0))
    comfort = [t for t, reason in fired if social_c.COMFORT in reason.split(",")]
    assert comfort == ["tg_1"], fired  # vers celle qui lui fait du bien — et une seule


def _profile(kernel, person, sensitive=()):
    return kernel.mind.append([social_c.PROFILE_REVISED.draft(
        person=person, summary=Content.of("C'est quelqu'un de drôle qui adore la montagne.", level=2),
        tone="taquin", interests=("montagne",), sensitive=tuple(sensitive))], emitter="social", correlation="genese",
        origin=Origin.GENESIS)


def test_her_notes_on_someone_reach_the_prompt_only_for_them_in_private(tmp_path):
    async def scenario(kernel, clock, script):
        await connect(kernel, "user_1", "Alice")
        await _profile(kernel, "user_1")
        p = await kernel.perceive(said("user_1", "salut !"))
        await p.reply
        await connect(kernel, "user_2", "Bob")
        p = await kernel.perceive(said("user_2", "tu connais Alice ?"))
        await p.reply

    _, llm = run(tmp_path, scenario, with_llm=True)
    assert any("adore la montagne" in m for m in prompts(llm, "user_1"))
    assert not any("adore la montagne" in m for m in prompts(llm, "user_2"))


def test_a_memory_touching_someones_sensitive_topic_becomes_a_confidence(tmp_path):
    async def scenario(kernel, clock, script):
        await connect(kernel, "user_1", "Alice")
        await connect(kernel, "user_2", "Bob")
        await befriend(kernel, "user_2", "friend")
        await _profile(kernel, "user_1", sensitive=("sa santé",))
        for text, sens in (("Alice attend des résultats pour sa santé cette semaine", Sensitivity.PERSONAL),
                           ("Alice prépare un voyage en Islande cette semaine", Sensitivity.PERSONAL)):
            await kernel.mind.append([memory_c.BELIEVED.draft(text=Content.of(text, level=int(sens)),
                                                               about=("user_1",), sensitivity=int(sens))],
                                     emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await asyncio.sleep(5)
        p = await kernel.perceive(said("user_2", "et Alice, elle fait quoi cette semaine ? sa santé, son voyage ?"))
        await p.reply

    _, llm = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0), with_llm=True)
    shown = "\n".join(prompts(llm, "user_2"))
    assert "Islande" in shown  # contrôle : le personnel sur Alice sort chez un ami
    assert "résultats pour sa santé" not in shown


def test_a_room_reply_sees_the_room_not_her_private_thread(tmp_path):
    async def scenario(kernel, clock, script):
        p = await kernel.perceive(said("tg_1", "CANARI-PRIVE je te le dis en privé", channel="telegram"))
        await p.reply
        p = await kernel.perceive(said("tg_2", "salut le groupe", channel="telegram", room="tg_chat_-1",
                                       public=True, addressed=False))
        p = await kernel.perceive(said("tg_1", "Mika, tu en penses quoi ?", channel="telegram", room="tg_chat_-1",
                                       public=True))
        await p.reply

    _, llm = run(tmp_path, scenario, with_llm=True)
    room = prompts(llm, "tg_1", "Mika, tu en penses quoi")
    assert room
    text = room[-1]
    assert "[tg_2] salut le groupe" in text
    assert "CANARI-PRIVE" not in text


def test_contacts_follow_the_person_not_the_handle(tmp_path):
    """Écrire sur un autre compte relié, c'est la même relation."""
    from mika.contracts import identity as identity_c

    async def scenario(kernel, clock, script):
        await kernel.mind.append([identity_c.LINKED.draft(handle="tg_5", person="user_1")], emitter="identity",
                                 correlation="genese", origin=Origin.GENESIS)
        await connect(kernel, "user_1", "Alice")
        p = await kernel.perceive(said("user_1", "coucou"))
        await p.reply
        await asyncio.sleep(HOUR / US)
        p = await kernel.perceive(said("tg_5", "c'est encore moi", channel="telegram"))
        await p.reply
        return kernel.mind.frame().get(social_c.CONTACT("user_1")), kernel.mind.frame().get(social_c.CONTACT("tg_5"))

    alice, handle = run(tmp_path, scenario)
    assert alice.inbound == 2 and handle.inbound == 0


def test_whatever_the_reason_no_second_message_to_an_absent_friend_who_has_not_answered(tmp_path):
    """Le filet de sécurité : une raison qui ne connaîtrait pas la règle (une
    pensée, un but) est arrêtée par la retenue elle-même."""
    from mika.contracts import runtime as rt
    from mika.faculties.social.initiative import _restraint
    from mika.kernel.arbitration import RowView
    from mika.kernel.events import VoiceProvenance

    async def scenario(kernel, clock, script):
        await befriend(kernel, "tg_1", "close")
        p = await kernel.perceive(said("tg_1", "coucou", channel="telegram"))
        await p.reply
        await kernel.mind.append([rt.UTTERANCE.draft(
            kind="INITIATIVE", text=Content.of("tu vas mieux ?"), target="tg_1", channel="telegram",
            voice=VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m"))],
            emitter="runtime", correlation="genese", origin=Origin.GENESIS)
        frame = kernel.mind.frame()
        absent = _restraint(frame.state("social"), frame, RowView("INITIATIVE", "tg_1", 5.0, ("thought",)))
        await connect(kernel, "tg_1", "Alice")
        frame = kernel.mind.frame()
        present = _restraint(frame.state("social"), frame, RowView("INITIATIVE", "tg_1", 5.0, ("thought",)))
        return absent, present

    absent, present = run(tmp_path, scenario)
    assert absent.veto == social_c.UNANSWERED
    assert present.veto is None and present.shift < 0  # en sa présence : plus rare, pas interdit


def test_a_grudge_needs_installed_hostility():
    """Un seuil de rancune à zéro (une surcharge passée, un réglage extrême) ne
    coupe pas les ponts avec tout le monde : sans hostilité, rien à garder
    contre personne. La moindre hostilité, elle, suffit alors."""
    from mika.faculties.social.faculty import grudging

    zero = SocialParams(grudge=0.0)
    assert not grudging(0.0, zero)
    assert lived(contact(3, 15), 0.0, zero, 0.0) == "friend"
    assert grudging(0.01, zero)  # contrôle : le seuil s'applique dès qu'il y a de l'hostilité
    assert lived(contact(3, 15), 0.0, zero, 0.01) == "acquaintance"
    assert not grudging(0.19, P) and grudging(0.2, P)


@pytest.mark.parametrize("hm,start,end,inside", [
    ((12, 0), (10, 0), (20, 30), True),
    ((21, 0), (10, 0), (20, 30), False),
    ((23, 30), (18, 0), (1, 0), True),  # une plage nocturne passe minuit…
    ((0, 30), (18, 0), (1, 0), True),
    ((1, 0), (18, 0), (1, 0), True),
    ((12, 0), (18, 0), (1, 0), False),  # … sans devenir « toujours »
    ((9, 59), (10, 0), (10, 0), False),
])
def test_a_daily_window_may_cross_midnight(hm, start, end, inside):
    from mika.kernel.clock import within_daily_window

    minute = hm[0] * 60 + hm[1]
    assert within_daily_window(minute, start[0] * 60 + start[1], end[0] * 60 + end[1]) is inside


def test_a_night_owl_reaches_out_to_a_friend_late_in_the_evening(tmp_path):
    """Réglée pour écrire de 18 h à 1 h, elle relance une amie absente à 23 h
    (la plage passe minuit) ; réglée de 10 h à 20 h 30, jamais à cette heure-là."""
    from mika.contracts import runtime as rt

    async def scenario(kernel, window):
        await boot(kernel)
        await kernel.set_params("social", SocialParams(day_start_min=window[0], day_end_min=window[1]))
        await befriend(kernel, "tg_1", social_c.FRIEND)
        for day in range(4):  # une amie qui écrit tous les jours à 22 h 30…
            await asyncio.sleep((DAY if day else 0) / US)
            p = await kernel.perceive(said("tg_1", "coucou, tu fais quoi ce soir ?", channel="telegram"))
            await p.reply
        await asyncio.sleep(2 * DAY / US + HOUR / US)  # … puis plus rien
        mind = kernel.mind
        sent = [mind.decode(e) for e in mind.store.read() if e.type == rt.UTTERANCE.name]
        return [local(e.at, PARIS).hour for e in sent if e.data.kind == "INITIATIVE" and e.data.target == "tg_1"]

    def go(path, window):
        kernel, clock, _, _ = build(path, lambda req: LLMResponse("d'accord [EMOTION:happy:0.5]"),
                                    start=at_paris(2026, 9, 28, 22, 30))

        async def main():
            try:
                return await scenario(kernel, window)
            finally:
                await kernel.stop()

        return run_virtual(clock, main)

    (tmp_path / "hibou").mkdir()
    (tmp_path / "jour").mkdir()
    owl = go(tmp_path / "hibou", (18 * 60, 60))
    day = go(tmp_path / "jour", (10 * 60, 20 * 60 + 30))
    assert owl and all(h >= 18 or h <= 1 for h in owl), owl
    assert all(10 <= h <= 20 for h in day), day
