"""Seule et désœuvrée, elle a une vie (lot H du chantier « émotions, conscience, mémoire », ADR 0098).

Avant : éveillée et seule, elle ne prenait jamais d'elle-même un livre, ne dessinait pas, ne regardait pas dehors
(ses mains ne servaient qu'en conversation ou à son bureau quand elle travaillait) ; aucun souvenir ne lui revenait
de lui-même (ses rêves seuls puisaient dans sa mémoire, la nuit). L'ennui et la solitude se ressentaient, et c'était
tout. Deux choses, bornées et sans appel au modèle :

- *s'occuper* : le vide ressenti (``needs.felt``) la fait s'occuper de ce qui nourrit ce qui lui manque le plus —
  quelques fois par jour, espacées, jamais deux fois de suite la même chose ;
- *un souvenir qui revient* : un peu ancien, à sa date anniversaire d'abord, puis ce que lui rappelle ce qu'elle a
  entre les mains, sinon l'un de ceux qui comptent — une pensée à elle (``reminiscence``), qui se ressent et peut se
  raconter à qui il concerne, jamais une raison d'écrire à elle seule ; sa filiation le suit.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import insert

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import memory as memory_c
from mika.contracts import world as w
from mika.faculties.attention.faculty import AttentionParams, AttentionState
from mika.faculties.attention.prompt import FELT_ONLY
from mika.faculties.attention.watch import reminisce_due, reminiscence
from mika.faculties.needs import WITH_THEM
from mika.faculties.world import WorldParams, _occupy_herself, genesis
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.vocab import causes
from mika.vocab.affect import Emotion
from tests.fixtures.mika import PARIS, at_paris
from tests.fixtures.sqldb import SqlDB

NOW = at_paris(2026, 10, 12, 15, 0)
P = AttentionParams()


def row(item: int, text: str, born_at: int, *, importance: float = 0.5, emotion: str = "happy",
        about: tuple[str, ...] = (), secret: bool = False) -> tuple:
    values = {"id": item, "kind": memory_c.SOUVENIR, "text": text, "about": json.dumps(list(about)),
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


def frame(*, doing=None, idle_since=NOW - 2 * HOUR, now=NOW):
    from datetime import datetime

    facts = {"world.doing": doing, "needs.needs": NS(idle_since=idle_since)}
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


def test_what_she_has_in_hand_reminds_her():
    rows = [row(1, "Une longue discussion sur la cuisine.", NOW - 40 * DAY, importance=0.9),
            row(2, "J'ai dessiné un chat pour Alice, elle a adoré.", NOW - 20 * DAY, importance=0.5)]
    doing = w.Doing(name="draw", label="dessiner", since=NOW - 10 * MINUTE)
    d = reminiscence(AttentionState(), frame(doing=doing), Store(rows), P)
    assert d.data.source == 2 and "dessiner" in d.data.text.text


def test_otherwise_one_that_counts_and_never_one_just_back_nor_too_fresh():
    rows = [row(1, "Une longue discussion sur la cuisine.", NOW - 40 * DAY, importance=0.9),
            row(3, "Hier, une recette ratée.", NOW - DAY, importance=1.0)]  # trop frais : pas un souvenir qui remonte
    d = reminiscence(AttentionState(), frame(), Store(rows), P)
    assert d.data.source == 1 and d.data.text.text.startswith("Un souvenir te revient")
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


# ── S'occuper ─────────────────────────────────────────────────────────────


def cx(*, curiosity=0.2, expression=0.2, asleep=False):
    facts = {"body.sleep": body_c.SleepPhase.DEEP_SLEEP if asleep else body_c.SleepPhase.AWAKE,
             "needs.needs": NS(curiosity=curiosity, expression=expression)}
    return NS(params=WorldParams(), facts=NS(get=lambda key: facts[key.name]))


def felt(at=NOW, seq=100):
    return NS(at=at, seq=seq, id=f"01FELT{seq}", data=NS(feeling="bored", intensity=0.4))


def activity(s):
    running = [i for i in s.intents.values() if i.actor == w.MIKA]
    return running[0].steps[-1] if running else None


def test_bored_she_occupies_herself_with_what_she_lacks():
    s = genesis()
    curious = _occupy_herself(s, felt(), cx(curiosity=0.9))
    expressive = _occupy_herself(s, felt(), cx(expression=0.9))
    assert curious.occupied == (NOW,) and expressive.occupied == (NOW,)
    assert activity(curious) is not None and activity(curious) != activity(expressive)
    actions = {getattr(activity(x), "action", None) for x in (curious, expressive)}
    assert "dessiner" in actions and actions & {"bouquiner", "regarder_dehors"}


@pytest.mark.parametrize("case", ["asleep", "spacing", "cap", "talked", "off"])
def test_a_tendency_with_bounds(case):
    s = genesis()
    if case == "asleep":
        assert _occupy_herself(s, felt(), cx(asleep=True)) is s
    elif case == "spacing":
        s2 = _occupy_herself(s, felt(), cx())
        # l'action finie, rien en cours : seul l'espacement la retient
        done = type(s2)(**{**{f: getattr(s2, f) for f in s2.__dataclass_fields__}, "intents": type(s.intents)()})
        assert _occupy_herself(done, felt(NOW + 30 * MINUTE, 101), cx()).occupied == s2.occupied
        assert len(_occupy_herself(done, felt(NOW + 3 * HOUR, 102), cx()).occupied) == 2
    elif case == "cap":
        full = type(s)(**{**{f: getattr(s, f) for f in s.__dataclass_fields__},
                          "occupied": (NOW - 10 * HOUR, NOW - 7 * HOUR, NOW - 4 * HOUR)})
        assert _occupy_herself(full, felt(), cx()) is full
    elif case == "talked":
        busy = type(s)(**{**{f: getattr(s, f) for f in s.__dataclass_fields__}, "talked_at": NOW - MINUTE})
        assert _occupy_herself(busy, felt(), cx()) is busy
    else:
        off = NS(params=WorldParams(occupy_per_day=0), facts=cx().facts)
        assert _occupy_herself(s, felt(), off) is s


# ── Ce que s'occuper fait au vide ─────────────────────────────────────────


def test_a_glance_outside_does_not_buy_two_hours_but_an_hour_drawing_does():
    """Deux heures de vide, puis deux minutes à regarder dehors : le vide reprend presque où il en était ; une heure à
    dessiner l'efface. Ce qui s'est passé entre-temps (un message) compte en entier."""
    from mika.faculties.needs import NeedsParams, Occupation, _void_after

    p = NeedsParams()
    start = NOW - 2 * HOUR
    glance = Occupation("look_outside", NOW, NOW + 2 * MINUTE, ("curiosity",), void_from=start, noted=NOW)
    assert _void_after(glance, NOW, NOW + 2 * MINUTE, p) < start + 10 * MINUTE
    drawing = Occupation("draw", NOW, None, ("expression",), void_from=start, noted=NOW)
    assert _void_after(drawing, NOW, NOW + p.occupied_full_us, p) == NOW + p.occupied_full_us
    assert _void_after(glance, NOW + MINUTE, NOW + 2 * MINUTE, p) == NOW + 2 * MINUTE  # un message pendant


def test_keeping_busy_holds_boredom_off_never_loneliness():
    from mika.faculties.needs import NeedsParams, NeedsState, Occupation, empty_since

    p = NeedsParams()
    reading = Occupation("draw", NOW - 10 * MINUTE, None, ("expression",), void_from=NOW - 3 * HOUR,
                         noted=NOW - 10 * MINUTE)
    s = NeedsState(idle_since=NOW - 10 * MINUTE, occupied=reading, lonely_since=NOW - 5 * HOUR)
    assert empty_since(s, False, p) > NOW  # l'ennui attend qu'elle ait fini
    assert empty_since(s, True, p) == NOW - 5 * HOUR  # personne depuis cinq heures : dessiner n'y change rien


def test_never_twice_in_a_row_the_same_thing():
    s = genesis()
    first = _occupy_herself(s, felt(), cx(curiosity=0.9))
    me = first.actors[w.MIKA]
    done = activity(first)
    # elle a fini (à l'heure dite) ce qu'elle avait pris ; deux heures plus tard, encore désœuvrée
    held = w.Activity(name={"bouquiner": "browse_books", "regarder_dehors": "look_outside"}[done.action],
                      object=done.object, since=NOW, until=NOW + 5 * MINUTE)
    later = type(first)(**{**{f: getattr(first, f) for f in first.__dataclass_fields__}, "intents": type(s.intents)(),
                           "actors": first.actors.set(w.MIKA, me.model_copy(update={"activity": held,
                                                                                     "moving": None}))})
    second = _occupy_herself(later, felt(NOW + 3 * HOUR, 101), cx(curiosity=0.9))
    assert activity(second) is not None and activity(second).action != done.action
