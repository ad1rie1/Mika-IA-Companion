"""L'esprit : décisions, état et faits, graphe des contributions, et les vues
que chaque faculté déclare (``@f.inspect``) — l'inspecteur n'en connaît
aucune ; une faculté ajoutée y apparaît seule."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mika.inspector.ui import PREFIX, UI
from mika.kernel.facts import FactKey
from mika.runtime import inspection
from mika.runtime.boundary import Failed, call

FACT_REPR_MAX = 400


def _names(items: Any) -> str:
    return ", ".join(sorted(items)) or "—"


def contributions(kernel: Any) -> list[dict[str, Any]]:
    """Ce que chaque faculté apporte au reste : lu depuis le registre, jamais
    transcrit."""
    reg = kernel.registry
    readers: dict[str, set[str]] = defaultdict(set)
    for f in reg.faculties.values():
        specs = [*f.reducers, *f.facts, *f.sections, *f.enrichers, *f.proposers, *f.modulators, *f.processes,
                 *f.appraisals]
        for s in specs:
            for r in getattr(s, "reads", ()):
                readers[r].add(f.name)
    out = []
    for f in reg.faculties.values():
        own = set(f.events)
        reduces = sorted({t.name for s in f.reducers for t in s.types if t.name not in own}
                         | {f"forme {sh.__name__}" for s in f.reducers for sh in s.shapes})
        out.append({
            "name": f.name,
            "public": sorted(n for n, t in f.events.items() if t.public),
            "private": len([t for t in f.events.values() if not t.public]),
            "reduces": reduces,
            "facts": [(s.key.name, _names(readers.get(s.key.name, set()) - {f.name})) for s in f.facts],
            "reads": sorted({r for s in [*f.reducers, *f.facts, *f.sections, *f.proposers, *f.processes]
                             for r in getattr(s, "reads", ()) if r not in {x.key.name for x in f.facts}}),
            "sections": [(s.key, s.zone.value, "non fiable" if getattr(s, "untrusted", False) else "",
                          _names(s.episodes)) for s in f.sections],
            "enrichers": [(s.key, s.deadline_ms) for s in f.enrichers],
            "proposers": [(_names(s.kinds), ", ".join(f"{r} [{lo:g} ; {hi:g}]" for r, (lo, hi) in s.reasons.items()))
                          for s in f.proposers],
            "modulators": [_names(s.kinds) for s in f.modulators],
            "appraisals": [s.type.name for s in f.appraisals],
            "processes": [(s.name, s.lane, _names(s.wake_on)[:160]) for s in f.processes],
            "tools": [(s.name, s.bundle, _names(s.episodes), str(s.effect)) for s in f.tools],
            "capabilities": [s.name for s in f.capabilities],
            "projectors": [(s.name, str(s.tier), s.version) for s in f.projectors],
            "views": [(v.name, v.title) for v in f.inspectors],
        })
    return out


def routes(ui: UI) -> list[Route]:
    kernel = ui.kernel

    async def decisions(request: Request) -> Response:
        frame = kernel.mind.frame()
        rows = kernel.arbiter.rows(frame)
        seqs = [int(r[0]) for r in kernel.mind.store.query_mind(
            "SELECT seq FROM events WHERE type='kernel.selected' ORDER BY seq DESC LIMIT 30")]
        chosen = [ui.decode(s) for s in kernel.mind.store.get_events(seqs)]
        selections = [{"seq": e.seq, "when": ui.when(e.at), "fired": ", ".join(e.data.fired), "draw": e.data.draw}
                      for e in reversed(chosen)]
        policy = kernel.registry.arbitration
        return ui.page(request, "decisions.html", "Décisions", rows=rows, selections=selections,
                       thresholds=sorted(policy.thresholds.items()), rates=dict(policy.max_rates),
                       anomalies=list(kernel.arbiter.anomalies)[-20:])

    async def state(request: Request) -> Response:
        frame = kernel.mind.frame()
        root = kernel.mind.root
        facts = []
        for name, spec in sorted(kernel.registry.providers.items()):
            if isinstance(spec.key, FactKey):
                got = call(frame.get, spec.key, label=f"fait {name}")
                value = f"(erreur : {got.error!r})" if isinstance(got, Failed) else repr(got)
            else:
                value = "famille : dépend de son argument"
            facts.append((name, spec.owner, getattr(spec.key, "doc", ""), value[:FACT_REPR_MAX]))
        slices = [(owner, repr(root.slices[owner])[:6000], root.changed.get(owner, 0)) for owner in root.slices]
        return ui.page(request, "state.html", "État et faits", facts=facts, slices=slices,
                       tainted=dict(root.tainted.items()))

    async def graph(request: Request) -> Response:
        return ui.page(request, "contributions.html", "Contributions", faculties=contributions(kernel))

    async def index(request: Request) -> Response:
        groups: dict[str, list[Any]] = defaultdict(list)
        for v in inspection.views(kernel):
            groups[v.owner].append(v)
        return ui.page(request, "views.html", "Facultés", groups=sorted(groups.items()))

    async def view(request: Request) -> Response:
        owner, name = request.path_params["owner"], request.path_params["name"]
        spec = inspection.find(kernel, owner, name)
        if spec is None:
            return ui.page(request, "view.html", "Vue inconnue", status=404, spec=None, blocks=[], values={})
        params = {k: v[:200] for k, v in request.query_params.items()}
        blocks = inspection.run_view(kernel, spec, params, ui.when)
        siblings = [v for v in inspection.views(kernel) if v.owner == owner]
        return ui.page(request, "view.html", f"{spec.title} · {owner}", spec=spec, blocks=blocks, values=params,
                       siblings=siblings)

    return [
        Route(PREFIX + "/decisions", ui.guarded(decisions)),
        Route(PREFIX + "/etat", ui.guarded(state)),
        Route(PREFIX + "/contributions", ui.guarded(graph)),
        Route(PREFIX + "/facultes", ui.guarded(index)),
        Route(PREFIX + "/facultes/{owner:str}/{name:str}", ui.guarded(view)),
    ]
