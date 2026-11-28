"""Elle sait où est la personne qui lui parle, quand son téléphone le lui dit (ADR 0119), par ses intentions.

- ce que le téléphone dit s'écrit au journal, coordonnées et lieu en contenus personnels (l'adresse et la personne
  pour sujets) ; elle le regarde par ``location_where`` et lit le lieu, les coordonnées, la précision, l'âge ;
- seulement en tête-à-tête, avec quelqu'un qui a un compte, et seulement sa position à elle : jamais celle d'une
  autre, jamais en salon, jamais à un inconnu, jamais dans une initiative (l'outil n'y est même pas offert) ;
- couper le partage efface sa dernière position ; oublier la personne l'efface aussi (contenus et tranche) ;
- un regard se voit : son message emporte la référence de la position regardée, le fil la garde, le port en fait
  une petite bulle (le lieu, de quand il datait), la trame ``speech`` et l'historique la portent ;
- ce n'est pas un fichier : la notification ne le compte pas.
"""

from __future__ import annotations

import asyncio

from mika.adapters.web import protocol
from mika.app.composition import policies
from mika.app.mindport import KernelPort
from mika.contracts import location as c
from mika.contracts import runtime as rt
from mika.contracts.entry import MessageNote
from mika.faculties.identity import audience_for
from mika.kernel.clock import MINUTE
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import boot, build, connect, said
from tests.unit.test_shares import call, journal

LYON = {"lat": 45.764043, "lon": 4.835659, "accuracy_m": 12, "label": "Rue de la République, Lyon", "age_ms": 0}


def quiet(req: LLMRequest) -> LLMResponse:
    return LLMResponse("D'accord.")


def live(tmp_path, scenario, *, respond=quiet):
    kernel, clock, llm, deliveries = build(tmp_path, respond, arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            return await scenario(kernel, llm, deliveries)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_the_phone_says_where_and_she_reads_it_for_that_person(tmp_path):
    async def scenario(kernel, llm, deliveries):
        port = KernelPort(kernel)
        seq = await port.locate("user_1", **{**LYON, "age_ms": 3 * 60_000})
        mine = await call(kernel, "location_where", "user_1")
        theirs = await call(kernel, "location_where", "user_2")  # Béa n'a rien partagé : pas la position d'Adrien
        return seq, mine, theirs, journal(kernel, c.LOCATED)

    seq, mine, theirs, [located] = live(tmp_path, scenario)
    assert located.seq == seq and located.data.handle == "user_1" and located.data.person == "user_1"
    assert located.data.coords.text == "45.764043,4.835659" and located.data.label.text == LYON["label"]
    assert located.data.coords.level == located.data.label.level == int(Sensitivity.PERSONAL)
    assert mine.ok and mine.attach == (c.note_ref(seq),)
    assert "Rue de la République, Lyon" in mine.content and "45.764043, 4.835659" in mine.content
    assert "à 12 m près" in mine.content and "3 min" in mine.content
    assert theirs.ok and theirs.content == phrase("location.tools.where.unknown") and theirs.attach == ()


def test_without_a_place_name_nor_accuracy_she_still_reads_the_coordinates(tmp_path):
    async def scenario(kernel, llm, deliveries):
        await KernelPort(kernel).locate("user_1", lat=-33.8688, lon=151.2093, accuracy_m=0, label="", age_ms=0)
        return await call(kernel, "location_where", "user_1")

    got = live(tmp_path, scenario)
    assert phrase("location.tools.where.unnamed") in got.content and "-33.868800, 151.209300" in got.content
    assert phrase("location.tools.where.accuracy_unknown") in got.content


def test_only_one_to_one_with_someone_who_has_an_account(tmp_path):
    async def scenario(kernel, llm, deliveries):
        await connect(kernel, "web_inconnu", "Zoé", authenticated=False)
        await KernelPort(kernel).locate("user_1", **LYON)
        frame = kernel.mind.frame()
        private = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="user_1"))
        room = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="user_1", room="salon"))
        stranger = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="web_inconnu"))
        pols = policies()
        offered = {name: "location_where" in kernel.runner._tools(pols[kind], kind, aud)
                   for name, kind, aud in (("privé", Kind.REPLY, private), ("initiative", Kind.INITIATIVE, private),
                                           ("salon", Kind.REPLY, room), ("inconnu", Kind.REPLY, stranger))}
        in_room = await call(kernel, "location_where", "user_1", audience=room)
        to_stranger = await call(kernel, "location_where", "web_inconnu", audience=stranger)
        return offered, in_room, to_stranger

    offered, in_room, to_stranger = live(tmp_path, scenario)
    assert offered == {"privé": True, "initiative": False, "salon": False, "inconnu": False}
    for refused in (in_room, to_stranger):
        assert not refused.ok and refused.content == phrase("location.tools.where.not_here") and refused.attach == ()


def test_stopping_the_share_clears_the_last_position(tmp_path):
    async def scenario(kernel, llm, deliveries):
        port = KernelPort(kernel)
        nothing = await port.unlocate("user_1")  # rien à effacer : rien d'écrit
        await port.locate("user_1", **LYON)
        cleared = await port.unlocate("user_1")
        again = await port.unlocate("user_1")
        return nothing, cleared, again, await call(kernel, "location_where", "user_1"), journal(kernel, c.CLEARED)

    nothing, cleared, again, got, events = live(tmp_path, scenario)
    assert nothing is None and cleared is not None and again is None and [e.seq for e in events] == [cleared]
    assert got.content == phrase("location.tools.where.unknown") and got.attach == ()


def test_forgetting_the_person_erases_her_position(tmp_path):
    async def scenario(kernel, llm, deliveries):
        port = KernelPort(kernel)
        seq = await port.locate("user_1", **LYON)
        before = port.notes([c.note_ref(seq)])
        await kernel.mind.forget("user_1")
        return (before, port.notes([c.note_ref(seq)]), await call(kernel, "location_where", "user_1"),
                journal(kernel, c.LOCATED), kernel.mind.frame().state(c.OWNER))

    before, after, got, [located], state = live(tmp_path, scenario)
    assert [n.text for n in before] == [LYON["label"]]
    assert located.data.coords.text is None and located.data.label.text is None  # les contenus effacés
    assert [n.text for n in after] == [""]  # elle a regardé : ça reste vrai, sans plus dire où
    assert got.content == phrase("location.tools.where.unknown") and not state.fixes


ASKED = "tu sais où je suis là ?"
SAID = "Rue de la République ! Tu fais les boutiques ? [EMOTION:happy:0.5]"


def looking(req: LLMRequest) -> LLMResponse:
    if req.role != "reply":
        return LLMResponse("D'accord.")
    if not any(m.role == "tool" for m in req.messages) and any(ASKED in (m.content or "") for m in req.messages):
        return LLMResponse("", (ToolCall("c1", "location_where", {}),), stop="tool_use")
    return LLMResponse(SAID)


def test_her_message_carries_a_bubble_saying_she_looked(tmp_path):
    async def scenario(kernel, llm, deliveries):
        port = KernelPort(kernel)
        seq = await port.locate("user_1", **{**LYON, "age_ms": 2 * 60_000})
        report = await (await kernel.perceive(said("user_1", ASKED))).reply
        await asyncio.sleep(1)
        [utterance] = [e for e in journal(kernel, rt.UTTERANCE) if e.data.attachments]
        delivered = [d for d in deliveries.items if d.target == "user_1" and d.text][-1]
        history = [r for r in port.recent("user_1", 10) if r.role == "assistant"]
        notes = port.notes(utterance.data.attachments)
        now = kernel.mind.clock.now()
        return seq, report, utterance, delivered, history, notes, now

    seq, report, utterance, delivered, history, notes, now = live(tmp_path, scenario, respond=looking)
    ref = c.note_ref(seq)
    assert report.outcome.value == "done" and utterance.data.attachments == (ref,)
    assert delivered.attachments == (ref,) and history[-1].attachments == f'[{{"id": "{ref}"}}]'
    [note] = notes
    assert note == MessageNote(id=ref, kind="location", text=LYON["label"], at=note.at)
    assert 0 < now // 1000 - note.at <= 3 * MINUTE // 1000  # la mesure datait de deux minutes
    # la trame et l'historique la portent ; ce n'est pas un fichier
    speech = protocol.speech(delivered, notes=notes)
    item = protocol.history_item(history[-1], {}, notes={note.id: note})
    assert speech["notes"] == item["notes"] == [{"kind": "location", "text": LYON["label"], "at": note.at}]
    assert speech["attachments"] == item["attachments"] == []
    assert "notes" not in protocol.speech(delivered)


def test_a_frame_from_the_phone_is_validated_and_bounded():
    ok = protocol.where_fix({"lat": 45.7, "lon": 4.8, "accuracy": 8.6, "label": " Rue\nde la\x00 Paix ", "age_ms": 500})
    assert ok == protocol.Where(45.7, 4.8, 9, "Rue de la Paix", 500)
    for bad in ({"lat": 91, "lon": 0}, {"lat": 0, "lon": 181}, {"lat": True, "lon": 0}, {"lat": "45", "lon": 4},
                {"lat": float("nan"), "lon": 0}, {"lon": 4}, {"lat": 0, "lon": 0, "age_ms": protocol.WHERE_MAX_AGE_MS + 1}):
        assert protocol.where_fix(bad) is None, bad
    odd = protocol.where_fix({"lat": 0, "lon": 0, "accuracy": -3, "label": 42, "age_ms": -10})
    assert odd == protocol.Where(0.0, 0.0, 0, "", 0)
    assert len(protocol.where_fix({"lat": 0, "lon": 0, "label": "x" * 500}).label) == protocol.WHERE_LABEL_MAX
    paris, lyon = protocol.Where(48.8566, 2.3522, 0, "", 0), protocol.Where(45.764, 4.8357, 0, "", 0)
    assert 390_000 < protocol.where_moved(paris, lyon) < 395_000 and protocol.where_moved(paris, paris) == 0
