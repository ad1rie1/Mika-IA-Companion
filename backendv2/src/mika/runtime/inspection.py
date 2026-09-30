"""Exécuter ce que les facultés déclarent pour la console : vues, fiches
d'objets (en-tête, recherche, onglets), badges et vitaux.

Rien ici ne nomme une faculté. Une vue, un en-tête ou un badge qui lève ne
casse pas la page : il devient une note (on ouvre la console justement quand
quelque chose ne va pas). Chaque vue est chronométrée : les lentes se voient
dans « Système ».
"""

from __future__ import annotations

import inspect as pyinspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mika.kernel.faculty import ActionSpec, InspectSpec, SubjectSpec, VitalSpec
from mika.kernel.inspect import Block, Found, Head, InspectContext, Note, Vital, read_params
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.effects import with_content

if TYPE_CHECKING:
    from mika.runtime.bootstrap import Kernel

#: au-delà, une vue est « lente » (elle tourne sur la boucle qui sert les conversations)
SLOW_US = 200_000


@dataclass(slots=True)
class Timing:
    runs: int = 0
    last_us: int = 0
    max_us: int = 0
    failures: int = 0


class Inspection:
    """Ce que la console demande au noyau, pour un noyau donné."""

    def __init__(self, kernel: Kernel, *, sampler: Callable[..., list[tuple[int, float]]] | None = None) -> None:
        self.kernel = kernel
        self.sampler = sampler
        self.timings: dict[str, Timing] = {}
        self._badges: dict[str, tuple[int, Any]] = {}

    # ── le catalogue ──
    @property
    def registry(self) -> Any:
        return self.kernel.registry

    def views(self) -> list[InspectSpec]:
        return sorted(self.registry.inspectors, key=lambda v: (v.owner, v.name))

    def find(self, owner: str, name: str) -> InspectSpec | None:
        return next((v for v in self.registry.inspectors if v.owner == owner and v.name == name), None)

    def in_section(self, section: str) -> list[InspectSpec]:
        return sorted((v for v in self.registry.inspectors if v.section == section),
                      key=lambda v: (v.order, v.title))

    def tabs(self, kind: str) -> list[InspectSpec]:
        return sorted((v for v in self.registry.inspectors if v.subject == kind), key=lambda v: (v.order, v.title))

    def subject(self, kind: str) -> SubjectSpec | None:
        return self.registry.subjects.get(kind)

    def action(self, key: str) -> ActionSpec | None:
        return self.registry.actions.get(key)

    def actions_for(self, *, subject: str = "", section: str = "") -> list[ActionSpec]:
        out = [a for a in self.registry.actions.values()
               if (subject and a.subject == subject) or (section and a.section == section)]
        return sorted(out, key=lambda a: (a.order, a.title))

    # ── exécuter ──
    def context(self, params: Mapping[str, str] | None = None, when: Callable[[int], str] = str, *,
                subject: str = "", values: Mapping[str, Any] | None = None) -> InspectContext:
        mind = self.kernel.mind

        def journal(types: list[str], limit: int, *, where: Any = None, before: int | None = None,
                    correlations: Any = None) -> list[Any]:
            stored = mind.store.latest(types, max(0, min(int(limit), 1000)), where=where, before=before,
                                       correlations=correlations)
            return [with_content(mind, mind.decode(s)) for s in stored]

        return InspectContext(store=self.kernel.ports["store"], ports=self.kernel.ports, params=dict(params or {}),
                              when=when, journal=journal, counter=mind.store.tally, subject=subject,
                              values=dict(values or {}), now=mind.clock.now(), sampler=self.sampler)

    def run(self, spec: InspectSpec, params: Mapping[str, str] | None = None, when: Callable[[int], str] = str,
            *, subject: str = "") -> list[Block]:
        """Une vue synchrone (une vue asynchrone rend une note : utiliser ``arun``)."""
        values, notes = read_params(spec.typed, params or {})
        frame = self.kernel.mind.frame()
        ctx = self.context(params, when, subject=subject, values=values)
        clock = self.kernel.mind.clock
        t0 = clock.now()
        out: Any = call(spec.fn, frame.state(spec.owner), frame, ctx, label=f"vue {spec.owner}/{spec.name}")
        if pyinspect.isawaitable(out):
            out.close()
            out = Failed(RuntimeError("vue asynchrone : à exécuter par arun"))
        self._time(f"{spec.owner}/{spec.name}", clock.now() - t0, isinstance(out, Failed))
        if isinstance(out, Failed):
            return [Note(f"Cette vue a échoué : {out.error!r}"[:500], tone="danger")]
        return [Note(n, tone="warn") for n in notes] + list(out or [])

    async def arun(self, spec: InspectSpec, params: Mapping[str, str] | None = None,
                   when: Callable[[int], str] = str, *, subject: str = "") -> list[Block]:
        """Une vue, synchrone ou asynchrone (une vue qui lit un port asynchrone :
        l'arborescence d'un atelier, un journal git)."""
        values, notes = read_params(spec.typed, params or {})
        frame = self.kernel.mind.frame()
        ctx = self.context(params, when, subject=subject, values=values)
        clock = self.kernel.mind.clock
        t0 = clock.now()
        out: Any = call(spec.fn, frame.state(spec.owner), frame, ctx, label=f"vue {spec.owner}/{spec.name}")
        if pyinspect.isawaitable(out):
            pending = out
            out = await acall(lambda: pending, label=f"vue {spec.owner}/{spec.name}")
        self._time(f"{spec.owner}/{spec.name}", clock.now() - t0, isinstance(out, Failed))
        if isinstance(out, Failed):
            return [Note(f"Cette vue a échoué : {out.error!r}"[:500], tone="danger")]
        return [Note(n, tone="warn") for n in notes] + list(out or [])

    def head(self, kind: str, key: str, when: Callable[[int], str] = str) -> Head | Note | None:
        """L'en-tête d'un objet : ``None`` s'il est inconnu, une note si l'en-tête a échoué."""
        spec = self.subject(kind)
        if spec is None:
            return None
        frame = self.kernel.mind.frame()
        out: Any = call(spec.head, frame.state(spec.owner), frame, self.context(None, when, subject=key), key,
                        label=f"fiche {kind}")
        if isinstance(out, Failed):
            return Note(f"L'en-tête de cette fiche a échoué : {out.error!r}"[:500], tone="danger")
        return out

    def search(self, kind: str, text: str, limit: int = 20) -> list[Found]:
        spec = self.subject(kind)
        if spec is None or spec.search is None:
            return []
        frame = self.kernel.mind.frame()
        out: Any = call(spec.search, frame.state(spec.owner), frame, self.context(), text.strip()[:200],
                        max(1, min(limit, 500)), label=f"recherche {kind}")
        return [] if isinstance(out, Failed) else list(out or [])[:limit]

    def badge(self, spec: InspectSpec) -> tuple[int, str] | None:
        """Ce qui demande une action (mis en cache jusqu'au prochain événement)."""
        if spec.badge is None:
            return None
        key = f"{spec.owner}/{spec.name}"
        head = self.kernel.mind.head
        cached = self._badges.get(key)
        if cached is not None and cached[0] == head:
            return cached[1]
        frame = self.kernel.mind.frame()
        out: Any = call(spec.badge, frame.state(spec.owner), frame, label=f"badge {key}")
        value: tuple[int, str] | None
        if isinstance(out, Failed) or out is None:
            value = None
        elif isinstance(out, tuple):
            value = (int(out[0]), str(out[1]))
        else:
            value = (int(out), "")
        value = value if value is not None and value[0] > 0 else None
        self._badges[key] = (head, value)
        return value

    def vitals(self) -> list[tuple[VitalSpec, Vital]]:
        frame = self.kernel.mind.frame()
        out = []
        for spec in self.registry.vitals:
            got: Any = call(spec.fn, frame.state(spec.owner), frame, label=f"vital {spec.key}")
            if isinstance(got, Vital):
                out.append((spec, got))
        return out

    def slow(self) -> list[tuple[str, Timing]]:
        return sorted(((k, t) for k, t in self.timings.items() if t.max_us >= SLOW_US),
                      key=lambda kt: -kt[1].max_us)

    def _time(self, key: str, us: int, failed: bool) -> None:
        t = self.timings.setdefault(key, Timing())
        t.runs += 1
        t.last_us = us
        t.max_us = max(t.max_us, us)
        t.failures += int(failed)


# ── compatibilité (tests et premières vues) ──


def views(kernel: Kernel) -> list[InspectSpec]:
    return Inspection(kernel).views()


def find(kernel: Kernel, owner: str, name: str) -> InspectSpec | None:
    return Inspection(kernel).find(owner, name)


def run_view(kernel: Kernel, spec: InspectSpec, params: Mapping[str, str] | None = None,
             when: Callable[[int], str] = str, *, subject: str = "") -> list[Block]:
    return Inspection(kernel).run(spec, params, when, subject=subject)
