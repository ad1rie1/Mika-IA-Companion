"""Le cache du courrier sur SQLAlchemy (ADR 0101) : ce que les colonnes calculées à l'écriture doivent tenir.

- **une valeur venue d'ailleurs trop longue pour sa colonne** (un Message-ID, un nom de dossier, une adresse) est
  gardée sous son début suivi d'une empreinte (``fit``) — jamais refusée, jamais confondue avec une autre — et se
  retrouve par sa valeur entière ;
- **la recherche ignore la casse et les accents** partout (mails, envois, fils, correspondants, brouillons), et
  ``%`` ou ``_`` sont des caractères comme les autres ;
- **oublier** efface ce que le correspondant a écrit, ce qui lui a été écrit (copies dans « Envoyés », envois,
  brouillons, copies et destinataires compris) et ce qui répondait à ses mails, sans rien laisser de lui dans les
  tables, et retient l'empreinte de ses mails : une relecture ne les ramène pas ;
- **chaque requête se compile pour MariaDB**, et rien de propre à SQLite n'y reste.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects.mysql import mariadbconnector
from sqlalchemy.dialects.sqlite import dml as sqlite_dml
from sqlalchemy.sql import ClauseElement

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.mail.cache import MailCache
from mika.adapters.mail.models import (
    FOLDER,
    MID,
    DraftRow,
    FolderRow,
    ForgottenRow,
    MessageRow,
    RecipientRow,
    SentRow,
    content_print,
    fit,
)
from mika.ports.mail import Draft, Mail, MailQuery, Sent
from mika.ports.sql import KeyTooLong


@pytest.fixture
def cache(tmp_path):
    found = MailCache(tmp_path / "mail.db")
    yield found
    found.close()


def mail(mid: str, sender: str, address: str, subject: str, date: int, body: str = "texte", **more) -> Mail:
    return Mail(mid, sender, address, subject, date, body, **{"account": "pro", "folder": "INBOX", **more})


def orphans(cache: MailCache) -> int:
    """Les personnes nommées par une ligne qui n'existe plus."""
    owners = {0: MessageRow, 1: SentRow, 2: DraftRow}
    with cache._use(write=False) as s:
        rows = s.execute(select(RecipientRow.kind, RecipientRow.owner)).all()
        return sum(1 for kind, owner in rows if s.get(owners[kind], owner) is None)


# ── une valeur trop longue ─────────────────────────────────────────────────


def test_fit_keeps_what_fits_and_prints_the_rest():
    assert fit("<court@x>", MID) == "<court@x>" and fit(None, 10) == ""
    long_a, long_b = "<" + "a" * 400 + "1@x>", "<" + "a" * 400 + "2@x>"
    assert len(fit(long_a, MID)) == MID and fit(long_a, MID) == fit(long_a, MID)  # déterministe
    assert fit(long_a, MID) != fit(long_b, MID) and fit(long_a, MID).startswith("<aaa")
    assert len(fit(long_a, 16)) == 16


def test_a_too_long_message_id_is_kept_under_a_print_and_found_again(cache):
    head = "<" + "a" * 400
    first = cache.store(mail(head + "1@x>", "Alice <alice@x.fr>", "alice@x.fr", "Un", 1, "Premier"), 1)
    second = cache.store(mail(head + "2@x>", "Alice <alice@x.fr>", "alice@x.fr", "Deux", 2, "Second"), 2)
    assert first.ref != second.ref and not first.twin and not second.twin  # même début : deux mails
    kept = cache.one(first.ref)
    assert kept.body == "Premier" and len(kept.message_id) == MID and kept.message_id == fit(first.message_id, MID)
    assert cache.one("pro:" + head + "1@x>").body == "Premier"  # désigné par son Message-ID entier
    assert cache.located(second.ref)[1] == 2
    # une réponse qui le cite par son Message-ID entier est dans son fil
    reply = cache.store(mail("<re@x>", "Bob <bob@x.fr>", "bob@x.fr", "Re: Un", 3, in_reply_to=head + "1@x>"), 3)
    box_thread = cache.browse("thread", reply.ref, 1, 25)
    assert sorted(h.subject for h in box_thread.items) == ["Re: Un", "Un"]
    # rendu une fois : par la partie locale de sa référence
    cache.hand("pro", "<" + "b" * 500 + ">")
    assert cache.handed("pro", "<" + "b" * 500 + ">") and not cache.handed("pro", "<" + "b" * 499 + ">")


def test_a_too_long_folder_name_is_kept_under_a_print(cache):
    deep, other = "Projets/" + "x" * 300 + "/A", "Projets/" + "x" * 300 + "/B"
    cache.save_folder("pro", deep, role="archive", uidvalidity=7, uidnext=9)
    cache.save_folder("pro", other)
    cache.store(mail("<p@x>", "Alice <alice@x.fr>", "alice@x.fr", "Rangé", 1, folder=deep), 5)
    cache.recount("pro", deep)
    names = {f.name: f for f in cache.folders("pro")}
    assert set(names) == {fit(deep, FOLDER), fit(other, FOLDER)} and all(len(n) == FOLDER for n in names)
    assert names[fit(deep, FOLDER)].total == 1 and cache.cursor("pro", deep) == (7, 9)
    assert [m.subject for m in cache.recent(5, folder=deep)] == ["Rangé"] and cache.folder_count("pro", other) == 0
    cache.relocate("pro", deep, 5, other, 12)
    assert cache.folder_count("pro", deep) == 0 and cache.uids("pro", other, 5)[0][0] == 12


def test_the_bound_is_real_fit_is_what_keeps_writes_within_it(cache):
    with pytest.raises(KeyTooLong), cache._use(write=True) as s:
        s.add(FolderRow(account="pro", name="x" * (FOLDER + 1), role="", uidvalidity=0, uidnext=0, total=0,
                        unseen=0, last_sync=0))
        s.flush()
    assert cache.folders("pro") == []  # rien n'a été écrit


# ── la recherche ───────────────────────────────────────────────────────────


@pytest.fixture
def box(tmp_path):
    found = ImapSmtpMail(lambda: MailConfig(accounts={"pro": MailAccount(address="me@x.fr")}), tmp_path / "mail.db")
    found._cache.save_folder("pro", "Envoyés", role="sent")
    found._cache.store(mail("<e@x>", "Élodie Dupré <elodie@x.fr>", "elodie@x.fr", "Réunion d'ÉTÉ", 1,
                            "Ça MARCHE pour jeudi", to="me@x.fr"), 1)
    found._cache.store(mail("<z@x>", "Zoé <zoe@x.fr>", "zoe@x.fr", "Autre chose", 2, "Rien à voir", to="me@x.fr"), 2)
    found._cache.remember_sent(Sent("<s@x>", "Élodie <elodie@x.fr>", "Re: Réunion", "D'accord, à JEUDI", 3,
                                    "pro:<e@x>", account="pro"))
    found._cache.save_draft(Draft("b1", "pro", "Zoé <zoe@x.fr>", "Écrire à Zoé", "Bonjour"))
    yield found
    found.close()


@pytest.mark.parametrize("text", ["elodie", "ÉLODIE", "reunion d'ete", "ça marche", "CA MARCHE", "dupre"])
def test_search_ignores_case_and_accents(box, text):
    assert [m.message_id for m in box.search(text, 10)] == ["<e@x>"]


def test_every_search_of_the_console_ignores_case_and_accents(box):
    assert box.messages_page(MailQuery(text="REUNION")).total == 1
    assert box.messages_page(MailQuery(sender="DUPRÉ")).total == 1
    assert box.messages_page(MailQuery(sender="zoe@x")).total == 1
    assert box.outgoing_page(MailQuery(text="jeudi")).total == 1
    assert [h.ref for h in box.search_page("JEUDI")] == ["pro:<s@x>", "pro:<e@x>"] and box.search_count("jeudi") == 2
    assert [c.address for c in box.contacts_page("pro", "ELODIE").items] == ["elodie@x.fr"]
    assert [d.id for d in box.drafts_page("ecrire a zoe").items] == ["b1"]
    for literal in ("%", "_", "\\"):
        assert box.search(literal, 10) == [] and box.search_count(literal) == 0  # pas de joker


# ── l'oubli ─────────────────────────────────────────────────────────────────


def test_forget_erases_what_it_must_and_keeps_the_print(cache):
    cache.save_folder("pro", "Envoyés", role="sent")
    theirs = mail("<t@x>", "Bob <bob@x.fr>", "bob@x.fr", "Salut", 1, "Coucou", to="me@x.fr")
    stored = cache.store(theirs, 1)
    cache.offer("pro", stored.ref)
    cache.store(mail("<o@x>", "Alice <alice@x.fr>", "alice@x.fr", "Autre", 2, to="me@x.fr"), 2)
    cache.store(mail("<a@x>", "Alice <alice@x.fr>", "alice@x.fr", "Pour Bob", 3, to="bob@x.fr"), 3)  # reçu : gardé
    # ses copies d'envoi : « À » seul (rien en copie), en copie, et dans un « Sent » sans rôle
    cache.store(mail("<c1@x>", "Moi <me@x.fr>", "me@x.fr", "Re: Salut", 4, folder="Envoyés", to="Bob <bob@x.fr>"), 4)
    cache.store(mail("<c2@x>", "Moi <me@x.fr>", "me@x.fr", "Info", 5, folder="Envoyés", to="alice@x.fr",
                     cc="BOB@x.fr"), 5)
    cache.store(mail("<c3@x>", "Moi <me@x.fr>", "me@x.fr", "Vieux", 6, folder="Sent", to="bob@x.fr"), 6)
    cache.remember_sent(Sent("<s1@x>", "bob@x.fr", "Re: Salut", "Réponse", 7, account="pro"), b"brut")
    cache.remember_sent(Sent("<s2@x>", "alice@x.fr", "Tr : Salut", "Cite Bob", 8, stored.ref, account="pro"))
    cache.remember_sent(Sent("<s3@x>", "alice@x.fr", "Gardé", "x", 9, account="pro"))
    cache.save_draft(Draft("d1", "pro", "Bob <bob@x.fr>", "Brouillon", "x"))
    cache.save_draft(Draft("d2", "pro", "alice@x.fr", "Re", "x", reply_to=stored.ref))
    cache.save_draft(Draft("d3", "pro", "alice@x.fr", "Gardé", "x"))

    assert cache.forget("  BOB@x.fr ") == 1 + 3 + 2 + 2  # son mail, trois copies, deux envois, deux brouillons
    assert cache.one(stored.ref) is None and cache.offered("pro", 10) == []
    assert sorted(m.message_id for m in cache.recent(10)) == ["<a@x>", "<o@x>"]
    assert [s.message_id for s in cache.sent(10)] == ["<s3@x>"] and cache.sent_source("pro:<s1@x>") is None
    assert [d.id for d in cache.drafts(10)] == ["d3"]
    with cache._use(write=False) as s:
        assert s.scalar(select(func.count()).select_from(RecipientRow).where(RecipientRow.address == "bob@x.fr")) \
            == 1  # seulement le destinataire du mail d'Alice, qu'elle a reçu
        prints = {tuple(r) for r in s.execute(select(ForgottenRow.account, ForgottenRow.fingerprint))}
    assert ("pro", content_print("bob@x.fr", "Salut", 1, "Coucou")) in prints and len(prints) == 4
    assert orphans(cache) == 0
    assert {f.name: f.total for f in cache.folders("pro")}.get("Envoyés") == 0  # recompté
    # une relecture du serveur ne le ramène pas
    again = cache.store(theirs, 11)
    assert again == theirs and cache.folder_count("pro", "INBOX") == 2
    assert cache.forget("bob@x.fr") == 0 and cache.forget("  ") == 0


def test_forget_reaches_an_address_too_long_for_its_column(cache):
    huge = "x" * 400 + "@exemple.fr"
    cache.save_draft(Draft("d1", "pro", huge, "Long", "x"))
    cache.save_draft(Draft("d2", "pro", "x" * 399 + "@exemple.fr", "Voisin", "x"))
    assert cache.forget(huge) == 1 and [d.id for d in cache.drafts(5)] == ["d2"] and orphans(cache) == 0


# ── ranger, élaguer ─────────────────────────────────────────────────────────


def test_two_mails_moved_without_their_uid_keep_their_own_place(cache):
    a = cache.store(mail("<1@x>", "A <a@x.fr>", "a@x.fr", "Un", 1), 1)
    b = cache.store(mail("<2@x>", "B <b@x.fr>", "b@x.fr", "Deux", 2), 2)
    cache.relocate("pro", "INBOX", 1, "Archives", None)
    cache.relocate("pro", "INBOX", 2, "Archives", None)
    assert cache.folder_count("pro", "Archives") == 2 and cache.located(a.ref)[1] < 0 and cache.located(b.ref)[1] < 0
    # le vrai UID arrive : il reprend sa place provisoire, avec sa référence
    moved = cache.store(replace(a, folder="Archives", key=""), 40)
    assert moved.ref == a.ref and cache.located(a.ref)[1] == 40 and cache.folder_count("pro", "Archives") == 2


def test_prune_keeps_the_most_recent_and_what_they_name(cache):
    for i in range(5):
        cache.store(mail(f"<{i}@x>", f"P{i} <p{i}@x.fr>", f"p{i}@x.fr", f"m{i}", i, to=f"q{i}@x.fr"), i + 1)
    cache.prune("pro", "INBOX", 2)
    assert [m.subject for m in cache.recent(10)] == ["m4", "m3"] and orphans(cache) == 0
    cache.prune("pro", "INBOX", 2)
    assert cache.folder_count("pro", "INBOX") == 2


# ── pour MariaDB ────────────────────────────────────────────────────────────


def test_every_statement_compiles_for_mariadb(box):
    cache = box._cache
    statements: list[ClauseElement] = []

    def record(_conn, element, *_args):
        if isinstance(element, ClauseElement):
            statements.append(element)

    event.listen(cache._engine, "before_execute", record)
    stored = cache.store(mail("<n@x>", "Bob <bob@x.fr>", "bob@x.fr", "Neuf", 9, in_reply_to="<e@x>"), 9)
    cache.offer("pro", stored.ref)
    cache.offered("pro", 5)
    cache.ack([stored.ref])
    cache.set_flags("pro", "INBOX", 9, seen=True)
    cache.relocate("pro", "INBOX", 9, "Archives", None)
    for method, args in (("messages", (MailQuery(account="pro", folder="INBOX", text="x", sender="y", seen=False,
                                                  flagged=True, refs=("pro:<e@x>",), exclude=("z",)), 1, 25)),
                         ("outgoing", (MailQuery(account="pro", text="jeudi"), 1, 25)),
                         ("hits", ("jeudi", 25, 0)), ("search_count", ("jeudi",)),
                         ("thread", ("pro:<e@x>", 1, 25)), ("contacts", ("pro", "e", ("me@x.fr",), 1, 25)),
                         ("drafts", ("zoe", 1, 25))):
        cache.browse(method, *args)
    cache.find_ref("pro:<e@x>")
    cache.search("x", 5, account="pro")
    cache.mark_draft("b1", state="envoye", sent_id="<s@x>")
    cache.recent_edits("pro", 5)
    cache.note("pro", at=1, error="panne")
    cache.prune("pro", "INBOX", 1)
    cache.forget("zoe@x.fr")
    cache.keep_folders("pro", ["INBOX"])
    event.remove(cache._engine, "before_execute", record)

    dialect = mariadbconnector.dialect()
    dialect.is_mariadb = True
    checked = 0
    for statement in statements:
        if isinstance(statement, sqlite_dml.Insert):
            continue  # ``insert_ignore`` : sous MariaDB, l'aide écrit un ``INSERT IGNORE``
        sql = str(statement.compile(dialect=dialect)).lower()
        for bad in ("||", "rowid", "json_each", "json_extract", "on conflict", "insert or", "pragma"):
            assert bad not in sql, f"{bad} dans : {sql[:300]}"
        checked += 1
    assert checked > 50
