"""Le moteur des droits (ADR 0134), par ses intentions.

- une ligne dit qui, par où, quand ; la première qui correspond décide, sinon la ligne par défaut ;
- « elle seule » est un canal sans personne : seule une ligne sans qui la désigne ; « tout le monde » ne la désigne pas ;
- les plafonds : une inconnue n'obtient au plus que des outils qui lisent, jamais une action, une garde « rien » ; à
  plusieurs, un des siens qui lit au plus, rien de ce qui vient du dehors, un projet en lecture seule au plus ; sans
  personne hors du travail, rien ;
- deux portes : le tableau du canal, puis celui de la ressource ; la plus stricte gagne, et la décision dit les deux ;
- une famille de ses propres outils naît du minimum vital que ses outils déclarent (``owner_only``) ; un tableau réglé
  le remplace ; la porte d'offre les lit, et l'offre réglée (en main, à chercher) suit l'outil ;
- un formulaire de tableau se lit d'un coup, et refuse une ligne sans qui, sans moment ou sans outil.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from mika.kernel.faculty import ToolSpec
from mika.kernel.frame import Audience
from mika.kernel.rights import Rights
from mika.runtime.tools import ASK, HAND, allowed, deferred
from mika.vocab.access import (
    ALONE,
    CARD,
    CLOSE,
    EVERYONE,
    INTERNAL,
    MOBILE,
    NO,
    OWNER,
    OWNER_OK,
    PERSON,
    STEER_EDIT,
    STEER_READ,
    TOGETHER,
    WEB,
    Canal,
    Rule,
    TableArgs,
    ToolRule,
    canal_of,
    ceiling,
    designates,
    moved,
    rows_sent,
    situation,
    via,
)
from mika.vocab.canals import CanalRule, Canals, CanalTable, mail_rule, mail_rule_for_all, teams_rule, vital
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import project_allowance, tool_allowance, vital_family

AUTH = ChannelTrust.AUTHENTICATED.value
YOU = Audience(persons=("user_1",), channel="web", public=False, trust=AUTH, owner=True, person="user_1")
PHONE = Audience(persons=("user_1",), channel="mobile", public=False, trust=AUTH, owner=True, person="user_1")
CAMILLE = Audience(persons=("user_2",), channel="web", public=False, trust=AUTH, person="user_2")
STRANGER = Audience(persons=("ext_9",), channel="external", public=False, trust=ChannelTrust.ACCOUNT.value,
                    person="ext_9")
ROOM = Audience(persons=("user_2",), channel="web", room="salon", public=True, trust=AUTH, person="user_2")
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
NOBODY = Audience(persons=(), channel="web", public=False, trust=AUTH)
#: une inconnue sur le chat web (sans session) : le canal laisse tout, le plafond serre
GUEST = Audience(persons=("anon_1",), channel="web", public=False, trust=ChannelTrust.PUBLIC.value, person="anon_1")


def test_where_she_is_and_by_which_canal():
    assert [situation(a) for a in (YOU, PHONE, CAMILLE, STRANGER, ROOM, WORKING, NOBODY)] == [
        "proprietaire", "proprietaire", "compte", "inconnue", "salon", "travail", None]
    assert canal_of(YOU) == Canal(WEB, "prive") and canal_of(ROOM) == Canal(WEB, TOGETHER)
    assert canal_of(PHONE) == Canal(MOBILE) and canal_of(WORKING) == Canal(INTERNAL)
    assert canal_of(STRANGER) == Canal("internet") and canal_of(STRANGER).key == "internet"
    assert via((), canal_of(YOU)) and via(("tous",), canal_of(ROOM)) and via((WEB,), canal_of(ROOM))
    assert via((f"{WEB}:{TOGETHER}",), canal_of(ROOM)) and not via((f"{WEB}:prive",), canal_of(ROOM))
    assert not via((MOBILE,), canal_of(YOU)) and via((MOBILE, WEB), canal_of(YOU))


def test_who_a_line_designates():
    near = {"user_2"}.__contains__
    assert designates((OWNER,), "proprietaire", "") and not designates((OWNER,), "compte", "user_2")
    assert designates((CLOSE,), "compte", "user_2", near) and not designates((CLOSE,), "compte", "user_3", near)
    assert designates((PERSON + "user_2",), "compte", "user_2") and not designates((PERSON + "user_2",), "compte", "user_3")
    # tout le monde : chacun, une inconnue et un salon compris — jamais elle seule
    assert all(designates((EVERYONE,), where, "x") for where in ("proprietaire", "compte", "inconnue", "salon"))
    assert not designates((EVERYONE,), "travail", "")
    # elle seule : seule une ligne sans personne (et la ligne par défaut)
    assert designates((), "travail", "") and designates((), "compte", "user_2")
    assert not designates((OWNER,), "travail", "")
    with pytest.raises(ValidationError):  # une source inconnue, un canal inconnu, un moment inconnu
        Rule(who=("salon",))
    with pytest.raises(ValidationError):
        Rule(canal=("telepathie",))
    with pytest.raises(ValidationError):
        Rule(when=("travail",))
    assert Rule(canal=("tous",)).canal == () and Rule(when=("conversation", "initiative")).when == ()


def test_the_ceilings():
    assert ceiling(YOU).act == ALONE and ceiling(WORKING).files
    stranger, room = ceiling(STRANGER), ceiling(ROOM)
    assert (stranger.read, stranger.act, stranger.keep, stranger.steer, stranger.files) == (ALONE, NO, "rien", STEER_READ, False)
    assert (room.read, room.act, room.steer, room.files) == (ALONE, NO, STEER_READ, False)
    assert ceiling(NOBODY) is None


def _tools(*lines: ToolRule, default: ToolRule = ToolRule()) -> tuple[tuple[ToolRule, ...], ToolRule]:
    return lines, default


def test_two_doors_the_stricter_wins_and_the_decision_says_both():
    lines, default = _tools(ToolRule(who=(EVERYONE,), read=ALONE, act=ALONE, keep="public"))
    wide = Rights(canals=Canals())  # les minimums vitaux : le chat web laisse tout
    got = tool_allowance(lines, default, YOU, Kind.REPLY, False, wide)
    assert (got.level, got.keep) == (ALONE, "public") and got.why == "ligne 1" and got.canal_key == WEB
    # le canal serre : par le chat web, un outil qui agit demande ton accord, et elle ne garde rien — dit comme tel
    canals = Canals(tables={WEB: CanalTable(lines=(CanalRule(who=(EVERYONE,), reply="seule", read=ALONE, act=OWNER_OK,
                                                             steer=STEER_EDIT, files=True, keep="rien"),))})
    got = tool_allowance(lines, default, YOU, Kind.REPLY, True, Rights(canals=canals))
    assert (got.level, got.keep) == (OWNER_OK, "rien") and got.narrowed
    assert got.why == "ligne 1 — serré par le canal Chat web (ligne 1)"
    # l'instance passe avant le type : en salon, le chat web est fermé — et de toute façon rien venu d'ailleurs
    canals = Canals(tables={f"{WEB}:{TOGETHER}": CanalTable()})
    got = tool_allowance(lines, default, ROOM, Kind.REPLY, False, Rights(canals=canals), outside=True)
    assert got.level == NO and got.canal_key == f"{WEB}:{TOGETHER}"
    # le plafond : une inconnue lit au plus, n'agit jamais, ne garde rien ; dit comme tel
    got = tool_allowance(lines, default, GUEST, Kind.REPLY, True, wide)
    assert got.level == NO and got.capped and "plafond" in got.why
    got = tool_allowance(lines, default, GUEST, Kind.REPLY, False, wide)
    assert (got.level, got.keep) == (ALONE, "rien")
    # par Internet, le minimum vital du canal ferme déjà les outils (son tableau peut les ouvrir)
    assert tool_allowance(lines, default, STRANGER, Kind.REPLY, False, wide).level == NO
    # sans personne : rien ; elle seule : la ligne sans qui
    assert tool_allowance(lines, default, NOBODY, Kind.REPLY, False, wide) is None
    assert tool_allowance(lines, default, WORKING, Kind.STEP, False, wide).level == NO
    alone = _tools(ToolRule(canal=(INTERNAL,), read=ALONE, act=ALONE))
    assert tool_allowance(*alone, WORKING, Kind.STEP, True, wide).level == ALONE
    assert tool_allowance(*alone, YOU, Kind.REPLY, True, wide).level == NO


def test_a_project_through_the_two_doors():
    from mika.contracts.projects import UNSET, UNSET_DEFAULT

    wide = Rights(canals=Canals())
    yours = project_allowance(UNSET, UNSET_DEFAULT, YOU, Kind.REPLY, wide)
    assert (yours.see, yours.steer, yours.files, yours.read) == (True, STEER_EDIT, True, ALONE)
    # un autre compte : la ligne par défaut, en lecture seule ; dans un salon ou pour une inconnue, pas plus
    other = project_allowance(UNSET, UNSET_DEFAULT, CAMILLE, Kind.REPLY, wide)
    assert (other.see, other.steer, other.files, other.reads) == (True, STEER_READ, False, True)
    for aud in (ROOM, STRANGER):
        got = project_allowance(UNSET, UNSET_DEFAULT, aud, Kind.REPLY, wide)
        assert got.see and got.steer == STEER_READ and not got.files
    # le canal serre le pilotage : par Internet, lecture seule au plus — même pour toi
    canals = Canals(tables={"internet": CanalTable(lines=(CanalRule(who=(EVERYONE,), reply="seule", steer=STEER_READ),))})
    you_there = Audience(persons=("ext_1",), channel="discord", public=False, trust=ChannelTrust.ACCOUNT.value,
                         owner=True, person="user_1")
    assert project_allowance(UNSET, UNSET_DEFAULT, you_there, Kind.REPLY, Rights(canals=canals)).steer == STEER_READ
    assert project_allowance(UNSET, UNSET_DEFAULT, WORKING, Kind.WORK, wide).read == ALONE


def _spec(name: str, bundle: str = "memoire", **kw) -> ToolSpec:
    return ToolSpec("probe", name, "un outil", NS, lambda a, c: None, bundle, frozenset({Kind.REPLY, Kind.STEP}), **kw)


def test_a_family_is_born_from_what_its_tools_declare():
    everyone = _spec("memory_search")
    mine = _spec("email_read", "email", owner_only=True)
    lines, default = vital_family([everyone])
    assert [(a.who, a.canal) for a in lines] == [((OWNER,), ()), ((), (INTERNAL,)), ((EVERYONE,), ())]
    lines, default = vital_family([mine])
    assert [(a.who, a.canal) for a in lines] == [((OWNER,), ()), ((), (INTERNAL,))] and default.read == NO
    # une famille mêlée : tout le monde n'a que ce que rien ne réserve
    lines, _ = vital_family([_spec("rss_list", "rss"), _spec("rss_read", "rss", owner_only=True)])
    assert lines[2].who == (EVERYONE,) and lines[2].tools == ("rss_list",)
    tools = {s.name: s for s in (everyone, mine)}
    rights = Rights(canals=Canals())
    assert allowed(tools, everyone, CAMILLE, Kind.REPLY, rights).level == ALONE
    assert allowed(tools, mine, CAMILLE, Kind.REPLY, rights).level == NO
    assert allowed(tools, mine, YOU, Kind.REPLY, rights).level == ALONE
    assert allowed(tools, mine, WORKING, Kind.STEP, rights).level == ALONE
    # un tableau réglé remplace le minimum vital : ton courrier à Camille
    ruled = Rights(canals=Canals(), families={"email": NS(lines=(ToolRule(who=(PERSON + "user_2",), read=ALONE),),
                                                           default=ToolRule())})
    assert allowed(tools, mine, CAMILLE, Kind.REPLY, ruled).level == ALONE
    assert allowed(tools, mine, YOU, Kind.REPLY, ruled).level == NO
    # l'offre réglée suit l'outil : en main, ou à chercher
    core = frozenset({"autre"})
    assert deferred(everyone, core) and not deferred(everyone, core, Rights(in_hand={"memory_search": HAND}))
    assert deferred(mine, core, Rights(in_hand={"email_read": ASK}))


def test_the_canal_tables_of_your_accounts_and_their_vital_minimum():
    canals = Canals()
    assert vital("courrier").lines[0].reply == "accord" and not vital("courrier").lines[0].prepare
    assert vital("courrier:perso") == vital("courrier") and vital("web").lines[0].read == ALONE
    rule = mail_rule(canals, "perso", "lea@shop.fr")
    assert (rule.prepare, rule.reply) == (False, "accord")
    ruled = Canals(tables={"courrier:perso": CanalTable(lines=(
        CanalRule(who=("adresse:@shop.fr",), prepare=False, reply="non"),
        CanalRule(who=(EVERYONE,), prepare=True, reply="seule")))})
    assert mail_rule(ruled, "perso", "lea@shop.fr").reply == "non"
    assert mail_rule(ruled, "perso", "paul@ami.fr").prepare and mail_rule(ruled, "pro", "paul@ami.fr").reply == "accord"
    # à plusieurs : la plus serrée
    assert mail_rule_for_all(ruled, "perso", ["paul@ami.fr", "lea@shop.fr"]).reply == "non"
    teams = Canals(tables={"teams": CanalTable(lines=(CanalRule(who=("adresse:rh",), prepare=False, reply="brouillon"),
                                                     CanalRule(who=(EVERYONE,), prepare=True, reply="accord")))})
    assert teams_rule(teams, "", "19:abc", "Équipe RH", "Paul").reply == "brouillon"
    assert teams_rule(teams, "", "19:xyz", "Projet", "Paul").prepare


def test_a_table_form_is_read_at_once_and_refuses_what_is_unreadable():
    args = TableArgs(ligne={"2": "2", "1": "1"},
                     qui={"1|proprietaire": True, "1|personne:user_2": True, "2|tous": True},
                     canal={"1|mobile": True, "2|web:salon": True}, toujours={"1": True},
                     moments={"2|conversation": True}, tous={"1": True}, prend={"2|a": True})
    rows = args.rows(tools=True, lecture={"1": "seule"})
    assert [(r["who"], r["canal"], r["when"], r["tools"], r["lecture"]) for r in rows] == [
        ((OWNER, PERSON + "user_2"), (MOBILE,), (), (), "seule"), ((EVERYONE,), ("web:salon",), ("conversation",), ("a",), None)]
    with pytest.raises(ValueError, match="Ligne 1 : coche qui"):
        rows_sent({"1": "1"}, {"qui": {}, "canal": {}, "moments": {}}, {})
    with pytest.raises(ValueError, match="moment"):
        rows_sent({"1": "1"}, {"qui": {"1|tous": True}, "canal": {}, "moments": {}}, {})
    with pytest.raises(ValueError, match="outil"):
        rows_sent({"1": "1"}, {"qui": {"1|tous": True}, "canal": {}, "moments": {}, "prend": {}}, {}, {"1": True}, tools=True)
    with pytest.raises(ValueError, match="elle seule"):
        rows_sent({"1": "1"}, {"qui": {"1|tous": True}, "canal": {"1|interne": True}, "moments": {}}, {}, {"1": True})
    alone = rows_sent({"1": "1"}, {"qui": {}, "canal": {"1|interne": True}, "moments": {}}, {})
    assert alone[0]["who"] == () and alone[0]["canal"] == (INTERNAL,)
    rows = [ToolRule(who=(OWNER,)), ToolRule(who=(EVERYONE,))]
    assert moved(rows, "monter:2", ToolRule())[0] == rows[::-1]
    assert moved(rows, "ajouter", ToolRule(who=(CLOSE,)))[0][-1].who == (CLOSE,)
    assert moved(rows, "retirer:1", ToolRule())[0] == rows[1:]
    assert moved(rows, "", ToolRule())[1] == "Accès enregistrés."
    assert CARD in {k for k, _ in __import__("mika.vocab.access", fromlist=["POLICIES"]).POLICIES}
