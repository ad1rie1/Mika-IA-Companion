"""Approbations : ce qu'elle voudrait faire hors de la machine. Ce qui est
montré est exactement ce qui partira : quand la capacité le sait
(``preview``), l'aperçu du résultat, et c'est cet aperçu-là qu'on approuve."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.kernel.inspect import Badge, Column, Ref, Row, Table, Text, When, paginate
from mika.runtime import decisions


def _pending(ui: Any) -> int:
    return len(ui.kernel.mind.frame().get(rt.PENDING_EFFECTS))


@TABS.tab("approbations.en_attente", title="En attente", badge=_pending,
          description="Ce qui attend ton accord. Ce qui est montré est exactement ce qui partira.")
async def pending(ui: Any, request: Request) -> Any:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    effects = frame.state("runtime").effects
    items = []
    ctx = ui.inspection.context(request.query_params)
    page, pager = paginate(frame.get(rt.PENDING_EFFECTS), ctx.pager(size=20))
    for p in page:
        full = effects.get(p.proposal)
        summary = kernel.mind.store.content([p.summary_ref]).get(p.summary_ref, "(oublié)") if p.summary_ref else ""
        try:
            args = json.dumps(json.loads(full.args_json), ensure_ascii=False, indent=1) if full else ""
        except ValueError:
            args = full.args_json if full else ""
        shown = await decisions.preview(kernel.mind, kernel.ports, p.capability, full.args_json) if full else None
        items.append({"proposal": p.proposal, "capability": ui.names.capability(p.capability),
                      "capability_key": p.capability, "owner": p.owner,
                      "context": f"à propos de {ui.names.who(p.context)}" if p.context else "",
                      "summary": summary, "args": args, "when": ui.when_long(p.at),
                      "preview": shown.text if shown is not None else "",
                      "seen": shown.digest if shown is not None else "",
                      "blocked": shown.blocked if shown is not None else ""})
    done_flag = request.query_params.get("fait", "")
    messages = {"oui": [("ok", "Approuvé.")], "non": [("ok", "Refusé.")],
                "inconnu": [("warn", "Action inconnue ou déjà décidée.")],
                "change": [("warn", decisions.MESSAGES[decisions.CHANGED])],
                "bloque": [("warn", "Ça ne peut pas partir tel quel : relis-le.")],
                "jeton": [("danger", "Jeton de formulaire invalide : recharge la page.")]}.get(done_flag, [])
    return {"panel": Panel("approvals.html", {"items": items, "pending_pager": render._pager(pager, request.query_params)}),
            "blocks": [], "messages": messages}


#: l'historique, par page
HISTORY_PAGE = 30


@TABS.tab("approbations.historique", title="Historique",
          description="Chaque décision (approuvé, refusé, par qui) et chaque exécution (réussie ou non), avec la "
                      "capacité concernée.")
async def history(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    done, pager = ctx.older([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], HISTORY_PAGE)
    # la capacité d'une exécution se lit sur sa décision
    proposals = {e.data.proposal for e in done if e.type.name == rt.EFFECT_EXECUTED.name}
    resolved = {p: found[0].data for p in proposals
                if (found := ctx.events([rt.EFFECT_RESOLVED], 1, where=("proposal", p)))}
    rows = []
    for e in done:
        is_decision = e.type.name == rt.EFFECT_RESOLVED.name
        capability = e.data.capability if is_decision else getattr(resolved.get(e.data.proposal), "capability", "")
        tone = "" if is_decision and e.data.approved else "muted" if is_decision else \
            ("ok" if e.data.ok else "danger")
        rows.append(Row((When(e.at), Badge("décidé" if is_decision else "exécuté", "info" if is_decision else "ok"),
                         Text(ui.names.capability(capability) if capability else "—", hint=capability),
                         Ref("event", str(e.data.proposal), f"n° {e.data.proposal}"),
                         Text(_detail(ui, e), "muted", clamp=200), Text(capability or "—", "mono")),
                        href=Ref("event", str(e.seq), ""), tone=tone))
    return [Table((Column("quand", "fit"), Column("quoi", "fit"), "capacité", Column("proposition", "fit"),
                   "détail", Column("capacité (clé)", detail=True)), tuple(rows), title="Décisions et exécutions",
                  empty="Rien n'a encore été décidé.", pager=pager)]


def _detail(ui: Any, e: Any) -> str:
    d = e.data
    if e.type.name == rt.EFFECT_RESOLVED.name:
        verdict = "approuvé" if d.approved else "refusé"
        return f"{verdict} par {ui.names.who(d.by) if d.by else '?'}" + (f" — {note}" if (note := d.said()) else "")
    return ("réussi" if d.ok else "échec") + (f" — {names.detail(d.result)}" if d.result else "")
