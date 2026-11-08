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
from sqlalchemy import event, func, select, update
from sqlalchemy.dialects.mysql import mariadbconnector
from sqlalchemy.dialects.sqlite import dml as sqlite_dml
from sqlalchemy.sql import ClauseElement

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig, compose
from mika.adapters.mail import cache as cache_module
from mika.adapters.mail import client as client_module
from mika.adapters.mail.cache import MailCache
from mika.adapters.mail.imap import Session
from mika.adapters.mail.models import BlobRow, PartRow
from mika.adapters.mail.parse import attachment_files, parse, parse_parts
from mika.ports.mail import PIECES_MAX, Attachment, File, Sent
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


def account_for(imap_port: int, smtp_port: int) -> MailAccount:
    return MailAccount(address="mika@exemple.fr", imap_host="127.0.0.1", imap_port=imap_port, imap_ssl=False,
                       user="mika", password="secret", smtp_host="127.0.0.1", smtp_port=smtp_port,
                       smtp_security="none", since_days=7)


def box_for(tmp_path, imap_port: int, smtp_port: int) -> ImapSmtpMail:
    account = account_for(imap_port, smtp_port)
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


# ── envoyer des pièces (ADR 0214) ───────────────────────────────────────


def sent(message_id: str, date: int, *files: File) -> tuple[Sent, tuple[File, ...]]:
    return (Sent(message_id, "dest@exemple.fr", "Objet", "Texte", date, account="pro",
                 attachments=tuple(Attachment(f.name, f.mime, len(f.data)) for f in files)), files)


def test_a_mail_sent_with_pieces_keeps_them_apart_and_hides_its_blind_copy(tmp_path, servers):
    box = box_for(tmp_path, *servers)
    mid = asyncio.run(box.send("dest@exemple.fr", "Le devis", "Le voici.", by="user_1", account="pro",
                               bcc="cachee@exemple.fr", files=(File("devis été.pdf", "application/pdf", PDF),)))
    _, rcpts, data, _ = Smtp.received[-1]
    assert any("cachee@exemple.fr" in r for r in rcpts) and b"cachee@exemple.fr" not in data  # dans l'enveloppe seulement
    assert [f.data for f in attachment_files(data)] == [PDF]
    ref = f"pro:{mid}"
    source = box._cache.sent_source(ref)
    assert b"Le voici" in source and b"cachee" not in source  # gardé ici sans ses octets ni sa copie cachée
    assert PDF not in source
    assert [(a.name, a.size) for a in box.sent_mail(ref).attachments] == [("devis été.pdf", len(PDF))]
    assert asyncio.run(box.file(ref, "0")).data == PDF  # relu d'ici, en morceaux (ADR 0172)
    assert kept(box._cache) == (1, 1)
    whole = asyncio.run(box.file(ref, "source")).data  # le message entier : ses pièces remises, toujours pas sa copie cachée
    assert [f.data for f in attachment_files(whole)] == [PDF] and b"cachee" not in whole
    asyncio.run(box.forward(ref, "autre@exemple.fr", "Tr : Le devis", "Pour toi."))
    assert [f.data for f in attachment_files(Smtp.received[-1][2])] == [PDF]
    box._cache.close()


def test_a_forward_adds_its_pieces_to_those_of_the_original(tmp_path, servers):
    box = box_for(tmp_path, *servers)
    m = asyncio.run(box.fetch_new(10))[0]
    asyncio.run(box.forward(m.ref, "dest@exemple.fr", "Tr : Signature", "Pour toi.",
                            files=(File("en-plus.txt", "text/plain", b"mot"),)))
    assert [f.data for f in attachment_files(Smtp.received[-1][2])] == [b"GIF89a-bandeau", PDF, b"mot"]
    box._cache.close()


def test_a_forward_never_silently_loses_a_piece_given_up(tmp_path, servers):
    box = box_for(tmp_path, *servers)
    mid = asyncio.run(box.send("dest@exemple.fr", "Le devis", "Le voici.", account="pro",
                               files=(File("devis.pdf", "application/pdf", PDF),)))
    with box._cache._use(write=True) as s:
        s.execute(update(PartRow).values(digest=""))  # ses octets cédés aux plus récents
    ref = f"pro:{mid}"
    with pytest.raises(ValueError, match="plus gardée"):
        asyncio.run(box.forward(ref, "autre@exemple.fr", "Tr", "Pour toi."))
    with pytest.raises(FileNotFoundError):
        asyncio.run(box.file(ref, "0"))
    asyncio.run(box.forward(ref, "autre@exemple.fr", "Tr", "Pour toi.", attachments=False))  # sans elles : il part
    box._cache.close()


def test_files_added_to_a_forward_count_with_the_pieces_it_carries(tmp_path, servers, monkeypatch):
    box = box_for(tmp_path, *servers)
    m = asyncio.run(box.fetch_new(10))[0]  # il porte deux pièces
    nine = tuple(File(f"p{i}.txt", "text/plain", b"x") for i in range(PIECES_MAX - 1))
    with pytest.raises(ValueError, match="plus de 10"):
        asyncio.run(box.forward(m.ref, "dest@exemple.fr", "Tr", "Pour toi.", files=nine))
    monkeypatch.setattr(client_module, "PIECES_TOTAL_MAX", len(PDF))
    with pytest.raises(ValueError, match="pèserait plus"):
        asyncio.run(box.forward(m.ref, "dest@exemple.fr", "Tr", "Pour toi.", files=(File("a.txt", "text/plain", b"x"),)))
    assert Smtp.received == []  # rien n'est parti
    asyncio.run(box.forward(m.ref, "dest@exemple.fr", "Tr", "Pour toi."))  # sans ajout : comme avant
    assert len(attachment_files(Smtp.received[-1][2])) == 2
    asyncio.run(box.forward(m.ref, "dest@exemple.fr", "Tr", "Pour toi.", attachments=False, files=nine))  # sans les siennes
    assert len(attachment_files(Smtp.received[-1][2])) == PIECES_MAX - 1
    box._cache.close()


# ── un mail lourd sur un débit lent (ADR 0214) ──

#: au-delà de ce que les tampons de la boucle locale avalent sans que le serveur lise
HEAVY = 12_000_000


def test_the_delay_follows_the_weight_of_the_mail():
    assert compose.transfer_timeout(2_000, 30.0) == 30.0  # un mail court : le délai d'une commande
    on_the_wire = 70_800_000  # 2 × 25 Mio, encodés
    assert compose.transfer_timeout(on_the_wire, 30.0) >= on_the_wire * 8 / 1_000_000  # il part à 1 Mbit/s
    m = EmailMessage()
    m.set_content("Bonjour")
    m.add_attachment(b"x" * 1_000_000, maintype="application", subtype="octet-stream", filename="a.bin")
    assert compose.wire_size(m) == pytest.approx(len(m.as_bytes()), rel=0.05)


def test_a_slow_smtp_server_gets_the_time_a_heavy_mail_needs(servers, monkeypatch):
    monkeypatch.setattr(client_module, "SMTP_TIMEOUT", 0.4)
    monkeypatch.setattr(Smtp, "stall", 1.0)  # plus longtemps que le délai d'une commande
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "mika@exemple.fr", "dest@exemple.fr", "Lourd"
    m.set_content("Le voici.")
    m.add_attachment(b"x" * HEAVY, maintype="application", subtype="octet-stream", filename="lourd.bin")
    ImapSmtpMail._smtp_sync(account_for(*servers), m)
    assert len(Smtp.received[-1][2]) > HEAVY


def test_a_slow_imap_server_gets_the_copy_and_the_session_its_delay_back(servers, monkeypatch):
    monkeypatch.setattr(Imap, "stall", 1.0)
    with Session(account_for(*servers), timeout=0.4) as s:
        s.append("Envoyés", b"x" * HEAVY)
        assert s.box.sock.gettimeout() == 0.4  # la suite de la session garde le délai d'une commande
    assert [len(raw) for _, raw in Imap.boxes["Envoyés"].mails.values()] == [HEAVY]


def test_pieces_of_a_sent_mail_leave_with_it_and_share_their_bytes(cache):
    one, two = sent("<s1@x>", 1, File("a.pdf", "application/pdf", PDF)), sent("<s2@x>", 2, File("b.pdf", "application/pdf", PDF))
    cache.remember_sent(one[0], b"", one[1])
    cache.remember_sent(two[0], b"", two[1])
    assert kept(cache) == (2, 1)  # une fois par contenu
    assert cache.part("pro:<s1@x>", 0).name == "a.pdf" and cache.part("pro:<s2@x>", 0).name == "b.pdf"
    cache.remember_sent(one[0], b"", one[1])  # le même envoi, redit : rien de plus
    assert kept(cache) == (2, 1)
    assert cache.forget("dest@exemple.fr") == 2
    assert kept(cache) == (0, 0) and cache.part("pro:<s1@x>", 0) is None


def test_beyond_the_bound_a_sent_mail_gives_up_its_bytes_like_a_received_one(cache, monkeypatch):
    monkeypatch.setattr(cache_module, "KEPT_MAX", 700)
    old = sent("<vieux@x>", 1, File("a.bin", "application/octet-stream", b"a" * 500))
    new = sent("<neuf@x>", 2, File("b.bin", "application/octet-stream", b"b" * 500))
    cache.remember_sent(old[0], b"", old[1])
    assert cache.part("pro:<vieux@x>", 0) is not None
    cache.remember_sent(new[0], b"", new[1])
    assert cache.part("pro:<vieux@x>", 0) is None and cache.part("pro:<neuf@x>", 0).data == b"b" * 500
    assert [a.name for a in cache.sent_one("pro:<vieux@x>").attachments] == ["a.bin"]  # toujours listée
