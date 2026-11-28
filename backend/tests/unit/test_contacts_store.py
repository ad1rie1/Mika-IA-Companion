"""L'annuaire (ADR 0298), son magasin : ce que ses vues disent, ce qui réunit et ce qui ne réunit pas, l'oubli.

- **un identifiant, un contact** : le même identifiant vu deux fois (une autre casse) est un seul contact, sa vue
  additionnée ; vu par deux comptes, une vue chacun ;
- **les organisations** : un domaine d'organisation fait son organisation (pas un webmail), une adresse générique y
  va sans jamais faire une personne ;
- **l'oubli** : le contact entier part, ses identifiants gardent leur empreinte — ce qui les revoit daté d'avant ne
  les ramène pas, ce qui est daté d'après, si ; une organisation qui n'existait que par lui part avec lui ;
- **réunir, séparer, suggérer** : la preuve réunit, un nom seul se propose, une paire écartée ne revient pas ;
- **ce qui est visible** : une page et une fiche lues pour quelqu'un ne disent que ses vues visibles — le nom qu'il y
  porte, ces identifiants-là, et la recherche ne cherche que là.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mika.adapters.contacts import ContactsStore
from mika.adapters.contacts.models import ForgottenRow, IdentifierRow
from mika.ports.contacts import EMAIL, MAIL, ORG, PERSON_KIND, TEAMS, TEAMS_ID, Observation
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
MIN = 60_000_000


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
    found = ContactsStore(backend.target(tmp_path, "contacts"), now=clock.now)
    yield found
    found.close()


def seen(store: ContactsStore, *observations: Observation, cursors=None) -> int:
    return asyncio.run(store.observe(list(observations), cursors=cursors))


def forget(store: ContactsStore, subject: str) -> int:
    return asyncio.run(store.forget(subject))


def teams(value: str, account: str = "adrien", name: str = "Gilles Rousseau", count: int = 1, at: int = NOW,
          **more) -> Observation:
    return Observation(TEAMS_ID, value, TEAMS, account, name, count, more.pop("first", at), at, **more)


def mail(value: str, account: str = "pro", name: str = "", count: int = 1, at: int = NOW, **more) -> Observation:
    return Observation(EMAIL, value, MAIL, account, name, count, more.pop("first", at), at, **more)


# ── Un identifiant, un contact ────────────────────────────────────────────


def test_the_same_identifier_seen_twice_is_one_contact_its_sighting_summed(store):
    assert seen(store, teams("8:orgid:ABC", name="G. Rousseau", count=2, at=NOW, first=NOW - 5 * MIN)) == 1
    assert seen(store, teams("8:orgid:abc ", name="Gilles Rousseau", count=3, at=NOW + MIN)) == 1
    page = store.page()
    assert page.total == 1
    line = page.items[0]
    assert (line.kind, line.name, line.seen, line.last, line.sources) == (PERSON_KIND, "Gilles Rousseau", 5,
                                                                          NOW + MIN, (TEAMS,))
    sheet = store.sheet(line.id)
    (ident,) = sheet.identifiers
    assert (ident.kind, ident.value) == (TEAMS_ID, "8:orgid:abc")
    (sight,) = ident.sightings
    assert (sight.count, sight.first, sight.last, sight.name) == (5, NOW - 5 * MIN, NOW + MIN, "Gilles Rousseau")
    assert sheet.names == ("Gilles Rousseau",)
    assert store.contact_of(TEAMS_ID, "8:ORGID:ABC") == line.id and store.contact_of(TEAMS_ID, "8:orgid:x") is None


def test_an_identifier_seen_by_two_accounts_has_a_sighting_in_each(store):
    seen(store, teams("8:orgid:abc", account="adrien"), teams("8:orgid:abc", account="bea", count=4))
    (ident,) = store.sheet(store.contact_of(TEAMS_ID, "8:orgid:abc")).identifiers
    assert sorted((s.account, s.count) for s in ident.sightings) == [("adrien", 1), ("bea", 4)]
    assert store.sources() == [(TEAMS, "adrien"), (TEAMS, "bea")]


def test_a_name_that_is_an_address_is_not_a_name(store):
    seen(store, mail("gilles@gmail.com", name="gilles@gmail.com"))
    assert store.page().items[0].name == "gilles@gmail.com"  # son adresse, faute de nom
    assert store.sheet(store.page().items[0].id).names == ()


# ── Les organisations ─────────────────────────────────────────────────────


def test_an_address_of_an_organisation_domain_makes_its_organisation(store):
    seen(store, mail("gilles.rousseau@nordis.fr", name="Gilles Rousseau"),
         mail("lea@news.nordis.fr", name="Léa Martin", count=2))
    orgs = store.page(kind=ORG).items
    assert [(o.name, o.seen) for o in orgs] == [("nordis.fr", 3)]  # le domaine a ses vues : trois mails de chez elle
    people = store.page(kind=PERSON_KIND).items
    assert sorted(p.name for p in people) == ["Gilles Rousseau", "Léa Martin"]
    assert {p.org for p in people} == {orgs[0].id} and {p.org_name for p in people} == {"nordis.fr"}
    sheet = store.sheet(orgs[0].id)
    assert sorted(m.name for m in sheet.members) == ["Gilles Rousseau", "Léa Martin"]
    assert [(i.kind, i.value) for i in sheet.identifiers] == [("domain", "nordis.fr")]


def test_a_webmail_makes_no_organisation(store):
    seen(store, mail("gilles@gmail.com", name="Gilles"), mail("lea@hotmail.fr", name="Léa"))
    assert store.page(kind=ORG).total == 0
    assert {p.org for p in store.page().items} == {0}


def test_a_generic_address_goes_to_its_organisation_and_never_makes_a_person(store):
    seen(store, mail("noreply@edf.fr", name="EDF"), mail("Facturation+42@edf.fr", name="EDF Facturation"),
         mail("notifications-abc@edf.fr"))
    assert store.page(kind=PERSON_KIND).total == 0
    (org,) = store.page().items
    assert (org.kind, org.name, org.seen) == (ORG, "edf.fr", 3)
    sheet = store.sheet(org.id)
    assert [(i.value, i.generic) for i in sheet.identifiers] == [
        ("edf.fr", False), ("noreply@edf.fr", True), ("facturation+42@edf.fr", True),
        ("notifications-abc@edf.fr", True)]
    assert "EDF Facturation" in sheet.names  # un nom vu sur une adresse générique se cherche…
    assert store.page(q="facturation").total == 1
    assert store.sheet(org.id).name == "edf.fr"  # … sans nommer l'organisation


def test_a_generic_address_of_a_webmail_is_a_person(store):
    """Sans organisation où la ranger (un webmail), une adresse générique reste quelqu'un (une petite entreprise)."""
    seen(store, mail("contact@gmail.com", name="Atelier Lune"))
    (line,) = store.page().items
    assert (line.kind, line.name) == (PERSON_KIND, "Atelier Lune")


# ── L'oubli ───────────────────────────────────────────────────────────────


def test_a_forgotten_person_comes_back_only_from_what_is_newer(store, clock):
    seen(store, mail("gilles@gmail.com", name="Gilles", at=NOW))
    clock.t = NOW + 10 * MIN
    assert forget(store, "mail:Gilles@gmail.com") > 0
    assert store.page().total == 0
    with store._session() as s:
        kept = s.scalars(select(ForgottenRow.digest)).all()
        assert kept and not any("gilles" in d for d in kept)  # une empreinte, jamais l'adresse
    # relue d'avant l'oubli (l'historique rechargé) : rien ne revient
    assert seen(store, mail("gilles@gmail.com", name="Gilles", at=NOW + 5 * MIN)) == 0
    assert store.page().total == 0
    # une correspondance nouvelle, après l'oubli : une fiche neuve
    assert seen(store, mail("gilles@gmail.com", name="Gilles", at=NOW + 20 * MIN)) == 1
    assert store.page().items[0].seen == 1


def test_forgetting_by_teams_forgets_the_whole_contact_with_its_address(store, clock):
    seen(store, teams("8:orgid:abc"), mail("gilles@gmail.com", name="Gilles Rousseau"))
    a, b = store.contact_of(TEAMS_ID, "8:orgid:abc"), store.contact_of(EMAIL, "gilles@gmail.com")
    assert store.merge(a, b)
    clock.t = NOW + MIN
    forget(store, "teams:8:orgid:ABC")
    assert store.page().total == 0
    assert seen(store, mail("gilles@gmail.com", at=NOW)) == 0  # son adresse est oubliée avec lui


def test_forgetting_a_generic_address_keeps_its_organisation(store):
    seen(store, mail("gilles@edf.fr", name="Gilles"), mail("noreply@edf.fr"))
    org = store.page(kind=ORG).items[0].id
    forget(store, "mail:noreply@edf.fr")
    assert [i.value for i in store.sheet(org).identifiers] == ["edf.fr"]
    assert store.page(kind=PERSON_KIND).total == 1


def test_an_organisation_known_only_through_a_forgotten_person_leaves_with_her(store):
    seen(store, mail("gilles@nordis.fr", name="Gilles"))
    assert store.page(kind=ORG).total == 1
    forget(store, f"contact:{store.contact_of(EMAIL, 'gilles@nordis.fr')}")
    assert store.page().total == 0
    with store._session() as s:
        assert s.scalars(select(IdentifierRow)).all() == []


def test_forgetting_a_person_of_the_identity_forgets_the_contacts_linked_to_her(store):
    seen(store, teams("8:orgid:adrien", name="Adrien", own=True, count=0), teams("8:orgid:bob", name="Bob"))
    assert store.link(store.contact_of(TEAMS_ID, "8:orgid:adrien"), "user_1")
    forget(store, "user_1")
    assert [line.name for line in store.page().items] == ["Bob"]
    assert forget(store, "user_2") == 0 and forget(store, "contact:999") == 0 and forget(store, "") == 0


# ── Réunir, séparer, suggérer, relier ─────────────────────────────────────


def test_merge_moves_identifiers_and_sightings_and_refuses_two_kinds(store):
    seen(store, teams("8:orgid:abc", name="Gilles Rousseau"), mail("gilles@nordis.fr", name="G. Rousseau"))
    a, b = store.contact_of(TEAMS_ID, "8:orgid:abc"), store.contact_of(EMAIL, "gilles@nordis.fr")
    org = store.page(kind=ORG).items[0].id
    with pytest.raises(ValueError, match="organisation"):
        store.merge(a, org)
    assert store.merge(a, b) and not store.merge(a, b)
    sheet = store.sheet(a)
    assert {i.value for i in sheet.identifiers} == {"8:orgid:abc", "gilles@nordis.fr"}
    assert sheet.org is not None and sheet.org.id == org  # l'organisation de l'adresse le suit
    assert store.page(kind=PERSON_KIND).total == 1


def test_two_contacts_linked_to_two_people_are_not_merged(store):
    seen(store, teams("8:orgid:a"), teams("8:orgid:b"))
    a, b = store.contact_of(TEAMS_ID, "8:orgid:a"), store.contact_of(TEAMS_ID, "8:orgid:b")
    store.link(a, "user_1")
    store.link(b, "user_2")
    with pytest.raises(ValueError, match="deux personnes"):
        store.merge(a, b)


def test_detach_makes_a_contact_of_its_own_that_suggestions_no_longer_bring_back(store):
    seen(store, teams("8:orgid:abc", name="Gilles Rousseau"), mail("gilles@gmail.com", name="Gilles Rousseau"))
    a, b = store.contact_of(TEAMS_ID, "8:orgid:abc"), store.contact_of(EMAIL, "gilles@gmail.com")
    assert [s.reason for s in store.suggestions()] == ["same_name"]
    store.merge(a, b)
    email = next(i for i in store.sheet(a).identifiers if i.kind == EMAIL)
    fresh = store.detach(email.id)
    assert fresh and fresh != a and store.contact_of(EMAIL, "gilles@gmail.com") == fresh
    assert store.sheet(fresh).identifiers[0].sightings[0].count == 1  # ses vues le suivent
    assert store.suggestions() == []
    with pytest.raises(ValueError, match="seul identifiant"):
        store.detach(email.id)
    assert store.detach(12345) == 0


def test_suggestions_by_name_or_initial_never_merge_and_a_dismissed_pair_stays_apart(store):
    seen(store, teams("8:orgid:a", name="ROUSSEAU, Gilles"), mail("gilles@gmail.com", name="Gilles Rousseau"),
         mail("g.r@hotmail.fr", name="G. Rousseau"), mail("pierre@gmail.com", name="Pierre"),
         mail("pierre@hotmail.fr", name="Pierre"))
    a = store.contact_of(TEAMS_ID, "8:orgid:a")
    b = store.contact_of(EMAIL, "gilles@gmail.com")
    c = store.contact_of(EMAIL, "g.r@hotmail.fr")
    got = {(s.a.id, s.b.id): s.reason for s in store.suggestions()}
    # le même nom complet, dans un autre ordre ; une initiale et le nom ; « Pierre » seul ne suffit pas
    assert got == {(min(a, b), max(a, b)): "same_name", (min(a, c), max(a, c)): "initial",
                   (min(b, c), max(b, c)): "initial"}
    assert store.page(kind=PERSON_KIND).total == 5  # rien n'est réuni
    assert store.dismiss(a, b) and not store.dismiss(b, a) and not store.dismiss(a, a)
    assert (min(a, b), max(a, b)) not in {(s.a.id, s.b.id) for s in store.suggestions()}
    store.link(b, "user_1")
    store.link(c, "user_2")  # reliés à deux personnes : pas la même
    assert {(s.a.id, s.b.id) for s in store.suggestions()} == {(min(a, c), max(a, c))}


def test_only_a_person_is_linked_and_an_earlier_link_is_kept_when_asked(store):
    seen(store, mail("gilles@nordis.fr", name="Gilles"))
    person, org = store.contact_of(EMAIL, "gilles@nordis.fr"), store.page(kind=ORG).items[0].id
    assert not store.link(org, "user_1")
    assert store.link(person, "user_1") and not store.link(person, "user_1")
    assert not store.link(person, "user_2", replace=False)
    assert store.sheet(person).person == "user_1"
    assert store.link(person, None) and store.sheet(person).person == ""


# ── Ce qui est visible ────────────────────────────────────────────────────


def test_a_page_and_a_sheet_read_for_someone_say_only_what_her_sources_saw(store):
    """Gilles vu dans le Teams d'Adrien (« Gilles R. ») et dans la boîte de Bea (« Gilles Rousseau », son adresse) :
    pour Adrien, ni l'adresse, ni le nom que porte la boîte de Bea, ni la recherche par eux."""
    seen(store, teams("8:orgid:abc", account="adrien", name="Gilles R.", at=NOW),
         mail("gilles@nordis.fr", account="bea", name="Gilles Rousseau", at=NOW + MIN),
         mail("hélène@gmail.com", account="bea", name="Hélène Durand"))
    store.merge(store.contact_of(TEAMS_ID, "8:orgid:abc"), store.contact_of(EMAIL, "gilles@nordis.fr"))
    adrien = {(TEAMS, "adrien")}
    (line,) = store.page(visible=adrien).items
    assert (line.name, line.identifiers, line.sources, line.org, line.org_name) == (
        "Gilles R.", ((TEAMS_ID, "8:orgid:abc"),), (TEAMS,), 0, "")
    assert store.page(visible=adrien, q="gilles r").total == 1
    assert store.page(visible=adrien, q="rousseau").total == 0
    assert store.page(visible=adrien, q="nordis").total == 0
    sheet = store.sheet(line.id, visible=adrien)
    assert [i.value for i in sheet.identifiers] == ["8:orgid:abc"] and sheet.org is None
    assert sheet.names == ("Gilles R.",)
    # Bea, elle, voit l'adresse, l'organisation, et l'accent ne compte pas dans sa recherche
    bea = {(MAIL, "bea")}
    assert store.page(visible=bea, q="rousseau").items[0].org_name == "nordis.fr"
    assert [p.name for p in store.page(visible=bea, q="helene").items] == ["Hélène Durand"]
    # une opératrice voit tout ; personne ne voit rien sans source
    everything = store.page()
    assert everything.total == 3 and store.page(visible=set()).total == 0
    assert store.sheet(line.id, visible=set()) is None
    assert store.sheet(line.id, visible={(MAIL, "autre")}) is None
    assert {i.value for i in store.sheet(line.id).identifiers} == {"8:orgid:abc", "gilles@nordis.fr"}


def test_a_page_is_the_last_seen_first_and_bounded(store):
    for n in range(5):
        seen(store, teams(f"8:orgid:{n}", name=f"Personne {n}", at=NOW + n * MIN))
    page = store.page(page=2, size=2)
    assert page.total == 5 and (page.number, page.size) == (2, 2)
    assert [line.name for line in page.items] == ["Personne 2", "Personne 1"]


# ── Les curseurs, un compte supprimé ──────────────────────────────────────


def test_cursors_move_in_the_same_write_as_their_observations(store):
    assert store.cursor("teams.messages") == 0
    seen(store, teams("8:orgid:a"), cursors={"teams.messages": 42, "mail.sent": 7})
    assert (store.cursor("teams.messages"), store.cursor("mail.sent")) == (42, 7)
    store.set_cursor("teams.messages", 50)
    assert store.cursor("teams.messages") == 50


def test_dropping_an_account_drops_what_only_it_saw(store):
    seen(store, teams("8:orgid:a", account="adrien"), teams("8:orgid:b", account="adrien"),
         teams("8:orgid:b", account="bea"), mail("gilles@nordis.fr", account="adrien"))
    assert store.drop_source(TEAMS, "adrien") > 0
    names = {store.sheet(line.id).identifiers[0].value for line in store.page().items}
    assert names == {"8:orgid:b", "gilles@nordis.fr", "nordis.fr"}
    store.drop_source(MAIL, "adrien")
    assert [line.identifiers for line in store.page().items] == [((TEAMS_ID, "8:orgid:b"),)]
    assert store.sources() == [(TEAMS, "bea")]


# ── Ce qui sépare tient, ce qui se montre se prouve ───────────────────────


def test_a_detached_identifier_is_not_merged_back_by_the_next_proof(store):
    """Relecture I4 : une opératrice détache l'e-mail réuni par erreur au profil Teams ; au changement suivant du
    profil, l'e-mail revenait en preuve (``proof``) et ``_prove`` réunissait de nouveau les deux fiches. La séparation
    est gardée (``dismissed``) et une preuve la respecte."""
    seen(store, teams("8:orgid:abc"), Observation(EMAIL, "gilles@gmail.com", TEAMS, "adrien", "Gilles Rousseau", 0,
                                                   NOW, NOW, joins=(TEAMS_ID, "8:orgid:abc"), proof=True))
    person = store.contact_of(TEAMS_ID, "8:orgid:abc")
    assert store.contact_of(EMAIL, "gilles@gmail.com") == person
    email = next(i for i in store.sheet(person).identifiers if i.kind == EMAIL)
    apart = store.detach(email.id)
    # le profil change (son poste) : son e-mail revient en preuve
    assert seen(store, teams("8:orgid:abc", count=0, at=NOW + MIN, title="Acheteur"),
                Observation(EMAIL, "gilles@gmail.com", TEAMS, "adrien", "Gilles Rousseau", 0, NOW + MIN, NOW + MIN,
                            joins=(TEAMS_ID, "8:orgid:abc"), proof=True)) == 1  # le profil, pas la preuve
    assert store.contact_of(EMAIL, "gilles@gmail.com") == apart != person
    assert store.sheet(apart) is not None and store.sheet(person).title == "Acheteur"


def test_dismissed_pairs_follow_a_merge(store):
    """Relecture, mineur 2 : « Léa ≠ Léa Martin » écarté ; Léa Martin réunie ensuite à une autre fiche (une preuve,
    une opératrice) — avant, ``_merge_in`` effaçait la paire et la suggestion revenait."""
    seen(store, mail("lea@gmail.com", name="Léa Martin"), mail("lea.martin@hotmail.fr", name="Léa Martin"),
         teams("8:orgid:lea", name="Léa Martin"))
    a, b, c = (store.contact_of(EMAIL, "lea@gmail.com"), store.contact_of(EMAIL, "lea.martin@hotmail.fr"),
               store.contact_of(TEAMS_ID, "8:orgid:lea"))
    store.dismiss(a, b)
    store.merge(c, b)  # Léa Martin (courrier) et Léa Martin (Teams), une seule fiche
    assert [(s.a.id, s.b.id) for s in store.suggestions()] == []  # « a » reste écartée de la fiche réunie


def test_an_organisation_is_said_only_with_its_proof_in_what_is_visible(store):
    """Relecture I2 : Gilles écrit à Adrien depuis un webmail ; son profil Teams, vu dans le Teams de Béa, dit son
    adresse pro ``@lumen.fr`` (la fiche est réunie) et son entreprise. Paul, de Lumen, est dans le Teams d'Adrien :
    l'organisation lui est visible. Avant, la fiche de Gilles disait à Adrien « chez Lumen Conseil », et l'organisation
    le comptait parmi ses personnes. La preuve (une adresse du domaine, un profil qui dit l'entreprise) doit se voir."""
    seen(store, mail("gilles@gmail.com", account="adrien", name="Gilles Rousseau"),
         teams("8:orgid:gilles", account="bea", company="Lumen Conseil"),
         Observation(EMAIL, "gilles@lumen.fr", TEAMS, "bea", "Gilles Rousseau", 0, NOW, NOW,
                     joins=(TEAMS_ID, "8:orgid:gilles"), proof=True),
         Observation(EMAIL, "gilles@gmail.com", TEAMS, "bea", "Gilles Rousseau", 0, NOW, NOW,
                     joins=(TEAMS_ID, "8:orgid:gilles"), proof=True),
         teams("8:orgid:paul", account="adrien", name="Paul Henry", company="Lumen Conseil"),
         Observation(EMAIL, "paul@lumen.fr", TEAMS, "adrien", "Paul Henry", 0, NOW, NOW,
                     joins=(TEAMS_ID, "8:orgid:paul"), proof=True))
    gilles, paul = store.contact_of(EMAIL, "gilles@gmail.com"), store.contact_of(TEAMS_ID, "8:orgid:paul")
    org = store.contact_of("domain", "lumen.fr")
    assert store.contact_of(TEAMS_ID, "8:orgid:gilles") == gilles and store.sheet(gilles).org.id == org
    adrien = {(MAIL, "adrien"), (TEAMS, "adrien")}
    sheet = store.sheet(gilles, visible=adrien)
    assert sheet is not None and sheet.org is None  # sa preuve n'est que chez Béa
    line = next(c for c in store.page(visible=adrien).items if c.id == gilles)
    assert (line.org, line.org_name) == (0, "")
    assert [m.id for m in store.sheet(org, visible=adrien).members] == [paul]
    assert next(c for c in store.page(visible=adrien).items if c.id == org).members == 1
    assert [c.id for c in store.page(visible=adrien, org=org).items] == [paul]
    assert store.sheet(paul, visible=adrien).org.id == org  # Paul : son adresse est dans le Teams d'Adrien
    # Béa voit la preuve : Gilles est de Lumen pour elle ; par son profil seul (sans l'adresse), aussi
    assert store.sheet(gilles, visible={(TEAMS, "bea")}).org.id == org
    assert store.sheet(gilles).org.id == org  # une opératrice voit tout


def test_a_company_alone_proves_the_membership_only_where_its_profile_was_read(store):
    """Relecture I2, sans domaine : Gilles (un webmail) rejoint l'organisation « Lumen Conseil » par le profil lu chez
    Béa ; Adrien, qui voit Gilles par sa boîte et l'organisation par Paul, n'apprend pas qu'il en est."""
    seen(store, mail("gilles@gmail.com", account="adrien", name="Gilles Rousseau"),
         teams("8:orgid:gilles", account="bea", company="Lumen Conseil"),
         Observation(EMAIL, "gilles@gmail.com", TEAMS, "bea", "Gilles Rousseau", 0, NOW, NOW,
                     joins=(TEAMS_ID, "8:orgid:gilles"), proof=True),
         Observation("company", "Lumen Conseil", TEAMS, "bea", "Lumen Conseil", 0, NOW, NOW,
                     joins=(TEAMS_ID, "8:orgid:gilles")),
         teams("8:orgid:paul", account="adrien", name="Paul Henry", company="Lumen Conseil"),
         Observation("company", "Lumen Conseil", TEAMS, "adrien", "Lumen Conseil", 0, NOW, NOW,
                     joins=(TEAMS_ID, "8:orgid:paul")))
    gilles, org = store.contact_of(EMAIL, "gilles@gmail.com"), store.contact_of("company", "lumen conseil")
    assert store.sheet(gilles).org.id == org
    adrien = {(MAIL, "adrien"), (TEAMS, "adrien")}
    assert store.sheet(gilles, visible=adrien).org is None
    assert {m.name for m in store.sheet(org, visible=adrien).members} == {"Paul Henry"}
    assert store.sheet(gilles, visible={(TEAMS, "bea")}).org.name == "Lumen Conseil"


def test_a_refused_proof_leaves_no_organisation_behind(store, clock):
    """Relecture, mineur 3 : l'organisation d'un domaine oubliée, un profil d'après l'oubli dit une adresse de ce
    domaine déjà à une fiche reliée à une autre personne : la preuve est refusée. Avant, l'organisation renaissait
    quand même (``_org`` avant le refus), avec son domaine et sans aucune vue."""
    seen(store, mail("g@nordis.fr", name="G"), teams("8:orgid:gilles"))
    store.link(store.contact_of(EMAIL, "g@nordis.fr"), "user_2")
    store.link(store.contact_of(TEAMS_ID, "8:orgid:gilles"), "user_3")
    clock.t = NOW + 1
    forget(store, f"contact:{store.contact_of('domain', 'nordis.fr')}")
    assert store.contact_of("domain", "nordis.fr") is None
    assert seen(store, Observation(EMAIL, "g@nordis.fr", TEAMS, "adrien", "", 0, NOW + MIN, NOW + MIN,
                                   joins=(TEAMS_ID, "8:orgid:gilles"), proof=True)) == 0
    assert store.contact_of("domain", "nordis.fr") is None


def test_dropping_her_own_places_keeps_what_others_see(store):
    """Relecture I3 : ce qu'une personne oublie d'un contact croisé aussi ailleurs n'efface que sa part : ses vues, ce
    qu'elle en a tiré ; l'identifiant qui n'était vu que chez elle part, avec sa pierre tombale."""
    seen(store, mail("bob@gmail.com", account="perso", name="Bob"), mail("bob@gmail.com", account="pro", name="Robert"),
         teams("8:orgid:bob", account="adrien", name="Bob"))
    bob = store.contact_of(EMAIL, "bob@gmail.com")
    store.merge(bob, store.contact_of(TEAMS_ID, "8:orgid:bob"))
    assert store.drop_places(bob, {(MAIL, "perso"), (TEAMS, "adrien")}) > 0
    sheet = store.sheet(bob)
    assert [(i.value, [x.account for x in i.sightings]) for i in sheet.identifiers] == [("bob@gmail.com", ["pro"])]
    assert sheet.name == "Robert" and store.contact_of(TEAMS_ID, "8:orgid:bob") is None
    assert seen(store, teams("8:orgid:bob", account="adrien")) == 0  # daté d'avant : ne revient pas
    assert store.drop_places(bob, ()) == 0 and store.drop_places(999, {(MAIL, "pro")}) == 0


def test_discarding_an_identifier_leaves_no_tombstone(store):
    seen(store, mail("mika@nordis.fr", account="adrien", name="Mika"))
    assert store.discard(EMAIL, "MIKA@nordis.fr") > 0
    assert store.contact_of(EMAIL, "mika@nordis.fr") is None and store.page(kind=ORG).total == 0
    assert seen(store, mail("mika@nordis.fr", account="adrien", name="Mika")) == 1  # aucune pierre tombale
    assert store.discard(EMAIL, "personne@nordis.fr") == 0
