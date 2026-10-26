"""Les bords des fournisseurs et de la passerelle (sans réseau) :

- un refus qui porte un appel d'outil n'exécute rien ;
- une pause de la boucle serveur est reprise, pas prise pour une fin ;
- une réponse n'attend jamais derrière le fond (un créneau réservé), et un appel
  fait pendant une réponse hérite de sa priorité ;
- chaque appel a un délai ; le repli reçoit le temps qui reste ;
- une boucle d'outils reste sur son fournisseur, et ne bascule jamais vers un
  fournisseur qui referait ses outils ;
- une sortie coupée par son plafond : redemandée (structurée) ou coupée à la
  dernière phrase (parole) ;
- un 400 sur la *valeur* de ``max_tokens`` ne fait pas changer de paramètre ;
- les tarifs des identifiants datés et des familles courantes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import openai
import pytest
from anthropic.types import Message as AnthropicMessage
from pydantic import BaseModel

from mika.adapters.llm.claude import ClaudeBackend
from mika.adapters.llm.config import BackendSpec, LLMConfig, build_backend, build_gateway
from mika.adapters.llm.gateway import Gateway, last_sentence, trim_speech
from mika.adapters.llm.ollama import OllamaBackend
from mika.adapters.llm.openai_compat import OpenAICompatBackend
from mika.adapters.llm.pricing import price_usd
from mika.kernel.clock import ManualClock
from mika.kernel.faculty import ToolSpec
from mika.kernel.prompt import PromptBudgetError
from mika.ports.llm import (
    DEADLINE_AT,
    RETRY_AFTER_CUT,
    LLMRequest,
    LLMResponse,
    Message,
    PersonaRender,
    ToolCall,
    Usage,
)
from mika.ports.llm_budget import LLMLimits
from mika.runtime.tools import ToolResult, declare, run_tool_loop
from tests.contract.test_llm_backends import (
    FakeAnthropic,
    FakeOllama,
    FakeOpenAI,
    bad_request,
    ollama_reply,
    request,
)


def claude(*content: dict[str, Any], stop: str) -> AnthropicMessage:
    return AnthropicMessage.model_validate({
        "id": "msg", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": list(content),
        "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}})


class SendArgs(BaseModel):
    to: str


def email_send(ran: list[str]) -> ToolSpec:
    async def handler(args: SendArgs, ctx: Any) -> ToolResult:
        ran.append(args.to)
        return ToolResult(content="envoyé")

    return ToolSpec(owner="email", name="email_send", description="envoie", args=SendArgs, handler=handler,
                    bundle="email", episodes=frozenset({"REPLY"}))


# ── Claude : refus, pause ─────────────────────────────────────────────────


@pytest.mark.parametrize("stop, executed", [("refusal", False), ("tool_use", True)])
async def test_a_refusal_carrying_a_tool_use_executes_nothing(stop: str, executed: bool):
    ran: list[str] = []
    spec = email_send(ran)
    first = claude({"type": "tool_use", "id": "toolu_1", "name": "email_send", "input": {"to": "a@b.c"}}, stop=stop)
    final = claude({"type": "text", "text": "ok"}, stop="end_turn")
    gw = Gateway({"c": ClaudeBackend("k", "claude-opus-5-5", client=FakeAnthropic(first, final))}, {"reply": "c"},
                 clock=ManualClock(0))
    req = LLMRequest(role="reply", call_id="e#0", system_stable="S", messages=(Message("user", "salut"),),
                     tools=declare([spec]))
    loop = await run_tool_loop(gw, req, {spec.name: spec}, lambda s, cid: SimpleNamespace(call_id=cid), max_turns=4)
    assert (ran == ["a@b.c"]) is executed
    if not executed:
        assert loop.stop == "refusal" and loop.calls == []


async def test_a_paused_server_turn_is_resumed_and_not_taken_for_its_end():
    paused = claude({"type": "text", "text": "Attends, je cherche. "},
                    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "tool_search_tool_bm25",
                     "input": {"query": "mail"}}, stop="pause_turn")
    done = claude({"type": "text", "text": "Voilà ce que j'ai trouvé."}, stop="end_turn")
    fake = FakeAnthropic(paused, done)
    resp = await ClaudeBackend("k", "claude-opus-5-5", client=fake).complete(request(Message("user", "x")))
    assert len(fake.create.calls) == 2
    resumed = fake.create.calls[1]["messages"][-1]
    assert resumed["role"] == "assistant" and resumed["content"][-1]["type"] == "server_tool_use"
    assert resp.stop == "end" and resp.text.endswith("Voilà ce que j'ai trouvé.")
    assert resp.usage.output_tokens == 10  # les deux tours comptés


async def test_pauses_are_resumed_a_bounded_number_of_times():
    pause = {"type": "server_tool_use", "id": "s", "name": "tool_search_tool_bm25", "input": {"query": "x"}}
    fake = FakeAnthropic(*[claude(pause, stop="pause_turn") for _ in range(10)])
    await ClaudeBackend("k", "claude-opus-5-5", client=fake).complete(request(Message("user", "x")))
    assert len(fake.create.calls) == 4  # le premier tour et trois reprises


async def test_a_foreground_call_asks_the_sdk_for_fewer_retries():
    seen: dict[str, Any] = {}
    inner = FakeAnthropic(claude({"type": "text", "text": "ok"}, stop="end_turn"))

    class WithOptions(SimpleNamespace):
        def with_options(self, **kw):
            seen.update(kw)
            return inner

    backend = ClaudeBackend("k", "claude-opus-5-5", client=WithOptions(messages=None))
    req = request(Message("user", "x"))
    await backend.complete(LLMRequest(**{**{f: getattr(req, f) for f in req.__dataclass_fields__}, "priority": 0}))
    assert seen == {"max_retries": 1}


# ── La passerelle : créneaux, priorité, délais, boucles ───────────────────


class Slow:
    name = "slow"

    def __init__(self, delay: float = 1.0, name: str = "slow") -> None:
        self.delay = delay
        self.name = name
        self.seen: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        await asyncio.sleep(self.delay if req.priority else 0.05)
        return LLMResponse("ok", model="claude-sonnet-5-5")


async def test_a_reply_never_waits_behind_background_calls():
    cfg = LLMConfig(backends={"api": BackendSpec(kind="claude", model="claude-sonnet-5-5")},
                    routes={"reply": "api", "extract": "api"})
    gw = build_gateway(cfg, ManualClock(0), make=lambda n, s: Slow(1.0))
    background = [asyncio.create_task(gw.call(LLMRequest(role="extract", call_id=f"bg{i}#0", system_stable="s",
                                                         priority=2))) for i in range(6)]
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    await gw.call(LLMRequest(role="reply", call_id="r#0", system_stable="s", priority=0, lane="conversation",
                             persona=PersonaRender("p", "h", "full")))
    assert time.monotonic() - t0 < 0.5  # un créneau sur quatre est gardé pour elle
    assert gw.status()[0]["busy"] <= 4
    await asyncio.gather(*background)


async def test_a_call_made_during_a_reply_inherits_its_priority():
    slow = Slow(0.0)
    gw = Gateway({"s": slow}, {"reply": "s", "caption": "s", "extract": "s"}, clock=ManualClock(0))

    async def episode() -> None:
        await gw.call(LLMRequest(role="reply", call_id="ep#0", system_stable="s", priority=0, lane="conversation",
                                 meta={"episode": "ep"}))
        # un outil qui regarde par la caméra, au milieu de la réponse
        await gw.call(LLMRequest(role="caption", call_id="toolu_1:look", system_stable="s", priority=3,
                                 lane="background"))

    async def elsewhere() -> None:
        await gw.call(LLMRequest(role="extract", call_id="x#0", system_stable="s", priority=3, lane="background"))

    await asyncio.gather(asyncio.create_task(episode()), asyncio.create_task(elsewhere()))
    by_id = {r.call_id: (r.priority, r.lane) for r in slow.seen}
    assert by_id["toolu_1:look"] == (0, "conversation")
    assert by_id["x#0"] == (3, "background")  # une autre tâche n'hérite de rien


class Hang:
    def __init__(self, name: str) -> None:
        self.name = name

    async def complete(self, req: LLMRequest) -> LLMResponse:
        await asyncio.sleep(3600)
        raise AssertionError


class Quick:
    def __init__(self, name: str = "quick", text: str = "réponse de repli", resumes: bool = True) -> None:
        self.name = name
        self.text = text
        self.resumes_tool_loops = resumes
        self.seen: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        return LLMResponse(self.text, model="spare-1")


async def test_a_mute_provider_times_out_without_calling_another_provider(caplog):
    spare = Quick("spare")
    gw = Gateway({"main": Hang("main"), "spare": spare}, {"reply": "main"}, clock=ManualClock(0),
                 deadlines={"conversation": 0.1})
    with pytest.raises(TimeoutError):
        await gw.call(LLMRequest(role="reply", call_id="r#0", system_stable="s", lane="conversation"))
    assert not spare.seen
    assert [(t.backend, t.outcome) for t in gw.traces] == [("main", "timeout")]
    assert "r#0" in caplog.text and "délai dépassé" in caplog.text


class Flaky:
    def __init__(self, name: str) -> None:
        self.name = name
        self.fail = True
        self.seen: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        if self.fail:
            raise ConnectionError("injoignable")
        return LLMResponse("principal", model="m")


MID_LOOP = (Message("user", "note pain"),
            Message("assistant", "", tool_calls=(ToolCall("t1", "note_add", {"what": "pain"}),)),
            Message("tool", "noté", tool_call_id="t1", name="note_add"))


async def test_a_tool_loop_never_switches_to_a_provider_that_would_redo_its_tools():
    main, cli = Flaky("main"), Quick("cli", resumes=False)
    gw = Gateway({"main": main, "cli": cli}, {"reply": "main"}, clock=ManualClock(0))
    first = LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP[:1])
    main.fail = False
    await gw.call(first)
    main.fail = True
    with pytest.raises(ConnectionError):  # en cours de boucle : pas de bascule vers la CLI (outils rejoués)
        await gw.call(LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP))
    assert cli.seen == []


async def test_a_failed_loop_can_resume_on_its_original_provider():
    main, spare = Flaky("main"), Quick("spare")
    gw = Gateway({"main": main, "spare": spare}, {"reply": "main"}, clock=ManualClock(0))
    req = LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP[:1])
    with pytest.raises(ConnectionError):
        await gw.call(req)
    main.fail = False
    await gw.call(replace(req, messages=MID_LOOP))
    assert len(main.seen) == 2 and not spare.seen


# ── Coupé par le plafond ──────────────────────────────────────────────────


class Cut:
    def __init__(self, *outs: LLMResponse) -> None:
        self.name = "cut"
        self.outs = list(outs)
        self.seen: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        return self.outs.pop(0)


async def test_a_spoken_reply_cut_by_its_cap_ends_on_its_last_full_sentence():
    cut = Cut(LLMResponse("Oui, je m'en souviens. On était au bord du lac et tu m'as dit que tu", stop="max_tokens"))
    gw = Gateway({"c": cut}, {"reply": "c"}, clock=ManualClock(0), voice_roles=frozenset({"reply"}))
    resp = await gw.call(LLMRequest(role="reply", call_id="r#0", system_stable="s",
                                    persona=PersonaRender("p", "h", "full")))
    assert resp.text == "Oui, je m'en souviens." and len(cut.seen) == 1


async def test_a_structured_output_cut_by_its_cap_is_asked_again_with_more_room():
    cut = Cut(LLMResponse('{"souvenirs": [{"texte": "Alice m', stop="max_tokens"),
              LLMResponse('{"souvenirs": []}', stop="end"))
    gw = Gateway({"c": cut}, {"extract": "c"}, clock=ManualClock(0))
    resp = await gw.call(LLMRequest(role="extract", call_id="x#0", system_stable="s", max_tokens=1000))
    assert resp.text == '{"souvenirs": []}'
    assert [r.max_tokens for r in cut.seen] == [1000, 2000] and cut.seen[1].meta[RETRY_AFTER_CUT]


async def test_a_spoken_reply_that_spent_everything_thinking_is_asked_again():
    cut = Cut(LLMResponse("", stop="max_tokens"), LLMResponse("Coucou toi.", stop="end"))
    gw = Gateway({"c": cut}, {"reply": "c"}, clock=ManualClock(0), voice_roles=frozenset({"reply"}))
    resp = await gw.call(LLMRequest(role="reply", call_id="r#0", system_stable="s",
                                    persona=PersonaRender("p", "h", "full")))
    assert resp.text == "Coucou toi." and len(cut.seen) == 2


def test_speech_trimming():
    assert last_sentence("Bon. Alors « oui ! » et puis") == "Bon. Alors « oui ! »"
    assert last_sentence("rien de complet") == ""
    assert trim_speech("rien de complet ici") == "rien de complet…"
    assert trim_speech("") == ""


async def test_a_local_model_lifts_its_own_cap_when_asked_again_after_a_cut():
    fake = FakeOllama(ollama_reply("a"), ollama_reply("b"))
    backend = OllamaBackend("gemma4:12b", client=fake)
    await backend.complete(request(Message("user", "x"), max_tokens=4096))
    retry = request(Message("user", "x"), max_tokens=4096)
    await backend.complete(LLMRequest(**{**{f: getattr(retry, f) for f in retry.__dataclass_fields__},
                                         "meta": {RETRY_AFTER_CUT: True}}))
    assert [c["options"]["num_predict"] for c in fake.chat.calls] == [768, 4096]


# ── Compatible OpenAI : un nom refusé n'est pas une valeur refusée ────────


async def test_a_value_error_on_max_tokens_does_not_rename_the_parameter_for_life():
    fake = FakeOpenAI(bad_request(openai, "max_tokens is too large: 50000. This model supports at most 16384 "
                                          "completion tokens, whereas you provided 50000."))
    backend = OpenAICompatBackend("k", "gpt-4.1", client=fake)
    with pytest.raises(openai.BadRequestError):
        await backend.complete(request(Message("user", "x"), max_tokens=50000))
    assert backend.memo.token_param == {} and len(fake.create.calls) == 1


# ── Tarifs ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model, cost", [
    ("claude-opus-4-20250514", 90.0),       # Opus 4.0 daté : 15 $ / 75 $, pas 5 / 25
    ("claude-opus-4-1-20250805", 90.0),
    ("claude-opus-4-5-20251101", 30.0),
    ("claude-sonnet-5-5", 12.0),
    ("claude-haiku-5-5", 0.6),               # 0,10 $ / 0,50 $ : dix fois moins que la famille 4.x
    ("claude-haiku-5-5-20260401", 0.6),
    ("claude-haiku-4-5", 6.0),
    ("claude-3-5-haiku-20241022", 4.8),
    ("claude-3-7-sonnet-20250219", 18.0),
    ("gpt-5", 11.25),
    ("gpt-5-mini", 2.25),
    ("o3", 10.0),
    ("o3-pro", 100.0),                      # pas « o3 » au rabais : le plus long préfixe le prenait
    ("gpt-5-pro-2025-10-06", 135.0),
])
def test_prices_of_dated_ids_and_current_families(model: str, cost: float):
    assert price_usd(model, Usage(1_000_000, 1_000_000), provider="x") == pytest.approx(cost)


# ── Audit du 2026-10-26 : le délai de l'épisode, le plafond effectif, l'estimation ──


class Slowish:
    def __init__(self, delay: float) -> None:
        self.name, self.delay = "slowish", delay

    async def complete(self, req: LLMRequest) -> LLMResponse:
        await asyncio.sleep(self.delay)
        return LLMResponse("fini", model="m", usage=Usage(10, 2))


async def test_a_call_takes_the_deadline_of_its_episode_not_of_its_lane():
    """Le mode pro a quinze minutes ; chaque tour restait un appel borné aux 120 s de sa voie, et un tour qui
    réfléchit puis écrit du code échouait. Le délai de la requête (``deadline_s``) l'emporte ; sans lui, celui de
    la voie reste le défaut (les processus)."""
    gw = Gateway({"s": Slowish(0.2)}, {"reply": "s", "pro": "s"}, clock=ManualClock(0),
                 deadlines={"conversation": 0.05})
    long = LLMRequest(role="pro", call_id="p#0", system_stable="s", lane="conversation", deadline_s=900.0)
    assert (await gw.call(long)).text == "fini"
    with pytest.raises(TimeoutError):
        await gw.call(LLMRequest(role="reply", call_id="r#0", system_stable="s", lane="conversation"))


async def test_a_call_never_outlives_what_its_episode_has_left():
    gw = Gateway({"s": Slowish(0.3)}, {"pro": "s"}, clock=ManualClock(0))
    soon = asyncio.get_running_loop().time() + 0.05
    with pytest.raises(TimeoutError):
        await gw.call(LLMRequest(role="pro", call_id="p#1", system_stable="s", deadline_s=900.0,
                                 meta={DEADLINE_AT: soon}))
    assert [t.outcome for t in gw.traces] == ["timeout"]


class Thinker(Cut):
    """Un fournisseur qui réfléchit : jamais sous 16 384 jetons de sortie, quoi qu'on lui demande (Claude 5.x)."""

    def output_tokens(self, req: LLMRequest) -> int:
        return max(req.max_tokens, 16_384)


async def test_a_cut_is_not_asked_again_when_the_provider_would_send_the_same_cap():
    """Avec un plancher de réflexion, demander 2 000 jetons au lieu de 1 000 envoie toujours 16 384 : la même
    coupure, un appel payé pour rien. La réponse coupée est rendue telle quelle ; la passerelle dit le plafond
    effectif à qui le lui demande (la boucle d'outils, les processus)."""
    cut = Thinker(LLMResponse('{"souvenirs": [{"texte": "Alice m', stop="max_tokens"))
    gw = Gateway({"c": cut}, {"extract": "c"}, clock=ManualClock(0))
    resp = await gw.call(LLMRequest(role="extract", call_id="x#0", system_stable="s", max_tokens=1000))
    assert resp.stop == "max_tokens" and len(cut.seen) == 1
    assert gw.output_tokens(LLMRequest(role="extract", call_id="y#0", system_stable="s", max_tokens=1000)) == 16_384
    assert gw.output_tokens(LLMRequest(role="inconnu", call_id="z#0", system_stable="s", max_tokens=1000)) == 1000


def test_the_prompt_budget_and_the_fit_reserve_the_effective_output():
    """Le budget du composeur et ``fit`` réservent la sortie sur ce que le fournisseur enverra vraiment : ce qui
    tenait avec 1 000 jetons réservés ne tient plus quand il en envoie 16 384 — et les deux s'accordent. Jamais plus
    de la moitié du contexte déclaré : un fournisseur à petite fenêtre garde de quoi lire son prompt."""
    wide = LLMLimits(context_tokens=200_000, chars_per_token=1.0)
    gw = Gateway({"c": Thinker()}, {"extract": "c"}, clock=ManualClock(0), limits={"c": wide})
    assert gw.budget("extract", 1000).max_tokens == 200_000 - 16_384
    plain = Gateway({"c": Cut()}, {"extract": "c"}, clock=ManualClock(0), limits={"c": wide})
    assert plain.budget("extract", 1000).max_tokens == 200_000 - 1000
    small = LLMLimits(context_tokens=20_000, chars_per_token=1.0)
    assert Gateway({"c": Thinker()}, {"extract": "c"}, clock=ManualClock(0),
                   limits={"c": small}).budget("extract", 1000).max_tokens == 10_000
    assert small.reserve(1000, 16_384) == 10_000 and small.reserve(1000) == 1000 and small.reserve(1000, 500) == 1000
    req = LLMRequest(role="extract", call_id="x#0", system_stable="x" * 10_000, max_tokens=1000)
    assert small.fit(req).max_tokens == 1000  # tient, la seule sortie demandée réservée
    with pytest.raises(PromptBudgetError):
        small.fit(req, effective=16_384)


class Counting(Quick):
    """Un fournisseur dont l'entrée réelle vaut dix fois ce que le budget estime."""

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        return LLMResponse("ok", model="m", usage=Usage(input_tokens=10 * len(req.system_stable), output_tokens=1))


async def test_each_trace_keeps_the_estimated_input_and_a_lying_estimate_is_said_once_an_hour(caplog):
    """L'entrée estimée (caractères / ``chars_per_token``) reste à côté de l'entrée réelle dans chaque trace ; quand
    leur rapport sort de [0,7 ; 1,4], un avertissement par fournisseur et par heure — rien ne se recale seul."""
    clock = ManualClock(0)
    gw = Gateway({"q": Counting("q")}, {"reply": "q"}, clock=clock, limits={"q": LLMLimits(chars_per_token=1.0)})
    req = LLMRequest(role="reply", call_id="r#0", system_stable="x" * 100)
    with caplog.at_level(logging.WARNING, logger="mika.llm.gateway"):
        await gw.call(req)
        await gw.call(req)
        clock.advance(3_600 * 1_000_000)
        await gw.call(req)
    first = gw.traces[0]
    assert first.input_tokens == 1000 and 100 < first.estimated_input_tokens < 1000
    warned = [r.getMessage() for r in caplog.records if "chars_per_token" in r.getMessage()]
    assert len(warned) == 2 and "q : l'entrée réelle fait" in warned[0]


def test_an_ollama_backend_is_built_with_the_context_window_of_its_spec():
    spec = BackendSpec(kind="ollama", model="gemma4:12b", context_tokens=8_000)
    assert build_backend("local", spec).context_tokens == 8_000
