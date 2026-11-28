"""La section « Avis (Google) » de la console (ADR 0256), à travers le vrai serveur : la clé s'enregistre scellée et ne
redescend jamais dans la page (vide : inchangée ; effacée : la variable d'environnement prend le relais), la page dit
d'où vient la clé en service, ses appels du jour et ceux du mois de chaque niveau sur leur quota offert, ce qui serait
facturé, son cache, les conditions de Google et ce qu'on en a décidé, et de restreindre la clé ; elle est un onglet de
Carte et téléphone. Sans clé, le serveur ne demande rien à personne."""

from __future__ import annotations

import html

from mika.adapters.maps.config import ReviewsConfig
from mika.app.domains.maps.settings import MapsSettings
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/admin/reglages/avis"
CANARY = "cle-canari-google-77"
FIELDS = ["api_key", "searches_per_month", "details_per_month", "photos_per_month", "per_day", "per_second",
          "reserve_pct", "cache_days", "cell_km", "split_depth", "preload", "warm"]


def post(client, data: dict) -> object:
    return client.post(PAGE, data={"csrf": client.cookies.get("csrftoken"), "_section": "avis", **data})


def test_the_key_is_kept_sealed_and_never_shown_again(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    page = client.get(PAGE)
    assert page.status_code == 200
    text = html.unescape(page.text)
    assert "Avis (Google)" in text and "aucune : rien ne part" in text
    assert "0 recherches ce mois sur 1000 (200 gardées pour le direct)" in text
    assert "Nearby Search Enterprise" in text and "Place Details Enterprise + Atmosphere" in text
    assert "Place Details Photos" in text and "35 $ les 1 000" in text and "7 $ les 1 000" in text
    assert "0 demandes en 24 heures sur 500" in text and "au plus 5 par seconde" in text
    assert "rien : tout tient dans les quotas offerts" in text
    assert "Conditions de Google" in text and "ADR 0256" in text and "Places API (New)" in text
    saved = post(client, {"_champs": FIELDS, "api_key": CANARY, "searches_per_month": "2000",
                          "details_per_month": "1000", "photos_per_month": "500", "per_day": "800",
                          "per_second": "2", "reserve_pct": "10", "cache_days": "14", "cell_km": "2",
                          "split_depth": "2", "preload": "on"})
    assert saved.status_code in (200, 303), saved.text[:300]
    cfg = client.portal.call(live.settings.of(MapsSettings).reviews_config)
    assert cfg == ReviewsConfig(api_key=CANARY, searches_per_month=2000, details_per_month=1000,
                                photos_per_month=500, per_day=800, per_second=2.0, reserve_pct=10, cache_days=14,
                                cell_km=2, split_depth=2, preload=True, warm=False)
    again = html.unescape(client.get(PAGE).text)
    assert CANARY not in again and "réglée ici" in again and "sur 2000" in again and "gardées 14 jour(s)" in again
    assert "de 1 à 21 recherches" in again
    post(client, {"_champs": ["api_key", "cache_days"], "api_key": "", "cache_days": "7"})
    assert client.portal.call(live.settings.of(MapsSettings).reviews_config).api_key == CANARY  # renvoyée vide : elle reste
    post(client, {"_champs": ["api_key"], "api_key": "", "_effacer": ["api_key"]})
    assert client.portal.call(live.settings.of(MapsSettings).reviews_config).api_key == ""
    assert "aucune : rien ne part" in html.unescape(client.get(PAGE).text)


def test_the_page_says_when_the_key_comes_from_the_environment(world, monkeypatch):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    monkeypatch.setenv("MIKA_GOOGLE_PLACES_API_KEY", CANARY)
    text = html.unescape(client.get(PAGE).text)
    assert "variable d'environnement MIKA_GOOGLE_PLACES_API_KEY" in text and CANARY not in text


def test_the_page_is_a_tab_of_map_and_phone_and_its_warm_budget_is_said(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    assert 'href="/admin/reglages/avis"' in client.get("/admin/reglages/carte").text
    warm = html.unescape(client.get("/admin/reglages/rechauffage").text)
    assert "Budget de Google" in warm and "Google : les restaurants" in warm


def test_the_page_says_its_counts_are_those_of_this_data_folder_only(world):  # noqa: F811
    """R3-08 : « rien n'est facturé » ne vaut que pour une clé qui ne sert qu'à ce serveur — les compteurs du mois sont
    ceux de ce dossier de données ; la même clé sur un autre serveur, ou dans le ``.env`` d'un poste, puise dans le même
    quota offert de Google, sans que ces comptes le voient. La page le dit là où on lit le mois et la facture."""
    client, _live, _ = world
    bootstrap(client)
    text = html.unescape(client.get(PAGE).text)
    assert "d'après les comptes de ce dossier de données" in text
    assert "la même clé ailleurs puise dans le même quota offert" in text
    assert "une clé à part pour un autre serveur ou un poste de développement" in text
