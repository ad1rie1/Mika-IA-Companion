"""Où elle est dans sa chambre, par ses intentions.

- c'est elle qui décide d'y aller : l'outil ``move_to`` est en main dans une
  conversation ordinaire, et l'appeler la déplace (un événement, un fait, un
  état poussé aux écrans sans parole) ;
- piloté par un modèle, il ne lui fait pas faire n'importe quoi : un lieu
  inventé est refusé avant d'écrire quoi que ce soit, y aller quand elle y est
  déjà n'écrit rien, un seul déplacement par épisode ;
- le sommeil la met au lit (au rejeu aussi) ; éveillée, son prompt dit où elle
  est, endormie il se tait ;
- les écrans lisent le lieu dans l'état intérieur.
"""

from __future__ import annotations

from collections.abc import Callable

from mika.adapters.web import protocol
from mika.contracts import body as body_c
from mika.contracts import place as c
from mika.faculties.place import _where
from mika.kernel.events import Origin
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said


def _calling(*calls: dict) -> Callable[[LLMRequest], LLMResponse]:
    """Une passerelle qui demande ces appels de ``move_to``, un par tour d'outils, puis répond."""
    queue = list(calls)

    def respond(req: LLMRequest) -> LLMResponse:
        if queue and any(t.name == "move_to" for t in req.tools):
            call = queue.pop(0)
            return LLMResponse("", (ToolCall(f"t{len(queue)}", "move_to", call),), stop="tool_use")
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    return respond


def _run(tmp_path, respond, script):
    kernel, clock, llm, deliveries = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))
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
    return kernel, out, deliveries, llm


async def _talk(kernel, out, text="Tu peux aller voir à la fenêtre ?"):
    await connect(kernel, "user_1", "Adrien", operator=True)
    await (await kernel.perceive(said("user_1", text))).reply


async def _nothing(kernel, out):
    return None


def test_she_starts_in_the_middle_of_her_room(tmp_path):
    _, out, _, _ = _run(tmp_path, lambda req: LLMResponse("Salut. [EMOTION:happy:0.4]"), _nothing)
    assert out["frame"].get(c.PLACE) == c.Place.CENTER


def test_move_to_is_in_hand_and_moves_her(tmp_path):
    offered: list[set[str]] = []
    inner = _calling({"place": "window"})

    def respond(req: LLMRequest) -> LLMResponse:
        if req.meta.get("target"):
            offered.append({t.name for t in req.tools})
        return inner(req)

    _, out, deliveries, _ = _run(tmp_path, respond, _talk)
    assert offered and "move_to" in offered[0]  # en main, pas à chercher dans un catalogue
    assert out["frame"].get(c.PLACE) == c.Place.WINDOW
    assert any(d.kind == "state" for d in deliveries.items), "l'écran doit recevoir l'état"
    assert protocol.inner_state(out["frame"], "user_1")["place"] == "window"


def test_an_invented_place_is_refused_and_nothing_moves(tmp_path):
    _, out, _, _ = _run(tmp_path, _calling({"place": "garden"}), lambda k, o: _talk(k, o, "Va dans le jardin !"))
    assert out["frame"].get(c.PLACE) == c.Place.CENTER


def test_going_where_she_already_is_writes_nothing(tmp_path):
    _, out, _, _ = _run(tmp_path, _calling({"place": "center"}), lambda k, o: _talk(k, o, "Reste là."))
    assert out["frame"].get(c.PLACE) == c.Place.CENTER
    assert out["frame"].get(c.SINCE) == 0


def test_one_move_per_episode(tmp_path):
    _, out, _, _ = _run(tmp_path, _calling({"place": "window"}, {"place": "door"}),
                        lambda k, o: _talk(k, o, "Fenêtre, puis porte, puis…"))
    assert out["frame"].get(c.PLACE) == c.Place.WINDOW


def test_falling_asleep_puts_her_to_bed(tmp_path):
    async def script(kernel, out):
        await kernel.mind.append([body_c.FELL_ASLEEP.draft(at=kernel.deps.clock.now(), pressure=1.0)],
                                 emitter="body", correlation="test:sleep", origin=Origin.EXTERNAL)

    _, out, _, _ = _run(tmp_path, lambda req: LLMResponse("…"), script)
    assert out["frame"].get(c.PLACE) == c.Place.BED


def test_the_prompt_says_where_she_is_while_awake(tmp_path):
    _, out, _, _ = _run(tmp_path, _calling({"place": "desk"}), lambda k, o: _talk(k, o, "Assieds-toi à ton bureau."))
    frame = out["frame"]
    text = _where(frame.state("place"), frame, None)
    assert text is not None and "bureau" in text
