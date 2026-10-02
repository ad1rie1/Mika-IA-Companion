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
  ouverte), et celle qu'il est temps de tenir ; ce qui se passe dans sa vie (un
  entretien jeudi, et après : « alors ? » — envers une amie, la première chose
  qu'elle demanderait ; une situation qui dure, son chat malade) ;
- au premier mot d'une conversation (« salut ! »), ou quand elle écrit
  d'elle-même, ce que la personne lui a raconté de sa vie ces derniers jours
  (sa fiche, de première main) : « et Moustache, il va mieux ? » ne dépend plus
  du hasard d'une ressemblance ;
- quand on lui parle d'elle (« ton plat préféré ? »), ce qu'elle a déjà dit de
  ses goûts, de ses avis, de sa vie : elle ne se contredit pas.

Une croyance apprise il y a plus d'une semaine dit depuis quand (« appris il y
a 3 semaines ») ; un souvenir vécu avec quelqu'un à qui elle tient s'endort
moins vite.

Toute panne → rien (le tour part sans mémoire, jamais avec trop).
"""

from __future__ import annotations

import math
import re
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
from mika.faculties.memory.life import keep_window
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.salience import (
    Item,
    Verdict,
    admissible,
    age_words,
    dormant,
    rank,
    salience,
    tag,
    touched,
    unsaid,
    unsaid_line,
    valence_sign,
)
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody
from mika.vocab import affect as A
from mika.vocab.days import window_of
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.people import clean_tokens, is_identifiable
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import fold, stems, words

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
#: un moment dont elles viennent de reparler (``moment_followed`` : en mots, pas seulement montré) reste sous ses
#: yeux le temps de la conversation — sans la consigne de demander, c'est fait
FOLLOWED_KEEP_US = 2 * HOUR
#: une croyance apprise il y a plus longtemps dit depuis quand (« ma sœur vient ce week-end » n'est plus vrai)
DATED_AFTER_US = 7 * DAY
#: on lui parle d'elle : « tu », « ton plat préféré », « t'as »… (replié, sans accents)
_TO_HER = re.compile(r"\b(?:tu|toi|ton|ta|tes)\b|\bt'")
#: au premier mot d'une conversation, ce qui la concerne, cherché parmi au plus tant d'éléments récents
_THEIR_LIFE_POOL = 40


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
    #: parmi elles, celles qu'il est temps de tenir (le moment dit est là)
    due_now: set[int] = field(default_factory=set)
    unsaid: list[str] = field(default_factory=list)
    moments: list[Moment] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    name: str = ""
    #: ce qu'elle a déjà dit d'elle-même (ses goûts, ses avis, sa vie) et qui touche le message
    self_said: list[Item] = field(default_factory=list)
    #: proche, ou amie : la première chose qu'une amie demanderait
    close: bool = False


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
    à quelqu'un parle pour lui (ce qu'elle a confié sous son autre compte est à elle) ; un nom qu'un opérateur a
    relié à une personne (« l'Alice dont Bob parlait », c'était elle) la désigne — sinon il reste ce qu'il est."""
    out = set()
    for k in keys:
        if k not in memo:
            memo[k] = frame.get(identity_c.PERSON(k)) or k
        out.add(memo[k])
    return tuple(sorted(out))


def phatic(text: str) -> bool:
    """Une politesse, un acquiescement : rien qui oriente un souvenir."""
    return not [w for w in words(text) if w not in PHATIC]


def addresses_her(text: str) -> bool:
    """On lui parle d'elle : « tu », « ton », « t'as »… (« c'est quoi ton plat préféré ? »)."""
    return bool(_TO_HER.search(fold(text)))


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


#: au plus tant de l'attachement d'une proche, d'une amie (quand l'attachement mesuré est plus faible)
_BOND_FLOOR = {social_c.CLOSE: 1.0, social_c.FRIEND: 0.5}


def bond_of(frame: Frame, keys: Sequence[str], memo: dict[str, float]) -> float:
    """Ce qui l'attache aux personnes d'un souvenir (0 à 1) : l'attachement mesuré, au moins ce que vaut une
    proche (1) ou une amie (½) — un souvenir avec elles s'endort moins vite."""
    best = 0.0
    for k in keys:
        if k.startswith("name:") or not is_identifiable(k):
            continue
        if k not in memo:
            memo[k] = max(frame.get(affect_c.BOND(k)), _BOND_FLOOR.get(frame.get(social_c.CLOSENESS(k)), 0.0))
        best = max(best, memo[k])
    return best


@MEMORY.enricher("recall", episodes=CONVERSATIONAL, deadline_ms=2500,
                 reads=[identity_c.PERSON, identity_c.IDENTITY, identity_c.HANDLES, c.PROMISES_TO, c.LIFE_EVENTS,
                        affect_c.MOOD, affect_c.BOND, social_c.CLOSENESS])
async def _recall(s: MemoryState, frame: Frame, ports: Mapping[str, Any]) -> Recall | None:
    vectors, store = ports.get("vectors"), ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or aud is None or not ep.target:
        return None
    p = params(frame.env.params_of("memory", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    out = Recall(name=frame.get(identity_c.IDENTITY(ep.target)).name,
                 close=is_identifiable(person) and frame.get(social_c.CLOSENESS(person)) in _BOND_FLOOR)
    memo: dict[str, str] = {}
    if aud.private_ok:
        pending = sorted(frame.get(c.PROMISES_TO(person)), key=lambda pr: (pr.due or 2**62, pr.id))[: p.max_promises]
        texts = {i: it.text for i, it in items_by_id(store, [pr.id for pr in pending]).items()}
        out.promised = [(pr.id, texts[pr.id], pr.due, pr.implicit_due) for pr in pending if texts.get(pr.id)]
        for pr in pending:
            window = keep_window(pr, frame, p)
            if window is not None and window[0] <= frame.now <= window[2]:
                out.due_now.add(pr.id)
    out.moments = _moments(frame, store, person, aud, p, memo)
    bonds: dict[str, float] = {}
    is_reply = ep.attrs.get("reply_to") is not None
    query = query_of(frame, store) if is_reply else ""
    context = context_of(frame, store, p.context_messages) if is_reply else ""
    if not is_reply or (phatic(query) and not context.strip()):
        # le premier mot d'une conversation (« salut ! »), ou elle qui écrit d'elle-même : ce qui se passe dans sa
        # vie à elle — pas les mots d'une consigne ni d'une politesse, qui ne désignent rien
        _their_life(out, frame, store, person, aud, p, memo, bonds)
        return out
    if vectors is None or not query.strip() or phatic(query):
        return out  # une politesse ne réveille rien
    if addresses_her(query):
        out.self_said = await _self_said(vectors, store, query, p)
    near, wider = await search(vectors, query, context, p.recall_k, kinds={c.SOUVENIR, c.BELIEF})
    found = items_by_id(store, sorted({*near, *wider}))
    candidates = kept(scored(near, wider, {i: it.text for i, it in found.items()}, query, context), p)
    said_ids = {it.id for it in out.self_said}
    items = {i: found[i] for i in candidates if i in found and i not in said_ids}
    mood = frame.get(affect_c.MOOD)
    mood_valence = A.valence(mood.felt) * mood.felt_intensity if mood.felt_intensity >= 0.1 else 0.0
    now = frame.now
    ranked: list[tuple[float, Item, Verdict]] = []
    hidden: dict[str, list[Item]] = {}
    asked: dict[str, tuple[str, ...]] = {}
    close = aud.level >= Sensitivity.PERSONAL
    for item in items.values():
        if item.status != "active" or item.kind not in (c.SOUVENIR, c.BELIEF):
            continue
        bond = bond_of(frame, canon(frame, item.about, memo), bonds) if item.kind == c.SOUVENIR else 0.0
        if dormant(item, now, p, bond) and candidates[item.id] < p.strong_cue:
            continue  # il dort ; seul un indice fort le réveille
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if not verdict.ok:
            # un secret ne laisse même pas deviner qu'il existe : devant les autres, elle n'en sait rien (« aucune
            # idée, demande-lui ») — la ligne vague « il t'a confié des choses » le trahissait à qui on le cachait
            # (sonde réelle du 2026-10-02 : « dis rien à Chloé », puis devant Chloé). Seule une proche peut sentir
            # qu'un secret lourd pèse (« traverse un moment difficile »), jamais ce qu'il dit.
            guessable = not item.secret or (close and heavy(item))
            whom = unsaid(verdict, canon(frame, item.about, memo), canon(frame, item.told_by, memo),
                          person) if guessable else ()
            for who in whom:
                hidden.setdefault(who, []).append(item)
                asked[who] = asked.get(who, ()) + tuple(w for w in touched(query, item.text) if w not in asked.get(who, ()))
            continue
        ranked.append((rank(item, candidates[item.id], now, p, interlocutor=person, mood_valence=mood_valence,
                            bond=bond), item, verdict))
    ranked.sort(key=lambda r: (-r[0], r[1].id))
    names = names_of(frame, {o for _, it, v in ranked for o in (*v.others, *it.about)} | set(hidden))
    out.names = names
    for _score, item, verdict in ranked:
        bucket, cap = (out.souvenirs, p.max_souvenirs) if item.kind == c.SOUVENIR else (out.beliefs, p.max_beliefs)
        if len(bucket) < cap:
            bucket.append(Recalled(item, verdict, item.text + tag(verdict, names)))
    if hidden and not aud.public and p.max_unsaid:
        for who in sorted(hidden, key=lambda w: (-max(candidates[i.id] for i in hidden[w]), w))[: p.max_unsaid]:
            out.unsaid.append(unsaid_line(who, names, heavy=any(heavy(i) for i in hidden[who]), close=close,
                                          asked=asked.get(who, ())[:3]))
    out.exchanges = await _exchanges_for(frame, store, vectors, query, context, person, aud, p)
    return out


def heavy(item: Item) -> bool:
    """Ce qui pèse : une peine, une peur, ou une confidence."""
    return valence_sign(item.emotion) < 0 or item.sensitivity >= Sensitivity.CONFIDENCE


def _their_life(out: Recall, frame: Frame, store: Any, person: str, aud: Audience, p: MemoryParams,
                memo: dict[str, str], bonds: dict[str, float]) -> None:
    """Ce que la personne lui a raconté de sa vie ces derniers jours — de première main (jamais ce qu'un tiers a
    dit d'elle), sa fiche (seulement si elle est ouverte) —, les plus importants et les plus frais d'abord : au
    premier « salut » de la semaine, « et Moustache, il va mieux ? » lui vient."""
    if p.max_person_items <= 0 or not aud.private_ok or not is_identifiable(person):
        return
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    since = frame.now - round(p.person_recall_days * DAY)
    where = " OR ".join("about LIKE ?" for _ in handles)
    rows = store.query_mind(
        f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE kind IN (?, ?) AND status='active' "
        f"AND born_at>=? AND ({where}) ORDER BY importance DESC, id DESC LIMIT ?",
        (c.SOUVENIR, c.BELIEF, since, *(f'%"{h}"%' for h in handles), _THEIR_LIFE_POOL))
    picked: list[tuple[float, Item, Verdict]] = []
    for row in rows:
        item = Item.of(dict(zip(ITEM_COLUMNS, row, strict=True)))
        if set(canon(frame, item.told_by, memo)) - {person}:
            continue  # de première main seulement
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if not verdict.ok:
            continue
        bond = bond_of(frame, canon(frame, item.about, memo), bonds) if item.kind == c.SOUVENIR else 0.0
        picked.append((item.importance * min(1.0, salience(item, frame.now, p, bond)), item, verdict))
    picked.sort(key=lambda x: (-x[0], -x[1].id))
    names = names_of(frame, {o for _, it, v in picked for o in (*v.others, *it.about)})
    out.names = names
    for _w, item, verdict in picked[: p.max_person_items]:
        bucket = out.souvenirs if item.kind == c.SOUVENIR else out.beliefs
        bucket.append(Recalled(item, verdict, item.text + tag(verdict, names)))


async def _self_said(vectors: Any, store: Any, query: str, p: MemoryParams) -> list[Item]:
    """Ce qu'elle a déjà dit de ses goûts, de ses avis, de sa vie, le plus proche du message — sans seuil : quand
    on lui demande son plat préféré, la réponse d'il y a trois semaines est là, même sans un mot commun."""
    if p.max_self_said <= 0:
        return []
    ids = [int(r[0]) for r in store.query_mind(
        f"SELECT id FROM {c.ITEMS_TABLE} WHERE kind=? AND about_self>=2 AND status='active' ORDER BY id DESC LIMIT 200",
        (c.BELIEF,))]
    if not ids:
        return []
    order = ids
    if vectors is not None:
        hits = [int(k) for k, _sim in await vectors.search(query, p.max_self_said, kinds={c.BELIEF}, keys=ids)]
        order = hits + [i for i in ids if i not in hits]
    found = items_by_id(store, order[: p.max_self_said])
    return [found[i] for i in order[: p.max_self_said] if i in found]


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
    before = ep.attrs.get("reply_to") or frame.now
    # se souvenir par le temps : « ce que je t'ai dit lundi matin » ne contient aucun mot du souvenir (sonde réelle
    # du 2026-10-02 : elle ne retrouvait pas l'entretien) — les échanges de ce moment-là, les plus fournis d'abord
    dated: list[Exchange] = []
    window = window_of(query, frame.now, frame.env.tz_of(frame.root)) if ep.attrs.get("reply_to") else None
    if window is not None:
        marks = ",".join("?" * len(ids))
        dated = [Exchange(int(i), int(at), u, r, who or "", q) for i, at, u, r, who, q in store.query_mind(
            f"SELECT id, at, user_text, reply_text, person, question FROM {c.CHUNKS_TABLE} WHERE id IN ({marks}) "
            "AND at >= ? AND at < ? ORDER BY length(user_text) DESC, id LIMIT ?",
            (*ids, window[0], window[1], p.max_chunks))]
        dated = [e for e in dated if frame.now - e.at > RECENT_EXCHANGE_US and e.id < before]
    near, wider = await search(vectors, query, context, p.max_chunks * 4, keys=ids)
    if not near and not wider:
        return dated
    marks = ",".join("?" * len({*near, *wider}))
    rows = store.query_mind(f"SELECT id, at, user_text, reply_text, person, question FROM {c.CHUNKS_TABLE} "
                            f"WHERE id IN ({marks})", tuple(sorted({*near, *wider})))
    sims = kept(scored(near, wider, {int(r[0]): f"{r[2]}\n{r[3]}" for r in rows}, query, context), p)
    rows = [r for r in rows if int(r[0]) in sims]
    exchanges = [Exchange(int(i), int(at), u, r, who or "", q) for i, at, u, r, who, q in rows]
    # ce qui est encore dans le fil montré ne se répète pas (le fil exact se vérifie à la composition)
    exchanges = [e for e in exchanges if frame.now - e.at > RECENT_EXCHANGE_US and e.id < before]
    exchanges.sort(key=lambda e: (-sims.get(e.id, 0.0), e.id))
    taken = {e.id for e in dated}
    return (dated + [e for e in exchanges if e.id not in taken])[: p.max_chunks * 2]


def followed_lately(ev: c.LifeEvent, now: int) -> bool:
    """Elles viennent d'en reparler (en mots) : le moment reste sous ses yeux, sans la consigne de demander."""
    return bool(ev.followed_at) and now - ev.followed_at < FOLLOWED_KEEP_US


def _moments(frame: Frame, store: Any, person: str, aud: Audience, p: MemoryParams,
             memo: dict[str, str]) -> list[Moment]:
    """Ce qui se passe dans sa vie : à venir bientôt, tout juste passé et dont
    elles n'ont pas encore reparlé (en mots : pas seulement montré), une
    situation qui dure — et ce dont elles viennent de reparler, le temps de la
    conversation."""
    now = frame.now
    shown: list[tuple[c.LifeEvent, Verdict]] = []
    for ev in frame.get(c.LIFE_EVENTS(person)):
        if ev.ongoing:
            current = ev.when <= now <= ev.when + round(p.situation_days * DAY)
            keep = current and (not ev.followed_at or followed_lately(ev, now)
                                or now - ev.followed_at >= round(p.situation_reask_days * DAY))
        else:
            upcoming = now <= ev.when <= now + round(p.event_ahead_days * DAY)
            recent = ev.when < now <= ev.when + round(p.event_recent_days * DAY) and (
                not ev.followed_at or followed_lately(ev, now))
            keep = upcoming or recent
        if not keep:
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
            how = [ORIGIN_FR.get(r.item.origin or "", "")]
            if now - r.item.born_at >= DATED_AFTER_US:
                # « ma sœur vient ce week-end », relu trois semaines plus tard, n'est plus vrai : elle sait depuis quand
                how.append(f"appris {age_words(r.item.born_at, now)}")
            told = ", ".join(h for h in how if h)
            lines.append(f"- {clean_tokens(r.label)}" + (f" ({told})" if told else ""))
        else:
            lines.append(f"- {age_words(r.item.born_at, now)} : {clean_tokens(r.label)}")
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
        # sonde réelle du 2026-10-02 : sans cette ligne, interrogée là-dessus, elle mentait (« il ne m'a rien dit »)
        lines += ["Ce que tu sais sans pouvoir le raconter ici :", *hidden,
                  "Si on te pose la question, ne mens pas et ne fais pas semblant de ne rien savoir : dis "
                  "simplement, à ta façon, que ce n'est pas à toi d'en parler."]
    shown = souvenirs + beliefs
    if shown:
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
        now = " — c'est le moment de le faire" if pid in recall.due_now else ""
        lines.append(f"- {text}{when}{now} — n° {pid}")
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{pid}" for pid, *_ in recall.promised))


@MEMORY.section("life", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=55,
                title="CE QUI SE PASSE DANS SA VIE")
def _life(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.moments:
        return None
    lines = []
    for m in recall.moments:
        lines.append(_moment_line(m, frame, recall.close))
    return SectionBody("\n".join(lines), level=max(m.verdict.level for m in recall.moments),
                       provenance=tuple(f"memory:{m.event.id}" for m in recall.moments))


def _moment_line(m: Moment, frame: Frame, close: bool) -> str:
    """Un moment, dit comme on y pense : à venir ; passé — envers une amie, c'est la première chose qu'elle
    demanderait ; une situation qui dure ; ce dont vous venez de reparler."""
    ev = m.event
    if ev.ongoing:
        since = when_words(ev.when, frame)
        head = "- en ce moment" + ("" if since == "aujourd'hui" else f" (depuis {since})") + f" : {m.label}"
        if followed_lately(ev, frame.now):
            return f"{head} — vous en avez reparlé."
        if close:
            return f"{head} — une amie lui demanderait comment ça va de ce côté-là."
        return f"{head} — tu peux lui en demander des nouvelles, si ça vient."
    when = when_words(ev.when, frame, all_day=ev.all_day)
    if ev.when > frame.now:
        return f"- {when} : {m.label}"
    if followed_lately(ev, frame.now):
        return f"- {when} : {m.label} — c'est passé, et vous en avez reparlé."
    if close:
        return (f"- {when} : {m.label} — c'est passé : c'est la première chose qu'une amie lui demanderait, comment "
                "ça s'est passé.")
    return f"- {when} : {m.label} — c'est passé : tu peux lui demander comment ça s'est passé, si ça vient."


@MEMORY.section("self_said", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=35,
                title="CE QUE TU AS DÉJÀ DIT DE TOI")
def _self_said_section(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ses goûts, ses avis, sa vie, tels qu'elle les a déjà dits : on lui parle d'elle, elle ne se contredit pas
    (elle peut changer d'avis — alors elle le dit)."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.self_said:
        return None
    lines = [f"- {it.text} (tu l'as dit {age_words(it.born_at, frame.now)})" for it in recall.self_said]
    lines.append("Reste cohérente avec ça ; si tu as changé d'avis, dis-le comme tel.")
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{it.id}" for it in recall.self_said))
