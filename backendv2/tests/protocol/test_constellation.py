"""La constellation (ADR 0103), à travers le vrai serveur : une page réservée aux opérateurs, une carte tirée de
l'index des vecteurs, un flux qui ne traduit rien sans lecteur, et des trajets qui sont des événements du journal —
un souvenir qui naît, une parole et ce que son prompt lui a vraiment montré."""

from __future__ import annotations

import asyncio
import math

from mika.app import genesis
from mika.app.constellation import BASE, point_refs
from mika.ports.vectors import VectorItem
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

ME = "user_1"
SEEDS = ("Son chat Moustache est malade depuis lundi", "Son chat Moustache est encore malade ce matin",
         "Il prépare un voyage au Japon cet été", "Il apprend la guitare depuis l'été")


def seed(client, live, texts=SEEDS) -> list[int]:
    async def go():
        return [await genesis.remember(live.kernel, t, [ME], told_by=[ME], importance=0.6) for t in texts]
    return client.portal.call(go)


def indexed(client, live, keys, texts=SEEDS) -> None:
    """Les éléments semés, dans l'index des vecteurs — posés directement, comme son processus d'index le ferait : il
    tourne sur l'ordonnanceur, et son heure n'est pas ce qu'on teste ici (sous charge, il passait parfois après 15 s)."""
    client.portal.call(live.constellation.vectors.upsert,
                       [VectorItem(k, "souvenir", t, (ME,)) for k, t in zip(keys, texts, strict=True)])
    assert set(keys) <= live.constellation.vectors.indexed()


def events(client, kind: str, after: int = 0, timeout: float = 15.0) -> list[dict]:
    """Le flux, lu comme l'écran le lit, jusqu'à un élément de cette sorte."""
    async def nap():
        await asyncio.sleep(0.05)
    for _ in range(int(timeout / 0.05)):
        got = client.get(f"{BASE}/flux", params={"apres": after}).json()["events"]
        if any(e["type"] == kind for e in got):
            return got
        client.portal.call(nap)
    raise AssertionError(f"pas d'élément « {kind} » dans le flux")


def test_point_refs_read_what_the_prompt_showed():
    assert point_refs(("memory:12", "chunk:40", "veiled:12", "goal:3", "dream:4", "memory:x", "chunk:40")) == [12, 40]


def test_only_an_operator_sees_her_memory(world):  # noqa: F811
    client, live, _ = world
    page = client.get(BASE, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].endswith("/inspecteur/connexion")
    for path in ("/carte", "/flux", "/rejeu", "/point/1", "/cherche?q=chat"):
        assert client.get(BASE + path).status_code == 401, path
    bootstrap(client)
    page = client.get(BASE)
    assert page.status_code == 200 and "script-src 'self'" in page.headers["content-security-policy"]
    ConsoleHTML(page.text).check()
    assert 'data-base="/inspecteur/constellation"' in page.text and "<script>" not in page.text
    # un compte qui n'est pas opérateur ne la voit pas non plus : elle montre tout, secrets compris
    async def guest():
        account = await live.accounts.create("bea", "un-autre-mot-de-passe", operator=False)
        return await live.accounts.open_session(account)
    client.cookies.set("sessionid", client.portal.call(guest))
    assert client.get(BASE, follow_redirects=False).status_code == 303
    assert client.get(BASE + "/carte").status_code == 401


def test_the_map_is_drawn_from_the_index_and_says_nothing_of_texts(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    empty = client.get(f"{BASE}/carte").json()
    assert empty["shown"] == 0 and empty["points"]["key"] == [] and empty["her"]
    keys = seed(client, live)
    indexed(client, live, keys)
    got = client.get(f"{BASE}/carte").json()
    p = got["points"]
    assert set(keys) <= set(p["key"]) and got["shown"] == len(p["key"]) == got["total"]
    n = got["shown"]
    assert len(p["dir"]) == 3 * n
    assert all(abs(math.dist((0, 0, 0), p["dir"][3 * i:3 * i + 3]) - 1) < 1e-3 for i in range(n))  # sur la sphère
    at = {k: i for i, k in enumerate(p["key"])}
    assert all(got["kinds"][p["kind"][at[k]]] == "souvenir" and p["importance"][at[k]] == 0.6 for k in keys)
    assert got["persons"][p["person"][at[keys[0]]]]["key"] == ME
    assert all(0 <= a < n and 0 <= b < n for a, b in zip(got["edges"][::2], got["edges"][1::2], strict=True))
    assert "Moustache" not in str(got)  # les textes ne partent qu'à la demande
    one = client.get(f"{BASE}/point/{keys[0]}").json()
    assert one["text"] == SEEDS[0] and one["kind"] == "souvenir" and one["href"] == f"/inspecteur/evenement/{keys[0]}"
    assert client.get(f"{BASE}/point/999999").status_code == 404


def test_search_finds_by_words_then_by_meaning(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    keys = seed(client, live)
    indexed(client, live, keys)
    client.get(f"{BASE}/carte")
    got = client.get(f"{BASE}/cherche", params={"q": "  MOUSTACHÉ "}).json()
    assert got["q"] == "MOUSTACHÉ"
    words = [h["key"] for h in got["hits"] if h["how"] == "mot"]
    assert words == sorted(keys[:2], reverse=True)  # replié comme la console ; les plus récents d'abord
    assert all("Moustache" in h["text"] for h in got["hits"] if h["how"] == "mot")
    meaning = [h for h in got["hits"] if h["how"] == "sens"]
    assert not {h["key"] for h in meaning} & set(words)  # un point n'y est qu'une fois
    # par le sens, seulement ce qui dépasse 0,4 : ni le Japon ni la guitare quand on parle de Moustache
    assert not {h["key"] for h in meaning} & set(keys[2:])
    near = [h for h in client.get(f"{BASE}/cherche", params={"q": "son chat est malade"}).json()["hits"]
            if h["how"] == "sens"]
    assert {h["key"] for h in near} == set(keys[:2]) and all(h["score"] > 0.4 for h in near)
    assert [h["score"] for h in meaning] == sorted((h["score"] for h in meaning), reverse=True)
    assert abs(math.dist((0, 0, 0), got["query"]) - 1) < 1e-3
    # « % » et « _ » sont des caractères comme les autres, pas des jokers
    assert not [h for h in client.get(f"{BASE}/cherche", params={"q": "%"}).json()["hits"] if h["how"] == "mot"]
    assert client.get(f"{BASE}/cherche", params={"q": "   "}).json() == {"q": "", "hits": [], "query": None}


def test_nothing_is_translated_without_a_viewer_then_a_memory_is_born_in_the_feed(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    keys = seed(client, live, SEEDS[:2])
    indexed(client, live, keys, SEEDS[:2])
    assert live.constellation.since(0) == []  # personne ne regardait : rien n'a été trié ni plongé
    head = client.get(f"{BASE}/carte").json()["head"]
    born = seed(client, live, ("Moustache s'est remis à manger",))[0]
    got = events(client, "naissance", head)
    birth = next(e for e in got if e["type"] == "naissance")
    assert birth["key"] == born and birth["kind"] == "souvenir" and birth["agent"] == "memoire"
    assert abs(math.dist((0, 0, 0), birth["dir"]) - 1) < 1e-3 and birth["person"] == ME
    assert set(birth["near"]) <= set(keys) and birth["near"]
    # posé sur la carte sans la recalculer, et le flux ne le rejoue pas
    assert born in client.get(f"{BASE}/carte").json()["points"]["key"]
    again = client.get(f"{BASE}/flux", params={"apres": birth["id"]}).json()
    assert all(e["id"] > birth["id"] for e in again["events"])


def test_a_reply_shows_what_came_back_to_her(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)
    keys = seed(client, live)
    indexed(client, live, keys)
    head = client.get(f"{BASE}/carte").json()["head"]
    with client.websocket_connect(WS) as ws:
        recv_until(ws, "inner_state_update")
        ws.send_json({"type": "chat", "message": "tu te souviens de Moustache, mon chat malade ?",
                      "client_msg_id": "c1"})
        speech = recv_until(ws, "speech")[-1]
    got = events(client, "rappel", head)
    recall = next(e for e in got if e["type"] == "rappel")
    assert recall["agent"] == "reponse" and recall["message"] == "tu te souviens de Moustache, mon chat malade ?"
    assert recall["seq"] == speech["message_id"]  # la parole, et « pourquoi a-t-elle dit ça ? » à son numéro
    # ce qui lui est revenu, c'est la provenance de sa parole (ce que son prompt montrait) — pas ce qu'on devine ici
    refs = point_refs(client.portal.call(_utterance, live, recall["seq"]))
    assert recall["shown"] == [k for k in refs if k in set(recall["shown"])]
    assert len(recall["shown"]) + recall["missing"] == len(refs)
    assert set(keys[:2]) <= set(recall["shown"])  # Moustache lui revient, les deux fois
    # le sondage : les plus proches du message, du plus proche au plus lointain — Moustache en tête
    sims = [s for _, s in recall["probed"]]
    assert sims == sorted(sims, reverse=True) and {k for k, _ in recall["probed"][:2]} == set(keys[:2])
    assert abs(math.dist((0, 0, 0), recall["query"]) - 1) < 1e-3
    # et le rejeu traduit la même parole de la même façon
    replay = client.get(f"{BASE}/rejeu", params={"n": 5}).json()["events"]
    again = next(e for e in replay if e["type"] == "rappel" and e["seq"] == recall["seq"])
    assert again["shown"] == recall["shown"] and again["replay"] is True


async def _utterance(live, seq: int) -> tuple[str, ...]:
    stored = live.kernel.mind.store.get_events([seq])
    return tuple(live.kernel.mind.decode(stored[0]).data.provenance)
