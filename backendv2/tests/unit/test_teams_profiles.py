"""Les profils des personnes croisées dans Teams (ADR 0298, lot 2), dans le cache de Teams (``TeamsStore``).

- **un profil par compte et par personne**, tel que l'extension l'a envoyé en dernier ; chaque changement (neuf, ou
  vraiment changé) prend le rang suivant, un profil redit tel quel ne bouge pas ;
- **``profiles_since``** relit les changements dans l'ordre de leurs rangs, par pages bornées, et ne saute rien : un
  rang ne resert jamais, même quand le dernier profil part ; un curseur au-delà du compteur repart de lui ;
- **l'oubli** de ``teams:<identifiant>`` emporte son profil dans tous les comptes ; un compte supprimé, les siens.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.ports.teams import InboxBatch, InboxProfile
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
GILLES = "8:orgid:0b5c1a2e-0000-4000-8000-000000000001"
LEA = "8:orgid:0b5c1a2e-0000-4000-8000-000000000002"


class Clock:
    def __init__(self) -> None:
        self.t = NOW

    def __call__(self) -> int:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    found = TeamsStore(lambda: TeamsConfig(), backend.target(tmp_path, "teams"), now=clock)
    yield found
    found.close()


def gilles(**more) -> InboxProfile:
    return InboxProfile(**{"id": GILLES, "name": "Gilles Rousseau", "email": "gilles@nordis.fr",
                           "title": "Chef de projet", "company": "Nordis", "department": "Achats",
                           "tenant": "Nordis", "phones": ("+33 6 12 34 56 78",), **more})


def push(store: TeamsStore, account: str, *profiles: InboxProfile, now: int = NOW) -> int:
    return store.store_batch(account, InboxBatch(self_id="8:orgid:moi", profiles=profiles), now).profiles


def test_a_profile_is_kept_per_account_and_person_and_each_change_takes_the_next_rank(store):
    assert push(store, "adrien", gilles(), InboxProfile(LEA, "Léa Martin")) == 2
    got = store.profiles_since(0, 10)
    assert [(p.account, p.id, p.seq) for p in got.profiles] == [("adrien", GILLES, 1), ("adrien", LEA, 2)]
    first = got.profiles[0]
    assert (first.name, first.email, first.title, first.company, first.department, first.tenant, first.phones,
            first.updated) == ("Gilles Rousseau", "gilles@nordis.fr", "Chef de projet", "Nordis", "Achats",
                               "Nordis", ("+33 6 12 34 56 78",), NOW)
    assert (got.cursor, got.more) == (2, False)
    # redit tel quel (l'extension relancée) : rien ne bouge, rien à relire
    assert push(store, "adrien", gilles(), now=NOW + 5) == 0
    assert store.profiles_since(got.cursor, 10).profiles == ()
    # vraiment changé : le rang suivant, et seulement lui à relire, à son dernier état
    assert push(store, "adrien", gilles(title="Directeur des achats"), now=NOW + 9) == 1
    (changed,) = store.profiles_since(got.cursor, 10).profiles
    assert (changed.id, changed.title, changed.seq, changed.updated) == (GILLES, "Directeur des achats", 3, NOW + 9)
    # la même personne vue par un autre compte : un profil à elle sous ce compte
    assert push(store, "bea", gilles(title="")) == 1
    assert [(p.account, p.title) for p in store.profiles_since(3, 10).profiles] == [("bea", "")]


def test_the_last_profile_of_a_person_in_a_batch_wins_and_its_id_is_read_in_lowercase(store):
    assert push(store, "adrien", gilles(id=GILLES.upper(), title="Avant"), gilles(title="Après")) == 1
    (p,) = store.profiles_since(0, 10).profiles
    assert (p.id, p.title) == (GILLES, "Après")


def test_profiles_since_reads_in_bounded_pages_and_skips_nothing(store):
    ids = [f"8:orgid:0b5c1a2e-0000-4000-8000-00000000010{n}" for n in range(5)]
    push(store, "adrien", *(InboxProfile(i, f"Personne {n}") for n, i in enumerate(ids)))
    first = store.profiles_since(0, 2)
    assert [p.name for p in first.profiles] == ["Personne 0", "Personne 1"] and first.more
    second = store.profiles_since(first.cursor, 2)
    third = store.profiles_since(second.cursor, 2)
    assert [p.name for p in (*second.profiles, *third.profiles)] == ["Personne 2", "Personne 3", "Personne 4"]
    assert not third.more and store.profiles_since(third.cursor, 2).profiles == ()


def test_a_rank_is_never_given_twice_even_when_the_last_profile_leaves(store):
    push(store, "adrien", InboxProfile(LEA, "Léa Martin"), gilles())
    cursor = store.profiles_since(0, 10).cursor
    assert cursor == 2
    assert asyncio.run(store.forget("teams:" + GILLES)) >= 1  # le dernier rang part
    push(store, "adrien", InboxProfile("8:live:camille", "Camille"))
    (p,) = store.profiles_since(cursor, 10).profiles
    assert (p.name, p.seq) == ("Camille", 3)  # pas le rang 2 de nouveau : la lecture ne le saute pas


def test_a_cursor_beyond_the_counter_starts_again_from_it(store):
    push(store, "adrien", gilles())
    late = store.profiles_since(99, 10)  # une base ``teams`` revenue d'une sauvegarde plus ancienne
    assert (late.profiles, late.cursor) == ((), 1)
    push(store, "adrien", InboxProfile(LEA, "Léa Martin"))
    assert [p.id for p in store.profiles_since(late.cursor, 10).profiles] == [LEA]


def test_forgetting_a_person_and_dropping_an_account_take_their_profiles(store):
    push(store, "adrien", gilles(), InboxProfile(LEA, "Léa Martin"))
    push(store, "bea", gilles())
    asyncio.run(store.forget("teams:" + GILLES.upper()))  # dans tous les comptes, quelle que soit la casse
    assert [(p.account, p.id) for p in store.profiles_since(0, 10).profiles] == [("adrien", LEA)]
    push(store, "bea", InboxProfile(LEA, "Léa M."))
    assert store.drop_account("adrien") >= 1
    assert [(p.account, p.name) for p in store.profiles_since(0, 10).profiles] == [("bea", "Léa M.")]
