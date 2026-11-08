"""Les apps suivent leur projet (ADR 0133), par leurs intentions.

- un outil d'app est offert selon la ligne d'accès de son projet qui le concerne : sa colonne « lecture » s'il ne fait
  que lire (``lit: true``), « action » sinon ; un projet jamais réglé : toi et elle qui travaille ; une app sans
  projet : toi et elle qui travaille ;
- sur accord, l'appel est proposé (``forge.call``) : rien ne part avant le oui ; accepté, ce qu'il a rendu revient
  comme un contenu (``forge.answered``), qu'elle dit à qui l'avait demandé ;
- « lit » se déclare par un booléen, rien d'autre.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from dataclasses import replace

from mika.adapters.forge.manifest import read_manifest
from mika.app.mindport import KernelPort
from mika.contracts import forge as forge_c
from mika.contracts import runtime as rt
from mika.kernel.events import Origin
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.plugins.forge import FORGE, calls, written_draft
from mika.plugins.forge.calls import _section, call_digest
from mika.runtime.tools import offer
from mika.vocab.access import OWNER, PERSON
from mika.vocab.episodes import PRO, Kind
from tests.fixtures.mika import connect
from tests.unit.test_forge_console import ADRIEN, needs_bwrap, run
from tests.unit.test_project_access import facing, set_access, talking
from tests.unit.test_projects import create, events

MANIFEST = """\
title: Cours
schedule: manual
tools:
  - name: cours
    description: Passer un ordre sur une action
    args:
      - {key: symbole, type: text, label: Symbole, required: true}
  - name: rien
    description: Lire le cours
    lit: true
"""
CODE = """\
def tool_cours(api, args):
    return {"ordre": args["symbole"]}


def tool_rien(api, args):
    return {"cours": 7300}
"""


def test_lit_is_declared_by_a_boolean():
    manifest, problems = read_manifest(MANIFEST)
    assert [(t["name"], t["lit"]) for t in manifest["tools"]] == [("cours", False), ("rien", True)]
    _, problems = read_manifest(MANIFEST.replace("lit: true", "lit: oui"))
    assert any("« lit » : true" in p for p in problems)


def test_the_forge_does_not_read_the_phrases_of_another_plugin():
    """Audit du 2026-11-05, K0-03 : elle lisait ``mcp.tools.*`` et ``mcp.section.*``. Ce que les deux partagent est dans
    ``approvals`` ; le reste est à elle."""
    keys = [node.args[0].value for node in ast.walk(ast.parse(inspect.getsource(calls)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "phrase"]
    assert keys and {key.split(".")[0] for key in keys} == {"forge", "approvals"}


def test_the_digest_of_an_app_call_already_journaled_does_not_change():
    """L'empreinte d'une carte en attente est au journal : relevée avant son passage au contrat, elle ne bouge pas."""
    call = {"app": "cours", "function": "tool_cours", "fingerprint": "f1", "args": {"symbole": "ACME"},
            rt.DECIDER: "user_1"}
    assert call_digest({**call, "tool": "cours_cours"}) == "fe075908c109f5c331c33ae15ce182f1"


@needs_bwrap
def test_her_apps_follow_the_access_of_their_project_and_on_approval_what_comes_back_is_told(tmp_path):
    async def scenario(kernel, forge, store):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Camille")
        pid = await create(kernel, "p1", title="La veille", objectives="Suivre les cours")
        await forge.write("cours", MANIFEST, CODE)
        await forge.write("solo", MANIFEST, CODE)
        await kernel.mind.append([written_draft(forge.info("cours"), project=pid), written_draft(forge.info("solo"))],
                                 emitter="forge", correlation="genese", origin=Origin.GENESIS)
        kernel.refresh_tools()
        camille = facing("user_2")
        policy = kernel.runner.policies[Kind.REPLY]

        def offered(audience) -> set[str]:
            return {n for n in offer(kernel.mind.registry.tools, policy, Kind.REPLY, audience,
                                     frame=kernel.mind.frame()) if n.startswith(("cours_", "solo_"))}

        out = {"before": (offered(ADRIEN), offered(camille))}
        await set_access(kernel, pid, {"who": [PERSON + "user_2"], "see": True, "read": "seule", "act": "carte"},
                         {"who": [OWNER], "see": True, "steer": "modification", "read": "seule", "act": "seule"}, nonce="a1")
        out["after"] = (offered(ADRIEN), offered(camille))

        async def as_camille(tool: str, **args):
            spec = kernel.mind.registry.tools[tool]
            return await spec.handler(spec.args(**args), talking(kernel, "user_2", camille, tool=tool))

        out["read"] = await as_camille("cours_rien")
        out["asked"] = await as_camille("cours_cours", symbole="AAPL")
        [pending] = [v for v in kernel.mind.frame().get(rt.PENDING_EFFECTS) if v.capability == forge_c.CALL]
        port = KernelPort(kernel)
        preview = await port.effect_preview(pending.proposal)
        out["preview"] = preview.text
        out["decider"] = json.loads(kernel.mind.frame().state("forge").calls[pending.proposal].args_json)[rt.DECIDER]
        out["answered_before"] = events(kernel, forge_c.ANSWERED)
        out["resolved"] = await port.resolve_effect(pending.proposal, True, by="user_2", seen=preview.digest)
        for _ in range(30):
            if events(kernel, forge_c.ANSWERED):
                break
            await asyncio.sleep(1)
        out["answered"] = events(kernel, forge_c.ANSWERED)
        mind = kernel.mind
        frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, camille,
                      talking(kernel, "user_2", camille).frame.episode)
        texts = {e.data.text.ref: e.data.text.text for e in out["answered"]}
        body = _section(frame.state("forge"), frame, {"calls": texts})
        out["section"] = str(body.content) if body is not None else ""
        return out

    out = run(tmp_path, scenario)
    adrien, camille = out["before"]
    # jamais réglé : toi, tout ; une app sans projet, toi seule
    assert {"cours_cours", "cours_rien", "solo_cours", "solo_rien"} <= adrien and camille == set()
    adrien, camille = out["after"]
    assert {"cours_cours", "cours_rien"} <= adrien and camille == {"cours_cours", "cours_rien"}  # pas « solo »
    assert out["read"].ok and "7300" in out["read"].content  # lecture : seule
    assert "Demandé, rien n'est encore parti" in out["asked"].content and out["answered_before"] == []
    assert out["decider"] == "user_2"  # une carte dans son chat : c'est elle qui accepte
    assert "Outil : cours_cours" in out["preview"] and '"symbole": "AAPL"' in out["preview"]
    [answered] = out["answered"]
    assert answered.data.ok and "AAPL" in answered.data.text.text and answered.data.about == ("user_2",)
    assert "« cours_cours » a rendu" in out["section"] and "AAPL" in out["section"]
    # sa demande est à elle (jamais citée comme venue d'ailleurs) ; ce que l'app a rendu est cité ; aucune consigne
    assert all(line.startswith("> ") for line in out["section"].splitlines() if "AAPL" in line)
    assert not any(line.startswith(">") for line in out["section"].splitlines() if "a rendu" in line)
    assert "Dis-le" not in out["section"]
    assert not next(s for s in FORGE.sections if s.key == "app_calls").untrusted


@needs_bwrap
def test_in_pro_mode_her_app_call_waits_for_the_card_and_hands_back_what_came_back(tmp_path):
    """ADR 0165 : en mode pro, l'appel d'app sur carte attend la décision dans la boucle ; accepté, l'outil rend ce que
    l'app a renvoyé, réputé dit avec sa réponse (sa provenance) — plus rien à annoncer ensuite."""
    async def scenario(kernel, forge, store):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Camille")
        pid = await create(kernel, "p1", title="La veille", objectives="Suivre les cours")
        await forge.write("cours", MANIFEST, CODE)
        await kernel.mind.append([written_draft(forge.info("cours"), project=pid)],
                                 emitter="forge", correlation="genese", origin=Origin.GENESIS)
        kernel.refresh_tools()
        camille = facing("user_2")
        await set_access(kernel, pid, {"who": [PERSON + "user_2"], "see": True, "read": "seule", "act": "carte"},
                         {"who": [OWNER], "see": True, "steer": "modification", "read": "seule", "act": "seule"},
                         nonce="a1")
        ctx = talking(kernel, "user_2", camille, tool="cours_cours")
        ctx.frame.episode = replace(ctx.frame.episode, attrs=FrozenDict({"mode": PRO}))
        spec = kernel.mind.registry.tools["cours_cours"]
        call = asyncio.ensure_future(spec.handler(spec.args(symbole="AAPL"), ctx))
        pending = []
        for _ in range(30):
            pending = [v for v in kernel.mind.frame().get(rt.PENDING_EFFECTS) if v.capability == forge_c.CALL]
            if pending:
                break
            await asyncio.sleep(1)
        out = {"waiting": not call.done()}
        port = KernelPort(kernel)
        preview = await port.effect_preview(pending[0].proposal)
        await port.resolve_effect(pending[0].proposal, True, by="user_2", seen=preview.digest)
        out["result"] = await asyncio.wait_for(call, 120)
        out["proposal"] = pending[0].proposal
        return out

    out = run(tmp_path, scenario)
    assert out["waiting"] is True
    result = out["result"]
    assert result.ok and "AAPL" in result.content and "« cours_cours » a rendu" in result.content
    assert result.provenance == (f"forge-call:{out['proposal']}",)
