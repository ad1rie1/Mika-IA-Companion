"""La base de l'agenda (ADR 0309), son magasin : sur SQLite, et sur MariaDB par la voie ``--mariadb``.

- **la base** passe à sa révision et y tient ses tables ; la sauvegarde la garde ;
- **ses comptes** : rangés comme les réglages les disent, leur synchro (faite, manquée — ses échecs comptés, l'erreur
  en mots), ceux en panne pour la santé (pas un compte décoché), retirés avec tout ce qu'ils portaient ;
- **ses agendas** : ce que le fournisseur liste, ceux qui n'y sont plus partent avec leurs événements ;
- **une période**, sur plusieurs agendas, même parmi des milliers d'événements : ce qui la touche, les séries
  développées, une exception déplacée hors de la période y retire son occurrence ;
- **une synchronisation** : un delta range et retire, un lot complet retire ce qu'il ne nomme plus dans la fenêtre, ce
  qui la précède part, le curseur suit ; une ressource redonnée en entière perd les lignes qu'elle n'a plus ; ce que
  Mika a ajouté reste marqué quand le fournisseur le redit sans la marque ;
- **l'oubli** d'une adresse ou d'une personne : elle part des participantes ; ce qu'elle organisait garde son créneau,
  vidé de ses mots ; jamais dans l'agenda d'un compte à elle ; une synchronisation ne la ramène pas dans ce qui a été
  créé avant, ce qui naît après revient ;
- **ce qui change** se dit une fois l'écriture validée (le sujet ``agenda``, ses comptes et ses agendas), rien d'une
  écriture annulée.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import pytest

from mika.adapters.agenda import AgendaStore
from mika.app import backup, schema
from mika.ports import changes
from mika.ports.agenda import (
    BY_HER,
    DAY_US,
    NEEDS,
    US_PER_S,
    AddedBy,
    AgendaError,
    Calendar,
    Event,
    Participant,
    Recurrence,
    Span,
    SyncBatch,
    Window,
    calendar_key,
    instance,
    occurrence_key,
)
from tests.fixtures import backend

NOW = 1_795_000_000_000_000
HOUR = 3600 * US_PER_S
GOOGLE = "google-perso"
PERSO = calendar_key(GOOGLE, "perso")
TRAVAIL = calendar_key(GOOGLE, "travail")
MINE = "moi:user_1"
MON = calendar_key(MINE, "mon-agenda")


class Clock:
    def __init__(self) -> None:
        self.t = NOW

    def now(self) -> int:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    found = AgendaStore(backend.target(tmp_path, "agenda"), now=clock.now)
    found.keep_account(GOOGLE, "google", owner="", address="adrien@gmail.com")
    found.keep_calendars(GOOGLE, [Calendar(PERSO, GOOGLE, "adrien@gmail.com", "Perso", primary=True),
                                  Calendar(TRAVAIL, GOOGLE, "travail", "Travail")])
    found.keep_account(MINE, "systeme", owner="personne:user_1")
    found.add_calendar(Calendar(MON, MINE, "mon-agenda", "Mon agenda", primary=True))
    yield found
    found.close()


def event(uid: str, start: int, *, calendar: str = PERSO, hours: int = 1, title: str = "", **more) -> Event:
    return Event(calendar, uid, Span(start, start + hours * HOUR, "Europe/Paris"), title or uid, **more)


def titles(occ) -> list[str]:
    return [o.event.title for o in occ]


@pytest.mark.sqlite_only  # les fichiers d'un dossier ; sur un serveur, test_schema a sa variante
def test_the_base_reaches_its_revision_and_the_backup_keeps_it(tmp_path):
    schema.migrate_data(tmp_path)
    engine = schema.targets(tmp_path)["agenda"].engine()
    try:
        assert schema.differences("agenda", engine) == []
    finally:
        engine.dispose()
    rows = {r["nom"]: r for r in backup.place(tmp_path)}
    assert rows["agenda.db"]["sauvegarde"] == "oui" and "agendas" in rows["agenda.db"]["garde"]


def test_accounts_their_sync_and_what_health_reads(store, clock):
    assert [a.key for a in store.accounts()] == [GOOGLE, MINE]
    assert store.account(GOOGLE).address == "adrien@gmail.com"
    clock.t += 1
    failed = store.synced(GOOGLE, error="erreur d'un agenda : Google demande de te reconnecter")
    assert (failed.failures, failed.tried_at, failed.synced_at) == (1, NOW + 1, 0)
    assert store.synced(GOOGLE, error="encore").failures == 2 and store.failing() == [GOOGLE]
    store.keep_account(GOOGLE, "google", address="adrien@gmail.com", enabled=False)
    assert store.failing() == []  # décoché, il ne se compte pas
    store.keep_account(GOOGLE, "google", address="adrien@gmail.com")
    ok = store.synced(GOOGLE)
    assert (ok.failures, ok.error, ok.synced_at) == (0, "", NOW + 1) and store.failing() == []
    with pytest.raises(AgendaError):
        store.synced("inconnu")


def test_calendars_gone_from_the_provider_leave_with_their_events(store):
    store.save([event("a", NOW, calendar=TRAVAIL), event("b", NOW)])
    kept = store.keep_calendars(GOOGLE, [Calendar(PERSO, GOOGLE, "adrien@gmail.com", "Perso (renommé)",
                                                  primary=True)])
    assert [(c.key, c.name) for c in kept] == [(PERSO, "Perso (renommé)")]
    assert store.calendar(TRAVAIL) is None and store.find(TRAVAIL, "a") is None
    assert store.find(PERSO, "b") is not None
    with pytest.raises(AgendaError):
        store.keep_calendars(GOOGLE, [Calendar(MON, MINE, "x")])


def test_dropping_an_account_takes_everything_it_carried(store):
    store.save([event("a", NOW, participants=(Participant("lea@x.fr", "Léa"),))])
    assert store.drop_account(GOOGLE) >= 3
    assert store.account(GOOGLE) is None and store.calendars(GOOGLE) == [] and store.find(PERSO, "a") is None
    assert [a.key for a in store.accounts()] == [MINE]


def test_a_period_reads_several_calendars_and_their_series(store):
    point = event("point", NOW - 7 * DAY_US, calendar=MON, title="Point", recurrence=Recurrence("FREQ=DAILY;COUNT=30"))
    moved_key = occurrence_key(NOW + DAY_US, False)
    moved = replace(instance(point, moved_key), span=Span(NOW + 60 * DAY_US, NOW + 60 * DAY_US + HOUR))
    store.save([point, moved, event("dej", NOW + 2 * HOUR, title="Déjeuner"),
                event("vieux", NOW - 30 * DAY_US, calendar=TRAVAIL), event("loin", NOW + 90 * DAY_US)])
    got = store.period([MON, PERSO, TRAVAIL], NOW, NOW + 3 * DAY_US)
    # le Point d'aujourd'hui, le Déjeuner, le Point d'après-demain (celui de demain est déplacé au-delà)
    assert titles(got) == ["Point", "Déjeuner", "Point"]
    assert got[2].key == occurrence_key(NOW + 2 * DAY_US, False)
    assert titles(store.period([PERSO], NOW, NOW + 3 * DAY_US)) == ["Déjeuner"]
    later = store.period([MON], NOW + 59 * DAY_US, NOW + 61 * DAY_US)
    assert [(o.event.original, o.span.start) for o in later] == [(moved_key, NOW + 60 * DAY_US)]


def test_a_period_stays_quick_among_thousands_of_events(store):
    day = 24 * HOUR
    many = [event(f"e{i}", NOW - 200 * day + i * 3 * HOUR) for i in range(3000)]
    many += [event(f"s{i}", NOW - 365 * day + i * HOUR, calendar=TRAVAIL, recurrence=Recurrence("FREQ=WEEKLY"))
             for i in range(100)]
    store.save(many)
    began = time.perf_counter()
    week = store.period([PERSO, TRAVAIL], NOW, NOW + 7 * day)
    spent = time.perf_counter() - began
    assert len([o for o in week if o.event.calendar == TRAVAIL]) == 100
    assert len([o for o in week if o.event.calendar == PERSO]) == 56
    assert spent < 2.0, spent


def test_a_delta_keeps_and_removes_a_complete_batch_prunes_the_window(store, clock):
    window = Window(NOW - 90 * DAY_US, NOW + 365 * DAY_US)
    store.apply(PERSO, SyncBatch(events=(event("a", NOW), event("b", NOW + HOUR), event("old", NOW - 100 * DAY_US)),
                                 cursor="c1"), window=window)
    assert store.find(PERSO, "old") is None  # avant la fenêtre : il part
    assert store.calendar(PERSO).cursor == "c1"
    store.apply(PERSO, SyncBatch(events=(event("a", NOW, title="A changé"),), removed=(("b", ""),), cursor="c2"),
                window=window)
    assert titles(store.period([PERSO], NOW - DAY_US, NOW + DAY_US)) == ["A changé"]
    store.save([event("c", NOW + 2 * HOUR), event("far", NOW + 400 * DAY_US)])
    store.apply(PERSO, SyncBatch(events=(event("a", NOW, title="A"),), cursor="c3", complete=True), window=window)
    assert store.find(PERSO, "c") is None  # dans la fenêtre, plus nommé : il part
    assert store.find(PERSO, "far") is not None  # hors de la fenêtre : le lot n'en disait rien
    assert store.calendar(PERSO).cursor == "c3"


def test_a_resource_given_whole_loses_the_rows_it_no_longer_has(store):
    master = event("serie", NOW, remote="/dav/perso/serie.ics", recurrence=Recurrence("FREQ=DAILY;COUNT=5"))
    key = occurrence_key(NOW + DAY_US, False)
    moved = replace(instance(master, key), title="Déplacé", remote="/dav/perso/serie.ics")
    other = event("autre", NOW + 2 * HOUR, remote="/dav/perso/autre.ics")
    store.apply(PERSO, SyncBatch(events=(master, moved, other), cursor="t1"))
    # la ressource a perdu son exception : redonnée en entier, sa ligne part ; l'autre ressource ne bouge pas
    store.apply(PERSO, SyncBatch(events=(master,), replaced=("/dav/perso/serie.ics",), cursor="t2"))
    assert [r.original for r in store.series(PERSO, "serie")] == [""]
    assert store.find(PERSO, "autre") is not None
    # supprimée chez le fournisseur : redonnée sans ligne, tout part
    store.apply(PERSO, SyncBatch(replaced=("/dav/perso/serie.ics",), cursor="t3"))
    assert store.series(PERSO, "serie") == [] and store.calendar(PERSO).cursor == "t3"


def test_what_she_added_stays_marked_when_the_provider_says_it_again_without_the_mark(store):
    made = event("dejeuner", NOW, added=AddedBy(BY_HER, "fil:7", NOW))
    store.save([made])
    store.apply(PERSO, SyncBatch(events=(event("dejeuner", NOW, title="Déjeuner (relu)"),), cursor="t1"))
    again = store.find(PERSO, "dejeuner")
    assert again.title == "Déjeuner (relu)" and again.added == AddedBy(BY_HER, "fil:7", NOW)


def test_invitations_are_what_waits_for_the_account(store):
    store.save([event("inv", NOW + DAY_US, calendar=MON, response=NEEDS),
                event("passee", NOW - DAY_US, calendar=MON, response=NEEDS),
                event("oui", NOW + DAY_US, calendar=MON, response="oui")])
    assert [e.uid for e in store.invitations([MON])] == ["inv"]


def test_forgetting_an_address_keeps_the_slot_not_her_words(store, clock):
    claire = Participant("claire@lumen.fr", "Claire")
    org = event("hebdo", NOW + DAY_US, title="Point hebdo avec Claire", description="ordre du jour de Claire",
                organizer=claire, participants=(claire, Participant("adrien@gmail.com", "Adrien", me=True)),
                created=NOW - DAY_US)
    other = event("atelier", NOW + 2 * DAY_US, title="Atelier", organizer=Participant("marc@lumen.fr", "Marc"),
                  participants=(Participant("marc@lumen.fr"), claire), created=NOW - DAY_US)
    store.save([org, other])
    clock.t += 1
    assert asyncio.run(store.forget("mail:Claire@lumen.fr")) >= 3
    kept = store.find(PERSO, "hebdo")
    assert (kept.title, kept.description, kept.organizer, kept.forgotten) == ("", "", None, True)
    assert kept.span == org.span and kept.busy  # le créneau reste : on n'y est pas libre
    assert [p.address for p in kept.participants] == ["adrien@gmail.com"]
    assert [p.address for p in store.find(PERSO, "atelier").participants] == ["marc@lumen.fr"]
    # une synchronisation ne la ramène pas dans ce qui a été créé avant l'oubli
    store.apply(PERSO, SyncBatch(events=(org, other)))
    again = store.find(PERSO, "hebdo")
    assert again.title == "" and again.organizer is None and again.forgotten
    assert [p.address for p in store.find(PERSO, "atelier").participants] == ["marc@lumen.fr"]
    # ce qui naît après l'oubli revient : elle est de nouveau quelqu'un qu'on croise
    clock.t += 10
    fresh = replace(org, uid="neuf", title="Café avec Claire", created=clock.t)
    store.apply(PERSO, SyncBatch(events=(fresh,)))
    assert store.find(PERSO, "neuf").title == "Café avec Claire"


def test_an_oblivion_never_empties_an_account_of_the_one_forgotten(store):
    mine = event("moi", NOW + DAY_US, title="Mon rendez-vous", organizer=Participant("adrien@gmail.com", "Adrien"))
    store.save([mine])
    asyncio.run(store.forget("mail:adrien@gmail.com"))
    assert store.find(PERSO, "moi").title == "Mon rendez-vous"  # le compte de cette adresse est à lui


def test_forgetting_a_person_reaches_the_system_events(store):
    store.keep_account("moi:user_2", "systeme", owner="personne:user_2")
    theirs = calendar_key("moi:user_2", "mon-agenda")
    store.add_calendar(Calendar(theirs, "moi:user_2", "mon-agenda", "Mon agenda", primary=True))
    lea = Participant(person="user_2")
    store.save([event("dej", NOW + DAY_US, calendar=MON, title="Déjeuner", organizer=Participant(person="user_1"),
                      participants=(lea,)),
                event("sien", NOW + DAY_US, calendar=theirs, title="Son rendez-vous",
                      organizer=Participant(person="user_2")),
                event("invite", NOW + 2 * DAY_US, calendar=MON, title="Son invitation",
                      organizer=Participant(person="user_2"), origin=theirs, response=NEEDS)])
    asyncio.run(store.forget("user_2"))
    assert store.find(MON, "dej").participants == ()
    invited = store.find(MON, "invite")
    assert invited.title == "" and invited.organizer is None and invited.forgotten
    assert store.find(theirs, "sien").title == "Son rendez-vous"  # son agenda à elle reste, avec son compte


def test_what_changes_is_said_once_written_and_never_for_a_rollback(store):
    said: list[changes.Change] = []
    store.on_change(said.append)
    store.save([event("a", NOW)])
    assert said == [changes.Change(changes.AGENDA, accounts=(GOOGLE,), keys=(PERSO,))]
    said.clear()
    with pytest.raises(AgendaError):
        store.save([event("b", NOW), event("c", NOW, calendar="inconnu~x")])
    assert said == [] and store.find(PERSO, "b") is None
    store.set_cursor(PERSO, "c9")  # la tenue de la synchro : rien qu'un écran montre
    assert said == []
    store.synced(GOOGLE)
    assert said == [changes.Change(changes.AGENDA, accounts=(GOOGLE,))]


def test_a_calendar_no_longer_followed_loses_its_copy(store):
    store.apply(PERSO, SyncBatch(events=(event("a", NOW),), cursor="c1"))
    assert store.clear_calendar(PERSO) == 1
    cal = store.calendar(PERSO)
    assert cal is not None and (cal.cursor, cal.synced_at) == ("", 0) and store.find(PERSO, "a") is None
