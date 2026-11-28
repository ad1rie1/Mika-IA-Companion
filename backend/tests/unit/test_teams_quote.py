"""Les citations Teams (ADR 0305) : celle d'un envoi, dans la boîte d'envoi de l'extension ; celle d'un message reçu,
gardée avec lui, rendue à l'écran et lue par Mika.

- dans un groupe, un envoi qui répond à un message le cite toujours ;
- dans un tête-à-tête, seulement si d'autres messages y sont arrivés après lui : sinon elle répond au dernier, et la
  citation ne dirait rien — sauf quand la personne l'a citée elle-même (un brouillon qu'elle a écrit) : comme dans
  Teams, toujours ;
- seulement un message qui a son identifiant de service (l'heure de son arrivée, le seul que Teams sache citer) et un
  auteur reconnaissable ; l'extrait est court, sur une ligne.
"""

from __future__ import annotations

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.app.domains.teams.desk import TeamsDesk, batch_of
from mika.plugins.teams.reactions import quote_said
from mika.ports.teams import DEFAULT_ACCOUNT as PRINCIPAL
from mika.ports.teams import QUOTE_PREVIEW_MAX, Draft, Quote, message_ref
from mika.vocab.phrasebook import phrase

NOW = 1_795_384_000_000_000  # µs
ME = "8:orgid:3e51ce13-6eb8-463b-a75a-a40b2ab67602"
GILLES = "8:orgid:de50c847-308e-4100-a076-6163609ba794"
DM = "19:3e51ce13-6eb8-463b-a75a-a40b2ab67602_de50c847-308e-4100-a076-6163609ba794@unq.gbl.spaces"
GROUP = "19:9f3c0b6e1d2a4c5b8e7f6a5b4c3d2e1f@thread.v2"


def _store(tmp_path) -> TeamsStore:
    return TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=lambda: NOW)


def _lot(conv: str, kind: str, *messages: tuple[str, str, str, int, str]) -> dict:
    return {"self": {"id": ME, "name": "Adrien"}, "conversations": [{"id": conv, "title": "Projet", "kind": kind}],
            "messages": [{"id": mid, "conv": conv, "author": author, "author_id": author_id, "time": at, "text": text}
                         for mid, author, author_id, at, text in messages]}


def _queued(store: TeamsStore, conv: str, reply_to: str, author: str = "") -> str:
    d = store.save_draft(Draft(id="", conversation=conv, body="Oui, je regarde.", reply_to=reply_to, author=author))
    shown = store.preview(d.id, her="Mika")
    assert store.enqueue(d.id, mode="send", digest=shown.digest, expires_at=0, now=NOW, her="Mika") == ""
    return d.id


def _quote(store: TeamsStore, draft: str) -> Quote | None:
    (item,) = [i for i in store.outbox(PRINCIPAL, NOW) if i.id == draft]
    return item.quote


def test_in_a_group_the_message_she_answers_is_quoted(tmp_path):
    store = _store(tmp_path)
    try:
        t = NOW // 1000 - 60_000
        long_text = "Tu as vu le devis ?\n" + "x" * 300
        store.store_batch(PRINCIPAL, batch_of(_lot(GROUP, "group", (str(t), "Gilles", GILLES, t, long_text)),
                                              NOW // 1000)[0], NOW)
        draft = _queued(store, GROUP, message_ref(GROUP, str(t)))
        quote = _quote(store, draft)
        assert quote == Quote(str(t), GILLES, "Gilles", t, ("Tu as vu le devis ? " + "x" * 300)[:QUOTE_PREVIEW_MAX])
        assert "\n" not in quote.preview
        # ce que l'extension relève (`GET /api/teams/outbox`, la connexion en direct)
        (item,) = TeamsDesk(None, lambda: NOW, store)._items(PRINCIPAL)
        assert item["quote"] == {"message": str(t), "author_id": GILLES, "author": "Gilles", "at": t,
                                 "preview": quote.preview}
    finally:
        store.close()


def test_in_a_dm_only_when_other_messages_came_after(tmp_path):
    store = _store(tmp_path)
    try:
        t = NOW // 1000 - 60_000
        store.store_batch(PRINCIPAL, batch_of(_lot(DM, "dm", (str(t), "Gilles", GILLES, t, "Tu viens demain ?")),
                                              NOW // 1000)[0], NOW)
        draft = _queued(store, DM, message_ref(DM, str(t)))
        assert _quote(store, draft) is None, "elle répond au dernier message : la citation ne dirait rien"
        store.store_batch(PRINCIPAL, batch_of(_lot(DM, "dm", (str(t + 5000), "Gilles", GILLES, t + 5000,
                                                              "Et pour vendredi ?")), NOW // 1000)[0], NOW)
        assert _quote(store, draft).message == str(t), "un autre message a suivi : elle cite celui auquel elle répond"
    finally:
        store.close()


def test_no_quote_without_the_service_id_teams_can_quote(tmp_path):
    store = _store(tmp_path)
    try:
        t = NOW // 1000 - 60_000
        client_id = "4123456789012345678"  # l'identifiant que le client donne tant qu'il attend (19 chiffres)
        store.store_batch(PRINCIPAL, batch_of(_lot(GROUP, "group", (client_id, "Gilles", GILLES, t, "Tu viens ?")),
                                              NOW // 1000)[0], NOW)
        draft = _queued(store, GROUP, message_ref(GROUP, client_id))
        assert _quote(store, draft) is None
        # un envoi qui ne répond à rien ne cite rien
        lone = store.save_draft(Draft(id="", conversation=GROUP, body="Bonjour à tous."))
        shown = store.preview(lone.id, her="Mika")
        store.enqueue(lone.id, mode="send", digest=shown.digest, expires_at=0, now=NOW, her="Mika")
        assert _quote(store, lone.id) is None
    finally:
        store.close()


def test_in_a_dm_the_person_quoting_herself_always_quotes(tmp_path):
    """Dans Teams, « Citer » cite toujours : un brouillon que la personne a écrit en citant part avec sa citation, même
    en réponse au dernier message d'un tête-à-tête."""
    store = _store(tmp_path)
    try:
        t = NOW // 1000 - 60_000
        store.store_batch(PRINCIPAL, batch_of(_lot(DM, "dm", (str(t), "Gilles", GILLES, t, "Tu viens demain ?")),
                                              NOW // 1000)[0], NOW)
        draft = _queued(store, DM, message_ref(DM, str(t)), author="personne:user_1")
        assert _quote(store, draft).message == str(t)
    finally:
        store.close()


def test_a_received_quote_is_kept_apart_from_the_text_and_points_to_the_quoted_message(tmp_path):
    store = _store(tmp_path)
    try:
        t = NOW // 1000 - 120_000
        quoted = {"message": str(t), "author_id": GILLES, "author": "Gilles", "at": t, "preview": "Tu as vu le devis ?"}
        lot = _lot(GROUP, "group", (str(t), "Gilles", GILLES, t, "Tu as vu le devis ?"),
                   (str(t + 60_000), "Adrien", ME, t + 60_000, "Oui, ce matin."))
        lot["messages"][1]["quote"] = quoted
        lot["messages"].append({"id": str(t + 90_000), "conv": GROUP, "author": "Sophie", "author_id": "8:orgid:s",
                                "time": t + 90_000, "text": "Et moi ?",
                                "quote": {"message": "abc", "author_id": GILLES}})  # illisible : ignorée, pas le message
        store.store_batch(PRINCIPAL, batch_of(lot, NOW // 1000)[0], NOW)
        thread = {m.text: m for m in store.thread(PRINCIPAL, GROUP, 10)}
        answer = thread["Oui, ce matin."]
        assert answer.quote == Quote(str(t), GILLES, "Gilles", t, "Tu as vu le devis ?", ref=message_ref(GROUP, str(t)))
        assert thread["Et moi ?"].quote is None and thread["Tu as vu le devis ?"].quote is None
        # ce que Mika en lit, devant son texte
        assert quote_said(answer.quote) == phrase("teams.quote", who="Gilles", text="Tu as vu le devis ?")
        # un message cité qu'elle n'a pas : la citation reste, sans référence
        lot2 = _lot(GROUP, "group", (str(t + 100_000), "Adrien", ME, t + 100_000, "Toujours d'accord."))
        lot2["messages"][0]["quote"] = {**quoted, "message": "1700000000000"}
        store.store_batch(PRINCIPAL, batch_of(lot2, NOW // 1000)[0], NOW)
        later = {m.text: m for m in store.thread(PRINCIPAL, GROUP, 10)}["Toujours d'accord."]
        assert later.quote.message == "1700000000000" and later.quote.ref == ""
    finally:
        store.close()
