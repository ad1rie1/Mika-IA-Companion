"""Ce qu'on lui raconte, dans l'annuaire (ADR 0298, lot 5) : une personne dont on lui a parlé (une clé ``name:…`` de sa
mémoire) a sa fiche d'emblée — sur le vrai annuaire et le vrai plugin, sa mémoire en doublure (les deux vues de sa
porte, ``KNOWLEDGE`` et ``KNOWLEDGE_ABOUT``, en vraies tables SQLite : la vraie requête s'y lit).

- **une fiche par nom raconté**, contact de qui le lui a raconté (``told_by``, résolu par ``identity.PERSON``) ; ni ce
  que personne ne lui a confié (une réflexion), ni un secret, ni ce qu'elle garde pour elle ou qui est restreint, ni ce
  qu'un expéditeur du téléphone a dit seul, ni ce qui n'est plus actif, ni ce qui n'est pas un souvenir, une croyance ou
  un moment de vie ; un passage de plus ne compte rien deux fois ; une règle nouvelle relit tout, et ce qui ne la suit
  plus part ;
- **son nom** tel que le texte l'écrit (les accents que la clé a perdus) ;
- **les rapprochements** : un même prénom, d'un côté sans nom de famille, se propose (plus faible) ; face à une fiche
  reliée à quelqu'un qui lui parle, c'est l'identité qui décide ;
- **les noms reliés** : ``identity.name_bound`` relie sa fiche, le lien défait la délie (si elle n'est qu'un nom) ;
- **l'oubli** : le nom, la personne qui l'a raconté.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, create_engine, insert

import mika.plugins.contacts as contacts_m
from mika.adapters.contacts import ContactsStore
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.state import FrozenDict
from mika.plugins.contacts import ContactsState, _forgotten, _named
from mika.plugins.contacts.ingest import (
    CURSOR_TOLD,
    CURSOR_TOLD_REBUILD,
    CURSOR_TOLD_RULE,
    TOLD_RULE,
    Ingest,
    confided,
    spelled,
    tellers,
)
from mika.ports.contacts import (
    EMAIL,
    MAIL,
    TEAMS,
    TEAMS_ID,
    TOLD,
    TOLD_NAME,
    Observation,
    person_accounts,
    visible_sources,
)
from mika.vocab.access import PERSON, SELF
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
ADRIEN, BEA = "user_1", "user_2"
LEA, LEA_MARTIN, CAROL = "name:aaaaaaaaaaaaaaaa:lea", "name:bbbbbbbbbbbbbbbb:lea martin", "name:cccccccccccccccc:carol"


class Mind:
    """Sa mémoire telle que la collecte la lit : les deux vues de sa porte, en tables."""

    def __init__(self, tmp) -> None:
        self.engine = create_engine(f"sqlite:///{tmp / 'mind.db'}")
        meta = MetaData()
        self.items = memory_c.KNOWLEDGE.to_metadata(meta)
        self.about = memory_c.KNOWLEDGE_ABOUT.to_metadata(meta)
        meta.create_all(self.engine)
        self.n = 1000

    def add(self, keys: tuple[str, ...], told_by: tuple[str, ...], text: str, *, kind: str = memory_c.BELIEF,
            status: str = "active", born: int = NOW, secret: int = 0, internal_only: int = 0,
            constraints: str = "[]") -> int:
        self.n += 1
        with self.engine.begin() as c:
            c.execute(insert(self.items).values(id=self.n, kind=kind, text=text, told_by=json.dumps(list(told_by)),
                                                born_at=born, status=status, secret=secret,
                                                internal_only=internal_only, constraints=constraints))
            for key in keys:
                c.execute(insert(self.about).values(item=self.n, person=key))
        return self.n

    def query_mind(self, sql, params=()):
        with self.engine.connect() as c:
            return [tuple(r) for r in c.execute(sql)]

    def get_events(self, seqs):
        return []

    def content(self, refs):
        return {}


class World:
    def __init__(self, tmp) -> None:
        self.contacts = ContactsStore(backend.target(tmp, "contacts"), now=lambda: NOW + 10**9)
        self.mind = Mind(tmp)
        #: ``identity.PERSON`` : l'adresse → sa personne, le nom raconté → la personne qu'un opérateur lui a reliée
        self.person = {"ext_5": BEA}
        self.state = ContactsState()
        self.process = Ingest()

    def get(self, key):
        if key == identity_c.OWNERS:
            return (ADRIEN,)
        return self.person.get(key.arg) if getattr(key, "family", None) is identity_c.PERSON else None

    def run(self) -> None:
        ctx = SimpleNamespace(state=self.state, ports={"contacts": self.contacts, "store": self.mind},
                              frame=SimpleNamespace(get=self.get), now=NOW)
        asyncio.run(self.process.run(ctx))

    def bind(self, name: str, person: str | None, seq: int) -> None:
        """``identity.name_bound`` : l'identité le relie (``PERSON`` du nom), la tranche le note."""
        if person:
            self.person[name] = person
        else:
            self.person.pop(name, None)
        self.state = _named(self.state, SimpleNamespace(seq=seq, data=SimpleNamespace(name=name)), None)

    def told(self, key: str):
        cid = self.contacts.contact_of(TOLD_NAME, key)
        return self.contacts.sheet(cid) if cid is not None else None


@pytest.fixture
def world(tmp_path):
    found = World(tmp_path)
    yield found
    found.contacts.close()


def test_the_person_key_family_is_what_the_world_reads():
    # la doublure lit ``identity.PERSON(...)`` par sa famille et son argument : la vraie forme d'une clé de fait
    key = identity_c.PERSON("ext_5")
    assert key.family is identity_c.PERSON and key.arg == "ext_5"


def test_a_person_she_is_told_about_has_a_contact_of_who_told_her(world):
    m = world.mind
    m.add((LEA,), (ADRIEN,), "Léa déménage à Lyon.")
    m.add((LEA,), (ADRIEN,), "Adrien dîne avec Léa jeudi.", kind=memory_c.EPISODE_MEMORY)
    m.add((LEA_MARTIN,), ("ext_5",), "Léa Martin est comptable.")
    m.add((CAROL,), (), "Carol a gagné le tournoi.")  # de personne (une réflexion) : ne fait connaître personne
    m.add(("name:dddddddddddddddd:max",), ("phone:abcdef012345:Max",), "Max part en vacances.")  # le téléphone seul
    m.add(("name:eeeeeeeeeeeeeeee:zoe",), (ADRIEN,), "Zoé, à rappeler.", kind="promise")  # pas un souvenir
    m.add(("name:ffffffffffffffff:ines",), (ADRIEN,), "Inès est partie.", status="superseded")  # plus active
    world.run()
    lea = world.told(LEA)
    assert lea.name == "Léa" and lea.person == ""  # le nom tel que le texte l'écrit ; connue de loin
    (ident,) = lea.identifiers
    (sight,) = ident.sightings
    assert (ident.kind, sight.source, sight.account, sight.count) == (TOLD_NAME, TOLD, ADRIEN, 2)
    martin = world.told(LEA_MARTIN)
    assert martin.name == "Léa Martin" and martin.identifiers[0].sightings[0].account == BEA  # sa personne
    assert world.told(CAROL) is None
    assert {c.name for c in world.contacts.page(size=50).items} == {"Léa", "Léa Martin"}
    # à qui : à qui le lui a raconté — jamais à tout le monde
    accounts = person_accounts(world.contacts.sources())
    assert accounts == {(TOLD, ADRIEN): PERSON + ADRIEN, (TOLD, BEA): PERSON + BEA}
    mine = visible_sources(ADRIEN, owners=(ADRIEN,), accounts=accounts)
    assert {c.name for c in world.contacts.page(visible=mine, size=50).items} == {"Léa"}
    # un passage de plus ne compte rien deux fois ; un élément de plus, si
    before = {c.id: c.seen for c in world.contacts.page(size=50).items}
    world.run()
    assert {c.id: c.seen for c in world.contacts.page(size=50).items} == before
    last = m.add((LEA, CAROL), (ADRIEN,), "Léa et Carol se connaissent.")
    world.run()
    assert world.told(LEA).identifiers[0].sightings[0].count == 3
    carol = world.told(CAROL)
    assert {(x.account, x.count) for x in carol.identifiers[0].sightings} == {(ADRIEN, 1)}
    assert world.contacts.cursor(CURSOR_TOLD) == last


def test_the_tellers_and_the_spelling_rules():
    person = {"ext_5": BEA, "ext_9": "name:x:y"}.get
    assert tellers((ADRIEN, "ext_5", "phone:ab12:Max", "name:x:lea", ADRIEN), lambda h: person(h) or h) == (ADRIEN, BEA)
    assert tellers(("ext_9",), lambda h: person(h) or h) == ()  # relié à une personne connue de nom : à personne
    assert spelled("name:aaaa:lea martin", "Hier, Léa Martin a appelé.") == "Léa Martin"
    assert spelled("name:aaaa:lea", "Lea") == "Lea" and spelled("name:aaaa:lea", "Rien ici.") == ""
    assert spelled("name:lea", "Léa vient.") == "Léa"  # une clé d'avant les portées


def test_a_first_name_alone_proposes_the_full_name_more_weakly(world):
    m = world.mind
    m.add((LEA,), (ADRIEN,), "Léa déménage à Lyon.")
    m.add((LEA_MARTIN,), ("ext_5",), "Léa Martin est comptable.")
    world.run()
    asyncio.run(world.contacts.observe([
        Observation(EMAIL, "lea.martin@calix.fr", MAIL, "pro", "Léa Martin", 5, NOW, NOW),
        Observation(TEAMS_ID, "8:orgid:support", TEAMS, "equipe", "Support", 2, NOW, NOW),
        Observation(TEAMS_ID, "8:orgid:support2", TEAMS, "equipe", "Support Nordis", 2, NOW, NOW)]))
    mail = world.contacts.contact_of(EMAIL, "lea.martin@calix.fr")
    told_lea, told_martin = world.told(LEA).id, world.told(LEA_MARTIN).id
    got = {(frozenset((s.a.id, s.b.id)), s.reason) for s in world.contacts.suggestions()}
    assert got == {(frozenset((told_martin, mail)), "same_name"), (frozenset((told_lea, mail)), "first_name"),
                   (frozenset((told_lea, told_martin)), "first_name")}
    reasons = [s.reason for s in world.contacts.suggestions()]
    assert reasons == sorted(reasons, key=["same_name", "initial", "first_name"].index)  # le plus faible en dernier
    # « Support » (Teams) n'est pas un prénom qu'on raconte : rien ; face à une fiche reliée à quelqu'un qui lui
    # parle, un nom raconté ne se propose pas ici (l'identité en décide)
    world.contacts.link(mail, "ext_7")
    assert {frozenset((s.a.id, s.b.id)) for s in world.contacts.suggestions()} == {frozenset((told_lea, told_martin))}


def test_a_bound_name_links_its_contact_and_unbinding_unlinks_a_mere_name(world):
    m = world.mind
    m.add((LEA,), (ADRIEN,), "Léa déménage à Lyon.")
    world.run()
    world.bind(LEA, "ext_7", 50)
    world.run()
    assert world.told(LEA).person == "ext_7"
    world.bind(LEA, None, 51)  # « Détacher un nom »
    world.run()
    assert world.told(LEA).person == ""
    # réunie à une fiche du courrier : le lien d'une fiche qui n'est plus qu'un nom ne se défait pas d'office
    asyncio.run(world.contacts.observe([Observation(EMAIL, "lea@calix.fr", MAIL, "pro", "Léa", 1, NOW, NOW)]))
    world.contacts.merge(world.contacts.contact_of(EMAIL, "lea@calix.fr"), world.told(LEA).id)
    world.bind(LEA, "ext_7", 52)
    world.run()
    assert world.told(LEA).person == "ext_7"
    world.bind(LEA, None, 53)
    world.run()
    assert world.told(LEA).person == "ext_7"
    # relié avant que sa mémoire n'en garde rien : la fiche, née ensuite, lui est reliée d'emblée
    world.bind(CAROL, "ext_8", 54)
    world.run()
    m.add((CAROL,), (ADRIEN,), "Carol a gagné le tournoi.")
    world.run()
    assert world.told(CAROL).person == "ext_8"


def test_forgetting_a_told_name_or_who_told_it_reaches_the_directory(world):
    m = world.mind
    m.add((LEA,), (ADRIEN,), "Léa déménage à Lyon.")
    m.add((LEA_MARTIN,), ("ext_5",), "Léa Martin est comptable.")
    world.run()
    assert asyncio.run(world.contacts.forget(LEA)) > 0
    assert world.told(LEA) is None
    world.contacts.set_cursor(CURSOR_TOLD, 0)  # relu : d'avant l'oubli, il ne revient pas
    world.run()
    assert world.told(LEA) is None and world.told(LEA_MARTIN) is not None
    asyncio.run(world.contacts.forget(BEA))  # oublier Bea : ce qu'elle lui a raconté part
    assert world.told(LEA_MARTIN) is None and (TOLD, BEA) not in world.contacts.sources()


def test_the_slice_notes_each_binding_once_and_forgets_a_forgotten_name(monkeypatch):
    s = _named(ContactsState(), SimpleNamespace(seq=5, data=SimpleNamespace(name=LEA)), None)
    s = _named(s, SimpleNamespace(seq=9, data=SimpleNamespace(name=CAROL)), None)
    s = _named(s, SimpleNamespace(seq=12, data=SimpleNamespace(name=LEA)), None)
    assert s.named.to_dict() == {CAROL: 9, LEA: 12} and s.heard == 3
    gone = _forgotten(s, SimpleNamespace(type=SUBJECT_FORGOTTEN, data=SimpleNamespace(subject=LEA)), None)
    assert gone.named == FrozenDict({CAROL: 9})
    assert _forgotten(gone, SimpleNamespace(data=SimpleNamespace(subject="user_1")), None) is gone
    # au-delà de sa borne, les plus anciennes décisions partent (pas les premiers noms dans l'ordre alphabétique)
    monkeypatch.setattr(contacts_m, "NAMED_KEPT", 2)
    full = _named(s, SimpleNamespace(seq=20, data=SimpleNamespace(name="name:0000000000000000:alice")), None)
    assert full.named.to_dict() == {LEA: 12, "name:0000000000000000:alice": 20}


def test_a_secret_or_a_night_reflection_never_makes_a_contact_seen_by_everyone(world):
    """Relecture C1 : Adrien confie en secret quelque chose sur « Léa Martin » ; la nuit en fait une réflexion, sans
    ``told_by``, qui reprend la clé du nom. Avant, la réflexion rangeait une vue ``(told, elle)`` — à tout le monde : Béa
    voyait « Léa Martin » dans ses contacts, et ``contacts_lookup`` la lui disait. Ni le secret, ni la réflexion, ni ce
    qu'elle garde pour elle, ni ce qui est restreint par ses sources ne font connaître quelqu'un."""
    m = world.mind
    m.add((LEA_MARTIN,), (ADRIEN,), "Léa Martin traverse une passe difficile.", secret=1)
    m.add((LEA_MARTIN,), (), "Je pense à ce qu'Adrien m'a dit de Léa Martin.", kind=memory_c.EPISODE_MEMORY, secret=1)
    m.add((LEA_MARTIN,), (), "Léa Martin compte pour Adrien.")  # une réflexion, sans rien de secret : à personne
    m.add((LEA,), (ADRIEN,), "Léa, une pensée pour moi seule.", internal_only=1)
    m.add((CAROL,), (ADRIEN,), "Carol, ce que ses sources restreignent.",
          constraints=json.dumps([{"told_by": [ADRIEN], "secret": True}]))
    m.add((CAROL,), (BEA,), "Carol, une enveloppe illisible.", constraints="pas du json")
    world.run()
    assert world.told(LEA_MARTIN) is None and world.told(LEA) is None and world.told(CAROL) is None
    assert world.contacts.page(size=50).total == 0 and world.contacts.sources() == []
    for envelope in ((1, 0, "[]"), (0, 1, "[]"), (0, 0, '[{"secret": true}]'), (0, 0, "{")):
        assert not confided(*envelope), envelope
    assert confided(0, 0, "[]") and confided(None, None, None)


def test_names_ingested_under_the_former_rule_disappear_on_the_next_pass(world):
    """Relecture C1, ce qui était déjà rangé : une vue ``(told, elle)`` née d'une réflexion, et un secret confié par
    Adrien, rangés sous l'ancienne règle, partent au passage suivant (toute sa mémoire se relit sous la règle neuve) ;
    ce qu'on lui a vraiment confié reste, avec ses liens et ses réunions."""
    m = world.mind
    secret = m.add((LEA_MARTIN,), (ADRIEN,), "Léa Martin traverse une passe difficile.", secret=1)
    m.add((LEA,), (ADRIEN,), "Léa déménage à Lyon.")
    m.add((CAROL,), (BEA,), "Carol a gagné le tournoi.")
    asyncio.run(world.contacts.observe([  # ce que l'ancienne règle avait rangé
        Observation(TOLD_NAME, CAROL, TOLD, SELF, "Carol", 1, NOW, NOW),
        Observation(TOLD_NAME, LEA_MARTIN, TOLD, SELF, "Léa Martin", 1, NOW, NOW),
        Observation(TOLD_NAME, LEA_MARTIN, TOLD, ADRIEN, "Léa Martin", 1, NOW, NOW),
        Observation(TOLD_NAME, LEA, TOLD, ADRIEN, "Léa", 1, NOW, NOW),
        Observation(EMAIL, "lea@calix.fr", MAIL, "pro", "Léa", 1, NOW, NOW)]))
    world.contacts.set_cursor(CURSOR_TOLD, secret + 10)  # tout avait été lu
    world.contacts.merge(world.contacts.contact_of(EMAIL, "lea@calix.fr"), world.contacts.contact_of(TOLD_NAME, LEA))
    world.contacts.link(world.contacts.contact_of(TOLD_NAME, LEA), "ext_7")
    assert world.contacts.cursor(CURSOR_TOLD_RULE) == 0
    world.run()
    assert world.told(LEA_MARTIN) is None  # le secret, et la réflexion
    lea, carol = world.told(LEA), world.told(CAROL)
    assert {(x.account, x.count) for x in carol.identifiers[0].sightings} == {(BEA, 1)}  # plus à tout le monde
    assert lea.person == "ext_7" and {i.kind for i in lea.identifiers} == {TOLD_NAME, EMAIL}  # sa réunion, son lien
    told = next(i for i in lea.identifiers if i.kind == TOLD_NAME)
    assert {(x.account, x.count) for x in told.sightings} == {(ADRIEN, 1)}  # relue une fois, pas deux
    assert (TOLD, SELF) not in world.contacts.sources()
    assert world.contacts.cursor(CURSOR_TOLD_RULE) == TOLD_RULE and world.contacts.cursor(CURSOR_TOLD_REBUILD) == 0
    world.run()  # la règle est la même : rien ne se relit
    assert {(x.account, x.count) for x in next(i for i in world.told(LEA).identifiers
                                                  if i.kind == TOLD_NAME).sightings} == {(ADRIEN, 1)}
