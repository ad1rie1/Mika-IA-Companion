"""Ce que l'oubli d'une fiche de l'annuaire atteint, et ce qu'il épargne (ADR 0298) : sur le vrai annuaire, l'identité
en doublure (ses faits ``IDENTITY`` et ``PERSON``).

- **oublier une personne qui lui parle** atteint aussi ce que l'annuaire lit d'elle par ses fiches reliées : leurs
  identifiants Teams, leurs adresses, leurs clés du téléphone, leurs noms racontés — que Teams, le courrier et sa
  mémoire gardent sous eux ;
- **oublier une fiche de l'annuaire** n'ampute jamais une personne qui lui parle : ni un de ses moyens de
  communication (reliée ou non à la fiche), ni un nom que l'identité relie à elle.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.contracts import identity as identity_c
from mika.faculties.identity.inspect import directory_aliases
from mika.plugins.contacts.inspect import aliases_of
from mika.ports.contacts import EMAIL, PHONE_APP, PHONE_SOURCE, TEAMS, TEAMS_ID, TOLD, TOLD_NAME, Observation
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
LEA = "name:aaaaaaaaaaaaaaaa:lea martin"


@pytest.fixture
def store(tmp_path):
    found = ContactsStore(backend.target(tmp_path, "contacts"), now=lambda: NOW)
    yield found
    found.close()


class Identity:
    """L'identité en doublure : les moyens de communication qu'elle connaît, les noms qu'elle relie à une personne."""

    def __init__(self, handles: dict[str, str], names: dict[str, str]) -> None:
        self.handles, self.names = handles, names

    def get(self, key):
        if key.family is identity_c.IDENTITY:
            return SimpleNamespace(known=key.arg in self.handles, person=self.handles.get(key.arg, key.arg))
        if key.family is identity_c.PERSON:
            return self.handles.get(key.arg) or self.names.get(key.arg) or key.arg
        return None


def gilles(store: ContactsStore) -> int:
    store.observe_now([
        Observation(TEAMS_ID, "8:orgid:gilles", TEAMS, "equipe", "Gilles Rousseau", 3, NOW, NOW),
        Observation(EMAIL, "gilles@nordis.fr", TEAMS, "equipe", "Gilles Rousseau", 0, NOW, NOW,
                    joins=(TEAMS_ID, "8:orgid:gilles"), proof=True),
        Observation(PHONE_APP, "whatsapp:abc123", PHONE_SOURCE, "user_1", "Gilles", 2, NOW, NOW,
                    joins=(TEAMS_ID, "8:orgid:gilles")),
        Observation(TOLD_NAME, LEA, TOLD, "user_1", "Léa Martin", 1, NOW, NOW)])
    cid = store.contact_of(TEAMS_ID, "8:orgid:gilles")
    store.merge(cid, store.contact_of(TOLD_NAME, LEA))
    return cid


def test_forgetting_someone_who_talks_to_her_reaches_her_linked_directory_entries(store):
    """Relecture I6 : Gilles lui parle par le chat ; sa fiche reliée de l'annuaire a son identifiant Teams et son
    adresse pro, qui ne sont pas des moyens de communication de l'identité. Oublier la personne ne les atteignait pas :
    Teams gardait ses messages et son profil, le courrier ses mails — et il revenait dans l'annuaire."""
    cid = gilles(store)
    store.link(cid, "ext_5")
    journal = SimpleNamespace(subjects=lambda prefix: [f"{prefix}Gilles"] if prefix == "phone:abc123:" else [])
    ctx = SimpleNamespace(ports={"contacts": store}, store=journal)
    got = directory_aliases(ctx, "ext_5")
    assert set(got) == {"teams:8:orgid:gilles", "mail:gilles@nordis.fr", "phone:abc123:Gilles", LEA}
    assert directory_aliases(ctx, "ext_9") == () and directory_aliases(SimpleNamespace(ports={}, store=None),
                                                                       "ext_5") == ()


def test_forgetting_an_unlinked_entry_never_forgets_a_handle_or_a_name_of_someone_who_talks_to_her(store):
    """Relecture I7 : la fiche « connue de loin » ``gilles@nordis.fr`` n'est pas reliée, mais cette adresse est aussi un
    moyen de communication de Gilles qui lui écrit, et « Léa Martin » un nom que l'identité relie à Léa. L'oublier
    lançait ``mail:gilles@nordis.fr`` et ``name:…`` : l'identité perdait un moyen de Gilles, sa mémoire ce qu'il avait
    confié par lui. Seul ce qui n'est à personne qui lui parle reste dans l'oubli."""
    cid = gilles(store)
    sheet = store.sheet(cid)
    nobody = Identity({}, {})
    assert set(aliases_of(sheet, (), None, nobody)) == {"teams:8:orgid:gilles", "mail:gilles@nordis.fr", LEA}
    talking = Identity({"mail:gilles@nordis.fr": "ext_5"}, {LEA: "ext_7"})
    assert aliases_of(sheet, (), None, talking) == ("teams:8:orgid:gilles",)
    # une mention que l'identité ne relie qu'à un nom, ou à rien, reste à oublier avec la fiche
    assert LEA in aliases_of(sheet, (), None, Identity({}, {LEA: "name:bbbbbbbbbbbbbbbb:lea"}))
    assert {a for a in aliases_of(store.sheet(cid), (), None, None)} >= {"mail:gilles@nordis.fr", LEA}
