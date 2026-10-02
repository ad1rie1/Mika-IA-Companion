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
import time
from types import SimpleNamespace
from typing import Any

import openai
import pytest
from anthropic.types import Message as AnthropicMessage
from pydantic import BaseModel

from mika.adapters.llm import gateway as gateway_mod
from mika.adapters.llm.claude import ClaudeBackend
from mika.adapters.llm.config import BackendSpec, LLMConfig, build_gateway
from mika.adapters.llm.gateway import Gateway, last_sentence, trim_speech
from mika.adapters.llm.ollama import OllamaBackend
from mika.adapters.llm.openai_compat import OpenAICompatBackend
from mika.adapters.llm.pricing import price_usd
from mika.kernel.clock import ManualClock
from mika.kernel.faculty import ToolSpec
from mika.ports.llm import RETRY_AFTER_CUT, LLMRequest, LLMResponse, Message, PersonaRender, ToolCall, Usage
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


async def test_a_mute_provider_times_out_and_the_fallback_gets_the_time_left(monkeypatch):
    monkeypatch.setattr(gateway_mod, "MIN_RETRY_S", 0.05)
    spare = Quick("spare")
    gw = Gateway({"main": Hang("main"), "spare": spare}, {"reply": "main"}, clock=ManualClock(0),
                 backend_fallbacks={"main": "spare"}, deadlines={"conversation": 0.6})
    t0 = time.monotonic()
    resp = await gw.call(LLMRequest(role="reply", call_id="r#0", system_stable="s", lane="conversation"))
    assert resp.text == "réponse de repli" and 0.3 < time.monotonic() - t0 < 0.6
    assert [(t.backend, t.outcome) for t in gw.traces] == [("main", "timeout"), ("spare", "ok")]
    alone = Gateway({"main": Hang("main")}, {"reply": "main"}, clock=ManualClock(0), deadlines={"conversation": 0.2})
    with pytest.raises(TimeoutError):
        await alone.call(LLMRequest(role="reply", call_id="r#0", system_stable="s", lane="conversation"))
    assert [t.outcome for t in alone.traces] == ["timeout"]


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
    gw = Gateway({"main": main, "cli": cli}, {"reply": "main"}, clock=ManualClock(0),
                 backend_fallbacks={"main": "cli"})
    first = LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP[:1])
    main.fail = False
    await gw.call(first)
    main.fail = True
    with pytest.raises(ConnectionError):  # en cours de boucle : pas de bascule vers la CLI (outils rejoués)
        await gw.call(LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP))
    assert cli.seen == []


async def test_a_loop_that_moved_to_the_fallback_stays_there():
    main, spare = Flaky("main"), Quick("spare")
    gw = Gateway({"main": main, "spare": spare}, {"reply": "main"}, clock=ManualClock(0),
                 backend_fallbacks={"main": "spare"})
    await gw.call(LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP[:1]))
    main.fail = False  # le principal revient : la boucle commencée sur le repli y reste
    await gw.call(LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP))
    assert len(main.seen) == 1 and len(spare.seen) == 2
    gw.release("ep#0")
    await gw.call(LLMRequest(role="reply", call_id="ep#0", system_stable="s", messages=MID_LOOP[:1]))
    assert len(main.seen) == 2  # boucle finie, oubliée : un nouvel appel repart du principal


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
