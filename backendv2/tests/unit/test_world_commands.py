"""Ce que le noyau fait des commandes d'un client du monde (ADR 0050), par ses intentions.

- un hôte qui a fini de jouer une action la fait terminer tout de suite, conclue par le noyau (pas crue sur
  parole) ; s'il n'y arrive pas, seul ce qui est vrai change — où est l'acteur, si l'endroit existe ;
- un constat d'un compte qui n'est pas opérateur, d'une action qui n'est plus en cours, ou d'un endroit qui
  n'existe pas : refusé, rien d'écrit ;
- ce que ce noyau ne sait pas encore faire est dit tel quel (``unsupported``), jamais inventé ;
- l'hôte et l'échéance ne terminent pas deux fois la même action.
"""

from __future__ import annotations

import asyncio

from mika.adapters.world import protocol
from mika.contracts import place as place_c
from mika.contracts import world as w
from mika.faculties.world import commands, plan, timing
from mika.kernel.events import Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build


def _run(tmp_path, script):
    kernel, clock, _, _ = build(tmp_path, lambda req: LLMResponse("…"), start=at_paris(2026, 9, 28, 15, 0))
    out: dict = {}

    async def main():
        await boot(kernel)
        try:
            await script(kernel, out)
            await kernel.lanes.join()
            out["frame"] = kernel.mind.frame()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    return kernel, out


async def _going_to_window(kernel) -> w.Intent:
    frame = kernel.mind.frame()
    s = frame.state("world")
    t = timing(None)
    steps = plan.plan_go(s.definition, t, s.actors, w.MIKA, "window")
    intent = plan.intent_of(w.MIKA, steps, frame.now, t, w.Cause(source=w.Source.MIKA, actor=w.MIKA), "i-test")
    await kernel.mind.append([w.INTENDED.draft(intent=intent)], emitter="world", correlation="test:geste",
                             origin=Origin.EXTERNAL)
    return intent


def _report(body) -> w.Report:
    return w.Report(cmd="r-1", report=body)


async def _submit(kernel, command, *, operator=True):
    frame = kernel.mind.frame()
    verdict = commands.handle(frame, command, actor="player:user_1", handle="user_1", operator=operator)
    commit = None
    if verdict.ok and verdict.drafts:
        commit = await kernel.mind.append(list(verdict.drafts), emitter="world", correlation="test:hote",
                                          origin=Origin.EXTERNAL, basis=frame.root, guard=verdict.guard)
    return verdict, commit


def _ends(kernel) -> int:
    return sum(1 for e in kernel.mind.store.read(after=0) if e.type == w.ENDED.name)


def test_l_hote_termine_plus_tot_et_le_noyau_conclut(tmp_path):
    async def script(kernel, out):
        intent = await _going_to_window(kernel)
        out["verdict"], _ = await _submit(kernel, _report(w.Finished(intent=intent.id, outcome=w.Outcome.DONE)))
        out["before_deadline"] = kernel.deps.clock.now() < intent.deadline
        out["me"] = kernel.mind.frame().get(w.SELF)

    _, out = _run(tmp_path, script)
    assert out["verdict"].ok and out["before_deadline"]
    assert (out["me"].place, out["me"].moving) == ("window", None)


def test_l_hote_n_y_arrive_pas_seul_ce_qui_est_vrai_change(tmp_path):
    async def script(kernel, out):
        intent = await _going_to_window(kernel)
        stuck = w.ActorMoved(actor=w.MIKA, room="bedroom", place="center")
        out["verdict"], _ = await _submit(kernel, _report(w.Finished(
            intent=intent.id, outcome=w.Outcome.FAILED, reason=w.Refusal.UNREACHABLE, at=stuck)))

    kernel, out = _run(tmp_path, script)
    assert out["verdict"].ok
    assert out["frame"].get(w.SELF).place == "center"
    assert out["frame"].get(place_c.PLACE) == place_c.Place.CENTER  # l'écran revient là où elle est vraiment
    assert _ends(kernel) == 1


def test_ce_qui_est_refuse_n_ecrit_rien(tmp_path):
    async def script(kernel, out):
        intent = await _going_to_window(kernel)
        done = _report(w.Finished(intent=intent.id, outcome=w.Outcome.DONE))
        out["guest"], _ = await _submit(kernel, done, operator=False)
        out["unknown"], _ = await _submit(kernel, _report(w.Finished(intent="i-perdu", outcome=w.Outcome.DONE)))
        nowhere = w.ActorMoved(actor=w.MIKA, room="garden")
        out["nowhere"], _ = await _submit(kernel, _report(w.Finished(intent=intent.id, outcome=w.Outcome.FAILED,
                                                                      at=nowhere)))
        someone = w.ActorMoved(actor="npc:moka", room="bedroom", place="center")
        out["someone"], _ = await _submit(kernel, _report(w.Finished(intent=intent.id, outcome=w.Outcome.FAILED,
                                                                      at=someone)))
        out["ends"] = _ends(kernel)

    _, out = _run(tmp_path, script)
    assert out["guest"].code is w.Refusal.NOT_HOST
    assert out["unknown"].code is w.Refusal.UNKNOWN
    assert out["nowhere"].code is w.Refusal.IMPLAUSIBLE
    assert out["someone"].code is w.Refusal.IMPLAUSIBLE
    assert out["ends"] == 0


def test_ce_que_le_noyau_ne_sait_pas_encore_faire_est_dit(tmp_path):
    async def script(kernel, out):
        out["act"], _ = await _submit(kernel, w.Act(cmd="a-1", action="ouvrir", object="window_pane"))
        out["progress"], out["progress_commit"] = await _submit(kernel, _report(w.Progress(intent="x", step=0)))

    _, out = _run(tmp_path, script)
    assert out["act"].code is w.Refusal.UNSUPPORTED and out["act"].message
    assert out["progress"].ok and out["progress_commit"] is None  # accepté, rien d'écrit


def test_l_hote_et_l_echeance_ne_terminent_pas_deux_fois(tmp_path):
    async def script(kernel, out):
        intent = await _going_to_window(kernel)
        await _submit(kernel, _report(w.Finished(intent=intent.id, outcome=w.Outcome.DONE)))
        await asyncio.sleep(30)  # l'échéance passe : rien à conclure, c'est déjà fait

    kernel, _ = _run(tmp_path, script)
    assert _ends(kernel) == 1


def test_les_commandes_du_fil_sont_celles_du_contrat():
    """Le port d'entrée reçoit les trames telles quelles : ce sont les types du contrat."""
    assert protocol.Act is w.Act and protocol.Report is w.Report and protocol.Finished is w.Finished
    frame = protocol.client_frame('{"type": "report", "cmd": "r-9", "report": {"kind": "loaded", "rev": 0}}')
    assert isinstance(frame, w.Report)
