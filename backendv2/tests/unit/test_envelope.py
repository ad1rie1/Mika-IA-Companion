"""L'enveloppe JSON des vues d'apps forgées : un décodeur qui ne lève jamais,
ne laisse rien passer de dangereux, nomme le premier problème par son chemin,
et relit à l'identique ce que l'encodeur écrit."""

from __future__ import annotations

import functools
import json
import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mika.kernel.envelope import VERSION, Limits, decode, encode, schema
from mika.kernel.inspect import (
    BLOCKS,
    TONES,
    ActionSlot,
    Badge,
    Chart,
    Code,
    Column,
    Disclosure,
    Entry,
    Fields,
    Grid,
    Meter,
    Nav,
    NavItem,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Section,
    Series,
    Stat,
    Stats,
    Swatch,
    Table,
    Text,
    Timeline,
    When,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - dépendance transitive, facultative
    jsonschema = None

PROFILE = settings(max_examples=200, deadline=None,
                   suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large,
                                          HealthCheck.large_base_example])


# ── Outils ────────────────────────────────────────────────────────────────


class Echo:
    """Reconnaît toute vue : relit à l'identique un lien de vue encodé."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def view(self, key, params):
        self.calls.append((key, dict(params)))
        return Ref("view", key, "", tuple(params.items()))


class Known:
    """Ne reconnaît que quelques vues de l'app « meteo »."""

    def __init__(self, *keys: str) -> None:
        self.keys = keys

    def view(self, key, params):
        return Ref.view("forge", f"meteo/{key}", "", **params) if key in self.keys else None


def env(*blocks) -> dict:
    return {"version": VERSION, "blocks": list(blocks)}


def is_invalid(out) -> bool:
    return (len(out) == 1 and isinstance(out[0], Note) and out[0].tone == "danger"
            and out[0].title == "Vue invalide")


def invalid(payload, **kw) -> str:
    out = decode(payload, **kw)
    assert is_invalid(out), out
    return out[0].text


def ok(payload, **kw) -> list:
    out = decode(payload, **kw)
    assert not is_invalid(out), out[0].text
    return out


def note(text: str = "n") -> dict:
    return {"type": "note", "text": text}


def nested(levels: int) -> dict:
    """Des sections imbriquées sur ``levels`` niveaux de blocs (la note du fond comprise)."""
    block = note("fond")
    for _ in range(levels - 1):
        block = {"type": "section", "title": "s", "items": [block]}
    return block


_validator = None


def validate(payload: dict) -> None:
    """Le payload respecte le schéma publié (si ``jsonschema`` est là)."""
    global _validator
    if jsonschema is None:
        return
    if _validator is None:
        _validator = jsonschema.Draft202012Validator(schema())
    _validator.validate(payload)


# ── Un exemple riche : chaque bloc, chaque genre de cellule ───────────────

RICH = [
    Table(
        columns=("Nom", Column("Valeur", align="num", hint="en unités"), Column("État", align="fit")),
        rows=(
            ("a", 1, None),
            ("b", 2.5, True),
            Row(("c", Text("12", kind="num", tone="ok", hint="douze", clamp=4), Badge("vif", tone="warn")),
                href=Ref.view("forge", "meteo/detail", "voir", id="3"), tone="info",
                detail=(Note("dans le détail", tone="muted"), ActionSlot("relancer", initial=(("id", "3"),)))),
            (Text("mono", kind="mono"), Text("gris", kind="muted"), Meter(0.4, text="40 %", tone="ok")),
            (Swatch("joie", "emotion", "happy", 0.7), When(1_790_000_000_000_000), When(5, relative=False)),
            (Ref.url("https://example.org/a?b=c#d", "doc"), Ref.view("forge", "meteo/liste", "liste"), Text("—")),
        ),
        title="Tableau", caption="légende", empty="vide", pager=Pager(number=2, size=6, total=12),
        filters=("etat", "q"),
    ),
    Fields((("âge", 3), ("humeur", Swatch("calme", "emotion", "relieved"))), title="Fiche",
           hints=(("âge", "en jours"),), columns=2),
    Note("attention", tone="warn", title="Note"),
    Prose("un long récit\nsur deux lignes\tet une tabulation", title="Récit", clamp=200),
    Code("print('x')", title="Code"),
    Stats((Stat("messages", 42, sub="aujourd'hui", tone="ok", href=Ref.url("https://example.org", "x"),
                trend=Chart((Series("n", ((0, 1.0), (1, 2.0))),), kind="spark")),
           Stat("taux", Meter(0.5))), title="Chiffres"),
    Timeline((Entry(10, "début", text="ça commence", tone="info",
                    href=Ref.view("forge", "meteo/e", "e", n="1"), meta="auto"),
              Entry(20, "fin")), title="Fil", empty="rien"),
    Chart((Series("a", ((0, 0.5), (60, -0.25)), slot=1), Series("b", ((0, 1.0),), slot=2)), kind="bars",
          title="Courbe", unit="%", y=(-1.0, 1.0), zero=0.0, since=0, until=60, empty="aucune", table=False),
    Grid((Note("g1"), Prose("g2")), columns=3),
    Section("Partie", (Disclosure("Plus", (Code("x"),), open=True),), description="desc"),
    ActionSlot("envoyer", initial=(("to", "a@b.c"), ("n", "2")), title="Envoyer", compact=True),
    Nav((NavItem("Réception", Ref.view("forge", "meteo/liste", "", dossier="INBOX"), count=3, active=True),
         NavItem("Archives", Ref.url("https://example.org/archives", ""), count="12+", tone="warn")),
        title="Dossiers"),
]

ALL_TYPES = {"table", "fields", "note", "prose", "code", "stats", "timeline", "chart", "grid", "section",
             "disclosure", "form", "nav"}
ALL_KINDS = {"text", "mono", "num", "muted", "badge", "meter", "emotion", "when", "link"}


def _walk(value):
    yield value
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def test_rich_example_round_trips():
    payload = encode(RICH)
    assert decode(payload, links=Echo()) == RICH
    # par le texte JSON aussi : ce qu'une app écrirait réellement
    assert decode(json.loads(json.dumps(payload)), links=Echo()) == RICH
    assert encode(decode(payload, links=Echo())) == payload


def test_rich_example_covers_every_block_and_cell_kind():
    payload = encode(RICH)
    dicts = [v for v in _walk(payload) if isinstance(v, dict)]
    assert {d["type"] for d in dicts if "type" in d} == ALL_TYPES
    assert {d["kind"] for d in dicts if "kind" in d and "type" not in d} == ALL_KINDS


def test_rich_example_validates_against_schema():
    pytest.importorskip("jsonschema")
    validate(encode(RICH))


def test_hand_written_payload():
    """Ce qu'une app écrit à la main : colonnes nues, cellules par clé, tons
    hérités, lien de vue à paramètres entiers."""
    links = Known("detail")
    out = ok(env({
        "type": "table", "title": "Villes",
        "columns": ["ville", {"key": "t", "label": "Température", "align": "num"}],
        "rows": [
            ["Paris", {"kind": "num", "text": "21"}],
            {"cells": {"t": 18, "ville": {"kind": "link", "text": "Lyon", "view": "detail", "params": {"id": 7}}},
             "tone": "ko", "detail": [{"type": "note", "text": "orage", "tone": "mut"}]},
        ],
    }), links=links)
    table = out[0]
    assert table.columns == ("ville", Column("Température", align="num"))
    assert table.rows[0] == ("Paris", Text("21", kind="num"))
    row = table.rows[1]
    assert row.cells == (Ref("view", "forge/meteo/detail", "Lyon", (("id", "7"),)), 18)
    assert row.tone == "danger" and row.detail == (Note("orage", tone="muted"),)


def test_empty_envelope_is_valid():
    assert decode(env()) == []


# ── Propriétés ────────────────────────────────────────────────────────────

_KEYS = ["version", "blocks", "type", "kind", "text", "title", "items", "columns", "rows", "cells", "label",
         "value", "key", "url", "view", "params", "href", "detail", "tone", "pagination", "page", "total",
         "per_page", "series", "points", "at", "ratio", "action", "initial", "open", "description", "y", "zero",
         "trend", "hint", "slot", "weight"]
_WORDS = sorted(ALL_TYPES | ALL_KINDS | {"emoji", "happy", "ko", "danger", "line", "https://x.org/a",
                                         "javascript:alert(1)", "//evil.org", "data:,x"})
_LEAF = st.one_of(
    st.none(), st.booleans(), st.integers(), st.integers(min_value=10**30, max_value=10**400),
    st.floats(), st.text(max_size=20), st.sampled_from(_WORDS),
    st.integers(9_990, 12_000).map(lambda n: "x" * n),
)
_JSON = st.recursive(_LEAF, lambda children: st.lists(children, max_size=5)
                     | st.dictionaries(st.sampled_from(_KEYS) | st.text(max_size=4), children, max_size=6),
                     max_leaves=40)
_BLOCK_LIKE = st.fixed_dictionaries({"type": st.sampled_from(sorted(ALL_TYPES) + ["emoji"])},
                                    optional={k: _JSON for k in _KEYS if k != "type"})


def _deep_list(n: int) -> list:
    x: list = []
    for _ in range(n):
        x = [x]
    return x


def _deep_sections(n: int) -> dict:
    return env(nested(n))


_PAYLOADS = st.one_of(
    _JSON,
    st.lists(_BLOCK_LIKE, max_size=4).map(lambda b: env(*b)),
    st.integers(1, 20_000).map(_deep_list),
    st.integers(1, 3_000).map(_deep_sections),
)


def _check_outcome(out) -> None:
    """Soit des blocs, soit une seule note « Vue invalide » ; ce qui passe se
    ré-encode, respecte le schéma et se relit à l'identique."""
    assert isinstance(out, list)
    assert all(isinstance(b, BLOCKS) for b in out)
    if is_invalid(out):
        assert " : " in out[0].text
        return
    again = encode(out)
    validate(again)
    assert decode(again, links=Echo()) == out


@PROFILE
@given(_PAYLOADS)
def test_random_json_never_raises(payload):
    _check_outcome(decode(payload, links=Echo()))


# un arbre valide, borné en profondeur (4) et en taille (bien sous 200 blocs)
_TEXT = st.text(st.characters(exclude_categories=("Cs", "Cc")), max_size=12)
_NONEMPTY = st.text(st.characters(exclude_categories=("Cs", "Cc")), min_size=1, max_size=12)
_TONE = st.sampled_from(TONES)
_PARAM = st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True)
_VIEW_KEY = st.from_regex(r"[a-z][a-z0-9_]{0,6}(/[a-z][a-z0-9_]{0,6}){0,2}", fullmatch=True)
_URL = st.builds(lambda s, h, p: f"{s}://{h}.org/{p}", st.sampled_from(["http", "https"]),
                 st.from_regex(r"[a-z]{1,8}", fullmatch=True), st.from_regex(r"[a-z0-9]{0,8}", fullmatch=True))
_REF = st.one_of(
    st.builds(lambda k, t, p: Ref("view", k, t, tuple(p.items())), _VIEW_KEY, _TEXT,
              st.dictionaries(_PARAM, _TEXT, max_size=3)),
    st.builds(lambda u, t: Ref("url", u, t), _URL, _TEXT),
)
_UNIT = st.floats(0, 1)
_FLOAT = st.floats(allow_nan=False, allow_infinity=False)
_INSTANT = st.integers(0, 2**62)
_CELL = st.one_of(
    st.none(), st.booleans(), st.integers(-(2**63), 2**63 - 1), _FLOAT, _TEXT,
    st.builds(Text, _TEXT, kind=st.sampled_from(("text", "mono", "num", "muted")), tone=_TONE, hint=_TEXT,
              clamp=st.integers(0, 100)),
    st.builds(Badge, _TEXT, tone=_TONE),
    st.builds(Meter, _UNIT, text=_TEXT, tone=_TONE),
    st.builds(lambda t, k, w: Swatch(t, "emotion", k, w), _TEXT, st.sampled_from(("happy", "sad", "curious")),
              st.none() | _UNIT),
    st.builds(When, _INSTANT, relative=st.booleans()),
    _REF,
)
_MAX_DEPTH = 4


@st.composite
def _charts(draw):
    series = draw(st.lists(st.builds(Series, _TEXT, st.lists(st.tuples(_INSTANT, _FLOAT), max_size=5).map(tuple),
                                     slot=st.integers(0, 4)), max_size=4).map(tuple))
    y = draw(st.none() | st.tuples(st.floats(-1e6, 1e6), st.floats(1e-3, 1e6)).map(lambda p: (p[0], p[0] + p[1])))
    since, until = draw(st.none() | _INSTANT), draw(st.none() | _INSTANT)
    if since is not None and until is not None and since > until:
        since, until = until, since
    return Chart(series, kind=draw(st.sampled_from(("line", "bars", "spark"))), title=draw(_TEXT),
                 unit=draw(st.sampled_from(("", "%", "$"))), y=y, zero=draw(st.none() | _FLOAT), since=since,
                 until=until, empty=draw(_TEXT), table=draw(st.booleans()))


@st.composite
def _pagers(draw, rows: int):
    size = draw(st.integers(max(1, rows), 200))
    return Pager(number=1, size=size, total=draw(st.integers(rows, 10_000)))


@st.composite
def _tables(draw, depth: int):
    columns = draw(st.lists(st.one_of(_NONEMPTY, st.builds(Column, _TEXT, align=st.sampled_from(("", "num", "fit")),
                                                           hint=_TEXT)),
                            max_size=4, unique_by=lambda c: c if isinstance(c, str) else ("\0", c)))
    cells = st.lists(_CELL, min_size=len(columns), max_size=len(columns)).map(tuple)
    detail = st.lists(_blocks_at(depth + 1), max_size=1).map(tuple) if depth < _MAX_DEPTH else st.just(())
    rows = draw(st.lists(cells | st.builds(Row, cells, href=st.none() | _REF, tone=_TONE, detail=detail),
                         max_size=2).map(tuple))
    return Table(tuple(columns), rows, title=draw(_TEXT), empty=draw(_TEXT), caption=draw(_TEXT),
                 pager=draw(st.none() | _pagers(len(rows))),
                 filters=draw(st.lists(_PARAM, unique=True, max_size=3).map(tuple)))


@st.composite
def _fields(draw):
    items = draw(st.lists(st.tuples(_TEXT, _CELL, st.none() | _NONEMPTY), max_size=4))
    return Fields(tuple((label, cell) for label, cell, _ in items), title=draw(_TEXT),
                  hints=tuple((label, hint) for label, _, hint in items if hint), columns=draw(st.integers(1, 3)))


@functools.cache
def _blocks_at(depth: int):
    leaves = st.one_of(
        st.builds(Note, _TEXT, tone=_TONE, title=_TEXT),
        st.builds(Prose, _TEXT, title=_TEXT, clamp=st.integers(0, 100)),
        st.builds(Code, _TEXT, title=_TEXT),
        _fields(),
        st.builds(Stats, st.lists(st.builds(Stat, _TEXT, _CELL, sub=_TEXT, tone=_TONE, href=st.none() | _REF,
                                            trend=st.none() | _charts()), max_size=3).map(tuple), title=_TEXT),
        st.builds(Timeline, st.lists(st.builds(Entry, _INSTANT, _TEXT, text=_TEXT, tone=_TONE,
                                               href=st.none() | _REF, meta=_TEXT), max_size=3).map(tuple),
                  title=_TEXT, empty=_TEXT),
        _charts(),
        st.builds(ActionSlot, st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
                  initial=st.dictionaries(_PARAM, _TEXT, max_size=3).map(lambda d: tuple(d.items())),
                  title=_TEXT, compact=st.booleans()),
        _tables(depth),
    )
    if depth >= _MAX_DEPTH:
        return leaves
    children = st.lists(st.deferred(lambda: _blocks_at(depth + 1)), max_size=2).map(tuple)
    return st.one_of(
        leaves,
        st.builds(Grid, children, columns=st.integers(1, 3)),
        st.builds(Section, _TEXT, children, description=_TEXT),
        st.builds(Disclosure, _TEXT, children, open=st.booleans()),
    )


_TREES = st.lists(_blocks_at(1), max_size=3)


@PROFILE
@given(_TREES)
def test_valid_trees_round_trip(blocks):
    payload = encode(blocks)
    validate(payload)
    assert decode(payload, links=Echo()) == blocks
    assert decode(json.loads(json.dumps(payload)), links=Echo()) == blocks


def _slots(value, out):
    """Toutes les places (conteneur, clé) d'un payload JSON."""
    if isinstance(value, dict):
        for k, v in value.items():
            out.append((value, k))
            _slots(v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.append((value, i))
            _slots(v, out)
    return out


_NEARBY = st.one_of(st.integers(-3, 3), st.floats(), st.text(max_size=3), st.booleans(), st.none(),
                    st.sampled_from(["ko", "danger", "https://example.org", "javascript:x", "emoji", "line"]))


@PROFILE
@given(_TREES, st.data())
def test_mutated_valid_payload_never_raises(blocks, data):
    """Un payload valide altéré en une place (valeur remplacée par du JSON
    quelconque ou une valeur voisine, clé retirée, élément dupliqué) : jamais
    d'exception, et ce qui passe se relit à l'identique."""
    payload = encode(blocks)
    slots = _slots(payload, [])
    if slots:
        container, key = data.draw(st.sampled_from(slots))
        match data.draw(st.sampled_from(["json", "nearby", "delete", "duplicate"])):
            case "json":
                container[key] = data.draw(_JSON)
            case "nearby":
                container[key] = data.draw(_NEARBY)
            case "delete":
                del container[key]
            case _:
                if isinstance(container, list):
                    container.insert(key, json.loads(json.dumps(container[key])))
    _check_outcome(decode(payload, links=Echo()))


# ── Bornes : juste en deçà passe, juste au-delà échoue au bon chemin ──────


def test_limit_depth():
    ok(env(nested(8)))
    assert invalid(env(nested(9))) == "blocks[0]" + ".items[0]" * 8 + " : imbrication au-delà de 8 niveaux"


def test_limit_depth_counts_row_details():
    def table(detail):
        return {"type": "table", "columns": ["a"], "rows": [{"cells": [1], "detail": [detail]}]}

    ok(env(table(nested(7))))
    text = invalid(env(table(nested(8))))
    assert text.startswith("blocks[0].rows[0].detail[0].items[0]") and "imbrication" in text


def test_limit_depth_is_injectable():
    ok(env(nested(2)), limits=Limits(depth=2))
    assert "au-delà de 2 niveaux" in invalid(env(nested(3)), limits=Limits(depth=2))


def test_limit_blocks_counted_across_nesting():
    def section(n):
        return {"type": "section", "title": "s", "items": [note() for _ in range(n)]}

    ok(env(section(99), section(99)))  # 2 + 198 = 200
    assert invalid(env(section(99), section(100))) == "blocks[1].items : plus de 200 blocs au total"
    ok(env(*[note() for _ in range(200)]))
    assert invalid(env(*[note() for _ in range(201)])) == "blocks : plus de 200 blocs au total"


def test_limit_rows():
    def table(n):
        return {"type": "table", "columns": ["a"], "rows": [[i] for i in range(n)]}

    ok(env(table(200)))
    assert invalid(env(table(201))) == "blocks[0].rows : plus de 200 lignes"


def test_limit_columns():
    def table(n):
        return {"type": "table", "columns": [f"c{i}" for i in range(n)], "rows": [list(range(n))]}

    ok(env(table(30)))
    assert invalid(env(table(31))) == "blocks[0].columns : plus de 30 colonnes"


def test_limit_items():
    def fields(n):
        return {"type": "fields", "items": [{"label": "l", "value": i} for i in range(n)]}

    ok(env(fields(200)))
    assert invalid(env(fields(201))) == "blocks[0].items : plus de 200 champs"


def test_limit_chars_per_string():
    ok(env({"type": "prose", "text": "x" * 10_000}))
    assert invalid(env({"type": "prose", "text": "x" * 10_001})) == \
        "blocks[0].text : texte de plus de 10000 caractères"


def test_limit_total_chars():
    full = [{"type": "prose", "text": "x" * 10_000} for _ in range(30)]
    ok(env(*full))  # 300 000 tout juste
    assert invalid(env(*full, note("y"))) == "blocks[30].text : plus de 300000 caractères au total"


def test_limit_points():
    def chart(*sizes):
        return {"type": "chart", "series": [{"label": "s", "points": [[i, 0.5] for i in range(n)]}
                                            for n in sizes]}

    ok(env(chart(2_000)))
    ok(env(chart(1_000, 1_000)))
    assert invalid(env(chart(1_000, 1_001))) == "blocks[0].series[1].points : plus de 2000 points au total"


def test_limit_series():
    def chart(n):
        return {"type": "chart", "series": [{"label": f"s{i}", "points": []} for i in range(n)]}

    ok(env(chart(4)))
    assert invalid(env(chart(5))) == "blocks[0].series : plus de 4 séries"


# ── Liens ─────────────────────────────────────────────────────────────────


def _url_field(url: str) -> dict:
    return env({"type": "fields", "items": [{"label": "l", "value": {"kind": "link", "text": "t", "url": url}}]})


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox",
    "ftp://example.org/x",
    "//evil.example/x",
    "/relative/path",
    "relative/path",
    "?q=1",
    "#frag",
    "http:example.org",
    "https:///path",
    "https://user:pass@example.org/",
    "https://user@example.org/",
    "https://example.org\\@evil.org/",
    "https://exa mple.org/",
    " https://example.org/",
    "https://example.org/\x00",
    "https://example.org/\n",
    "https://example.org/‮",
    "https://[::1/",
    "https://example.org:99999/",
    "",
])
def test_unsafe_urls_refused(url):
    text = invalid(_url_field(url))
    assert text.startswith("blocks[0].items[0].value.url : "), text


@pytest.mark.parametrize("url", [
    "https://example.org",
    "http://example.org:8080/a?b=c#d",
    "HTTPS://Example.org/x",
    "https://[::1]/x",
    "https://exemple.fr/é",
])
def test_http_urls_accepted(url):
    assert ok(_url_field(url))[0].pairs[0][1] == Ref("url", url, "t")


def test_url_hrefs_follow_the_same_rules():
    row = {"type": "table", "columns": ["a"], "rows": [{"cells": [1], "href": {"kind": "link", "url": "javascript:x"}}]}
    assert invalid(env(row)).startswith("blocks[0].rows[0].href.url : ")
    stat = {"type": "stats", "items": [{"label": "l", "value": 1, "href": {"kind": "link", "url": "//evil.org"}}]}
    assert invalid(env(stat)).startswith("blocks[0].items[0].href.url : ")
    entry = {"type": "timeline", "items": [{"at": 1, "title": "t", "href": {"kind": "link", "url": "/x"}}]}
    assert invalid(env(entry)).startswith("blocks[0].items[0].href.url : ")
    ok(env({"type": "timeline", "items": [{"at": 1, "title": "t",
                                           "href": {"kind": "link", "url": "https://example.org"}}]}))


def test_view_links_resolved_by_policy():
    link = {"kind": "link", "text": "voir", "view": "detail", "params": {"id": "3", "n": 4}}
    out = ok(env({"type": "fields", "items": [{"label": "l", "value": link}]}), links=Known("detail"))
    assert out[0].pairs[0][1] == Ref("view", "forge/meteo/detail", "voir", (("id", "3"), ("n", "4")))


def test_unknown_view_refused():
    link = {"kind": "link", "text": "voir", "view": "ailleurs"}
    payload = env({"type": "fields", "items": [{"label": "l", "value": link}]})
    assert invalid(payload, links=Known("detail")) == "blocks[0].items[0].value.view : vue inconnue « ailleurs »"
    # sans politique de liens, aucun lien de vue n'est permis
    assert invalid(payload).startswith("blocks[0].items[0].value.view : ")


@pytest.mark.parametrize("link", [
    {"kind": "link", "text": "t"},                                                 # ni vue, ni adresse
    {"kind": "link", "text": "t", "view": "detail", "url": "https://example.org"},  # les deux
    {"kind": "link", "text": "t", "url": "https://example.org", "params": {"a": "1"}},
    {"kind": "link", "text": "t", "view": "../detail"},
    {"kind": "link", "text": "t", "view": "detail", "params": {"a b": "1"}},
    {"kind": "link", "text": "t", "view": "detail", "params": {"a": [1]}},
    {"kind": "link", "text": "t", "view": "detail", "params": {"a": True}},
    {"kind": "link", "view": "detail"},                                             # texte requis en cellule
])
def test_malformed_links_refused(link):
    invalid(env({"type": "fields", "items": [{"label": "l", "value": link}]}), links=Echo())


def test_policy_returning_garbage_is_refused():
    class Garbage:
        def view(self, key, params):
            return "/admin"

    link = {"kind": "link", "text": "t", "view": "detail"}
    assert "vue inconnue" in invalid(env({"type": "fields", "items": [{"label": "l", "value": link}]}),
                                     links=Garbage())


def test_policy_receives_validated_strings():
    echo = Echo()
    link = {"kind": "link", "text": "t", "view": "a/b", "params": {"id": 12}}
    ok(env({"type": "fields", "items": [{"label": "l", "value": link}]}), links=echo)
    assert echo.calls == [("a/b", {"id": "12"})]


# ── Violations de forme ───────────────────────────────────────────────────


def test_unknown_keys_refused():
    assert invalid({"version": 2, "blocks": [], "x": 1}) == "enveloppe : champ inconnu « x »"
    assert invalid(env({"type": "note", "text": "x", "color": "red"})) == "blocks[0] : champ inconnu « color »"
    assert invalid(env({"type": "note", "text": "x", "open": True})) == "blocks[0] : champ inconnu « open »"
    cell = {"kind": "badge", "text": "x", "href": "https://example.org"}
    assert invalid(env({"type": "fields", "items": [{"label": "l", "value": cell}]})) == \
        "blocks[0].items[0].value : champ inconnu « href »"
    assert invalid(env({"type": "grid", "items": [], "title": "t"})) == "blocks[0] : champ inconnu « title »"


def test_missing_required_keys_refused():
    assert invalid({"version": 2}) == "enveloppe : champ requis « blocks » manquant"
    assert invalid(env({"type": "note"})) == "blocks[0] : champ requis « text » manquant"
    assert invalid(env({"text": "x"})) == "blocks[0] : champ requis « type » manquant"
    assert invalid(env({"type": "section", "items": []})) == "blocks[0] : champ requis « title » manquant"
    cell = {"kind": "meter"}
    assert invalid(env({"type": "fields", "items": [{"label": "l", "value": cell}]})) == \
        "blocks[0].items[0].value : champ requis « ratio » manquant"


def test_wrong_types_refused():
    assert invalid("x") == "enveloppe : un objet est attendu, pas un texte"
    assert invalid({"version": 2, "blocks": {}}) == "blocks : une liste de blocs est attendue, pas un objet"
    assert invalid(env({"type": "note", "text": 3})) == "blocks[0].text : un texte est attendu, pas un entier"
    assert invalid(env({"type": "section", "title": "t", "items": "x"})) == \
        "blocks[0].items : une liste de blocs est attendue, pas un texte"
    assert invalid(env({"type": "fields", "items": [{"label": "l", "value": [1]}]})) == \
        "blocks[0].items[0].value : une cellule est un scalaire ou un objet, pas une liste"


def test_bool_is_not_an_int():
    assert invalid({"version": True, "blocks": []}) == "version : la version 2 est attendue"
    assert invalid({"version": 2.0, "blocks": []}) == "version : la version 2 est attendue"
    assert invalid(env({"type": "grid", "items": [], "columns": True})) == \
        "blocks[0].columns : un entier est attendu, pas un booléen"
    assert invalid(env({"type": "timeline", "items": [{"at": False, "title": "t"}]})) == \
        "blocks[0].items[0].at : un entier est attendu, pas un booléen"
    meter = {"kind": "meter", "ratio": True}
    assert invalid(env({"type": "fields", "items": [{"label": "l", "value": meter}]})) == \
        "blocks[0].items[0].value.ratio : un nombre est attendu, pas un booléen"


def test_unknown_block_and_cell_types_refused():
    assert invalid(env({"type": "html", "text": "<b>"})) == "blocks[0].type : type de bloc inconnu « html »"
    table = {"type": "table", "columns": ["a", "b"], "rows": [[1, 2], [3, {"kind": "emoji"}]]}
    assert invalid(env(table)) == "blocks[0].rows[1][1] : type de cellule inconnu « emoji »"


def test_tones():
    assert invalid(env({"type": "note", "text": "x", "tone": "rouge"})) == "blocks[0].tone : ton inconnu « rouge »"
    assert ok(env({"type": "note", "text": "x", "tone": "ko"}))[0].tone == "danger"
    assert ok(env({"type": "note", "text": "x", "tone": "mut"}))[0].tone == "muted"
    assert ok(env({"type": "note", "text": "x", "tone": ""}))[0].tone == ""
    badge = {"kind": "badge", "text": "x", "tone": "fuchsia"}
    assert invalid(env({"type": "fields", "items": [{"label": "l", "value": badge}]})) == \
        "blocks[0].items[0].value.tone : ton inconnu « fuchsia »"


def test_emotions():
    def payload(key):
        return env({"type": "fields", "items": [{"label": "l", "value": {"kind": "emotion", "key": key}}]})

    canon = frozenset({"happy", "sad"})
    assert invalid(payload("joy"), emotions=canon) == "blocks[0].items[0].value.key : émotion inconnue « joy »"
    assert ok(payload("happy"), emotions=canon)[0].pairs[0][1] == Swatch("happy", "emotion", "happy")
    # sans ensemble injecté : tout mot ascii en minuscules
    assert ok(payload("joy"))[0].pairs[0][1].key == "joy"
    assert "émotion" in invalid(payload("Joie!"))


def test_table_consistency():
    base = {"type": "table", "columns": ["a", {"key": "b", "label": "B"}]}
    assert invalid(env({**base, "rows": [[1]]})) == "blocks[0].rows[0] : 1 cellules pour 2 colonnes"
    assert invalid(env({**base, "rows": [{"cells": {"a": 1, "b": 2, "z": 3}}]})) == \
        "blocks[0].rows[0].cells : colonne inconnue « z »"
    assert invalid(env({**base, "rows": [{"cells": {"a": 1}}]})) == \
        "blocks[0].rows[0].cells : cellule manquante pour la colonne « b »"
    assert invalid(env({"type": "table", "columns": ["a", {"key": "a", "label": "A"}], "rows": []})) == \
        "blocks[0].columns[1] : clé de colonne en double « a »"
    assert "clé de colonne vide" in invalid(env({"type": "table", "columns": [""], "rows": []}))
    assert "alignement inconnu" in invalid(env({"type": "table", "columns": [{"key": "a", "label": "A",
                                                                              "align": "center"}], "rows": []}))


def test_pagination():
    def table(rows, **pagination):
        return env({"type": "table", "columns": ["a"], "rows": [[i] for i in range(rows)], "pagination": pagination})

    assert ok(table(6, page=2, total=12, per_page=6))[0].pager == Pager("page", 2, 6, 12)
    assert ok(table(2, page=3, total=12, per_page=5))[0].pager == Pager("page", 3, 5, 12)
    assert ok(table(0, page=1, total=0, per_page=5))[0].pager.total == 0
    assert invalid(table(1, page=4, total=12, per_page=5)) == \
        "blocks[0].pagination.page : page 4 au-delà de la dernière (3)"
    assert "au plus 5" in invalid(table(6, page=1, total=12, per_page=5))
    assert "au plus 2" in invalid(table(3, page=3, total=12, per_page=5))
    assert invalid(table(0, page=1, total=0, per_page=0)).startswith("blocks[0].pagination.per_page : ")
    assert invalid(table(0, page=1, total=0, per_page=201)).startswith("blocks[0].pagination.per_page : ")
    assert "booléen" in invalid(table(0, page=True, total=0, per_page=5))
    assert "champ requis « total »" in invalid(table(0, page=1, per_page=5))


def test_chart_rules():
    def chart(**kw):
        return env({"type": "chart", "series": [{"label": "s", "points": [[0, 1.0]]}], **kw})

    ok(chart(kind="spark", unit="$", y=[0, 1], zero=0, since=0, until=5))
    assert "genre de courbe inconnu" in invalid(chart(kind="pie"))
    assert "unité inconnue « km »" in invalid(chart(unit="km"))
    assert invalid(chart(y=[1, 1])) == "blocks[0].y : le bas doit être inférieur au haut"
    assert invalid(chart(y=[0])) == "blocks[0].y : une paire [bas, haut] est attendue"
    assert "postérieur" in invalid(chart(since=9, until=5))
    bad_points = [[[-1, 0.5]], [[0, float("nan")]], [[0, float("inf")]], [[0]], [[0.5, 1.0]], [[True, 1.0]]]
    for points in bad_points:
        payload = env({"type": "chart", "series": [{"label": "s", "points": points}]})
        assert invalid(payload).startswith("blocks[0].series[0].points[0]"), points


def test_numbers_and_strings_are_sanitised():
    def field(value):
        return env({"type": "fields", "items": [{"label": "l", "value": value}]})

    assert invalid(field(float("nan"))) == "blocks[0].items[0].value : nombre non fini"
    assert invalid(field(float("-inf"))) == "blocks[0].items[0].value : nombre non fini"
    assert "hors de" in invalid(field(10**400))  # jamais de conversion en texte d'un entier démesuré
    assert ok(field(2**63 - 1))[0].pairs[0][1] == 2**63 - 1
    assert "hors de" in invalid(field(2**63))
    assert ok(field({"kind": "meter", "ratio": 1.7}))[0].pairs[0][1].ratio == 1.0
    assert ok(field({"kind": "meter", "ratio": -3}))[0].pairs[0][1].ratio == 0.0
    assert invalid(field({"kind": "meter", "ratio": float("nan")})).endswith("nombre non fini")
    assert "hors bornes" in invalid(field({"kind": "meter", "ratio": 10**400}))
    for bad in ("a\x00b", "\ud800", "a\x1bb", "\x85"):
        assert "caractère de contrôle" in invalid(field(bad)), repr(bad)
    assert ok(field("ligne\nsuivante\ttab\r"))[0].pairs[0][1] == "ligne\nsuivante\ttab\r"


def test_messages_never_echo_huge_or_invisible_input():
    text = invalid(env({"type": "note", "text": "x", ("k" * 5_000 + "‮"): 1}))
    assert len(text) < 120 and "‮" not in text and "…" in text


def test_form():
    ok_form = {"type": "form", "action": "relancer", "initial": {"id": 3, "force": True, "vide": None, "r": 0.5}}
    assert ok(env(ok_form))[0] == ActionSlot("relancer", initial=(("id", "3"), ("force", "1"), ("vide", ""),
                                                                   ("r", "0.5")))
    assert "clé d'action invalide" in invalid(env({"type": "form", "action": "Envoyer!"}))
    assert "clé d'action invalide" in invalid(env({"type": "form", "action": "forge.envoyer"}))
    assert invalid(env({"type": "form", "action": "a", "initial": {"x": [1]}})) == \
        "blocks[0].initial.x : une valeur scalaire est attendue, pas une liste"
    assert "nom invalide" in invalid(env({"type": "form", "action": "a", "initial": {"1x": "v"}}))


def test_stat_trend_must_be_a_chart():
    stat = {"type": "stats", "items": [{"label": "l", "value": 1, "trend": note()}]}
    assert invalid(env(stat)) == "blocks[0].items[0].trend : une courbe (« chart ») est attendue"


# ── Entrées pathologiques ─────────────────────────────────────────────────


def test_exotic_objects_never_run_their_code():
    class Evil(str):
        def __len__(self):
            raise RuntimeError("appelé")

        def __eq__(self, other):
            raise RuntimeError("appelé")

        __hash__ = str.__hash__

    class Meta(type):
        def __eq__(cls, other):
            raise RuntimeError("appelé")

        __hash__ = type.__hash__

    class Odd(metaclass=Meta):
        pass

    class Key:
        def __hash__(self):
            return hash("type")

        def __eq__(self, other):
            raise RuntimeError("appelé")

    class Blocks(list):
        def __len__(self):
            raise RuntimeError("appelé")

    assert "un texte est attendu" in invalid(env({"type": "note", "text": Evil("x")}))
    assert "autre type" in invalid(env({"type": "fields", "items": [{"label": "l", "value": Odd()}]}))
    assert "clé non textuelle" in invalid(env({Key(): "note", "text": "x"}))
    assert "liste de blocs" in invalid({"version": 2, "blocks": Blocks()})
    assert "un texte est attendu" in invalid(env({"type": Evil("note"), "text": "x"}))


def test_self_reference_and_deep_nesting():
    loop: dict = {"version": 2, "blocks": []}
    loop["blocks"].append(loop)
    assert is_invalid(decode(loop))
    assert invalid(_deep_list(100_000)) == "enveloppe : un objet est attendu, pas une liste"
    assert "imbrication" in invalid(env(nested(50_000)))


def test_pathological_errors_end_as_the_note():
    """Une ``TypeError``, une ``RecursionError`` ou une ``OverflowError`` levée
    en cours de route (ici par la politique de liens) finit en note, au chemin
    du dernier bloc abordé ; une autre exception n'est pas avalée."""
    link = {"kind": "link", "text": "t", "view": "detail"}
    payload = env(note(), {"type": "fields", "items": [{"label": "l", "value": link}]})
    for exc in (TypeError, RecursionError, OverflowError):
        class Broken:
            def view(self, key, params, exc=exc):
                raise exc("boum")

        assert invalid(payload, links=Broken()) == f"blocks[1] : contenu illisible ({exc.__name__})"

    class Bug:
        def view(self, key, params):
            raise KeyError("un vrai bogue de l'hôte")

    with pytest.raises(KeyError):
        decode(payload, links=Bug())


# ── Encodage ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("block", [
    Fields((("l", Ref("event", "12", "#12")),)),
    Fields((("l", Ref.subject("person", "p1", "Alice")),)),
    Fields((("l", Swatch("x", "autre", "k")),)),
    Table(("a",), (), pager=Pager(older=(("avant", "12"),))),
    Table(("a",), (), pager=Pager(param="p", total=3)),
    Fields((("a", 1),), hints=(("b", "aide orpheline"),)),
    Grid((object(),)),
])
def test_encode_refuses_what_the_envelope_cannot_say(block):
    with pytest.raises(ValueError):
        encode([block])


def test_encode_omits_defaults():
    assert encode([Note("x")]) == {"version": 2, "blocks": [{"type": "note", "text": "x"}]}
    assert encode([Table(("a", Column("B")), (("1", 2),))])["blocks"][0] == {
        "type": "table", "columns": ["a", {"key": "c1", "label": "B"}], "rows": [["1", 2]]}


def test_encode_column_keys_avoid_bare_labels():
    table = Table(("c1", Column("B"), "c1_"), (("x", "y", "z"),))
    payload = encode([table])
    assert payload["blocks"][0]["columns"][1]["key"] == "c1__"
    assert decode(payload) == [table]


# ── Schéma ────────────────────────────────────────────────────────────────


def test_schema_is_valid_draft_2020_12():
    js = pytest.importorskip("jsonschema")
    s = schema()
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    js.Draft202012Validator.check_schema(s)


def test_schema_objects_are_closed():
    """Tout objet décrit est fermé ; seuls les dictionnaires ouverts par nature
    (paramètres, valeurs initiales, cellules par colonne) contraignent leurs
    noms à la place."""
    objects = [v for v in _walk(schema()) if isinstance(v, dict) and v.get("type") == "object"]
    assert len(objects) > 20
    for obj in objects:
        if "properties" in obj:
            assert obj["additionalProperties"] is False, obj
        else:
            assert "propertyNames" in obj, obj


def test_schema_names_every_block_type():
    defs = schema()["$defs"]
    consts = {v["properties"]["type"]["const"] for k, v in defs.items() if k.startswith("block_")}
    assert consts == ALL_TYPES


def test_schema_follows_limits():
    s = schema(limits=Limits(blocks=7, chars=9))
    assert s["properties"]["blocks"]["maxItems"] == 7
    assert s["$defs"]["block_note"]["properties"]["text"]["maxLength"] == 9


def test_schema_rejects_what_decode_rejects_structurally():
    pytest.importorskip("jsonschema")
    for bad in (
        {"version": 2, "blocks": [], "x": 1},
        env({"type": "note", "text": "x", "color": "red"}),
        env({"type": "html", "text": "x"}),
        env({"type": "note", "text": "x", "tone": "rouge"}),
        _url_field("javascript:alert(1)"),
        _url_field("//evil.org"),
        env({"type": "fields", "items": [{"label": "l", "value": {"kind": "emoji"}}]}),
    ):
        with pytest.raises(jsonschema.ValidationError):
            validate(bad)
        assert is_invalid(decode(bad, links=Echo()))


def test_chart_bounds_must_be_finite():
    assert invalid(env({"type": "chart", "series": [], "zero": math.inf})) == "blocks[0].zero : nombre non fini"
    assert invalid(env({"type": "chart", "series": [], "y": [0, math.nan]})) == "blocks[0].y[1] : nombre non fini"
