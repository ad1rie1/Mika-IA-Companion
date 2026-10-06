"""Oublier quelqu'un avant l'injection : ses messages, ses tête-à-tête, ce qui la nomme — et pour de bon."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from twin.corpus import Corpus, SourceStats
from twin.forget import forget_person
from twin.people import resolve_people
from twin.records import NOTES, WHATSAPP, Author, Conversation, Document, Message
from twin.sessions import build_sessions
from twin.timing import Temps

TZ = ZoneInfo("Europe/Paris")
T0 = 1_600_000_000_000_000
MIN = 60_000_000


def items() -> list[Any]:
    out: list[Any] = [Author(WHATSAPP, "Julie Martin", name="Julie Martin", me=False),
                      Author(WHATSAPP, "Paul Durand", name="Paul Durand", me=False),
                      Author(WHATSAPP, "Léa", name="Léa", me=True, me_reason="test"),
                      Conversation(WHATSAPP, "Julie Martin", members=("Julie Martin", "Léa")),
                      Conversation(WHATSAPP, "Les copains", group=True, members=("Julie Martin", "Paul Durand", "Léa"))]
    out += [Message(WHATSAPP, "Julie Martin", who, text, Temps.exact(T0 + i * MIN), i) for i, (who, text) in
            enumerate([("Julie Martin", "je te confie un secret"), ("Léa", "promis je dirai rien")])]
    out += [Message(WHATSAPP, "Les copains", who, text, Temps.exact(T0 + (10 + i) * MIN), i) for i, (who, text) in
            enumerate([("Paul Durand", "qui vient samedi ?"), ("Julie Martin", "moi !"), ("Léa", "moi aussi")])]
    out += [Author(NOTES, "moi", me=True),
            Document(NOTES, "carnet#0", "note", "Samedi", "Soirée chez Paul, Julie Martin était là.", Temps.exact(T0), 0)]
    return out


def corpus(tmp_path: Path) -> Corpus:
    c = Corpus(tmp_path / "corpus.db")
    with c.transaction():
        sid = c.begin_source("wa", "x", "test", 1, 0, "now")
        c.add_items(sid, items(), SourceStats())
    c.rebuild_search()
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    build_sessions(c)
    julie = c.db.execute("SELECT id FROM persons WHERE name = 'Julie Martin'").fetchone()["id"]
    paul = c.db.execute("SELECT id FROM persons WHERE name = 'Paul Durand'").fetchone()["id"]
    c.db.execute("CREATE TABLE annotations (session INTEGER, version INTEGER, tier TEXT, data TEXT, model TEXT)")
    c.db.execute("CREATE TABLE syntheses (kind TEXT, key TEXT, version INTEGER, data TEXT, model TEXT)")
    for s in c.db.execute("SELECT id FROM sessions").fetchall():
        c.db.execute("INSERT INTO annotations VALUES (?, 1, 'A', ?, '')", (s["id"], json.dumps({
            "souvenirs": [{"texte": "Julie m'a confié un secret", "personnes": [f"p{julie}"]},
                          {"texte": "Paul organise samedi", "personnes": [f"p{paul}"]}],
            "promesses": [{"texte": "ne rien dire", "envers": f"p{julie}"}], "emotions": []})))
    c.db.executemany("INSERT INTO syntheses VALUES (?, ?, 1, ?, '')", [
        ("profil", f"p{julie}:2020T3", json.dumps({"resume": "une amie"})),
        ("profil", f"p{paul}:2020T3", json.dumps({"resume": "un ami"})),
        ("mois", "2020-09", json.dumps({"recit": "Un mois avec Julie et Paul."})),
        ("mois", "2020-10", json.dumps({"recit": "Un mois calme."}))])
    c.db.commit()
    return c


def test_oublier_julie(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    r = forget_person(c, "Julie Martin")
    texts = {row["text"] for row in c.db.execute("SELECT text FROM messages")}
    assert texts == {"qui vient samedi ?", "moi aussi"}  # son tête-à-tête entier, ses messages au groupe
    assert r.conversations == 1 and r.messages == 3
    assert c.db.execute("SELECT COUNT(*) FROM persons WHERE name = 'Julie Martin'").fetchone()[0] == 0
    for row in c.db.execute("SELECT data FROM annotations"):
        data = json.loads(row["data"])
        assert [s["texte"] for s in data["souvenirs"]] == ["Paul organise samedi"] and not data["promesses"]
    kept = {(row["kind"], row["key"]) for row in c.db.execute("SELECT kind, key FROM syntheses")}
    assert kept == {("profil", next(k for _, k in kept if k.startswith("p"))), ("mois", "2020-10")}
    assert r.documents_naming == ["carnet#0"]  # son texte à elle : listé, pas modifié
    assert "Julie Martin" in c.db.execute("SELECT text FROM documents").fetchone()["text"]


def test_une_source_relue_ne_la_fait_pas_revenir(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    forget_person(c, "Julie Martin")
    stats = SourceStats()
    with c.transaction():
        sid = c.begin_source("wa-bis", "y", "test", 1, 0, "now")
        c.add_items(sid, items(), stats)
    assert stats.forgotten == 3
    assert c.db.execute("SELECT COUNT(*) FROM participants WHERE key = 'Julie Martin'").fetchone()[0] == 0
    assert c.db.execute("SELECT COUNT(*) FROM conversations WHERE key = 'Julie Martin'").fetchone()[0] == 0


def test_un_nom_ambigu_est_refuse(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    with pytest.raises(ValueError, match="désigne personne"):
        forget_person(c, "Zoé")
