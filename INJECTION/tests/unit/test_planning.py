"""Séances, signifiance et paliers sous budget."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from twin.corpus import Corpus, SourceStats
from twin.people import resolve_people
from twin.planning import plan
from twin.records import MAIL, NOTES, WHATSAPP, Author, Conversation, Document, Message
from twin.sessions import GAP, build_sessions
from twin.timing import HOUR, Origin, Temps

TZ = ZoneInfo("Europe/Paris")
T0 = 1_600_000_000_000_000


def build(tmp_path: Path) -> Corpus:
    c = Corpus(tmp_path / "corpus.db")
    items: list = [  # type: ignore[type-arg]
        Author(WHATSAPP, "Julie", name="Julie", me=False), Author(WHATSAPP, "Léa", name="Léa", me=True),
        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa")),
    ]
    # séance 1 : un moment fort ; séance 2 (4 h plus tard) : banal
    fort = ["Je suis enceinte !!!", "QUOI ?? félicitations je suis trop heureuse pour toi ❤️❤️", "merci 😭"]
    for i, text in enumerate(fort):
        items.append(Message(WHATSAPP, "Julie", "Julie" if i % 2 == 0 else "Léa", text,
                             Temps.exact(T0 + i * 60_000_000), i))
    for i, text in enumerate(["ok", "ok"]):
        items.append(Message(WHATSAPP, "Julie", "Julie" if i == 0 else "Léa", text,
                             Temps.exact(T0 + GAP + HOUR + i * 60_000_000), 10 + i))
    items += [Author(MAIL, "promo@shop.example", address="promo@shop.example"),
              Conversation(MAIL, "pub", members=("promo@shop.example",)),
              Message(MAIL, "pub", "promo@shop.example", "Soldes !", Temps.exact(T0), 0, kind="masse")]
    items += [Author(NOTES, "moi", me=True),
              Document(NOTES, "journal#0", "journal", "12 mars", "J'ai pleuré de joie toute la journée.",
                       Temps.exact(T0, Origin.HEADER), 0)]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    return c


def test_seances_coupees_par_le_silence_et_signifiance(tmp_path: Path) -> None:
    c = build(tmp_path)
    report = build_sessions(c)
    assert report.sessions == 3 and report.documents == 1
    rows = c.db.execute("SELECT * FROM sessions WHERE conversation IS NOT NULL ORDER BY t_point").fetchall()
    wa = [r for r in rows if r["n_messages"] in (2, 3) and r["chars"] > 0 and r["significance"] > 0]
    strong = max(wa, key=lambda r: r["significance"])
    weak = min(wa, key=lambda r: r["significance"])
    assert strong["n_messages"] == 3 and weak["n_messages"] == 2
    assert strong["significance"] > weak["significance"]
    pub = [r for r in rows if r["n_her"] == 0 and r["n_messages"] == 1]
    assert pub and pub[0]["significance"] == 0  # un envoi de masse ne compte pas
    assert c.db.execute("SELECT COUNT(*) FROM messages WHERE session IS NULL").fetchone()[0] == 0


def test_paliers_sous_budget(tmp_path: Path) -> None:
    c = build(tmp_path)
    build_sessions(c)
    knobs = tmp_path / "plan.yaml"
    p = plan(c, knobs)
    tiers = {r["significance"]: r["tier"] for r in c.db.execute("SELECT significance, tier FROM sessions")}
    assert tiers[0.0] == "D"
    assert c.db.execute("SELECT tier FROM sessions WHERE document IS NOT NULL").fetchone()["tier"] == "A"
    assert p.replayed_messages == 5
    # un budget de lecture minuscule : ses textes restent lus, les conversations passent en « rejouée sans lecture »
    data = yaml.safe_load(knobs.read_text(encoding="utf-8"))
    data["lecture"]["jetons_max"] = 30
    data["paliers"]["part_C"] = 0
    knobs.write_text(yaml.safe_dump(data), encoding="utf-8")
    p2 = plan(c, knobs)
    assert "R" in p2.tiers and p2.tiers["A"].sessions == 1  # le seul A restant : son journal
    # un plafond de rejeu minuscule : la séance forte passe d'abord, la faible devient du savoir d'archive au mieux
    data["lecture"]["jetons_max"] = 10_000_000
    data["paliers"]["part_C"] = 0.5
    data["rejeu"]["messages_max"] = 3
    knobs.write_text(yaml.safe_dump(data), encoding="utf-8")
    p3 = plan(c, knobs)
    assert p3.replayed_messages == 3 and p3.tiers["C"].sessions == 1


def test_plan_fige_une_fois_la_lecture_commencee(tmp_path: Path) -> None:
    c = build(tmp_path)
    build_sessions(c)
    plan(c, tmp_path / "plan.yaml")
    c.db.execute("UPDATE sessions SET status = 'done' WHERE id = (SELECT MIN(id) FROM sessions)")
    with pytest.raises(RuntimeError):
        plan(c, tmp_path / "plan.yaml")
    with pytest.raises(RuntimeError):
        build_sessions(c)


def test_un_echange_banal_avec_une_proche_n_est_pas_un_moment_fort(tmp_path: Path) -> None:
    c = build(tmp_path)
    build_sessions(c)
    weak = c.db.execute("SELECT significance FROM sessions WHERE n_messages = 2").fetchone()["significance"]
    assert weak < 0.55  # sous le seuil d'une lecture à fond
