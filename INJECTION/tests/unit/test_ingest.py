"""De brut/ au corpus : ingestion idempotente, doublons, datation par l'ordre, revue à la main."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from twin.cli import main
from twin.corpus import Corpus
from twin.dating import date_corpus, parse_manual
from twin.ingest import ingest
from twin.readers import ReadContext
from twin.timing import Origin, Precision, from_us

TZ = ZoneInfo("Europe/Paris")

CHAT = """12/03/2019 à 14:05 - Julie: Salut
12/03/2019 à 14:07 - Léa: Coucou
"""
CHAT_LONGER = CHAT + "13/03/2019 à 09:00 - Julie: Bien dormi ?\n"


def brut(tmp_path: Path) -> Path:
    root = tmp_path / "brut"
    (root / "whatsapp").mkdir(parents=True)
    (root / "whatsapp" / "Discussion WhatsApp avec Julie.txt").write_text(CHAT, encoding="utf-8")
    (root / "notes" / "2009").mkdir(parents=True)
    (root / "notes" / "2009" / "carnet.txt").write_text(
        "12 mars\nJulie m'a appelée.\n\nmardi 13 mars\nRien de spécial.\n\n14 mars\nCiné.\n", encoding="utf-8")
    (root / "notes" / "sans-date.txt").write_text("Une liste d'envies.", encoding="utf-8")
    (root / "photos").mkdir()
    (root / "photos" / "a.jpg").write_bytes(b"\xff\xd8")
    (root / "bizarre.dat").write_text("???", encoding="utf-8")
    return root


def test_ingestion_relance_et_chevauchement(tmp_path: Path) -> None:
    root = brut(tmp_path)
    corpus = Corpus(tmp_path / "travail" / "corpus.db")
    ctx = ReadContext(tz=TZ, root=root)
    r1 = ingest(corpus, root, ctx)
    assert r1.read == {"whatsapp": 1, "notes": 2}
    assert r1.unknown == ["bizarre.dat"] and r1.skipped_media == 1
    assert r1.messages == 2 and r1.documents == 4

    r2 = ingest(corpus, root, ctx)  # rien n'a changé : rien n'est relu
    assert r2.read == {} and r2.skipped_unchanged == 3

    # un second export de la même discussion, plus long : seul le nouveau message entre
    (root / "whatsapp" / "Discussion WhatsApp avec Julie (2).txt").write_text(CHAT_LONGER, encoding="utf-8")
    r3 = ingest(corpus, root, ctx)
    assert r3.messages == 1 and r3.duplicates == 2
    assert corpus.db.execute("SELECT COUNT(*) FROM conversations WHERE channel = 'whatsapp'").fetchone()[0] == 1

    # la recherche plein texte trouve sans accents
    hits = corpus.db.execute("SELECT rowid FROM fts_documents WHERE fts_documents MATCH 'appelee'").fetchall()
    assert len(hits) == 1
    s = corpus.stats()
    assert s["moi"] >= 1 and s["messages"] == 3


def test_datation_puis_revue_a_la_main(tmp_path: Path) -> None:
    root = brut(tmp_path)
    corpus = Corpus(tmp_path / "travail" / "corpus.db")
    ingest(corpus, root, ReadContext(tz=TZ, root=root))
    review = tmp_path / "travail" / "dates.yaml"
    report = date_corpus(corpus, review, TZ)
    assert report.conflicts == 0

    rows = corpus.db.execute("SELECT key, t_point, t_precision FROM documents ORDER BY key").fetchall()
    carnet = [r for r in rows if r["key"].startswith("notes/2009/carnet.txt#")]
    days = [from_us(r["t_point"], TZ).date() for r in carnet]
    assert days == [date(2009, 3, 12), date(2009, 3, 13), date(2009, 3, 14)]  # « 2009 » vient du dossier

    data = yaml.safe_load(review.read_text(encoding="utf-8"))
    todo = [e for e in data["a_dater"] if e.get("document") == "notes/sans-date.txt"]
    assert todo and todo[0]["estime"].startswith("au plus tard")

    # on écrit une date à la main : elle s'applique au passage suivant
    for e in data["a_dater"]:
        if e.get("document") == "notes/sans-date.txt":
            e["date"] = "été 2011"
    review.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    report2 = date_corpus(corpus, review, TZ)
    assert report2.manual == 1
    row = corpus.db.execute("SELECT * FROM documents WHERE key = 'notes/sans-date.txt'").fetchone()
    t = corpus.temps_of(row)
    assert t.origin == Origin.MANUAL and t.precision == Precision.SEASON
    data3 = yaml.safe_load(review.read_text(encoding="utf-8"))
    assert not [e for e in data3["a_dater"] if e.get("document") == "notes/sans-date.txt"]


def test_date_a_la_main_en_plage() -> None:
    t = parse_manual("2008..2010", TZ)
    assert t is not None and t.precision == Precision.RANGE
    assert from_us(t.start, TZ).year == 2008 and from_us(t.end, TZ).year == 2010  # type: ignore[arg-type]
    assert parse_manual("n'importe quoi", TZ) is None
    assert parse_manual("2011..2009", TZ) is None


def test_cli_de_bout_en_bout(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    brut(tmp_path)
    racine = ["--racine", str(tmp_path)]
    assert main([*racine, "ingerer", "--silence"]) == 0
    assert main([*racine, "dater"]) == 0
    assert main([*racine, "etat"]) == 0
    out = capsys.readouterr().out
    assert "messages" in out and "précision des dates" in out
    assert (tmp_path / "travail" / "inconnus.txt").read_text(encoding="utf-8") == "bizarre.dat\n"
