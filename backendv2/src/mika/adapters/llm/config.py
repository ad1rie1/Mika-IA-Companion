"""Configurer les modèles : fournisseurs déclarés, rôles routés, passerelle
rechargeable à chaud.

Une installation neuve n'a aucun modèle : chaque tour échoue proprement
(« aucun modèle associé au rôle… ») jusqu'à ce qu'on en déclare un. Les clés
ne passent jamais par ce module en clair ailleurs qu'à la construction du
client.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mika.adapters.llm.gateway import TRACES_KEPT, Gateway, LLMTrace, UnconfiguredRole
from mika.kernel.clock import Clock
from mika.kernel.forms import Knob
from mika.ports.llm import LLMBackend, LLMRequest, LLMResponse, MissingPersona
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, Role

Kind = Literal["claude", "openai", "ollama", "ollama_cloud"]


_KINDS = (("claude", "Claude (Anthropic)"), ("openai", "Compatible OpenAI"), ("ollama", "Ollama (local)"),
          ("ollama_cloud", "Ollama Cloud"))


class BackendSpec(BaseModel):
    """Un fournisseur de modèles déclaré (les bornes et libellés servent au
    formulaire de la console ; la validation reste celle du modèle)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Annotated[Kind, Knob(label="Type", choices=_KINDS, advanced=False, order=10)]
    model: Annotated[str, Knob(label="Modèle", help="L'identifiant chez le fournisseur ; « charger » liste ceux "
                                              "qu'il propose.", loader="models", advanced=False, order=20)]
    api_key: Annotated[str, Knob(label="Clé d'API", secret=True, advanced=False, order=30,
                                 only=(("kind", ("claude", "openai", "ollama_cloud")),))] = ""
    base_url: Annotated[str, Knob(label="URL de base", help="Un serveur compatible OpenAI (vide : OpenAI).",
                                  advanced=False, order=40, only=(("kind", ("openai",)),))] = ""
    host: Annotated[str, Knob(label="Hôte", help="Vide : http://localhost:11434 en local, https://ollama.com "
                                                "pour le cloud.", advanced=False, order=40,
                              only=(("kind", ("ollama", "ollama_cloud")),))] = ""
    slots: Annotated[int, Knob(label="Créneaux", help="Appels simultanés (0 : 1 en local, 4 hébergé).", lo=0, hi=32,
                               order=50)] = Field(default=0, ge=0, le=32)
    temperature: Annotated[float | None, Knob(label="Température", help="Vide : celle du fournisseur.", lo=0.0,
                                              hi=2.0, step=0.05, order=60)] = None
    cache_ttl: Annotated[Literal["5m", "1h"], Knob(label="Durée du cache", choices=(("5m", "5 minutes"),
                                                                                    ("1h", "1 heure")),
                                                   order=70, only=(("kind", ("claude",)),))] = "5m"
    think: Annotated[bool, Knob(label="Laisser réfléchir", help="Les modèles à raisonnement (lents en local).",
                                order=80, only=(("kind", ("ollama", "ollama_cloud")),))] = False
    max_reply_tokens: Annotated[int, Knob(label="Réponse max. (jetons)", help="0 : défaut du type.", lo=0,
                                          hi=65_536, order=90)] = Field(default=0, ge=0)

    @property
    def local(self) -> bool:
        return self.kind == "ollama"

    def redacted(self) -> dict[str, Any]:
        data = self.model_dump()
        data["api_key"] = "••••" if self.api_key else ""
        return data


#: les rôles, en français (voix d'abord)
ROLE_LABELS = {"reply": "répondre (voix)", "initiative": "prendre la parole (voix)", "step": "travailler (voix)",
               "murmur": "murmurer (voix)", "journal": "tenir son journal (voix)", "dream": "rêver (voix)",
               "narrative": "se raconter (voix)", "extract": "retenir (mémoire)", "validate": "vérifier",
               "profile": "comprendre les gens", "interpret": "interpréter", "triage": "trier le courrier",
               "caption": "décrire une image", "compact": "résumer le fil", "plan": "planifier"}


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backends: Annotated[dict[str, BackendSpec], Knob(label="Fournisseurs", advanced=False, order=10)] = \
        Field(default_factory=dict)
    #: rôle → nom de fournisseur déclaré
    routes: Annotated[dict[str, str], Knob(
        label="Rôles", help="Quel fournisseur sert chaque rôle. Les rôles « voix » reçoivent sa persona ; un rôle "
                             "sans fournisseur retombe sur son rôle de repli.",
        keys=tuple((str(r), ROLE_LABELS.get(str(r), str(r))) for r in Role), choices_from="backends",
        advanced=False, order=20)] = Field(default_factory=dict)
    context_tokens: Annotated[int, Knob(label="Contexte (jetons)", help="La fenêtre que le prompt peut remplir.",
                                        lo=2_000, hi=1_000_000, step=1_000, order=30)] = Field(default=24_000,
                                                                                               ge=2_000)

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
                   on_trace=on_trace, pricing={n: (s.kind, s.cache_ttl) for n, s in cfg.backends.items()})


class LiveGateway:
    """La passerelle en service, remplaçable sans redémarrer (nouvelle clé,
    nouveau modèle). Sans configuration, tout appel échoue proprement."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._inner = gateway
        self.traces: deque[LLMTrace] = deque(maxlen=TRACES_KEPT)

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
