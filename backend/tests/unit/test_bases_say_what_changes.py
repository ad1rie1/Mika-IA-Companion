"""Les bases tenues à côté du journal disent ce que change chacune de leurs écritures, une fois validée (ADR 0308).

- ce qui est noté pendant une écriture part à sa validation (la plus extérieure), rien d'une écriture annulée, et un
  écouteur en panne ne défait rien ni ne prive les autres (``adapters/changes.py``) ;
- le courrier relevé dit ses boîtes, le cache de Teams ses comptes et ses conversations, sa boîte d'envoi à part,
  l'annuaire ses sources ; ce qui ne change rien de ce qu'une personne voit ne dit rien.

Que chaque écriture le dise, la garde d'architecture le vérifie (``tests/architecture/test_changes_signalled.py``).
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from mika.adapters.changes import Changes
from mika.adapters.contacts import ContactsStore
from mika.adapters.mail.cache import MailCache
from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.ports.changes import CONTACTS, MAIL, MAIL_DRAFTS, OUTBOX, TEAMS, TEAMS_DRAFTS, Change
from mika.ports.contacts import EMAIL, Observation
from mika.ports.contacts import MAIL as MAIL_SOURCE
from mika.ports.gate import ACCEPTED
from mika.ports.mail import Draft, Mail
from mika.ports.teams import DEFAULT_ACCOUNT as P
from mika.ports.teams import Draft as TeamsDraft
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage

NOW = 1_790_000_000_000_000
DM = "19:alice_adrien@unq.gbl.spaces"


def heard(base) -> list[Change]:
    said: list[Change] = []
    base.on_change(said.append)
    return said


# ── la mécanique ──


def test_what_a_write_notes_is_told_once_it_is_committed_and_never_if_it_fails():
    changes, said = Changes(), []
    changes.listen(said.append)
    changes.note(Change(MAIL, ("pro",)))  # hors d'une écriture : aussitôt
    assert said == [Change(MAIL, ("pro",))]
    with changes.writing():
        changes.note(Change(MAIL, ("perso",)))
        with changes.writing():  # une écriture dans une écriture : c'est la plus extérieure qui valide
            changes.note(Change(MAIL, ("perso",)))
        assert said == [Change(MAIL, ("pro",))]
    assert said == [Change(MAIL, ("pro",)), Change(MAIL, ("perso",))]  # dit une fois
    with pytest.raises(RuntimeError), changes.writing():
        changes.note(Change(MAIL_DRAFTS, ("pro",)))
        raise RuntimeError("annulée")
    assert said[-1] == Change(MAIL, ("perso",))


def test_a_failing_listener_neither_undoes_the_write_nor_deprives_the_others():
    changes, said = Changes(), []

    def broken(change: Change) -> None:
        raise ValueError("en panne")

    changes.listen(broken)
    changes.listen(said.append)
    with changes.writing():
        changes.note(Change(TEAMS))
    assert said == [Change(TEAMS)]


def test_a_note_from_another_thread_is_not_mixed_into_the_write_in_progress():
    changes, said = Changes(), []
    changes.listen(said.append)
    with changes.writing():
        other = threading.Thread(target=changes.note, args=(Change(CONTACTS),))
        other.start()
        other.join()
        assert said == [Change(CONTACTS)]  # dite aussitôt, dans son fil : elle n'attend pas une écriture d'ailleurs


# ── le courrier relevé ──


def mail(mid: str, **more) -> Mail:
    return Mail(mid, "Léa <lea@x.fr>", "lea@x.fr", "Maquettes", NOW // 1000, "Bonjour", **{"account": "pro",
                                                                                         "folder": "INBOX", **more})


def test_the_mail_cache_says_its_box_once_the_mail_is_committed(tmp_path):
    cache = MailCache(tmp_path / "mail.db")
    try:
        seen_then: list[int] = []

        def check(change: Change) -> None:  # une autre connexion ne voit que ce qui est validé
            with sqlite3.connect(tmp_path / "mail.db") as other:
                seen_then.append(other.execute("select count(*) from messages").fetchone()[0])

        cache.on_change(check)
        said = heard(cache)
        cache.store(mail("<a@x.fr>"), 1)
        assert said == [Change(MAIL, ("pro",))] and seen_then == [1]
        cache.set_flags("pro", "INBOX", 1, seen=True)
        cache.recount("pro", "INBOX")  # ses compteurs ont changé (son dossier se montre autrement) : dit une fois
        assert said[1:] == [Change(MAIL, ("pro",)), Change(MAIL, ("pro",))]
        cache.recount("pro", "INBOX")  # rien n'a bougé : rien à dire
        assert len(said) == 3
    finally:
        cache.close()


def test_held_writes_are_told_once_at_the_end_even_when_the_block_fails():
    """Un passage de l'historique, le rangement d'un dossier : ce que valident ses écritures part une fois, à la fin —
    chaque changement une seule fois ; ce qui a été validé part même si le bloc lève ; un autre fil n'est pas retenu."""
    changes, said = Changes(), []
    changes.listen(said.append)
    with changes.held():
        for box in ("pro", "pro", "perso"):
            with changes.writing():
                changes.note(Change(MAIL, (box,)))
        with changes.held():  # un bloc dans un autre ne retient rien de plus
            changes.note(Change(MAIL, ("pro",)))
        other = threading.Thread(target=changes.note, args=(Change(CONTACTS),))
        other.start()
        other.join()
        assert said == [Change(CONTACTS)]
    assert said == [Change(CONTACTS), Change(MAIL, ("pro",)), Change(MAIL, ("perso",))]
    with pytest.raises(RuntimeError), changes.held():
        with changes.writing():
            changes.note(Change(MAIL_DRAFTS, ("pro",)))
        raise RuntimeError("le passage s'arrête")
    assert said[-1] == Change(MAIL_DRAFTS, ("pro",))  # validée avant : elle a eu lieu


def test_a_mail_stored_again_as_it_was_says_nothing(tmp_path):
    """Une relève qui repasse, la console qui relit un dossier, une source relue pour une pièce : le même mail rangé
    à l'identique ne fait relire aucun écran ; qu'il change (lu, complété) se dit."""
    cache = MailCache(tmp_path / "mail.db")
    try:
        cache.store(mail("<a@x.fr>", complete=False), 1)
        said = heard(cache)
        cache.store(mail("<a@x.fr>", complete=False), 1)
        cache.store(mail("<a@x.fr>", complete=False), 1, parts=())
        assert said == []
        cache.store(mail("<a@x.fr>", complete=False, seen=True), 1)  # lu ailleurs : il se montre autrement
        cache.store(mail("<a@x.fr>", seen=True), 1)  # relu entier
        cache.store(mail("<a@x.fr>", seen=True), 1)
        assert said == [Change(MAIL, ("pro",))] * 2
        cache.offer("pro", "pro:<a@x.fr>")
        cache.offer("pro", "pro:<a@x.fr>")  # déjà en attente : rien de neuf
        assert len(said) == 3
    finally:
        cache.close()


def test_what_waits_for_her_poll_is_bounded(tmp_path, monkeypatch):
    """Sa relève qui ne passe plus (le courrier coupé, des jours sans réveil) : ce qui l'attend ne grandit pas sans fin
    — le plus ancien cède sa place ; ce qui a été lu ailleurs aussi."""
    import mika.adapters.mail.cache as cache_m

    monkeypatch.setattr(cache_m, "OFFERED_MAX", 3)
    monkeypatch.setattr(cache_m, "SEEN_ELSEWHERE_MAX", 2)
    cache = MailCache(tmp_path / "mail.db")
    try:
        for n in range(5):
            cache.store(mail(f"<m{n}@x.fr>"), n + 1)
            cache.offer("pro", f"pro:<m{n}@x.fr>")
            cache.seen_elsewhere("pro", f"pro:<m{n}@x.fr>")
        assert [m.key for m in cache.offered("pro", 10)] == [f"pro:<m{n}@x.fr>" for n in (2, 3, 4)]
        assert len(cache.take_seen_elsewhere()) == 2
    finally:
        cache.close()


def test_the_mail_cache_says_its_drafts_and_says_nothing_of_a_quiet_poll(tmp_path):
    cache = MailCache(tmp_path / "mail.db")
    try:
        said = heard(cache)
        cache.save_draft(Draft("d1", "pro", "Léa <lea@x.fr>", "Re: Maquettes", "Merci"))
        cache.mark_draft("d1", state="envoye", sent_id="<s@x.fr>")  # une écriture dans une écriture : dit une fois
        assert said == [Change(MAIL_DRAFTS, ("pro",))] * 2
        cache.note("pro", at=NOW, polled=True)  # une relève sans histoire
        assert len(said) == 2
        cache.note("pro", at=NOW, error="le serveur ne répond pas")  # une panne se voit
        cache.note("pro", at=NOW + 1, polled=True)  # et sa fin
        assert said[2:] == [Change(MAIL, ("pro",))] * 2
        with pytest.raises(RuntimeError), cache._use(write=True):
            cache._changed(MAIL, "pro")
            raise RuntimeError("annulée")
        assert len(said) == 4
    finally:
        cache.close()


# ── le cache de Teams ──


def batch(*messages: InboxMessage) -> InboxBatch:
    return InboxBatch("8:orgid:adrien", "Adrien", (InboxConversation(DM, "", "dm"),), messages)


def test_the_teams_cache_says_its_conversations_and_its_outbox(tmp_path):
    store = TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=lambda: NOW)
    try:
        said = heard(store)
        first = InboxMessage("1", DM, "Alice", "8:orgid:a", NOW // 1000, "On se voit à 14 h ?")
        store.store_batch(P, batch(first), NOW)
        assert said == [Change(TEAMS, (P,), (DM,))]
        store.store_batch(P, batch(first), NOW)  # le même lot, redit par l'extension : rien de neuf à montrer
        assert len(said) == 1
        draft = store.save_draft(TeamsDraft(id="", conversation=DM, body="Oui, 14 h me va."))
        shown = store.preview(draft.id)
        assert store.enqueue(draft.id, mode="send", digest=shown.digest, expires_at=NOW + 10**9, now=NOW) == ""
        assert store.settle(draft.id, "sending", now=NOW) == (ACCEPTED, None)  # en cours d'envoi : il se voit
        assert [c.topic for c in said[1:]] == [TEAMS_DRAFTS, OUTBOX, OUTBOX]
        assert all(c.accounts == (P,) and c.keys == (DM,) for c in said[1:])
        store.ack([m.ref for m in store.thread(P, DM, 10)])  # rendu à son tri : rien que l'écran montre
        assert len(said) == 4
    finally:
        store.close()


# ── l'annuaire ──


def test_the_directory_says_its_sources_and_keeps_its_own_bookkeeping_quiet(tmp_path):
    store = ContactsStore(tmp_path / "contacts.db", now=lambda: NOW)
    try:
        said = heard(store)
        store.observe_now([Observation(EMAIL, "lea@x.fr", MAIL_SOURCE, "pro", "Léa Martin", 1, NOW, NOW)])
        assert said == [Change(CONTACTS, places=((MAIL_SOURCE, "pro"),))]
        store.set_cursor("mail", 12)  # où il en est de sa lecture : rien qu'une personne voie
        assert len(said) == 1
    finally:
        store.close()
