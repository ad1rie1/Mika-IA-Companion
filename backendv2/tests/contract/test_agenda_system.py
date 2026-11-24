"""Le fournisseur Système (ADR 0309) : l'agenda de ce serveur, dont les événements font foi dans la base.

- chaque personne qui a un compte a « Mon agenda » sans rien faire, et en crée d'autres ;
- une série se change pour cet événement (une exception), à partir de lui (la série coupée, la suite sous un nouvel UID,
  ses exceptions avec elle) ou en entier (depuis une occurrence, elle garde son premier jour et prend l'heure ; ses
  exceptions suivent ce qu'elles tenaient d'elle) ; supprimer une occurrence l'ajoute aux EXDATE ;
- une invitation entre deux personnes qui ont un compte arrive dans « Mon agenda » de l'invitée, en attente de sa
  réponse ; sa réponse revient à l'organisatrice ; refusée, elle ne se montre plus dans sa grille ; supprimée de son
  agenda, elle est refusée ; elle ne se modifie que chez qui l'organise, et ce qui y change la suit ;
- une invitée retirée de la série perd sa copie ; retirée d'une occurrence, elle l'y voit annulée.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mika.adapters.agenda import AgendaStore, Providers
from mika.ports.agenda import (
    ALL,
    BY_HER,
    CANCELLED,
    FOLLOWING,
    MAYBE,
    NEEDS,
    NO,
    ONE,
    US_PER_S,
    YES,
    AddedBy,
    AgendaError,
    EventChange,
    EventDraft,
    Participant,
    Span,
    at_us,
    occurrence_key,
    us_of,
)
from tests.fixtures import backend

PARIS = ZoneInfo("Europe/Paris")
NOW = us_of(datetime(2026, 11, 23, 14, 20, tzinfo=PARIS))
HOUR = 3600 * US_PER_S


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def run(coro):
    return asyncio.run(coro)


class World:
    def __init__(self, tmp) -> None:
        self.store = AgendaStore(backend.target(tmp, "agenda"), now=lambda: NOW)
        self.providers = Providers(self.store)
        self.system = self.providers.system
        self.adrien = self.providers.connection("moi:user_1")
        self.lea = self.providers.connection("moi:user_2")
        self.mon = self.system.default_calendar("user_1")
        self.sien = self.system.default_calendar("user_2")

    def grid(self, calendar, start=None, end=None, **kw):
        start = paris(2026, 11, 1) if start is None else start
        end = paris(2027, 1, 1) if end is None else end
        return [(o.event.title, at_us(o.span.start, PARIS).strftime("%d/%m %H:%M"), o.event.response)
                for o in self.store.period([calendar.key], start, end, **kw)]


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.store.close()


def draft(title: str, start: int, *, hours: int = 1, rule: str = "", people=(), **more) -> EventDraft:
    return EventDraft(title, Span(start, start + hours * HOUR, "Europe/Paris"), rule=rule,
                      participants=tuple(people), **more)


def test_each_person_has_my_agenda_and_creates_others(world):
    assert (world.mon.name, world.mon.primary, world.mon.account) == ("Mon agenda", True, "moi:user_1")
    assert world.store.account("moi:user_1").owner == "personne:user_1"
    sport = run(world.system.create_calendar(world.adrien, "Sport"))
    assert sport.account == "moi:user_1" and not sport.primary
    assert [c.name for c in run(world.system.calendars(world.adrien))] == ["Mon agenda", "Sport"]
    with pytest.raises(AgendaError):
        run(world.system.create_calendar(world.adrien, "  "))


def test_what_mika_added_is_marked(world):
    e = run(world.system.create(world.adrien, world.mon, draft(
        "Dentiste", paris(2026, 11, 24, 17, 30), added=AddedBy(BY_HER, "chat:user_1:42", NOW))))
    assert e.added == AddedBy(BY_HER, "chat:user_1:42", NOW) and e.organizer.person == "user_1"
    with pytest.raises(AgendaError):  # pas dans l'agenda d'une autre
        run(world.system.create(world.adrien, world.sien, draft("Intrus", NOW)))


def test_a_series_changes_for_one_from_one_or_for_all(world):
    point = run(world.system.create(world.adrien, world.mon, draft(
        "Point", paris(2026, 11, 2, 9), rule="FREQ=WEEKLY;COUNT=6")))
    second = occurrence_key(paris(2026, 11, 9, 9), False)
    run(world.system.edit(world.adrien, world.mon, point, second,
                          EventChange(title="Point (salle 3)", span=Span(paris(2026, 11, 10, 15), paris(2026, 11, 10, 16),
                                                                          "Europe/Paris")), ONE))
    assert world.grid(world.mon)[:3] == [("Point", "02/11 09:00", ""), ("Point (salle 3)", "10/11 15:00", ""),
                                         ("Point", "16/11 09:00", "")]
    # pour toutes, depuis une occurrence : la série garde son premier jour, prend l'heure ; l'exception déplacée reste
    run(world.system.edit(world.adrien, world.mon, point, occurrence_key(paris(2026, 11, 16, 9), False),
                          EventChange(title="Point hebdo", span=Span(paris(2026, 11, 16, 10), paris(2026, 11, 16, 11),
                                                                     "Europe/Paris")), ALL))
    assert world.grid(world.mon) == [
        ("Point hebdo", "02/11 10:00", ""), ("Point (salle 3)", "10/11 15:00", ""), ("Point hebdo", "16/11 10:00", ""),
        ("Point hebdo", "23/11 10:00", ""), ("Point hebdo", "30/11 10:00", ""), ("Point hebdo", "07/12 10:00", "")]
    # à partir d'une occurrence : la série coupée, la suite sous un nouvel UID, le compte des occurrences gardé
    head = world.store.find(world.mon.key, point.uid)
    rest = run(world.system.edit(world.adrien, world.mon, head, occurrence_key(paris(2026, 11, 30, 10), False),
                                 EventChange(location="Salle du conseil"), FOLLOWING))
    assert rest.uid != point.uid and rest.recurrence.rule.endswith("COUNT=2")
    assert [(t, w) for t, w, _ in world.grid(world.mon)][-2:] == [("Point hebdo", "30/11 10:00"),
                                                                   ("Point hebdo", "07/12 10:00")]
    assert len(world.grid(world.mon)) == 6
    assert world.store.find(world.mon.key, point.uid).recurrence.rule.startswith("FREQ=WEEKLY;UNTIL=")
    # supprimer une occurrence : une EXDATE
    run(world.system.delete(world.adrien, world.mon, head, occurrence_key(paris(2026, 11, 23, 10), False), ONE))
    assert [w for _, w, _ in world.grid(world.mon)] == ["02/11 10:00", "10/11 15:00", "16/11 10:00", "30/11 10:00",
                                                        "07/12 10:00"]


def test_an_occurrence_that_no_longer_exists_is_refused_not_made_up(world):
    point = run(world.system.create(world.adrien, world.mon, draft(
        "Point", paris(2026, 11, 2, 9), rule="FREQ=WEEKLY;COUNT=4", people=[Participant(person="user_2")])))
    stale = occurrence_key(paris(2026, 11, 9, 9), False)  # gardée par un écran resté ouvert
    run(world.system.edit(world.adrien, world.mon, point, stale, EventChange(span=Span(
        paris(2026, 11, 9, 10), paris(2026, 11, 9, 11), "Europe/Paris")), ALL))
    series = world.store.find(world.mon.key, point.uid)
    for scope in (ONE, FOLLOWING):
        with pytest.raises(AgendaError, match="n'existe plus"):
            run(world.system.edit(world.adrien, world.mon, series, stale, EventChange(title="Fantôme"), scope))
    copy = world.store.find(world.sien.key, point.uid)
    with pytest.raises(AgendaError, match="n'existe plus"):
        run(world.system.respond(world.lea, world.sien, copy, stale, NO, ONE))
    assert all(w.endswith("10:00") for _, w, _ in world.grid(world.mon))  # aucun rendez-vous à 9 h n'apparaît
    assert all(w.endswith("10:00") for _, w, _ in world.grid(world.sien))
    moved = occurrence_key(paris(2026, 11, 16, 10), False)  # une vraie occurrence se change toujours
    run(world.system.edit(world.adrien, world.mon, series, moved, EventChange(title="Point (salle 3)"), ONE))
    assert ("Point (salle 3)", "16/11 10:00", "") in world.grid(world.mon)


def test_an_invitation_arrives_in_her_agenda_and_her_answer_comes_back(world):
    dej = run(world.system.create(world.adrien, world.mon, draft(
        "Déjeuner", paris(2026, 11, 25, 12, 30), people=[Participant(person="user_2"),
                                                          Participant("julien@x.fr", "Julien")])))
    assert world.grid(world.sien) == [("Déjeuner", "25/11 12:30", NEEDS)]
    invitation = world.store.invitations([world.sien.key])[0]
    assert invitation.origin == world.mon.key and invitation.organizer.person == "user_1"
    assert [p.me for p in invitation.participants] == [True, False]
    run(world.system.respond(world.lea, world.sien, invitation, "", MAYBE))
    theirs = {p.person or p.address: p.response for p in world.store.find(world.mon.key, dej.uid).participants}
    assert theirs == {"user_2": MAYBE, "julien@x.fr": NEEDS}
    assert world.grid(world.sien) == [("Déjeuner", "25/11 12:30", MAYBE)]
    # l'organisatrice change l'heure : la copie suit, sa réponse reste
    run(world.system.edit(world.adrien, world.mon, dej, "", EventChange(span=Span(
        paris(2026, 11, 25, 13), paris(2026, 11, 25, 14), "Europe/Paris"))))
    assert world.grid(world.sien) == [("Déjeuner", "25/11 13:00", MAYBE)]
    # refusée : elle ne se montre plus dans sa grille ; elle reste lisible si on la demande
    run(world.system.respond(world.lea, world.sien, invitation, "", NO))
    assert world.grid(world.sien) == [] and len(world.grid(world.sien, declined=True)) == 1
    # elle ne la modifie pas ; elle ne répond que oui, peut-être ou non
    with pytest.raises(AgendaError):
        run(world.system.edit(world.lea, world.sien, invitation, "", EventChange(title="À moi")))
    with pytest.raises(AgendaError):
        run(world.system.respond(world.lea, world.sien, invitation, "", "bof"))
    with pytest.raises(AgendaError):  # l'organisatrice ne répond pas à son propre événement
        run(world.system.respond(world.adrien, world.mon, dej, "", YES))


def test_deleting_an_invitation_declines_it_and_the_organizer_deleting_takes_it_away(world):
    run(world.system.create(world.adrien, world.mon, draft("Afterwork", paris(2026, 11, 26, 18, 30),
                                                           people=[Participant(person="user_2")])))
    invitation = world.store.invitations([world.sien.key])[0]
    run(world.system.delete(world.lea, world.sien, invitation, ""))
    assert world.grid(world.sien) == []
    mine = world.store.find(world.mon.key, invitation.uid)
    assert [p.response for p in mine.participants] == [NO] and world.grid(world.mon)[0][0] == "Afterwork"
    run(world.system.delete(world.adrien, world.mon, mine, ""))
    assert world.grid(world.mon) == [] and world.grid(world.sien, declined=True) == []
    with pytest.raises(AgendaError):  # ce qui n'est plus ne renaît pas d'une copie périmée
        run(world.system.edit(world.adrien, world.mon, mine, "", EventChange(title="Afterwork (bis)")))
    assert world.grid(world.mon) == []


def test_an_invited_series_answers_one_occurrence_or_all(world):
    yoga = run(world.system.create(world.adrien, world.mon, draft(
        "Yoga", paris(2026, 11, 2, 19), rule="FREQ=WEEKLY;COUNT=3", people=[Participant(person="user_2")])))
    copy = world.store.find(world.sien.key, yoga.uid)
    run(world.system.respond(world.lea, world.sien, copy, occurrence_key(paris(2026, 11, 9, 19), False), NO, ONE))
    assert [(w, r) for _, w, r in world.grid(world.sien)] == [("02/11 19:00", NEEDS), ("16/11 19:00", NEEDS)]
    run(world.system.respond(world.lea, world.sien, copy, "", YES, ALL))
    assert [r for _, _, r in world.grid(world.sien)] == [YES, YES, YES]
    with pytest.raises(AgendaError):
        run(world.system.respond(world.lea, world.sien, copy, occurrence_key(paris(2026, 11, 9, 19), False), YES,
                                 FOLLOWING))


def test_a_guest_removed_from_one_occurrence_sees_it_cancelled_and_from_the_series_loses_it(world):
    lea = Participant(person="user_2")
    yoga = run(world.system.create(world.adrien, world.mon, draft(
        "Yoga", paris(2026, 11, 2, 19), rule="FREQ=WEEKLY;COUNT=3", people=[lea])))
    second = occurrence_key(paris(2026, 11, 9, 19), False)
    run(world.system.edit(world.adrien, world.mon, yoga, second, EventChange(participants=()), ONE))
    assert [w for _, w, _ in world.grid(world.sien)] == ["02/11 19:00", "16/11 19:00"]
    cancelled = world.store.find(world.sien.key, yoga.uid, second)
    assert cancelled is not None and cancelled.status == CANCELLED
    run(world.system.edit(world.adrien, world.mon, yoga, "", EventChange(participants=()), ALL))
    assert world.grid(world.sien) == [] and world.store.copies(world.mon.key, yoga.uid) == []


def test_a_system_account_is_one_of_a_person(world):
    with pytest.raises(AgendaError):
        world.system.ensure("google-perso")
    assert world.providers.connection("google-perso") is None
    assert world.providers.connection("moi:user_9").owner == "personne:user_9"
    assert world.providers.of("systeme") is world.system and world.providers.of("google") is None
