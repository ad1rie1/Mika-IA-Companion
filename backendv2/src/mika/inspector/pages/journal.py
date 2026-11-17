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
from collections.abc import Mapping
from typing import Any, NamedTuple

from sqlalchemy import func, select

from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.catalog import Panel
from mika.inspector.pages.decisions import selection_detail, waterfall
from mika.inspector.pages.episode_overview import overview
from mika.inspector.pages.home import outcome_badge
from mika.inspector.pages.system import OUTBOX_TONES, departures, guidance, outbox_card
from mika.inspector.pages.why import (
    author_blocks,
    context_blocks,
    episode_events,
    prompt_blocks,
    selection_of,
    tools_blocks,
    trace_of,
)
from mika.inspector.ui import PREFIX
from mika.kernel.inspect import (
    Badge,
    Cell,
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
    plural,
)
from mika.ports.journal import JournalEvent, JournalOutbox
from mika.ports.llm import LLMRequest, Message
from mika.runtime import operations as ops
from mika.runtime.boundary import Failed, call
from mika.runtime.effects import OUTBOX_LABELS, OUTBOX_PROBLEMS
from mika.runtime.tool_offer import declare
from mika.runtime.traces import STABLE_KEY, TRUNCATION_MARK
from mika.vocab.episodes import TRIAL_ROLE, outcome_words
from mika.vocab.privacy import LEVEL_WORDS

EPISODE_TABS = (("resume", "Résumé"), ("deroule", "Déroulé"), ("dit", "Ce qu'elle a dit"), ("prompt", "Prompt"), ("outils", "Outils"),
                ("appels", "Appels de modèle"), ("decision", "Décision"))
_PROVENANCE = ("memory:", "event:", "goal:", "thought:")
#: une page d'événements d'épisode
EPISODE_PAGE = 25
#: « Rejouer avec… » : au plus tant d'appels de l'épisode lus (où son prompt est déjà allé, ce qu'il a coûté)
REPLAY_CALLS = 50
#: où la page dessinée range un fait du prompt (``PromptFact.place``) : sa carte « Ses outils » le dit déjà ; replié
#: sous « Détails techniques »
FACT_TOOLS, FACT_TECHNICAL = "outils", "technique"
#: une réponse reprise (``reprise:<n>``, ``runtime/bootstrap.py``) : au démarrage après un arrêt, après une réponse
#: supplantée ou préemptée, ou quand elle se réveille — les mots de « Pourquoi a-t-elle parlé ? » (``why.py``)
RESUMED = "repris après une interruption"


def _events(ui: Any, corr: str, query=None, *, speeches: bool = False) -> tuple[list[Any], Pager]:
    request = ui.inspection.context(query).pager(size=EPISODE_PAGE)
    e = JournalEvent
    where = (e.correlation == corr, e.type == rt.UTTERANCE.name) if speeches else (e.correlation == corr,)
    total = int(ui.kernel.mind.store.query_mind(select(func.count()).select_from(e).where(*where))[0][0])
    pager = Pager(number=min(request.number, max(1, (total + EPISODE_PAGE - 1) // EPISODE_PAGE)), size=EPISODE_PAGE,
                  total=total)
    seqs = [int(r[0]) for r in ui.kernel.mind.store.query_mind(
        select(e.seq).where(*where).order_by(e.seq).limit(pager.size).offset(pager.offset))]
    return [ui.decode(s) for s in ui.kernel.mind.store.get_events(seqs)], pager


def _provenance(ref: str) -> Any:
    head, _, tail = ref.partition(":")
    if f"{head}:" in _PROVENANCE and tail.isdigit():
        return Ref("event", tail, ref)
    return ref


def is_episode(ui: Any, corr: str) -> bool:
    """Une corrélation d'épisode (un début ou une fin au journal) — pas une action d'opérateur, un effet,
    un processus : ceux-là n'ont pas de page d'épisode."""
    e = JournalEvent
    return bool(ui.kernel.mind.store.query_mind(
        select(e.seq).where(e.correlation == corr, e.type.in_([rt.EPISODE_STARTED.name, rt.EPISODE_ENDED.name]))
        .limit(1)))


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
    if tab == "resume":
        return overview(ui, corr, info)
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
            rows.append(Row((When(u.at), Badge("elle", "info"), ui.names.who_cell(d.target), Text(d.text.text or "(oublié)", clamp=400),
                             "visible" if d.visible else "pas dans le fil"), href=Ref.why(u.seq), detail=tuple(out)))
        return [Table(("Quand", Column("Qui parle", role="title"), "À", Column("Parole", role="body"), "Visibilité"), tuple(rows),
                      title="Paroles de l'épisode", pager=pager, layout="feed", link_label="Expliquer cette parole",
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
        out.append(Fields(tuple((f.label, f.value) for f in prompt_facts(ui, trace, started or ended))))
        out += context_blocks(trace)
        if trace.get("reply"):
            said = trace.get("outcome") in ("done", "abstained")
            out.append(Prose(str(trace["reply"]), "Ce que le modèle a répondu" if said
                             else "Ce qu'elle allait dire (jamais livré)", clamp=1500))
        # l'autrice a récrit derrière (ADR 0114) : ce qu'elle a lu et rendu
        out += author_blocks(trace)
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
                     href=Ref("event", str(e.seq), ""), detail=(Code(ui.show(e, 4000), "Données"),)) for e in events)
    return [Table((Column("Quand", "fit"), Column("Ce qui s’est passé", role="title"), Column("Explication", "fit"),
                   Column("Événement", detail=True), Column("Type", detail=True)), rows, title="Déroulé", pager=pager,
                  layout="list", link_label="Ouvrir l’événement")]


class PromptFact(NamedTuple):
    """Un fait de l'onglet Prompt : son libellé, sa cellule, et où la page dessinée le range (``""`` : avec les autres ;
    ``FACT_TOOLS``, ``FACT_TECHNICAL``). Les blocs les montrent tous, dans l'ordre."""

    label: str
    value: Cell
    place: str = ""


def prompt_facts(ui: Any, trace: Mapping[str, Any], started: Any | None) -> list[PromptFact]:
    """Ce qui a décidé du prompt, en mots, pour les deux rendus de l'onglet Prompt (la page dessinée et ses blocs) :
    son rôle, son déclencheur (``trigger_cell``), ce qu'elle pouvait dire d'autrui (le niveau de son audience), ses
    outils offerts, ce qui a été rassemblé avant de l'écrire (ses enrichisseurs, ``Names.enricher``), l'empreinte de
    son préfixe et son issue, dite comme l'étiquette de la page : avec la sorte de l'épisode (« a parlé »), lue sur
    ``started`` (son début, ou sa fin)."""
    outcome = trace.get("outcome")
    kind = getattr(getattr(started, "data", None), "kind", None)
    enriched = [ui.names.enricher(str(k)) for k in trace.get("enrichments") or ()]
    return [
        PromptFact("rôle", names.role(trace.get("role"))),
        PromptFact("déclencheur", trigger_cell(trace.get("trigger"))),
        PromptFact("ce qu'elle pouvait dire d'autrui", _level((trace.get("audience") or {}).get("level"))),
        PromptFact("outils offerts", ", ".join(trace.get("tools") or ()) or "aucun", FACT_TOOLS),
        PromptFact("enrichissements", " · ".join(enriched) or "aucun"),
        PromptFact("empreinte du préfixe", Text(str(trace.get("system_stable_hash") or "—")[:16], "mono",
                                                hint="la même d'un épisode à l'autre : le cache sert"), FACT_TECHNICAL),
        PromptFact("issue", "en cours" if outcome == "running" else outcome_words(outcome, kind)[0]),
    ]


def _level(level: Any) -> Cell:
    """Le niveau d'une audience (une ``Sensitivity``) en mots (« personnel ») ; un niveau illisible, tel quel."""
    if level is None:
        return Text("—", "muted")
    said = LEVEL_WORDS.get(level) if isinstance(level, int) and not isinstance(level, bool) else None
    return said if said is not None else Text(str(level), "mono")


def trigger_cell(trigger: str | None) -> Cell:
    """Le déclencheur d'un épisode (celui de son début, celui de sa trace), en mots : le message auquel elle répond,
    en lien (``perception:<n>``, ou ``reprise:<n>``, ``RESUMED``) ; un choix de l'arbitre (``selected:<n>``,
    ``runtime/bootstrap.py``) ; ce qu'un prélude précède (``prélude:<x>``, ``runtime/pipeline.py``). Une autre forme
    se montre telle quelle. Les onglets Prompt et Décision le disent ainsi."""
    raw = str(trigger or "")
    said = _trigger_said(raw)
    if said is None:
        return Text(raw, "mono") if raw else Text("—", "muted")
    text, seq = said
    return Ref("event", seq, text) if seq else text


def reply_trigger_cell(trigger: str | None) -> Cell | None:
    """Ce que le déclencheur d'une réponse ajoute au message auquel elle répond, quand ce message se montre déjà
    (« Ce qui l'a lancé », l'onglet Décision dessiné) : rien pour ``perception:<n>`` (c'est ce message) ni pour un
    déclencheur vide ; ``RESUMED`` pour ``reprise:<n>`` ; une autre forme, en mots (``trigger_cell``)."""
    raw = str(trigger or "")
    head, _, tail = raw.partition(":")
    if not raw or (head == "perception" and tail.isdigit()):
        return None
    return RESUMED if head == "reprise" and tail.isdigit() else trigger_cell(raw)


def _trigger_said(raw: str, *, before: bool = False) -> tuple[str, str] | None:
    """(ce que dit un déclencheur, le numéro du message à lier ou « ») ; ``before`` : dit après « avant »."""
    head, _, tail = raw.partition(":")
    if head in ("perception", "reprise") and tail.isdigit():
        if before:
            return f"la réponse au message n° {tail}", tail
        return f"message n° {tail}" + (f", {RESUMED}" if head == "reprise" else ""), tail
    if head == "selected":
        return ("ce que l'arbitre a choisi" if before else "un choix de l'arbitre"), ""
    if head == "prélude" and not before:
        inner = _trigger_said(tail, before=True)
        return (f"avant {inner[0]}", inner[1]) if inner is not None else None
    return None


def names_outcome_call(outcome: str) -> Badge:
    """L'issue d'un appel de modèle, en mots."""
    return Badge("réussi" if outcome == "ok" else names.detail(outcome), "ok" if outcome == "ok" else "danger")


def decision_blocks(ui: Any, started: Any, ended: Any, info: dict[str, Any]) -> list[Any]:
    """L'onglet « Décision » : le déclencheur, et — pour un épisode lancé par l'arbitre — **le** choix qui
    l'a lancé (le numéro exact s'il est au journal), sa ligne pas à pas et les autres lignes."""
    if started is None:
        return [Note("Début d'épisode introuvable.", "muted")]
    d = started.data
    # une réponse : le message auquel elle répond, en lien, et son déclencheur en mots quand il en dit plus (une
    # reprise, ``reprise:<n>``) ; sinon son déclencheur, en mots
    reply = (("en réponse à", Ref("event", str(d.reply_to), f"message n° {d.reply_to}")),) if d.reply_to else ()
    trigger = (("déclencheur", trigger_cell(d.trigger)),) \
        if not d.reply_to or reply_trigger_cell(d.trigger) is not None else ()
    out: list[Any] = [Fields((("sorte", info["kind"]), ("vers", ui.names.who_cell(d.target)),
                              ("raison", ", ".join(ui.names.reason("", r) for r in str(d.reason or "").split(",") if r)
                               or "—"),
                              ("objet", d.subject or "—"), *reply, *trigger))]
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


#: l'aide de « état lu » sur la page d'un événement (``Event.basis``)
BASIS_HINT = ("Le journal tel qu'il était quand l'événement a été décidé : ce qu'il a lu s'arrêtait à ce numéro.")


def basis_words(basis: int) -> str:
    """L'état du journal qu'un événement a lu, en mots : « jusqu'au n° 49 » ; rien avant le premier."""
    return f"jusqu'au n° {basis}" if basis > 0 else "rien : le journal était vide"


def event_page(ui: Any, seq: int, query=None) -> dict[str, Any] | None:
    """Un événement du journal : son titre (ce qui s'est passé en mots — son numéro, le fil d'Ariane le dit), ses
    repères (``facts`` : quand, émis par, son origine en mots, son épisode et, pour une parole, « Pourquoi a-t-elle dit
    ça ? »), que la route pose sur la ligne de faits de l'en-tête, ses blocs, et ce que dessine
    ``handmade/evenement/evenement.html`` (``view``) — ses textes titrés en mots (``names.content_field``), ses départs
    (ses lignes de la file de sortie, dites par ``system.departures`` comme la File de sortie les dit : l'effet en mots,
    à qui, l'état, les essais, la dernière erreur ; un départ à traiter porte Relancer / Marquer comme vu, qui
    reviennent à cette page), son parcours dans la machine (son type, qui le réduit, ce qu'il réveille, qui le
    projette, l'état du journal qu'il a lu), qui il concerne, les épisodes qu'il a déclenchés, ses données brutes."""
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
    linked = is_episode(ui, e.correlation)
    episode = Ref("episode", e.correlation, "son épisode") if linked else \
        Ref("local", f"{PREFIX}/systeme/chronologie", "les événements liés", (("correlation", e.correlation),))
    title = ui.names.event(e.type.name)
    owner = f"{ui.names.faculty(e.type.owner)} · {'public' if e.type.public else 'privé'}"
    origin = names.event_origin(e.origin.value)
    spoken = e.type.name == rt.UTTERANCE.name
    # ses repères, sur la ligne de faits de l'en-tête (dessinée comme au repli) ; « Pourquoi a-t-elle dit ça ? »
    # n'a pas besoin de libellé
    facts: list[tuple[str, Any]] = [("quand", ui.when_long(e.at)), ("émis par", owner), ("origine", origin),
                                    ("lié à" if linked else "", episode)]
    if spoken:
        facts.append(("", Ref.why(e.seq, "Pourquoi a-t-elle dit ça ? →")))
    contents = [(f, getattr(getattr(e.data, f, None), "text", None)) for f in sorted(e.type.content_fields)]
    basis = Ref("event", str(e.basis), basis_words(e.basis)) if e.basis > 0 else Text(basis_words(e.basis), "muted")
    raw = json.dumps(json.loads(e.data.model_dump_json()), ensure_ascii=False, indent=1)
    blocks: list[Any] = [
        Fields((("type", Text(e.type.name, "mono")), ("réduit par", ", ".join(readers) or "—"),
                ("réveille", ", ".join(processes) or "—"), ("projeté par", ", ".join(projectors) or "—"),
                ("état lu", basis)), title="Son parcours dans la machine", hints=(("état lu", BASIS_HINT),)),
        Fields((("personnes concernées", ", ".join(ui.names.who(s) for s in subjects) or "—"),
                ("contenus", ", ".join(f"{names.content_field(f)} : {'oublié' if text is None else 'présent'}"
                                       for f, text in contents) or "—"))),
    ]
    if triggered:
        blocks.append(Table(("épisode", "vers", "quand"), tuple(
            (Ref("episode", t.correlation, names.kind(t.data.kind)), ui.names.who(t.data.target), When(t.at))
            for t in triggered), title="A déclenché", pager=pager))
    # ses départs : ce que la file de sortie a fait partir de lui (ou n'a pas pu), dit comme la File de sortie
    o = JournalOutbox
    left = ui.kernel.mind.store.query_mind(select(o.key, o.effect, o.status, o.attempts, o.last_error)
                                           .where(o.seq == e.seq).order_by(o.key))
    told = departures(ui, ((e.seq, effect) for _key, effect, *_ in left), {e.seq: found[0]})
    gone = [(key, effect, st, int(attempts or 0), err, told[(e.seq, effect)])
            for key, effect, st, attempts, err in left]
    if gone:
        blocks.append(Table(
            ("effet", "état", Column("essais", "num"), "dernière erreur", "à qui", "quoi", "que faire",
             Column("effet (clé)", detail=True), Column("clé", detail=True)),
            tuple(Row((Text(d.title, hint=effect), Badge(OUTBOX_LABELS.get(st, st), OUTBOX_TONES.get(st, ""), key=st),
                       attempts, Text(names.detail(err) if err else "—", "muted", clamp=200), d.to or "—",
                       d.text or "—", guidance(st, d.sort) or "—", Text(effect, "mono"), Text(key, "mono")),
                      tone="danger" if st in ("failed", "orphan") else "warn" if st in OUTBOX_PROBLEMS else "")
                  for key, effect, st, attempts, err, d in gone),
            title=DEPARTURES_TITLE,
            caption="Ce que la file de sortie a fait partir de cet événement. Un départ à traiter se relance ou se "
                    "marque comme vu dans Système › File de sortie, ou sur la page dessinée de l'événement."))
    blocks.append(Code(raw, "Données (techniques)"))
    back = f"{PREFIX}/evenement/{e.seq}"

    def view(env: Any, q: Any) -> dict[str, Any]:
        ends = {t.correlation: episode_events(ui, t.correlation)[1] for t in triggered}
        return {
            "title": title, "type": e.type.name,
            "basis": {"text": basis_words(e.basis), "href": render.href(basis) if isinstance(basis, Ref) else "",
                      "hint": BASIS_HINT},
            "texts": [{"field": names.content_field(f), "text": text} for f, text in contents],
            "speech": e.type.name in (rt.UTTERANCE.name, rt.PERCEPTION_RECEIVED.name),
            "mine": spoken,
            "readers": readers, "processes": processes, "projectors": projectors,
            "people": [{"name": ui.names.who(s), "href": render.href(Ref.subject("person", s, ""))
                        if s.startswith("user_") else ""} for s in subjects],
            "triggered": [{"kind": names.kind(t.data.kind), "to": ui.names.who(t.data.target),
                           "when": ui.when_long(t.at), "href": render.href(Ref("episode", t.correlation, "")),
                           "outcome": outcome_words(ends[t.correlation].data.outcome, ends[t.correlation].data.kind)
                           if ends.get(t.correlation) is not None else ("en cours", "warn")} for t in triggered],
            "pager": render.pager_ctx(pager, q or {}), "raw": raw,
            # ses départs : à traiter, avec Relancer / Marquer comme vu (qui reviennent ici) ; les autres, leur état
            "back": back,
            "todo": [outbox_card(key, "", d, st, err, attempts=plural(attempts, "essai", "essais"))
                     for key, effect, st, attempts, err, d in gone if st in OUTBOX_PROBLEMS],
            "departures": [{"name": d.title, "to": d.to, "state": OUTBOX_LABELS.get(st, st),
                            "tone": OUTBOX_TONES.get(st, ""), "attempts": plural(attempts, "essai", "essais"),
                            "error": names.detail(err) if err and st != "done" else ""}
                           for key, effect, st, attempts, err, d in gone if st not in OUTBOX_PROBLEMS],
        }

    return {"title": title, "facts": facts, "blocks": blocks, "view": view}


#: le titre du bloc des départs d'un événement (sa vue en tableau, la console en MCP)
DEPARTURES_TITLE = "Ses départs"
#: la page d'un événement, dessinée, et ses feuilles
EVENT_TEMPLATE = "handmade/evenement/evenement.html"
EVENT_STYLES = ("handmade/episode.css",)


def event_panel(got: dict[str, Any], env: Any, query: Any) -> Panel | None:
    """La page d'un événement, dessinée : son gabarit et ce qu'il dessine (``v``) ; ``None`` si ce qu'il dessine ne se
    lit pas (ses blocs, alors)."""
    drawn = call(got["view"], env, query, label="événement dessiné")
    return None if isinstance(drawn, Failed) else Panel(EVENT_TEMPLATE, {"v": drawn}, styles=EVENT_STYLES)


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
    return Panel("handmade/parole/rejouer.html", {"replay": {"episode": corr, "back": back, "choices": choices, "warning": warning,
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
