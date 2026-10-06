"""Chaque lecteur sur un échantillon synthétique de son format (aucune donnée réelle)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from twin.readers import ReadContext, all_readers, pick
from twin.readers.mail import READER as MAIL
from twin.readers.mail import strip_quotes
from twin.readers.meta import READER as META
from twin.readers.meta import fix_mojibake
from twin.readers.msn import READER as MSN
from twin.readers.msn import clean_nick
from twin.readers.notes import READER as NOTES
from twin.readers.sms import READER as SMS
from twin.readers.whatsapp import READER as WHATSAPP
from twin.records import ME, Author, Conversation, Document, Message
from twin.timing import Origin, Precision, from_us

TZ = ZoneInfo("Europe/Paris")


def ctx(root: Path) -> ReadContext:
    return ReadContext(tz=TZ, root=root)


def parts(items):  # type: ignore[no-untyped-def]
    a = [i for i in items if isinstance(i, Author)]
    c = [i for i in items if isinstance(i, Conversation)]
    m = [i for i in items if isinstance(i, Message)]
    d = [i for i in items if isinstance(i, Document)]
    return a, c, m, d


def local(us: int | None) -> datetime:
    assert us is not None
    return from_us(us, TZ)


# -- WhatsApp -----------------------------------------------------------------------------------

ANDROID_FR = """12/03/2019 à 14:05 - Les messages et les appels sont chiffrés de bout en bout.
12/03/2019 à 14:05 - Julie: Salut ! tu viens ce soir ?
12/03/2019 à 14:07 - Léa Martin: Oui !! trop hâte
et j'amène le gâteau
13/03/2019 à 09:12 - Julie: <Médias omis>
13/03/2019 à 09:13 - Léa Martin: Ce message a été supprimé
"""

IOS_EN = """‎[3/12/19, 2:05:33 PM] Julie: hey
[3/12/19, 2:06:01 PM] Léa: hi there: what's up
‎[3/13/19, 9:00:00 AM] Julie: ‎<attached: 00000012-PHOTO-2019-03-13.jpg>
"""


def test_whatsapp_android_fr(tmp_path: Path) -> None:
    f = tmp_path / "Discussion WhatsApp avec Julie.txt"
    f.write_text(ANDROID_FR, encoding="utf-8")
    assert pick(f, all_readers())[0] is WHATSAPP
    a, c, m, _ = parts(list(WHATSAPP.read(f, ctx(tmp_path))))
    assert c[0].key == "Julie" and not c[0].group
    me = {x.key: x.me for x in a}
    assert me == {"Julie": False, "Léa Martin": True}  # le fichier nomme l'autre
    assert m[0].kind == "systeme" and m[0].author == ""
    assert m[2].text == "Oui !! trop hâte\net j'amène le gâteau"  # suite sur plusieurs lignes
    assert m[2].temps.precision == Precision.EXACT and local(m[2].temps.point).hour == 14
    assert m[3].attachments and m[3].text == ""
    assert m[4].kind == "supprime"


def test_whatsapp_ios_anglais_mois_d_abord(tmp_path: Path) -> None:
    f = tmp_path / "WhatsApp Chat - Julie" / "_chat.txt"
    f.parent.mkdir()
    f.write_text(IOS_EN, encoding="utf-8")
    a, c, m, _ = parts(list(WHATSAPP.read(f, ctx(tmp_path))))
    assert c[0].key == "Julie"
    first = local(m[0].temps.point)
    assert (first.month, first.day, first.hour) == (3, 12, 14)  # 13 en 2e position ⇒ mois d'abord ; PM
    assert m[1].text == "hi there: what's up"  # deux-points dans le texte
    assert m[2].attachments[0].name.startswith("00000012-PHOTO")


def test_whatsapp_groupe_ne_devine_pas_qui_est_elle(tmp_path: Path) -> None:
    f = tmp_path / "Discussion WhatsApp avec Les copines.txt"
    f.write_text("01/02/2020 10:00 - Julie a créé le groupe « Les copines »\n"
                 "01/02/2020 10:01 - Julie: coucou\n01/02/2020 10:02 - Léa: yo\n01/02/2020 10:03 - Zoé: hey\n",
                 encoding="utf-8")
    a, c, _, _ = parts(list(WHATSAPP.read(f, ctx(tmp_path))))
    assert c[0].group
    assert all(x.me is None for x in a)


# -- Meta ------------------------------------------------------------------------------------------

def test_meta_messenger_repare_les_accents_et_trie_par_le_temps(tmp_path: Path) -> None:
    thread = tmp_path / "messages" / "inbox" / "julie_abc123"
    thread.mkdir(parents=True)
    data = {
        "participants": [{"name": "Julie"}, {"name": "LÃ©a"}],
        "messages": [  # Meta range du plus récent au plus ancien
            {"sender_name": "LÃ©a", "timestamp_ms": 1552399000000, "content": "DÃ©jÃ  lÃ "},
            {"sender_name": "Julie", "timestamp_ms": 1552395933000, "content": "t'es oÃ¹ ?",
             "photos": [{"uri": "messages/inbox/julie/photos/1.jpg"}]},
        ],
        "title": "Julie", "thread_path": "inbox/julie_abc123",
    }
    f = thread / "message_1.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    assert pick(f, all_readers())[0] is META
    a, c, m, _ = parts(list(META.read(f, ctx(tmp_path))))
    assert c[0].key == "inbox/julie_abc123" and c[0].title == "Julie"
    assert {x.key: x.me for x in a} == {"Julie": False, "Léa": True}
    assert [x.text for x in m] == ["t'es où ?", "Déjà là"]
    assert m[0].attachments[0].name == "1.jpg"
    assert m[0].temps.point == 1552395933000 * 1000


def test_meta_titulaire_lue_dans_le_profil(tmp_path: Path) -> None:
    prof = tmp_path / "personal_information" / "profile_information"
    prof.mkdir(parents=True)
    (prof / "profile_information.json").write_text(json.dumps({"profile_v2": {"name": {"full_name": "Léa"}}}))
    thread = tmp_path / "your_instagram_activity" / "messages" / "inbox" / "groupe_1"
    thread.mkdir(parents=True)
    f = thread / "message_1.json"
    f.write_text(json.dumps({"participants": [{"name": "Léa"}, {"name": "A"}, {"name": "B"}],
                             "messages": [{"sender_name": "A", "timestamp_ms": 1, "content": "x"}],
                             "title": "Groupe", "thread_path": "inbox/groupe_1"}))
    a, c, _, _ = parts(list(META.read(f, ctx(tmp_path))))
    assert c[0].channel == "instagram" and c[0].group
    assert {x.key: x.me for x in a} == {"Léa": True, "A": False, "B": False}


def test_mojibake_ne_touche_pas_un_texte_juste() -> None:
    assert fix_mojibake("été 😀") == "été 😀"
    assert fix_mojibake("Ã©tÃ©") == "été"


# -- MSN ---------------------------------------------------------------------------------------------

MSN_XML = """<?xml version="1.0"?>
<?xml-stylesheet type='text/xsl' href='MessageLog.xsl'?>
<Log FirstSessionID="1" LastSessionID="2">
<Message Date="12/03/2009" Time="14:05:33" DateTime="2009-03-12T13:05:33.383Z" SessionID="1"><From><User FriendlyName="·$4Julie [b]☆[/b]"/></From><To><User FriendlyName="Léa ~ zik"/></To><Text Style="x">salut</Text></Message>
<Message Date="12/03/2009" Time="14:06:00" DateTime="2009-03-12T13:06:00.000Z" SessionID="1"><From><User FriendlyName="Léa ~ zik"/></From><To><User FriendlyName="·$4Julie [b]☆[/b]"/></To><Text>coucou toi</Text></Message>
<Message Date="13/03/2009" Time="20:00:00" SessionID="2"><From><User FriendlyName="Léa (en cours)"/></From><To><User FriendlyName="·$4Julie [b]☆[/b]"/></To><Text>re</Text></Message>
</Log>
"""


def test_msn_xml_deux_cotes_et_pseudos(tmp_path: Path) -> None:
    f = tmp_path / "History" / "julie1234567890.xml"
    f.parent.mkdir()
    f.write_text(MSN_XML, encoding="utf-8")
    assert pick(f, all_readers())[0] is MSN
    a, c, m, _ = parts(list(MSN.read(f, ctx(tmp_path))))
    assert not c[0].group
    sides = {x.key: set(x.aliases) for x in a}
    assert len(sides) == 2
    assert {"Léa ~ zik", "Léa (en cours)"} in sides.values()  # deux pseudos, un seul côté
    assert m[0].temps.origin == Origin.SOURCE and local(m[0].temps.point).hour == 14  # UTC → Paris
    third = local(m[2].temps.point)  # sans DateTime : Date + Time locaux
    assert (third.day, third.hour) == (13, 20)
    assert m[1].author == m[2].author


def test_msn_xml_abime_est_repris_message_par_message(tmp_path: Path) -> None:
    f = tmp_path / "x.xml"
    broken = MSN_XML.replace("<Text>re</Text>", "<Text>re \x01</Text>").replace("</Log>", "")
    f.write_text(broken, encoding="utf-8")
    c = ctx(tmp_path)
    _, _, m, _ = parts(list(MSN.read(f, c)))
    assert len(m) == 3


def test_messenger_plus_texte(tmp_path: Path) -> None:
    f = tmp_path / "julie@hotmail.com.txt"
    f.write_text(""".--------------------------------------------------------------------.
| Début de session : jeudi 12 mars 2009                              |
| Participants :                                                     |
|    Julie (julie@hotmail.com)                                       |
.--------------------------------------------------------------------.
[23:59:00] Léa : on se capte demain ?
[00:01:10] Julie : ouii
""", encoding="utf-8")
    assert pick(f, all_readers())[0] is MSN
    a, _, m, _ = parts(list(MSN.read(f, ctx(tmp_path))))
    who = {x.key: (x.me, x.address) for x in a}
    assert who["Julie"] == (False, "julie@hotmail.com")
    assert who["Léa"][0] is True
    assert local(m[1].temps.point).day == 13  # passé minuit dans la même session


def test_pseudo_nettoye() -> None:
    assert clean_nick("·$4,2Julie [c=12]☆[/c]") == "Julie ☆"


# -- SMS ---------------------------------------------------------------------------------------------

SMS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<smses count="3">
  <sms protocol="0" address="06 12 34 56 78" date="1552395933000" type="1" body="Tu rentres quand ?" contact_name="Maman" />
  <sms protocol="0" address="+33612345678" date="1552396000000" type="2" body="Vers 20h" contact_name="Maman" />
  <mms date="1552400000000" msg_box="1" address="+33611111111~+33622222222" contact_name="Julie, Paul">
    <parts><part ct="application/smil" text="x"/><part ct="text/plain" text="photo du soir"/><part ct="image/jpeg" name="IMG_1.jpg"/></parts>
    <addrs><addr address="+33611111111" type="137"/><addr address="+33622222222" type="151"/><addr address="+33699999999" type="151"/></addrs>
  </mms>
</smses>
"""


def test_sms_envoye_vient_d_elle_et_numeros_normalises(tmp_path: Path) -> None:
    f = tmp_path / "sms-20190312.xml"
    f.write_text(SMS_XML, encoding="utf-8")
    assert pick(f, all_readers())[0] is SMS
    a, c, m, _ = parts(list(SMS.read(f, ctx(tmp_path))))
    assert any(x.key == ME and x.me for x in a)
    maman = [x for x in c if x.key == "+33612345678"]
    assert maman and maman[0].title == "Maman"
    assert [x.author for x in m[:2]] == ["+33612345678", ME]  # 06… et +336… : la même conversation
    assert m[2].author == "+33611111111" and m[2].text == "photo du soir"
    assert m[2].attachments[0].name == "IMG_1.jpg"


# -- Mails ---------------------------------------------------------------------------------------------

EML = """From: Julie Martin <Julie@Example.com>
To: Lea <lea@example.org>
Subject: Re: vacances
Date: Thu, 12 Mar 2009 14:05:33 +0100
Message-ID: <b@example.com>
In-Reply-To: <a@example.com>
References: <a@example.com>
Content-Type: text/plain; charset=utf-8

Carrément pour l'Italie !

--
Julie

Le 11/03/2009 à 10:00, Lea a écrit :
> on part où ?
"""


def test_mail_eml_sans_citation_ni_signature(tmp_path: Path) -> None:
    f = tmp_path / "boite" / "Envoyés" / "1.eml"
    f.parent.mkdir(parents=True)
    f.write_text(EML, encoding="utf-8")
    assert pick(f, all_readers())[0] is MAIL
    a, c, m, _ = parts(list(MAIL.read(f, ctx(tmp_path))))
    assert m[0].text == "Carrément pour l'Italie !"
    assert c[0].key == "<a@example.com>"  # le fil : la racine des références
    assert m[0].author == "julie@example.com"
    assert {x.key: x.me for x in a}["julie@example.com"] is True  # rangé dans « Envoyés »
    assert m[0].temps.precision == Precision.EXACT


def test_mbox_et_masse(tmp_path: Path) -> None:
    f = tmp_path / "Inbox.mbox"
    f.write_text("From MAILER Thu Mar 12 14:05:33 2009\n" + EML.replace("Message-ID: <b@", "Message-ID: <c@")
                 + "\nFrom MAILER Thu Mar 12 15:00:00 2009\nFrom: Promo <noreply@shop.example>\nTo: lea@example.org\n"
                 "Subject: -50% !\nDate: Thu, 12 Mar 2009 15:00:00 +0100\nList-Unsubscribe: <mailto:x>\n\nSoldes\n",
                 encoding="utf-8")
    _, _, m, _ = parts(list(MAIL.read(f, ctx(tmp_path))))
    assert [x.kind for x in m] == ["message", "masse"]


def test_citation_outlook() -> None:
    body = "Ok pour moi.\n\nDe : Paul\nEnvoyé : jeudi 12 mars 2009\nÀ : Léa\nObjet : RE: réunion\n\nAncien texte"
    assert strip_quotes(body) == "Ok pour moi."


# -- Notes et journaux ---------------------------------------------------------------------------------

def test_journal_dans_un_seul_fichier(tmp_path: Path) -> None:
    f = tmp_path / "carnets" / "2009" / "journal.txt"
    f.parent.mkdir(parents=True)
    f.write_text("Mardi 30 décembre\nJournée calme.\n\n2 janvier\nNouvelle année, nouvelles résolutions.\n\n"
                 "Le 5 janvier 2010 :\nJ'ai rêvé de la mer.\n", encoding="utf-8")
    assert pick(f, all_readers())[0] is NOTES
    _, _, _, d = parts(list(NOTES.read(f, ctx(tmp_path))))
    assert [x.kind for x in d] == ["journal"] * 3
    dates = [local(x.temps.point).date() for x in d]
    assert [(x.year, x.month, x.day) for x in dates] == [(2009, 12, 30), (2010, 1, 2), (2010, 1, 5)]
    assert d[2].text == "J'ai rêvé de la mer."


def test_note_datee_par_son_dossier_sinon_bornee_par_le_fichier(tmp_path: Path) -> None:
    f = tmp_path / "été 2011" / "idées.md"
    f.parent.mkdir()
    f.write_text("# Idées\nApprendre la guitare", encoding="utf-8")
    _, _, _, d = parts(list(NOTES.read(f, ctx(tmp_path))))
    assert d[0].temps.precision == Precision.SEASON and d[0].title == "Idées"
    g = tmp_path / "sans-date.txt"
    g.write_text("une pensée", encoding="utf-8")
    _, _, _, d2 = parts(list(NOTES.read(g, ctx(tmp_path))))
    assert d2[0].temps.origin == Origin.FILE and d2[0].temps.start is None and d2[0].temps.end is not None


def test_keep(tmp_path: Path) -> None:
    f = tmp_path / "Keep" / "courses.json"
    f.parent.mkdir()
    f.write_text(json.dumps({"title": "Courses", "listContent": [{"text": "pain", "isChecked": True}],
                             "createdTimestampUsec": 1552395933000000, "isTrashed": False}))
    assert pick(f, all_readers())[0] is NOTES
    _, _, _, d = parts(list(NOTES.read(f, ctx(tmp_path))))
    assert d[0].text == "[x] pain" and d[0].temps.precision == Precision.EXACT


@pytest.mark.parametrize("name", ["LISEZMOI.md", "photo.jpg"])
def test_ce_qui_n_est_pas_une_archive(tmp_path: Path, name: str) -> None:
    f = tmp_path / name
    f.write_text("x", encoding="utf-8")
    reader, _ = pick(f, all_readers())
    assert reader is None
