"""Des historiques dépassant les anciennes limites, avec le véritable cache SQLite."""

from dataclasses import replace

import pytest

from mika.adapters.feeds import HttpFeeds
from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.mail.parse import parse
from mika.ports.mail import Draft, Mail, MailQuery, Sent, reference_key
from tests.fixtures.mail_servers import raw_mail


@pytest.fixture
def archive(tmp_path):
    box = ImapSmtpMail(lambda: MailConfig(accounts={"pro": MailAccount(address="me@example.test")}), tmp_path / "mail.db")
    cache = box._cache
    cache.save_folder("pro", "Envoyés", role="sent")
    for i in range(555):
        parent = "" if not i else "<m0@example.test>"
        m = Mail(f"<m{i}@example.test>", f"Contact {i} <c{i}@example.test>", f"c{i}@example.test",
                 f"Été {i}", i, "Corps complet " * 100 + f"FIN-{i}", account="pro", folder="INBOX",
                 to="me@example.test", in_reply_to=parent, seen=i % 2 == 0, flagged=i % 3 == 0)
        cache.store(m, i + 1)
        cache.remember_sent(Sent(f"<s{i}@example.test>", f"c{i}@example.test", f"Envoi {i}", "Réponse " * 100,
                                 i, f"pro:{m.message_id}", account="pro"))
        cache.save_draft(Draft(f"d{i}", "pro", f"c{i}@example.test", f"Brouillon {i}", "À relire", updated=i))
    cache.store(replace(m, account="perso", subject="Autre compte"), 1)
    cache.store(replace(m, folder="Archives"), 1)
    cache.store(replace(m, message_id="<s554@example.test>", folder="Envoyés", subject="Copie IMAP"), 2)
    yield box
    cache.close()


def test_mail_pages_filter_count_and_load_only_the_requested_rows(archive, monkeypatch):
    cache = archive._cache
    original = cache.at_row
    reads = []
    def record(rowid, **kwargs):
        reads.append(rowid)
        return original(rowid, **kwargs)
    monkeypatch.setattr(cache, "at_row", record)
    page = archive.messages_page(MailQuery(account="pro", folder="INBOX"), 22, 25)
    assert page.total == 555 and page.number == 22 and len(page.items) == len(reads) == 25
    assert all(len(m.body) <= 400 and not m.html for m in page.items)
    assert archive.cached_one(page.items[0].ref).body.endswith("FIN-29")
    filtered = archive.messages_page(MailQuery(account="pro", folder="INBOX", text="ete", seen=False, flagged=True))
    assert filtered.total == 92 and all(not m.seen and m.flagged for m in filtered.items)
    assert archive.messages_page(MailQuery(text="FIN-0")).total == 1
    assert archive.messages_page(MailQuery(refs=())).total == 0
    assert archive.messages_page(MailQuery(refs=("pro:<m0@example.test>",))).total == 1
    last = archive.messages_page(MailQuery(account="pro", folder="INBOX"), 10**100, 25)
    assert last.number == 23 and len(last.items) == 5 and last.items[-1].message_id == "<m0@example.test>"
    assert archive.messages_page(MailQuery(text="absent"), 4).number == 1


def test_all_outgoing_contacts_threads_and_drafts_remain_accessible(archive):
    outgoing = archive.outgoing_page(MailQuery(account="pro"), 23)
    assert outgoing.total == 555 and len(outgoing.items) == 5
    assert all(local and len(m.body) <= 400 for m, local in outgoing.items)
    assert archive.outgoing_page(MailQuery(account="perso")).total == 0
    contacts = archive.contacts_page("pro", page=23)
    assert contacts.total == 555 and len(contacts.items) == 5
    assert all(c.received == c.sent == 1 for c in contacts.items)
    assert archive.contacts_page("pro", "c0@").items[0].address == "c0@example.test"
    thread = archive.thread_page("pro:<m0@example.test>", 45)
    assert thread.total == 1110 and len(thread.items) == 10
    assert all(m.account == "pro" for m in thread.items)
    assert archive.thread_page("perso:<m554@example.test>").total == 1
    drafts = archive.drafts_page(page=23)
    assert drafts.total == 555 and len(drafts.items) == 5 and drafts.items[-1].id == "d0"


def test_search_is_unbounded_deduplicated_and_accent_insensitive(archive):
    assert archive.search_count("été") == 555
    assert len(archive.search_page("ete", 25, 525)) == 25
    assert archive.search_page("ete", 25, 555) == []
    assert archive.search_count("") == 1111  # copies de dossier et d'envoi dédoublonnées
    assert archive.search_count("%") == 0  # caractères littéraux, pas de joker SQL
    assert archive.search_count("FIN-0") == 1
    assert archive.sent_mail("perso:<s0@example.test>") is None


def test_long_message_ids_resolve_without_loading_the_archive(archive, monkeypatch):
    m = Mail("<long/" + "a" * 240 + "@example.test>", "Alice", "a@example.test", "Ancien", -1, "texte", account="pro")
    archive._cache.store(m, 1000)
    def forbidden(*args, **kwargs):
        raise AssertionError("une résolution de clé ne doit pas charger les corps")
    monkeypatch.setattr(archive._cache, "_mail", forbidden)
    assert archive.find_ref(reference_key(m.ref)) == m.ref
    assert archive.find_ref("#absent") is None


def test_a_sent_message_copied_to_inbox_keeps_its_outgoing_role(archive):
    m = Mail('<self-copy@example.test>', 'Me <me@example.test>', 'me@example.test', 'Copie reçue de mon envoi', 9999,
             'Message', account='pro', folder='INBOX', to='dest@example.test')
    archive._cache.store(m, 2000)
    archive._cache.store(replace(m, folder='Envoyés'), 2000)
    outgoing = archive.outgoing_page(MailQuery(account='pro'))
    assert outgoing.total == 556 and outgoing.items[0][0].ref == m.ref
    [contact] = archive.contacts_page('pro', 'dest@').items
    assert contact.received == 0 and contact.sent == 1


def test_rss_pages_filter_in_sql_and_keep_counts_consistent(tmp_path):
    feeds = HttpFeeds(lambda: [], tmp_path / "feeds.db")
    try:
        feeds._db.executemany("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?)", [
            (str(i), "https://example.test/rss", "Création", f"Été {i}", "https://example.test/article", f"Résumé {i}", i, 1, i)
            for i in range(555)])
        feeds._db.commit()
        page = feeds.entries_page("creation", "ete", 23)
        assert page.total == 555 and [e.id for e in page.items] == ["4", "3", "2", "1", "0"]
        assert feeds.entry_count("crea", ("0", "1", "inconnu")) == 553
        assert feeds.feed_counts() == {"Création": 555}
        assert feeds.entries_page(text="Résumé 554").items[0].id == "554"
        assert feeds.entries_page(text="inconnu", page=100).number == 1
    finally:
        feeds.close()


def test_synchronizing_keeps_more_than_two_thousand_messages(tmp_path):
    acc = MailAccount(address='me@example.test')
    box = ImapSmtpMail(lambda: MailConfig(accounts={'pro': acc}), tmp_path / 'mail.db')
    cache = box._cache
    class Session:
        def select(self, folder):
            return 2002, 1, 2003
        def search(self, query):
            return [2002]
        def fetch(self, uids):
            return [(u, frozenset(), raw_mail(u, f'Message {u}', 'Corps')) for u in uids]
        def flags(self, uids):
            return {u: frozenset() for u in uids}
    try:
        for uid in range(1, 2002):
            cache.store(parse(raw_mail(uid, f'Message {uid}', 'Corps'), str(uid), account='pro', folder='INBOX', complete=True), uid)
        cache.save_folder('pro', 'INBOX', uidvalidity=1, uidnext=2002)
        box._sync_sync(Session(), 'pro', acc, 'INBOX', 25, hand=False)
        assert cache.folder_count('pro', 'INBOX') == 2002
        assert box.cached_one('pro:<mail-1@exemple.fr>') is not None
        assert box.messages_page(MailQuery(account='pro', folder='INBOX'), 81).total == 2002
    finally:
        cache.close()
