"""Toute information en table se lit par pages (ADR 0029) : le rendu découpe une
table ou une chronologie qu'une vue a laissée entière, chaque table d'une page
garde sa propre page, et une pagination à curseur sait revenir aux plus récents
et au début — sans jamais perdre une ligne."""

from __future__ import annotations

from mika.inspector import render
from mika.kernel.inspect import (
    ActionSlot,
    Chart,
    Column,
    Disclosure,
    Entry,
    Pager,
    Param,
    Ref,
    Row,
    Series,
    Table,
    Timeline,
)


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
    assert render.blocks([short], env(), {})[0]["pager"]["total"] == 5
    one = Table(("x",), rows(5), pager=Pager(total=5, size=25))
    got = render.blocks([one], env(), {})[0]
    assert got["pager"]["pages"] == 1 and got["count"] == 5
    a, b = Table(("x",), rows(30), title="A"), Table(("x",), rows(40), title="B")
    got = render.blocks([a, b], env(), {"pg2": "2"})
    assert texts(got[0])[0] == "ligne 0" and texts(got[1])[0] == "ligne 25"  # seule B a changé de page


def test_secondary_columns_keep_their_values_and_links_on_every_page():
    source = Table((Column("ID", hint="Identifiant du message", detail=True), "Message", Column("Source", detail=True)),
                   tuple(Row((n, f"message {n}", Ref("event", str(n), f"source {n}"))) for n in range(31)))
    page = render.blocks([source], env(), {"pg1": "2"})[0]
    assert [c["label"] for c in page["columns"]] == ["Message"]
    assert texts(page) == [f"message {n}" for n in range(25, 31)]
    fields = page["rows"][0]["detail"][0]["pairs"]
    assert fields[0]["value"]["text"] == "25"
    assert fields[0]["hint"] == "Identifiant du message"
    assert fields[1]["value"]["href"] == "/inspecteur/evenement/25"
    assert page["pager"]["total"] == 31
    # Même une déclaration entièrement secondaire laisse une colonne lisible.
    fallback = render.blocks([Table((Column("clé", detail=True),), (("a",),))], env(), {})[0]
    assert texts(fallback) == ["a"] and not fallback["rows"][0]["detail"]


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


def test_all_chart_values_are_accessible_including_more_than_two_hundred_points():
    chart = Chart((Series("mesure", tuple((i, float(i)) for i in range(301))),))
    seen = []
    for number in range(1, 14):
        table = render.blocks([chart], env(), {"pg1": str(number)})[0]["table"]
        assert table["pager"]["total"] == 301
        assert len(table["rows"]) <= render.AUTO_PAGE
        seen += texts(table)
    assert seen == [str(i) for i in reversed(range(301))]


def test_tables_in_row_details_do_not_change_the_pagination_of_other_tables():
    nested = Table(("x",), rows(40))
    parent = Table(("x",), tuple(Row((f"parent {i}",), detail=(Disclosure("Détail", (nested,)),))
                                 for i in range(30)))
    sibling = Table(("x",), rows(40))
    first, other = render.blocks([parent, sibling], env(), {"pg2": "2", "pg1r0_1": "2"})
    assert texts(other)[0] == "ligne 25"
    assert first["rows"][0]["open"]
    assert first["rows"][0]["detail"][0]["open"]
    last, other = render.blocks([parent, sibling], env(), {"pg1": "2", "pg2": "2"})
    assert len(last["rows"]) == 5 and texts(other)[0] == "ligne 25"
    assert last["rows"][0]["detail"][0]["items"][0]["id"] == "pg1r25_1"
    outer = render.blocks([Disclosure("Tout", (parent,))], env(), {"pg1r0_1": "2"})[0]
    assert outer["open"]


def test_repeated_actions_get_distinct_form_slots():
    action = ActionSlot("forge.agir", (("app", "meteo"),))
    first, second = render.blocks([action, action], env(), {})
    assert first["slot"] != second["slot"]
    assert first["initial"] == second["initial"]


def test_an_unknown_cursor_total_is_never_reported_as_a_total():
    table = render.blocks([Table(("x",), rows(3), pager=Pager())], env(), {})[0]
    assert table["count"] is None and table["shown"] == 3
    assert table["pager"]["cursor"] is True
    empty = render.blocks([Table(("x",), ())], env(), {})[0]
    assert empty["pager"]["total"] == 0 and empty["pager"]["first"] == 0


def test_a_very_large_remote_total_has_only_a_bounded_number_of_page_links():
    pager = render._pager(Pager(total=2**63-1, size=25), {})
    assert len(pager["links"]) <= 7


def test_filters_show_the_validated_value_and_default_that_the_view_uses():
    specs = (Param("period", "Période", "select", (("jour", "Journée"), ("mois", "Mois")), "jour"),
             Param("active", "Actif", "bool", default="oui"), Param("n", "Nombre", "int", default="5"))
    fields, active = render.filters_ctx(specs, {"period": "journée", "n": "invalide"})
    assert [f["value"] for f in fields] == ["jour", "oui", "5"]
    assert not active
    fields, active = render.filters_ctx(specs, {"active": "non"})
    assert fields[1]["value"] == "non" and active
