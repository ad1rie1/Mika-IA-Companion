"""Les serveurs que ses plugins système apportent au client MCP (ADR 0066) — par leurs intentions :

- actif, le plugin ``web`` ajoute son serveur à la configuration de l'opérateur, lancé dans sa cage, réseau isolé,
  ses réglages dans l'environnement ; désactivé, il n'y est plus ;
- ses outils sont approuvés d'office, sur l'empreinte exacte de ce que le serveur proposera (la fonction même du
  client) : en lecture, sans accord ; un outil qui ne se dit pas en lecture attendrait l'opérateur ;
- l'opérateur ne range rien pour eux, et un serveur à lui du même nom s'efface ;
- des paramètres illisibles : aucun serveur système, rien d'offert ;
- le plugin est une faculté de la composition, avec ses paramètres dans la console.
"""

from __future__ import annotations

import asyncio

from mika.adapters.mcp.client import live_tool
from mika.adapters.mcp.config import McpConfig, McpServer, StoredReview
from mika.adapters.mcp.system import BY, Provided, SystemServers
from mika.app import composition, system_mcp
from mika.app.console import FACULTY_LABELS, PARAM_FAMILIES
from mika.kernel.clock import MINUTE, US
from mika.plugins import web
from mika.plugins.web import serveur


def _system(p: web.WebParams | None) -> SystemServers:
    return SystemServers(lambda: system_mcp.provided(lambda owner: p if owner == "web" else None))


OPERATOR = McpServer(purpose="la météo d'une ville", url="https://meteo.example/mcp")


def test_active_the_web_plugin_brings_its_server_into_the_mcp_client():
    cfg = _system(web.WebParams()).config(McpConfig(servers={"meteo": OPERATOR}))
    assert set(cfg.servers) == {"meteo", "web"}  # ajouté à ceux de l'opérateur, qui restent
    srv = cfg.servers["web"]
    assert srv.ready and srv.local and srv.network == "isole" and srv.command == "python3"
    assert srv.args == ("-I", str(web.server_path())) and srv.shared == (str(web.server_path().parent),)
    assert srv.in_conversation and srv.in_work and not srv.in_initiative and not srv.in_hand
    assert srv.audience == "proprietaire" and "DuckDuckGo" in srv.purpose


def test_disabled_it_is_gone():
    system = _system(web.WebParams(enabled=False))
    assert set(system.config(McpConfig(servers={"meteo": OPERATOR})).servers) == {"meteo"}
    assert system.reviews({}) == {}


def test_its_settings_reach_the_server_through_its_environment():
    p = web.WebParams(spacing_us=7 * US, searches_per_minute=5, parallel_pages=2, pause_us=30 * MINUTE,
                      cache_us=0, region="be-fr", safesearch="strict", call_timeout_us=60 * US, max_result_chars=5000)
    srv = _system(p).config(McpConfig()).servers["web"]
    env = dict(line.split("=", 1) for line in srv.env)
    assert serveur.Settings.from_env(env) == serveur.Settings(spacing_s=7, searches_per_minute=5, parallel_pages=2,
                                                              pause_s=1800, cache_s=0, region="be-fr",
                                                              safesearch="strict")
    assert srv.timeout_s == 60 and srv.max_result_chars == 5000


def test_its_tools_are_approved_on_what_the_server_will_say():
    p = web.WebParams(parallel_pages=3)
    reviews = _system(p).reviews({})["web"]
    listed = {t.remote: t for t in (live_tool(raw) for raw in serveur.tools(web.settings_of(p)))}
    assert set(reviews) == set(listed) == {"search", "read", "read_pages"}
    for name, review in reviews.items():
        assert review.fingerprint == listed[name].fingerprint  # l'empreinte que le client calculera
        assert review.enabled and review.nature == "lecture" and review.approval == "aucun" and review.by == BY
    assert set(_system(web.WebParams(parallel_pages=1)).reviews({})["web"]) == {"search", "read"}


def test_a_tool_that_does_not_say_it_only_reads_waits_for_the_operator():
    raw = {"name": "envoyer", "description": "envoie", "inputSchema": {"type": "object"}}
    system = SystemServers(lambda: {"x": Provided(OPERATOR, (raw,))})
    review = system.reviews({})["x"]["envoyer"]
    assert review.nature == "action" and review.approval == "operateur"


def test_the_operator_stores_nothing_for_it_and_its_name_wins():
    system = _system(web.WebParams())
    mine = StoredReview(fingerprint="f", enabled=True)
    theirs = {"meteo": {"prevoir": mine}, "web": {"search": StoredReview(fingerprint="ancien", enabled=False)}}
    merged = system.reviews(theirs)
    assert merged["meteo"] == {"prevoir": mine} and merged["web"]["search"].enabled  # le système l'emporte
    saved: list[dict] = []

    async def save(reviews):
        saved.append(reviews)

    asyncio.run(system.saving(save)(merged))
    assert saved == [{"meteo": {"prevoir": mine}}]  # rien de ce qui est calculé n'est rangé
    clash = system.config(McpConfig(servers={"web": OPERATOR}))
    assert clash.servers["web"].local  # le serveur de l'opérateur du même nom s'efface


def test_unreadable_parameters_mean_no_system_server():
    def broken():
        raise KeyError("paramètres")

    system = SystemServers(broken)
    assert system.config(McpConfig(servers={"meteo": OPERATOR})).servers == {"meteo": OPERATOR}
    assert system.reviews({}) == {} and system.names() == frozenset()


def test_the_plugin_is_part_of_her_and_its_settings_have_a_page():
    assert web.WEB in composition.faculties()
    assert web.WEB.params is web.WebParams and "web" in system_mcp.OWNERS
    assert FACULTY_LABELS["web"] == "Recherche web" and any("web" in names for _f, names in PARAM_FAMILIES)
    assert web.WebParams().enabled  # actif d'office : c'est un outil système
