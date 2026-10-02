"""Les garde-fous du courrier réel, contre de faux serveurs IMAP et SMTP.

- **un mail de 5 Mo ne fige rien** : son HTML se lit en une passe (mesuré), et
  un mail que la lecture ne comprend pas ne revient pas à chaque relevé (le
  curseur avance mail après mail) ;
- **un mail se désigne par une référence que l'expéditeur ne choisit pas** :
  un second mail qui reprend le Message-ID d'un autre ne prend jamais sa
  place ; les deux sont signalés, et elle remarque les deux ;
- « Actualiser le dossier » ne lui cache plus les nouveaux mails ;
- « Tout marquer comme lu » : par lot, une session et pas une par mail ;
- « Répondre » à « "Dupré, Élodie" <…> » écrit à une seule personne ;
- un « [À COMPLÉTER » ne part sous aucune graphie ;
- IMAP sans SSL tente STARTTLS avant d'envoyer le mot de passe.
"""

from __future__ import annotations

import asyncio
import time
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig, compose
from mika.adapters.mail import client as mail_client
from mika.adapters.mail.cache import MailCache
from mika.adapters.mail.parse import parse
from mika.ports.mail import AccountInfo, Draft, Mail, Sent, addresses, reply_recipients
from tests.fixtures.mail_servers import Imap, Smtp, raw_mail, serve

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def go(coro):
    return asyncio.run(coro)


@pytest.fixture
def servers():
    Imap.reset({3: raw_mail(3, "Coucou", "Tu viens samedi ?")})
    Smtp.received = []
    imap, smtp = serve(Imap), serve(Smtp)
    yield imap.server_address[1], smtp.server_address[1]
    imap.shutdown()
    smtp.shutdown()


def account(imap_port: int, smtp_port: int, **more) -> MailAccount:
    base = dict(address="mika@exemple.fr", imap_host="127.0.0.1", imap_port=imap_port, imap_ssl=False, user="mika",
                password="secret", smtp_host="127.0.0.1", smtp_port=smtp_port, smtp_security="none", since_days=7)
    return MailAccount(**{**base, **more})


def box_for(tmp_path, acc: MailAccount) -> ImapSmtpMail:
    return ImapSmtpMail(lambda: MailConfig(accounts={"perso": acc}), tmp_path / "mail.db", now=lambda: NOW, tz=UTC)


def html_mail(html: str, *, message_id: str = "<lourd@exemple.fr>") -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "Alice <alice@exemple.fr>", "mika@exemple.fr", "Lourd", message_id
    m.set_content(html, subtype="html")
    return bytes(m)


# ── Un mail hostile ne fige rien ──────────────────────────────────────────


def test_a_five_megabyte_hostile_html_mail_is_read_in_well_under_a_second():
    # des balises <script> jamais fermées : le nettoyage par expressions régulières y mettait des heures
    raw = html_mail("<p>Bonjour</p>" + "<script>" * 650_000)
    assert len(raw) > 5_000_000
    started = time.perf_counter()
    mail = parse(raw, "1", account="perso", folder="INBOX", complete=True)
    took = time.perf_counter() - started
    assert took < 2.0, f"{took:.1f} s"
    assert mail.body.startswith("Bonjour") and "<script" not in mail.body


def test_an_unreadable_mail_does_not_come_back_at_every_poll(tmp_path, servers, monkeypatch):
    Imap.boxes["INBOX"].add(raw_mail(4, "Piégé", "x"), uid=4)
    Imap.boxes["INBOX"].add(raw_mail(5, "Normal", "Rien de spécial."), uid=5)
    real = mail_client.parse

    def poisoned(raw, uid="", **kw):
        if b"Pi=C3=A9g=C3=A9" in raw or "Piégé".encode() in raw:
            raise RecursionError("un mail construit pour casser la lecture")
        return real(raw, uid, **kw)

    monkeypatch.setattr(mail_client, "parse", poisoned)
    box = box_for(tmp_path, account(*servers))
    first = go(box.fetch_new(10))
    assert [m.subject for m in first] == ["Coucou", "(un mail illisible)", "Normal"]  # rangé, dit, et le reste passe
    fetched = sum(1 for c in Imap.commands if "FETCH" in c and "BODY.PEEK" in c)
    assert go(box.fetch_new(10)) == []
    assert sum(1 for c in Imap.commands if "FETCH" in c and "BODY.PEEK" in c) == fetched  # rien n'est relu


# ── Une référence que l'expéditeur ne choisit pas (CON-3) ─────────────────


def raw_with_id(uid: int, subject: str, body: str, date: str, sender: str) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, "mika@exemple.fr", subject, date
    m["Message-ID"] = "<CAF-facture-42@banque.example>"
    m.set_content(body)
    return bytes(m)


def test_a_mail_reusing_another_ones_message_id_never_takes_its_place(tmp_path, servers):
    legit = raw_with_id(3, "Votre facture", "IBAN officiel FR76 1111", "Mon, 28 Sep 2026 10:00:00 +0200",
                        "Banque <noreply@banque.example>")
    spoof = raw_with_id(4, "Votre facture (corrigée)", "Nouvel IBAN FR76 9999, payez ici",
                        "Fri, 01 Jan 2100 10:00:00 +0100", "Banque <support@banque-secu.example>")
    Imap.reset({3: legit})
    box = box_for(tmp_path, account(*servers))
    [first] = go(box.fetch_new(10))
    Imap.boxes["INBOX"].add(spoof, uid=4)
    [second] = go(box.fetch_new(10))  # le faux est remarqué (il n'est pas avalé par le vrai)…
    assert first.ref == "perso:<CAF-facture-42@banque.example>"  # la forme historique : les journaux restent valables
    assert second.ref != first.ref and second.twin
    # … mais la référence du vrai désigne toujours le vrai, malgré une date dans le futur
    shown = go(box.get(first.ref))
    assert "FR76 1111" in shown.body and shown.twin  # et le vrai est signalé : un autre porte son identifiant
    assert "FR76 9999" in go(box.get(second.ref)).body
    assert box._cache.located(first.ref)[1] == 3  # ranger, répondre, supprimer agissent sur le bon
    assert box.cached_one("<CAF-facture-42@banque.example>").body.endswith("1111")  # une ancienne référence aussi


def test_the_same_mail_in_two_folders_keeps_one_reference_and_a_copy_of_her_sent_mail_is_not_a_twin(tmp_path):
    cache = MailCache(tmp_path / "mail.db")
    cache.save_folder("perso", "Envoyés", role="sent")
    m = parse(raw_mail(3, "Coucou", "Tu viens ?"), "3", account="perso", folder="INBOX", complete=True)
    a = cache.store(m, 3)
    b = cache.store(replace(m, folder="Archives"), 9)  # une copie (IMAP COPY) : le même mail
    assert a.ref == b.ref == "perso:<mail-3@exemple.fr>" and not a.twin and not b.twin
    # un envoi d'elle, rangé dans « Envoyés » : le même mail, pas un imitateur…
    cache.remember_sent(Sent("<s1@exemple.fr>", "bob@x.fr", "Salut", "Coucou Bob", 1, account="perso"))
    own = Mail("<s1@exemple.fr>", "Mika <mika@exemple.fr>", "mika@exemple.fr", "Salut", 1, "Coucou Bob",
               account="perso", folder="Envoyés")
    assert cache.store(own, 1).ref == "perso:<s1@exemple.fr>"
    # … mais le même identifiant, arrivé dans la boîte de réception avec un autre texte : un imitateur
    fake = replace(own, folder="INBOX", sender="Mika <mika@exemple.fr.evil>", body="Paie ici")
    stored = cache.store(fake, 77)
    assert stored.ref != "perso:<s1@exemple.fr>" and stored.twin
    cache.close()


# ── « Actualiser le dossier » ne cache rien (CON-10) ──────────────────────


def test_refreshing_a_polled_folder_from_the_console_does_not_hide_new_mail_from_her(tmp_path, servers):
    box = box_for(tmp_path, account(*servers))
    assert [m.subject for m in go(box.fetch_new(10))] == ["Coucou"]
    Imap.boxes["INBOX"].add(raw_mail(9, "URGENT : rappelle-moi", "Appelle avant 18h ?"))
    assert go(box.sync_folder("perso", "INBOX", 50)) == 1  # l'opérateur le voit tout de suite…
    assert [m.subject for m in go(box.fetch_new(10))] == ["URGENT : rappelle-moi"]  # … et elle le remarque


# ── « Tout marquer comme lu » : par lot (CON-20) ──────────────────────────


def test_marking_twenty_mails_read_opens_one_session_not_twenty(tmp_path, servers):
    Imap.reset({i: raw_mail(i, f"m{i}", "x") for i in range(1, 21)})
    box = box_for(tmp_path, account(*servers))
    mails = go(box.fetch_new(20))
    before = len(Imap.logins)
    assert go(box.mark_seen([m.ref for m in mails] + ["perso:<inconnu@x>"])) == 1  # l'inconnu se compte
    assert len(Imap.logins) - before == 1
    assert all("\\Seen" in flags for flags, _ in Imap.boxes["INBOX"].mails.values())
    assert all(m.seen for m in box.cached(30))


# ── Répondre à « "Dupré, Élodie" » (CON-20) ───────────────────────────────


def test_replying_to_a_name_with_a_comma_writes_to_one_person(tmp_path, servers):
    raw = (b"From: =?utf-8?q?Dupr=C3=A9=2C_=C3=89lodie?= <elodie@exemple.fr>\r\nTo: mika@exemple.fr\r\n"
           b"Subject: test\r\nMessage-ID: <a@b>\r\n\r\nbonjour\r\n")
    m = parse(raw, "1", account="perso", folder="INBOX", complete=True)
    to, _ = reply_recipients(m, ("mika@exemple.fr",))
    assert to == '"Dupré, Élodie" <elodie@exemple.fr>'  # lisible, et relisible tel quel
    assert addresses(to) == [("Dupré, Élodie", "elodie@exemple.fr")]
    box = box_for(tmp_path, account(*servers))
    go(box.send(to, "Re: test", "Merci !"))
    [(_, rcpt, _, _)] = Smtp.received
    assert [r.strip("<>") for r in rcpt] == ["elodie@exemple.fr"]  # pas « Dupré » en destinataire de plus


# ── « [À COMPLÉTER » sous toutes ses graphies (CON-9, EDG-27) ─────────────


ACC = AccountInfo(key="pro", label="Pro", address="moi@ex.fr", display_name="Adrien", voice="proprietaire",
                  ready=True, can_send=True)


@pytest.mark.parametrize("body", [
    "Rendez-vous le [À COMPLÉTER : date].", "Rendez-vous le [à compléter : date].",
    "Rendez-vous le [A COMPLETER : date].", "Rendez-vous le [ À COMPLÉTER : date ].",
    unicodedata.normalize("NFD", "Rendez-vous le [À COMPLÉTER : date]."), "Rendez-vous le [À  COMPLÉTER]",
    "Rendez-vous le [COMPLÉTER : date].", "Rendez-vous le [à remplir : date].", "Rendez-vous le ［à compléter］",
])
def test_a_placeholder_never_leaves_whatever_its_spelling(body):
    assert compose.blocked(Draft("b1", "pro", "x@y.fr", "Re: rdv", body), ACC)
    assert compose.blocked(Draft("b1", "pro", "x@y.fr", f"Re: {body}", "Oui."), ACC)  # l'objet aussi


def test_a_placeholder_hidden_in_the_quote_or_signature_is_caught_but_a_real_mail_leaves():
    parent = Mail("<p@x>", "Bob <bob@x.fr>", "bob@x.fr", "rdv", 0, "Je viendrai le [à compléter]")
    draft = Draft("b1", "pro", "bob@x.fr", "Re: rdv", "Avec plaisir, à jeudi.", reply_to="perso:<p@x>")
    assert compose.preview(draft, ACC, parent).blocked  # la citation partirait avec
    assert not compose.preview(Draft("b1", "pro", "bob@x.fr", "Re: rdv", "Avec plaisir, à jeudi.", quote=False),
                               ACC, parent).blocked  # sans citation : il part
    assert not compose.blocked(Draft("b1", "pro", "bob@x.fr", "Re: rdv", "Le devis est [à confirmer] par Bob."),
                               ACC)  # un crochet ordinaire n'est pas un trou


# ── STARTTLS (EDG-30) ──────────────────────────────────────────────────────


def test_imap_without_ssl_upgrades_with_starttls_before_sending_the_password(monkeypatch):
    from mika.adapters.mail import imap as imap_mod

    calls = []

    class Fake:
        def __init__(self, host, port, timeout=None):
            self.capabilities = ("IMAP4REV1", "STARTTLS", "LOGINDISABLED")

        def starttls(self, ssl_context=None):
            calls.append("starttls")
            self.capabilities = ("IMAP4REV1",)
            return "OK", [b"go"]

        def login(self, user, password):
            calls.append("login")
            return "OK", [b"ok"]

        def logout(self):
            return "BYE", []

    monkeypatch.setattr(imap_mod.imaplib, "IMAP4", Fake)
    with imap_mod.Session(MailAccount(imap_host="h", imap_ssl=False, user="u", password="p")):
        pass
    assert calls == ["starttls", "login"]
