"""Les profils Teams dans l'annuaire (ADR 0298, lot 2) : ``contacts.ingest`` sur le vrai cache de Teams, le vrai
courrier et le vrai annuaire.

- **la preuve par l'e-mail** : la personne de Teams et le correspondant du courrier qui ont la même adresse sont un
  seul contact (celui qui a le plus d'histoire est gardé) — jamais deux contacts reliés à deux personnes différentes ;
- **ce qu'un profil dit d'elle** : son poste et son service sur sa fiche (dits seulement à qui voit ce Teams), ses
  numéros (un numéro déjà à quelqu'un d'autre, un standard, reste où il est) ;
- **son organisation** : l'entreprise nomme l'organisation de son domaine, ou fait la sienne, retrouvée par son nom ;
  jamais un webmail ; deux organisations à domaine du même nom restent deux ; l'organisation Teams n'est gardée que
  quand elle porte le nom de l'entreprise (un prestataire hébergé ailleurs) ;
- **l'oubli tient** : un profil d'avant l'oubli ne ramène ni la personne ni ses identifiants ; le profil de la
  personne d'un compte à elle n'est pas rangé ; un second passage ne relit rien.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.contracts import identity as identity_c
from mika.plugins.contacts import ContactsState
from mika.plugins.contacts.ingest import CURSOR_PROFILES, Ingest, from_profile
from mika.ports.contacts import (
    COMPANY,
    DOMAIN,
    EMAIL,
    MAIL,
    ORG,
    PERSON_KIND,
    PHONE,
    TEAMS,
    TEAMS_ID,
    TENANT,
    normalized,
)
from mika.ports.mail import Mail
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage, InboxProfile, TeamsProfile
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
MS = NOW // 1000
GROUP = "19:projet@thread.v2"
GILLES = "8:orgid:0b5c1a2e-0000-4000-8000-000000000001"
LEA = "8:orgid:0b5c1a2e-0000-4000-8000-000000000002"
MIKA = "8:orgid:0b5c1a2e-0000-4000-8000-00000000000f"


class Clock:
    def __init__(self) -> None:
        self.t = NOW

    def __call__(self) -> int:
        return self.t


class World:
    """Teams (le compte d'Adrien, celui de Mika), la boîte « pro » d'Adrien, l'annuaire ; une horloge chacun."""

    def __init__(self, tmp) -> None:
        self.teams_cfg = TeamsConfig(accounts={"adrien": TeamsAccount(owner="personne:user_1"),
                                               "sien": TeamsAccount(owner="elle")})
        self.mail_cfg = MailConfig(accounts={"pro": MailAccount(address="adrien@nordis.fr")})
        self.teams_clock, self.contacts_clock = Clock(), Clock()
        self.teams = TeamsStore(lambda: self.teams_cfg, tmp / "teams.db", now=self.teams_clock)
        self.mail = ImapSmtpMail(lambda: self.mail_cfg, tmp / "mail.db")
        self.contacts = ContactsStore(backend.target(tmp, "contacts"), now=self.contacts_clock)
        self.process = Ingest()

    def run(self) -> None:
        frame = SimpleNamespace(now=NOW, get=lambda key: ("user_1",) if key == identity_c.OWNERS else None)
        ctx = SimpleNamespace(state=ContactsState(), frame=frame, now=NOW,
                              ports={"teams": self.teams, "mail": self.mail, "contacts": self.contacts})
        asyncio.run(self.process.run(ctx))

    def push(self, *messages: InboxMessage, profiles: tuple[InboxProfile, ...] = (), account: str = "adrien",
             self_id: str = "8:orgid:adrien") -> int:
        return self.teams.store_batch(account, InboxBatch(self_id=self_id, conversations=(
            InboxConversation(GROUP, "Projet", "group"),), messages=messages, profiles=profiles),
            self.teams_clock()).profiles

    def receive(self, mid: str, sender: str, address: str, uid: int) -> None:
        self.mail._cache.store(Mail(mid, sender, address, "objet", NOW, "texte", to="adrien@nordis.fr",
                                    account="pro", folder="INBOX"), uid)

    def of(self, kind: str, value: str) -> int | None:
        return self.contacts.contact_of(kind, value)

    def close(self) -> None:
        self.teams.close()
        self.mail._cache.close()
        self.contacts.close()


@pytest.fixture
def world(tmp_path):
    found = World(tmp_path)
    yield found
    found.close()


def said(author: str, name: str, n: int) -> InboxMessage:
    return InboxMessage(str(n), GROUP, name, author, MS + n, f"message {n}")


def gilles(**more) -> InboxProfile:
    return InboxProfile(**{"id": GILLES, "name": "Gilles Rousseau", "email": "gilles@nordis.fr",
                           "title": "Chef de projet", "company": "Nordis", "department": "Achats",
                           "tenant": "Nordis", "phones": ("+33 6 12 34 56 78",), **more})


def orgs(world: World) -> dict[str, object]:
    return {line.name: line for line in world.contacts.page(kind=ORG, size=100).items}


def test_a_teams_person_and_a_mail_correspondent_with_the_same_email_become_one_contact(world):
    world.push(said(GILLES, "Gilles Rousseau", 1), said(GILLES, "Gilles Rousseau", 2))
    world.receive("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", 1)
    world.run()
    teams_id, mail_id = world.of(TEAMS_ID, GILLES), world.of(EMAIL, "gilles@nordis.fr")
    assert teams_id != mail_id and world.contacts.suggestions()  # deux fiches, un même nom : proposées seulement
    world.push(profiles=(gilles(),))
    world.run()
    # la même adresse le prouve : un seul contact, celui qui a le plus d'histoire (ses deux messages)
    assert world.of(TEAMS_ID, GILLES) == world.of(EMAIL, "gilles@nordis.fr") == teams_id
    assert world.contacts.sheet(mail_id) is None and world.contacts.suggestions() == []
    sheet = world.contacts.sheet(teams_id)
    kinds = {i.kind: i for i in sheet.identifiers}
    assert set(kinds) == {TEAMS_ID, EMAIL, PHONE}
    assert {s.source for s in kinds[EMAIL].sightings} == {MAIL, TEAMS}  # lue au courrier, et dans son profil Teams
    assert kinds[PHONE].value == "+33612345678"
    # son poste et son service, sur sa fiche et sur sa ligne
    assert (sheet.title, sheet.department) == ("Chef de projet", "Achats")
    (line,) = world.contacts.page(kind=PERSON_KIND, q="gilles").items
    assert (line.title, line.department, line.org_name) == ("Chef de projet", "Achats", "Nordis")
    assert line.seen == 3  # deux messages, un mail : le profil ne compte pas comme une fois de plus
    # l'organisation de son domaine porte maintenant le nom de son entreprise, et l'organisation Teams du compte
    org = world.contacts.sheet(world.of(DOMAIN, "nordis.fr"))
    assert org.name == "Nordis" and sheet.org.id == org.id
    assert {(i.kind, i.value) for i in org.identifiers} == {(DOMAIN, "nordis.fr"), (COMPANY, "nordis"),
                                                           (TENANT, "nordis")}


def test_what_a_profile_says_is_said_only_to_who_sees_that_teams(world):
    world.receive("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", 1)
    world.push(said(GILLES, "Gilles R.", 1), profiles=(gilles(),))
    world.run()
    by_mail = {(MAIL, "pro")}
    (line,) = world.contacts.page(visible=by_mail, kind=PERSON_KIND, q="gilles").items
    # vue depuis la boîte seule : ni son poste ni le nom d'entreprise lus dans le Teams d'Adrien
    assert (line.name, line.title, line.department, line.org_name) == ("Gilles Rousseau", "", "", "nordis.fr")
    assert world.contacts.sheet(line.id, visible=by_mail).title == ""
    assert {o.name for o in world.contacts.page(visible=by_mail, kind=ORG).items} == {"nordis.fr"}
    by_teams = {(TEAMS, "adrien")}
    (line,) = world.contacts.page(visible=by_teams, kind=PERSON_KIND, q="gilles").items
    assert (line.title, line.org_name) == ("Chef de projet", "Nordis")


def test_the_organisation_is_named_from_the_company_and_a_webmail_never_makes_one(world):
    world.push(profiles=(InboxProfile(LEA, "Léa Martin", "lea.martin@gmail.com", company="Atelier Brun"),
                         InboxProfile("8:live:camille", "Camille", "camille@hotmail.fr", company="ATELIER  BRÛN")))
    world.run()
    # « nordis.fr » : la boîte d'Adrien ; ni « gmail.com » ni « hotmail.fr »
    assert set(orgs(world)) == {"nordis.fr", "Atelier Brun"}
    assert world.of(DOMAIN, "gmail.com") is None and world.of(DOMAIN, "hotmail.fr") is None
    brun = orgs(world)["Atelier Brun"]
    members = {m.name for m in world.contacts.sheet(brun.id).members}
    assert members == {"Léa Martin", "Camille"}  # retrouvée par son nom, casse et accents ignorés
    # une personne du domaine de l'entreprise : l'organisation qui n'avait que ce nom rejoint celle du domaine
    world.push(profiles=(InboxProfile("8:live:paul", "Paul Brun", "paul@atelier-brun.fr", company="Atelier Brun"),))
    world.run()
    assert set(orgs(world)) == {"nordis.fr", "Atelier Brun"}
    org = world.contacts.sheet(world.of(DOMAIN, "atelier-brun.fr"))
    assert org.id == world.of(COMPANY, "atelier brun")
    assert {m.name for m in org.members} == {"Léa Martin", "Camille", "Paul Brun"}


def test_two_domain_organisations_of_the_same_name_stay_two_and_a_named_one_is_not_renamed(world):
    for profile in (InboxProfile(LEA, "Léa Martin", "lea@nordis.fr", company="Nordis"),
                    InboxProfile("8:live:yves", "Yves", "yves@nordis.com", company="Nordis"),
                    InboxProfile("8:live:zoe", "Zoé", "zoe@nordis.fr", company="Nordis Holding")):
        world.push(profiles=(profile,))
        world.run()
    fr, com = world.contacts.sheet(world.of(DOMAIN, "nordis.fr")), world.contacts.sheet(world.of(DOMAIN, "nordis.com"))
    assert fr.id != com.id and (fr.name, com.name) == ("Nordis", "nordis.com")
    assert {m.name for m in fr.members} == {"Léa Martin", "Zoé", "adrien@nordis.fr"}  # (la boîte d'Adrien)
    assert [m.name for m in com.members] == ["Yves"]
    assert world.of(COMPANY, "nordis holding") is None  # son organisation avait déjà son nom


def test_a_tenant_is_kept_only_when_it_names_the_company(world):
    world.push(profiles=(InboxProfile(LEA, "Léa Martin", company="Prestatech", tenant="Nordis"),))
    world.run()
    assert set(orgs(world)) == {"nordis.fr", "Prestatech"}  # « nordis.fr » : la boîte d'Adrien
    assert world.of(TENANT, "nordis") is None  # le Teams qui l'héberge n'est pas son employeur
    world.push(profiles=(InboxProfile("8:live:yves", "Yves", company="Prestatech", tenant="PRESTATECH"),))
    world.run()
    assert world.of(TENANT, "prestatech") == orgs(world)["Prestatech"].id


def test_two_contacts_linked_to_two_people_are_not_merged_by_a_profile(world):
    world.receive("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", 1)
    world.push(said(GILLES, "Gilles Rousseau", 1))
    world.run()
    world.contacts.link(world.of(EMAIL, "gilles@nordis.fr"), "user_2")
    world.contacts.link(world.of(TEAMS_ID, GILLES), "user_3")
    world.push(profiles=(gilles(),))
    world.run()
    teams_id, mail_id = world.of(TEAMS_ID, GILLES), world.of(EMAIL, "gilles@nordis.fr")
    assert teams_id != mail_id
    (email,) = [i for i in world.contacts.sheet(mail_id).identifiers if i.kind == EMAIL]
    assert {s.source for s in email.sightings} == {MAIL}  # rien du profil ne s'y range
    assert world.of(PHONE, "+33612345678") == teams_id  # ses numéros, eux, vont à sa fiche Teams


def test_a_number_already_someone_elses_stays_where_it_is(world):
    switchboard = "+33 1 40 00 00 00"
    world.push(profiles=(InboxProfile(LEA, "Léa Martin", phones=(switchboard,)),))
    world.run()
    world.push(profiles=(InboxProfile("8:live:yves", "Yves Morel", phones=(switchboard, "06 99 88 77 66")),))
    world.run()
    lea, yves = world.of(TEAMS_ID, LEA), world.of(TEAMS_ID, "8:live:yves")
    assert lea != yves  # un standard partagé ne réunit pas
    assert world.of(PHONE, switchboard) == lea and world.of(PHONE, "0699887766") == yves


def test_a_profile_from_before_a_forgetting_brings_nobody_back(world):
    world.receive("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", 1)
    world.run()
    world.push(profiles=(gilles(),))  # rangé dans Teams, pas encore lu par l'annuaire
    world.contacts_clock.t = NOW + 10
    asyncio.run(world.contacts.forget("mail:gilles@nordis.fr"))
    world.run()
    # ni son adresse, ni son identifiant Teams que le profil prouve être elle, ni ses numéros, ni son poste
    assert world.of(EMAIL, "gilles@nordis.fr") is None and world.of(TEAMS_ID, GILLES) is None
    assert world.of(PHONE, "+33612345678") is None
    assert world.contacts.page(q="gilles").total == 0 and world.contacts.page(q="achats").total == 0
    # un profil qui change ensuite, sans un message neuf d'elle, ne la ramène pas (il n'atteste rien d'après l'oubli)
    world.teams_clock.t = NOW + 20
    world.push(profiles=(gilles(title="Acheteur"),))
    world.run()
    assert world.of(TEAMS_ID, GILLES) is None and world.of(EMAIL, "gilles@nordis.fr") is None
    # un message neuf d'elle, daté d'après l'oubli, avec son profil : elle revient (comme un message)
    world.push(InboxMessage("neuf", GROUP, "Gilles Rousseau", GILLES, (NOW + 15) // 1000 + 1, "me revoilà"),
               profiles=(gilles(title="Acheteur principal"),))
    world.run()
    gone = world.of(TEAMS_ID, GILLES)
    assert gone is not None and world.of(EMAIL, "gilles@nordis.fr") == gone
    # oubliée entière après coup, relue depuis le début : rien ne revient de ce qui est daté d'avant
    world.contacts_clock.t = NOW + 5000
    asyncio.run(world.contacts.forget(f"contact:{gone}"))
    world.contacts.set_cursor(CURSOR_PROFILES, 0)
    world.run()
    assert world.of(TEAMS_ID, GILLES) is None and world.of(EMAIL, "gilles@nordis.fr") is None


def test_the_profile_of_her_own_account_is_not_kept_and_a_second_pass_reads_nothing_twice(world):
    world.push(profiles=(InboxProfile(MIKA, "Mika", "mika@nordis.fr", company="Nordis"),), account="sien",
               self_id=MIKA)
    world.push(said(GILLES, "Gilles Rousseau", 1), profiles=(gilles(),))
    world.run()
    assert world.of(TEAMS_ID, MIKA) is None and world.of(EMAIL, "mika@nordis.fr") is None
    before = {line.id: (line.seen, line.last) for line in world.contacts.page(size=100).items}
    cursor = world.contacts.cursor(CURSOR_PROFILES)
    assert cursor == 2
    assert world.push(profiles=(gilles(),)) == 0  # redit tel quel : rien à relire
    world.run()
    assert {line.id: (line.seen, line.last) for line in world.contacts.page(size=100).items} == before
    assert world.contacts.cursor(CURSOR_PROFILES) == cursor


def test_a_company_is_compared_folded_and_a_profile_says_its_person_in_order():
    assert normalized(COMPANY, "  Atelier   BRÛN ") == "atelier brun" and normalized(COMPANY, " - ") == ""
    assert normalized(TENANT, "Nordis") == normalized(COMPANY, "NORDIS")
    p = TeamsProfile("adrien", GILLES, "Gilles Rousseau", "gilles@nordis.fr", "Chef de projet", "Nordis", "Achats",
                     "nordis", ("+33 6 12 34 56 78",), updated=NOW + 99, seq=4, said_at=NOW)
    got = from_profile(p)
    assert [(o.kind, o.joins, o.proof) for o in got] == [
        (TEAMS_ID, (), False), (EMAIL, (TEAMS_ID, GILLES), True), (PHONE, (TEAMS_ID, GILLES), False),
        (COMPANY, (TEAMS_ID, GILLES), False), (TENANT, (TEAMS_ID, GILLES), False)]
    first = got[0]
    # daté par son dernier message dans ce compte, jamais par l'heure où le serveur a reçu le profil
    assert (first.title, first.department, first.same, first.count, first.last, first.company) == (
        "Chef de projet", "Achats", ((EMAIL, "gilles@nordis.fr"),), 0, NOW, "Nordis")
    # un prestataire hébergé par un autre Teams : son organisation Teams ne se range pas
    assert [o.kind for o in from_profile(TeamsProfile("adrien", LEA, "Léa", company="Prestatech",
                                                      tenant="Nordis"))] == [TEAMS_ID, COMPANY]


def test_a_reloaded_history_does_not_bring_a_forgotten_person_back_through_her_profile(world):
    """Relecture I5 : la console oublie Gilles (Teams efface ses messages et son profil, l'annuaire pose ses pierres
    tombales) ; l'extension, réinstallée, recharge l'historique : ses vieux messages reviennent dans Teams, avec son
    profil. Les messages sont arrêtés par la pierre tombale (datés d'avant) ; le profil, lui, portait l'heure de sa
    réception par le serveur — et Gilles revenait entier, sans un message neuf. Il est maintenant daté par son dernier
    message dans ce compte."""
    old = InboxMessage("1", GROUP, "Gilles Rousseau", GILLES, MS - 10, "un vieux message")
    world.push(old, profiles=(gilles(),))
    world.run()
    gone = world.of(TEAMS_ID, GILLES)
    assert gone is not None and world.of(EMAIL, "gilles@nordis.fr") == gone
    world.contacts_clock.t = NOW + 50
    asyncio.run(world.teams.forget(f"teams:{GILLES}"))
    asyncio.run(world.contacts.forget(f"contact:{gone}"))
    world.teams_clock.t = NOW + 100  # l'historique rechargé, reçu après l'oubli
    world.teams.store_batch("adrien", InboxBatch(self_id="8:orgid:adrien", conversations=(
        InboxConversation(GROUP, "Projet", "group"),), messages=(old,), profiles=(gilles(),), history=True),
        world.teams_clock())
    (profile,) = world.teams.profiles_since(0, 10).profiles
    assert profile.updated == NOW + 100 and profile.said_at == (MS - 10) * 1000
    world.run()
    assert world.of(TEAMS_ID, GILLES) is None and world.of(EMAIL, "gilles@nordis.fr") is None
    assert world.of(PHONE, "+33612345678") is None and world.contacts.page(q="gilles").total == 0
