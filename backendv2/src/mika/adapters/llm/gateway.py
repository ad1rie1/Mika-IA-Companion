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
- **Chaque appel a un délai**, l'attente d'un créneau comprise : celui que la
  requête porte (``deadline_s`` : l'échéance de l'épisode — le mode pro a
  quinze minutes), jamais plus que ce qui reste devant l'épisode
  (``meta[DEADLINE_AT]``) ; sans lui, celui de sa voie (``deadlines`` : les
  processus). Une réponse n'attend pas dix minutes un fournisseur muet. Un
  appel dont l'épisode n'a plus de temps n'est pas tenté (issue ``expired``,
  pas « timeout » : le fournisseur n'a pas manqué).
- Une erreur est journalisée et propagée, sans changement de fournisseur.
- Une boucle d'outils reste sur son fournisseur pendant toute sa durée — et sur sa passerelle : une boucle
  ouverte (``continues``) y finit même quand les réglages en installent une autre (``LiveGateway``, ADR 0142).
- Le budget (``LLMLimits.fit``) mesure ce qui part : un tour qu'un fournisseur à session tient déjà
  (``carries`` : la CLI de Claude Code n'en reçoit que les nouveaux résultats) n'y est pas mesuré.
- Une réponse coupée par son plafond de jetons, sans appel d'outil : une sortie
  structurée (extraction, profil…) est redemandée une fois avec un plafond
  doublé ; une parole (rôle voix) est coupée à sa dernière phrase complète —
  redemandée seulement si rien de complet n'en restait (un modèle qui réfléchit
  a tout dépensé avant le premier mot). Jamais redemandée quand le fournisseur
  enverrait le même plafond **effectif** (``output_tokens`` : un modèle qui
  réfléchit a son plancher) — la même coupure, un appel payé pour rien ; la
  sortie est réservée dans le budget sur ce plafond effectif, pas sur le seul
  plafond demandé (jamais plus de la moitié du contexte déclaré :
  ``LLMLimits.reserve``).
- Chaque appel laisse une trace (rôle, fournisseur, modèle, jetons, cache, coût,
  latence, attente, issue), avec l'entrée telle que le budget l'estimait à côté
  de l'entrée réelle — la plus grande entrée d'un seul appel au modèle quand le
  fournisseur en a fait plusieurs (``LLMResponse.prompt_tokens`` : la CLI de
  Claude Code), jamais leur somme : quand leur rapport sort de
  ``ESTIMATE_RATIO``, un avertissement (un par fournisseur et par heure) dit
  que ``chars_per_token`` est à régler — rien ne se recale seul.
- Un **essai** de la console (``try_on``, « Rejouer avec… ») envoie un prompt
  gardé à un fournisseur nommé : un seul appel, derrière tout le reste, sans
  repli ni reprise, sous un rôle à part (``TRIAL_ROLE``) ; un appel d'outil
  demandé est rendu, jamais exécuté.
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
from mika.kernel.prompt import Budget
from mika.kernel.slots import PrioritySlots
from mika.ports.llm import (
    DEADLINE_AT,
    PREEMPTED,
    RETRY_AFTER_CUT,
    LLMBackend,
    LLMRequest,
    LLMResponse,
    MissingPersona,
    Usage,
)
from mika.ports.llm_budget import LLMLimits
from mika.vocab.episodes import TRIAL_ROLE

#: les derniers appels gardés en mémoire
TRACES_KEPT = 2000
#: le délai d'un appel par voie (secondes, attente d'un créneau comprise), quand la requête n'en porte pas
#: (``LLMRequest.deadline_s``) ; une voie inconnue prend « background »
DEFAULT_DEADLINES: Mapping[str, float] = {"conversation": 120.0, "background": 300.0}
#: temps minimal pour redemander une sortie tronquée (secondes)
MIN_RETRY_S = 5.0
#: le plafond d'une sortie redemandée après une coupure
CUT_RETRY_CEILING = 8192
#: les boucles d'outils dont on retient le fournisseur (collant par ``call_id``)
STICKY_KEPT = 4096
#: une boucle ouverte sans nouvelles depuis aussi longtemps (microsecondes) ne retient plus une passerelle remplacée :
#: plus long que le plus long épisode (le mode pro : quinze minutes), une boucle abandonnée sans ``release`` n'y
#: reste pas pour toujours
OPEN_LOOP_STALE_US = 3_600 * 1_000_000
#: la priorité d'un essai de la console : derrière tout le fond
TRIAL_PRIORITY = 9
#: l'entrée réelle (jetons du fournisseur, cache compris) rapportée à l'entrée estimée (caractères du budget) : hors
#: de cet intervalle, l'estimation ment et ``chars_per_token`` du fournisseur est à régler
ESTIMATE_RATIO = (0.7, 1.4)
#: au plus un avertissement d'estimation par fournisseur et par heure (microsecondes)
ESTIMATE_WARN_EVERY_US = 3_600 * 1_000_000

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
    #: l'entrée telle que le budget l'estimait (caractères de la requête / ``chars_per_token``), à côté de l'entrée
    #: réelle (``input_tokens`` + cache) : de quoi voir si l'estimation ment
    estimated_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Trial:
    """Ce qu'un essai a donné (``Gateway.try_on``) : la réponse, ou pourquoi il n'y en a pas."""

    backend: str
    response: LLMResponse | None = None
    #: la trace de l'appel (durée, attente, jetons, coût) ; ``None`` : il n'est pas parti
    trace: LLMTrace | None = None
    #: « NomDeClasse: message », ou une cause en mots ; vide quand il a répondu
    error: str = ""
    #: ses outils lui ont été retirés (un fournisseur à session, voir ``try_on``)
    tools_dropped: bool = False


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
        deadlines: Mapping[str, float] | None = None,
        limits: Mapping[str, LLMLimits] | None = None,
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
        #: voie → délai d'un appel (secondes)
        self.deadlines = {**DEFAULT_DEADLINES, **dict(deadlines or {})}
        self.limits = dict(limits or {})
        #: boucle d'outils (``call_id``) → le fournisseur qui la tient
        self._sticky: OrderedDict[str, str] = OrderedDict()
        #: les boucles ouvertes (``call_id`` → quand sa dernière réponse a demandé des outils) : leur prochain tour
        #: viendra ici
        self._open: OrderedDict[str, int] = OrderedDict()
        #: les appels en cours
        self._inflight = 0
        #: fournisseur → quand son estimation d'entrée a été dite fausse pour la dernière fois
        self._estimate_warned: dict[str, int] = {}

    def is_voice(self, role: str) -> bool:
        return role in self.voice_roles

    def budget(self, role: str, max_tokens: int) -> Budget:
        """Le budget de prompt du fournisseur de ce rôle, la sortie réservée sur le plafond qu'il enverra vraiment
        (``output_tokens`` du fournisseur : un modèle qui réfléchit a son plancher)."""
        name = self.resolve(role)
        limits = self.limits.get(name, LLMLimits())
        probe = LLMRequest(role=role, call_id="", system_stable="", max_tokens=max_tokens)
        return limits.budget(max_tokens, self._sent(name, probe))

    def output_tokens(self, req: LLMRequest) -> int:
        """Le plafond de sortie effectif de ``req`` chez le fournisseur qui la servira (celui de sa boucle, sinon celui
        de son rôle), son propre plafond appliqué ; ``req.max_tokens`` quand personne ne la sert."""
        name = self._sticky.get(req.call_id)
        if name not in self.backends:
            try:
                name = self.resolve(req.role)
            except UnconfiguredRole:
                return req.max_tokens
        return self._sent(name, req)

    def _sent(self, name: str, req: LLMRequest) -> int:
        """Ce que le fournisseur ``name`` enverra comme plafond de sortie pour ``req`` : le plafond demandé, borné par le
        sien (``LLMLimits.output``), puis relevé par lui s'il le dit (``output_tokens``, facultatif)."""
        limits = self.limits.get(name, LLMLimits())
        capped = limits.output(req.max_tokens)
        ask = getattr(self.backends.get(name), "output_tokens", None)
        if not callable(ask):
            return capped
        got = ask(replace(req, max_tokens=capped))
        return max(capped, int(got)) if isinstance(got, int) else capped

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
        préemption, et ce que le fournisseur dit de lui (le quota d'un abonnement)."""
        out = []
        for name, backend in sorted(self.backends.items()):
            slots = self._slots[name]
            own = getattr(backend, "status", None)
            try:
                extra = own() if callable(own) else {}
            except Exception:  # noqa: BLE001 — un état illisible ne casse pas la console
                extra = {}
            out.append({"name": name, "slots": slots.n, "busy": slots.busy, "waiting": slots.waiting,
                        "preempt": name in self.preempt,
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

    def serving(self, role: str) -> str:
        """Le fournisseur qui sert vraiment ce rôle (replis compris) ; « » : aucun (comme ``LiveGateway``)."""
        try:
            return self.resolve(role)
        except UnconfiguredRole:
            return ""

    def held(self, role: str, priority: int = 1) -> str:
        """Un appel de ce rôle à cette priorité serait-il refusé d'avance par son fournisseur (le quota d'un
        abonnement, ``Held``) ? La raison en mots, « » : il passerait — ou personne ne sert ce rôle (l'appel
        échouera de lui-même, ce n'est pas une retenue)."""
        try:
            backend = self.backends[self.resolve(role)]
        except UnconfiguredRole:
            return ""
        holds = getattr(backend, "holds", None)
        return str(holds(priority) or "") if callable(holds) else ""

    def holding(self) -> list[tuple[str, str]]:
        """Les fournisseurs qui refusent en ce moment leurs appels de fond : (fournisseur, raison)."""
        out = []
        for name, backend in sorted(self.backends.items()):
            holds = getattr(backend, "holds", None)
            reason = holds(1) if callable(holds) else ""
            if reason:
                out.append((name, str(reason)))
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

    def deadline_of(self, req: LLMRequest) -> float:
        """Le délai d'un appel de ``req`` (secondes) : celui qu'elle porte (l'échéance de l'épisode), sinon celui de sa
        voie — et jamais plus que ce qui reste devant l'épisode (``meta[DEADLINE_AT]``, un instant de la boucle)."""
        budget = float(req.deadline_s) if req.deadline_s is not None else self.deadline(req.lane)
        until = req.meta.get(DEADLINE_AT) if req.meta else None
        if isinstance(until, (int, float)) and not isinstance(until, bool):
            budget = min(budget, max(0.0, float(until) - asyncio.get_running_loop().time()))
        return budget

    # ── Appel ────────────────────────────────────────────────────────────

    async def call(self, req: LLMRequest) -> LLMResponse:
        if self.is_voice(req.role) and req.persona is None:
            raise MissingPersona(f"le rôle voix « {req.role} » exige une persona")
        req = _inherit(req)
        name = self._sticky.get(req.call_id)
        if name not in self.backends:
            name = self.resolve(req.role)
        budget = self.deadline_of(req)
        loop = asyncio.get_running_loop()
        start = loop.time()
        self._inflight += 1
        try:
            resp = await self._on(name, req, budget)
            self._stick(req.call_id, name)
            resp = await self._after_cut(name, req, resp, budget - (loop.time() - start))
            self._mark(req.call_id, resp)
            return resp
        finally:
            self._inflight -= 1

    def _stick(self, call_id: str, name: str) -> None:
        self._sticky[call_id] = name
        self._sticky.move_to_end(call_id)
        while len(self._sticky) > STICKY_KEPT:
            self._sticky.popitem(last=False)

    def _mark(self, call_id: str, resp: LLMResponse) -> None:
        """Une réponse qui demande des outils laisse sa boucle ouverte (son prochain tour viendra ici) ; une autre
        la ferme."""
        if not resp.tool_calls:
            self._open.pop(call_id, None)
            return
        self._open[call_id] = self.clock.now()
        self._open.move_to_end(call_id)
        while len(self._open) > STICKY_KEPT:
            self._open.popitem(last=False)

    def continues(self, req: LLMRequest) -> bool:
        """``req`` est-elle le tour suivant d'une boucle ouverte ici ?"""
        return req.call_id in self._open and in_tool_loop(req)

    def busy(self) -> bool:
        """Tient-elle encore quelque chose : un appel en cours, ou une boucle ouverte qui a eu des nouvelles depuis
        moins de ``OPEN_LOOP_STALE_US`` ? Remplacée par les réglages, elle sert jusque-là ses boucles (ADR 0142)."""
        now = self.clock.now()
        return bool(self._inflight) or any(now - at < OPEN_LOOP_STALE_US for at in self._open.values())

    async def _after_cut(self, name: str, req: LLMRequest, resp: LLMResponse, remaining: float) -> LLMResponse:
        """Une réponse coupée par son plafond, sans appel d'outil (voir l'en-tête)."""
        if resp.stop != "max_tokens" or resp.tool_calls or resp.truncated_tool_call:
            return resp
        voice = self.is_voice(req.role)
        if voice and resp.text.strip():
            return replace(resp, text=trim_speech(resp.text))
        ceiling = self.limits.get(name, LLMLimits()).max_output_tokens
        if ceiling and req.max_tokens >= ceiling:
            return resp
        if req.meta.get(RETRY_AFTER_CUT) or req.max_tokens >= CUT_RETRY_CEILING or remaining < MIN_RETRY_S:
            return resp
        retry = replace(req, max_tokens=min(CUT_RETRY_CEILING, req.max_tokens * 2),
                        meta={**dict(req.meta), RETRY_AFTER_CUT: True})
        if self._sent(name, retry) <= self._sent(name, req):
            # le fournisseur enverrait le même plafond (un modèle qui réfléchit a son plancher) : la même coupure,
            # un appel payé pour rien
            return resp
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
        self._open.pop(call_id, None)
        for backend in ([self.backends[name]] if name in self.backends else self.backends.values()):
            hook = getattr(backend, "release", None)
            if callable(hook):
                hook(call_id)

    async def try_on(self, name: str, req: LLMRequest) -> Trial:
        """Un essai de la console (« Rejouer avec… ») : ``req`` envoyée au fournisseur ``name`` par son créneau,
        derrière tout le fond (voie de fond, ``TRIAL_PRIORITY``), sous le rôle ``TRIAL_ROLE``. Un seul appel :
        ni repli, ni reprise après coupure, ni fournisseur collant ; un appel d'outil demandé est rendu tel quel,
        jamais exécuté. Un fournisseur à session (la CLI de Claude Code, qui ne rend un appel d'outil qu'en
        gardant sa session ouverte dans l'attente d'un résultat) reçoit la requête sans ses outils, et l'essai le
        dit. Ne lève pas : un échec, un délai, une préemption par une réponse sont rendus (``Trial.error``) ;
        seule l'annulation de l'essai lui-même remonte."""
        backend = self.backends.get(name)
        if backend is None:
            return Trial(name, error=f"aucun fournisseur « {name} » n'est déclaré")
        dropped = bool(req.tools) and not getattr(backend, "resumes_tool_loops", True)
        trial = replace(req, role=TRIAL_ROLE, lane="background", priority=TRIAL_PRIORITY, persona=None,
                        tools=() if dropped else req.tools, meta={})
        # une tâche à part : c'est elle que le premier plan interrompt quand il préempte le créneau, pas la
        # requête de la console qui l'attend
        task = asyncio.create_task(self._on(name, trial, self.deadline(trial.lane)))
        resp: LLMResponse | None = None
        error = ""
        try:
            resp = await task
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if me is not None and me.cancelling():
                raise  # c'est l'essai qu'on arrête (la page fermée, un arrêt du serveur)
            error = "interrompu : une réponse avait besoin de ce créneau"
        except Exception as exc:  # un essai qui échoue se montre, il ne casse pas la page
            error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            hook = getattr(backend, "release", None)
            if callable(hook):
                hook(trial.call_id)  # une session restée ouverte sur un appel d'outil
        found = next((t for t in reversed(self.traces) if t.call_id == trial.call_id), None)
        return Trial(name, resp, found, error, dropped)

    async def _on(self, name: str, req: LLMRequest, budget: float) -> LLMResponse:
        backend = self.backends[name]
        slots = self._slots[name]
        t_wait = self.clock.now()
        t0: int | None = None
        token: int | None = None
        outcome = "ok"
        resp: LLMResponse | None = None
        if budget <= 0:
            # l'épisode n'a plus de temps devant lui : rien n'est tenté (ni créneau ni appel), et la trace le dit
            # autrement qu'un fournisseur muet (« timeout »)
            log.info("appel LLM %s (%s, rôle %s) : plus de temps devant l'épisode, appel non tenté",
                     req.call_id, name, req.role)
            self._trace(req, name, None, t_wait, t_wait, "expired")
            raise TimeoutError(f"plus de temps devant l'épisode pour l'appel {req.call_id}")
        try:
            async with asyncio.timeout(budget):
                if not _carried(backend, req):
                    req = self.limits.get(name, LLMLimits()).fit(req, self._sent(name, req))
                token = await slots.acquire(req.priority, preempt=name in self.preempt)
                t0 = self.clock.now()
                resp = await backend.complete(req)
            return resp
        except TimeoutError:
            outcome = "timeout"
            log.error("appel LLM %s (%s, rôle %s) : délai dépassé", req.call_id, name, req.role)
            raise
        except asyncio.CancelledError as exc:
            outcome = "preempted" if PREEMPTED in exc.args else "cancelled"
            raise
        except Exception as exc:
            outcome = f"error:{type(exc).__name__}"
            log.error("appel LLM %s (%s, rôle %s) : %s", req.call_id, name, req.role, type(exc).__name__)
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
        limits = self.limits.get(backend, LLMLimits())
        estimated = round(limits.size(req) / limits.chars_per_token)
        tr = LLMTrace(
            at=now, role=req.role, backend=backend, model=resp.model if resp else "", lane=req.lane,
            priority=req.priority, latency_us=now - t0, wait_us=t0 - t_wait,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, outcome=outcome,
            call_id=req.call_id, cache_read=usage.cache_read, cache_write=usage.cache_write, cost_usd=cost,
            correlation=correlation_of(req), estimated_input_tokens=estimated,
        )
        self.traces.append(tr)
        if resp is not None:
            # un fournisseur qui a fait plusieurs appels pour cette réponse dit la plus grande entrée d'un seul
            real = resp.prompt_tokens or (usage.input_tokens + usage.cache_read + usage.cache_write)
            self._check_estimate(backend, tr, limits.chars_per_token, now, real)
        if self._on_trace is not None:
            self._on_trace(tr)

    def _check_estimate(self, backend: str, tr: LLMTrace, chars_per_token: float, now: int, real: int) -> None:
        """L'entrée réelle (``real`` : les jetons d'un seul appel au modèle, cache compris) contre l'estimation du
        budget : hors de ``ESTIMATE_RATIO``, un avertissement par fournisseur et par heure — pas de recalage
        automatique."""
        if real <= 0 or tr.estimated_input_tokens <= 0:
            return
        ratio = real / tr.estimated_input_tokens
        if ESTIMATE_RATIO[0] <= ratio <= ESTIMATE_RATIO[1]:
            return
        last = self._estimate_warned.get(backend)
        if last is not None and now - last < ESTIMATE_WARN_EVERY_US:
            return
        self._estimate_warned[backend] = now
        log.warning("%s : l'entrée réelle fait %.2f× l'estimation (%d jetons pour %d estimés à %.1f car./jeton, "
                    "soit %.1f réels) — « chars_per_token » du fournisseur est à régler",
                    backend, ratio, real, tr.estimated_input_tokens, chars_per_token, chars_per_token / ratio)


def _carried(backend: LLMBackend, req: LLMRequest) -> bool:
    """Le fournisseur tient-il déjà le fil de ``req`` (``carries``, facultatif : une CLI dont la session vivante attend
    ces résultats) ? Seuls les nouveaux résultats partent alors : mesurer tout le fil refusait un tour qui n'envoyait
    presque rien (projet n° 257, 2026-10-27 : une app écrite quatre fois dans la boucle, puis le tour suivant refusé,
    « requête trop longue », le travail fait et l'épisode en échec)."""
    carries = getattr(backend, "carries", None)
    return bool(carries(req)) if callable(carries) else False


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
