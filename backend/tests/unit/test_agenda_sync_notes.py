"""L'historique de la synchro d'un compte (ADR 0309, lot 5 : l'onglet Synchronisation de la fiche d'un agenda), sur le
vrai magasin et le fournisseur doublure de ``test_agenda_sync`` :

- une relecture qui range quelque chose se note (entière quand l'agenda n'avait pas de curseur), une relecture qui ne
  change rien ne se note pas ;
- une panne se note une fois (la même erreur, encore et encore, ne se renote pas ; une autre, si), sa reprise aussi ;
- un agenda qu'on ne suit plus, sa copie partie ;
- ce qui est plus ancien que sa durée de garde part ; le compte retiré emporte son historique ;
- jamais un titre : ce qu'une note dit, ce sont des nombres et l'erreur en mots.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from mika.kernel.clock import DAY
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.sync import sync_account
from mika.ports.agenda import (
    SYNC_DROPPED,
    SYNC_FAILED,
    SYNC_FULL,
    SYNC_READ,
    SYNC_RECOVERED,
    AgendaError,
    SyncBatch,
    SyncNote,
)
from tests.unit.test_agenda_sync import HOUR, NOW, FakeProvider, world  # noqa: F401 — la fixture partagée


def _sync(w, at: int, p: AgendaParams | None = None) -> None:
    conn = next(c for c in w.accounts if c.key == "feries")
    w.store.keep_account(conn.key, conn.kind)
    asyncio.run(sync_account(w.store, w.fake, conn, p or AgendaParams(), at))


def _whats(w, calendar: str = "") -> list[str]:
    return [n.what for n in reversed(w.store.sync_notes("feries", calendar))]


def test_a_read_that_changes_something_is_noted_and_a_quiet_one_is_not(world):  # noqa: F811
    w = world
    w.accounts[0] = replace(w.accounts[0], followed={"feries": True, "fetes": True})
    _sync(w, NOW)
    notes = w.store.sync_notes("feries", "feries~feries")
    assert [n.what for n in notes] == [SYNC_FULL]  # sans curseur : relu en entier
    assert notes[0].changed == 3 and notes[0].calendar == "feries~feries" and "Jour" not in notes[0].detail
    w.fake.sync = _quiet  # le fournisseur n'a plus rien de neuf
    _sync(w, NOW + HOUR)
    assert _whats(w, "feries~feries") == [SYNC_FULL]
    w.fake.sync = _one_more
    _sync(w, NOW + 2 * HOUR)
    assert _whats(w, "feries~feries")[-1] == SYNC_READ  # avec son curseur : une relecture ordinaire


async def _quiet(account, calendar, cursor, window) -> SyncBatch:
    return SyncBatch(cursor=cursor)


async def _one_more(account, calendar, cursor, window) -> SyncBatch:
    return await FakeProvider().sync(account, calendar, "0", window)


def test_a_failure_is_noted_once_and_its_recovery_too(world):  # noqa: F811
    w = world
    w.fake.fail = AgendaError("le serveur est injoignable")
    _sync(w, NOW)
    _sync(w, NOW + HOUR)  # la même panne : pas une seconde ligne
    assert _whats(w) == [SYNC_FAILED]
    assert w.store.sync_notes("feries")[0].detail == "le serveur est injoignable"
    w.fake.fail = AgendaError("identifiant refusé")
    _sync(w, NOW + 2 * HOUR)  # une autre : une ligne
    w.fake.fail = None
    _sync(w, NOW + 3 * HOUR)
    whats = _whats(w)
    assert whats[:2] == [SYNC_FAILED, SYNC_FAILED] and whats[-1] == SYNC_RECOVERED  # la reprise, après ce qu'elle relit
    # ce qui touche tout le compte se lit aussi sur chacun de ses agendas
    assert SYNC_RECOVERED in _whats(w, "feries~feries")


def test_a_calendar_no_longer_followed_says_its_copy_left(world):  # noqa: F811
    w = world
    w.accounts[0] = replace(w.accounts[0], followed={"feries": True})
    _sync(w, NOW)
    w.accounts[0] = replace(w.accounts[0], followed={"feries": False})
    _sync(w, NOW + HOUR)
    assert _whats(w, "feries~feries")[-1] == SYNC_DROPPED


def test_old_notes_leave_and_the_account_takes_its_history_with_it(world):  # noqa: F811
    w = world
    w.store.keep_account("feries", "ical")
    w.store.note_sync(SyncNote("feries", "", NOW - 40 * DAY, SYNC_FAILED, detail="ancienne panne"))
    w.store.note_sync(SyncNote("feries", "", NOW, SYNC_RECOVERED), keep_us=30 * DAY)
    assert _whats(w) == [SYNC_RECOVERED] and w.store.sync_notes_count("feries") == 1
    w.store.drop_account("feries")
    assert w.store.sync_notes_count("feries") == 0
