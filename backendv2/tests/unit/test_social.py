"""Les liens, par leurs intentions.

- la proximité se vit (jours, messages, chaleur) : dix minutes d'insultes ne
  font pas une connaissance, et une rancune ne fait jamais une amie ;
- le rythme d'une relation est le sien ;
- elle relance une amie joignable, jamais une connaissance, jamais la nuit,
  jamais quelqu'un qu'elle ne peut pas joindre ;
- sous la détresse, elle va vers la personne auprès de qui elle se sent bien ;
- sa fiche d'une personne n'entre dans le prompt que pour elle, en privé ;
- un souvenir qui touche un sujet délicat de quelqu'un devient une confidence ;
- une rancune retient l'ordinaire, jamais une promesse (ADR 0044) : le rappel
  qu'on lui a demandé part à l'heure, prévenir n'est que décalé ;
- une reconnexion, un redémarrage d'elle ne sont pas des arrivées : on ne
  resalue pas quelqu'un qui n'est jamais parti.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import email as email_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.others.tone import read_tone
from mika.faculties.social.faculty import Contact, SocialParams, lived, owner_floored, rhythm
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, US, local
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, disconnect, said

P = SocialParams()


def contact(days: int, messages: int, step: int = 1) -> Contact:
    """Une histoire : ``days`` jours de contact, espacés de ``step`` jours, ``messages`` en tout."""
    return Contact(days=tuple(range(1000, 1000 + days * step, step))[:64], inbound=messages, first_in=1, last_in=1,
                   total_days=days)


# (jours, messages, espacement, regard, hostilité, attendu, pourquoi)
LIVED = [
    (0, 0, 1, 0.0, 0.0, "stranger", "jamais parlé"),
    (1, 12, 1, -0.5, 0.5, "stranger", "dix minutes d'insultes ne font pas une connaissance"),
    (1, 25, 1, 0.2, 0.0, "acquaintance", "une longue première conversation"),
    (2, 4, 1, 0.0, 0.0, "acquaintance", "se reparler un autre jour"),
    (3, 15, 1, 0.0, 0.0, "friend", "trois jours, quinze messages : une amie"),
    (3, 15, 1, -0.1, 0.0, "friend", "une curiosité banale, sans chaleur particulière, suffit"),
    (3, 15, 1, -0.4, 0.0, "friend", "un chagrin partagé n'éloigne pas"),
    (3, 15, 1, -0.3, 0.3, "acquaintance", "une rancune ne fait jamais une amie naissante"),
    (30, 6, 1, 0.4, 0.0, "acquaintance", "un contact rare reste une connaissance"),
    (7, 50, 1, 0.3, 0.0, "friend", "une semaine chaleureuse : amie, pas encore proche (il faut un mois)"),
    (7, 50, 5, 0.3, 0.0, "close", "un mois de conversations chaleureuses"),
    (7, 50, 5, 0.0, 0.0, "friend", "beaucoup d'échanges sans chaleur : amie, pas proche"),
    (14, 100, 3, -0.3, 0.0, "close", "une longue histoire, même dans une mauvaise passe"),
    (30, 150, 2, 0.4, 0.3, "close", "une dispute n'efface pas deux mois d'amitié"),
    (30, 150, 2, 0.4, 0.4, "acquaintance", "une rancune lourde, si"),
]


@pytest.mark.parametrize("days,messages,step,regard,hostility,expected,why", LIVED)
def test_closeness_is_lived(days, messages, step, regard, hostility, expected, why):
    assert lived(contact(days, messages, step), regard, P, hostility) == expected, why


# (jours, messages, espacement, silence en jours, attendu, pourquoi)
SILENCES = [
    (60, 300, 1, 10, "close", "dix jours sans nouvelles d'une proche : rien ne change"),
    (60, 300, 1, 40, "friend", "un long silence la fait descendre d'un cran"),
    (60, 300, 1, 150, "friend", "cinq mois : une longue histoire ne tombe jamais plus d'un cran"),
    (5, 25, 1, 40, "acquaintance", "une jeune amitié qui se tait s'éloigne"),
    (5, 25, 1, 15, "friend", "contrôle : pas encore un long silence"),
]


@pytest.mark.parametrize("days,messages,step,silent,expected,why", SILENCES)
def test_closeness_follows_a_sliding_window_with_a_floor_of_history(days, messages, step, silent, expected, why):
    ct = contact(days, messages, step)
    assert lived(ct, 0.4, P, 0.0, now_day=ct.days[-1] + silent) == expected, why


# (jours, messages, espacement, regard, attachement, attendu, pourquoi)
BONDS = [
    (7, 50, 5, -0.1, 0.25, "close", "un mois d'amitié à laquelle elle tient, dans une mauvaise passe : toujours proche"),
    (7, 50, 5, -0.1, 0.05, "friend", "contrôle : sans attachement, la mauvaise passe la laisse amie"),
    (10, 100, 1, 0.0, 0.3, "friend", "dix soirées d'affilée, même chaleureuses : on ne devient pas proche en dix jours"),
    (11, 110, 3, 0.0, 0.3, "close", "les mêmes soirées sur un mois : proche, avant la longue histoire"),
]


@pytest.mark.parametrize("days,messages,step,regard,bond,expected,why", BONDS)
def test_an_installed_attachment_makes_a_close_friend_after_a_month(days, messages, step, regard, bond, expected,
                                                                      why):
    """WP1 (ADR 0032) installe un attachement lent (``affect.bond``) ; la proximité le lit, sous le même plancher
    d'histoire (un mois) que la chaleur du moment."""
    ct = contact(days, messages, step)
    assert lived(ct, regard, P, 0.0, bond=bond) == expected, why
    # un réglage à zéro ne fait pas une proche de quelqu'un à qui elle ne tient pas du tout
    assert lived(ct, regard, SocialParams(close_bond=0.0), 0.0, bond=0.0) == lived(ct, regard, P, 0.0)


@pytest.mark.parametrize("lived_level, floor, hostility, expected, why", [
    (social_c.STRANGER, social_c.FRIEND, 0.0, social_c.FRIEND, "installation neuve : sa propriétaire est une amie d'office"),
    (social_c.ACQUAINTANCE, social_c.FRIEND, 0.0, social_c.FRIEND, "le plancher relève"),
    (social_c.CLOSE, social_c.FRIEND, 0.0, social_c.CLOSE, "il ne rabaisse jamais ce qui a été vécu"),
    (social_c.STRANGER, social_c.ACQUAINTANCE, 0.0, social_c.ACQUAINTANCE, "le plancher se règle"),
    (social_c.STRANGER, social_c.CLOSE, 0.0, social_c.STRANGER, "jamais « proche » d'office : ça se vit"),
    (social_c.STRANGER, social_c.FRIEND, 0.9, social_c.STRANGER, "une rancune lourde lève le plancher"),
])
def test_her_owner_is_at_least_a_friend_never_close_by_right(lived_level, floor, hostility, expected, why):
    assert owner_floored(lived_level, SocialParams(owner_floor=floor), hostility) == expected, why


def test_a_retired_setting_still_replays():
    """``social.ignored_shift`` n'a plus de lecteur (la retenue est celle d'``agency``) : un ancien
    ``kernel.params_changed`` qui le porte se relit sans lui ; une clé inconnue reste une erreur."""
    import json

    from pydantic import ValidationError

    from mika.faculties.social.faculty import SOCIAL
    from mika.kernel.registry import _decode_params

    old = json.dumps({"ignored_shift": -1.5, "grudge": 0.3})
    assert _decode_params(SocialParams, old, SOCIAL.retired_params).grudge == 0.3
    assert "ignored_shift" not in SocialParams.model_fields
    with pytest.raises(ValidationError):
        _decode_params(SocialParams, json.dumps({"ignored_shif": -1.5}), SOCIAL.retired_params)


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
        if p.reply is not None:  # endormie, la réponse d'une inconnue attend son réveil (ADR 0036)
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
        tone=Content.of("taquin", level=2), interests=Content.of("montagne", level=2),
        sensitive=Content.of("\n".join(sensitive), level=2) if sensitive else None)], emitter="social",
        correlation="genese", origin=Origin.GENESIS)


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
                                       public=True, addressed=False, display_name="Léa"))
        p = await kernel.perceive(said("tg_1", "Mika, tu en penses quoi ?", channel="telegram", room="tg_chat_-1",
                                       public=True, display_name="Tom"))
        await p.reply

    _, llm = run(tmp_path, scenario, with_llm=True)
    room = prompts(llm, "tg_1", "Mika, tu en penses quoi")
    assert room
    text = room[-1]
    assert "Léa : salut le groupe" in text  # chacun parle sous son nom, jamais sous son adresse
    assert "[tg_2]" not in text
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


def test_whatever_the_reason_no_second_message_to_a_friend_who_has_not_answered(tmp_path):
    """Le filet de sécurité : une raison qui ne connaîtrait pas la règle (une
    pensée, un but) est arrêtée par la retenue elle-même — présente ou non
    (ADR 0033 : la règle est celle du budget d'initiatives, pour toutes les
    raisons à la fois)."""
    from mika.contracts import agency as agency_c
    from mika.contracts import runtime as rt
    from mika.faculties.agency import _budget
    from mika.kernel.arbitration import RowView
    from mika.kernel.events import VoiceProvenance

    def budget(kernel):
        frame = kernel.mind.frame()
        return _budget(frame.state("agency"), frame, RowView("INITIATIVE", "tg_1", 5.0, ("thought",)))

    async def scenario(kernel, clock, script):
        await befriend(kernel, "tg_1", "close")
        p = await kernel.perceive(said("tg_1", "coucou", channel="telegram"))
        await p.reply
        await kernel.mind.append([rt.UTTERANCE.draft(
            kind="INITIATIVE", text=Content.of("tu vas mieux ?"), target="tg_1", channel="telegram",
            voice=VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m"))],
            emitter="runtime", correlation="genese", origin=Origin.GENESIS)
        absent = budget(kernel)
        await connect(kernel, "tg_1", "Alice")
        return absent, budget(kernel)

    absent, present = run(tmp_path, scenario)
    assert absent.veto == agency_c.UNANSWERED
    assert present.veto == agency_c.UNANSWERED  # en sa présence non plus : elle ne harcèle pas


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


# ── Ce qui est dû, ce qui prévient, et la rancune (ADR 0044) ──────────────


class _Frame:
    """Ce qu'un modulateur lit : des faits posés à la main, les réglages par défaut."""

    def __init__(self, facts):
        self.facts, self.root = facts, None
        self.env = SimpleNamespace(params_of=lambda owner, root: None)

    def get(self, key):
        return self.facts[key]


def _resented(handle="user_9", hostility=0.4):
    return _Frame({identity_c.PERSON(handle): handle, affect_c.HOSTILITY(handle): hostility})


@pytest.mark.parametrize("reasons,veto,shift,why", [
    ((goals_c.REMIND, social_c.PRESENT_PERSON), None, 0.0, "tenir parole : ni veto ni décalage"),
    ((email_c.MENTION,), None, P.grudge_inform_shift, "prévenir d'un mail important : décalé, pas empêché"),
    ((projects_c.NEED,), None, P.grudge_inform_shift, "« j'ai besoin de toi pour ton projet » : décalé"),
    ((goals_c.REMIND, email_c.MENTION), None, 0.0, "une promesse à tenir l'emporte"),
    ((social_c.GREETING, social_c.PRESENT_PERSON), social_c.GRUDGE, 0.0, "pas même une salutation (ADR 0013)"),
    ((social_c.CHAT,), social_c.GRUDGE, 0.0, "pas d'envie de bavarder"),
    ((others_c.FOLLOW_UP,), social_c.GRUDGE, 0.0, "« alors, cet entretien ? » n'est pas dû"),
])
def test_a_grudge_holds_back_the_ordinary_never_a_promise(reasons, veto, shift, why):
    from mika.faculties.social.initiative import _restraint

    got = _restraint(None, _resented(), RowView("INITIATIVE", "user_9", 9.0, tuple(sorted(reasons))))
    assert (got.veto, got.shift) == (veto, shift), why
    calm = _restraint(None, _resented(hostility=0.0), RowView("INITIATIVE", "user_9", 9.0, tuple(sorted(reasons))))
    assert calm == Modulation()  # contrôle : sans rancune, rien


def test_what_is_owed_is_declared_once_and_every_restraint_reads_it():
    """Un rappel promis n'est retenu par aucune retenue — rancune, budget d'initiatives, heure où la personne
    répond d'habitude : toutes lisent la même déclaration (``agency.OWED``), aucune ne la redit."""
    from mika.faculties.agency import _budget
    from mika.faculties.others.faculty import _receptive
    from mika.faculties.social.initiative import _restraint

    row = RowView("INITIATIVE", "user_9", 12.0, (goals_c.REMIND,))
    frame = _resented()
    assert [m(None, frame, row) for m in (_restraint, _budget, _receptive)] == [Modulation()] * 3
    assert agency_c.OWED <= agency_c.NOT_SPEAKING_UP and agency_c.INFORMS.isdisjoint(agency_c.NOT_SPEAKING_UP)
    assert social_c.GREETING not in agency_c.OWED  # saluer n'est pas dû : la rancune l'empêche


def test_she_keeps_her_word_even_to_someone_she_resents(tmp_path):
    """BUG-1 : Kev l'insulte douze fois — elle lui en veut —, puis lui demande un rappel. Elle accepte, et le rappel
    part à l'heure : tenir parole ne dépend pas de ce qu'elle ressent. Rien d'autre ne va vers lui."""
    from mika.sim.others import TROLL
    from tests.unit.test_senses import run as run_senses

    async def scenario(kernel, llm, mail, feeds):
        await connect(kernel, "user_9", "Kev")
        for text in TROLL:
            await (await kernel.perceive(said("user_9", text))).reply
            await asyncio.sleep(60)
        hostility = kernel.mind.frame().get(affect_c.HOSTILITY("user_9"))
        await (await kernel.perceive(said("user_9", "rappelle-moi dans 20 minutes de rappeler Paul"))).reply
        asked = kernel.mind.clock.now()
        await asyncio.sleep(4 * HOUR / US)
        return hostility, asked

    r = run_senses(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    hostility, asked = r.result
    assert hostility >= P.grudge  # une rancune installée
    reasons = {e.correlation: set(e.data.reason.split(",")) for e in r.of(rt.EPISODE_STARTED)
               if e.data.kind == "INITIATIVE" and e.data.target == "user_9"}
    said_ = [e for e in r.of(rt.UTTERANCE) if e.correlation in reasons and e.data.visible]
    assert len(said_) == 1 and goals_c.REMIND in reasons[said_[0].correlation]
    assert 15 * MINUTE <= said_[0].at - asked <= 40 * MINUTE  # à l'heure
    assert all(goals_c.REMIND in r_ for r_ in reasons.values())  # rien d'ordinaire vers lui


# ── Une arrivée, pas une reconnexion (BUG-12) ─────────────────────────────


def test_a_reconnection_or_her_restart_is_not_an_arrival(tmp_path):
    """Bea est là depuis 9 h sans écrire : saluée une fois. Une coupure de quelques secondes à 11 h, un redémarrage
    d'elle à 14 h : Bea n'est jamais partie, pas de nouveau « coucou ». Contre-exemple : Chloé, partie deux heures,
    est saluée à son retour (et pas une fois de plus au redémarrage, puisqu'elle était là)."""
    script = Script()
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 9, 0))

    async def first():
        await boot(kernel)
        await connect(kernel, "user_2", "Bea")
        await connect(kernel, "user_3", "Chloé")
        await asyncio.sleep((at_paris(2026, 9, 28, 11, 0) - clock.now()) / US)
        await disconnect(kernel, "user_2")  # une coupure de réseau…
        await asyncio.sleep(5)
        await connect(kernel, "user_2", "Bea", connection="c-user_2-bis")  # … et le navigateur se reconnecte
        await disconnect(kernel, "user_3")  # Chloé s'en va
        await asyncio.sleep((at_paris(2026, 9, 28, 13, 0) - clock.now()) / US)
        await connect(kernel, "user_3", "Chloé")  # … et revient deux heures plus tard
        await asyncio.sleep((at_paris(2026, 9, 28, 14, 0) - clock.now()) / US)
        await kernel.stop()  # elle s'arrête, sans que personne soit parti

    run_virtual(clock, first)
    clock.advance_to(at_paris(2026, 9, 28, 14, 5))
    again, _, _, _ = build(tmp_path, script, clock=clock, llm=llm)

    async def second():
        await boot(again)
        await connect(again, "user_2", "Bea", connection="c-user_2-ter")  # leurs onglets se reconnectent
        await connect(again, "user_3", "Chloé", connection="c-user_3-bis")
        await asyncio.sleep(30 * MINUTE / US)
        greeted = [(e.data.target, local(e.at, PARIS).hour) for e in started(again)
                   if e.data.kind == "INITIATIVE" and social_c.GREETING in e.data.reason.split(",")]
        await again.stop()
        return greeted

    greeted = run_virtual(clock, second)
    assert [h for t, h in greeted if t == "user_2"] == [9], greeted  # une fois, à son arrivée
    assert [h for t, h in greeted if t == "user_3"] == [9, 13], greeted  # partie deux heures : saluée au retour
