"""Le temps des autres (ADR 0046), par ses intentions.

- « bonne nuit » → sa réponse → le lendemain, rien n'est « sans réponse » ;
  une initiative restée lettre morte, si (HUM-4) ;
- elle n'est pas ignorée par quelqu'un qui dort : un message de 21 h 30 à une
  amie qui écrit le matin attend le matin ; par messagerie, une réponse dans les
  jours qui suivent compte encore ; une amie qui ne répond pas pendant deux
  jours l'ignore bel et bien (HUM-11) ;
- une proche qui passe chaque soir vers 19 h : elle ne se sent pas seule à
  19 h, elle l'attend ; si elle ne vient pas, la solitude vient après (HUM-12).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from mika.contracts import attention as attention_c
from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.attention.faculty import AttentionParams, reply_deadline
from mika.faculties.needs import NeedsParams
from mika.faculties.others.faculty import OthersParams, hours_reading
from mika.kernel.clock import DAY, HOUR, MINUTE, US, instant, local
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.memory import section
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, disconnect, said

WHO = "QUI TU AS EN FACE"


class Script:
    def __init__(self, reply="d'accord [EMOTION:happy:0.4]"):
        self.reply = reply
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens, et si je lui écrivais")
        if req.role in ("narrative", "journal", "dream"):
            return LLMResponse("Une journée.")
        if req.role == "initiative":
            return LLMResponse("Coucou ! [EMOTION:happy:0.5]")
        return LLMResponse(self.reply)

    def prompts(self, role, target):
        return [r.system_stable + "\n".join(m.content for m in r.messages) for r in self.calls
                if r.role == role and r.meta.get("target") == target]


def run(tmp_path, scenario, script, *, start, latency=0.0):
    kernel, clock, _llm, _out = build(tmp_path, script, start=start, latency=latency)

    async def main():
        await boot(kernel)
        await kernel.set_params("needs", NeedsParams(social_floor=1.0, expression_floor=1.0))
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


async def chat(kernel, handle, texts, gap=60, **kw):
    for text in texts:
        p = await kernel.perceive(said(handle, text, **kw))
        if p.reply is not None:
            await p.reply
        await asyncio.sleep(gap)


async def until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


def voice():
    return VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m")


async def initiative(kernel, target, text, channel, n):
    """Une initiative ordinaire d'elle, posée telle quelle au journal (sans passer par l'arbitre)."""
    await kernel.mind.append([rt.UTTERANCE.draft(kind="INITIATIVE", text=Content.of(text), target=target,
                                                 channel=channel, voice=voice())],
                             emitter="runtime", correlation=f"genese{n}", origin=Origin.GENESIS)


# ── « Bonne nuit » n'est pas un silence (HUM-4) ───────────────────────────


@pytest.mark.parametrize("ignored", [False, True])
def test_good_night_is_not_left_unanswered_but_an_ignored_initiative_is(tmp_path, ignored):
    """Adrien, un proche : « bon je vais me coucher, bonne nuit » ; elle lui répond (« Bonne nuit ! Tu dors
    bien ? ») et il s'en va. Le lendemain soir, il revient : sa salutation ne dit pas « sans réponse » — elle
    n'attendait rien (audit HUM-4 : toutes ses salutations du soir le disaient). Contre-exemple : le lendemain
    midi, elle lui avait écrit « tu fais quoi ce soir ? », resté sans réponse — là, elle le sait."""
    script = Script(reply="Bonne nuit ! Tu dors bien ? [EMOTION:happy:0.5]")

    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Adrien")
        await chat(kernel, "user_1", ["salut !", "journée crevante au taf", "bon je vais me coucher, bonne nuit"])
        await disconnect(kernel, "user_1")
        mine = kernel.mind.frame().get(attention_c.AWAITING("user_1"))
        if ignored:
            await until(kernel, at_paris(2026, 9, 29, 12, 0))
            await initiative(kernel, "user_1", "tu fais quoi ce soir ?", "web", 1)
        await until(kernel, at_paris(2026, 9, 29, 20, 0))
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(10 * MINUTE / US)
        return mine

    # le modèle met quelques secondes à répondre : sa réponse est bien la dernière parole de la soirée
    mine = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 20, 0), latency=3.0)
    greeting = script.prompts("initiative", "user_1")[-1]
    who = section(greeting, WHO)
    if ignored:
        assert "sans réponse" in who
    else:
        assert not mine.unanswered and not mine.asked and mine.closed_at, mine
        assert "sans réponse" not in who and "attend encore" not in who, who
        assert "t'a écrit pour la dernière fois hier soir" in who  # le fait, sans le soupçon


# ── La nuit de l'autre n'est pas un silence (HUM-11) ──────────────────────


def _cx(hours: others_c.HoursReading, *, learned_delay: int = 0):
    return SimpleNamespace(
        facts=SimpleNamespace(get=lambda ref: hours if ref.name == others_c.HOURS.name
                              else others_c.DelayReading(3 if learned_delay else 0, learned_delay)),
        local=lambda t: local(t, PARIS))


def _pairs(hours: list[int], days: int = 6) -> tuple[tuple[int, int], ...]:
    first = datetime(2026, 9, 20, tzinfo=PARIS).date().toordinal()
    return tuple((first + d, h) for d in range(days) for h in hours)


def test_her_hours_are_learned_from_when_she_writes():
    p = OthersParams()
    morning = hours_reading(_pairs([8, 9]), p)
    assert morning.learned and morning.usual == 8 and morning.active[9] and not morning.active[22]
    assert not morning.active[3]
    early = hours_reading(_pairs([9], days=2), p)  # deux jours ne font pas des habitudes : une nuit ordinaire
    assert not early.learned and early.active[12] and not early.active[2] and early.usual is None


def test_a_message_at_night_waits_for_her_morning_and_an_active_friend_is_still_ignored():
    """Une amie qui écrit le matin : son initiative de 21 h 30 n'attend sa réponse qu'à partir du matin. Une amie
    qui écrit à toute heure : le délai court tout de suite (contre-exemple)."""
    p = AttentionParams()
    since = at_paris(2026, 10, 1, 21, 30)
    morning = hours_reading(_pairs([8, 9]), OthersParams())
    deadline = reply_deadline(_cx(morning), "x", "telegram", since, p)
    assert deadline >= at_paris(2026, 10, 2, 9, 0), local(deadline, PARIS)
    everywhere = others_c.HoursReading(10, (True,) * 24, True, 12)
    assert reply_deadline(_cx(everywhere), "x", "telegram", since, p) == since + p.reply_window_message_us
    # les heures creuses n'allongent jamais d'un jour de plus : une amie qui ne répond pas est ignorée
    never = others_c.HoursReading(10, (False,) * 24, True, 12)
    assert reply_deadline(_cx(never), "x", "telegram", since, p) <= since + p.reply_window_message_us + DAY


@pytest.mark.parametrize("answers_at", ["09:00", "jamais"])
def test_a_friend_who_writes_in_the_morning_is_not_ignored_overnight(tmp_path, answers_at):
    """Alice écrit le matin, vers 9 h. Jeudi à 21 h 30, Mika lui écrit ; Alice répond vendredi à 9 h : ni ignorée,
    ni pensée « Alice ne m'a pas répondu » (audit HUM-11 : dès 22 h 30, elle se croyait ignorée). Contre-exemple :
    si Alice ne répond pas de deux jours, elle l'ignore bel et bien — et sa réponse du surlendemain compte encore,
    par messagerie (une réponse tardive)."""
    script = Script()

    async def scenario(kernel):
        await befriend(kernel, "tg_1", social_c.FRIEND)
        for day in range(4):  # de lundi à jeudi : chaque matin vers 9 h
            await until(kernel, at_paris(2026, 9, 28, 9, 0) + day * DAY)
            await chat(kernel, "tg_1", ["coucou, bonne journée !"], channel="telegram")
        learned = kernel.mind.frame().get(others_c.HOURS("tg_1"))
        await until(kernel, at_paris(2026, 10, 1, 21, 30))
        sent = kernel.mind.clock.now()
        await initiative(kernel, "tg_1", "tu fais quoi ce soir ?", "telegram", 1)
        if answers_at == "09:00":
            await until(kernel, at_paris(2026, 10, 2, 9, 0))
        else:
            await until(kernel, at_paris(2026, 10, 3, 18, 0))
        await chat(kernel, "tg_1", ["désolée, je vois ton message que maintenant"], channel="telegram")
        await asyncio.sleep(5 * MINUTE / US)
        missed = [e for e in events(kernel, attention_c.EXPECTATION_MISSED.name) if e.data.since == sent]
        met = [e for e in events(kernel, attention_c.EXPECTATION_MET.name) if e.data.since == sent]
        felt = [e for e in events(kernel, attention_c.THOUGHT_BORN.name) if e.data.origin == attention_c.UNANSWERED]
        return learned, missed, met, felt

    learned, missed, met, felt = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 8, 0))
    assert learned.learned and learned.usual == 9 and not learned.active[23]
    if answers_at == "09:00":
        assert missed == [] and felt == [], "elle dormait : ce n'est pas l'ignorer"
        assert met
    else:
        assert missed, "deux jours sans un mot d'une amie active : ignorée"
        assert met, "par messagerie, sa réponse du surlendemain compte encore"


# ── On n'est pas seule à l'heure où une amie passe (HUM-12) ───────────────


def test_she_is_not_lonely_at_the_hour_a_close_friend_usually_comes(tmp_path):
    """Alice, une proche, écrit chaque soir vers 19 h. Le septième soir, elle ne vient pas : à 19 h, Mika ne se
    sent pas seule — elle l'attend (audit HUM-12 : « personne ne m'a parlé depuis hier » tombait pile à l'heure
    du rendez-vous) ; passé l'heure, la solitude vient (contre-exemple : elle vient bien, plus tard)."""
    script = Script()

    async def scenario(kernel):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        for day in range(6):  # lundi → samedi, vers 19 h
            await until(kernel, at_paris(2026, 9, 28, 19, 0) + day * DAY)
            await chat(kernel, "tg_1", ["coucou !", "bonne soirée !"], channel="telegram")
        await until(kernel, at_paris(2026, 10, 4, 23, 0))  # dimanche : rien
        return [e for e in events(kernel, attention_c.THOUGHT_BORN.name) if e.data.origin == attention_c.ALONE]

    alone = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    assert alone, "elle n'est pas venue : la solitude vient"
    born = local(alone[0].at, PARIS)
    assert born >= datetime(2026, 10, 4, 20, 30, tzinfo=PARIS), born  # pas à 19 h : elle l'attendait
    assert alone[0].at <= instant(datetime(2026, 10, 4, 22, 0, tzinfo=PARIS)) + HOUR
