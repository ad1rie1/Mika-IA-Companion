"""Où quelqu'un écrit dans Teams (ADR 0298, l'écran Contacts) : ``TeamsStore.written_in`` rend les conversations où
ces personnes ont écrit, dans les comptes demandés seulement, la plus récente d'abord, chacune sous son nom (l'autre
personne pour un tête-à-tête), avec combien de leurs messages — sans compter ce que la personne du compte a écrit."""

from __future__ import annotations

import pytest

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
GILLES = "8:orgid:0B5C1A2E-0000-4000-8000-000000000001"
DM, GROUP = "19:gilles_adrien@unq.gbl.spaces", "19:projet@thread.v2"


@pytest.fixture
def store(tmp_path):
    found = TeamsStore(lambda: TeamsConfig(), backend.target(tmp_path, "teams"), now=lambda: NOW)
    yield found
    found.close()


def message(i: int, conversation: str, author: str = "Gilles", author_id: str = GILLES, *, own: bool = False,
            at: int = 0) -> InboxMessage:
    return InboxMessage(f"m{i}", conversation, author, author_id, at or NOW // 1000 - 10_000 + i, "Bonjour", own=own)


def test_the_conversations_where_someone_wrote_in_the_accounts_asked(store):
    store.store_batch("adrien", InboxBatch("8:orgid:moi", "Adrien", (
        InboxConversation(DM, "", "dm"), InboxConversation(GROUP, "Projet Lumen", "group")), (
        message(1, GROUP), message(2, GROUP), message(3, DM),
        message(4, DM, "Adrien", "8:orgid:moi", own=True), message(5, GROUP, "Léa", "8:orgid:lea"))), NOW)
    store.store_batch("bea", InboxBatch("8:orgid:bea", "Béa", (InboxConversation(DM, "", "dm"),),
                                        (message(6, DM),)), NOW)
    got = store.written_in([GILLES.lower()], 10, accounts=["adrien"])
    assert [(c.account, c.id, c.title, c.kind, n) for c, n, _at in got] == [
        ("adrien", DM, "Gilles", "dm", 1), ("adrien", GROUP, "Projet Lumen", "group", 2)]
    assert got[0][2] > got[1][2]  # la plus récente d'abord
    assert {c.account for c, _n, _at in store.written_in([GILLES], 10)} == {"adrien", "bea"}  # sans casse, partout
    assert store.written_in([GILLES], 10, accounts=[]) == [] and store.written_in([], 10) == []
    assert store.written_in(["8:orgid:moi"], 10) == []  # la personne du compte n'y compte pas
    assert len(store.written_in([GILLES], 1)) == 1
