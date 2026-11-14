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
from mika.ports.llm_budget import LLMLimits


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
