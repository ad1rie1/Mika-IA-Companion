"""Les demandes du banc du travail : ce qu'Adrien demande, ce qu'il veut vraiment, et le web que verront ses apps.

Chaque scénario porte :

- **la demande**, écrite comme Adrien écrit ;
- **sa fiche d'intention**, cachée à Mika : ce qu'il veut vraiment, ce qu'il répondrait aux questions probables, ce
  qui le décevrait. L'Adrien simulé et le juge la lisent, elle jamais ;
- **les sources figées** que ses apps trouveront sur le réseau (``api.http``, ``api.http_get``) : une réponse
  canonique par motif d'adresse, un 404 sinon. Ce qui bouge (un colis, un prix, un flux) bouge avec l'horloge
  virtuelle, depuis le début du scénario : deux mesures voient le même web, et rien ne sort de la machine.

``reserve`` : tenu à l'écart des réglages (six sur huit), pour voir qu'on améliore sa façon de travailler et pas
seulement les demandes qu'on regarde. Les noms de studios, de jeux et les articles des flux sont inventés.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
HOUR = 3_600_000_000
JSON = "application/json; charset=utf-8"
HTML = "text/html; charset=utf-8"
RSS = "application/rss+xml; charset=utf-8"
CSV = "text/csv; charset=utf-8"

Reply = tuple[int, str, str]
#: une réponse : (le motif reconnu, le début du scénario, maintenant — en µs, virtuels —, les en-têtes envoyés)
#: → (statut, type, corps)
Answer = Callable[[re.Match[str], int, int, Mapping[str, str]], Reply]


@dataclass(frozen=True, slots=True)
class Source:
    #: cherché dans l'adresse demandée (``re.search``) ; la première source qui répond l'emporte
    pattern: str
    #: ce que c'est, pour le juge
    what: str
    answer: Answer
    #: une adresse qui répond (le mode sec en bâtit son app)
    sample: str


@dataclass(frozen=True, slots=True)
class Item:
    """Un article : paru tant d'heures après le début du scénario (négatif : avant)."""

    hours: float
    title: str
    link: str
    text: str = ""


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    #: année, mois, jour, heure, minute (Paris) : le moment de la demande
    when: tuple[int, int, int, int, int]
    demand: str
    wants: str
    answers: tuple[str, ...]
    disappoints: tuple[str, ...]
    sources: tuple[Source, ...]
    reserve: bool = True
    #: les heures virtuelles qu'on laisse passer après la demande (``--heures`` les remplace)
    hours: int = 12
    #: les messages qu'Adrien lui écrit au plus après sa demande
    exchanges: int = 6

    def fiche(self) -> dict[str, Any]:
        return {"demande": self.demand, "veut": self.wants, "reponses": list(self.answers),
                "decevrait": list(self.disappoints),
                "sources": [{"motif": s.pattern, "quoi": s.what} for s in self.sources]}


# ── Outils des sources ──────────────────────────────────────────────────


def _local(us: int, zone: Any = PARIS) -> datetime:
    return datetime.fromtimestamp(us / 1_000_000, zone)


def _query(m: re.Match[str]) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(m.string).query).items()}


def _wave(seed: str, x: float) -> float:
    """Une variation déterministe autour de 0 (±1 environ) : la même série pour la même graine, à chaque mesure."""
    h = zlib.crc32(seed.encode())
    return 0.6 * math.sin(x / 3.1 + h % 7) + 0.4 * math.sin(x / 1.27 + h % 11)


def static(body: str, kind: str = JSON, status: int = 200) -> Answer:
    def answer(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
        return status, kind, body
    return answer


def published(items: Sequence[Item], start: int, now: int) -> list[Item]:
    """Ce qui est déjà paru, du plus récent au plus ancien."""
    return sorted((i for i in items if start + int(i.hours * HOUR) <= now), key=lambda i: -i.hours)


def rss(title: str, link: str, items: Sequence[Item]) -> Answer:
    """Un flux RSS 2.0 dont chaque article paraît à son heure."""
    def answer(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
        rows = "".join(
            f"<item><title>{escape(i.title)}</title><link>{escape(i.link)}</link><guid>{escape(i.link)}</guid>"
            f"<pubDate>{format_datetime(_local(start + int(i.hours * HOUR)))}</pubDate>"
            f"<description>{escape(i.text)}</description></item>" for i in published(items, start, now))
        return 200, RSS, (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
                          f"<title>{escape(title)}</title><link>{escape(link)}</link>"
                          f"<description>{escape(title)}</description><language>fr</language>{rows}"
                          f"</channel></rss>")
    return answer


def hn(items: Sequence[Item]) -> Answer:
    """La recherche de Hacker News (Algolia) : les mêmes articles, en JSON."""
    def answer(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
        hits = []
        for i in published(items, start, now):
            at = _local(start + int(i.hours * HOUR), UTC)
            hits.append({"objectID": str(zlib.crc32(i.link.encode())), "title": i.title, "url": i.link,
                         "author": "anon", "points": 20 + int(abs(_wave(i.link, 1.0)) * 300),
                         "num_comments": int(abs(_wave(i.link, 2.0)) * 120), "story_text": i.text,
                         "created_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "created_at_i": int(at.timestamp())})
        return 200, JSON, json.dumps({"hits": hits, "nbHits": len(hits), "page": 0, "hitsPerPage": 20},
                                     ensure_ascii=False)
    return answer


def reddit(sub: str, items: Sequence[Item]) -> Answer:
    def answer(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
        children = [{"kind": "t3", "data": {
            "title": i.title, "url": i.link, "selftext": i.text, "subreddit": sub,
            "permalink": f"/r/{sub}/comments/{zlib.crc32(i.link.encode()):x}/",
            "score": 5 + int(abs(_wave(i.link, 3.0)) * 400),
            "created_utc": float(int((start + int(i.hours * HOUR)) / 1_000_000))}}
            for i in published(items, start, now)]
        return 200, JSON, json.dumps({"kind": "Listing", "data": {"children": children, "after": None}},
                                     ensure_ascii=False)
    return answer


NOT_FOUND = "<!doctype html><html><head><title>404 Not Found</title></head><body><h1>Not Found</h1></body></html>"


# ── La bourse ───────────────────────────────────────────────────────────

BASES = {"AAPL": 231.4, "MSFT": 508.2, "NVDA": 181.6, "GOOGL": 246.0, "AMZN": 221.3, "TSLA": 438.0,
         "^FCHI": 8104.0, "^GSPC": 6630.0, "^IXIC": 22410.0, "AIR.PA": 171.8, "MC.PA": 612.0, "TTE.PA": 56.9,
         "BNP.PA": 71.2, "SAN.PA": 84.5, "OR.PA": 382.0, "BTC-EUR": 96200.0, "ETH-EUR": 3480.0,
         "BTC-USD": 111600.0, "ETH-USD": 4040.0, "BITCOIN": 96200.0, "ETHEREUM": 3480.0, "SOLANA": 168.0}


def price(symbol: str, hour: float) -> float:
    """Le cours d'un symbole à une heure donnée (heures depuis 1970) : déterministe, il bouge dans la journée."""
    s = symbol.upper()
    base = BASES.get(s, 20.0 + zlib.crc32(s.encode()) % 280)
    return round(base * (1 + 0.035 * _wave(s, hour / 24) + 0.004 * _wave(s + "h", hour)), 2)


def _currency(symbol: str) -> str:
    s = symbol.upper()
    return "EUR" if s.endswith((".PA", "-EUR")) or s == "^FCHI" else "USD"


def _bars(symbol: str, hours: Sequence[int]) -> dict[str, list[Any]]:
    closes = [price(symbol, h) for h in hours]
    opens = [price(symbol, h - 1) for h in hours]
    return {"open": opens, "close": closes,
            "high": [round(max(o, c) * 1.004, 2) for o, c in zip(opens, closes, strict=True)],
            "low": [round(min(o, c) * 0.996, 2) for o, c in zip(opens, closes, strict=True)],
            "volume": [int(1_000_000 * (1.5 + _wave(symbol + "v", h))) for h in hours]}


def yahoo_chart(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    symbol = unquote(m.group(1))
    q = _query(m)
    hourly = q.get("interval", "1d") in ("1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h")
    end = now // HOUR
    hours = [end - k for k in reversed(range(72))] if hourly else [end - 24 * k for k in reversed(range(90))]
    bars = _bars(symbol, hours)
    live = price(symbol, now / HOUR)
    meta = {"currency": _currency(symbol), "symbol": symbol, "exchangeName": "PAR" if symbol.endswith(".PA") else "NMS",
            "instrumentType": "INDEX" if symbol.startswith("^") else "EQUITY", "regularMarketPrice": live,
            "chartPreviousClose": bars["close"][-2], "previousClose": bars["close"][-2],
            "regularMarketTime": int(now / 1_000_000), "regularMarketDayHigh": round(live * 1.006, 2),
            "regularMarketDayLow": round(live * 0.993, 2), "gmtoffset": 3600, "timezone": "CET",
            "dataGranularity": "1h" if hourly else "1d"}
    result = {"meta": meta, "timestamp": [h * 3600 for h in hours],
              "indicators": {"quote": [bars], "adjclose": [{"adjclose": bars["close"]}]}}
    return 200, JSON, json.dumps({"chart": {"result": [result], "error": None}})


def stooq_history(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    symbol = _query(m).get("s", "").upper().removesuffix(".US")
    if not symbol:
        return 200, CSV, "No data"
    end = now // HOUR
    hours = [end - 24 * k for k in reversed(range(1, 91))]
    bars = _bars(symbol, hours)
    rows = [f"{_local(h * HOUR):%Y-%m-%d},{o},{hi},{lo},{c},{v}" for h, o, hi, lo, c, v in zip(
        hours, bars["open"], bars["high"], bars["low"], bars["close"], bars["volume"], strict=True)]
    return 200, CSV, "Date,Open,High,Low,Close,Volume\n" + "\n".join(rows) + "\n"


def stooq_quote(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    symbols = [s for s in _query(m).get("s", "").split("+") if s]
    lines = ["Symbol,Date,Time,Open,High,Low,Close,Volume"]
    for s in symbols:
        p = price(s.upper().removesuffix(".US"), now / HOUR)
        lines.append(f"{s.upper()},{_local(now):%Y-%m-%d},{_local(now):%H:%M:%S},{round(p * 0.997, 2)},"
                     f"{round(p * 1.004, 2)},{round(p * 0.992, 2)},{p},1250300")
    return 200, CSV, "\n".join(lines) + "\n"


def coingecko_price(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    q = _query(m)
    vs = [v for v in q.get("vs_currencies", "eur").split(",") if v]
    out = {c: {v: round(price(c, now / HOUR) * (1.0 if v == "eur" else 1.16), 2) for v in vs}
           for c in q.get("ids", "").split(",") if c.upper() in BASES}
    return 200, JSON, json.dumps(out)


def coingecko_chart(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    coin = m.group(1)
    if coin.upper() not in BASES:
        return 404, JSON, json.dumps({"error": "coin not found"})
    days = max(1, min(int(_query(m).get("days", "30") or 30), 365))
    end = now // HOUR
    hours = [end - k for k in reversed(range(days * 24))] if days <= 2 else [end - 24 * k for k in reversed(range(days))]
    return 200, JSON, json.dumps({"prices": [[h * 3_600_000, price(coin, h)] for h in hours],
                                  "total_volumes": [[h * 3_600_000, 2.1e10] for h in hours]})


# ── La météo ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Day:
    tmin: float
    tmax: float
    rain: float = 0.0  # mm sur la journée
    gusts: float = 22.0  # km/h
    code: int = 2  # code WMO


def _hour_temp(d: Day, h: int) -> float:
    frac = max(0.0, math.sin(math.pi * (h - 6) / 16)) if 6 <= h <= 22 else 0.0
    return round(d.tmin + (d.tmax - d.tmin) * frac, 1)


def open_meteo(profile: Mapping[int, Day], lat: float, lon: float) -> Answer:
    """L'API de prévision d'Open-Meteo : la journée ``k`` après le début du scénario suit ``profile[k]``. Elle rend
    toujours un large choix de variables (de quoi lire ce qu'on lui demande), à l'heure de Paris si on la demande."""
    def answer(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
        q = _query(m)
        zone = PARIS if q.get("timezone", "GMT") in ("auto", "Europe/Paris") else UTC
        past = max(0, min(int(q.get("past_days", "0") or 0), 10))
        ahead = max(1, min(int(q.get("forecast_days", "7") or 7), 16))
        day0, today = _local(start).date(), _local(now, zone).date()
        days = [today + timedelta(days=k) for k in range(-past, ahead)]
        rows = [profile.get((d - day0).days, Day(6, 14)) for d in days]
        moist, hourly = 0.24, {k: [] for k in ("time", "temperature_2m", "precipitation", "rain",
                                                "precipitation_probability", "relative_humidity_2m",
                                                "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm",
                                                "soil_moisture_3_to_9cm", "et0_fao_evapotranspiration",
                                                "weather_code", "wind_speed_10m", "cloud_cover")}
        for d, row in zip(days, rows, strict=True):
            for h in range(24):
                wet = row.rain / 6 if row.rain and 13 <= h <= 18 else 0.0
                moist = min(0.45, max(0.08, moist - 0.0015 + wet * 0.012))
                t = _hour_temp(row, h)
                hourly["time"].append(f"{d.isoformat()}T{h:02d}:00")
                hourly["temperature_2m"].append(t)
                hourly["precipitation"].append(round(wet, 1))
                hourly["rain"].append(round(wet, 1))
                hourly["precipitation_probability"].append(85 if row.rain else 5)
                hourly["relative_humidity_2m"].append(int(min(99, 92 - 3 * max(0.0, t - row.tmin) + (6 if wet else 0))))
                hourly["soil_moisture_0_to_1cm"].append(round(moist, 3))
                hourly["soil_moisture_1_to_3cm"].append(round(moist * 1.08, 3))
                hourly["soil_moisture_3_to_9cm"].append(round(moist * 1.15, 3))
                hourly["et0_fao_evapotranspiration"].append(round(max(0.0, (t - 4) * 0.012), 3))
                hourly["weather_code"].append(row.code)
                hourly["wind_speed_10m"].append(round(row.gusts * 0.55, 1))
                hourly["cloud_cover"].append(90 if row.rain else 35)
        daily = {"time": [d.isoformat() for d in days], "weather_code": [r.code for r in rows],
                 "weathercode": [r.code for r in rows], "temperature_2m_max": [r.tmax for r in rows],
                 "temperature_2m_min": [r.tmin for r in rows], "precipitation_sum": [r.rain for r in rows],
                 "rain_sum": [r.rain for r in rows], "precipitation_hours": [6.0 if r.rain else 0.0 for r in rows],
                 "precipitation_probability_max": [85 if r.rain else 5 for r in rows],
                 "et0_fao_evapotranspiration": [round(max(0.2, (r.tmax - 4) * 0.12), 2) for r in rows],
                 "wind_speed_10m_max": [round(r.gusts * 0.6, 1) for r in rows],
                 "wind_gusts_10m_max": [r.gusts for r in rows],
                 "sunshine_duration": [0.0 if r.rain else 21600.0 for r in rows],
                 "uv_index_max": [1.0 if r.rain else 2.5 for r in rows],
                 "sunrise": [f"{d.isoformat()}T08:{10 + k % 5:02d}" for k, d in enumerate(days)],
                 "sunset": [f"{d.isoformat()}T18:{20 - k % 5:02d}" for k, d in enumerate(days)]}
        local = _local(now, zone)
        i = min(len(hourly["time"]) - 1, max(0, past * 24 + local.hour))
        current = {"time": hourly["time"][i], "interval": 900, "temperature_2m": hourly["temperature_2m"][i],
                   "relative_humidity_2m": hourly["relative_humidity_2m"][i],
                   "precipitation": hourly["precipitation"][i], "rain": hourly["rain"][i],
                   "weather_code": hourly["weather_code"][i], "wind_speed_10m": hourly["wind_speed_10m"][i]}
        body = {"latitude": lat, "longitude": lon, "generationtime_ms": 0.41,
                "utc_offset_seconds": int(local.utcoffset().total_seconds()) if zone is PARIS else 0,
                "timezone": "Europe/Paris" if zone is PARIS else "GMT",
                "timezone_abbreviation": local.tzname() if zone is PARIS else "GMT", "elevation": 43.0,
                "current_units": {"temperature_2m": "°C", "precipitation": "mm", "relative_humidity_2m": "%",
                                  "wind_speed_10m": "km/h"},
                "current": current,
                "current_weather": {"time": current["time"], "temperature": current["temperature_2m"],
                                    "windspeed": current["wind_speed_10m"], "weathercode": current["weather_code"],
                                    "winddirection": 240, "is_day": 1 if 8 <= local.hour <= 18 else 0},
                "hourly_units": {"temperature_2m": "°C", "precipitation": "mm", "soil_moisture_0_to_1cm": "m³/m³",
                                 "et0_fao_evapotranspiration": "mm", "relative_humidity_2m": "%"},
                "hourly": hourly,
                "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm",
                                "et0_fao_evapotranspiration": "mm", "wind_gusts_10m_max": "km/h"},
                "daily": daily}
        return 200, JSON, json.dumps(body)
    return answer


GEOCODING = json.dumps({"results": [
    {"id": 2992292, "name": "Montaigu", "latitude": 49.5418, "longitude": 3.8276, "elevation": 150.0,
     "feature_code": "PPL", "country_code": "FR", "timezone": "Europe/Paris", "population": 520,
     "country": "France", "admin1": "Hauts-de-France", "admin2": "Aisne", "postcodes": ["02820"]},
    {"id": 2992287, "name": "Montaigu-Vendée", "latitude": 46.9733, "longitude": -1.3097, "elevation": 43.0,
     "feature_code": "PPLA3", "country_code": "FR", "timezone": "Europe/Paris", "population": 20590,
     "country": "France", "admin1": "Pays de la Loire", "admin2": "Vendée", "postcodes": ["85600"]}],
    "generationtime_ms": 0.6}, ensure_ascii=False)
NOMINATIM = json.dumps([
    {"place_id": 1, "lat": "49.5418", "lon": "3.8276", "display_name": "Montaigu, Laon, Aisne, Hauts-de-France, France",
     "type": "village"},
    {"place_id": 2, "lat": "46.9733", "lon": "-1.3097",
     "display_name": "Montaigu-Vendée, La Roche-sur-Yon, Vendée, Pays de la Loire, France", "type": "town"}],
    ensure_ascii=False)


# ── Le colis ────────────────────────────────────────────────────────────

PARCEL = "6A23456789012"
#: (heures après la demande, code, libellé) : il bouge pendant le scénario, et finit à retirer au bureau de poste
TRACK = ((-30.0, "DR1", "Votre colis est pris en charge par le commerçant (MondoGames), en attente de dépôt."),
         (-21.0, "PC1", "Votre colis est pris en charge par La Poste."),
         (-7.0, "ET1", "Votre colis est en transit sur nos plateformes logistiques (Nantes)."),
         (2.5, "ET2", "Votre colis est arrivé sur son site de distribution (Montaigu-Vendée)."),
         (4.0, "MD2", "Votre colis est en cours de livraison."),
         (7.2, "AG1", "Votre colis n'a pas pu être livré : vous étiez absent. Il sera disponible dans votre bureau "
                      "de poste de Montaigu-Vendée (12 rue de la Gare) à partir de demain 14h, sur présentation de "
                      "l'avis de passage et d'une pièce d'identité. Il y restera 15 jours."))


def _track(start: int, now: int) -> list[tuple[datetime, str, str]]:
    return [(_local(start + int(h * HOUR)), code, label) for h, code, label in TRACK if start + int(h * HOUR) <= now]


def laposte_api(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    if not any(k.lower() == "x-okapi-key" and v for k, v in headers.items()):
        return 401, JSON, json.dumps({"code": "UNAUTHORIZED", "message": "Missing or invalid X-Okapi-Key header"})
    if m.group(1) != PARCEL:
        return 404, JSON, json.dumps({"returnCode": 104, "returnMessage": "Numéro de suivi introuvable"})
    events = _track(start, now)
    return 200, JSON, json.dumps({"lang": "fr_FR", "scope": "open", "returnCode": 200, "shipment": {
        "idShip": PARCEL, "holder": 4, "product": "Colissimo", "isFinal": False, "url":
        f"https://www.laposte.fr/outils/suivre-vos-envois?code={PARCEL}",
        "event": [{"code": c, "label": lab, "date": at.isoformat()} for at, c, lab in reversed(events)],
        "timeline": [{"id": k + 1, "shortLabel": lab.split(".")[0], "status": True, "type": 1}
                     for k, (_, _, lab) in enumerate(events)]}}, ensure_ascii=False)


def laposte_page(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    code = _query(m).get("code") or _query(m).get("parcelnumber") or _query(m).get("colispart") or ""
    if code.upper() != PARCEL:
        return 200, HTML, ("<!doctype html><html><body><main><h1>Suivre un envoi</h1><p class='error'>Nous ne "
                           "trouvons pas d'envoi avec ce numéro.</p></main></body></html>")
    rows = "".join(f"<li class='step'><time datetime='{at.isoformat()}'>{at:%d/%m/%Y %H:%M}</time>"
                   f"<p class='label'>{escape(lab)}</p></li>" for at, _, lab in reversed(_track(start, now)))
    return 200, HTML, (f"<!doctype html><html lang='fr'><head><title>Suivi {PARCEL} | La Poste</title></head><body>"
                       f"<main><h1>Colissimo n° {PARCEL}</h1><ol class='tracking-history'>{rows}</ol></main>"
                       "</body></html>")


# ── Les recettes ────────────────────────────────────────────────────────

#: (id, nom, catégorie, cuisine, ingrédients, consignes) — le Marengo porte des champignons
MEALS = (
    ("52934", "Chicken Basquaise", "Chicken", "French",
     (("chicken thighs", "6"), ("red pepper", "2"), ("onion", "1"), ("chorizo", "100g"), ("tomatoes", "400g"),
      ("rice", "300g"), ("garlic", "2 cloves"), ("olive oil", "2 tbs")),
     "Brown the chicken, add peppers, onion and chorizo, then tomatoes; simmer 40 minutes. Serve with rice."),
    ("52937", "Chicken Marengo", "Chicken", "French",
     (("chicken legs", "4"), ("mushrooms", "300g"), ("tomato puree", "1 tbs"), ("white wine", "200ml"),
      ("chicken stock", "200ml"), ("olive oil", "2 tbs"), ("parsley", "to serve")),
     "Brown the chicken, add mushrooms, wine and stock; simmer 35 minutes."),
    ("52772", "Teriyaki Chicken Casserole", "Chicken", "Japanese",
     (("soy sauce", "3/4 cup"), ("brown sugar", "1/4 cup"), ("chicken breasts", "2"), ("stir-fry vegetables", "350g"),
      ("brown rice", "3 cups"), ("cornstarch", "4 tbs")),
     "Make the sauce, pour over chicken and vegetables, bake 35 minutes, serve on rice."),
    ("52771", "Spicy Arrabiata Penne", "Vegetarian", "Italian",
     (("penne rigate", "300g"), ("chopped tomatoes", "400g"), ("garlic", "3 cloves"), ("red chilli flakes", "1/2 tsp"),
      ("olive oil", "1/4 cup"), ("parmigiano-reggiano", "to serve")),
     "Cook the pasta; fry garlic and chilli, add tomatoes, simmer 10 minutes, toss with pasta."),
    ("52807", "Baingan Bharta", "Vegetarian", "Indian",
     (("aubergine", "2"), ("onion", "1"), ("tomatoes", "2"), ("garlic", "3 cloves"), ("cumin seeds", "1 tsp"),
      ("naan", "4")),
     "Roast the aubergines, mash, cook with onion, tomato and spices; serve with naan."),
    ("52819", "Cajun spiced fish tacos", "Seafood", "Mexican",
     (("white fish fillets", "400g"), ("cajun seasoning", "2 tbs"), ("tortillas", "8"), ("red cabbage", "1/4"),
      ("lime", "2"), ("sour cream", "100ml")),
     "Season and pan-fry the fish, flake into warm tortillas with cabbage, lime and sour cream."),
    ("52885", "Bubble & Squeak", "Pork", "British",
     (("potatoes", "600g"), ("cabbage", "1/2"), ("bacon", "4 slices"), ("butter", "30g"), ("eggs", "2")),
     "Fry bacon, add mashed potato and cabbage, press and fry until crisp; top with a fried egg."),
    ("53050", "Lentil and Sausage Stew", "Pork", "French",
     (("green lentils", "300g"), ("toulouse sausages", "4"), ("carrots", "2"), ("onion", "1"), ("thyme", "2 sprigs"),
      ("chicken stock", "800ml")),
     "Brown the sausages, add vegetables, lentils and stock; simmer 35 minutes."),
)


def _meal(row: tuple[Any, ...], full: bool) -> dict[str, Any]:
    mid, name, cat, area, ingredients, instructions = row
    out: dict[str, Any] = {"idMeal": mid, "strMeal": name,
                           "strMealThumb": f"https://www.themealdb.com/images/media/meals/{mid}.jpg"}
    if full:
        out |= {"strCategory": cat, "strArea": area, "strInstructions": instructions}
        for k in range(20):
            ing, mes = ingredients[k] if k < len(ingredients) else ("", "")
            out[f"strIngredient{k + 1}"], out[f"strMeasure{k + 1}"] = ing, mes
    return out


def mealdb(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    kind, q = m.group(1), _query(m)
    rows: list[dict[str, Any]] | None
    if kind == "search":
        wanted = q.get("s", "").lower()
        rows = [_meal(r, True) for r in MEALS if wanted in r[1].lower()]
    elif kind == "filter":
        ing, cat = q.get("i", "").lower().replace("_", " "), q.get("c", "").lower()
        rows = [_meal(r, False) for r in MEALS if (ing and any(ing in i for i, _ in r[4])) or (cat and r[2].lower() == cat)]
    elif kind == "lookup":
        rows = [_meal(r, True) for r in MEALS if r[0] == q.get("i", "")]
    elif kind == "random":
        rows = [_meal(MEALS[int(now // HOUR) % len(MEALS)], True)]
    else:  # categories
        return 200, JSON, json.dumps({"categories": [{"strCategory": c} for c in
                                                     ("Chicken", "Pork", "Seafood", "Vegetarian")]})
    return 200, JSON, json.dumps({"meals": rows or None})


# ── Les jeux ────────────────────────────────────────────────────────────

#: (appid, nom, sorte, genres, sortie en jours après le début, prix en €) — un DLC, un jeu mobile, un de la semaine suivante
GAMES = (
    (3104410, "Iron Crown: Dominion", "game", ("Stratégie",), 2, 49.99),
    (2987720, "Ashfall Chronicles", "game", ("RPG", "Aventure"), 3, 59.99),
    (3220150, "Northern Legions", "game", ("Stratégie", "Simulation"), 4, 29.99),
    (3301870, "Hollow Saints", "game", ("RPG", "Action"), 5, 24.99),
    (3150020, "Ashfall Chronicles – Les Tisseurs", "dlc", ("RPG",), 3, 9.99),
    (3010440, "Mecha Tycoon 3", "game", ("Simulation", "Gestion"), 1, 19.99),
    (3355810, "Pixel Kart Rush", "game", ("Course", "Free to Play"), 2, 0.0),
    (2899110, "Dune Shepherds", "game", ("Stratégie", "4X"), 10, 39.99),
)
_MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def _release(start: int, days: int) -> date:
    return _local(start).date() + timedelta(days=days)


def steam_featured(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    def item(g: tuple[Any, ...]) -> dict[str, Any]:
        return {"id": g[0], "type": 0, "name": g[1], "discounted": False, "discount_percent": 0,
                "original_price": None, "final_price": int(round(g[5] * 100)), "currency": "EUR",
                "large_capsule_image": f"https://cdn.akamai.steamstatic.com/steam/apps/{g[0]}/capsule_467x181.jpg",
                "windows_available": True, "mac_available": False, "linux_available": g[0] % 2 == 0}
    today = _local(now).date()
    soon = [item(g) for g in GAMES if _release(start, g[4]) > today]
    new = [item(g) for g in GAMES if _release(start, g[4]) <= today]
    return 200, JSON, json.dumps({"coming_soon": {"id": "cat_comingsoon", "name": "Bientôt disponibles",
                                                  "items": soon},
                                  "new_releases": {"id": "cat_newreleases", "name": "Nouveautés", "items": new}},
                                 ensure_ascii=False)


def steam_details(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
    out: dict[str, Any] = {}
    for raw in _query(m).get("appids", "").split(","):
        g = next((g for g in GAMES if str(g[0]) == raw.strip()), None)
        if g is None:
            out[raw] = {"success": False}
            continue
        day = _release(start, g[4])
        out[raw] = {"success": True, "data": {
            "type": g[2], "name": g[1], "steam_appid": g[0], "is_free": g[5] == 0,
            "short_description": f"{g[1]} — {', '.join(g[3])}.",
            "genres": [{"id": str(k), "description": d} for k, d in enumerate(g[3])],
            "release_date": {"coming_soon": day > _local(now).date(),
                             "date": f"{day.day} {_MONTHS[day.month - 1]} {day.year}"},
            "platforms": {"windows": True, "mac": False, "linux": g[0] % 2 == 0},
            **({} if g[5] == 0 else {"price_overview": {
                "currency": "EUR", "initial": int(round(g[5] * 100)), "final": int(round(g[5] * 100)),
                "discount_percent": 0, "final_formatted": f"{g[5]:.2f}€".replace(".", ",")}})}}
    return 200, JSON, json.dumps(out, ensure_ascii=False)


# ── Les prix ────────────────────────────────────────────────────────────

#: (titre, boutique, prix, état, d'heures, à heures) — la baisse sous 550 € vient vers 7 h le lendemain ; une Ti et une
#: reconditionnée tentent de tromper
OFFERS = (
    ("MSI GeForce RTX 5070 Ventus 2X OC 12G", "LDLC", 589.95, "neuf", -99, 99),
    ("ASUS Prime GeForce RTX 5070 OC 12 Go", "Materiel.net", 604.90, "neuf", -99, 99),
    ("Gigabyte GeForce RTX 5070 Windforce OC SFF 12G", "Amazon", 579.99, "neuf", -99, 4),
    ("Gigabyte GeForce RTX 5070 Windforce OC SFF 12G", "Amazon", 566.50, "neuf", 4, 11),
    ("Gigabyte GeForce RTX 5070 Windforce OC SFF 12G", "Amazon", 539.90, "neuf", 11, 99),
    ("PNY GeForce RTX 5070 Ti OC 16 Go", "Rue du Commerce", 749.99, "neuf", -99, 99),
    ("MSI GeForce RTX 5070 Gaming Trio 12G (reconditionné)", "Back Market", 489.00, "reconditionné", -99, 99),
)


def _offers(start: int, now: int) -> list[tuple[str, str, float, str]]:
    h = (now - start) / HOUR
    return sorted(((t, s, p, e) for t, s, p, e, a, b in OFFERS if a <= h < b), key=lambda o: o[2])


def shop_page(site: str) -> Answer:
    def answer(m: re.Match[str], start: int, now: int, headers: Mapping[str, str]) -> Reply:
        query = (_query(m).get("q") or _query(m).get("search") or _query(m).get("query") or "").lower()
        rows = [o for o in _offers(start, now) if not query or all(w in o[0].lower() for w in query.split()[:2])]
        items = "".join(
            f"<li class='offer' data-price='{p:.2f}'><span class='title'>{escape(t)}</span>"
            f"<span class='shop'>{escape(s)}</span><span class='state'>{escape(e)}</span>"
            f"<span class='price'>{f'{p:.2f}'.replace('.', ',')} €</span></li>" for t, s, p, e in rows)
        return 200, HTML, (f"<!doctype html><html lang='fr'><head><title>{escape(query)} — {site}</title></head>"
                           f"<body><main><h1>Comparer les prix : {escape(query)}</h1><ul class='offers'>{items}</ul>"
                           f"<p class='updated'>Mis à jour le {_local(now):%d/%m/%Y à %H:%M}</p></main></body></html>")
    return answer


# ── Les articles des flux ───────────────────────────────────────────────

MARKET_NEWS = (
    Item(-20, "Le CAC 40 termine en légère baisse, plombé par le luxe", "https://news.exemple.fr/marches/cac-luxe",
         "Le luxe recule de 2 % après des ventes en Asie décevantes ; les banques limitent la casse."),
    Item(-14, "Les marchés américains attendent la décision de la Fed mercredi",
         "https://news.exemple.fr/marches/fed-attente", "Les investisseurs anticipent une baisse d'un quart de point."),
    Item(-3, "Airbus relève ses objectifs de livraisons pour l'année", "https://news.exemple.fr/entreprises/airbus",
         "Le titre gagne 3 % en préouverture."),
    Item(1.5, "Nvidia : des résultats records portés par les centres de données",
         "https://news.exemple.fr/tech/nvidia-resultats", "Le chiffre d'affaires dépasse les attentes de 8 %."),
    Item(4, "Le bitcoin repasse au-dessus de 95 000 euros", "https://news.exemple.fr/crypto/bitcoin-95k",
         "Les flux vers les ETF reprennent."),
    Item(6.5, "TotalEnergies chute après la baisse du pétrole", "https://news.exemple.fr/entreprises/total-petrole",
         "Le Brent perd 4 % sur la journée."),
    Item(9, "Clôture : le CAC 40 rebondit de 0,9 % grâce à l'aéronautique", "https://news.exemple.fr/marches/cloture",
         "Airbus et Safran mènent la hausse."),
)

AI_GAMES_NEWS = (
    Item(-30, "Le syndicat des comédiens de doublage signe un accord-cadre sur les voix générées par IA",
         "https://news.exemple.fr/jv/doublage-accord-ia",
         "Consentement, rémunération et durée d'usage : ce que l'accord change pour les studios."),
    Item(-26, "Top 10 des jeux IA à essayer ce week-end", "https://blog.exemple.com/top-10-jeux-ia",
         "Notre sélection subjective."),
    Item(-22, "La boutique Nebula impose d'indiquer l'usage d'IA générative sur chaque fiche de jeu",
         "https://news.exemple.fr/jv/nebula-regles-ia", "Près de 9 000 jeux déclarent déjà en utiliser."),
    Item(-9, "NFT et IA : la révolution du play-to-earn est enfin là (sponsorisé)",
         "https://promo.exemple.io/nft-ia", "Contenu sponsorisé."),
    Item(-5, "Studio Brume licencie 30 personnes et invoque des outils d'IA pour les décors",
         "https://news.exemple.fr/jv/studio-brume-licenciements",
         "Le syndicat du jeu vidéo dénonce un prétexte ; la direction parle de réorganisation."),
    Item(2, "Kestrel Games montre un prototype de PNJ conversationnels qui tournent en local",
         "https://news.exemple.fr/jv/kestrel-pnj-ia", "Un petit modèle sur la carte graphique, sans serveur."),
    Item(6, "Comment j'ai généré 500 assets en une nuit (et pourquoi je ne le referai pas)",
         "https://blog.exemple.com/assets-nuit", "Retour d'expérience d'un développeur indépendant."),
    Item(15, "Le CNC ouvre un fonds pour les jeux qui déclarent leur usage de l'IA",
         "https://news.exemple.fr/jv/cnc-fonds-ia", "Une aide de 2 millions d'euros, conditionnée à la transparence."),
    Item(19, "Kestrel Games : la démo des PNJ IA en accès anticipé la semaine prochaine",
         "https://news.exemple.fr/jv/kestrel-demo", "Suite de l'annonce d'hier."),
    Item(21, "Les 5 meilleurs memes IA de la semaine", "https://blog.exemple.com/memes-ia", "On rit un peu."),
)

KORBEN = (
    Item(-18, "Un outil libre pour chiffrer vos sauvegardes sans prise de tête", "https://korben.info/chiffrer-sauvegardes.html",
         "Présentation d'un petit utilitaire en ligne de commande, avec ses limites."),
    Item(-12, "Bon plan : -40 % sur un SSD 2 To", "https://korben.info/bon-plan-ssd.html", "Offre limitée."),
    Item(-6, "Linux : le noyau 7.3 apporte un ordonnanceur pour les processeurs hybrides",
         "https://korben.info/linux-7-3.html", "Ce qui change pour les portables récents."),
    Item(-2, "Faille critique dans un routeur grand public : mettez à jour", "https://korben.info/faille-routeur.html",
         "Le correctif est disponible depuis hier soir."),
    Item(3, "Un émulateur de consoles rétro dans le navigateur", "https://korben.info/emulateur-navigateur.html",
         "WebAssembly et un peu de magie."),
    Item(8, "Bon plan : un casque sans fil à 39 €", "https://korben.info/bon-plan-casque.html", "Offre limitée."),
    Item(13, "Pourquoi votre box internet écoute plus qu'elle ne devrait", "https://korben.info/box-ecoute.html",
         "Analyse des requêtes sortantes d'une box opérateur."),
    Item(16.5, "Un petit modèle d'IA qui tourne sur un Raspberry Pi 5", "https://korben.info/ia-raspberry.html",
         "Installation pas à pas et premiers essais."),
    Item(19, "Bon plan : abonnement VPN à 1,99 €/mois", "https://korben.info/bon-plan-vpn.html", "Offre limitée."),
    Item(22, "Le gouvernement veut rendre obligatoire la double authentification des comptes publics",
         "https://korben.info/double-auth.html", "Ce que prévoit le décret."),
)

GAMES_NEWS = (
    Item(-28, "Iron Crown: Dominion sortira bien le 27 octobre, la configuration requise dévoilée",
         "https://www.jeuxvideo.com/news/iron-crown-config.htm", "Un STR historique ambitieux."),
    Item(-20, "Pixel Kart Rush débarque sur mobile et PC en free-to-play", "https://www.jeuxvideo.com/news/pixel-kart.htm",
         "Le jeu de course arrive mardi."),
    Item(-15, "Ashfall Chronicles : le RPG sort jeudi, le DLC Les Tisseurs le même jour",
         "https://www.jeuxvideo.com/news/ashfall-sortie.htm", "Un RPG à la Baldur's Gate, en tour par tour."),
    Item(-6, "Test de Northern Legions : la stratégie nordique qui ne pardonne rien",
         "https://www.jeuxvideo.com/test/northern-legions.htm", "Notre verdict : 16/20."),
    Item(-3, "Hollow Saints repoussé ? Le studio dément", "https://www.jeuxvideo.com/news/hollow-saints.htm",
         "La sortie est maintenue au 30 octobre."),
    Item(5, "Dune Shepherds, le 4X du désert, daté au 4 novembre", "https://www.jeuxvideo.com/news/dune-shepherds.htm",
         "Précommandes ouvertes."),
    Item(12, "Les sorties jeux vidéo de la semaine", "https://www.jeuxvideo.com/dossier/sorties-semaine.htm",
         "Iron Crown, Ashfall Chronicles, Northern Legions, Hollow Saints, Mecha Tycoon 3…"),
)


def gnews(items: Sequence[Item]) -> Source:
    return Source(r"news\.google\.com/rss", "Google Actualités en RSS (recherche ou rubrique)",
                  rss("Google Actualités", "https://news.google.com", items),
                  "https://news.google.com/rss/search?q=actualites&hl=fr&gl=FR&ceid=FR:fr")


# ── Les scénarios ───────────────────────────────────────────────────────

JARDIN_METEO = {-5: Day(7, 17), -4: Day(8, 18), -3: Day(6, 17), -2: Day(7, 18), -1: Day(6, 16),
                0: Day(7, 17, code=1), 1: Day(5, 16, code=1), 2: Day(-1.5, 11, gusts=15, code=0),
                3: Day(6, 12, rain=12.5, gusts=48, code=63), 4: Day(7, 13, rain=6.0, gusts=35, code=61),
                5: Day(4, 14), 6: Day(3, 13, code=1), 7: Day(5, 14)}

SCENARIOS = [
    Scenario(
        "trading", (2026, 10, 27, 9, 42),
        "peux-tu créer un projet pour faire du trading par ia ? mais pour le moment fait semblant d'acheter/vendre",
        "Un bac à sable de trading où c'est l'IA qui décide : un portefeuille fictif (10 000 €), des achats et des "
        "ventes simulés, décidés en lisant les cours ET l'actualité, chaque décision avec sa raison. Il veut voir le "
        "portefeuille, l'historique des ordres avec leurs raisons et la performance comparée au CAC 40. Pas de vrai "
        "argent. L'intérêt, pour lui, c'est que l'IA réfléchisse : une app à règles fixes (moyennes mobiles) ne "
        "l'intéresse pas.",
        ("le budget : « 10 000 € fictifs »", "les marchés : « des actions françaises et us, un peu de crypto pourquoi pas »",
         "le rythme : « une décision par jour ca suffit, pas besoin de temps réel »",
         "ce qu'il veut voir : « je veux voir pourquoi elle a acheté ou vendu, et si on bat le cac »",
         "les nouvelles : « un point le vendredi soir, sinon me spam pas »",
         "les sources : « yahoo finance c'est bien je crois, et les news google »"),
        ("une app à règles fixes, sans IA dans les décisions", "des décisions sans raison lisible",
         "des stratégies qu'il n'a pas demandées, choisies sans lui demander", "rien à voir après une journée"),
        (Source(r"query[12]\.finance\.yahoo\.com/v8/finance/chart/([^/?#]+)",
                "Yahoo Finance, l'historique d'un symbole (journalier ou horaire)", yahoo_chart,
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EFCHI?range=3mo&interval=1d"),
         Source(r"query[12]\.finance\.yahoo\.com/v7/finance/quote", "Yahoo Finance, cotations : refusé sans jeton",
                static(json.dumps({"finance": {"result": None, "error": {"code": "Unauthorized",
                                                                       "description": "Invalid Crumb"}}}),
                       status=401), "https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL"),
         Source(r"stooq\.(?:com|pl)/q/d/l/", "Stooq, l'historique journalier en CSV", stooq_history,
                "https://stooq.com/q/d/l/?s=aapl.us&i=d"),
         Source(r"stooq\.(?:com|pl)/q/l/", "Stooq, la cotation du moment en CSV", stooq_quote,
                "https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv"),
         Source(r"api\.coingecko\.com/api/v3/simple/price", "CoinGecko, le prix des cryptos", coingecko_price,
                "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=eur"),
         Source(r"api\.coingecko\.com/api/v3/coins/([a-z0-9-]+)/market_chart", "CoinGecko, l'historique d'une crypto",
                coingecko_chart, "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=eur&days=30"),
         gnews(MARKET_NEWS)),
        reserve=False, hours=12),
    Scenario(
        "meteo-jardin", (2026, 10, 28, 8, 15),
        "tu pourrais me faire un truc pour savoir quand il faut arroser au jardin ? j'ai des salades et des poireaux, "
        "et je viens de planter une haie",
        "Un conseil simple chaque matin vers 8 h dans le chat : arroser ce soir ou pas, et pourquoi (pluie des "
        "derniers jours, pluie prévue, chaleur). Une alerte la veille s'il gèle (pour couvrir les salades) ou en cas "
        "de grosse pluie ou de vent fort (la haie vient d'être plantée). Une vue de la semaine à venir. Il habite "
        "Montaigu en Vendée (85), pas celui de l'Aisne. Il ne veut pas un bulletin météo brut.",
        ("l'heure : « le matin vers 8h c'est bien »", "le lieu : « montaigu en vendée, 85 »",
         "le potager : « en pleine terre, pas de récupérateur d'eau »",
         "la haie : « des photinias, plantés il y a 2 semaines »",
         "les alertes : « oui pour le gel surtout, et si il y a une tempête »"),
        ("un bulletin météo brut au lieu d'un conseil", "la météo d'un autre Montaigu",
         "pas d'alerte avant la nuit de gel", "un conseil d'arroser la veille d'une grosse pluie"),
        (Source(r"api\.open-meteo\.com/v1/forecast", "Open-Meteo, la prévision (journalière, horaire, sol)",
                open_meteo(JARDIN_METEO, 46.9733, -1.3097),
                "https://api.open-meteo.com/v1/forecast?latitude=46.97&longitude=-1.31&daily=precipitation_sum,"
                "temperature_2m_min&past_days=3&timezone=Europe/Paris"),
         Source(r"geocoding-api\.open-meteo\.com/v1/search", "Open-Meteo, chercher une ville (deux Montaigu)",
                static(GEOCODING), "https://geocoding-api.open-meteo.com/v1/search?name=Montaigu&count=5&language=fr"),
         Source(r"nominatim\.openstreetmap\.org/search", "OpenStreetMap, chercher une ville (deux Montaigu)",
                static(NOMINATIM), "https://nominatim.openstreetmap.org/search?q=Montaigu&format=json")),
        reserve=False, hours=26),
    Scenario(
        "veille", (2026, 10, 29, 18, 20),
        "tu peux me faire une veille sur l'ia dans le jeu video ? genre les news importantes, pas tout le blabla",
        "Un point chaque soir vers 19 h dans le chat : 3 à 5 nouvelles qui comptent vraiment sur l'IA dans le jeu "
        "vidéo (droits des comédiens, règles des boutiques, licenciements, vraies avancées techniques), chacune en "
        "une phrase avec son lien, en français. Sans doublon d'un jour à l'autre, sans le contenu sponsorisé, les "
        "tops et les memes, sans crypto ni NFT. Les jours sans rien d'important, un mot suffit.",
        ("le rythme : « un point le soir ca me va »", "la langue : « en francais si possible, l'anglais ca passe »",
         "le tri : « ce qui change vraiment quelque chose pour les devs ou les joueurs »",
         "à exclure : « les trucs nft crypto je veux pas »",
         "les sources : « google news et hacker news c'est bien, reddit gamedev aussi »"),
        ("une liste brute de liens sans tri", "les mêmes nouvelles deux jours de suite",
         "le contenu sponsorisé ou les tops", "devoir aller voir une app pour lire la veille"),
        (gnews(AI_GAMES_NEWS),
         Source(r"hn\.algolia\.com/api/v1/search", "Hacker News (Algolia), la recherche", hn(AI_GAMES_NEWS),
                "https://hn.algolia.com/api/v1/search_by_date?query=ai%20games&tags=story"),
         Source(r"hnrss\.org/", "Hacker News en RSS (hnrss)", rss("Hacker News", "https://news.ycombinator.com",
                                                                 AI_GAMES_NEWS), "https://hnrss.org/newest?q=AI+games"),
         Source(r"(?:www\.|old\.)?reddit\.com/r/(\w+)/(?:new|hot|top)?\.?json", "Reddit, un sous-forum en JSON",
                reddit("gamedev", AI_GAMES_NEWS), "https://www.reddit.com/r/gamedev/new.json")),
        hours=26),
    Scenario(
        "colis", (2026, 10, 28, 10, 5),
        "j'attend un colis colissimo, numero 6A23456789012, tu peux me dire quand il bouge ?",
        "Être prévenu au bon moment, pas à chaque relevé : quand le colis part en livraison, et surtout s'il faut "
        "aller le chercher (avis de passage : où, à partir de quand, avec quoi). C'est une manette commandée chez "
        "MondoGames. Il n'a pas de clé d'API La Poste et n'en veut pas ; la page de suivi publique suffit.",
        ("le numéro : « 6A23456789012 »", "le transporteur : « colissimo »",
         "une clé d'api : « j'en ai pas, la page de suivi de la poste suffit non ? »",
         "quand prévenir : « juste quand il est en livraison ou si faut aller le chercher »",
         "la forme : « pas besoin d'une app de fou, juste me prevenir »"),
        ("pas prévenu qu'il faut aller chercher le colis", "un message à chaque relevé sans changement",
         "un statut inventé", "une app qui attend une clé qu'il n'a pas"),
        (Source(r"api\.laposte\.fr/suivi/v2/idships/(\w+)", "L'API Suivi de La Poste : 401 sans clé X-Okapi-Key",
                laposte_api, f"https://api.laposte.fr/suivi/v2/idships/{PARCEL}?lang=fr_FR"),
         Source(r"laposte\.fr/outils/(?:suivre-vos-envois|track-a-parcel)", "La page de suivi publique de La Poste",
                laposte_page, f"https://www.laposte.fr/outils/suivre-vos-envois?code={PARCEL}"),
         Source(r"colissimo\.fr/", "La page de suivi de Colissimo (la même)", laposte_page,
                f"https://www.colissimo.fr/portail_colissimo/suivreResultat.do?parcelnumber={PARCEL}")),
        hours=12),
    Scenario(
        "menus", (2026, 10, 24, 11, 0),
        "tu pourrais me faire les menus de la semaine ? on est 2, pas trop cher, et je deteste les champignons",
        "Les dîners du lundi au vendredi pour deux (le midi ils mangent au travail), simples (30 min max en "
        "semaine), budget d'environ 60 € la semaine, sans champignons ; il aime les plats en sauce et le poulet. Une "
        "liste de courses rangée par rayon, avec les quantités. Les menus de cette semaine tout de suite, puis chaque "
        "dimanche matin, sans les mêmes plats d'une semaine à l'autre.",
        ("le midi : « non juste le soir, le midi on mange au boulot »", "le budget : « dans les 60 balles la semaine »",
         "les goûts : « on mange de tout sauf les champignons, j'adore les trucs en sauce et le poulet »",
         "le temps : « en semaine 30 min max »", "quand : « le dimanche matin c'est parfait pour les recevoir »",
         "le nombre : « on est 2, moi et ma copine »"),
        ("un plat aux champignons", "des recettes longues ou compliquées en semaine", "pas de liste de courses",
         "des menus en anglais copiés d'un site"),
        (Source(r"themealdb\.com/api/json/v1/\w+/(search|filter|lookup|random|categories)\.php",
                "TheMealDB, des recettes (en anglais)", mealdb,
                "https://www.themealdb.com/api/json/v1/1/filter.php?i=chicken"),),
        hours=26),
    Scenario(
        "resume-flux", (2026, 10, 26, 14, 0),
        "chaque matin tu pourrais me faire un resume du flux de korben ? https://korben.info/feed",
        "Chaque matin vers 8 h, dans le chat, un résumé court des articles parus depuis la veille : 5 ou 6 points, "
        "une phrase chacun qui dit de quoi ça parle vraiment (pas le titre recopié), avec le lien. Sans les « bons "
        "plans » (des pubs). S'il n'y a rien, un mot suffit.",
        ("l'heure : « vers 8h quand je bois mon café »", "les bons plans : « non, c'est de la pub »",
         "la longueur : « court, je veux pas lire un roman »", "le format : « une phrase par article avec le lien »"),
        ("le résumé rangé dans une app qu'il doit ouvrir", "les titres recopiés sans résumé", "les bons plans inclus",
         "des articles déjà résumés la veille"),
        (Source(r"korben\.info/feed", "Le flux RSS de Korben", rss("Korben", "https://korben.info", KORBEN),
                "https://korben.info/feed"),),
        hours=26),
    Scenario(
        "sorties-jeux", (2026, 10, 25, 17, 30),
        "tu peux me faire un truc qui me dit les sorties jeux de la semaine ? surtout strategie et rpg",
        "Chaque lundi matin, la liste des jeux PC de stratégie et de RPG qui sortent dans la semaine, avec le jour "
        "et le prix, et un mot sur ceux qui ressemblent à ce qu'il aime (Total War, Baldur's Gate 3). Sans les jeux "
        "mobiles ni les DLC, sans ce qui sort la semaine d'après.",
        ("la plateforme : « pc, steam »", "les goûts : « total war, baldur's gate 3, les 4x »",
         "les dlc : « non, que les vrais jeux »", "quand : « le lundi matin c'est bien »",
         "le prix : « oui si tu l'as »"),
        ("des DLC ou des jeux mobiles dans la liste", "un jeu de la semaine suivante présenté comme de cette semaine",
         "pas de date de sortie", "une liste sans lien avec ses goûts"),
        (Source(r"store\.steampowered\.com/api/featuredcategories", "Steam, les nouveautés et les sorties prochaines",
                steam_featured, "https://store.steampowered.com/api/featuredcategories?cc=fr&l=french"),
         Source(r"store\.steampowered\.com/api/appdetails", "Steam, la fiche d'un jeu (genres, date, prix)",
                steam_details, "https://store.steampowered.com/api/appdetails?appids=3104410&cc=fr&l=french"),
         Source(r"jeuxvideo\.com/rss/", "jeuxvideo.com en RSS", rss("jeuxvideo.com", "https://www.jeuxvideo.com",
                                                                   GAMES_NEWS), "https://www.jeuxvideo.com/rss/rss.xml"),
         Source(r"api\.rawg\.io/api/", "RAWG : refusé sans clé",
                static(json.dumps({"error": "The key parameter is not provided"}), status=401),
                "https://api.rawg.io/api/games?dates=2026-10-26,2026-11-01"),
         gnews(GAMES_NEWS)),
        hours=20),
    Scenario(
        "alerte-prix", (2026, 10, 28, 20, 10),
        "je veux m'acheter une rtx 5070, tu peux surveiller le prix et me prevenir si ca descend sous 550 balles ?",
        "Une alerte dès qu'une RTX 5070 (pas Ti) neuve passe sous 550 € chez un vendeur français sérieux, avec le "
        "prix, la boutique et le lien. Pas de message à chaque relevé. Une petite vue de l'évolution des prix lui "
        "plairait. Toutes les marques lui vont.",
        ("la marque : « n'importe, asus msi gigabyte ca va »", "l'état : « neuve, pas d'occaz ni reconditionné »",
         "la ti : « non trop chere »", "quand : « direct quand ca passe sous 550 »",
         "les sites : « idealo ou ledenicheur c'est bien »"),
        ("pas d'alerte quand le prix passe sous 550 €", "une alerte pour une Ti ou une reconditionnée",
         "un message à chaque relevé", "un prix inventé"),
        (Source(r"idealo\.fr/", "idealo, la comparaison des prix (page HTML)", shop_page("idealo"),
                "https://www.idealo.fr/prechcat.html?q=rtx+5070"),
         Source(r"ledenicheur\.fr/", "LeDénicheur, la comparaison des prix (page HTML)", shop_page("LeDénicheur"),
                "https://ledenicheur.fr/search?search=rtx%205070")),
        hours=20),
]

BY_ID = {s.id: s for s in SCENARIOS}
