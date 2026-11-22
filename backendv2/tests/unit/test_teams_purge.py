"""`mika teams purge` : ce que l'extension d'un compte a apporté s'efface, sa clé reste — on recharge l'historique.

Ce qui avait été rangé de travers (ses propres messages pris pour ceux d'un autre, le 2026-11-22) ne se convertit pas :
on efface et on recharge (« effacer plutôt que convertir »). Les vues de l'annuaire venues de ce compte partent aussi,
sinon le rechargement les compterait deux fois ; serveur arrêté (le verrou du dossier).
"""

from __future__ import annotations

from types import SimpleNamespace

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.app import schema
from mika.app.cli.plugins import purge_teams
from mika.app.teams import batch_of
from mika.ports.teams import DEFAULT_ACCOUNT as PRINCIPAL

CONV = "19:projet@thread.v2"


def _fill(data, now_us: int) -> None:
    bases = schema.targets(data)
    schema.migrate_data(data, bases)
    store = TeamsStore(lambda: TeamsConfig(), bases["teams"], now=lambda: now_us)
    try:
        lot = {"self": {"id": "8:orgid:3e51ce13-6eb8-463b-a75a-a40b2ab67602", "name": "Adrien"},
               "conversations": [{"id": CONV, "title": "Projet", "kind": "group"}],
               "messages": [{"id": "1763000000001", "conv": CONV, "author": "Gilles", "author_id": "8:orgid:g",
                             "time": now_us // 1000, "text": "bonjour"}]}
        store.store_batch(PRINCIPAL, batch_of(lot, now_us // 1000)[0], now_us)
        assert store.thread(PRINCIPAL, CONV, 10)
    finally:
        store.close()


def test_purge_erases_what_the_extension_brought_and_keeps_nothing_to_convert(tmp_path):
    now_us = 1_763_000_000_000_000
    _fill(tmp_path, now_us)
    settings = SimpleNamespace(teams=lambda: TeamsConfig())
    out = purge_teams(tmp_path, settings, PRINCIPAL)
    assert out["ok"] is True and out["lignes_teams"] >= 3  # message, conversation, compte
    store = TeamsStore(lambda: TeamsConfig(), schema.targets(tmp_path)["teams"], now=lambda: now_us)
    try:
        assert store.thread(PRINCIPAL, CONV, 10) == []
    finally:
        store.close()
