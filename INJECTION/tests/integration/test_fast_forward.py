"""L'avance rapide de bout en bout, dans le vrai noyau : une petite archive vécue, puis reprise après un arrêt."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("mika")

from twin.corpus import Corpus, SourceStats  # noqa: E402
from twin.passes.synth import ensure, store  # noqa: E402
from twin.people import resolve_people  # noqa: E402
from twin.records import WHATSAPP, Author, Conversation, Message  # noqa: E402
from twin.replay.driver import run  # noqa: E402
from twin.replay.script import build_script  # noqa: E402
from twin.sessions import build_sessions  # noqa: E402
from twin.timing import Temps, to_us  # noqa: E402

TZ = ZoneInfo("Europe/Paris")
T0 = datetime(2019, 3, 11, 9, 0, tzinfo=TZ)

PERSONA = {
    "name": "Léa", "nature": "incarnee", "description": "Étudiante en master à Lyon, fidèle en amitié.",
    "tone": "Familière et rieuse avec ses proches.", "traits": ["Fidèle", "Rieuse"], "speech": ["Écrit « mdr »"],
    "facts": ["Fait un master à Lyon"], "timezone": "Europe/Paris",
    "temperament": {"reactivity": 0.6, "resilience": 0.5, "contagion": 0.6, "optimism": 0.6, "sociability": 0.7,
                    "curiosity": 0.5, "perseverance": 0.6, "chronotype": 0.6, "background": "happy"},
}


def archive(tmp_path: Path) -> Corpus:
    c = Corpus(tmp_path / "travail" / "corpus.db")
    items: list[Any] = [Author(WHATSAPP, "Julie", name="Julie Martin", me=False),
                        Author(WHATSAPP, "Léa", name="Léa", me=True),
                        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa"))]
    rank = 0
    for day in range(4):
        base = T0 + timedelta(days=day)
        script = [(0, "Julie", "Salut ! tu fais quoi ?"), (1, "Léa", "je révise mon partiel, et toi ?"),
                  (2, "Julie", "je suis enceinte !!!" if day == 1 else "rien de spécial"),
                  (190, "Léa", "QUOI ?? félicitations !!" if day == 1 else "ok bonne journée")]  # 3 h après : différée
        if day == 3:
            script.append((600, "Léa", "au fait, tu veux venir dimanche ?"))  # elle ouvre, le soir
        for minutes, who, text in script:
            items.append(Message(WHATSAPP, "Julie", who, text, Temps.exact(to_us(base + timedelta(minutes=minutes))),
                                 rank))
            rank += 1
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "travail" / "personnes.yaml", TZ)
    build_sessions(c)
    c.db.execute("UPDATE sessions SET tier = 'A'")
    # ce que la lecture aurait rendu : ses émotions, et le souvenir de l'annonce
    c.db.execute("CREATE TABLE IF NOT EXISTS annotations (session INTEGER, version INTEGER, tier TEXT, data TEXT, "
                 "model TEXT)")
    julie = c.db.execute("SELECT id FROM persons WHERE name = 'Julie Martin'").fetchone()[0]
    for s in c.db.execute("SELECT id FROM sessions").fetchall():
        msgs = c.db.execute("SELECT m.id, m.text, pa.person FROM messages m JOIN participants pa ON pa.id = m.author "
                            "WHERE m.session = ?", (s["id"],)).fetchall()
        hers = [m["id"] for m in msgs if m["person"] != julie]
        data: dict[str, Any] = {"resume": "J'ai parlé avec Julie.", "emotions": [
            {"id": i, "emotion": "excited" if "QUOI" in next(m["text"] for m in msgs if m["id"] == i) else "happy",
             "intensite": 0.8} for i in hers]}
        news = [m["id"] for m in msgs if "enceinte" in m["text"]]
        if news:
            data["souvenirs"] = [{"texte": "Julie m'a annoncé qu'elle était enceinte.", "personnes": [f"p{julie}"],
                                  "messages": news, "importance": 4, "sensibilite": "personnel"}]
        c.db.execute("INSERT INTO annotations VALUES (?, 1, 'A', ?, '')", (s["id"], json.dumps(data)))
    ensure(c)
    store(c, "mois", "2019-03", 1, {"recit": "Je suis quelqu'un qui se réjouit pour les autres."}, "fake")
    c.db.commit()
    assert build_script(c, her_names=("Léa",)).steps > 0
    return c


def events(life: Path, kind: str) -> list[dict[str, Any]]:
    with sqlite3.connect(life / "mind.db") as db:
        return [json.loads(d) for (d,) in db.execute("SELECT data FROM events WHERE type = ? ORDER BY seq", (kind,))]


def test_une_petite_vie_vecue_puis_reprise(tmp_path: Path) -> None:
    c = archive(tmp_path)
    life = tmp_path / "sortie" / "vie"
    middle = to_us(T0 + timedelta(days=2))
    first = run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, until=middle, log=lambda _m: None)
    assert first.stats["perçus"] > 0 and "arrivée" not in first.stats
    report = run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, log=lambda _m: None)  # reprise
    assert report.stats["arrivée"] == 1
    assert report.stats["paroles perdues"] == 0, report.gaps

    utterances = events(life, "episode.utterance")
    assert len(utterances) == 9  # 2 par jour pendant 4 jours, plus son invitation du dernier soir
    replies = [u for u in utterances if u.get("kind") == "REPLY"]
    assert any(u.get("answers") for u in replies)  # les réponses différées portent ce à quoi elles répondent
    assert any(u.get("kind") == "INITIATIVE" for u in utterances)
    perceptions = events(life, "perception.received")
    assert len(perceptions) == 8  # 2 par jour, aucun doublon malgré la reprise

    with sqlite3.connect(life / "mind.db") as db:
        memories = [t for (t,) in db.execute("SELECT text FROM content WHERE text LIKE '%enceinte%'")]
        persona = [json.loads(d) for (d,) in db.execute(
            "SELECT data FROM events WHERE type = 'self.persona_revised' ORDER BY seq")]
    assert any("Julie m'a annoncé" in t for t in memories)  # le souvenir assemblé est dans sa mémoire
    assert persona and persona[-1]["persona"]["name"] == "Léa" and persona[-1]["persona"]["nature"] == "incarnee"
