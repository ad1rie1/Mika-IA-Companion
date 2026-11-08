"""Ce qu'une demande à autoriser concerne et d'où elle vient (``app/handmade/approval_sources.py``, ADR 0177) : le seul
lecteur du contexte d'une demande, côté composition. Un canal (``teams``, ``email``, ``phone``) n'est jamais une
personne ; un service, une app, un projet mènent à leur fiche ; une personne à la sienne et à leur conversation, « de »
élidé devant une voyelle. L'inspecteur, lui, ne lit plus ces contextes (audit du 2026-11-05, C1-01 et K0-17)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mika.app.handmade.approval_sources import about, sources
from mika.app.handmade.waiting import QUEUE

INSPECTOR_PAGE = Path(__file__).resolve().parents[2] / "src" / "mika" / "inspector" / "pages" / "approvals.py"


class _Names:
    """Les noms d'une console : Adrien (son adresse est sa personne) et Béa (une adresse, ``ext_2``, de la personne
    ``p_bea``) ; toute autre clé est inconnue (``person_of`` la rend telle quelle, comme la vraie)."""

    known = {"user_1": ("user_1", "Adrien"), "ext_2": ("p_bea", "Béa")}

    def person_of(self, handle: str) -> str:
        return self.known.get(handle, (handle, ""))[0]

    def name_of(self, handle: str) -> str:
        return self.known.get(handle, ("", ""))[1]

    def who(self, target: str) -> str:
        return self.name_of(target) or target


class _Console:
    names = _Names()


UI = _Console()


@pytest.mark.parametrize(("context", "said"), [("teams", "Teams"), ("email", "courrier"), ("phone", "téléphone")])
def test_a_channel_is_never_a_person(context: str, said: str) -> None:
    assert about(UI, context) == (said, None)
    assert QUEUE.about(UI, context) == (said, None)  # ce que la file, sa demande ouverte et l'historique reçoivent
    assert sources(UI, "demo.envoyer", context, {}) == []  # ni « La fiche de teams », ni une fiche qui n'existe pas


def test_a_teams_reply_links_its_draft_and_its_conversation_never_a_person() -> None:
    got = sources(UI, "teams.send", "teams", {"draft": "r-1", "conversation": "19:projet"})
    assert [text for text, _ in got] == ["La réponse préparée", "La conversation Teams"]
    assert not [href for _, href in got if "/fiche/person/" in href]


def test_a_mail_links_its_draft_and_its_box() -> None:
    assert sources(UI, "email.send", "email", {"draft": "d-1", "account": "perso"}) == [
        ("Le brouillon", "/inspecteur/fiche/brouillon/d-1"),
        ("La boîte « perso »", "/inspecteur/courrier/reception?compte=perso")]


@pytest.mark.parametrize(("context", "said", "href", "label"), [
    ("mcp:agenda", "service « agenda »", "/inspecteur/fiche/serveur/agenda", "Le service « agenda »"),
    ("forge:meteo", "app « meteo »", "/inspecteur/fiche/app/meteo", "L'app « meteo »"),
    ("project:61", "projet n° 61", "/inspecteur/fiche/project/61", "Le projet n° 61"),
])
def test_a_service_an_app_and_a_project_lead_to_their_fiche(context: str, said: str, href: str, label: str) -> None:
    assert about(UI, context) == (said, href)
    assert sources(UI, "demo.envoyer", context, {}) == [(label, href)]


def test_a_person_leads_to_their_fiche_and_their_conversation() -> None:
    assert about(UI, "user_1") == ("Adrien", "/inspecteur/fiche/person/user_1")
    assert sources(UI, "demo.envoyer", "user_1", {}) == [
        ("La fiche d'Adrien", "/inspecteur/fiche/person/user_1"),  # « de » élidé devant une voyelle
        ("Leur conversation", "/inspecteur/fiche/person/user_1?onglet=echanges")]
    assert sources(UI, "demo.envoyer", "ext_2", {})[0] == ("La fiche de Béa", "/inspecteur/fiche/person/p_bea")


def test_nothing_is_said_without_a_context() -> None:
    assert about(UI, "") == ("", None) and sources(UI, "demo.envoyer", "", {}) == []


def test_the_inspector_reads_no_context_itself() -> None:
    """La page de la console n'écrit ni ``mcp``, ni ``forge``, ni un canal : ce qu'une demande concerne lui vient de la
    composition (``queue.about``), qui seule nomme les plugins (K0-17)."""
    tree = ast.parse(INSPECTOR_PAGE.read_text(encoding="utf-8"))
    written = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not written & {"mcp", "forge", "teams", "email", "phone"}
