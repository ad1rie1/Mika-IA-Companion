"""L'API par personne, Teams (ADR 0187, 0189, 0191) : à travers le vrai serveur et la vraie porte de l'extension. Une
personne ne voit que ses comptes ; ce qu'elle écrit elle-même part par l'extension sous son nom, sans signature ni
accord ; ses décisions sur une réponse de Mika passent par les actions de la console, en son nom."""

from __future__ import annotations

import json
import time

from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.app.moi import form
from mika.contracts import runtime as rt
from mika.contracts import teams as teams_c
from mika.kernel.events import Content
from mika.plugins.teams import ANSWERED, WAITING, WRITTEN, TeamsParams
from mika.ports.teams import Draft as TeamsDraft
from mika.ports.teams import conversation_key
from mika.runtime.operations import perform
from mika.vocab.episodes import Kind, task_target
from tests.protocol.test_moi_mail import API, append, journal, login, post, second_person
from tests.protocol.test_teams_web import DM, batch, headers, new_key
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def with_teams(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(2), headers=headers(key)).status_code == 202
    return client, live, key


def first_message(client, live):
    store = live.kernel.ports["teams"]
    return client.portal.call(store.thread, "principal", DM, 10)[-1]


def propose(client, live, body: str = "Oui, 14 h me va.") -> str:
    store = live.kernel.ports["teams"]
    message = first_message(client, live)
    draft = client.portal.call(store.save_draft, TeamsDraft(id="", conversation=DM, body=body, reply_to=message.ref))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="teams.send", owner="teams", summary=Content.of("Répondre à Alice dans Teams"), context="teams",
        args_json=json.dumps({"draft": draft.id, "conversation": DM, "message": message.ref, "mode": "validation"}))])
    return draft.id


def test_her_accounts_conversations_and_threads(world):  # noqa: F811
    client, live, _ = with_teams(world)
    got = client.get(API + "/teams/accounts").json()
    assert got["plugged"] and [a["key"] for a in got["accounts"]] == ["principal"]
    principal = got["accounts"][0]
    assert principal["level"] == "proprietaire" and principal["extension_key"]["hint"].startswith("mtk_")
    assert principal["last_batch"] > 0 and principal["self_name"] == "Adrien"
    conversations = client.get(API + "/teams/conversations").json()["items"]
    assert [c["key"] for c in conversations] == [DM] and conversations[0]["kind"] == "dm"
    assert conversations[0]["last"]["text"] == "On se voit à 14 h ?" and conversations[0]["her"] is None
    thread = client.get(API + f"/teams/thread?conversation={DM}").json()
    assert len(thread["messages"]) == 2 and not thread["more"] and thread["replies"] == []
    assert thread["messages"][-1]["author"] == "Alice" and not thread["messages"][-1]["own"]
    assert client.get(API + "/teams/thread?conversation=19:ailleurs").status_code == 404
    assert client.get(API).json()["counts"]["teams"] == 0


def test_the_list_of_conversations_reads_their_last_messages_in_one_go(world, monkeypatch):  # noqa: F811
    client, live, _ = with_teams(world)
    store = live.kernel.ports["teams"]
    draft = propose(client, live)

    def one_by_one(*args, **kwargs):
        raise AssertionError("une requête par conversation")

    monkeypatch.setattr(store, "thread", one_by_one)
    [item] = client.get(API + "/teams/conversations").json()["items"]
    assert item["last"]["text"] == "On se voit à 14 h ?"  # le dernier message, comme le fil le montrerait
    assert item["her"] == {"state": WAITING, "draft": draft}  # sa réponse en chemin, toujours là


def test_a_person_sees_only_her_own_account(world):  # noqa: F811
    client, live, _ = with_teams(world)
    lea = second_person(client, live)
    config = live.settings.teams()
    client.portal.call(live.settings.save_teams, TeamsConfig(accounts={
        **config.accounts, "lea": TeamsAccount(label="Teams de Léa", owner="personne:" + lea)}))
    client.portal.call(live.kernel.set_params, "teams", TeamsParams(owners={"lea": "personne:" + lea}))
    login(client, "lea")
    assert [a["key"] for a in client.get(API + "/teams/accounts").json()["accounts"]] == ["lea"]
    assert client.get(API + "/teams/conversations").json()["items"] == []
    message = first_message(client, live)
    assert client.get(API + f"/teams/thread?conversation={DM}").status_code == 404
    assert post(client, "/teams/send", {"conversation": DM, "body": "coucou"}).status_code == 404
    assert post(client, "/teams/prefill", {"message": message.ref}).status_code == 404


def test_what_you_write_leaves_by_the_extension_in_your_name(world):  # noqa: F811
    client, live, key = with_teams(world)
    r = post(client, "/teams/send", {"conversation": DM, "body": "J'arrive dans dix minutes."})
    assert r.status_code == 200, r.text
    outbox = client.get("/api/teams/outbox", headers=headers(key)).json()["items"]
    assert len(outbox) == 1 and outbox[0]["mode"] == "send" and outbox[0]["text"] == "J'arrive dans dix minutes."
    pending = client.get(API + f"/teams/thread?conversation={DM}").json()["pending"]
    assert [m["body"] for m in pending] == ["J'arrive dans dix minutes."] and pending[0]["by"] == "user_1"
    store = live.kernel.ports["teams"]
    written = client.portal.call(store.draft, outbox[0]["id"])
    assert written.author == "user_1" and written.final == "J'arrive dans dix minutes."  # sans sa signature
    assert post(client, "/teams/send", {"conversation": DM, "body": "Je te dis [À COMPLÉTER]"}).status_code == 400
    assert post(client, "/teams/send", {"conversation": DM, "body": ""}).status_code == 400


def test_prefill_asks_her_once_and_her_replies_are_decided_here(world):  # noqa: F811
    client, live, _ = with_teams(world)
    message = first_message(client, live)
    asked = post(client, "/teams/prefill", {"message": message.ref, "instruction": "dis oui"})
    assert asked.status_code == 200 and asked.json()["asked"], asked.text
    [ask] = journal(live, teams_c.DRAFT_ASKED)
    assert ask.data.by == "user_1" and ask.data.message == message.ref
    assert post(client, "/teams/prefill", {"message": message.ref}).json()["message"] == "Elle y travaille déjà."

    draft = propose(client, live)
    replies = client.get(API + "/teams/replies").json()["items"]
    assert [d["id"] for d in replies] == [draft] and replies[0]["state"] == "attend"
    assert replies[0]["preview"]["text"].startswith("Oui, 14 h me va.") and replies[0]["conversation"] == DM
    assert client.get(API).json()["counts"]["teams"] == 1
    again = post(client, "/teams/prefill", {"message": message.ref}).json()
    assert again["draft"] == draft  # la saisie reprend la sienne

    edited = post(client, "/teams/reply/edit", {"id": draft, "body": "Oui, 14 h c'est parfait."})
    assert edited.status_code == 200, edited.text
    seen = client.get(API + "/teams/replies").json()["items"][0]["preview"]["digest"]
    sent = post(client, "/teams/reply/send", {"id": draft, "seen": seen})
    assert sent.status_code == 200, sent.text
    assert post(client, "/teams/reply/refuse", {"id": draft}).status_code == 409  # déjà décidée
    assert post(client, "/teams/reply/send", {"id": "inconnu"}).status_code == 404


def test_your_unsent_message_says_so_and_a_read_share_sees_no_replies(world):  # noqa: F811
    client, live, _ = with_teams(world)
    assert post(client, "/teams/send", {"conversation": DM, "body": "Je passe à 15 h."}).status_code == 200
    store = live.kernel.ports["teams"]
    later = live.kernel.mind.clock.now() + 9 * 3600 * 1_000_000  # l'extension ne l'a jamais pris : passé son échéance
    assert client.portal.call(store.expire_written, "principal", later) == 1
    [pending] = client.get(API + f"/teams/thread?conversation={DM}").json()["pending"]
    assert pending["state"] == "inutilise" and pending["body"] == "Je passe à 15 h."  # « pas parti », pas « en file »

    propose(client, live)  # une réponse d'elle qui attend Adrien
    lea = second_person(client, live)
    client.portal.call(live.kernel.set_params, "teams", TeamsParams(shares={"principal": {"personne:" + lea: "lire"}}))
    login(client, "lea")
    [account] = client.get(API + "/teams/accounts").json()["accounts"]
    assert account["level"] == "lire" and account["drafts_waiting"] == 0 and account["extension_key"] is None
    assert client.get(API + "/teams/conversations").json()["items"][0]["her"] is None
    read = client.get(API + f"/teams/thread?conversation={DM}").json()
    assert read["replies"] == [] and read["under_way"] is False and read["asked"] is False  # l'affaire d'Adrien
    assert client.get(API + "/teams/replies").json()["items"] == []
    assert post(client, "/teams/send", {"conversation": DM, "body": "coucou"}).status_code == 403


def test_a_read_share_sees_no_ask_and_an_ask_she_gave_up_is_no_longer_said(world):  # noqa: F811
    client, live, _ = with_teams(world)
    message = first_message(client, live)
    assert post(client, "/teams/prefill", {"message": message.ref}).json()["asked"]
    assert client.get(API + f"/teams/thread?conversation={DM}").json()["asked"] is True  # demandée : elle s'y met
    lea = second_person(client, live)
    client.portal.call(live.kernel.set_params, "teams", TeamsParams(shares={"principal": {"personne:" + lea: "lire"}}))
    login(client, "lea")
    assert client.get(API + f"/teams/thread?conversation={DM}").json()["asked"] is False  # l'affaire d'Adrien
    login(client, "adrien")
    # ses deux essais de rédaction n'ont rien donné : elle y a renoncé, le fil ne dit plus qu'elle s'y met
    append(client, live, [rt.EPISODE_STARTED.draft(kind=Kind.TASK, target=task_target("teams", message.ref))
                          for _ in range(TeamsParams().draft_attempts_max)])
    assert client.get(API + f"/teams/thread?conversation={DM}").json()["asked"] is False
    again = post(client, "/teams/prefill", {"message": message.ref}).json()
    assert again["asked"] and again["message"] != "Elle y travaille déjà."  # « Préremplir » la relance


def test_an_unchecked_account_takes_no_request_and_says_none_is_under_way(world):  # noqa: F811
    client, live, _ = with_teams(world)
    message = first_message(client, live)
    assert post(client, "/teams/prefill", {"message": message.ref}).json()["asked"]  # demandée, compte coché
    client.portal.call(live.kernel.set_params, "teams", TeamsParams(accounts_off=("principal",)))
    # décoché : ses tâches l'écartent, elle ne s'y mettra pas — le fil ne dit pas qu'elle y travaille
    assert client.get(API + f"/teams/thread?conversation={DM}").json()["asked"] is False
    refused = post(client, "/teams/prefill", {"message": message.ref})
    assert refused.status_code == 409 and refused.json()["error"] == "Ce compte Teams est décoché : elle n'y prépare rien."
    console = client.portal.call(lambda: perform(live.kernel, "teams.rediger", form(fixed={"message": message.ref}),
                                                 by="user_1", subject=conversation_key("principal", DM)))
    assert not console.ok and console.message == "Ce compte Teams est décoché : elle n'y prépare rien."
    client.portal.call(live.kernel.set_params, "teams", TeamsParams(enabled=False))
    off = post(client, "/teams/prefill", {"message": message.ref})
    assert off.status_code == 409 and off.json()["error"] == "Teams est désactivé : elle n'y prépare rien."


# ── Le nom d'un tête-à-tête (audit du 2026-11-05, F2-01) ──


def said(conv: str, author: str, author_id: str, text: str, *, n: int, own: bool = False, title: str = "",
         kind: str = "dm", ago_ms: int = 0) -> dict:
    """Un lot de l'extension : un message dans une conversation."""
    now = int(time.time() * 1000)
    return {"self": {"id": "8:orgid:adrien", "name": "Adrien"},
            "conversations": [{"id": conv, "title": title, "kind": kind}],
            "messages": [{"id": f"{1_759_100_000_000 + n}", "conv": conv, "author": author, "author_id": author_id,
                          "time": now - ago_ms, "text": text, "own": own, "mentions_me": False}]}


def test_a_one_to_one_is_named_after_the_other_person_everywhere(world):  # noqa: F811
    client, live, key = with_teams(world)
    other = "19:x7_adrien@unq.gbl.spaces"  # un identifiant qui ne dit pas qui est en face
    group = "19:equipe@thread.v2"
    for batch_ in (said(other, "Bérénice Fontaine", "8:orgid:b", "Tu as vu ?", n=1),
                   said(other, "Adrien", "8:orgid:adrien", "Pas encore.", n=2, own=True),
                   said(group, "Marc", "8:orgid:m", "Point hebdo demain", n=3, title="Point hebdo", kind="group")):
        assert client.post("/api/teams/inbox", json=batch_, headers=headers(key)).status_code == 202
    items = {c["key"]: c for c in client.get(API + "/teams/conversations").json()["items"]}
    # deux tête-à-tête sans titre de Teams : chacun au nom de l'autre personne (jamais le sien, qui a écrit en dernier)
    assert items[DM]["title"] == "Alice" and items[other]["title"] == "Bérénice Fontaine"
    assert items[group]["title"] == "Point hebdo"  # un groupe garde le titre de Teams
    # le même nom dans le fil, que ses réponses portaient déjà
    assert client.get(API + f"/teams/thread?conversation={other}").json()["title"] == "Bérénice Fontaine"
    assert client.get(API + f"/teams/thread?conversation={group}").json()["title"] == "Point hebdo"
    # et la recherche le trouve, casse et accents ignorés
    found = client.get(API + "/teams/conversations?q=berenice").json()["items"]
    assert [c["key"] for c in found] == [other]
    assert [c["key"] for c in client.get(API + "/teams/conversations?q=hebdo").json()["items"]] == [group]
    assert client.get(API + "/teams/conversations?q=personne").json()["items"] == []


def test_an_untitled_group_is_not_named_after_whoever_spoke_last(world):  # noqa: F811
    """Un groupe sans titre de Teams ne prend pas le nom de qui y a parlé en dernier : il en changerait à chaque
    auteur, et se confondrait avec le tête-à-tête de cette personne (relecture du lot L11). Un tête-à-tête dont
    l'extension n'a pas dit la sorte se reconnaît à son identifiant."""
    client, live, key = with_teams(world)
    group = "19:sanstitre@thread.v2"
    other = "19:y8_adrien@unq.gbl.spaces"
    for batch_ in (said(group, "Marc", "8:orgid:m", "On fait le point ?", n=1, kind="group"),
                   said(group, "Bérénice Fontaine", "8:orgid:b", "Oui, demain.", n=2, kind="group"),
                   said(other, "Bérénice Fontaine", "8:orgid:b", "Tu as vu ?", n=3, kind="other")):
        assert client.post("/api/teams/inbox", json=batch_, headers=headers(key)).status_code == 202
    items = {c["key"]: c for c in client.get(API + "/teams/conversations").json()["items"]}
    assert (items[group]["kind"], items[group]["title"]) == ("group", "")  # le client écrit « (sans titre) »
    assert (items[other]["kind"], items[other]["title"]) == ("other", "Bérénice Fontaine")
    assert client.get(API + f"/teams/thread?conversation={group}").json()["title"] == ""
    assert client.get(API + f"/teams/thread?conversation={other}").json()["title"] == "Bérénice Fontaine"
    # la recherche trouve la personne dans son tête-à-tête, pas dans le groupe où elle a parlé en dernier
    assert [c["key"] for c in client.get(API + "/teams/conversations?q=berenice").json()["items"]] == [other]


# ── Répondu autrement (ADR 0199, audit du 2026-11-05 Q16) ──


def until(check, seconds: float = 5.0):
    """Ce que ``check`` rend, dès qu'il est vrai (un processus du serveur y travaille, à côté)."""
    deadline = time.monotonic() + seconds
    while True:
        got = check()
        if got or time.monotonic() > deadline:
            return got
        time.sleep(0.05)


def reply_of(client, draft: str) -> dict:
    return next(r for r in client.get(API + "/teams/replies").json()["items"] if r["id"] == draft)


def test_your_message_refuses_her_reply_waiting_in_the_discussion(world):  # noqa: F811
    client, live, key = with_teams(world)
    draft = propose(client, live)
    seen = reply_of(client, draft)["preview"]["digest"]
    assert client.get(API).json()["counts"]["teams"] == 1
    assert post(client, "/teams/send", {"conversation": DM, "body": "Oui, 14 h."}).status_code == 200
    # aussitôt : sa réponse ne s'approuve plus — sinon elle partirait après la tienne
    late = post(client, "/teams/reply/send", {"id": draft, "seen": seen})
    assert late.status_code == 409, late.text
    refused = until(lambda: reply_of(client, draft)["state"] == "refuse" and reply_of(client, draft))
    assert refused, reply_of(client, draft)
    assert refused["answered"] is True and refused["note"] == ANSWERED  # la carte le dit
    [decision] = journal(live, rt.EFFECT_RESOLVED)
    assert not decision.data.approved and decision.data.by == "user_1"
    assert [w.data.conversation for w in journal(live, WRITTEN)] == [DM]
    thread = client.get(API + f"/teams/thread?conversation={DM}").json()
    assert thread["under_way"] is False and client.get(API).json()["counts"]["teams"] == 0
    # seul ton message part
    assert [i["text"] for i in client.get("/api/teams/outbox", headers=headers(key)).json()["items"]] == ["Oui, 14 h."]
    assert client.portal.call(live.kernel.ports["teams"].draft, draft).state == "abandonne"


def test_a_message_typed_in_teams_after_hers_refuses_her_waiting_reply(world):  # noqa: F811
    client, live, key = with_teams(world)
    draft = propose(client, live)
    # un vieux message d'Adrien, d'avant la question (un rattrapage) : il n'y répond pas
    old = said(DM, "Adrien", "8:orgid:adrien", "Salut !", n=7, own=True, ago_ms=3_600_000)
    assert client.post("/api/teams/inbox", json=old, headers=headers(key)).status_code == 202
    assert not until(lambda: reply_of(client, draft)["answered"], 0.5)
    assert reply_of(client, draft)["state"] == "attend"
    # sa réponse, tapée dans Teams après la question : elle revient dans le fil, la sienne ne partira pas
    now = said(DM, "Adrien", "8:orgid:adrien", "Oui, 14 h.", n=8, own=True)
    assert client.post("/api/teams/inbox", json=now, headers=headers(key)).status_code == 202
    assert until(lambda: reply_of(client, draft)["state"] == "refuse"), reply_of(client, draft)
    got = reply_of(client, draft)
    assert got["answered"] is True and got["note"] == ANSWERED


def test_a_refusal_note_is_read_by_the_owner_not_through_a_share(world):  # noqa: F811
    """La note de qui a refusé est gardée à part (l'oubli l'atteint) : « Ses brouillons » la relit pour le propriétaire
    du compte ; ce qu'il a dit à Mika ne se lit pas par un partage, qui voit seulement qu'elle est refusée."""
    client, live, _ = with_teams(world)
    draft = propose(client, live)
    assert post(client, "/teams/reply/refuse", {"id": draft, "note": "trop sec"}).status_code == 200
    mine = reply_of(client, draft)
    assert mine["state"] == "refuse" and mine["note"] == "trop sec" and mine["answered"] is False
    lea = second_person(client, live)
    client.portal.call(live.kernel.set_params, "teams",
                       TeamsParams(shares={"principal": {"personne:" + lea: "preparer"}}))
    login(client, "lea")
    shared_ = reply_of(client, draft)
    assert shared_["state"] == "refuse" and shared_["note"] == ""
