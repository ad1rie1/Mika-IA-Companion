"""Le journal vu de près : un épisode (ce qui l'a déclenché, ce qu'elle a vu, dit
et fait) et un événement (ce qui l'a produit, qui le lit, ce qu'il a déclenché).
Pour une parole précise, « Pourquoi a-t-elle dit ça ? » (``why.py``) rassemble
tout en mots.

« Rejouer avec… » (``replay_panel``, ``replay_blocks``) renvoie le prompt gardé
d'un épisode à un autre fournisseur déclaré et montre côte à côte ce qu'elle a
vraiment dit et ce que l'autre modèle répond : un seul appel (``try_on`` de la
passerelle), un appel d'outil montré jamais exécuté, rien de livré ni de gardé
au-delà de la page ; seule une ligne d'audit (``console.rejouer``, sujet :
l'épisode) entre au journal."""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.catalog import Panel
from mika.inspector.pages.decisions import selection_detail, waterfall
from mika.inspector.pages.home import outcome_badge
from mika.inspector.pages.why import episode_events, prompt_blocks, selection_of, tools_blocks, trace_of
from mika.kernel.inspect import (
    Badge,
    Code,
    Column,
    Disclosure,
    Fields,
    Grid,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Section,
    Table,
    Text,
    When,
    int_query,
    money_fr,
    num_fr,
)
from mika.ports.llm import LLMRequest, Message
from mika.runtime import operations as ops
from mika.runtime.boundary import Failed, call
from mika.runtime.tools import declare
from mika.runtime.traces import STABLE_KEY, TRUNCATION_MARK
from mika.vocab.episodes import TRIAL_ROLE

EPISODE_TABS = (("deroule", "Déroulé"), ("dit", "Ce qu'elle a dit"), ("prompt", "Prompt"), ("outils", "Outils"),
                ("appels", "Appels de modèle"), ("decision", "Décision"))
_PROVENANCE = ("memory:", "event:", "goal:", "thought:")
#: une page d'événements d'épisode
EPISODE_PAGE = 25
#: « Rejouer avec… » : au plus tant d'appels de l'épisode lus (où son prompt est déjà allé, ce qu'il a coûté)
REPLAY_CALLS = 50


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


# ── « Rejouer avec… » ────────────────────────────────────────────────────


def replay_blocked(trace: dict[str, Any] | None) -> str:
    """Pourquoi le prompt gardé d'un épisode ne peut pas être rejoué (« » : il peut l'être)."""
    if trace is None:
        return ("Le prompt de cet épisode n'a pas été gardé (plus de 14 jours, oubli, ou épisode antérieur à la "
                "console) : il n'y a rien à rejouer.")
    if trace.get("error"):
        return "La trace de cet épisode est illisible : il n'y a rien à rejouer."
    if "messages" not in trace:
        return "Aucun prompt n'est parti au modèle dans cet épisode : il n'y a rien à rejouer."
    messages, stable = trace["messages"], trace.get(STABLE_KEY)
    texts = [str(stable or ""), str(trace.get("system_volatile") or ""),
             *(str(m.get("content", "")) if isinstance(m, dict) else str(m)
               for m in (messages if isinstance(messages, list) else [messages]))]
    if trace.get(f"{STABLE_KEY}_truncated") or not isinstance(messages, list) or \
            any(TRUNCATION_MARK in t for t in texts):
        return ("Cette trace a été tronquée (un texte trop long) : un prompt incomplet ne dirait rien de ce que "
                "l'autre modèle aurait répondu.")
    if stable is None:
        return "La partie stable de ce prompt n'est plus gardée : le rejouer sans elle ne dirait rien."
    return ""


def replay_request(ui: Any, trace: dict[str, Any], corr: str) -> tuple[LLMRequest, list[str]]:
    """La requête du premier tour d'un épisode, reconstruite depuis sa trace, et les outils qui n'existent plus.
    Les déclarations d'outils sont reprises du registre actuel par leur nom, toutes en main (sa trace ne dit pas
    lesquels étaient à la demande)."""
    registry = ui.kernel.registry.tools
    offered = [str(n) for n in trace.get("tools") or ()] if isinstance(trace.get("tools"), list) else []
    req = LLMRequest(
        role=TRIAL_ROLE, call_id=f"essai:{corr}#{ui.now()}", system_stable=str(trace.get(STABLE_KEY) or ""),
        system_volatile=str(trace.get("system_volatile") or ""),
        messages=tuple(Message(str(m.get("role") or "user"), str(m.get("content") or ""))
                       for m in trace["messages"] if isinstance(m, dict)),
        tools=declare([registry[n] for n in offered if n in registry]),
        max_tokens=max(1, int_query(trace.get("max_tokens"), 1024)),
    )
    return req, [n for n in offered if n not in registry]


def _declared(gateway: Any) -> list[str]:
    """Les fournisseurs déclarés, dans l'ordre de la passerelle ; aucun sans passerelle qui sache faire un essai."""
    if not callable(getattr(gateway, "try_on", None)):
        return []
    return [str(b["name"]) for b in (getattr(gateway, "status", lambda: [])() or ()) if b.get("name")]


def _episode_calls(ui: Any, corr: str) -> list[Any]:
    """Les appels de modèle d'un épisode : le registre durable, sinon ceux qu'on a en mémoire."""
    calls = ui.deps.calls
    if calls is not None and hasattr(calls, "for_correlation"):
        return list(calls.for_correlation(corr, limit=REPLAY_CALLS))
    return [t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)][:REPLAY_CALLS]


def _local_backends(ui: Any) -> frozenset[str] | None:
    """Les fournisseurs déclarés qui tournent sur cette machine ; ``None`` : la configuration ne se lit pas."""
    llm = getattr(ui.deps.settings, "llm", None)
    if not callable(llm):
        return None
    got = call(llm, label="les fournisseurs locaux")
    return None if isinstance(got, Failed) else frozenset(n for n, s in got.backends.items() if s.local)


def replay_panel(ui: Any, corr: str, back: str) -> Panel | None:
    """« Rejouer avec… » : un bouton par fournisseur déclaré, désactivés quand la trace ne permet pas de rejouer
    (la page dit pourquoi). Un prompt qui n'est jamais sorti de cette machine (servi en local) et qui partirait
    vers un service hébergé est signalé avant l'envoi : il mêle les personnes. ``None`` : aucun fournisseur."""
    declared = _declared(ui.kernel.deps.gateway)
    if not declared:
        return None
    local = _local_backends(ui)
    served = sorted({str(t.backend) for t in _episode_calls(ui, corr) if getattr(t, "backend", "")})
    # sorti de la machine : au moins un appel servi par un service hébergé encore déclaré ; on ne le suppose jamais
    left = local is not None and any(b in declared and b not in local for b in served)
    stayed = bool(served) and local is not None and all(b in local for b in served)
    choices, warned = [], False
    for name in declared:
        hosted = local is None or name not in local
        leaves = hosted and not left
        warned = warned or leaves
        where = "" if local is None else " (sur cette machine)" if not hosted else " (hébergé)"
        label = f"Rejouer avec {name}{where}" + (" — qui l'a servi" if name in served else "")
        confirm = f"Envoyer ce prompt, qui mêle les personnes, à « {name} », hors de cette machine ?" if leaves else ""
        choices.append({"name": name, "label": label, "confirm": confirm})
    warning = ""
    if warned:
        origin = (f"Cet épisode a été servi sur cette machine ({', '.join(served)}) : son prompt n'en est jamais sorti."
                  if stayed else
                  "On ne sait pas où cet épisode a été servi : son prompt n'est peut-être jamais sorti de cette machine.")
        warning = (f"{origin} Le rejouer avec un service hébergé l'enverra au dehors — et il mêle les personnes (le fil "
                   "partagé, ce qu'elle sait des autres).")
    return Panel("replay.html", {"replay": {"episode": corr, "back": back, "choices": choices, "warning": warning,
                                            "blocked": replay_blocked(trace_of(ui, corr))}, "panel_after": True})


async def replay_blocks(ui: Any, corr: str, backend: str, *, by: str) -> tuple[list[Any], int]:
    """Rejouer le prompt gardé d'un épisode avec ``backend`` : ce qu'elle a vraiment dit et ce que l'autre modèle
    répond, côte à côte, avec durée, jetons et coût. Audité avant l'envoi (``console.rejouer``, sujet : l'épisode,
    jamais le contenu) ; rien n'est livré, rien n'entre au fil ni dans sa mémoire."""
    if not is_episode(ui, corr):
        return [Note("Aucun épisode sous ce nom.", "warn")], 404
    trace = trace_of(ui, corr)
    blocked = replay_blocked(trace)
    if blocked or trace is None:
        return [Note(blocked, "warn")], 409
    gateway = ui.kernel.deps.gateway
    if backend not in _declared(gateway):
        return [Note(f"Aucun fournisseur « {backend} » n'est déclaré (la configuration a changé ?).", "warn")], 404
    req, missing = replay_request(ui, trace, corr)
    await ops.audit(ui.kernel, "console.rejouer", by=by, subject_kind="épisode", subject=corr)
    trial = await gateway.try_on(backend, req)
    out: list[Any] = [Note("Un essai : rien n'a été livré, rien n'est entré au fil ni dans sa mémoire, et cette "
                           "réponse n'est gardée nulle part au-delà de cette page.", "info")]
    if trial.tools_dropped:
        out.append(Note(f"« {backend} » a reçu ce prompt sans ses outils : la CLI ne rend un appel d'outil qu'en "
                        "gardant sa session ouverte dans l'attente d'un résultat, qu'un essai ne donne jamais.", "warn"))
    if missing:
        out.append(Note("Des outils offerts n'existent plus, l'essai part sans eux : " + ", ".join(missing) + ".",
                        "warn"))
    out.append(Grid((Section("Ce qu'elle a vraiment dit", tuple(_said_blocks(ui, corr, trace))),
                     Section(f"Ce que « {backend} » répond", tuple(_trial_blocks(trial)))), columns=2))
    return out, 200


def _said_blocks(ui: Any, corr: str, trace: dict[str, Any]) -> list[Any]:
    """Ce qu'elle a vraiment dit dans l'épisode (le journal), et ce que ses appels de modèle ont coûté."""
    said, _pager = _events(ui, corr, speeches=True)
    out: list[Any] = []
    if said:
        out.append(Prose("\n\n".join(u.data.text.text or "(oublié)" for u in said), reading=True))
        voice = said[-1].data.voice
        out.append(Fields((("voix", f"{names.role(voice.role)} · {voice.model or '—'}"),)))
        if trace.get("reply"):
            out.append(Disclosure("Le texte brut du modèle", (Prose(str(trace["reply"]), clamp=1500),)))
    elif trace.get("reply"):
        out.append(Prose(str(trace["reply"]), "Ce que le modèle avait répondu (jamais livré)", reading=True))
    else:
        out.append(Note("Elle n'a rien dit dans cet épisode.", "muted"))
    calls = _episode_calls(ui, corr)
    if calls:
        out.append(Fields((
            ("servie par", Text(", ".join(sorted({f"{t.backend} · {t.model or '—'}" for t in calls})), "mono")),
            ("appels", num_fr(len(calls))),
            ("durée", f"{num_fr(sum(t.latency_us for t in calls) / 1e6, 1)} s"),
            ("jetons", f"{num_fr(sum(t.input_tokens for t in calls))} → {num_fr(sum(t.output_tokens for t in calls))}"),
            ("coût", money_fr(sum(t.cost_usd or 0.0 for t in calls))),
        ), title="Ses appels de modèle (l'épisode entier, outils compris)"))
    return out


def _trial_blocks(trial: Any) -> list[Any]:
    """Ce que l'autre modèle répond, au mot près ; les outils qu'il demande (jamais exécutés) ; ce qu'a coûté
    l'appel."""
    out: list[Any] = []
    resp = trial.response
    if resp is None:
        out.append(Note(f"« {trial.backend} » n'a rien rendu : {names.detail(trial.error)}", "danger"))
    else:
        out.append(Prose(resp.text or "(aucun texte)", reading=True))
        if resp.stop == "max_tokens":
            out.append(Note("Coupée par son plafond de jetons : un essai n'est jamais redemandé.", "warn"))
        elif resp.stop == "refusal":
            out.append(Note("Le modèle a refusé de répondre.", "warn"))
        if resp.tool_calls:
            out.append(Table(("outil", "arguments"), tuple(
                (Text(c.name, "mono"), Text(json.dumps(dict(c.args), ensure_ascii=False, indent=1, default=str),
                                            "mono", clamp=600)) for c in resp.tool_calls),
                title="Les outils qu'il demande", caption="Montrés tels qu'il les a demandés, jamais exécutés."))
    tr = trial.trace
    if tr is not None:
        out.append(Fields((
            ("modèle", Text(tr.model or "—", "mono")),
            ("attente d'un créneau", f"{num_fr(tr.wait_us / 1e6, 1)} s"),
            ("durée", f"{num_fr(tr.latency_us / 1e6, 1)} s"),
            ("jetons", f"{num_fr(tr.input_tokens)} → {num_fr(tr.output_tokens)}"),
            ("cache lu", num_fr(tr.cache_read)),
            ("coût", money_fr(tr.cost_usd)),
        ), title="L'appel"))
    return out
