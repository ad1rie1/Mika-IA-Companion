"""Ses réponses jugées depuis le chat (ADR 0113).

Son opératrice dit, sous une de ses réponses, si elle était adaptée — et, si elle veut, ce qu'elle aurait dû dire.
L'avis passe par le chemin des actions de la console (validé, audité), se garde à côté du message dans le fil,
revient dans l'historique de l'opératrice seulement, et se lit dans la console (« pourquoi a-t-elle dit ça ? », « Ses
réponses jugées »). Une autre connexion ne peut ni juger ni voir un avis.
"""

from __future__ import annotations

import re

from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from tests.protocol.test_console_operator import BASE, html_of
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée
from tests.protocol.test_web_thread import opening, talk


def _result(ws) -> dict:
    return next(f for f in recv_until(ws, "verdict_result") if f["type"] == "verdict_result")


def test_her_owner_judges_a_reply_from_the_chat_and_only_she_sees_it(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)

    async def bea_session() -> str:
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        return await live.accounts.open_session(bea)

    key_b = client.portal.call(bea_session)
    with client.websocket_connect(WS) as a:
        opening(a)
        speech = talk(a, "coucou", "m1")
        seq = speech["message_id"]
        a.send_json({"type": "verdict", "message_id": seq, "verdict": "ko",
                     "comment": "trop long : juste « salut ! »"})
        got = _result(a)
        assert got["status"] == "ok" and got["verdict"] == "ko" and got["message_id"] == seq
        # contre-exemples : un message de la personne n'est pas une de ses réponses ; un avis inconnu est ignoré
        a.send_json({"type": "verdict", "message_id": speech["user_message_id"], "verdict": "ok"})
        assert _result(a)["status"] == "invalid"
        a.send_json({"type": "sync", "after_id": 0})
        rows = {m["id"]: m for m in recv_until(a, "history")[-1]["messages"]}
        assert rows[seq]["verdict"] == "ko" and rows[seq]["verdict_note"] == "trop long : juste « salut ! »"
        assert "verdict" not in rows[speech["user_message_id"]]
    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as b:
        opening(b)
        b.send_json({"type": "verdict", "message_id": seq, "verdict": "ok"})
        assert _result(b)["status"] == "forbidden"  # pas une opératrice

    judged = client.portal.call(lambda: live.kernel.mind.store.latest([transcript_c.JUDGED.name], 5))
    assert len(judged) == 1  # le refus n'a rien écrit
    audited = client.portal.call(lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 5))
    assert any("transcript.juger" in live.kernel.mind.decode(e).data.action for e in audited)

    why = html_of(client.get(f"/inspecteur/parole/{seq}"))
    assert "Ton avis" in why and "pas adaptée" in why and "juste « salut ! »" in why
    listed = html_of(client.get(f"{BASE}/fil/jugees"))
    assert "Ses réponses jugées" in listed and "coucou" in listed and "juste « salut ! »" in listed


def test_the_judged_replies_filter_by_verdict_in_one_click(world):  # noqa: F811
    """L'avis est un filtre de trois choix toujours posé (« toutes » par défaut) : un bouton à choix au bout de la
    barre d'onglets, pas un sélecteur et « Filtrer » (ADR 0176) ; la personne s'y lit par son nom, sans sa clé."""
    client, _live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as a:
        opening(a)
        for text, cid, verdict, note in (("coucou", "m1", "ko", "trop long"), ("bonsoir", "m2", "ok", "parfait")):
            seq = talk(a, text, cid)["message_id"]
            a.send_json({"type": "verdict", "message_id": seq, "verdict": verdict, "comment": note})
            assert _result(a)["status"] == "ok"
    url = f"{BASE}/fil/jugees"
    listed = html_of(client.get(url))
    seg = listed.split('<nav class="seg" aria-label="avis">', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r">([^<]+)</a>", seg) == ["toutes", "pas adaptées", "adaptées"]
    assert re.search(r'aria-current="true">toutes<', seg) and '<select name="avis"' not in listed
    shown = listed.split('data-tab="fil/jugees"', 1)[1]
    assert "trop long" in shown and "parfait" in shown
    assert ">adrien</a>" in shown and "(user_1)" not in shown
    ko = html_of(client.get(f"{url}?avis=ko")).split('data-tab="fil/jugees"', 1)[1]
    assert "trop long" in ko and "parfait" not in ko
    ok = html_of(client.get(f"{url}?avis=ok")).split('data-tab="fil/jugees"', 1)[1]
    assert "parfait" in ok and "trop long" not in ok
    before = html_of(client.get(f"{url}?avis="))  # une adresse d'avant le bouton à choix : toutes
    assert "trop long" in before and "parfait" in before and re.search(r'aria-current="true">toutes<', before)


def test_an_opinion_withdrawn_leaves_the_reply_unjudged(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as a:
        opening(a)
        seq = talk(a, "coucou", "m1")["message_id"]
        a.send_json({"type": "verdict", "message_id": seq, "verdict": "ok", "comment": "parfait"})
        assert _result(a)["status"] == "ok"
        a.send_json({"type": "verdict", "message_id": seq, "verdict": ""})
        assert _result(a)["status"] == "ok"
        a.send_json({"type": "sync", "after_id": 0})
        rows = {m["id"]: m for m in recv_until(a, "history")[-1]["messages"]}
        assert "verdict" not in rows[seq]
    assert "Ton avis" not in html_of(client.get(f"/inspecteur/parole/{seq}"))
