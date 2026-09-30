"""Le courrier réel, contre de faux serveurs IMAP et SMTP qui parlent le vrai
protocole.

- relever : chaque mail rendu une fois, en texte brut ; UID par dossier ;
  plusieurs comptes sans collision ; **un relevé ne marque rien comme lu** ;
  un mail lu ailleurs est su ; un UIDVALIDITY qui change fait tout relire sans
  rien rendre deux fois ;
- ranger : les dossiers et leurs rôles (special-use, noms en UTF-7 modifié),
  lu/non lu et suivi sur le serveur, archiver, corbeille, supprimer depuis la
  corbeille, déplacer sans MOVE (COPY + EXPUNGE) ;
- envoyer : l'expéditeur suit la voix du compte, la signature et la citation
  sont ajoutées, le fil est chaîné, une copie est rangée dans « Envoyés » et le
  mail d'origine est marqué répondu ; un brouillon ne part que tel qu'il a été
  lu, et jamais avec un « [À COMPLÉTER » ;
- l'ancien cache et l'ancienne configuration (un seul compte) sont repris.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig, compose, from_stored, utf7
from mika.adapters.mail.cache import MailCache
from mika.ports.mail import AccountInfo, Draft, Mail, reply_recipients, split_ref
from tests.fixtures.mail_servers import Imap, Smtp, raw_mail, serve

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def go(coro):
    return asyncio.run(coro)


@pytest.fixture
def servers():
    Imap.reset({3: raw_mail(3, "Coucou", "Tu viens samedi ?"), 7: raw_mail(7, "Lettre", "", bulk=True)})
    Smtp.received = []
    imap, smtp = serve(Imap), serve(Smtp)
    yield imap.server_address[1], smtp.server_address[1]
    imap.shutdown()
    smtp.shutdown()


def account(imap_port: int, smtp_port: int, **more) -> MailAccount:
    base = dict(address="mika@exemple.fr", imap_host="127.0.0.1", imap_port=imap_port, imap_ssl=False, user="mika",
                password="secret", smtp_host="127.0.0.1", smtp_port=smtp_port, smtp_security="none", since_days=7)
    return MailAccount(**{**base, **more})


def box_for(tmp_path, *accounts: tuple[str, MailAccount]) -> ImapSmtpMail:
    return ImapSmtpMail(lambda: MailConfig(accounts=dict(accounts)), tmp_path / "mail.db", now=lambda: NOW, tz=UTC)


def test_imap_hands_each_mail_once_as_plain_text_and_never_marks_it_read(tmp_path, servers):
    box = box_for(tmp_path, ("perso", account(*servers)))
    first = go(box.fetch_new(10))
    assert [m.ref for m in first] == ["perso:<mail-3@exemple.fr>", "perso:<mail-7@exemple.fr>"]
    coucou, lettre = first
    assert coucou.address == "alice@exemple.fr" and coucou.subject == "Coucou" and "samedi" in coucou.body
    assert coucou.account == "perso" and coucou.folder == "INBOX" and not coucou.seen
    assert not coucou.bulk and lettre.bulk and coucou.date > 0
    assert go(box.fetch_new(10)) == []  # déjà rendus
    Imap.boxes["INBOX"].add(raw_mail(9, "En HTML", "", html=True))
    [html] = go(box.fetch_new(10))
    assert "Bonjour Mika" in html.body and "alert" not in html.body and "<" not in html.body and html.has_html
    assert go(box.get(coucou.ref)) == coucou and len(go(box.recent(10))) == 3
    assert box.cached_one("<mail-3@exemple.fr>") == coucou  # une ancienne référence, sans compte
    assert Imap.logins[0] == ("mika", "secret")
    assert all(not flags for flags, _ in Imap.boxes["INBOX"].mails.values())  # rien n'est marqué lu
    assert not any(c.upper().startswith(("UID STORE", "SELECT")) for c in Imap.commands)  # EXAMINE seulement


def test_two_accounts_on_the_same_uids_never_collide(tmp_path, servers):
    box = box_for(tmp_path, ("perso", account(*servers)), ("pro", account(*servers, user="pro")))
    got = go(box.fetch_new(10))
    assert sorted(m.ref for m in got) == sorted(["perso:<mail-3@exemple.fr>", "perso:<mail-7@exemple.fr>",
                                                 "pro:<mail-3@exemple.fr>", "pro:<mail-7@exemple.fr>"])
    assert len(box.cached(10)) == 4 and len(box.cached(10, account="pro")) == 2
    assert [a.key for a in box.accounts()] == ["perso", "pro"] and box.configured()


def test_a_mail_read_elsewhere_is_known_and_a_new_uidvalidity_hands_nothing_twice(tmp_path, servers):
    box = box_for(tmp_path, ("perso", account(*servers)))
    go(box.fetch_new(10))
    Imap.boxes["INBOX"].mails[3][0].add("\\Seen")  # lu dans un autre client
    assert go(box.fetch_new(10)) == [] and box.seen_elsewhere() == ["perso:<mail-3@exemple.fr>"]
    assert box.seen_elsewhere() == []  # vidé à la lecture
    assert box.cached_one("perso:<mail-3@exemple.fr>").seen
    inbox = Imap.boxes["INBOX"]
    inbox.validity = 99  # le serveur a renuméroté
    inbox.mails = {1: [set(), inbox.mails[3][1]], 2: [set(), inbox.mails[7][1]]}
    inbox.next_uid = 3
    assert go(box.fetch_new(10)) == []  # relus, pas rendus deux fois
    assert len(box.cached(10)) == 2


def test_folders_their_roles_and_what_the_console_does_on_the_server(tmp_path, servers):
    box = box_for(tmp_path, ("perso", account(*servers)))
    go(box.fetch_new(10))
    folders = {f.name: f for f in box.folders("perso")}
    assert {n: f.role for n, f in folders.items()} == {"INBOX": "inbox", "Envoyés": "sent", "Archives": "archive",
                                                     "Corbeille": "trash", "Indésirables": "junk"}
    assert folders["INBOX"].polled and not folders["Archives"].polled and folders["INBOX"].unseen == 2
    ref = "perso:<mail-3@exemple.fr>"
    go(box.set_flags(ref, seen=True, flagged=True))
    assert Imap.boxes["INBOX"].mails[3][0] == {"\\Seen", "\\Flagged"}
    assert box.cached_one(ref).seen and box.cached_one(ref).flagged
    assert box.seen_elsewhere() == []  # c'est elle (la console) qui l'a lu, pas « ailleurs »
    assert go(box.archive(ref)) == "Archives"
    assert 3 not in Imap.boxes["INBOX"].mails and len(Imap.boxes["Archives"].mails) == 1
    assert box.cached_one(ref).folder == "Archives"
    assert go(box.trash(ref)) == "Corbeille" and box.cached_one(ref).folder == "Corbeille"
    go(box.delete(ref))
    assert Imap.boxes["Corbeille"].mails == {} and box.cached_one(ref) is None
    with pytest.raises(ValueError, match="corbeille"):
        go(box.delete("perso:<mail-7@exemple.fr>"))
    assert go(box.sync_folder("perso", "Archives", 10)) == 0  # rien de neuf là-bas
    assert go(box.fetch_new(10)) == []  # ranger ne rend rien à nouveau


def test_moving_without_the_move_extension_copies_then_expunges(tmp_path, servers):
    Imap.caps = "IMAP4rev1"
    box = box_for(tmp_path, ("perso", account(*servers)))
    go(box.fetch_new(10))
    assert go(box.move("perso:<mail-7@exemple.fr>", "Indésirables")) == "Indésirables"
    assert 7 not in Imap.boxes["INBOX"].mails and len(Imap.boxes["Indésirables"].mails) == 1
    assert any(c.upper().startswith("UID COPY") for c in Imap.commands)
    assert any(c.upper().startswith("EXPUNGE") for c in Imap.commands)


def test_folder_names_travel_in_modified_utf7():
    assert utf7.encode("Envoyés") == "Envoy&AOk-s" and utf7.decode("Envoy&AOk-s") == "Envoyés"
    assert utf7.encode("R&D") == "R&-D" and utf7.decode("R&-D") == "R&D"
    for name in ("Éléments supprimés", "日本語", "a/b & c"):
        assert utf7.decode(utf7.encode(name)) == name


def test_sending_follows_the_voice_signature_and_thread(tmp_path, servers):
    acc = account(*servers, voice="proprietaire", display_name="Adrien Dupont", signature="Adrien\n06 00 00 00 00")
    box = box_for(tmp_path, ("perso", acc))
    go(box.fetch_new(10))
    parent = "perso:<mail-3@exemple.fr>"
    message_id = go(box.send("alice@exemple.fr", "Re: Coucou", "Oui, je viens !", in_reply_to=parent, quote=True,
                             by="user_1"))
    [(sender, rcpts, data, auth)] = Smtp.received
    text = data.decode()
    assert "mika@exemple.fr" in sender and rcpts == ["<alice@exemple.fr>"] and auth == "\0mika\0secret"
    assert "From: Adrien Dupont <mika@exemple.fr>" in text  # à sa place : son nom à lui
    assert "Oui, je viens !" in text and "-- \r\nAdrien" in text and "> Tu viens samedi ?" in text
    assert "In-Reply-To: <mail-3@exemple.fr>" in text and message_id in text
    sent_copy = list(Imap.boxes["Envoyés"].mails.values())
    assert len(sent_copy) == 1 and "\\Seen" in sent_copy[0][0] and b"Oui, je viens" in sent_copy[0][1]
    assert "\\Answered" in Imap.boxes["INBOX"].mails[3][0]
    [gone] = box.sent_mails(5)
    assert gone.by == "user_1" and gone.account == "perso" and gone.in_reply_to == parent
    assert "Oui, je viens !" in gone.body and box.sent_mail(message_id) == gone


def test_smtp_sends_as_written_even_for_a_mail_not_in_the_cache(tmp_path, servers):
    box = box_for(tmp_path, ("perso", account(*servers, save_sent=False)))
    message_id = go(box.send("bob@exemple.fr", "Samedi", "Oui, je viens !", in_reply_to="<mail-3@exemple.fr>"))
    [(sender, rcpts, data, auth)] = Smtp.received
    assert "mika@exemple.fr" in sender and rcpts == ["<bob@exemple.fr>"] and "\0mika\0secret" == auth
    assert b"Oui, je viens !" in data and b"In-Reply-To: <mail-3@exemple.fr>" in data
    assert b"From: Mika <mika@exemple.fr>" in data  # en son nom
    assert message_id.encode() in data and Imap.boxes["Envoyés"].mails == {}


def test_a_draft_leaves_only_as_it_was_read(tmp_path, servers):
    box = box_for(tmp_path, ("perso", account(*servers, voice="assistante", display_name="Adrien")))
    go(box.fetch_new(10))
    draft = box.save_draft(Draft(id="", account="perso", to="alice@exemple.fr", subject="Re: Coucou",
                                 body="Adrien viendra samedi. [À COMPLÉTER : l'heure]",
                                 reply_to="perso:<mail-3@exemple.fr>"))
    assert draft.id and draft.state == "brouillon"
    shown = box.preview(draft.id)
    assert shown.sender == "\"Mika (pour Adrien)\" <mika@exemple.fr>" and "compléter" in shown.blocked
    with pytest.raises(ValueError, match="compléter"):
        go(box.send_draft(draft.id))
    read = box.save_draft(replace(draft, body="Adrien viendra samedi vers 15 h."))
    seen = box.preview(read.id)
    assert not seen.blocked and "> Tu viens samedi ?" in seen.text
    box.save_draft(replace(read, body="Adrien viendra samedi vers 16 h."))  # modifié après lecture
    with pytest.raises(ValueError, match="changé"):
        go(box.send_draft(read.id, digest=seen.digest))
    now = box.preview(read.id)
    message_id = go(box.send_draft(read.id, by="user_1", digest=now.digest))
    assert box.draft(read.id).state == "envoye" and box.draft(read.id).sent_id == message_id
    assert b"16 h" in Smtp.received[-1][2]
    with pytest.raises(ValueError, match="déjà parti"):
        go(box.send_draft(read.id))
    assert box.sent_mail(message_id).draft == read.id


def test_voices_recipients_and_what_blocks_a_draft():
    base = AccountInfo("perso", "", "mika@exemple.fr", display_name="Adrien", can_send=True)
    assert compose.sender(base) == "Mika <mika@exemple.fr>"
    assert compose.sender(_voice(base, "assistante")) == "\"Mika (pour Adrien)\" <mika@exemple.fr>"
    assert compose.sender(_voice(base, "proprietaire")) == "Adrien <mika@exemple.fr>"
    parent = Mail("<p@x>", "Alice <alice@x.fr>", "alice@x.fr", "Salut", 0, "Ça va ?", to="mika@exemple.fr, bob@x.fr",
                  cc="Carla <carla@x.fr>", reply_to="Alice Pro <alice@pro.fr>")
    assert reply_recipients(parent, ("mika@exemple.fr",)) == ("Alice Pro <alice@pro.fr>", "")
    to, cc = reply_recipients(parent, ("mika@exemple.fr",), everyone=True)
    assert to == "Alice Pro <alice@pro.fr>" and cc == "bob@x.fr, Carla <carla@x.fr>"
    nobody = Draft("d", "perso", "pas-une-adresse", "x", "y")
    assert "destinataire" in compose.blocked(nobody, base)
    assert "envoyer" in compose.blocked(Draft("d", "perso", "a@b.fr", "x", "y"), _voice(base, "elle", send=False))
    assert split_ref("perso:<a@b>") == ("perso", "<a@b>") and split_ref("<a@b>") == ("", "<a@b>")


def _voice(info: AccountInfo, voice: str, *, send: bool = True) -> AccountInfo:
    return replace(info, voice=voice, can_send=send)


def test_the_old_cache_and_the_old_single_account_config_are_taken_over(tmp_path):
    path = tmp_path / "mail.db"
    db = sqlite3.connect(str(path))
    db.executescript(
        "CREATE TABLE mails(message_id TEXT PRIMARY KEY, uid TEXT, sender TEXT, address TEXT, subject TEXT,"
        " date INTEGER, body TEXT, dest TEXT, in_reply_to TEXT, bulk INTEGER, seen_at TEXT);"
        "CREATE TABLE uids(uid TEXT PRIMARY KEY);"
        "CREATE TABLE envoyes(message_id TEXT PRIMARY KEY, dest TEXT, subject TEXT, body TEXT, date INTEGER,"
        " in_reply_to TEXT, by TEXT);"
        "INSERT INTO mails VALUES('<old@x>', '12', 'Alice <a@x.fr>', 'a@x.fr', 'Avant', 5, 'Texte', 'mika@x',"
        " '', 0, '');"
        "INSERT INTO uids VALUES('12');"
        "INSERT INTO envoyes VALUES('<gone@x>', 'bob@x.fr', 'Parti', 'Corps', 6, '', 'user_1');")
    db.commit()
    db.close()
    cache = MailCache(path)
    [old] = cache.recent(10)
    assert (old.account, old.folder, old.subject) == ("principal", "INBOX", "Avant")
    assert cache.handed("principal", "<old@x>") and cache.cursor("principal", "INBOX") == (0, 13)
    assert cache.sent(5)[0].account == "principal" and cache.one("<old@x>") == old
    cache.close()
    cfg = MailConfig.model_validate(from_stored({"address": "mika@x.fr", "imap_host": "h", "user": "u",
                                                 "password": "p", "folder": "Boîte"}))
    assert list(cfg.accounts) == ["principal"] and cfg.accounts["principal"].folders == ("Boîte",)
    assert MailConfig.model_validate(from_stored({})).accounts == {}
    with pytest.raises(ValueError, match="nom de compte invalide"):
        MailConfig(accounts={"Mon compte": MailAccount()})


def test_an_unconfigured_box_reads_nothing(tmp_path):
    box = ImapSmtpMail(lambda: MailConfig(), tmp_path / "mail.db")
    assert not box.configured() and go(box.fetch_new(10)) == [] and box.accounts() == []


def test_a_failing_account_is_noted_and_does_not_stop_the_others(tmp_path, servers):
    broken = account(1, servers[1])  # personne n'écoute là
    box = box_for(tmp_path, ("casse", broken), ("perso", account(*servers)))
    got = go(box.fetch_new(10))
    assert {m.account for m in got} == {"perso"}
    assert box.status("casse").error and not box.status("perso").error and box.status("perso").last_poll
    ok, said = go(box.test("casse"))
    assert not ok and "lecture : échec" in said.lower()
    ok, said = go(box.test("perso"))
    assert ok and "5 dossier(s)" in said and "envoi : ok" in said.lower()
