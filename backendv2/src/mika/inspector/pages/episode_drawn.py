"""La page d'un épisode, dessinée (ADR 0121) : un gabarit, une forme par onglet (``handmade/episode/episode.html``).

- **Résumé** : son issue en grand, ce qui l'a déclenché (le message en bulle, ou l'arbitre), ses dernières paroles,
  ses chiffres (durée, paroles, événements, appels et leur coût, outils) ;
- **Déroulé** : ses événements sur un fil, l'heure, le nom en mots, un extrait, le lien ;
- **Ce qu'elle a dit** : ses paroles en bulles, à qui, quand, visibles ou non, sa voix, ses outils, ses sections ;
- **Prompt** : ce qui a décidé du prompt, ses sections dépliables sur leur texte, le contexte complet, ses outils en main,
  sa réponse pas à pas (le modèle principal, la relecture, l'autrice) ;
- **Outils** : chaque appel en carte, ses arguments et son résultat ;
- **Appels de modèle** : leurs totaux, puis leur tableau ;
- **Décision** : ce qui l'a lancé, en mots, et le calcul de l'arbitre.

Les données sont celles des onglets en blocs (``journal.episode_tab``), qui restent le repli : un dessin qui échoue
rend la main aux blocs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select

from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.catalog import Panel
from mika.inspector.pages.episode_overview import PREVIEW_SPEECHES
from mika.inspector.pages.journal import EPISODE_TABS, _events, episode_tab
from mika.inspector.pages.why import (
    _decoded,
    answer_steps,
    cause_blocks,
    context_parts,
    prompt_view,
    tools_view,
    trace_of,
)
from mika.inspector.ui import PREFIX
from mika.kernel.clock import US
from mika.kernel.forms import show_duration
from mika.kernel.inspect import Ref, money_fr, num_fr
from mika.ports.journal import JournalEvent
from mika.runtime.boundary import Failed, call
from mika.runtime.traces import TRUNCATION_MARK

EPISODE_TEMPLATE = "handmade/episode/episode.html"
EPISODE_STYLES = ("handmade/parole.css", "handmade/episode.css")
#: au plus tant d'appels de modèle comptés dans le résumé
CALLS_COUNTED = 200


def episode_panel(ui: Any, corr: str, slug: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
                  replay: Panel | None = None) -> Panel | None:
    """L'onglet ``slug`` d'un épisode, dessiné : son gabarit et ce qu'il dessine (``v``), inclus dans la page commune
    avec « Rejouer avec… » pour le prompt ; ``None`` si ce qu'il dessine ne se lit pas (ses blocs, alors)."""
    drawn = call(episode_view, ui, corr, slug, info, query, env, label=f"épisode dessiné ({slug})")
    if isinstance(drawn, Failed):
        return None
    shared = {k: v for k, v in (replay.context if replay is not None else {}).items() if k != "panel_after"}
    return Panel(EPISODE_TEMPLATE, {**shared, "v": drawn}, styles=EPISODE_STYLES)


def episode_view(ui: Any, corr: str, slug: str, info: Mapping[str, Any], query: Mapping[str, str],
                 env: Any) -> dict[str, Any]:
    base = f"{PREFIX}/episode/{quote(corr, safe='')}"
    shapes = {"resume": _resume, "deroule": _flow, "dit": _said, "prompt": _prompt, "outils": _tools,
              "appels": _calls, "decision": _decision}
    return {"tab": slug, "episode": corr, "href": {s: f"{base}?onglet={s}" for s, _t in EPISODE_TABS},
            **shapes[slug](ui, corr, info, query, env)}


def _drawn(items: Sequence[Any], env: Any, query: Mapping[str, str]) -> list[dict[str, Any]]:
    return render.blocks(list(items), env, query, namespace="episode")


def _hms(ui: Any, at: int) -> str:
    return datetime.fromtimestamp(at / US, ui.tz).strftime("%H:%M:%S")


def _text(e: Any) -> str:
    """Le texte d'un événement qui en porte un (une parole, un message) ; vide sinon."""
    content = getattr(getattr(e, "data", None), "text", None)
    return str(getattr(content, "text", "") or "") if content is not None else ""


def _trigger(ui: Any, started: Any | None) -> dict[str, Any]:
    """Ce qui l'a déclenché, en mots : le message auquel elle répondait (en bulle), l'arbitre, ou autre chose."""
    if started is None:
        return {"note": "Le début de cet épisode n'est pas au journal : son déclencheur ne peut pas être retrouvé.",
                "tone": "warn"}
    d = started.data
    if d.reply_to:
        asked = _decoded(ui, int(d.reply_to))
        return {"who": ui.names.who((getattr(asked.data, "handle", None) if asked is not None else None) or d.target),
                "text": (_text(asked) if asked is not None else "") or "Le texte de ce message n'est plus disponible.",
                "when": ui.when_long(asked.at) if asked is not None else "",
                "href": render.href(Ref("event", str(d.reply_to), "")), "number": d.reply_to}
    if d.selected or str(d.trigger).startswith(("selected:", "prélude:")):
        return {"note": "Elle a démarré cet épisode d'elle-même, à la suite d'un choix de l'arbitre.", "tone": "info"}
    reason = ", ".join(ui.names.reason("", r) for r in str(d.reason or "").split(",") if r)
    return {"note": f"Déclenché autrement (« {d.trigger or '—'} »)" + (f" : {reason}." if reason else "."),
            "tone": "muted"}


def _speech(ui: Any, e: Any) -> dict[str, Any]:
    d = e.data
    return {"text": _text(e) or "(oublié)", "to": ui.names.who(d.target), "when": ui.when_long(e.at),
            "visible": d.visible, "why": render.href(Ref.why(e.seq)),
            "voice": f"{names.role(d.voice.role)} · {d.voice.model or '—'}",
            "tools": [{"name": t.name, "ok": t.ok} for t in d.tools],
            "sections": [ui.names.section(k) for k in d.sections]}


def _resume(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    started, ended = info["started"], info["ended"]
    e = JournalEvent
    counts = dict(ui.kernel.mind.store.query_mind(
        select(e.type, func.count()).where(e.correlation == corr).group_by(e.type)))
    speeches = counts.get(rt.UTTERANCE.name, 0)
    label, tone = names.outcome(ended.data.outcome, ended.data.kind) if ended else ("ouvert", "warn")
    detail = names.detail(ended.data.detail or ended.data.guard) if ended else (
        "Aucune fin n’est enregistrée : il peut être encore en cours, ou avoir été coupé.")
    if started and ended:
        span = max(0, ended.at - started.at)
        duration = "< 1 s" if span < US else show_duration(span)
    else:
        duration = "—"
    calls = _llm_calls(ui, corr, CALLS_COUNTED)
    trace = trace_of(ui, corr)
    tool_calls = len([t for t in (trace or {}).get("tool_calls") or () if isinstance(t, dict)])
    latest = ui.inspection.context().events([rt.UTTERANCE], PREVIEW_SPEECHES, correlations=[corr])
    href = {s: f"{PREFIX}/episode/{quote(corr, safe='')}?onglet={s}" for s, _t in EPISODE_TABS}
    return {
        "kind": info["kind"], "outcome": {"text": label, "tone": tone}, "detail": detail,
        "to": ui.names.who((started.data.target if started else None) or (ended.data.target if ended else None)),
        "began": ui.when_long(started.at) if started else "", "open": ended is None,
        "trigger": _trigger(ui, started),
        "speeches": [_speech(ui, s) for s in reversed(latest)], "speech_count": speeches,
        "tiles": [
            {"label": "Durée", "value": duration, "sub": "du début à la fin" if started and ended else "fin ou début absent"},
            {"label": "Paroles produites", "value": num_fr(speeches), "sub": "dans le journal", "href": href["dit"]},
            {"label": "Événements", "value": num_fr(sum(counts.values())), "sub": "dans cet épisode",
             "href": href["deroule"]},
            {"label": "Appels de modèle", "value": num_fr(len(calls)),
             "sub": money_fr(sum(c.cost_usd for c in calls)) if calls else "aucun", "href": href["appels"]},
            {"label": "Outils appelés", "value": num_fr(tool_calls) if trace else "—",
             "sub": "d'après la trace" if trace else "trace non gardée", "href": href["outils"]},
        ],
    }


def _llm_calls(ui: Any, corr: str, limit: int) -> list[Any]:
    calls = ui.deps.calls
    if calls is not None and hasattr(calls, "for_correlation"):
        return list(calls.for_correlation(corr, limit=limit))
    return [t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)][:limit]


def _tone(e: Any) -> str:
    """Le ton d'un événement sur le fil (``now-feed``) : ce qu'elle dit, ce qu'on lui dit, la fin, le reste."""
    name = e.type.name
    if name == rt.UTTERANCE.name:
        return "accent"
    if name == rt.PERCEPTION_RECEIVED.name:
        return ""
    if name == rt.EPISODE_ENDED.name:
        return {"done": "ok", "failed": "danger", "timeout": "danger"}.get(str(e.data.outcome), "muted")
    return "muted"


def _flow(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    events, pager = _events(ui, corr, query)
    return {"events": [{"time": _hms(ui, e.at), "label": ui.names.event(e.type.name), "type": e.type.name,
                        "href": render.href(Ref("event", str(e.seq), "")), "number": e.seq, "tone": _tone(e),
                        "excerpt": (_text(e) or _ending(e))[:280],
                        "why": render.href(Ref.why(e.seq)) if e.type.name == rt.UTTERANCE.name else ""}
                       for e in events],
            "pager": render.pager_ctx(pager, query)}


def _ending(e: Any) -> str:
    """Ce que dit une fin d'épisode sur le fil : son détail en mots, ou ce qui l'a supplantée."""
    if e.type.name != rt.EPISODE_ENDED.name:
        return ""
    return names.detail(e.data.detail or e.data.guard or "")


def _said(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    said, pager = _events(ui, corr, query, speeches=True)
    return {"speeches": [_speech(ui, e) for e in said], "pager": render.pager_ctx(pager, query)}


def _prompt(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    trace = trace_of(ui, corr)
    if trace is None:
        return {"kept": False}
    latest = ui.inspection.context().events([rt.UTTERANCE], 1, correlations=[corr])
    utterance = latest[0] if latest else None
    audience = (trace.get("audience") or {}).get("level", "—")
    outcome = trace.get("outcome")
    texts = [str(trace.get("system_stable") or ""), *(str(m.get("content", "")) for m in trace.get("messages") or ()
                                                     if isinstance(m, dict))]
    return {
        "kept": True, "truncated": bool(trace.get("truncated")) or any(TRUNCATION_MARK in t for t in texts),
        "facts": [("rôle", names.role(trace.get("role"))), ("déclencheur", str(trace.get("trigger") or "—")),
                  ("audience", str(audience)),
                  ("enrichissements", ", ".join(trace.get("enrichments") or ()) or "aucun"),
                  ("empreinte du préfixe", str(trace.get("system_stable_hash") or "—")[:16]),
                  ("issue", names.outcome(outcome)[0] if outcome != "running" else "en cours")],
        "prompt": prompt_view(ui, trace), "context": [{"title": t, "text": x} for t, x in context_parts(trace)],
        "tools": tools_view(trace, utterance.data.tools if utterance is not None else ()),
        "steps": answer_steps(trace, utterance),
        "unsaid": outcome not in ("done", "abstained") and bool(trace.get("reply")),
    }


def _tools(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    trace = trace_of(ui, corr)
    calls = [t for t in (trace or {}).get("tool_calls") or () if isinstance(t, dict)]
    if calls:
        return {"kept": True, "calls": [
            {"name": str(t.get("name", "?")), "ok": bool(t.get("ok")), "executed": t.get("executed", True),
             "ms": num_fr(int(t.get("duration_us") or 0) / 1000, 0), "args": _pretty(t.get("args", "")),
             "result": str(t.get("result", ""))} for t in calls]}
    said, _pager = _events(ui, corr, query, speeches=True)
    return {"kept": bool(trace), "calls": [], "named": [
        {"why": render.href(Ref.why(e.seq)), "number": e.seq, "tools": [{"name": t.name, "ok": t.ok}
                                                                          for t in e.data.tools]}
        for e in said if e.data.tools]}


def _pretty(raw: Any) -> str:
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=1) if isinstance(raw, str) else str(raw)
    except ValueError:
        return str(raw)


def _calls(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    calls = _llm_calls(ui, corr, CALLS_COUNTED)
    failed = [c for c in calls if c.outcome != "ok"]
    return {
        "tiles": [
            {"label": "Appels", "value": num_fr(len(calls)),
             "sub": f"{len(failed)} en échec" if failed else "tous réussis" if calls else "aucun",
             "tone": "danger" if failed else ""},
            {"label": "Jetons", "value": f"{num_fr(sum(c.input_tokens for c in calls))} → "
                                         f"{num_fr(sum(c.output_tokens for c in calls))}",
             "sub": f"cache lu : {num_fr(sum(c.cache_read for c in calls))}"},
            {"label": "Coût", "value": money_fr(sum(c.cost_usd for c in calls)), "sub": "estimé"},
            {"label": "Durée", "value": f"{num_fr(sum(c.latency_us for c in calls) / 1e6, 1)} s",
             "sub": f"dont {num_fr(sum(c.wait_us for c in calls) / 1e6, 1)} s d'attente"},
        ] if calls else [],
        "table": _drawn(episode_tab(ui, corr, "appels", dict(info), query), env, query),
    }


def _decision(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any) -> dict[str, Any]:
    started, ended = info["started"], info["ended"]
    if started is None:
        return {"facts": [], "cause": [], "missing": True}
    d = started.data
    facts = [("sorte", info["kind"]), ("vers", ui.names.who(d.target)),
             ("raison", ", ".join(ui.names.reason("", r) for r in str(d.reason or "").split(",") if r) or "—"),
             ("objet", d.subject or "—"), ("déclencheur", str(d.trigger or "—"))]
    if d.reply_to:
        facts.append(("en réponse à", f"message n° {d.reply_to}"))
    guard = (f"Supplanté par la garde « {ended.data.guard} » : a changé {', '.join(ended.data.changed)}."
             if ended is not None and ended.data.guard else "")
    return {"facts": facts, "guard": guard, "trigger": _trigger(ui, started),
            "cause": _drawn(cause_blocks(ui, started), env, query) if not d.reply_to else [], "missing": False}
