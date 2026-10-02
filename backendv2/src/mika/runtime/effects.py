"""La file de sortie : les effets visibles ne partent qu'après le commit.

Une ligne de la file est écrite dans la transaction même de l'événement ;
l'exécuteur la traite ensuite, au moins une fois — le gestionnaire est
idempotent par identifiant d'événement. Après un arrêt brutal, les lignes
restées en attente sont reprises.

Un gestionnaire peut rendre des brouillons (ce que l'effet a produit :
``effect.executed``) : ils sont journalisés avant que la ligne soit close,
dédoublonnés par ligne — une reprise ne les écrit pas deux fois.

**Deux files, jamais l'une derrière l'autre.** La parole (et ce qui se montre)
part par la file ``delivery`` : rapide, dans l'ordre de chaque destinataire
(deux destinataires ne s'attendent pas, et une réponse ne double jamais celle
d'avant pour la même personne). Les capacités (une commande réseau, un envoi
de mail, un ``git push``) partent par la file ``capability`` : chacune dans sa
tâche, en parallèle borné — une commande de deux minutes ne retient plus la
réponse de quelqu'un. Chaque gestionnaire a son échéance.

**Réessais datés.** Une livraison qui échoue (le gestionnaire lève, dépasse
son échéance, ou le transport répond ``False``) est réessayée plus tard, avec
un recul (5 s, 10 s, 20 s… jusqu'à dix minutes), jusqu'à ``max_attempts`` ;
puis la ligne est abandonnée (``failed``), ce que la santé montre. Une parole
qui n'a pas pu partir dans les dix minutes ne part plus (``stale``) : répondre
des heures plus tard serait pire que se taire (ADR 0009) — elle reste dans le
fil, où l'historique la rattrape.

**Rien n'est rejoué à l'aveugle.** Une capacité qui ne se rejoue pas sans
risque est marquée « en cours » avant de partir : si le processus meurt
pendant, elle n'est pas relancée au démarrage suivant — son échec est dit.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mika.kernel.events import Content, Draft, Event, Origin
from mika.kernel.faculty import CAPABILITY_LANE, EffectSpec
from mika.kernel.state import Root
from mika.ports.store import OutboxRow
from mika.runtime.boundary import Failed, acall, call

if TYPE_CHECKING:
    from mika.runtime.mind import Mind

US = 1_000_000
#: une parole qui n'a pas pu partir dans ce délai ne part plus
STALE_AFTER_S = 600.0
RETRY_BASE_S = 5.0
RETRY_MAX_S = 600.0
MAX_ATTEMPTS = 8
#: capacités qui s'exécutent en même temps
CAPABILITY_SLOTS = 2


class _Watched:
    """Le port de livraison vu d'un gestionnaire : un ``False`` du transport (le canal n'a pas pu prendre la
    livraison) est retenu — la ligne échoue et sera réessayée, au lieu d'être close comme livrée."""

    __slots__ = ("_port", "refused")

    def __init__(self, port: Any) -> None:
        self._port = port
        self.refused = 0

    async def deliver(self, d: Any) -> Any:
        ok = await self._port.deliver(d)
        if ok is False:
            self.refused += 1
        return ok

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)


class _Outcome:
    __slots__ = ("ok", "error", "retry")

    def __init__(self, ok: bool, error: str = "", *, retry: bool = True) -> None:
        self.ok = ok
        self.error = error
        #: réessayer plus tard a un sens (un transport qui hoquette) ; non : l'effet a eu lieu mais son compte
        #: rendu est refusé (un bogue) — le rejouer n'y changerait rien
        self.retry = retry


class EffectExecutor:
    def __init__(
        self,
        mind: Mind,
        ports: Mapping[str, Any] | None = None,
        *,
        max_attempts: int = MAX_ATTEMPTS,
        stale_after_s: float = STALE_AFTER_S,
        retry_base_s: float = RETRY_BASE_S,
        retry_max_s: float = RETRY_MAX_S,
        capability_slots: int = CAPABILITY_SLOTS,
    ) -> None:
        self.mind = mind
        self.ports = dict(ports or {})
        self.max_attempts = max_attempts
        self.stale_after_us = int(stale_after_s * US)
        self.retry_base_us = int(retry_base_s * US)
        self.retry_max_us = int(retry_max_s * US)
        self._wake = asyncio.Event()
        self._stopping = False
        self._cap_slots = asyncio.Semaphore(max(1, capability_slots))
        #: clé de ligne → instant de la prochaine tentative (une ligne qui a échoué attend son tour)
        self._next_try: dict[str, int] = {}
        #: les capacités en cours (une tâche par ligne)
        self._capabilities: dict[str, asyncio.Task[None]] = {}
        self._recovered = False
        self.executed = 0
        self.failed = 0
        self.stale = 0
        mind.subscribe(self._on_events)

    def _on_events(self, events: Sequence[Event[Any]], root: Root) -> None:
        if any(self.mind.registry.effects.get(e.type.name) for e in events):
            self._wake.set()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    def wake(self) -> None:
        """Reprendre la file maintenant (une ligne qu'un opérateur vient de relancer depuis la console)."""
        self._wake.set()

    async def run(self) -> None:
        clock = self.mind.clock
        while not self._stopping:
            self._wake.clear()
            got = await acall(self.drain, label="file de sortie")
            if self._stopping:
                break
            due = self.next_attempt()
            if isinstance(got, Failed) and due is None:
                due = clock.now() + self.retry_base_us  # un tour raté : on repasse, sans tourner à vide
            if due is None:
                await self._wake.wait()
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0, due - clock.now()) / US)
            except TimeoutError:
                pass

    async def settle(self) -> None:
        """Attend la fin des capacités en cours (tests, arrêt propre)."""
        while self._capabilities:
            await asyncio.gather(*list(self._capabilities.values()), return_exceptions=True)

    async def cancel(self) -> None:
        for t in list(self._capabilities.values()):
            t.cancel()
        await asyncio.gather(*list(self._capabilities.values()), return_exceptions=True)
        self._capabilities.clear()

    def next_attempt(self) -> int | None:
        """La prochaine tentative datée (une ligne qui a échoué), s'il y en a une."""
        return min(self._next_try.values()) if self._next_try else None

    def load(self, seq: int) -> Event[Any]:
        stored = self.mind.store.get_events([seq])[0]  # type: ignore[attr-defined]
        ev = self.mind.decode(stored)
        return with_content(self.mind, ev)

    # ── le tour de la file ──
    async def drain(self) -> int:
        """Traite ce qui est dû : les livraisons tout de suite (dans l'ordre de chaque destinataire), les
        capacités chacune dans sa tâche. Rend le nombre de lignes closes ou lancées."""
        if not self._recovered:
            self._recovered = True
            await self.recover()
        now = self.mind.clock.now()
        groups: dict[str, list[tuple[OutboxRow, EffectSpec, Event[Any]]]] = defaultdict(list)
        #: les destinataires dont une livraison attend son réessai : les suivantes attendent derrière elle
        waiting: set[str] = set()
        done = 0
        for row in self.mind.store.pending_outbox():
            if row.key in self._capabilities:
                continue
            spec = self._spec(row)
            if spec is None:
                await self._mark(row.key, "orphan", "aucun gestionnaire")
                continue
            due = self._next_try.get(row.key, 0) <= now
            if spec.lane == CAPABILITY_LANE and not due:
                continue
            ev = call(self.load, row.seq, label=f"relecture de {row.effect}")
            if isinstance(ev, Failed):
                await self._mark(row.key, "failed", f"illisible : {ev.error!r}"[:500])  # un poison, pas un blocage
                self.failed += 1
                continue
            if spec.lane == CAPABILITY_LANE:
                self._launch(row, spec, ev)
                done += 1
                continue
            recipient = _recipient(row, ev)
            if recipient in waiting or not due:
                waiting.add(recipient)
                continue
            if ev.type.authored and now - ev.at > self.stale_after_us:
                await self._mark(row.key, "stale", "trop tard : elle ne le dit plus")
                self._next_try.pop(row.key, None)
                self.stale += 1
                continue
            groups[recipient].append((row, spec, ev))
        if groups:
            counts = await asyncio.gather(*(self._deliver_in_order(items) for _, items in sorted(groups.items())))
            done += sum(counts)
        return done

    def _spec(self, row: OutboxRow) -> EffectSpec | None:
        owner, type_name = row.effect.split(":", 1)
        specs = [s for s in self.mind.registry.effects.get(type_name, ()) if s.owner == owner]
        return specs[0] if specs else None

    async def _deliver_in_order(self, items: list[tuple[OutboxRow, EffectSpec, Event[Any]]]) -> int:
        """Les livraisons d'un destinataire, dans l'ordre ; la première qui échoue retient les suivantes
        (elles repartiront derrière elle : jamais une réponse avant celle d'avant)."""
        done = 0
        for row, spec, ev in items:
            out = await self._run_handler(row, spec, ev)
            if not await self._close(row, out):
                break
            done += 1
        return done

    def _launch(self, row: OutboxRow, spec: EffectSpec, ev: Event[Any]) -> None:
        async def job() -> None:
            try:
                async with self._cap_slots:
                    if spec.on_interrupted is not None:
                        await self._mark(row.key, "running", None)  # « en cours » : pas rejouée à l'aveugle
                    out = await self._run_handler(row, spec, ev)
                    if out.ok or spec.on_interrupted is None:
                        await self._close(row, out)
                    else:
                        # coupée, ou son compte rendu n'a pas pu s'écrire : on ne sait pas si l'effet a eu
                        # lieu — comme après un arrêt brutal, son crochet décide (rejouer, ou dire l'échec)
                        await self._interrupt(row, spec, ev, out.error)
            finally:
                self._capabilities.pop(row.key, None)
                self._wake.set()

        self._capabilities[row.key] = asyncio.create_task(job(), name=f"capacité:{row.key}")

    async def _run_handler(self, row: OutboxRow, spec: EffectSpec, ev: Event[Any]) -> _Outcome:
        ports = dict(self.ports)
        watched = _Watched(ports["delivery"]) if ports.get("delivery") is not None else None
        if watched is not None:
            ports["delivery"] = watched
        try:
            async with asyncio.timeout(spec.deadline_s):
                out = await acall(spec.fn, ev, ports, label=f"effet {row.effect}")
        except TimeoutError:
            return _Outcome(False, f"délai dépassé ({spec.deadline_s:.0f} s)")
        if isinstance(out, Failed):
            return _Outcome(False, repr(out.error)[:500])
        if watched is not None and watched.refused:
            return _Outcome(False, "le transport n'a pas pris la livraison")
        drafts = [d for d in (out if isinstance(out, (list, tuple)) else ()) if isinstance(d, Draft)]
        if not drafts:
            return _Outcome(True)
        keyed = [replace(d, dedupe_key=d.dedupe_key or f"effet:{row.key}:{i}") for i, d in enumerate(drafts)]
        wrote = await acall(
            lambda: self.mind.append(keyed, emitter=spec.owner, correlation=f"effet:{row.seq}", origin=Origin.KERNEL),
            label=f"journal de l'effet {row.effect}")
        if isinstance(wrote, Failed):
            return _Outcome(False, f"journal impossible : {wrote.error!r}"[:500], retry=False)
        return _Outcome(True)

    async def _close(self, row: OutboxRow, out: _Outcome) -> bool:
        """Clôt la ligne (``done``), ou la remet à plus tard avec un recul, ou l'abandonne (``failed``)."""
        if out.ok:
            self._next_try.pop(row.key, None)
            await self._mark(row.key, "done", None)
            self.executed += 1
            return True
        if not out.retry:
            self.failed += 1
            self._next_try.pop(row.key, None)
            await self._mark(row.key, "failed", out.error)
            return True  # close : rien ne reste derrière elle
        return await self._retry_later(row, out.error)

    async def _retry_later(self, row: OutboxRow, error: str) -> bool:
        self.failed += 1
        attempts = row.attempts + 1
        if attempts >= self.max_attempts:
            self._next_try.pop(row.key, None)
            await self._mark(row.key, "failed", error)
            return False
        self._next_try[row.key] = self.mind.clock.now() + min(
            self.retry_max_us, self.retry_base_us * 2 ** min(attempts - 1, 20))
        await self._mark(row.key, "pending", error)
        return False

    async def _interrupt(self, row: OutboxRow, spec: EffectSpec | None, ev: Event[Any] | Failed, why: str) -> bool:
        """Un effet qui ne se rejoue pas sans risque, dont on ne sait pas s'il a eu lieu : son crochet
        ``on_interrupted`` décide — ``None`` le rejoue (plus tard), des brouillons le closent en disant
        l'échec (``interrupted``). Rend ``True`` si la ligne est close."""
        hook = spec.on_interrupted if spec is not None else None
        drafts = None if hook is None or isinstance(ev, Failed) else call(hook, ev, self.ports,
                                                                          label=f"interrompu : {row.effect}")
        if hook is None or drafts is None:
            await self._retry_later(row, why or "reprise")
            return False
        if isinstance(drafts, Failed):
            await self._mark(row.key, "failed", f"interrompue : {drafts.error!r}"[:500])
            return True
        keyed = [replace(d, dedupe_key=d.dedupe_key or f"interrompu:{row.key}:{i}")
                 for i, d in enumerate(drafts) if isinstance(d, Draft)]
        if keyed and spec is not None:
            await acall(lambda: self.mind.append(keyed, emitter=spec.owner, correlation=f"effet:{row.seq}",
                                                 origin=Origin.KERNEL), label=f"journal d'interruption {row.effect}")
        self._next_try.pop(row.key, None)
        await self._mark(row.key, "interrupted", (why or "interrompue")[:500])
        return True

    async def _mark(self, key: str, status: str, error: str | None) -> None:
        if status == "running":
            await acall(lambda: self.mind.store.run_mind(
                lambda sql: sql.execute("UPDATE outbox SET status='running' WHERE key=?", (key,))),
                label="file de sortie : en cours")
            return
        await acall(lambda: self.mind.store.mark_outbox(key, status, error), label="file de sortie")

    # ── au démarrage ──
    async def recover(self) -> int:
        """Les lignes trouvées « en cours » : le processus est mort pendant leur exécution. Le crochet
        ``on_interrupted`` de leur effet décide : rejouée (``None``) ou close avec son échec journalisé."""
        rows = call(self.mind.store.query_mind,
                    "SELECT key, seq, effect, status, attempts, last_error FROM outbox WHERE status='running' "
                    "ORDER BY seq", label="file de sortie : lignes en cours")
        if isinstance(rows, Failed):
            return 0
        closed = 0
        for raw in rows:
            row = OutboxRow(*raw)
            ev = call(self.load, row.seq, label=f"relecture de {row.effect}")
            if await self._interrupt(row, self._spec(row), ev, "interrompue par un arrêt : pas relancée"):
                closed += 1
            else:
                self._next_try.pop(row.key, None)  # une reprise après un arrêt n'a pas à attendre
        return closed


def _recipient(row: OutboxRow, ev: Event[Any]) -> str:
    """L'ordre à garder : celui d'un même gestionnaire vers une même adresse (``target``, sinon « tout le
    monde ») — deux réponses à Alice partent dans l'ordre, une panne chez Alice ne retient pas Bob."""
    target = getattr(ev.data, "target", None)
    return f"{row.effect}→{target or '*'}"


def with_content(mind: Mind, ev: Event[Any]) -> Event[Any]:
    """Restitue le texte des contenus d'un événement relu (s'il n'a pas été oublié)."""
    fields = ev.type.content_fields
    if not fields:
        return ev
    refs = [getattr(ev.data, f).ref for f in fields if isinstance(getattr(ev.data, f, None), Content)]
    texts = mind.store.content([r for r in refs if r])
    update = {}
    for f in fields:
        c = getattr(ev.data, f, None)
        if isinstance(c, Content) and c.ref is not None:
            update[f] = Content(ref=c.ref, text=texts.get(c.ref), level=c.level) if c.ref in texts else c
    return replace(ev, data=ev.data.model_copy(update=update))
