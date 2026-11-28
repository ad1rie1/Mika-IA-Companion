"""Les sections « Données touristiques (DATAtourisme) » et « Réchauffage des caches » de la console (ADR 0245), à
travers le vrai serveur : la clé s'enregistre scellée et ne redescend jamais dans la page (vide : inchangée), la page
dit d'où vient la clé en service (réglée ici, ou la variable d'environnement), ses demandes, son cache ; « Synchroniser
maintenant » et « Réchauffer maintenant » sont des boutons de leur page. Sans clé, le serveur ne demande rien à
personne."""

from __future__ import annotations

import html

from mika.adapters.maps.config import TourismConfig, WarmConfig
from mika.app.domains.maps.settings import MapsSettings
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/admin/reglages/tourisme"
CANARY = "cle-canari-datatourisme-77"


def post(client, data: dict) -> object:
    return client.post(PAGE, data={"csrf": client.cookies.get("csrftoken"), "_section": "tourisme", **data})


def test_the_key_is_kept_sealed_and_never_shown_again(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    page = client.get(PAGE)
    assert page.status_code == 200
    text = html.unescape(page.text)
    assert "Données touristiques (DATAtourisme)" in text and "aucune : rien ne part" in text
    assert "0 demandes dans l'heure sur 900 (180 gardées pour le direct)" in text
    assert "Synchroniser maintenant" in text and "Licence Ouverte 2.0" in text
    saved = post(client, {"_champs": ["api_key", "zones", "horizon_days", "night_hour", "per_hour", "per_second",
                                      "reserve_pct", "cell_km", "places_days", "events_days"],
                          "api_key": CANARY, "zones": "59\n62", "horizon_days": "60", "night_hour": "3",
                          "per_hour": "800", "per_second": "5", "reserve_pct": "10", "cell_km": "8",
                          "places_days": "5", "events_days": "2"})
    assert saved.status_code in (200, 303), saved.text[:300]
    cfg = client.portal.call(live.settings.of(MapsSettings).tourism_config)
    assert cfg == TourismConfig(api_key=CANARY, zones=("59", "62"), horizon_days=60, night_hour=3, per_hour=800,
                                per_second=5.0, reserve_pct=10, cell_km=8, places_days=5, events_days=2)
    again = html.unescape(client.get(PAGE).text)
    assert CANARY not in again and "réglée ici" in again and "sur 800" in again
    # renvoyé sans clé : elle reste
    post(client, {"_champs": ["api_key", "zones"], "api_key": "", "zones": "59"})
    assert client.portal.call(live.settings.of(MapsSettings).tourism_config).api_key == CANARY
    # effacée : la variable d'environnement prend le relais, et la page le dit
    post(client, {"_champs": ["api_key"], "api_key": "", "_effacer": ["api_key"]})
    assert client.portal.call(live.settings.of(MapsSettings).tourism_config).api_key == ""
    assert "aucune : rien ne part" in html.unescape(client.get(PAGE).text)


def test_the_page_says_when_the_key_comes_from_the_environment(world, monkeypatch):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    monkeypatch.setenv("MIKA_DATATOURISME_API_KEY", CANARY)
    text = html.unescape(client.get(PAGE).text)
    assert "variable d'environnement MIKA_DATATOURISME_API_KEY" in text and CANARY not in text


def test_the_sync_now_button_answers_in_words(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    pressed = post(client, {"_commande": "synchroniser"})
    assert pressed.status_code in (200, 303)
    shown = html.unescape(client.get(pressed.headers["location"]).text if pressed.status_code == 303 else pressed.text)
    assert "Aucune clé DATAtourisme" in shown


def test_the_pages_are_among_the_map_and_phone_tabs(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    text = client.get("/admin/reglages/carte").text
    assert 'href="/admin/reglages/tourisme"' in text and 'href="/admin/reglages/rechauffage"' in text


def test_the_warm_page_sets_its_hour_and_points_and_says_its_state(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    text = html.unescape(client.get("/admin/reglages/rechauffage").text)
    assert "Réchauffage des caches" in text and "chaque soir à 22:00" in text and "Réchauffer maintenant" in text
    assert "pas de clé : rien ne part" in text and "Dernier passage" in text
    saved = client.post("/admin/reglages/rechauffage", data={
        "csrf": client.cookies.get("csrftoken"), "_section": "rechauffage", "_champs": ["hour", "people", "points"],
        "hour": "21", "people": "on", "points": "Lille\n45.90, 6.13"})
    assert saved.status_code in (200, 303), saved.text[:300]
    assert client.portal.call(live.settings.of(MapsSettings).warm_config) == WarmConfig(hour=21, points=("Lille", "45.90, 6.13"))
    pressed = client.post("/admin/reglages/rechauffage", data={
        "csrf": client.cookies.get("csrftoken"), "_section": "rechauffage", "_commande": "rechauffer"})
    shown = html.unescape(client.get(pressed.headers["location"]).text if pressed.status_code == 303 else pressed.text)
    assert "Aucune source n'est prête" in shown
