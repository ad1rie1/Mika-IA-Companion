"""Le tour de conversation (ADR 0040), par ses intentions.

- une rafale reçoit **une** réponse, qui a lu tous les messages et les règle
  tous (KER-5) ; une réponse supplantée par un nouveau message ne repasse
  jamais derrière la réponse à ce message (KER-12) ;
- une reprise (après une panne, après une supplantation) répond au dernier
  message du tour, jamais en retard à une question dépassée ; trop vieille,
  la question est abandonnée en le disant ;
- une réponse impossible le dit au transport, sans voix, même reprise
  (KER-15) ; se taire aussi ;
- jamais un marqueur de la boucle d'outils comme sa parole (KER-3, P1),
  jamais un silence déguisé (P2) ;
- un épisode est toujours réglé, une fois et une seule (KER-2, KER-26).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mika.app import composition
from mika.contracts import runtime as rt
from mika.kernel.clock import HOUR, MINUTE, US, local
from mika.kernel.episode import Outcome
from mika.ports.delivery import REPLY_ABSTAINED, REPLY_FAILED, REPLY_OUTCOMES
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolCall
from mika.runtime.pipeline import is_silence
from mika.runtime.tools import run_tool_loop
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.scripted import ScriptedLLM
from mika.sim.world import Driver
from tests.fixtures.harness import events_of
from tests.fixtures.mika import AFTERNOON, PARIS, at_paris, boot, build, connect, said

BURST = ("salut", "t'as vu le match hier ?", "allo ?")


def _replies(kernel, handle: str = "user_1") -> list:
    return [e for e in events_of(kernel, rt.UTTERANCE.name) if e.data.kind == "REPLY" and e.data.target == handle]


def _ended(kernel, kind: str = "REPLY") -> list:
    return [e for e in events_of(kernel, rt.EPISODE_ENDED.name) if e.data.kind == kind]


# ── La rafale ─────────────────────────────────────────────────────────────


def test_a_burst_gets_one_reply_that_read_every_message(tmp_path):
    shown: list[str] = []

    def respond(req: LLMRequest) -> LLMResponse:
        if req.role == "reply":
            shown.append("\n".join(m.content for m in req.messages))
        return LLMResponse("Coucou ! Oui, quel match ! [EMOTION:happy:0.5]")

    kernel, clock, llm, out = build(tmp_path, respond, latency=lambda r: 10.0 if r.role == "reply" else 1.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)  # la salutation éventuelle est passée
        sent = []
        for text in BURST:
            sent.append(await kernel.perceive(said("user_1", text)))
            await asyncio.sleep(1)
        reports = [await p.reply for p in sent]
        last_at = clock.now()
        await asyncio.sleep(5)
        await kernel.stop()
        return sent, reports, last_at

    sent, reports, _ = run_virtual(clock, main)
    replies = _replies(kernel)
    assert len(replies) == 1, "trois messages coup sur coup : une seule réponse"
    seqs = tuple(p.seq for p in sent)
    assert replies[0].data.reply_to == seqs[-1] and replies[0].data.answers == seqs
    assert all(text in shown[-1] for text in BURST), "la réponse a lu les trois messages"
    # les deux premières compositions ont été supplantées (jamais un échec) ; la dernière a répondu au tour
    assert [r.outcome for r in reports] == [Outcome.SUPERSEDED, Outcome.SUPERSEDED, Outcome.DONE]
    assert sum(1 for d in out.items if d.source == "reply" and d.kind == "speech") == 1
    assert not kernel.mind.root.slices["runtime"].pending, "plus rien n'attend"


def test_a_burst_she_cannot_answer_is_told_once_on_its_last_message(tmp_path):
    """La réponse impossible se dit par tour, pas par message : trois messages coup sur coup, une réponse qui
    échoue — le transport l'apprend une fois, pour le dernier (une messagerie n'écrit pas trois « désolée »)."""

    def respond(req: LLMRequest) -> LLMResponse:
        if req.role == "reply":
            raise ConnectionError("modèle injoignable")
        return LLMResponse("ok")

    kernel, clock, llm, out = build(tmp_path, respond, latency=lambda r: 10.0 if r.role == "reply" else 1.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        sent = []
        for text in BURST:
            sent.append(await kernel.perceive(said("user_1", text)))
            await asyncio.sleep(1)
        for p in sent:
            await p.reply
        await kernel.lanes.join()
        await asyncio.sleep(120)
        await kernel.stop()
        return tuple(p.seq for p in sent)

    seqs = run_virtual(clock, main)
    told = [(d.reply_to, d.kind) for d in out.items if d.kind in REPLY_OUTCOMES]
    assert told == [(seqs[-1], REPLY_FAILED)], told
    assert not _replies(kernel) and not kernel.mind.root.slices["runtime"].pending


def test_two_separate_turns_still_get_two_replies(tmp_path):
    """Le contre-exemple de la rafale : une minute d'écart, la première réponse partie — deux tours."""
    kernel, clock, llm, out = build(tmp_path, lambda r: LLMResponse("d'accord [EMOTION:happy:0.5]"),
                                    latency=lambda r: 3.0 if r.role == "reply" else 1.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        a = await kernel.perceive(said("user_1", "bon je file"))
        await a.reply
        await asyncio.sleep(60)
        b = await kernel.perceive(said("user_1", "re !"))
        await b.reply
        await kernel.stop()
        return a.seq, b.seq

    a, b = run_virtual(clock, main)
    assert [(u.data.reply_to, u.data.answers) for u in _replies(kernel)] == [(a, (a,)), (b, (b,))]


def test_a_superseded_reply_is_never_said_after_the_next_one(tmp_path):
    """KER-12 : la personne écrit pendant qu'elle compose ; la réponse est recomposée en lisant le nouveau
    message — une seule réponse, jamais l'ancienne qui arrive après la nouvelle."""
    kernel, clock, llm, out = build(tmp_path, lambda r: LLMResponse("voilà [EMOTION:happy:0.5]"),
                                    latency=lambda r: 30.0 if r.role == "reply" else 1.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        first = await kernel.perceive(said("user_1", "tu te souviens de ce que je t'ai dit ?"))
        await asyncio.sleep(5)
        second = await kernel.perceive(said("user_1", "en fait laisse tomber"))
        await first.reply
        await second.reply
        await kernel.lanes.join()
        await asyncio.sleep(5)
        await kernel.stop()
        return first.seq, second.seq

    q1, q2 = run_virtual(clock, main)
    replies = _replies(kernel)
    assert [(u.data.reply_to, u.data.answers) for u in replies] == [(q2, (q1, q2))]
    superseded = [e for e in _ended(kernel) if e.data.outcome == "superseded"]
    assert superseded and superseded[0].data.reply_to == q1 and superseded[0].data.unanswered == ()


# ── Les reprises ──────────────────────────────────────────────────────────


def _driver(tmp_path: Path, latency: float = 20.0, respond=None) -> tuple[Driver, SimClock]:
    clock = SimClock(AFTERNOON)
    llm = ScriptedLLM(clock, respond or (lambda r: LLMResponse("me revoilà [EMOTION:happy:0.5]")),
                      latency=lambda r: latency if r.role == "reply" else 1.0)
    return Driver(tmp_path, composition.for_simulation(), llm, clock), clock


def test_after_a_crash_the_turn_is_answered_once_on_its_last_message(tmp_path):
    driver, clock = _driver(tmp_path)

    async def main():
        await driver.boot()
        await driver.connect("user_1", "Adrien")
        await asyncio.sleep(1200)
        a = await driver.say("user_1", "t'es là ?", wait=False)
        await asyncio.sleep(2)
        b = await driver.say("user_1", "j'ai une question", wait=False)
        await asyncio.sleep(2)  # elle compose : la panne tombe en plein appel
        await driver.restart()
        assert driver.kernel is not None
        await asyncio.sleep(1)
        await driver.kernel.lanes.join()
        await asyncio.sleep(5)
        events = driver.read_events()
        await driver.stop()
        return a.seq, b.seq, events

    a, b, events = run_virtual(clock, main)
    replies = [e for e in events if e.type.name == rt.UTTERANCE.name and e.data.kind == "REPLY"]
    assert [(u.data.reply_to, u.data.answers) for u in replies] == [(b, (a, b))]


def test_a_question_too_old_to_answer_is_abandoned_and_the_transport_told(tmp_path):
    driver, clock = _driver(tmp_path)

    async def main():
        await driver.boot()
        await driver.connect("user_1", "Adrien")
        await asyncio.sleep(1200)
        a = await driver.say("user_1", "t'es là ?", wait=False)
        await asyncio.sleep(2)
        assert driver.kernel is not None
        await driver.crash()
        await asyncio.sleep(3600)  # une heure d'arrêt
        await driver.boot()
        await asyncio.sleep(5)
        events = driver.read_events()
        await driver.stop()
        return a.seq, events

    a, events = run_virtual(clock, main)
    assert not [e for e in events if e.type.name == rt.UTTERANCE.name and e.data.kind == "REPLY"]
    late = [e for e in events if e.type.name == rt.EPISODE_ENDED.name and e.data.outcome == "failed"]
    assert late and late[-1].data.unanswered == (a,) and "trop tard" in late[-1].data.detail
    assert driver.transport is not None and (a, "failed") in driver.transport.no_replies


def test_a_queue_that_fills_while_journaling_settles_the_turn_instead_of_orphaning_it(tmp_path):
    """La file était libre au contrôle, pleine après l'ajout au journal (d'autres messages sont arrivés pendant
    l'écriture) : la question est au journal, en attente, sans épisode pour lui répondre — rien ne la relançait
    avant le prochain démarrage, et la consolidation attendait sa réponse. Le tour est réglé tout de suite, en
    le disant une fois au transport."""
    kernel, clock, _llm, out = build(tmp_path, lambda req: LLMResponse("Coucou !"))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        kernel.lanes.full = lambda kind: False  # le contrôle passe…
        kernel.lanes.max_pending = 0  # …la file est pleine au moment de demander la réponse
        got = await kernel.perceive(said("user_1", "t'es là ?"))
        await asyncio.sleep(30)
        awaiting = set(kernel.mind.frame().get(rt.AWAITING))
        ended = _ended(kernel)
        await kernel.stop()
        return got, awaiting, ended

    got, awaiting, ended = run_virtual(clock, main)
    assert got.reply is None and not got.overloaded  # au journal : son sort est dit par la file de sortie
    assert got.seq not in awaiting  # plus de question orpheline : la consolidation n'attend plus
    assert [(e.data.outcome, e.data.unanswered) for e in ended] == [("failed", (got.seq,))]
    told = [d for d in out.items if d.kind == REPLY_FAILED]
    assert len(told) == 1 and told[0].reply_to == got.seq and told[0].target == "user_1"


def test_a_night_message_found_at_a_restart_still_waits_for_her_morning(tmp_path):
    """La nuit compose avec la reprise : un message de 3 h qui ne l'a pas réveillée, le serveur qui repart à
    4 h — rien ne part au milieu de sa nuit ; au réveil, une réponse."""
    def script(req: LLMRequest) -> LLMResponse:
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role in ("journal", "dream", "murmur", "narrative"):
            return LLMResponse("hmm")
        return LLMResponse("d'accord [EMOTION:happy:0.5]")

    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 20, 0))

    async def first():
        await boot(kernel)
        await asyncio.sleep((at_paris(2026, 9, 29, 3, 0) - clock.now()) / US)
        await kernel.perceive(said("user_2", "tu dors ?"))
        await asyncio.sleep(MINUTE / US)
        await kernel.stop()

    run_virtual(clock, first)
    clock.advance_to(at_paris(2026, 9, 29, 4, 0))
    again, _, _, _ = build(tmp_path, script, clock=clock, llm=llm)

    async def second():
        await boot(again)
        await asyncio.sleep(HOUR / US)
        at_night = [e for e in events_of(again, rt.UTTERANCE.name) if e.data.target == "user_2"]
        await asyncio.sleep((at_paris(2026, 9, 29, 11, 0) - clock.now()) / US)
        later = [e for e in events_of(again, rt.UTTERANCE.name) if e.data.target == "user_2"]
        await again.stop()
        return at_night, later

    at_night, later = run_virtual(clock, second)
    assert not at_night, "à 4 h, elle dort encore : la question attend son réveil"
    assert len(later) == 1 and local(later[0].at, PARIS).hour >= 5


# ── Ce qui ne part jamais ─────────────────────────────────────────────────


SILENCES = ["[SILENCE]", "[silence]", "[SILENCE].", "**[SILENCE]**", "(silence)", "« [SILENCE] »", "SILENCE",
            "[SILENCE] (je préfère la laisser tranquille)", "Bon, je vais rien dire. [SILENCE]", "*silence*",
            "Silence.", "  [ Silence ]  "]
NOT_SILENCES = ["le silence de la nuit me plaît", "Silence radio de ton côté depuis hier !",
                "(silence) bon, tu m'expliques ?", "un silence gênant, haha"]


@pytest.mark.parametrize("text", SILENCES)
def test_silence_is_recognised_in_its_real_forms(text):
    assert is_silence(text)


@pytest.mark.parametrize("text", NOT_SILENCES)
def test_a_real_message_with_the_word_is_not_silence(text):
    assert not is_silence(text)


@pytest.mark.parametrize("text", ["**[SILENCE]**", "Bon, je vais rien dire. [SILENCE]"])
def test_a_dressed_up_silence_is_never_delivered(tmp_path, text):
    kernel, clock, llm, out = build(tmp_path, lambda r: LLMResponse(text if r.role == "reply" else "ok"))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        p = await kernel.perceive(said("user_1", "bon allez, salut"))
        report = await p.reply
        await asyncio.sleep(5)
        await kernel.stop()
        return p.seq, report

    seq, report = run_virtual(clock, main)
    assert report.outcome is Outcome.ABSTAINED and not _replies(kernel)
    assert not [d for d in out.items if d.source == "reply" and d.kind == "speech"]
    told = [d for d in out.items if d.kind in REPLY_OUTCOMES]
    assert [(d.reply_to, d.kind, d.text) for d in told] == [(seq, REPLY_ABSTAINED, "")]  # sans voix ni texte


def test_the_tool_loop_never_delivers_its_markers(tmp_path):
    """KER-3 / P1 : au plafond d'appels d'outils, un dernier tour sans outil lui demande de répondre ; ce
    qu'elle répond part, jamais « [trop d'appels d'outils…] »."""
    turns = [0]

    def respond(req: LLMRequest) -> LLMResponse:
        if req.role != "reply":
            return LLMResponse("ok")
        if "sans appeler d'outil" in req.messages[-1].content:
            return LLMResponse("Je n'ai rien de prévu de spécial, en fait ! [EMOTION:happy:0.5]")
        turns[0] += 1
        return LLMResponse("je vérifie…", tool_calls=(ToolCall(f"t{turns[0]}", "memory_search", {"query": "x"}),),
                           stop="tool_use")

    kernel, clock, llm, out = build(tmp_path, respond)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        p = await kernel.perceive(said("user_1", "tu peux regarder ce que t'as prévu ?"))
        report = await p.reply
        await asyncio.sleep(5)
        texts = [kernel.mind.content_text(u.data.text) for u in _replies(kernel)]
        await kernel.stop()
        return report, texts

    report, said_ = run_virtual(clock, main)
    assert report.outcome is Outcome.DONE and said_ == ["Je n'ai rien de prévu de spécial, en fait !"]
    assert not any("[" in (d.text or "") for d in out.items if d.source == "reply")


def test_a_loop_that_cannot_finish_fails_and_says_nothing(tmp_path):
    """Même le dernier tour veut encore un outil : rien n'est dit (ni le préambule « je vérifie… »), la
    réponse échoue et le transport le sait."""

    def respond(req: LLMRequest) -> LLMResponse:
        if req.role != "reply":
            return LLMResponse("ok")
        return LLMResponse("je vérifie…", tool_calls=(ToolCall("t", "memory_search", {"query": "x"}),),
                           stop="tool_use")

    kernel, clock, llm, out = build(tmp_path, respond)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        p = await kernel.perceive(said("user_1", "tu peux regarder ?"))
        report = await p.reply
        await asyncio.sleep(5)
        await kernel.stop()
        return p.seq, report

    seq, report = run_virtual(clock, main)
    assert report.outcome is Outcome.FAILED and not _replies(kernel)
    assert [(d.reply_to, d.kind) for d in out.items if d.kind in REPLY_OUTCOMES] == [(seq, REPLY_FAILED)]


class _Releasing:
    """Une passerelle qui sait relâcher une boucle (un fournisseur à session, la CLI de Claude Code)."""

    def __init__(self, responses: list[LLMResponse], hang: bool = False) -> None:
        self.responses = responses
        self.hang = hang
        self.released: list[str] = []
        self.calls: list[LLMRequest] = []

    async def call(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        if self.hang:
            await asyncio.sleep(3600)
        return self.responses.pop(0)

    def release(self, call_id: str) -> None:
        self.released.append(call_id)


def test_a_finished_tool_loop_is_released_however_it_ends():
    """Jonction WP7 : la boucle finie — une réponse, le plafond de tours, ou coupée en route — est relâchée
    une fois (``release(call_id)``), sans attendre le délai d'inactivité du fournisseur ; la clôture au
    plafond a la forme « résultats d'outils, puis un mot de l'utilisateur » que la session sait finir."""
    req = LLMRequest(role="reply", call_id="ep#0", system_stable="Tu es Mika.",
                     messages=(Message("user", "salut"),))
    looping = LLMResponse("je vérifie…", tool_calls=(ToolCall("t", "inconnu", {}),), stop="tool_use")

    async def main():
        plain = _Releasing([LLMResponse("coucou")])
        await run_tool_loop(plain, req, {}, lambda spec, cid: None, max_turns=4)
        capped = _Releasing([looping, looping, LLMResponse("bon, voilà")])
        out = await run_tool_loop(capped, req, {}, lambda spec, cid: None, max_turns=2)
        hung = _Releasing([], hang=True)
        task = asyncio.ensure_future(run_tool_loop(hung, req, {}, lambda spec, cid: None, max_turns=2))
        await asyncio.sleep(1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return plain, capped, out, hung

    plain, capped, out, hung = run_virtual(SimClock(AFTERNOON), main)
    assert plain.released == ["ep#0"] and capped.released == ["ep#0"] and hung.released == ["ep#0"]
    closing = capped.calls[-1].messages
    assert out.text == "bon, voilà" and [m.role for m in closing[-2:]] == ["tool", "user"]


# ── Toujours réglé, une fois ──────────────────────────────────────────────


def test_an_unexpected_exception_still_settles_the_episode(tmp_path):
    """KER-2 : la persona lève — l'épisode est réglé (``failed``), rien ne reste ouvert, la question ne reste
    pas en attente, et le transport sait qu'elle n'aura pas de réponse."""
    broken = [False]

    def persona(frame, depth):
        if broken[0]:
            raise KeyError("persona illisible")
        return composition.persona_for(frame, depth)

    kernel, clock, llm, out = build(tmp_path, lambda r: LLMResponse("ok [EMOTION:happy:0.5]"), persona=persona)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        broken[0] = True
        p = await kernel.perceive(said("user_1", "coucou"))
        report = await p.reply
        await asyncio.sleep(5)
        rs = kernel.mind.root.slices["runtime"]
        await kernel.stop()
        return p.seq, report, rs

    seq, report, rs = run_virtual(clock, main)
    assert report.outcome is Outcome.FAILED and "persona illisible" in report.detail
    assert not rs.open and seq not in rs.pending
    ended = _ended(kernel)
    assert len(ended) == 1 and ended[0].data.unanswered == (seq,)
    assert [(d.reply_to, d.kind) for d in out.items if d.kind in REPLY_OUTCOMES] == [(seq, REPLY_FAILED)]


def test_an_abstention_ends_its_episode_exactly_once(tmp_path):
    """KER-26 : se taire règle l'épisode une fois — jamais un second ``superseded`` derrière, même quand
    quelqu'un écrit au même instant."""
    kernel, clock, llm, out = build(tmp_path, lambda r: LLMResponse("[SILENCE]" if r.role == "reply" else "ok"),
                                    latency=lambda r: 2.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await connect(kernel, "user_2", "Bea")
        await asyncio.sleep(1200)
        p = await kernel.perceive(said("user_1", "bonne nuit"))
        await asyncio.sleep(2.0)
        other = await kernel.perceive(said("user_2", "hello"))
        await p.reply
        await other.reply
        await asyncio.sleep(5)
        await kernel.stop()

    run_virtual(clock, main)
    per_episode: dict[str, int] = {}
    for e in _ended(kernel):
        per_episode[e.correlation] = per_episode.get(e.correlation, 0) + 1
    assert per_episode and set(per_episode.values()) == {1}


def test_a_resumed_reply_that_fails_is_told_too(tmp_path):
    """KER-15 : une réponse reprise au démarrage n'a personne qui l'attend ; si elle échoue, le transport le
    sait quand même (par la file de sortie)."""
    down = [False]

    def respond(req: LLMRequest) -> LLMResponse:
        if req.role == "reply" and down[0]:
            raise RuntimeError("le modèle est tombé")
        return LLMResponse("ok [EMOTION:happy:0.5]")

    driver, clock = _driver(tmp_path, latency=20.0, respond=respond)

    async def main():
        await driver.boot()
        await driver.connect("user_1", "Adrien")
        await asyncio.sleep(1200)
        a = await driver.say("user_1", "t'es là ?", wait=False)
        await asyncio.sleep(5)
        await driver.restart()
        down[0] = True  # la reprise tombe sur un modèle en panne
        assert driver.kernel is not None
        await asyncio.sleep(1)
        await driver.kernel.lanes.join()
        await asyncio.sleep(10)
        await driver.stop()
        return a.seq

    a = run_virtual(clock, main)
    assert driver.transport is not None and driver.transport.no_replies == [(a, "failed")]


def test_lag_of_a_reply_is_its_model_time_not_the_queue(tmp_path):
    """La réponse part dans le temps du modèle : sans fond ni file, ``+latence``."""
    kernel, clock, llm, out = build(tmp_path, lambda r: LLMResponse("oui ! [EMOTION:happy:0.5]"),
                                    latency=lambda r: 4.0 if r.role == "reply" else 1.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        t0 = clock.now()
        p = await kernel.perceive(said("user_1", "t'es là ?"))
        await p.reply
        lag = (clock.now() - t0) / US
        await kernel.stop()
        return lag

    assert run_virtual(clock, main) < 6
