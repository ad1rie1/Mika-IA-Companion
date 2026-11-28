"""La base des données touristiques (ADR 0245) : ``cartes/tourisme.db``, un fichier SQLite à elle, un cache de
DATAtourisme par cases (``tourism_cells`` ; en option, des départements entiers : ``tourism_sync``) — jamais
sauvegardée, elle se relit.

**Ce qu'elle garde** : une ligne par fiche (``fiche`` : un lieu ou un événement, ce qu'en dit une fiche, son auteur et
sa mise à jour), cherchée par le texte intégral (``fiche_text`` : le nom, la commune, le résumé) et par l'arbre R
(``fiche_box``) ; les occurrences d'un événement (``occurrence`` : des jours, ou des périodes et leurs jours de la
semaine, à venir seulement) ; ses photos (``photo`` : l'adresse d'origine, le crédit, la licence, la fin des droits,
la référence ``p:<hash>``) ; les cases du cache (``cell`` : une case de la grille et une liste — ses événements ou ses
lieux —, quand elle a été lue, où en est sa lecture) ; où en est la synchronisation des départements (``progress``) ;
ce qu'elle dit d'elle (``meta``). Elle s'écrit page par page, en flux (jamais toute la France en
mémoire), en journal de retour arrière : un lecteur lit pendant qu'elle s'écrit, et le fichier seul suffit à la copier.

**Le rapprochement** avec l'index des lieux (``lieux.db``, OpenStreetMap), refait après chaque lecture pour ce qui a
changé, et pour tout quand l'index a été reconstruit ou que sa règle a changé (``match_stamp``) : un lieu DATAtourisme
est un lieu d'OpenStreetMap à moins de ``TWIN_M`` mètres qui est lui — son nom, et sa sorte quand les noms ne sont pas
les mêmes ; jamais une gare, un parking, une banque (``same_place``, ADR 0269) — (``twin`` : son objet, ``n123``) ;
sinon il reste trouvable comme
``t:<uuid>`` — seulement s'il est sûr qu'aucun lieu d'OpenStreetMap n'est le sien, jamais en double. Le lieu d'un
événement (``venue``, ADR 0259) est le plus proche à moins de ``VENUE_M`` mètres qui accueille du public (une salle,
un théâtre, un musée, une bibliothèque, un stade… ; une église, pour un concert ou une visite) — jamais pour un
marché ni pour une fête qui n'est que cela, qui se tiennent dehors ; une adresse sans numéro qui nomme une place ou
une rue (« Place du Concert ») dit où il est, et un lieu n'y est retenu que si l'événement ou l'adresse le nomme ; un
peu plus loin (``VENUE_FAR_M``), un lieu que l'événement nomme en entier ou qui est à la même adresse (ADR 0269).
Sinon, son adresse. **Les doublons** d'un événement (une fiche par date, sous des identifiants différents : même nom, même
endroit) se réunissent à la lecture, toutes leurs dates ensemble, sous l'identifiant le plus petit."""

from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from mika.adapters.maps.config import TOURISM_FILE
from mika.adapters.maps.datatourisme import (
    EVENT,
    GENERIC_WORDS,
    PLACE,
    THEME_BITS,
    UUID,
    Fiche,
    name_key,
    place_sort,
    plain_words,
)
from mika.adapters.maps.geo import box_around, meters_between
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.photos import PhotoOrigin, photo_ref
from mika.adapters.maps.places import match_query
from mika.adapters.maps.tags import read_kept
from mika.adapters.maps.when import Occurrence, dates_fr, session, upcoming, when_text
from mika.ports.maps import (
    DATES_SHOWN,
    THEMES,
    EventDetail,
    EventHit,
    MapsUnavailable,
    Photo,
    PlaceHit,
    TourismFacts,
)

SCHEMA_VERSION = "1"
NOT_SYNCED = "Les données touristiques ne sont pas encore lues ici : elles le seront ce soir."
DAMAGED = "La base des données touristiques est illisible."
#: ce que la base garde comme index de son rapprochement quand elle a été rapprochée sans index des lieux
NO_INDEX = "aucun"
SOURCE = "datatourisme"
#: un lieu DATAtourisme et un lieu d'OpenStreetMap à moins de tant de mètres, aux noms qui se ressemblent : le même
TWIN_M = 150
TWIN_LIKENESS = 0.75
#: la règle du rapprochement : quand elle change, tout se rejuge (``match_stamp``, avec la date de l'index)
MATCH_RULE = "3"
#: les catégories de l'index qui ne sont le pendant de rien : une gare, une station, un parking, une borne, une banque,
#: une location, une pharmacie — même sous le même nom, ce n'est pas le lieu qu'une fiche ou des avis décrivent ;
#: sauf une mairie, qui se visite (``TOWN_HALL``), et, sous son nom même, une fiche de cette catégorie (une location,
#: un office de tourisme : ``same_place``)
NO_TWIN = frozenset({"route", "services", "sante", "villes"})
TOWN_HALL = "townhall"
#: sous des noms qui ne sont pas les mêmes, les sortes qui peuvent être un même lieu (la sorte d'une fiche ou d'un lieu
#: de Google → celle d'un lieu de l'index) : un restaurant et une boulangerie, une pâtisserie, un hôtel-restaurant ; ce
#: qui se visite et un parc, ou une salle de spectacle (``STAGES``)
AKIN = {
    "manger": frozenset({"manger", "courses", "dormir"}),
    "dormir": frozenset({"dormir", "manger"}),
    "courses": frozenset({"courses", "manger"}),
    "voir": frozenset({"voir", "nature", "sortir"}),
    "nature": frozenset({"nature", "voir"}),
    "sortir": frozenset({"sortir", "voir"}),
}
#: ce qui, de « sortir », se visite aussi : une salle de spectacle, un centre d'art (« à voir » chez Google)
STAGES = frozenset({"theatre", "arts_centre", "cinema"})
#: le lieu d'un événement : le plus proche, à moins de tant de mètres, qui accueille du public (ADR 0259) ; plus loin,
#: jusqu'à ``VENUE_FAR_M``, seulement celui que l'événement nomme en entier ou qui est à la même adresse (ADR 0269 : un
#: grand lieu est placé au centre de ses contours, loin de l'entrée que ses événements donnent)
VENUE_M = 60
VENUE_FAR_M = 300
#: les sortes de l'index qui accueillent du public pour un événement : salles, scènes, musées, bibliothèques, stades…
#: (jamais une place, un parc, un monument, une « attraction » : un marché ou une fête de plein air s'y rapprocherait)
VENUE_KINDS = frozenset({
    "theatre", "cinema", "arts_centre", "nightclub", "library", "community_centre", "townhall",
    "museum", "gallery", "castle", "manor", "fort", "zoo", "aquarium", "theme_park",
    "stadium", "sports_centre", "swimming_pool", "golf_course", "horse_riding",
})
#: un lieu de culte, seulement pour ces thèmes (un concert dans une église, une visite d'une chapelle)
WORSHIP = "place_of_worship"
WORSHIP_THEMES = frozenset({"concerts", "visites"})
#: un événement de plein air ne se rapproche d'aucun lieu : un marché, ou une fête qui n'est rien de ce qui se tient
#: dans une salle
OPEN_AIR, INDOOR = frozenset({"marches"}), frozenset({"concerts", "spectacles", "expositions", "conferences", "visites"})
FEAST = "fetes"
#: une adresse sans numéro qui nomme une place ou une rue (« Place du Concert ») : c'est là qu'il a lieu
STREET = re.compile(r"^(?:place|rue|avenue|boulevard|bd|quai|parvis|esplanade|square|cours|cour|allee|chemin|impasse|"
                    r"route|promenade|mail|rond[- ]?point|grand[- ]?place|jardin|parc|port|plage|pont|porte|halle)s?\b")
#: les événements d'un lieu : à moins de tant de mètres, dans les trente jours, au plus tant
NEAR_EVENTS_M = 200
NEAR_EVENTS_DAYS = 30
NEAR_EVENTS_MAX = 6
#: chercher : au plus tant de candidats lus avant de réunir les doublons et de juger des dates
CANDIDATES_MAX = 3_000
MATCH_BATCH = 2_000
DEFAULT_DAYS = 30
#: un IN (…) de SQLite : au plus tant de paramètres à la fois
CHUNK = 500
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE fiche (
    id INTEGER PRIMARY KEY, uuid TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, name TEXT NOT NULL,
    twins TEXT NOT NULL DEFAULT '', types TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
    sort TEXT NOT NULL DEFAULT '', sort_fr TEXT NOT NULL DEFAULT '', themes INTEGER NOT NULL DEFAULT 0,
    lat REAL, lon REAL, street TEXT NOT NULL DEFAULT '', postcode TEXT NOT NULL DEFAULT '',
    town TEXT NOT NULL DEFAULT '', insee TEXT NOT NULL DEFAULT '', department TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', labels TEXT NOT NULL DEFAULT '[]',
    prices TEXT NOT NULL DEFAULT '', free INTEGER, contacts TEXT NOT NULL DEFAULT '[]',
    author TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL DEFAULT '', uri TEXT NOT NULL DEFAULT '',
    last_day TEXT NOT NULL DEFAULT '', seen TEXT NOT NULL DEFAULT '', synced TEXT NOT NULL DEFAULT '',
    twin TEXT, twin_m INTEGER, venue TEXT, venue_place TEXT NOT NULL DEFAULT '',
    cell_seen TEXT NOT NULL DEFAULT ''
);
CREATE INDEX fiche_twin ON fiche(twin);
CREATE INDEX fiche_twins ON fiche(twins);
CREATE INDEX fiche_kind ON fiche(kind, last_day);
CREATE INDEX fiche_seen ON fiche(seen);
CREATE INDEX fiche_venue ON fiche(venue_place);
CREATE VIRTUAL TABLE fiche_text USING fts5(name, town, summary, content='fiche', content_rowid='id',
                                           tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE fiche_box USING rtree(id, lat0, lat1, lon0, lon1);
CREATE TABLE occurrence (fiche INTEGER NOT NULL, day0 TEXT NOT NULL, day1 TEXT NOT NULL,
                         opens TEXT NOT NULL DEFAULT '', closes TEXT NOT NULL DEFAULT '',
                         days INTEGER NOT NULL DEFAULT 0);
CREATE INDEX occurrence_fiche ON occurrence(fiche, day1);
CREATE INDEX occurrence_day1 ON occurrence(day1);
CREATE TABLE photo (fiche INTEGER NOT NULL, rank INTEGER NOT NULL, ref TEXT NOT NULL, url TEXT NOT NULL,
                    credit TEXT NOT NULL DEFAULT '', licence TEXT NOT NULL DEFAULT '',
                    caption TEXT NOT NULL DEFAULT '', rights_end TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (fiche, rank));
CREATE INDEX photo_ref ON photo(ref);
CREATE TABLE progress (run TEXT NOT NULL, endpoint TEXT NOT NULL, part TEXT NOT NULL, rank INTEGER NOT NULL,
                       done INTEGER NOT NULL DEFAULT 0, next TEXT NOT NULL DEFAULT '',
                       count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (run, endpoint, part));
CREATE TABLE cell (key TEXT NOT NULL, part TEXT NOT NULL, south REAL NOT NULL, west REAL NOT NULL,
                   north REAL NOT NULL, east REAL NOT NULL, fetched TEXT NOT NULL DEFAULT '',
                   started TEXT NOT NULL DEFAULT '', next TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 0,
                   PRIMARY KEY (key, part));
CREATE TRIGGER fiche_added AFTER INSERT ON fiche BEGIN
    INSERT INTO fiche_text(rowid, name, town, summary) VALUES (new.id, new.name, new.town, new.summary);
END;
CREATE TRIGGER fiche_removed AFTER DELETE ON fiche BEGIN
    INSERT INTO fiche_text(fiche_text, rowid, name, town, summary)
        VALUES ('delete', old.id, old.name, old.town, old.summary);
    DELETE FROM fiche_box WHERE id = old.id;
    DELETE FROM occurrence WHERE fiche = old.id;
    DELETE FROM photo WHERE fiche = old.id;
END;
CREATE TRIGGER fiche_renamed AFTER UPDATE OF name, town, summary ON fiche BEGIN
    INSERT INTO fiche_text(fiche_text, rowid, name, town, summary)
        VALUES ('delete', old.id, old.name, old.town, old.summary);
    INSERT INTO fiche_text(rowid, name, town, summary) VALUES (new.id, new.name, new.town, new.summary);
END;
"""
_FIELDS = ("uuid", "kind", "name", "twins", "types", "category", "sort", "sort_fr", "themes", "lat", "lon", "street",
           "postcode", "town", "insee", "department", "summary", "description", "labels", "prices", "free",
           "contacts", "author", "updated", "uri", "last_day", "synced")


def utc_now() -> datetime:
    return datetime.now(UTC)


def paris_today(at: datetime) -> date:
    return at.astimezone(PARIS).date()


def _chunks(items: Sequence[Any]) -> Iterator[Sequence[Any]]:
    for k in range(0, len(items), CHUNK):
        yield items[k:k + CHUNK]


def _marks(items: Sequence[Any]) -> str:
    return ", ".join("?" * len(items))


def twins_key(fiche: Fiche) -> str:
    """Ce qui réunit les fiches d'un même événement : son nom comparable, et où (à une centaine de mètres)."""
    where = f"{fiche.lat:.3f}|{fiche.lon:.3f}" if fiche.lat is not None and fiche.lon is not None else \
        name_key(fiche.street + " " + fiche.town)
    return f"{name_key(fiche.name)}|{where}"


def match_stamp(built: str) -> str:
    """Ce que le rapprochement suit (``meta.matched_with``) : quand l'index a été construit, et la règle
    (``MATCH_RULE``) — l'un ou l'autre changé, tout se rejuge."""
    return f"{built} · règle {MATCH_RULE}"


def likeness(a: str, b: str) -> float:
    """Deux noms de lieux se ressemblent-ils (0 à 1) : les mêmes mots, l'un dans l'autre (« Barrière Lille » et
    « Resort Barrière Lille » — pas quand ils n'ont en commun que ce qui dit une rue ou une place : « La Place » n'est
    pas « Friterie Meunier - Grand Place »), ou presque les mêmes lettres — sans accents, casse, articles ni mots de
    sorte. Seul, il ne dit pas que deux lieux sont le même : ``same_place`` y ajoute leur sorte."""
    ka, kb = name_key(a).split(), name_key(b).split()
    if not ka or not kb:
        return 0.0
    sa, sb = set(ka), set(kb)
    if sa == sb:
        return 1.0
    common = sa & sb
    contained = 0.9 if common and common == (sa if len(sa) <= len(sb) else sb) and \
        len("".join(common)) >= 4 and not all(STREET.fullmatch(w) for w in common) else 0.0
    return max(contained, len(common) / len(sa | sb), SequenceMatcher(None, " ".join(ka), " ".join(kb)).ratio())


def akin(sort: str, category: str, kind: str) -> bool:
    """Une fiche ou un lieu de Google de cette sorte (``sort`` : une catégorie de l'écran Carte) peut-il être, sous un
    autre nom, ce lieu de l'index (sa catégorie, sa sorte) : la même sorte, ou une voisine (``AKIN``) ; une sorte
    inconnue, jamais."""
    other = "voir" if kind == TOWN_HALL else category
    if not sort or not other:
        return False
    if sort == "voir" and other == "sortir":
        return kind in STAGES
    return other == sort or other in AKIN.get(sort, ())


def same_name(a: str, b: str, town: str = "") -> bool:
    """Deux noms qui sont les mêmes (sans accents, casse, articles ni mots de sorte), ou qui ne diffèrent que par la
    commune (``town``) que l'un y ajoute — « France Cars Villeneuve d'Ascq » et « France Cars », à Villeneuve-d'Ascq."""
    ka, kb = set(name_key(a).split()), set(name_key(b).split())
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    there = set(name_key(town).split()) if town else set()
    return bool(there) and bool(ka - there) and ka - there == kb - there


def same_place(name: str, sort: str, other: str, category: str, kind: str, *, town: str = "") -> float:
    """Combien un lieu (son nom, sa sorte ; ``town`` : sa commune) est ce lieu de l'index (son nom, sa catégorie, sa
    sorte), de 0 à 1 : jamais ce qui n'est le pendant de rien (``NO_TWIN`` : une banque, une gare, un parking…), sauf
    une fiche de cette catégorie sous son nom même, sa commune mise à part (une location, un office de tourisme :
    « France Cars Villeneuve d'Ascq » est « France Cars » ; « Taxi Lille Europe » n'est pas la gare) ; sous le même
    nom, lui ; sous un nom qui se ressemble seulement (l'un dans l'autre, presque les mêmes lettres), seulement d'une
    sorte voisine (``akin``) — « BAR PARIBAS » n'est pas « BNP Paribas », ni « Le Beffroi », un restaurant, le beffroi
    d'à côté."""
    if category in NO_TWIN and kind != TOWN_HALL:
        return 1.0 if sort == category and same_name(name, other, town) else 0.0
    score = likeness(name, other)
    if score >= 1.0:
        return score
    return score if akin(sort, category, kind) else 0.0


def busy(exc: sqlite3.DatabaseError) -> bool:
    """Une base tenue par une autre écriture (``database is locked``, ``busy``), pas une base abîmée : on ne l'efface
    jamais pour cela (ADR 0269)."""
    said = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and ("locked" in said or "busy" in said)


def _connect(path: Path, *, write: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30 if write else 10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL" if write else "PRAGMA query_only=1")
    return conn


# ── écrire (la synchronisation) ──
@dataclass(frozen=True, slots=True)
class CellStep:
    """Où en est la lecture d'une case, écrit avec sa page : sa marque (``started``), la page suivante."""

    key: str
    part: str
    started: str
    next: str


@dataclass(frozen=True, slots=True)
class Step:
    """Où en est une partie d'une synchronisation complète, écrit avec sa page : la page suivante, finie ou non."""

    run: str
    endpoint: str
    part: str
    next: str
    done: bool


class TourismBase:
    """Le fichier, pour qui l'écrit (la synchronisation) : ses méthodes prennent une connexion ouverte en écriture
    (``open``) et ne s'appellent qu'hors de la boucle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        #: deux lectures en direct qui ouvrent la base en même temps (les cases d'un rayon, ADR 0259) ne la créent
        #: qu'une fois
        self._opening = threading.Lock()

    def open(self) -> sqlite3.Connection:
        """Une connexion en écriture, la base créée si elle manque — ou refaite si elle est d'une autre version ou
        illisible : elle se refait, on ne la convertit pas. Tenue par une autre écriture : l'erreur remonte, elle
        reste."""
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
                if busy(exc):  # tenue par une autre écriture : pas abîmée, jamais effacée pour cela
                    raise
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(str(self.path) + suffix).unlink(missing_ok=True)
        conn = _connect(self.path, write=True)
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                         [("version", SCHEMA_VERSION), ("created", utc_now().isoformat(timespec="seconds"))])
        conn.commit()
        return conn

    # ── ce qu'elle dit d'elle ──
    @staticmethod
    def meta(conn: sqlite3.Connection) -> dict[str, str]:
        return {k: v for k, v in conn.execute("SELECT key, value FROM meta").fetchall()}

    @staticmethod
    def set_meta(conn: sqlite3.Connection, values: dict[str, str | None], *, commit: bool = True) -> None:
        for key, value in values.items():
            conn.execute("DELETE FROM meta WHERE key = ?", (key,))
            if value is not None:
                conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, value))
        if commit:
            conn.commit()

    # ── une page ──
    @staticmethod
    def write_page(conn: sqlite3.Connection, fiches: Iterable[Fiche], *, run: str | None, synced: str,
                   today: date, step: Step | None = None, cell: CellStep | None = None) -> int:
        """Les fiches d'une page, ajoutées ou remplacées (``run`` : la synchronisation complète qui les a vues ;
        ``cell`` : la lecture d'une case qui les a vues) ; et, dans la même transaction, où en est la partie
        (``step``) ou la case (``cell``). Rend combien de fiches."""
        count = 0
        for fiche in fiches:
            _write(conn, fiche, run=run, synced=synced, today=today, cell_seen=cell.started if cell else "")
            count += 1
        if step is not None:
            conn.execute("UPDATE progress SET next = ?, done = ?, count = count + ? WHERE run = ? AND endpoint = ? "
                         "AND part = ?", (step.next, int(step.done), count, step.run, step.endpoint, step.part))
        if cell is not None:
            conn.execute("UPDATE cell SET next = ?, count = count + ? WHERE key = ? AND part = ?",
                         (cell.next, count, cell.key, cell.part))
        conn.commit()
        return count

    # ── une case du cache ──
    @staticmethod
    def cell_row(conn: sqlite3.Connection, key: str, part: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM cell WHERE key = ? AND part = ?", (key, part)).fetchone()

    @staticmethod
    def cell_begin(conn: sqlite3.Connection, key: str, part: str, box: tuple[float, float, float, float],
                   started: str) -> None:
        """Une lecture de la case commence (ou recommence au début) : sa marque, ``started``."""
        w, s, e, n = box
        found = TourismBase.cell_row(conn, key, part)
        if found is None:
            conn.execute("INSERT INTO cell(key, part, south, west, north, east, started) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (key, part, s, w, n, e, started))
        else:
            conn.execute("UPDATE cell SET started = ?, next = '', count = 0 WHERE key = ? AND part = ?",
                         (started, key, part))
        conn.commit()

    @staticmethod
    def cell_finish(conn: sqlite3.Connection, key: str, part: str, kind: str, fetched: str) -> int:
        """La case lue jusqu'au bout : ce qu'elle a rendu porte sa marque ; les fiches de cette sorte qui sont dans la
        case et ne la portent pas n'y sont plus (retirées, finies, hors de l'horizon) et s'effacent. Rend combien."""
        row = TourismBase.cell_row(conn, key, part)
        if row is None or not row["started"]:
            return 0
        gone = [r[0] for r in conn.execute(
            "SELECT f.id FROM fiche_box b JOIN fiche f ON f.id = b.id WHERE b.lat0 <= ? AND b.lat1 >= ? AND "
            "b.lon0 <= ? AND b.lon1 >= ? AND f.kind = ? AND f.cell_seen != ?",
            (row["north"], row["south"], row["east"], row["west"], kind, row["started"]))]
        for part_ids in _chunks(gone):
            conn.execute(f"DELETE FROM fiche WHERE id IN ({_marks(part_ids)})", list(part_ids))
        conn.execute("UPDATE cell SET fetched = ?, started = '', next = '' WHERE key = ? AND part = ?",
                     (fetched, key, part))
        conn.commit()
        return len(gone)

    # ── une synchronisation complète ──
    @staticmethod
    def begin_run(conn: sqlite3.Connection, run: str, zones: str, horizon: int,
                  parts: Sequence[tuple[str, str]]) -> None:
        conn.execute("DELETE FROM progress")
        conn.executemany("INSERT INTO progress(run, endpoint, part, rank) VALUES (?, ?, ?, ?)",
                         [(run, endpoint, part, k) for k, (endpoint, part) in enumerate(parts)])
        TourismBase.set_meta(conn, {"run": run, "run_zones": zones, "run_horizon": str(horizon)}, commit=False)
        conn.commit()

    @staticmethod
    def forget(conn: sqlite3.Connection, uuid: str) -> bool:
        """Une fiche que DATAtourisme n'a plus : effacée (rend si elle y était)."""
        gone = conn.execute("DELETE FROM fiche WHERE uuid = ?", (uuid,)).rowcount
        conn.commit()
        return bool(gone)

    @staticmethod
    def pending(conn: sqlite3.Connection, run: str) -> list[tuple[str, str, str, int]]:
        """Les parties pas finies de cette synchronisation, dans l'ordre : (liste, département, page suivante, fiches
        déjà lues)."""
        return [(r[0], r[1], r[2], r[3]) for r in conn.execute(
            "SELECT endpoint, part, next, count FROM progress WHERE run = ? AND done = 0 ORDER BY rank", (run,))]

    @staticmethod
    def restart_part(conn: sqlite3.Connection, run: str, endpoint: str, part: str) -> None:
        conn.execute("UPDATE progress SET next = '', count = 0 WHERE run = ? AND endpoint = ? AND part = ?",
                     (run, endpoint, part))
        conn.commit()

    @staticmethod
    def finish_run(conn: sqlite3.Connection, run: str, zones: Sequence[str] = ()) -> int:
        """Une synchronisation complète des départements ``zones`` finie (vide : toute la France) : ce qu'elle n'y a
        pas vu a été retiré de DATAtourisme (ou n'est plus à venir) et s'efface — les fiches des autres départements,
        lues par les cases, restent. Rend combien."""
        if zones:
            removed = conn.execute(f"DELETE FROM fiche WHERE seen != ? AND department IN ({_marks(zones)})",
                                   [run, *zones]).rowcount
        else:
            removed = conn.execute("DELETE FROM fiche WHERE seen != ?", (run,)).rowcount
        conn.execute("DELETE FROM progress")
        TourismBase.set_meta(conn, {"run": None, "run_zones": None, "run_horizon": None}, commit=False)
        conn.commit()
        return removed

    @staticmethod
    def purge(conn: sqlite3.Connection, today: date) -> int:
        """Ce qui est passé : les occurrences finies, les événements qui n'en ont plus."""
        day = today.isoformat()
        conn.execute("DELETE FROM occurrence WHERE day1 < ?", (day,))
        gone = conn.execute("DELETE FROM fiche WHERE kind = ? AND last_day < ?", (EVENT, day)).rowcount
        conn.commit()
        return gone

    # ── le rapprochement avec l'index des lieux ──
    @staticmethod
    def match(conn: sqlite3.Connection, index: Path | None, *, everything: bool) -> tuple[int, int]:
        """Chaque lieu à son pendant d'OpenStreetMap, chaque événement à son lieu nommé — ceux pas encore jugés, ou
        tous (``everything`` : l'index a changé). Sans index : aucun pendant (les lieux restent ``t:<uuid>``). Rend
        (lieux rapprochés, événements situés) de ce passage."""
        if everything:
            conn.execute("UPDATE fiche SET twin = NULL, twin_m = NULL, venue = NULL, venue_place = ''")
        conn.execute("UPDATE fiche SET twin = '' WHERE kind = ? AND twin IS NULL AND lat IS NULL", (PLACE,))
        conn.execute("UPDATE fiche SET venue = '' WHERE kind = ? AND venue IS NULL AND lat IS NULL", (EVENT,))
        lieux = open_places(index)
        twins = venues = 0
        last = 0
        try:
            while True:
                rows = conn.execute(
                    "SELECT id, kind, name, lat, lon, street, town, themes, category, types FROM fiche WHERE id > ? "
                    "AND lat IS NOT NULL AND ((kind = ? AND twin IS NULL) OR (kind = ? AND venue IS NULL)) ORDER BY id "
                    "LIMIT ?", (last, PLACE, EVENT, MATCH_BATCH)).fetchall()
                if not rows:
                    break
                for fid, kind, name, lat, lon, street, town, themes, category, types in rows:
                    if kind == PLACE:
                        # une fiche lue avant qu'on connaisse sa classe (``Transport``) : sa sorte d'aujourd'hui
                        sort = category or place_sort((types or "").split(";"))[0]
                        found = index_twin(lieux, name, lat, lon, sort=sort, town=town) if lieux is not None else None
                        conn.execute("UPDATE fiche SET twin = ?, twin_m = ? WHERE id = ?",
                                     (found[0] if found else "", found[1] if found else None, fid))
                        twins += found is not None
                    else:
                        spot = _venue(lieux, lat, lon, name=name, street=street, town=town,
                                      themes=_themes(themes)) if lieux is not None else None
                        conn.execute("UPDATE fiche SET venue = ?, venue_place = ? WHERE id = ?",
                                     (spot[0] if spot else "", spot[1] if spot else "", fid))
                        venues += spot is not None
                conn.commit()
                last = rows[-1][0]
        finally:
            if lieux is not None:
                lieux[0].close()
        conn.commit()
        return twins, venues


def _write(conn: sqlite3.Connection, fiche: Fiche, *, run: str | None, synced: str, today: date,
           cell_seen: str = "") -> None:
    occurrences = [o for o in fiche.occurrences if o.last >= today]
    last_day = max((o.last for o in fiche.occurrences), default=None)
    values = {
        "uuid": fiche.uuid, "kind": fiche.kind, "name": fiche.name, "twins": twins_key(fiche),
        "types": ";".join(fiche.types), "category": fiche.category, "sort": fiche.sort, "sort_fr": fiche.sort_fr,
        "themes": sum(THEME_BITS[t] for t in fiche.themes), "lat": fiche.lat, "lon": fiche.lon,
        "street": fiche.street, "postcode": fiche.postcode, "town": fiche.town, "insee": fiche.insee,
        "department": fiche.department, "summary": fiche.summary, "description": fiche.description,
        "labels": json.dumps(fiche.labels, ensure_ascii=False), "prices": fiche.prices,
        "free": None if fiche.free is None else int(fiche.free),
        "contacts": json.dumps(fiche.contacts, ensure_ascii=False), "author": fiche.author,
        "updated": fiche.updated, "uri": fiche.uri, "last_day": last_day.isoformat() if last_day else "",
        "synced": synced,
    }
    row = conn.execute("SELECT id, name, lat, lon FROM fiche WHERE uuid = ?", (fiche.uuid,)).fetchone()
    if row is None:
        conn.execute(f"INSERT INTO fiche({', '.join(_FIELDS)}, seen, cell_seen) VALUES ({_marks(_FIELDS)}, ?, ?)",
                     [values[k] for k in _FIELDS] + [run or "", cell_seen])
        fid = conn.execute("SELECT id FROM fiche WHERE uuid = ?", (fiche.uuid,)).fetchone()[0]
    else:
        fid = row[0]
        moved = (row[1], row[2], row[3]) != (fiche.name, fiche.lat, fiche.lon)
        sets = ", ".join(f"{k} = ?" for k in _FIELDS)
        extra = (", seen = ?" if run else "") + (", cell_seen = ?" if cell_seen else "") + \
            (", twin = NULL, twin_m = NULL, venue = NULL, venue_place = ''" if moved else "")
        conn.execute(f"UPDATE fiche SET {sets}{extra} WHERE id = ?",
                     [values[k] for k in _FIELDS] + ([run] if run else []) + ([cell_seen] if cell_seen else []) + [fid])
        conn.execute("DELETE FROM fiche_box WHERE id = ?", (fid,))
        conn.execute("DELETE FROM occurrence WHERE fiche = ?", (fid,))
        conn.execute("DELETE FROM photo WHERE fiche = ?", (fid,))
    if fiche.lat is not None and fiche.lon is not None:
        conn.execute("INSERT INTO fiche_box(id, lat0, lat1, lon0, lon1) VALUES (?, ?, ?, ?, ?)",
                     (fid, fiche.lat, fiche.lat, fiche.lon, fiche.lon))
    conn.executemany("INSERT INTO occurrence(fiche, day0, day1, opens, closes, days) VALUES (?, ?, ?, ?, ?, ?)",
                     [(fid, o.first.isoformat(), o.last.isoformat(), o.opens, o.closes, o.days)
                      for o in sorted(set(occurrences))])
    conn.executemany("INSERT INTO photo(fiche, rank, ref, url, credit, licence, caption, rights_end) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     [(fid, k, photo_ref(p.url), p.url, p.credit, p.licence, p.caption, p.rights_end)
                      for k, p in enumerate(fiche.photos)])


_Lieux = tuple[sqlite3.Connection, bool]


def open_places(index: Path | None) -> _Lieux | None:
    """L'index des lieux en lecture seule, et s'il connaît les objets d'OpenStreetMap (schéma 2)."""
    if index is None or not index.is_file():
        return None
    try:
        conn = sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True)
        version = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    except sqlite3.DatabaseError:
        return None
    return conn, bool(version) and version[0] >= "2"


def _near(lieux: _Lieux, lat: float, lon: float, radius: float) -> list[tuple[Any, ...]]:
    conn, detailed = lieux
    w, s, e, n = box_around(lat, lon, radius)
    columns = "p.id, p.name, p.kind, p.category, p.lat, p.lon" + (", p.osm" if detailed else ", ''")
    rows = conn.execute(f"SELECT {columns} FROM place_box b JOIN place p ON p.id = b.id "
                        "WHERE b.lat0 <= ? AND b.lat1 >= ? AND b.lon0 <= ? AND b.lon1 >= ? AND p.category != 'villes'",
                        (n, s, e, w)).fetchall()
    out = []
    for row in rows:
        d = meters_between(lat, lon, row[4], row[5])
        if d <= radius:
            out.append((d, row))
    out.sort(key=lambda item: item[0])
    return [(*row, d) for d, row in out]


def _place_id(row: Sequence[Any]) -> str:
    """L'identifiant d'un lieu de l'index qui survit à sa reconstruction : son objet d'OpenStreetMap ; à défaut (un
    index tiré des tuiles), sa ligne."""
    return row[6] or f"l{row[0]}"


def index_twin(lieux: _Lieux, name: str, lat: float, lon: float, radius: float = TWIN_M, *,
          sort: str = "", town: str = "") -> tuple[str, int] | None:
    """Le lieu de l'index à moins de ``radius`` mètres qui est le plus ce lieu (``same_place`` : son nom, sa sorte —
    ``sort``, une catégorie de l'écran Carte —, sa commune ; le plus proche à égalité) : son identifiant durable et sa
    distance. Le cache des avis s'en sert aussi (ADR 0250), à son rayon."""
    best: tuple[float, float, tuple[Any, ...]] | None = None
    for row in _near(lieux, lat, lon, radius):
        score = same_place(name, sort, row[1], row[3], row[2], town=town)
        if score >= TWIN_LIKENESS and (best is None or (score, -row[7]) > (best[0], -best[1])):
            best = (score, row[7], row)
    return (_place_id(best[2]), round(best[1])) if best else None


def lone_places(path: Path) -> sqlite3.Connection | None:
    """La base en lecture seule, pour un autre cache qui y cherche un pendant (les avis, ADR 0250) ; absente, d'une autre
    version ou illisible : ``None``."""
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None or row[0] != SCHEMA_VERSION:
        conn.close()
        return None
    return conn


def lone_twin(conn: sqlite3.Connection, name: str, lat: float, lon: float, radius: float, *,
              sort: str = "") -> tuple[str, int] | None:
    """Le lieu DATAtourisme qu'OpenStreetMap n'a pas (``t:<uuid>``) à moins de ``radius`` mètres qui est ce lieu (son
    nom, sa sorte ``sort`` : ``same_place``) : son identifiant et sa distance."""
    w, s, e, n = box_around(lat, lon, radius)
    best: tuple[float, float, str] | None = None
    for uuid, other, olat, olon, category, kind in conn.execute(
            "SELECT f.uuid, f.name, f.lat, f.lon, f.category, f.sort FROM fiche_box b JOIN fiche f ON f.id = b.id "
            "WHERE b.lat0 <= ? AND b.lat1 >= ? AND b.lon0 <= ? AND b.lon1 >= ? AND f.kind = ? AND f.twin = ''",
            (n, s, e, w, PLACE)):
        d = meters_between(lat, lon, olat, olon)
        score = same_place(name, sort, other, category, kind)
        if d <= radius and score >= TWIN_LIKENESS and (best is None or (score, -d) > (best[0], -best[1])):
            best = (score, d, uuid)
    return (f"t:{best[2]}", round(best[1])) if best else None


def open_air(themes: Iterable[str]) -> bool:
    """Un événement de plein air (ADR 0259) : un marché, ou une fête qui n'est rien de ce qui se tient dans une salle
    (ni concert, ni spectacle, ni exposition, ni conférence, ni visite)."""
    said = set(themes)
    return bool(said & OPEN_AIR) or (FEAST in said and not said & INDOOR)


def names_a_street(street: str) -> bool:
    """Une adresse sans numéro qui nomme une place ou une rue (« Place du Concert », « Rue de Béthune ») : c'est là."""
    words = " ".join(_words_of(street))
    return bool(words) and not words[0].isdigit() and bool(STREET.match(words))


def _words_of(text: str) -> list[str]:
    """Les mots d'un nom, comparables (``name_key``)."""
    return name_key(text).split() if text else []


def _echo(text: str, town: str) -> set[str]:
    """Les mots qui distinguent un nom (sans articles, ni mots de sorte, ni la commune, ni ce qui dit une rue)."""
    ignored = set(_words_of(town)) | GENERIC_WORDS
    return {w for w in _words_of(text) if len(w) >= 3 and w not in ignored and not STREET.match(w)}


def _venue(lieux: _Lieux, lat: float, lon: float, *, name: str = "", street: str = "", town: str = "",
           themes: Sequence[str] = ()) -> tuple[str, str] | None:
    """Le lieu où se tient un événement (ADR 0259, 0269) : le plus proche à moins de ``VENUE_M`` mètres qui accueille
    du public (``VENUE_KINDS`` ; un lieu de culte pour un concert ou une visite) — aucun pour un événement de plein
    air ; à une adresse qui nomme une place ou une rue, seulement un lieu que l'événement ou l'adresse nomme
    (« l'opéra », place du Théâtre : l'Opéra de Lille) ; plus loin, jusqu'à ``VENUE_FAR_M``, seulement un lieu que
    l'événement nomme en entier (« … à l'Aéronef ») ou qui est à son adresse (le LaM, « 1 allée du Musée ») ; sinon
    ``None`` : son adresse dit où il est."""
    if open_air(themes):
        return None
    worship = bool(WORSHIP_THEMES & set(themes))
    words = _echo(f"{name} {street}", town)
    said = words if names_a_street(street) else None
    for row in _near(lieux, lat, lon, VENUE_FAR_M):
        if row[2] not in VENUE_KINDS and not (worship and row[2] == WORSHIP):
            continue
        own = _echo(row[1], town)
        if row[7] > VENUE_M:  # plus loin : nommé en entier, ou à la même adresse
            if not ((own and own <= words) or _same_address(lieux, row[0], street)):
                continue
        elif said is not None and not own & said:
            continue
        return row[1], _place_id(row)
    return None


def _same_address(lieux: _Lieux, place: int, street: str) -> bool:
    """Ce lieu de l'index est-il à cette adresse : son numéro et sa rue (``addr:housenumber``, ``addr:street``) en tête
    de celle de l'événement, mot pour mot (« 1 allée du Musée »)."""
    conn, detailed = lieux
    if not detailed or not street:
        return False
    row = conn.execute("SELECT tags FROM place WHERE id = ?", (place,)).fetchone()
    tags = read_kept(row[0] if row is not None else "")
    number, way = tags.get("addr:housenumber", ""), tags.get("addr:street", "")
    if not number or not way:
        return False
    want = plain_words(f"{number} {way}")
    return plain_words(street)[:len(want)] == want


# ── lire ──
@dataclass(frozen=True, slots=True)
class TourismInfo:
    """Ce que la base dit d'elle, pour la console et l'écran."""

    ready: bool
    places: int = 0
    events: int = 0
    twins: int = 0
    venues: int = 0
    photos: int = 0
    size: int = 0
    last_sync: str = ""
    last_kind: str = ""
    last_ended: str = ""
    last_full: str = ""
    run: str = ""
    run_done: int = 0
    run_parts: int = 0
    run_fiches: int = 0
    last_error: str = ""
    last_error_at: str = ""
    zones: str = ""
    #: la construction de l'index des lieux avec lequel elle a été rapprochée
    matched_with: str = ""
    #: les cases lues jusqu'au bout (une case et une liste), la plus ancienne et la plus récente de leurs lectures
    cells: int = 0
    oldest_cell: str = ""
    newest_cell: str = ""

    @property
    def read_at(self) -> str:
        """Sa dernière lecture (ISO 8601 ; vide : jamais) : celle d'une case ou d'un département, la plus récente
        (R3-04 — le cache par cases, le défaut, ne marque pas la synchronisation des départements)."""
        return max(self.last_ended, self.newest_cell)


@dataclass(frozen=True, slots=True)
class CellState:
    """Une case et une liste dans la base : ``fetched``, quand elle a été lue jusqu'au bout (ISO 8601 ; vide :
    jamais) ; ``reading`` : une lecture commencée, pas finie (elle reprend à sa page suivante)."""

    fetched: str = ""
    reading: bool = False
    count: int = 0


def _json_pairs(text: str) -> list[list[str]]:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return [v for v in value if isinstance(v, list) and len(v) == 2] if isinstance(value, list) else []


def _occurrence(row: Sequence[Any]) -> Occurrence:
    return Occurrence(date.fromisoformat(row[1]), date.fromisoformat(row[2]), row[3], row[4], row[5])


def _themes(bits: int) -> tuple[str, ...]:
    return tuple(theme for theme, _label in THEMES if bits & THEME_BITS[theme])


def _where(row: sqlite3.Row) -> str:
    head = row["venue"] or row["street"]
    return ", ".join(p for p in (head, row["town"]) if p)


class Tourism:
    """La base telle qu'on la lit (``data``/``cartes/tourisme.db``) : une connexion par lecture, hors de la boucle ;
    ``now``, l'instant où l'on juge ce qui est à venir."""

    def __init__(self, data: Path, *, now: Callable[[], datetime] = utc_now) -> None:
        self.data = data
        self.now = now
        self.base = TourismBase(data / TOURISM_FILE)
        self._info: tuple[tuple[int, int], TourismInfo] | None = None

    @property
    def path(self) -> Path:
        return self.base.path

    def _key(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def info(self) -> TourismInfo:
        """Ce que la base dit d'elle (relu quand le fichier change)."""
        key = self._key()
        if key is None:
            return TourismInfo(False)
        if self._info is not None and self._info[0] == key:
            return self._info[1]
        try:
            conn = _connect(self.path)
            try:
                got = _info(conn, key[1])
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            got = TourismInfo(False, last_error=DAMAGED)
        self._info = (key, got)
        return got

    def ready(self) -> bool:
        return self.info().ready

    async def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        if not self.ready():
            raise MapsUnavailable(NOT_SYNCED)

        def run() -> Any:
            conn = _connect(self.path)
            try:
                return fn(conn)
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(run)
        except sqlite3.DatabaseError:
            raise MapsUnavailable(DAMAGED) from None

    # ── les événements ──
    async def events(self, *, near: tuple[float, float] | None, bbox: tuple[float, float, float, float] | None,
                     radius_m: float, start: date, end: date, themes: int, words: list[str], free: bool,
                     limit: int) -> list[EventHit]:
        now = self.now()
        return await self._run(lambda conn: _events(conn, now, near=near, bbox=bbox, radius_m=radius_m, start=start,
                                                    end=end, themes=themes, words=words, free=free, limit=limit))

    async def event(self, uuid: str) -> EventDetail | None:
        if not UUID.match(uuid):
            return None
        now = self.now()
        return await self._run(lambda conn: _event(conn, uuid, now))

    async def near_events(self, lat: float, lon: float, places: Sequence[str]) -> list[EventHit]:
        """Les événements à venir d'un lieu : ceux qui s'y tiennent (``venue_place``), puis ceux d'à côté."""
        if not self.ready():
            return []
        now = self.now()
        today = paris_today(now)
        end = today + timedelta(days=NEAR_EVENTS_DAYS)

        def read(conn: sqlite3.Connection) -> list[EventHit]:
            hits = _events(conn, now, near=(lat, lon), bbox=None, radius_m=NEAR_EVENTS_M, start=today, end=end,
                           themes=0, words=[], free=False, limit=NEAR_EVENTS_MAX, also=places)
            return hits

        try:
            return await self._run(read)
        except MapsUnavailable:
            return []

    # ── les lieux ──
    async def facts_for(self, places: Sequence[str]) -> tuple[TourismFacts | None, str]:
        """La partie DATAtourisme d'un lieu de l'index (son objet, sa ligne) : la fiche rapprochée la plus proche ; et
        l'identifiant ``t:<uuid>`` de cette fiche."""
        keys = [p for p in places if p]
        if not keys or not self.ready():
            return None, ""
        today = paris_today(self.now())

        def read(conn: sqlite3.Connection) -> tuple[TourismFacts | None, str]:
            row = conn.execute(f"SELECT * FROM fiche WHERE kind = ? AND twin IN ({_marks(keys)}) "
                               "ORDER BY twin_m, id LIMIT 1", [PLACE, *keys]).fetchone()
            return (_facts(conn, row, today), row["uuid"]) if row is not None else (None, "")

        try:
            return await self._run(read)
        except MapsUnavailable:
            return None, ""

    async def synced_at(self, uuid: str) -> datetime | None:
        """Quand cette fiche a été lue chez DATAtourisme la dernière fois (``None`` : on ne l'a pas) — « Actualiser »
        ne la relit pas tout de suite (ADR 0269)."""
        if not UUID.match(uuid) or not self.ready():
            return None

        def read(conn: sqlite3.Connection) -> str:
            row = conn.execute("SELECT synced FROM fiche WHERE uuid = ?", (uuid,)).fetchone()
            return row[0] if row is not None else ""

        try:
            synced = await self._run(read)
        except MapsUnavailable:
            return None
        try:
            return datetime.fromisoformat(synced.replace("Z", "+00:00")) if synced else None
        except ValueError:
            return None

    async def place(self, uuid: str) -> tuple[PlaceHit, TourismFacts, str] | None:
        """Un lieu DATAtourisme (``t:<uuid>``) : ce qu'en dit une liste, sa partie DATAtourisme, et son pendant
        d'OpenStreetMap s'il en a un (vide sinon)."""
        if not UUID.match(uuid) or not self.ready():
            return None
        today = paris_today(self.now())

        def read(conn: sqlite3.Connection) -> tuple[PlaceHit, TourismFacts, str] | None:
            row = conn.execute("SELECT * FROM fiche WHERE uuid = ? AND kind = ? AND lat IS NOT NULL",
                               (uuid, PLACE)).fetchone()
            if row is None:
                return None
            return _place_hit(row), _facts(conn, row, today), row["twin"] or ""

        return await self._run(read)

    async def places(self, words: list[str], *, near: tuple[float, float] | None,
                     bbox: tuple[float, float, float, float] | None, radius_m: float | None, category: str,
                     limit: int) -> list[PlaceHit]:
        """Les lieux DATAtourisme qu'OpenStreetMap n'a pas (sûrement : leur rapprochement les a jugés sans pendant),
        comme ``t:<uuid>`` — par le texte, autour d'un point, dans une zone, d'une catégorie."""
        if not self.ready():
            return []
        try:
            return await self._run(lambda conn: _places(conn, words, near=near, bbox=bbox, radius_m=radius_m,
                                                        category=category, limit=limit))
        except MapsUnavailable:
            return []

    # ── les cases ──
    def cell_states(self, keys: Sequence[str]) -> dict[tuple[str, str], CellState]:
        """Ce que la base sait de ces cases, par (case, liste) ; une case jamais lue n'y est pas."""
        if not keys or not self.path.exists():
            return {}
        out: dict[tuple[str, str], CellState] = {}
        try:
            conn = _connect(self.path)
            try:
                for part in _chunks(list(dict.fromkeys(keys))):
                    for row in conn.execute(f"SELECT key, part, fetched, started, count FROM cell "
                                            f"WHERE key IN ({_marks(part)})", list(part)):
                        out[(row[0], row[1])] = CellState(row[2], bool(row[3]), row[4])
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return {}
        return out

    # ── les photos (``photos.PhotoSource``) ──
    def photo_origin(self, ref: str) -> PhotoOrigin | None:
        if not self.path.exists():
            return None
        try:
            conn = _connect(self.path)
            try:
                rows = conn.execute("SELECT url, rights_end FROM photo WHERE ref = ?", (ref,)).fetchall()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return None
        if not rows:
            return None
        ends = [r[1] for r in rows]
        return PhotoOrigin(rows[0][0], SOURCE, "" if "" in ends else max(ends))


def _info(conn: sqlite3.Connection, size: int) -> TourismInfo:
    meta = TourismBase.meta(conn)
    if meta.get("version") != SCHEMA_VERSION:
        return TourismInfo(False, last_error=DAMAGED)
    counts = dict(conn.execute("SELECT kind, COUNT(*) FROM fiche GROUP BY kind").fetchall())
    twins = conn.execute("SELECT COUNT(*) FROM fiche WHERE kind = ? AND twin != ''", (PLACE,)).fetchone()[0]
    venues = conn.execute("SELECT COUNT(*) FROM fiche WHERE kind = ? AND venue != ''", (EVENT,)).fetchone()[0]
    photos = conn.execute("SELECT COUNT(*) FROM photo").fetchone()[0]
    cells, oldest, newest = conn.execute("SELECT COUNT(*), MIN(fetched), MAX(fetched) FROM cell "
                                         "WHERE fetched != ''").fetchone()
    run = meta.get("run", "")
    done = parts = fiches = 0
    if run:
        done, parts, fiches = conn.execute("SELECT SUM(done), COUNT(*), SUM(count) FROM progress WHERE run = ?",
                                           (run,)).fetchone()
    return TourismInfo(bool(meta.get("last_sync")) or bool(counts), places=counts.get(PLACE, 0),
                       events=counts.get(EVENT, 0), twins=twins, venues=venues, photos=photos, size=size,
                       last_sync=meta.get("last_sync", ""), last_kind=meta.get("last_kind", ""),
                       last_ended=meta.get("last_ended", ""), last_full=meta.get("last_full", ""), run=run,
                       run_done=done or 0, run_parts=parts or 0, run_fiches=fiches or 0,
                       last_error=meta.get("last_error", ""), last_error_at=meta.get("last_error_at", ""),
                       zones=meta.get("zones", ""), matched_with=meta.get("matched_with", ""), cells=cells or 0,
                       oldest_cell=oldest or "", newest_cell=newest or "")


def _photos(conn: sqlite3.Connection, ids: Sequence[int], today: date) -> dict[int, list[Photo]]:
    out: dict[int, list[Photo]] = {}
    day = today.isoformat()
    for part in _chunks(list(ids)):
        for row in conn.execute(f"SELECT fiche, ref, credit, licence, caption, rights_end FROM photo "
                                f"WHERE fiche IN ({_marks(part)}) ORDER BY fiche, rank", part):
            if row[5] and row[5] < day:
                continue  # ses droits ont pris fin
            out.setdefault(row[0], []).append(Photo(ref=row[1], source=SOURCE, credit=row[2], licence=row[3],
                                                    caption=row[4]))
    return out


def _facts(conn: sqlite3.Connection, row: sqlite3.Row, today: date) -> TourismFacts:
    day = today.isoformat()
    labels = tuple(label for label, ends in _json_pairs(row["labels"]) if not ends or ends >= day)
    contacts = tuple((a, b) for a, b in _json_pairs(row["contacts"]))
    return TourismFacts(id=f"t:{row['uuid']}", description=row["description"] or row["summary"], labels=labels,
                        prices=row["prices"], contacts=contacts, author=row["author"], updated=row["updated"],
                        url=row["uri"], photos=tuple(_photos(conn, [row["id"]], today).get(row["id"], [])))


def _place_hit(row: sqlite3.Row, distance_m: float | None = None) -> PlaceHit:
    return PlaceHit(id=f"t:{row['uuid']}", name=row["name"], kind=row["sort"], kind_fr=row["sort_fr"],
                    category=row["category"], lat=row["lat"], lon=row["lon"], town=row["town"],
                    distance_m=None if distance_m is None else round(distance_m))


def _area(near: tuple[float, float] | None, bbox: tuple[float, float, float, float] | None,
          radius_m: float | None) -> tuple[float, float, float, float] | None:
    if bbox is not None:
        return bbox
    if near is not None and radius_m is not None:
        return box_around(near[0], near[1], radius_m)
    return None


def _candidates(conn: sqlite3.Connection, kind: str, *, area: tuple[float, float, float, float] | None,
                near: tuple[float, float] | None, words: list[str], where: str, params: list[Any],
                limit: int) -> list[sqlite3.Row]:
    sql = "SELECT f.* FROM fiche f"
    conditions = ["f.kind = ?"]
    args: list[Any] = [kind]
    if area is not None:
        sql += " JOIN fiche_box b ON b.id = f.id"
        w, s, e, n = area
        conditions.append("b.lat0 <= ? AND b.lat1 >= ? AND b.lon0 <= ? AND b.lon1 >= ?")
        args += [n, s, e, w]
    if words:
        conditions.append("f.id IN (SELECT rowid FROM fiche_text WHERE fiche_text MATCH ?)")
        args.append(match_query(words))
    if where:
        conditions.append(where)
        args += params
    sql += " WHERE " + " AND ".join(conditions)
    if near is not None:
        lat, lon = near
        sql += " ORDER BY (f.lat - ?) * (f.lat - ?) + (f.lon - ?) * (f.lon - ?) * ?"
        cos = max(0.01, abs(math.cos(math.radians(lat))))
        args += [lat, lat, lon, lon, cos * cos]
    else:
        sql += " ORDER BY f.id"
    sql += " LIMIT ?"
    return conn.execute(sql, [*args, limit]).fetchall()


def _places(conn: sqlite3.Connection, words: list[str], *, near: tuple[float, float] | None,
            bbox: tuple[float, float, float, float] | None, radius_m: float | None, category: str,
            limit: int) -> list[PlaceHit]:
    where, params = "f.twin = '' AND f.lat IS NOT NULL", []
    if category:
        where += " AND f.category = ?"
        params.append(category)
    rows = _candidates(conn, PLACE, area=_area(near, bbox, radius_m), near=near, words=words, where=where,
                       params=params, limit=limit * 3 + 20)
    out = []
    for row in rows:
        d = meters_between(near[0], near[1], row["lat"], row["lon"]) if near is not None else None
        if radius_m is not None and d is not None and d > radius_m:
            continue
        out.append(_place_hit(row, d))
    if near is not None:
        out.sort(key=lambda h: h.distance_m or 0)
    return out[:limit]


def _members(conn: sqlite3.Connection, keys: Sequence[str]) -> dict[str, list[sqlite3.Row]]:
    groups: dict[str, list[sqlite3.Row]] = {}
    for part in _chunks(list(keys)):
        for row in conn.execute(f"SELECT * FROM fiche WHERE kind = ? AND twins IN ({_marks(part)})",
                                [EVENT, *part]):
            groups.setdefault(row["twins"], []).append(row)
    return groups


def _occurrences(conn: sqlite3.Connection, ids: Sequence[int], today: date) -> dict[int, list[Occurrence]]:
    out: dict[int, list[Occurrence]] = {}
    for part in _chunks(list(ids)):
        for row in conn.execute(f"SELECT fiche, day0, day1, opens, closes, days FROM occurrence "
                                f"WHERE fiche IN ({_marks(part)}) AND day1 >= ?", [*part, today.isoformat()]):
            out.setdefault(row[0], []).append(_occurrence(row))
    return out


@dataclass(frozen=True, slots=True)
class _Group:
    """Les fiches d'un même événement : l'identifiant (le plus petit), la fiche qu'on lit (la plus récente), toutes
    leurs dates, leurs photos."""

    id_row: sqlite3.Row
    row: sqlite3.Row
    members: tuple[sqlite3.Row, ...]
    occurrences: tuple[Occurrence, ...]
    photos: tuple[Photo, ...]

    @property
    def themes(self) -> int:
        bits = 0
        for m in self.members:
            bits |= m["themes"]
        return bits


def _groups(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row], today: date) -> list[_Group]:
    keys = list(dict.fromkeys(r["twins"] for r in rows))
    members = _members(conn, keys)
    ids = [m["id"] for group in members.values() for m in group]
    occurrences = _occurrences(conn, ids, today)
    photos = _photos(conn, ids, today)
    out = []
    for key in keys:
        group = members.get(key) or []
        if not group:
            continue
        id_row = min(group, key=lambda m: m["uuid"])
        row = max(group, key=lambda m: (m["updated"], len(m["description"]), m["uuid"]))
        occs = sorted({o for m in group for o in occurrences.get(m["id"], ())})
        pics = tuple(dict.fromkeys(p for m in sorted(group, key=lambda m: m["uuid"]) for p in photos.get(m["id"], ())))
        out.append(_Group(id_row, row, tuple(group), tuple(occs), pics))
    return out


def _free(group: _Group) -> bool | None:
    said = [m["free"] for m in (group.row, *group.members) if m["free"] is not None]
    return None if not said else bool(said[0])


def _hit(group: _Group, now: datetime, *, start: date | None = None, end: date | None = None,
         near: tuple[float, float] | None = None) -> EventHit | None:
    ahead = upcoming(group.occurrences, now, start, end)
    row = group.row
    distance = meters_between(near[0], near[1], row["lat"], row["lon"]) if near is not None and row["lat"] is not None \
        else None
    if ahead:
        day, first = ahead[0]
        begins, ends = session(day, first)  # sa prochaine séance, jamais la fin de sa période (ses ``dates`` la disent)
    elif start is not None:
        return None
    else:
        begins = ends = ""
    return EventHit(id=f"e:{group.id_row['uuid']}", name=row["name"], start=begins, end=ends,
                    when_text=when_text(group.occurrences, now, start, end), place=_where(row), lat=row["lat"],
                    lon=row["lon"], distance_m=None if distance is None else round(distance),
                    themes=_themes(group.themes), free=_free(group), price=row["prices"],
                    **_photo_cited(group.photos[0] if group.photos else None))


def _photo_cited(photo: Photo | None) -> dict[str, str]:
    """La première photo d'un événement et ce qu'il faut en citer là où elle se montre (ADR 0269) : son auteur et sa
    licence ; sans photo, rien."""
    if photo is None:
        return {}
    return {"photo": photo.ref, "photo_source": photo.source, "photo_credit": photo.credit,
            "photo_credit_url": photo.credit_url, "photo_licence": photo.licence}


def _events(conn: sqlite3.Connection, now: datetime, *, near: tuple[float, float] | None,
            bbox: tuple[float, float, float, float] | None, radius_m: float, start: date, end: date, themes: int,
            words: list[str], free: bool, limit: int, also: Sequence[str] = ()) -> list[EventHit]:
    today = paris_today(now)
    where = ("f.last_day >= ? AND EXISTS (SELECT 1 FROM occurrence o WHERE o.fiche = f.id AND o.day1 >= ? AND "
             "o.day0 <= ?)")
    params: list[Any] = [max(today, start).isoformat(), max(today, start).isoformat(), end.isoformat()]
    if themes:
        where += " AND (f.themes & ?) != 0"
        params.append(themes)
    if free:
        where += " AND f.free = 1"
    area = _area(near, bbox, radius_m if bbox is None else None)
    rows = list(_candidates(conn, EVENT, area=area, near=near, words=words, where=where, params=params,
                            limit=CANDIDATES_MAX))
    if also:  # ceux qui se tiennent dans ce lieu, même un peu plus loin
        rows += conn.execute(f"SELECT f.* FROM fiche f WHERE f.kind = ? AND f.venue_place IN ({_marks(also)}) "
                             f"AND {where} LIMIT ?", [EVENT, *also, *params, CANDIDATES_MAX]).fetchall()
    hits: list[tuple[tuple[Any, ...], EventHit]] = []
    for group in _groups(conn, rows, today):
        hit = _hit(group, now, start=start, end=end, near=near)
        if hit is None:
            continue
        if bbox is None and near is not None and hit.distance_m is not None and hit.distance_m > radius_m and \
                group.row["venue_place"] not in also:
            continue
        ahead = upcoming(group.occurrences, now, start, end)
        order = (ahead[0][0], ahead[0][1].opens or "99", hit.distance_m or 0, hit.id)
        hits.append((order, hit))
    hits.sort(key=lambda item: item[0])
    return [hit for _order, hit in hits[:limit]]


def _event(conn: sqlite3.Connection, uuid: str, now: datetime) -> EventDetail | None:
    row = conn.execute("SELECT * FROM fiche WHERE uuid = ? AND kind = ?", (uuid, EVENT)).fetchone()
    if row is None:
        return None
    today = paris_today(now)
    groups = _groups(conn, [row], today)
    if not groups:
        return None
    group = groups[0]
    hit = _hit(group, now)
    assert hit is not None
    dates, more = dates_fr(group.occurrences, now, DATES_SHOWN)
    main = group.row
    contacts = tuple(dict.fromkeys((a, b) for m in (main, *group.members) for a, b in _json_pairs(m["contacts"])))
    address = ", ".join(p for p in (main["street"], " ".join(p for p in (main["postcode"], main["town"]) if p)) if p)
    return EventDetail(hit=hit, description=main["description"] or main["summary"], dates=tuple(dates),
                       more_dates=more, prices=main["prices"], contacts=contacts[:8], address=address,
                       town=main["town"], venue=main["venue"] or "", venue_place=main["venue_place"],
                       author=main["author"], updated=main["updated"], url=main["uri"], photos=group.photos,
                       merged=len(group.members))


def merge_places(osm: Sequence[PlaceHit], tourism: Sequence[PlaceHit], *, near: bool, limit: int) -> list[PlaceHit]:
    """Les lieux d'OpenStreetMap et ceux des données touristiques qu'il n'a pas, sans jamais un lieu en double : un
    ``t:`` à moins de ``TWIN_M`` mètres d'un lieu de la liste qui est lui (``same_place``) s'en va. Autour d'un point,
    tous par la distance ; sinon ceux d'OpenStreetMap d'abord."""
    kept = [t for t in tourism if not any(
        meters_between(t.lat, t.lon, o.lat, o.lon) <= TWIN_M
        and same_place(t.name, t.category, o.name, o.category, o.kind, town=t.town) >= TWIN_LIKENESS for o in osm)]
    if near:
        both = sorted([*osm, *kept], key=lambda h: (h.distance_m is None, h.distance_m or 0))
        return both[:limit]
    return [*osm, *kept][:limit]


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
