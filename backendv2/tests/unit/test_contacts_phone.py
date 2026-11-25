"""Le téléphone dans l'annuaire (ADR 0298, lot 5) : les expéditeurs des messages WhatsApp et SMS, sur le vrai annuaire
et le vrai plugin, le journal en doublure (``get_events``, ``content``).

- **ce que le téléphone montre devient l'annuaire** : chaque expéditeur (``PHONE_APP``, sa clé sans son nom : renommé,
  il reste le même), contact de la personne dont c'est le téléphone, ses conversations (un groupe et son nom) ; ses
  propres messages ne comptent pas, un passage de plus ne compte rien deux fois ;
- **à qui** : au propriétaire du téléphone seulement (``person_accounts``, ``visible_sources``) ;
- **un numéro** : un expéditeur que le téléphone ne nomme que par son numéro est ce numéro ; rangé en E.164, il
  retrouve celui d'un profil Teams, dans un sens comme dans l'autre ; deux fiches qui ont un nom ne se réunissent
  jamais par un numéro ;
- **le même sur WhatsApp et par SMS** : deux identifiants, un rapprochement proposé, jamais réuni seul ;
- **l'oubli** : la clé d'un expéditeur, la personne dont c'est le téléphone.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.contracts import identity as identity_c
from mika.contracts import phone as phone_c
from mika.plugins.contacts import PHONE_KEPT, ContactsState, _phoned
from mika.plugins.contacts.ingest import CURSOR_PHONE, Ingest
from mika.ports.contacts import (
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    SMS,
    TEAMS,
    TEAMS_ID,
    WHATSAPP,
    Observation,
    e164,
    normalized,
    number_in_name,
    person_accounts,
    phone_app_value,
    visible_sources,
)
from mika.ports.store import StoredEvent
from mika.vocab.access import PERSON
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
ADRIEN, BEA = "user_1", "user_2"
GROUP = "f00dfeedf00dfeed"
DUO = "abcdefabcdefabcd"


def sender(person: str, app: str, key: str, name: str) -> str:
    """La clé d'un expéditeur, comme la porte du téléphone la forme (``app/domains/phone/desk.py``)."""
    digest = phone_c.contact_hash(person, app, key)
    return phone_c.contact_key(digest, name)


class Journal:
    """Le journal tel que la collecte le lit : des ``phone.received`` (enveloppes, contenus en références)."""

    def __init__(self) -> None:
        self.events: dict[int, StoredEvent] = {}
        self.texts: dict[str, str] = {}
        self.seq = 100

    def received(self, recipient: str, app: str, key: str, name: str, *, thread: str = DUO, title: str = "",
                 own: bool = False, at: int = NOW, first_name: str = "") -> int:
        self.seq += 1
        refs = {}
        for field, text in (("sender_name", name), ("title", title), ("text", "bonjour")):
            if text and not (own and field == "sender_name"):
                ref = f"c{self.seq}{field}"
                self.texts[ref] = text
                refs[field] = {"ref": ref}
        data = {"recipient": recipient, "handle": recipient, "source": app, "thread": thread,
                "sender": "" if own else sender(recipient, app, key, first_name or name), "group": bool(title),
                "own": own, "sent_at": at, **refs}
        self.events[self.seq] = StoredEvent(self.seq, f"e{self.seq}", phone_c.RECEIVED.name, 1, at, None, "c", 0,
                                            "external", json.dumps(data))
        return self.seq

    def get_events(self, seqs):
        return [self.events[s] for s in seqs if s in self.events]

    def content(self, refs):
        return {r: self.texts[r] for r in refs if r in self.texts}

    def query_mind(self, sql, params=()):
        return []  # sa mémoire n'a rien sur personne (``test_contacts_told``)


class World:
    def __init__(self, tmp) -> None:
        self.contacts = ContactsStore(backend.target(tmp, "contacts"), now=lambda: NOW + 10**9)
        self.journal = Journal()
        self.state = ContactsState()

    def heard(self, *seqs: int) -> None:
        """Ce que la tranche garde : chaque ``phone.received`` passe par son réducteur."""
        for seq in seqs:
            event = self.journal.events[seq]
            data = json.loads(event.data)
            e = SimpleNamespace(seq=seq, at=data["sent_at"], data=SimpleNamespace(
                own=data["own"], sender=data["sender"], recipient=data["recipient"], source=data["source"],
                thread=data["thread"], sent_at=data["sent_at"]))
            self.state = _phoned(self.state, e, None)

    def run(self, process: Ingest | None = None) -> Ingest:
        process = process or Ingest()
        ctx = SimpleNamespace(state=self.state, ports={"contacts": self.contacts, "store": self.journal},
                              frame=SimpleNamespace(get=lambda key: () if key == identity_c.OWNERS else None),
                              now=NOW)
        asyncio.run(process.run(ctx))
        return process


@pytest.fixture
def world(tmp_path):
    found = World(tmp_path)
    yield found
    found.contacts.close()


def test_numbers_are_kept_in_e164_when_a_french_number_is_unambiguous():
    for raw in ("06 12 34 56 78", "06.12.34.56.78", "+33 6 12 34 56 78", "+33 (0)6 12 34 56 78", "0033 6 12 34 56 78",
                "0612345678"):
        assert e164(raw) == "+33612345678", raw
        assert normalized(PHONE, raw) == "+33612345678", raw
    assert e164("+44 20 7946 0958") == "+442079460958"  # un indicatif : gardé
    assert e164("01 23 45 67 89") == "+33123456789"
    assert e164("112") == "112" and e164("3631") == "3631"  # un numéro court reste ses chiffres
    assert e164("00 12") == "0012" and e164("") == "" and e164("pas de numéro") == ""
    assert number_in_name("+33 6 12 34 56 78") == "+33612345678"
    assert number_in_name("06 12 34 56 78") == "+33612345678"
    assert number_in_name("Gilles") == "" and number_in_name("Gilles 06") == "" and number_in_name("12") == ""
    assert phone_app_value("whatsapp", "phone:3fa9c2d81b0e:Léa") == "whatsapp:3fa9c2d81b0e"
    assert phone_app_value("whatsapp", "user_1") == "" and phone_app_value("", "phone:3fa9c2d81b0e:Léa") == ""


def test_what_the_phone_shows_becomes_the_directory_and_a_second_pass_counts_nothing_twice(world):
    j = world.journal
    seqs = [j.received(ADRIEN, "whatsapp", "k-gilles", "Gilles Nordis", at=NOW - 3),
            j.received(ADRIEN, "whatsapp", "k-gilles", "Gilles Nordis", at=NOW - 2),
            j.received(ADRIEN, "whatsapp", "", "", own=True, at=NOW - 1),  # le sien : rien
            j.received(ADRIEN, "whatsapp", "k-lea", "Léa", thread=GROUP, title="Famille", at=NOW)]
    world.heard(*seqs)
    assert world.state.phone == (seqs[0], seqs[1], seqs[3])  # ses propres messages ne sont pas gardés
    process = world.run()
    gilles_key = sender(ADRIEN, "whatsapp", "k-gilles", "Gilles Nordis")
    gilles = world.contacts.contact_of(PHONE_APP, phone_app_value("whatsapp", gilles_key))
    sheet = world.contacts.sheet(gilles)
    assert sheet.name == "Gilles Nordis" and sheet.person == ""  # connu de loin, jamais une interlocutrice
    (ident,) = sheet.identifiers
    (sight,) = ident.sightings
    assert (sight.source, sight.account, sight.count, sight.name) == (PHONE_SOURCE, ADRIEN, 2, "Gilles Nordis")
    assert [(t.key, t.group, t.count) for t in sight.threads] == [(DUO, False, 2)]
    lea = world.contacts.sheet(world.contacts.contact_of(
        PHONE_APP, phone_app_value("whatsapp", sender(ADRIEN, "whatsapp", "k-lea", "Léa"))))
    (thread,) = lea.identifiers[0].sightings[0].threads
    assert (thread.title, thread.group, thread.count) == ("Famille", True, 1)
    # la page de l'annuaire dit l'appli de chacun
    lines = {c.name: c for c in world.contacts.page(size=50).items}
    assert lines["Gilles Nordis"].apps == ((WHATSAPP, 2),) and lines["Gilles Nordis"].sources == (PHONE_SOURCE,)
    assert world.contacts.cursor(CURSOR_PHONE) == seqs[3]
    before = {c.id: c.seen for c in world.contacts.page(size=50).items}
    world.run(process)
    assert {c.id: c.seen for c in world.contacts.page(size=50).items} == before
    # renommé dans le carnet : le même identifiant, le nouveau nom
    renamed = j.received(ADRIEN, "whatsapp", "k-gilles", "Gilles (Nordis)", at=NOW + 5, first_name="Gilles Nordis")
    world.heard(renamed)
    world.run(process)
    again = world.contacts.sheet(gilles)
    assert again.name == "Gilles (Nordis)" and again.identifiers[0].sightings[0].count == 3
    assert len(again.identifiers) == 1


def test_a_phone_contact_belongs_to_the_owner_of_the_phone_only(world):
    j = world.journal
    world.heard(j.received(ADRIEN, "whatsapp", "k-gilles", "Gilles Nordis"),
                j.received(BEA, "messages", "k-max", "Max"))
    world.run()
    accounts = person_accounts(world.contacts.sources())
    assert accounts == {(PHONE_SOURCE, ADRIEN): PERSON + ADRIEN, (PHONE_SOURCE, BEA): PERSON + BEA}

    def seen_by(person: str) -> set[str]:
        visible = visible_sources(person, owners=(ADRIEN,), accounts=accounts)
        return {c.name for c in world.contacts.page(visible=visible, size=50).items}

    assert seen_by(ADRIEN) == {"Gilles Nordis"}  # même propriétaire de Mika, Adrien ne voit pas le téléphone de Bea
    assert seen_by(BEA) == {"Max"}
    assert seen_by("user_3") == set()
    assert world.contacts.sheet(world.contacts.page(size=50).items[0].id,
                                visible=visible_sources("user_3", owners=(ADRIEN,), accounts=accounts)) is None


def test_the_same_person_on_whatsapp_and_by_sms_is_two_identifiers_and_a_suggestion(world):
    j = world.journal
    world.heard(j.received(ADRIEN, "whatsapp", "k-gilles", "Gilles Rousseau"),
                j.received(ADRIEN, "messages", "k-gilles", "Gilles Rousseau"))
    world.run()
    lines = world.contacts.page(size=50).items
    assert len(lines) == 2 and {c.apps for c in lines} == {((WHATSAPP, 1),), ((SMS, 1),)}
    (s,) = world.contacts.suggestions()
    assert s.reason == "same_name" and {s.a.id, s.b.id} == {c.id for c in lines}  # proposé, jamais réuni seul


def test_a_sender_known_only_by_a_number_is_that_number(world):
    j = world.journal
    world.heard(j.received(ADRIEN, "messages", "k-unknown", "+33 6 12 34 56 78"))
    world.run()
    cid = world.contacts.contact_of(PHONE, "06 12 34 56 78")
    sheet = world.contacts.sheet(cid)
    assert sheet.name == "+33612345678" and {i.kind for i in sheet.identifiers} == {PHONE, PHONE_APP}
    assert world.contacts.page(size=10).items[0].seen == 1  # le numéro ne compte pas les messages deux fois


def test_a_profile_number_and_a_phone_number_meet_whichever_comes_first(tmp_path):
    def profile(store: ContactsStore, teams_id: str, name: str, number: str, at: int) -> None:
        asyncio.run(store.observe([
            Observation(TEAMS_ID, teams_id, TEAMS, "equipe", name, 3, at, at),
            Observation(PHONE, number, TEAMS, "equipe", name, 0, at, at, joins=(TEAMS_ID, teams_id))]))

    # le profil d'abord : le message du téléphone va à sa fiche
    first = World(tmp_path / "a")
    try:
        profile(first.contacts, "8:orgid:gilles", "Gilles Rousseau", "06 12 34 56 78", NOW - 10)
        first.heard(first.journal.received(ADRIEN, "messages", "k-unknown", "+33 6 12 34 56 78"))
        first.run()
        (gilles,) = first.contacts.page(size=10).items
        assert gilles.name == "Gilles Rousseau" and set(gilles.sources) == {TEAMS, PHONE_SOURCE}
        assert gilles.apps == ((SMS, 1),)
    finally:
        first.contacts.close()
    # le téléphone d'abord : la fiche qui n'est que ce numéro rejoint celle du profil
    later = World(tmp_path / "b")
    try:
        later.heard(later.journal.received(ADRIEN, "messages", "k-unknown", "06 12 34 56 78"))
        later.run()
        profile(later.contacts, "8:orgid:gilles", "Gilles Rousseau", "+33612345678", NOW + 10)
        (gilles,) = later.contacts.page(size=10).items
        assert gilles.name == "Gilles Rousseau" and set(gilles.sources) == {TEAMS, PHONE_SOURCE}
        # deux fiches qui ont un nom ne se réunissent jamais par un numéro (un standard se partage)
        asyncio.run(later.contacts.observe([
            Observation(TEAMS_ID, "8:orgid:bob", TEAMS, "equipe", "Bob Martin", 1, NOW, NOW),
            Observation(PHONE, "+33612345678", TEAMS, "equipe", "Bob Martin", 0, NOW, NOW,
                        joins=(TEAMS_ID, "8:orgid:bob"))]))
        assert world_names(later.contacts) == {"Gilles Rousseau", "Bob Martin"}
        bob = later.contacts.sheet(later.contacts.contact_of(TEAMS_ID, "8:orgid:bob"))
        assert {i.kind for i in bob.identifiers} == {TEAMS_ID}
    finally:
        later.contacts.close()


def world_names(store: ContactsStore) -> set[str]:
    return {c.name for c in store.page(size=50).items}


def test_forgetting_a_sender_or_the_owner_of_the_phone_reaches_the_directory(world):
    j = world.journal
    old = [j.received(ADRIEN, "whatsapp", "k-gilles", "Gilles Nordis"), j.received(ADRIEN, "whatsapp", "k-lea", "Léa"),
           j.received(BEA, "whatsapp", "k-max", "Max")]
    world.heard(*old)
    process = world.run()
    key = sender(ADRIEN, "whatsapp", "k-gilles", "Gilles Nordis")
    assert asyncio.run(world.contacts.forget(key)) > 0
    assert world_names(world.contacts) == {"Léa", "Max"}
    # relu (le curseur remis à zéro) : daté d'avant l'oubli, il ne revient pas
    world.contacts.set_cursor(CURSOR_PHONE, 0)
    world.run(process)
    assert world_names(world.contacts) == {"Léa", "Max"}
    # oublier Adrien : ce que son téléphone avait apporté part, celui de Bea reste
    asyncio.run(world.contacts.forget(ADRIEN))
    assert world_names(world.contacts) == {"Max"} and (PHONE_SOURCE, ADRIEN) not in world.contacts.sources()
    world.contacts.set_cursor(CURSOR_PHONE, 0)
    world.run(process)
    assert world_names(world.contacts) == {"Max"}


def test_the_slice_keeps_only_the_latest_phone_messages():
    s = ContactsState()
    for seq in range(PHONE_KEPT + 3):
        s = _phoned(s, SimpleNamespace(seq=seq, data=SimpleNamespace(own=False, sender="phone:ab12:x")), None)
    assert len(s.phone) == PHONE_KEPT and s.phone[0] == 3 and s.heard == PHONE_KEPT + 3
    mine = _phoned(s, SimpleNamespace(seq=10**6, at=NOW, data=SimpleNamespace(
        own=True, sender="", recipient=ADRIEN, source="whatsapp", thread="t1", sent_at=NOW)), None)
    assert mine.phone == s.phone and mine.heard == s.heard + 1
    # le sien : la conversation où elle a écrit elle-même (lot 6 : on y échange vraiment)
    assert dict(mine.replied.items()) == {f"{ADRIEN}|whatsapp|t1": NOW}
