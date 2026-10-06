"""Assemblage du noyau — la même racine pour le serveur et le simulateur.

``Kernel(deps)`` construit le registre (runtime + facultés), le Mind, le
lanceur d'épisodes et ses voies, l'arbitre, l'ordonnanceur, l'exécuteur de la
file de sortie et le moteur des projections. Il ne sait jamais s'il est
simulé : l'horloge, les identifiants, le magasin et la passerelle LLM lui sont
donnés.

Le démarrage se fait en deux temps : ``boot`` (relire sa vie, journaliser la
configuration) puis ``live`` (les voies, la reprise, les processus, la file de
sortie). Entre les deux, l'hôte branche ce dont la vie a besoin — la
passerelle des modèles, le budget, les écrans — : rien ne part,
rien ne se décide avant que tout soit en place. ``start`` fait les deux.

Les reprises de réponses sont datées : une réponse supplantée revient tout de
suite, puis avec un recul si elle n'arrive pas à partir ; et jamais au-delà de
``max_reply_age_s`` — une question trop vieille est abandonnée en le disant.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel

from mika.contracts.runtime import EPISODE_ENDED, PERCEPTION_RECEIVED, PerceptionReceived
from mika.kernel.arbitration import Row
from mika.kernel.builtin import BOOT, PARAMS_CHANGED, STOPPED
from mika.kernel.clock import Clock
from mika.kernel.codec import canonical_json
from mika.kernel.episode import EpisodePolicy
from mika.kernel.events import Origin
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.ids import IdGen
from mika.kernel.prompt import Budget
from mika.kernel.registry import ArbitrationPolicy, Registry
from mika.ports.delivery import TOO_LATE
from mika.ports.llm import LLMGateway
from mika.ports.store import EventStore
from mika.runtime.arbiter import Arbiter, arbiter_spec
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.effects import EffectExecutor, with_content
from mika.runtime.lanes import Lanes
from mika.runtime.mind import BootReport, Commit, Mind
from mika.runtime.pipeline import (
    AudienceResolver,
    EpisodeReport,
    EpisodeRequest,
    EpisodeRunner,
    Parser,
    PersonaProvider,
)
from mika.runtime.projections import ProjectionWorker, ensure_t0
from mika.runtime.scheduler import Scheduler
from mika.runtime.series import Sampler, SeriesStore, sampler_spec
from mika.runtime.state import MAX_REPLY_ATTEMPTS, RETRY_NOW, RUNTIME, turn_of, turn_upto, unanswered_at_end
from mika.runtime.traces import EpisodeTraces

log = logging.getLogger("mika.kernel")

#: le recul entre deux reprises d'une réponse qui n'arrive pas à partir
RETRY_BASE_S = 0.5
RETRY_MAX_S = 30.0
#: ce qu'un tour réglé faute de place dit (le détail technique d'un ``reply_failed``)
SATURATED = "saturée : trop de messages en attente"


@dataclass(slots=True)
class KernelDeps:
    faculties: Sequence[Faculty[Any, Any]]
    store: EventStore
    clock: Clock
    ids: IdGen
    gateway: LLMGateway | None = None
    policies: Mapping[str, EpisodePolicy] = field(default_factory=dict)
    arbitration: ArbitrationPolicy | None = None
    persona: PersonaProvider | None = None
    audience_of: AudienceResolver | None = None
    parsers: Sequence[Parser] = ()
    budget: Budget | None = None
    lanes: Mapping[str, int] | None = None
    process_lanes: Mapping[str, int] | None = None
    ports: Mapping[str, Any] = field(default_factory=dict)
    code: str = ""
    seed: int | str = 0
    snapshot_every: int = 500
    reply_kind: str = "REPLY"
    arbiter_quantum_s: float = 600.0
    max_pending: int = 100
    #: Au-delà, une question restée sans réponse n'est plus reprise (au démarrage ou après une
    #: supplantation) : répondre des heures plus tard à « t'es là ? » serait pire que se taire.
    max_reply_age_s: float = 600.0
    #: Une réponse peut attendre (elle dort) : ``reply_wait(frame, seq)`` rend ``None``
    #: (rien de particulier), ``0`` (la réponse attend encore : le message reste en
    #: attente, sans épisode) ou l'instant d'où elle est due — son réveil, d'où la
    #: reprise au démarrage compte l'âge de la question.
    reply_wait: Callable[[Frame, int], int | None] | None = None
    #: l'échéance d'un passage de processus qui n'en déclare pas
    process_deadline_s: float = 900.0


class ReadOnlyStore:
    """Ce que les facultés peuvent lire du magasin (enrichisseurs, effets) :
    des requêtes SQL en lecture, jamais une écriture."""

    __slots__ = ("_store",)

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def query_mind(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self._store.query_mind(sql, params)

    def query_views(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self._store.query_views(sql, params)

    def content(self, refs: Sequence[str]) -> dict[str, str]:
        return self._store.content(list(refs))

    def get_events(self, seqs: Sequence[int]) -> list[Any]:
        """Des événements du journal tels qu'écrits (enveloppes, contenus en références)."""
        return self._store.get_events(list(seqs))


@dataclass(frozen=True, slots=True)
class Perceived:
    commit: Commit | None
    reply: asyncio.Future[EpisodeReport] | None
    overloaded: bool = False
    #: elle dort : la réponse attend son réveil (``reply`` est vide, rien ne viendra avant)
    held: bool = False

    @property
    def seq(self) -> int | None:
        return self.commit.seqs[-1] if self.commit is not None else None


class Kernel:
    def __init__(self, deps: KernelDeps) -> None:
        self.deps = deps
        registry = Registry([RUNTIME, *deps.faculties], arbitration=deps.arbitration)
        self.mind = Mind(registry, deps.store, deps.clock, deps.ids, code=deps.code,
                         snapshot_every=deps.snapshot_every)
        #: ce que chaque épisode a eu sous les yeux (``views.db``, jetable)
        self.traces = EpisodeTraces(deps.store)
        ports = {"store": ReadOnlyStore(deps.store), "frame": self._head_frame,
                 "capabilities": self.mind.registry.capabilities.get, "llm": deps.gateway, **dict(deps.ports),
                 "traces": self.traces}
        self.ports = ports
        self.runner = EpisodeRunner(
            self.mind, deps.gateway, policies=deps.policies, persona=deps.persona,
            audience_of=deps.audience_of, parsers=deps.parsers, budget=deps.budget, ports=ports,
            traces=self.traces,
        )
        self.lanes = Lanes(self.runner, capacities=deps.lanes, max_pending=deps.max_pending)
        self.arbiter = Arbiter(lambda: self.mind.registry, self._submit_selected, seed=deps.seed)
        self.mind.subscribe(self.arbiter.invalidate)
        self.mind.subscribe(self._retry_replies)
        self._retries: set[asyncio.Task[None]] = set()
        #: les messages dont la réponse attend (``reply_wait``), dans l'ordre d'arrivée
        self._held: dict[int, None] = {}
        #: reprises d'affilée par tour (adresse, salon) : le recul entre deux reprises
        self._retry_counts: dict[tuple[str, str | None], int] = {}
        #: les mesures des courbes de la console (``@f.series``), dans ``views.db``
        self.series = SeriesStore(deps.store)
        self.sampler = Sampler(self.series, list(registry.series.values()))
        self.scheduler = Scheduler(
            self.mind, extra=[arbiter_spec(self.arbiter, quantum_s=deps.arbiter_quantum_s), sampler_spec(self.sampler)],
            lanes=deps.process_lanes, llm=deps.gateway, ports=ports, deadline_s=deps.process_deadline_s,
        )
        self.effects = EffectExecutor(self.mind, ports)
        self.projections = ProjectionWorker(self.mind)
        self._tasks: list[asyncio.Task[None]] = []
        self.started = False
        self.booted = False
        #: quand la vie a repris (``live``) : une question de la nuit qui attendait son réveil lui est due à
        #: son retour, si elle n'était pas là pour la lire au matin
        self._live_at = 0
        #: ``stopped`` → ``starting`` → ``ready`` → ``stopping`` → ``stopped`` (la santé)
        self.phase = "stopped"

    @property
    def registry(self) -> Registry:
        return self.mind.registry

    def dead_loops(self) -> list[str]:
        """Les boucles du noyau mortes en marche (ordonnanceur, file de sortie,
        projections) : rien ne les relance, la santé doit le dire."""
        return [t.get_name() for t in self._tasks if t.done()] if self.started else []

    def _head_frame(self) -> Frame:
        """Une vue en lecture sur la tête (effets, enrichisseurs)."""
        return self.mind.frame()

    # ── cycle de vie ──
    async def start(self, configure: Callable[[Kernel], Awaitable[Any]] | None = None) -> BootReport:
        """Démarre d'un coup : ``boot`` puis ``live`` (le simulateur, les tests)."""
        report = await self.boot(configure)
        await self.live()
        return report

    async def boot(self, configure: Callable[[Kernel], Awaitable[Any]] | None = None) -> BootReport:
        """Premier temps : relire sa vie, ouvrir les ports, journaliser le démarrage puis ``configure`` (la
        persona, les paramètres) — **avant** que les voies, la reprise et les processus ne tournent : aucun
        processus ne voit jamais un fuseau ou un tempérament par défaut. Rien ne vit encore."""
        self.phase = "starting"
        report = await self.mind.boot(append_boot=False)
        await ensure_t0(self.mind)
        failures = self.registry.check_invariants(self.mind.root)
        if failures:
            raise RuntimeError("invariants de composition violés :\n" + "\n".join(failures))
        for port in self.deps.ports.values():
            opener = getattr(port, "open", None)
            if opener is not None:
                await opener()  # index, caches : prêts avant la première perception
        await self.traces.open()
        await self.series.open()
        await self.traces.prune(self.mind.clock.now())
        self.refresh_tools()
        # le dernier instant vécu avant ce démarrage : son absence, s'il y en a une, va de là à maintenant
        await self.mind.append([BOOT.draft(code=self.deps.code, last_at=self.mind.root.at)], emitter="kernel",
                               origin=Origin.KERNEL, correlation="boot")
        if configure is not None:
            await configure(self)
        self.booted = True
        return report

    def refresh_tools(self) -> list[str]:
        """Recalculer les outils dynamiques (ADR 0064) : chaque source les rend d'après ses ports, le registre les
        range. Au démarrage, et quand un port signale que son offre a changé. Rend les problèmes (dits au journal)."""
        problems: list[str] = []
        for src in self.registry.tool_sources.values():
            got = call(src.fn, self.ports, label=f"source d'outils {src.family}")
            if isinstance(got, Failed) or not isinstance(got, tuple) or len(got) != 2:
                problems.append(f"source d'outils {src.family} : illisible")
                tools, bundles = (), {}
            else:
                tools, bundles = got
            problems += self.registry.set_dynamic(src.owner, tools, bundles)
        for problem in problems:
            log.warning("outils : %s", problem)
        return problems

    async def live(self) -> None:
        """Second temps, une fois l'hôte branché (passerelle, budget, écrans, canaux) : les voies, la reprise
        des questions restées sans réponse, l'ordonnanceur, la file de sortie, les projections."""
        if not self.booted:
            raise RuntimeError("live() avant boot()")
        self.lanes.start()
        self.started = True
        self._live_at = self.mind.clock.now()
        await self.recover()
        self._tasks = [
            asyncio.create_task(self.scheduler.run(), name="ordonnanceur"),
            asyncio.create_task(self.effects.run(), name="file-de-sortie"),
            asyncio.create_task(self.projections.run(), name="projections"),
        ]
        self.phase = "ready"

    def _shutdown_ports(self) -> None:
        """Les ports qui tiennent des processus (la Forge) les arrêtent."""
        for port in self.deps.ports.values():
            hook = getattr(port, "shutdown", None)
            if hook is not None:
                call(hook, label="arrêt d'un port")

    async def stop(self, release: Callable[[], Awaitable[Any]] | None = None) -> None:
        """``release`` ferme ce qui sert les épisodes (fournisseurs, outils) : appelé une fois
        les épisodes annulés — fermé avant, un appel en vol se réglait en échec au lieu de
        rester à reprendre — et avant le magasin, où ses dernières écritures vont encore.
        Le dernier événement est ``kernel.stopped`` : son absence commence là."""
        self.started = False
        self.phase = "stopping"
        for t in list(self._retries):
            t.cancel()
        self.scheduler.stop()
        self.effects.stop()
        self.projections.stop()
        await self.scheduler.cancel_all()
        await self.lanes.stop()
        await self.effects.cancel()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if release is not None:
            await release()
        self._shutdown_ports()
        await self.traces.flush()  # les épisodes annulés ci-dessus ont écrit leur règlement
        if self.booted:
            await acall(lambda: self.mind.append([STOPPED.draft()], emitter="kernel", origin=Origin.KERNEL,
                                                 correlation="stop"), label="arrêt journalisé")
        await self.mind.close()
        self.started = False
        self.booted = False
        self.phase = "stopped"

    async def abort(self) -> None:
        """Arrêt brutal (simulation d'un ``kill -9`` : plus rien n'est écrit à
        partir de cet instant — les gestionnaires d'annulation qui voudraient
        encore journaliser trouvent le magasin scellé)."""
        seal = getattr(self.mind.store, "seal", None)
        if seal is not None:
            seal()
        self.started = False
        self.phase = "stopping"
        for t in [*self._tasks, *self._retries]:
            t.cancel()
        await self.scheduler.cancel_all()
        await self.lanes.stop()
        await self.effects.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        unseal = getattr(self.mind.store, "unseal", None)
        if unseal is not None:
            unseal()
        self._shutdown_ports()
        await self.mind.close()
        self.started = False
        self.booted = False
        self.phase = "stopped"

    # ── entrées ──
    async def perceive(self, data: PerceptionReceived, *, dedupe_key: str | None = None,
                       correlation: str | None = None) -> Perceived:
        """Une perception : journalisée, puis une réponse demandée. File pleine →
        refusée avant d'être journalisée (sinon la reprise au démarrage
        répondrait des heures plus tard à un message qu'on a dit refusé). Si elle se
        remplit pendant qu'on journalise, le tour est réglé tout de suite (``failed``,
        en le disant une fois par la file de sortie) : jamais une question en attente
        sans épisode pour lui répondre — elle figerait aussi la consolidation."""
        if self.deps.reply_kind in self.runner.policies and self.lanes.full(self.deps.reply_kind):
            return Perceived(None, None, overloaded=True)
        correlation = correlation or f"perception:{self.mind.ids.new(self.mind.clock.now())}"
        commit = await self.mind.append(
            [PERCEPTION_RECEIVED.draft(data, dedupe_key=dedupe_key)], emitter="runtime", origin=Origin.EXTERNAL,
            correlation=correlation,
        )
        if commit.deduped:
            return Perceived(commit, None)
        seq = commit.seqs[-1]
        await self.interpret(seq, correlation)
        if not data.addressed or self.deps.reply_kind not in self.runner.policies:
            return Perceived(commit, None)
        self._retry_counts.pop((data.handle, data.room), None)  # la personne parle : un tour neuf
        if self._wait_of(seq, self.mind.root) == 0:
            self._held[seq] = None  # elle dort : la réponse attend son réveil (``_release_held``)
            return Perceived(commit, None, held=True)
        fut = self.lanes.submit(self._reply_request(seq, data, f"perception:{seq}"))
        if fut is None:
            await self._saturated(seq)
        return Perceived(commit, fut)

    def _reply_request(self, seq: int, data: PerceptionReceived, trigger: str) -> EpisodeRequest:
        """La demande de réponse au message ``seq`` — le dernier de son tour : le modèle lit les précédents
        dans le fil, et son énoncé les règle tous."""
        return EpisodeRequest(
            kind=self.deps.reply_kind, target=data.handle, trigger=trigger, reply_to=seq,
            message=data.text.text or "", typed_chars=data.typed_chars, priority=0, channel=data.channel,
            room=data.room,
        )

    async def interpret(self, seq: int, correlation: str) -> None:
        """Ce que chaque faculté tire du message, journalisé avant la réponse :
        une réponse composée ensuite voit déjà « elle dit être Alice ». Aussi pour
        un événement venu d'ailleurs qu'un port journalise lui-même (un réveil par
        API, ADR 0068) : un ajout seul ne fait jamais tourner les interprètes."""
        stored = self.mind.store.get_events([seq])
        if not stored:
            return
        ev = with_content(self.mind, self.mind.decode(stored[0]))
        for spec in self.registry.interpreters.get(ev.type.name, ()):
            frame = self.mind.frame()
            got = call(spec.fn, frame.state(spec.owner), frame, ev, self.ports, label=f"interprète {spec.owner}")
            if isinstance(got, Failed) or not got:
                continue
            drafts = [replace(d, dedupe_key=d.dedupe_key or f"interp:{spec.owner}:{seq}:{i}")
                      for i, d in enumerate(got)]
            await acall(
                lambda drafts=drafts, owner=spec.owner: self.mind.append(
                    drafts, emitter=owner, correlation=correlation, origin=Origin.PROCESS),
                label=f"interprétation {spec.owner}",
            )

    async def forget(self, subject: str) -> dict[str, int]:
        """L'oubli d'un sujet : les traces d'épisode (toutes : un prompt mêle
        les personnes), contenus et projections (le Mind), puis tout port qui
        garde une trace dérivée (index de vecteurs…). Les traces d'abord : le
        Mind finit par compacter les deux bases, ce qui efface aussi leurs pages."""
        traces = await self.traces.forget(subject)
        out = {"contents": await self.mind.forget(subject), "traces": traces}
        for name, port in sorted(self.deps.ports.items()):
            hook = getattr(port, "forget", None)
            if hook is not None:
                out[name] = await hook(subject)
        return out

    async def set_params(self, owner: str, params: BaseModel) -> bool:
        """Journalise de nouveaux paramètres s'ils diffèrent de ceux en vigueur."""
        data = canonical_json(params)
        current = self.mind.root.slices["kernel"].params.get(owner)
        if current is not None and current.data == data:
            return False
        await self.mind.append([PARAMS_CHANGED.draft(owner=owner, data=data)], emitter="kernel",
                               origin=Origin.KERNEL, correlation="params")
        return True

    # ── reprise après arrêt ──
    async def recover(self) -> dict[str, int]:
        """Au démarrage : les épisodes restés ouverts sont interrompus ; chaque tour resté sans réponse est
        repris **une fois, sur son dernier message** — ou abandonné en le disant s'il est trop vieux ou si
        ses tentatives sont épuisées. Jamais une réponse en retard à une question dépassée."""
        rs = self.mind.root.slices[RUNTIME.name]
        interrupted = 0
        for eid, ep in rs.open.items():
            unanswered = None
            if ep.reply_to is not None:
                unanswered = unanswered_at_end(self.mind.root.slices[RUNTIME.name], ep.reply_to, "interrupted")
            await self.mind.append(
                [EPISODE_ENDED.draft(kind=ep.kind, outcome="interrupted", target=ep.target, reply_to=ep.reply_to,
                                     unanswered=unanswered)],
                emitter="runtime", correlation=eid, origin=Origin.KERNEL,
            )
            interrupted += 1
        rs = self.mind.root.slices[RUNTIME.name]
        counts = {"resumed": 0, "abandoned": 0, "held": 0}
        turns = sorted({(p.handle, p.room) for p in rs.pending.values()}, key=lambda k: (k[0], k[1] or ""))
        for handle, room in turns:
            seqs = turn_of(self.mind.root.slices[RUNTIME.name], handle, room)
            if not seqs:
                continue
            for seq in seqs:
                await self.interpret(seq, f"reprise:{seq}")  # un arrêt entre le message et son interprétation
            got = await self._answer_turn(seqs[-1], f"reprise:{seqs[-1]}")
            if got in counts:
                counts[got] += len(seqs) if got == "held" else 1
        return {"interrupted": interrupted, **counts}

    async def _answer_turn(self, latest: int, trigger: str) -> str:
        """Répondre au tour de ``latest`` (son dernier message) : ``held`` s'il attend son réveil (elle dort),
        ``abandoned`` s'il est trop vieux ou ses tentatives épuisées (en le disant), ``resumed`` si une réponse
        est en file — ``none`` sinon (rien pour répondre, file pleine)."""
        due = self._wait_of(latest, self.mind.root)
        if due == 0:
            self._held[latest] = None  # elle dort encore : la réponse attend son réveil
            return "held"
        if await self._abandon_if_due(latest, due):
            return "abandoned"
        if self.deps.reply_kind not in self.runner.policies:
            return "none"
        if self._submit_reply(latest, trigger):
            return "resumed"
        # file pleine : réglé en le disant, plutôt qu'en attente sans épisode jusqu'au prochain démarrage
        return "abandoned" if await self._saturated(latest) else "none"

    def _wait_of(self, seq: int, root: Any) -> int | None:
        """``reply_wait`` sur cette racine ; une panne ne retient rien (``None``)."""
        if self.deps.reply_wait is None:
            return None
        got = call(self.deps.reply_wait, Frame(root, self.mind.clock.now(), self.mind.registry), seq,
                   label="attente d'une réponse")
        return None if isinstance(got, Failed) else got

    def release_held(self) -> None:
        """Relâcher maintenant les réponses retenues dont l'attente est finie — celles pour qui ``reply_wait`` ne
        rend plus 0 (0 : « retenue ») : ce que fait tout ajout au journal, pour un pilote qui vient de changer ce
        que son ``reply_wait`` répond (l'avance rapide d'une vie importée, ADR 0070). Sans effet tant que le noyau
        ne vit pas (avant ``live``, après ``stop`` : la reprise au démarrage les retiendra de nouveau)."""
        if not self.started:
            return
        self._release_held(self.mind.root)

    def _release_held(self, root: Any) -> None:
        """Les réponses qui attendaient son réveil partent quand il vient : une par tour (adresse, salon) —
        à son dernier message, qui règle les précédents (ils sont lus avec lui). Si la personne l'a réveillée
        elle-même (un message plus récent du même tour, qui n'attend pas), la réponse à celui-là les lit déjà
        tous : rien de plus ne part."""
        rs = root.slices[RUNTIME.name]
        released: set[int] = set()
        for seq in list(self._held):
            if seq not in rs.pending:
                self._held.pop(seq, None)
            elif self._wait_of(seq, root) != 0:
                self._held.pop(seq, None)
                released.add(seq)
        turns = {(rs.pending[s].handle, rs.pending[s].room) for s in released}
        for handle, room in sorted(turns, key=lambda k: (k[0], k[1] or "")):
            latest = turn_of(rs, handle, room)[-1]
            if latest not in released:
                continue  # son dernier message attend encore, ou a déjà sa réponse en route : elle les lira
            task = asyncio.ensure_future(self._resume_turn(latest))
            self._retries.add(task)
            task.add_done_callback(self._retries.discard)

    async def _abandon_if_due(self, latest: int, due: int | None = None) -> bool:
        """Le tour de ``latest`` est-il à abandonner (trop vieux, tentatives épuisées) ? Si oui, il l'est, en
        le disant (``failed`` ; ses messages partent comme « sans réponse »). L'âge d'une question qui a
        attendu son réveil (``due``) compte depuis ce réveil."""
        rs = self.mind.root.slices[RUNTIME.name]
        pending = rs.pending.get(latest)
        if pending is None:
            return False
        # une question de la nuit est due au réveil — et, si elle n'était pas là pour la lire (un arrêt), à
        # son retour : ce qui l'attendait au matin lui est encore dû. Une question du jour, depuis qu'elle est posée.
        since = pending.at if due is None else max(pending.at, due, self._live_at)
        too_old = self.mind.clock.now() - since > self.deps.max_reply_age_s * 1_000_000
        if not too_old and pending.attempts < MAX_REPLY_ATTEMPTS:
            return False
        detail = TOO_LATE if too_old else "abandonnée après deux tentatives"
        await acall(lambda: self.mind.append(
            [EPISODE_ENDED.draft(kind=self.deps.reply_kind, outcome="failed", target=pending.handle,
                                 reply_to=latest, detail=detail, unanswered=turn_upto(rs, latest))],
            emitter="runtime", correlation=f"abandon:{latest}", origin=Origin.KERNEL,
        ), label="abandon d'une question")
        self._retry_counts.pop((pending.handle, pending.room), None)
        return True

    async def _saturated(self, latest: int) -> bool:
        """Le tour de ``latest`` n'a pas trouvé de place dans la file : il est réglé (``failed``, détail
        ``SATURATED`` ; ses messages partent comme « sans réponse », une fois). Rend ``True`` s'il l'est."""
        rs = self.mind.root.slices[RUNTIME.name]
        pending = rs.pending.get(latest)
        if pending is None:
            return False
        got = await acall(lambda: self.mind.append(
            [EPISODE_ENDED.draft(kind=self.deps.reply_kind, outcome="failed", target=pending.handle,
                                 reply_to=latest, detail=SATURATED, unanswered=turn_upto(rs, latest))],
            emitter="runtime", correlation=f"saturée:{latest}", origin=Origin.KERNEL,
        ), label="tour sans place dans la file")
        self._retry_counts.pop((pending.handle, pending.room), None)
        return not isinstance(got, Failed)

    def _submit_reply(self, seq: int, trigger: str) -> bool:
        stored = self.mind.store.get_events([seq])
        if not stored:
            return False
        ev = with_content(self.mind, self.mind.decode(stored[0]))
        return self.lanes.submit(self._reply_request(seq, ev.data, trigger)) is not None

    def _retry_replies(self, events: Sequence[Any], root: Any) -> None:
        """Une réponse supplantée (un nouveau message, ou ce qu'elle avait composé ne valait plus pour cette
        audience) ou préemptée est recomposée, sur le **dernier** message du tour, tant qu'il attend encore —
        jamais perdue en silence, jamais en retard sur une question dépassée. La première reprise part tout
        de suite ; si elle ne peut toujours pas partir, les suivantes s'espacent (½ s, 1 s, 2 s… 30 s). Une
        réponse qui attendait son réveil part quand il vient."""
        rs = root.slices[RUNTIME.name]
        if self._held and self.started:
            self._release_held(root)
        for e in events:
            if e.type.name != EPISODE_ENDED.name or e.data.kind != self.deps.reply_kind:
                continue
            if e.data.outcome not in RETRY_NOW or e.data.reply_to not in rs.pending:
                continue
            if self.deps.reply_kind not in self.runner.policies or not self.started:
                continue
            p = rs.pending[e.data.reply_to]
            key = (p.handle, p.room)
            n = self._retry_counts.get(key, 0)
            self._retry_counts[key] = n + 1
            delay = 0.0 if n == 0 else min(RETRY_MAX_S, RETRY_BASE_S * 2 ** min(n - 1, 10))
            task = asyncio.ensure_future(self._resubmit(e.data.reply_to, delay))
            self._retries.add(task)
            task.add_done_callback(self._retries.discard)

    async def _resubmit(self, seq: int, delay: float = 0.0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        rs = self.mind.root.slices[RUNTIME.name]
        p = rs.pending.get(seq)
        if p is None or not self.started:
            return  # réglée entre-temps (une réponse au tour, un abandon)
        await self._resume_turn(turn_of(rs, p.handle, p.room)[-1])

    async def _resume_turn(self, latest: int) -> None:
        if latest not in self.mind.root.slices[RUNTIME.name].pending or not self.started:
            return
        await self._answer_turn(latest, f"reprise:{latest}")

    async def _submit_selected(self, row: Row, frame: Frame, selected: int | None = None) -> bool:
        """Lance l'épisode choisi ; ``True`` s'il est en file (un épisode viendra
        le régler), ``False`` sinon (décision sans modèle, file pleine).
        ``selected`` : le ``seq`` de l'événement ``kernel.selected``."""
        policy = self.runner.policies.get(row.kind)
        if policy is None or policy.role is None:
            return False  # DECISION : l'événement kernel.selected est l'action
        target = None if row.target in ("none", "any") else row.target
        subject = row.args.get("subject")
        queued = self.lanes.submit(EpisodeRequest(
            kind=row.kind, target=target, selected=row, reason=",".join(p[1] for p in row.parts),
            trigger=f"selected:{selected if selected is not None else frame.seq}", priority=policy.priority,
            basis=frame.root, subject=str(subject) if subject else None, selected_seq=selected,
        ))
        return queued is not None
