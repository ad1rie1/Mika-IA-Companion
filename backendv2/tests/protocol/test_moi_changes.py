"""Le direct (ADR 0308), par le vrai serveur : ce qui change ce que montrent les écrans part sur le ``/ws`` de qui le
voit, en une trame ``changed`` qui dit quoi, jamais le contenu — et rien à qui ne le voit pas.

Pour lire ce qu'une connexion a reçu sans l'attendre indéfiniment, on laisse passer le regroupement, puis on lui envoie
un ``ping`` : ce qui est arrivé avant le ``pong`` est ce qu'elle a reçu.
"""

from __future__ import annotations

import json
import time

from mika.adapters.mail.oauth import Grant
from mika.app.domains.mail.settings import MailSettings
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.ports.mail import Draft as MailDraft
from tests.protocol.test_moi_mail import PROJET, append, with_mail
from tests.protocol.test_teams_live import LIVE
from tests.protocol.test_teams_web import DM, EXTENSION, batch, headers, new_key
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

#: le regroupement du serveur (150 ms), et de la marge
SETTLED_S = 0.6


def received(ws, t: int) -> list[dict]:
    """Ce que cette connexion a reçu jusqu'ici : tout ce qui précède le ``pong`` de ce ``ping``."""
    ws.send_json({"type": "ping", "t": t})
    return recv_until(ws, "pong", limit=200)[:-1]


def changes(frames: list[dict]) -> list[dict]:
    return [c for f in frames if f["type"] == "changed" for c in f["changes"]]


def lea_session(client, live) -> str:
    async def make() -> str:
        lea = await live.accounts.create("lea", "un-mot-de-passe-long", operator=False, full_name="Léa Martin")
        return await live.accounts.open_session(lea)

    return client.portal.call(make)


def test_a_teams_batch_reaches_the_screen_of_its_owner_and_no_one_else(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)  # Adrien : une des propriétaires, à qui est « principal » (« à toi »)
    key = new_key(client, live)
    session = lea_session(client, live)  # un compte de plus : les écrans relisent qui est connecté (``me``)
    with client.websocket_connect(WS) as adrien, \
            client.websocket_connect(WS, headers={"cookie": f"sessionid={session}"}) as lea:
        time.sleep(SETTLED_S)
        received(adrien, 1), received(lea, 1)  # ce que dit une ouverture (l'historique, son visage, son panneau)
        assert client.post("/api/teams/inbox", json=batch(2), headers=headers(key)).status_code == 202
        time.sleep(SETTLED_S)
        his, hers = changes(received(adrien, 2)), changes(received(lea, 2))
    assert {"topic": "teams", "conversations": [DM]} in his
    assert all(set(c) <= {"topic", "boxes", "conversations", "refs", "projects"} for c in his)  # jamais le contenu
    assert "On se voit" not in json.dumps(his)
    assert hers == []  # le compte d'un autre n'existe pas pour elle, même dans un avis


def test_a_draft_she_proposes_tells_its_box_and_the_badges(world):  # noqa: F811
    client, live, box = with_mail(world)
    with client.websocket_connect(WS) as adrien:
        received(adrien, 1)
        draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re: Maquettes",
                                         body="Merci Léa, retour jeudi.", reply_to=PROJET))
        append(client, live, [rt.EFFECT_PROPOSED.draft(
            capability="email.send", owner="email", summary=Content.of("Répondre à Léa"), context="email",
            args_json=json.dumps({"draft": draft.id, "account": "pro", "mail": PROJET}))])
        time.sleep(SETTLED_S)
        said = changes(received(adrien, 2))
    assert {"topic": "mail.drafts", "boxes": ["pro"]} in said and {"topic": "me"} in said
    assert {"topic": "mail.work", "refs": [PROJET]} in said


def test_the_extension_that_comes_and_goes_is_seen_by_the_screens_of_its_account(world):  # noqa: F811
    """La présence de l'extension (``last_seen``) se voit : sa connexion en direct qui s'ouvre, puis se ferme, fait
    relire ses comptes à qui lit le compte — et à personne d'autre."""
    client, live, _ = world
    bootstrap(client)
    key = new_key(client, live)
    session = lea_session(client, live)
    # elle s'est déjà manifestée il y a un instant (un lot) : c'est sa connexion en direct qui se dit
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    with client.websocket_connect(WS) as adrien, \
            client.websocket_connect(WS, headers={"cookie": f"sessionid={session}"}) as lea:
        time.sleep(SETTLED_S)
        received(adrien, 1), received(lea, 1)
        with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as extension:
            extension.send_json({"type": "hello", "key": key})
            assert extension.receive_json()["type"] == "outbox"
            time.sleep(SETTLED_S)
            opened, hers = changes(received(adrien, 2)), changes(received(lea, 2))
        time.sleep(SETTLED_S)
        closed = changes(received(adrien, 3))
    assert opened == [{"topic": "teams"}] and closed == [{"topic": "teams"}]
    assert hers == []


def test_a_box_setting_saved_outside_the_journal_is_pushed(world):  # noqa: F811
    """Ce qui s'enregistre hors du journal (``Settings._put``) — ici la connexion Microsoft d'une boîte, que Paramètres
    attendait en relisant — se pousse aussi."""
    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as adrien:
        time.sleep(SETTLED_S)
        received(adrien, 1)
        client.portal.call(live.settings.of(MailSettings).save_mail_grant, "pro", Grant("un-jeton", "client", "common"))
        time.sleep(SETTLED_S)
        said = changes(received(adrien, 2))
    assert {"topic": "mail"} in said and {"topic": "settings"} in said
