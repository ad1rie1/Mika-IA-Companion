"""La passerelle des images : routage par rôle, capacités, replis, créneaux.

Le pendant de la passerelle des modèles de langage (``adapters/llm/gateway.py``),
avec trois règles qu'elle n'a pas :

- **Les capacités d'abord.** Un rôle désigne un fournisseur ; lui et sa chaîne de
  replis (``fallback`` de fournisseur en fournisseur, sans boucle) forment les
  candidats, et seuls ceux qui savent servir la demande restent (``unmet`` :
  partir d'images de référence, un contenu pour adultes). Aucun ne le sait :
  ``unsupported``, sans rien appeler.
- **Un refus n'est pas une panne.** La modération d'un service hébergé est une
  réponse : la demande ne repart jamais vers un autre service hébergé (ce serait
  chercher le plus permissif). Seule une demande qui le permet
  (``refusal_fallback``) repart vers un fournisseur **local** de la chaîne.
- **Une panne ou un délai** passent au candidat suivant avec le temps qui reste
  (le premier n'en consomme que ``PRIMARY_SHARE`` quand un autre l'attend).

Comme pour les modèles de langage : chaque fournisseur a ses créneaux à priorité
(``kernel/slots.py``, un réservé au premier plan dès deux ; à un seul, un serveur
local, la conversation interrompt un dessin de fond), chaque appel a un délai par
voie (attente comprise), et chaque appel laisse une trace (rôle, fournisseur,
modèle, attente, durée, jetons, coût, issue). La passerelle ne lève pas : elle
rend un ``ImageResult`` ; seule une annulation se propage.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from mika.adapters.imaging.errors import ImagingError, failure_fr
from mika.adapters.imaging.pricing import price_usd
from mika.kernel.clock import Clock
from mika.kernel.slots import PREEMPTED, PrioritySlots
from mika.ports.imaging import (
    FAILED,
    OK,
    REFUSED,
    ROLE_FALLBACKS,
    TIMEOUT,
    UNCONFIGURED,
    UNSUPPORTED,
    ImageBackend,
    ImageRequest,
    ImageResult,
    ImageUsage,
    Picture,
    unmet,
)

#: le délai d'un appel par voie (secondes, attente d'un créneau comprise) : une image prend de l'ordre de la
#: minute chez un service hébergé, jusqu'à dix sur un serveur local soigné (Q8, 40 pas, sans cache : ≈ 10 min en
#: 1536×864 sur une RTX 3060), et elle peut attendre qu'un dessin de fond se termine
DEFAULT_DEADLINES: Mapping[str, float] = {"conversation": 900.0, "background": 1800.0}
#: la part du délai que le premier candidat peut consommer quand un autre l'attend
PRIMARY_SHARE = 2 / 3
#: en dessous, un repli ne vaut pas la peine d'être tenté (secondes)
MIN_RETRY_S = 10.0
#: la longueur d'une chaîne de replis (au-delà : ignorée)
MAX_CHAIN = 4
#: les derniers appels gardés en mémoire
TRACES_KEPT = 500

log = logging.getLogger("mika.imaging.gateway")


class UnconfiguredImageRole(LookupError):
    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(f"aucun fournisseur d'images ne sert le rôle « {role} »")


@dataclass(slots=True)
class ImageTrace:
    at: int
    role: str
    backend: str
    model: str
    lane: str
    priority: int
    latency_us: int
    wait_us: int
    outcome: str
    call_id: str
    cost_usd: float = 0.0
    text_tokens: int = 0
    image_tokens: int = 0
    output_tokens: int = 0
    #: l'épisode qui a demandé l'image (``meta["episode"]``), sinon ce qui précède ``#`` dans ``call_id``
    correlation: str = ""


def correlation_of(req: ImageRequest) -> str:
    episode = req.meta.get("episode") if req.meta else None
    return str(episode) if episode else req.call_id.split("#", 1)[0]


class ImageGateway:
    def __init__(
        self,
        backends: Mapping[str, ImageBackend],
        routes: Mapping[str, str],
        *,
        clock: Clock,
        slots: Mapping[str, int] | None = None,
        preempt: frozenset[str] = frozenset(),
        backend_fallbacks: Mapping[str, str] | None = None,
        kinds: Mapping[str, str] | None = None,
        deadlines: Mapping[str, float] | None = None,
        on_trace: Callable[[ImageTrace], None] | None = None,
    ) -> None:
        self.backends = dict(backends)
        self.routes = {r: n for r, n in routes.items() if n in self.backends}
        self.clock = clock
        counts = {name: (slots or {}).get(name, 2) for name in self.backends}
        self._slots = {name: PrioritySlots(n, reserved=1 if n >= 2 else 0) for name, n in counts.items()}
        self.preempt = preempt
        self.backend_fallbacks = {k: v for k, v in (backend_fallbacks or {}).items()
                                  if k in self.backends and v in self.backends and v != k}
        #: fournisseur → son type (de quoi chiffrer un appel)
        self.kinds = dict(kinds or {})
        self.deadlines = {**DEFAULT_DEADLINES, **dict(deadlines or {})}
        self._on_trace = on_trace

    # ── Résolution ───────────────────────────────────────────────────────

    def resolve(self, role: str) -> str:
        """Le fournisseur désigné pour ce rôle (« retoucher » et « ses dessins » retombent sur « dessiner »)."""
        seen: set[str] = set()
        r: str | None = role
        while r is not None and r not in seen:
            seen.add(r)
            if r in self.routes:
                return self.routes[r]
            r = ROLE_FALLBACKS.get(r)
        raise UnconfiguredImageRole(role)

    def chain(self, name: str) -> list[str]:
        """Un fournisseur puis ses replis successifs, sans boucle, ``MAX_CHAIN`` au plus."""
        out: list[str] = []
        cur: str | None = name
        while cur is not None and cur in self.backends and cur not in out and len(out) < MAX_CHAIN:
            out.append(cur)
            cur = self.backend_fallbacks.get(cur)
        return out

    def can(self, role: str, *, refs: int = 0, adult: bool = False) -> bool:
        """Un fournisseur de la chaîne de ce rôle sait-il servir une telle demande ?"""
        try:
            primary = self.resolve(role)
        except UnconfiguredImageRole:
            return False
        probe = ImageRequest(role=role, call_id="", prompt="", refs=(Picture("image/png", b""),) * refs,
                             adult=adult)
        return any(not unmet(self.backends[n].caps, probe) for n in self.chain(primary))

    def resolution(self, roles: Iterable[str]) -> dict[str, str]:
        """Pour chaque rôle, le fournisseur qui le sert (« » : aucun)."""
        out = {}
        for role in roles:
            try:
                out[role] = self.resolve(role)
            except UnconfiguredImageRole:
                out[role] = ""
        return out

    def status(self) -> list[dict[str, Any]]:
        out = []
        for name, backend in sorted(self.backends.items()):
            slots = self._slots[name]
            own = getattr(backend, "status", None)
            try:
                extra = own() if callable(own) else {}
            except Exception:  # noqa: BLE001 — un état illisible ne casse pas la console
                extra = {}
            caps = backend.caps
            out.append({"name": name, "slots": slots.n, "busy": slots.busy, "waiting": slots.waiting,
                        "fallback": self.backend_fallbacks.get(name, ""), "local": caps.local, "edit": caps.edit,
                        "adult": caps.adult, "extra": extra if isinstance(extra, dict) else {}})
        return out

    def deadline(self, lane: str) -> float:
        return float(self.deadlines.get(lane, self.deadlines.get("background", DEFAULT_DEADLINES["background"])))

    # ── Génération ───────────────────────────────────────────────────────

    async def generate(self, req: ImageRequest) -> ImageResult:
        try:
            primary = self.resolve(req.role)
        except UnconfiguredImageRole as exc:
            return ImageResult(UNCONFIGURED, reason=str(exc))
        chain = self.chain(primary)
        capable = [n for n in chain if not unmet(self.backends[n].caps, req)]
        if not capable:
            return ImageResult(UNSUPPORTED, backend=primary,
                               reason=f"« {primary} » {unmet(self.backends[primary].caps, req)}, et aucun repli "
                                      "ne le sait")
        loop = asyncio.get_running_loop()
        start = loop.time()
        budget = self.deadline(req.lane)
        last = ImageResult(FAILED, reason="aucun fournisseur n'a répondu", backend=primary)
        refused = False
        for i, name in enumerate(capable):
            if refused and not self.backends[name].caps.local:
                continue  # après un refus, seulement un serveur à soi
            remaining = budget - (loop.time() - start)
            if i > 0 and remaining < MIN_RETRY_S:
                break
            rest = [n for n in capable[i + 1:] if not refused or self.backends[n].caps.local]
            try:
                result = await self._on(name, req, remaining * PRIMARY_SHARE if rest else remaining)
            except TimeoutError:
                last = ImageResult(TIMEOUT, reason="délai dépassé", backend=name)
                log.warning("images : %s n'a pas répondu à temps pour « %s »", name, req.role)
                continue
            except Exception as exc:  # noqa: BLE001 — une panne passe au candidat suivant, dite en mots
                last = ImageResult(FAILED, reason=failure_fr(exc), backend=name)
                log.warning("images : %s a échoué pour « %s » (%s)", name, req.role, last.reason)
                continue
            if result.outcome == REFUSED and req.refusal_fallback and not self.backends[name].caps.local \
                    and any(self.backends[n].caps.local for n in capable[i + 1:]):
                last, refused = result, True
                continue
            return result
        return last

    async def _on(self, name: str, req: ImageRequest, budget: float) -> ImageResult:
        backend = self.backends[name]
        slots = self._slots[name]
        t_wait = self.clock.now()
        t0: int | None = None
        token: int | None = None
        outcome = "ok"
        result: ImageResult | None = None
        try:
            async with asyncio.timeout(max(0.0, budget)):
                token = await slots.acquire(req.priority, preempt=name in self.preempt)
                t0 = self.clock.now()
                result = await backend.generate(req)
            if result.outcome not in (OK, REFUSED):
                raise ImagingError(f"issue inattendue du fournisseur : {result.outcome}")
            if result.outcome == OK and not result.images:
                raise ImagingError("réponse sans image")
            result = replace(result, backend=name, cost_usd=price_usd(result, kind=self.kinds.get(name, "")))
            outcome = result.outcome
            return result
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
            self._trace(req, name, result, t_wait, t0 if t0 is not None else self.clock.now(), outcome)

    def _trace(self, req: ImageRequest, backend: str, result: ImageResult | None, t_wait: int, t0: int,
               outcome: str) -> None:
        if self._on_trace is None:
            return
        now = self.clock.now()
        usage = result.usage if result is not None else ImageUsage()
        self._on_trace(ImageTrace(
            at=now, role=req.role, backend=backend, model=result.model if result is not None else "",
            lane=req.lane, priority=req.priority, latency_us=now - t0, wait_us=t0 - t_wait, outcome=outcome,
            call_id=req.call_id, cost_usd=result.cost_usd if result is not None else 0.0,
            text_tokens=usage.text_tokens, image_tokens=usage.image_tokens, output_tokens=usage.output_tokens,
            correlation=correlation_of(req)))
