"""Propriétés du noyau (audit du 2026-10-26) : ce que la doc promet comme invariant se vérifie sur des entrées tirées.

- ``FrozenDict`` : même ordre d'itération quel que soit l'ordre d'insertion (la condition du déterminisme sous
  ``PYTHONHASHSEED``), ``set``/``delete`` ne touchent pas l'original, ``items`` triés ;
- ``canonical_json`` : indépendant de l'ordre des clés, stable sous un aller-retour ;
- ``vocab.access.tighten`` : idempotente, commutative, associative, et jamais plus permissive qu'une des deux ;
- ``store_sql._marks`` : un ``?`` entre apostrophes n'est jamais remplacé, les autres le sont tous, ``%`` doublé.
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from mika.adapters.store_sql.store import _marks
from mika.kernel.codec import canonical_json
from mika.kernel.state import FrozenDict
from mika.vocab.access import POLICY_RANK, tighten

keys = st.text(min_size=0, max_size=12)
values = st.one_of(st.integers(), st.text(max_size=8), st.booleans(), st.none())


@settings(max_examples=200, deadline=None)
@given(st.dictionaries(keys, values, max_size=40), st.integers())
def test_frozendict_iterates_the_same_whatever_the_insertion_order(data, seed):
    items = list(data.items())
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    a, b = FrozenDict(items), FrozenDict(shuffled)
    assert a == b
    assert list(a) == list(b) == sorted(data)
    assert a.items() == b.items() == [(k, data[k]) for k in sorted(data)]


@settings(max_examples=200, deadline=None)
@given(st.dictionaries(keys, values, max_size=20), keys, values)
def test_frozendict_updates_leave_the_original_alone(data, key, value):
    original = FrozenDict(data)
    before = original.to_dict()
    changed = original.set(key, value)
    gone = changed.delete(key)
    assert original.to_dict() == before
    assert changed[key] == value and key not in gone
    assert gone.to_dict() == {k: v for k, v in changed.to_dict().items() if k != key}


@settings(max_examples=200, deadline=None)
@given(st.dictionaries(keys, st.one_of(values, st.lists(st.integers(), max_size=5)), max_size=20), st.integers())
def test_canonical_json_ignores_key_order_and_round_trips(data, seed):
    shuffled = list(data.items())
    random.Random(seed).shuffle(shuffled)
    text = canonical_json(data)
    assert text == canonical_json(dict(shuffled))
    assert canonical_json(json.loads(text)) == text


levels = st.sampled_from(sorted(POLICY_RANK))


@settings(max_examples=300, deadline=None)
@given(levels, levels, levels)
def test_tighten_is_a_meet(a, b, c):
    assert tighten(a, a, POLICY_RANK) == a
    assert tighten(a, b, POLICY_RANK) == tighten(b, a, POLICY_RANK)
    assert tighten(tighten(a, b, POLICY_RANK), c, POLICY_RANK) == tighten(a, tighten(b, c, POLICY_RANK), POLICY_RANK)
    got = tighten(a, b, POLICY_RANK)
    assert POLICY_RANK[got] <= min(POLICY_RANK[a], POLICY_RANK[b])
    assert got in (a, b)


_FORMAT = SimpleNamespace(paramstyle="format")
_QMARK = SimpleNamespace(paramstyle="qmark")
#: des morceaux de SQL : du texte sans apostrophe ni ``?`` ni ``%``, des ``?``, des ``%``, des chaînes entre apostrophes
_pieces = st.one_of(
    st.text(alphabet=st.characters(blacklist_characters="'?%"), max_size=6),
    st.just("?"),
    st.just("%"),
    st.text(alphabet=st.characters(blacklist_characters="'"), max_size=6).map(lambda s: f"'{s}'"),
)


@settings(max_examples=300, deadline=None)
@given(st.lists(_pieces, max_size=12))
def test_marks_translates_every_placeholder_outside_quotes_and_none_inside(pieces):
    sql = "".join(pieces)
    assert _marks(sql, _QMARK) == sql
    out = _marks(sql, _FORMAT)
    # ce qu'on attend : hors apostrophes, chaque ``?`` devient ``%s`` et chaque ``%`` est doublé ; dedans, rien
    expected, quoted = [], False
    for ch in sql:
        if ch == "'":
            quoted = not quoted
            expected.append(ch)
        elif ch == "%":
            expected.append("%%")
        elif ch == "?" and not quoted:
            expected.append("%s")
        else:
            expected.append(ch)
    assert out == "".join(expected)
    outside = [c for i, c in enumerate(out) if c == "?" and out[:i].count("'") % 2 == 0]
    assert not outside, "un ? hors apostrophes a survécu"
