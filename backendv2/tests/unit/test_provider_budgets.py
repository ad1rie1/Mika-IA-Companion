"""Le budget de chaque fournisseur de modèle (``LLMConfig``, ``LLMLimits``, la passerelle) : il migre sans écraser une
valeur écrite, compte les outils sans séparer un appel de sa réponse, et chaque route garde le sien sans jamais
basculer ailleurs sur un échec (ADR 0073)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mika.adapters.llm.config import BackendSpec, LLMConfig, build_gateway
from mika.kernel.clock import ManualClock
from mika.kernel.prompt import PromptBudgetError
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolCall
from mika.ports.llm_budget import TOOL_CUT, TOOL_STUB, LLMLimits


def test_provider_budgets_migrate_without_overwriting_explicit_values():
    cfg = LLMConfig.model_validate({"context_tokens": 32000, "backends": {
        "a": {"kind": "openai", "model": "a"},
        "b": {"kind": "ollama", "model": "b", "context_tokens": 8000}}})
    assert cfg.backends["a"].context_tokens == 32000 and cfg.backends["b"].context_tokens == 8000
    assert "context_tokens" not in cfg.model_dump()


def test_provider_budget_counts_tools_and_preserves_tool_call_pairs():
    limits = LLMLimits(2000, 300, 1.0)
    req = LLMRequest("reply", "call", "system", max_tokens=700,
        messages=(Message("user", "question"), Message("assistant", tool_calls=(ToolCall("id", "search", {}),)),
                  Message("tool", "x" * 9000, tool_call_id="id", name="search")))
    fitted = limits.fit(req)
    assert fitted.max_tokens == 300 and limits.size(fitted) <= 1700
    assert fitted.messages[-1].tool_call_id == "id" and "abrégé" in fitted.messages[-1].content
    with pytest.raises(PromptBudgetError):
        limits.fit(replace(req, messages=(Message("user", "x" * 9000),)))


def test_an_old_tool_result_is_cut_the_same_way_at_every_call_of_the_loop():
    """ADR 0267. Coupé « au plus juste », un ancien résultat d'outil changeait à chaque appel de la boucle : le préfixe
    en cache se réécrivait depuis lui, et la réflexion rejouée après lui n'était plus celle de ce fil. Les anciens
    sont ramenés à leur début, le même d'un appel à l'autre ; les derniers — ce qu'elle lit — au plus juste."""
    limits = LLMLimits(4000, 300, 1.0)
    calls = [Message("assistant", tool_calls=(ToolCall(f"c{i}", "read", {}),)) for i in range(3)]
    results = [Message("tool", f"résultat {i} " + "x" * 2500, tool_call_id=f"c{i}", name="read") for i in range(3)]
    base = LLMRequest("reply", "call", "system", max_tokens=300, messages=(Message("user", "lis tout"),))
    second = limits.fit(base.extend(calls[0], results[0], calls[1], results[1]))
    third = limits.fit(base.extend(calls[0], results[0], calls[1], results[1], calls[2], results[2]))
    old = second.messages[2].content
    assert old.startswith("résultat 0 ") and old.endswith(TOOL_CUT) and len(old) <= TOOL_STUB + len(TOOL_CUT)
    assert third.messages[2].content == old  # le même, au tour suivant : le préfixe ne bouge pas
    assert third.messages[4].content.endswith(TOOL_CUT) and len(third.messages[4].content) <= TOOL_STUB + len(TOOL_CUT)
    # ce qu'elle lit maintenant garde le plus possible
    assert len(second.messages[4].content) > 2000 and len(third.messages[6].content) > 2000
    assert limits.size(second) <= 3700 and limits.size(third) <= 3700
    assert [m.tool_call_id for m in third.messages if m.role == "tool"] == ["c0", "c1", "c2"]


async def test_routing_uses_each_providers_budget_and_never_switches_on_failure():
    class Backend:
        def __init__(self, name):
            self.name, self.requests = name, []

        async def complete(self, req):
            self.requests.append(req)
            if self.name == "main":
                raise RuntimeError("unavailable")
            return LLMResponse("ok")

    cfg = LLMConfig(backends={
        "main": BackendSpec(kind="openai", model="a", context_tokens=8000, fallback="small"),
        "small": BackendSpec(kind="openai", model="b", context_tokens=2000, max_output_tokens=100, chars_per_token=1)},
        routes={"extract": "small", "reply": "main", "validate": "main"})
    gateway = build_gateway(cfg, ManualClock(0), make=lambda n, s: Backend(n))
    assert gateway.budget("reply", 1000).max_tokens == 7000
    assert gateway.budget("extract", 1000).max_tokens == 1900
    req = LLMRequest("validate", "test", "system", messages=(Message("user", "x" * 4000),))
    with pytest.raises(RuntimeError, match="unavailable"):
        await gateway.call(req)
    assert len(gateway.backends["main"].requests) == 1 and not gateway.backends["small"].requests
