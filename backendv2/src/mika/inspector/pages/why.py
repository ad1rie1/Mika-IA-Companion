"""« Pourquoi a-t-elle dit ça ? » : une page par parole.

Tout ce qui explique une phrase, à un seul endroit et en mots :

1. **ce qu'elle a dit**, à qui, quand ;
2. **ce qui l'a fait parler** — le message auquel elle répondait, ou la ligne
   exacte de l'arbitre qui l'a fait prendre la parole (chaque preuve, chaque
   modulation, le seuil, le score, le taux, le tirage) ;
3. **ce qu'elle avait sous les yeux** — les sections du prompt, nommées en
   français, gardées, rognées ou coupées (et pourquoi) ;
4. **ce dont elle s'est souvenue** — les souvenirs, croyances, promesses,
   échanges, buts et projets qui l'ont nourrie, avec leur texte et un lien ;
5. **ce qu'elle a fait** — les outils appelés, leurs arguments et leurs
   résultats.

Elle se lit dans le journal (l'énoncé, le début d'épisode, le choix de
l'arbitre) et dans la trace de l'épisode (``runtime/traces.py``, 14 jours) ;
quand la trace n'existe plus, la page le dit et montre ce que le journal
garde. Les identifiants techniques restent dans « Détails techniques ».
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.pages.decisions import arbiter_rows, waterfall
from mika.kernel.builtin import SELECTED
from mika.kernel.inspect import (
    Badge,
    Code,
    Column,
    Disclosure,
    Fields,
    Meter,
    Note,
    Prose,
    Ref,
    Row,
    Section,
    Table,
    Text,
    When,
    num_fr,
)
from mika.runtime.boundary import Failed, call

#: au-delà, l'arbitre a pu choisir plus tôt : le choix d'un départ se cherche dans ces événements-ci
SELECTION_LOOKUP = 50
#: une provenance montre au plus tant de souvenirs (une parole en cite rarement plus)
RECALL_MAX = 60


def _decoded(ui: Any, seq: int) -> Any | None:
    found = ui.kernel.mind.store.get_events([seq]) if seq > 0 else []
    return ui.decode(found[0]) if found else None


def episode_events(ui: Any, corr: str) -> tuple[Any | None, Any | None]:
    """Le début et la fin d'un épisode (``None`` : pas trouvés)."""
    ctx = ui.inspection.context()
    started = next(iter(ctx.events([rt.EPISODE_STARTED], 1, correlations=[corr])), None)
    ended = next(iter(ctx.events([rt.EPISODE_ENDED], 1, correlations=[corr])), None)
    return started, ended


def selection_of(ui: Any, started: Any) -> tuple[Any | None, Any | None, bool]:
    """Le choix de l'arbitre qui a lancé cet épisode : (l'événement ``kernel.selected``, sa ligne
    choisie, exact ?). Exact quand l'épisode porte le numéro du choix (``EpisodeStarted.selected``) ;
    sinon retrouvé d'après le déclencheur (``selected:<tête>`` : le premier choix après cette tête, qui
    a tiré cette sorte envers cette cible). ``(None, None, False)`` : pas lancé par l'arbitre."""
    data = started.data
    trigger = str(data.trigger or "")
    # un prélude (le murmure avant de prendre la parole) n'a ni la sorte ni la cible du choix qui le précède :
    # il suit n'importe quelle ligne tirée
    prelude = trigger.startswith("prélude:")
    kind, target = (None, ANY_TARGET) if prelude else (data.kind, data.target)
    exact = getattr(data, "selected", None)
    if isinstance(exact, int) and exact > 0:
        e = _decoded(ui, exact)
        if e is not None and e.type.name == SELECTED.name:
            return e, _fired_row(e.data, kind, target), True
    if prelude:
        trigger = trigger[len("prélude:"):]
    if not trigger.startswith("selected:"):
        return None, None, False
    try:
        head = int(trigger[len("selected:"):])
    except ValueError:
        return None, None, False
    seqs = [int(r[0]) for r in ui.kernel.mind.store.query_mind(
        "SELECT seq FROM events WHERE type=? AND seq>? AND seq<? ORDER BY seq LIMIT ?",
        (SELECTED.name, head, started.seq, SELECTION_LOOKUP))]
    candidates = [ui.decode(s) for s in ui.kernel.mind.store.get_events(seqs)]
    for e in sorted(candidates, key=lambda x: x.seq):
        row = _fired_row(e.data, kind, target)
        if row is not None:
            return e, row, False
    return None, None, False


#: une cible quelconque (``_fired_row``) : un prélude suit la ligne tirée, quelle que soit sa cible
ANY_TARGET = "\x00quelconque"


def _fired_row(d: Any, kind: str | None, target: str | None) -> Any | None:
    """La ligne tirée d'un choix, si elle correspond à cette sorte (``None`` : n'importe laquelle) et
    à cette cible (une cible absente : « personne » ou « n'importe qui » ; ``ANY_TARGET`` : toute)."""
    for key in d.fired:
        k, _, t = key.partition(":")
        if kind is not None and k != kind:
            continue
        if target is not None and target != ANY_TARGET and t != target:
            continue
        if target is None and t not in ("none", "any"):
            continue
        return next((r for r in d.rows if r.kind == k and r.target == t), None)
    return None


def trace_of(ui: Any, corr: str) -> dict[str, Any] | None:
    traces = ui.kernel.ports.get("traces")
    got = traces.get(corr) if traces is not None else None
    return got if isinstance(got, dict) else None


# ── les morceaux de la page ──────────────────────────────────────────────


def cause_blocks(ui: Any, started: Any | None) -> list[Any]:
    """Ce qui l'a fait parler : le message auquel elle répondait, ou l'arbitre."""
    if started is None:
        return [Note("Le début de cet épisode n'est pas au journal : on ne sait pas ce qui l'a déclenché.", "muted")]
    data = started.data
    out: list[Any] = []
    trigger = str(data.trigger or "")
    if data.reply_to:
        asked = _decoded(ui, int(data.reply_to))
        text = getattr(getattr(asked.data, "text", None), "text", None) if asked is not None else None
        who = ui.names.who(getattr(asked.data, "handle", None) or data.target) if asked is not None else \
            ui.names.who(data.target)
        lead = "Elle répondait au message de" if not trigger.startswith("reprise:") else \
            "Elle a repris, après une interruption, sa réponse au message de"
        out.append(Note(f"{lead} {who}. Une réponse ne se décide pas : un message attend toujours la sienne.",
                        "info", title="Une réponse"))
        out.append(Fields((("le message", Ref("event", str(data.reply_to), f"message n° {data.reply_to}")),
                           ("ce qu'il disait", Text(text or "(oublié)", clamp=600)))))
        return out
    event, row, exact = selection_of(ui, started)
    if event is not None and row is not None:
        d = event.data
        others = [r for r in d.rows if not (r.kind == row.kind and r.target == row.target)]
        how = "le choix exact de l'arbitre" if exact else "le choix de l'arbitre retrouvé d'après le déclencheur"
        if trigger.startswith("prélude:"):
            lead = f"Un {names.kind(started.data.kind)} juste avant d'agir d'elle-même"
        elif row.kind == "INITIATIVE":
            lead = "Elle a pris la parole d'elle-même"
        else:
            lead = "Elle s'y est mise d'elle-même"
        out.append(Note(
            f"{lead} : la ligne « {ui.names.arbiter_row(row.kind, row.target)} » avait un score de "
            f"{num_fr(row.score, 2, signed=True)} — au plus {num_fr(row.hazard * 3600, 2)} fois par heure. Parmi "
            f"{getattr(d, 'candidates', 0) or len(d.rows)} ligne(s), le tirage ({num_fr(d.draw, 3)}) l'a retenue "
            f"({how}).", "info", title=f"Décidé par l'arbitre · {names.kind(row.kind)}"))
        out.append(waterfall(ui, row, title="Pourquoi cette ligne : du signal au score"))
        out.append(Fields((("le choix", Ref("event", str(event.seq), f"événement n° {event.seq}")),
                           ("quand", When(event.at)))))
        if others:
            out.append(Disclosure(f"Les autres lignes à ce moment-là ({len(others)})", (
                Table((Column("ligne"), Column("ce qui pousse"), Column("score", "num"), Column("fois / h", "num"),
                       "ce qui l'empêche"), arbiter_rows(ui, others), title="Les lignes non retenues"),)))
        return out
    if trigger.startswith(("selected:", "prélude:")):
        return [Note("Lancé par l'arbitre, mais son choix n'a pas été retrouvé au journal.", "muted")]
    reason = ", ".join(ui.names.reason("", r) for r in str(data.reason or "").split(",") if r)
    return [Note(f"Déclenché autrement (« {trigger or '—'} »)" + (f" : {reason}." if reason else "."), "muted")]


def prompt_blocks(ui: Any, trace: dict[str, Any] | None, sections: Sequence[str]) -> list[Any]:
    """Les sections du prompt, nommées en français : gardées, rognées, coupées (et pourquoi)."""
    compose = (trace or {}).get("compose") or {}
    if not compose:
        if not sections:
            return [Note("Le détail du prompt n'a pas été gardé (plus de 14 jours, oubli, ou épisode ancien).",
                         "muted")]
        return [Table((Column("section"), Column("clé", detail=True)), tuple(
            (ui.names.section(k), Text(k, "mono")) for k in sections),
            title="Les sections qu'elle avait sous les yeux",
            caption="La trace détaillée n'a pas été gardée : seule leur liste est au journal.")]
    sizes = {k: v for k, v in (compose.get("sizes") or ())}
    total = max(1, sum(sizes.values()))
    trimmed = set(compose.get("trimmed") or ())
    rows = [Row((ui.names.section(k), num_fr(sizes.get(k, 0)) if k in sizes else "—",
                 Meter(sizes.get(k, 0) / total), Badge("rognée", "warn") if k in trimmed else Badge("gardée", "ok"),
                 Text(k, "mono")), tone="warn" if k in trimmed else "")
            for k in compose.get("included") or ()]
    rows += [Row((ui.names.section(k), "—", None, Badge(f"coupée : {why}", "muted"), Text(k, "mono")), tone="muted")
             for k, why in compose.get("dropped") or ()]
    return [Table((Column("section"), Column("caractères", "num"), Column("part"), Column("état"),
                   Column("clé", detail=True)), tuple(rows),
                  title=f"Les sections de son prompt · {num_fr(int(compose.get('chars', 0) or 0))} caractères, "
                        f"{compose.get('history_turns', 0)} tour(s) de conversation",
                  caption="Une section rognée a perdu sa fin faute de place ; une coupée n'a pas été montrée.")]


def recall_blocks(ui: Any, provenance: Sequence[str]) -> list[Any]:
    """Ce qui l'a nourrie : chaque souvenir, croyance, promesse, échange, but, projet, avec son texte."""
    if not provenance:
        return [Note("Aucun souvenir ni objet n'a nourri cette parole (rien n'était cité dans son prompt).",
                     "muted")]
    refs = [_split(p) for p in provenance[:RECALL_MAX]]
    items = _memory_items(ui, [n for kind, n in refs if kind == "memory" and n is not None])
    chunks = _chunks(ui, [n for kind, n in refs if kind == "chunk" and n is not None])
    kinds = {memory_c.SOUVENIR: "souvenir", memory_c.BELIEF: "croyance", memory_c.PROMISE: "promesse"}
    rows = []
    for (kind, n), raw in zip(refs, provenance[:RECALL_MAX], strict=True):
        if kind == "memory" and n is not None:
            item_kind, text = items.get(n, ("", None))
            rows.append(Row((Badge(kinds.get(item_kind, "souvenir"), "info"),
                             Text(text or "(oublié ou effacé depuis)", clamp=400),
                             Ref("event", str(n), f"n° {n}"))))
        elif kind == "chunk" and n is not None:
            said, reply = chunks.get(n, (None, None))
            text = " → ".join(x for x in (said, reply) if x) or "(oublié ou effacé depuis)"
            rows.append(Row((Badge("échange passé", "info"), Text(text, clamp=400), Text(f"n° {n}", "muted"))))
        elif kind == "goal" and n is not None:
            rows.append(Row((Badge("but", "info"), "un de ses buts", Ref.subject("goal", str(n), f"but n° {n}"))))
        elif kind == "project" and n is not None:
            rows.append(Row((Badge("projet", "info"), "un de ses projets",
                             Ref.subject("project", str(n), f"projet n° {n}"))))
        elif kind == "dream":
            rows.append(Row((Badge("rêve", "info"), "son rêve de la nuit", Text(raw, "mono"))))
        elif n is not None:
            rows.append(Row((Badge(kind or "événement", "muted"), "—", Ref("event", str(n), f"n° {n}"))))
        else:
            rows.append(Row((Badge("autre", "muted"), "—", Text(raw, "mono"))))
    more = [Note(f"… et {len(provenance) - RECALL_MAX} autre(s).", "muted")] if len(provenance) > RECALL_MAX else []
    return [Table((Column("quoi", "fit"), "ce qu'elle en avait sous les yeux", Column("où", "fit")), tuple(rows),
                  title=f"Ce dont elle s'est souvenue ({len(provenance)})"), *more]


def _split(ref: str) -> tuple[str, int | None]:
    head, _, tail = ref.partition(":")
    try:
        return head, int(tail)
    except ValueError:
        return head, None


def _memory_items(ui: Any, ids: Sequence[int]) -> dict[int, tuple[str, str | None]]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    got = call(ui.kernel.mind.store.query_mind,
               f"SELECT id, kind, text FROM {memory_c.ITEMS_TABLE} WHERE id IN ({marks})", tuple(ids),
               label="souvenirs d'une parole")
    return {} if isinstance(got, Failed) else {int(r[0]): (str(r[1]), r[2] or None) for r in got}


def _chunks(ui: Any, ids: Sequence[int]) -> dict[int, tuple[str | None, str | None]]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    got = call(ui.kernel.mind.store.query_mind,
               f"SELECT id, user_text, reply_text FROM {memory_c.CHUNKS_TABLE} WHERE id IN ({marks})", tuple(ids),
               label="échanges d'une parole")
    return {} if isinstance(got, Failed) else {int(r[0]): (r[1] or None, r[2] or None) for r in got}


def tools_blocks(ui: Any, trace: dict[str, Any] | None, utterance: Any) -> list[Any]:
    """Les outils appelés : leurs arguments et leurs résultats (la trace), sinon leurs noms (le journal)."""
    calls = [t for t in (trace or {}).get("tool_calls") or () if isinstance(t, dict)]
    if calls:
        return [Table(("outil", "issue", Column("durée", "num"), "arguments", "résultat"), tuple(
            Row((Text(str(t.get("name", "?")), "mono"), Badge("réussi" if t.get("ok") else "échec",
                                                               "ok" if t.get("ok") else "danger"),
                 f"{num_fr(int(t.get('duration_us') or 0) / 1000, 0)} ms",
                 Text(_args(t.get("args", "")), "mono", clamp=240), Text(str(t.get("result", "")), clamp=400)),
                tone="" if t.get("ok") else "danger") for t in calls), title=f"Ce qu'elle a fait ({len(calls)} outil(s))")]
    used = tuple(getattr(utterance.data, "tools", ()) or ())
    if not used:
        return [Note("Elle n'a utilisé aucun outil pour dire ça.", "muted")]
    return [Table(("outil", "issue"), tuple((Text(t.name, "mono"), Badge("réussi" if t.ok else "échec",
                                                                         "ok" if t.ok else "danger")) for t in used),
                  title="Ce qu'elle a fait", caption="La trace détaillée (arguments, résultats) n'a pas été gardée.")]


def _args(raw: Any) -> str:
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=1) if isinstance(raw, str) else str(raw)
    except ValueError:
        return str(raw)


def why_page(ui: Any, seq: int) -> dict[str, Any] | None:
    """La page d'une parole, ou ``None`` si ce numéro n'en est pas une."""
    utterance = _decoded(ui, seq)
    if utterance is None or utterance.type.name != rt.UTTERANCE.name:
        return None
    d = utterance.data
    corr = utterance.correlation
    started, ended = episode_events(ui, corr)
    trace = trace_of(ui, corr)
    text = d.text.text
    issue = names.outcome(ended.data.outcome, ended.data.kind) if ended is not None else ("en cours", "warn")
    facts = [("à", ui.names.who_cell(d.target)), ("quand", When(utterance.at)),
             ("épisode", Ref("episode", corr, names.kind(d.kind))), ("issue", Badge(*issue)),
             ("voix", f"{names.role(d.voice.role)} · {d.voice.model or '—'}"),
             ("visible", "dans le fil" if d.visible else "pas dans le fil")]
    blocks: list[Any] = [
        Prose(text or "(oublié : le texte a été effacé)", "Ce qu'elle a dit", reading=True),
        Section("Ce qui l'a fait parler", tuple(cause_blocks(ui, started))),
        Section("Ce qu'elle avait sous les yeux", (
            *prompt_blocks(ui, trace, tuple(d.sections)),
            Fields((("le prompt exact", Ref("episode", corr, "le voir en entier, tel qu'envoyé au modèle",
                                            (("onglet", "prompt"),))),)))),
        Section("Ce dont elle s'est souvenue", tuple(recall_blocks(ui, tuple(d.provenance)))),
        Section("Ce qu'elle a fait", tuple(tools_blocks(ui, trace, utterance))),
        Disclosure("Détails techniques", (Fields((
            ("parole", Text(f"événement n° {utterance.seq}", "mono")), ("épisode", Text(corr, "mono")),
            ("déclencheur", Text(str(started.data.trigger) if started else "—", "mono")),
            ("raisons", Text(str(started.data.reason) if started and started.data.reason else "—", "mono")),
            ("appel", Text(d.voice.call_id or "—", "mono")),
            ("persona", Text((d.voice.persona_hash or "—")[:16], "mono")),
            ("sections", Text(", ".join(d.sections) or "—", "mono")),
            ("provenance", Text(", ".join(d.provenance) or "—", "mono")),
        )), Code(json.dumps(json.loads(d.model_dump_json()), ensure_ascii=False, indent=1), "L'énoncé au journal"))),
    ]
    return {"title": "Pourquoi a-t-elle dit ça ?", "subtitle": f"« {(text or '(oublié)')[:160]} »",
            "facts": facts, "blocks": blocks, "correlation": corr}
