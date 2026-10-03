"""Le monde dans le noyau (ADR 0050), par ses intentions.

- ce qu'elle décide se fait : un trajet, ouvrir sa fenêtre, se mettre à regarder dehors — planifié, puis conclu
  à son échéance sans moteur pour le jouer ; son prompt dit ensuite ce qu'elle fait ;
- ce qu'elle invente ne s'écrit pas : un objet ou une action qui n'existe pas revient au modèle comme un refus
  qui dit ce qui se peut, et le journal n'en garde rien ;
- son corps a ses réflexes : endormie, elle finit allongée dans son lit ; réveillée, elle s'y assied ;
- le monde se rejoue : la tranche reconstruite depuis la genèse est celle qui a vécu ;
- une opératrice peut le changer : une édition passe sur la révision qu'elle a lue, les écrans en sont avertis.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from mika.contracts import body as body_c
from mika.contracts import world as w
from mika.faculties.world import _around
from mika.kernel.clock import US
from mika.kernel.codec import digest
from mika.kernel.events import Origin
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "monde" / "chambre.json"


def _calling(*calls: tuple[str, dict]) -> Callable[[LLMRequest], LLMResponse]:
    """Une passerelle qui fait ces appels d'outils, un par tour, puis répond."""
    queue = list(calls)
    results: list[str] = []

    def respond(req: LLMRequest) -> LLMResponse:
        results[:] = [m.content for m in req.messages if m.role == "tool"]
        if queue and any(t.name == queue[0][0] for t in req.tools):
            name, args = queue.pop(0)
            return LLMResponse("", (ToolCall(f"t{len(queue)}", name, args),), stop="tool_use")
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    respond.results = results  # type: ignore[attr-defined]
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
    return kernel, out, deliveries


def _talk(text: str, wait_s: float = 30) -> Callable:
    async def script(kernel, out):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await (await kernel.perceive(said("user_1", text))).reply
        await asyncio.sleep(wait_s)

    return script


def _types(kernel, name: str) -> list:
    return [e for e in kernel.mind.store.read(after=0) if e.type == name]


def test_un_trajet_se_conclut_a_son_echeance(tmp_path):
    kernel, out, _ = _run(tmp_path, _calling(("go_to", {"place": "window"})), _talk("Va voir dehors."))
    me = out["frame"].get(w.SELF)
    assert (me.place, me.posture, me.moving) == ("window", w.Posture.STAND, None)
    (ended,) = _types(kernel, w.ENDED.name)
    assert json.loads(ended.data)["outcome"] == "done"


def test_regarder_dehors_et_le_dire(tmp_path):
    _, out, _ = _run(tmp_path, _calling(("interact", {"object": "window_pane", "action": "regarder_dehors"})),
                     _talk("Qu'est-ce que tu vois dehors ?", wait_s=20))
    frame = out["frame"]
    me = frame.get(w.SELF)
    assert me.place == "window" and me.activity is not None and me.activity.name == "look_outside"
    assert "en train de regarder dehors" in (_around(frame.state("world"), frame, None) or "")


def test_ouvrir_sa_fenetre(tmp_path):
    _, out, _ = _run(tmp_path, _calling(("interact", {"object": "window_pane", "action": "ouvrir"})),
                     _talk("Il fait chaud, non ?"))
    state = out["frame"].get(w.STATE)
    assert next(o for o in state.objects if o.id == "window_pane").state == "open"


def test_s_asseoir_pour_dessiner(tmp_path):
    _, out, _ = _run(tmp_path, _calling(("interact", {"object": "writing_desk", "action": "dessiner"})),
                     _talk("Tu dessines un peu ?"))
    me = out["frame"].get(w.SELF)
    assert (me.place, me.posture) == ("desk", w.Posture.SIT)
    assert me.activity is not None and me.activity.name == "draw" and me.activity.until is None


def test_ce_qu_elle_invente_ne_s_ecrit_pas(tmp_path):
    respond = _calling(("interact", {"object": "window_pane", "action": "s_envoler"}),
                       ("interact", {"object": "piano", "action": "jouer"}))
    kernel, out, _ = _run(tmp_path, respond, _talk("Fais quelque chose d'impossible."))
    assert _types(kernel, w.INTENDED.name) == []
    said_back = " ".join(respond.results)  # type: ignore[attr-defined]
    assert "regarder_dehors" in said_back, "le refus dit ce qui se peut"
    assert "piano" in said_back


def test_endormie_elle_finit_allongee_dans_son_lit_puis_s_y_assied_au_reveil(tmp_path):
    async def script(kernel, out):
        now = kernel.deps.clock.now()
        await kernel.mind.append([body_c.FELL_ASLEEP.draft(at=now, pressure=1.0)], emitter="body",
                                 correlation="test:dodo", origin=Origin.EXTERNAL)
        await asyncio.sleep(60)
        out["asleep"] = kernel.mind.frame().get(w.SELF)
        await kernel.mind.append([body_c.WOKE.draft(at=kernel.deps.clock.now(), pressure=0.1)], emitter="body",
                                 correlation="test:debout", origin=Origin.EXTERNAL)

    _, out, _ = _run(tmp_path, lambda req: LLMResponse("…"), script)
    assert (out["asleep"].place, out["asleep"].posture, out["asleep"].moving) == ("bed", w.Posture.LIE, None)
    me = out["frame"].get(w.SELF)
    assert (me.place, me.posture) == ("bed", w.Posture.SIT)


def test_le_monde_se_rejoue(tmp_path):
    async def script(kernel, out):
        await _talk("Va voir dehors puis ouvre la fenêtre.", wait_s=30)(kernel, out)
        lived = kernel.mind.frame().root.slices["world"]
        await kernel.mind.rebuild(["world"])
        out["same"] = digest(lived) == digest(kernel.mind.frame().root.slices["world"])

    _, out, _ = _run(tmp_path, _calling(("interact", {"object": "window_pane", "action": "ouvrir"})), script)
    assert out["same"]


def test_une_operatrice_change_le_monde(tmp_path):
    example = w.WorldDef.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))

    async def script(kernel, out):
        current: w.WorldDef = kernel.mind.frame().get(w.DEFINITION)
        changes: list = [w.DefRemove(of=w.DefKind(item.kind), id=item.id)
                         for item in (*current.places, *current.archetypes, *current.objects, *current.rooms)
                         if not _has(example, item)]
        changes += [w.DefPut(item=item) for item in (*example.rooms, *example.places, *example.archetypes,
                                                      *example.objects, *example.actors)]
        await kernel.mind.append([w.AUTHORED.draft(base_rev=current.rev, changes=tuple(changes), by="user_1")],
                                 emitter="world", correlation="test:edition", origin=Origin.EXTERNAL)
        stale = w.DefRemove(of=w.DefKind.OBJECT, id="mug")
        await kernel.mind.append([w.AUTHORED.draft(base_rev=current.rev, changes=(stale,), by="user_1")],
                                 emitter="world", correlation="test:perimee", origin=Origin.EXTERNAL)

    _, out, deliveries = _run(tmp_path, lambda req: LLMResponse("…"), script)
    frame = out["frame"]
    defn = frame.get(w.DEFINITION)
    assert defn.rev == 1 and defn.room("living_room") is not None
    assert any(o.id == "mug" for o in frame.get(w.STATE).objects), "une édition sur une révision dépassée ne passe pas"
    assert frame.get(w.SELF).place == "center"  # ce qui a encore un sens ne bouge pas
    assert any(d.kind == "state" for d in deliveries.items), "les écrans sont avertis"


def _has(world: w.WorldDef, item) -> bool:
    finder = {"room": world.room, "place": world.place, "archetype": world.archetype, "object": world.object}
    return finder[item.kind](item.id) is not None


def test_les_durees_viennent_de_ses_reglages(tmp_path):
    """Un trajet de la fenêtre au milieu dure ce que dit la vitesse de marche (pas un nombre magique)."""
    _, out, _ = _run(tmp_path, _calling(("go_to", {"place": "window"})), _talk("Va voir dehors.", wait_s=0.5))
    me = out["frame"].get(w.SELF)
    assert me.moving is not None
    span = me.moving.eta - me.moving.started
    assert 3 * US < span < 5 * US  # ~3,4 m à 0,9 m/s


def test_autour_de_toi_ne_pose_pas_les_objets_sur_les_lieux():
    """« sur ton lit (`bed`) : ta sansevière » se lisait « la plante est sur le lit » : où aller et de quoi se
    servir sont deux listes, et la section reste courte (elle est dans chaque prompt)."""
    from mika.faculties.world import WorldParams, around, genesis

    text = around(genesis(), 0, WorldParams())
    assert "sur ton lit (`bed`) :" not in text and "→" not in text
    assert "Tu peux aller" in text and "de quoi te servir" in text
    assert "ta sansevière (`snake_plant`) : arroser" in text
    assert len(text.splitlines()) <= 4


def test_ce_qu_elle_a_vecu_se_lit(tmp_path):
    """Ses occupations, terminées ou en cours, sont un fait (``world.lived``) : son journal peut raconter sa
    journée sans l'inventer."""
    from mika.faculties.world import plan, timing

    async def intend(kernel, steps_of):
        frame = kernel.mind.frame()
        s = frame.state("world")
        intent = plan.intent_of(w.MIKA, steps_of(s), frame.now, timing(None),
                                w.Cause(source=w.Source.MIKA, actor=w.MIKA), f"i-{frame.now}")
        await kernel.mind.append([w.INTENDED.draft(intent=intent)], emitter="world", correlation="test:vecu",
                                 origin=Origin.EXTERNAL)

    async def script(kernel, out):
        await intend(kernel, lambda s: plan.plan_interact(s.definition, timing(None), s.actors, s.objects, w.MIKA,
                                                          "writing_desk", "dessiner"))
        await asyncio.sleep(600)
        out["drawing"] = kernel.mind.frame().get(w.LIVED)
        await intend(kernel, lambda s: plan.plan_go(s.definition, timing(None), s.actors, w.MIKA, "window"))
        await asyncio.sleep(30)

    _, out, _ = _run(tmp_path, lambda req: LLMResponse("…"), script)
    (current,) = out["drawing"]
    assert (current.name, current.label, current.until) == ("draw", "dessiner", None)  # en cours
    (done,) = out["frame"].get(w.LIVED)
    assert (done.name, done.object_label) == ("draw", "ton bureau")
    assert done.until is not None and done.until - done.since >= 590 * US
