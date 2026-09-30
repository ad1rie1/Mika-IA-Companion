"""Approbations : ce qu'elle voudrait faire hors de la machine. Ce qui est
montré est exactement ce qui partira : quand la capacité le sait
(``preview``), l'aperçu du résultat, et c'est cet aperçu-là qu'on approuve."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.kernel.inspect import Badge, Column, Row, Table, Text, When
from mika.runtime import decisions


def _pending(ui: Any) -> int:
    return len(ui.kernel.mind.frame().get(rt.PENDING_EFFECTS))


@TABS.tab("approbations.en_attente", title="En attente", badge=_pending)
async def pending(ui: Any, request: Request) -> Any:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    effects = frame.state("runtime").effects
    items = []
    for p in frame.get(rt.PENDING_EFFECTS):
        full = effects.get(p.proposal)
        summary = kernel.mind.store.content([p.summary_ref]).get(p.summary_ref, "(oublié)") if p.summary_ref else ""
        try:
            args = json.dumps(json.loads(full.args_json), ensure_ascii=False, indent=1) if full else ""
        except ValueError:
            args = full.args_json if full else ""
        shown = await decisions.preview(kernel.mind, kernel.ports, p.capability, full.args_json) if full else None
        items.append({"proposal": p.proposal, "capability": p.capability, "owner": p.owner, "context": p.context,
                      "summary": summary, "args": args, "when": ui.when_long(p.at),
                      "preview": shown.text if shown is not None else "",
                      "seen": shown.digest if shown is not None else "",
                      "blocked": shown.blocked if shown is not None else ""})
    ctx = ui.inspection.context(request.query_params)
    done = ctx.events([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], 40)
    history = Table((Column("quand", "fit"), "quoi", "action", "détail"), tuple(
        Row((When(e.at), Badge("décidé" if e.type.name == rt.EFFECT_RESOLVED.name else "exécuté",
                               "info" if e.type.name == rt.EFFECT_RESOLVED.name else "ok"),
             f"n° {e.data.proposal}",
             Text(_detail(e), "muted", clamp=200))) for e in done), title="Décisions et exécutions récentes",
        empty="aucune")
    done_flag = request.query_params.get("fait", "")
    messages = {"oui": [("ok", "Approuvé.")], "non": [("ok", "Refusé.")],
                "inconnu": [("warn", "Action inconnue ou déjà décidée.")],
                "change": [("warn", decisions.MESSAGES[decisions.CHANGED])],
                "bloque": [("warn", "Ça ne peut pas partir tel quel : relis-le.")],
                "jeton": [("danger", "Jeton de formulaire invalide : recharge la page.")]}.get(done_flag, [])
    return {"panel": Panel("approvals.html", {"items": items}), "blocks": [history], "messages": messages}


def _detail(e: Any) -> str:
    d = e.data
    if e.type.name == rt.EFFECT_RESOLVED.name:
        verdict = "approuvé" if d.approved else "refusé"
        return f"{verdict} par {d.by or '?'}" + (f" — {d.note}" if d.note else "")
    return ("réussi" if d.ok else "échec") + (f" — {d.result}" if d.result else "")
