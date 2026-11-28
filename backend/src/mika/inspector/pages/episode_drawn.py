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

Ses onglets disent leur compte (le gabarit de la vue d'un objet, ADR 0176) : ses paroles, ses événements, ses appels de
modèle, ses outils appelés. ``tally`` les lit une fois par page, avec le résumé (``episode_overview.summary``) que le
Résumé dessine ensuite sans le relire ; la route les pose sur la barre d'onglets, au dessin comme au repli.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.catalog import Panel
from mika.inspector.pages.episode_overview import Summary, summary
from mika.inspector.pages.journal import (
    EPISODE_TABS,
    FACT_TECHNICAL,
    episode_page,
    episode_tab,
    prompt_facts,
    reply_trigger_cell,
    trigger_cell,
)
from mika.inspector.pages.why import (
    answer_steps,
    cause_blocks,
    context_parts,
    decoded_event,
    prompt_view,
    tools_view,
    trace_of,
)
from mika.inspector.ui import PREFIX
from mika.kernel.clock import US
from mika.kernel.inspect import Ref, money_fr, num_fr, plural
from mika.runtime.boundary import Failed, call
from mika.runtime.traces import TRUNCATION_MARK

EPISODE_TEMPLATE = "handmade/episode/episode.html"
EPISODE_STYLES = ("handmade/parole.css", "handmade/episode.css")
#: au plus tant d'appels de modèle lus pour leurs sommes (coût, jetons, durée, échecs) ; leur nombre, lui, est celui
#: du registre (``Tally.calls``), et une tuile ou une note dit quand ces sommes n'en couvrent qu'une part (``_partial``)
CALLS_COUNTED = 200
#: au plus tant de paroles lues pour compter les outils qu'elles nomment, quand la trace ne les dit pas
SPEECHES_COUNTED = 200


@dataclass(frozen=True, slots=True)
class Tally:
    """Ce que comptent les onglets d'un épisode, lu une fois par page : son résumé (ses paroles, ses événements), sa
    trace (``None`` si elle n'est pas gardée), ses appels de modèle, ses outils appelés comptés comme les montre
    l'onglet Outils (``_tools``) et d'où vient ce compte (``trace`` : les appels de la trace ; ``paroles`` : les outils
    nommés sur ses paroles ; vide : ni l'une ni les autres n'en disent)."""

    said: Summary
    trace: dict[str, Any] | None
    calls: int
    tools: int
    tools_from: str

    @property
    def counts(self) -> dict[str, int]:
        """Le compte de chaque onglet qui en a un (Résumé, Prompt et Décision n'en ont pas)."""
        return {"dit": self.said.speeches, "deroule": self.said.events, "appels": self.calls, "outils": self.tools}


def tally(ui: Any, corr: str, info: Mapping[str, Any]) -> Tally:
    """Les comptes d'un épisode : le résumé (une requête groupée sur le journal), le nombre de ses appels de modèle (le
    registre durable, sinon ceux qu'on a en mémoire, comme l'onglet Appels de modèle), ses outils appelés."""
    trace = trace_of(ui, corr)
    called = [t for t in (trace or {}).get("tool_calls") or () if isinstance(t, dict)]
    if called:
        tools, source = len(called), "trace"
    else:  # l'onglet Outils montre alors les outils nommés sur ses paroles
        said = ui.inspection.context().events([rt.UTTERANCE], SPEECHES_COUNTED, correlations=[corr])
        tools = sum(len(e.data.tools) for e in said)
        source = "paroles" if tools else ""
    registry = ui.deps.calls
    if registry is not None and hasattr(registry, "for_correlation"):
        calls = int(registry.count(correlation=corr))
    else:
        calls = len([t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)])
    return Tally(said=summary(ui, corr, dict(info)), trace=trace, calls=calls, tools=tools, tools_from=source)


def episode_panel(ui: Any, corr: str, slug: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
                  replay: Panel | None = None, counted: Tally | None = None) -> Panel | None:
    """L'onglet ``slug`` d'un épisode, dessiné : son gabarit et ce qu'il dessine (``v``), inclus dans la page commune
    avec « Rejouer avec… » pour le prompt ; ``None`` si ce qu'il dessine ne se lit pas (ses blocs, alors). ``counted`` :
    ses comptes, déjà lus par la route pour la barre d'onglets (lus ici sinon)."""
    drawn = call(episode_view, ui, corr, slug, info, query, env, counted, label=f"épisode dessiné ({slug})")
    if isinstance(drawn, Failed):
        return None
    shared = {k: v for k, v in (replay.context if replay is not None else {}).items() if k != "panel_after"}
    return Panel(EPISODE_TEMPLATE, {**shared, "v": drawn}, styles=EPISODE_STYLES)


def episode_view(ui: Any, corr: str, slug: str, info: Mapping[str, Any], query: Mapping[str, str],
                 env: Any, counted: Tally | None = None) -> dict[str, Any]:
    base = f"{PREFIX}/episode/{quote(corr, safe='')}"
    shapes = {"resume": _resume, "deroule": _flow, "dit": _said, "prompt": _prompt, "outils": _tools,
              "appels": _calls, "decision": _decision}
    return {"tab": slug, "episode": corr, "href": {s: f"{base}?onglet={s}" for s, _t in EPISODE_TABS},
            **shapes[slug](ui, corr, info, query, env, counted)}


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
        asked = decoded_event(ui, int(d.reply_to))
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


def _trace(ui: Any, corr: str, counted: Tally | None) -> dict[str, Any] | None:
    """Sa trace : celle que ses comptes ont déjà lue, sinon lue ici."""
    return counted.trace if counted is not None else trace_of(ui, corr)


def _resume(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
            counted: Tally | None) -> dict[str, Any]:
    """Le résumé dessiné : ce que lit ``episode_overview.summary`` (le même que ses blocs), en tuiles et en bulles,
    plus ce que seule la page dessinée montre (ses appels de modèle, ses outils) ; ses chiffres sont ceux que disent
    les onglets (``counted``, lu une fois par la route)."""
    started = info["started"]
    counted = counted if counted is not None else tally(ui, corr, info)
    said = counted.said
    calls = _llm_calls(ui, corr, CALLS_COUNTED)
    cost = money_fr(sum(c.cost_usd for c in calls))
    # au-delà de CALLS_COUNTED, la tuile dit le nombre du registre (celui de la pastille) et son coût, d'une part
    calls_sub = ("aucun" if not calls else
                 f"{cost} pour les {num_fr(len(calls))} premiers" if _partial(counted.calls, calls) else cost)
    tools_sub = {"trace": "d'après la trace", "paroles": "nommés sur ses paroles"}.get(
        counted.tools_from, "d'après la trace" if counted.trace is not None else "trace non gardée")
    href = {s: f"{PREFIX}/episode/{quote(corr, safe='')}?onglet={s}" for s, _t in EPISODE_TABS}
    # ni sa sorte, ni à qui, ni quand : l'en-tête de la page les dit (son titre, ses faits)
    return {
        "outcome": {"text": said.outcome, "tone": said.tone}, "detail": said.detail, "open": said.open,
        "trigger": _trigger(ui, started),
        "speeches": [_speech(ui, s) for s in reversed(said.latest)], "speech_count": said.speeches,
        # « Les 3 dernières paroles sur 12. », ou toutes : « 1 parole. » (jamais « Les 1 dernières paroles »)
        "speeches_said": (f"Les {num_fr(len(said.latest))} dernières paroles sur {num_fr(said.speeches)}."
                          if len(said.latest) < said.speeches else f"{plural(said.speeches, 'parole', 'paroles')}."),
        "tiles": [
            {"label": "Durée", "value": said.duration, "sub": said.duration_said},
            {"label": "Paroles produites", "value": num_fr(said.speeches), "sub": "dans le journal",
             "href": href["dit"]},
            {"label": "Événements", "value": num_fr(said.events), "sub": "dans cet épisode", "href": href["deroule"]},
            {"label": "Appels de modèle", "value": num_fr(counted.calls), "sub": calls_sub, "href": href["appels"]},
            {"label": "Outils appelés",
             "value": num_fr(counted.tools) if counted.trace is not None or counted.tools else "—",
             "sub": tools_sub, "href": href["outils"]},
        ],
    }


def _llm_calls(ui: Any, corr: str, limit: int) -> list[Any]:
    calls = ui.deps.calls
    if calls is not None and hasattr(calls, "for_correlation"):
        return list(calls.for_correlation(corr, limit=limit))
    return [t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)][:limit]


def _partial(total: int, calls: Sequence[Any]) -> bool:
    """Les sommes lues sur ``calls`` (au plus ``CALLS_COUNTED``) ne couvrent qu'une part des ``total`` appels."""
    return bool(calls) and total > len(calls)


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


def _flow(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
          counted: Tally | None) -> dict[str, Any]:
    events, pager = episode_page(ui, corr, query)
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


def _said(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
          counted: Tally | None) -> dict[str, Any]:
    said, pager = episode_page(ui, corr, query, speeches=True)
    return {"speeches": [_speech(ui, e) for e in said], "pager": render.pager_ctx(pager, query)}


def _prompt(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
            counted: Tally | None) -> dict[str, Any]:
    trace = _trace(ui, corr, counted)
    if trace is None:
        return {"kept": False}
    latest = ui.inspection.context().events([rt.UTTERANCE], 1, correlations=[corr])
    utterance = latest[0] if latest else None
    outcome = trace.get("outcome")
    # les faits de ses blocs, en cellules : « outils offerts » se tait (la carte « Ses outils » les montre),
    # l'empreinte du préfixe se replie sous « Détails techniques »
    facts = prompt_facts(ui, trace, info["started"] or info["ended"])
    texts = [str(trace.get("system_stable") or ""), *(str(m.get("content", "")) for m in trace.get("messages") or ()
                                                     if isinstance(m, dict))]
    return {
        "kept": True, "truncated": bool(trace.get("truncated")) or any(TRUNCATION_MARK in t for t in texts),
        "facts": [{"label": f.label, "cell": render.cell(f.value, env)} for f in facts if not f.place],
        "technical": [{"label": f.label, "cell": render.cell(f.value, env)} for f in facts
                      if f.place == FACT_TECHNICAL],
        "prompt": prompt_view(ui, trace), "context": [{"title": t, "text": x} for t, x in context_parts(trace)],
        "tools": tools_view(trace, utterance.data.tools if utterance is not None else ()),
        "steps": answer_steps(trace, utterance),
        "unsaid": outcome not in ("done", "abstained") and bool(trace.get("reply")),
    }


def _tools(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
           counted: Tally | None) -> dict[str, Any]:
    trace = _trace(ui, corr, counted)
    calls = [t for t in (trace or {}).get("tool_calls") or () if isinstance(t, dict)]
    if calls:
        return {"kept": True, "calls": [
            {"name": str(t.get("name", "?")), "ok": bool(t.get("ok")), "executed": t.get("executed", True),
             "ms": num_fr(int(t.get("duration_us") or 0) / 1000, 0), "args": _pretty(t.get("args", "")),
             "result": str(t.get("result", ""))} for t in calls]}
    said, _pager = episode_page(ui, corr, query, speeches=True)
    return {"kept": bool(trace), "calls": [], "named": [
        {"why": render.href(Ref.why(e.seq)), "number": e.seq, "tools": [{"name": t.name, "ok": t.ok}
                                                                          for t in e.data.tools]}
        for e in said if e.data.tools]}


def _pretty(raw: Any) -> str:
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=1) if isinstance(raw, str) else str(raw)
    except ValueError:
        return str(raw)


def _calls(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
           counted: Tally | None) -> dict[str, Any]:
    calls = _llm_calls(ui, corr, CALLS_COUNTED)
    failed = [c for c in calls if c.outcome != "ok"]
    total = counted.calls if counted is not None else len(calls)
    return {
        # la tuile Appels dit leur nombre (celui de la pastille) ; les autres sommes, celles des appels lus
        "partial": (f"Échecs, jetons, coût et durée : les {num_fr(len(calls))} premiers appels sur {num_fr(total)}. "
                    "Le tableau les montre tous." if _partial(total, calls) else ""),
        "tiles": [
            {"label": "Appels", "value": num_fr(total),
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


def _decision(ui: Any, corr: str, info: Mapping[str, Any], query: Mapping[str, str], env: Any,
              counted: Tally | None) -> dict[str, Any]:
    started, ended = info["started"], info["ended"]
    if started is None:
        return {"facts": [], "cause": [], "missing": True}
    d = started.data
    facts = [("sorte", info["kind"]), ("vers", ui.names.who(d.target)),
             ("raison", ", ".join(ui.names.reason("", r) for r in str(d.reason or "").split(",") if r) or "—"),
             ("objet", d.subject or "—")]
    # une réponse : la carte « Ce qui l'a lancé » montre déjà le message, et son lien ; « En bref » ne dit que ce que
    # son déclencheur y ajoute (une reprise)
    said = reply_trigger_cell(d.trigger) if d.reply_to else trigger_cell(d.trigger)
    if said is not None:
        facts.append(("déclencheur", said))
    guard = (f"Supplanté par la garde « {ended.data.guard} » : a changé {', '.join(ended.data.changed)}."
             if ended is not None and ended.data.guard else "")
    return {"facts": [{"label": k, "cell": render.cell(v, env)} for k, v in facts], "guard": guard,
            "trigger": _trigger(ui, started),
            "cause": _drawn(cause_blocks(ui, started), env, query) if not d.reply_to else [], "missing": False}
