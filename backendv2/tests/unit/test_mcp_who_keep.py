"""Qui peut quoi, en lignes d'accès lues de haut en bas comme les règles d'un pare-feu, et ce qu'elle en garde
(ADR 0128, 0131) — par leurs intentions.

- une fiche d'avant (avec qui, quand, ce qu'elle fait seule, ce qu'elle en garde, les exceptions de ses outils) devient
  les lignes qui font la même chose, sa ligne par défaut fermée ; une ligne illisible est refusée ;
- pour un outil, la première ligne qui le concerne (ses sources, quand, ses outils) décide ; aucune, la ligne par
  défaut ; ce qui lui est offert, c'est l'ensemble des outils qu'une ligne lui ouvre — jamais dans un salon ni avec une
  inconnue, même à « tout le monde » ; tes proches et une personne nommée, seulement authentifiés (ADR 0133) ;
- l'accord se décide à l'appel : seule, l'appel part et rend ce qu'il vaut (``floor``, ``unkept``) ; ``carte``, une
  carte à la personne en face ; ``toi``, une carte à sa propriétaire quand c'est elle en face, sinon l'opérateur ;
- ce que vaut ce qu'un outil a rendu remonte la boucle jusqu'à l'énoncé, et la trace n'en garde rien à « rien » ;
- la mémoire le respecte : « rien » ne s'indexe pas et ne se relit pas (ni la réplique, ni la demande qu'elle
  suivait) ; une confidence de service fait de ce qu'on en tire un secret, la nuit aussi ;
- qui peut quoi (ADR 0129) : la console applique la règle du moteur à des personnes types — jamais une recopie.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel, ValidationError

from mika.adapters.mcp.config import AccessRule, McpServer, StoredReview, access_from_0128
from mika.adapters.mcp.hub import access_of, granted
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
from mika.plugins.mcp import ExternalArgs, _gate, _handler, access_for, situation
from mika.plugins.mcp.console import closeness, faces, said_level, serves_nobody, tool_view
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.ports.mcp import CLOSE, CLOSED, PERSON, WHO_ACCOUNTS, Access
from mika.ports.mcp import EVERYONE as ALL
from mika.ports.mcp import OWNER as YOU
from mika.ports.mcp import WORK as AT_WORK
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
#: la sorte d'épisode de chacun : on répond à quelqu'un, on travaille seule
KINDS = {who: Kind.STEP if who == "work" else Kind.REPLY for who in EVERYONE}
NAMED_3 = PERSON + "user_3"


def tool(*rows: Access, nature: str = "lecture", default: Access = CLOSED, remote: str = "prevision") -> NS:
    """Un outil tel que la règle du moteur le lit : sa nature, les lignes de son service qui le concernent, la ligne
    par défaut."""
    return NS(nature=nature, access=tuple(a for a in rows if a.concerns(remote)), default=default)


def levels(t, close=None) -> dict[str, str]:
    return {who: access_for(t, aud, KINDS[who], close)[0] for who, aud in EVERYONE.items()}


# ── les fiches d'avant ──────────────────────────────────────────────────────


def test_a_server_saved_before_0131_becomes_the_rows_that_do_the_same():
    old = McpServer.model_validate({"purpose": "la facturation", "url": URL, "with_owner": True,
                                    "in_conversation": True, "in_work": True, "autonomy": "lit", "keep": "prive"})
    # une ligne : toi quand elle répond, et elle quand elle travaille (une source, plus un moment : ADR 0133)
    assert [(a.who, a.when, a.read, a.act, a.keep, a.tools) for a in old.access] == [
        ((YOU, AT_WORK), ("conversation",), "seule", "carte", "prive", ())]
    assert (old.default_read, old.default_act, old.default_keep) == ("non", "non", "rien")  # fermé : comme avant
    # d'avant l'ADR 0128 : « pour qui : les comptes », « devient un savoir »
    shared = McpServer.model_validate({"purpose": "la météo", "url": URL, "audience": "comptes", "learns": True})
    assert {(a.who, a.keep) for a in shared.access} == {((YOU,), "public"), ((WHO_ACCOUNTS,), "public")}
    assert not {"audience", "learns", "with_owner", "autonomy"} & set(shared.model_dump())
    with pytest.raises(ValidationError):  # une clé inconnue reste refusée
        McpServer.model_validate({"purpose": "la météo", "url": URL, "pour": "comptes"})


def test_the_exceptions_of_her_tools_become_rows_above_the_service():
    spec = {"purpose": "la météo", "url": URL, "with_accounts": True, "with_people": ["user_3"],
            "in_initiative": True, "in_work": True, "autonomy": "carte", "keep": "prive"}
    tools = {"t1": {"enabled": True, "nature": "action", "autonomy": "seule", "situations": {"compte": "non"},
                    "people": {"user_3": "toi"}, "keep": "rien"},
             # une lecture « seule » sous « lit seule » : rien ne change, aucune ligne (2026-10-23)
             "t2": {"enabled": True, "nature": "lecture", "autonomy": "seule"},
             "coupe": {"enabled": False, "nature": "action", "autonomy": "seule"}}
    rows, _ = access_of(McpServer.model_validate(access_from_0128({**spec, "autonomy": "lit"}, {"t2": tools["t2"]})))
    assert all(not a.tools for a in rows)
    rows, _ = access_of(McpServer.model_validate(access_from_0128(spec, tools)))
    t1 = tool(*rows, nature="action", remote="t1")
    # la personne nommée d'abord, puis les autres comptes, puis toi ; ce qu'elle garde suit l'outil
    assert levels(t1) == {"owner": "seule", "account": "non", "named": "toi", "unproven": "non", "stranger": "non",
                          "room": "non", "work": "seule", "none": "non"}
    assert access_for(t1, NAMED, Kind.REPLY) == ("toi", "rien")
    other = tool(*rows, nature="action", remote="t9")
    assert levels(other) == {"owner": "carte", "account": "carte", "named": "carte", "unproven": "non",
                             "stranger": "non", "room": "non", "work": "carte", "none": "non"}
    assert not any("coupe" in a.tools for a in rows)  # un outil coupé n'a pas de ligne


def _before_0131(spec: dict, raw: dict, nature: str, who: str) -> tuple[str, str]:
    """La règle d'avant l'ADR 0131 (``level_of``, ``tool_autonomy``, ``tool_keep``), figée ici comme témoin."""
    aud, kind = EVERYONE[who], KINDS[who]
    where = situation(aud)
    episodes = {"conversation": spec["in_conversation"], "initiative": spec["in_initiative"], "travail": spec["in_work"]}
    family = "travail" if kind == Kind.STEP else "conversation"
    if where not in ("proprietaire", "compte", "travail") or not episodes[family]:
        return "non", "rien"
    person = aud.person if where == "compte" else ""
    if (where != "compte" and not spec["with_owner"]) or (
            where == "compte" and not (spec["with_accounts"] or person in spec["with_people"])):
        return "non", "rien"
    own, service = raw["autonomy"], spec["autonomy"]
    autonomy = own if own != "service" else (
        ("seule" if nature == "lecture" else "carte") if service == "lit" else service)
    keep = spec["keep"] if raw["keep"] == "service" else raw["keep"]
    level = raw["people"].get(person) if person in raw["people"] else raw["situations"].get(where) or autonomy
    return (level, keep) if level != "non" else ("non", "rien")


def test_a_tool_rule_for_a_named_person_survives_the_rule_of_the_accounts():
    """2026-10-25 : une personne nommée réglée « comme le service » passait sous la ligne des comptes de l'outil —
    « carte » devenait « non », ou « seule » sans demander."""
    spec = {"purpose": "la météo", "url": URL, "with_accounts": True, "autonomy": "carte", "keep": "prive"}
    for compte in ("non", "seule"):
        tools = {"t1": {"enabled": True, "nature": "lecture", "situations": {"compte": compte},
                        "people": {"user_3": "carte"}}}
        rows, _ = access_of(McpServer.model_validate(access_from_0128(spec, tools)))
        t1 = tool(*rows, remote="t1")
        assert access_for(t1, NAMED, Kind.REPLY) == ("carte", "prive")
        assert access_for(t1, ACCOUNT, Kind.REPLY)[0] == compte
    # toutes les combinaisons : la fiche traduite fait ce que faisait la règle d'avant, devant chacun
    levels_ = ("seule", "carte", "toi", "non")
    for accounts in (False, True):
        for people in ((), ("user_3",)):
            for work in (False, True):
                spec = {"purpose": "la météo", "url": URL, "with_owner": True, "with_accounts": accounts,
                        "with_people": list(people), "in_conversation": True, "in_initiative": False,
                        "in_work": work, "autonomy": "lit", "keep": "perso"}
                for nature in ("lecture", "action"):
                    for own in ("service", "seule", "toi"):
                        for keep in ("service", "rien"):
                            for compte in (None, *levels_):
                                for named in (None, *levels_):
                                    for mine in (None, "non", "seule"):
                                        raw = {"enabled": True, "nature": nature, "autonomy": own, "keep": keep,
                                               "situations": {k: v for k, v in (("compte", compte),
                                                                                ("proprietaire", mine)) if v},
                                               "people": {"user_3": named} if named else {}}
                                        rows, _ = access_of(McpServer.model_validate(
                                            access_from_0128(spec, {"t1": raw})))
                                        t1 = tool(*rows, nature=nature, remote="t1")
                                        for who in EVERYONE:
                                            want = _before_0131(spec, raw, nature, who)
                                            got = access_for(t1, EVERYONE[who], KINDS[who])
                                            # « non » : ce qu'elle garderait ne compte pas
                                            assert got[0] == want[0] and (got[0] == "non" or got == want), (
                                                who, got, want, spec, raw)


def test_a_review_keeps_only_what_is_hers_and_a_bad_row_is_refused():
    review = StoredReview.model_validate({"fingerprint": "f", "nature": "action", "approval": "aucun",
                                          "autonomy": "toi", "keep": "rien", "situations": {"compte": "non"}})
    assert (review.nature, review.enabled) == ("action", False)
    assert not {"autonomy", "keep", "situations", "people"} & set(review.model_dump())
    for bad in ({"who": ["salon"]}, {"who": [PERSON]}, {"who": []}, {"who": [YOU], "when": ["parfois"]},
                {"who": [YOU], "read": "jamais"}, {"who": [YOU], "keep": "tout"}):
        with pytest.raises(ValidationError):
            AccessRule.model_validate(bad)


# ── de haut en bas ──────────────────────────────────────────────────────────


def test_where_she_would_use_a_service():
    assert {who: situation(aud) for who, aud in EVERYONE.items()} == {
        "owner": "proprietaire", "account": "compte", "named": "compte", "unproven": "inconnue",
        "stranger": "inconnue", "room": "salon", "work": "travail", "none": None}
    owner_in_room = Audience(persons=("user_1",), room="salon", public=True, trust=ChannelTrust.AUTHENTICATED.value,
                             owner=True, person="user_1")
    assert situation(owner_in_room) == "salon"  # même sa propriétaire : un salon reste un salon


def test_without_a_row_the_default_decides_and_it_starts_closed():
    assert set(levels(tool()).values()) == {"non"}
    opened = tool(default=Access(who=(), read="carte", act="toi", keep="prive"))
    # la ligne par défaut vaut pour tous, mais un outil jamais dans un salon, avec une inconnue, ni sans personne
    assert levels(opened) == {"owner": "carte", "account": "carte", "named": "carte", "unproven": "non",
                              "stranger": "non", "room": "non", "work": "carte", "none": "non"}


def test_you_she_at_work_accounts_and_named_people_only_authenticated():
    assert levels(tool(Access(who=(YOU, AT_WORK), read="seule"))) == {
        "owner": "seule", "account": "non", "named": "non", "unproven": "non", "stranger": "non", "room": "non",
        "work": "seule", "none": "non"}
    # elle qui travaille est une source à elle : toi seule ne l'ouvre pas au travail, ni l'inverse
    assert levels(tool(Access(who=(YOU,), read="seule")))["work"] == "non"
    assert {k for k, v in levels(tool(Access(who=(AT_WORK,), read="seule"))).items() if v != "non"} == {"work"}
    assert levels(tool(Access(who=(WHO_ACCOUNTS,), read="carte"))) == {
        "owner": "non", "account": "carte", "named": "carte", "unproven": "non", "stranger": "non", "room": "non",
        "work": "non", "none": "non"}
    assert levels(tool(Access(who=(NAMED_3,), read="toi"))) == {
        "owner": "non", "account": "non", "named": "toi", "unproven": "non", "stranger": "non", "room": "non",
        "work": "non", "none": "non"}


def test_her_close_ones_in_private_and_everyone_but_never_a_tool_in_a_room():
    """Tes proches : un lien « proche », authentifié, en privé ; tout le monde : chacun en tête-à-tête, sauf elle
    qui travaille seule — un outil n'est jamais offert dans un salon ni à une inconnue (ADR 0133)."""
    is_close = {"user_2"}.__contains__
    near = tool(Access(who=(CLOSE,), read="carte"))
    assert {k for k, v in levels(near, is_close).items() if v != "non"} == {"account"}
    assert levels(near)["account"] == "non"  # sans savoir qui est proche : personne
    # proche, mais sur un canal où rien ne prouve que c'est elle
    assert access_for(near, NAMED_UNPROVEN, Kind.REPLY, {"user_3"}.__contains__)[0] == "non"
    # plusieurs sources sur une ligne : l'une suffit
    assert {k for k, v in levels(tool(Access(who=(CLOSE, NAMED_3), read="seule")), is_close).items()
            if v != "non"} == {"account", "named"}
    assert levels(tool(Access(who=(ALL,), read="seule"))) == {
        "owner": "seule", "account": "seule", "named": "seule", "unproven": "non", "stranger": "non", "room": "non",
        "work": "non", "none": "non"}


def test_the_first_row_that_matches_decides():
    rows = (Access(who=(NAMED_3,), read="non"), Access(who=(WHO_ACCOUNTS,), read="seule"),
            Access(who=(YOU,), when=("conversation",), read="seule"), Access(who=(YOU, AT_WORK), read="toi"))
    t = tool(*rows, default=Access(who=(), read="carte"))
    assert levels(t) == {"owner": "seule", "account": "seule", "named": "non", "unproven": "non",
                         "stranger": "non", "room": "non", "work": "toi", "none": "non"}
    assert access_for(t, OWNER, Kind.INITIATIVE)[0] == "toi"  # « quand elle répond » ne vaut pas d'elle-même
    # dans l'autre ordre, la ligne des comptes passe avant celle de la personne nommée : elle n'y vaut plus rien
    assert access_for(tool(rows[1], rows[0]), NAMED, Kind.REPLY)[0] == "seule"


def test_a_tool_reads_or_acts_and_takes_its_column():
    row = Access(who=(YOU,), read="seule", act="toi", keep="prive")
    assert access_for(tool(row, nature="lecture"), OWNER, Kind.REPLY) == ("seule", "prive")
    assert access_for(tool(row, nature="action"), OWNER, Kind.REPLY) == ("toi", "prive")


def test_what_she_has_at_hand_is_every_tool_a_row_opens():
    """La facturation : la lecture des factures en souvenir, leur écriture sur ton accord, en confidence — deux
    lignes, deux outils ; ce qu'elle a sous la main, ce sont les deux (2026-10-23)."""
    rows = (Access(who=(YOU,), read="seule", act="toi", keep="prive", tools=("set_facture",)),
            Access(who=(YOU,), read="seule", act="toi", keep="perso", tools=("get_facture",)),
            Access(who=(YOU,), read="non", act="non"))
    get = tool(*rows, nature="lecture", remote="get_facture")
    put = tool(*rows, nature="action", remote="set_facture")
    rest = tool(*rows, nature="lecture", remote="ticket_list")
    assert access_for(get, OWNER, Kind.REPLY) == ("seule", "perso")
    assert access_for(put, OWNER, Kind.REPLY) == ("toi", "prive")
    assert access_for(rest, OWNER, Kind.REPLY)[0] == "non"  # sa première ligne le ferme
    gates = {name: _gate(t)(OWNER, Kind.REPLY) for name, t in (("get", get), ("put", put), ("rest", rest))}
    assert gates == {"get": True, "put": True, "rest": False}


def test_the_moments_she_may_be_offered_it_come_from_the_rows_that_open_it():
    rows = (Access(who=(YOU,), when=("conversation",), read="seule"), Access(who=(AT_WORK,), act="toi"))
    assert granted(rows, CLOSED, "lecture") == frozenset({"conversation"})
    assert granted(rows, CLOSED, "action") == frozenset({"travail"})
    assert granted((), Access(who=(), read="carte"), "lecture") == frozenset({"conversation", "initiative", "travail"})
    assert granted((), CLOSED, "lecture") == frozenset()


# ── qui peut quoi (ADR 0129, 0131) ──────────────────────────────────────────


def service(*rows: Access, default: Access = CLOSED) -> NS:
    return NS(access=rows, default=default, reviews={})


def facing(st, nature: str = "action", remote: str = "prevision") -> dict[str, str]:
    t = tool_view(st, remote, nature)
    return {f.label: " / ".join(filter(None, said_level(access_for(t, f.audience, f.kind, closeness(f, None))[0],
                                                         f)[:2]))
            for f in faces(st)}


def test_who_can_do_what_is_the_engine_rule_on_typical_people():
    # « carte » : toi, une carte dans ton chat ; une personne, la sienne ; personne en face, la console
    st = service(Access(who=(NAMED_3,), act="carte"), Access(who=(CLOSE,), act="carte"),
                 Access(who=(YOU, AT_WORK), act="carte"))
    assert facing(st) == {
        "Toi": "te demande / une carte dans ton chat",
        "Toi, quand elle te parle d'elle-même": "te demande / une carte dans ton chat",
        "user_3": "lui demande / une carte dans son chat", "Un proche": "lui demande / une carte dans son chat",
        "Un autre compte": "non", "Elle travaille seule": "te demande / dans la console (« À valider »)"}
    # « ton accord » devant quelqu'un d'autre : la console, pas une carte
    assert facing(service(Access(who=(NAMED_3,), act="toi")))["user_3"] == "te demande / dans la console (« À valider »)"
    # un moment : toi quand elle répond, mais pas d'elle-même ni au travail
    only = facing(service(Access(who=(YOU,), when=("conversation",), act="seule")))
    assert (only["Toi"], only["Toi, quand elle te parle d'elle-même"], only["Elle travaille seule"]) == (
        "seule", "non", "non")


def test_a_service_open_to_nobody_says_so():
    assert serves_nobody(service())
    assert serves_nobody(service(Access(who=(YOU,), read="non", act="non")))
    assert not serves_nobody(service(Access(who=(YOU,), read="seule")))
    assert not serves_nobody(service(default=Access(who=(), act="toi")))


# ── l'accord, décidé à l'appel ──────────────────────────────────────────────


class Ctx:
    """Le contexte d'un appel d'outil, réduit à ce que lit le gestionnaire ``mcp`` : ce qu'il écrit est gardé."""

    def __init__(self, audience, target, kind=Kind.REPLY, port=None):
        self.ports = {"mcp": port if port is not None else FakePort()}
        self.frame = NS(audience=audience, episode=NS(kind=kind, target=target), now=1_000,
                        get=lambda key, default=None: default)
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


async def call(t, ctx) -> ToolResult:
    return await _handler(t)(ExternalArgs(ville="Lyon"), ctx)


def asking(level: str, who: tuple[str, ...] = (YOU, AT_WORK), keep: str = "prive", **kw):
    return offered_tool(access=(Access(who=who, read=level, act=level, keep=keep),), **kw)


async def test_alone_the_call_leaves_and_what_it_returns_carries_what_she_keeps():
    for keep, floor, unkept in (("public", 0, False), ("perso", 0, False), ("prive", CONFIDENCE, False),
                                ("rien", CONFIDENCE, True)):
        ctx = Ctx(OWNER, "user_1")
        got = await call(offered_tool(keep=keep), ctx)
        assert got.ok and (got.floor, got.unkept) == (floor, unkept), keep
        assert ctx.ports["mcp"].calls == [("meteo", "prevision", {"ville": "Lyon"})] and ctx.proposed == []
        assert "Grand soleil sur Lyon" in got.content


async def test_what_she_keeps_comes_from_the_row_that_matched():
    t = offered_tool(access=(Access(who=(YOU,), when=("conversation",), read="seule", keep="rien"),
                             Access(who=(YOU, AT_WORK), read="seule", keep="public")))
    got = await call(t, Ctx(OWNER, "user_1"))
    assert got.unkept
    got = await call(t, Ctx(WORK, None, kind=Kind.STEP))
    assert not got.unkept and got.floor == 0


async def test_a_card_goes_to_the_authenticated_person_in_front():
    ctx = Ctx(ACCOUNT, "user_2")
    got = await call(asking("carte", (WHO_ACCOUNTS,), fingerprint="f1"), ctx)
    args = ctx.payload()
    assert got.ok and "rien n'est encore parti" in got.content and ctx.ports["mcp"].calls == []
    assert args[rt.DECIDER] == "user_2" and args["approval"] == "conversation" and args["target"] == "user_2"
    assert args["keep"] == "prive" and args["fingerprint"] == "f1" and args["args"] == {"ville": "Lyon"}


async def test_her_approval_before_someone_else_goes_to_the_operator():
    ctx = Ctx(ACCOUNT, "user_2")
    await call(asking("toi", (WHO_ACCOUNTS,)), ctx)
    args = ctx.payload()
    assert rt.DECIDER not in args and args["approval"] == "operateur" and args["target"] == "user_2"
    assert ctx.ports["mcp"].calls == []


async def test_her_approval_before_her_is_a_card():
    ctx = Ctx(OWNER, "user_1")
    await call(asking("toi"), ctx)
    args = ctx.payload()
    assert args[rt.DECIDER] == "user_1" and args["approval"] == "conversation"


async def test_working_alone_nobody_can_accept_so_the_operator_decides():
    ctx = Ctx(WORK, None, kind=Kind.STEP)
    await call(asking("carte"), ctx)
    args = ctx.payload()
    assert rt.DECIDER not in args and args["approval"] == "operateur" and args["target"] == ""


async def test_out_of_its_rows_nothing_leaves_and_without_port_nothing_either():
    ctx = Ctx(STRANGER, "web_x")
    got = await call(asking("seule", (WHO_ACCOUNTS,)), ctx)
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
