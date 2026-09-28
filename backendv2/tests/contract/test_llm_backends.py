"""Contrat des fournisseurs LLM : conversion aller-retour, points de cache,
reprises au 400, troncature, réflexion rejouée, tarifs.

De faux clients enregistrent ce qu'on leur envoie et rendent des réponses du
vrai SDK (types pydantic d'``anthropic``, ``openai``, ``ollama``) : aucun réseau.
"""

from __future__ import annotations

import copy
import logging
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import ollama
import openai
import pytest
from anthropic.types import Message as AnthropicMessage
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from mika.adapters.llm import pricing
from mika.adapters.llm.claude import ClaudeBackend
from mika.adapters.llm.gateway import Gateway
from mika.adapters.llm.ollama import OllamaBackend, OllamaCloudBackend
from mika.adapters.llm.openai_compat import OpenAICompatBackend
from mika.adapters.llm.pricing import price_usd
from mika.kernel.clock import ManualClock
from mika.kernel.faculty import ToolSpec
from mika.kernel.prompt import ChatPrompt
from mika.ports.llm import LLMRequest, Message, ToolCall, ToolDecl, Usage
from mika.runtime.tools import ToolResult, declare, run_tool_loop

# ── Faux clients ──────────────────────────────────────────────────────────


class Script:
    """Sert les réponses (ou lève les exceptions) dans l'ordre ; enregistre chaque appel."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


class FakeAnthropic:
    def __init__(self, *outcomes: Any) -> None:
        self.create = Script(*outcomes)
        self.messages = SimpleNamespace(create=self.create)


class FakeOpenAI:
    def __init__(self, *outcomes: Any) -> None:
        self.create = Script(*outcomes)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))


class FakeOllama:
    def __init__(self, *outcomes: Any) -> None:
        self.chat = Script(*outcomes)


def bad_request(sdk: Any, message: str) -> Exception:
    req = httpx2.Request("POST", "https://example.invalid/v1")
    return sdk.BadRequestError(message, response=httpx2.Response(400, request=req), body=None)


# ── Réponses canoniques (types du vrai SDK) ───────────────────────────────


def claude_reply(*content: dict[str, Any], stop: str = "end_turn", model: str = "claude-sonnet-4-6",
                 **usage: int) -> AnthropicMessage:
    return AnthropicMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": model,
        "content": list(content), "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 5, **usage},
    })


def text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def tool_use(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": args}


def thinking(signature: str, content: str = "") -> dict[str, Any]:
    return {"type": "thinking", "thinking": content, "signature": signature}


def openai_reply(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None, finish: str = "stop",
                 *, refusal: str | None = None, model: str = "gpt-4.1", prompt_tokens: int = 20,
                 completion_tokens: int = 5, cached: int | None = None) -> ChatCompletion:
    usage: dict[str, Any] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                             "total_tokens": prompt_tokens + completion_tokens}
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return ChatCompletion.model_validate({
        "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "finish_reason": finish, "message": {
            "role": "assistant", "content": content, "refusal": refusal, "tool_calls": tool_calls or None,
        }}],
        "usage": usage,
    })


def fn_call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def ollama_reply(content: str = "", tool_calls: list[tuple[str, dict[str, Any]]] | None = None,
                 done_reason: str = "stop", *, model: str = "gemma4:12b", prompt_eval_count: int = 30,
                 eval_count: int = 4) -> ollama.ChatResponse:
    return ollama.ChatResponse.model_validate({
        "model": model, "done": True, "done_reason": done_reason,
        "message": {"role": "assistant", "content": content,
                    "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in tool_calls or []] or None},
        "prompt_eval_count": prompt_eval_count, "eval_count": eval_count,
    })


# ── Requêtes ──────────────────────────────────────────────────────────────

TOOLS = (
    ToolDecl("note_count", "Compte les notes.", {"type": "object", "properties": {}}),
    ToolDecl("note_add", "Ajoute une note.",
             {"type": "object", "properties": {"what": {"type": "string"}}, "required": ["what"]}),
)

LOOP = (
    Message("user", "Note « pain »."),
    Message("assistant", "Je note.", tool_calls=(ToolCall("t1", "note_add", {"what": "pain"}),
                                                  ToolCall("t2", "note_count", {}))),
    Message("tool", "noté", tool_call_id="t1", name="note_add"),
    Message("tool", "base verrouillée", tool_call_id="t2", name="note_count", is_error=True),
)


def request(*messages: Message, tools: tuple[ToolDecl, ...] = TOOLS, system: str = "Tu es Mika.",
            volatile: str = "", max_tokens: int = 1024) -> LLMRequest:
    return LLMRequest(role="reply", call_id="c1", system_stable=system, system_volatile=volatile,
                      messages=messages, tools=tools, max_tokens=max_tokens)


def cache_marks(body: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "cache_control" in node:
                found.append(node["cache_control"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    return found


EPHEMERAL = {"type": "ephemeral"}


# ── Claude ────────────────────────────────────────────────────────────────


async def test_claude_caches_the_stable_prefix_and_the_last_history_turn():
    fake = FakeAnthropic(claude_reply(text("Très bien.")))
    backend = ClaudeBackend("k", "claude-sonnet-4-6", client=fake)
    resp = await backend.complete(request(Message("user", "salut"), Message("assistant", "coucou !"),
                                          Message("user", "ça va ?")))
    body = fake.create.calls[0]
    assert body["model"] == "claude-sonnet-4-6" and body["max_tokens"] == 1024
    assert body["system"] == [{"type": "text", "text": "Tu es Mika.", "cache_control": EPHEMERAL}]
    assert [t["name"] for t in body["tools"]] == ["note_add", "note_count"]
    assert body["tools"][0] == {"name": "note_add", "description": "Ajoute une note.",
                                "input_schema": dict(TOOLS[1].schema)}
    assert body["messages"] == [
        {"role": "user", "content": [text("salut")]},
        {"role": "assistant", "content": [{**text("coucou !"), "cache_control": EPHEMERAL}]},
        {"role": "user", "content": [text("ça va ?")]},
    ]
    assert len(cache_marks(body)) == 2
    assert "temperature" not in body
    assert (resp.text, resp.tool_calls, resp.stop) == ("Très bien.", (), "end")


async def test_claude_never_exceeds_four_breakpoints_on_a_long_tool_conversation():
    history = [Message("user" if i % 2 == 0 else "assistant", f"tour {i}") for i in range(30)]
    fake = FakeAnthropic(claude_reply(text("ok")))
    await ClaudeBackend("k", "claude-sonnet-4-6", client=fake).complete(
        request(*history, *LOOP, volatile="humeur : calme"))
    body = fake.create.calls[0]
    assert len(cache_marks(body)) == 2 <= 4
    assert "cache_control" in body["system"][0] and "cache_control" not in body["system"][1]


async def test_claude_tool_calls_become_tool_use_and_results_one_user_turn():
    fake = FakeAnthropic(claude_reply(text("C'est noté.")))
    await ClaudeBackend("k", "claude-sonnet-4-6", client=fake).complete(request(*LOOP))
    messages = fake.create.calls[0]["messages"]
    assert len(messages) == 3
    assert messages[1] == {"role": "assistant", "content": [
        text("Je note."),
        tool_use("t1", "note_add", {"what": "pain"}),
        {**tool_use("t2", "note_count", {}), "cache_control": EPHEMERAL},
    ]}
    assert messages[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "noté"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "base verrouillée", "is_error": True},
    ]}


async def test_claude_assistant_turn_without_text_sends_no_empty_block():
    fake = FakeAnthropic(claude_reply(text("ok")))
    await ClaudeBackend("k", "claude-sonnet-4-6", client=fake).complete(request(
        Message("user", "Note."),
        Message("assistant", "", tool_calls=(ToolCall("t1", "note_add", {"what": "pain"}),)),
        Message("tool", "", tool_call_id="t1", name="note_add"),
    ))
    messages = fake.create.calls[0]["messages"]
    assert [b["type"] for b in messages[1]["content"]] == ["tool_use"]
    assert messages[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1"}]


async def test_claude_reads_text_tool_calls_usage_and_model():
    fake = FakeAnthropic(claude_reply(text("Je regarde."), tool_use("toolu_1", "note_add", {"what": "pain"}),
                                      stop="tool_use", cache_read_input_tokens=900,
                                      cache_creation_input_tokens=40))
    resp = await ClaudeBackend("k", "claude-sonnet-4-6", client=fake).complete(request(Message("user", "Note.")))
    assert resp.text == "Je regarde."
    assert resp.tool_calls == (ToolCall("toolu_1", "note_add", {"what": "pain"}),)
    assert resp.stop == "tool_use" and not resp.truncated_tool_call
    assert resp.usage == Usage(input_tokens=12, output_tokens=5, cache_read=900, cache_write=40)
    assert resp.model == "claude-sonnet-4-6"


async def test_claude_tool_use_cut_by_max_tokens_is_a_truncated_call():
    fake = FakeAnthropic(claude_reply(text("Je"), tool_use("toolu_1", "note_add", {}), stop="max_tokens"),
                         claude_reply(text("un long texte"), stop="max_tokens"))
    backend = ClaudeBackend("k", "claude-sonnet-4-6", client=fake)
    cut = await backend.complete(request(Message("user", "Note.")))
    assert cut.truncated_tool_call and cut.stop == "max_tokens" and cut.tool_calls == ()
    long = await backend.complete(request(Message("user", "Raconte.")))
    assert not long.truncated_tool_call and long.stop == "max_tokens"


async def test_claude_refusal_is_a_refusal_stop():
    fake = FakeAnthropic(claude_reply(stop="refusal"))
    resp = await ClaudeBackend("k", "claude-opus-5", client=fake).complete(request(Message("user", "…")))
    assert (resp.stop, resp.text, resp.tool_calls) == ("refusal", "", ())


@pytest.mark.parametrize(("model", "sent"), [
    ("claude-opus-5", False), ("claude-opus-5-5", False), ("claude-opus-4-7", False),
    ("claude-sonnet-5", False), ("claude-fable-5-1", False), ("claude-mythos-5-1", False),
    ("claude-sonnet-4-6", True), ("claude-haiku-4-5", True), ("claude-opus-4-6", True),
])
async def test_claude_temperature_is_gated_per_model(model: str, sent: bool):
    fake = FakeAnthropic(claude_reply(text("ok")))
    await ClaudeBackend("k", model, temperature=0.7, client=fake).complete(request(Message("user", "x")))
    assert ("temperature" in fake.create.calls[0]) is sent


async def test_claude_temperature_rejection_is_retried_once_without_it_and_memoized():
    fake = FakeAnthropic(
        bad_request(anthropic, "Error code: 400 - `temperature` is deprecated for this model."),
        claude_reply(text("un")), claude_reply(text("deux")),
    )
    backend = ClaudeBackend("k", "claude-futur-9", temperature=0.4, client=fake)
    first = await backend.complete(request(Message("user", "x")))
    second = await backend.complete(request(Message("user", "y")))
    calls = fake.create.calls
    assert len(calls) == 3
    assert calls[0]["temperature"] == 0.4
    assert "temperature" not in calls[1] and "temperature" not in calls[2]
    assert (first.text, second.text) == ("un", "deux")


async def test_claude_other_bad_requests_are_not_retried():
    fake = FakeAnthropic(bad_request(anthropic, "Error code: 400 - messages: roles must alternate"))
    backend = ClaudeBackend("k", "claude-futur-9", temperature=0.4, client=fake)
    with pytest.raises(anthropic.BadRequestError):
        await backend.complete(request(Message("user", "x")))
    assert len(fake.create.calls) == 1


async def test_claude_cache_ttl_one_hour_and_unknown_ttl_refused():
    fake = FakeAnthropic(claude_reply(text("ok")))
    backend = ClaudeBackend("k", "claude-sonnet-4-6", cache_ttl="1h", client=fake)
    await backend.complete(request(Message("user", "a"), Message("assistant", "b"), Message("user", "c")))
    assert cache_marks(fake.create.calls[0]) == [{"type": "ephemeral", "ttl": "1h"}] * 2
    with pytest.raises(ValueError):
        ClaudeBackend("k", "claude-sonnet-4-6", cache_ttl="2h", client=fake)


async def test_claude_without_system_the_last_tool_carries_the_prefix_breakpoint():
    fake = FakeAnthropic(claude_reply(text("ok")))
    await ClaudeBackend("k", "claude-sonnet-4-6", client=fake).complete(request(Message("user", "x"), system=""))
    body = fake.create.calls[0]
    assert "system" not in body
    assert body["tools"][-1]["cache_control"] == EPHEMERAL
    assert len(cache_marks(body)) == 1


async def test_claude_replays_the_thinking_of_a_tool_turn_unchanged():
    fake = FakeAnthropic(
        claude_reply(thinking("sig-1"), text("Je note."), tool_use("toolu_1", "note_add", {"what": "pain"}),
                     stop="tool_use", model="claude-opus-5"),
        claude_reply(text("C'est noté."), model="claude-opus-5"),
        claude_reply(text("Autre."), model="claude-opus-5"),
    )
    backend = ClaudeBackend("k", "claude-opus-5", client=fake)
    req = request(Message("user", "Note « pain »."))
    first = await backend.complete(req)
    result = Message("tool", "noté", tool_call_id="toolu_1", name="note_add")
    await backend.complete(req.extend(Message("assistant", first.text, tool_calls=first.tool_calls), result))
    assert fake.create.calls[1]["messages"][1]["content"] == [
        thinking("sig-1"),
        text("Je note."),
        {**tool_use("toolu_1", "note_add", {"what": "pain"}), "cache_control": EPHEMERAL},
    ]
    # un tour réécrit n'est plus celui que le modèle a produit : il repart sans réflexion
    await backend.complete(req.extend(Message("assistant", "Autre chose.", tool_calls=first.tool_calls), result))
    assert [b["type"] for b in fake.create.calls[2]["messages"][1]["content"]] == ["text", "tool_use"]


async def test_claude_through_the_runtime_tool_loop():
    """La boucle unique du runtime : appel coupé rejoué au double, outil exécuté, réflexion rejouée."""
    seen: list[str] = []

    class AddArgs(BaseModel):
        what: str

    async def note_add(args: AddArgs, ctx: Any) -> ToolResult:
        seen.append(args.what)
        return ToolResult(content="noté")

    spec = ToolSpec(owner="notes", name="note_add", description="Ajoute une note.", args=AddArgs,
                    handler=note_add, bundle="atelier", episodes=frozenset({"REPLY"}))
    fake = FakeAnthropic(
        claude_reply(text("Je"), tool_use("toolu_0", "note_add", {}), stop="max_tokens"),
        claude_reply(thinking("sig"), tool_use("toolu_1", "note_add", {"what": "pain"}), stop="tool_use"),
        claude_reply(text("C'est noté.")),
    )
    gateway = Gateway({"claude": ClaudeBackend("k", "claude-opus-5", client=fake)}, {"reply": "claude"},
                      clock=ManualClock(0))
    req = LLMRequest(role="reply", call_id="c1", system_stable="Tu es Mika.",
                     messages=(Message("user", "Note « pain »."),), tools=declare([spec]), max_tokens=512)
    loop = await run_tool_loop(gateway, req, {"note_add": spec},
                               lambda spec, call_id: SimpleNamespace(call_id=call_id), max_turns=4)
    assert loop.text == "C'est noté." and seen == ["pain"]
    calls = fake.create.calls
    assert [c["max_tokens"] for c in calls] == [512, 1024, 1024]
    last = calls[2]["messages"]
    assert last[1]["content"][0] == thinking("sig")
    assert last[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "noté"}]}
    assert [t.outcome for t in gateway.traces] == ["ok", "ok", "ok"]


# ── Compatible OpenAI ─────────────────────────────────────────────────────


async def test_openai_messages_tools_and_parameters():
    fake = FakeOpenAI(openai_reply("C'est noté."))
    backend = OpenAICompatBackend("k", "gpt-4.1", temperature=0.3, client=fake)
    await backend.complete(request(*LOOP, max_tokens=700))
    body = fake.create.calls[0]
    assert body["messages"] == [
        {"role": "system", "content": "Tu es Mika."},
        {"role": "user", "content": "Note « pain »."},
        {"role": "assistant", "content": "Je note.", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "note_add", "arguments": '{"what": "pain"}'}},
            {"id": "t2", "type": "function", "function": {"name": "note_count", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "t1", "content": "noté"},
        {"role": "tool", "tool_call_id": "t2", "content": '{"error": "base verrouillée"}'},
    ]
    assert body["tools"] == [
        {"type": "function", "function": {"name": "note_add", "description": "Ajoute une note.",
                                          "parameters": dict(TOOLS[1].schema)}},
        {"type": "function", "function": {"name": "note_count", "description": "Compte les notes.",
                                          "parameters": dict(TOOLS[0].schema)}},
    ]
    assert body["max_tokens"] == 700 and "max_completion_tokens" not in body
    assert body["temperature"] == 0.3


async def test_openai_reads_tool_calls_usage_and_unreadable_arguments():
    fake = FakeOpenAI(openai_reply(None, [fn_call("call_1", "note_add", '{"what": "pain"}'),
                                          fn_call("call_2", "note_add", '{"what": "pa')],
                                   finish="tool_calls", prompt_tokens=100, completion_tokens=7, cached=60))
    resp = await OpenAICompatBackend("k", "gpt-4.1", client=fake).complete(request(Message("user", "x")))
    assert resp.tool_calls == (ToolCall("call_1", "note_add", {"what": "pain"}),
                               ToolCall("call_2", "note_add", {"_raw": '{"what": "pa'}))
    assert resp.stop == "tool_use" and resp.text == "" and resp.model == "gpt-4.1"
    assert resp.usage == Usage(input_tokens=40, output_tokens=7, cache_read=60, cache_write=0)


async def test_openai_unreadable_arguments_are_replayed_as_written():
    fake = FakeOpenAI(openai_reply("ok"))
    await OpenAICompatBackend("k", "gpt-4.1", client=fake).complete(request(
        Message("user", "x"),
        Message("assistant", "", tool_calls=(ToolCall("call_2", "note_add", {"_raw": '{"what": "pa'}),)),
        Message("tool", "arguments illisibles", tool_call_id="call_2", name="note_add", is_error=True),
    ))
    call = fake.create.calls[0]["messages"][2]["tool_calls"][0]
    assert call["function"]["arguments"] == '{"what": "pa'


async def test_openai_max_tokens_renamed_on_400_and_memoized():
    fake = FakeOpenAI(
        bad_request(openai, "Unsupported parameter: 'max_tokens' is not supported with this model. "
                            "Use 'max_completion_tokens' instead."),
        openai_reply("un"), openai_reply("deux"),
    )
    backend = OpenAICompatBackend("k", "o3-mini", client=fake)
    await backend.complete(request(Message("user", "x")))
    await backend.complete(request(Message("user", "y")))
    calls = fake.create.calls
    assert len(calls) == 3
    assert calls[0]["max_tokens"] == 1024 and "max_completion_tokens" not in calls[0]
    for call in calls[1:]:
        assert call["max_completion_tokens"] == 1024 and "max_tokens" not in call
    assert backend.memo.token_param == {"o3-mini": "max_completion_tokens"}


async def test_openai_temperature_dropped_on_400_and_memoized():
    fake = FakeOpenAI(
        bad_request(openai, "Unsupported value: 'temperature' does not support 0.3 with this model."),
        openai_reply("un"), openai_reply("deux"),
    )
    backend = OpenAICompatBackend("k", "gpt-5", temperature=0.3, client=fake)
    await backend.complete(request(Message("user", "x")))
    await backend.complete(request(Message("user", "y")))
    calls = fake.create.calls
    assert len(calls) == 3
    assert calls[0]["temperature"] == 0.3
    assert "temperature" not in calls[1] and "temperature" not in calls[2]
    assert backend.memo.no_temperature == {"gpt-5"}


async def test_openai_both_rejections_in_sequence():
    fake = FakeOpenAI(
        bad_request(openai, "Unsupported parameter: 'max_tokens'"),
        bad_request(openai, "Unsupported value: 'temperature'"),
        openai_reply("ok"),
    )
    resp = await OpenAICompatBackend("k", "o1", temperature=0.2, client=fake).complete(request(Message("user", "x")))
    last = fake.create.calls[-1]
    assert len(fake.create.calls) == 3 and resp.text == "ok"
    assert last["max_completion_tokens"] == 1024 and "max_tokens" not in last and "temperature" not in last


async def test_openai_other_bad_requests_propagate_without_retry():
    fake = FakeOpenAI(bad_request(openai, "Invalid 'messages[1].content': empty"))
    with pytest.raises(openai.BadRequestError):
        await OpenAICompatBackend("k", "gpt-4.1", temperature=0.2, client=fake).complete(request(Message("user", "x")))
    assert len(fake.create.calls) == 1


async def test_openai_length_with_a_pending_call_is_a_truncated_call():
    fake = FakeOpenAI(openai_reply(None, [fn_call("call_1", "note_add", '{"wha')], finish="length"),
                      openai_reply("un long texte", finish="length"))
    backend = OpenAICompatBackend("k", "gpt-4.1", client=fake)
    cut = await backend.complete(request(Message("user", "x")))
    assert cut.truncated_tool_call and cut.stop == "max_tokens" and cut.tool_calls == ()
    long = await backend.complete(request(Message("user", "y")))
    assert not long.truncated_tool_call and long.stop == "max_tokens" and long.text == "un long texte"


async def test_openai_missing_call_ids_are_made_unique():
    fake = FakeOpenAI(openai_reply(None, [fn_call("", "note_count", "{}"), fn_call("", "note_count", "")],
                                   finish="tool_calls"))
    resp = await OpenAICompatBackend("k", "local-model", client=fake).complete(request(Message("user", "x")))
    ids = [c.id for c in resp.tool_calls]
    assert all(ids) and len(set(ids)) == 2
    assert [c.args for c in resp.tool_calls] == [{}, {}]


async def test_openai_refusals():
    fake = FakeOpenAI(openai_reply(None, refusal="Je ne peux pas aider."),
                      openai_reply("…", finish="content_filter"))
    backend = OpenAICompatBackend("k", "gpt-4.1", client=fake)
    assert (await backend.complete(request(Message("user", "x")))).stop == "refusal"
    assert (await backend.complete(request(Message("user", "y")))).stop == "refusal"


async def test_openai_through_the_runtime_tool_loop():
    seen: list[str] = []

    class AddArgs(BaseModel):
        what: str

    async def note_add(args: AddArgs, ctx: Any) -> ToolResult:
        seen.append(args.what)
        return ToolResult(content="noté")

    spec = ToolSpec(owner="notes", name="note_add", description="Ajoute une note.", args=AddArgs,
                    handler=note_add, bundle="atelier", episodes=frozenset({"REPLY"}))
    fake = FakeOpenAI(
        openai_reply(None, [fn_call("call_1", "note_add", '{"what": "pa')], finish="tool_calls"),
        openai_reply(None, [fn_call("call_2", "note_add", '{"what": "pain"}')], finish="tool_calls"),
        openai_reply("C'est noté."),
    )
    gateway = Gateway({"openai": OpenAICompatBackend("k", "gpt-4.1", client=fake)}, {"reply": "openai"},
                      clock=ManualClock(0))
    req = LLMRequest(role="reply", call_id="c1", system_stable="Tu es Mika.",
                     messages=(Message("user", "Note « pain »."),), tools=declare([spec]))
    loop = await run_tool_loop(gateway, req, {"note_add": spec},
                               lambda spec, call_id: SimpleNamespace(call_id=call_id), max_turns=4)
    assert loop.text == "C'est noté." and seen == ["pain"]
    second = fake.create.calls[1]["messages"]
    # l'appel illisible revient au modèle tel qu'il l'a écrit, avec l'erreur de validation
    assert second[2]["tool_calls"][0]["function"]["arguments"] == '{"what": "pa'
    assert second[3]["tool_call_id"] == "call_1" and second[3]["content"].startswith('{"error": ')
    assert fake.create.calls[2]["messages"][5] == {"role": "tool", "tool_call_id": "call_2", "content": "noté"}


# ── Ollama ────────────────────────────────────────────────────────────────


async def test_ollama_thinking_off_by_default_and_reply_cap():
    fake = FakeOllama(ollama_reply("salut"), ollama_reply("salut"))
    backend = OllamaBackend("gemma4:12b", client=fake)
    await backend.complete(request(Message("user", "coucou"), max_tokens=4096))
    await backend.complete(request(Message("user", "coucou"), max_tokens=200))
    first, second = fake.chat.calls
    assert first["think"] is False and first["model"] == "gemma4:12b"
    assert first["options"] == {"num_predict": 768}
    assert second["options"] == {"num_predict": 200}


async def test_ollama_thinking_and_temperature_are_configurable():
    fake = FakeOllama(ollama_reply("salut"))
    await OllamaBackend("qwen3:8b", think=True, temperature=0.5, client=fake).complete(request(Message("user", "x")))
    body = fake.chat.calls[0]
    assert body["think"] is True and body["options"] == {"num_predict": 768, "temperature": 0.5}


async def test_ollama_messages_tool_name_and_empty_result_placeholder():
    fake = FakeOllama(ollama_reply("C'est noté."))
    await OllamaBackend("gemma4:12b", client=fake).complete(request(
        Message("user", "Note."),
        Message("assistant", "", tool_calls=(ToolCall("t1", "note_add", {"what": "pain"}),
                                             ToolCall("t2", "note_count", {}))),
        Message("tool", "", tool_call_id="t1", name="note_add"),
        Message("tool", "base verrouillée", tool_call_id="t2", name="note_count", is_error=True),
    ))
    body = fake.chat.calls[0]
    assert body["messages"] == [
        {"role": "system", "content": "Tu es Mika."},
        {"role": "user", "content": "Note."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "note_add", "arguments": {"what": "pain"}}},
            {"function": {"name": "note_count", "arguments": {}}},
        ]},
        {"role": "tool", "content": "(résultat vide)", "tool_name": "note_add"},
        {"role": "tool", "content": '{"error": "base verrouillée"}', "tool_name": "note_count"},
    ]
    assert [t["function"]["name"] for t in body["tools"]] == ["note_add", "note_count"]


async def test_ollama_reads_calls_with_unique_ids_and_usage():
    fake = FakeOllama(ollama_reply("", [("note_add", {"what": "pain"}), ("note_add", {"what": "lait"})],
                                   prompt_eval_count=30, eval_count=4))
    resp = await OllamaBackend("gemma4:12b", client=fake).complete(request(Message("user", "x")))
    assert [(c.name, c.args) for c in resp.tool_calls] == [("note_add", {"what": "pain"}),
                                                           ("note_add", {"what": "lait"})]
    ids = [c.id for c in resp.tool_calls]
    assert all(ids) and len(set(ids)) == 2
    assert resp.stop == "tool_use" and resp.usage == Usage(input_tokens=30, output_tokens=4)
    assert resp.model == "gemma4:12b"


async def test_ollama_unreadable_string_arguments_become_raw():
    odd = SimpleNamespace(model="m", done_reason="stop", prompt_eval_count=1, eval_count=1, message=SimpleNamespace(
        content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(name="note_add", arguments='{"what": "pa'))]))
    resp = await OllamaBackend("m", client=FakeOllama(odd)).complete(request(Message("user", "x")))
    assert resp.tool_calls[0].args == {"_raw": '{"what": "pa'}


async def test_ollama_length_with_a_call_is_a_truncated_call():
    fake = FakeOllama(ollama_reply("", [("note_add", {})], done_reason="length"),
                      ollama_reply("un long texte", done_reason="length"))
    backend = OllamaBackend("gemma4:12b", client=fake)
    cut = await backend.complete(request(Message("user", "x")))
    assert cut.truncated_tool_call and cut.stop == "max_tokens" and cut.tool_calls == ()
    long = await backend.complete(request(Message("user", "y")))
    assert not long.truncated_tool_call and long.stop == "max_tokens"


@pytest.mark.parametrize("error", [
    ollama.ResponseError('{"error":"\\"gemma3:4b\\" does not support thinking"}', 400),
    ollama.ResponseError("json: unknown field", 400),
])
async def test_ollama_think_rejection_is_retried_once_without_think(error: Exception):
    fake = FakeOllama(error, ollama_reply("salut"))
    resp = await OllamaBackend("gemma3:4b", client=fake).complete(request(Message("user", "x")))
    first, second = fake.chat.calls
    assert first["think"] is False and "think" not in second
    assert resp.text == "salut"


@pytest.mark.parametrize("error", [
    ollama.ResponseError("model 'qwen3-thinking:8b' not found", 404),
    ollama.ResponseError("llama runner process has terminated", 500),
    ConnectionError("Failed to connect to Ollama."),
    TimeoutError(),
])
async def test_ollama_other_errors_are_not_retried(error: Exception):
    fake = FakeOllama(error)
    with pytest.raises(type(error)):
        await OllamaBackend("qwen3-thinking:8b", client=fake).complete(request(Message("user", "x")))
    assert len(fake.chat.calls) == 1


async def test_ollama_cloud_bearer_host_and_larger_cap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    fake = FakeOllama(ollama_reply("ok"))
    cloud = OllamaCloudBackend("gpt-oss:120b", "sk-cloud", client=fake)
    assert (cloud.name, cloud.host, cloud.max_reply_tokens) == ("ollama_cloud", "https://ollama.com", 2048)
    assert cloud.headers == {"Authorization": "Bearer sk-cloud"}
    await cloud.complete(request(Message("user", "x"), max_tokens=4096))
    body = fake.chat.calls[0]
    assert body["options"] == {"num_predict": 2048} and body["think"] is False
    # le vrai client est construit avec l'hôte et l'en-tête (aucun appel réseau à la construction)
    real = OllamaCloudBackend("gpt-oss:120b", "sk-cloud")
    assert real._client._client.headers["authorization"] == "Bearer sk-cloud"
    assert str(real._client._client.base_url).startswith("https://ollama.com")
    assert OllamaCloudBackend("m", "", client=fake).headers == {}
    assert OllamaBackend("m", client=fake).headers == {}


async def test_ollama_through_the_runtime_tool_loop():
    seen: list[str] = []

    class AddArgs(BaseModel):
        what: str

    async def note_add(args: AddArgs, ctx: Any) -> ToolResult:
        seen.append(args.what)
        return ToolResult(content="noté")

    spec = ToolSpec(owner="notes", name="note_add", description="Ajoute une note.", args=AddArgs,
                    handler=note_add, bundle="atelier", episodes=frozenset({"REPLY"}))
    fake = FakeOllama(ollama_reply("", [("note_add", {"what": "pain"})]), ollama_reply("C'est noté."))
    gateway = Gateway({"ollama": OllamaBackend("gemma4:12b", client=fake)}, {"reply": "ollama"},
                      clock=ManualClock(0))
    req = LLMRequest(role="reply", call_id="c1", system_stable="Tu es Mika.",
                     messages=(Message("user", "Note « pain »."),), tools=declare([spec]))
    loop = await run_tool_loop(gateway, req, {"note_add": spec},
                               lambda spec, call_id: SimpleNamespace(call_id=call_id), max_turns=4)
    assert loop.text == "C'est noté." and seen == ["pain"]
    replay = fake.chat.calls[1]["messages"]
    assert replay[2]["tool_calls"] == [{"function": {"name": "note_add", "arguments": {"what": "pain"}}}]
    assert replay[3] == {"role": "tool", "content": "noté", "tool_name": "note_add"}


# ── Commun : le bloc volatile ─────────────────────────────────────────────


def _backend(kind: str) -> tuple[Any, Script]:
    if kind == "claude":
        fake_a = FakeAnthropic(claude_reply(text("ok")))
        return ClaudeBackend("k", "claude-sonnet-4-6", client=fake_a), fake_a.create
    if kind == "openai":
        fake_o = FakeOpenAI(openai_reply("ok"))
        return OpenAICompatBackend("k", "gpt-4.1", client=fake_o), fake_o.create
    fake_l = FakeOllama(ollama_reply("ok"))
    return OllamaBackend("gemma4:12b", client=fake_l), fake_l.chat


def _system(kind: str, body: dict[str, Any]) -> str:
    if kind == "claude":
        return "\n\n".join(block["text"] for block in body["system"])
    assert body["messages"][0]["role"] == "system"
    return body["messages"][0]["content"]


@pytest.mark.parametrize("kind", ["claude", "openai", "ollama"])
async def test_volatile_block_joins_the_system_only_when_not_already_embedded(kind: str):
    prompt = ChatPrompt("Tu es Mika.", "humeur : calme", (), "ça va ?")
    embedded = LLMRequest(role="reply", call_id="c1", system_stable=prompt.system_stable,
                          system_volatile=prompt.system_volatile,
                          messages=tuple(Message(m["role"], m["content"]) for m in prompt.chat_messages()))
    backend, script = _backend(kind)
    await backend.complete(embedded)
    assert _system(kind, script.calls[0]) == "Tu es Mika."

    backend, script = _backend(kind)
    await backend.complete(request(Message("user", "ça va ?"), volatile="humeur : calme"))
    assert _system(kind, script.calls[0]) == "Tu es Mika.\n\nhumeur : calme"


# ── Tarifs ────────────────────────────────────────────────────────────────


def test_price_input_and_output_per_family():
    assert price_usd("claude-opus-4-7", Usage(input_tokens=1_000_000)) == pytest.approx(5.0)
    assert price_usd("claude-opus-4-7", Usage(output_tokens=1_000_000)) == pytest.approx(25.0)
    assert price_usd("claude-opus-4-1", Usage(1_000_000, 1_000_000)) == pytest.approx(90.0)
    assert price_usd("claude-sonnet-4-5-20250929", Usage(input_tokens=1_000_000)) == pytest.approx(3.0)
    assert price_usd("claude-opus-5-5", Usage(1_000_000, 1_000_000)) == pytest.approx(24.0)
    assert price_usd("gpt-4.1-mini", Usage(1_000_000, 1_000_000)) == pytest.approx(2.0)


def test_price_cache_tokens():
    read = Usage(cache_read=1_000_000)
    write = Usage(cache_write=1_000_000)
    assert price_usd("claude-sonnet-4-6", read) == pytest.approx(0.3)
    assert price_usd("claude-sonnet-4-6", write) == pytest.approx(3.75)
    assert price_usd("claude-sonnet-4-6", write, cache_ttl="1h") == pytest.approx(6.0)
    assert price_usd("claude-opus-5", read) == pytest.approx(0.5)
    assert price_usd("claude-opus-5-5", read) == pytest.approx(0.20)
    assert price_usd("claude-fable-5-1", read) == pytest.approx(0.25)
    assert price_usd("claude-mythos-5-1", read) == pytest.approx(0.25)
    assert price_usd("claude-fable-5", read) == pytest.approx(1.0)
    assert price_usd("gpt-4o", read) == pytest.approx(2.5)  # pas de tarif de cache : tarif d'entrée
    with pytest.raises(ValueError):
        price_usd("claude-opus-5", read, cache_ttl="2h")


def test_price_ollama_providers_are_free():
    big = Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert price_usd("gemma4:12b", big, provider="ollama") == 0.0
    assert price_usd("gpt-oss:120b", big, provider="ollama_cloud") == 0.0
    assert price_usd("claude-opus-5", big, provider="ollama") == 0.0


def test_price_unknown_model_is_free_and_warned_once(caplog: pytest.LogCaptureFixture):
    pricing._unpriced_warned.discard("modele-inconnu-x")
    with caplog.at_level(logging.WARNING, logger="mika.llm.pricing"):
        assert price_usd("modele-inconnu-x", Usage(1_000_000, 1_000_000), provider="openai") == 0.0
        assert price_usd("modele-inconnu-x", Usage(1, 1), provider="openai") == 0.0
    assert len([r for r in caplog.records if "modele-inconnu-x" in r.getMessage()]) == 1
