"""Le journal : vue d'ensemble, chronologie, épisodes (« pourquoi a-t-elle
dit ça ? ») et événements (ce qui l'a produit, qui le lit)."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import runtime as rt
from mika.inspector.ui import PREFIX, SESSION_COOKIE, UI
from mika.runtime import health
from mika.vocab.affect import FR

PAGE = 200
_PROVENANCE_EVENT = ("memory:", "event:", "goal:", "thought:")


def _seqs(ui: UI, where: str, params: tuple[Any, ...], limit: int) -> list[int]:
    rows = ui.kernel.mind.store.query_mind(f"SELECT seq FROM events {where} ORDER BY seq DESC LIMIT ?",
                                           (*params, limit))
    return [int(r[0]) for r in rows]


def _events(ui: UI, seqs: list[int]) -> list[Any]:
    return [ui.decode(s) for s in ui.kernel.mind.store.get_events(seqs)]


def _link_of(ref: str) -> tuple[str, str] | None:
    """Une provenance (« memory:12 ») → le lien vers l'événement qui l'a créée."""
    head, _, tail = ref.partition(":")
    if f"{head}:" in _PROVENANCE_EVENT and tail.isdigit():
        return ref, f"{PREFIX}/evenement/{tail}"
    return None


def routes(ui: UI) -> list[Route]:
    kernel = ui.kernel
    deps = ui.deps

    async def login(request: Request) -> Response:
        error = ""
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                error = "Jeton de formulaire invalide : recharge la page."
            else:
                acc = deps.accounts.authenticate(data.get("username", ""), data.get("password", ""))
                if acc is None or not acc.operator:
                    error = "Identifiants invalides, ou compte non opérateur."
                else:
                    key = await deps.accounts.open_session(acc)
                    response = RedirectResponse(PREFIX + "/", status_code=303)
                    response.set_cookie(SESSION_COOKIE, key, httponly=True, samesite="lax", secure=ui.cookie_secure)
                    return response
        return ui.page(request, "login.html", "Connexion", error=error)

    async def overview(request: Request) -> Response:
        frame = kernel.mind.frame()
        mood = frame.get(affect_c.MOOD)
        felt = "au repos" if mood.felt_intensity < 0.1 else f"{FR[mood.felt]} ({mood.felt_intensity:.2f})"
        rhythm = f"{frame.get(body_c.PHASE).value}, énergie {frame.get(body_c.ENERGY):.0%}"
        ended = _events(ui, _seqs(ui, "WHERE type=?", (rt.EPISODE_ENDED.name,), 25))
        episodes = [{"when": ui.when(e.at), "corr": e.correlation, "kind": e.data.kind, "target": e.data.target,
                     "outcome": e.data.outcome, "detail": (e.data.detail or "")[:120]} for e in reversed(ended)]
        declared = getattr(kernel.deps.gateway, "routes", {})
        model_routes = sorted((declared() if callable(declared) else declared).items())
        report = health.report(kernel)
        pending = len(frame.get(rt.PENDING_EFFECTS))
        return ui.page(request, "overview.html", "Mika", head=kernel.mind.head, mood=felt, rhythm=rhythm,
                       boots=kernel.mind.root.slices["kernel"].boots, routes=model_routes, episodes=episodes,
                       health_status=report.status, checks=[c for c in report.checks if c.state != health.OK],
                       pending=pending)

    async def timeline(request: Request) -> Response:
        kind = request.query_params.get("type", "").strip()[:80]
        corr = request.query_params.get("correlation", "").strip()[:120]
        try:
            before = int(request.query_params.get("before", "0")) or None
        except ValueError:
            before = None
        clauses, params = [], []
        if kind:
            clauses.append("type LIKE ? ESCAPE '\\'")
            params.append(kind.replace("\\", "").replace("%", "").replace("_", "\\_") + "%")
        if corr:
            clauses.append("correlation=?")
            params.append(corr)
        if before:
            clauses.append("seq < ?")
            params.append(before)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        seqs = _seqs(ui, where, tuple(params), PAGE)
        events = [{"seq": e.seq, "when": ui.when(e.at), "type": e.type.name, "corr": e.correlation,
                   "data": ui.show(e, 1500)} for e in reversed(_events(ui, seqs))]
        older = min(seqs) if len(seqs) == PAGE else None
        return ui.page(request, "timeline.html", "Chronologie", events=events, kind=kind, corr=corr, older=older)

    async def episode(request: Request) -> Response:
        corr = request.path_params["corr"]
        seqs = [int(r[0]) for r in kernel.mind.store.query_mind(
            "SELECT seq FROM events WHERE correlation=? ORDER BY seq LIMIT 500", (corr,))]
        events = _events(ui, seqs)
        started = next((e for e in events if e.type.name == rt.EPISODE_STARTED.name), None)
        ended = next((e for e in events if e.type.name == rt.EPISODE_ENDED.name), None)
        utterances = [e for e in events if e.type.name == rt.UTTERANCE.name]
        cause = None
        if started is not None and started.data.reply_to:
            found = _events(ui, [started.data.reply_to])
            cause = found[0] if found else None
        said = [{"text": (u.data.text.text or "(oublié)"), "target": u.data.target, "visible": u.data.visible,
                 "sections": u.data.sections, "tools": [(t.name, t.ok) for t in u.data.tools],
                 "provenance": [(_link_of(p) or (p, "")) for p in u.data.provenance]} for u in utterances]
        rows = [{"seq": e.seq, "when": ui.when(e.at), "type": e.type.name, "data": ui.show(e)} for e in events]
        traces = [t for t in list(deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)]
        return ui.page(request, "episode.html", f"Épisode {corr[:40]}", corr=corr, started=started, ended=ended,
                       cause=cause, cause_data=ui.show(cause, 1500) if cause else "", said=said, events=rows,
                       traces=traces)

    async def event(request: Request) -> Response:
        try:
            seq = int(request.path_params["seq"])
        except ValueError:
            seq = 0
        found = _events(ui, [seq]) if seq > 0 else []
        if not found:
            return ui.page(request, "event.html", "Événement introuvable", status=404, e=None)
        e = found[0]
        readers = sorted({s.owner for s in kernel.registry.reducers_by_type.get(e.type.name, [])})
        processes = sorted(p.name for p in kernel.registry.processes.values() if e.type.name in p.wake_on)
        projectors = sorted(p.name for p in kernel.registry.projectors.values() if e.type.name in p.types)
        answered = _events(ui, [int(r[0]) for r in kernel.mind.store.query_mind(
            "SELECT seq FROM events WHERE type=? AND json_extract(data, '$.reply_to')=? ORDER BY seq LIMIT 20",
            (rt.EPISODE_STARTED.name, seq))])
        return ui.page(request, "event.html", f"{e.type.name} · seq {e.seq}", e=e, when=ui.when(e.at),
                       data=ui.show(e, 20000), owner=e.type.owner, public=e.type.public, readers=readers,
                       processes=processes, projectors=projectors,
                       answered=[(a.correlation, a.data.kind, ui.when(a.at)) for a in answered])

    return [
        Route(PREFIX + "/connexion", login, methods=["GET", "POST"]),
        Route(PREFIX + "/", ui.guarded(overview)),
        Route(PREFIX + "/chronologie", ui.guarded(timeline)),
        Route(PREFIX + "/episode/{corr:str}", ui.guarded(episode)),
        Route(PREFIX + "/evenement/{seq:str}", ui.guarded(event)),
    ]
