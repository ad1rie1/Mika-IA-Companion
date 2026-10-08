"""Les projections T0 de la mémoire (dans la transaction d'ajout) :

- ``memory_items`` : souvenirs, croyances, promesses, moments de la vie des
  autres, avec ce qui les fait durer (importance, renforcements, rappels),
  leur statut, et ce qui décide devant qui ils peuvent ressortir (qui l'a
  confié, qui l'a entendu, secret ou non) ;
- ``memory_chunks`` : les échanges bruts avec chacun (sa question, sa
  réponse), retrouvables sans que la consolidation ait décidé de les garder.

**Montré, ou dit.** Un élément montré dans un prompt n'est pas un élément
dont elle s'est servie : être montré date seulement l'anti-répétition
(``shown_at``) ; seul ce qu'elle a vraiment repris dans ce qu'elle a dit
(au moins deux radicaux en commun) compte comme un rappel, qui le fait durer.

L'oubli d'une personne efface ses lignes : ce qui la concerne, et ce qu'elle a confié.
Une projection reconstruite (sa version change) ne les fait pas revenir : un
élément dont le texte a été oublié ne se recopie pas.

**Tenir des années** (ADR 0059) : ``memory_items`` est indexée par sorte,
statut et naissance ; ``memory_about`` dit qui concerne chaque élément, une
personne par ligne (« ce qu'elle sait d'Alice » ne parcourt plus toute la
mémoire) ; ``memory_chunks`` est indexée par personne et par salon, dans le
temps (« ce que je t'ai dit lundi » se lit sur l'intervalle, jamais par la
liste de tous ses échanges) ; ``memory_forgets`` compte les oublis, pour que
l'index des vecteurs se rapproche de ce qui reste sans tout relire.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.faculty import MEMORY
from mika.kernel.codec import digest
from mika.kernel.faculty import Tier
from mika.ports.store import Sql
from mika.vocab.affect import strip_prosody
from mika.vocab.words import WORD, fold, same_words, stems

ITEM_COLUMNS = ("id", "kind", "text", "about", "sensitivity", "importance", "confidence", "origin", "source",
                "emotion", "born_at", "touched_at", "recalled_at", "recalls", "status", "replaces", "recipient",
                "due", "sources", "told_by", "heard_by", "secret", "informants", "about_self", "shown_at", "between_us",
                "knowledge_kind", "holder", "constraints", "internal_only")
CHUNK_TEXT_MAX = 600
#: élément → la référence de son texte (``Content.ref``)
REFS_TABLE = "memory_refs"
CHANGES_TABLE = "memory_changes"
#: les événements qui créent un élément (et portent son texte)
_CREATES = frozenset({c.REMEMBERED.name, c.BELIEVED.name, c.PROMISE_NOTICED.name, c.EVENT_NOTED.name})
#: deux radicaux en commun entre ce qu'elle a dit et un élément montré : elle s'en est servie
USED_STEMS = 2


def _keys(values: Iterable[str]) -> str:
    return json.dumps(sorted({v for v in values if v}), ensure_ascii=False)


def _loads(raw: str | None) -> list[str]:
    try:
        got = json.loads(raw or "[]")
    except ValueError:
        return []
    return [str(x) for x in got] if isinstance(got, list) else []


def informants_of(source: str | None, told_by: Sequence[str]) -> tuple[str, ...]:
    """Qui le lui a appris : la source nommée, sinon ceux qui le lui ont confié.
    Une croyance redite par un informateur déjà compté n'en devient pas plus sûre."""
    return (source,) if source else tuple(sorted(set(told_by)))


def forgotten(text: Any) -> bool:
    """Un texte oublié (relu après l'oubli de qui il concerne) : sa référence reste, plus son texte."""
    return text is not None and text.ref is not None and text.text is None


def _about_rows(sql: Sql, table: str, item: int, keys: Iterable[str]) -> None:
    sql.executemany(f"INSERT OR IGNORE INTO {table}(item, person) VALUES(?,?)",
                    [(item, k) for k in sorted({k for k in keys if k})])


def used(item_text: str, said: str) -> bool:
    """Elle s'en est servie : ce qu'elle a dit reprend l'élément (radicaux communs)."""
    return len(stems(item_text) & stems(said)) >= USED_STEMS


def fingerprint(text: str) -> str:
    return digest(WORD.findall(fold(text)))


class Items:
    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {c.ITEMS_TABLE}{sfx}(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
            "text TEXT NOT NULL, about TEXT NOT NULL, sensitivity INTEGER NOT NULL, importance REAL NOT NULL, "
            "confidence REAL, origin TEXT, source TEXT, emotion TEXT, born_at INTEGER NOT NULL, "
            "touched_at INTEGER NOT NULL, recalled_at INTEGER NOT NULL DEFAULT 0, recalls INTEGER NOT NULL DEFAULT 0, "
            "status TEXT NOT NULL, replaces INTEGER, recipient TEXT, due INTEGER, sources TEXT NOT NULL, "
            "told_by TEXT NOT NULL DEFAULT '[]', heard_by TEXT NOT NULL DEFAULT '[]', "
            "secret INTEGER NOT NULL DEFAULT 0, informants TEXT NOT NULL DEFAULT '[]', "
            "about_self INTEGER NOT NULL DEFAULT 0, shown_at INTEGER NOT NULL DEFAULT 0, "
            "between_us INTEGER NOT NULL DEFAULT 0, knowledge_kind TEXT NOT NULL DEFAULT 'claim', holder TEXT, "
            "constraints TEXT NOT NULL DEFAULT '[]', internal_only INTEGER NOT NULL DEFAULT 0, fingerprint TEXT NOT NULL DEFAULT '')"
        )
        t, about = f"{c.ITEMS_TABLE}{sfx}", f"{c.ABOUT_TABLE}{sfx}"
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_kind ON {t}(kind, status, born_at)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_fingerprint ON {t}"
                    "(fingerprint, kind, status, about, told_by, heard_by)")
        sql.execute(f"CREATE TABLE IF NOT EXISTS {about}(item INTEGER NOT NULL, person TEXT NOT NULL, "
                    "PRIMARY KEY(item, person)) WITHOUT ROWID")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {about}_person ON {about}(person, item)")
        sql.execute(f"CREATE TABLE IF NOT EXISTS {REFS_TABLE}{sfx}(item INTEGER PRIMARY KEY, ref TEXT NOT NULL)")
        sql.execute(f"CREATE TABLE IF NOT EXISTS {CHANGES_TABLE}{sfx}(item INTEGER PRIMARY KEY, seq INTEGER NOT NULL)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {CHANGES_TABLE}{sfx}_seq ON {CHANGES_TABLE}{sfx}(seq)")
        sql.execute(f"CREATE TABLE IF NOT EXISTS {c.FORGETS_TABLE}{sfx}(n INTEGER NOT NULL)")
        if not sql.query(f"SELECT 1 FROM {c.FORGETS_TABLE}{sfx}"):
            sql.execute(f"INSERT INTO {c.FORGETS_TABLE}{sfx}(n) VALUES(0)")

    def drop(self, sql: Sql, sfx: str) -> None:
        for table in (c.ITEMS_TABLE, c.ABOUT_TABLE, c.FORGETS_TABLE, REFS_TABLE, CHANGES_TABLE):
            sql.execute(f"DROP TABLE IF EXISTS {table}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t, about = f"{c.ITEMS_TABLE}{sfx}", f"{c.ABOUT_TABLE}{sfx}"
        cols = ",".join(ITEM_COLUMNS)
        marks = ",".join("?" * len(ITEM_COLUMNS))

        def insert(row: dict[str, Any]) -> None:
            full = {"confidence": None, "origin": None, "source": None, "emotion": None, "recalled_at": 0,
                    "recalls": 0, "replaces": None, "recipient": None, "due": None, "told_by": "[]",
                    "heard_by": "[]", "secret": 0, "informants": "[]", "about_self": 0, "shown_at": 0, "between_us": 0,
                    "knowledge_kind": "claim", "holder": None, "constraints": "[]", "internal_only": 0,
                    **row}
            sql.execute(f"INSERT OR REPLACE INTO {t}({cols},fingerprint) VALUES({marks},?)",
                        (*[full[k] for k in ITEM_COLUMNS], fingerprint(full["text"])))
            _about_rows(sql, about, int(full["id"]), _loads(full["about"]))

        for e in events:
            d = e.data
            name = e.type.name
            changed = set()
            if name in _CREATES:
                changed.add(e.seq)
            for attr in ("item", "replaces", "promise", "event"):
                if (item_id := getattr(d, attr, None)) is not None:
                    changed.add(item_id)
            if name == c.NIGHT_SORTED.name:
                changed.update(i for pair in d.merges for i in pair)
            sql.executemany(f"INSERT OR REPLACE INTO {CHANGES_TABLE}{sfx}(item, seq) VALUES(?,?)",
                            [(i, e.seq) for i in sorted(changed)])
            if name in _CREATES and forgotten(d.text):
                continue  # relu après un oubli (une reconstruction) : ce qui a été oublié ne revient pas
            if name in _CREATES and d.text is not None and d.text.ref:
                # la référence de son texte : l'oubli d'une personne rattachée depuis (un renfort) l'atteint aussi
                sql.execute(f"INSERT OR REPLACE INTO {REFS_TABLE}{sfx}(item, ref) VALUES(?,?)", (e.seq, d.text.ref))
            if name == c.REMEMBERED.name:
                insert({"id": e.seq, "kind": c.SOUVENIR, "text": d.text.text or "", "about": _keys(d.about),
                        "sensitivity": d.sensitivity, "importance": d.importance, "emotion": d.emotion,
                        "born_at": e.at, "touched_at": e.at, "status": "active", "sources": json.dumps(list(d.sources)),
                        "told_by": _keys(d.told_by), "heard_by": _keys(d.heard_by), "secret": int(d.secret),
                        "constraints": json.dumps([rule.model_dump() for rule in d.constraints]),
                        "internal_only": int(d.internal_only)})
            elif name == c.BELIEVED.name:
                insert({"id": e.seq, "kind": c.BELIEF, "text": d.text.text or "", "about": _keys(d.about),
                        "sensitivity": d.sensitivity, "importance": d.importance, "confidence": d.confidence,
                        "origin": d.origin, "source": d.source, "born_at": e.at, "touched_at": e.at,
                        "status": "active", "replaces": d.replaces, "sources": json.dumps(list(d.sources)),
                        "told_by": _keys(d.told_by), "heard_by": _keys(d.heard_by), "secret": int(d.secret),
                        "informants": _keys(informants_of(d.source, d.told_by)),
                        # 1 : ce qu'elle raconte d'elle, qui s'efface ; 2 : ce qui la définit (un goût, un avis), qui tient
                        "about_self": 2 if d.durable else int(d.about_self), "between_us": int(d.between_us),
                        "knowledge_kind": d.knowledge_kind, "holder": d.holder})
                if d.replaces is not None:
                    sql.execute(f"UPDATE {t} SET status='superseded' WHERE id=?", (d.replaces,))
            elif name == c.PROMISE_NOTICED.name:
                insert({"id": e.seq, "kind": c.PROMISE, "text": d.text.text or "", "about": _keys([d.to]),
                        "sensitivity": d.sensitivity, "importance": 0.6, "born_at": e.at, "touched_at": e.at,
                        "status": "pending", "recipient": d.to, "due": d.due, "sources": json.dumps(list(d.sources))})
            elif name == c.EVENT_NOTED.name:
                insert({"id": e.seq, "kind": c.EVENT, "text": d.text.text or "", "about": _keys(d.about),
                        "sensitivity": d.sensitivity, "importance": d.importance, "born_at": e.at, "touched_at": e.at,
                        "status": "active", "due": d.when, "replaces": d.replaces,
                        "sources": json.dumps(list(d.sources)), "told_by": _keys(d.told_by),
                        "heard_by": _keys(d.heard_by), "secret": int(d.secret)})
                if d.replaces is not None:
                    sql.execute(f"UPDATE {t} SET status='superseded' WHERE id=? AND kind=?", (d.replaces, c.EVENT))
            elif name == c.PROMISE_RESOLVED.name:
                sql.execute(f"UPDATE {t} SET status=?, touched_at=? WHERE id=?", (d.status, e.at, d.promise))
            elif name == c.SITUATION_ENDED.name:
                sql.execute(f"UPDATE {t} SET status='ended', touched_at=? WHERE id=?", (e.at, d.event))
            elif name == c.REINFORCED.name:
                self._reinforce(sql, t, about, d, e.at)
            elif name == c.NIGHT_SORTED.name:
                for keep, drop in d.merges:
                    self._merge(sql, t, about, keep, drop, e.at)
            elif name == rt.UTTERANCE.name:
                self._uttered(sql, t, d, e.at)

    @staticmethod
    def _row(sql: Sql, t: str, item: int) -> dict[str, Any] | None:
        got = sql.query(f"SELECT about, told_by, heard_by, informants, sensitivity, secret, importance, sources, text, constraints, internal_only FROM {t} "
                        "WHERE id=?", (item,))
        if not got:
            return None
        return dict(zip(("about", "told_by", "heard_by", "informants", "sensitivity", "secret", "importance", "sources", "text", "constraints", "internal_only"), got[0],
                        strict=True))

    def _reinforce(self, sql: Sql, t: str, about: str, d: Any, at: int) -> None:
        """Ce qui revient dure plus longtemps ; il garde la plus haute
        sensibilité, et les personnes, confidents et témoins s'unissent."""
        row = self._row(sql, t, d.item)
        if row is None:
            return
        sens = max(int(row["sensitivity"]), int(d.sensitivity)) if d.sensitivity is not None else int(row["sensitivity"])
        informants = _loads(row["informants"])
        if d.source or d.told_by:
            informants = [*informants, *informants_of(d.source, d.told_by)]
        sql.execute(
            f"UPDATE {t} SET touched_at=?, importance=MIN(1.0, importance + 0.05), sensitivity=?, about=?, told_by=?, "
            "heard_by=?, secret=?, informants=?, sources=? WHERE id=?",
            # Un ancien renfort peut avoir été fondé sur une simple similarité. En rejouant le journal,
            # il ne doit pas élargir les permissions du texte conservé.
            (at, sens, _keys([*_loads(row["about"]), *d.about]), row["told_by"],
             row["heard_by"], int(bool(row["secret"]) or d.secret), _keys(informants),
             json.dumps(sorted({*map(int, _loads(row["sources"])), *d.sources})),
             d.item))
        _about_rows(sql, about, d.item, d.about)
        if d.corroborated:
            sql.execute(f"UPDATE {t} SET confidence=MIN(0.95, COALESCE(confidence, 0.5) + 0.1) WHERE id=?", (d.item,))
        if d.between_us:
            sql.execute(f"UPDATE {t} SET between_us=1 WHERE id=?", (d.item,))
        if d.replaces is not None and d.replaces != d.item:
            sql.execute(f"UPDATE {t} SET status='superseded' WHERE id=?", (d.replaces,))

    def _merge(self, sql: Sql, t: str, about: str, keep: int, drop: int, at: int) -> None:
        """La nuit, un souvenir se fond dans un autre : le gardé prend le plus
        haut de chaque et l'union des personnes — une confidence fondue dans un
        souvenir anodin reste une confidence."""
        a, b = self._row(sql, t, keep), self._row(sql, t, drop)
        if a is None or b is None or any(a[k] != b[k] for k in ("about", "told_by", "heard_by", "secret", "constraints", "internal_only")):
            return  # même lors du rejeu d'un ancien journal, aucune permission ne s'élargit
        if not same_words(a["text"], b["text"]):
            return  # une négation ou un détail différent ne disparaît pas dans un quasi-doublon
        if a is not None and b is not None:
            sql.execute(
                f"UPDATE {t} SET importance=?, sensitivity=?, about=?, told_by=?, heard_by=?, secret=?, touched_at=? "
                "WHERE id=?",
                (max(float(a["importance"]), float(b["importance"])), max(int(a["sensitivity"]), int(b["sensitivity"])),
                 _keys([*_loads(a["about"]), *_loads(b["about"])]),
                 _keys([*_loads(a["told_by"]), *_loads(b["told_by"])]),
                 _keys([*_loads(a["heard_by"]), *_loads(b["heard_by"])]), int(bool(a["secret"]) or bool(b["secret"])),
                 at, keep))
            _about_rows(sql, about, keep, _loads(b["about"]))
        sql.execute(f"UPDATE {t} SET status='merged' WHERE id=?", (drop,))

    @staticmethod
    def _uttered(sql: Sql, t: str, d: Any, at: int) -> None:
        ids = [int(p.split(":", 1)[1]) for p in d.provenance if p.startswith("memory:") and p[7:].isdigit()]
        if not ids:
            return
        sql.executemany(f"UPDATE {t} SET shown_at=? WHERE id=?", [(at, i) for i in ids])
        said = strip_prosody(d.text.text or "")
        if not said:
            return
        marks = ",".join("?" * len(ids))
        rows = sql.query(f"SELECT id, text FROM {t} WHERE id IN ({marks})", tuple(ids))
        hits = [(at, at, int(i)) for i, text in rows if used(text or "", said)]
        if hits:
            sql.executemany(f"UPDATE {t} SET recalls=recalls+1, recalled_at=?, touched_at=? WHERE id=?", hits)

    def forget(self, sql: Sql, subject: str, sfx: str) -> list[str]:
        t, about = f"{c.ITEMS_TABLE}{sfx}", f"{c.ABOUT_TABLE}{sfx}"
        like = f'%"{subject}"%'
        doomed = [(int(i),) for (i,) in sql.query(
            f"SELECT id FROM {t} WHERE id IN (SELECT item FROM {about} WHERE person=?) OR told_by LIKE ? "
            "OR recipient=? OR holder=?", (subject, like, subject, subject))]
        refs = [str(r) for (i,) in doomed for (r,) in sql.query(f"SELECT ref FROM {REFS_TABLE}{sfx} WHERE item=?", (i,))]
        sql.executemany(f"DELETE FROM {t} WHERE id=?", doomed)
        sql.executemany(f"DELETE FROM {about} WHERE item=?", doomed)
        sql.executemany(f"DELETE FROM {REFS_TABLE}{sfx} WHERE item=?", doomed)
        sql.executemany(f"DELETE FROM {CHANGES_TABLE}{sfx} WHERE item=?", doomed)
        # l'index des vecteurs saura qu'il a quelque chose à oublier (``memory.index``)
        sql.execute(f"UPDATE {c.FORGETS_TABLE}{sfx} SET n=n+1")
        # qui l'a seulement entendu (un salon) ou appris en passant : son nom s'efface des listes
        for column in ("heard_by", "informants"):
            for item, raw in sql.query(f"SELECT id, {column} FROM {t} WHERE {column} LIKE ?", (like,)):
                sql.execute(f"UPDATE {t} SET {column}=? WHERE id=?",
                            (_keys(k for k in _loads(raw) if k != subject), item))
        sql.execute(f"UPDATE {t} SET source=NULL WHERE source=?", (subject,))
        # un élément qu'on lui a rattaché par un renfort ne nomme pas toujours ce sujet dans son texte : le magasin
        # efface ces textes-là aussi (sinon une reconstruction le ferait revenir — audit du lot L2 du 2026-10-03)
        return refs


def _joined(texts: Iterable[str | None]) -> str:
    """Les messages d'un tour, à la suite (« salut / t'as vu le match ? / allo ? »), bornés à
    ``CHUNK_TEXT_MAX`` : au-delà, chacun garde sa part plutôt que le premier mange tout."""
    parts = [" ".join(t.split()) for t in texts if t and t.strip()]
    if not parts:
        return ""
    joined = " / ".join(parts)
    if len(joined) <= CHUNK_TEXT_MAX:
        return joined
    share = max(40, CHUNK_TEXT_MAX // len(parts) - 3)
    return " / ".join(p if len(p) <= share else p[: share - 1] + "…" for p in parts)[:CHUNK_TEXT_MAX]


class Chunks:
    """T0 : un échange par réponse visible — ce qu'on lui a dit (tout le tour) et ce qu'elle a répondu."""

    def create(self, sql: Sql, sfx: str) -> None:
        t = f"{c.CHUNKS_TABLE}{sfx}"
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {t}(id INTEGER PRIMARY KEY, person TEXT NOT NULL, "
            "question INTEGER, user_text TEXT NOT NULL, reply_text TEXT NOT NULL, at INTEGER NOT NULL, room TEXT)"
        )
        # ses échanges dans le temps (« ce que je t'ai dit lundi »), et ceux d'un salon
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_person_at ON {t}(person, at)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_room_at ON {t}(room, at)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.CHUNKS_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        for e in events:
            d = e.data
            if not d.visible or not d.target or d.reply_to is None or forgotten(d.text):
                continue
            # une réponse règle tout le tour (``answers`` : « salut », « t'as vu le match ? », « allo ? ») ; la
            # question n'est souvent pas le dernier message — l'échange les garde tous, dans l'ordre (un journal
            # d'avant le tour : ``reply_to`` seul)
            asked = tuple(sorted({*d.answers, d.reply_to}))
            marks = ",".join("?" * len(asked))
            rows = sql.query(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id IN ({marks}) ORDER BY id", asked)
            user_text = _joined(t for (t,) in rows)
            reply = strip_prosody(d.text.text or "")[:CHUNK_TEXT_MAX]
            sql.execute(f"INSERT OR REPLACE INTO {c.CHUNKS_TABLE}{sfx}(id, person, question, user_text, reply_text, at, "
                        "room) VALUES(?,?,?,?,?,?,?)", (e.seq, d.target, asked[0], user_text, reply, e.at, d.room))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.CHUNKS_TABLE}{sfx} WHERE person=?", (subject,))


class Told:
    """À qui elle a répété quoi : ce que montrait le prompt d'un énoncé adressé
    à quelqu'un (sa provenance). Ce qu'elle a raconté à Bob, Bob le sait — et,
    dans le doute, ce qu'on lui a montré pour parler à Bob compte comme dit."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"CREATE TABLE IF NOT EXISTS {c.TOLD_TABLE}{sfx}(item INTEGER NOT NULL, handle TEXT NOT NULL, "
                    "at INTEGER NOT NULL, PRIMARY KEY(item, handle))")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.TOLD_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        rows = []
        for e in events:
            d = e.data
            if not d.visible or not d.target:
                continue
            rows += [(int(p.split(":", 1)[1]), d.target, e.at) for p in d.provenance
                     if p.startswith("memory:") and p[7:].isdigit()]
        if rows:
            sql.executemany(f"INSERT OR REPLACE INTO {c.TOLD_TABLE}{sfx}(item, handle, at) VALUES(?,?,?)", rows)

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.TOLD_TABLE}{sfx} WHERE handle=?", (subject,))


# v3 : ce qui n'appartient qu'à elle et à la personne (``between_us`` : un surnom, une blague à elles, ADR 0055)
# v4 : index (sorte, statut, naissance), ``memory_about``, ``memory_forgets`` ; l'oublié ne revient pas (ADR 0059)
# v5 : ``memory_refs`` (élément → référence de son texte) : l'oubli d'une personne rattachée par un renfort l'efface
MEMORY.projector(c.ITEMS_TABLE, version=8, tier=Tier.T0,
                 types=[*c.ALL, rt.UTTERANCE])(Items)
# v3 : l'échange garde tout le tour (``Utterance.answers``), pas seulement le dernier message d'une rafale
# v4 : index (personne, instant) et (salon, instant) ; l'oublié ne revient pas (ADR 0059)
MEMORY.projector(c.CHUNKS_TABLE, version=4, tier=Tier.T0, types=[rt.UTTERANCE])(Chunks)
MEMORY.projector(c.TOLD_TABLE, version=1, tier=Tier.T0, types=[rt.UTTERANCE])(Told)


DEFERRED_TABLE = "memory_extraction_queue"


class ExtractionQueue:
    def create(self, sql: Sql, sfx: str) -> None:
        t = DEFERRED_TABLE + sfx
        sql.execute(f"CREATE TABLE IF NOT EXISTS {t}(key INTEGER PRIMARY KEY, messages TEXT NOT NULL, "
                    "about TEXT NOT NULL, attempts INTEGER NOT NULL, retry_at INTEGER NOT NULL, "
                    "status TEXT NOT NULL, reason TEXT NOT NULL, detail_ref TEXT NOT NULL, since INTEGER NOT NULL, "
                    "aside TEXT NOT NULL DEFAULT '[]')")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_due ON {t}(status,retry_at,key)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {DEFERRED_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = DEFERRED_TABLE + sfx
        for e in events:
            d = e.data
            if d.status == "resolved" or forgotten(d.detail):
                sql.execute(f"DELETE FROM {t} WHERE key=?", (d.key,))
                continue
            sql.execute(f"INSERT INTO {t}(key,messages,about,attempts,retry_at,status,reason,detail_ref,since,aside) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                        "messages=excluded.messages,about=excluded.about,attempts=excluded.attempts,"
                        "retry_at=excluded.retry_at,status=excluded.status,reason=excluded.reason,"
                        "detail_ref=excluded.detail_ref,aside=excluded.aside",
                        (d.key, json.dumps(d.messages), _keys(d.about), d.attempts, d.retry_at, d.status,
                         d.failure_code, d.detail.ref or "", e.at, json.dumps(sorted(d.aside))))

    def forget(self, sql: Sql, subject: str, sfx: str) -> list[str]:
        t = DEFERRED_TABLE + sfx
        rows = sql.query(f"SELECT key,detail_ref FROM {t} WHERE EXISTS "
                         "(SELECT 1 FROM json_each(about) WHERE value=?)", (subject,))
        sql.executemany(f"DELETE FROM {t} WHERE key=?", [(key,) for key, _ in rows])
        return [ref for _, ref in rows]


# v2 : ``aside`` (ce qui, dans un salon, ne lui était pas adressé), relu tel quel à la reprise
MEMORY.projector(DEFERRED_TABLE, version=2, tier=Tier.T0, types=[c.EXTRACTION_DEFERRED])(ExtractionQueue)
