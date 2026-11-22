"""Les messages de la personne d'un compte Teams sont les siens, même quand l'extension ne l'a pas dit.

Le 2026-11-22, un tête-à-tête avec Gilles s'appelait « Adrien » : les messages d'Adrien captés en direct (ADR 0251)
arrivaient avec `own` faux — leur auteur n'avait pas la forme exacte que l'extension compare —, et le nom d'un
tête-à-tête, c'est le dernier à y avoir écrit qui n'est pas la personne du compte. Le serveur connaît le compte : il
reconnaît ses messages par son identifiant (quelle que soit sa forme), ou, sans identifiant, par son nom. Ce qui avait
été rangé de travers ne se convertit pas : `mika teams purge`, puis l'historique rechargé depuis l'extension.
"""

from __future__ import annotations

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.adapters.teams.store import same_person, written_by_self
from mika.app.teams import batch_of
from mika.ports.teams import DEFAULT_ACCOUNT as PRINCIPAL
from mika.sim.clock import SimClock
from mika.sim.lane import at_paris

START = at_paris(2026, 11, 20, 10, 0)
ME = "3e51ce13-6eb8-463b-a75a-a40b2ab67602"
GILLES = "8:orgid:de50c847-308e-4100-a076-6163609ba794"
DM = f"19:{ME}_de50c847-308e-4100-a076-6163609ba794@unq.gbl.spaces"


def lot(clock: SimClock, *messages: tuple[int, str, str, bool]) -> dict:
    return {"self": {"id": f"8:orgid:{ME}", "name": "Adrien FAVERAUX-EXT"},
            "conversations": [{"id": DM, "title": "", "kind": "dm"}],
            "messages": [{"id": str(1_763_000_000_000 + n), "conv": DM, "author": author, "author_id": author_id,
                          "time": clock.now() // 1000 + n, "text": f"message {n}", "own": own}
                         for n, author, author_id, own in messages]}


def test_an_author_id_in_another_form_or_missing_still_reads_as_the_account_person():
    assert same_person(f"orgid:{ME.upper()}", f"8:orgid:{ME}")
    assert same_person(f"https://emea.ng.msg.teams.microsoft.com/v1/users/ME/contacts/8:orgid:{ME}", f"8:orgid:{ME}")
    assert not same_person(GILLES, f"8:orgid:{ME}")
    assert written_by_self("", "Adrien FAVERAUX-EXT", f"8:orgid:{ME}", "Adrien FAVERAUX-EXT")
    assert not written_by_self("", "Gilles ROSSIGNEUX", f"8:orgid:{ME}", "Adrien FAVERAUX-EXT")
    # un autre identifiant au même nom n'est pas la personne du compte
    assert not written_by_self(GILLES, "Adrien FAVERAUX-EXT", f"8:orgid:{ME}", "Adrien FAVERAUX-EXT")


def test_own_messages_the_extension_missed_are_kept_as_hers_and_the_dm_keeps_the_other_name(tmp_path):
    clock = SimClock(START)
    store = TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=clock.now)
    try:
        batch = lot(clock, (1, "Gilles ROSSIGNEUX", GILLES, False),
                    (2, "Adrien FAVERAUX-EXT", f"orgid:{ME}", False),   # une autre forme d'identifiant
                    (3, "Adrien FAVERAUX-EXT", "", False))               # pas d'identifiant du tout
        store.store_batch(PRINCIPAL, batch_of(batch, clock.now() // 1000)[0], clock.now())
        thread = sorted(store.thread(PRINCIPAL, DM, 10), key=lambda m: m.at)
        assert [(m.author, m.own) for m in thread] == [
            ("Gilles ROSSIGNEUX", False), ("Adrien FAVERAUX-EXT", True), ("Adrien FAVERAUX-EXT", True)]
        assert store.title(PRINCIPAL, DM) == "Gilles ROSSIGNEUX"
    finally:
        store.close()
