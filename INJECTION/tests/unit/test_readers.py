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



def test_whatsapp_ios_ligne_systeme_au_nom_du_fil(tmp_path: Path) -> None:
    """iPhone : « Julie: ‎Les messages… chiffrés » est une ligne système, pas un message de Julie."""
    f = tmp_path / "WhatsApp Chat - Julie" / "_chat.txt"
    f.parent.mkdir()
    f.write_text("\u200e[12/03/2019 14:05:33] Julie: \u200eLes messages et les appels sont chiffrés de bout en bout.\n"
                 "[12/03/2019 14:06:00] Julie: Salut !\n"
                 "[12/03/2019 14:07:00] Léa: \u200eimage omise\n"
                 "[12/03/2019 14:08:00] Léa: coucou\n", encoding="utf-8")
    _, _, m, _ = parts(list(WHATSAPP.read(f, ctx(tmp_path))))
    assert (m[0].author, m[0].kind) == ("", "systeme") and "\u200e" not in m[0].text
    assert (m[1].author, m[1].text) == ("Julie", "Salut !")
    assert m[2].author == "Léa" and m[2].attachments  # une pièce jointe reste un message

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



def test_meta_chiffre_un_fichier_par_fil_dans_un_meme_dossier(tmp_path: Path) -> None:
    folder = tmp_path / "messages" / "e2ee"
    folder.mkdir(parents=True)
    for name, other in (("julie_10", "Julie"), ("paul_20", "Paul")):
        (folder / f"{name}.json").write_text(json.dumps({
            "participants": [other, "Léa"], "threadName": other,
            "messages": [{"senderName": other, "timestamp": 1552395933000, "text": "coucou", "type": "text"}]}),
            encoding="utf-8")
    keys = {x.key for f in folder.iterdir() for x in META.read(f, ctx(tmp_path)) if isinstance(x, Conversation)}
    assert keys == {"e2ee/julie_10", "e2ee/paul_20"}  # deux fils, pas un seul « e2ee »

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



def test_messenger_plus_un_ajoute_en_cours_de_session_n_est_pas_elle(tmp_path: Path) -> None:
    """Paul rejoint la conversation : absent de la liste lui aussi, il ne devient pas « elle »."""
    f = tmp_path / "julie@hotmail.com.txt"
    f.write_text(""".--------------------------------------------------------------------.
| Début de session : jeudi 12 mars 2009                              |
| Participants :                                                     |
|    Julie (julie@hotmail.com)                                       |
.--------------------------------------------------------------------.
[20:00:00] Léa : coucou
[20:00:10] Julie : salut
[20:01:00] Léa : t'as vu Paul ?
[20:02:00] Paul : je suis là
[20:03:00] Léa : ah bah voilà
""", encoding="utf-8")
    a, _, _, _ = parts(list(MSN.read(f, ctx(tmp_path))))
    who = {x.key: x.me for x in a}
    assert who["Léa"] is True and who["Paul"] is not True


def test_messenger_plus_a_egalite_on_ne_sait_pas(tmp_path: Path) -> None:
    f = tmp_path / "julie@hotmail.com.txt"
    f.write_text(""".--------------------------------------------------------------------.
| Début de session : jeudi 12 mars 2009                              |
| Participants :                                                     |
|    Julie (julie@hotmail.com)                                       |
.--------------------------------------------------------------------.
[20:00:00] Léa : coucou
[20:02:00] Paul : je suis là
""", encoding="utf-8")
    a, _, _, _ = parts(list(MSN.read(f, ctx(tmp_path))))
    assert not any(x.me for x in a)

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


MMS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<smses count="5">
  <sms address="0611111111" date="1552395000000" type="1" body="&#55357;&#56832; t'es où &#55357;&#1;?" contact_name="Julie" />
  <sms address="0611111111" date="1552395100000" type="3" body="brouillon jamais parti" contact_name="Julie" />
  <mms date="1552395200000" msg_box="2" address="+33611111111" contact_name="Julie">
    <parts><part ct="text/plain" text="regarde"/></parts>
    <addrs><addr address="+33699999999" type="137"/><addr address="+33611111111" type="151"/></addrs>
  </mms>
  <mms date="1552395300000" msg_box="1" address="+33611111111~+33622222222" contact_name="Julie, Paul">
    <parts><part ct="text/plain" text="ce soir ?"/></parts>
    <addrs><addr address="+33622222222" type="137"/><addr address="+33611111111" type="151"/>
           <addr address="+33699999999" type="151"/></addrs>
  </mms>
  <sms address="ORANGE" date="1552395400000" type="1" body="Votre forfait" />
</smses>
"""


def test_mms_son_numero_n_est_pas_une_correspondante(tmp_path: Path) -> None:
    f = tmp_path / "sms.xml"
    f.write_text(MMS_XML, encoding="utf-8")
    a, c, m, _ = parts(list(SMS.read(f, ctx(tmp_path))))
    me = next(x for x in a if x.key == ME)
    assert me.address == "+33699999999"  # l'expéditeur de son MMS envoyé
    assert all("+33699999999" not in x.members for x in c)
    # son MMS à Julie tombe dans la conversation de ses SMS avec Julie
    assert [x.conversation for x in m[:2]] == ["+33611111111", "+33611111111"]
    group = next(x for x in c if x.group)
    assert group.key == "+33611111111~+33622222222" and group.title == "Julie, Paul"
    assert m[2].author == "+33622222222"
    assert m[3].author == "orange"  # un expéditeur sans numéro garde son nom
    assert [x.text for x in m].count("brouillon jamais parti") == 0  # un brouillon n'a pas été envoyé


def test_sms_emojis_en_demi_caracteres_recomposes(tmp_path: Path) -> None:
    f = tmp_path / "sms.xml"
    f.write_text(MMS_XML, encoding="utf-8")
    m = parts(list(SMS.read(f, ctx(tmp_path))))[2]
    assert m[0].text == "😀 t'es où �?"  # la paire recomposée, la moitié seule remplacée, le contrôle retiré


def test_sms_reparation_au_vol_ne_coupe_pas_une_entite(tmp_path: Path) -> None:
    from functools import partial

    from twin.readers.sms import _repair, _Repaired

    f = tmp_path / "x.xml"
    data = ("<a>" + "&#55357;&#56832;x" * 40 + "&#55357;</a>").encode()
    f.write_bytes(data)
    for chunk in (3, 7, 16, 33):
        r = _Repaired(f, chunk=chunk)
        got = b"".join(iter(partial(r.read, 5), b""))
        r.close()
        assert got == _repair(data), chunk


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


def test_citation_html_emboitee_retiree_avant_le_reste() -> None:
    from twin.readers.mail import html_to_text

    got = html_to_text("<div>Oui, carrément !</div><blockquote>Tu viens ?<blockquote>On part samedi"
                       "</blockquote>Dis-moi vite</blockquote><p>Bises</p>")
    assert "Tu viens" not in got and "Dis-moi" not in got and "samedi" not in got
    assert "carrément" in got and "Bises" in got


def test_maildir_reconnu_par_ses_drapeaux(tmp_path: Path) -> None:
    f = tmp_path / ".Sent" / "cur" / "1552395933.M1P2.portable:2,S"
    f.parent.mkdir(parents=True)
    f.write_text(EML, encoding="utf-8")
    assert pick(f, all_readers())[0] is MAIL
    a, _, m, _ = parts(list(MAIL.read(f, ctx(tmp_path))))
    assert m[0].text == "Carrément pour l'Italie !"
    assert {x.key: x.me for x in a}["julie@example.com"] is True  # rangé dans « .Sent »


def test_mbox_sans_extension_aux_longs_en_tetes(tmp_path: Path) -> None:
    f = tmp_path / "Inbox"
    received = "".join(f"Received: from relais{i}.example.net (relais{i} [10.0.0.{i}]) by mx.example.org;"
                       f" Thu, 12 Mar 2009 14:05:{i % 60:02d} +0100\n" for i in range(60))
    f.write_text(f"From julie@example.com Thu Mar 12 14:05:33 2009\n{received}{EML}\n", encoding="utf-8")
    assert pick(f, all_readers())[0] is MAIL
    assert parts(list(MAIL.read(f, ctx(tmp_path))))[2][0].text == "Carrément pour l'Italie !"


def test_un_debut_de_fichier_coupe_en_plein_caractere_reste_lisible(tmp_path: Path) -> None:
    from twin.readers import head

    f = tmp_path / "x.txt"
    f.write_text("é" * 10, encoding="utf-8")
    assert head(f, 5) == "éé"  # le troisième « é » est coupé : pas de bascule en UTF-16

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



def test_journal_tenu_du_plus_recent_au_plus_ancien(tmp_path: Path) -> None:
    f = tmp_path / "carnets" / "2009" / "journal.txt"
    f.parent.mkdir(parents=True)
    f.write_text("Le 5 janvier 2010 :\nJ'ai rêvé de la mer.\n\n2 janvier\nNouvelle année.\n\n"
                 "Mardi 30 décembre\nJournée calme.\n\n12 décembre\nPremière neige.\n", encoding="utf-8")
    _, _, _, d = parts(list(NOTES.read(f, ctx(tmp_path))))
    assert [x.rank for x in d] == [0, 1, 2, 3]
    dates = [local(x.temps.point).date() for x in d]
    assert [(x.year, x.month, x.day) for x in dates] == [(2009, 12, 12), (2009, 12, 30), (2010, 1, 2), (2010, 1, 5)]
    assert d[0].text == "Première neige." and d[0].key.endswith("#3")  # la clé garde sa place dans le fichier

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
