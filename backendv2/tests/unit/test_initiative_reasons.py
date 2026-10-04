"""Écrire pour une raison, et pour la personne d'abord (ADR 0047, HUM-10) ; ce qu'on ne remet pas à plus tard
(restes de l'ADR 0044), par ses intentions.

- une initiative dit sa raison la plus forte, et au plus une seconde (« et aussi ») — jamais trois consignes côte à
  côte ; ce qui est dû ou prévient ne se tait jamais au profit d'une autre ;
- de quoi parler : ce qui concerne la personne passe avant ses choses à elle (le moment de sa vie avant son projet
  fini), ce qu'elle lui a raconté de plus important avant le plus récent, et une matière dite ne resert pas ;
- elle ne se ravise pas de tenir parole ni de prévenir (le murmure peut y penser, jamais « pas maintenant ») ;
- prévenir d'un mail important ne subit pas l'allongement de sa période réfractaire par les initiatives restées
  sans réponse, ni de s'être ravisée de lui écrire pour autre chose — la période de base, si.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mika.app import composition
from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import email as email_c
from mika.contracts import expression as expression_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.agency import brief, restraint
from mika.faculties.expression import murmur
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.frame import EpisodeRef, Frame
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind
from tests.fixtures.mika import DOC, at_paris, befriend, build, connect

MONDAY_10H = at_paris(2026, 9, 28, 10, 0)


def script(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    return LLMResponse("hmm")


def run(tmp_path, scenario, *, overrides=None, start=MONDAY_10H):
    kernel, clock, llm, _ = build(tmp_path, script, start=start)

    async def main():
        await kernel.start(configure=lambda k: composition.configure(k, DOC, overrides))
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def voice():
    return VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m")


# ── Une raison, au plus deux ──────────────────────────────────────────────


def _brief(frame: Frame, target: str, parts, args) -> str:
    reasons = tuple(sorted({r for _s, r, _e in parts}))
    ep = EpisodeRef("e", Kind.INITIATIVE, target, attrs=FrozenDict({"reasons": reasons, "args": FrozenDict(args)}))
    framed = Frame(frame.root, frame.now, frame.env, frame.audience, ep)
    return brief(framed, SimpleNamespace(selected=SimpleNamespace(parts=tuple(parts))))


def test_an_initiative_says_its_strongest_reason_and_at_most_a_second(tmp_path):
    comfort, share = "Tu ne vas pas très bien : tu as envie de lui parler.", "Tu as fini quelque chose : raconte-le."
    remind, mail = "C'est l'heure de son rappel.", "Un mail important vient d'arriver pour elle."

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        frame = kernel.mind.frame()
        many = _brief(frame, "ext_1", [("social", social_c.COMFORT, 10.0), ("goals", goals_c.SHARE, 9.0),
                                      ("needs", needs_c.NEED_SOCIAL, 3.0), ("affect", "mood_overflow", 2.0)],
                      {"brief:social": comfort, "brief:goals": share})
        owed = _brief(frame, "ext_1", [("goals", goals_c.REMIND, 12.0), ("email", email_c.MENTION, 8.0),
                                      ("social", social_c.RECONTACT, 10.5)],
                      {"brief:goals": remind, "brief:email": mail, "brief:social": comfort})
        lone = _brief(frame, "ext_1", [("social", social_c.COMFORT, 10.0), ("needs", needs_c.NEED_SOCIAL, 2.0)],
                      {"brief:social": comfort})
        return many, owed, lone

    many, owed, lone = run(tmp_path, scenario)
    assert f"- {comfort}" in many and "- Et aussi : tu as fini" in many  # la plus forte, puis une seconde
    assert "déborde" not in many and "envie de compagnie" not in many  # pas trois consignes côte à côte
    assert remind in owed and "Et aussi : un mail important" in owed  # ce qui est dû ou prévient se dit toujours
    assert comfort not in owed
    assert comfort in lone and "Et aussi" not in lone  # une envie bien plus faible ne s'ajoute pas


# ── De quoi parler : la personne d'abord ──────────────────────────────────


async def _her_finished_exploration(kernel):
    title = Content.of("Fouiller un peu du côté du café", level=0)
    await kernel.mind.append([
        goals_c.GOAL_OPENED.draft(kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=title, sensitivity=0,
                                  bundles=("goals", "rss"), source="interest:Le café", origin=goals_c.FROM_INTEREST),
        goals_c.STEP_REPORTED.draft(goal=1, verdict=goals_c.DONE, summary=Content.of("lu", level=0), proven=True,
                                    tools=("rss_read",)),
        goals_c.GOAL_CLOSED.draft(goal=1, status=goals_c.ACHIEVED, kind=goals_c.EXPLORATION, authority=goals_c.SELF,
                                  title=title, sensitivity=0)], emitter="goals", correlation="but", origin=Origin.GENESIS)


async def _believed(kernel, text: str, importance: float, n: int):
    await kernel.mind.append([memory_c.BELIEVED.draft(text=Content.of(text, level=1), about=("ext_1",), sensitivity=1,
                                                      source="ext_1", importance=importance)],
                             emitter="memory", correlation=f"croyance{n}", origin=Origin.GENESIS)


def test_her_friends_life_comes_before_her_own_finished_thing(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await _her_finished_exploration(kernel)
        mine = kernel.mind.frame().get(needs_c.MATTER("ext_1"))
        await kernel.mind.append([memory_c.EVENT_NOTED.draft(
            text=Content.of("son entretien chez Ubisoft", level=2), when=kernel.mind.clock.now() + DAY,
            about=("ext_1",), told_by=("ext_1",))], emitter="memory", correlation="moment", origin=Origin.GENESIS)
        theirs = kernel.mind.frame().get(needs_c.MATTER("ext_1"))
        return mine, theirs

    mine, theirs = run(tmp_path, scenario)
    assert mine is not None and mine.kind == needs_c.DONE_MATTER  # contre-exemple : rien sur elle, son projet
    assert theirs is not None and theirs.kind == needs_c.MOMENT_MATTER  # sa vie à elle d'abord


def test_what_a_third_told_of_her_life_is_never_a_matter_with_her(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await kernel.mind.append([memory_c.EVENT_NOTED.draft(
            text=Content.of("son départ au Japon", level=2), when=kernel.mind.clock.now() + DAY, about=("ext_1",),
            told_by=("ext_2",))], emitter="memory", correlation="moment", origin=Origin.GENESIS)
        return kernel.mind.frame().get(needs_c.MATTER("ext_1"))

    assert run(tmp_path, scenario) is None  # le lui dire trahirait qui le lui a raconté


def test_what_she_told_counts_by_its_weight_and_a_matter_said_is_not_said_again(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await _believed(kernel, "Son chat Moustache est malade", 0.9, 1)
        await asyncio.sleep(HOUR / US)
        await _believed(kernel, "Elle a mangé des pâtes ce midi", 0.2, 2)
        first = kernel.mind.frame().get(needs_c.MATTER("ext_1"))
        texts = kernel.mind.store.content([first.ref])
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind="INITIATIVE", target="ext_1", reason="need_social")],
                                 emitter="runtime", correlation="ep1", origin=Origin.KERNEL)
        await kernel.mind.append([rt.UTTERANCE.draft(kind="INITIATIVE", text=Content.of("et Moustache ?"),
                                                     target="ext_1", voice=voice(),
                                                     provenance=(f"matter:{first.ref}",))],
                                 emitter="runtime", correlation="ep1", origin=Origin.KERNEL)
        then = kernel.mind.frame().get(needs_c.MATTER("ext_1"))
        return texts[first.ref], then.ref if then is not None else None, first.ref

    first_text, then_ref, first_ref = run(tmp_path, scenario)
    assert "Moustache" in first_text  # le plus important, pas le plus récent
    assert then_ref != first_ref  # dite une fois, elle ne resert pas


# ── Tenir parole, prévenir : ni « pas maintenant », ni la rancune d'être ignorée ──


def test_she_never_thinks_better_of_keeping_her_word_or_warning_someone(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(2 * HOUR / US)  # aucun murmure récent
        frame = kernel.mind.frame()

        def prelude(reason):
            return murmur(frame, SimpleNamespace(reason=reason, target="user_1", trigger=f"t:{reason}",
                                                 selected=None))
        return prelude(goals_c.REMIND), prelude(email_c.MENTION), prelude(needs_c.NEED_SOCIAL)

    always_adrift = {"expression": {"murmur_chance": 1.0, "murmur_charged_chance": 1.0, "murmur_adrift": 1.0}}
    remind, mention, chat = run(tmp_path, scenario, overrides=always_adrift)
    assert chat is not None and chat.instead  # contre-exemple : bavarder, elle peut s'en raviser
    assert remind is not None and not remind.instead  # tenir parole : elle y pense, et elle le fait
    assert mention is not None and not mention.instead  # prévenir : de même


async def _ignored_initiative(kernel, n: int, handle: str):
    """Une initiative dite (comptée au budget), restée sans réponse."""
    eid = f"ep-ignoree-{n}"
    await kernel.mind.append([rt.EPISODE_STARTED.draft(kind="INITIATIVE", target=handle, reason="need_social")],
                             emitter="runtime", correlation=eid, origin=Origin.KERNEL)
    await kernel.mind.append([rt.UTTERANCE.draft(kind="INITIATIVE", text=Content.of("coucou ?"), target=handle,
                                                 channel="web", voice=voice())],
                             emitter="runtime", correlation=eid, origin=Origin.KERNEL)
    await kernel.mind.append([rt.EPISODE_ENDED.draft(kind="INITIATIVE", outcome="done", target=handle)],
                             emitter="runtime", correlation=eid, origin=Origin.KERNEL)


def test_warning_of_an_urgent_mail_does_not_wait_out_being_ignored(tmp_path):
    """Deux initiatives (à d'autres) restées sans réponse allongent sa période réfractaire (×2,5 chacune) : envers
    l'ordinaire, c'est voulu ; prévenir sa propriétaire d'un mail urgent n'a pas à attendre deux heures de plus
    (sonde du 2026-10-02). La période de base reste (pas trois annonces en trois messages d'affilée)."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await _ignored_initiative(kernel, 1, "user_2")
        await asyncio.sleep(40 * MINUTE / US)
        await _ignored_initiative(kernel, 2, "user_3")
        await asyncio.sleep(45 * MINUTE / US)
        frame = kernel.mind.frame()
        ignored = frame.get(attention_c.IGNORED)
        ordinary = restraint(frame, "user_1", (needs_c.NEED_SOCIAL,))
        warns = restraint(frame, "user_1", (email_c.MENTION,))
        # elle s'est ravisée de lui écrire pour bavarder
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind="MURMUR", target=None,
                                                           reason=f"{expression_c.MURMUR_ADRIFT}:user_1")],
                                 emitter="runtime", correlation="murmure", origin=Origin.KERNEL)
        await kernel.mind.append([rt.UTTERANCE.draft(kind="MURMUR", text=Content.of("bof, pas maintenant"),
                                                     voice=voice())],
                                 emitter="runtime", correlation="murmure", origin=Origin.KERNEL)
        frame = kernel.mind.frame()
        return (ignored, ordinary, warns, restraint(frame, "user_1", (needs_c.NEED_SOCIAL,)),
                restraint(frame, "user_1", (email_c.MENTION,)))

    ignored, ordinary, warns, chat_after, warn_after = run(tmp_path, scenario)
    assert ignored == 2  # le décor : deux initiatives ignorées d'affilée
    assert ordinary.veto is None and warns.veto is None
    assert warns.shift < -0.5  # la période de base pèse encore un peu…
    assert warns.shift > ordinary.shift + 2.0  # … mais bien moins que l'allongement par les ignorées
    assert chat_after.veto == agency_c.CHANGED_MIND  # contre-exemple : bavarder attend
    assert warn_after.veto is None  # prévenir, non
