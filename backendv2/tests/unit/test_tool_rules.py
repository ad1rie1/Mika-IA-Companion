"""Ses outils réglés par un opérateur, situation par situation (ADR 0122) — par leurs intentions.

- une règle ne fait que restreindre : « retiré » ôte un outil à la porte d'offre, « en main » et « à la demande »
  le rangent autrement, et rien ne donne un outil que le code n'offre pas ;
- un outil qui clôt la boucle (rendre compte d'un pas) ne se règle pas ;
- les situations de la console sont celles que le pipeline reconnaît à un épisode ;
- un vrai épisode n'en voit plus le schéma, et l'outil retiré ne s'exécute pas ;
- les règles se gardent dans les réglages, et se relisent à l'ouverture.
"""

from __future__ import annotations

import pytest

from mika.adapters.store_sql import SqlStore
from mika.app.settings import SecretBox, Settings
from mika.inspector.pages import tools as page
from mika.kernel.faculty import ToolSpec
from mika.ports.llm import LLMRequest, LLMResponse
from mika.runtime.tools import ASK, HAND, OFF, SITUATIONS, catalogue, declare, deferred, offer, situation_of
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said


def _spec(name: str, bundle: str = "memory", **kw) -> ToolSpec:
    return ToolSpec(owner="memory", name=name, description=f"{name} fait une chose", args=None, handler=None, schema={"type": "object"},
                    bundle=bundle, episodes=frozenset({"reply"}), **kw)


def test_a_rule_only_restricts():
    tools = {"lire": _spec("lire"), "chercher": _spec("chercher", bundle="web")}
    policy = page.SITUATIONS[0]
    kernel_policy = type("P", (), {"tool_bundles": frozenset({"memory"}), "core_bundles": frozenset({"memory"})})()
    audience = policy.audience
    # « chercher » n'est pas dans les lots de la politique : aucune règle ne le donne
    got = offer(tools, kernel_policy, "reply", audience, rules={"chercher": HAND, "lire": ASK})
    assert set(got) == {"lire"}
    assert set(offer(tools, kernel_policy, "reply", audience, rules={"lire": OFF})) == set()
    core = frozenset({"memory"})
    assert not deferred(tools["lire"], core) and deferred(tools["lire"], core, {"lire": ASK})
    assert deferred(tools["chercher"], core) and not deferred(tools["chercher"], core, {"chercher": HAND})
    assert not deferred(tools["lire"], None, {"lire": ASK})  # tout en main : la règle ne range rien
    decl = {d.name: d.deferred for d in declare(list(tools.values()), core, {"lire": ASK, "chercher": HAND})}
    assert decl == {"lire": True, "chercher": False}
    said_ = catalogue(list(tools.values()), core, {"memory": "sa mémoire", "web": "le web"}, {"lire": ASK})
    assert "sa mémoire" in said_  # rangé à la demande, son lot se dit au catalogue


def test_a_tool_that_closes_the_loop_is_not_ruled():
    report = _spec("report_step", bundle="goals", ends_loop=True)
    policy = type("P", (), {"tool_bundles": frozenset({"goals"}), "core_bundles": frozenset({"goals"})})()
    got = offer({"report_step": report}, policy, "reply", page.SITUATIONS[0].audience, rules={"report_step": OFF})
    assert "report_step" in got and not deferred(report, frozenset({"goals"}), {"report_step": ASK})


def test_the_console_situations_are_the_ones_the_pipeline_knows():
    assert tuple(s.key for s in page.SITUATIONS) == SITUATIONS
    for s in page.SITUATIONS:
        assert situation_of(s.kind, s.audience) == s.key, s.key


def test_a_removed_tool_is_neither_shown_nor_run(tmp_path):
    offered: list[set[str]] = []

    def respond(req: LLMRequest) -> LLMResponse:
        if req.meta.get("target"):
            offered.append({t.name for t in req.tools})
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    ruled = {"proprietaire": {"memory_search": OFF}}
    kernel, clock, _, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0),
                                tool_rules=lambda situation: ruled.get(situation, {}))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Salut, tu fais quoi ?"))).reply
            ruled.clear()
            await (await kernel.perceive(said("user_1", "Et maintenant ?"))).reply
            await kernel.lanes.join()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    assert "memory_search" not in offered[0] and "memory_search" in offered[-1]


async def test_the_rules_are_kept_and_read_back(tmp_path):
    store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    box = SecretBox.for_data(tmp_path)
    try:
        settings = Settings(store, box)
        await settings.open()
        await settings.save_tool_rules("salon", {"draw": OFF, "memory_search": ASK})
        await settings.save_tool_rules("salon", {"memory_search": None})
        with pytest.raises(ValueError):
            await settings.save_tool_rules("ailleurs", {"draw": OFF})
        with pytest.raises(ValueError):
            await settings.save_tool_rules("salon", {"draw": "partout"})
        again = Settings(store, box)
        await again.open()
        assert again.tool_rules_for("salon") == {"draw": OFF} and again.tool_rules_for("proprietaire") == {}
    finally:
        await store.close()
