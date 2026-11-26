"""Les fichiers du chat (ADR 0312), sans serveur : la sorte d'un fichier, une page et ses filtres, l'état d'une pièce
de la personne et d'un fichier de Mika."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from mika.app.me.chat import REASONS, SORTES, ChatFile, _hers, _piece, page_of, sorte_of

KEY = "a" * 32


@pytest.mark.parametrize(("name", "mime", "kind", "sorte"), [
    ("tableau.jpg", "image/jpeg", "image", "image"),
    ("sans-extension", "image/png", "file", "image"),
    ("devis.pdf", "application/octet-stream", "file", "pdf"),
    ("devis.bin", "application/pdf", "file", "pdf"),
    ("comparatif.csv", "text/plain", "file", "tableau"),
    ("export", "text/csv; charset=utf-8", "file", "tableau"),
    ("notes.md", "", "file", "texte"),
    ("build.log", "application/octet-stream", "file", "texte"),
    ("donnees.json", "application/json", "file", "texte"),
    ("budget.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "file", "autre"),
    ("voix.mp3", "audio/mpeg", "audio", "autre"),
    ("archive.zip", "", "file", "autre"),
])
def test_a_file_has_one_sort(name: str, mime: str, kind: str, sorte: str) -> None:
    assert sorte_of(name, mime, kind) == sorte


def _file(n: int, name: str, sorte: str, sender: str = "toi", available: bool = True) -> ChatFile:
    return ChatFile(key=f"{n:032x}", id=f"{n:032x}", name=name, mime="", size=n, sorte=sorte, sender=sender,
                    at=n, message=n, index=0, available=available, reason="" if available else "retention")


FILES = [_file(9, "Été à Annecy.jpg", "image"), _file(8, "devis-lefevre.pdf", "pdf"),
         _file(7, "comparatif devis.csv", "tableau", "mika"), _file(6, "notes.md", "texte"),
         _file(5, "vieille photo.png", "image", available=False)]


def test_a_page_counts_each_sort_within_the_search_and_the_sender() -> None:
    got = page_of(FILES)
    assert got["total"] == 5 and got["unavailable"] == 1
    assert got["counts"] == {"": 5, "image": 2, "pdf": 1, "texte": 1, "tableau": 1, "autre": 0}
    assert set(got["counts"]) == {"", *SORTES}
    devis = page_of(FILES, q="DEVIS", sorte="pdf")
    assert [i["name"] for i in devis["items"]] == ["devis-lefevre.pdf"]
    assert devis["counts"] == {"": 2, "image": 0, "pdf": 1, "texte": 0, "tableau": 1, "autre": 0}
    assert [i["name"] for i in page_of(FILES, q="ete annecy")["items"]] == ["Été à Annecy.jpg"]
    assert page_of(FILES, q="annecy devis")["total"] == 0  # chaque mot
    assert [i["name"] for i in page_of(FILES, sender="mika")["items"]] == ["comparatif devis.csv"]


def test_pages_follow_each_other_and_stay_within_bounds() -> None:
    first = page_of(FILES, per=2)
    assert [i["name"] for i in first["items"]] == ["Été à Annecy.jpg", "devis-lefevre.pdf"] and first["pages"] == 3
    assert [i["name"] for i in page_of(FILES, per=2, page=3)["items"]] == ["vieille photo.png"]
    assert page_of(FILES, per=2, page=40)["page"] == 3 and page_of(FILES, per=2, page=0)["page"] == 1
    empty = page_of([], q="rien")
    assert empty["items"] == [] and empty["pages"] == 1 and empty["page"] == 1


def test_only_what_downloads_has_an_address() -> None:
    removed, kept = page_of(FILES, q="photo")["items"] + page_of(FILES, q="annecy")["items"]
    assert "url" not in removed and removed["reason"] == "retention" and removed["available"] is False
    assert kept["url"] == f"/files/{9:032x}" and "reason" not in kept


def _row(**kw):
    base = {"name": "note.txt", "mime": "text/plain", "size": 4, "handle": "web:bea", "expired_at": None,
            "reason": None, "stored": True}
    return NS(**(base | kw))


@pytest.mark.parametrize(("meta", "row", "available", "reason"), [
    ({"name": "note.txt", "kind": "file", "file": KEY}, _row(), True, ""),
    ({"name": "note.txt", "kind": "file", "file": KEY}, None, False, "missing"),
    ({"name": "note.txt", "kind": "file"}, None, False, "unkept"),
    ({"name": "note.txt", "kind": "file", "file": KEY}, _row(stored=False), False, "unkept"),
    ({"name": "note.txt", "kind": "file", "file": KEY}, _row(expired_at=5, reason="budget"), False, "budget"),
    ({"name": "note.txt", "kind": "file", "file": KEY}, _row(expired_at=5, reason="missing"), False, "missing"),
    ({"name": "note.txt", "kind": "file", "file": KEY}, _row(handle="web:chloe"), False, "missing"),
])
def test_her_piece_says_whether_it_downloads_and_why_not(meta, row, available, reason) -> None:
    mine = {KEY: row} if row is not None else {}
    got = _piece(meta, 1, 40, 7, mine, "web:bea")
    assert (got.available, got.reason) == (available, reason) and reason in ("", *REASONS)
    assert got.sender == "toi" and got.message == 40 and got.index == 1
    assert got.key == "40-1"  # son message et sa place : la même pièce renvoyée n'a pas deux fois la même clé
    if row is not None and row.handle != "web:bea":
        assert got.size == 0  # une pièce d'une autre adresse ne dit rien d'elle


def test_the_same_piece_sent_again_keeps_the_name_of_each_message() -> None:
    first = _piece({"name": "chantier-3.jpg", "kind": "image", "file": KEY}, 0, 50, 7,
                   {KEY: _row(name="chantier-1.jpg", mime="image/jpeg")}, "web:bea")
    assert first.name == "chantier-3.jpg" and first.sorte == "image" and first.available


def test_a_file_she_sent_downloads_only_where_this_account_reads_the_thread() -> None:
    row = NS(id=KEY, name="courses.md", mime="text/markdown", size=9, kind="file", gone=False, sent=True,
             person="web:bea", reason=None)
    got = _hers({"id": KEY}, 0, 41, 8, {KEY: row}, {"web:bea"})
    assert got is not None and got.available and got.sender == "mika" and got.sorte == "texte"
    elsewhere = _hers({"id": KEY}, 0, 41, 8, {KEY: row}, {"web:chloe"})
    assert elsewhere is not None and not elsewhere.available and elsewhere.reason == "missing"
    retired = _hers({"id": KEY}, 0, 41, 8, {KEY: NS(**(vars(row) | {"gone": True, "reason": "retention"}))},
                    {"web:bea"})
    assert retired is not None and retired.reason == "retention"
    assert _hers({"id": "b" * 32}, 0, 41, 8, {KEY: row}, {"web:bea"}) is None  # inconnu : oublié, rien
