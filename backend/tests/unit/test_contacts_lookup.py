"""Ce qu'elle sait de ses contacts, quand elle parle (ADR 0298, lot 6) : l'outil ``contacts_lookup``.

- **à qui** : seulement en tête-à-tête, avec une personne reconnue — jamais dans un salon, jamais à une inconnue ;
  réservé à ses propriétaires par défaut (la famille « contacts » de ses droits peut l'ouvrir) ;
- **ce qu'il dit** : la fiche et les faits que la personne en face voit — ce qu'elle a lu dans le Teams d'Adrien se dit
  à Adrien, jamais à Béa ; ses phrases viennent de sa voix, ce qui vient d'ailleurs y est inerte ;
- **de quoi agir** (le 2026-11-22) : comment la joindre, où elle écrit (avec la référence que ``teams_read`` et
  ``email_read`` relisent), chaque fait daté, à qui de l'identité la fiche est reliée (à ses propriétaires), les
  personnes qu'elle connaît dans une organisation. Avant, l'outil ne disait que le poste, les sources et les faits :
  elle ne pouvait ni écrire à la personne, ni relire où elle écrit, ni juger si un fait était encore vrai.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from mika.adapters.contacts import ContactsStore
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.app.domains.teams.desk import batch_of
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.kernel.frame import Audience
from mika.plugins.contacts import BUNDLE, CONTACTS
from mika.plugins.contacts.tools import LookupArgs, contacts_lookup
from mika.ports.contacts import (
    DOMAIN,
    EMAIL,
    MAIL,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    Note,
    Observation,
    Portrait,
    phone_app_value,
)
from mika.ports.mail import Mail
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
HOUR = 3_600_000_000
ADRIEN, BEA, CHLOE = "user_1", "user_2", "user_3"
PARIS = ZoneInfo("Europe/Paris")


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


#: qui lui a déjà écrit (``transcript.LAST_FROM`` de sa clé) : l'instant
HEARD: dict[str, int] = {}


def known(key):
    if key == identity_c.OWNERS:
        return (ADRIEN,)
    if key == identity_c.IDENTITY(CHLOE):
        return SimpleNamespace(name="Chloé")
    if key == transcript_c.LAST_FROM(CHLOE):
        return HEARD.get(CHLOE, 0)
    return None


def ask(ports, audience: Audience | None, name: str = "Gilles") -> object:
    frame = SimpleNamespace(audience=audience, episode=SimpleNamespace(kind="REPLY"), get=known,
                            local=lambda t=None: datetime.fromtimestamp((NOW if t is None else t) / 1e6, PARIS))
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


def test_it_gives_what_she_needs_to_act_on_what_her_own_accounts_show(ports):
    """Comment le joindre (jamais son identifiant Teams), combien de fois et quand elle le voit, ses autres noms, et
    chaque fait daté avec la référence de son message — dans ce que la personne en face voit seulement."""
    contacts = ports["contacts"]
    contacts.observe_now([
        Observation(EMAIL, "gilles.rousseau@lumen.fr", TEAMS, "equipe", "Gilles Rousseau", 1, NOW - HOUR, NOW,
                    joins=(TEAMS_ID, "8:orgid:gilles"), proof=True),
        Observation(PHONE, "+33612345678", TEAMS, "equipe", "Gilles Rousseau", 1, NOW - HOUR, NOW,
                    joins=(TEAMS_ID, "8:orgid:gilles"))])
    to_adrien = ask(ports, private(ADRIEN, owner=True))
    assert phrase("contacts.tools.lookup.ways", ways="e-mail gilles.rousseau@lumen.fr ; téléphone +33612345678") \
        in to_adrien
    assert "8:orgid:gilles" not in to_adrien
    assert phrase("contacts.tools.lookup.last", count=6, when="aujourd'hui") in to_adrien
    assert "(lu dans Teams, en tête-à-tête, aujourd'hui, sûr à 80 %) [m1]" in to_adrien
    to_bea = ask(ports, private(BEA, owner=False))
    assert "lumen.fr" not in to_bea and "+33" not in to_bea  # vus dans le Teams d'Adrien
    assert phrase("contacts.tools.lookup.also_named", names="Gilles Rousseau") not in to_bea


def test_it_says_where_he_writes_with_the_reference_teams_read_rereads(ports):
    teams = ports["teams"]
    dm = "19:adrien_gilles@unq.gbl.spaces"
    lot = {"self": {"id": "8:orgid:adrien", "name": "Adrien"},
           "conversations": [{"id": dm, "title": "", "kind": "dm"},
                             {"id": "19:migration@thread.v2", "title": "Migration", "kind": "group"}],
           "messages": [{"id": "1789999000001", "conv": dm, "author": "Gilles Rousseau", "author_id": "8:orgid:gilles",
                         "time": (NOW - 2 * HOUR) // 1000, "text": "tu as vu le devis ?"},
                        {"id": "1789999000002", "conv": dm, "author": "Adrien", "author_id": "8:orgid:adrien",
                         "time": (NOW - HOUR) // 1000, "text": "oui"},
                        {"id": "1789999000003", "conv": "19:migration@thread.v2", "author": "Gilles Rousseau",
                         "author_id": "8:orgid:gilles", "time": (NOW - 30 * 24 * HOUR) // 1000, "text": "go"}]}
    teams.store_batch("equipe", batch_of(lot, NOW // 1000)[0], NOW)
    to_adrien = ask(ports, private(ADRIEN, owner=True))
    (line,) = [x for x in to_adrien.splitlines() if x.startswith("  · sur Teams")]
    assert line.startswith(phrase("contacts.tools.lookup.on_teams", places="en tête-à-tête (un message, le dernier "
                                                                           "aujourd'hui) ["))
    last = teams.last_messages([("equipe", dm)])[("equipe", dm)]
    assert f"[{last.ref}]" in line  # le dernier message de la conversation : teams_read la relit
    assert "dans le groupe « Migration » (un message, le dernier le " in line
    assert "sur Teams" not in ask(ports, private(BEA, owner=False))  # le compte d'Adrien


def test_his_last_mails_from_the_boxes_she_reads_for_the_person(ports):
    contacts = ports["contacts"]
    contacts.observe_now([Observation(EMAIL, "gilles.rousseau@lumen.fr", MAIL, "pro", "Gilles Rousseau", 3,
                                      NOW - HOUR, NOW, joins=(TEAMS_ID, "8:orgid:gilles"), proof=True)])
    asked: list[tuple] = []

    def letters_from(address, *, since=0, limit=30, accounts=None):
        asked.append((address, tuple(accounts or ())))
        return [Mail("<a@lumen.fr>", "Gilles <gilles.rousseau@lumen.fr>", address, "Devis migration", NOW - 24 * HOUR,
                     "Bonjour", account="pro")]

    ports = {**ports, "mail": SimpleNamespace(accounts=lambda: [SimpleNamespace(key="pro", owner="personne:" + ADRIEN)],
                                              letters_from=letters_from)}
    got = ask(ports, private(ADRIEN, owner=True))
    assert asked == [("gilles.rousseau@lumen.fr", ("pro",))]
    (line,) = [x for x in got.splitlines() if x.startswith("  · ses derniers mails")]
    assert line.startswith("  · ses derniers mails : un mail, objet « Devis migration », hier [")


def test_his_conversations_on_the_phone_of_the_person(ports):
    contacts = ports["contacts"]
    value = phone_app_value("whatsapp", "phone:abc123:Gilles boulot")
    contacts.observe_now([Observation(PHONE_APP, value, PHONE_SOURCE, ADRIEN, "Gilles boulot", 2, NOW - HOUR, NOW,
                                      thread="t1")])
    got = ask(ports, private(ADRIEN, owner=True), "Gilles boulot")
    assert phrase("contacts.tools.lookup.on_phone", places="en tête-à-tête (WhatsApp, sous le nom « Gilles boulot »), "
                                                           "aujourd'hui") in got
    assert value not in got and "abc123" not in got  # une clé du téléphone ne se dit pas


def test_who_of_her_own_people_it_is_said_only_to_her_owners(ports, monkeypatch):
    """La fiche est reliée à Chloé : à Adrien (un propriétaire, qui le voit dans la console), elle « a un compte »
    tant qu'elle n'a pas écrit, puis « te parle aussi » (ADR 0298) ; à Béa, rien."""
    contacts = ports["contacts"]
    contacts.link(contacts.contact_of(TEAMS_ID, "8:orgid:gilles"), CHLOE)
    assert phrase("contacts.tools.lookup.has_account", name="Chloé") in ask(ports, private(ADRIEN, owner=True))
    monkeypatch.setitem(HEARD, CHLOE, NOW - HOUR)
    to_adrien = ask(ports, private(ADRIEN, owner=True))
    assert phrase("contacts.tools.lookup.talks_to_you", name="Chloé") in to_adrien
    assert phrase("contacts.tools.lookup.has_account", name="Chloé") not in to_adrien
    assert "Chloé" not in ask(ports, private(BEA, owner=False))


def test_an_organisation_says_its_domain_its_generic_addresses_and_who_she_knows_there(ports):
    contacts = ports["contacts"]
    contacts.observe_now([
        Observation(EMAIL, "gilles.rousseau@lumen.fr", TEAMS, "equipe", "Gilles Rousseau", 1, NOW - HOUR, NOW,
                    joins=(TEAMS_ID, "8:orgid:gilles"), proof=True),
        Observation(EMAIL, "support@lumen.fr", TEAMS, "equipe", "Support Lumen", 1, NOW - HOUR, NOW)])
    contacts.observe_now([Observation(DOMAIN, "lumen.fr", TEAMS, "equipe", "Lumen", 1, NOW, NOW)])
    got = ask(ports, private(ADRIEN, owner=True), "lumen")
    org = got[got.index("(" + phrase("contacts.tools.lookup.org") + ")"):]
    assert phrase("contacts.tools.lookup.ways", ways="adresse générique support@lumen.fr") in org
    assert phrase("contacts.tools.lookup.members", names="Gilles Rousseau") in org
    # un domaine n'est pas un moyen de la joindre : il se dit sur sa ligne, quand son nom n'est pas lui
    head = got[got.rindex("\n", 0, got.index(org)) + 1:].splitlines()[0]
    assert (phrase("contacts.tools.lookup.domain", domain="lumen.fr") in head) == (not head.startswith("- lumen.fr "))
    assert "domaine" not in org.splitlines()[1]
