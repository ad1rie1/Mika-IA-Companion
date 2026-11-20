"""Le limiteur des services de la carte (ADR 0245) : ce qui part vers un service payé ou borné (DATAtourisme,
Google Places), compté et retenu, une instance par service, ses bornes réglées dans la section de console du service
et relues à chaque demande.

**Les bornes** (``Limits``) sont facultatives et se combinent : par seconde (un espacement, en mémoire), par heure et
par jour (des fenêtres glissantes de 60 minutes et de 24 heures, qui comptent les demandes), par mois (le mois civil,
à l'heure de Paris ou à celle du service — Google remet ses quotas à zéro à minuit, heure du Pacifique : ``month_zone``
—, un compteur qu'on incrémente du coût d'un appel : ``charge`` après coup, ou dès qu'il part, ``take(book=True)``,
pour un service qui facture chaque appel). **Une réserve** garde une part de chaque borne aux demandes faites en direct (une personne qui ouvre un
écran) : un travail de fond (``background``) ne prend que ce qui reste au-delà. **Un recul** : quand le service dit
d'attendre (un 429), plus rien ne part avant l'heure dite (``back_off``).

**Les compteurs survivent** à un redémarrage, et se partagent entre le serveur et une commande : ils sont dans
``cartes/quotas.db`` (``QuotaStore``). **Ce qui bloque se dit en mots** (``QuotaExceeded`` : « le quota du jour de
Google est atteint : il revient à 14:05 »), avec l'heure où il revient ; une demande attend au plus ``wait_max``
secondes qu'il revienne.

Pour s'en servir (un nouveau service) : ``Limiter("google", store, lambda: Limits(...), label="Google",
unit="appels")``, puis ``await limiter.take(background=…, wait_max=…)`` avant chaque appel (``book=True`` : compté au
mois dès qu'il part), ``await limiter.charge(n)`` après si le mois compte autre chose que des appels (``unit`` : ce
qu'il compte, en mots), ``limiter.back_off(s)`` sur un 429, ``limiter.status()`` pour la console."""

from __future__ import annotations

import asyncio
import contextlib
import math
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path

from mika.adapters.maps.config import MAPS_DIR
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.pace import Pace
from mika.ports.maps import MapsUnavailable

QUOTAS_FILE = f"{MAPS_DIR}/quotas.db"
HOUR_S, DAY_S = 3600.0, 86_400.0
#: ce que la base garde des demandes : un peu plus que la plus longue fenêtre
KEPT_S = DAY_S + HOUR_S
HOUR, DAY, MONTH, SECOND, WAIT = "heure", "jour", "mois", "seconde", "recul"
MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS call (service TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS call_at ON call(service, at);
CREATE TABLE IF NOT EXISTS month (service TEXT NOT NULL, month TEXT NOT NULL, used INTEGER NOT NULL,
                                  PRIMARY KEY (service, month));
CREATE TABLE IF NOT EXISTS backoff (service TEXT PRIMARY KEY, until REAL NOT NULL);
"""


@dataclass(frozen=True, slots=True)
class Limits:
    """Les bornes d'un service ; ``None`` : pas de borne de cette sorte. ``reserve`` : la part (0 à 0,9) de chaque
    borne d'heure, de jour et de mois gardée aux demandes en direct."""

    per_second: float | None = None
    per_hour: int | None = None
    per_day: int | None = None
    per_month: int | None = None
    reserve: float = 0.0


class QuotaExceeded(MapsUnavailable):
    """Une borne atteinte, en mots ; ``until`` : quand elle revient (``None`` : on ne sait pas) ; ``window`` : laquelle
    (``HOUR``, ``DAY``, ``MONTH``, ``WAIT``)."""

    def __init__(self, text: str, until: datetime | None, window: str) -> None:
        super().__init__(text)
        self.until = until
        self.window = window


class QuotaStore:
    """``cartes/quotas.db`` : les demandes de chaque service (les dernières 25 heures), son compteur de chaque mois, son
    recul. Une connexion courte par opération, hors de la boucle ; un fichier absent se lit vide (rien n'est créé à la
    lecture)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self, *, write: bool) -> sqlite3.Connection | None:
        if not write and not self.path.exists():
            return None
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        if write:
            conn.executescript(_SCHEMA)
        return conn

    def calls_since(self, service: str, since: float) -> list[float]:
        conn = self._connect(write=False)
        if conn is None:
            return []
        try:
            return [r[0] for r in conn.execute("SELECT at FROM call WHERE service = ? AND at > ? ORDER BY at",
                                               (service, since))]
        except sqlite3.OperationalError:  # le fichier d'avant ses tables
            return []
        finally:
            conn.close()

    def note_call(self, service: str, at: float) -> None:
        conn = self._connect(write=True)
        assert conn is not None
        try:
            conn.execute("INSERT INTO call(service, at) VALUES (?, ?)", (service, at))
            if int(at) % 50 == 0:  # de temps en temps : ce qui est sorti de toutes les fenêtres
                conn.execute("DELETE FROM call WHERE at < ?", (at - KEPT_S,))
            conn.commit()
        finally:
            conn.close()

    def month_used(self, service: str, month: str) -> int:
        conn = self._connect(write=False)
        if conn is None:
            return 0
        try:
            row = conn.execute("SELECT used FROM month WHERE service = ? AND month = ?", (service, month)).fetchone()
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()
        return int(row[0]) if row else 0

    def add_month(self, service: str, month: str, cost: int) -> None:
        conn = self._connect(write=True)
        assert conn is not None
        try:
            found = conn.execute("SELECT used FROM month WHERE service = ? AND month = ?", (service, month)).fetchone()
            if found is None:
                conn.execute("INSERT INTO month(service, month, used) VALUES (?, ?, ?)", (service, month, cost))
            else:
                conn.execute("UPDATE month SET used = used + ? WHERE service = ? AND month = ?",
                             (cost, service, month))
            conn.commit()
        finally:
            conn.close()

    def backoff(self, service: str) -> float:
        conn = self._connect(write=False)
        if conn is None:
            return 0.0
        try:
            row = conn.execute("SELECT until FROM backoff WHERE service = ?", (service,)).fetchone()
        except sqlite3.OperationalError:
            return 0.0
        finally:
            conn.close()
        return float(row[0]) if row else 0.0

    def set_backoff(self, service: str, until: float) -> None:
        conn = self._connect(write=True)
        assert conn is not None
        try:
            conn.execute("DELETE FROM backoff WHERE service = ?", (service,))
            conn.execute("INSERT INTO backoff(service, until) VALUES (?, ?)", (service, until))
            conn.commit()
        finally:
            conn.close()


@dataclass(frozen=True, slots=True)
class Window:
    """Une borne vue à un instant : combien sont pris, sur combien, dont combien gardés pour le direct."""

    name: str
    used: int
    limit: int
    kept: int


@dataclass(frozen=True, slots=True)
class Status:
    """Ce que le limiteur dit de lui (la console) : ses fenêtres, et ce qui bloque un travail de fond, en mots."""

    windows: tuple[Window, ...]
    per_second: float | None
    blocked: str = ""
    until: datetime | None = None


def _month_of(at: float, zone: tzinfo = PARIS) -> str:
    """Le mois de cet instant (« 2026-11 »), à l'heure de ``zone``."""
    local = datetime.fromtimestamp(at, zone)
    return f"{local.year:04d}-{local.month:02d}"


def _next_month(at: float, zone: tzinfo = PARIS) -> datetime:
    """Minuit du premier jour du mois suivant, à l'heure de ``zone``."""
    local = datetime.fromtimestamp(at, zone)
    first = date(local.year + (local.month == 12), local.month % 12 + 1, 1)
    return datetime.combine(first, datetime.min.time(), zone)


def when_fr(until: datetime, now: datetime) -> str:
    """« à 14:05 », « demain à 09:12 », « le 1er décembre » : quand une borne revient, vu de maintenant (Paris)."""
    local, today = until.astimezone(PARIS), now.astimezone(PARIS).date()
    if local.date() == today:
        return f"à {local:%H:%M}"
    if local.date() == today + timedelta(days=1):
        return f"demain à {local:%H:%M}"
    return f"le {'1er' if local.day == 1 else local.day} {MONTHS_FR[local.month - 1]}"


class Limiter:
    """Les demandes d'un service (``service`` : son nom dans la base ; ``label`` : en mots), sous les bornes que
    ``limits`` rend (relu à chaque demande) ; ``month_zone`` : à quelle heure son mois commence (Paris, par défaut)."""

    def __init__(self, service: str, store: QuotaStore, limits: Callable[[], Limits], *, label: str = "",
                 unit: str = "unités", now: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[object]] = asyncio.sleep, month_zone: tzinfo = PARIS) -> None:
        self.service = service
        self.store = store
        self.limits = limits
        self.label = label or service
        #: ce que compte le mois, en mots (« recherches », « fiches », « photos » pour Google)
        self.unit = unit
        self.month_zone = month_zone
        self._now = now
        self._sleep = sleep
        self._counting = asyncio.Lock()
        self._pace: tuple[float, Pace] | None = None

    def _cap(self, limit: int, reserve: float, background: bool) -> int:
        return max(0, math.floor(limit * (1 - reserve))) if background else limit

    def _blocked(self, lim: Limits, now: float, cost: int, background: bool) -> tuple[str, float, str] | None:
        """Ce qui empêche une demande à cet instant : (sa phrase, quand elle revient, sa fenêtre) ; ``None`` : rien."""
        reserve = min(0.9, max(0.0, lim.reserve))
        part = "la part de fond du quota" if background and reserve else "le quota"
        held = self.store.backoff(self.service)
        if held > now:
            return f"{self.label} a demandé d'attendre", held, WAIT
        for name, span, limit in ((HOUR, HOUR_S, lim.per_hour), (DAY, DAY_S, lim.per_day)):
            if limit is None:
                continue
            cap = self._cap(limit, reserve, background)
            calls = self.store.calls_since(self.service, now - span)
            if len(calls) >= cap:
                until = calls[len(calls) - cap] + span if cap else now + span
                return f"{part} de l'{name} de {self.label} est atteint" if name == HOUR else \
                    f"{part} du {name} de {self.label} est atteint", until + 0.5, name
        if lim.per_month is not None:
            cap = self._cap(lim.per_month, reserve, background)
            if self.store.month_used(self.service, _month_of(now, self.month_zone)) + cost > cap:
                return f"{part} du mois de {self.label} est atteint", \
                    _next_month(now, self.month_zone).timestamp(), MONTH
        return None

    async def take(self, *, cost: int = 1, background: bool = False, wait_max: float = 0.0,
                   book: bool = False) -> None:
        """Une demande (``cost`` : ce qu'elle coûtera au mois, au plus) : comptée, ou retenue tant qu'une borne est
        atteinte — au plus ``wait_max`` secondes, puis ``QuotaExceeded``. ``background`` : un travail de fond, qui
        laisse la réserve au direct. ``book`` : ``cost`` compte au mois dès maintenant, dans le même tour que le
        contrôle (deux demandes en même temps ne passent pas toutes deux sous le plafond), qu'elle réussisse ou non —
        pour un service qui facture l'appel."""
        waited = 0.0
        while True:
            lim = self.limits()
            async with self._counting:
                now = self._now()
                blocked = await asyncio.to_thread(self._blocked, lim, now, cost, background)
                if blocked is None:
                    await asyncio.to_thread(self.store.note_call, self.service, now)
                    if book and cost > 0:
                        await asyncio.to_thread(self.store.add_month, self.service,
                                                _month_of(now, self.month_zone), int(cost))
                    break
            text, until, window = blocked
            wait = max(0.0, until - now)
            if waited + wait > wait_max:
                at = datetime.fromtimestamp(until, PARIS)
                raise QuotaExceeded(f"{text} : il revient {when_fr(at, datetime.fromtimestamp(now, PARIS))}.", at,
                                    window)
            await self._sleep(wait)
            waited += wait
        if lim.per_second:
            await self._turns(lim.per_second).turn()

    def _turns(self, rate: float) -> Pace:
        if self._pace is None or self._pace[0] != rate:
            pace = Pace(rate, wait_max=HOUR_S, now=self._now, sleep=self._sleep)
            if self._pace is not None:  # un débit changé dans la console : le tour déjà pris reste pris
                pace._next = self._pace[1]._next
            self._pace = (rate, pace)
        return self._pace[1]

    async def charge(self, cost: int) -> None:
        """Le coût réel d'un appel, au compteur du mois."""
        if cost > 0:
            await asyncio.to_thread(self.store.add_month, self.service, _month_of(self._now(), self.month_zone),
                                    int(cost))

    def back_off(self, seconds: float) -> None:
        """Le service a dit d'attendre : plus rien ne part avant ``seconds`` secondes."""
        until = self._now() + max(1.0, seconds)
        with contextlib.suppress(sqlite3.Error, OSError):
            self.store.set_backoff(self.service, max(until, self.store.backoff(self.service)))

    def status(self) -> Status:
        """Ses fenêtres à cet instant, et ce qui bloquerait un travail de fond."""
        lim = self.limits()
        now = self._now()
        reserve = min(0.9, max(0.0, lim.reserve))
        windows = []
        for name, span, limit in ((HOUR, HOUR_S, lim.per_hour), (DAY, DAY_S, lim.per_day)):
            if limit is not None:
                windows.append(Window(name, len(self.store.calls_since(self.service, now - span)), limit,
                                      limit - self._cap(limit, reserve, True)))
        if lim.per_month is not None:
            windows.append(Window(MONTH, self.store.month_used(self.service, _month_of(now, self.month_zone)),
                                  lim.per_month, lim.per_month - self._cap(lim.per_month, reserve, True)))
        blocked = self._blocked(lim, now, 1, True)
        if blocked is None:
            return Status(tuple(windows), lim.per_second)
        at = datetime.fromtimestamp(blocked[1], PARIS)
        return Status(tuple(windows), lim.per_second,
                      f"{blocked[0]} : il revient {when_fr(at, datetime.fromtimestamp(now, PARIS))}", at)

    def describe(self) -> str:
        """En mots, pour la console : « 123 demandes dans l'heure sur 900 (180 gardées pour le direct), au plus 8 par
        seconde »."""
        st = self.status()
        parts = []
        for w in st.windows:
            what = {HOUR: "demandes dans l'heure", DAY: "demandes en 24 heures", MONTH: f"{self.unit} ce mois"}[w.name]
            parts.append(f"{w.used} {what} sur {w.limit}" + (f" ({w.kept} gardées pour le direct)" if w.kept else ""))
        if st.per_second:
            parts.append(f"au plus {st.per_second:g} par seconde".replace(".", ","))
        said = " ; ".join(parts) or "aucune borne"
        return said + (f" — {st.blocked}" if st.blocked else "")
