"""Le rappel : ce qui lui revient pendant qu'elle parle à quelqu'un.

L'enrichisseur cherche ce qui ressemble à la conversation — le dernier
message, et les quelques précédents (« et lui, il va mieux ? » se comprend
avec ce qui précède). Rien sur un tour phatique (« bonne nuit », « ah
d'accord ») : on ne repense pas à sa vie à chaque politesse. Ne revient que
ce qui dépasse un seuil absolu **et** reste près du meilleur candidat ; ce qui
dort ne revient que sur un indice fort. Puis il garde ce qui peut se dire
devant cette audience, le classe (pertinence × ce qu'il en reste × lien avec
la personne × humeur × pas montré à l'instant), et rend :

- ses souvenirs et ce qu'elle sait (``CE QUI TE REVIENT``) — ce qui vient
  d'autres au-delà de l'anodin porte une étiquette qui nomme qui l'a confié ;
  ce qui ne peut pas se dire ici devient une ligne vague (elle sait qu'elle
  sait, sans un mot du contenu) ;
- ce qu'elle a vécu avec l'interlocuteur et d'autres (il était là) ;
- des extraits d'échanges passés **avec cette personne** (ou dans ce salon),
  cherchés à part — les extraits des autres n'étouffent pas ses souvenirs —
  et jamais ce que le fil montré contient déjà ;
- les promesses qu'elle lui a faites (sa fiche, donc seulement si elle est
  ouverte) ; ce qui se passe dans sa vie (un entretien jeudi, et après :
  « alors ? »).

Toute panne → rien (le tour part sans mémoire, jamais avec trop).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.extraction import day_words
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, params
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.salience import (
    Item,
    Verdict,
    admissible,
    age_words,
    dormant,
    rank,
    tag,
    unsaid,
    unsaid_line,
    valence_sign,
)
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody
from mika.vocab import affect as A
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import stems, words

#: ce qu'elle devine se dit comme tel ; ce qu'on lui a dit se lit déjà dans le texte
ORIGIN_FR = {"inferred": "tu le devines"}
#: les mots d'une politesse : un tour qui n'a rien d'autre ne réveille aucun souvenir
PHATIC = frozenset("""
bonne bonnes nuit soiree soir journee matinee aprem bonjour bonsoir hello coucou salut hey yop accord daccord okay oki
cool super top genial parfait nickel bisous bises bisou plus tard bientot dodo ciao bye byebye lol mdr haha hahaha
hihi yes yep nope voila bref ouf merci beaucoup grave clair carrement exact exactement tranquille tkt dac fais quoi
ahah ahh ohh hmm hum mmh ptdr xptdr sinon allez drole marrant dingue wow waouh ouah chouette comment pourquoi
combien lequel laquelle appelle appelles appelait souvenir rappeler rappel
""".split())
#: le poids des messages précédents dans la recherche (le dernier compte davantage)
CONTEXT_WEIGHT = 0.9
#: les messages précédents ne comptent que s'ils sont de la même conversation (pas d'hier)
CONTEXT_SPAN_US = HOUR
#: ce que vaut, en plus de la similarité des vecteurs, un élément qui contient tous les mots qui portent le
#: sujet du message (« samedi », « Moustache ») : un plongement multilingue rapproche volontiers « samedi »
#: de « hier soir » ; le mot lui-même ne trompe pas
LEXICAL_BONUS = 0.35
#: le fil que le prompt montre déjà (l'enrichissement de ``transcript``) : ses tours portent leur ``id``
SHOWN_THREAD = "thread"
#: un échange encore à l'écran (sans fil connu) ne se répète pas
RECENT_EXCHANGE_US = 10 * MINUTE
#: un moment passé dont elle vient de reparler reste sous ses yeux le temps de la conversation
FOLLOWED_KEEP_US = 2 * HOUR


@dataclass(frozen=True, slots=True)
class Recalled:
    item: Item
    verdict: Verdict
    label: str  # le texte à montrer, étiquette comprise


@dataclass(frozen=True, slots=True)
class Exchange:
    id: int
    at: int
    user_text: str
    reply_text: str
    person: str = ""  # qui parlait (un salon en compte plusieurs)
    question: int | None = None


@dataclass(frozen=True, slots=True)
class Moment:
    """Un moment de la vie de l'interlocuteur, tel qu'il peut se dire."""

    event: c.LifeEvent
    text: str
    verdict: Verdict
    label: str


@dataclass(slots=True)
class Recall:
    souvenirs: list[Recalled] = field(default_factory=list)
    beliefs: list[Recalled] = field(default_factory=list)
    exchanges: list[Exchange] = field(default_factory=list)
    #: (id, texte, échéance, échéance implicite)
    promised: list[tuple[int, str, int | None, bool]] = field(default_factory=list)
    unsaid: list[str] = field(default_factory=list)
    moments: list[Moment] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    name: str = ""


def names_of(frame: Frame, keys: set[str]) -> dict[str, str]:
    out = {}
    for k in keys:
        if k.startswith("name:"):
            out[k] = k[5:].title()
        else:
            out[k] = frame.get(identity_c.IDENTITY(k)).name or k
    return out


def canon(frame: Frame, keys: Sequence[str], memo: dict[str, str]) -> tuple[str, ...]:
    """Les clés telles qu'elles valent maintenant : une adresse reliée depuis
    à quelqu'un parle pour lui (ce qu'elle a confié sous son autre compte est à elle)."""
    out = set()
    for k in keys:
        if k not in memo:
            memo[k] = k if k.startswith("name:") else (frame.get(identity_c.PERSON(k)) or k)
        out.add(memo[k])
    return tuple(sorted(out))


def phatic(text: str) -> bool:
    """Une politesse, un acquiescement : rien qui oriente un souvenir."""
    return not [w for w in words(text) if w not in PHATIC]


def query_of(frame: Frame, store: Any) -> str:
    """Le dernier message (ou, pour une initiative, ce qui la motive)."""
    ep = frame.episode
    if ep is None:
        return ""
    reply_to = ep.attrs.get("reply_to")
    if reply_to is not None:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (reply_to,))
        if rows:
            return str(rows[0][0])
    args = ep.attrs.get("args") or {}
    return " ".join(str(v) for k, v in args.items() if str(k).startswith("brief:"))


def context_of(frame: Frame, store: Any, n: int) -> str:
    """Les messages qui précèdent le dernier, de la même personne (ou du
    même salon) et de la même conversation (moins d'une heure avant), jusqu'à
    ``n`` en tout : la conversation, pas une phrase — ni celle d'hier."""
    ep = frame.episode
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    if ep is None or reply_to is None or n <= 1:
        return ""
    since = frame.now - CONTEXT_SPAN_US
    room = ep.attrs.get("room")
    if room:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE room=? AND role='user' AND id<? "
                                "AND at>=? ORDER BY id DESC LIMIT ?", (room, reply_to, since, n - 1))
    else:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE person=? AND room IS NULL AND "
                                "role='user' AND id<? AND at>=? ORDER BY id DESC LIMIT ?",
                                (ep.target, reply_to, since, n - 1))
    return " ".join(str(r[0]) for r in reversed(rows))


def topic(text: str) -> set[str]:
    """Les mots qui portent le sujet d'un message (radicaux, sans les mots
    vides ni les politesses)."""
    return {w[:6] for w in words(text, min_len=4) if w not in PHATIC}


def relevance(similarity: float, wanted: set[str], text: str) -> float:
    """La similarité des vecteurs, plus un bonus pour la part des mots du
    sujet que l'élément contient (un mot sur deux vaut déjà 70 % du bonus) :
    la recherche hybride."""
    if not wanted:
        return similarity
    return similarity + LEXICAL_BONUS * math.sqrt(len(wanted & stems(text)) / len(wanted))


def touches(text: str, topics: tuple[str, ...]) -> bool:
    """Le texte touche-t-il un de ces sujets (radicaux communs) ?"""
    if not topics:
        return False
    have = stems(text)
    return any(stems(topic) & have for topic in topics)


def sensitivity_of(frame: Frame, item: Item, interlocutor: str | None, store: Any = None) -> int:
    """Un souvenir qui touche un sujet délicat d'une autre personne concernée
    devient une confidence, quoi qu'en ait dit la consolidation. Les sujets
    délicats d'un profil récent sont gardés à part (``store``)."""
    level = item.sensitivity
    for other in item.about:
        if other == interlocutor or other.startswith("name:"):
            continue
        topics = tuple(frame.get(social_c.SENSITIVE(other)))
        ref = frame.get(social_c.SENSITIVE_REF(other)) if store is not None else ""
        if ref:
            topics += tuple(t.strip() for t in (store.content([ref]).get(ref) or "").splitlines() if t.strip())
        if touches(item.text, topics):
            return max(level, int(Sensitivity.CONFIDENCE))
    return level


def items_by_id(store: Any, ids: list[int]) -> dict[int, Item]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = store.query_mind(f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE id IN ({marks})",
                            tuple(ids))
    return {int(r[0]): Item.of(dict(zip(ITEM_COLUMNS, r, strict=True))) for r in rows}


def verdict_of(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
               store: Any = None) -> Verdict:
    """Ce qui décide si un élément peut se dire ici : ses personnes, qui l'a
    confié et entendu (telles qu'elles valent maintenant), sa sensibilité
    (sujets délicats des profils compris, gardés à part dans ``store``)."""
    return admissible(canon(frame, item.about, memo), sensitivity_of(frame, item, person, store), person, aud,
                      told_by=canon(frame, item.told_by, memo), heard_by=canon(frame, item.heard_by, memo),
                      secret=item.secret)


def promises_to(frame: Frame, store: Any, person: str) -> list[tuple[int, str, int | None]]:
    """Les promesses en cours faites à cette personne, avec leur texte. Ne
    vérifie pas la porte de sa fiche (``private_ok``) : à l'appelant de le faire."""
    pending = frame.get(c.PROMISES_TO(person))
    if not pending:
        return []
    texts = {i: it.text for i, it in items_by_id(store, [pr.id for pr in pending]).items()}
    return [(pr.id, texts.get(pr.id, ""), pr.due) for pr in pending if texts.get(pr.id)]


async def search(vectors: Any, query: str, context: str, k: int, **kw: Any) -> tuple[dict[int, float],
                                                                                dict[int, float]]:
    """Les plus proches du dernier message, et de la conversation qui le
    précède : les similarités des deux recherches (la seconde vide sans contexte)."""
    near = {key: float(sim) for key, sim in await vectors.search(query, k, **kw)}
    wider: dict[int, float] = {}
    if context.strip():
        wider = {key: float(sim) for key, sim in await vectors.search(f"{context} {query}", k, **kw)}
    return near, wider


def scored(near: dict[int, float], wider: dict[int, float], texts: Mapping[int, str], query: str,
           context: str) -> dict[int, float]:
    """La pertinence de chaque candidat : la meilleure du message seul et de
    la conversation (un peu moins), chacune hybride (vecteurs + mots du sujet)."""
    own, around = topic(query), topic(f"{context} {query}")
    out: dict[int, float] = {}
    for key in {*near, *wider}:
        text = texts.get(key, "")
        best = relevance(near[key], own, text) if key in near else 0.0
        if key in wider:
            best = max(best, CONTEXT_WEIGHT * relevance(wider[key], around, text))
        out[key] = best
    return out


def kept(sims: dict[int, float], p: MemoryParams) -> dict[int, float]:
    """Le seuil absolu, et l'écart au meilleur : le rappel suit le sujet."""
    if not sims:
        return {}
    floor = max(p.recall_floor, max(sims.values()) - p.recall_margin)
    return {k: s for k, s in sims.items() if s >= floor}


@MEMORY.enricher("recall", episodes=CONVERSATIONAL, deadline_ms=2500)
async def _recall(s: MemoryState, frame: Frame, ports: Mapping[str, Any]) -> Recall | None:
    vectors, store = ports.get("vectors"), ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or aud is None or not ep.target:
        return None
    p = params(frame.env.params_of("memory", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    out = Recall(name=frame.get(identity_c.IDENTITY(ep.target)).name)
    memo: dict[str, str] = {}
    if aud.private_ok:
        pending = sorted(frame.get(c.PROMISES_TO(person)), key=lambda pr: (pr.due or 2**62, pr.id))[: p.max_promises]
        texts = {i: it.text for i, it in items_by_id(store, [pr.id for pr in pending]).items()}
        out.promised = [(pr.id, texts[pr.id], pr.due, pr.implicit_due) for pr in pending if texts.get(pr.id)]
    out.moments = _moments(frame, store, person, aud, p, memo)
    query = query_of(frame, store)
    if vectors is None or not query.strip():
        return out
    is_reply = ep.attrs.get("reply_to") is not None
    if is_reply and phatic(query):
        return out  # une politesse ne réveille rien
    context = context_of(frame, store, p.context_messages) if is_reply else ""
    near, wider = await search(vectors, query, context, p.recall_k, kinds={c.SOUVENIR, c.BELIEF})
    found = items_by_id(store, sorted({*near, *wider}))
    candidates = kept(scored(near, wider, {i: it.text for i, it in found.items()}, query, context), p)
    items = {i: found[i] for i in candidates if i in found}
    mood = frame.get(affect_c.MOOD)
    mood_valence = A.valence(mood.felt) * mood.felt_intensity if mood.felt_intensity >= 0.1 else 0.0
    now = frame.now
    ranked: list[tuple[float, Item, Verdict]] = []
    hidden: dict[str, list[Item]] = {}
    for item in items.values():
        if item.status != "active" or item.kind not in (c.SOUVENIR, c.BELIEF):
            continue
        if dormant(item, now, p) and candidates[item.id] < p.strong_cue:
            continue  # il dort ; seul un indice fort le réveille
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if not verdict.ok:
            for who in unsaid(verdict, canon(frame, item.about, memo), canon(frame, item.told_by, memo), person):
                hidden.setdefault(who, []).append(item)
            continue
        ranked.append((rank(item, candidates[item.id], now, p, interlocutor=person, mood_valence=mood_valence), item,
                       verdict))
    ranked.sort(key=lambda r: (-r[0], r[1].id))
    names = names_of(frame, {o for _, it, v in ranked for o in (*v.others, *it.about)} | set(hidden))
    out.names = names
    for _score, item, verdict in ranked:
        bucket, cap = (out.souvenirs, p.max_souvenirs) if item.kind == c.SOUVENIR else (out.beliefs, p.max_beliefs)
        if len(bucket) < cap:
            bucket.append(Recalled(item, verdict, item.text + tag(verdict, names)))
    if hidden and not aud.public and p.max_unsaid:
        close = aud.level >= Sensitivity.PERSONAL
        for who in sorted(hidden, key=lambda w: (-max(candidates[i.id] for i in hidden[w]), w))[: p.max_unsaid]:
            heavy = any(valence_sign(i.emotion) < 0 or i.sensitivity >= Sensitivity.CONFIDENCE for i in hidden[who])
            out.unsaid.append(unsaid_line(who, names, heavy=heavy, close=close))
    out.exchanges = await _exchanges_for(frame, store, vectors, query, context, person, aud, p)
    return out


async def _exchanges_for(frame: Frame, store: Any, vectors: Any, query: str, context: str, person: str,
                         aud: Audience, p: MemoryParams) -> list[Exchange]:
    """Les échanges passés avec cette personne (ou dans ce salon), cherchés
    parmi les siens seulement : ceux des autres ne prennent pas leur place."""
    ep = frame.episode
    if ep is None or p.max_chunks <= 0:
        return []
    room = ep.attrs.get("room") or aud.room
    if room:
        # dans un salon : seulement ce qui s'y est dit (public pour ce salon)
        ids = [int(r[0]) for r in store.query_mind(f"SELECT id FROM {c.CHUNKS_TABLE} WHERE room=?", (room,))]
    else:
        # en privé : ses échanges privés — sur ses autres adresses seulement si sa fiche est ouverte
        # (une liaison par simple recoupement, pas encore confirmée : ses seuls échanges)
        handles = tuple(frame.get(identity_c.THREAD(ep.target))) if aud.private_ok else ()
        handles = tuple(sorted({ep.target, *handles}))
        marks = ",".join("?" * len(handles))
        ids = [int(r[0]) for r in store.query_mind(
            f"SELECT id FROM {c.CHUNKS_TABLE} WHERE room IS NULL AND person IN ({marks})", handles)]
    if not ids:
        return []
    near, wider = await search(vectors, query, context, p.max_chunks * 4, keys=ids)
    if not near and not wider:
        return []
    marks = ",".join("?" * len({*near, *wider}))
    rows = store.query_mind(f"SELECT id, at, user_text, reply_text, person, question FROM {c.CHUNKS_TABLE} "
                            f"WHERE id IN ({marks})", tuple(sorted({*near, *wider})))
    sims = kept(scored(near, wider, {int(r[0]): f"{r[2]}\n{r[3]}" for r in rows}, query, context), p)
    rows = [r for r in rows if int(r[0]) in sims]
    before = ep.attrs.get("reply_to") or frame.now
    exchanges = [Exchange(int(i), int(at), u, r, who or "", q) for i, at, u, r, who, q in rows]
    # ce qui est encore dans le fil montré ne se répète pas (le fil exact se vérifie à la composition)
    exchanges = [e for e in exchanges if frame.now - e.at > RECENT_EXCHANGE_US and e.id < before]
    exchanges.sort(key=lambda e: (-sims.get(e.id, 0.0), e.id))
    return exchanges[: p.max_chunks * 2]


def _moments(frame: Frame, store: Any, person: str, aud: Audience, p: MemoryParams,
             memo: dict[str, str]) -> list[Moment]:
    """Ce qui se passe dans sa vie : à venir bientôt, ou tout juste passé et
    dont elle ne lui a pas encore reparlé."""
    now = frame.now
    shown: list[tuple[c.LifeEvent, Verdict]] = []
    for ev in frame.get(c.LIFE_EVENTS(person)):
        upcoming = now <= ev.when <= now + round(p.event_ahead_days * DAY)
        recent = ev.when < now <= ev.when + round(p.event_recent_days * DAY) and (
            not ev.followed_at or now - ev.followed_at < FOLLOWED_KEEP_US)
        if not (upcoming or recent):
            continue
        verdict = admissible(canon(frame, ev.about, memo), ev.sensitivity, person, aud,
                             told_by=canon(frame, ev.told_by, memo), heard_by=(), secret=ev.secret)
        if verdict.ok:
            shown.append((ev, verdict))
    if not shown:
        return []
    texts = store.content([ev.text_ref for ev, _ in shown])
    names = names_of(frame, {o for _, v in shown for o in v.others})
    out = []
    for ev, verdict in shown:
        text = texts.get(ev.text_ref)
        if text:  # oublié : rien
            out.append(Moment(ev, text, verdict, text + tag(verdict, names)))
    return out


# ── Les sections ──────────────────────────────────────────────────────────


def _lines(recalled: list[Recalled], now: int, *, beliefs: bool) -> list[str]:
    lines = []
    for r in recalled:
        if beliefs:
            how = ORIGIN_FR.get(r.item.origin or "", "")
            lines.append(f"- {r.label}" + (f" ({how})" if how else ""))
        else:
            lines.append(f"- {age_words(r.item.born_at, now)} : {r.label}")
    return lines


def _body(recall: Recall, frame: Frame, *, witness: bool) -> SectionBody | None:
    souvenirs = [r for r in recall.souvenirs if r.verdict.witness == witness]
    beliefs = [r for r in recall.beliefs if r.verdict.witness == witness]
    hidden = recall.unsaid if not witness else []
    if not souvenirs and not beliefs and not hidden:
        return None
    lines: list[str] = []
    if souvenirs:
        lines += ["Des souvenirs :", *_lines(souvenirs, frame.now, beliefs=False)]
    if beliefs:
        lines += ["Ce que tu sais (tes notes) :", *_lines(beliefs, frame.now, beliefs=True)]
    if hidden:
        lines += ["Ce que tu sais sans pouvoir le raconter ici :", *hidden]
    shown = souvenirs + beliefs
    advice = "Sers-t'en seulement si ça vient naturellement."
    if any(r.label != r.item.text for r in shown):
        advice += " Ce qu'on t'a confié en privé, à toi de juger si ça se dit ici."
    lines.append(advice)
    return SectionBody("\n".join(lines), level=max((r.verdict.level for r in shown), default=0),
                       provenance=tuple(f"memory:{r.item.id}" for r in shown), witness=witness)


@MEMORY.section("memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=30,
                title="CE QUI TE REVIENT")
def _memories(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=False) if recall else None


@MEMORY.section("shared_memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=31,
                title="CE QUE VOUS AVEZ VÉCU AVEC D'AUTRES")
def _shared(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=True) if recall else None


def shown_since(enrich: Mapping[str, Any]) -> int | None:
    """Le plus ancien message que le fil montré contient (son résumé compris) :
    ce qui suit est déjà sous ses yeux, mot pour mot. L'enrichissement est une
    vue (``key``, ``turns``, ``current``) ; un tuple de tours reste accepté."""
    view = enrich.get(SHOWN_THREAD)
    turns = getattr(view, "turns", view) or ()
    ids = [t.id for t in turns if (getattr(t, "id", 0) or 0) > 0]  # 0 : un tour sans repère
    return min(ids) if ids else None


@MEMORY.section("past_exchanges", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=20,
                title="VOS ÉCHANGES PASSÉS")
def _exchanges(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.exchanges:
        return None
    since = shown_since(enrich)
    exchanges = [e for e in recall.exchanges if since is None or (e.question or e.id) < since]
    p = params(frame.env.params_of("memory", frame.root))
    exchanges = exchanges[: p.max_chunks]
    if not exchanges:
        return None
    names = names_of(frame, {e.person for e in exchanges if e.person})
    lines = []
    for e in exchanges:
        who = names.get(e.person) or recall.name or "la personne"
        lines.append(f"- {age_words(e.at, frame.now)}, {who} : « {e.user_text[:240]} » — toi : « {e.reply_text[:240]} »")
    return SectionBody("\n".join(lines), provenance=tuple(f"chunk:{e.id}" for e in exchanges))


def when_words(t: int, frame: Frame, *, all_day: bool = True) -> str:
    """Un jour dit comme on le dit : aujourd'hui, demain, jeudi, hier soir, le 12 octobre."""
    today, then = frame.local().date(), frame.local(t)
    days = (then.date() - today).days
    hour = "" if all_day else f" à {then.hour}h{then.minute:02d}" if then.minute else f" à {then.hour}h"
    if days == 0:
        return "aujourd'hui" + hour
    if days == 1:
        return "demain" + hour
    if days == -1:
        return "hier" + hour
    if 1 < days < 7:
        return f"{day_words(then.date()).split()[0]}{hour} (dans {days} jours)"
    if -7 < days < -1:
        return f"{day_words(then.date()).split()[0]} dernier"
    return f"le {' '.join(day_words(then.date()).split()[1:])}{hour}"


@MEMORY.section("promises", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=60,
                title="CE QUE TU LUI AS PROMIS")
def _promises(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.promised:
        return None
    lines = []
    for pid, text, due, implicit in recall.promised:
        when = ""
        if due and not implicit:
            when = f" (c'était pour {when_words(due, frame)})" if due < frame.now else f" (pour {when_words(due, frame)})"
        lines.append(f"- {text}{when} — n° {pid}")
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{pid}" for pid, *_ in recall.promised))


@MEMORY.section("life", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=55,
                title="CE QUI SE PASSE DANS SA VIE")
def _life(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.moments:
        return None
    lines = []
    for m in recall.moments:
        when = when_words(m.event.when, frame, all_day=m.event.all_day)
        if m.event.when <= frame.now:
            lines.append(f"- {when} : {m.label} — c'est passé : tu peux lui demander comment ça s'est passé, "
                         "si ça vient.")
        else:
            lines.append(f"- {when} : {m.label}")
    return SectionBody("\n".join(lines), level=max(m.verdict.level for m in recall.moments),
                       provenance=tuple(f"memory:{m.event.id}" for m in recall.moments))
