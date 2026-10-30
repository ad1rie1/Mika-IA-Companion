"""Le mode pro (ADR 0116) : un travail demandé dans le chat, comme dans Claude Code.

Un message en mode pro reçoit une réponse de travail : son rôle de modèle à lui (``pro``), une persona sans voix de
chat ni tempérament, ni sa consigne de style ni « TA RÉPONSE », ni relecture ni seconde passe. Sa réponse est du
Markdown : ses blocs de code et son indentation passent l'analyse tels quels. Chaque moment de sa boucle d'outils
se montre en direct à la personne (le port ``activity``), puis la fin de l'épisode. Le contre-exemple : le même
message sans mode reçoit sa réponse ordinaire, relue, passée par l'autrice, sans rien montrer.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from mika.app.composition import modes, policies
from mika.contracts import runtime as rt
from mika.faculties import transcript
from mika.faculties.expression import parse
from mika.faculties.self.persona import render
from mika.kernel.clock import HOUR
from mika.kernel.faculty import ToolSpec
from mika.ports.delivery import DONE, NOTE, TOOL_END, TOOL_START
from mika.ports.llm import DEADLINE_AT, LLMRequest, LLMResponse, ToolCall
from mika.runtime.tools import LoopEvent, ToolResult, run_tool_loop
from mika.sim.clock import run_virtual
from mika.vocab.episodes import PRO, Kind
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import SHIPPED, at_paris, boot, build, connect, said

CODE = "```python\ndef f(x):\n    if x:\n        return ARR[INDEX]  # deux  espaces\n```"
ANSWER = f"**Trouvé.** Le devis est dans ta boîte :\n\n{CODE}\n\n- le montant\n  - hors taxes"
#: un tic de chat (une question à options) : la relecture le reprendrait, l'autrice le récrirait
CHAT = "Ah, sympa ! Tu l'as pris en bleu, ou en noir ? [EMOTION:happy:0.4]"
STYLE = phrase("expression.style", names="", header="", footer="")[:40]


class Shown:
    """Le port d'activité : ce que la personne voit en direct."""

    def __init__(self) -> None:
        self.items: list = []

    async def activity(self, a) -> None:
        self.items.append(a)


def _life(tmp_path, *, mode: str = "pro", tools: bool = True, polish: bool = True):
    calls: list[LLMRequest] = []

    def respond(req):
        calls.append(req)
        if req.role == "polish":
            return LLMResponse("récrit par l'autrice")
        if req.role not in ("reply", "pro"):
            return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")
        if tools and not any(m.role == "tool" for m in req.messages):
            return LLMResponse("Je regarde ce que je sais… [EMOTION:calm:0.3]", tool_calls=(
                ToolCall("t1", "memory_search", {"query": "devis de Paul"}), ToolCall("t2", "outil_inconnu", {})))
        return LLMResponse(ANSWER if req.role == "pro" else CHAT)

    shown = Shown()
    kernel, clock, _llm, deliveries = build(tmp_path, respond, start=at_paris(2026, 10, 15, 18, 0), polish=polish,
                                            ports={"activity": shown})
    seen: dict = {}

    async def main():
        await boot(kernel, SHIPPED)
        await connect(kernel, "user_1", "Adrien", operator=True)
        await asyncio.sleep(2 * HOUR / 1e6)
        got = await kernel.perceive(said("user_1", "trouve-moi le devis de Paul", mode=mode))
        seen["report"] = await got.reply
        seen["seq"] = got.commit.seqs[-1]
        last = kernel.mind.store.latest([rt.UTTERANCE.name], 1)
        seen["utterance"] = kernel.mind.decode(last[0]).data
        seen["thread"] = transcript.recent(kernel.mind.store, "user_1", 10)
        await kernel.stop()

    run_virtual(clock, main)
    return seen, calls, shown.items, [d for d in deliveries.items if d.target == "user_1" and d.text]


def test_a_pro_request_is_worked_with_her_tools_shown_live_and_answered_in_markdown(tmp_path):
    seen, calls, shown, said_to_him = _life(tmp_path)
    pro = [c for c in calls if c.role == "pro"]
    assert len(pro) == 2 and not [c for c in calls if c.role in ("reply", "polish")]
    first = pro[0]
    content = first.system_stable + "".join(m.content for m in first.messages)
    # la consigne du mode, sa persona de travail ; ni son tempérament, ni sa voix de chat, ni « TA RÉPONSE »
    assert "MODE PRO" in first.system_stable and first.persona.depth == "pro" and first.max_tokens == 8192
    assert "Ton caractère, pour toi seule" not in content  # son caractère écrit (ADR 0139) n'entre pas en mode pro
    assert STYLE not in content and phrase("expression.answer.title") not in content
    assert SHIPPED.portrait.strip()[:60] not in content
    # sa réponse en Markdown, telle qu'écrite : le code, ses crochets, ses espaces et son indentation
    assert seen["report"].text == ANSWER
    assert seen["utterance"].mode == "pro" and [d.mode for d in said_to_him] == ["pro"]
    rows = {r["role"]: r for r in seen["thread"]}
    assert rows["user"]["mode"] == "pro" and rows["assistant"]["mode"] == "pro"
    # ce qu'elle a fait, en direct, dans l'ordre : ce qu'elle a écrit avant, l'outil parti puis fini, l'appel
    # refusé (fini sans être parti), la fin de l'épisode
    assert [(a.phase, a.name) for a in shown] == [(NOTE, ""), (TOOL_START, "memory_search"),
                                                   (TOOL_END, "memory_search"), (TOOL_END, "outil_inconnu"),
                                                   (DONE, "")]
    note, start, end, refused, done = shown
    assert note.text == "Je regarde ce que je sais…"  # sans sa balise
    assert "devis de Paul" in start.args and end.ok is True and refused.ok is False
    assert done.outcome == "done"
    assert {a.target for a in shown} == {"user_1"} and {a.reply_to for a in shown} == {seen["seq"]}
    assert len({a.episode for a in shown}) == 1


def test_her_pro_calls_carry_the_fifteen_minutes_of_the_mode(tmp_path):
    """Chaque appel du mode pro portait le délai de sa voie (120 s) : un tour qui réfléchit puis écrit du code
    échouait alors que l'épisode avait quinze minutes (audit du 2026-10-26, L1). Le délai de l'épisode suit la
    requête, borné par ce qui lui reste ; l'ordinaire aussi, avec les siens."""
    _seen, calls, _shown, _said = _life(tmp_path / "pro", tools=False)
    pro = [c for c in calls if c.role == "pro"]
    assert pro and all(c.deadline_s == 900.0 and DEADLINE_AT in c.meta for c in pro)
    _seen, calls, _shown, _said = _life(tmp_path / "chat", mode="", tools=False)
    assert {c.deadline_s for c in calls if c.role in ("reply", "polish")} == {180.0}


def test_a_pro_answer_without_tools_is_not_rewritten(tmp_path):
    seen, calls, shown, _said = _life(tmp_path, tools=False)
    assert len([c for c in calls if c.role == "pro"]) == 1
    assert not [c for c in calls if c.role == "polish"]  # pas d'autrice
    assert seen["report"].text == ANSWER
    assert [a.phase for a in shown] == [DONE]


def test_the_same_message_without_mode_gets_her_ordinary_reply(tmp_path):
    """Le contre-exemple : sans mode, la réponse est passée par l'autrice, et rien ne se montre en direct ; sans modèle
    pour l'autrice, le premier jet part tel quel (un seul appel : plus de relecture, ADR 0154)."""
    seen, calls, shown, said_to_him = _life(tmp_path / "autrice", mode="", tools=False)
    assert not [c for c in calls if c.role == "pro"]
    replies = [c for c in calls if c.role == "reply"]
    assert len(replies) == 1 and [c for c in calls if c.role == "polish"]
    assert STYLE in replies[0].system_stable + "".join(m.content for m in replies[0].messages)
    assert seen["report"].text == "récrit par l'autrice" and seen["utterance"].mode == ""
    assert shown == [] and [d.mode for d in said_to_him] == [""]
    _seen, calls, _shown, _said = _life(tmp_path / "seule", mode="", tools=False, polish=False)
    assert len([c for c in calls if c.role == "reply"]) == 1


def test_an_unknown_mode_is_the_ordinary_conversation(tmp_path):
    seen, calls, shown, _said = _life(tmp_path, mode="turbo", tools=False)
    assert not [c for c in calls if c.role == "pro"] and seen["utterance"].mode == "" and shown == []


def test_her_pro_persona_says_who_she_is_without_her_chat_voice_nor_her_character():
    character = "Tu prends le temps avant de répondre, et tu repenses longuement à ce qui t'a marquée."
    text = render(SHIPPED, "pro", character=character)
    assert text.startswith(f"Tu es {SHIPPED.name}") and SHIPPED.language in text
    assert character not in text and "Ton caractère" not in text
    assert SHIPPED.portrait.strip()[:60] not in text
    assert not any(sample in text for sample in SHIPPED.samples)
    # le contre-exemple : en conversation, son caractère écrit se dit
    assert character in render(SHIPPED, "full", chat=True, character=character)


def test_without_the_shield_her_code_would_be_mangled():
    """Ce que protège le mode Markdown : l'analyse d'une parole de chat resserre les espaces, ôte l'indentation et
    prend ``[INDEX]`` pour un jeton."""
    assert parse(ANSWER)[0] != ANSWER


class _Stub:
    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)

    async def call(self, req: LLMRequest) -> LLMResponse:
        return self.responses.pop(0)


def test_a_watch_that_fails_changes_nothing_to_the_loop():
    seen: list[LoopEvent] = []

    async def watch(event: LoopEvent) -> None:
        seen.append(event)
        raise RuntimeError("l'écran est parti")

    gateway = _Stub(LLMResponse("", tool_calls=(ToolCall("t1", "nulle_part", {}),)), LLMResponse("fini"))
    got = asyncio.run(run_tool_loop(gateway, LLMRequest(role="pro", call_id="e#0", system_stable=""), {},
                                    lambda spec, cid: None, max_turns=3, watch=watch))
    assert got.text == "fini" and got.stop == "end"
    assert [(e.phase, e.name, e.record.ok) for e in seen] == [(TOOL_END, "nulle_part", False)]


class _Query(BaseModel):
    status: str = ""


def _tool(name: str, cap: int, *, outside: bool) -> ToolSpec:
    async def answer(args: _Query, ctx) -> ToolResult:
        return ToolResult(content=f"{name} {args.status}")

    return ToolSpec(owner="x", name=name, description="Liste.", args=_Query, handler=answer, bundle="x",
                    episodes=frozenset({Kind.REPLY}), max_calls_per_episode=cap, outside=outside)


def _ran(outside_calls: int | None) -> list[tuple[str, bool]]:
    """Cinq appels à un outil de service (plafonné à 3 par son serveur), deux à l'un de ses outils (plafonné à 1)."""
    tools = {"devis_list": _tool("devis_list", 3, outside=True), "create_project": _tool("create_project", 1,
                                                                                         outside=False)}
    calls = (*(ToolCall(f"d{i}", "devis_list", {"status": s})
               for i, s in enumerate(("", "brouillon", "signé", "refusé", "envoyé"))),
             ToolCall("p1", "create_project", {}), ToolCall("p2", "create_project", {}))
    gateway = _Stub(LLMResponse("", tool_calls=calls), LLMResponse("fini"))
    got = asyncio.run(run_tool_loop(gateway, LLMRequest(role="pro", call_id="e#0", system_stable=""), tools,
                                    lambda spec, cid: None, max_turns=3, outside_calls=outside_calls))
    return [(r.name, r.ok) for r in got.records]


def test_in_pro_mode_a_service_is_tried_with_every_filter_its_own_tools_keep_their_cap():
    """Éprouver une API, c'est appeler le même outil avec chaque filtre : au quatrième appel de ``devis_list``, le
    plafond de son serveur (3 par défaut) l'arrêtait à mi-chemin. Le mode pro et ses exécutions de projet le
    relèvent à leurs 24 tours (ADR 0162) ; ses propres outils gardent le leur, et l'ordinaire celui du serveur."""
    assert _ran(24) == [*[("devis_list", True)] * 5, ("create_project", True), ("create_project", False)]
    assert _ran(None) == [*[("devis_list", True)] * 3, *[("devis_list", False)] * 2,
                          ("create_project", True), ("create_project", False)]
    assert _ran(2)[:4] == [*[("devis_list", True)] * 3, ("devis_list", False)]  # relevé, jamais abaissé
    reply = policies()[Kind.REPLY]
    pro = modes()[PRO]
    assert reply.outside_calls is None and pro.applied(reply).outside_calls == pro.max_tool_turns == 24
    # une exécution de projet a le budget du mode pro, ce relèvement compris
    assert policies()[Kind.WORK].outside_calls == policies()[Kind.JOB].outside_calls == 24
