"""Les traces d'épisode, dans ``views.db`` (jetable) : ce qu'elle avait sous
les yeux quand elle a parlé.

Le journal dit ce qui s'est passé (le déclencheur, la phrase, les sections
incluses) ; la trace garde ce qui a réellement été envoyé au modèle — le
préfixe stable, les tours de conversation, les outils offerts —, comment le
prompt a été composé (sections incluses et leur taille, coupées et pourquoi),
chaque appel d'outil avec ses arguments et son résultat, et les appels de
modèle. De quoi répondre après coup à « pourquoi a-t-elle dit ça ? ».

- Une ligne par épisode (clé : sa corrélation), écrite à la composition puis
  remplacée au règlement — un épisode coupé en route garde ce qu'il a vu.
- Le préfixe stable, identique d'un épisode à l'autre tant que la persona et
  les sections stables ne bougent pas, est rangé une seule fois par empreinte
  (``prompt_blobs``) et réinséré à la lecture.
- Bornée : chaque texte à ``MAX_TEXT`` caractères, chaque trace à ~``MAX_BLOB``
  octets, avec une marque explicite ; ``keep_days`` jours et ``max_rows`` lignes.
- L'oubli efface **toutes** les traces : un prompt mêle les personnes (le fil
  partagé, les souvenirs d'autrui), l'oubli est rare et ces données jetables.
- Chaque appel d'outil d'une trace a aussi sa ligne dans ``tool_uses`` (nom,
  réussi, exécuté, quand, épisode — jamais ses arguments) : de quoi compter les
  appels d'un outil sans décompresser les traces. Remplacées avec la trace,
  élaguées et oubliées avec elle.

Les écritures partent en tâches depuis du code synchrone (le pipeline n'attend
jamais sa trace) ; ``flush`` les attend.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import zlib
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mika.kernel.clock import DAY
from mika.ports.store import EventStore, Sql

log = logging.getLogger("mika.traces")

TABLE = "episode_traces"
BLOBS = "prompt_blobs"
USES = "tool_uses"
KEEP_DAYS = 14
MAX_ROWS = 3000
#: un texte (message, préfixe stable, réponse) au-delà : coupé
MAX_TEXT = 200_000
#: une trace (JSON, hors préfixe stable) au-delà : ses plus gros textes rétrécis
MAX_BLOB = 1_000_000
#: ce que contient toute marque de coupe (à chercher pour signaler une trace incomplète)
TRUNCATION_MARK = "[tronqué pour la trace"
#: la clé du préfixe stable dans une trace (rangé à part, réinséré à la lecture)
STABLE_KEY = "system_stable"
_MIN_CAP = 2_000
_PRUNE_EVERY = 50
#: les épisodes dont une trace a été écrite récemment (voir ``forget``)
_RECENT_KEPT = 512


@dataclass(frozen=True, slots=True)
class TraceHead:
    """Une trace sans son contenu : de quoi lister."""

    correlation: str
    at: int
    kind: str
    target: str | None


@dataclass(frozen=True, slots=True)
class ToolUsage:
    """Ce qu'un outil a servi depuis un instant : appels, échecs, le dernier."""

    calls: int
    failures: int
    last_at: int


@dataclass(frozen=True, slots=True)
class ToolUse:
    """Un appel d'outil, sans ses arguments : l'épisode où le relire."""

    correlation: str
    at: int
    kind: str
    ok: bool
    executed: bool


class EpisodeTraces:
    def __init__(self, store: EventStore, *, keep_days: int = KEEP_DAYS, max_rows: int = MAX_ROWS) -> None:
        self.store = store
        self.keep_us = keep_days * DAY
        self.max_rows = max(1, max_rows)
        self._pending: set[asyncio.Task[Any]] = set()
        self._since_prune = 0
        self._ready = False
        self._recent: deque[str] = deque(maxlen=_RECENT_KEPT)
        #: épisodes en vol au moment d'un oubli : leur trace ne revient pas
        self._barred: frozenset[str] = frozenset()

    async def open(self) -> None:
        def create(sql: Sql) -> None:
            sql.execute(f"CREATE TABLE IF NOT EXISTS {TABLE}(correlation TEXT PRIMARY KEY, at INTEGER, "
                        f"kind TEXT, target TEXT, stable TEXT, blob BLOB)")
            sql.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_at ON {TABLE}(at)")
            sql.execute(f"CREATE TABLE IF NOT EXISTS {BLOBS}(hash TEXT PRIMARY KEY, text BLOB)")
            sql.execute(f"CREATE TABLE IF NOT EXISTS {USES}(correlation TEXT, at INTEGER, kind TEXT, name TEXT, "
                        f"ok INTEGER, executed INTEGER)")
            sql.execute(f"CREATE INDEX IF NOT EXISTS {USES}_name ON {USES}(name, at)")
            sql.execute(f"CREATE INDEX IF NOT EXISTS {USES}_corr ON {USES}(correlation)")

        await self.store.run_views(create)
        self._ready = True

    # ── écriture ──
    def record(self, correlation: str, at: int, kind: str, target: str | None, data: Mapping[str, Any]) -> None:
        """Range (ou remplace) la trace d'un épisode. Synchrone : l'écriture part
        en tâche. ``data`` est du JSON (dicts, listes, textes, nombres) que
        l'appelant ne modifie plus ; ``data["system_stable"]`` est rangé à part."""
        if not self._ready or correlation in self._barred:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if not self._recent or self._recent[-1] != correlation:
            self._recent.append(correlation)
        self._since_prune += 1
        prune = self._since_prune >= _PRUNE_EVERY
        if prune:
            self._since_prune = 0
        keep_us, max_rows = self.keep_us, self.max_rows

        def write(sql: Sql) -> None:
            body = dict(data)
            full = str(body.pop(STABLE_KEY, "") or "")
            stable = _clip_text(full, MAX_TEXT)
            key = hashlib.blake2b(stable.encode(), digest_size=16).hexdigest() if stable else None
            body[f"{STABLE_KEY}_hash"] = key
            if len(stable) != len(full):
                body[f"{STABLE_KEY}_truncated"] = True
            blob = zlib.compress(_bounded_json(body).encode())
            if key is not None:
                sql.execute(f"INSERT OR IGNORE INTO {BLOBS}(hash, text) VALUES(?, ?)",
                            (key, zlib.compress(stable.encode())))
            sql.execute(f"INSERT OR REPLACE INTO {TABLE}(correlation, at, kind, target, stable, blob) "
                        f"VALUES(?, ?, ?, ?, ?, ?)", (correlation, at, kind, target, key, blob))
            if isinstance(body.get("tool_calls"), list):
                sql.execute(f"DELETE FROM {USES} WHERE correlation=?", (correlation,))
                for t in body["tool_calls"]:
                    if isinstance(t, Mapping) and t.get("name"):
                        sql.execute(f"INSERT INTO {USES}(correlation, at, kind, name, ok, executed) "
                                    f"VALUES(?, ?, ?, ?, ?, ?)",
                                    (correlation, at, kind, str(t["name"])[:200], int(bool(t.get("ok"))),
                                     int(bool(t.get("executed", True)))))
            if prune:
                _prune(sql, at - keep_us, max_rows)

        task = loop.create_task(self.store.run_views(write))
        self._pending.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._pending.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("traces d'épisode : écriture perdue (%r)", task.exception())

    async def flush(self) -> None:
        while self._pending:
            batch = list(self._pending)
            await asyncio.gather(*batch, return_exceptions=True)
            # attendre des tâches déjà finies ne rend pas la main à la boucle : leurs
            # rappels (qui les retirent) n'ont pas encore tourné — on les retire ici
            self._pending.difference_update(batch)

    async def prune(self, now: int) -> int:
        """Retire les traces plus vieilles que ``keep_days`` et celles au-delà de
        ``max_rows`` (les plus anciennes), puis les préfixes que plus rien ne cite."""
        await self.flush()
        before, max_rows = now - self.keep_us, self.max_rows
        return int(await self.store.run_views(lambda sql: _prune(sql, before, max_rows)))

    async def forget(self, subject: str) -> int:
        """Efface toutes les traces (``subject`` n'est pas cherché : un prompt
        mêle les personnes). Les épisodes en vol, déjà tracés, ne réécrivent pas
        la leur à leur règlement."""
        self._barred = frozenset(self._recent)
        await self.flush()
        if not self._ready:
            return 0

        def clear(sql: Sql) -> int:
            n = int(sql.query(f"SELECT COUNT(*) FROM {TABLE}")[0][0])
            sql.execute(f"DELETE FROM {TABLE}")
            sql.execute(f"DELETE FROM {BLOBS}")
            sql.execute(f"DELETE FROM {USES}")
            return n

        return int(await self.store.run_views(clear))

    # ── lecture ──
    def get(self, correlation: str) -> dict[str, Any] | None:
        """La trace d'un épisode, décompressée, préfixe stable réinséré
        (``None`` s'il a été élagué entre-temps) ; ``None`` si aucune."""
        if not self._ready:
            return None
        rows = self.store.query_views(
            f"SELECT at, kind, target, stable, blob FROM {TABLE} WHERE correlation=?", (correlation,))
        if not rows:
            return None
        at, kind, target, key, blob = rows[0]
        head = {"correlation": correlation, "at": at, "kind": kind, "target": target}
        try:
            body = json.loads(zlib.decompress(blob).decode())
        except (zlib.error, ValueError) as exc:
            return {**head, "error": f"trace illisible ({exc})"}
        stable: str | None = None
        if key:
            found = self.store.query_views(f"SELECT text FROM {BLOBS} WHERE hash=?", (key,))
            if found:
                try:
                    stable = zlib.decompress(found[0][0]).decode()
                except (zlib.error, ValueError):
                    stable = None
        else:
            stable = ""
        return {**body, **head, STABLE_KEY: stable}

    def recent(self, limit: int = 100, *, kind: str = "", target: str = "") -> list[TraceHead]:
        """Les dernières traces (sans leur contenu), les plus récentes d'abord."""
        if not self._ready:
            return []
        where, args = [], []
        if kind:
            where.append("kind=?")
            args.append(kind)
        if target:
            where.append("target=?")
            args.append(target)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.store.query_views(
            f"SELECT correlation, at, kind, target FROM {TABLE} {clause} ORDER BY at DESC, correlation DESC "
            f"LIMIT ?", (*args, max(1, min(limit, 1000))))
        return [TraceHead(str(c), int(a), str(k), t) for c, a, k, t in rows]

    def count(self) -> int:
        if not self._ready:
            return 0
        return int(self.store.query_views(f"SELECT COUNT(*) FROM {TABLE}")[0][0])

    def tool_usage(self, since: int) -> dict[str, ToolUsage]:
        """Par outil, ses appels depuis ``since`` (ceux qu'un refus a arrêtés avant le gestionnaire compris :
        ce sont des échecs)."""
        if not self._ready:
            return {}
        rows = self.store.query_views(
            f"SELECT name, COUNT(*), SUM(CASE WHEN ok THEN 0 ELSE 1 END), MAX(at) FROM {USES} WHERE at >= ? "
            f"GROUP BY name", (since,))
        return {str(n): ToolUsage(int(c), int(f or 0), int(a)) for n, c, f, a in rows}

    def tool_uses(self, name: str, limit: int = 20) -> list[ToolUse]:
        """Les derniers appels d'un outil, les plus récents d'abord."""
        if not self._ready:
            return []
        rows = self.store.query_views(
            f"SELECT correlation, at, kind, ok, executed FROM {USES} WHERE name=? ORDER BY at DESC, rowid DESC "
            f"LIMIT ?", (name, max(1, min(limit, 500))))
        return [ToolUse(str(c), int(a), str(k), bool(o), bool(e)) for c, a, k, o, e in rows]


# ── bornes ──
def _prune(sql: Sql, before: int, max_rows: int) -> int:
    removed = int(sql.execute(f"DELETE FROM {TABLE} WHERE at < ?", (before,)).rowcount or 0)
    removed += int(sql.execute(
        f"DELETE FROM {TABLE} WHERE correlation IN (SELECT correlation FROM {TABLE} "
        f"ORDER BY at DESC, correlation DESC LIMIT -1 OFFSET ?)", (max_rows,)).rowcount or 0)
    sql.execute(f"DELETE FROM {BLOBS} WHERE hash NOT IN (SELECT stable FROM {TABLE} WHERE stable IS NOT NULL)")
    sql.execute(f"DELETE FROM {USES} WHERE correlation NOT IN (SELECT correlation FROM {TABLE})")
    return removed


def _clip_text(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return f"{text[:cap]} …{TRUNCATION_MARK} : {len(text) - cap} caractères coupés]"


def _clip(value: Any, cap: int, cuts: list[int]) -> Any:
    if isinstance(value, str):
        if len(value) > cap:
            cuts.append(len(value) - cap)
        return _clip_text(value, cap)
    if isinstance(value, Mapping):
        return {str(k): _clip(v, cap, cuts) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v, cap, cuts) for v in value]
    return value


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _bounded_json(body: Mapping[str, Any]) -> str:
    """Le JSON d'une trace, sous ``MAX_BLOB`` octets : chaque texte coupé à
    ``MAX_TEXT``, puis la coupe resserrée tant que ça dépasse ; en dernier
    recours, les plus grosses entrées remplacées par une marque. Une trace
    coupée le dit (``truncated``)."""
    cap = MAX_TEXT
    cuts: list[int] = []
    clipped: dict[str, Any] = _clip(body, cap, cuts)
    raw = _encode(clipped)
    while len(raw.encode()) > MAX_BLOB and cap > _MIN_CAP:
        cap //= 2
        cuts.clear()
        clipped = _clip(body, cap, cuts)
        raw = _encode(clipped)
    while len(raw.encode()) > MAX_BLOB:
        sizes = {k: len(_encode(v).encode()) for k, v in clipped.items()}
        biggest = max(sizes, key=lambda k: (sizes[k], k))
        clipped[biggest] = f"…{TRUNCATION_MARK} : {biggest} omis ({sizes[biggest]} octets)]"
        cuts.append(sizes[biggest])
        raw = _encode(clipped)
    if cuts:
        clipped["truncated"] = True
        raw = _encode(clipped)
    return raw
