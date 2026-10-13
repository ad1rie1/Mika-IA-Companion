"""La constellation : sa mémoire en une boule de points, et ce qui la parcourt, en direct.

Chaque point est un élément de l'index des vecteurs — un souvenir, une croyance, une promesse, un moment de la vie de
quelqu'un, un échange. Sa direction vient de ses voisins de sens (``adapters.vectors.layout``) ; sa profondeur se
choisit à l'écran (l'âge, la vivacité). Rien n'y bouge pour faire joli : chaque trajet est un événement du journal qui
nomme ces éléments.

- **Une parole** et sa provenance : ce que son prompt lui montrait vraiment (``memory:…``, ``chunk:…``,
  ``veiled:…``). Le **sondage** — les voisins les plus proches du message auquel elle répondait — est recalculé ici
  par la même recherche que l'index : il dit ce qui *ressemblait*, la provenance ce qui lui est *revenu*.
- **Un élément qui naît** (la consolidation) se pose près de ses voisins ; un **renfort** le fait briller.
- **La nuit** : les souvenirs fondus, les croyances réunies, confrontées, la relecture.
- **Un rêve, son récit, son journal** parcourent leurs sources, dans l'ordre.

Réservée aux opérateurs (leur session), comme la console : la carte montre tout, secrets compris, et les textes ne
partent qu'à la demande (un point ouvert). Elle ne coûte que si quelqu'un la regarde : sans lecture depuis
``WATCH_S``, les événements ne sont même pas triés.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.vectors import layout as lay
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts.self_ import name_of
from mika.faculties.memory.recall import relevance, topic
from mika.inspector.names import Names
from mika.inspector.ui import PREFIX, SESSION_COOKIE, env, secure
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import US
from mika.ports.paging import fold_text
from mika.runtime.boundary import Failed, call
from mika.vocab.episodes import Kind

log = logging.getLogger("mika.constellation")

#: l'adresse de la page, sous la console
BASE = f"{PREFIX}/constellation"
#: au plus tant de points (les plus récents) : au-delà, la carte le dit
MAX_POINTS = 50_000
#: ce que garde le flux pour les écrans qui le lisent
FEED_MAX = 400
#: sans lecture depuis tant de secondes, plus personne ne regarde : les événements ne sont plus traduits
WATCH_S = 30
#: les voisins du message qu'on montre sondés
PROBE = 24
#: ce qu'une parole rejouée remonte au plus
REPLAY_MAX = 30
#: un extrait de message, au plus
EXCERPT = 90
#: une recherche : au plus tant d'éléments par les mots (les plus récents), tant de candidats par le sens (avant le
#: seuil de son rappel), et le texte des premiers ; par les mots, seulement à partir de tant de lettres
SEARCH_WORDS = 40
SEARCH_MEANING = 60
SEARCH_TEXTS = 12
SEARCH_MAX = 200
SEARCH_WORD_MIN = 3
#: par le sens, tout ce dont la pertinence (le score affiché) dépasse ce seuil — choisi par la propriétaire : tout
#: au-dessus de 0,4, sans écart au meilleur
SEARCH_FLOOR = 0.4

#: la sorte d'épisode d'une parole → l'agent qui parcourt sa mémoire
AGENTS = {Kind.REPLY: "reponse", Kind.INITIATIVE: "initiative", Kind.MURMUR: "murmure", Kind.STEP: "travail",
          Kind.WORK: "travail", Kind.JOB: "travail", Kind.WAKE: "travail", Kind.WAKE_JOB: "travail",
          Kind.TASK: "travail", Kind.JOURNAL: "journal", Kind.DREAM: "reve", Kind.NARRATIVE: "recit"}
#: les références de provenance qui désignent un point de la carte
_POINT_REFS = ("memory:", memory_c.VEILED_PROVENANCE, "chunk:")
_BIRTHS = (memory_c.REMEMBERED, memory_c.BELIEVED, memory_c.PROMISE_NOTICED, memory_c.EVENT_NOTED)
_WATCHED = frozenset({rt.UTTERANCE, *_BIRTHS, memory_c.REINFORCED, memory_c.NIGHT_SORTED, memory_c.JOINED,
                      memory_c.CONFRONTED, memory_c.REREAD, self_c.DREAMT, self_c.NARRATED, self_c.JOURNALED,
                      SUBJECT_FORGOTTEN})
_BIRTH_KIND = {memory_c.REMEMBERED: memory_c.SOUVENIR, memory_c.BELIEVED: memory_c.BELIEF,
               memory_c.PROMISE_NOTICED: memory_c.PROMISE, memory_c.EVENT_NOTED: memory_c.EVENT}


@dataclass(slots=True)
class Map:
    """La carte en vigueur : une ligne par point, dans l'ordre des clés."""

    keys: list[int]
    kinds: list[str]
    persons: list[tuple[str, ...]]
    #: (n, d) : les vecteurs normalisés (placer ce qui arrive près de ses voisins)
    mat: np.ndarray
    #: (n, 3) : la direction de chaque point
    dirs: np.ndarray
    edges: np.ndarray
    edge_sims: np.ndarray
    #: ce qui est né sous les yeux d'un écran, pas encore dans l'index
    born: set[int] = field(default_factory=set)
    at: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.at = {k: i for i, k in enumerate(self.keys)}

    def add(self, key: int, kind: str, persons: tuple[str, ...], vec: np.ndarray, direction: np.ndarray) -> None:
        self.at[key] = len(self.keys)
        self.keys.append(key)
        self.kinds.append(kind)
        self.persons.append(persons)
        self.mat = np.vstack([self.mat, lay.normalized(vec[None, :])]) if len(self.mat) else lay.normalized(vec[None, :])
        self.dirs = np.vstack([self.dirs, direction[None, :]]).astype(np.float32)
        self.born.add(key)


def _secs(us: Any) -> int:
    return int(us) // US if us else 0


def _excerpt(text: str | None, limit: int = EXCERPT) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _dir(v: np.ndarray) -> list[float]:
    return [round(float(x), 4) for x in v]


def point_refs(provenance: Sequence[str]) -> list[int]:
    """Les éléments de la carte qu'une provenance désigne (``memory:12``, ``veiled:12``, ``chunk:40``), dans l'ordre,
    chacun une fois."""
    out: list[int] = []
    for ref in provenance:
        for prefix in _POINT_REFS:
            if ref.startswith(prefix) and ref[len(prefix):].isdigit():
                n = int(ref[len(prefix):])
                if n not in out:
                    out.append(n)
    return out


class Constellation:
    """La page, sa carte et son flux. ``listen`` s'abonne au noyau ; ``start``/``stop`` suivent le serveur."""

    def __init__(self, kernel: Any, vectors: Any, accounts: Any, *, names: Names | None = None) -> None:
        self.kernel = kernel
        self.vectors = vectors
        self.accounts = accounts
        self.names = names or Names(kernel)
        self._map: Map | None = None
        self._building = asyncio.Lock()
        self._feed: deque[dict[str, Any]] = deque(maxlen=FEED_MAX)
        self._last = 0
        self._watched_until = 0
        self._queue: asyncio.Queue[Sequence[Any]] | None = None
        self._worker: asyncio.Task[None] | None = None

    # ── le cycle de vie ──
    def start(self) -> None:
        if self._worker is None:
            self._queue = asyncio.Queue(maxsize=256)
            self._worker = asyncio.get_running_loop().create_task(self._work())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def now(self) -> int:
        return int(self.kernel.deps.clock.now())

    def watching(self) -> bool:
        return self.now() < self._watched_until

    def _watched(self) -> None:
        self._watched_until = self.now() + WATCH_S * US

    # ── l'abonnement ──
    def listen(self, events: Sequence[Any], root: Any) -> None:
        """Chaque lot commité : ce qui nomme des éléments part au traducteur, seulement si quelqu'un regarde."""
        if self._queue is None or not self.watching():
            return
        kept = [e for e in events if e.type in _WATCHED]
        if kept:
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(kept)

    async def _work(self) -> None:
        assert self._queue is not None
        while True:
            batch = await self._queue.get()
            try:
                for item in await self.translate(batch):
                    self.publish(item)
            except Exception:  # noqa: BLE001 — un écran qui ne suit plus ne doit rien faire tomber
                log.exception("constellation : un lot d'événements n'a pas pu être traduit")

    def publish(self, item: dict[str, Any]) -> dict[str, Any]:
        self._last += 1
        item = {"id": self._last, **item}
        self._feed.append(item)
        return item

    def since(self, after: int) -> list[dict[str, Any]]:
        return [e for e in self._feed if e["id"] > after]

    # ── la carte ──
    async def ensure_map(self) -> Map:
        """La carte en vigueur, recalculée (en partant de la précédente) si l'index a gagné ou perdu des points."""
        async with self._building:
            indexed = self.vectors.indexed()
            if len(indexed) > MAX_POINTS:
                indexed = set(sorted(indexed)[-MAX_POINTS:])
            current = self._map
            if current is not None:
                have = set(current.keys)
                # rien de nouveau dans l'index, rien d'oublié, et ce qui est né sous nos yeux n'y est pas encore : la
                # même carte (un élément né puis indexé se repose, lui, parmi les siens)
                if not (indexed - have) and not ((have - current.born) - indexed) and not (current.born & indexed):
                    return current
            keys, kinds, persons, mat = await self.vectors.dump(limit=MAX_POINTS)
            previous = None
            if current is not None:
                previous = lay.carried_over(keys, {k: current.dirs[i] for k, i in current.at.items()})
            made = await asyncio.to_thread(lay.layout, mat, previous=previous) if len(keys) else None
            if made is None:
                self._map = Map([], [], [], np.zeros((0, 0), dtype=np.float32), np.zeros((0, 3), dtype=np.float32),
                                np.zeros((0, 2), dtype=np.int32), np.zeros(0, dtype=np.float32))
            else:
                edges, sims = made.edges()
                self._map = Map(keys, kinds, persons, lay.normalized(mat), made.dirs, edges, sims)
            return self._map

    def pending(self) -> int:
        """Ce que l'index a gagné depuis le dernier calcul de la carte (à placer au prochain)."""
        if self._map is None:
            return 0
        indexed = self.vectors.indexed()
        if len(indexed) > MAX_POINTS:
            indexed = set(sorted(indexed)[-MAX_POINTS:])
        return len(indexed - self._map.at.keys())

    def _her(self) -> str:
        return name_of(self.kernel.mind.root.slices["self"].persona)

    def _ledger(self, keys: Sequence[int]) -> dict[int, tuple[Any, ...]]:
        if not keys:
            return {}
        v = memory_c.LEDGER
        got = call(self.kernel.mind.store.query_mind,
                   select(v.c.id, v.c.status, v.c.importance, v.c.confidence, v.c.emotion, v.c.born_at,
                          v.c.recalled_at, v.c.recalls, v.c.sensitivity, v.c.secret), label="constellation : registre")
        wanted = set(keys)
        return {} if isinstance(got, Failed) else {int(r[0]): tuple(r[1:]) for r in got if int(r[0]) in wanted}

    def _chunks(self, keys: Sequence[int]) -> dict[int, int]:
        if not keys:
            return {}
        t = memory_c.chunks_table()
        got = call(self.kernel.mind.store.query_mind, select(t.c.id, t.c.at), label="constellation : échanges")
        wanted = set(keys)
        return {} if isinstance(got, Failed) else {int(r[0]): int(r[1] or 0) for r in got if int(r[0]) in wanted}

    async def payload(self) -> dict[str, Any]:
        """La carte pour l'écran : la géométrie et ce qu'il faut pour colorer, jamais les textes."""
        m = await self.ensure_map()
        n = len(m.keys)
        ledger = self._ledger([k for k, kind in zip(m.keys, m.kinds, strict=True) if not kind.endswith("chunk")])
        chunks = self._chunks([k for k, kind in zip(m.keys, m.kinds, strict=True) if kind.endswith("chunk")])
        kinds = sorted(set(m.kinds))
        people = Counter(p[0] for p in m.persons if p)
        persons = [p for p, _ in people.most_common()]
        person_at = {p: i for i, p in enumerate(persons)}
        emotions: list[str] = []
        statuses: list[str] = []
        cols: dict[str, list[Any]] = {c: [] for c in ("importance", "confidence", "born", "recalled", "recalls",
                                                      "sensitivity", "secret", "status", "emotion")}
        for key in m.keys:
            row = ledger.get(key)
            if row is None:
                status, importance, confidence, emotion, born, recalled, recalls, sens, secret = (
                    "", None, None, None, chunks.get(key, 0), 0, 0, None, 0)
            else:
                status, importance, confidence, emotion, born, recalled, recalls, sens, secret = row
            if status and status not in statuses:
                statuses.append(str(status))
            if emotion and emotion not in emotions:
                emotions.append(str(emotion))
            cols["importance"].append(round(float(importance), 3) if importance is not None else -1)
            cols["confidence"].append(round(float(confidence), 3) if confidence is not None else -1)
            cols["born"].append(_secs(born))
            cols["recalled"].append(_secs(recalled))
            cols["recalls"].append(int(recalls or 0))
            cols["sensitivity"].append(int(sens) if sens is not None else -1)
            cols["secret"].append(1 if secret else 0)
            cols["status"].append(statuses.index(str(status)) if status else -1)
            cols["emotion"].append(emotions.index(str(emotion)) if emotion else -1)
        return {
            "her": self._her(),
            "head": self._last,
            "now": self.now() // US,
            # combien l'index en compte : au-delà de ``MAX_POINTS``, les plus anciens ne sont pas sur la carte
            "total": max(len(self.vectors.indexed()), n),
            "shown": n,
            "kinds": kinds,
            "statuses": statuses,
            "emotions": emotions,
            "persons": [{"key": p, "name": self.names.name_of(p) or p, "count": people[p]} for p in persons],
            "points": {
                "key": m.keys,
                "kind": [kinds.index(k) for k in m.kinds],
                "dir": [round(float(x), 4) for x in m.dirs.ravel()],
                "person": [person_at[p[0]] if p else -1 for p in m.persons],
                **cols,
            },
            "edges": [int(x) for x in m.edges.ravel()],
            "edge_sims": [round(float(x), 3) for x in m.edge_sims],
        }

    def point(self, key: int) -> dict[str, Any] | None:
        """Ce qu'un point garde : son texte, qui il concerne, d'où il vient — pour l'opératrice qui l'ouvre."""
        v = memory_c.LEDGER
        got = call(self.kernel.mind.store.query_mind,
                   select(v.c.id, v.c.kind, v.c.text, v.c.about, v.c.told_by, v.c.importance, v.c.confidence,
                          v.c.emotion, v.c.born_at, v.c.recalled_at, v.c.recalls, v.c.sensitivity, v.c.secret,
                          v.c.status, v.c.knowledge_kind, v.c.origin).where(v.c.id == key),
                   label="constellation : un point")
        if not isinstance(got, Failed) and got:
            (_, kind, text, about, told_by, importance, confidence, emotion, born, recalled, recalls, sens, secret,
             status, knowledge_kind, origin) = got[0]
            return {"key": key, "kind": kind, "text": text or "", "about": self._who(about),
                    "told_by": self._who(told_by), "importance": importance, "confidence": confidence,
                    "emotion": emotion, "born": _secs(born), "recalled": _secs(recalled), "recalls": int(recalls or 0),
                    "sensitivity": sens, "secret": bool(secret), "status": status or "",
                    "knowledge_kind": knowledge_kind or "", "origin": origin or "",
                    "href": f"{PREFIX}/evenement/{key}"}
        t = memory_c.chunks_table()
        got = call(self.kernel.mind.store.query_mind,
                   select(t.c.id, t.c.person, t.c.room, t.c.user_text, t.c.reply_text, t.c.at).where(t.c.id == key),
                   label="constellation : un échange")
        if isinstance(got, Failed) or not got:
            return None
        _, person, room, said, reply, at = got[0]
        return {"key": key, "kind": memory_c.ROOM_CHUNK if room else memory_c.CHUNK, "said": said or "",
                "reply": reply or "", "about": [self.names.name_of(person) or person] if person else [],
                "born": _secs(at), "href": f"{PREFIX}/parole/{key}"}

    def _texts(self, keys: Sequence[int]) -> dict[int, str]:
        """Le texte de ces points : celui d'un élément, ou l'échange (ce qu'on lui a dit → ce qu'elle a répondu)."""
        if not keys:
            return {}
        v, t = memory_c.LEDGER, memory_c.chunks_table()
        out: dict[int, str] = {}
        got = call(self.kernel.mind.store.query_mind, select(v.c.id, v.c.text).where(v.c.id.in_(list(keys))),
                   label="constellation : textes")
        if not isinstance(got, Failed):
            out.update({int(k): text or "" for k, text in got})
        rest = [k for k in keys if k not in out]
        if rest:
            got = call(self.kernel.mind.store.query_mind,
                       select(t.c.id, t.c.user_text, t.c.reply_text).where(t.c.id.in_(rest)),
                       label="constellation : textes d'échanges")
            if not isinstance(got, Failed):
                out.update({int(k): " → ".join(x for x in (said, reply) if x) for k, said, reply in got})
        return out

    async def search(self, q: str) -> dict[str, Any]:
        """Recadrer sur quelque chose : les éléments dont le texte **contient** ces mots (replié, casse et accents
        ignorés, comme la console), puis ceux qui leur **ressemblent** — notés comme sa recherche délibérée (la
        similarité des vecteurs, plus un bonus pour les mots du sujet qu'ils contiennent), tous ceux au-dessus de
        ``SEARCH_FLOOR``. Seulement ce qui est sur la carte ; ``query`` : où se poserait la requête parmi eux."""
        q = " ".join(q.split())[:SEARCH_MAX]
        if not q:
            return {"q": "", "hits": [], "query": None}
        m = self._map if self._map is not None else await self.ensure_map()
        words: list[int] = []
        if len(fold_text(q)) >= SEARCH_WORD_MIN:
            v = memory_c.LEDGER
            got = call(self.kernel.mind.store.query_mind,
                       select(v.c.id).where(v.c.folded.contains(fold_text(q), autoescape=True))
                       .order_by(v.c.id.desc()).limit(SEARCH_WORDS), label="constellation : recherche")
            words = [] if isinstance(got, Failed) else [int(r[0]) for r in got if int(r[0]) in m.at]
        found = [(k, s) for k, s in await self.vectors.search(q, SEARCH_MEANING) if k in m.at]
        texts = self._texts([k for k, _ in found])
        wanted = topic(q)
        scored = {k: relevance(s, wanted, texts.get(k, "")) for k, s in found}
        meaning = sorted(((k, s) for k, s in scored.items() if s > SEARCH_FLOOR), key=lambda hit: (-hit[1], hit[0]))
        seen = set(words)
        hits: list[dict[str, Any]] = [{"key": k, "how": "mot"} for k in words]
        hits += [{"key": k, "how": "sens", "score": round(float(s), 3)} for k, s in meaning if k not in seen]
        texts.update(self._texts([h["key"] for h in hits[:SEARCH_TEXTS] if h["key"] not in texts]))
        for h in hits[:SEARCH_TEXTS]:
            h["text"] = _excerpt(texts.get(h["key"]), 160)
        if meaning:
            query = lay.toward(m.dirs[[m.at[k] for k, _ in meaning]], [s for _, s in meaning])
        elif words:
            query = lay.toward(m.dirs[[m.at[k] for k in words]], [1.0] * len(words))
        else:
            query = None
        return {"q": q, "hits": hits, "query": _dir(query) if query is not None else None}

    def _who(self, raw: Any) -> list[str]:
        """Les noms derrière une colonne de clés (une liste JSON)."""
        try:
            keys = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return [self.names.name_of(str(k)) or str(k) for k in keys if k] if isinstance(keys, list) else []

    # ── la traduction ──
    async def translate(self, events: Sequence[Any]) -> list[dict[str, Any]]:
        """Ce que ces événements font à la carte, en éléments de flux (des clés et des directions, pas de textes —
        sauf l'extrait d'un message auquel elle répondait). La carte n'est pas recalculée pour autant : ce qui naît
        s'y pose près de ses voisins, le reste de l'index attend le prochain calcul (``pending``)."""
        m = self._map if self._map is not None else await self.ensure_map()
        out: list[dict[str, Any]] = []
        births = [e for e in events if e.type in _BIRTHS and e.seq not in m.at]
        if births:
            out += await self._births(m, births)
        for e in events:
            item = await self._one(m, e)
            if item is not None:
                out.append({"seq": e.seq, "at": e.at // US, **item})
        return out

    async def _one(self, m: Map, e: Any) -> dict[str, Any] | None:
        d = e.data
        if e.type is rt.UTTERANCE:
            return await self._utterance(m, e)
        if e.type is memory_c.REINFORCED:
            return {"type": "renfort", "agent": "memoire", "key": d.item, "corroborated": d.corroborated} \
                if d.item in m.at else None
        if e.type in (memory_c.NIGHT_SORTED, memory_c.JOINED):
            pairs = d.merges if e.type is memory_c.NIGHT_SORTED else d.pairs
            kept = [[a, b] for a, b in pairs if a in m.at and b in m.at]
            return {"type": "fusion", "agent": "nuit", "pairs": kept,
                    "how": "fondu" if e.type is memory_c.NIGHT_SORTED else "joint"} if kept else None
        if e.type is memory_c.CONFRONTED:
            replaced = [[a, b] for a, b in d.supersedes if a in m.at and b in m.at]
            contested = [[a, b] for a, b in d.contests if a in m.at and b in m.at]
            return {"type": "confrontation", "agent": "nuit", "replaced": replaced, "contested": contested} \
                if replaced or contested else None
        if e.type is memory_c.REREAD:
            return {"type": "relecture", "agent": "nuit", "readings": d.readings, "pairs": d.pairs}
        if e.type in (self_c.DREAMT, self_c.NARRATED, self_c.JOURNALED):
            sources = d.lineage.sources if e.type is self_c.JOURNALED and d.lineage is not None else \
                getattr(d, "sources", ())
            keys = [k for k in dict.fromkeys(sources) if k in m.at]
            agent = {self_c.DREAMT: "reve", self_c.NARRATED: "recit", self_c.JOURNALED: "journal"}[e.type]
            return {"type": "parcours", "agent": agent, "keys": keys} if keys else None
        if e.type is SUBJECT_FORGOTTEN:
            return {"type": "carte"}
        return None

    async def _utterance(self, m: Map, e: Any) -> dict[str, Any] | None:
        d = e.data
        refs = point_refs(d.provenance)
        shown = [k for k in refs if k in m.at]
        if not shown:
            return None
        asked = d.answers[-1] if d.answers else d.reply_to
        message = self._message(asked) if asked else None
        probed: list[list[float]] = []
        query = None
        if message:
            hits = await self.vectors.search(message, PROBE)
            near = [(k, s) for k, s in hits if k in m.at]
            probed = [[k, round(float(s), 3)] for k, s in near]
            if near:
                query = lay.toward(m.dirs[[m.at[k] for k, _ in near]], [s for _, s in near])
        if query is None:
            query = lay.toward(m.dirs[[m.at[k] for k in shown]], [1.0] * len(shown))
        return {"type": "rappel", "agent": AGENTS.get(d.kind, "autre"),
                "who": self.names.who(d.target), "message": _excerpt(message), "query": _dir(query),
                "probed": probed, "shown": shown, "missing": len(refs) - len(shown)}

    def _message(self, seq: int) -> str | None:
        """Le texte que la personne a tapé (sans ce que ses fichiers ont donné à percevoir)."""
        found = call(self.kernel.mind.store.get_events, [seq], label="constellation : un message")
        if isinstance(found, Failed) or not found:
            return None
        ev = self.kernel.mind.decode(found[0])
        text = self.kernel.mind.content_text(getattr(ev.data, "text", None))
        typed = getattr(ev.data, "typed_chars", None)
        return (text[:typed] if typed is not None else text) if text else None

    async def _births(self, m: Map, events: Sequence[Any]) -> list[dict[str, Any]]:
        texts = [self.kernel.mind.content_text(e.data.text) or "" for e in events]
        keep = [(e, t) for e, t in zip(events, texts, strict=True) if t.strip()]
        if not keep:
            return []
        vecs = np.asarray(await self.vectors.embedder.embed([t for _, t in keep]), dtype=np.float32)
        out = []
        for (e, _), vec in zip(keep, vecs, strict=True):
            direction, idx, _ = lay.place(vec, m.mat, m.dirs) if len(m.keys) else (
                lay.normalized(np.ones((1, 3), dtype=np.float32))[0], np.zeros(0, dtype=np.int32), None)
            near = [m.keys[i] for i in idx[:3]]
            kind = _BIRTH_KIND[e.type]
            about = tuple(getattr(e.data, "about", ()) or ((e.data.to,) if e.type is memory_c.PROMISE_NOTICED else ()))
            m.add(e.seq, kind, about, vec, direction)
            out.append({"seq": e.seq, "at": e.at // US, "type": "naissance", "agent": "memoire", "key": e.seq,
                        "kind": kind, "dir": _dir(direction), "near": near,
                        "importance": float(getattr(e.data, "importance", 0.5) or 0.5),
                        "person": about[0] if about else "",
                        "person_name": (self.names.name_of(about[0]) or about[0]) if about else ""})
        return out

    async def replay(self, n: int) -> list[dict[str, Any]]:
        """Les dernières paroles qui se sont souvenues de quelque chose, le dernier rêve et le dernier récit, traduits
        comme en direct : de quoi voir la boule vivre quand personne ne parle."""
        store = self.kernel.mind.store
        picked: list[Any] = []
        got = call(store.latest, [rt.UTTERANCE.name], max(1, n) * 4, label="constellation : paroles")
        if not isinstance(got, Failed):
            for stored in got:
                ev = self.kernel.mind.decode(stored)
                if point_refs(ev.data.provenance):
                    picked.append(ev)
                if len(picked) >= n:
                    break
        for t in (self_c.DREAMT, self_c.NARRATED):
            got = call(store.latest, [t.name], 1, label="constellation : nuits")
            if not isinstance(got, Failed):
                picked += [self.kernel.mind.decode(s) for s in got]
        picked.sort(key=lambda ev: ev.seq)
        m = await self.ensure_map()
        out = []
        for ev in picked:
            item = await self._one(m, ev)
            if item is not None:
                out.append({"seq": ev.seq, "at": ev.at // US, "replay": True, **item})
        return out

    # ── HTTP ──
    def _operator(self, request: Request) -> bool:
        account = self.accounts.session(request.cookies.get(SESSION_COOKIE))
        return account is not None and account.operator

    async def page(self, request: Request) -> Response:
        if not self._operator(request):
            return secure(RedirectResponse(f"{PREFIX}/connexion", status_code=303))
        html = env.get_template("constellation.html").render(her=self._her(), base=BASE)
        return secure(HTMLResponse(html))

    async def map_json(self, request: Request) -> Response:
        if not self._operator(request):
            return secure(Response(status_code=401))
        self._watched()
        return secure(JSONResponse(await self.payload()))

    async def feed_json(self, request: Request) -> Response:
        if not self._operator(request):
            return secure(Response(status_code=401))
        self._watched()
        try:
            after = int(request.query_params.get("apres", "0"))
        except ValueError:
            after = 0
        return secure(JSONResponse({"head": self._last, "events": self.since(after), "pending": self.pending()}))

    async def point_json(self, request: Request) -> Response:
        if not self._operator(request):
            return secure(Response(status_code=401))
        got = self.point(int(request.path_params["key"]))
        return secure(JSONResponse(got) if got is not None else Response(status_code=404))

    async def search_json(self, request: Request) -> Response:
        if not self._operator(request):
            return secure(Response(status_code=401))
        return secure(JSONResponse(await self.search(request.query_params.get("q", ""))))

    async def replay_json(self, request: Request) -> Response:
        if not self._operator(request):
            return secure(Response(status_code=401))
        self._watched()
        try:
            n = max(1, min(REPLAY_MAX, int(request.query_params.get("n", "12"))))
        except ValueError:
            n = 12
        return secure(JSONResponse({"events": await self.replay(n)}))

    def routes(self) -> list[Route]:
        """À poser avant celles de la console (son adresse attrape tout ``/inspecteur/<clé>``)."""
        return [Route(BASE, self.page, methods=["GET"]),
                Route(f"{BASE}/carte", self.map_json, methods=["GET"]),
                Route(f"{BASE}/flux", self.feed_json, methods=["GET"]),
                Route(f"{BASE}/rejeu", self.replay_json, methods=["GET"]),
                Route(f"{BASE}/cherche", self.search_json, methods=["GET"]),
                Route(BASE + "/point/{key:int}", self.point_json, methods=["GET"])]
