"""Le journal vu de près : un épisode (« pourquoi a-t-elle dit ça ? ») et un
événement (ce qui l'a produit, qui le lit, ce qu'il a déclenché)."""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import runtime as rt
from mika.inspector.pages.home import KINDS, outcome_badge
from mika.kernel.inspect import (
    Badge,
    Code,
    Column,
    Fields,
    Meter,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
)

EPISODE_TABS = (("deroule", "Déroulé"), ("dit", "Ce qu'elle a dit"), ("prompt", "Prompt"), ("outils", "Outils"),
                ("appels", "Appels de modèle"), ("decision", "Décision"))
_PROVENANCE = ("memory:", "event:", "goal:", "thought:")


def _events(ui: Any, corr: str, query=None, *, speeches: bool = False) -> tuple[list[Any], Pager]:
    request = ui.inspection.context(query).pager(size=25)
    clause, args = ("correlation=? AND type=?", (corr, rt.UTTERANCE.name)) if speeches else ("correlation=?", (corr,))
    total = int(ui.kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM events WHERE {clause}", args)[0][0])
    pager = Pager(number=min(request.number, max(1, (total + 24) // 25)), size=25, total=total)
    seqs = [int(r[0]) for r in ui.kernel.mind.store.query_mind(
        f"SELECT seq FROM events WHERE {clause} ORDER BY seq LIMIT ? OFFSET ?", (*args, pager.size, pager.offset))]
    return [ui.decode(s) for s in ui.kernel.mind.store.get_events(seqs)], pager


def _provenance(ref: str) -> Any:
    head, _, tail = ref.partition(":")
    if f"{head}:" in _PROVENANCE and tail.isdigit():
        return Ref("event", tail, ref)
    return ref


def episode_head(ui: Any, corr: str) -> dict[str, Any] | None:
    if not ui.kernel.mind.store.query_mind("SELECT seq FROM events WHERE correlation=? LIMIT 1", (corr,)):
        return None
    ctx = ui.inspection.context()
    started = next(iter(ctx.events([rt.EPISODE_STARTED], 1, correlations={corr})), None)
    ended = next(iter(ctx.events([rt.EPISODE_ENDED], 1, correlations={corr})), None)
    kind = started.data.kind if started else (ended.data.kind if ended else "")
    badges = []
    if ended:
        b = outcome_badge(ended.data.outcome)
        badges.append({"text": b.text, "tone": b.tone})
    else:
        badges.append({"text": "en cours ou interrompu", "tone": "warn"})
    facts = [{"label": "vers", "value": (started.data.target if started else None) or "—"},
             {"label": "début", "value": ui.when_long(started.at) if started else "—"}]
    if started and started.data.reason:
        facts.append({"label": "raison", "value": started.data.reason})
    return {"started": started, "ended": ended, "kind": KINDS.get(kind, kind or "épisode"),
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
            out = [Prose(d.text.text or "(oublié)", "Parole complète", reading=True)]
            out.append(Fields((
                ("ce que le prompt lui montrait", Text(" · ".join(d.sections) or "—", "muted")),
                ("ce qui l'a nourrie", " · ".join(d.provenance) or "—"),
                ("outils", ", ".join(f"{t.name}{'' if t.ok else ' (échec)'}" for t in d.tools) or "aucun"),
                ("voix", f"{d.voice.role} · {d.voice.model}")),
                hints=(("ce qui l'a nourrie", "souvenirs et événements qu'elle avait sous les yeux"),)))
            links = [p for p in (_provenance(x) for x in d.provenance) if isinstance(p, Ref)]
            if links:
                out.append(Table(("source",), tuple((p,) for p in links), title="Sources"))
            rows.append(Row((When(u.at), d.target or "Pour elle", Text(d.text.text or "(oublié)", clamp=400),
                             "visible" if d.visible else "pas dans le fil"), detail=tuple(out)))
        return [Table(("Quand", "À", "Parole", "Visibilité"), tuple(rows), title="Paroles de l'épisode", pager=pager)]
    if tab == "prompt":
        trace = _trace(ui, corr)
        if trace is None:
            return [Note("Le prompt de cet épisode n'a pas été gardé (plus de 14 jours, oubli, ou épisode antérieur "
                         "à la console).", "muted")]
        out = []
        compose = trace.get("compose") or {}
        if trace.get("truncated"):
            out.append(Note("Cette trace a été tronquée (un texte trop long) : ce qui est montré est incomplet.",
                            "warn"))
        if compose:
            sizes = {k: v for k, v in (compose.get("sizes") or ())}
            total = max(1, sum(sizes.values()))
            trimmed = set(compose.get("trimmed") or ())
            rows = [Row((k, sizes.get(k, "—"), Meter(sizes.get(k, 0) / total),
                         Badge("rognée", "warn") if k in trimmed else Badge("incluse", "ok")))
                    for k in compose.get("included") or ()]
            rows += [Row((k, "—", None, Badge(f"coupée : {why}", "muted")), tone="muted")
                     for k, why in compose.get("dropped") or ()]
            out.append(Table(("section", Column("caractères", "num"), "part", "état"), tuple(rows),
                             title=f"Composition · {compose.get('chars', 0)} caractères, "
                                   f"{compose.get('history_turns', 0)} tour(s) d'historique"))
        facts = [("rôle", trace.get("role") or "—"), ("déclencheur", trace.get("trigger") or "—"),
                 ("audience", str((trace.get("audience") or {}).get("level", "—"))),
                 ("outils offerts", ", ".join(trace.get("tools") or ()) or "aucun"),
                 ("enrichissements", ", ".join(trace.get("enrichments") or ()) or "aucun"),
                 ("empreinte du préfixe", Text(str(trace.get("system_stable_hash") or "—")[:16], "mono",
                                               hint="la même d'un épisode à l'autre : le cache sert")),
                 ("issue", trace.get("outcome") or "—")]
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
        trace = _trace(ui, corr)
        tools = (trace or {}).get("tool_calls") or []
        if not tools:
            said, pager = _events(ui, corr, query, speeches=True)
            if not said:
                return [Note("Aucun outil retrouvé pour cet épisode.", "muted")]
            return [Table(("Parole", "Outils utilisés"), tuple(Row((Ref("event", str(e.seq), f"n° {e.seq}"),
                        ", ".join(t.name for t in e.data.tools) or "aucun"), detail=(Table(("Outil", "Issue"),
                        tuple((t.name, Badge("ok" if t.ok else "échec", "ok" if t.ok else "danger")) for t in e.data.tools)),))
                        for e in said), title="Outils par parole", pager=pager),
                    Note("La trace détaillée n'a pas été gardée. Les outils restent consultables par parole.", "muted")]
        return [Table(("outil", "issue", Column("durée", "num"), "arguments", "résultat"), tuple(
            Row((t.get("name", "?"), Badge("ok" if t.get("ok") else "échec", "ok" if t.get("ok") else "danger"),
                 f"{int(t.get('duration_us') or 0) // 1000} ms", Text(str(t.get("args", "")), "mono", clamp=160),
                 Text(str(t.get("result", "")), "mono", clamp=240)),
                tone="" if t.get("ok") else "danger") for t in tools if isinstance(t, dict)),
            title="Outils appelés")]
    if tab == "appels":
        calls = ui.deps.calls
        pager = None
        if calls is not None and hasattr(calls, "for_correlation"):
            total = calls.count(correlation=corr)
            request = ui.inspection.context(query).pager(size=25)
            pager = Pager(number=min(request.number, max(1, (total + 24) // 25)), size=25, total=total)
            traces = calls.for_correlation(corr, limit=pager.size, offset=pager.offset)
        else:
            traces = [t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)]
        if not traces:
            return [Note("Aucun appel de modèle retrouvé pour cet épisode.", "muted")]
        return [Table(("rôle", "fournisseur", "modèle", Column("attente", "num"), Column("durée", "num"),
                       Column("jetons", "num"), Column("cache lu", "num"), Column("coût", "num"), "issue"), tuple(
            (t.role, t.backend, Text(t.model, "mono"), f"{t.wait_us / 1e6:.1f} s", f"{t.latency_us / 1e6:.1f} s",
             f"{t.input_tokens} → {t.output_tokens}", t.cache_read, f"{t.cost_usd:.4f} $",
             Badge(t.outcome, "ok" if t.outcome == "ok" else "danger")) for t in traces), pager=pager)]
    if tab == "decision":
        if started is None:
            return [Note("Début d'épisode introuvable.", "muted")]
        out = [Fields((("sorte", info["kind"]), ("déclencheur", started.data.trigger or "—"),
                       ("raison", started.data.reason or "—"), ("objet", started.data.subject or "—")))]
        if started.data.reply_to:
            out.append(Fields((("en réponse à", Ref("event", str(started.data.reply_to),
                                                    f"message n° {started.data.reply_to}")),)))
        if ended is not None and ended.data.guard:
            out.append(Note(f"Supplanté par la garde « {ended.data.guard} » : a changé {', '.join(ended.data.changed)}.",
                            "warn"))
        chosen = ui.inspection.context().events(["kernel.selected"], 1, before=started.seq + 1)
        if chosen and chosen[0].seq >= started.seq - 5 and started.data.kind == "INITIATIVE":
            d = chosen[0].data
            out.append(Table(("ligne", Column("score", "num"), Column("taux /h", "num"), "preuves"), tuple(
                (f"{KINDS.get(r.kind, r.kind)} → {r.target}", round(r.score, 2), round(r.hazard * 3600, 3),
                 Text("\n".join(f"{o} · {why} {v:+.2f}" for o, why, v in r.parts), "mono")) for r in d.rows),
                title=f"Le choix de l'arbitre (tirage {d.draw:.3f})"))
        return out
    events, pager = _events(ui, corr, query)
    rows = tuple(Row((Ref("event", str(e.seq), str(e.seq)), When(e.at), Text(e.type.name, "mono"),
                      Text(ui.show(e, 1200), "mono", clamp=180))) for e in events)
    return [Table((Column("seq", "fit"), Column("quand", "fit"), "type", "données"), rows, title="Déroulé", pager=pager)]


def _trace(ui: Any, corr: str) -> dict[str, Any] | None:
    traces = ui.kernel.ports.get("traces")
    if traces is None:
        return None
    got = traces.get(corr)
    return got if isinstance(got, dict) else None


def event_blocks(ui: Any, seq: int, query=None) -> tuple[str, list[Any]] | None:
    found = ui.kernel.mind.store.get_events([seq])
    if not found:
        return None
    e = ui.decode(found[0])
    reg = ui.kernel.registry
    readers = sorted({s.owner for s in reg.reducers_by_type.get(e.type.name, [])})
    processes = sorted(p.name for p in reg.processes.values() if e.type.name in p.wake_on)
    projectors = sorted(p.name for p in reg.projectors.values() if e.type.name in p.types)
    subjects = sorted({str(v) for f in e.type.subject_fields for v in _values(getattr(e.data, f, None))})
    ctx = ui.inspection.context(query)
    triggered = ctx.events([rt.EPISODE_STARTED], 26, where=("reply_to", seq), before=ctx.int_param("avant", 0) or None)
    pager = Pager(older=(("avant", str(triggered[24].seq)),)) if len(triggered) > 25 else Pager()
    triggered = triggered[:25]
    pairs: list[tuple[str, Any]] = [
        ("quand", ui.when_long(e.at)), ("propriétaire", f"{e.type.owner} · {'public' if e.type.public else 'privé'}"),
        ("corrélation", Ref("episode", e.correlation, e.correlation)), ("origine", str(e.origin.value)),
        ("lu sur la tête", e.basis), ("réduit par", ", ".join(readers) or "—"),
        ("réveille", ", ".join(processes) or "—"), ("projeté par", ", ".join(projectors) or "—"),
        ("personnes concernées", ", ".join(subjects) or "—"),
        ("contenus", ", ".join(f"{f} : {'oublié' if getattr(getattr(e.data, f, None), 'text', 1) is None else 'présent'}"
                                for f in sorted(e.type.content_fields)) or "—"),
    ]
    blocks: list[Any] = [Fields(tuple(pairs))]
    if triggered:
        blocks.append(Table(("épisode", "sorte", "quand"), tuple(
            (Ref("episode", t.correlation, t.correlation[:30]), KINDS.get(t.data.kind, t.data.kind), When(t.at))
            for t in triggered), title="A déclenché", pager=pager))
    blocks.append(Code(json.dumps(json.loads(e.data.model_dump_json()), ensure_ascii=False, indent=1),
                       "Données"))
    return f"{e.type.name} · n° {e.seq}", blocks


def _values(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list | tuple | set | frozenset):
        return [x for x in v if x]
    return [v]
