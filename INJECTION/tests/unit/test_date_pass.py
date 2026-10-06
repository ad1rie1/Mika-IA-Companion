"""La datation par recoupement : resserrer oui, élargir jamais, contredire = conflit, ancres vérifiées."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from twin.corpus import Corpus, SourceStats
from twin.engine.claude import CallResult
from twin.passes.date import DatePass
from twin.people import resolve_people
from twin.records import NOTES, WHATSAPP, Author, Conversation, Document, Message
from twin.sessions import build_sessions
from twin.timing import Origin, Temps, from_us, to_us

TZ = ZoneInfo("Europe/Paris")


def setup(tmp_path: Path) -> tuple[Corpus, DatePass]:
    c = Corpus(tmp_path / "travail" / "corpus.db")
    t = to_us(datetime(2010, 9, 15, 10, 0, tzinfo=TZ))
    items: list[Any] = [
        Author(WHATSAPP, "Julie", name="Julie", me=False), Author(WHATSAPP, "Léa", name="Léa", me=True),
        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa")),
        Message(WHATSAPP, "Julie", "Léa", "Premier jour de master, stressée", Temps.exact(t), 0),
        Author(NOTES, "moi", me=True),
        Document(NOTES, "n#0", "note", "Rentrée", "Le master commence, j'ai peur.", Temps.year(2010, TZ, Origin.PATH), 0),
        Document(NOTES, "n#1", "note", "Vieux", "Le lycée c'est fini.", Temps.year(2006, TZ, Origin.PATH), 1),
    ]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "travail" / "personnes.yaml", TZ)
    build_sessions(c)
    return c, DatePass(tmp_path, TZ)


def doc(c: Corpus, title: str) -> Any:
    return c.db.execute("SELECT * FROM documents WHERE title = ?", (title,)).fetchone()


def test_un_recoupement_resserre_et_garde_ses_ancres(tmp_path: Path) -> None:
    c, p = setup(tmp_path)
    units = list(p.units(c))
    refs = units[0][1]["refs"]
    assert any(r.startswith("d") for r in refs)
    spec = p.build(c, units[0][1])
    assert spec.mcp_config is not None and spec.mcp_config.is_file()
    assert "mcp__jumeau__corpus_chercher" in spec.allowed_tools
    assert "master" in spec.prompt
    rentree, vieux = doc(c, "Rentrée"), doc(c, "Vieux")
    msg_id = c.db.execute("SELECT id FROM messages").fetchone()["id"]
    answer = {"dates": [
        {"ref": f"d{rentree['id']}", "debut": "2010-09-01", "fin": "2010-09-30", "point": "2010-09-15",
         "ancres": [f"m{msg_id}", "m999999"], "raison": "la rentrée de master, datée par ses messages"},
        {"ref": f"d{vieux['id']}", "debut": "2009-01-01", "fin": "2009-12-31", "raison": "contredit le dossier"},
        {"ref": "d424242", "debut": "2001-01-01", "fin": "2001-01-02"},  # pas demandé : ignoré
    ]}
    assert p.accept(c, units[0][0], units[0][1], CallResult(text="", data=answer)) is None
    r = doc(c, "Rentrée")
    assert (r["t_precision"], r["t_origin"]) == ("mois", "recoupement")
    assert from_us(r["t_point"], TZ).day == 15
    session = c.db.execute("SELECT t_precision, t_point FROM sessions WHERE document = ?", (r["id"],)).fetchone()
    assert (session["t_precision"], session["t_point"]) == ("mois", r["t_point"])  # la séance suit son texte
    decided = c.db.execute("SELECT ref FROM decisions WHERE kind = 'date:document'").fetchall()
    assert [d["ref"] for d in decided] == ["n#0"]  # gardée : une relecture de la source ne l'effacera pas
    v = doc(c, "Vieux")
    assert v["t_precision"] == "annee"  # pas écrasé
    assert c.db.execute("SELECT COUNT(*) FROM conflicts WHERE ref = ?", (v["id"],)).fetchone()[0] == 1


def test_jamais_plus_large(tmp_path: Path) -> None:
    c, p = setup(tmp_path)
    rentree = doc(c, "Rentrée")
    payload = {"refs": [f"d{rentree['id']}"]}
    p.accept(c, "u", payload, CallResult(text="", data={"dates": [
        {"ref": f"d{rentree['id']}", "debut": "2008-01-01", "fin": "2012-12-31", "raison": "vague"}]}))
    assert doc(c, "Rentrée")["t_precision"] == "annee"


def test_sans_ancre_valable_c_est_du_contenu(tmp_path: Path) -> None:
    c, p = setup(tmp_path)
    rentree = doc(c, "Rentrée")
    p.accept(c, "u", {"refs": [f"d{rentree['id']}"]}, CallResult(text="", data={"dates": [
        {"ref": f"d{rentree['id']}", "debut": "2010-09-01", "fin": "2010-10-31", "ancres": ["m999999"]}]}))
    assert doc(c, "Rentrée")["t_origin"] == "contenu"
