"""Le script de l'avance rapide : rafales fusionnées, trois sortes de paroles, balise d'émotion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from twin.corpus import Corpus, SourceStats
from twin.people import resolve_people
from twin.records import WHATSAPP, Author, Conversation, Message
from twin.replay.script import Inbound, Utterance, build_script
from twin.sessions import build_sessions
from twin.timing import Temps, to_us

TZ = ZoneInfo("Europe/Paris")
T = datetime(2019, 3, 12, 10, 0, tzinfo=TZ)


def at(minutes: float) -> Temps:
    return Temps.exact(to_us(T + timedelta(minutes=minutes)))


def corpus(tmp_path: Path, tier: str = "A") -> Corpus:
    c = Corpus(tmp_path / "corpus.db")
    script = [  # (minutes, qui, texte)
        (0, "Léa", "coucou ça va ?"),  # elle ouvre : initiative
        (0.5, "Léa", "j'ai une news"),  # même rafale
        (3, "Julie", "oui et toi ?"),
        (3.5, "Léa", "trop bien !!"),  # 30 s après : immédiate
        (4, "Julie", "raconte"),
        (120, "Léa", "désolée j'étais en cours"),  # 2 h après : différée
    ]
    items: list[Any] = [Author(WHATSAPP, "Julie", name="Julie Martin", me=False),
                        Author(WHATSAPP, "Léa", name="Léa", me=True),
                        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa"))]
    items += [Message(WHATSAPP, "Julie", who, text, at(m), i) for i, (m, who, text) in enumerate(script)]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    build_sessions(c)
    c.db.execute("UPDATE sessions SET tier = ?", (tier,))
    her = [r["id"] for r in c.db.execute(
        "SELECT m.id FROM messages m JOIN participants pa ON pa.id = m.author JOIN persons p ON p.id = pa.person "
        "WHERE p.is_me = 1 ORDER BY m.rank")]
    c.db.execute("CREATE TABLE IF NOT EXISTS annotations (session INTEGER, version INTEGER, tier TEXT, data TEXT, "
                 "model TEXT)")
    for sid in [r["id"] for r in c.db.execute("SELECT id FROM sessions")]:
        c.db.execute("INSERT INTO annotations VALUES (?, 1, 'A', ?, '')", (sid, json.dumps({"emotions": [
            {"id": her[0], "emotion": "excited", "intensite": 0.5}, {"id": her[1], "emotion": "excited",
                                                                    "intensite": 0.9},
            {"id": her[2], "emotion": "happy", "intensite": 0.7}]})))
    c.db.commit()
    return c


def test_trois_sortes_de_paroles(tmp_path: Path) -> None:
    steps = list(build_script(corpus(tmp_path)))
    kinds = [(type(s).__name__, getattr(s, "kind", "")) for s in steps]
    assert kinds == [("Utterance", "initiative"), ("Inbound", ""), ("Utterance", "immediate"), ("Inbound", ""),
                     ("Utterance", "delayed")]
    first = steps[0]
    assert isinstance(first, Utterance)
    assert first.text == "coucou ça va ?\nj'ai une news [EMOTION:excited:0.90]"  # rafale fusionnée, émotion la plus forte
    assert first.target.startswith("ext_julie")
    assert isinstance(steps[1], Inbound) and steps[1].name == "Julie Martin"
    last = steps[-1]
    assert isinstance(last, Utterance) and "[EMOTION" not in last.text  # pas d'annotation : pas de balise
    assert last.reply_to == steps[3].archive
    assert [s.at for s in steps] == sorted(s.at for s in steps)


def test_seance_non_rejouee_absente(tmp_path: Path) -> None:
    assert list(build_script(corpus(tmp_path, tier="C"))) == []
