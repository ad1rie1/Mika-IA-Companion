"""La collecte de l'annuaire (ADR 0298), ``contacts.ingest`` : sur le vrai cache de Teams, le vrai courrier et le vrai
annuaire, un passage à la main (un cadre et des ports jouets autour).

- **ce qu'elle lit devient l'annuaire** : les auteurs Teams de chaque compte, les correspondants de chaque boîte, une
  organisation par domaine (son adresse générique y va) — et un passage de plus ne compte rien deux fois ;
- **relier sur preuve** : l'identifiant d'un compte Teams et l'adresse d'une boîte sont sa personne, reliée quand elle
  est une seule ; jamais un compte à elle, jamais un lien posé avant défait ;
- **un compte supprimé des réglages** : ce qu'il avait apporté s'efface ;
- **quand** : au démarrage, peu après un message remarqué, vite tant qu'il en reste, sinon lentement.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.app.composition import faculties
from mika.contracts import email as email_c
from mika.contracts import identity as identity_c
from mika.contracts import phone as phone_c
from mika.contracts import teams as teams_c
from mika.plugins.contacts import CONTACTS, ContactsState, _heard
from mika.plugins.contacts import ingest as ingest_m
from mika.plugins.contacts.ingest import BUSY_EVERY, IDLE_EVERY, WAKE_GAP, Ingest
from mika.ports.contacts import EMAIL, MAIL, ORG, PERSON_KIND, TEAMS, TEAMS_ID, Observation
from mika.ports.mail import Mail
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
MS = NOW // 1000
GROUP = "19:projet@thread.v2"


class Frame:
    def __init__(self, owners: tuple[str, ...], now: int = NOW) -> None:
        self.owners, self.now = owners, now

    def get(self, key):
        return self.owners if key == identity_c.OWNERS else None


class World:
    """Les ports d'un passage : Teams, le courrier, l'annuaire, réglés comme une opératrice le ferait."""

    def __init__(self, tmp, *, teams_accounts=None, boxes=None, owners=("user_1",)) -> None:
        self.teams_cfg = TeamsConfig(accounts=teams_accounts or {
            "adrien": TeamsAccount(owner="personne:user_1"), "sien": TeamsAccount(owner="elle")})
        self.mail_cfg = MailConfig(accounts=boxes or {"pro": MailAccount(address="adrien@nordis.fr")})
        self.teams = TeamsStore(lambda: self.teams_cfg, tmp / "teams.db", now=lambda: NOW)
        self.mail = ImapSmtpMail(lambda: self.mail_cfg, tmp / "mail.db")
        self.contacts = ContactsStore(backend.target(tmp, "contacts"), now=lambda: NOW)
        self.owners = owners
        self.heard = 0

    def ctx(self, *, contacts: bool = True) -> SimpleNamespace:
        ports = {"teams": self.teams, "mail": self.mail, **({"contacts": self.contacts} if contacts else {})}
        return SimpleNamespace(state=ContactsState(heard=self.heard), ports=ports, frame=Frame(self.owners),
                               now=NOW)

    def push(self, account: str, self_id: str, *messages: InboxMessage, now: int = NOW) -> None:
        self.teams.store_batch(account, InboxBatch(self_id=self_id, self_name=self_id.split(":")[-1].title(),
                                                   conversations=(InboxConversation(GROUP, "Projet", "group"),),
                                                   messages=messages), now)

    def receive(self, mid: str, sender: str, address: str, uid: int, at: int = NOW) -> None:
        self.mail._cache.store(Mail(mid, sender, address, "objet", at, "texte", to="adrien@nordis.fr",
                                    account="pro", folder="INBOX"), uid)

    def close(self) -> None:
        self.teams.close()
        self.mail._cache.close()
        self.contacts.close()


@pytest.fixture
def world(tmp_path):
    found = World(tmp_path)
    yield found
    found.close()


def run(process: Ingest, world: World, **kw) -> None:
    asyncio.run(process.run(world.ctx(**kw)))


def by_name(world: World, **kw) -> dict[str, object]:
    return {line.name: line for line in world.contacts.page(size=100, **kw).items}


def test_what_she_reads_becomes_the_directory_and_a_second_pass_counts_nothing_twice(world):
    world.push("adrien", "8:orgid:adrien",
               InboxMessage("1", GROUP, "Gilles Rousseau", "8:orgid:gilles", MS, "bonjour"),
               InboxMessage("2", GROUP, "Adrien", "8:orgid:adrien", MS + 1, "salut", own=True),
               InboxMessage("3", GROUP, "Gilles Rousseau", "8:orgid:gilles", MS + 2, "ça va ?"))
    world.push("sien", "8:orgid:mika", InboxMessage("4", GROUP, "Léa Martin", "8:orgid:lea", MS + 3, "coucou"))
    world.receive("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", 1)
    world.receive("<b@x>", "Nordis <noreply@nordis.fr>", "noreply@nordis.fr", 2)
    process = Ingest()
    run(process, world)
    people = by_name(world, kind=PERSON_KIND)
    assert set(people) == {"Gilles Rousseau", "Léa Martin", "Adrien", "adrien@nordis.fr"}
    gilles_teams = world.contacts.contact_of(TEAMS_ID, "8:orgid:gilles")
    assert world.contacts.sheet(gilles_teams).identifiers[0].sightings[0].count == 2  # ses deux messages, pas le tien
    # la personne d'un compte à elle n'est pas rangée (ce serait elle) ; ce que son compte lit, si
    assert world.contacts.contact_of(TEAMS_ID, "8:orgid:mika") is None
    assert world.contacts.contact_of(TEAMS_ID, "8:orgid:lea") is not None
    # une organisation par domaine, son adresse générique rangée chez elle
    (org,) = world.contacts.page(kind=ORG).items
    assert org.name == "nordis.fr"
    assert {i.value for i in world.contacts.sheet(org.id).identifiers} == {"nordis.fr", "noreply@nordis.fr"}
    # un même nom ne réunit pas : il se propose
    assert [(s.a.name, s.b.name) for s in world.contacts.suggestions()] == [("Gilles Rousseau", "Gilles Rousseau")]
    before = {line.id: line.seen for line in world.contacts.page(size=100).items}
    run(process, world)
    assert {line.id: line.seen for line in world.contacts.page(size=100).items} == before
    world.push("adrien", "8:orgid:adrien", InboxMessage("5", GROUP, "Gilles Rousseau", "8:orgid:gilles", MS + 9, "re"))
    run(process, world)
    assert world.contacts.sheet(gilles_teams).identifiers[0].sightings[0].count == 3


def test_an_account_designates_its_person_linked_when_she_is_the_only_one(world):
    world.push("adrien", "8:orgid:adrien")
    run(Ingest(), world)
    teams_self = world.contacts.sheet(world.contacts.contact_of(TEAMS_ID, "8:orgid:adrien"))
    assert teams_self.person == "user_1"  # « personne:user_1 »
    (sight,) = teams_self.identifiers[0].sightings
    assert (sight.source, sight.account, sight.own, sight.count) == (TEAMS, "adrien", True, 0)
    box_self = world.contacts.sheet(world.contacts.contact_of(EMAIL, "adrien@nordis.fr"))
    assert box_self.person == "user_1"  # « à toi », et tu es la seule propriétaire
    assert box_self.identifiers[0].sightings[0].source == MAIL


def test_nobody_is_linked_when_the_owner_is_not_a_single_person_and_no_link_is_undone(tmp_path):
    world = World(tmp_path, owners=("user_1", "user_2"),
                  teams_accounts={"commun": TeamsAccount(owner=""), "bea": TeamsAccount(owner="personne:user_3")})
    try:
        world.push("commun", "8:orgid:commun")
        world.push("bea", "8:orgid:bea")
        box = world.contacts
        run(Ingest(), world)
        assert box.sheet(box.contact_of(TEAMS_ID, "8:orgid:commun")).person == ""  # à toi, mais vous êtes deux
        assert box.sheet(box.contact_of(EMAIL, "adrien@nordis.fr")).person == ""
        assert box.sheet(box.contact_of(TEAMS_ID, "8:orgid:bea")).person == "user_3"
        box.link(box.contact_of(TEAMS_ID, "8:orgid:bea"), "user_9")  # une opératrice l'a relié autrement
        world.teams_cfg = TeamsConfig(accounts={"bea": TeamsAccount(owner="personne:user_4")})
        run(Ingest(), world)
        assert box.sheet(box.contact_of(TEAMS_ID, "8:orgid:bea")).person == "user_9"
    finally:
        world.close()


def test_an_account_removed_from_the_settings_takes_away_what_it_brought(world):
    world.push("adrien", "8:orgid:adrien", InboxMessage("1", GROUP, "Gilles", "8:orgid:gilles", MS, "x"))
    process = Ingest()
    run(process, world)
    assert (TEAMS, "adrien") in world.contacts.sources()
    world.teams_cfg = TeamsConfig(accounts={"sien": TeamsAccount(owner="elle")})
    world.mail_cfg = MailConfig(accounts={})
    run(process, world)
    assert world.contacts.sources() == [] and world.contacts.page().total == 0


def test_without_the_directory_a_pass_does_nothing(world):
    world.push("adrien", "8:orgid:adrien", InboxMessage("1", GROUP, "Gilles", "8:orgid:gilles", MS, "x"))
    process = Ingest()
    run(process, world, contacts=False)
    assert process.handled == 0 and not process.busy and world.contacts.page().total == 0


def test_a_long_backlog_is_read_in_bounded_passes_that_come_back_soon(world, monkeypatch):
    monkeypatch.setattr(ingest_m, "BATCH", 2)
    monkeypatch.setattr(ingest_m, "READS_PER_RUN", 1)
    world.push("adrien", "8:orgid:adrien", *(InboxMessage(str(n), GROUP, f"Auteur {n}", f"8:orgid:{n}", MS + n, "x")
                                             for n in range(5)))
    process = Ingest()
    run(process, world)
    assert process.busy
    frame = Frame(())
    assert process.next_due(ContactsState(), frame, NOW) == NOW + BUSY_EVERY
    for _ in range(3):
        run(process, world)
    assert not process.busy
    assert {f"Auteur {n}" for n in range(5)} <= set(by_name(world))


def test_it_runs_at_start_soon_after_a_noticed_message_and_slowly_otherwise():
    process, frame = Ingest(), Frame(())
    assert process.next_due(ContactsState(), frame, None) == NOW  # au démarrage
    process.handled, process.done_at = 3, NOW - 1
    assert process.next_due(ContactsState(heard=3), frame, NOW - 1) == NOW - 1 + IDLE_EVERY
    assert process.next_due(ContactsState(heard=4), frame, NOW - 1) == NOW - 1 + WAKE_GAP  # une rafale : un passage
    process.done_at = NOW - 60 * WAKE_GAP
    assert process.next_due(ContactsState(heard=4), frame, NOW - 60 * WAKE_GAP) == NOW


def test_the_plugin_is_composed_wakes_on_what_is_noticed_and_counts_it():
    assert CONTACTS in faculties()
    spec = next(s for s in CONTACTS.processes if s.name == "contacts.ingest")
    # le téléphone et les noms reliés aussi (lot 5)
    assert spec.name == "contacts.ingest" and spec.wake_on == {teams_c.NOTICED.name, email_c.NOTICED.name,
                                                                phone_c.RECEIVED.name, identity_c.NAME_BOUND.name}
    assert identity_c.OWNERS.name in spec.reads
    assert _heard(ContactsState(heard=2), None, None) == ContactsState(heard=3)


def test_she_is_never_a_contact_of_anyone_and_what_was_kept_of_her_leaves(tmp_path):
    """Relecture I8 : Mika écrit depuis sa boîte (à elle) à la boîte d'Adrien, et dans le Teams d'Adrien depuis son
    compte Teams (à elle). Avant, son adresse et son identifiant Teams devenaient des personnes « connues de loin »
    d'Adrien (seuls ses profils étaient écartés), portraiturées et redites par ``contacts_lookup``. Ce qui en avait été
    rangé part au passage suivant."""
    world = World(tmp_path, boxes={"pro": MailAccount(address="adrien@nordis.fr"),
                                   "siens": MailAccount(address="mika@nordis.fr", owner="elle")})
    try:
        # ce qu'un passage d'avant avait rangé d'elle
        world.contacts.observe_now([
            Observation(EMAIL, "mika@nordis.fr", MAIL, "pro", "Mika", 2, NOW, NOW),
            Observation(TEAMS_ID, "8:orgid:mika", TEAMS, "adrien", "Mika", 1, NOW, NOW)])
        world.push("sien", "8:orgid:mika")
        world.push("adrien", "8:orgid:adrien", InboxMessage("1", GROUP, "Mika", "8:orgid:mika", MS, "c'est fait"),
                   InboxMessage("2", GROUP, "Gilles", "8:orgid:gilles", MS + 1, "merci"))
        world.receive("<m@x>", "Mika <mika@nordis.fr>", "mika@nordis.fr", 1)
        world.receive("<g@x>", "Gilles <gilles@nordis.fr>", "gilles@nordis.fr", 2)
        run(Ingest(), world)
        assert world.contacts.contact_of(EMAIL, "mika@nordis.fr") is None
        assert world.contacts.contact_of(TEAMS_ID, "8:orgid:mika") is None
        assert world.contacts.contact_of(TEAMS_ID, "8:orgid:gilles") is not None
        assert world.contacts.contact_of(EMAIL, "gilles@nordis.fr") is not None
        assert "Mika" not in by_name(world)
    finally:
        world.close()
