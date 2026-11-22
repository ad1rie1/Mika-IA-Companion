"""Ce qu'elle sait de ses contacts, quand elle parle (ADR 0298, lot 6) : l'outil ``contacts_lookup``.

- **à qui** : seulement en tête-à-tête, avec une personne reconnue — jamais dans un salon, jamais à une inconnue ;
  réservé à ses propriétaires par défaut (la famille « contacts » de ses droits peut l'ouvrir) ;
- **ce qu'il dit** : la fiche et les faits que la personne en face voit — ce qu'elle a lu dans le Teams d'Adrien se dit
  à Adrien, jamais à Béa ; ses phrases viennent de sa voix, ce qui vient d'ailleurs y est inerte.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.contracts import identity as identity_c
from mika.kernel.frame import Audience
from mika.plugins.contacts import BUNDLE, CONTACTS
from mika.plugins.contacts.tools import LookupArgs, contacts_lookup
from mika.ports.contacts import TEAMS, TEAMS_ID, Note, Observation, Portrait
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
HOUR = 3_600_000_000
ADRIEN, BEA = "user_1", "user_2"


@pytest.fixture
def ports(tmp_path):
    teams = TeamsStore(lambda: TeamsConfig(accounts={"equipe": TeamsAccount(owner="personne:" + ADRIEN),
                                                     "autre": TeamsAccount(owner="personne:" + BEA)}),
                       tmp_path / "teams.db", now=lambda: NOW)
    contacts = ContactsStore(backend.target(tmp_path, "contacts"), now=lambda: NOW)
    contacts.observe_now([
        Observation(TEAMS_ID, "8:orgid:gilles", TEAMS, "equipe", "Gilles Rousseau", 4, NOW - HOUR, NOW,
                    title="Responsable réseau"),
        Observation(TEAMS_ID, "8:orgid:gilles", TEAMS, "autre", "Gilles R.", 2, NOW - HOUR, NOW - 1)])
    gilles = contacts.contact_of(TEAMS_ID, "8:orgid:gilles")
    for account, text in (("equipe", "Il pilote la migration des centrales."),
                          ("autre", "Il cherche un nouveau poste.")):
        contacts.portrayed(Portrait(gilles, TEAMS, account, NOW), [
            Note(0, gilles, TEAMS, account, text, "role", 0.8, "m1", "en tête-à-tête", NOW, NOW, "run#1")])
    yield {"teams": teams, "contacts": contacts}
    teams.close()
    contacts.close()


def ask(ports, audience: Audience | None, name: str = "Gilles") -> object:
    frame = SimpleNamespace(audience=audience, episode=SimpleNamespace(kind="REPLY"),
                            get=lambda key: (ADRIEN,) if key == identity_c.OWNERS else None)
    return asyncio.run(contacts_lookup(LookupArgs(name=name), SimpleNamespace(frame=frame, ports=ports)))


def private(person: str, *, owner: bool) -> Audience:
    return Audience(persons=(person,), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                    person=person, owner=owner)


def test_it_says_to_each_person_only_what_her_own_accounts_show(ports):
    to_adrien = ask(ports, private(ADRIEN, owner=True))
    assert to_adrien.startswith(phrase("contacts.tools.lookup.data"))
    assert "Gilles Rousseau" in to_adrien and "Responsable réseau" in to_adrien
    assert "Il pilote la migration des centrales." in to_adrien and "sûr à 80 %" in to_adrien
    assert "nouveau poste" not in to_adrien and "Gilles R." not in to_adrien  # lu dans le Teams de Béa
    to_bea = ask(ports, private(BEA, owner=False))
    assert "Il cherche un nouveau poste." in to_bea and "migration" not in to_bea
    assert "Responsable réseau" not in to_bea  # le poste vient d'une vue d'Adrien
    assert ask(ports, private(ADRIEN, owner=True), "Zoé") == phrase("contacts.tools.lookup.nobody", name="Zoé")


def test_never_in_a_room_nor_to_a_stranger_nor_without_anyone(ports):
    room = Audience(persons=(ADRIEN, BEA), channel="web", room="salon", public=True,
                    trust=ChannelTrust.AUTHENTICATED.value, person=ADRIEN, owner=True)
    stranger = Audience(persons=("ext_1",), channel="web", public=False, trust=ChannelTrust.ACCOUNT.value,
                        person="ext_1")
    for audience in (room, stranger, None):
        got = ask(ports, audience)
        assert not got.ok and got.content == phrase("contacts.tools.lookup.not_here"), audience
    assert not ask({}, private(ADRIEN, owner=True)).ok  # sans annuaire


def test_the_tool_is_hers_owner_only_in_its_own_family():
    (spec,) = [t for t in CONTACTS.tools if t.name == "contacts_lookup"]
    assert spec.owner_only and spec.bundle == BUNDLE == "contacts" and not spec.acts
    assert spec.label == phrase("contacts.tools.lookup.label") and BUNDLE in CONTACTS.bundles


def test_the_person_facing_her_is_not_counted_among_the_others(ports):
    """Relecture, mineur 9 : cinq « Gilles » visibles d'Adrien, dont sa propre fiche (reliée à lui) : trois sont dits,
    il en reste un. Avant, sa propre fiche prenait une place de la lecture (le quatrième restait caché) et comptait
    parmi les « autres »."""
    contacts = ports["contacts"]
    contacts.observe_now([Observation(TEAMS_ID, f"8:orgid:g{i}", TEAMS, "equipe", f"Gilles {i}", 1, NOW - i, NOW - i)
                          for i in range(1, 5)])
    contacts.link(contacts.contact_of(TEAMS_ID, "8:orgid:g3"), ADRIEN)  # sa propre fiche
    got = ask(ports, private(ADRIEN, owner=True))
    assert "Gilles 3" not in got and got.count("\n- ") == 3
    assert got.endswith(phrase("contacts.tools.lookup.more", count=1))
