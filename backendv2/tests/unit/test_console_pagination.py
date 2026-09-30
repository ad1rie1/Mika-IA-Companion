"""Toute information en table se lit par pages (ADR 0029) : le rendu découpe une
table ou une chronologie qu'une vue a laissée entière, chaque table d'une page
garde sa propre page, et une pagination à curseur sait revenir aux plus récents
et au début — sans jamais perdre une ligne."""

from __future__ import annotations

from mika.inspector import render
from mika.kernel.inspect import Entry, Pager, Table, Timeline


def env() -> render.Env:
    return render.Env(when=str, now=0)


def rows(n: int) -> tuple[tuple[str], ...]:
    return tuple((f"ligne {i}",) for i in range(n))


def texts(table: dict) -> list[str]:
    return [r["cells"][0]["text"] for r in table["rows"]]


def test_a_long_table_without_pager_is_cut_into_pages_and_nothing_is_lost():
    t = Table(("x",), rows(60), title="Tout")
    first = render.blocks([t], env(), {})[0]
    assert len(first["rows"]) == render.AUTO_PAGE and first["count"] == 60
    assert first["pager"]["total"] == 60 and first["pager"]["next"].endswith("pg1=2")
    seen = []
    for page in (1, 2, 3):
        seen += texts(render.blocks([t], env(), {"pg1": str(page)})[0])
    assert seen == [f"ligne {i}" for i in range(60)]  # chaque ligne, une seule fois
    assert texts(render.blocks([t], env(), {"pg1": "99"})[0])[-1] == "ligne 59"  # une page hors bornes est ramenée


def test_a_short_table_is_left_whole_and_two_tables_page_independently():
    short = Table(("x",), rows(5))
    assert render.blocks([short], env(), {})[0]["pager"] is None
    one = Table(("x",), rows(5), pager=Pager(total=5, size=25))
    got = render.blocks([one], env(), {})[0]
    assert got["pager"] is None and got["count"] == 5  # une seule page : pas de pageur, l'en-tête dit combien
    a, b = Table(("x",), rows(30), title="A"), Table(("x",), rows(40), title="B")
    got = render.blocks([a, b], env(), {"pg2": "2"})
    assert texts(got[0])[0] == "ligne 0" and texts(got[1])[0] == "ligne 25"  # seule B a changé de page


def test_a_view_pager_wins_and_a_long_timeline_is_cut_too():
    t = Table(("x",), rows(50), pager=Pager(total=500, number=3))
    assert len(render.blocks([t], env(), {})[0]["rows"]) == 50  # la vue a déjà découpé : rien de plus
    line = Timeline(tuple(Entry(at=i, title=f"t{i}") for i in range(40)))
    got = render.blocks([line], env(), {})[0]
    assert len(got["entries"]) == render.AUTO_PAGE and got["pager"]["total"] == 40


def test_a_cursor_goes_back_to_newer_pages_and_to_the_start():
    first = render._pager(Pager(older=(("avant", "90"),)), {"q": "x"})
    assert first["older"] == "?q=x&avant=90&pile=0" and not first["newer"]
    second = render._pager(Pager(older=(("avant", "40"),)), {"q": "x", "avant": "90", "pile": "0"})
    assert second["newer"] == "?q=x" and second["page"] == 2
    third = render._pager(Pager(older=(("avant", "10"),)), {"q": "x", "avant": "40", "pile": "0,90"})
    assert third["newer"] == "?q=x&avant=90&pile=0" and third["first"] == "?q=x" and third["page"] == 3
    # une seconde table à curseur a son propre chemin : elle ne dérange pas la première
    other = render._pager(Pager(older=(("avant_nuits", "7"),)), {"avant": "40", "pile": "0,90"})
    assert "avant=40" in other["older"] and "pile=0%2C90" in other["older"] and "pile_avant_nuits=0" in other["older"]
    last = render._pager(Pager(), {"avant": "10", "pile": "0,90,40"})
    assert last is not None and not last["older"] and last["newer"] == "?avant=40&pile=0%2C90"

    # la dernière page d'une seconde table à curseur sait encore revenir (la vue nomme sa clé)
    tail = render._pager(Pager(param="avant_nuits"), {"avant_nuits": "5", "pile_avant_nuits": "0,9"})
    assert tail is not None and tail["newer"] == "?avant_nuits=9&pile_avant_nuits=0" and tail["page"] == 3
