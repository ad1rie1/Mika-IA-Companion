"""L'effort de réflexion d'une réponse, forcé par la personne (ADR 0287).

Son opératrice force l'effort de réflexion des réponses qu'elle reçoit : pour toute sa conversation, ou pour un fil de
travail. L'épisode qui lui répond le lit quand il compose et le pose sur sa requête (``LLMRequest.effort``) : il vaut
pour sa boucle d'outils, pas pour les autres appels (l'extraction, la seconde passe). Un fil en auto suit la
conversation ; la conversation en auto ne demande rien — le rôle décide (ADR 0285). Le contre-exemple de chaque règle :
sans réglage, ou hors d'une réponse à son message, rien n'est demandé.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mika.contracts import transcript as transcript_c
from mika.faculties import transcript
from mika.kernel import forms
from mika.kernel.clock import HOUR
from mika.ports.llm import LLMRequest, LLMResponse
from mika.runtime import operations
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind
from tests.fixtures.mika import SHIPPED, at_paris, boot, build, connect, said


def _life(tmp_path, script):
    """Une opératrice et ses messages (``script`` : une fonction qui les envoie) ; chaque appel au modèle, dans
    l'ordre."""
    calls: list[LLMRequest] = []

    def respond(req):
        calls.append(req)
        if req.role in ("reply", "pro"):
            return LLMResponse("Voilà." if req.role == "pro" else "D'accord ! [EMOTION:calm:0.3]")
        return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")

    kernel, clock, _llm, _deliveries = build(tmp_path, respond, start=at_paris(2026, 11, 21, 10, 0))
    seen: dict = {}

    async def main():
        await boot(kernel, SHIPPED)
        await connect(kernel, "user_1", "Adrien", operator=True)
        await asyncio.sleep(2 * HOUR / 1e6)
        await script(kernel, seen)
        await kernel.stop()

    run_virtual(clock, main)
    return seen, calls


async def _ask(kernel, text: str, **kw):
    got = await kernel.perceive(said("user_1", text, **kw))
    return await got.reply


async def _force(kernel, effort: str, strand: str = "", by: str = "user_1"):
    """Le geste du chat : l'action de la console, au nom de celle qui règle (« auto » : plus rien de forcé)."""
    form = {"strand": [strand], operations.FIXED_FIELD: ["strand"], forms.RENDERED: ["effort"], "effort": [effort]}
    return await operations.perform(kernel, "transcript.regler_effort", form, by=by, via=operations.SPACE)


def _efforts(calls: list[LLMRequest], role: str) -> list[str]:
    return [c.effort for c in calls if c.role == role]


def test_a_reply_thinks_at_the_effort_its_person_forced_for_the_whole_conversation(tmp_path):
    async def script(kernel, seen):
        await _ask(kernel, "tu vas bien ?")  # rien de forcé : rien n'est demandé
        seen["set"] = await _force(kernel, "high")
        seen["forced"] = transcript.efforts_of(kernel.mind.store, "user_1")
        await _ask(kernel, "explique-moi les marées")
        report = await _ask(kernel, "résume ce contrat", mode="pro")  # le mode pro est dans la conversation
        await kernel.traces.flush()
        seen["trace"] = kernel.traces.get(report.id)
        await _force(kernel, "auto")
        seen["auto"] = transcript.efforts_of(kernel.mind.store, "user_1")
        await _ask(kernel, "merci")

    seen, calls = _life(tmp_path, script)
    assert seen["set"].ok and seen["forced"] == {"": "high"} and seen["auto"] == {}
    assert _efforts(calls, "reply") == ["", "high", ""]
    assert _efforts(calls, "pro") == ["high"]
    # la trace de l'épisode dit l'effort demandé
    assert seen["trace"]["effort"] == "high"
    # les autres appels (ce que sa mémoire tire de l'échange…) ne le portent pas : le rôle décide
    assert {c.effort for c in calls if c.role not in ("reply", "pro")} <= {""}


def test_a_work_thread_has_its_own_effort_and_follows_the_conversation_without_one(tmp_path):
    async def script(kernel, seen):
        await _force(kernel, "low")
        await _force(kernel, "max", strand="devis-1")
        seen["forced"] = transcript.efforts_of(kernel.mind.store, "user_1")
        await _ask(kernel, "compare ces devis", mode="pro", strand="devis-1")   # le sien
        await _ask(kernel, "et ce script ?", mode="pro", strand="nas-2")        # sans le sien : la conversation
        await _force(kernel, "auto", strand="devis-1")
        await _ask(kernel, "encore un", mode="pro", strand="devis-1")           # revenu en auto : la conversation
        await _force(kernel, "auto")
        await _ask(kernel, "un dernier", mode="pro", strand="devis-1")          # plus rien de forcé

    seen, calls = _life(tmp_path, script)
    assert seen["forced"] == {"": "low", "devis-1": "max"}
    assert _efforts(calls, "pro") == ["max", "low", "low", ""]


def test_only_the_answer_to_her_message_in_private_thinks_at_the_forced_effort(tmp_path):
    async def script(kernel, seen):
        await _force(kernel, "max")
        store = kernel.mind.store
        ask = SimpleNamespace(target="user_1", reply_to=12, room=None, strand=None)
        seen["reply"] = transcript.asked_effort(store, ask)
        # une initiative (elle écrit d'elle-même), un salon, un travail sans personne : rien
        seen["initiative"] = transcript.asked_effort(store, SimpleNamespace(target="user_1", reply_to=None, room=None,
                                                                            strand=None))
        seen["room"] = transcript.asked_effort(store, SimpleNamespace(target="user_1", reply_to=12, room="salon",
                                                                      strand=None))
        seen["work"] = transcript.asked_effort(store, SimpleNamespace(target=None, reply_to=None, room=None,
                                                                      strand=None))
        # et quelqu'un d'autre : son réglage n'est qu'à elle
        seen["other"] = transcript.asked_effort(store, SimpleNamespace(target="user_2", reply_to=3, room=None,
                                                                       strand=None))

    seen, _calls = _life(tmp_path, script)
    assert seen == {"reply": "max", "initiative": "", "room": "", "work": "", "other": ""}


def test_an_unknown_effort_is_refused_and_a_setting_needs_its_person(tmp_path):
    async def script(kernel, seen):
        seen["unknown"] = await _force(kernel, "énorme")
        seen["nobody"] = await _force(kernel, "high", by="")
        seen["bad_strand"] = await _force(kernel, "high", strand="pas un id !")
        seen["forced"] = transcript.efforts_of(kernel.mind.store, "user_1")

    seen, _calls = _life(tmp_path, script)
    assert not seen["unknown"].ok and not seen["nobody"].ok and not seen["bad_strand"].ok
    assert seen["forced"] == {}


def test_forgetting_her_erases_what_she_forced(tmp_path):
    async def script(kernel, seen):
        await _force(kernel, "high")
        await _force(kernel, "max", strand="devis-1")
        seen["before"] = transcript.efforts_of(kernel.mind.store, "user_1")
        await kernel.mind.forget("user_1")
        seen["after"] = transcript.efforts_of(kernel.mind.store, "user_1")

    seen, _calls = _life(tmp_path, script)
    assert seen["before"] == {"": "high", "devis-1": "max"} and seen["after"] == {}


def test_a_chosen_candidate_asks_its_own_effort_before_what_the_composition_reads(tmp_path):
    async def script(kernel, seen):
        await _force(kernel, "low")
        runner = kernel.runner
        # ce que la demande porte (les arguments du candidat choisi) passe devant ce que la personne a forcé
        seen["asked"] = runner._effort(EpisodeRequest(kind=Kind.REPLY, target="user_1", reply_to=1, effort="max"))
        seen["read"] = runner._effort(EpisodeRequest(kind=Kind.REPLY, target="user_1", reply_to=1))
        # une valeur inconnue ne demande rien : ni le candidat, ni un réglage que le code ne connaît plus
        seen["unknown"] = runner._effort(EpisodeRequest(kind=Kind.WORK, effort="énorme"))
        await kernel.mind.append([transcript_c.EFFORT_SET.draft(person="user_1", strand="", effort="colossal")],
                                 emitter="transcript", correlation="test")
        seen["stale"] = runner._effort(EpisodeRequest(kind=Kind.REPLY, target="user_1", reply_to=1))

    seen, _calls = _life(tmp_path, script)
    assert seen == {"asked": "max", "read": "low", "unknown": "", "stale": ""}
