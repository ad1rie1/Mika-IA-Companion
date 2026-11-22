"""Le téléphone et ce qu'on lui raconte, dans l'annuaire de la console (ADR 0298, lot 5), à travers le vrai serveur :
d'où elle connaît chacun (« WhatsApp · 5 », « SMS · 1 », « Racontée · 3 fois »), où elle le voit (chaque conversation
du téléphone, chaque personne qui lui en a parlé), ce qui l'identifie (le nom du carnet, le nom raconté), de qui c'est
le contact (de la personne dont c'est le téléphone, de qui l'a raconté) ; les rapprochements d'un prénom seul ; et un
nom raconté qui se relie à quelqu'un qui lui parle par l'identité, jamais par l'annuaire seul."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, quote, urlsplit

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.ports.contacts import EMAIL, MAIL, PHONE_APP, PHONE_SOURCE, TOLD, TOLD_NAME, Observation
from mika.vocab.access import SELF
from tests.protocol.test_console_annuaire import ANNUAIRE, HOUR, _entry, fiche
from tests.protocol.test_drawn_fiches import drawn, form_of
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ADRIEN = "user_1"
LEA = "name:aaaaaaaaaaaaaaaa:lea"
DUO, GROUP = "abcdefabcdefabcd", "f00dfeedf00dfeed"
WHATSAPP_GILLES, SMS_GILLES = "whatsapp:3fa9c2d81b0e", "messages:7b1d0e93aa42"


def seed(client, live) -> dict[str, int]:
    """Le téléphone d'adrien : Gilles sur WhatsApp (en tête-à-tête et dans le groupe « Famille ») et par SMS ; Léa,
    dont adrien lui a parlé trois fois ; « Léa Martin », dans une boîte à elle."""
    store = live.kernel.ports["contacts"]
    now = live.kernel.mind.frame().now
    phone = (PHONE_SOURCE, ADRIEN)
    client.portal.call(lambda: store.observe([
        Observation(PHONE_APP, WHATSAPP_GILLES, *phone, "Gilles Nordis", 2, now - 9 * HOUR, now - 3 * HOUR,
                    thread=DUO),
        Observation(PHONE_APP, WHATSAPP_GILLES, *phone, "Gilles Nordis", 3, now - 8 * HOUR, now - 2 * HOUR,
                    thread=GROUP, thread_title="Famille", group=True),
        Observation(PHONE_APP, SMS_GILLES, *phone, "Gilles Nordis", 1, now - 5 * HOUR, now - 5 * HOUR, thread=DUO),
        Observation(TOLD_NAME, LEA, TOLD, ADRIEN, "Léa", 3, now - 30 * HOUR, now - 6 * HOUR),
        Observation(EMAIL, "lea.martin@calix.fr", MAIL, "perso", "Léa Martin", 5, now - 40 * HOUR, now - 7 * HOUR),
    ]))
    out = {"whatsapp": store.contact_of(PHONE_APP, WHATSAPP_GILLES), "sms": store.contact_of(PHONE_APP, SMS_GILLES),
           "lea": store.contact_of(TOLD_NAME, LEA), "martin": store.contact_of(EMAIL, "lea.martin@calix.fr")}
    assert all(out.values()) and len(set(out.values())) == 4
    return out


def setup(client, live) -> dict[str, int]:
    bootstrap(client)
    chat(client, "salut ! moi c'est Adrien")
    client.portal.call(lambda: live.settings.save_email(MailConfig(accounts={"perso": MailAccount(
        label="Personnel", address="mika@example.test", enabled=False, owner=SELF)})))
    return seed(client, live)


def test_the_directory_says_where_she_knows_each_one_from(world):  # noqa: F811
    client, live, _ = world
    ids = setup(client, live)
    page = drawn(client, ANNUAIRE)
    sms = page.index(f'href="{fiche(ids["sms"])}"')
    whatsapp = _entry(page, "Gilles Nordis")  # le plus récent des deux : WhatsApp
    assert "WhatsApp · <b>5</b>" in whatsapp and "Téléphone ·" not in whatsapp
    assert re.search(r'contact de</span> <a href="/admin/fiche/person/user_1\?onglet=contacts">adrien</a>', whatsapp)
    assert '<span class="k">WhatsApp</span><span class="v">Gilles Nordis</span>' in whatsapp  # son appli, pas sa clé
    assert "SMS · <b>1</b>" in page[sms:]
    lea = _entry(page, "Léa")
    assert "Racontée · <b>3 fois</b>" in lea and "racontée il y a" in lea
    assert "Aucun moyen de communication : connue seulement de nom." in lea and LEA not in lea
    assert "contact de</span> <a" in lea
    # ses contacts à lui : son téléphone et ce qu'il lui a raconté
    mine = drawn(client, f"{ANNUAIRE}?de=user_1")
    assert "Gilles Nordis" in mine and ">Léa</a>" in mine and "Léa Martin" not in mine
    tab = drawn(client, "/admin/fiche/person/user_1?onglet=contacts")
    assert "Gilles Nordis" in tab and ">Léa</a>" in tab
    assert "Téléphone" in tab and "Racontés" in tab  # ses puces : son téléphone, ce qu'il lui a raconté


def test_a_phone_contact_sheet_lists_each_conversation(world):  # noqa: F811
    client, live, _ = world
    ids = setup(client, live)
    page = html.unescape(drawn(client, fiche(ids["whatsapp"])))
    assert "<h1>Gilles Nordis</h1>" in page and "ne lui a jamais écrit" in page and "5 messages lus" in page
    assert "3 messages · groupe « Famille »" in page and "2 messages · en tête-à-tête" in page
    assert 'href="/admin/fiche/person/user_1?onglet=telephone"' in page and "le téléphone d'adrien" in page
    assert "ne se dit qu'à adrien" in page
    tab = html.unescape(drawn(client, fiche(ids["whatsapp"], "identifiants")))
    assert "Contact WhatsApp" in tab and "Le nom sous lequel le téléphone d'adrien le connaît" in tab
    assert WHATSAPP_GILLES not in tab.split("<main", 1)[1]


def test_a_told_contact_says_who_told_her_and_how_often(world):  # noqa: F811
    client, live, _ = world
    ids = setup(client, live)
    page = html.unescape(drawn(client, fiche(ids["lea"])))
    assert "<h1>Léa</h1>" in page and "racontée 3 fois" in page and "Racontée pour la première fois" in page
    assert "connue seulement de nom" in page and "0 moyen" not in page and "messages lus" not in page
    assert "par ce qu'adrien lui a raconté" in page
    assert "racontée par adrien · 3 fois" in page and 'href="/admin/fiche/person/user_1?onglet=echanges"' in page
    tab = html.unescape(drawn(client, fiche(ids["lea"], "identifiants")))
    assert "Nom raconté" in tab and "On lui en a parlé sous ce nom" in tab


def test_a_first_name_alone_is_a_weaker_rapprochement(world):  # noqa: F811
    client, live, _ = world
    ids = setup(client, live)
    queue = html.unescape(drawn(client, "/admin/approbations/rapprochements"))
    assert "« Léa » et « Léa Martin » : la même personne ?" in queue or \
        "« Léa Martin » et « Léa » : la même personne ?" in queue
    pair = f"rapprochement:{min(ids['lea'], ids['martin'])}-{max(ids['lea'], ids['martin'])}"
    opened = html.unescape(drawn(client, f"/admin/approbations/rapprochements?element={quote(pair)}"))
    assert "Le même prénom, d'un côté sans nom de famille" in opened and "Racontée · <b>3 fois</b>" in opened
    gilles = f"rapprochement:{min(ids['whatsapp'], ids['sms'])}-{max(ids['whatsapp'], ids['sms'])}"
    opened = html.unescape(drawn(client, f"/admin/approbations/rapprochements?element={quote(gilles)}"))
    assert "Le même nom" in opened and "WhatsApp · <b>5</b>" in opened and "SMS · <b>1</b>" in opened


def test_a_told_name_is_tied_to_who_talks_to_her_through_the_identity(world):  # noqa: F811
    """« Réunir avec… » une personne, depuis une fiche qui n'est qu'un nom raconté, mène au formulaire de l'identité
    (« C'est la personne dont on lui a parlé », pré-rempli) : sa mémoire le saura ; l'annuaire seul ne la relie pas."""
    client, live, _ = world
    ids = setup(client, live)
    merge = form_of(drawn(client, fiche(ids["lea"])), "contacts.reunir")
    done = client.post("/admin/action/contacts.reunir", data={**merge, "personne": [ADRIEN], "fiche": [""]},
                       follow_redirects=False)
    assert done.status_code == 303
    target = urlsplit(done.headers["location"])
    assert target.path == "/admin/fiche/person/user_1"
    assert parse_qs(target.query)["nom"] == [LEA] and parse_qs(target.query)["onglet"] == ["synthese"]
    assert live.kernel.ports["contacts"].sheet(ids["lea"]).person == ""


def test_forgetting_a_told_contact_reaches_her_memory_of_the_name(world):  # noqa: F811
    client, live, _ = world
    ids = setup(client, live)
    page = drawn(client, fiche(ids["lea"]))
    form = re.search(r'<form[^>]+action="(/admin/oublier/contact/[^"]+)".*?</form>', page, re.S)
    data = {name: [html.unescape(value)] for name, value in
            re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(0))}
    store = live.kernel.ports["contacts"]
    reached: list[str] = []
    original = store.forget

    async def spy(subject: str) -> int:
        reached.append(subject)
        return await original(subject)

    store.forget = spy
    try:
        done = client.post(form.group(1), data={**data, "_confirmer": ["Léa"]}, follow_redirects=False)
    finally:
        store.forget = original
    assert done.status_code == 303
    assert store.sheet(ids["lea"]) is None and LEA in reached
    assert quote(LEA, safe="") not in client.get(ANNUAIRE).text
