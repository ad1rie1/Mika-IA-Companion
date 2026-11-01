"""Les pièces d'un mail, gardées avec lui (ADR 0172).

- **lire** : ``parse_parts`` rend chaque pièce jointe à son rang (celui du lien de téléchargement) et chaque image
  intégrée que le HTML désigne par ``cid:``, avec ses octets et son Content-ID nu ;
- **garder** : le cache garde les octets d'une pièce une seule fois, quel que soit le nombre de mails qui la portent,
  en morceaux recollés à l'identique ; relire un mail ne réécrit rien ; une écriture sans pièces garde les siennes ;
- **effacer** : les pièces partent avec leur mail (oubli, élagage, mail rangé ailleurs), et leurs octets quand plus
  rien ne les désigne ;
- **borner** : une pièce trop grosse reste sur le serveur ; au-delà de la borne totale, les mails les plus anciens
  cèdent leurs octets ; les images rendues à la lecture sont bornées et d'un type sûr ;
- **relever** : un mail relevé se télécharge, se transfère et montre ses images sans le serveur ; un mail gardé
  avant se relit pour garder les siennes ;
- chaque requête se compile pour MariaDB.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects.mysql import mariadbconnector
from sqlalchemy.dialects.sqlite import dml as sqlite_dml
from sqlalchemy.sql import ClauseElement

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.mail import cache as cache_module
from mika.adapters.mail.cache import MailCache
from mika.adapters.mail.models import BlobRow, PartRow
from mika.adapters.mail.parse import attachment_files, parse, parse_parts
from tests.fixtures.mail_servers import Imap, Smtp, serve

PNG = b"\x89PNG\r\n\x1a\n" + b"logo" * 50
PDF = b"%PDF-1.7\x00\xff devis"
NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def rich(mid: str = "<logo@exemple.fr>", *, sender: str = "Alice <alice@exemple.fr>", pdf: bytes = PDF,
         date: str = "Mon, 28 Sep 2026 10:00:00 +0200") -> bytes:
    """Un mail HTML avec son logo intégré (``cid:``), une pièce jointe, et une image intégrée à la façon d'Outlook
    (un nom de fichier et un Content-ID : une pièce jointe que le HTML désigne aussi)."""
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"], m["Date"] = sender, "mika@exemple.fr", "Signature", mid, date
    m.set_content("Bonjour")
    m.add_alternative('<p>Bonjour</p><img src="cid:Logo.1@Exemple.fr" alt="Logo"><img src="cid:image001.png@01DA" '
                      'alt="Bandeau">', subtype="html")
    html = m.get_payload()[1]
    html.add_related(PNG, "image", "png", cid="<Logo.1@Exemple.fr>")
    html.add_related(b"GIF89a-bandeau", "image", "gif", cid="<image001.png@01DA>", filename="image001.gif",
                     disposition="inline")
    m.add_attachment(pdf, maintype="application", subtype="pdf", filename="devis été.pdf")
    return bytes(m)


def kept(cache: MailCache) -> tuple[int, int]:
    """Les pièces, et les morceaux d'octets, que le cache tient."""
    with cache._use(write=False) as s:
        return (int(s.scalar(select(func.count()).select_from(PartRow))),
                int(s.scalar(select(func.count()).select_from(BlobRow))))


def store(cache: MailCache, raw: bytes, uid: int, **more):
    mail, parts = parse_parts(raw, str(uid), account="pro", folder=more.pop("folder", "INBOX"), complete=True)
    return cache.store(replace(mail, **more), uid, parts)


@pytest.fixture
def cache(tmp_path):
    found = MailCache(tmp_path / "mail.db")
    yield found
    found.close()


# ── lire ────────────────────────────────────────────────────────────────────


def test_reading_gives_each_attachment_at_its_rank_and_each_inline_image():
    raw = rich()
    mail, parts = parse_parts(raw, account="pro", complete=True)
    assert mail == parse(raw, account="pro", complete=True)
    assert [a.name for a in mail.attachments] == ["image001.gif", "devis été.pdf"]
    attached = [p for p in parts if p.position >= 0]
    assert [(p.position, p.name, p.mime, p.data) for p in attached] == [
        (0, "image001.gif", "image/gif", b"GIF89a-bandeau"), (1, "devis été.pdf", "application/pdf", PDF)]
    assert [f.data for f in attachment_files(raw)] == [p.data for p in attached]  # le même rang que le téléchargement
    assert attached[0].content_id == "image001.png@01da"  # nu, en minuscules
    inline = [p for p in parts if p.position < 0]
    assert [(p.mime, p.content_id, p.data) for p in inline] == [("image/png", "logo.1@exemple.fr", PNG)]


# ── garder ──────────────────────────────────────────────────────────────────


def test_the_cache_keeps_each_part_once_and_serves_it_back(cache):
    first = store(cache, rich(), 1)
    store(cache, rich(), 7, folder="Archives")  # le même mail dans un autre dossier
    store(cache, rich("<autre@exemple.fr>", sender="Bob <bob@exemple.fr>"), 2)  # même logo, même devis
    assert first.parts_kept and cache.one(first.ref).parts_kept
    assert kept(cache) == (9, 3)  # trois pièces par mail ; trois contenus
    found = cache.part(first.ref, 1)
    assert (found.name, found.mime, found.data) == ("devis été.pdf", "application/pdf", PDF)
    assert cache.part(first.ref, 2) is None
    assert [f.name for f in cache.files(first.ref, 2)] == ["image001.gif", "devis été.pdf"]
    assert cache.files(first.ref, 3) is None  # il en manque une : on ne transfère pas un mail amputé
    assert sorted(cache.inline(first.ref)) == [("image001.png@01da", "image/gif", b"GIF89a-bandeau"),
                                               ("logo.1@exemple.fr", "image/png", PNG)]


def test_bytes_are_cut_into_chunks_and_glued_back(cache, monkeypatch):
    monkeypatch.setattr(cache_module, "CHUNK", 7)
    first = store(cache, rich(), 1)
    assert cache.part(first.ref, 1).data == PDF and kept(cache)[1] > 3
    with cache._use(write=False) as s:
        assert max(len(d) for d in s.scalars(select(BlobRow.data))) <= 7


def test_rereading_rewrites_no_bytes_and_a_store_without_parts_keeps_them(cache):
    first = store(cache, rich(), 1)
    written: list[str] = []
    event.listen(cache._engine, "before_execute", lambda _c, element, *_a: written.append(str(element).lower()))
    store(cache, rich(), 1)  # relu à l'identique
    assert not [w for w in written if w.startswith(("insert into blobs", "delete from blobs"))]
    assert kept(cache) == (3, 3)
    cache.store(replace(cache.one(first.ref), seen=True), 1)  # les drapeaux, sans les pièces
    assert kept(cache) == (3, 3) and cache.part(first.ref, 1).data == PDF and cache.one(first.ref).seen


# ── effacer ─────────────────────────────────────────────────────────────────


def test_parts_leave_with_their_mail_and_their_bytes_with_the_last_of_them(cache):
    alice = store(cache, rich(), 1)
    bob = store(cache, rich("<b@exemple.fr>", sender="Bob <bob@exemple.fr>", pdf=b"%PDF autre"), 2)
    cache.forget("bob@exemple.fr")
    assert cache.part(bob.ref, 1) is None and kept(cache) == (3, 3)  # le logo partagé reste : Alice le porte
    assert cache.part(alice.ref, 1).data == PDF
    cache.forget_uids("pro", "INBOX", [1])  # rangé ailleurs par un autre client
    assert kept(cache) == (0, 0)
    store(cache, rich(), 1)
    cache.reset_folder("pro", "INBOX")
    assert kept(cache) == (0, 0)


# ── borner ──────────────────────────────────────────────────────────────────


def test_a_too_big_part_stays_on_the_server(cache, monkeypatch):
    monkeypatch.setattr(cache_module, "PART_MAX", len(PDF) - 1)
    first = store(cache, rich(), 1)
    assert cache.part(first.ref, 1) is None and cache.part(first.ref, 0) is not None
    assert cache.files(first.ref, 2) is None


def test_beyond_the_bound_the_oldest_mails_give_up_their_bytes(cache, monkeypatch):
    ancient = b"%PDF ancien" + b"x" * 500
    monkeypatch.setattr(cache_module, "KEPT_MAX", len(PNG) + len(b"GIF89a-bandeau") + len(ancient) + 5)
    old = store(cache, rich("<vieux@exemple.fr>", pdf=ancient, date="Mon, 21 Sep 2026 10:00:00 +0200"), 1)
    assert cache.part(old.ref, 1).data == ancient  # sous la borne : gardé
    new = store(cache, rich("<neuf@exemple.fr>", pdf=b"%PDF recent"), 2)
    assert cache.part(new.ref, 1).data == b"%PDF recent"
    assert cache.part(old.ref, 1) is None  # cédé : il se relira sur le serveur
    assert cache.part(new.ref, 0) is not None and cache.inline(new.ref)  # partagées avec le plus récent : gardées
    assert cache.one(old.ref).parts_kept  # ses pièces sont connues, pas leurs octets


def test_inline_images_are_bounded_and_of_a_safe_type(cache):
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = "alice@exemple.fr", "Images", "<img@exemple.fr>"
    m.set_content('<img src="cid:svg@x"><img src="cid:a@x"><img src="cid:b@x">', subtype="html")
    m.add_related(b"<svg onload='x()'/>", "image", "svg+xml", cid="<svg@x>")
    m.add_related(b"a" * 300, "image", "png", cid="<a@x>")
    m.add_related(b"b" * 300, "image", "jpeg", cid="<b@x>")
    first = store(cache, bytes(m), 1)
    assert [c for c, _, _ in cache.inline(first.ref)] == ["a@x", "b@x"]  # pas de SVG
    assert [c for c, _, _ in cache.inline(first.ref, limit=500)] == ["a@x"]


# ── pour MariaDB ────────────────────────────────────────────────────────────


def test_every_parts_statement_compiles_for_mariadb(cache, monkeypatch):
    statements: list[ClauseElement] = []
    event.listen(cache._engine, "before_execute",
                 lambda _c, element, *_a: statements.append(element) if isinstance(element, ClauseElement) else None)
    monkeypatch.setattr(cache_module, "KEPT_MAX", 10)
    first = store(cache, rich(), 1)
    cache.part(first.ref, 1)
    cache.files(first.ref, 2)
    cache.inline(first.ref)
    cache.forget("alice@exemple.fr")
    dialect = mariadbconnector.dialect()
    dialect.is_mariadb = True
    # ``insert_ignore`` (l'oubli retient une empreinte) : sous MariaDB, l'aide écrit un ``INSERT IGNORE``
    sql = [str(s.compile(dialect=dialect)).lower() for s in statements if not isinstance(s, sqlite_dml.Insert)]
    assert any("parts" in q for q in sql) and any("blobs" in q for q in sql)
    for q in sql:
        for bad in ("||", "rowid", "json_each", "json_extract", "on conflict", "insert or", "pragma"):
            assert bad not in q, f"{bad} dans : {q[:300]}"


# ── relever ─────────────────────────────────────────────────────────────────


@pytest.fixture
def servers():
    Imap.reset({3: rich()})
    Smtp.received = []
    imap, smtp = serve(Imap), serve(Smtp)
    yield imap.server_address[1], smtp.server_address[1]
    imap.shutdown()
    smtp.shutdown()


def box_for(tmp_path, imap_port: int, smtp_port: int) -> ImapSmtpMail:
    account = MailAccount(address="mika@exemple.fr", imap_host="127.0.0.1", imap_port=imap_port, imap_ssl=False,
                          user="mika", password="secret", smtp_host="127.0.0.1", smtp_port=smtp_port,
                          smtp_security="none", since_days=7)
    return ImapSmtpMail(lambda: MailConfig(accounts={"pro": account}), tmp_path / "mail.db", now=lambda: NOW, tz=UTC)


def test_a_polled_mail_serves_its_parts_without_the_server(tmp_path, servers):
    box = box_for(tmp_path, *servers)
    m = asyncio.run(box.fetch_new(10))[0]
    del Imap.boxes["INBOX"].mails[3]  # plus sur le serveur
    assert asyncio.run(box.file(m.ref, "1")).data == PDF
    assert {c for c, _, _ in box.inline_images(m.ref)} == {"logo.1@exemple.fr", "image001.png@01da"}
    asyncio.run(box.forward(m.ref, "dest@exemple.fr", "Tr : Signature", "Pour toi."))
    assert [f.data for f in attachment_files(Smtp.received[-1][2])] == [b"GIF89a-bandeau", PDF]
    with pytest.raises(FileNotFoundError):  # le message entier, lui, reste au serveur
        asyncio.run(box.file(m.ref, "source"))
    box._cache.close()


def test_a_mail_kept_before_its_parts_rereads_them(tmp_path, servers):
    box = box_for(tmp_path, *servers)
    m = asyncio.run(box.fetch_new(10))[0]
    box._cache.reset_folder("pro", "INBOX")
    box._cache.store(replace(parse(Imap.boxes["INBOX"].mails[3][1], account="pro", folder="INBOX", complete=True),
                             parts_kept=False), 3)  # le cache d'avant : le mail, sans ses pièces
    assert not box.cached_one(m.ref).parts_kept and box.inline_images(m.ref) == ()
    again = asyncio.run(box.reread(m.ref))
    assert again.parts_kept and box.cached_one(m.ref).parts_kept and len(box.inline_images(m.ref)) == 2
    assert not Imap.boxes["INBOX"].mails[3][0]  # relire ne marque pas lu
    box._cache.close()
