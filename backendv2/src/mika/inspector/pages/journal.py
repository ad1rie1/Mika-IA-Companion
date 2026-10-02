"""Le journal vu de près : un épisode (ce qui l'a déclenché, ce qu'elle a vu, dit
et fait) et un événement (ce qui l'a produit, qui le lit, ce qu'il a déclenché).
Pour une parole précise, « Pourquoi a-t-elle dit ça ? » (``why.py``) rassemble
tout en mots."""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.pages.decisions import selection_detail, waterfall
from mika.inspector.pages.home import outcome_badge
from mika.inspector.pages.why import episode_events, prompt_blocks, selection_of, tools_blocks, trace_of
from mika.kernel.inspect import (
    Badge,
    Code,
    Column,
    Fields,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
    money_fr,
    num_fr,
)

EPISODE_TABS = (("deroule", "Déroulé"), ("dit", "Ce qu'elle a dit"), ("prompt", "Prompt"), ("outils", "Outils"),
                ("appels", "Appels de modèle"), ("decision", "Décision"))
_PROVENANCE = ("memory:", "event:", "goal:", "thought:")
#: une page d'événements d'épisode
EPISODE_PAGE = 25


def _events(ui: Any, corr: str, query=None, *, speeches: bool = False) -> tuple[list[Any], Pager]:
    request = ui.inspection.context(query).pager(size=EPISODE_PAGE)
    clause, args = ("correlation=? AND type=?", (corr, rt.UTTERANCE.name)) if speeches else ("correlation=?", (corr,))
    total = int(ui.kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM events WHERE {clause}", args)[0][0])
    pager = Pager(number=min(request.number, max(1, (total + EPISODE_PAGE - 1) // EPISODE_PAGE)), size=EPISODE_PAGE,
                  total=total)
    seqs = [int(r[0]) for r in ui.kernel.mind.store.query_mind(
        f"SELECT seq FROM events WHERE {clause} ORDER BY seq LIMIT ? OFFSET ?", (*args, pager.size, pager.offset))]
    return [ui.decode(s) for s in ui.kernel.mind.store.get_events(seqs)], pager


def _provenance(ref: str) -> Any:
    head, _, tail = ref.partition(":")
    if f"{head}:" in _PROVENANCE and tail.isdigit():
        return Ref("event", tail, ref)
    return ref


def is_episode(ui: Any, corr: str) -> bool:
    """Une corrélation d'épisode (un début ou une fin au journal) — pas une action d'opérateur, un effet,
    un processus : ceux-là n'ont pas de page d'épisode."""
    return bool(ui.kernel.mind.store.query_mind(
        "SELECT 1 FROM events WHERE correlation=? AND type IN (?, ?) LIMIT 1",
        (corr, rt.EPISODE_STARTED.name, rt.EPISODE_ENDED.name)))


def episode_head(ui: Any, corr: str) -> dict[str, Any] | None:
    if not is_episode(ui, corr):
        return None
    started, ended = episode_events(ui, corr)
    kind = started.data.kind if started else (ended.data.kind if ended else "")
    badges = []
    if ended:
        b = outcome_badge(ended.data.outcome, ended.data.kind)
        badges.append({"text": b.text, "tone": b.tone})
    else:
        badges.append({"text": "en cours (ou coupé par un arrêt)", "tone": "warn"})
    target = (started.data.target if started else None) or (ended.data.target if ended else None)
    facts = [{"label": "vers", "value": ui.names.who(target)},
             {"label": "début", "value": ui.when_long(started.at) if started else "—"}]
    if started and started.data.reason:
        facts.append({"label": "raison", "value": ", ".join(
            ui.names.reason("", r) for r in str(started.data.reason).split(",") if r)})
    return {"started": started, "ended": ended, "kind": names.kind(kind or "épisode"),
            "badges": badges, "facts": facts}


def episode_tab(ui: Any, corr: str, tab: str, info: dict[str, Any], query=None) -> list[Any]:
    started, ended = info["started"], info["ended"]
    if tab == "dit":
        said, pager = _events(ui, corr, query, speeches=True)
        if not said:
            return [Note("Elle n'a rien dit dans cet épisode.", "muted")]
        rows = []
        for u in said:
            d = u.data
            out = [Prose(d.text.text or "(oublié)", "Parole complète", reading=True),
                   Fields((("pourquoi", Ref.why(u.seq, "Pourquoi a-t-elle dit ça ?")),
                           ("ce que le prompt lui montrait", Text(" · ".join(
                               ui.names.section(k) for k in d.sections) or "—", "muted")),
                           ("outils", ", ".join(f"{t.name}{'' if t.ok else ' (échec)'}" for t in d.tools) or "aucun"),
                           ("voix", f"{names.role(d.voice.role)} · {d.voice.model or '—'}")))]
            links = [p for p in (_provenance(x) for x in d.provenance) if isinstance(p, Ref)]
            if links:
                out.append(Table(("source",), tuple((p,) for p in links), title="Ce qui l'a nourrie"))
            rows.append(Row((When(u.at), ui.names.who_cell(d.target), Text(d.text.text or "(oublié)", clamp=400),
                             "visible" if d.visible else "pas dans le fil"), href=Ref.why(u.seq), detail=tuple(out)))
        return [Table(("Quand", "À", "Parole", "Visibilité"), tuple(rows), title="Paroles de l'épisode", pager=pager,
                      caption="Chaque parole mène à « Pourquoi a-t-elle dit ça ? ».")]
    if tab == "prompt":
        trace = trace_of(ui, corr)
        if trace is None:
            return [Note("Le prompt de cet épisode n'a pas été gardé (plus de 14 jours, oubli, ou épisode antérieur "
                         "à la console).", "muted")]
        out: list[Any] = []
        if trace.get("truncated"):
            out.append(Note("Cette trace a été tronquée (un texte trop long) : ce qui est montré est incomplet.",
                            "warn"))
        out += prompt_blocks(ui, trace, ())
        audience = (trace.get("audience") or {}).get("level", "—")
        facts = [("rôle", names.role(trace.get("role"))),
                 ("déclencheur", Text(str(trace.get("trigger") or "—"), "mono")),
                 ("audience", str(audience)),
                 ("outils offerts", ", ".join(trace.get("tools") or ()) or "aucun"),
                 ("enrichissements", ", ".join(trace.get("enrichments") or ()) or "aucun"),
                 ("empreinte du préfixe", Text(str(trace.get("system_stable_hash") or "—")[:16], "mono",
                                               hint="la même d'un épisode à l'autre : le cache sert")),
                 ("issue", names.outcome(trace.get("outcome"))[0] if trace.get("outcome") != "running" else "en cours")]
        out.append(Fields(tuple(facts)))
        if trace.get("system_stable"):
            out.append(Prose(trace["system_stable"], "La partie stable (persona, en cache)", clamp=1200))
        if trace.get("system_volatile"):
            out.append(Prose(trace["system_volatile"], "La partie volatile", clamp=1200))
        for m in trace.get("messages") or ():
            role = m.get("role", "?") if isinstance(m, dict) else "?"
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            out.append(Prose(str(content), {"user": "Tour (entrée)", "assistant": "Tour (elle)",
                                            "tool": "Résultat d'outil"}.get(role, role), clamp=1500))
        if trace.get("reply"):
            said = trace.get("outcome") in ("done", "abstained")
            out.append(Prose(str(trace["reply"]), "Ce que le modèle a répondu" if said
                             else "Ce qu'elle allait dire (jamais livré)", clamp=1500))
        return out
    if tab == "outils":
        trace = trace_of(ui, corr)
        if (trace or {}).get("tool_calls"):
            return tools_blocks(ui, trace, None)
        said, pager = _events(ui, corr, query, speeches=True)
        if not said:
            return [Note("Aucun outil retrouvé pour cet épisode.", "muted")]
        return [Table(("Parole", "Outils utilisés"), tuple(Row((Ref.why(e.seq, f"parole n° {e.seq}"),
                    ", ".join(t.name for t in e.data.tools) or "aucun"), detail=tuple(tools_blocks(ui, None, e)))
                    for e in said), title="Outils par parole", pager=pager),
                Note("La trace détaillée n'a pas été gardée. Les outils restent consultables par parole.", "muted")]
    if tab == "appels":
        calls = ui.deps.calls
        pager = None
        if calls is not None and hasattr(calls, "for_correlation"):
            total = calls.count(correlation=corr)
            request = ui.inspection.context(query).pager(size=EPISODE_PAGE)
            pager = Pager(number=min(request.number, max(1, (total + EPISODE_PAGE - 1) // EPISODE_PAGE)),
                          size=EPISODE_PAGE, total=total)
            traces = calls.for_correlation(corr, limit=pager.size, offset=pager.offset)
        else:
            traces = [t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)]
        if not traces:
            return [Note("Aucun appel de modèle retrouvé pour cet épisode.", "muted")]
        return [Table(("rôle", "fournisseur", "modèle", Column("attente", "num"), Column("durée", "num"),
                       Column("jetons", "num"), Column("cache lu", "num"), Column("coût", "num"), "issue"), tuple(
            (names.role(t.role), t.backend, Text(t.model, "mono"), f"{num_fr(t.wait_us / 1e6, 1)} s",
             f"{num_fr(t.latency_us / 1e6, 1)} s", f"{num_fr(t.input_tokens)} → {num_fr(t.output_tokens)}",
             num_fr(t.cache_read), money_fr(t.cost_usd),
             names_outcome_call(t.outcome)) for t in traces), pager=pager)]
    if tab == "decision":
        return decision_blocks(ui, started, ended, info)
    events, pager = _events(ui, corr, query)
    rows = tuple(Row((When(e.at), Text(ui.names.event(e.type.name), hint=e.type.name),
                      Ref.why(e.seq, "pourquoi ?") if e.type.name == rt.UTTERANCE.name else "",
                      Ref("event", str(e.seq), f"n° {e.seq}"), Text(e.type.name, "mono")),
                     detail=(Code(ui.show(e, 4000), "Données"),)) for e in events)
    return [Table((Column("quand", "fit"), "ce qui s'est passé", Column("", "fit"), Column("événement", detail=True),
                   Column("type", detail=True)), rows, title="Déroulé", pager=pager)]


def names_outcome_call(outcome: str) -> Badge:
    """L'issue d'un appel de modèle, en mots."""
    return Badge("réussi" if outcome == "ok" else names.detail(outcome), "ok" if outcome == "ok" else "danger")


def decision_blocks(ui: Any, started: Any, ended: Any, info: dict[str, Any]) -> list[Any]:
    """L'onglet « Décision » : le déclencheur, et — pour un épisode lancé par l'arbitre — **le** choix qui
    l'a lancé (le numéro exact s'il est au journal), sa ligne pas à pas et les autres lignes."""
    if started is None:
        return [Note("Début d'épisode introuvable.", "muted")]
    d = started.data
    out: list[Any] = [Fields((("sorte", info["kind"]), ("vers", ui.names.who_cell(d.target)),
                              ("raison", ", ".join(ui.names.reason("", r) for r in str(d.reason or "").split(",") if r)
                               or "—"),
                              ("objet", d.subject or "—"),
                              ("déclencheur", Text(str(d.trigger or "—"), "mono"))))]
    if d.reply_to:
        out.append(Fields((("en réponse à", Ref("event", str(d.reply_to), f"message n° {d.reply_to}")),)))
    if ended is not None and ended.data.guard:
        out.append(Note(f"Supplanté par la garde « {ended.data.guard} » : a changé {', '.join(ended.data.changed)}.",
                        "warn"))
    event, row, exact = selection_of(ui, started)
    if event is not None:
        out.append(Note(("Le choix exact de l'arbitre" if exact else
                         "Le choix de l'arbitre, retrouvé d'après le déclencheur")
                        + f" (événement n° {event.seq}).", "info"))
        if row is not None:
            out.append(waterfall(ui, row, title=f"La ligne choisie : {ui.names.arbiter_row(row.kind, row.target)}"))
        out += selection_detail(ui, event.data, frozenset(event.data.fired))
    return out


def event_blocks(ui: Any, seq: int, query=None) -> tuple[str, list[Any]] | None:
    found = ui.kernel.mind.store.get_events([seq]) if seq > 0 else []
    if not found:
        return None
    e = ui.decode(found[0])
    reg = ui.kernel.registry
    readers = sorted({ui.names.faculty(s.owner) for s in reg.reducers_by_type.get(e.type.name, [])})
    processes = sorted(ui.names.process(p.name) for p in reg.processes.values() if e.type.name in p.wake_on)
    projectors = sorted(p.name for p in reg.projectors.values() if e.type.name in p.types)
    subjects = sorted({str(v) for f in e.type.subject_fields for v in _values(getattr(e.data, f, None))})
    ctx = ui.inspection.context(query)
    triggered, pager = ctx.older([rt.EPISODE_STARTED], 25, where=("reply_to", seq))
    episode = Ref("episode", e.correlation, "son épisode") if is_episode(ui, e.correlation) else \
        Ref("local", "/inspecteur/systeme/chronologie", "les événements liés", (("correlation", e.correlation),))
    pairs: list[tuple[str, Any]] = [
        ("quand", ui.when_long(e.at)), ("ce qui s'est passé", ui.names.event(e.type.name)),
        ("émis par", f"{ui.names.faculty(e.type.owner)} · {'public' if e.type.public else 'privé'}"),
        ("lié à", episode), ("origine", str(e.origin.value)),
        ("lu sur la tête", e.basis), ("réduit par", ", ".join(readers) or "—"),
        ("réveille", ", ".join(processes) or "—"), ("projeté par", ", ".join(projectors) or "—"),
        ("personnes concernées", ", ".join(ui.names.who(s) for s in subjects) or "—"),
        ("contenus", ", ".join(f"{f} : {'oublié' if getattr(getattr(e.data, f, None), 'text', 1) is None else 'présent'}"
                                for f in sorted(e.type.content_fields)) or "—"),
    ]
    blocks: list[Any] = []
    if e.type.name == rt.UTTERANCE.name:
        blocks.append(Note("Une de ses paroles : ce qui l'a fait parler, ce qu'elle avait sous les yeux, ce dont "
                           "elle s'est souvenue et ce qu'elle a fait sont rassemblés sur une page.", "info",
                           title="Pourquoi a-t-elle dit ça ?"))
        blocks.append(Fields((("explication", Ref.why(e.seq, "Pourquoi a-t-elle dit ça ? →")),)))
    blocks.append(Fields(tuple(pairs)))
    if triggered:
        blocks.append(Table(("épisode", "vers", "quand"), tuple(
            (Ref("episode", t.correlation, names.kind(t.data.kind)), ui.names.who(t.data.target), When(t.at))
            for t in triggered), title="A déclenché", pager=pager))
    blocks.append(Code(json.dumps(json.loads(e.data.model_dump_json()), ensure_ascii=False, indent=1),
                       "Données (techniques)"))
    return f"{ui.names.event(e.type.name)} · n° {e.seq}", blocks


def _values(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list | tuple | set | frozenset):
        return [x for x in v if x]
    return [v]
