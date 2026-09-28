"""Le Mind : le seul point d'écriture de l'état.

Algorithme d'ajout (``append``), atomique vis-à-vis des autres ajouts :

1. dédoublonnage (type, clé) — un brouillon déjà vu rend le commit d'origine ;
2. validation — l'émetteur possède le type, charge utile valide, provenance de
   voix pour un événement « écrit par elle », contenus avec texte ;
3. garde — empreintes des faits lus identiques entre la base et la tête,
   prédicat, baux, épisode vivant ; sinon ``Superseded`` et rien n'est ajouté ;
4. estampille — ``seq``, ``at = max(horloge, dernier at)``, identifiant ;
5. application des réducteurs (double tampon : chaque réducteur voit sa tranche
   et les faits des autres *avant* l'événement) ;
6. une transaction — événements, contenus séparés, dédoublonnage, file de
   sortie, projections T0, instantané si dû ;
7. publication de la nouvelle racine ;
8. notifications — revérification des gardes des épisodes en vol, réveils.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from mika.kernel.builtin import BOOT
from mika.kernel.clock import Clock
from mika.kernel.codec import canonical_json, digest
from mika.kernel.events import Content, Draft, Event, EventType, Origin, Payload, VoiceProvenance
from mika.kernel.facts import FactView, ReduceContext
from mika.kernel.faculty import Tier
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.kernel.guards import Guard, Superseded, check
from mika.kernel.ids import IdGen
from mika.kernel.registry import Registry
from mika.kernel.state import FrozenDict, Root
from mika.ports.store import AppendBatch, ContentRow, EventStore, OutboxRow, SnapshotRow, StoredEvent
from mika.runtime.boundary import Failed, call

log = logging.getLogger("mika.mind")


@dataclass(frozen=True, slots=True)
class Commit:
    seqs: tuple[int, ...]
    events: tuple[Event[Any], ...]
    root: Root
    deduped: bool = False


@dataclass(slots=True)
class InFlight:
    correlation: str
    guard: Guard
    basis: Root
    holder: str
    on_supersede: Callable[[Superseded], None]


@dataclass(frozen=True, slots=True)
class BootReport:
    snapshot_seq: int
    replayed: int
    stale: tuple[str, ...]
    head: int


@dataclass(slots=True)
class Trace:
    at: int
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)


class Mind:
    def __init__(
        self,
        registry: Registry,
        store: EventStore,
        clock: Clock,
        ids: IdGen,
        *,
        code: str = "",
        snapshot_every: int = 500,
        snapshot_interval_us: int = 30 * 60 * 1_000_000,
        trace_size: int = 500,
    ) -> None:
        self.registry = registry
        self.store = store
        self.clock = clock
        self.ids = ids
        self.code = code
        self._root = registry.initial_root()
        self._lock = asyncio.Lock()
        self._inflight: dict[str, InFlight] = {}
        self._listeners: list[Callable[[Sequence[Event[Any]], Root], None]] = []
        self._snapshot_every = snapshot_every
        self._snapshot_interval = snapshot_interval_us
        self._last_snapshot_seq = 0
        self._last_snapshot_at = 0
        self.traces: list[Trace] = []
        self._trace_size = trace_size
        self.anomalies: list[str] = []

    # ── lecture ────────────────────────────────────────────────────────────
    @property
    def root(self) -> Root:
        return self._root

    @property
    def head(self) -> int:
        return self._root.seq

    def frame(
        self, *, now: int | None = None, audience: Audience | None = None, episode: EpisodeRef | None = None
    ) -> Frame:
        return Frame(self._root, self.clock.now() if now is None else now, self.registry, audience, episode)

    def view(self, root: Root | None = None, now: int | None = None) -> FactView:
        return FactView(root or self._root, self.clock.now() if now is None else now, self.registry)

    def subscribe(self, fn: Callable[[Sequence[Event[Any]], Root], None]) -> None:
        self._listeners.append(fn)

    def trace(self, kind: str, **detail: Any) -> None:
        self.traces.append(Trace(self.clock.now(), kind, detail))
        if len(self.traces) > self._trace_size:
            del self.traces[: len(self.traces) - self._trace_size]

    def content_text(self, content: Content | None) -> str | None:
        if content is None:
            return None
        if content.text is not None:
            return content.text
        if content.ref is None:
            return None
        return self.store.content([content.ref]).get(content.ref)

    # ── démarrage ──────────────────────────────────────────────────────────
    async def boot(self, *, append_boot: bool = True) -> BootReport:
        await self.store.open()
        snap = self.store.latest_snapshot()
        root = self.registry.initial_root()
        stale: set[str] = set()
        if snap is not None:
            root, stale = self._load_snapshot(snap)
        if stale:
            root = self._rebuild_from_genesis(root, stale, upto=root.seq)
        replayed = 0
        skip = {n for n, f in self.registry.faculties.items() if f.volatile}
        for stored in self.store.read(after=root.seq):
            root = self._apply(root, self.decode(stored), skip=skip, live=False)
            replayed += 1
        self._root = root
        self._last_snapshot_seq = snap.seq if snap else 0
        self._last_snapshot_at = snap.at if snap else 0
        if append_boot:
            await self.append([BOOT.draft(code=self.code)], emitter="kernel", origin=Origin.KERNEL, correlation="boot")
        return BootReport(snap.seq if snap else 0, replayed, tuple(sorted(stale)), self.head)

    async def close(self) -> None:
        await self.store.close()

    def decode(self, stored: StoredEvent) -> Event[Any]:
        t, data = self.registry.events.decode(stored.type, stored.v, stored.data)
        return Event(
            seq=stored.seq, id=stored.id, type=t, at=stored.at, data=data, causation=stored.causation,
            correlation=stored.correlation, basis=stored.basis, origin=Origin(stored.origin),
        )

    def snapshot_data(self, root: Root) -> str:
        slices = {}
        for owner in self.registry.persisted_owners():
            adapter = self.registry.slice_adapter(owner)
            slices[owner] = {
                "v": self.registry.faculties[owner].state_version,
                "data": adapter.dump_python(root.slices[owner], mode="json"),
            }
        return canonical_json(
            {"seq": root.seq, "at": root.at, "slices": slices,
             "changed": root.changed.to_dict(), "tainted": root.tainted.to_dict()}
        )

    def _load_snapshot(self, snap: SnapshotRow) -> tuple[Root, set[str]]:
        data = json.loads(snap.data)
        initial = self.registry.initial_root()
        slices = dict(initial.slices.items())
        stale: set[str] = set()
        for owner in self.registry.persisted_owners():
            entry = data["slices"].get(owner)
            f = self.registry.faculties[owner]
            if entry is None or entry["v"] != f.state_version:
                stale.add(owner)
                continue
            slices[owner] = self.registry.slice_adapter(owner).validate_python(entry["data"])
        root = Root(
            seq=int(data["seq"]), at=int(data["at"]), slices=FrozenDict(slices),
            changed=FrozenDict({k: int(v) for k, v in data.get("changed", {}).items()}),
            tainted=FrozenDict({k: int(v) for k, v in data.get("tainted", {}).items()}),
        )
        return root, stale

    def _rebuild_from_genesis(self, root: Root, owners: set[str], upto: int) -> Root:
        """Rejoue la clôture de lecture de ``owners`` depuis la genèse, puis
        remplace leurs tranches dans ``root``."""
        closure = self.registry.read_closure(owners)
        shadow = self.registry.initial_root()
        types = {
            name for name, specs in self.registry.reducers_by_type.items()
            if any(s.owner in closure for s in specs)
        }
        for stored in self.store.read(after=0, types=types, upto=upto):
            shadow = self._apply(shadow, self.decode(stored), only=closure, live=False)
        slices = root.slices
        changed = root.changed
        for owner in owners:
            slices = slices.set(owner, shadow.slices[owner])
            changed = changed.set(owner, shadow.changed.get(owner, 0))
        return replace(root, slices=slices, changed=changed)

    # ── application ────────────────────────────────────────────────────────
    def _apply(
        self,
        root: Root,
        event: Event[Any],
        *,
        only: set[str] | None = None,
        skip: set[str] | None = None,
        live: bool = True,
        registry: Registry | None = None,
    ) -> Root:
        reg = registry or self.registry
        specs = reg.reducers_by_type.get(event.type.name)
        if not specs:
            return Root(event.seq, event.at, root.slices, root.changed, root.tainted)
        tz = reg.tz_of(root)
        slices, changed, tainted = root.slices, root.changed, root.tainted
        pre_view: list[FactView] = []

        def facts_factory(allowed: frozenset[str]) -> Callable[[], FactView]:
            def make() -> FactView:
                if not pre_view:
                    pre_view.append(FactView(root, event.at, reg))
                return pre_view[0].restricted(allowed)

            return make

        for spec in specs:
            owner = spec.owner
            if only is not None and owner not in only:
                continue
            if skip is not None and owner in skip:
                continue
            state = slices[owner]
            ctx = ReduceContext(
                owner=owner, event_id=event.id, now=event.at, params=reg.params_of(owner, root), tz=tz,
                _facts_factory=facts_factory(spec.reads),
            )
            result = call(spec.fn, state, event, ctx, label=f"réducteur {owner} sur {event.type.name}")
            if isinstance(result, Failed):
                tainted = tainted.set(owner, event.seq)
                self.anomalies.append(f"{owner}@{event.seq}: {result.error!r}")
                if live:
                    self.trace("tainted", owner=owner, seq=event.seq, error=repr(result.error))
                continue
            if result is not state:
                slices = slices.set(owner, result)
                changed = changed.set(owner, event.seq)
        return Root(event.seq, event.at, slices, changed, tainted)

    # ── écriture ───────────────────────────────────────────────────────────
    async def append(
        self,
        drafts: Sequence[Draft[Any]],
        *,
        emitter: str,
        correlation: str,
        origin: Origin = Origin.PROCESS,
        causation: str | None = None,
        basis: Root | None = None,
        guard: Guard | None = None,
        holder: str | None = None,
    ) -> Commit:
        async with self._lock:
            head_root = self._root
            now = self.clock.now()

            # 1. dédoublonnage
            fresh: list[Draft[Any]] = []
            existing: list[int] = []
            seen_keys: set[tuple[str, str]] = set()
            for d in drafts:
                if d.dedupe_key is not None:
                    k = (d.type.name, d.dedupe_key)
                    prev = self.store.find_dedupe(*k)
                    if prev is not None:
                        existing.append(prev)
                        continue
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                fresh.append(d)
            if not fresh:
                return Commit(tuple(existing), (), head_root, deduped=True)

            # 2. validation
            for d in fresh:
                self._validate(d, emitter)

            # 3. garde
            if guard is not None:
                failure = check(
                    guard,
                    holder=holder or correlation,
                    basis_view=FactView(basis or head_root, now, self.registry),
                    head_view=FactView(head_root, now, self.registry),
                )
                if failure is not None:
                    self.trace("superseded", correlation=correlation, guard=failure.guard,
                               reason=failure.reason, changed=list(failure.changed))
                    raise failure

            # 4. estampille + 5. application
            at = max(now, head_root.at)
            seq = head_root.seq
            events: list[Event[Any]] = []
            full: list[Event[Any]] = []
            contents: list[ContentRow] = []
            dedupe: list[tuple[str, str, int]] = []
            outbox: list[OutboxRow] = []
            stored: list[StoredEvent] = []
            root = head_root
            basis_seq = (basis or head_root).seq
            for d in fresh:
                seq += 1
                eid = self.ids.new(at)
                stored_data, full_data, rows = self._split_content(d, seq)
                contents.extend(rows)
                ev = Event(seq, eid, d.type, at, stored_data, causation, correlation, basis_seq, origin)
                events.append(ev)
                full.append(replace(ev, data=full_data))
                stored.append(
                    StoredEvent(seq, eid, d.type.name, d.type.version, at, causation, correlation, basis_seq,
                                origin.value, stored_data.model_dump_json())
                )
                if d.dedupe_key is not None:
                    dedupe.append((d.type.name, d.dedupe_key, seq))
                for eff in self.registry.effects.get(d.type.name, ()):
                    outbox.append(OutboxRow(f"{eid}:{eff.owner}", seq, f"{eff.owner}:{d.type.name}"))
                root = self._apply(root, ev)

            # 6. transaction
            snapshot = None
            if (root.seq - self._last_snapshot_seq >= self._snapshot_every
                    or root.at - self._last_snapshot_at >= self._snapshot_interval):
                snapshot = SnapshotRow(root.seq, root.at, self.snapshot_data(root))
            batch = AppendBatch(stored, contents, dedupe, outbox, snapshot, self._t0_apply(full))
            await self.store.append(batch)

            # 7. publication
            self._root = root
            if snapshot is not None:
                self._last_snapshot_seq, self._last_snapshot_at = snapshot.seq, snapshot.at
            own = self._inflight.get(correlation)
            if own is not None:
                own.basis = root  # lire ses propres écritures
            commit = Commit(tuple(existing) + tuple(e.seq for e in events), tuple(events), root)

        # 8. notifications (hors verrou)
        self._recheck_inflight(correlation, root)
        for fn in list(self._listeners):
            call(fn, events, root, label="écouteur du Mind")
        return commit

    def _validate(self, d: Draft[Any], emitter: str) -> None:
        t = d.type
        if t.name not in self.registry.events or self.registry.events.get(t.name) is not t:
            raise ValueError(f"type d'événement non enregistré : {t.name}")
        if t.owner != emitter:
            raise PermissionError(f"{emitter} ne peut pas émettre {t.name} (propriétaire : {t.owner})")
        if not isinstance(d.data, t.payload):
            raise TypeError(f"{t.name} attend {t.payload.__name__}, reçu {type(d.data).__name__}")
        if t.authored and not isinstance(getattr(d.data, "voice", None), VoiceProvenance):
            raise ValueError(f"{t.name} est écrit par elle : la provenance de voix est exigée")
        for f in t.content_fields:
            v = getattr(d.data, f, None)
            if v is not None and (not isinstance(v, Content) or v.text is None):
                raise ValueError(f"{t.name}.{f} doit être un Content avec texte à l'émission")

    def _split_content(self, d: Draft[Any], seq: int) -> tuple[Payload, Payload, list[ContentRow]]:
        t = d.type
        if not t.content_fields:
            return d.data, d.data, []
        subjects: list[str] = []
        for sf in sorted(t.subject_fields):
            v = getattr(d.data, sf, None)
            if isinstance(v, str) and v:
                subjects.append(v)
            elif isinstance(v, (tuple, list)):
                subjects.extend(str(x) for x in v if x)
        stored_update: dict[str, Content] = {}
        full_update: dict[str, Content] = {}
        rows: list[ContentRow] = []
        for f in sorted(t.content_fields):
            v = getattr(d.data, f, None)
            if v is None:
                continue
            ref = f"{seq}.{f}"
            rows.append(ContentRow(ref, seq, tuple(sorted(set(subjects))), v.level, v.text or ""))
            stored_update[f] = Content(ref=ref, level=v.level)
            full_update[f] = Content(ref=ref, text=v.text, level=v.level)
        return d.data.model_copy(update=stored_update), d.data.model_copy(update=full_update), rows

    def _t0_apply(self, full_events: list[Event[Any]]) -> Callable[[Any], None] | None:
        t0 = [p for p in self.registry.projectors.values() if p.tier is Tier.T0]
        if not t0:
            return None

        def apply(sql: Any) -> None:
            for p in t0:
                relevant = [e for e in full_events if e.type.name in p.types]
                if relevant:
                    p.projector.apply(sql, relevant, "")

        return apply

    # ── épisodes en vol ────────────────────────────────────────────────────
    def track(self, correlation: str, guard: Guard, basis: Root, holder: str,
              on_supersede: Callable[[Superseded], None]) -> None:
        self._inflight[correlation] = InFlight(correlation, guard, basis, holder, on_supersede)

    def untrack(self, correlation: str) -> None:
        self._inflight.pop(correlation, None)

    def inflight(self, correlation: str) -> InFlight | None:
        return self._inflight.get(correlation)

    def _recheck_inflight(self, author: str, head: Root) -> None:
        if not self._inflight:
            return
        now = self.clock.now()
        head_view = FactView(head, now, self.registry)
        for corr, inf in list(self._inflight.items()):
            if corr == author:
                continue
            failure = check(inf.guard, holder=inf.holder,
                            basis_view=FactView(inf.basis, now, self.registry), head_view=head_view)
            if failure is not None:
                self._inflight.pop(corr, None)
                self.trace("superseded", correlation=corr, guard=failure.guard, reason=failure.reason,
                           changed=list(failure.changed))
                call(inf.on_supersede, failure, label="annulation d'épisode")

    # ── oubli ──────────────────────────────────────────────────────────────
    async def forget(self, subject: str) -> int:
        """Efface les contenus d'un sujet et purge les projections qui les
        reprennent ; le journal garde ses enveloppes (références orphelines)."""
        projectors = list(self.registry.projectors.values())

        def purge(mind_sql: Any, views_sql: Any) -> None:
            for p in projectors:
                hook = getattr(p.projector, "forget", None)
                if hook is None:
                    continue
                if p.tier is Tier.T0:
                    hook(mind_sql, subject, "")
                else:
                    hook(views_sql, subject, f"_v{p.version}")

        async with self._lock:
            removed = await self.store.forget_subject(subject, purge)
        self.trace("forget", subject=subject, contents=removed)
        return removed

    # ── reconstruction en ligne ────────────────────────────────────────────
    async def rebuild(self, owners: Iterable[str], *, registry: Registry | None = None) -> dict[str, Any]:
        """Reconstruit ``owners`` depuis la genèse dans une racine fantôme, sans
        arrêter les ajouts, puis bascule. Avec ``registry``, le nouveau code
        (nouvelle version de tranche) est adopté à la bascule."""
        owners = set(owners)
        new_reg = registry or self.registry
        closure = new_reg.read_closure(owners)
        h1 = self.head
        shadow = new_reg.initial_root()
        count = 0
        for stored in self.store.read(after=0, upto=h1):
            shadow = self._apply(shadow, self._decode_with(new_reg, stored), only=closure, live=False,
                                 registry=new_reg)
            count += 1
            if count % 2000 == 0:
                await asyncio.sleep(0)
        async with self._lock:
            for stored in self.store.read(after=h1, upto=self.head):
                shadow = self._apply(shadow, self._decode_with(new_reg, stored), only=closure, live=False,
                                     registry=new_reg)
            live = self._root
            mismatches = []
            for owner in sorted(closure - owners):
                if digest(shadow.slices[owner]) != digest(live.slices[owner]):
                    mismatches.append(owner)
            slices, changed = live.slices, live.changed
            for owner in owners:
                slices = slices.set(owner, shadow.slices[owner])
                changed = changed.set(owner, shadow.changed.get(owner, 0))
            self._root = replace(live, slices=slices, changed=changed)
            self.registry = new_reg
            if mismatches:
                self.trace("rebuild_mismatch", owners=mismatches)
        return {"closure": sorted(closure), "mismatches": mismatches, "replayed": count}

    @staticmethod
    def _decode_with(registry: Registry, stored: StoredEvent) -> Event[Any]:
        t, data = registry.events.decode(stored.type, stored.v, stored.data)
        return Event(stored.seq, stored.id, t, stored.at, data, stored.causation, stored.correlation,
                     stored.basis, Origin(stored.origin))


def event_type_names(types: Iterable[EventType[Any]]) -> set[str]:
    return {t.name for t in types}
