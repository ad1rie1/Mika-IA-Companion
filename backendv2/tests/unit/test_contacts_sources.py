"""Les lectures que l'annuaire fait de ses sources (ADR 0298) : qui écrit dans Teams (``TeamsStore.people_since``), qui
correspond avec les boîtes (``correspondents_since`` du courrier réel et du courrier simulé).

- **dans l'ordre d'arrivée, par lots** : un curseur rendu reprend où la lecture s'est arrêtée, ``more`` dit qu'il en
  reste ; un curseur au-delà de la dernière ligne (ses dernières effacées) repart d'elle, sans rien sauter ;
- **jamais la personne du compte** : ses messages Teams, l'adresse de sa boîte ;
- **le courrier ne compte pas deux fois un mail** : sa copie dans un second dossier, ni la copie dans « Envoyés » d'un
  envoi déjà gardé ici ; un mail reçu dit son expéditeur (son nom tiré de l'en-tête), un mail parti ses destinataires.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.mail.cache import MailCache
from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.ports.mail import AccountInfo, Mail, Sent
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage
from mika.sim.outside import FakeMail

NOW = 1_790_000_000_000_000
MS = NOW // 1000
GROUP = "19:groupe@thread.v2"


@pytest.fixture
def teams(tmp_path):
    found = TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=lambda: NOW)
    yield found
    found.close()


def push(store: TeamsStore, account: str, *messages: InboxMessage, history: bool = False, now: int = NOW) -> None:
    store.store_batch(account, InboxBatch(self_id="8:orgid:moi", self_name="Moi",
                                          conversations=(InboxConversation(GROUP, "Projet", "group"),),
                                          messages=messages, history=history), now)


# ── Teams ─────────────────────────────────────────────────────────────────


def test_teams_people_are_read_by_account_without_the_account_person(teams):
    push(teams, "adrien",
         InboxMessage("1", GROUP, "G. Rousseau", "8:orgid:GILLES", MS, "bonjour"),
         InboxMessage("2", GROUP, "Moi", "8:orgid:moi", MS + 1000, "salut", own=True),
         InboxMessage("3", GROUP, "Gilles Rousseau", "8:orgid:gilles", MS + 2000, "ça va ?"))
    push(teams, "bea", InboxMessage("4", GROUP, "Gilles Rousseau", "8:orgid:gilles", MS + 3000, "re"), history=True)
    got = teams.people_since((0, 0), 100)
    assert not got.more
    assert [(p.account, p.author_id, p.name, p.count, p.first, p.last) for p in got.people] == [
        ("adrien", "8:orgid:gilles", "Gilles Rousseau", 2, NOW, NOW + 2_000_000),
        ("bea", "8:orgid:gilles", "Gilles Rousseau", 1, NOW + 3_000_000, NOW + 3_000_000)]  # l'historique compte
    assert teams.people_since(got.cursor, 100).people == ()  # rien de neuf


def test_teams_people_are_read_in_batches_from_their_cursor(teams):
    push(teams, "adrien", *(InboxMessage(str(n), GROUP, f"Auteur {n}", f"8:orgid:{n}", MS + n, "x")
                            for n in range(5)))
    first = teams.people_since((0, 0), 2)
    assert first.more and [p.author_id for p in first.people] == ["8:orgid:0", "8:orgid:1"]
    rest = teams.people_since(first.cursor, 10)
    assert not rest.more and [p.author_id for p in rest.people] == ["8:orgid:2", "8:orgid:3", "8:orgid:4"]


def test_a_teams_message_that_takes_the_number_of_a_forgotten_one_is_still_read(teams):
    """Sous SQLite, le numéro du dernier message effacé resert au suivant : le curseur retient aussi son arrivée."""
    push(teams, "adrien", InboxMessage("0", GROUP, "Ana", "8:orgid:ana", MS, "x"), now=NOW)
    push(teams, "adrien", InboxMessage("1", GROUP, "Bob", "8:orgid:bob", MS + 1, "x"), now=NOW + 1)
    cursor = teams.people_since((0, 0), 10).cursor
    assert cursor[1] == NOW + 1
    asyncio.run(teams.forget("teams:8:orgid:bob"))  # son message part : son numéro est libre
    push(teams, "adrien", InboxMessage("2", GROUP, "Chloé", "8:orgid:chloe", MS + 5, "y"), now=NOW + 2)
    got = teams.people_since(cursor, 10)
    assert [p.author_id for p in got.people] == ["8:orgid:chloe"] and got.cursor == (cursor[0], NOW + 2)
    assert teams.people_since(got.cursor, 10).people == ()
    # un curseur au-delà du dernier message (ses derniers effacés, rien depuis) ne relit rien de vieux
    asyncio.run(teams.forget("teams:8:orgid:chloe"))
    assert teams.people_since(got.cursor, 10).people == ()


# ── Le courrier ───────────────────────────────────────────────────────────


def mail(mid: str, sender: str, address: str, date: int, *, folder: str = "INBOX", to: str = "me@x.fr",
         **more) -> Mail:
    return Mail(mid, sender, address, "objet", date, "texte", to=to, account="pro", folder=folder, **more)


@pytest.fixture
def cache(tmp_path):
    found = MailCache(tmp_path / "mail.db")
    found.save_folder("pro", "Envoyés", role="sent")
    yield found
    found.close()


def test_mail_correspondents_are_the_senders_received_and_the_recipients_sent(cache):
    cache.store(mail("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", NOW), 1)
    cache.store(mail("<a@x>", "Gilles Rousseau <gilles@nordis.fr>", "gilles@nordis.fr", NOW, folder="Archives"), 7)
    cache.store(mail("<b@x>", "Moi <me@x.fr>", "me@x.fr", NOW + 1, folder="Envoyés",
                     to="Léa Martin <lea@nordis.fr>", cc="gilles@nordis.fr, me@x.fr"), 2)
    cache.remember_sent(Sent("<c@x>", "Léa <lea@nordis.fr>", "objet", "texte", NOW + 2, account="pro"))
    # la copie dans « Envoyés » d'un envoi déjà gardé ici n'est comptée que par lui
    cache.store(mail("<c@x>", "Moi <me@x.fr>", "me@x.fr", NOW + 2, folder="Envoyés", to="Léa <lea@nordis.fr>"), 3)
    got = cache.correspondents_since((0, 0), 100, {"pro": "Me@x.fr"})
    assert not got.more
    assert [(p.address, p.name, p.received, p.sent, p.first, p.last) for p in got.people] == [
        ("gilles@nordis.fr", "Gilles Rousseau", 1, 1, NOW, NOW + 1),
        ("lea@nordis.fr", "Léa", 0, 2, NOW + 1, NOW + 2)]
    assert {p.account for p in got.people} == {"pro"}
    again = cache.correspondents_since(got.cursor, 100, {"pro": "me@x.fr"})
    assert again.people == () and again.cursor == got.cursor


def test_mail_correspondents_are_read_in_batches_and_a_cursor_beyond_the_end_skips_nothing(cache):
    for n in range(3):
        cache.store(mail(f"<m{n}@x>", f"P{n} <p{n}@gmail.com>", f"p{n}@gmail.com", NOW + n), n + 1)
    first = cache.correspondents_since((0, 0), 2, {})
    assert first.more and [p.address for p in first.people] == ["p0@gmail.com", "p1@gmail.com"]
    rest = cache.correspondents_since(first.cursor, 2, {})
    assert not rest.more and [p.address for p in rest.people] == ["p2@gmail.com"]
    # un curseur au-delà de la dernière ligne (ses dernières effacées) repart d'elle : le mail suivant est lu
    stale = cache.correspondents_since((99, 99), 10, {})
    assert stale.people == () and stale.cursor == rest.cursor
    cache.store(mail("<m9@x>", "Q <q@gmail.com>", "q@gmail.com", NOW + 9), 9)
    assert [p.address for p in cache.correspondents_since(stale.cursor, 10, {}).people] == ["q@gmail.com"]


def test_the_real_mail_port_leaves_out_each_box_own_address(tmp_path):
    box = ImapSmtpMail(lambda: MailConfig(accounts={"pro": MailAccount(address="me@x.fr")}), tmp_path / "mail.db")
    try:
        box._cache.store(mail("<a@x>", "Moi <me@x.fr>", "me@x.fr", NOW), 1)
        box._cache.store(mail("<b@x>", "Bob <bob@gmail.com>", "bob@gmail.com", NOW + 1), 2)
        assert [p.address for p in box.correspondents_since((0, 0), 10).people] == ["bob@gmail.com"]
    finally:
        box._cache.close()


def test_the_simulated_mail_reads_its_correspondents_the_same_way():
    fake = FakeMail(boxes=[AccountInfo(key="pro", label="Pro", address="me@x.fr", ready=True)])
    fake.inbox.append(mail("<a@x>", "Gilles <gilles@nordis.fr>", "gilles@nordis.fr", NOW))
    fake.inbox.append(mail("<b@x>", "Moi <me@x.fr>", "me@x.fr", NOW + 1, folder="Envoyés", to="Léa <lea@x.fr>"))
    got = fake.correspondents_since((0, 0), 10)
    assert [(p.address, p.received, p.sent) for p in got.people] == [("gilles@nordis.fr", 1, 0), ("lea@x.fr", 0, 1)]
    assert got.cursor == (2, 0) and not got.more
    assert fake.correspondents_since(got.cursor, 10).people == ()
