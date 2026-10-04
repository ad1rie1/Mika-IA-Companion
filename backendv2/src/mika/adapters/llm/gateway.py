"""La passerelle LLM : routage par rôle, persona exigée, créneaux à priorité.

- Un rôle « voix » sans persona est refusé (``MissingPersona``) : tout ce
  qu'elle dit, pense, écrit ou rêve passe par la même persona.
- Chaque fournisseur a un nombre de créneaux ; un appel au premier plan
  (priorité 0) passe devant les appels de fond en attente. À deux créneaux ou
  plus, **un créneau est réservé au premier plan** : le fond n'en occupe jamais
  plus que ``n - 1``, une réponse n'attend donc jamais derrière lui. À un seul
  créneau (un modèle local), l'appel au premier plan interrompt l'appel de fond
  en cours — qui se règle en ``preempted`` et sera reproposé.
- Un appel fait **pendant** un épisode (un outil qui regarde par la caméra au
  milieu d'une réponse) hérite de la priorité et de la voie de cet épisode : il
  ne repasse pas derrière le fond qu'il devançait.
- **Chaque appel a un délai**, par voie (``deadlines``) : l'attente d'un créneau
  comprise. Une réponse n'attend pas dix minutes un fournisseur muet.
- Un fournisseur peut avoir un repli : s'il échoue (non connecté, quota, délai,
  panne), l'appel repart une fois sur le repli **avec le temps qui reste** — le
  principal n'en consomme que ``PRIMARY_SHARE`` quand un repli existe. Deux
  traces, l'échec puis la reprise. Une annulation n'est jamais reprise ailleurs.
- **Une boucle d'outils reste sur son fournisseur** (``call_id``) : passée sur le
  repli, elle y reste ; et elle ne bascule en cours de route que vers un
  fournisseur qui sait reprendre un fil d'outils déjà commencé — jamais vers la
  CLI de Claude Code, qui le referait (des outils exécutés deux fois).
- Une réponse coupée par son plafond de jetons, sans appel d'outil : une sortie
  structurée (extraction, profil…) est redemandée une fois avec un plafond
  doublé ; une parole (rôle voix) est coupée à sa dernière phrase complète —
  redemandée seulement si rien de complet n'en restait (un modèle qui réfléchit
  a tout dépensé avant le premier mot).
- Chaque appel laisse une trace (rôle, fournisseur, modèle, jetons, cache, coût,
  latence, attente, issue).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from mika.adapters.llm.pricing import price_usd
from mika.kernel.clock import Clock
from mika.kernel.slots import PrioritySlots
from mika.ports.llm import (
    PREEMPTED,
    RETRY_AFTER_CUT,
    LLMBackend,
    LLMRequest,
    LLMResponse,
    MissingPersona,
    Usage,
)

#: les derniers appels gardés en mémoire
TRACES_KEPT = 2000
#: le délai d'un appel par voie (secondes, attente d'un créneau comprise) ; une voie inconnue prend « background »
DEFAULT_DEADLINES: Mapping[str, float] = {"conversation": 120.0, "background": 300.0}
#: la part du délai que le fournisseur principal peut consommer quand un repli existe
PRIMARY_SHARE = 2 / 3
#: en dessous, un repli ne vaut pas la peine d'être tenté (secondes)
MIN_RETRY_S = 5.0
#: le plafond d'une sortie redemandée après une coupure
CUT_RETRY_CEILING = 8192
#: les boucles d'outils dont on retient le fournisseur (collant par ``call_id``)
STICKY_KEPT = 4096

log = logging.getLogger("mika.llm.gateway")

#: la priorité et la voie de l'épisode en cours dans cette tâche (posées par son appel principal)
_AMBIENT: ContextVar[tuple[int, str] | None] = ContextVar("mika_llm_ambient", default=None)
#: une fin de phrase : ponctuation forte, guillemets ou parenthèses fermants éventuels (« oui ! » à la
#: française, espace comprise), puis un blanc ou la fin
_SENTENCE_END = re.compile(r"[.!?…]+(?:[   ]*[»\"'”’)\]])*(?=\s|$)")


class UnconfiguredRole(LookupError):
    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(f"aucun modèle associé au rôle « {role} »")


@dataclass(slots=True)
class LLMTrace:
    at: int
    role: str
    backend: str
    model: str
    lane: str
    priority: int
    latency_us: int
    wait_us: int
    input_tokens: int
    output_tokens: int
    outcome: str
    call_id: str
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    #: l'épisode (ou le passage d'un processus) qui a fait l'appel : de quoi
    #: retrouver ses appels après un redémarrage
    correlation: str = ""


def correlation_of(req: LLMRequest) -> str:
    """L'épisode d'un appel : ``meta["episode"]`` s'il est dit, sinon ce qui
    précède ``#`` dans l'identifiant d'appel (``<passage>#<n>``)."""
    episode = req.meta.get("episode") if req.meta else None
    if episode:
        return str(episode)
    return req.call_id.split("#", 1)[0]


def last_sentence(text: str) -> str:
    """Le texte jusqu'à sa dernière phrase complète (vide : aucune)."""
    ends = list(_SENTENCE_END.finditer(text))
    return text[: ends[-1].end()].rstrip() if ends else ""


def trim_speech(text: str) -> str:
    """Une parole coupée par son plafond : jusqu'à sa dernière phrase complète ;
    sans aucune, jusqu'au dernier mot entier, suivie de points de suspension."""
    kept = last_sentence(text)
    if kept:
        return kept
    words = text.strip().rsplit(maxsplit=1)
    return f"{words[0].rstrip(' ,;:')}…" if len(words) == 2 else ""


def in_tool_loop(req: LLMRequest) -> bool:
    """La requête continue-t-elle une boucle d'outils déjà commencée ?"""
    return any(m.role == "tool" or m.tool_calls for m in req.messages)


class Gateway:
    def __init__(
        self,
        backends: Mapping[str, LLMBackend],
        routes: Mapping[str, str],
        *,
        clock: Clock,
        voice_roles: frozenset[str] = frozenset(),
        fallbacks: Mapping[str, str] | None = None,
        slots: Mapping[str, int] | None = None,
        preempt: frozenset[str] = frozenset(),
        on_trace: Callable[[LLMTrace], None] | None = None,
        pricing: Mapping[str, tuple[str, str]] | None = None,
        backend_fallbacks: Mapping[str, str] | None = None,
        deadlines: Mapping[str, float] | None = None,
    ) -> None:
        self.backends = dict(backends)
        self.routes = dict(routes)
        self.clock = clock
        self.voice_roles = voice_roles
        self.fallbacks = dict(fallbacks or {})
        counts = {name: (slots or {}).get(name, 4) for name in self.backends}
        self._slots = {name: PrioritySlots(n, reserved=1 if n >= 2 else 0) for name, n in counts.items()}
        self.preempt = preempt
        #: les derniers appels (bornés : le détail durable va dans ``CallLog``)
        self.traces: deque[LLMTrace] = deque(maxlen=TRACES_KEPT)
        self._on_trace = on_trace
        #: fournisseur → (type, durée du cache) : de quoi chiffrer un appel
        self.pricing = dict(pricing or {})
        #: fournisseur → fournisseur de repli quand il échoue
        self.backend_fallbacks = {k: v for k, v in (backend_fallbacks or {}).items()
                                  if v in self.backends and v != k}
        #: voie → délai d'un appel (secondes)
        self.deadlines = {**DEFAULT_DEADLINES, **dict(deadlines or {})}
        #: boucle d'outils (``call_id``) → le fournisseur qui la tient
        self._sticky: OrderedDict[str, str] = OrderedDict()

    def is_voice(self, role: str) -> bool:
        return role in self.voice_roles

    def defers_tools(self, role: str) -> bool:
        """Le fournisseur qui sert ce rôle sait-il différer des outils ? Un fournisseur qui n'en dit rien : oui
        (la déclaration le dit) ; un rôle sans fournisseur : oui (l'appel échouera de toute façon)."""
        try:
            backend = self.backends[self.resolve(role)]
        except UnconfiguredRole:
            return True
        return bool(getattr(backend, "defers_tools", True))

    def status(self) -> list[dict[str, Any]]:
        """L'état vivant de chaque fournisseur : créneaux (total, occupés, en attente),
        préemption, repli, et ce que le fournisseur dit de lui (le quota d'un abonnement)."""
        out = []
        for name, backend in sorted(self.backends.items()):
            slots = self._slots[name]
            own = getattr(backend, "status", None)
            try:
                extra = own() if callable(own) else {}
            except Exception:  # noqa: BLE001 — un état illisible ne casse pas la console
                extra = {}
            out.append({"name": name, "slots": slots.n, "busy": slots.busy, "waiting": slots.waiting,
                        "preempt": name in self.preempt, "fallback": self.backend_fallbacks.get(name, ""),
                        "extra": extra if isinstance(extra, dict) else {}})
        return out

    def resolution(self, roles: Iterable[str]) -> dict[str, str]:
        """Pour chaque rôle, le fournisseur qui le sert vraiment (replis compris) ; « » : aucun."""
        out = {}
        for role in roles:
            try:
                out[role] = self.resolve(role)
            except UnconfiguredRole:
                out[role] = ""
        return out

    def resolve(self, role: str) -> str:
        seen = set()
        r: str | None = role
        while r is not None and r not in seen:
            seen.add(r)
            if r in self.routes and self.routes[r] in self.backends:
                return self.routes[r]
            r = self.fallbacks.get(r)
        raise UnconfiguredRole(role)

    def deadline(self, lane: str) -> float:
        return float(self.deadlines.get(lane, self.deadlines.get("background", DEFAULT_DEADLINES["background"])))

    # ── Appel ────────────────────────────────────────────────────────────

    async def call(self, req: LLMRequest) -> LLMResponse:
        if self.is_voice(req.role) and req.persona is None:
            raise MissingPersona(f"le rôle voix « {req.role} » exige une persona")
        req = _inherit(req)
        name = self._sticky.get(req.call_id)
        if name not in self.backends:
            name = self.resolve(req.role)
        budget = self.deadline(req.lane)
        loop = asyncio.get_running_loop()
        start = loop.time()
        alt = self._fallback_for(name, req)
        try:
            resp = await self._on(name, req, budget * PRIMARY_SHARE if alt is not None else budget)
        except Exception as exc:
            remaining = budget - (loop.time() - start)
            if alt is None or remaining < MIN_RETRY_S:
                raise
            log.warning("%s a échoué pour « %s » (%s) : repli sur %s", name, req.role, exc, alt)
            self._stick(req.call_id, alt)  # la suite de cette boucle reste sur le repli
            name = alt
            resp = await self._on(alt, req, remaining)
        else:
            self._stick(req.call_id, name)
        return await self._after_cut(name, req, resp, budget - (loop.time() - start))

    def _fallback_for(self, name: str, req: LLMRequest) -> str | None:
        """Le repli permis pour cet appel : en cours de boucle d'outils, seulement un
        fournisseur qui sait reprendre un fil d'outils (sinon des outils rejoués)."""
        alt = self.backend_fallbacks.get(name)
        if alt is None:
            return None
        if in_tool_loop(req) and not getattr(self.backends[alt], "resumes_tool_loops", True):
            return None
        return alt

    def _stick(self, call_id: str, name: str) -> None:
        self._sticky[call_id] = name
        self._sticky.move_to_end(call_id)
        while len(self._sticky) > STICKY_KEPT:
            self._sticky.popitem(last=False)

    async def _after_cut(self, name: str, req: LLMRequest, resp: LLMResponse, remaining: float) -> LLMResponse:
        """Une réponse coupée par son plafond, sans appel d'outil (voir l'en-tête)."""
        if resp.stop != "max_tokens" or resp.tool_calls or resp.truncated_tool_call:
            return resp
        voice = self.is_voice(req.role)
        if voice and resp.text.strip():
            return replace(resp, text=trim_speech(resp.text))
        if req.meta.get(RETRY_AFTER_CUT) or req.max_tokens >= CUT_RETRY_CEILING or remaining < MIN_RETRY_S:
            return resp
        retry = replace(req, max_tokens=min(CUT_RETRY_CEILING, req.max_tokens * 2),
                        meta={**dict(req.meta), RETRY_AFTER_CUT: True})
        try:
            again = await self._on(name, retry, remaining)
        except Exception as exc:  # la première réponse, même coupée, vaut mieux que rien
            log.info("%s : reprise après coupure impossible (%r)", name, exc)
            return resp
        if again.stop == "max_tokens" and not again.tool_calls and voice:
            return replace(again, text=trim_speech(again.text))
        return again

    def release(self, call_id: str) -> None:
        """La boucle d'outils ``call_id`` est finie : oublier son fournisseur, et
        laisser celui-ci relâcher ce qu'il tient encore (une CLI en attente)."""
        name = self._sticky.pop(call_id, None)
        for backend in ([self.backends[name]] if name in self.backends else self.backends.values()):
            hook = getattr(backend, "release", None)
            if callable(hook):
                hook(call_id)

    async def _on(self, name: str, req: LLMRequest, budget: float) -> LLMResponse:
        backend = self.backends[name]
        slots = self._slots[name]
        t_wait = self.clock.now()
        t0: int | None = None
        token: int | None = None
        outcome = "ok"
        resp: LLMResponse | None = None
        try:
            async with asyncio.timeout(max(0.0, budget)):
                token = await slots.acquire(req.priority, preempt=name in self.preempt)
                t0 = self.clock.now()
                resp = await backend.complete(req)
            return resp
        except TimeoutError:
            outcome = "timeout"
            raise
        except asyncio.CancelledError as exc:
            outcome = "preempted" if PREEMPTED in exc.args else "cancelled"
            raise
        except Exception as exc:
            outcome = f"error:{type(exc).__name__}"
            raise
        finally:
            if token is not None:
                slots.release(token)
            self._trace(req, name, resp, t_wait, t0 if t0 is not None else self.clock.now(), outcome)

    def _trace(self, req: LLMRequest, backend: str, resp: LLMResponse | None, t_wait: int, t0: int, outcome: str) -> None:
        now = self.clock.now()
        usage = resp.usage if resp else Usage()
        cost = 0.0
        if resp is not None and backend in self.pricing:
            kind, ttl = self.pricing[backend]
            cost = price_usd(resp.model, usage, provider=kind, cache_ttl=ttl)
        tr = LLMTrace(
            at=now, role=req.role, backend=backend, model=resp.model if resp else "", lane=req.lane,
            priority=req.priority, latency_us=now - t0, wait_us=t0 - t_wait,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, outcome=outcome,
            call_id=req.call_id, cache_read=usage.cache_read, cache_write=usage.cache_write, cost_usd=cost,
            correlation=correlation_of(req),
        )
        self.traces.append(tr)
        if self._on_trace is not None:
            self._on_trace(tr)


def _inherit(req: LLMRequest) -> LLMRequest:
    """L'appel principal d'un épisode (``meta["episode"]``) pose sa priorité et sa
    voie pour la tâche ; un appel fait ensuite dans la même tâche sans être celui
    d'un épisode (un outil qui appelle un modèle) en hérite s'il était moins
    prioritaire. Le prochain épisode de la tâche repose les siennes."""
    if req.meta and req.meta.get("episode"):
        _AMBIENT.set((req.priority, req.lane))
        return req
    ambient = _AMBIENT.get()
    if ambient is not None and ambient[0] < req.priority:
        return replace(req, priority=ambient[0], lane=ambient[1])
    return req
