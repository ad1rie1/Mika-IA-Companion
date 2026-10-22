"""Activité › En cours, dessinée (ADR 0121) : ce qu'elle fait maintenant, ce qui attend, ce qu'elle vient de faire.

D'abord une phrase (elle répond à Adrien depuis 12 s ; ou rien, et depuis quand). Puis ses épisodes ouverts et ce qui
tourne en arrière-plan ; ce qui attend (les voies, les questions sans réponse, les actions à autoriser, les ressources
réservées) ; ses derniers épisodes, chacun vers sa page. Lu au noyau, comme l'onglet de la console (``decisions.en_cours``),
qui reste la source pour la console en MCP et le repli.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, span
from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import Ref
from mika.vocab.episodes import Kind

#: ce qu'elle fait, dit par un verbe (« elle répond à Adrien »)
DOING = {Kind.REPLY: "répond à", Kind.INITIATIVE: "écrit d'elle-même à", Kind.STEP: "avance sur",
         Kind.MURMUR: "murmure à", Kind.JOURNAL: "écrit son journal", Kind.DREAM: "rêve",
         Kind.NARRATIVE: "relit son récit", Kind.TASK: "prépare en silence", Kind.WORK: "travaille sur",
         Kind.JOB: "exécute", Kind.WAKE: "répond à un réveil", Kind.WAKE_JOB: "exécute un réveil"}
#: au-delà, un épisode ouvert dure plus longtemps que d'habitude
LONG = 120 * US
#: les derniers épisodes montrés
RECENT = 8


def _ref(kind: str, key: str) -> Ref:
    return Ref(kind, key, "")


def _who(ui: UI, shown: render.Env, target: str | None) -> dict[str, Any] | None:
    if not target or target in ("none", "any"):
        return None
    return render.cell(ui.names.who_cell(target), shown)


def running(ui: UI, items: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """Activité › En cours : ce qu'elle fait, ce qui attend, ce qu'elle vient de faire."""
    look = Look.of(ui, DAY)
    shown = render.Env(when=ui.when, now=look.now)
    kernel, frame, now = ui.kernel, look.frame, look.now
    state = frame.state("runtime")
    doing = []
    for corr, o in sorted(state.open.items(), key=lambda kv: kv[1].started_at):
        late = now - o.started_at > LONG
        doing.append({"verb": DOING.get(o.kind, names.kind(o.kind)), "kind": names.kind(o.kind),
                      "who": _who(ui, shown, o.target), "since": span(max(0, now - o.started_at)),
                      "late": late, "href": render.href(_ref("episode", corr)),
                      "reply": render.href(_ref("event", str(o.reply_to))) if o.reply_to else "",
                      "reply_n": o.reply_to})
    processes = [ui.names.process(p) for p in sorted(kernel.scheduler.running())]
    lanes = kernel.lanes
    ways = [{"name": names.lane(lane), "busy": lanes.busy(lane), "cap": cap, "waiting": lanes.pending(lane)}
            for lane, cap in lanes.capacities.items()]
    questions = [{"who": _who(ui, shown, q.handle), "since": look.ago(q.at), "attempts": q.attempts,
                  "room": q.room or "", "href": render.href(_ref("event", str(seq)))}
                 for seq, q in sorted(state.pending.items(), key=lambda kv: kv[1].at)]
    leases = [{"what": ui.names.resource(res), "until": ui.when(lease.until),
               "href": render.href(_ref("episode", lease.holder))}
              for res, lease in sorted(frame.root.slices["kernel"].leases.items())]
    ended = ui.inspection.context().events([rt.EPISODE_ENDED], RECENT)
    recent = []
    for e in ended:
        word, tone = names.outcome(e.data.outcome, e.data.kind)
        recent.append({"kind": names.kind(e.data.kind), "who": _who(ui, shown, e.data.target), "outcome": word,
                       "tone": tone, "ago": look.ago(e.at), "when": ui.when(e.at),
                       "detail": names.detail(e.data.detail or e.data.guard or "")[:200],
                       "href": render.href(_ref("episode", e.correlation))})
    last = ended[0] if ended else None
    return Markup(env.get_template("handmade/decisions/en_cours.html").render(
        doing=doing, processes=processes, ways=ways, questions=questions, leases=leases,
        approvals=len(state.effects), recent=recent, stamp=ui.when_long(now),
        idle_since=look.ago(last.at) if last is not None else "", idle_last=recent[0] if recent else None))
