"""Les cas limites de l'avance rapide, dans le vrai noyau (relecture du 2026-10-06).

- un plantage en pleine journée ne fait rien redire ;
- une parole dite juste avant de tomber, pas encore notée, est retrouvée, pas redite ;
- deux réponses dues dans la même minute : chacune libère son tour, jamais celui de l'autre ;
- deux conversations avec la même personne (WhatsApp et Messenger) ne se défont pas l'une l'autre.
"""

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
from twin.people import resolve_people  # noqa: E402
from twin.records import MESSENGER, WHATSAPP, Author, Conversation, Message  # noqa: E402
from twin.replay import driver as driver_mod  # noqa: E402
from twin.replay.driver import run  # noqa: E402
from twin.replay.script import build_script  # noqa: E402
from twin.sessions import build_sessions  # noqa: E402
from twin.timing import Temps, to_us  # noqa: E402

TZ = ZoneInfo("Europe/Paris")
T0 = datetime(2019, 3, 11, 10, 0, tzinfo=TZ)
PERSONA = {"name": "Léa", "nature": "incarnee", "description": "Étudiante.", "tone": "Familière.",
           "timezone": "Europe/Paris"}


def corpus_of(tmp_path: Path, items: list[Any]) -> Corpus:
    c = Corpus(tmp_path / "travail" / "corpus.db")
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "travail" / "personnes.yaml", TZ)
    build_sessions(c)
    c.db.execute("UPDATE sessions SET tier = 'R'")
    c.db.commit()
    assert build_script(c, her_names=("Léa",)).steps > 0
    return c


def at(minutes: float) -> Temps:
    return Temps.exact(to_us(T0 + timedelta(minutes=minutes)))


def events(life: Path, kind: str) -> list[dict[str, Any]]:
    with sqlite3.connect(life / "mind.db") as db:
        return [json.loads(d) for (d,) in db.execute("SELECT data FROM events WHERE type = ? ORDER BY seq", (kind,))]


def outcomes(life: Path) -> list[str]:
    return [e["outcome"] for e in events(life, "episode.ended")]


def chat(channel: str, conv: str, other: str, script: list[tuple[float, str, str]], start_rank: int = 0) -> list[Any]:
    items: list[Any] = [Author(channel, other, name=other, me=False), Author(channel, "Léa", name="Léa", me=True),
                        Conversation(channel, conv, members=(other, "Léa"))]
    items += [Message(channel, conv, who, text, at(m), start_rank + i) for i, (m, who, text) in enumerate(script)]
    return items


def test_deux_reponses_dues_la_meme_minute_ne_se_liberent_pas_l_une_l_autre(tmp_path: Path) -> None:
    items = chat(WHATSAPP, "Julie Martin", "Julie Martin", [(0, "Julie Martin", "tu viens ?"), (5, "Léa", "oui !")])
    items += chat(WHATSAPP, "Paul Durand", "Paul Durand", [(2, "Paul Durand", "t'as fini ?"), (5, "Léa", "presque")],
                  100)
    c = corpus_of(tmp_path, items)
    life = tmp_path / "vie"
    report = run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, log=lambda _m: None)
    replies = [u for u in events(life, "episode.utterance") if u["kind"] == "REPLY"]
    assert len(replies) == 2 and all(u.get("answers") for u in replies), replies
    assert "abstained" not in outcomes(life)  # Paul n'a pas reçu un silence à 10 h 05
    assert report.stats["réponse:libérée"] == 2 and report.stats["réponse:repli"] == 0


def test_deux_conversations_avec_la_meme_personne(tmp_path: Path) -> None:
    """Julie sur WhatsApp à 10 h ; elle écrit à Julie sur Messenger à 10 h 30 ; elle répond sur WhatsApp à 11 h."""
    items = chat(WHATSAPP, "Julie Martin", "Julie Martin", [(0, "Julie Martin", "on se voit quand ?"),
                                                              (60, "Léa", "samedi ?")])
    items += [Author(MESSENGER, "Julie Martin", name="Julie Martin", me=False),
              Author(MESSENGER, "Léa", name="Léa", me=True),
              Conversation(MESSENGER, "inbox/julie", members=("Julie Martin", "Léa")),
              Message(MESSENGER, "inbox/julie", "Léa", "regarde ce lien", at(30), 0)]
    c = corpus_of(tmp_path, items)
    life = tmp_path / "vie"
    report = run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, log=lambda _m: None)
    late = [u for u in events(life, "episode.utterance") if u["kind"] == "REPLY"]
    assert len(late) == 1 and late[0].get("answers"), "la réponse de 11 h répond au message de 10 h"
    assert "failed" not in outcomes(life)
    assert report.stats["réponse:repli"] == 0


def test_un_plantage_en_pleine_journee_ne_fait_rien_redire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = []
    for day in range(3):
        base = day * 24 * 60
        script += [(base, "Julie Martin", "salut"), (base + 1, "Léa", f"coucou {day}"),
                   (base + 2, "Julie Martin", "ça va ?"), (base + 120, "Léa", f"oui et toi {day}")]
    c = corpus_of(tmp_path, chat(WHATSAPP, "Julie Martin", "Julie Martin", script))
    life = tmp_path / "vie"
    calls = {"n": 0}
    original = driver_mod.FastForward._step

    async def crashing(self, kind, data, sid):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 7:  # au milieu de la deuxième journée
            raise RuntimeError("le processus tombe")
        return await original(self, kind, data, sid)

    monkeypatch.setattr(driver_mod.FastForward, "_step", crashing)
    with pytest.raises(RuntimeError):
        run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, log=lambda _m: None)
    monkeypatch.setattr(driver_mod.FastForward, "_step", original)
    report = run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, log=lambda _m: None)
    assert report.stats["arrivée"] == 1
    texts = [u["text"] for u in events(life, "episode.utterance")]
    assert len(texts) == 6, texts  # deux par jour, rien de redit
    assert len(events(life, "perception.received")) == 6


def test_une_parole_dite_mais_pas_notee_est_retrouvee(tmp_path: Path) -> None:
    """Le plantage tombe entre l'énoncé (au journal) et sa note (dans le corpus) : la reprise le retrouve."""
    script = [(0, "Julie Martin", "salut"), (1, "Léa", "coucou"), (2, "Julie Martin", "tu fais quoi ?"),
              (3, "Léa", "je révise"), (24 * 60, "Julie Martin", "et demain ?"), (24 * 60 + 1, "Léa", "pareil")]
    c = corpus_of(tmp_path, chat(WHATSAPP, "Julie Martin", "Julie Martin", script))
    life = tmp_path / "vie"
    middle = to_us(T0 + timedelta(hours=12))
    run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, until=middle, log=lambda _m: None)
    # on défait la note de sa dernière parole et le curseur d'un pas, comme si le processus était tombé entre les deux
    last = c.db.execute("SELECT MAX(seq) FROM replay_seq").fetchone()[0]
    archive = c.db.execute("SELECT archive FROM replay_seq WHERE seq = ?", (last,)).fetchone()[0]
    c.db.execute("DELETE FROM replay_seq WHERE seq = ?", (last,))
    c.db.execute("DELETE FROM replay_archive WHERE seq = ?", (last,))
    step = c.db.execute("SELECT id, at FROM replay_steps WHERE kind = 'her' AND data LIKE ? ORDER BY id DESC LIMIT 1",
                        (f'%"archive": [{archive}]%',)).fetchone()
    previous = c.db.execute("SELECT id, at FROM replay_steps WHERE at < ? OR (at = ? AND id < ?) ORDER BY at DESC, "
                            "id DESC LIMIT 1", (step["at"], step["at"], step["id"])).fetchone()
    c.db.execute("UPDATE replay_state SET value = ? WHERE key = 'cursor'", (json.dumps([previous["at"],
                                                                                       previous["id"]]),))
    c.db.commit()
    report = run(c, life, TZ, start_persona=PERSONA, final_persona=PERSONA, log=lambda _m: None)
    assert report.stats["reprise:parole retrouvée"] == 1
    assert len(events(life, "episode.utterance")) == 3
