"""« Pourquoi a-t-elle dit ça ? » : une page par parole.

Tout ce qui explique une phrase, à un seul endroit et en mots :

1. **ce qu'elle a dit**, à qui, quand ;
2. **ce qui l'a fait parler** — le message auquel elle répondait, ou la ligne
   exacte de l'arbitre qui l'a fait prendre la parole (chaque preuve, chaque
   modulation, le seuil, le score, le taux, le tirage) ;
3. **son humeur à ce moment-là** — ce qu'elle a déclaré ressentir en le
   disant, ce qu'elle lisait chez l'autre, et ce que son prompt disait de sa vie
   intérieure ; **ce qu'elle avait sous les yeux** — les sections du prompt,
   nommées en français, gardées, rognées ou coupées (et pourquoi), le texte de
   chacune, et le contexte complet tel qu'envoyé ;
4. **ce dont elle s'est souvenue** — les souvenirs, croyances, promesses,
   échanges, buts et projets qui l'ont nourrie, avec leur texte et un lien ;
5. **ce qu'elle a fait** — les outils qu'elle avait en main, ceux qu'elle a
   appelés, leurs arguments et leurs résultats ;
6. **sa réponse, pas à pas** — ce que le modèle principal a répondu (le
   premier jet, balises comprises), la relecture, puis l'autrice : ce qu'elle a
   lu, ce qu'elle a rendu, et laquelle des deux est partie.

Elle se lit dans le journal (l'énoncé, le début d'épisode, le choix de
l'arbitre) et dans la trace de l'épisode (``runtime/traces.py``, 14 jours) ;
quand la trace n'existe plus, la page le dit et montre ce que le journal
garde. Les identifiants techniques restent dans « Détails techniques ».

La question inverse a la même adresse : le numéro d'un message reçu resté
sans réponse mène à « Pourquoi n'a-t-elle pas répondu ? » (``silence_page``) —
la fin d'épisode qui l'a réglé (``EpisodeEnded.unanswered``), sa cause en mots
(un silence choisi, ce qui l'a fait taire, trop tard, une panne), et selon le
cas ce qu'elle avait sous les yeux, ses outils, ou l'appel de modèle en échec.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import select

from mika.contracts import expression as expression_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.inspector import names, render
from mika.inspector.catalog import Panel
from mika.inspector.pages.decisions import arbiter_rows, waterfall
from mika.kernel.builtin import SELECTED
from mika.kernel.faculty import Zone
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
from mika.kernel.prompt import HEADER_FMT
from mika.ports.delivery import TOO_LATE
from mika.ports.journal import JournalEvent
from mika.runtime.boundary import Failed, call
from mika.runtime.traces import STABLE_KEY
from mika.vocab import affect as A
from mika.vocab.episodes import Tag
from mika.vocab.reading import Reading

#: au-delà, l'arbitre a pu choisir plus tôt : le choix d'un départ se cherche dans ces événements-ci
SELECTION_LOOKUP = 50
#: une provenance montre au plus tant de souvenirs (une parole en cite rarement plus)
RECALL_MAX = 60
#: la fin qui a laissé un message sans réponse se cherche parmi tant de fins d'épisode qui le suivent
SILENCE_LOOKUP = 500
#: une panne montre au plus tant d'appels de modèle de son épisode
CALLS_MAX = 20


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
    e = JournalEvent
    seqs = [int(r[0]) for r in ui.kernel.mind.store.query_mind(
        select(e.seq).where(e.type == SELECTED.name, e.seq > head, e.seq < started.seq).order_by(e.seq)
        .limit(SELECTION_LOOKUP))]
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
    texts = section_texts(ui, trace)
    rows = [Row((ui.names.section(k), num_fr(sizes.get(k, 0)) if k in sizes else "—",
                 Meter(sizes.get(k, 0) / total), Badge("rognée", "warn") if k in trimmed else Badge("gardée", "ok"),
                 Text(k, "mono")), tone="warn" if k in trimmed else "",
                detail=(Prose(texts[k], "Ce qu'elle y lisait", clamp=1500),) if texts.get(k) else ())
            for k in compose.get("included") or ()]
    rows += [Row((ui.names.section(k), "—", None, Badge(f"coupée : {why}", "muted"), Text(k, "mono")), tone="muted")
             for k, why in compose.get("dropped") or ()]
    return [Table((Column("section"), Column("caractères", "num"), Column("part"), Column("état"),
                   Column("clé", detail=True)), tuple(rows),
                  title=f"Les sections de son prompt · {num_fr(int(compose.get('chars', 0) or 0))} caractères, "
                        f"{compose.get('history_turns', 0)} tour(s) de conversation",
                  caption="Une section rognée a perdu sa fin faute de place ; une coupée n'a pas été montrée. "
                          "Le détail d'une ligne montre ce que la section disait.")]


def section_texts(ui: Any, trace: Mapping[str, Any] | None) -> dict[str, str]:
    """Le texte de chaque section, retrouvé dans le prompt gardé : son ancre (``ComposeTrace.anchors`` : son en-tête,
    ou ses premiers caractères ; pour une trace d'avant elles, l'en-tête du titre déclaré au registre), puis sa taille
    rendue (``sizes``), l'en-tête retiré. La zone stable se cherche dans le système, la volatile dans le dernier tour
    — jamais dans l'historique, où un message tapé pourrait imiter un en-tête —, chacune après la précédente."""
    if not trace:
        return {}
    compose = trace.get("compose") or {}
    anchors = dict(compose.get("anchors") or ()) or {
        s.key: HEADER_FMT.format(title=s.title) + "\n" for s in ui.kernel.registry.sections
        if s.title and s.zone is not Zone.HISTORY}
    messages = [m for m in trace.get("messages") or () if isinstance(m, dict)]
    texts = [str(trace.get(STABLE_KEY) or ""), str(messages[-1].get("content") or "") if messages else ""]
    after = [0] * len(texts)
    out: dict[str, str] = {}
    for key, size in compose.get("sizes") or ():
        anchor = anchors.get(key)
        if not anchor:
            continue
        for i, text in enumerate(texts):
            at = text.find(anchor, after[i])
            if at >= 0:
                out[key] = _HEADER.sub("", text[at:at + int(size)], count=1)
                after[i] = at + int(size)
                break
    return out


#: la ligne d'en-tête d'une section (``HEADER_FMT``), en tête de son bloc
_HEADER = re.compile("^" + re.escape(HEADER_FMT).replace(re.escape("{title}"), ".+?") + "\n")


def context_parts(trace: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Le prompt du premier tour, tel qu'envoyé au modèle, en parties titrées : le système (persona, sections stables,
    outils), la partie volatile quand elle voyage à part, puis chaque tour — le dernier porte son état interne et le
    message."""
    out: list[tuple[str, str]] = []
    if trace.get(STABLE_KEY):
        out.append(("La partie stable (persona, en cache)", str(trace[STABLE_KEY])))
    if trace.get("system_volatile"):
        out.append(("La partie volatile", str(trace["system_volatile"])))
    for m in trace.get("messages") or ():
        role = m.get("role", "?") if isinstance(m, dict) else "?"
        content = m.get("content", "") if isinstance(m, dict) else str(m)
        out.append(({"user": "Tour (entrée)", "assistant": "Tour (elle)", "tool": "Résultat d'outil"}.get(role, role),
                    str(content)))
    return out


def context_blocks(trace: Mapping[str, Any]) -> list[Any]:
    """Le prompt du premier tour (``context_parts``), une prose par partie."""
    return [Prose(text, title, clamp=1200 if i == 0 else 1500) for i, (title, text) in enumerate(context_parts(trace))]


def inner_state(ui: Any, trace: Mapping[str, Any] | None, utterance: Any) -> tuple[list[tuple[str, str]], bool]:
    """Ce que son prompt disait de sa vie intérieure : les sections affectives de la zone volatile qu'il montrait, avec
    leur texte tel qu'envoyé — et s'il en manque un (la trace a expiré, ou a été oubliée)."""
    inner = {s.key for s in ui.kernel.registry.sections if s.zone is Zone.VOLATILE and Tag.AFFECTIVE in s.tags}
    texts = section_texts(ui, trace)
    shown = [k for k in utterance.data.sections if k in inner]
    return [(ui.names.section(k), texts[k]) for k in shown if texts.get(k)], any(not texts.get(k) for k in shown)


def mood_blocks(ui: Any, trace: Mapping[str, Any] | None, utterance: Any) -> list[Any]:
    """Son humeur à ce moment-là : ce qu'elle a déclaré ressentir en le disant (sa balise, ADR 0093), ce qu'elle lisait
    chez l'autre (``[EN_FACE]``), et ce que son prompt disait de sa vie intérieure (``inner_state``)."""
    pairs: list[tuple[str, Any]] = []
    felt = _felt(utterance)
    if felt is not None:
        pairs.append(("ce qu'elle ressentait en le disant", _facets(felt.all)))
    their = _their(utterance)
    if their:
        pairs.append(("ce qu'elle lisait chez l'autre", their))
    state, missing = inner_state(ui, trace, utterance)
    pairs += [(label, Text(text, clamp=600)) for label, text in state]
    if not pairs:
        return [Note("Ni balise d'émotion dans sa réponse, ni section de sa vie intérieure dans son prompt.", "muted")]
    out: list[Any] = [Fields(tuple(pairs))]
    if missing:
        out.append(Note(MISSING_STATE, "muted"))
    return out


MISSING_STATE = ("Le texte de son état n'est plus gardé (la trace a expiré, ou a été oubliée) : seule la balise de sa "
                 "réponse reste.")


def _felt(utterance: Any) -> A.Declared | None:
    """Ce qu'elle a déclaré ressentir en le disant (sa balise ``[EMOTION]``)."""
    return A.Declared.decode(utterance.data.annotation(expression_c.EMOTION_ANNOTATION))


def _their(utterance: Any) -> str:
    """Ce qu'elle lisait chez l'autre (``[EN_FACE]``), en mots ; vide : rien de déclaré."""
    their = Reading.decode(utterance.data.annotation(expression_c.READING_ANNOTATION))
    if their is None or not (their.felt or their.gesture or their.grave):
        return ""
    read = _facets(their.felt) if their.felt else "rien de particulier"
    more = [x for x in (their.gesture and f"geste : {their.gesture}", their.grave and f"grave : {their.grave}") if x]
    return " · ".join([read, *more])


def _facets(felt: Sequence[tuple[str, float]]) -> str:
    """Des facettes en mots : « contente 0,40 · anxieuse 0,20 »."""
    return " · ".join(f"{_word(name)} {num_fr(x, 2)}" for name, x in felt)


def _word(name: str) -> str:
    emotion = A.emotion_of(name)
    return A.FR[emotion] if emotion is not None else name


def answer_blocks(ui: Any, trace: Mapping[str, Any] | None, utterance: Any) -> list[Any]:
    """Sa réponse, pas à pas : ce que le modèle principal a répondu (le texte brut, balises comprises), la relecture,
    puis l'autrice (ADR 0114, 0124) — son contexte, sa réponse, et si c'est elle qui est partie."""
    if not trace:
        return [Note("La trace de cet épisode n'est plus gardée (14 jours, oubli) : seul ce qui est parti reste.",
                     "muted")]
    out: list[Any] = []
    responses = [r for r in trace.get("responses") or () if isinstance(r, dict)]
    model = (responses[-1].get("model") if responses else "") or utterance.data.voice.model or "—"
    if trace.get("reply"):
        out.append(Prose(str(trace["reply"]), f"La réponse principale · {names.role(trace.get('role'))} · {model}",
                         clamp=1500))
    review = trace.get("relecture")
    if isinstance(review, dict):
        out.append(Fields((("la remarque", Text(str(review.get("remarque") or "—"))),
                           ("avant la relecture", Text(str(review.get("premier_jet") or "—"), clamp=600))),
                          title="La relecture lui a fait récrire sa réponse"))
    authored = author_blocks(trace)
    if not authored and trace.get("reply"):
        authored = [Note("Aucune autrice ne l'a récrite : la réponse principale est partie telle quelle, ses balises "
                         "retirées.", "muted")]
    return [*out, *authored] or [Note("Le modèle principal n'a rien rendu de gardé pour cet épisode.", "muted")]


def author_blocks(trace: Mapping[str, Any]) -> list[Any]:
    """L'autrice qui a récrit sa réponse (``naturel`` dans la trace) : qui, laquelle des deux est partie, son contexte
    et sa réponse brute ; rien quand aucune autrice n'est passée."""
    author = trace.get("naturel")
    if not isinstance(author, dict):
        return []
    dropped = author.get("ecartee")
    out: list[Any] = [Fields((
        ("autrice", Text(str(author.get("autrice") or "—"), "mono")),
        ("issue", Badge(f"écartée : {dropped} — le premier jet est parti", "warn") if dropped
         else Badge("retenue : c'est son texte qui est parti", "ok")),
        ("le premier jet qu'elle a récrit", Text(str(author.get("premier_jet") or "—"), clamp=600)),
    ), title="L'autrice")]
    if not (author.get("systeme") or author.get("message")):
        out.append(Note("Le contexte et la réponse de l'autrice n'étaient pas encore gardés quand elle a parlé.",
                        "muted"))
        return out
    if author.get("systeme"):
        out.append(Prose(str(author["systeme"]), "Le contexte de l'autrice · son système", clamp=1200))
    if author.get("message"):
        out.append(Prose(str(author["message"]), "Le contexte de l'autrice · le fil et le brouillon", clamp=1500))
    out.append(Prose(str(author["reponse"]), "La réponse de l'autrice", clamp=1500) if author.get("reponse")
               else Note("L'autrice n'a rien rendu (une panne avant sa réponse).", "muted"))
    return out


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
    v = memory_c.LEDGER
    got = call(ui.kernel.mind.store.query_mind, select(v.c.id, v.c.kind, v.c.text).where(v.c.id.in_(list(ids))),
               label="souvenirs d'une parole")
    return {} if isinstance(got, Failed) else {int(r[0]): (str(r[1]), r[2] or None) for r in got}


def _chunks(ui: Any, ids: Sequence[int]) -> dict[int, tuple[str | None, str | None]]:
    if not ids:
        return {}
    t = memory_c.chunks_table()
    got = call(ui.kernel.mind.store.query_mind,
               select(t.c.id, t.c.user_text, t.c.reply_text).where(t.c.id.in_(list(ids))),
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


def offered_blocks(trace: Mapping[str, Any] | None) -> list[Any]:
    """Les outils qu'elle avait en main (la trace : ceux déclarés au modèle au premier tour)."""
    if not trace or "tools" not in trace:
        return []
    offered = sorted(str(n) for n in trace.get("tools") or ())
    if not offered:
        return [Note("Aucun outil ne lui était offert.", "muted")]
    return [Fields((("offerts", Text(", ".join(offered), "mono", clamp=300)),),
                   title=f"Les outils qu'elle avait en main ({len(offered)})")]


def _args(raw: Any) -> str:
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=1) if isinstance(raw, str) else str(raw)
    except ValueError:
        return str(raw)


def verdict_blocks(ui: Any, seq: int) -> list[Any]:
    """L'avis de son opératrice sur cette réponse, donné depuis le chat (ADR 0113) : le plus récent vaut."""
    judged = next(iter(ui.inspection.context().events([transcript_c.JUDGED], 1, where=("seq", seq))), None)
    if judged is None or not judged.data.verdict:
        return []
    d = judged.data
    ok = d.verdict == transcript_c.VERDICT_OK
    note = d.comment.text if d.comment is not None else None
    return [Section("Ton avis", (Fields((
        ("sa réponse était", Badge("adaptée", "ok") if ok else Badge("pas adaptée", "warn")),
        ("ce qu'elle aurait dû dire", Text(note or "—")),
        ("donné", When(judged.at)),
        ("par", ui.names.who_cell(d.by)),
    )),))]


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
    if d.mode:
        # demandée en mode pro (ADR 0116) : ni sa voix de chat, ni son tempérament, ni la seconde passe
        facts.append(("mode", Badge(f"{d.mode} — un travail demandé", "info")))
    context = context_blocks(trace) if trace else []
    blocks: list[Any] = [
        Prose(text or "(oublié : le texte a été effacé)", "Ce qu'elle a dit", reading=True),
        *verdict_blocks(ui, seq),
        Section("Ce qui l'a fait parler", tuple(cause_blocks(ui, started))),
        Section("Son humeur à ce moment-là", tuple(mood_blocks(ui, trace, utterance))),
        Section("Ce qu'elle avait sous les yeux", (
            *prompt_blocks(ui, trace, tuple(d.sections)),
            *([Disclosure("Le contexte complet, tel qu'envoyé au modèle", tuple(context))] if context else []),
            Fields((("le prompt exact", Ref("episode", corr, "dans l'onglet Prompt de l'épisode",
                                            (("onglet", "prompt"),))),)))),
        Section("Ce dont elle s'est souvenue", tuple(recall_blocks(ui, tuple(d.provenance)))),
        Section("Ce qu'elle a fait", (*offered_blocks(trace), *tools_blocks(ui, trace, utterance))),
        Section("Sa réponse, pas à pas", tuple(answer_blocks(ui, trace, utterance))),
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
            "facts": facts, "blocks": blocks, "correlation": corr,
            "view": lambda env, query: why_view(ui, env, query, utterance, started, trace, issue, blocks)}


# ── la page dessinée (ADR 0121) ─────────────────────────────────────────

#: les gabarits des pages dessinées (une parole, un message resté sans réponse), et leur feuille
WHY_TEMPLATE = "handmade/parole/parole.html"
SILENCE_TEMPLATE = "handmade/parole/silence.html"
WHY_STYLES = ("handmade/parole.css",)


def why_panel(got: Mapping[str, Any], env: Any, query: Mapping[str, str], replay: Panel | None = None) -> Panel | None:
    """La page d'une parole, ou d'un message resté sans réponse, dessinée : son gabarit et ce qu'il dessine (``v``),
    inclus dans la page commune avec « Rejouer avec… » s'il y en a un ; ``None`` si ce qu'il dessine ne se lit pas (la
    page retombe sur ses blocs)."""
    view = got.get("view")
    if view is None:
        return None
    drawn = call(view, env, query, label="parole dessinée")
    if isinstance(drawn, Failed):
        return None
    shared = {k: v for k, v in (replay.context if replay is not None else {}).items() if k != "panel_after"}
    return Panel(SILENCE_TEMPLATE if got.get("silence") else WHY_TEMPLATE, {**shared, "v": drawn},
                 styles=WHY_STYLES)


def why_view(ui: Any, env: Any, query: Mapping[str, str], utterance: Any, started: Any | None,
             trace: Mapping[str, Any] | None, issue: tuple[str, str], blocks: Sequence[Any]) -> dict[str, Any]:
    """Ce que dessine ``handmade/parole/parole.html`` : sa phrase en grand et ce qu'elle ressentait, ce qui l'a fait
    parler, sa réponse pas à pas (le modèle principal, la relecture, l'autrice, ce qui est parti), son état intérieur,
    ce qu'elle avait sous les yeux, ses outils. Ce qui n'a pas de forme à lui (la cascade de l'arbitre, ses souvenirs,
    ses appels d'outils, ton avis, les détails techniques) reprend ses blocs, rendus."""
    d = utterance.data

    def drawn(items: Sequence[Any]) -> list[dict[str, Any]]:
        return render.blocks(list(items), env, query, namespace="parole")

    def titled(title: str) -> list[Any]:
        return [b for b in blocks if isinstance(b, Section | Disclosure) and b.title == title]

    felt = _felt(utterance)
    chips = [{"text": issue[0], "tone": issue[1] if issue[1] in ("warn", "danger") else ""},
             {"text": f"{names.role(d.voice.role)} · {d.voice.model or '—'}", "tone": ""},
             {"text": "dans le fil" if d.visible else "pas dans le fil", "tone": ""}]
    if d.mode:
        chips.append({"text": f"mode {d.mode}", "tone": ""})
    author = (trace or {}).get("naturel")
    if isinstance(author, dict):
        chips.append({"text": f"autrice {author.get('autrice') or '—'}" + (" écartée" if author.get("ecartee") else ""),
                      "tone": "warn" if author.get("ecartee") else ""})
    state, missing = inner_state(ui, trace, utterance)
    # ton avis : ses champs en carte titrée ; ses souvenirs : leur tableau, ou rien (la carte dit « aucun »)
    verdict = [replace(f, title="Ton avis") for s in titled("Ton avis") for f in s.items if isinstance(f, Fields)]
    return {
        "text": d.text.text or "(oublié : le texte a été effacé)",
        "to": ui.names.who(d.target), "when": ui.when_long(utterance.at), "chips": chips,
        "felt": _felt_view(felt) if felt is not None else None, "their": _their(utterance),
        "cause": _cause_view(ui, started) or {"blocks": drawn(titled("Ce qui l'a fait parler"))},
        "verdict": drawn(verdict), "steps": answer_steps(trace, utterance), "kept": bool(trace),
        "inner": [{"label": label, "text": text} for label, text in state], "inner_missing": missing,
        "prompt": prompt_view(ui, trace, d.sections), "context": [{"title": t, "text": x} for t, x in context_parts(trace or {})],
        "episode": utterance.correlation,
        "recall": drawn([b for s in titled("Ce dont elle s'est souvenue") for b in s.items]) if d.provenance else [],
        "tools": tools_view(trace, d.tools), "calls": drawn(tools_blocks(ui, trace, utterance)),
        "details": drawn(titled("Détails techniques")),
    }


def _felt_view(felt: A.Declared) -> dict[str, Any]:
    """Sa balise, comme la dessine « En ce moment » : le mot, son intensité, le mélange de ses facettes."""
    facets = felt.all
    total = sum(x for _e, x in facets) or 1.0
    x, shown = 0.0, []
    for name, value in facets:
        width = 100 * value / total
        emotion = A.emotion_of(name)
        shown.append({"emotion": emotion.value if emotion else "neutral", "word": _word(name), "x": round(x, 2),
                      "w": round(width, 2), "share": num_fr(value, 2)})
        x += width
    return {"emotion": felt.emotion.value, "word": A.FR[felt.emotion],
            "how": f"{A.intensity_word(felt.intensity)} · {num_fr(felt.intensity, 2)}", "facets": shown}


def _cause_view(ui: Any, started: Any | None) -> dict[str, Any] | None:
    """Une réponse : le message auquel elle répondait, en bulle ; ``None`` : la cause se dit par ses blocs (l'arbitre,
    un autre déclencheur)."""
    if started is None or not started.data.reply_to:
        return None
    data = started.data
    asked = _decoded(ui, int(data.reply_to))
    text = getattr(getattr(asked.data, "text", None), "text", None) if asked is not None else None
    who = ui.names.who((getattr(asked.data, "handle", None) if asked is not None else None) or data.target)
    resumed = str(data.trigger or "").startswith("reprise:")
    return {"who": who, "text": text or "(oublié)", "when": ui.when_long(asked.at) if asked is not None else "",
            "href": render.href(Ref("event", str(data.reply_to), "")), "number": data.reply_to,
            "lead": (f"Elle a repris, après une interruption, sa réponse au message de {who}." if resumed
                     else f"Elle répondait au message de {who}.") + " Une réponse ne se décide pas : un message "
                                                                    "attend toujours la sienne."}


def answer_steps(trace: Mapping[str, Any] | None, utterance: Any | None) -> list[dict[str, Any]]:
    """Sa réponse, pas à pas : le modèle principal (son texte brut), la relecture, l'autrice (son contexte, sa
    réponse, retenue ou écartée), puis ce qui est parti (``utterance`` : sa parole ; ``None`` : rien n'est parti)."""
    out: list[dict[str, Any]] = []
    if trace:
        responses = [r for r in trace.get("responses") or () if isinstance(r, dict)]
        last = responses[-1] if responses else {}
        usage = last.get("usage") or {}
        model = last.get("model") or (utterance.data.voice.model if utterance is not None else "")
        meta = [names.role(trace.get("role")), str(model or "—")]
        if usage.get("input") or usage.get("output"):
            meta.append(f"{num_fr(int(usage.get('input') or 0))} → {num_fr(int(usage.get('output') or 0))} jetons")
        out.append({"title": "Le modèle principal", "meta": " · ".join(meta),
                    "text": str(trace.get("reply") or ""), "empty": "Rien de gardé de sa réponse."})
        review = trace.get("relecture")
        if isinstance(review, dict):
            out.append({"title": "La relecture", "meta": str(review.get("remarque") or ""),
                        "text": str(review.get("premier_jet") or ""), "label": "avant la relecture"})
        author = trace.get("naturel")
        if isinstance(author, dict):
            dropped = author.get("ecartee")
            out.append({
                "title": f"L'autrice · {author.get('autrice') or '—'}",
                "tag": {"text": f"écartée : {dropped}", "tone": "warn"} if dropped else {"text": "retenue", "tone": "ok"},
                "context": [{"title": t, "text": str(author[k])} for t, k in
                            (("Son système", "systeme"), ("Le fil et le brouillon", "message")) if author.get(k)],
                "text": str(author.get("reponse") or ""),
                "empty": ("L'autrice n'a rien rendu (une panne avant sa réponse)." if author.get("systeme")
                          else "Son contexte et sa réponse n'étaient pas encore gardés quand elle a parlé."),
            })
    author = (trace or {}).get("naturel")
    if isinstance(author, dict) and not author.get("ecartee"):
        sent = "le texte de l'autrice, avec ce que ressentait le premier jet"
    elif isinstance((trace or {}).get("relecture"), dict):
        sent = "sa réponse relue, ses balises retirées"
    else:
        sent = "la réponse principale, ses balises retirées"
    if utterance is not None:
        out.append({"title": "Ce qui est parti", "said": utterance.data.text.text or "(oublié)",
                    "meta": sent if trace else ""})
    return out


def prompt_view(ui: Any, trace: Mapping[str, Any] | None, sections: Sequence[str] = ()) -> dict[str, Any]:
    """Les sections de son prompt : chacune nommée, sa part, son état, son texte ; ou leur seule liste (``sections``,
    le journal)."""
    compose = (trace or {}).get("compose") or {}
    if not compose:
        return {"rows": [{"label": ui.names.section(k), "key": k, "share": 0, "chars": "—", "state": "", "tone": "",
                          "text": ""} for k in sections], "kept": False, "chars": "", "turns": 0}
    sizes = {k: int(v) for k, v in (compose.get("sizes") or ())}
    total = max(1, sum(sizes.values()))
    trimmed = set(compose.get("trimmed") or ())
    texts = section_texts(ui, trace)
    rows = [{"label": ui.names.section(k), "key": k, "share": round(100 * sizes.get(k, 0) / total, 1),
             "chars": num_fr(sizes.get(k, 0)) if k in sizes else "—", "text": texts.get(k, ""),
             "state": "rognée" if k in trimmed else "gardée", "tone": "warn" if k in trimmed else "ok"}
            for k in compose.get("included") or ()]
    rows += [{"label": ui.names.section(k), "key": k, "share": 0, "chars": "—", "text": "",
              "state": f"coupée : {why}", "tone": "muted"} for k, why in compose.get("dropped") or ()]
    return {"rows": rows, "kept": True, "chars": num_fr(int(compose.get("chars", 0) or 0)),
            "turns": int(compose.get("history_turns", 0) or 0)}


def tools_view(trace: Mapping[str, Any] | None, used: Sequence[Any] = ()) -> dict[str, Any]:
    """Ses outils : ceux qu'elle avait en main (la trace), ceux qu'elle a appelés en tête (la trace, sinon ``used`` :
    ceux que sa parole nomme au journal)."""
    called = {str(t.get("name")): bool(t.get("ok")) for t in (trace or {}).get("tool_calls") or ()
              if isinstance(t, dict)} or {t.name: t.ok for t in used}
    offered = sorted({str(n) for n in (trace or {}).get("tools") or ()} | set(called))
    return {"known": bool(trace) and "tools" in (trace or {}), "called": len(called),
            "items": sorted(({"name": n, "called": n in called, "ok": called.get(n, True)} for n in offered),
                            key=lambda t: (not t["called"], t["name"]))}


# ── « Pourquoi n'a-t-elle pas répondu ? » ─────────────────────────────────


def silence_of(ui: Any, seq: int) -> Any | None:
    """La fin d'épisode qui a laissé le message ``seq`` sans réponse (``EpisodeEnded.leaves_unanswered``) : la
    première qui le suit et le dit — celle d'une rafale porte sur son dernier message et règle ceux d'avant.
    ``None`` : pas retrouvée (il a reçu sa réponse, ou sa fin est trop loin)."""
    store = ui.kernel.mind.store
    e = JournalEvent
    seqs = [int(r[0]) for r in store.query_mind(
        select(e.seq).where(e.type == rt.EPISODE_ENDED.name, e.seq > seq).order_by(e.seq).limit(SILENCE_LOOKUP))]
    for stored in store.get_events(seqs):  # dans l'ordre du journal
        e = ui.decode(stored)
        if e.data.leaves_unanswered(seq):
            return e
    return None


def _silence_note(e: Any) -> Note:
    """Ce qui l'a laissé sans réponse, en mots : un silence (choisi par le modèle, ou ce qui l'a fait taire), trop
    tard, une panne, des tentatives épuisées."""
    detail = names.detail(e.detail)
    if e.detail.startswith(TOO_LATE):
        return Note("Trop tard : la question a attendu au-delà du délai de réponse (un arrêt, son sommeil) — elle ne "
                    "répond pas en retard à une question dépassée.", "warn", title="Trop tard")
    if e.outcome == "abstained":
        if e.detail:
            return Note(f"Elle s'est tue : {detail}. Ce n'est pas une panne.", "info", title="Un silence")
        return Note("Elle a choisi de se taire : le modèle a lu ce qui suit et n'a rien répondu. Ce n'est pas une "
                    "panne.", "info", title="Un silence choisi")
    if e.outcome in ("failed", "timeout"):
        cause = detail or ("délai dépassé" if e.outcome == "timeout" else "échec sans détail")
        return Note(f"Une panne : {cause}. Ce n'est pas un choix : elle n'a pas pu répondre.", "danger",
                    title="Une panne")
    return Note(f"{names.outcome(e.outcome)[0].capitalize()}, et ses tentatives de réponse étaient épuisées : la "
                "question n'a pas été reprise.", "warn", title="Abandonnée")


def calls_blocks(ui: Any, corr: str) -> list[Any]:
    """Les appels de modèle d'un épisode : lequel a échoué, chez quel fournisseur."""
    calls = ui.deps.calls
    if calls is not None and hasattr(calls, "for_correlation"):
        traces = calls.for_correlation(corr, limit=CALLS_MAX)
    else:
        traces = [t for t in list(ui.deps.traces) if str(getattr(t, "call_id", "")).startswith(corr)][:CALLS_MAX]
    if not traces:
        return [Note("Aucun appel de modèle retrouvé : la panne est arrivée avant l'appel (aucun modèle configuré, "
                     "une erreur en préparant le prompt), ou le registre des appels a été vidé.", "muted")]
    return [Table(("rôle", "fournisseur", "modèle", Column("durée", "num"), "issue"), tuple(
        Row((names.role(t.role), t.backend or "—", Text(t.model or "—", "mono"), f"{num_fr(t.latency_us / 1e6, 1)} s",
             Badge("réussi", "ok") if t.outcome == "ok" else Badge(names.detail(t.outcome), "danger")),
            tone="" if t.outcome == "ok" else "danger") for t in traces), title="Ses appels au modèle"),
            Fields((("le détail", Ref("episode", corr, "attente, jetons et coût de chaque appel",
                                      (("onglet", "appels"),))),))]


def silence_page(ui: Any, seq: int) -> dict[str, Any] | None:
    """« Pourquoi n'a-t-elle pas répondu ? » : la page d'un message reçu resté sans réponse (ou qui l'attend
    encore), ou ``None`` si ce numéro n'en est pas un (une de ses paroles, un message auquel elle a répondu). Ses blocs,
    et sa vue dessinée (``silence.html``)."""
    asked = _decoded(ui, seq)
    if asked is None or asked.type.name != rt.PERCEPTION_RECEIVED.name:
        return None
    d = asked.data
    text = d.text.text
    page: dict[str, Any] = {"title": "Pourquoi n'a-t-elle pas répondu ?",
                            "subtitle": f"« {(text or '(oublié)')[:160]} »", "correlation": "", "silence": True}
    facts: list[tuple[str, Any]] = [("de", ui.names.who_cell(d.handle)), ("reçu", When(asked.at)),
                                    ("où", f"salon « {d.room} »" if d.room else "en privé")]
    blocks: list[Any] = [Prose(text or "(oublié : le texte a été effacé)", "Ce qu'on lui a écrit", reading=True)]
    view: dict[str, Any] = {"text": text or "(oublié : le texte a été effacé)", "from": ui.names.who(d.handle),
                            "when": ui.when_long(asked.at), "where": f"salon « {d.room} »" if d.room else "en privé"}

    def drawn(state: Note, more: Mapping[str, Any] | None = None) -> Any:
        return lambda env, query: {**view, "state": {"title": state.title, "text": state.text, "tone": state.tone},
                                   **{k: (v(env, query) if callable(v) else v) for k, v in (more or {}).items()}}

    if not d.addressed:
        note = Note("Ce message ne lui était pas adressé : dans un salon, elle entend tout mais ne répond qu'à ce qui "
                    "lui parle (son nom, une réponse à l'un de ses messages).", "info", title="Pas pour elle")
        return {**page, "facts": facts, "blocks": [*blocks, note], "view": drawn(note)}
    if seq in ui.names.frame().get(rt.AWAITING):
        note = Note("Sa réponse est en attente : elle y travaille, ou elle dort et y répondra à son réveil.", "warn",
                    title="En attente")
        return {**page, "facts": [*facts, ("issue", Badge("en attente", "warn"))], "blocks": [*blocks, note],
                "view": drawn(note)}
    ended = silence_of(ui, seq)
    if ended is None:
        return None
    e, corr = ended.data, ended.correlation
    # une fin écrite sans épisode (une question abandonnée, trop vieille ou sans place) n'a ni prompt ni appel
    started, _end = episode_events(ui, corr)
    trace = trace_of(ui, corr)
    facts.append(("issue", Badge(*names.outcome(e.outcome, e.kind))))
    if started is not None:
        facts.append(("épisode", Ref("episode", corr, names.kind(e.kind))))
    state = _silence_note(e)
    cause: list[Any] = [state]
    burst = ""
    if e.reply_to is not None and e.reply_to != seq:
        burst = (f"Ce message faisait partie d'une rafale : la fin porte sur le dernier (n° {e.reply_to}), qu'elle "
                 "aurait lu avec celui-ci.")
        cause.append(Note(burst, "muted"))
    cause.append(Fields((("la fin", Ref("event", str(ended.seq), f"événement n° {ended.seq}")),
                         ("réglé", When(ended.at)),
                         ("elle s'y est mise", When(started.at) if started is not None else "—"))))
    blocks.append(Section("Pourquoi elle n'a pas répondu", tuple(cause)))
    failed = started is not None and e.outcome in ("failed", "timeout")
    if started is not None:
        if failed:
            blocks.append(Section("L'appel au modèle", tuple(calls_blocks(ui, corr))))
        if (trace or {}).get("compose"):
            seen = [*prompt_blocks(ui, trace, ()), Fields((("le prompt exact", Ref(
                "episode", corr, "le voir en entier, tel qu'envoyé au modèle", (("onglet", "prompt"),))),))]
        else:
            seen = [Note(UNKEPT_PROMPT, "muted")]
        blocks.append(Section("Ce qu'elle avait sous les yeux", tuple(seen)))
        if any(isinstance(t, dict) for t in (trace or {}).get("tool_calls") or ()):
            did = tools_blocks(ui, trace, None)
        elif (trace or {}).get("compose"):
            did = [Note("Elle n'a appelé aucun outil.", "muted")]
        else:
            did = [Note("La trace n'est pas gardée : on ne sait pas quels outils elle a appelés.", "muted")]
        blocks.append(Section("Ce qu'elle a fait", tuple(did)))
    details = Disclosure("Détails techniques", (Fields((
        ("message", Text(f"événement n° {seq}", "mono")), ("fin", Text(f"événement n° {ended.seq}", "mono")),
        ("épisode", Text(corr, "mono")),
        ("déclencheur", Text(str(started.data.trigger) if started is not None else "—", "mono")),
        ("issue", Text(e.outcome, "mono")), ("détail", Text(e.detail or "—", "mono")),
    )), Code(json.dumps(json.loads(e.model_dump_json()), ensure_ascii=False, indent=1), "La fin d'épisode au journal")))
    blocks.append(details)

    def rendered(items: Sequence[Any]) -> Any:
        return lambda env, query: render.blocks(list(items), env, query, namespace="silence")

    outcome = names.outcome(e.outcome, e.kind)
    more: dict[str, Any] = {
        "outcome": {"text": outcome[0], "tone": outcome[1]}, "burst": burst,
        "ended": {"href": render.href(Ref("event", str(ended.seq), "")), "number": ended.seq,
                  "when": ui.when_long(ended.at)},
        "started": ui.when_long(started.at) if started is not None else "",
        "episode": corr if started is not None else "", "kept": bool((trace or {}).get("compose")),
        "calls": rendered(calls_blocks(ui, corr)) if failed else [],
        "prompt": prompt_view(ui, trace) if trace else None,
        "context": [{"title": t, "text": x} for t, x in context_parts(trace or {})],
        "tools": tools_view(trace) if trace else None,
        "calls_made": rendered(tools_blocks(ui, trace, None)) if any(
            isinstance(t, dict) for t in (trace or {}).get("tool_calls") or ()) else [],
        "steps": answer_steps(trace, None) if trace and trace.get("reply") else [],
        "details": rendered([details]),
    }
    return {**page, "facts": facts, "blocks": blocks, "correlation": corr if started is not None else "",
            "view": drawn(state, more)}


#: un prompt pas gardé, et pourquoi il peut ne pas l'être
UNKEPT_PROMPT = ("Son prompt n'est pas gardé : elle n'est pas allée jusqu'à le composer (elle s'est ravisée, une panne "
                 "avant l'appel), ou sa trace a expiré (14 jours) ou a été oubliée.")
