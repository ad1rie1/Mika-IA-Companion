"""Un service dit avec qui, ce qu'elle fait seule, et ce qu'elle en garde (ADR 0128) — par leurs intentions.

- une fiche d'avant l'ADR (« pour qui », « devient un savoir », l'accord d'un outil) reste lisible, sous la forme
  neuve ; une règle d'outil inconnue est refusée ;
- avec qui : sa propriétaire, toute personne qui a un compte, des personnes nommées et authentifiées — jamais un
  salon ni une inconnue ; une règle par personne passe avant sa situation, et aucune règle ne laisse personne de
  plus que le service ; quand elle travaille seule, seulement un service « avec toi » ;
- l'accord se décide à l'appel : seule, l'appel part et rend ce qu'il vaut (``floor``, ``unkept``) ; ``carte``, une
  carte à la personne en face ; ``toi``, une carte à sa propriétaire quand c'est elle en face, sinon l'opérateur ;
- ce que vaut ce qu'un outil a rendu remonte la boucle jusqu'à l'énoncé, et la trace n'en garde rien à « rien » ;
- la mémoire le respecte : « rien » ne s'indexe pas et ne se relit pas (ni la réplique, ni la demande qu'elle
  suivait) ; une confidence de service fait de ce qu'on en tire un secret, la nuit aussi ;
- qui peut quoi (ADR 0129) : la console applique la règle du moteur à des personnes types, et dit où un outil
  s'écarte de son service — jamais une recopie de la règle.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel, ValidationError

from mika.adapters.mcp.config import McpServer, StoredReview
from mika.adapters.mcp.hub import autonomy_of
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts.transcript import thread_table
from mika.faculties.memory.consolidation import Consolidate, floored
from mika.faculties.memory.extraction import Conversation, Line, Speaker, render
from mika.faculties.memory.night import _disclosure
from mika.faculties.memory.projections import Chunks
from mika.faculties.transcript import Thread
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult, ToolSpec
from mika.kernel.frame import Audience
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.mcp import ExternalArgs, _handler, level_of, situation
from mika.plugins.mcp.console import drift, faces, looser_tools, rules_of, said_level
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.tools import run_tool_loop
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust, Sensitivity
from tests.fixtures.mika import boot, build, connect, said
from tests.fixtures.sqldb import SqlDB
from tests.unit.test_knowledge_coherence import FRAME
from tests.unit.test_mcp_plugin import NAME, FakePort, offered_tool

URL = "https://meteo.example/mcp"
CONFIDENCE = int(Sensitivity.CONFIDENCE)
UNKEPT = phrase("memory.extraction.render.unkept")

OWNER = Audience(persons=("user_1",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                 owner=True, person="user_1")
ACCOUNT = Audience(persons=("user_2",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                   person="user_2")
NAMED = Audience(persons=("user_3",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                 person="user_3")
#: la même personne nommée, sur un canal où rien ne prouve que c'est elle
NAMED_UNPROVEN = Audience(persons=("ext_3",), channel="external", public=False, trust=ChannelTrust.ACCOUNT.value,
                          person="user_3")
STRANGER = Audience(persons=("web_x",), channel="web", public=False, trust=ChannelTrust.ACCOUNT.value,
                    person="web_x")
ROOM = Audience(persons=("user_2",), channel="web", room="salon", public=True,
                trust=ChannelTrust.AUTHENTICATED.value, person="user_2")
WORK = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
EVERYONE = {"owner": OWNER, "account": ACCOUNT, "named": NAMED, "unproven": NAMED_UNPROVEN, "stranger": STRANGER,
            "room": ROOM, "work": WORK, "none": None}


def levels(tool) -> dict[str, str]:
    return {who: level_of(tool, aud) for who, aud in EVERYONE.items()}


# ── les fiches d'avant ──────────────────────────────────────────────────────


def test_a_server_saved_before_0128_keeps_who_it_served_and_what_became_knowledge():
    shared = McpServer.model_validate({"purpose": "la météo", "url": URL, "audience": "comptes", "learns": True})
    assert (shared.with_owner, shared.with_accounts, shared.keep) == (True, True, "public")
    mine = McpServer.model_validate({"purpose": "la météo", "url": URL, "audience": "proprietaire", "learns": False})
    assert (mine.with_owner, mine.with_accounts, mine.keep, mine.autonomy) == (True, False, "prive", "carte")
    # ce qui est écrit sous la forme neuve l'emporte ; la forme ancienne ne se réécrit jamais
    both = McpServer.model_validate({"purpose": "la météo", "url": URL, "audience": "comptes", "learns": True,
                                     "with_accounts": False, "keep": "rien"})
    assert (both.with_accounts, both.keep) == (False, "rien")
    assert not {"audience", "learns"} & set(shared.model_dump())
    with pytest.raises(ValidationError):  # une clé inconnue reste refusée
        McpServer.model_validate({"purpose": "la météo", "url": URL, "pour": "comptes"})


def test_a_review_saved_before_0128_keeps_its_approval_and_bad_rules_are_refused():
    for old, new in (("aucun", "seule"), ("conversation", "service"), ("operateur", "toi"), ("inconnu", "service")):
        assert StoredReview.model_validate({"fingerprint": "f", "approval": old}).autonomy == new
    assert StoredReview.model_validate({"fingerprint": "f", "approval": "aucun", "autonomy": "toi"}).autonomy == "toi"
    ok = StoredReview(fingerprint="f", situations={"proprietaire": "seule", "compte": "non", "travail": "toi"},
                      people={"user_3": "carte"})
    assert ok.situations["compte"] == "non" and ok.people == {"user_3": "carte"}
    for bad in ({"situations": {"salon": "seule"}}, {"situations": {"compte": "toujours"}},
                {"people": {"user_3": "jamais"}}, {"people": {"": "seule"}}, {"autonomy": "lit"}):
        with pytest.raises(ValidationError):
            StoredReview.model_validate({"fingerprint": "f", **bad})


def test_a_tool_follows_its_service_unless_it_has_its_own_approval():
    reading, acting = StoredReview(fingerprint="f", nature="lecture"), StoredReview(fingerprint="f", nature="action")
    reads = McpServer(purpose="la météo", url=URL, autonomy="lit")
    assert (autonomy_of(reads, reading), autonomy_of(reads, acting)) == ("seule", "carte")
    for mode in ("seule", "carte", "toi"):
        assert autonomy_of(McpServer(purpose="la météo", url=URL, autonomy=mode), acting) == mode
    assert autonomy_of(reads, StoredReview(fingerprint="f", nature="lecture", autonomy="toi")) == "toi"


# ── avec qui ────────────────────────────────────────────────────────────────


def test_where_she_would_use_a_service():
    assert {who: situation(aud) for who, aud in EVERYONE.items()} == {
        "owner": "proprietaire", "account": "compte", "named": "compte", "unproven": None, "stranger": None,
        "room": None, "work": "travail", "none": None}
    owner_in_room = Audience(persons=("user_1",), room="salon", public=True, trust=ChannelTrust.AUTHENTICATED.value,
                             owner=True, person="user_1")
    assert situation(owner_in_room) is None  # même sa propriétaire, jamais dans un salon


def test_with_her_owner_only_by_default():
    assert levels(offered_tool()) == {"owner": "seule", "account": "non", "named": "non", "unproven": "non",
                                      "stranger": "non", "room": "non", "work": "seule", "none": "non"}


def test_with_every_account_never_a_room_nor_a_stranger():
    tool = offered_tool(autonomy="carte", with_accounts=True)
    assert levels(tool) == {"owner": "carte", "account": "carte", "named": "carte", "unproven": "non",
                            "stranger": "non", "room": "non", "work": "carte", "none": "non"}


def test_a_named_person_is_served_only_authenticated_and_her_rule_beats_her_situation():
    tool = offered_tool(autonomy="toi", with_owner=False, with_people=("user_3",),
                        situations=(("compte", "non"),), people=(("user_3", "seule"),))
    # pas avec sa propriétaire, ni quand elle travaille seule : le service n'est pas « avec toi »
    assert levels(tool) == {"owner": "non", "account": "non", "named": "seule", "unproven": "non",
                            "stranger": "non", "room": "non", "work": "non", "none": "non"}
    # sans règle à elle, sa situation décide (ici : retiré)
    assert level_of(offered_tool(with_owner=False, with_people=("user_3",), situations=(("compte", "non"),)),
                    NAMED) == "non"
    # et sans aucune règle, l'accord du service
    assert level_of(offered_tool(autonomy="toi", with_owner=False, with_people=("user_3",)), NAMED) == "toi"


def test_no_rule_lets_anyone_in_beyond_the_service():
    tool = offered_tool(people=(("user_2", "seule"), ("web_x", "seule")), situations=(("compte", "seule"),))
    assert level_of(tool, ACCOUNT) == "non" and level_of(tool, STRANGER) == "non"
    assert level_of(tool, OWNER) == "seule"


def test_a_situation_rule_changes_the_approval_or_removes_the_tool():
    tool = offered_tool(autonomy="seule", with_accounts=True,
                        situations=(("compte", "carte"), ("proprietaire", "toi"), ("travail", "non")))
    assert (level_of(tool, OWNER), level_of(tool, ACCOUNT), level_of(tool, WORK)) == ("toi", "carte", "non")


# ── qui peut quoi (ADR 0129) ────────────────────────────────────────────────


def service(**kw):
    base = {"with_owner": True, "with_accounts": False, "with_people": (), "episodes": ("conversation", "travail"),
            "autonomy": "carte", "keep": "prive", "reviews": {}}
    return NS(**{**base, **kw})


def decided(**kw):
    base = {"enabled": True, "nature": "action", "autonomy": "service", "keep": "service", "situations": {},
            "people": {}}
    return NS(**{**base, **kw})


def facing(st, review) -> dict[str, str]:
    rules = rules_of(st, review)
    return {f.label: " / ".join(filter(None, said_level(level_of(rules, f.audience), f)[:2]))
            for f in faces(st, None, tuple(review.people))}


def test_who_can_do_what_is_the_engine_rule_on_typical_people():
    # « carte » : toi, une carte dans ton chat ; une personne, la sienne ; personne en face, la console
    st = service(with_accounts=True, with_people=("user_3",))
    assert facing(st, decided()) == {
        "Toi": "te demande / une carte dans ton chat", "user_3": "lui demande / une carte dans son chat",
        "Les autres comptes": "lui demande / une carte dans son chat",
        "Elle travaille seule": "te demande / dans la console (« À valider »)"}
    # « toi » devant quelqu'un d'autre : la console, pas une carte
    assert facing(st, decided(autonomy="toi"))["user_3"] == "te demande / dans la console (« À valider »)"
    # une règle par personne passe avant ; une règle de situation retire
    ruled = decided(people={"user_3": "seule"}, situations={"compte": "non"})
    assert facing(st, ruled) == {"Toi": "te demande / une carte dans ton chat", "user_3": "seule",
                               "Les autres comptes": "non", "Elle travaille seule": "te demande / dans la console "
                                                                                    "(« À valider »)"}
    # rien de plus que le service : sans les comptes, pas de colonne pour eux ni pour une personne qu'il n'ouvre pas
    assert list(facing(service(), decided(people={"user_9": "seule"}))) == ["Toi", "Elle travaille seule"]
    # ni toi ni le travail quand le service n'est pas avec toi ; aucun moment, aucune colonne
    assert list(facing(service(with_owner=False, with_people=("user_3",)), decided())) == ["user_3"]
    assert facing(service(episodes=()), decided()) == {}


def test_a_tool_freer_or_stricter_than_its_service_is_said():
    st = service(autonomy="toi", keep="prive")
    assert drift(st, decided(autonomy="seule")) == (["Toi", "Elle travaille seule"], [])
    assert drift(st, decided(situations={"travail": "non"})) == ([], ["Elle travaille seule"])
    assert drift(st, decided(keep="public")) == (["ce qu'elle en garde"], [])
    assert drift(st, decided(keep="rien")) == ([], ["ce qu'elle en garde"])
    # sous « lit seule, demande pour agir », une lecture « seule » à elle ne s'écarte de rien (2026-10-23 : quatre
    # lectures se disaient « exception » sans rien changer)…
    reads = service(autonomy="lit")
    assert drift(reads, decided(nature="lecture", autonomy="seule")) == ([], [])
    # … jusqu'à ce que le service se resserre : son genre ne le dit pas, la fiche si
    tight = service(autonomy="toi", reviews={"facture_get": decided(nature="lecture", autonomy="seule"),
                                             "ticket_create": decided()})
    assert looser_tools(tight) == ["facture_get"]
    # « carte » et « toi » reviennent au même quand c'est toi qui décides
    assert drift(st, decided(autonomy="carte")) == ([], [])


def test_a_tool_keeps_its_own_level_or_follows_its_service():
    assert StoredReview(fingerprint="f").keep == "service"
    assert StoredReview(fingerprint="f", keep="rien").keep == "rien"
    with pytest.raises(ValidationError):
        StoredReview.model_validate({"fingerprint": "f", "keep": "tout"})


# ── l'accord, décidé à l'appel ──────────────────────────────────────────────


class Ctx:
    """Le contexte d'un appel d'outil, réduit à ce que lit le gestionnaire ``mcp`` : ce qu'il écrit est gardé."""

    def __init__(self, audience, target, kind=Kind.REPLY, port=None):
        self.ports = {"mcp": port if port is not None else FakePort()}
        self.frame = NS(audience=audience, episode=NS(kind=kind, target=target), now=1_000)
        self.episode_id, self.call_key, self.call_id = "ep1", "k1", "c1"
        self.emitted: list = []
        self.proposed: list = []

    async def emit(self, *drafts):
        self.emitted.extend(drafts)

    async def propose(self, draft):
        self.proposed.append(draft)

    def payload(self) -> dict:
        (draft,) = self.proposed
        return json.loads(draft.data.args_json)


async def call(tool, ctx) -> ToolResult:
    return await _handler(tool)(ExternalArgs(ville="Lyon"), ctx)


async def test_alone_the_call_leaves_and_what_it_returns_carries_what_she_keeps():
    for keep, floor, unkept in (("public", 0, False), ("perso", 0, False), ("prive", CONFIDENCE, False),
                                ("rien", CONFIDENCE, True)):
        ctx = Ctx(OWNER, "user_1")
        got = await call(offered_tool(keep=keep), ctx)
        assert got.ok and (got.floor, got.unkept) == (floor, unkept), keep
        assert ctx.ports["mcp"].calls == [("meteo", "prevision", {"ville": "Lyon"})] and ctx.proposed == []
        assert "Grand soleil sur Lyon" in got.content


async def test_a_card_goes_to_the_authenticated_person_in_front():
    ctx = Ctx(ACCOUNT, "user_2")
    got = await call(offered_tool(autonomy="carte", with_accounts=True, keep="prive", fingerprint="f1"), ctx)
    args = ctx.payload()
    assert got.ok and "rien n'est encore parti" in got.content and ctx.ports["mcp"].calls == []
    assert args[rt.DECIDER] == "user_2" and args["approval"] == "conversation" and args["target"] == "user_2"
    assert args["keep"] == "prive" and args["fingerprint"] == "f1" and args["args"] == {"ville": "Lyon"}


async def test_her_approval_before_someone_else_goes_to_the_operator():
    ctx = Ctx(ACCOUNT, "user_2")
    await call(offered_tool(autonomy="toi", with_accounts=True), ctx)
    args = ctx.payload()
    assert rt.DECIDER not in args and args["approval"] == "operateur" and args["target"] == "user_2"
    assert ctx.ports["mcp"].calls == []


async def test_her_approval_before_her_is_a_card():
    ctx = Ctx(OWNER, "user_1")
    await call(offered_tool(autonomy="toi"), ctx)
    args = ctx.payload()
    assert args[rt.DECIDER] == "user_1" and args["approval"] == "conversation"


async def test_working_alone_nobody_can_accept_so_the_operator_decides():
    ctx = Ctx(WORK, None, kind=Kind.STEP)
    await call(offered_tool(autonomy="carte"), ctx)
    args = ctx.payload()
    assert rt.DECIDER not in args and args["approval"] == "operateur" and args["target"] == ""


async def test_out_of_its_service_nothing_leaves_and_without_port_nothing_either():
    ctx = Ctx(STRANGER, "web_x")
    got = await call(offered_tool(with_accounts=True), ctx)
    assert not got.ok and got.content == phrase("mcp.tools.closed")
    assert ctx.ports["mcp"].calls == [] and ctx.proposed == []
    ctx = Ctx(OWNER, "user_1")
    ctx.ports = {}
    got = await call(offered_tool(), ctx)
    assert not got.ok and got.content == phrase("mcp.unavailable")


# ── ce que vaut ce qu'il a rendu, dans la boucle ────────────────────────────


class Q(BaseModel):
    q: str = ""


def _tool(name: str, result: ToolResult) -> ToolSpec:
    async def handler(args, ctx):
        return result

    return ToolSpec("probe", name, "un outil", Q, handler, "probe", frozenset({Kind.REPLY}))


class Scripted:
    """Une passerelle qui demande ces outils, puis répond."""

    def __init__(self, *calls: ToolCall) -> None:
        self.calls = calls

    async def call(self, req: LLMRequest) -> LLMResponse:
        if any(m.role == "tool" for m in req.messages):
            return LLMResponse("voilà")
        return LLMResponse("", self.calls, stop="tool_use")


async def _loop(*specs_and_calls):
    tools = {spec.name: spec for spec, _ in specs_and_calls}
    return await run_tool_loop(Scripted(*(c for _, c in specs_and_calls)),
                               LLMRequest(role="reply", call_id="ep#0", system_stable="", messages=()), tools,
                               lambda spec, cid: NS(), max_turns=3)


async def test_the_loop_carries_the_highest_floor_and_keeps_nothing_of_an_unkept_call():
    loop = await _loop((_tool("perso", ToolResult(content="il fait beau")), ToolCall("a", "perso", {"q": "météo"})),
                       (_tool("prive", ToolResult(content="facture 12 : 400 €", floor=CONFIDENCE)),
                        ToolCall("b", "prive", {"q": "factures"})),
                       (_tool("rien", ToolResult(content="relevé : 1 234 €", floor=CONFIDENCE, unkept=True)),
                        ToolCall("c", "rien", {"q": "mon relevé"})))
    assert loop.text == "voilà" and (loop.floor, loop.unkept) == (CONFIDENCE, True)
    perso, prive, rien = loop.records
    assert (perso.args_json, perso.result) == ('{"q": "météo"}', "il fait beau")
    assert "factures" in prive.args_json and prive.result == "facture 12 : 400 €"
    assert (rien.args_json, rien.result, rien.ok) == ("{}", "", True)  # ni ce qu'elle a demandé, ni ce qu'il a rendu


async def test_a_failed_call_carries_no_floor():
    loop = await _loop((_tool("rate", ToolResult(ok=False, content="panne", floor=CONFIDENCE)),
                        ToolCall("a", "rate", {"q": "x"})),
                       (_tool("public", ToolResult(content="il fait beau")), ToolCall("b", "public", {"q": "y"})))
    assert (loop.floor, loop.unkept) == (0, False)


# ── de bout en bout : « rien » ne se garde pas ──────────────────────────────


def _asks_once(req: LLMRequest) -> LLMResponse:
    if req.role == "reply":
        if not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", tool_calls=(ToolCall("t1", NAME, {"ville": "Lyon"}),), stop="tool_use")
        return LLMResponse("Grand soleil à Lyon ! [EMOTION:happy:0.5]")
    return LLMResponse("{}")


def _lived(tmp_path, keep: str):
    port = FakePort(offered_tool(keep=keep))
    kernel, clock, _llm, _ = build(tmp_path, _asks_once, ports={"mcp": port}, arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            report = await (await kernel.perceive(said("user_1", "quel temps à Lyon ?", display_name="Adrien"))).reply
            await kernel.traces.flush()
            utterances = [e for e in kernel.mind.store.read() if e.type == rt.UTTERANCE.name]
            uttered = kernel.mind.decode(utterances[-1]).data
            chunks = [r[0] for r in kernel.mind.store.query_mind(f"SELECT id FROM {memory_c.CHUNKS_TABLE}")]
            return kernel.traces.get(report.id), uttered, chunks, port.calls
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_an_answer_fed_by_a_service_she_keeps_nothing_of_leaves_no_trace(tmp_path):
    trace, uttered, chunks, calls = _lived(tmp_path / "rien", "rien")
    assert calls == [("meteo", "prevision", {"ville": "Lyon"})]  # l'appel est bien parti, elle s'en est servie
    (record,) = trace["tool_calls"]
    assert (record["args"], record["result"], record["ok"]) == ("{}", "", True)
    assert (uttered.floor, uttered.unkept) == (CONFIDENCE, True) and chunks == []
    # contre-épreuve : « perso », l'échange s'indexe et la trace garde ce qu'il a rendu
    trace, uttered, chunks, _ = _lived(tmp_path / "perso", "perso")
    (record,) = trace["tool_calls"]
    assert "Grand soleil sur Lyon" in record["result"] and '"ville"' in record["args"]
    assert (uttered.floor, uttered.unkept) == (0, False) and len(chunks) == 1


# ── la mémoire ──────────────────────────────────────────────────────────────


def _voice() -> rt.VoiceProvenance:
    return rt.VoiceProvenance(call_id="t", persona_hash="h", role="reply", model="m")


def test_an_unkept_exchange_is_not_indexed():
    db = SqlDB()
    Thread().create(db, "")
    Chunks().create(db, "")
    db.execute(thread_table().insert(), [
        {"id": 10, "at": 10, "role": "user", "person": "user_1", "text": "mon relevé ?", "folded": "mon releve ?"},
        {"id": 20, "at": 20, "role": "user", "person": "user_1", "text": "et la météo ?", "folded": "et la meteo ?"}])

    def answer(seq: int, reply_to: int, **kw):
        draft = rt.UTTERANCE.draft(kind="REPLY", text=Content.of("voilà"), voice=_voice(), target="user_1",
                                   reply_to=reply_to, answers=(reply_to,), **kw)
        return NS(type=draft.type, data=draft.data, seq=seq, at=seq)

    Chunks().apply(db, [answer(11, 10, unkept=True, floor=CONFIDENCE), answer(21, 20, floor=CONFIDENCE)], "")
    rows = db.query(f"SELECT id, user_text FROM {memory_c.CHUNKS_TABLE}")
    assert rows == [(21, "et la météo ?")]  # une confidence s'indexe (elle la retrouve avec la personne), « rien » non
    db.conn.close()


class Said:
    """Ses répliques au journal : ce que vaut ce qu'elle a lu pour chacune."""

    def __init__(self, **by_seq: dict) -> None:
        self.by_seq = {int(k[1:]): v for k, v in by_seq.items()}

    def get_events(self, seqs):
        return [NS(seq=s, type=rt.UTTERANCE.name, data=json.dumps(self.by_seq.get(s, {}))) for s in seqs]


def _conversation() -> Conversation:
    lines = (Line(10, FRAME.now, "Alice [P1]", "lis-moi mon relevé de compte", "user_2"),
             Line(11, FRAME.now, "Mika", "Ton solde est de 1 234 €."),
             Line(12, FRAME.now, "Alice [P1]", "et ma dernière facture ?", "user_2"),
             Line(13, FRAME.now, "Mika", "La facture 12 fait 400 €."),
             Line(14, FRAME.now, "Alice [P1]", "merci !", "user_2"),
             Line(15, FRAME.now, "Mika", "Avec plaisir !"))
    return Conversation("private:user_2", (Speaker("P1", "user_2", "Alice"),), lines)


def test_the_reread_sees_neither_an_unkept_reply_nor_the_request_it_followed():
    store = Said(s11={"unkept": True, "floor": CONFIDENCE, "reply_to": 10, "answers": [10]},
                 s13={"floor": CONFIDENCE, "reply_to": 12, "answers": [12]}, s15={"reply_to": 14})
    conv = Consolidate._her_lines(store, _conversation())
    assert [(ln.seq, ln.unkept, ln.floor) for ln in conv.lines] == [
        (10, True, CONFIDENCE), (11, True, CONFIDENCE), (12, False, CONFIDENCE), (13, False, CONFIDENCE),
        (14, False, 0), (15, False, 0)]
    text = render(conv, now=FRAME.local(), beliefs=(), promises=())
    assert "relevé" not in text and "1 234" not in text and text.count(UNKEPT) == 2
    assert "La facture 12 fait 400 €." in text and "et ma dernière facture ?" in text  # une confidence se relit
    # rien de tout ça : la conversation telle quelle
    plain = Consolidate._her_lines(Said(), _conversation())
    assert not any(ln.unkept or ln.floor for ln in plain.lines)


def test_what_a_confidential_service_fed_becomes_a_secret_at_least_that_sensitive():
    conv = Consolidate._her_lines(Said(s13={"floor": CONFIDENCE, "reply_to": 12, "answers": [12]}), _conversation())
    drafts = [memory_c.REMEMBERED.draft(text=Content.of("Alice a une facture de 400 €"), sources=(13,), sensitivity=1),
              memory_c.BELIEVED.draft(text=Content.of("Alice doit 400 €"), sources=(12, 14), sensitivity=2),
              memory_c.REMEMBERED.draft(text=Content.of("Alice m'a remerciée"), sources=(14, 15), sensitivity=1),
              memory_c.REINFORCED.draft(item=7, sources=(13,)),
              memory_c.CONSOLIDATED.draft(upto=15)]
    out = floored(drafts, conv)
    remembered, believed, thanked, reinforced, consolidated = (d.data for d in out)
    assert (remembered.sensitivity, remembered.secret) == (CONFIDENCE, True)
    assert (believed.sensitivity, believed.secret) == (CONFIDENCE, True)
    assert (thanked.sensitivity, thanked.secret) == (1, False)  # rien de ce service : inchangé
    assert (reinforced.sensitivity, reinforced.secret) == (CONFIDENCE, True)
    assert consolidated == drafts[-1].data
    assert floored(drafts, _conversation()) == drafts  # aucun plancher : rien ne change


def test_at_night_what_she_wrote_from_a_service_stays_a_confidence_of_the_person_she_read_for():
    utterance = NS(seq=30, type=rt.UTTERANCE.name, data=json.dumps(
        {"target": "user_2", "floor": CONFIDENCE, "unkept": False, "reply_to": 29, "provenance": []}))
    unkept = NS(seq=31, type=rt.UTTERANCE.name, data=json.dumps(
        {"target": "user_2", "floor": 0, "unkept": True, "reply_to": 29, "provenance": []}))
    plain = NS(seq=32, type=rt.UTTERANCE.name, data=json.dumps({"target": "user_2", "reply_to": 29}))

    class Store:
        def query_mind(self, sql, args=()):
            return []

        def get_events(self, seqs):
            return [e for e in (utterance, unkept, plain) if e.seq in seqs]

    for seq in (30, 31):
        rules, _unknown = _disclosure(FRAME, Store(), seq)
        assert memory_c.Disclosure(about=("user_2",), told_by=("user_2",), heard_by=("user_2",),
                                   sensitivity=CONFIDENCE, secret=True) in rules, seq
    rules, _unknown = _disclosure(FRAME, Store(), 32)
    assert rules == ()
