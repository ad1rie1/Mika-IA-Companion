"""La file de sortie : les effets visibles ne partent qu'après le commit.

Une ligne de la file est écrite dans la transaction même de l'événement ;
l'exécuteur la traite ensuite, au moins une fois — le gestionnaire est
idempotent par identifiant d'événement. Après un arrêt brutal, les lignes
restées en attente sont reprises.

Un gestionnaire peut rendre des brouillons (ce que l'effet a produit :
``effect.executed``) : ils sont journalisés avant que la ligne soit close,
dédoublonnés par ligne — une reprise ne les écrit pas deux fois.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mika.kernel.events import Content, Draft, Event, Origin
from mika.kernel.state import Root
from mika.runtime.boundary import Failed, acall

if TYPE_CHECKING:
    from mika.runtime.mind import Mind


class EffectExecutor:
    def __init__(self, mind: Mind, ports: Mapping[str, Any] | None = None, *, max_attempts: int = 5) -> None:
        self.mind = mind
        self.ports = dict(ports or {})
        self.max_attempts = max_attempts
        self._wake = asyncio.Event()
        self._stopping = False
        self.executed = 0
        self.failed = 0
        mind.subscribe(self._on_events)

    def _on_events(self, events: Sequence[Event[Any]], root: Root) -> None:
        if any(self.mind.registry.effects.get(e.type.name) for e in events):
            self._wake.set()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    async def run(self) -> None:
        while not self._stopping:
            self._wake.clear()
            await self.drain()
            if self._stopping:
                break
            await self._wake.wait()

    def load(self, seq: int) -> Event[Any]:
        stored = self.mind.store.get_events([seq])[0]  # type: ignore[attr-defined]
        ev = self.mind.decode(stored)
        return with_content(self.mind, ev)

    async def drain(self) -> int:
        done = 0
        for row in self.mind.store.pending_outbox():
            owner, type_name = row.effect.split(":", 1)
            specs = [s for s in self.mind.registry.effects.get(type_name, ()) if s.owner == owner]
            if not specs:
                await self.mind.store.mark_outbox(row.key, "orphan", "aucun gestionnaire")
                continue
            ev = self.load(row.seq)
            out = await acall(specs[0].fn, ev, self.ports, label=f"effet {row.effect}")
            if isinstance(out, Failed):
                self.failed += 1
                status = "failed" if row.attempts + 1 >= self.max_attempts else "pending"
                await self.mind.store.mark_outbox(row.key, status, repr(out.error)[:500])
                continue
            drafts = [d for d in (out if isinstance(out, (list, tuple)) else ()) if isinstance(d, Draft)]
            if drafts:
                keyed = [replace(d, dedupe_key=d.dedupe_key or f"effet:{row.key}:{i}") for i, d in enumerate(drafts)]
                await self.mind.append(keyed, emitter=specs[0].owner, correlation=f"effet:{row.seq}",
                                       origin=Origin.KERNEL)
            await self.mind.store.mark_outbox(row.key, "done")
            self.executed += 1
            done += 1
        return done


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
