"""La lecture des arguments d'une proposition d'effet (``contracts/runtime.py``) : une seule, totale.

Un réducteur est pur et total (ADR 0001) : une charge mal formée (un texte illisible, une liste JSON, une échéance
qui n'est pas un nombre) se lit comme une proposition sans arguments, elle ne le fait jamais lever.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mika.contracts import email as email_c
from mika.contracts import forge as forge_c
from mika.contracts import mcp as mcp_c
from mika.contracts import phone as phone_c
from mika.contracts import runtime as rt
from mika.contracts import teams as teams_c
from mika.kernel.events import Content
from mika.plugins import email as email_p
from mika.plugins import forge as forge_p
from mika.plugins import mcp as mcp_p
from mika.plugins import phone as phone_p
from mika.plugins import teams as teams_p
from mika.plugins.forge import calls as forge_calls
from mika.plugins.forge import install as forge_install


@pytest.mark.parametrize(("text", "expected"), [
    ('{"draft": "b1", "_expires": 5}', {"draft": "b1", "_expires": 5}),
    ("{pas du json", {}),
    ("[1, 2]", {}),
    ("null", {}),
    ('"une chaîne"', {}),
    ("", {}),
])
def test_proposal_args_reads_only_an_object(text, expected):
    assert rt.proposal_args(text) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("12", 12), ("abc", 0), (None, 0), (3, 3), ([1], 0), ({"a": 1}, 0), (float("inf"), 0), (float("nan"), 0),
])
def test_arg_int_never_raises(value, expected):
    assert rt.arg_int({"k": value}, "k") == expected


def test_arg_int_of_a_missing_key_is_zero():
    assert rt.arg_int({}, "k") == 0


def _proposed(capability: str, owner: str, args_json: str) -> SimpleNamespace:
    data = rt.EffectProposed(capability=capability, owner=owner, args_json=args_json, summary=Content.of("une demande"))
    return SimpleNamespace(seq=7, at=1_000, data=data)


MALFORMED = ["[1, 2]", json.dumps({"_expires": "abc"}), json.dumps({"_expires": [1]}), "{illisible", "null"]


@pytest.mark.parametrize("args_json", MALFORMED)
def test_the_forge_call_reducer_is_total(args_json):
    s = forge_calls._call_proposed(forge_p.ForgeState(), _proposed(forge_c.CALL, forge_p.FORGE.name, args_json), None)
    req = s.calls[7]
    assert req.expires == 0 and req.app == "" and req.args_json == args_json


@pytest.mark.parametrize("args_json", MALFORMED)
def test_the_mcp_call_reducer_is_total(args_json):
    s = mcp_p._proposed(mcp_p.McpState(), _proposed(mcp_c.CALL, mcp_c.OWNER, args_json), None)
    req = s.requests[7]
    assert req.expires == 0 and req.server == "" and req.args_json == args_json


@pytest.mark.parametrize("args_json", MALFORMED)
def test_the_other_proposal_reducers_are_total(args_json):
    """Les autres lecteurs d'une proposition passent par la même lecture : aucun ne lève."""
    assert forge_install._install_proposed(forge_p.ForgeState(),
                                           _proposed(forge_install.INSTALL, forge_p.FORGE.name, args_json),
                                           None).installs == {}
    assert phone_p._proposed(phone_p.PhoneState(), _proposed(phone_c.SEND, phone_c.OWNER, args_json), None) \
        == phone_p.PhoneState()
    assert teams_p._proposed(teams_p.TeamsState(), _proposed(teams_c.SEND, teams_c.OWNER, args_json),
                             None).drafts[7].expires == 0
    assert email_p._proposed(email_p.EmailState(), _proposed(email_c.SEND, email_c.OWNER, args_json),
                             None).drafts[7].draft == ""


def test_a_well_formed_call_is_read_as_before():
    args = {"app": "meteo", "tool": "prevision", "target": "user_1", "approval": "conversation", "keep": "toi",
            rt.EXPIRES: 42, "server": "srv", "request": "r1"}
    forge_req = forge_calls._call_proposed(
        forge_p.ForgeState(), _proposed(forge_c.CALL, forge_p.FORGE.name, json.dumps(args)), None).calls[7]
    mcp_req = mcp_p._proposed(mcp_p.McpState(), _proposed(mcp_c.CALL, mcp_c.OWNER, json.dumps(args)), None).requests[7]
    assert (forge_req.app, forge_req.tool, forge_req.expires, forge_req.keep) == ("meteo", "prevision", 42, "toi")
    assert (mcp_req.server, mcp_req.request, mcp_req.expires) == ("srv", "r1", 42)
