"""Exécuter une vue d'inspection déclarée par une faculté (``@f.inspect``).

Une vue qui lève ne casse pas la page : elle rend une note d'erreur — on
ouvre l'inspecteur justement quand quelque chose ne va pas.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from mika.kernel.faculty import InspectSpec
from mika.kernel.inspect import Block, InspectContext, Note
from mika.runtime.boundary import Failed, call
from mika.runtime.effects import with_content

if TYPE_CHECKING:
    from mika.runtime.bootstrap import Kernel


def views(kernel: Kernel) -> list[InspectSpec]:
    return sorted(kernel.registry.inspectors, key=lambda v: (v.owner, v.name))


def find(kernel: Kernel, owner: str, name: str) -> InspectSpec | None:
    return next((v for v in kernel.registry.inspectors if v.owner == owner and v.name == name), None)


def run_view(kernel: Kernel, spec: InspectSpec, params: Mapping[str, str] | None = None,
             when: Callable[[int], str] = str) -> list[Block]:
    frame = kernel.mind.frame()
    mind = kernel.mind

    def journal(types: list[str], limit: int, *, where: Any = None, before: int | None = None,
                correlations: Any = None) -> list[Any]:
        stored = mind.store.latest(types, max(0, min(int(limit), 1000)), where=where, before=before,
                                   correlations=correlations)
        return [with_content(mind, mind.decode(s)) for s in stored]

    ctx = InspectContext(store=kernel.ports["store"], ports=kernel.ports, params=dict(params or {}), when=when,
                         journal=journal, counter=mind.store.tally)
    out: Any = call(spec.fn, frame.state(spec.owner), frame, ctx, label=f"vue {spec.owner}/{spec.name}")
    if isinstance(out, Failed):
        return [Note(f"Cette vue a échoué : {out.error!r}"[:500], tone="ko")]
    return list(out or [])
