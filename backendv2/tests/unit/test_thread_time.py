"""Le fil tel qu'on le perçoit (ADR 0041), par ses intentions.

- un message qui arrive après un silence est situé dans le temps comme une
  personne le perçoit (« le lendemain », « cinq jours plus tard »), en jours
  vécus du calendrier — pas en durée — et sans dépendre de l'heure qu'il est :
  le début du prompt, en cache, ne bouge pas d'un tour à l'autre ;
- le message auquel elle répond est situé par rapport au dernier échange ;
- ses propres tours gardent leur balise d'émotion ;
- dans un salon, chacun parle sous son nom, jamais sous son adresse ;
- le budget compte ce qui part hors du composeur (persona, outils).
"""

from __future__ import annotations

import asyncio

import pytest

from mika.faculties.transcript import (
    gap_mark,
    opening_mark,
    read_late,
    thread_turns,
    window_start,
)
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.codec import canonical_json
from mika.kernel.prompt import CONTEXT_FOOTER, Budget, ChatPrompt
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.affect import parse_tag
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, disconnect, said

MON = (2026, 9, 28)  # un lundi


def mon(h: int, mi: int = 0, plus_days: int = 0) -> int:
    return at_paris(*MON, h, mi) + plus_days * 24 * HOUR


# (avant, après, repère attendu, pourquoi)
MARKS = [
    (mon(18), mon(18, 5), "", "un message qui suit de près n'a pas de repère"),
    (mon(23), mon(23, 25), "25 minutes plus tard", "revenir après une dispute, ça se remarque"),
    (mon(14), mon(14, 31), "une demi-heure plus tard", "à cinq minutes près"),
    (mon(14), mon(15, 4), "une heure plus tard", "une heure"),
    (mon(14), mon(15, 35), "une heure et demie plus tard", "une heure et demie"),
    (mon(14), mon(17, 10), "plus tard, vers 17h", "le même jour, l'heure à la demi-heure près"),
    (mon(14), mon(17, 20), "plus tard, vers 17h30", "la demi-heure"),
    (mon(18), mon(14, 13, 1), "le lendemain, mardi 14h13", "le retour du lendemain"),
    (mon(23), mon(9, 0, 1), "le lendemain, mardi 9h00", "dix heures seulement, mais un autre jour"),
    (mon(22), mon(1, 30, 1), "plus tard dans la nuit, vers 1h30", "la nuit appartient encore à la veille"),
    (mon(18), mon(9, 0, 2), "le surlendemain, mercredi 9h00", "39 heures : deux jours du calendrier, pas un"),
    (mon(2, 0, 1), mon(2, 0, 3), "le surlendemain, dans la nuit de mercredi à jeudi, 2h00", "de quelle nuit"),
    (mon(18), mon(18, 8, 5), "cinq jours plus tard, samedi 18h08", "quelques jours"),
    (mon(18), mon(9, 2, 21), "trois semaines plus tard, lundi 19 octobre, 9h02", "au-delà d'une semaine, la date"),
    (mon(10), at_paris(2027, 1, 5, 10, 0), "trois mois plus tard, mardi 5 janvier 2027, 10h00",
     "l'année quand elle change"),
]


@pytest.mark.parametrize("before,after,expected,why", MARKS)
def test_a_mark_reads_like_time_as_a_person_perceives_it(before, after, expected, why):
    assert gap_mark(before, after, PARIS) == expected, why


@pytest.mark.parametrize("written,read,expected,why", [
    (mon(3, 10, 1), mon(7, 14, 1), "tu ne le lis que maintenant, mardi 7h14",
     "écrit dans la nuit, lu au réveil : un autre jour vécu"),
    (mon(14), mon(17, 10), "tu ne le lis que maintenant, vers 17h", "le même jour, l'heure à la demi-heure près"),
    (mon(14), mon(14, 2), "", "contre-exemple : une réponse aussitôt n'est pas une lecture en retard"),
    (mon(14), mon(14, 19), "", "contre-exemple : une file d'attente de quelques minutes non plus"),
])
def test_a_message_read_late_says_when_she_reads_it(written, read, expected, why):
    """Un message de 3 h lu à 7 h 14 : son repère seul (« vers 3h ») faisait répondre « non je dors pas »
    (sonde réelle du 2026-10-02)."""
    assert read_late(written, read, PARIS) == expected, why


def test_the_quiet_needed_for_a_mark_is_a_setting():
    assert gap_mark(mon(14), mon(14, 15), PARIS, after_us=10 * MINUTE) == "15 minutes plus tard"
    assert gap_mark(mon(14), mon(14, 15), PARIS) == ""  # par défaut, vingt minutes


def test_the_opening_mark_is_absolute():
    assert opening_mark(mon(18, 2), mon(9, 0, 1), PARIS) == "lundi 28 septembre, 18h02"
    assert opening_mark(mon(18, 2), at_paris(2027, 2, 1, 9, 0), PARIS) == "lundi 28 septembre 2026, 18h02"


def test_the_window_start_moves_by_steps_not_at_every_message():
    """Le début de l'historique, donc du prompt en cache, ne bouge qu'une fois
    par paquet ; on montre toujours entre ``window - step`` et ``window`` messages."""
    starts = [window_start(total, 60, 20) for total in range(0, 301)]
    assert all(40 < total - start <= 60 for total, start in enumerate(starts) if total > 60)
    assert all(start == 0 for start in starts[:61])
    moves = sum(1 for a, b in zip(starts, starts[1:], strict=False) if a != b)
    assert moves <= (300 - 60) // 20 + 1, moves
    # contre-exemple : sans paquets, il glisse à chaque message
    sliding = [window_start(total, 60, 1) for total in range(0, 301)]
    assert sum(1 for a, b in zip(sliding, sliding[1:], strict=False) if a != b) == 240


# ── De bout en bout ───────────────────────────────────────────────────────


def respond(req):
    if req.role in ("extract", "profile"):
        return LLMResponse("{}")
    return LLMResponse("ah oui ? [EMOTION:happy:0.6]")


def replies_to(llm, target):
    return [c for c in llm.calls if c.role == "reply" and c.meta.get("target") == target]


def after_footer(req) -> str:
    return req.messages[-1].content.split(CONTEXT_FOOTER, 1)[1].strip()


def test_a_friend_coming_back_the_next_day_is_placed_in_time(tmp_path):
    kernel, clock, llm, _ = build(tmp_path, respond, start=mon(17, 55))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        for text in ("salut toi ! ça va ?", "jeudi j'ai mon entretien chez Ubisoft", "bon je file, bonne soirée !"):
            p = await kernel.perceive(said("user_1", text))
            await p.reply
            await asyncio.sleep(120)
        await disconnect(kernel, "user_1")
        await asyncio.sleep((mon(14, 13, 1) - clock.now()) / US)
        p = await kernel.perceive(said("user_1", "re ! tu fais quoi cet aprèm ?"))
        await p.reply
        await asyncio.sleep(180)
        p = await kernel.perceive(said("user_1", "moi j'arrive pas à bosser"))
        await p.reply
        await kernel.stop()

    run_virtual(clock, main)
    calls = replies_to(llm, "user_1")
    tuesday, later = calls[-2], calls[-1]
    assert after_footer(tuesday) == "[le lendemain, mardi 14h13] re ! tu fais quoi cet aprèm ?"
    # contre-exemple : trois minutes plus tard, à la suite, sans repère
    assert after_footer(later) == "moi j'arrive pas à bosser"
    shown = [m.content for m in later.messages[:-1]]
    assert sum("[le lendemain, mardi 14h13]" in m for m in shown) == 1, "le retour reste situé dans le fil"
    monday = [m for m in shown if "entretien" in m or "bonne soirée !" == m]
    assert monday and all(not m.startswith("[") for m in monday), "lundi soir, tout se suivait"
    # ses tours gardent leur balise, et elle se relit
    mine = [m for m in later.messages[:-1] if m.role == "assistant"]
    assert mine and all(m.content.endswith("[EMOTION:happy:0.6]") for m in mine)
    assert parse_tag(mine[0].content).declared is not None
    # le cache : l'historique du tour suivant commence exactement par celui du tour d'avant
    before = [(m.role, m.content) for m in tuesday.messages[:-1]]
    assert [(m.role, m.content) for m in later.messages[:len(before)]] == before


def test_midnight_does_not_move_what_was_already_said(tmp_path):
    """Les repères ne dépendent que des messages : passer minuit entre deux
    tours ne réécrit pas l'historique (le préfixe en cache tient). Une amie :
    une inconnue n'aurait pas de réponse avant le matin (elle dort, ADR 0036)."""
    kernel, clock, llm, _ = build(tmp_path, respond, start=mon(23, 40))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await befriend(kernel, "user_1", "friend")
        for text in ("t'es encore debout ?", "moi non plus je dors pas", "allez, j'essaie de dormir"):
            p = await kernel.perceive(said("user_1", text))
            await p.reply
            await asyncio.sleep(25 * 60)
        await kernel.stop()

    run_virtual(clock, main)
    first, second, third = replies_to(llm, "user_1")[-3:]
    assert clock.now() > mon(0, 0, 1), "minuit est passé pendant la conversation"
    assert after_footer(third).startswith("[25 minutes plus tard] ")
    for a, b in ((first, second), (second, third)):
        prefix = [(m.role, m.content) for m in a.messages[:-1]]
        assert [(m.role, m.content) for m in b.messages[:len(prefix)]] == prefix


def test_in_a_room_everyone_speaks_under_their_name(tmp_path):
    kernel, clock, llm, _ = build(tmp_path, respond, start=at_paris(2026, 9, 30, 20, 0))
    room = {"channel": "external", "room": "ext_chat_-7", "public": True}

    async def main():
        await boot(kernel)
        await kernel.perceive(said("ext_7", "salut tout le monde", display_name="Léa", addressed=False, **room))
        await kernel.perceive(said("ext_9", "yo", display_name="Max Dupont", addressed=False, **room))
        await kernel.perceive(said("ext_10", "yo aussi", display_name="Max Dupont", addressed=False, **room))
        await kernel.perceive(said("ext_11", "…", addressed=False, **room))
        p = await kernel.perceive(said("ext_8", "Mika t'es là ?", display_name="Tom", **room))
        await p.reply
        p = await kernel.perceive(said("ext_8", "en privé cette fois", channel="external", display_name="Tom"))
        await p.reply
        await kernel.stop()

    run_virtual(clock, main)
    in_room, private = replies_to(llm, "ext_8")[-2:]
    shown = [m.content for m in in_room.messages]
    assert any(m.endswith("Léa : salut tout le monde") for m in shown)
    maxes = {m for m in shown if m.startswith("Max Dupont")}
    assert maxes in ({"Max Dupont : yo", "Max Dupont (2) : yo aussi"},
                     {"Max Dupont (2) : yo", "Max Dupont : yo aussi"}), "deux homonymes se distinguent"
    assert "Quelqu'un : …" in shown, "un nom inconnu n'est jamais remplacé par l'adresse"
    assert after_footer(in_room) == "Tom : Mika t'es là ?", "l'interlocuteur aussi parle sous son nom"
    assert not any("ext_" in m for m in shown)
    # contre-exemple : en privé, deux personnes, pas d'étiquette
    assert after_footer(private) == "en privé cette fois"


def test_the_budget_counts_persona_and_tools(tmp_path):
    """Ce qui part au modèle — persona, catalogue, déclarations d'outils, fil,
    état — tient dans le budget : le composeur réserve ce qu'il n'écrit pas."""
    kernel, clock, llm, _ = build(tmp_path, respond)
    budget = Budget(max_tokens=8000)
    kernel.runner.budget = budget
    long = "je te raconte ma journée en détail, " * 14

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        reports = []
        for i in range(40):
            p = await kernel.perceive(said("user_1", f"{i} {long}"))
            reports.append(await p.reply)
            await asyncio.sleep(60)
        await kernel.stop()
        return reports

    reports = run_virtual(clock, main)
    last = replies_to(llm, "user_1")[-1]
    tools = sum(len(t.name) + len(t.description) + len(canonical_json(t.schema)) for t in last.tools)
    sent = len(last.system_stable) + sum(len(m.content) for m in last.messages) + tools
    assert sent <= budget.max_chars, (sent, budget.max_chars)
    assert reports[-1].trace.reserved >= len(last.persona.text) + tools
    assert reports[-1].trace.history_turns > 0, "le fil n'est pas sacrifié pour autant"


# ── Un message qu'elle a écrit d'elle-même (HUM-22) ───────────────────────


def _row(n: int, at: int, role: str, kind: str, text: str, room: str | None = None) -> dict:
    return {"id": n, "at": at, "role": role, "person": "ext_1", "room": room, "kind": kind, "text": text,
            "emotion": None, "emotion_intensity": None}


def test_her_own_initiative_is_never_read_as_an_empty_message_from_the_person():
    """Le fil montre un repère avant son message ; pour une initiative, le repère seul (« [trois jours plus tard, jeudi
    19h06] ») se lisait comme un message vide de la personne — comme si Alice l'avait relancée. Il dit maintenant que
    c'est elle qui a écrit. Contre-exemple : une réponse garde son repère nu ; dans un salon, elle a « pris la
    parole »."""
    rows = [_row(1, mon(19), "user", "message", "bonne nuit !"),
            _row(2, mon(19, 1), "assistant", "REPLY", "bonne nuit Alice !"),
            _row(3, mon(19, 6, 3), "assistant", "INITIATIVE", "coucou, alors cet entretien ?"),
            _row(4, mon(19, 30, 3), "user", "message", "trop bien !"),
            _row(5, mon(9, 0, 4), "assistant", "REPLY", "trop contente pour toi")]
    turns = thread_turns(rows, PARIS, mon(12, 0, 4), 20 * MINUTE)
    msgs = ChatPrompt("", history=tuple(turns), message="x").chat_messages()
    separator = [m["content"] for m in msgs if m["role"] == "user" and "jeudi 19h06" in m["content"]]
    assert separator == [f"[trois jours plus tard, jeudi 19h06 — {phrase('transcript.thread.she_wrote_first')}]"]
    assert any(m["content"] == "[le lendemain, vendredi 9h00]" for m in msgs)  # une réponse : le repère nu
    # elle ouvre l'historique : son repère absolu le dit aussi
    opening = thread_turns(rows[2:3], PARIS, mon(12, 0, 4), 20 * MINUTE)[0]
    assert opening.opening.endswith(f"— {phrase('transcript.thread.she_wrote_first')}")
    # une initiative qui suit de près garde la précision (sans repère de temps)
    close = thread_turns([rows[0], _row(9, mon(19, 5), "assistant", "INITIATIVE", "et au fait…")], PARIS,
                         mon(20), 20 * MINUTE)
    assert close[-1].mark == phrase("transcript.thread.she_wrote_first")
    room = thread_turns([_row(7, mon(19), "assistant", "INITIATIVE", "yo tout le monde", room="salon")], PARIS,
                        mon(20), 20 * MINUTE)
    assert room[0].opening.endswith(phrase("transcript.thread.she_spoke_first"))
