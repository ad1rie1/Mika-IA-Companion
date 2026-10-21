"""« En ce moment » (``app/now.py``), à travers le vrai serveur : une page réservée aux opérateurs, dans le cadre
de la console, qui croise ses facultés — son humeur, sa journée, les gens, ses pensées — et dont le fragment se
relit seul ; une lecture qui échoue tait sa carte, jamais la page."""

from __future__ import annotations

import html
import re

from mika.app import handmade
from mika.app.handmade import now
from mika.contracts import attention as attention_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

THOUGHT = "Je me demande comment s'est passé le concert de guitare"


def chat(client, text: str = "salut ! je reviens d'un concert") -> None:
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": text, "client_msg_id": "now-1"})
        recv_until(ws, "speech", limit=40)


def think(client, live, text: str = THOUGHT) -> None:
    async def go():
        await live.kernel.mind.append([attention_c.THOUGHT_BORN.draft(
            text=Content.of(text), emotion="curious", intensity=0.6, origin=attention_c.EXCHANGE,
            about=("user_1",))], emitter="attention", origin=Origin.GENESIS, correlation="test-en-ce-moment")
    client.portal.call(go)


def test_only_an_operator_sees_her_now(world):  # noqa: F811
    client, live, _ = world
    page = client.get(now.BASE, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].endswith("/inspecteur/connexion")
    assert client.get(now.FRAGMENT).status_code == 401
    async def guest():
        account = await live.accounts.create("bea", "un-autre-mot-de-passe", operator=False)
        return await live.accounts.open_session(account)
    client.cookies.set("sessionid", client.portal.call(guest))
    assert client.get(now.BASE, follow_redirects=False).status_code == 303
    assert client.get(now.FRAGMENT).status_code == 401


def test_the_page_crosses_her_faculties(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client)
    think(client, live)
    page = client.get(now.BASE)
    assert page.status_code == 200
    assert "script-src 'self'" in page.headers["content-security-policy"]
    ConsoleHTML(page.text).check()
    text = html.unescape(page.text)
    # dans le cadre de la console : son menu allume « En ce moment », le titre porte son nom (sa persona)
    assert re.search(r'<a class="nav-item on" href="/inspecteur/maintenant"', text)
    assert "<h1>Mika, en ce moment</h1>" in text
    # ni style ni script en ligne (CSP stricte) : les longueurs sont des attributs SVG
    assert " style=" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text)
    assert f'data-now-live="{now.FRAGMENT}"' in text
    # son humeur en mots, ce que son prompt lui en dit, le plan plaisir × éveil
    assert 'class="now-word"' in text and "ce que son prompt lui en dit" in text and 'class="plane-now"' in text
    # les gens : celle qui vient de lui écrire, et sa fiche (ouverte sur ce qu'elle vit avec elle)
    assert 'href="/inspecteur/fiche/person/user_1"' in text and "lui a écrit à l'instant" in text
    # sa pensée, et le fil de sa journée (une réponse, la pensée)
    assert THOUGHT in text
    assert "A répondu à adrien" in text and "Une pensée lui vient" in text
    # sur l'axe des 24 heures : sa réponse et sa pensée, chacune de sa couleur (des classes que la feuille connaît)
    assert 'class="mark mark-reply"' in text and 'class="mark mark-thought"' in text
    # sa propriétaire se dit, et une conversation en cours n'est pas une attente
    assert '<span class="now-tag owner">propriétaire</span>' in text and "en pleine conversation" in text
    # aujourd'hui, en chiffres : sa réponse, sa pensée
    assert re.search(r'now-today-value now-num">1</span><span class="now-today-label">réponses', text)
    # aucune carte n'a échoué
    assert "Impossible de lire" not in text


def test_the_fragment_is_the_body_alone(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    think(client, live)
    fragment = client.get(now.FRAGMENT)
    assert fragment.status_code == 200
    assert "<html" not in fragment.text and "<h1" not in fragment.text
    assert "data-now-stamp" in fragment.text and THOUGHT in html.unescape(fragment.text)


def test_a_failing_reading_silences_its_card_not_the_page(world, monkeypatch):  # noqa: F811
    client, _, _ = world
    bootstrap(client)

    def broken(look):
        raise RuntimeError("lecture cassée")

    monkeypatch.setattr(now, "PARTS", tuple((key, broken if key == "needs" else part) for key, part in now.PARTS))
    page = client.get(now.BASE)
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    assert "Impossible de lire ses besoins" in page.text
    assert page.text.count("Impossible de lire") == 1


# ── ce qui se calcule sans serveur ──


def test_time_is_said_in_words():
    assert handmade.ago(10 * MINUTE, 10 * MINUTE) == "à l'instant"
    assert handmade.ago(HOUR, 48 * MINUTE) == "il y a 12 min"
    assert handmade.ago(DAY, DAY - 3 * HOUR) == "il y a 3 h"
    assert handmade.span(40 * MINUTE) == "40 min"
    assert handmade.span(7 * HOUR + 40 * MINUTE) == "7 h 40"
    assert handmade.span(7 * HOUR) == "7 h"
    assert handmade.span(2 * DAY + 3 * HOUR) == "2 j 3 h"


def test_the_plane_keeps_her_inside_and_draws_her_day_oldest_palest():
    lo, hi = now.PLANE_PAD, now.PLANE - now.PLANE_PAD
    assert now.plane_xy(-1, -1) == (lo, hi) and now.plane_xy(1, 1) == (hi, lo)
    assert now.plane_xy(5, -5) == now.plane_xy(1, -1)  # hors bornes : au bord, jamais hors du dessin
    valence = [(i * 10 * MINUTE, i / 20) for i in range(20)]
    arousal = [(i * 10 * MINUTE, -i / 20) for i in range(20)]
    parts = now.trail(valence, arousal)
    assert [p["step"] for p in parts] == sorted(p["step"] for p in parts) and parts[-1]["step"] == 5
    # deux tronçons voisins se touchent : la trace ne saute pas
    assert parts[0]["d"].split(" L")[-1] == parts[1]["d"][1:].split(" L")[0]
    assert now.trail(valence, []) == []  # sans éveil mesuré au même instant, pas de trace


def test_a_gap_in_the_measures_cuts_the_line():
    points = [(i * 10 * MINUTE, 0.5) for i in range(6)] + [(5 * HOUR + i * 10 * MINUTE, 0.5) for i in range(6)]
    assert [len(run) for run in now._runs(points)] == [6, 6]
