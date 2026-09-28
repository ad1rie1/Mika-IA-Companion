"""Configurer les modèles : fournisseurs déclarés, rôles routés, passerelle
rechargeable à chaud.

Une installation neuve n'a aucun modèle : chaque tour échoue proprement
(« aucun modèle associé au rôle… ») jusqu'à ce qu'on en déclare un. Les clés
ne passent jamais par ce module en clair ailleurs qu'à la construction du
client.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mika.adapters.llm.gateway import Gateway, LLMTrace, UnconfiguredRole
from mika.kernel.clock import Clock
from mika.ports.llm import LLMBackend, LLMRequest, LLMResponse, MissingPersona
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES

Kind = Literal["claude", "openai", "ollama", "ollama_cloud"]


class BackendSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Kind
    model: str
    api_key: str = ""
    base_url: str = ""
    host: str = ""
    slots: int = Field(default=0, ge=0, le=32)  # 0 : défaut du type (1 en local, 4 hébergé)
    temperature: float | None = None
    cache_ttl: Literal["5m", "1h"] = "5m"
    think: bool = False
    max_reply_tokens: int = Field(default=0, ge=0)

    @property
    def local(self) -> bool:
        return self.kind == "ollama"

    def redacted(self) -> dict[str, Any]:
        data = self.model_dump()
        data["api_key"] = "••••" if self.api_key else ""
        return data


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backends: dict[str, BackendSpec] = Field(default_factory=dict)
    #: rôle → nom de fournisseur déclaré
    routes: dict[str, str] = Field(default_factory=dict)
    context_tokens: int = Field(default=24_000, ge=2_000)

    def problems(self) -> list[str]:
        out = []
        for role, name in self.routes.items():
            if name not in self.backends:
                out.append(f"le rôle « {role} » vise un fournisseur inconnu : {name}")
        return out


def build_backend(name: str, spec: BackendSpec) -> LLMBackend:
    # imports ici : chaque fournisseur tire son SDK, qui peut manquer (extra « llm »)
    if spec.kind == "claude":
        from mika.adapters.llm.claude import ClaudeBackend  # noqa: PLC0415

        return ClaudeBackend(spec.api_key, spec.model, cache_ttl=spec.cache_ttl, temperature=spec.temperature,
                             name=name)
    if spec.kind == "openai":
        from mika.adapters.llm.openai_compat import OpenAICompatBackend  # noqa: PLC0415

        return OpenAICompatBackend(spec.api_key, spec.model, base_url=spec.base_url or None,
                                   temperature=spec.temperature, name=name)
    if spec.kind == "ollama":
        from mika.adapters.llm.ollama import OllamaBackend  # noqa: PLC0415

        return OllamaBackend(spec.model, host=spec.host or "http://localhost:11434", think=spec.think,
                             max_reply_tokens=spec.max_reply_tokens or 768, temperature=spec.temperature, name=name)
    from mika.adapters.llm.ollama import OllamaCloudBackend  # noqa: PLC0415

    return OllamaCloudBackend(spec.model, spec.api_key, host=spec.host or "https://ollama.com", think=spec.think,
                              max_reply_tokens=spec.max_reply_tokens or 2048, temperature=spec.temperature,
                              name=name)


def build_gateway(cfg: LLMConfig, clock: Clock, *, on_trace: Callable[[LLMTrace], None] | None = None,
                  make: Callable[[str, BackendSpec], LLMBackend] = build_backend) -> Gateway:
    backends = {name: make(name, spec) for name, spec in sorted(cfg.backends.items())}
    slots = {name: spec.slots or (1 if spec.local else 4) for name, spec in cfg.backends.items()}
    preempt = frozenset(name for name, spec in cfg.backends.items() if slots[name] == 1)
    return Gateway(backends, dict(cfg.routes), clock=clock, voice_roles=frozenset(str(r) for r in VOICE_ROLES),
                   fallbacks={str(k): str(v) for k, v in FALLBACKS.items()}, slots=slots, preempt=preempt,
                   on_trace=on_trace)


class LiveGateway:
    """La passerelle en service, remplaçable sans redémarrer (nouvelle clé,
    nouveau modèle). Sans configuration, tout appel échoue proprement."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._inner = gateway
        self.traces: list[LLMTrace] = []

    def set(self, gateway: Gateway | None) -> None:
        self._inner = gateway

    @property
    def configured(self) -> bool:
        return self._inner is not None

    def routes(self) -> Mapping[str, str]:
        return dict(self._inner.routes) if self._inner is not None else {}

    def is_voice(self, role: str) -> bool:
        return role in {str(r) for r in VOICE_ROLES}

    async def call(self, req: LLMRequest) -> LLMResponse:
        if self.is_voice(req.role) and req.persona is None:
            raise MissingPersona(f"le rôle voix « {req.role} » exige une persona")
        if self._inner is None:
            raise UnconfiguredRole(req.role)
        return await self._inner.call(req)
