"""Le rejoueur : chaque rôle du noyau reçoit ce que Claude Code a lu, ou se tait."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("mika")
from mika.ports.llm import LLMRequest  # noqa: E402
from mika.ports.llm import Message as LLMMessage

from twin.corpus import Corpus, SourceStats  # noqa: E402
from twin.passes.synth import ensure, store  # noqa: E402
from twin.people import resolve_people  # noqa: E402
from twin.records import NOTES, WHATSAPP, Author, Conversation, Document, Message  # noqa: E402
from twin.replay.provider import SILENCE, ReplayLLM  # noqa: E402
from twin.sessions import build_sessions  # noqa: E402
from twin.timing import Origin, Temps, to_us  # noqa: E402

TZ = ZoneInfo("Europe/Paris")
DAY = datetime(2019, 3, 12, 18, 0, tzinfo=TZ)


def req(role: str, call_id: str = "run#x", text: str = "", system: str = "", target: str = "") -> LLMRequest:
    return LLMRequest(role=role, call_id=call_id, system_stable=system, messages=(LLMMessage("user", text),),
                      meta={"target": target} if target else {})


def setup(tmp_path: Path) -> tuple[Corpus, ReplayLLM, dict[str, Any]]:
    c = Corpus(tmp_path / "corpus.db")
    items: list[Any] = [
        Author(WHATSAPP, "Julie", name="Julie Martin", me=False), Author(WHATSAPP, "Léa", name="Léa", me=True),
        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa")),
        Message(WHATSAPP, "Julie", "Julie", "Je suis enceinte !", Temps.exact(to_us(DAY)), 0),
        Message(WHATSAPP, "Julie", "Léa", "Félicitations !!", Temps.exact(to_us(DAY) + 60_000_000), 1),
        Author(NOTES, "moi", me=True),
        Document(NOTES, "j#0", "journal", "13 mars", "Je n'arrive pas à croire que Julie va être maman.",
                 Temps.day(datetime(2019, 3, 13, tzinfo=TZ).date(), TZ, Origin.HEADER), 0),
    ]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    build_sessions(c)
    ids = [r["id"] for r in c.db.execute("SELECT id FROM messages ORDER BY rank")]
    session = c.db.execute("SELECT session FROM messages LIMIT 1").fetchone()[0]
    c.db.execute("CREATE TABLE IF NOT EXISTS annotations (session INTEGER, version INTEGER, tier TEXT, data TEXT, "
                 "model TEXT)")
    c.db.execute("INSERT INTO annotations VALUES (?, 1, 'A', ?, '')", (session, json.dumps({
        "resume": "Le 12 mars 2019, Julie m'a annoncé qu'elle était enceinte.",
        "souvenirs": [{"texte": "Julie m'a annoncé sa grossesse.", "personnes": ["p2"], "messages": ids,
                       "importance": 4}],
        "reves": [{"texte": "Je portais un bébé qui riait dans une gare vide.", "nuit": "2019-03-13"}]})))
    ensure(c)
    store(c, "profil", "p2:2019T1", 1, {"resume": "Julie va être maman.", "ton": "complice", "interets": ["bébés"],
                                        "sujets_sensibles": []}, "fake")
    store(c, "mois", "2019-03", 1, {"recit": "Je suis quelqu'un qui pleure de joie pour les autres."}, "fake")
    store(c, "reve", "2019-03-14", 1, {"soir": "2019-03-14", "reves": [
        {"ton": "doux", "texte": "Un champ de tournesols."}, {"ton": "cauchemar", "texte": "Une porte qui claque."}]},
        "fake")
    c.db.commit()
    now = [to_us(DAY)]
    llm = ReplayLLM(c, TZ, lambda: now[0])
    handle = c.db.execute("SELECT handle FROM persons WHERE name = 'Julie Martin'").fetchone()[0]
    return c, llm, {"ids": ids, "handle": handle, "now": now}


async def test_sa_parole_annoncee_sinon_silence(tmp_path: Path) -> None:
    _, llm, ctx = setup(tmp_path)
    llm.expect(ctx["handle"], "Félicitations !! [EMOTION:excited:0.90]")
    got = await llm.complete(req("reply", target=ctx["handle"]))
    assert got.text.startswith("Félicitations")
    again = await llm.complete(req("reply", target=ctx["handle"]))
    assert again.text == SILENCE and llm.holes["reply:imprévu"] == 1


async def test_extract_assemble_sur_les_seq_du_journal(tmp_path: Path) -> None:
    _, llm, ctx = setup(tmp_path)
    llm.note_seq(40, (ctx["ids"][0],))
    llm.note_seq(42, (ctx["ids"][1],))
    window = ("Conversation privée avec Julie Martin [P1].\n\nLes messages :\n"
              "[#40] 18:00 Julie Martin [P1] : Je suis enceinte !\n[#42] 18:01 Léa : Félicitations !!")
    got = await llm.complete(req("extract", text=window))
    args = got.tool_calls[0].args
    assert got.tool_calls[0].name == "record_memories"
    assert args["souvenirs"][0]["messages"] == [40, 42]
    assert args["souvenirs"][0]["personnes"] == ["Julie Martin [P1]"]


async def test_profil_d_un_trimestre_fini_jamais_du_futur(tmp_path: Path) -> None:
    _, llm, ctx = setup(tmp_path)
    during = await llm.complete(req("profile", call_id=f"run#{ctx['handle']}"))
    assert during.text == SILENCE  # le profil de 2019T1 est tiré de semaines qu'elle n'a pas encore vécues
    ctx["now"][0] = to_us(datetime(2019, 4, 2, 10, 0, tzinfo=TZ))
    got = await llm.complete(req("profile", call_id=f"run#{ctx['handle']}"))
    assert got.tool_calls[0].name == "record_profile" and got.tool_calls[0].args["ton"] == "complice"


async def test_journal_vrai_puis_resumes(tmp_path: Path) -> None:
    _, llm, _ = setup(tmp_path)
    real = await llm.complete(req("journal", call_id="run#2019-03-13"))
    assert real.text.startswith("Je n'arrive pas à croire")  # son vrai journal
    fallback = await llm.complete(req("journal", call_id="run#2019-03-12"))
    assert "enceinte" in fallback.text  # ses résumés du jour, faute de mieux


async def test_reves_vrai_puis_selon_le_ton(tmp_path: Path) -> None:
    _, llm, _ = setup(tmp_path)
    real = await llm.complete(req("dream", call_id="run#2019-03-12:0", system="… Ton du rêve : doux, lumineux."))
    assert "gare vide" in real.text  # raconté le matin du 13
    scary = await llm.complete(req("dream", call_id="run#2019-03-14:0",
                                   system="… Ton du rêve : un cauchemar, inquiétant."))
    assert scary.text == "Une porte qui claque."
    nothing = await llm.complete(req("dream", call_id="run#2019-05-01:0", system="Ton du rêve : banal, quotidien."))
    assert nothing.text == SILENCE


async def test_recit_d_un_mois_fini_et_repli(tmp_path: Path) -> None:
    _, llm, ctx = setup(tmp_path)
    assert (await llm.complete(req("narrative"))).text == ""  # mars n'est pas fini le 12 mars
    ctx["now"][0] = to_us(datetime(2019, 4, 2, 10, 0, tzinfo=TZ))
    assert "pleure de joie" in (await llm.complete(req("narrative"))).text
    ctx["now"][0] = to_us(DAY) + 3600 * 1_000_000
    folded = await llm.complete(req("compact", call_id=f"run#{ctx['handle']}"))
    assert "enceinte" in folded.text
    again = await llm.complete(req("compact", call_id=f"run#{ctx['handle']}"))
    assert again.text == ""  # déjà replié
    assert (await llm.complete(req("murmur"))).text == SILENCE and llm.holes["murmur"] == 1
