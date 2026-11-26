"""Le cache des avis (ADR 0250, 0256) : ``cartes/avis.db``, un fichier SQLite à lui — jamais sauvegardé, il se relit —,
ce que ce serveur a lu de Google Places (l'API officielle, ``google_places``) : les lieux, leur fiche avec leurs avis,
leurs photos, et à quel lieu de l'index chacun répond.

**Ce qu'il garde** : une ligne par lieu de Google (``spot`` : son nom, sa sorte, sa position, son type premier, sa note
et le nombre de ses avis, son prix et sa fourchette, sa page chez Google, sa première photo, le reste de ce qu'une
liste en dit en JSON — son état, son adresse, ses horaires —, quand on l'a lu, ``fetched`` ; et ce que sa fiche seule
dit — son résumé, ce qu'il sert, ses avis —, quand on l'a lue, ``detailed`` ; son pendant dans l'index, ``twin`` ;
combien de fois on a ouvert sa fiche, et quand, ``looks``, ``looked``) ; les cases de la grille par sorte (``cell`` :
ses bords, quand elle a été lue jusqu'au bout, les cercles qui restent à lire d'une lecture commencée) ; les photos
qu'on relaie (``photo`` : leur référence ``p:<hash>``, stable d'une lecture à l'autre, et le dernier nom que Google
leur a donné — il expire —, leur auteur) ; ce qu'a trouvé la recherche à très petit rayon d'un lieu de l'index pas
encore rapproché (``probe`` : un lieu de Google, ou rien) ; ce qu'il dit de lui (``meta``).

**Les conditions de Google**, écrites telles quelles (ADR 0256) : elles ne permettent de garder que l'identifiant d'un
lieu (``place_id``), et ses coordonnées trente jours ; l'opérateur a choisi de garder ce cache et de le faire lire par
Mika, sous sa responsabilité.

**Vieux et effacé** : ce qui a plus de ``ReviewsConfig.cache_days`` jours (sept par défaut) est vieux — on le montre
avec sa date et on le relit dès qu'on peut ; ce qui n'a pas été relu depuis ``PURGE_TIMES`` fois cette durée s'efface.

**Le rapprochement** (``match``) : un lieu de Google est le lieu de l'index (OpenStreetMap) à moins de ``TWIN_M`` mètres
qui est lui — son nom et sa sorte (la même règle que les données touristiques, ``tourism.same_place`` : jamais une
banque, une gare, un parking ; sous un nom seulement ressemblant, une sorte voisine) —, sinon le lieu DATAtourisme
sans pendant (``t:<uuid>``) qui y répond ; sans pendant, il ne se montre nulle part (jamais un lieu de plus, jamais un
double). Ce qui est neuf se rapproche après chaque lecture, et tout quand l'index a été reconstruit.

Le SQL reste portable (pas de ``PRAGMA``, d'``INSERT OR``…) : ``tests/architecture/test_sql_portable.py``."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mika.adapters.maps.config import REVIEWS_FILE
from mika.adapters.maps.google_places import (
    CLOSED_PERMANENTLY,
    CLOSED_TEMPORARILY,
    Spot,
    SpotPhoto,
    attribute_facts,
)
from mika.adapters.maps.photos import photo_ref
from mika.adapters.maps.tourism import busy, index_twin, lone_places, lone_twin, open_places
from mika.ports.maps import Photo, Review, ReviewFacts

#: le schéma 2 : Google (le 1 était celui de la source d'avant : un fichier d'une autre version s'efface, il se relit)
SCHEMA_VERSION = "2"
SOURCE = "google"
#: un lieu de Google et un lieu de l'index à moins de tant de mètres, aux noms qui se ressemblent : le même
TWIN_M = 100
#: ce qui n'a pas été relu depuis tant de fois la durée du cache s'efface
PURGE_TIMES = 4
CHUNK = 500
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE spot (
    id TEXT PRIMARY KEY, category TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, lat REAL NOT NULL,
    lon REAL NOT NULL, kind TEXT NOT NULL DEFAULT '', rating REAL, count INTEGER, price TEXT NOT NULL DEFAULT '',
    price_range TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', photo TEXT NOT NULL DEFAULT '',
    more TEXT NOT NULL DEFAULT '{}', fetched TEXT NOT NULL, detailed TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}', reviews INTEGER NOT NULL DEFAULT 0, twin TEXT, twin_m INTEGER,
    looks INTEGER NOT NULL DEFAULT 0, looked TEXT NOT NULL DEFAULT ''
);
CREATE INDEX spot_lat ON spot(lat, lon);
CREATE INDEX spot_twin ON spot(twin);
CREATE INDEX spot_fetched ON spot(fetched);
CREATE TABLE cell (key TEXT NOT NULL, category TEXT NOT NULL, south REAL NOT NULL, west REAL NOT NULL,
                   north REAL NOT NULL, east REAL NOT NULL, fetched TEXT NOT NULL DEFAULT '',
                   started TEXT NOT NULL DEFAULT '', queue TEXT NOT NULL DEFAULT '[]',
                   circles INTEGER NOT NULL DEFAULT 0, full INTEGER NOT NULL DEFAULT 0,
                   count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (key, category));
CREATE TABLE photo (ref TEXT PRIMARY KEY, spot TEXT NOT NULL, name TEXT NOT NULL, rank INTEGER NOT NULL,
                    author TEXT NOT NULL DEFAULT '', author_url TEXT NOT NULL DEFAULT '', width INTEGER,
                    height INTEGER);
CREATE INDEX photo_spot ON photo(spot);
CREATE TABLE probe (place TEXT PRIMARY KEY, fetched TEXT NOT NULL, spot TEXT);
"""


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _marks(items: Sequence[Any]) -> str:
    return ", ".join("?" * len(items))


def _chunks(items: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for k in range(0, len(items), CHUNK):
        yield items[k:k + CHUNK]


def _connect(path: Path, *, write: bool = False) -> sqlite3.Connection:
    if write:
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    else:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _json(text: str, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def photo_refs(place: str, photos: Sequence[SpotPhoto]) -> list[str]:
    """La référence de chaque photo d'un lieu : son empreinte d'après le lieu, son auteur et ses dimensions (et son rang
    parmi celles qui ont les mêmes) — jamais d'après son nom, que Google change : une photo garde sa référence, et le
    fichier qu'on en garde, d'une lecture à l'autre."""
    seen: dict[tuple[str, int | None, int | None], int] = {}
    out = []
    for p in photos:
        same = (p.author_url or p.author, p.width, p.height)
        seen[same] = seen.get(same, -1) + 1
        out.append(photo_ref(f"google:{place}:{same[0]}:{p.width}x{p.height}:{seen[same]}"))
    return out


@dataclass(frozen=True, slots=True)
class CellState:
    """Une case et une sorte dans le cache : ``fetched``, quand elle a été lue jusqu'au bout (ISO 8601 ; vide :
    jamais) ; ``reading`` : une lecture commencée, pas finie ; ``count`` : combien de lieux elle a rendus ;
    ``circles`` : combien de recherches elle a demandées (une case dense en demande plus)."""

    fetched: str = ""
    reading: bool = False
    count: int = 0
    circles: int = 0


class ReviewsBase:
    """Le fichier, pour qui l'écrit : ses méthodes prennent une connexion ouverte en écriture (``open``) et ne
    s'appellent qu'hors de la boucle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        #: deux fils qui ouvrent un fichier neuf en même temps (le préchargement, une fiche) ne le créent qu'une fois
        self._opening = threading.Lock()

    def open(self) -> sqlite3.Connection:
        """Une connexion en écriture, le fichier créé s'il manque — ou refait s'il est d'une autre version ou
        illisible : il se relit, on ne le convertit pas. Tenu par une autre écriture (``busy``) : l'erreur remonte,
        il reste."""
        with self._opening:
            return self._open()

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                conn = _connect(self.path, write=True)
                row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
                if row is not None and row[0] == SCHEMA_VERSION:
                    return conn
                conn.close()
            except sqlite3.DatabaseError as exc:
                if busy(exc):
                    raise
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(str(self.path) + suffix).unlink(missing_ok=True)
        conn = _connect(self.path, write=True)
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO meta(key, value) VALUES ('version', ?)", (SCHEMA_VERSION,))
        conn.commit()
        return conn

    @staticmethod
    def meta(conn: sqlite3.Connection) -> dict[str, str]:
        return {k: v for k, v in conn.execute("SELECT key, value FROM meta").fetchall()}

    @staticmethod
    def set_meta(conn: sqlite3.Connection, values: dict[str, str]) -> None:
        for key, value in values.items():
            conn.execute("DELETE FROM meta WHERE key = ?", (key,))
            conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    # ── les lieux ──
    @staticmethod
    def write_spots(conn: sqlite3.Connection, spots: Iterable[Spot], fetched: str, *, commit: bool = True) -> int:
        """Des lieux lus, ajoutés ou remplacés (leur sorte gardée si la réponse ne la dit pas ; ce que dit leur fiche
        gardé si c'est une liste qui les rend) ; leurs photos, sous leurs références, avec le nom neuf que Google leur
        donne ; un lieu qui a bougé, ou qu'on n'avait rapproché de rien, se rapprochera de nouveau. Rend combien."""
        count = 0
        for spot in spots:
            row = conn.execute("SELECT category, name, lat, lon, twin FROM spot WHERE id = ?", (spot.id,)).fetchone()
            refs = photo_refs(spot.id, spot.photos)
            more = json.dumps({"status": spot.status, "address": spot.address, "hours": list(spot.hours)},
                              ensure_ascii=False)
            values = (spot.name, spot.lat, spot.lon, spot.kind, spot.rating, spot.count, spot.price,
                      spot.price_range, spot.url, refs[0] if refs else "", more, fetched)
            if row is None:
                conn.execute("INSERT INTO spot(category, name, lat, lon, kind, rating, count, price, price_range, url, "
                             "photo, more, fetched, id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (spot.sort, *values, spot.id))
            else:
                again = (row["name"], row["lat"], row["lon"]) != (spot.name, spot.lat, spot.lon) or row["twin"] == ""
                conn.execute("UPDATE spot SET category = ?, name = ?, lat = ?, lon = ?, kind = ?, rating = ?, "
                             "count = ?, price = ?, price_range = ?, url = ?, photo = ?, more = ?, fetched = ?"
                             + (", twin = NULL, twin_m = NULL" if again else "") + " WHERE id = ?",
                             (spot.sort or row["category"], *values, spot.id))
            if spot.detailed:
                detail = json.dumps({"summary": spot.summary, "attributes": [list(a) for a in spot.attributes],
                                     "reviews": [asdict(r) for r in spot.reviews]}, ensure_ascii=False)
                conn.execute("UPDATE spot SET detailed = ?, detail = ?, reviews = ? WHERE id = ?",
                             (fetched, detail, len(spot.reviews), spot.id))
            conn.execute("DELETE FROM photo WHERE spot = ?", (spot.id,))
            for rank, (ref, photo) in enumerate(zip(refs, spot.photos, strict=True)):
                conn.execute("DELETE FROM photo WHERE ref = ?", (ref,))
                conn.execute("INSERT INTO photo(ref, spot, name, rank, author, author_url, width, height) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (ref, spot.id, photo.name, rank, photo.author,
                                                                photo.author_url, photo.width, photo.height))
            count += 1
        if commit:
            conn.commit()
        return count

    @staticmethod
    def look(conn: sqlite3.Connection, spot: str, at: str) -> None:
        """Sa fiche ouverte : une fois de plus, et quand (le réchauffage relit d'abord la fiche des lieux ouverts depuis
        peu, les plus regardés d'abord)."""
        conn.execute("UPDATE spot SET looks = looks + 1, looked = ? WHERE id = ?", (at, spot))
        conn.commit()

    # ── une case ──
    @staticmethod
    def cell_row(conn: sqlite3.Connection, key: str, category: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM cell WHERE key = ? AND category = ?", (key, category)).fetchone()

    @staticmethod
    def cell_begin(conn: sqlite3.Connection, key: str, category: str, box: tuple[float, float, float, float],
                   started: str, queue: Sequence[str]) -> None:
        """Une lecture de la case commence (ou recommence au début) : sa marque, ``started``, et ses cercles à lire."""
        w, s, e, n = box
        todo = json.dumps(list(queue))
        if ReviewsBase.cell_row(conn, key, category) is None:
            conn.execute("INSERT INTO cell(key, category, south, west, north, east, started, queue) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (key, category, s, w, n, e, started, todo))
        else:
            conn.execute("UPDATE cell SET started = ?, queue = ?, circles = 0, full = 0, count = 0 "
                         "WHERE key = ? AND category = ?", (started, todo, key, category))
        conn.commit()

    @staticmethod
    def cell_step(conn: sqlite3.Connection, key: str, category: str, spots: Sequence[Spot], queue: Sequence[str],
                  full: bool, fetched: str) -> None:
        """Un cercle de la case lu : ses lieux, et les cercles qui restent (ses quarts en plus, s'il était plein),
        dans la même transaction."""
        ReviewsBase.write_spots(conn, spots, fetched, commit=False)
        conn.execute("UPDATE cell SET queue = ?, circles = circles + 1, full = full + ?, count = count + ? "
                     "WHERE key = ? AND category = ?", (json.dumps(list(queue)), int(full), len(spots), key, category))
        conn.commit()

    @staticmethod
    def cell_finish(conn: sqlite3.Connection, key: str, category: str, fetched: str) -> None:
        conn.execute("UPDATE cell SET fetched = ?, started = '', queue = '[]' WHERE key = ? AND category = ?",
                     (fetched, key, category))
        conn.commit()

    @staticmethod
    def write_probe(conn: sqlite3.Connection, place: str, spot: str | None, fetched: str) -> None:
        """Ce qu'a trouvé la recherche à très petit rayon de ce lieu de l'index : un lieu de Google, ou rien."""
        conn.execute("DELETE FROM probe WHERE place = ?", (place,))
        conn.execute("INSERT INTO probe(place, fetched, spot) VALUES (?, ?, ?)", (place, fetched, spot))
        conn.commit()

    # ── ce qui est trop vieux ──
    @staticmethod
    def purge(conn: sqlite3.Connection, before: str) -> int:
        """Ce qui n'a pas été relu depuis ``before`` s'efface : les lieux (leurs photos), les cases, les recherches
        d'un lieu. Rend combien de lieux."""
        gone = [r[0] for r in conn.execute("SELECT id FROM spot WHERE fetched < ?", (before,))]
        for part in _chunks(gone):
            marks = _marks(part)
            for table, column in (("photo", "spot"), ("probe", "spot"), ("spot", "id")):
                conn.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", list(part))
        conn.execute("DELETE FROM probe WHERE fetched < ?", (before,))
        conn.execute("DELETE FROM cell WHERE fetched < ? AND started < ?", (before, before))
        conn.commit()
        return len(gone)

    # ── le rapprochement avec l'index des lieux ──
    @staticmethod
    def match(conn: sqlite3.Connection, index: Path | None, built: str, tourism: Path | None) -> int:
        """Chaque lieu pas encore jugé à son pendant : le lieu de l'index à moins de ``TWIN_M`` mètres au nom qui se
        ressemble, sinon le lieu DATAtourisme sans pendant qui y répond, sinon aucun (``''``). Un index reconstruit
        depuis le dernier passage (``built``) : tout se rejuge. Rend combien ont trouvé leur pendant."""
        if ReviewsBase.meta(conn).get("matched_with", "") != built:
            conn.execute("UPDATE spot SET twin = NULL, twin_m = NULL")
            ReviewsBase.set_meta(conn, {"matched_with": built})
        rows = conn.execute("SELECT id, name, lat, lon, category FROM spot WHERE twin IS NULL").fetchall()
        if not rows:
            return 0
        lieux = open_places(index)
        lone = lone_places(tourism) if tourism is not None else None
        found = 0
        try:
            for sid, name, lat, lon, sort in rows:
                twin = index_twin(lieux, name, lat, lon, TWIN_M, sort=sort) if lieux is not None else None
                if twin is None and lone is not None:
                    twin = lone_twin(lone, name, lat, lon, TWIN_M, sort=sort)
                conn.execute("UPDATE spot SET twin = ?, twin_m = ? WHERE id = ?",
                             (twin[0] if twin else "", twin[1] if twin else None, sid))
                found += twin is not None
        finally:
            if lieux is not None:
                lieux[0].close()
            if lone is not None:
                lone.close()
        conn.commit()
        return found


@dataclass(frozen=True, slots=True)
class ReviewsInfo:
    """Ce que le cache dit de lui, pour la console."""

    ready: bool
    spots: int = 0
    twins: int = 0
    detailed: int = 0
    reviews: int = 0
    photos: int = 0
    cells: int = 0
    oldest_cell: str = ""
    size: int = 0


@dataclass(frozen=True, slots=True)
class Noted:
    """Ce qu'une liste montre d'un lieu rapproché : sa note, le nombre de ses avis, son prix, sa première photo
    (``p:<hash>``) et son auteur, avec son lien (``credit``, ``credit_url`` : Google les demande avec la photo)."""

    rating: float | None
    count: int | None
    price: str
    photo: str
    credit: str = ""
    credit_url: str = ""


def _reviews_of(items: object) -> tuple[Review, ...]:
    out = []
    for item in items if isinstance(items, list) else ():
        if isinstance(item, dict):
            try:
                out.append(Review(**{k: item[k] for k in Review.__dataclass_fields__ if k in item}))
            except TypeError:
                continue
    return tuple(out)


class Reviews:
    """Le cache tel qu'on le lit (``data``/``cartes/avis.db``) : une connexion par lecture, hors de la boucle."""

    def __init__(self, data: Path) -> None:
        self.data = data
        self.base = ReviewsBase(data / REVIEWS_FILE)
        self._info: tuple[tuple[int, int], ReviewsInfo] | None = None

    @property
    def path(self) -> Path:
        return self.base.path

    def _read(self, fn: Callable[[sqlite3.Connection], Any], default: Any) -> Any:
        """Une lecture, hors de la boucle ; un fichier absent, d'une autre version ou illisible : ``default``."""
        if not self.path.exists():
            return default
        try:
            conn = _connect(self.path)
            try:
                if (conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone() or (None,))[0] \
                        != SCHEMA_VERSION:
                    return default
                return fn(conn)
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return default

    async def read(self, fn: Callable[[sqlite3.Connection], Any], default: Any) -> Any:
        return await asyncio.to_thread(self._read, fn, default)

    def info(self) -> ReviewsInfo:
        """Ce que le cache dit de lui (relu quand le fichier change)."""
        try:
            st = self.path.stat()
        except OSError:
            return ReviewsInfo(False)
        key = (st.st_mtime_ns, st.st_size)
        if self._info is not None and self._info[0] == key:
            return self._info[1]

        def read(conn: sqlite3.Connection) -> ReviewsInfo:
            spots, twins, detailed, reviews = conn.execute(
                "SELECT COUNT(*), COUNT(CASE WHEN twin != '' THEN 1 END), COUNT(CASE WHEN detailed != '' THEN 1 END), "
                "SUM(reviews) FROM spot").fetchone()
            cells, oldest = conn.execute("SELECT COUNT(*), MIN(fetched) FROM cell WHERE fetched != ''").fetchone()
            photos = conn.execute("SELECT COUNT(*) FROM photo").fetchone()[0]
            return ReviewsInfo(True, spots=spots, twins=twins, detailed=detailed, reviews=reviews or 0, photos=photos,
                               cells=cells or 0, oldest_cell=oldest or "", size=key[1])

        got = self._read(read, ReviewsInfo(False))
        self._info = (key, got)
        return got

    # ── ce que montre une liste ──
    async def noted(self, keys: Sequence[str]) -> dict[str, Noted]:
        """Les lieux rapprochés de ces lieux de l'index (leur objet d'OpenStreetMap, leur ligne, ``t:<uuid>``) : ce
        qu'une liste en montre, par pendant ; le plus proche quand deux répondent au même."""
        wanted = [k for k in dict.fromkeys(keys) if k]
        if not wanted:
            return {}

        def read(conn: sqlite3.Connection) -> dict[str, Noted]:
            out: dict[str, tuple[int, Noted]] = {}
            for part in _chunks(wanted):
                for row in conn.execute(f"SELECT s.twin, s.twin_m, s.rating, s.count, s.price, s.photo, p.author, "
                                        f"p.author_url FROM spot s LEFT JOIN photo p ON p.ref = s.photo "
                                        f"WHERE s.twin IN ({_marks(part)})", list(part)):
                    near = row["twin_m"] if row["twin_m"] is not None else TWIN_M
                    if row["twin"] not in out or near < out[row["twin"]][0]:
                        out[row["twin"]] = (near, Noted(row["rating"], row["count"], row["price"], row["photo"],
                                                        row["author"] or "", row["author_url"] or ""))
            return {k: v for k, (_d, v) in out.items()}

        return await self.read(read, {})

    async def rated_near(self, box: tuple[float, float, float, float], *, min_rating: float | None,
                         categories: Sequence[str], limit: int) -> list[str]:
        """Les pendants des lieux rapprochés les mieux notés de cette zone (ouest, sud, est, nord), de ces sortes
        (vide : toutes), d'une note d'au moins ``min_rating`` : pour qu'un tri par note trouve aussi ceux qui ne sont
        pas parmi les plus proches."""
        w, s, e, n = box

        def read(conn: sqlite3.Connection) -> list[str]:
            sql = ("SELECT twin FROM spot WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND twin != '' AND "
                   "rating IS NOT NULL")
            args: list[Any] = [s, n, w, e]
            if min_rating is not None:
                sql += " AND rating >= ?"
                args.append(min_rating)
            if categories:
                sql += f" AND category IN ({_marks(categories)})"
                args += list(categories)
            sql += " ORDER BY rating DESC, count DESC LIMIT ?"
            return list(dict.fromkeys(r[0] for r in conn.execute(sql, [*args, limit])))

        return await self.read(read, [])

    # ── la fiche d'un lieu ──
    async def spot_for(self, keys: Sequence[str]) -> sqlite3.Row | None:
        """Le lieu de Google rapproché de ce lieu de l'index (le plus proche s'ils sont deux)."""
        wanted = [k for k in dict.fromkeys(keys) if k]
        if not wanted:
            return None
        return await self.read(lambda conn: conn.execute(
            f"SELECT * FROM spot WHERE twin IN ({_marks(wanted)}) ORDER BY twin_m, count DESC LIMIT 1",
            wanted).fetchone(), None)

    async def spot(self, spot: str) -> sqlite3.Row | None:
        return await self.read(lambda conn: conn.execute("SELECT * FROM spot WHERE id = ?", (spot,)).fetchone(), None)

    async def probe_of(self, place: str) -> sqlite3.Row | None:
        return await self.read(lambda conn: conn.execute("SELECT * FROM probe WHERE place = ?", (place,)).fetchone(),
                               None)

    async def facts(self, spot: str, *, note: str = "") -> ReviewFacts | None:
        """Sa partie « avis » de la fiche, telle que le cache la tient : sa note, son prix et sa fourchette, son résumé,
        ses avis, ses photos (chacune avec son auteur), ce que Google dit de lui (``ReviewFacts.facts`` : ce qu'il sert,
        ses horaires), sa page, la date de ce qu'on montre (la plus ancienne de la liste et de la fiche) ; ``note`` : ce
        qu'il faut en dire."""
        def read(conn: sqlite3.Connection) -> ReviewFacts | None:
            row = conn.execute("SELECT * FROM spot WHERE id = ?", (spot,)).fetchone()
            if row is None:
                return None
            more = _json(row["more"], {})
            detail = _json(row["detail"], {})
            photos = tuple(Photo(ref=p["ref"], source=SOURCE, credit=p["author"], credit_url=p["author_url"],
                                 width=p["width"], height=p["height"])
                           for p in conn.execute("SELECT * FROM photo WHERE spot = ? ORDER BY rank", (spot,)))
            said = [note] if note else []
            if more.get("status") == CLOSED_PERMANENTLY:
                said.append("Google le dit fermé définitivement.")
            elif more.get("status") == CLOSED_TEMPORARILY:
                said.append("Google le dit fermé pour un temps.")
            facts = list(attribute_facts([a for a in detail.get("attributes") or () if isinstance(a, list)
                                          and len(a) == 2]))
            hours = [h for h in more.get("hours") or () if isinstance(h, str)]
            if hours:
                facts.insert(0, ("Horaires", " ; ".join(hours) + " (selon Google)"))
            dates = [d for d in (row["fetched"], row["detailed"]) if d]
            return ReviewFacts(
                id=row["id"], rating=row["rating"], count=row["count"], price=row["price"],
                reviews=_reviews_of(detail.get("reviews")), photos=photos, url=row["url"], cached=min(dates),
                note=" ".join(said), source=SOURCE, summary=str(detail.get("summary") or ""),
                price_range=row["price_range"], facts=tuple(facts))

        return await self.read(read, None)

    # ── les cases ──
    def cell_states(self, keys: Sequence[str]) -> dict[tuple[str, str], CellState]:
        """Ce que le cache sait de ces cases, par (case, sorte) ; une case jamais lue n'y est pas."""
        wanted = list(dict.fromkeys(keys))
        if not wanted:
            return {}

        def read(conn: sqlite3.Connection) -> dict[tuple[str, str], CellState]:
            out = {}
            for part in _chunks(wanted):
                for row in conn.execute(f"SELECT key, category, fetched, started, count, circles FROM cell "
                                        f"WHERE key IN ({_marks(part)})", list(part)):
                    out[(row[0], row[1])] = CellState(row[2], bool(row[3]), row[4], row[5])
            return out

        return self._read(read, {})

    def due(self, box: tuple[float, float, float, float], *, looked_since: str, before: str, limit: int) -> list[str]:
        """Les lieux rapprochés de cette zone ouverts depuis ``looked_since`` dont la fiche manque ou date d'avant
        ``before`` : les plus regardés d'abord, puis les mieux notés (le réchauffage, une fois les cases lues)."""
        w, s, e, n = box

        def read(conn: sqlite3.Connection) -> list[str]:
            rows = conn.execute(
                "SELECT id FROM spot WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND twin != '' AND "
                "looked >= ? AND looked != '' AND (detailed = '' OR detailed < ?) "
                "ORDER BY looks DESC, rating DESC, count DESC LIMIT ?",
                (s, n, w, e, looked_since, before, limit)).fetchall()
            return [r[0] for r in rows]

        return self._read(read, [])

    # ── les photos ──
    def photo_row(self, ref: str) -> sqlite3.Row | None:
        """La photo de cette référence : son lieu, son dernier nom chez Google, son auteur ; inconnue : ``None``."""
        return self._read(lambda conn: conn.execute("SELECT * FROM photo WHERE ref = ?", (ref,)).fetchone(), None)


def older_than(now: datetime, days: float) -> str:
    """La date (ISO 8601) d'il y a ``days`` jours : ce qui est d'avant est vieux."""
    return stamp(now - timedelta(days=days))
