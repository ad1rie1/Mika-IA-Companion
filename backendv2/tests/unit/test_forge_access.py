"""Les apps suivent leur projet (ADR 0133), par leurs intentions.

- un outil d'app est offert selon la ligne d'accès de son projet qui le concerne : sa colonne « lecture » s'il ne fait
  que lire (``lit: true``), « action » sinon ; un projet jamais réglé : toi et elle qui travaille ; une app sans
  projet : toi et elle qui travaille ;
- sur accord, l'appel est proposé (``forge.call``) : rien ne part avant le oui ; accepté, ce qu'il a rendu revient
  comme un contenu (``forge.answered``), qu'elle dit à qui l'avait demandé ;
- ce qu'elle en garde (la ligne d'accès) tient seule comme sur accord : la réponse journalisée à sa sensibilité, la
  section, la carte attendue et une page lue seule en portent le plancher, comme pour un service (ADR 0128) ;
- « lit » se déclare par un booléen, rien d'autre.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from dataclasses import replace
from types import SimpleNamespace

from mika.adapters.forge.manifest import read_manifest
from mika.app.mindport import KernelPort
from mika.contracts import forge as forge_c
from mika.contracts import runtime as rt
from mika.contracts.runtime import ANSWERED, REFUSED
from mika.kernel.events import Origin
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.plugins.forge import ACCESS_SET, FORGE, AppCall, calls, written_draft
from mika.plugins.forge.calls import _section, call_digest
from mika.runtime.tool_offer import offer
from mika.vocab.access import CLOSED_TOOLS, OWNER, PERSON, ToolRule
from mika.vocab.episodes import PRO, Kind
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import connect, effect_preview
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


PAGES_MANIFEST = MANIFEST + """\
views:
  - {key: cours, label: Le cours}
"""
PAGES_CODE = CODE + """

def view_cours(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "page du cours"}]}
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
        preview = await effect_preview(kernel, pending.proposal)
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
        preview = await effect_preview(kernel, pending[0].proposal)
        await port.resolve_effect(pending[0].proposal, True, by="user_2", seen=preview.digest)
        out["result"] = await asyncio.wait_for(call, 120)
        out["proposal"] = pending[0].proposal
        return out

    out = run(tmp_path, scenario)
    assert out["waiting"] is True
    result = out["result"]
    assert result.ok and "AAPL" in result.content and "« cours_cours » a rendu" in result.content
    assert result.provenance == (f"forge-call:{out['proposal']}",)


@needs_bwrap
def test_what_she_keeps_of_an_app_holds_on_approval_as_when_she_calls_it_alone(tmp_path):
    """Audit du 2026-11-05, K8-01 : approuvé par une carte, un outil d'app perdait ce que sa ligne d'accès dit d'en
    garder (la réponse revenait comme un souvenir personnel, sans plancher), et une page lue seule aussi. Comme pour
    un service (ADR 0128) : la demande porte ``keep`` (hors de l'empreinte), l'aperçu le dit, la réponse est
    journalisée à sa sensibilité, la section en porte le plancher."""
    async def scenario(kernel, forge, store):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Camille")
        await connect(kernel, "user_3", "Bruno")
        await forge.write("solo", PAGES_MANIFEST, PAGES_CODE)
        rows = (ToolRule(who=(PERSON + "user_2",), read="carte", act="carte", keep="rien"),
                ToolRule(who=(PERSON + "user_3",), read="carte", act="carte", keep="prive"),
                ToolRule(who=(OWNER,), read="seule", act="seule", keep="rien"))
        await kernel.mind.append([written_draft(forge.info("solo")),
                                  ACCESS_SET.draft(app="solo", rows=rows, default=CLOSED_TOOLS, by="user_1")],
                                 emitter="forge", correlation="genese", origin=Origin.GENESIS)
        kernel.refresh_tools()
        port = KernelPort(kernel)
        out, seen = {}, set()
        for handle, keep in (("user_2", "rien"), ("user_3", "prive")):
            audience = facing(handle)
            spec = kernel.mind.registry.tools["solo_cours"]
            asked = await spec.handler(spec.args(symbole="AAPL"), talking(kernel, handle, audience, tool="solo_cours"))
            [pending] = [v for v in kernel.mind.frame().get(rt.PENDING_EFFECTS)
                         if v.capability == forge_c.CALL and v.proposal not in seen]
            seen.add(pending.proposal)
            preview = await effect_preview(kernel, pending.proposal)
            await port.resolve_effect(pending.proposal, True, by=handle, seen=preview.digest)
            for _ in range(30):
                if len(events(kernel, forge_c.ANSWERED)) == len(seen):
                    break
                await asyncio.sleep(1)
            answered = events(kernel, forge_c.ANSWERED)[-1]
            mind = kernel.mind
            frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, audience,
                          talking(kernel, handle, audience).frame.episode)
            body = _section(frame.state("forge"), frame, {"calls": {answered.data.text.ref: answered.data.text.text}})
            out[keep] = {"asked": asked, "call": frame.state("forge").calls[pending.proposal], "preview": preview.text,
                         "answered": answered, "section": body}
        spec = kernel.mind.registry.tools["solo_pages"]
        out["pages"] = await spec.handler(spec.args(), talking(kernel, "user_1", ADRIEN, tool="solo_pages"))
        return out

    out = run(tmp_path, scenario)
    confidence = int(Sensitivity.CONFIDENCE)
    for keep, said in (("rien", "rien"), ("prive", "une confidence")):
        got = out[keep]
        assert "Demandé, rien n'est encore parti" in got["asked"].content
        assert got["call"].keep == keep and got["call"].status == ANSWERED
        assert f"Ce qu'elle en gardera : {said}" in got["preview"]
        answered = got["answered"]
        assert answered.data.ok and "AAPL" in answered.data.text.text
        assert answered.data.text.level == confidence  # plus jamais « personnel » quoi qu'en dise la ligne
        assert got["section"] is not None and got["section"].floor == confidence
        assert got["section"].unkept is (keep == "rien")
    pages = out["pages"]  # toi, seule, une ligne qui ne garde rien
    assert pages.ok and "page du cours" in pages.content and pages.proof is False
    assert pages.floor == confidence and pages.unkept is True
    # ce qu'elle en garde voyage avec la demande, hors de ce qu'on accepte : l'empreinte ne bouge pas
    call = {"app": "cours", "function": "tool_cours", "fingerprint": "f1", "args": {"symbole": "ACME"},
            rt.DECIDER: "user_1", "tool": "cours_cours"}
    assert call_digest({**call, "keep": "rien"}) == call_digest(call)


def test_a_card_awaited_in_pro_mode_hands_back_what_she_keeps_of_what_came_back():
    """Audit du 2026-11-05, K8-01 : la carte attendue dans la boucle (ADR 0165) rend ce que l'app a rendu avec son
    plancher, comme un service ; rien n'est parti, rien à garder ; une demande d'avant (sans ``keep``) : sans
    plancher, comme avant."""
    r = AppCall(proposal=7, app="solo", tool="solo_cours", target="user_2", approval="conversation", at=0, expires=0,
                keep="rien", status=ANSWERED)
    ctx = SimpleNamespace(ports={})
    got = calls._decided(r, ctx)
    assert got.ok and got.unkept is True and got.floor == int(Sensitivity.CONFIDENCE)
    kept = calls._decided(replace(r, keep="prive"), ctx)
    assert kept.floor == int(Sensitivity.CONFIDENCE) and kept.unkept is False
    refused = calls._decided(replace(r, status=REFUSED), ctx)
    assert not refused.ok and refused.floor == 0 and refused.unkept is False
    before = calls._decided(replace(r, keep=""), ctx)
    assert before.floor == 0 and before.unkept is False
