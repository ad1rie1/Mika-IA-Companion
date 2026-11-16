"""Une liste de la console prête pour une carte (``app/handmade/lists.py::card_as``) : ce qui ne dit rien se tait —
une étiquette vide ou « — » (une cellule sans valeur), sur toutes les fiches ; l'état ordinaire, sur la fiche de
quelqu'un seulement."""

from __future__ import annotations

from typing import Any

from mika.app.handmade.lists import card_as

DASH = {"t": "text", "text": "—", "kind": "muted"}


def badge(text: str, tone: str = "") -> dict[str, Any]:
    return {"t": "badge", "text": text, "tone": tone, "key": ""}


def moments(*badges: dict[str, Any]) -> dict[str, Any]:
    """Une liste aux rôles déclarés, de la forme que rend ``render.block`` : les moments de sa vie, dont les colonnes
    « situation », « issue » et « se fête » sont des étiquettes, vides (« — ») quand la mémoire n'en dit rien."""
    title = {"t": "text", "kind": "text", "text": "Le prochain stream d'Adrien", "tone": "", "hint": ""}
    labels = ("moment", "sensibilité", "situation", "issue", "se fête", "statut")
    return {"t": "table", "id": "pg1", "title": "Ce qui se passe dans la vie des autres", "layout": "list",
            "columns": [{"label": label, "align": "", "hint": ""} for label in labels],
            "rows": [{"cells": [title, *badges], "tone": "", "href": "", "detail": [], "heading": title,
                      "badges": list(badges), "body": [], "fields": []}],
            "pager": {"pages": 1, "page": 1, "total": 1, "prev": "", "next": ""}, "count": 1, "shown": 1}


def tags(card: dict[str, Any]) -> list[str]:
    return [b["text"] for b in card["rows"][0]["badges"]]


def test_an_empty_or_dash_badge_says_nothing_on_any_card():
    listed = moments(badge("personnel"), DASH, DASH, {"t": "text", "text": "", "kind": "muted"}, badge("à suivre", "info"))
    assert tags(card_as(listed)) == ["personnel", "à suivre"]
    listed = moments(badge("personnel"), DASH, DASH, DASH, badge("à suivre", "info"))
    assert tags(card_as(listed, "adrien", quiet=True)) == ["personnel", "à suivre"]


def test_the_ordinary_state_is_quiet_only_on_someones_card():
    assert tags(card_as(moments(badge("actif"), badge("secret", "danger")))) == ["actif", "secret"]
    assert tags(card_as(moments(badge("actif"), badge("secret", "danger")), "adrien", quiet=True)) == ["secret"]
