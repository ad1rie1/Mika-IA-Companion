"""Un Teams par personne (ADR 0186), par ses intentions.

- un compte sert à son propriétaire (comme une boîte, ADR 0185) : les tiens — toi en privé, elle quand elle
  travaille ; les siens — elle seule, au travail ; celui d'une personne — avec elle, reconnue, en tête-à-tête ; une
  tâche voit le compte de son message ;
- ses outils Teams sont offerts à qui a un compte à son nom, réduits à ses comptes : ni tes conversations, ni tes
  messages, ni tes brouillons ;
- le stockage range chaque ligne sous son compte : deux personnes d'un même groupe ont chacune sa conversation et ses
  références ; la file et un accusé ne concernent que le compte de la clé ;
- elle remarque les messages de tous les comptes, ne prépare d'elle-même que dans les tiens ; demandée, une réponse
  dans le compte d'une personne s'écrit à sa place et part de son compte, par son extension seule ;
- une configuration d'avant (un seul Teams) devient le compte « principal », à toi ; un compte est à toi, à elle ou
  à une personne — rien d'autre ;
- une base d'avant (un seul Teams) passe à la dernière révision sans rien perdre : tout au compte « principal », les
  références inchangées ; deux comptes peuvent alors tenir la même conversation (SQLite, et MariaDB sous
  ``--mariadb``).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from alembic import command
from pydantic import ValidationError

from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.app import schema
from mika.app.teams import digest
from mika.contracts import teams as teams_c
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.plugins.teams import TEAMS, TeamsParams, accounts_here, owns_an_account
from mika.plugins.teams.accounts import Accounts
from mika.plugins.teams.tools import ListArgs, _port, teams_conversations
from mika.ports.teams import (
    ACCEPTED,
    DEFAULT_ACCOUNT,
    MISSING,
    Draft,
    InboxBatch,
    InboxConversation,
    InboxMessage,
    Message,
    conversation_key,
    message_ref,
    split_conversation_key,
)
from mika.runtime.operations import perform
from mika.vocab.episodes import Kind, task_target
from mika.vocab.privacy import ChannelTrust
from tests.fixtures import backend
from tests.fixtures.mika import connect
from tests.unit.test_teams import DM, KEY, QUESTION, Model, conv, events, msg, prompt_text, push, sleep
from tests.unit.test_teams import live as live_teams

PRINCIPAL = DEFAULT_ACCOUNT
OWNERS = {"elle_t": "elle", "nadia_t": "personne:user_2"}
ACCOUNTS = (PRINCIPAL, "elle_t", "nadia_t")
YOU = Audience(persons=("user_1",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value, owner=True,
               person="user_1")
NADIA = Audience(persons=("user_2",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                 owner=False, person="user_2")
ROOM = Audience(persons=("user_1", "user_2"), channel="web", public=True, trust=ChannelTrust.AUTHENTICATED.value,
                owner=True, person="user_1")
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
GROUP = "19:projet@thread.v2"
NOW = 1_790_000_000_000_000


def frame(audience: Audience, kind: str = Kind.REPLY, target: str = "user_1", owners=OWNERS) -> Frame:
    env = NS(params_of=lambda owner, root: TeamsParams(owners=owners), tools={}, access_tables=None, closeness=None,
             tz_of=lambda root: ZoneInfo("Europe/Paris"))
    return Frame(None, NOW, env, audience, EpisodeRef("e", kind, target=target))


def test_an_account_serves_its_owner():
    assert accounts_here(frame(YOU), ACCOUNTS) == (PRINCIPAL,)  # toi : les tiens, pas les siens, pas celui de Nadia
    assert accounts_here(frame(NADIA), ACCOUNTS) == ("nadia_t",)  # Nadia, reconnue en privé : le sien seulement
    working = frame(WORKING, Kind.STEP, "goal:1")
    assert accounts_here(working, ACCOUNTS) == (PRINCIPAL, "elle_t")  # elle seule : les tiens, les siens
    assert accounts_here(frame(ROOM), ACCOUNTS) == ()  # à plusieurs : aucun
    # une tâche de rédaction : le compte de son message, même celui de Nadia (on la lui a demandée)
    ref = message_ref(GROUP, "1", "nadia_t")
    port = NS(message=lambda r: Message(r, GROUP, "Bob", "8:b", 1, "?", account="nadia_t") if r == ref else None)
    task = frame(WORKING, Kind.TASK, task_target("teams", ref))
    assert "nadia_t" in accounts_here(task, ACCOUNTS, port)
    assert "nadia_t" not in accounts_here(task, ACCOUNTS)  # sans dire où est son message : pas son compte
    # sans propriétaire nommé, tout est à toi : rien ne change d'avant
    assert accounts_here(frame(YOU, owners={}), ACCOUNTS) == ACCOUNTS


def test_her_tools_are_offered_to_whoever_owns_an_account():
    assert owns_an_account(NADIA, Kind.REPLY, frame(NADIA))
    assert not owns_an_account(NADIA, Kind.REPLY, frame(NADIA, owners={"elle_t": "elle"}))  # rien à elle
    assert not owns_an_account(YOU, Kind.REPLY, frame(YOU))  # toi : ta famille d'outils décide, comme avant
    assert not owns_an_account(ROOM, Kind.REPLY, frame(ROOM))  # jamais à plusieurs
    assert not owns_an_account(NADIA, Kind.REPLY, None)  # une console qui juge sans ce qu'elle vit : personne
    reserved = [t for t in TEAMS.tools if t.owner_only]
    from mika.plugins.teams import owns_an_account_to_prepare
    wanted = {"teams_draft": owns_an_account_to_prepare}  # préparer une réponse (ADR 0188) ; sinon lire
    assert reserved and all(t.owned is wanted.get(t.name, owns_an_account) for t in reserved)


def _config() -> TeamsConfig:
    return TeamsConfig(accounts={PRINCIPAL: {"display_name": "Adrien"},
                                 "nadia_t": {"owner": "personne:user_2", "display_name": "Nadia", "sign": True}})


def _batch(*messages: InboxMessage, title: str = "Projet") -> InboxBatch:
    return InboxBatch("8:orgid:moi", "Moi", (InboxConversation(GROUP, title, "group"),), messages)


def _question(n: str, *, own: bool = False, text: str = "On avance ?") -> InboxMessage:
    return InboxMessage(n, GROUP, "Moi" if own else "Bob", "8:moi" if own else "8:b", NOW // 1000 + int(n), text,
                        own=own)


def test_the_store_keeps_each_account_apart(tmp_path):
    store = TeamsStore(_config, tmp_path / "teams.db", now=lambda: NOW)
    try:
        # le même groupe, le même message, vu par deux personnes : deux conversations, deux références
        assert store.store_batch(PRINCIPAL, _batch(_question("1")), NOW).new == 1
        assert store.store_batch("nadia_t", _batch(_question("1"), title="Projet (Nadia)"), NOW).new == 1
        mine, hers = message_ref(GROUP, "1"), message_ref(GROUP, "1", "nadia_t")
        assert mine != hers and store.message(mine).account == PRINCIPAL and store.message(hers).account == "nadia_t"
        assert store.title(PRINCIPAL, GROUP) == "Projet" and store.title("nadia_t", GROUP) == "Projet (Nadia)"
        assert sorted(c.account for c in store.conversations(10)) == ["nadia_t", PRINCIPAL]
        assert [c.account for c in store.conversations(10, accounts=["nadia_t"])] == ["nadia_t"]
        assert [m.ref for m in store.thread("nadia_t", GROUP, 10)] == [hers]
        assert {a.key: a.last_batch for a in store.accounts()} == {PRINCIPAL: NOW, "nadia_t": NOW}
        assert store.voice("nadia_t").display_name == "Nadia" and store.voice("nadia_t").signature
        assert not store.voice(PRINCIPAL).signature
        # sa réponse part de son compte : la file de l'autre ne la voit pas, son extension seule l'accuse
        d = store.save_draft(Draft(id="", conversation=GROUP, body="Oui.", reply_to=hers, account="nadia_t"))
        shown = store.preview(d.id, her="Mika")
        assert "Mika" in shown.text and shown.title == "Projet (Nadia)"  # sa signature à elle, son titre à elle
        assert store.enqueue(d.id, mode="draft", digest=shown.digest, expires_at=NOW + HOUR, now=NOW, her="Mika") == ""
        assert store.outbox(PRINCIPAL, NOW) == [] and [i.id for i in store.outbox("nadia_t", NOW)] == [d.id]
        assert store.settle(d.id, "placed", now=NOW, account=PRINCIPAL) == (MISSING, None)
        assert store.settle(d.id, "placed", now=NOW, account="nadia_t")[0] == ACCEPTED
        # ce que la personne d'un compte écrit ne règle que les brouillons de son compte
        settled = store.store_batch(PRINCIPAL, _batch(_question("2", own=True, text="Oui.")), NOW + 1).settled
        assert settled == () and store.draft(d.id).state == "pose"
        assert [s.draft for s in store.store_batch("nadia_t", _batch(_question("2", own=True, text="Oui.")),
                                                   NOW + 1).settled] == [d.id]
        # oublier quelqu'un l'oublie dans tous les comptes
        asyncio.run(store.forget("teams:8:b"))
        assert store.message(mine) is None and store.message(hers) is None
        # un compte supprimé des réglages : tout ce que son extension avait apporté s'efface, rien chez l'autre
        store.store_batch("nadia_t", _batch(_question("3")), NOW + 2)
        assert store.drop_account("nadia_t") > 0
        assert store.conversations(10, accounts=["nadia_t"]) == [] and store.draft(d.id) is None
        assert store.conversations(10, accounts=[PRINCIPAL])
    finally:
        store.close()


def test_her_tools_see_only_the_accounts_of_whoever_is_there(tmp_path):
    store = TeamsStore(_config, tmp_path / "teams.db", now=lambda: NOW)
    try:
        store.store_batch(PRINCIPAL, _batch(_question("1"), title="Le tien"), NOW)
        store.store_batch("nadia_t", _batch(_question("1"), title="Le sien"), NOW)
        view = Accounts(store, ("nadia_t",))
        assert [a.key for a in view.accounts()] == ["nadia_t"] and view.account(PRINCIPAL) is None
        assert [c.account for c in view.conversations(10)] == ["nadia_t"]
        assert [c.account for c in view.conversations(10, accounts=[PRINCIPAL])] == []  # ni en le demandant
        assert view.message(message_ref(GROUP, "1")) is None  # nommer un message d'un autre compte ne l'ouvre pas
        assert view.thread(PRINCIPAL, GROUP, 10) == [] and view.title(PRINCIPAL, GROUP) == ""
        with pytest.raises(ValueError):
            view.save_draft(Draft(id="", conversation=GROUP, body="x", account=PRINCIPAL))
        # par l'outil : Nadia ne voit que son Teams ; personne en salon
        said = asyncio.run(teams_conversations(ListArgs(), NS(ports={"teams": store}, frame=frame(NADIA))))
        assert "Le sien" in said and "Le tien" not in said
        port, refused = _port(NS(ports={"teams": store}, frame=frame(ROOM)))
        assert port is None and refused is not None and not refused.ok
    finally:
        store.close()


def test_a_teams_config_of_before_becomes_the_principal_account():
    before = TeamsConfig.model_validate({"enabled": True, "display_name": "Adrien", "tone": "bref", "sign": True})
    assert set(before.accounts) == {PRINCIPAL}
    assert before.accounts[PRINCIPAL] == TeamsAccount(display_name="Adrien", tone="bref", sign=True)
    assert set(TeamsConfig().accounts) == {PRINCIPAL}  # une installation neuve a son Teams, comme avant
    assert TeamsConfig().voice("retire", "Teams").display_name == "Teams"  # un compte retiré : sans voix réglée
    assert TeamsAccount(owner="elle").owner == "elle" and TeamsAccount(owner=" personne:user_2 ").owner == \
        "personne:user_2"
    for bad in ("nadia", "personne:", "tous"):
        with pytest.raises(ValidationError):
            TeamsAccount(owner=bad)
    with pytest.raises(ValidationError):
        TeamsConfig(accounts={"Pas Une Clé": {}})


def test_a_conversation_key_keeps_the_links_of_before():
    assert conversation_key(PRINCIPAL, DM) == DM and split_conversation_key(DM) == (PRINCIPAL, DM)
    key = conversation_key("nadia_t", GROUP)
    assert key == f"nadia_t~{GROUP}" and split_conversation_key(key) == ("nadia_t", GROUP)


# ── Elle remarque tout, ne prépare d'elle-même que chez toi ; demandée, elle écrit depuis le compte ──


NADIA_DM = "19:bob_nadia@unq.gbl.spaces"
KEY2 = "mtk_cle-de-nadia"


def test_a_persons_account_is_noticed_drafted_only_when_asked_and_leaves_from_it(tmp_path):
    cfg = TeamsConfig(accounts={PRINCIPAL: {"display_name": "Adrien"},
                                "nadia_t": {"owner": "personne:user_2", "display_name": "Nadia"}})

    async def scenario(kernel, llm, desk, store, clock):
        desk.settings.keys["nadia_t"] = {"digest": digest(KEY2), "hint": KEY2[:8], "created_at": 0, "by": "test"}
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        got = await desk.inbox(KEY2, {"self": {"id": "8:orgid:nadia", "name": "Nadia"},
                                      "conversations": [conv(NADIA_DM)],
                                      "messages": [msg(clock, 1, QUESTION, conv=NADIA_DM, author="Bob",
                                                       author_id="8:orgid:bob")]})
        assert got.outcome == "accepted"
        await sleep(HOUR)
        out = {"noticed": events(kernel, teams_c.NOTICED),
               "auto": [c for c in llm.calls if c.role == "step"],
               "before": (store.outbox(PRINCIPAL, clock.now()), store.outbox("nadia_t", clock.now()))}
        theirs = message_ref(NADIA_DM, "1759000000001", "nadia_t")
        out["asked"] = await perform(kernel, "teams.rediger", {"_champs": ["instruction"], "instruction": [""],
                                                               "_fixes": ["message"], "message": [theirs]},
                                     by="user_1", subject=conversation_key("nadia_t", NADIA_DM), nonce="n1")
        await sleep(30 * MINUTE)
        out["task"] = [c for c in llm.calls if c.role == "step" and theirs in prompt_text(c)]
        out["gate"] = ((await desk.outbox(KEY)).data["items"], (await desk.outbox(KEY2)).data["items"])
        out["theirs"] = theirs
        return out

    out = live_teams(tmp_path, Model(), scenario, cfg=cfg,
                     inputs={"owners": {PRINCIPAL: "", "nadia_t": "personne:user_2"}})
    by_account = {e.data.account: e.data for e in out["noticed"]}
    assert set(by_account) == {PRINCIPAL, "nadia_t"}  # elle remarque les messages de tous les comptes
    assert by_account["nadia_t"].needs_reply
    # d'elle-même, une réponse dans ton compte seulement
    assert not any(out["theirs"] in prompt_text(c) for c in out["auto"])
    mine, hers = out["before"]
    assert len(mine) == 1 and hers == []
    # demandée : écrite à la place de Nadia (sa voix), partie de son compte, relevée par son extension seule
    assert out["asked"].ok and out["task"] and "à la place** de Nadia" in prompt_text(out["task"][0])
    gate_mine, gate_hers = out["gate"]
    assert [i["conversation"] for i in gate_mine] == [DM] and [i["conversation"] for i in gate_hers] == [NADIA_DM]


# ── Une base d'avant ──────────────────────────────────────────────────────


def _old_base(target) -> None:
    """Une base ``teams`` telle que l'ADR 0101 l'avait laissée (un seul Teams), avec ce qu'une extension y avait
    poussé."""
    target.ensure()
    engine = target.engine()
    cfg = schema._config("teams")
    try:
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "f7de680acc8b")
            conn.commit()
        meta = sa.table("meta", sa.column("name"), sa.column("value"))
        convs = sa.table("conversations", *(sa.column(c) for c in ("id", "title", "kind", "last_at", "title_fold",
                                                                   "id_fold")))
        msgs = sa.table("messages", *(sa.column(c) for c in (
            "ref", "conversation", "external_id", "author", "author_id", "author_key", "at", "text", "own",
            "mentions_me", "received", "acked")))
        drafts = sa.table("drafts", *(sa.column(c) for c in (
            "draft_id", "conversation", "body", "reply_to", "author", "created", "updated", "state", "mode", "digest",
            "final", "expires_at", "placed_at", "sent_at", "sent_text", "edited", "edited_by", "reason")))
        with engine.begin() as conn:
            conn.execute(sa.insert(meta), [{"name": "last_batch", "value": "123"},
                                           {"name": "self_id", "value": "8:orgid:adrien"},
                                           {"name": "self_name", "value": "Adrien"}])
            conn.execute(sa.insert(convs).values(id=GROUP, title="Projet", kind="group", last_at=5, title_fold="projet",
                                                 id_fold=GROUP))
            conn.execute(sa.insert(msgs).values(ref=message_ref(GROUP, "1"), conversation=GROUP, external_id="1",
                                                author="Bob", author_id="8:b", author_key="8:b", at=5, text="On avance ?",
                                                own=False, mentions_me=False, received=5, acked=True))
            conn.execute(sa.insert(drafts).values(
                draft_id="t000000000001", conversation=GROUP, body="Oui.", reply_to=message_ref(GROUP, "1"),
                author="", created=1, updated=1, state="brouillon", mode="", digest="", final="", expires_at=0,
                placed_at=0, sent_at=0, sent_text="", edited=False, edited_by="", reason=""))
    finally:
        engine.dispose()


def test_a_base_from_before_is_taken_over_without_loss(tmp_path):
    target = backend.target(tmp_path, "teams")
    _old_base(target)
    schema.migrate_data(tmp_path, {"teams": target})
    schema.migrate_data(tmp_path, {"teams": target})  # deux fois : rien ne change
    engine = target.engine()
    try:
        assert schema.differences("teams", engine) == []
        assert sa.inspect(engine).get_pk_constraint("conversations")["constrained_columns"] == ["account", "id"]
    finally:
        engine.dispose()
    store = TeamsStore(_config, target, now=lambda: NOW)
    try:
        # ce que l'extension avait dit, ses conversations, ses messages, ses brouillons : au compte d'avant
        assert store.last_batch(PRINCIPAL) == 123 and store.owner(PRINCIPAL) == ("8:orgid:adrien", "Adrien")
        assert store.configured(PRINCIPAL) and not store.configured("nadia_t")
        assert store.conversation(PRINCIPAL, GROUP).title == "Projet"
        ref = message_ref(GROUP, "1")
        assert store.message(ref).account == PRINCIPAL and store.draft("t000000000001").account == PRINCIPAL
        # sa référence n'a pas changé : le même message, poussé de nouveau, est reconnu
        again = store.store_batch(PRINCIPAL, _batch(InboxMessage("1", GROUP, "Bob", "8:b", 5, "On avance ?")), NOW)
        assert (again.new, again.known) == (0, 1)
        # et un autre compte peut maintenant tenir la même conversation
        assert store.store_batch("nadia_t", _batch(_question("1")), NOW).new == 1
        assert {c.account for c in store.conversations(10)} == {PRINCIPAL, "nadia_t"}
    finally:
        store.close()
