"""Relire un fil Teams (``teams_read``, ADR 0303), par ses intentions, sur le vrai cache de Teams.

- **la fin dit ce qu'elle a lu** : combien de messages sur combien, et d'où remonter (la référence du plus ancien
  qu'elle vient de lire) ; relire jusqu'à lui remonte le fil, page par page, jusqu'à son début ;
- **ses suivants seulement** : après le message relu, les derniers du fil s'ils le suivent de près ; plus loin, la fin
  dit combien restent après, au lieu de montrer la fin du fil comme s'ils se suivaient ;
- **une borne de taille** qui coupe les plus anciens, jamais le message demandé ni ceux qui y mènent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from mika.adapters.teams import TeamsStore
from mika.plugins.teams.accounts import Accounts
from mika.plugins.teams.tools import READ_CHARS, ReadArgs, teams_read
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage, message_ref
from mika.vocab.phrasebook import phrase
from tests.unit.test_teams import ALICE, DM
from tests.unit.test_teams_accounts import NOW, YOU, _config, frame

BOB = "8:orgid:bob"


@pytest.fixture
def store(tmp_path):
    found = TeamsStore(_config, tmp_path / "teams.db", now=lambda: NOW)
    yield found
    found.close()


def fill(store: TeamsStore, count: int, text=lambda n: f"Message {n}") -> None:
    """Un fil de ``count`` messages, Bob et Alice à tour de rôle, numérotés de 1 à ``count``."""
    messages = tuple(InboxMessage(str(n), DM, "Alice" if n % 2 == 0 else "Bob", ALICE if n % 2 == 0 else BOB,
                                  NOW // 1000 - 10_000 + n, text(n)) for n in range(1, count + 1))
    store.store_batch("principal", InboxBatch("8:moi", "Adrien", (InboxConversation(DM, "", "dm"),), messages), NOW)


def read(store: TeamsStore, n: int, **more) -> str:
    said = asyncio.run(teams_read(ReadArgs(message=f"[{message_ref(DM, str(n))}]", **more),
                                  NS(ports={"teams": store}, frame=frame(YOU))))
    assert isinstance(said, str), said
    return said


def numbers(said: str) -> list[int]:
    """Les numéros des messages relus, dans l'ordre où elle les lit."""
    return [int(line.rsplit("Message ", 1)[1].split()[0]) for line in said.splitlines()
            if line.startswith("> ") and "Message " in line]


def span(shown: int, total: int, older: int = 0, ref: str = "", newer: int = 0) -> str:
    said = phrase("teams.tools.read.span.read", shown=shown, total=total)
    if older:
        said += phrase("teams.tools.read.span.older", older=older, ref=ref)
    if newer:
        said += phrase("teams.tools.read.span.newer", newer=newer)
    return phrase("teams.tools.read.span.frame", said=said)


def test_the_end_says_how_much_she_read_and_where_to_climb_back_from(store):
    fill(store, 60)
    said = read(store, 60)  # la référence que donne l'annuaire : le dernier message du fil
    assert numbers(said) == list(range(46, 61))  # quinze par défaut
    assert span(15, 60, older=45, ref=message_ref(DM, "46")) in said
    # relire jusqu'au plus ancien lu remonte le fil, quarante au plus à la fois
    page = read(store, 46, limit=40)
    assert numbers(page) == list(range(7, 47))
    assert span(40, 60, older=6, ref=message_ref(DM, "7"), newer=14) in page
    first = read(store, 7, limit=40)
    assert numbers(first) == list(range(1, 8))  # le début du fil : plus rien avant
    assert span(7, 60, newer=53) in first and "plus anciens" not in first


def test_after_the_message_only_the_ones_that_follow_it(store):
    fill(store, 60)
    near = read(store, 57)  # trois après lui, les derniers du fil : ses suivants
    assert numbers(near) == list(range(43, 61))
    assert span(18, 60, older=42, ref=message_ref(DM, "43")) in near and "plus récents" not in near
    far = read(store, 30)  # trente après lui : la fin du fil n'est pas sa suite
    assert numbers(far) == list(range(16, 31))
    assert span(15, 60, older=15, ref=message_ref(DM, "16"), newer=30) in far


def test_a_long_thread_drops_its_oldest_never_the_message_asked_for(store):
    fill(store, 60, text=lambda n: f"Message {n} " + "très long " * 80)
    said = read(store, 60, limit=40)
    got = numbers(said)
    assert got[-1] == 60 and got == list(range(got[0], 61)) and len(got) < 40  # la fin demandée, sans trou
    assert "la suite est coupée" not in said
    body = said.split(":\n", 1)[1]
    quoted = body[:body.index("\n(" + phrase("teams.tools.read.span.read", shown=len(got), total=60))]
    assert len(quoted) <= READ_CHARS + 2 * len(got)  # la borne, aux « > » de la citation près
    assert span(len(got), 60, older=got[0] - 1, ref=message_ref(DM, str(got[0]))) in said


def test_the_count_of_a_thread_is_kept_to_its_account(store):
    fill(store, 12)
    assert store.thread_count("principal", DM) == 12
    assert store.thread_count("principal", DM, before=(NOW // 1000 - 10_000 + 5) * 1000) == 4
    assert store.thread_count("nadia_t", DM) == 0 and store.thread_count("principal", "19:autre@x") == 0


def test_messages_of_the_same_instant_leave_no_gap(store):
    """Relecture du 2026-11-22 : le compte des plus anciens se faisait sur la date du premier lu ; ceux du même instant,
    plus anciens que lui, n'étaient comptés nulle part — et l'invitation à remonter disparaissait s'ils restaient seuls."""
    at = NOW // 1000 - 10_000
    store.store_batch("principal", InboxBatch("8:moi", "Adrien", (InboxConversation(DM, "", "dm"),), tuple(
        InboxMessage(str(n), DM, "Bob", BOB, at if n <= 6 else at + n, f"Message {n}") for n in range(1, 21))), NOW)
    said = read(store, 20)
    shown = numbers(said)
    assert len(shown) == 15 and 20 in shown
    older = 20 - len(shown)
    assert phrase("teams.tools.read.span.older", older=older, ref=message_ref(DM, str(shown[0]))) in said


def test_another_persons_account_counts_nothing(store):
    fill(store, 5)
    assert Accounts(store, ["nadia_t"]).thread_count("principal", DM) == 0
    assert Accounts(store, ["principal"]).thread_count("principal", DM) == 5
