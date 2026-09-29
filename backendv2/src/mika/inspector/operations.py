"""L'exploitation : santé, appels de modèle (coûts, cache), file
d'approbation, rapports de simulation."""

from __future__ import annotations

import json
import re
from datetime import datetime

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.contracts import runtime as rt
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY, US
from mika.runtime import health

REPORT_NAME = re.compile(r"^[\w.-]{1,120}\.(md|html|json|txt)$")
REPORT_MAX = 400_000


def routes(ui: UI) -> list[Route]:
    kernel = ui.kernel
    deps = ui.deps

    async def sante(request: Request) -> Response:
        report = health.report(kernel)
        sched = kernel.scheduler
        running = set(sched.running())
        processes = [{
            "name": s.name, "owner": s.owner, "lane": s.lane, "runs": sched.runs.get(s.name, 0),
            "failures": sched.failures.get(s.name, 0), "consecutive": sched.consecutive.get(s.name, 0),
            "last": ui.when(sched.last_run(s.name) or 0), "running": s.name in running,
            "error": sched.last_error.get(s.name, (0, ""))[1],
        } for s in sched.specs]
        lag = kernel.projections.lag()
        projections = [(p.name, str(p.tier), p.version, lag.get(p.name, 0))
                       for p in sorted(kernel.registry.projectors.values(), key=lambda p: p.name)]
        return ui.page(request, "health.html", "Santé", report=report, processes=processes, projections=projections,
                       quarantined=kernel.projections.quarantined[-50:], public=json.dumps(report.public(), indent=1))

    async def appels(request: Request) -> Response:
        now = kernel.mind.clock.now()
        calls = deps.calls

        def day_of(at: int) -> str:
            return datetime.fromtimestamp(at / US, deps.tz).strftime("%Y-%m-%d")

        days = calls.usage(now - 14 * DAY, by="day", day_of=day_of) if calls else []
        roles = calls.usage(now - 7 * DAY, by="role") if calls else []
        backends = calls.usage(now - 7 * DAY, by="backend") if calls else []
        recent = calls.recent(100) if calls else list(reversed(list(deps.traces)))[:100]
        return ui.page(request, "calls.html", "Appels de modèle", days=list(reversed(days)), roles=roles,
                       backends=backends, recent=[(ui.when(t.at), t) for t in recent], persisted=calls is not None)

    async def approbations(request: Request) -> Response:
        messages: list[tuple[str, str]] = []
        if request.method == "POST":
            data = await ui.form(request)
            account = ui.operator(request)
            if data is None or account is None:
                messages.append(("ko", "Jeton de formulaire invalide : recharge la page."))
            else:
                try:
                    proposal = int(data.get("proposal", "0"))
                except ValueError:
                    proposal = 0
                approved = data.get("decision") == "approve"
                status = await deps.port.resolve_effect(proposal, approved, by=account.handle,
                                                        note=data.get("note", "")[:500])
                if status == "unknown":
                    messages.append(("ko", "Action inconnue ou déjà décidée."))
                else:
                    messages.append(("ok", "Approuvé." if approved else "Refusé."))
                    if deps.after_decision is not None:
                        await deps.after_decision()
                    return RedirectResponse(PREFIX + "/approbations?fait=" + ("oui" if approved else "non"),
                                            status_code=303)
        done = request.query_params.get("fait")
        if done in ("oui", "non"):
            messages.append(("ok", "Approuvé." if done == "oui" else "Refusé."))
        frame = kernel.mind.frame()
        effects = frame.state("runtime").effects
        pending = []
        for p in frame.get(rt.PENDING_EFFECTS):
            full = effects.get(p.proposal)
            summary = kernel.mind.store.content([p.summary_ref]).get(p.summary_ref, "(oublié)") if p.summary_ref else ""
            try:
                args = json.dumps(json.loads(full.args_json), ensure_ascii=False, indent=1) if full else ""
            except ValueError:
                args = full.args_json if full else ""
            pending.append({"proposal": p.proposal, "capability": p.capability, "owner": p.owner,
                            "context": p.context, "summary": summary, "args": args, "when": ui.when(p.at)})
        seqs = [int(r[0]) for r in kernel.mind.store.query_mind(
            "SELECT seq FROM events WHERE type IN (?, ?) ORDER BY seq DESC LIMIT 40",
            (rt.EFFECT_RESOLVED.name, rt.EFFECT_EXECUTED.name))]
        history = [{"seq": e.seq, "when": ui.when(e.at), "type": e.type.name, "data": ui.show(e, 600)}
                   for e in reversed([ui.decode(s) for s in kernel.mind.store.get_events(seqs)])]
        return ui.page(request, "approvals.html", "Approbations", pending=pending, history=history,
                       messages=messages)

    async def rapports(request: Request) -> Response:
        folder = deps.reports
        files = []
        if folder is not None and folder.is_dir():
            files = sorted((f for f in folder.rglob("*") if f.is_file() and REPORT_NAME.match(f.name)),
                           key=lambda f: f.stat().st_mtime, reverse=True)[:200]
        chosen = request.query_params.get("fichier", "")
        text = ""
        if chosen:
            match = next((f for f in files if str(f.relative_to(folder)) == chosen), None) if folder else None
            text = match.read_text(encoding="utf-8", errors="replace")[:REPORT_MAX] if match else "Fichier inconnu."
        listing = [(str(f.relative_to(folder)), ui.when(int(f.stat().st_mtime * US))) for f in files] if folder else []
        return ui.page(request, "reports.html", "Simulations", folder=str(folder) if folder else "", files=listing,
                       chosen=chosen, text=text)

    return [
        Route(PREFIX + "/sante", ui.guarded(sante)),
        Route(PREFIX + "/appels", ui.guarded(appels)),
        Route(PREFIX + "/approbations", ui.guarded(approbations), methods=["GET", "POST"]),
        Route(PREFIX + "/rapports", ui.guarded(rapports)),
    ]
