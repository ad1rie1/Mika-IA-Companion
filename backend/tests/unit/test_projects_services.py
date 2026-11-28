"""Un service branché se donne à un projet (ADR 0254).

Les outils d'un projet étaient une liste fixe de cases : un service MCP branché par l'opérateur pouvait servir à un
réveil par API, jamais à un projet. « Ses outils » propose une case par service branché ; cochée, les outils du
service sont offerts à ses exécutions — tant que les lignes d'accès du service la laissent s'en servir seule, au
travail. Un service débranché depuis se décoche encore."""

from __future__ import annotations

from mika.app.composition import policies
from mika.contracts import mcp as mcp_c
from mika.faculties.identity import audience_for
from mika.faculties.projects.actions import service_knob
from mika.faculties.projects.faculty import REFRAMED, run_bundles
from mika.faculties.projects.inspect import _tools_words
from mika.ports.mcp import Access
from mika.runtime.operations import dynamic_fields, perform
from mika.runtime.pipeline import EpisodeRequest
from mika.vocab.access import OWNER
from mika.vocab.episodes import Kind, project_target
from tests.unit.test_mcp_plugin import NAME, FakePort, live, offered_tool
from tests.unit.test_projects import create, events, form

WORK = frozenset({"travail"})
CLOSED = "mcp_cms_publier"


def _port() -> FakePort:
    """Deux services branchés : la météo, qu'elle peut appeler seule au travail ; un CMS que seule sa propriétaire
    ouvre, en conversation — aucune ligne ne le lui laisse au travail."""
    return FakePort(offered_tool(episodes=WORK),
                    offered_tool(server="cms", remote="publier", name=CLOSED, episodes=WORK, nature="action",
                                 purpose="publier une page", access=(Access(who=(OWNER,), read="seule", act="seule"),)))


def _project(kernel, pid: int):
    return kernel.mind.frame().state("projects").projects[pid]


def _offered(kernel, pid: int) -> set[str]:
    """Les outils venus d'un service qu'une exécution de ce projet aurait en main."""
    frame = kernel.mind.frame()
    audience = audience_for(frame, EpisodeRequest(kind=Kind.WORK, target=project_target(pid)))
    only = ",".join(run_bundles(_project(kernel, pid)))
    got = kernel.runner._tools(policies()[Kind.WORK], Kind.WORK, audience, only, frame)
    return {name for name in got if name.startswith("mcp_")}


def _fields(kernel, pid: int) -> dict[str, str]:
    spec = kernel.registry.actions["projects.outils"]
    return {f.path: f.label for f in dynamic_fields(kernel, spec, str(pid), {})}


async def _tick(kernel, pid: int, nonce: str, **values: str):
    return await perform(kernel, "projects.outils", form(**values), by="user_1", subject=str(pid), nonce=nonce)


def test_the_contract_tells_a_plugged_service_from_her_own_web():
    assert mcp_c.is_service("mcp.meteo") and mcp_c.service_of("mcp.meteo") == "meteo"
    assert not mcp_c.is_service(mcp_c.WEB_BUNDLE)  # le web est à elle : il a sa case
    assert not mcp_c.is_service("memory") and not mcp_c.is_service("mcpx.meteo")
    assert service_knob("mcp.meteo") == "service_meteo"


def test_a_plugged_service_is_a_box_to_tick_and_its_tools_reach_the_runs(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Site", objectives="Publier un article")
        out = {"fields": _fields(kernel, pid), "before": _offered(kernel, pid)}
        out["ticked"] = await _tick(kernel, pid, "t1", tool_memory="on", service_meteo="on", service_cms="on")
        out["bundles"] = _project(kernel, pid).bundles
        out["after"] = _offered(kernel, pid)
        out["words"] = _tools_words(_project(kernel, pid))
        out["same"] = await _tick(kernel, pid, "t2", tool_memory="on", service_meteo="on", service_cms="on")
        out["unticked"] = await _tick(kernel, pid, "t3", tool_memory="on")
        out["end"] = (_project(kernel, pid).bundles, _offered(kernel, pid))
        out["reframed"] = [e.data.bundles for e in events(kernel, REFRAMED) if e.data.project == pid]
        return out

    out = live(tmp_path, scenario, _port())
    # une case par service branché, à côté des cases des lots du code
    assert out["fields"]["service_meteo"] == "Le service « meteo »" and "service_cms" in out["fields"]
    assert {"tool_memory", "tool_web", "tool_forge"} <= set(out["fields"]) and "service_web" not in out["fields"]
    assert out["before"] == set()  # pas coché : rien d'un service n'arrive à l'exécution
    assert out["ticked"].ok, out["ticked"]
    assert {"mcp.meteo", "mcp.cms"} <= set(out["bundles"]) and {"projects", "workshop", "memory"} <= set(out["bundles"])
    # coché et ouvert au travail : offert ; coché mais fermé par ses lignes d'accès : pas offert
    assert out["after"] == {NAME} and CLOSED not in out["after"]
    assert "le service « meteo »" in out["words"]
    assert not out["same"].ok  # rien n'a changé
    assert out["unticked"].ok and out["end"] == (("projects", "workshop", "memory"), set())
    assert len(out["reframed"]) == 2


def test_an_unplugged_service_can_still_be_unticked(tmp_path):
    port = _port()

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Site", objectives="Publier un article")
        await _tick(kernel, pid, "t1", tool_memory="on", service_meteo="on")
        port.tools = []  # l'opérateur le débranche
        kernel.refresh_tools()
        fields, offered = _fields(kernel, pid), _offered(kernel, pid)
        kept = await _tick(kernel, pid, "t2", tool_memory="on", tool_rss="on", service_meteo="on")
        between = _project(kernel, pid).bundles
        gone = await _tick(kernel, pid, "t3", tool_memory="on", tool_rss="on")
        return fields, offered, kept, between, gone, _project(kernel, pid).bundles, _fields(kernel, pid)

    fields, offered, kept, between, gone, bundles, after = live(tmp_path, scenario, port)
    assert fields["service_meteo"] == "Le service « meteo » (débranché)" and "service_cms" not in fields
    assert offered == set()  # plus aucun outil : le lot reste, vide
    assert kept.ok and "mcp.meteo" in between  # changer autre chose ne le retire pas
    assert gone.ok and "mcp.meteo" not in bundles and "service_meteo" not in after  # décoché : il disparaît


def test_a_box_for_a_service_that_was_never_plugged_is_ignored(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Site", objectives="Publier un article")
        got = await _tick(kernel, pid, "t1", tool_memory="on", tool_rss="on", service_inconnu="on")
        return got, _project(kernel, pid).bundles

    got, bundles = live(tmp_path, scenario, _port())
    assert got.ok and not [b for b in bundles if mcp_c.is_service(b)]
