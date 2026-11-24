"""La synchronisation des agendas branchés (ADR 0309), ``agenda.sync`` : un passage à la main, sur le vrai magasin, avec
un fournisseur doublure (une sorte qu'aucun lot n'a encore branchée).

- les comptes des réglages se rangent dans la base (à qui, son adresse, actif) ; un compte retiré des réglages emporte
  sa copie ; celui du système d'une personne n'a rien à relire et reste ;
- un passage range les agendas listés et relit chaque agenda suivi depuis son curseur, page après page ; un agenda
  qu'on ne suit plus perd sa copie ;
- une panne, quelle qu'elle soit, se dit en mots sur le compte (la santé la lit) et recule, doublée à chaque échec,
  bornée ; la suivante réussie l'efface ;
- un compte décoché, ou d'une sorte sans fournisseur, attend ; au plus ``per_run`` comptes par passage ; l'échéance
  suivante est la plus proche.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.adapters.agenda import AgendaStore, Providers
from mika.kernel.clock import MINUTE
from mika.plugins.agenda import AGENDA, AgendaParams, cadence
from mika.plugins.agenda.sync import IDLE_EVERY, Sync, due_at, sync_due
from mika.ports.agenda import (
    US_PER_S,
    Abilities,
    AccountState,
    AgendaError,
    Calendar,
    Connection,
    Event,
    Span,
    SyncBatch,
    calendar_key,
    system_account,
)
from tests.fixtures import backend

NOW = 1_795_000_000_000_000
HOUR = 3600 * US_PER_S


class FakeProvider:
    """Un fournisseur d'abonnements : deux agendas, des pages, une panne à la demande."""

    kind = "ical"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail: Exception | None = None
        self.listed = ["feries", "fetes"]

    def abilities(self, account: Connection) -> Abilities:
        return Abilities()

    async def calendars(self, account: Connection) -> list[Calendar]:
        if self.fail is not None:
            raise self.fail
        return [Calendar(calendar_key(account.key, local), account.key, local, local.title(), primary=i == 0,
                         selected=False) for i, local in enumerate(self.listed)]

    async def create_calendar(self, account, name):
        raise AgendaError("lecture seule")

    async def sync(self, account, calendar, cursor, window) -> SyncBatch:
        self.calls.append((calendar.key, cursor))
        page = int(cursor or 0)
        e = Event(calendar.key, f"jour-{page}", Span(NOW + page * 24 * HOUR, NOW + (page + 1) * 24 * HOUR,
                                                      all_day=True), f"Jour {page}")
        return SyncBatch(events=(e,), cursor=str(page + 1), more=page < 2)

    async def create(self, *a, **k):
        raise AgendaError("lecture seule")

    edit = delete = respond = create


@pytest.fixture
def world(tmp_path):
    store = AgendaStore(backend.target(tmp_path, "agenda"), now=lambda: NOW)
    accounts = [Connection("feries", "ical", label="Jours fériés", url="https://x/feries.ics"),
                Connection("lea-google", "google", owner="personne:user_2", address="lea@gmail.com")]
    providers = Providers(store, lambda: list(accounts))
    fake = FakeProvider()
    providers.add(fake)
    yield SimpleNamespace(store=store, providers=providers, fake=fake, accounts=accounts)
    store.close()


def run(coro):
    return asyncio.run(coro)


def test_a_pass_keeps_the_accounts_and_reads_each_followed_calendar_page_by_page(world):
    p = AgendaParams()
    nxt = run(sync_due(world.store, world.providers, p, NOW))
    assert {a.key: (a.kind, a.owner, a.address) for a in world.store.accounts()} == {
        "feries": ("ical", "", ""), "lea-google": ("google", "personne:user_2", "lea@gmail.com")}
    # le principal seulement (le fournisseur ne coche pas l'autre), ses trois pages
    assert world.fake.calls == [("feries~feries", ""), ("feries~feries", "1"), ("feries~feries", "2")]
    assert [c.key for c in world.store.calendars("feries")] == ["feries~feries", "feries~fetes"]
    assert world.store.calendar("feries~feries").cursor == "3"
    assert len(world.store.period(["feries~feries"], NOW, NOW + 10 * 24 * HOUR)) == 3
    done = world.store.account("feries")
    assert done.synced_at == NOW and done.failures == 0
    # Google n'a pas encore de fournisseur : il attend ; l'échéance suivante est celle de l'abonnement
    assert world.store.account("lea-google").tried_at == 0
    assert nxt == NOW + cadence(p, "ical")


def test_a_calendar_no_longer_followed_loses_its_copy_and_a_new_one_is_read(world):
    run(sync_due(world.store, world.providers, AgendaParams(), NOW))
    world.accounts[0] = Connection("feries", "ical", followed={"feries": False, "fetes": True})
    world.fake.calls.clear()
    run(sync_due(world.store, world.providers, AgendaParams(), NOW + 2 * HOUR))
    assert world.fake.calls[0] == ("feries~fetes", "")
    assert world.store.period(["feries~feries"], NOW, NOW + 10 * 24 * HOUR) == []
    assert world.store.calendar("feries~feries").cursor == ""


def test_a_failure_is_said_in_words_and_backs_off_doubling(world):
    p = AgendaParams()
    world.fake.fail = OSError(111, "Connection refused")
    nxt = run(sync_due(world.store, world.providers, p, NOW))
    st = world.store.account("feries")
    assert st.failures == 1 and "Connection refused" in st.error and world.store.failing() == ["feries"]
    assert nxt == NOW + p.retry_us
    run(sync_due(world.store, world.providers, p, NOW + p.retry_us))
    assert world.store.account("feries").failures == 2
    assert due_at(world.store.account("feries"), "ical", p) == NOW + p.retry_us + 2 * p.retry_us
    world.fake.fail = AgendaError("l'adresse ne rend pas un agenda")
    run(sync_due(world.store, world.providers, p, NOW + 3 * p.retry_us))
    # celle d'un fournisseur se dit telle qu'il la dit (sans « erreur d'un agenda : » devant)
    assert world.store.account("feries").error == "l'adresse ne rend pas un agenda"
    world.fake.fail = None
    run(sync_due(world.store, world.providers, p, NOW + 10 * p.retry_us))
    assert world.store.account("feries").failures == 0 and world.store.failing() == []


def test_the_back_off_is_bounded():
    p = AgendaParams(retry_us=MINUTE, retry_max_us=10 * MINUTE)
    st = AccountState("x", "ical", tried_at=NOW, failures=40)
    assert due_at(st, "ical", p) == NOW + 10 * MINUTE
    assert due_at(None, "ical", p) == 0 and due_at(AccountState("x", "ical"), "ical", p) == 0
    assert due_at(AccountState("x", "google", synced_at=NOW, tried_at=NOW), "google", p) == NOW + p.google_every_us


def test_an_account_gone_from_the_settings_takes_its_copy_and_a_system_one_stays(world):
    run(sync_due(world.store, world.providers, AgendaParams(), NOW))
    world.providers.system.ensure(system_account("user_1"))
    world.accounts.clear()
    nxt = run(sync_due(world.store, world.providers, AgendaParams(), NOW + HOUR))
    assert [a.key for a in world.store.accounts()] == ["moi:user_1"]
    assert world.store.calendars("feries") == [] and nxt == NOW + HOUR + IDLE_EVERY


def test_an_unticked_account_waits_and_a_pass_is_bounded(world):
    nxt = run(sync_due(world.store, world.providers, AgendaParams(accounts_off=("feries",)), NOW))
    assert world.fake.calls == [] and not world.store.account("feries").enabled
    assert nxt == NOW + IDLE_EVERY
    world.accounts[:] = [Connection(f"abo{i}", "ical") for i in range(4)]
    run(sync_due(world.store, world.providers, AgendaParams(per_run=2), NOW))
    assert sum(1 for a in world.store.accounts() if a.tried_at) == 2


def test_the_process_waits_for_its_ports_and_follows_its_next_due(world):
    sync = Sync()
    frame = SimpleNamespace(now=NOW, root=None, env=SimpleNamespace(params_of=lambda owner, root: AgendaParams()))
    assert sync.next_due(None, frame, None) == NOW
    run(sync.run(SimpleNamespace(ports={}, frame=frame, now=NOW)))
    assert sync.next_due(None, frame, NOW) == NOW + IDLE_EVERY
    ports = {"agenda": world.store, "agenda_providers": world.providers}
    run(sync.run(SimpleNamespace(ports=ports, frame=frame, now=NOW)))
    assert sync.next_due(None, frame, NOW) == NOW + AgendaParams().ical_every_us
    assert [s.name for s in AGENDA.processes] == ["agenda.sync", "agenda.watch"]  # et ce qu'elle voit venir (lot 3b)
