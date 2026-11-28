"""Seule et désœuvrée, un souvenir lui revient (lot H du chantier « émotions, conscience, mémoire », ADR 0098).

Avant : aucun souvenir ne lui revenait de lui-même (ses rêves seuls puisaient dans sa mémoire, la nuit). L'ennui et
la solitude se ressentaient, et c'était tout. Désormais, borné et sans appel au modèle, *un souvenir qui revient* : un
peu ancien, à sa date anniversaire d'abord, sinon l'un de ceux qui comptent — une pensée à elle (``reminiscence``),
qui se ressent et peut se raconter à qui il concerne, jamais une raison d'écrire à elle seule ; sa filiation le suit.

S'occuper d'elle-même dans sa chambre (dessiner, feuilleter un livre) est parti avec le monde (ADR 0319) : il reste
que le vide de la solitude se compte depuis que personne ne lui a parlé.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

from sqlalchemy import insert

from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.faculties.attention.faculty import AttentionParams, AttentionState
from mika.faculties.attention.prompt import FELT_ONLY
from mika.faculties.attention.watch import reminisce_due, reminiscence
from mika.faculties.needs import WITH_THEM
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.vocab import causes
from mika.vocab.affect import Emotion
from tests.fixtures.mika import PARIS, at_paris
from tests.fixtures.sqldb import SqlDB

NOW = at_paris(2026, 10, 12, 15, 0)
P = AttentionParams()


def row(item: int, text: str, born_at: int, *, importance: float = 0.5, emotion: str = "happy",
        about: tuple[str, ...] = (), secret: bool = False) -> tuple:
    values = {"id": item, "kind": memory_c.EPISODE_MEMORY, "text": text, "about": json.dumps(list(about)),
              "sensitivity": 2 if about else 1, "importance": importance, "confidence": None, "origin": "",
              "source": None, "emotion": emotion, "born_at": born_at, "touched_at": born_at, "status": "active",
              "recipient": None, "due": None, "sources": "[]", "told_by": json.dumps(list(about)),
              "heard_by": "[]", "secret": int(secret), "about_self": 0, "between_us": 0, "knowledge_kind": "claim",
              "holder": None, "constraints": "[]", "internal_only": 0}
    return tuple(values[c] for c in memory_c.KNOWN_COLUMNS)


class Store(SqlDB):
    """Ce qu'elle sait, dans une table qui porte le nom et les colonnes de la vue (``memory_c.KNOWLEDGE``) : la
    requête de ``reminiscence`` s'y lit telle quelle."""

    def __init__(self, rows):
        super().__init__()
        self.create(memory_c.KNOWLEDGE)
        if rows:
            self.execute(insert(memory_c.KNOWLEDGE), [dict(zip(memory_c.KNOWN_COLUMNS, r, strict=True)) for r in rows])


def frame(*, idle_since=NOW - 2 * HOUR, now=NOW):
    from datetime import datetime

    facts = {"needs.needs": NS(idle_since=idle_since)}
    return NS(now=now, get=lambda key: facts[key.name],
              local=lambda t=None: datetime.fromtimestamp((now if t is None else t) / 1e6, PARIS))


def test_a_year_ago_today_comes_back_first():
    rows = [row(1, "J'ai dessiné un chat pour Alice.", NOW - 30 * DAY, importance=0.9),
            row(2, "Premier concert de jazz avec Alice, une soirée magique.", NOW - 365 * DAY, importance=0.4,
                about=("alice",))]
    d = reminiscence(AttentionState(), frame(), Store(rows), P)
    assert d.data.origin == attention_c.REMINISCENCE and d.data.source == 2
    assert d.data.text.text.startswith("Il y a un an jour pour jour")
    assert d.data.emotion == "happy"  # son émotion d'alors, jamais devinée
    assert d.data.lineage is not None and d.data.about == ("alice",)  # sa filiation la suit


def test_otherwise_one_that_counts_and_never_one_just_back_nor_too_fresh():
    rows = [row(1, "Une longue discussion sur la cuisine.", NOW - 40 * DAY, importance=0.9),
            row(3, "Hier, une recette ratée.", NOW - DAY, importance=1.0)]  # trop frais : pas un souvenir qui remonte
    d = reminiscence(AttentionState(), frame(), Store(rows), P)
    assert d.data.source == 1 and d.data.text.text.startswith("Un souvenir me revient")
    back = AttentionState(reminisced=((NOW - 2 * DAY, 1),))
    assert reminiscence(back, frame(), Store(rows), P) is None  # il vient de revenir
    no_feeling = reminiscence(AttentionState(), frame(), Store([row(4, "Une balade.", NOW - 9 * DAY, emotion="")]),
                              P)
    assert no_feeling.data.emotion == Emotion.THINKING.value


def test_memories_come_back_rarely_and_only_when_nothing_happens():
    assert reminisce_due(AttentionState(), frame(idle_since=NOW - 10 * MINUTE), P) > NOW  # on lui parle
    assert reminisce_due(AttentionState(), frame(), P) <= NOW
    two = AttentionState(reminisced=((NOW - 5 * HOUR, 1), (NOW - 9 * HOUR, 2)))
    assert reminisce_due(two, frame(), P) > NOW  # deux aujourd'hui
    one = AttentionState(reminisced=((NOW - HOUR, 1),))
    assert reminisce_due(one, frame(), P) == NOW - HOUR + P.reminisce_spacing_us
    assert reminisce_due(AttentionState(), frame(), P, tried_at=NOW - MINUTE) > NOW  # rien n'est venu : on attend
    assert reminisce_due(AttentionState(), frame(), AttentionParams(reminisce_per_day=0)) is None


def test_a_memory_is_felt_and_shared_with_whom_it_concerns_never_a_reason_to_write():
    assert attention_c.REMINISCENCE in FELT_ONLY and attention_c.REMINISCENCE in WITH_THEM
    from mika.faculties.affect.prose import cause_line

    assert cause_line(attention_c.REMINISCENCE)  # « Ça vient d'un souvenir qui t'est revenu. »
    assert causes.said_as(attention_c.REMINISCENCE) == attention_c.REMINISCENCE


# ── Le vide ───────────────────────────────────────────────────────────────


def test_loneliness_counts_from_the_last_time_someone_spoke_to_her():
    from mika.faculties.needs import NeedsState, empty_since

    s = NeedsState(idle_since=NOW - 10 * MINUTE, lonely_since=NOW - 5 * HOUR)
    assert empty_since(s, False) == NOW - 10 * MINUTE  # l'ennui : depuis que rien ne s'est passé
    assert empty_since(s, True) == NOW - 5 * HOUR  # la solitude : personne depuis cinq heures
    assert empty_since(NeedsState(idle_since=NOW - HOUR), True) == NOW - HOUR  # sans repère, le dernier événement
