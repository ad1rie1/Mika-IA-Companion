"""« Pourquoi a-t-elle parlé ? » retrouve **le** choix de l'arbitre qui a lancé un épisode (CON-17), et le dit en mots.

Plusieurs choix peuvent se suivre de près (envers Bob, puis envers Alice) : le
plus récent avant le départ n'est pas forcément le sien. Le numéro exact, quand
l'épisode le porte (``EpisodeStarted.selected``), fait foi ; sinon, le premier
choix après la tête notée par le déclencheur (``selected:<tête>``) qui a tiré
cette sorte envers cette cible.
"""

from __future__ import annotations

from types import SimpleNamespace

from mika.inspector.pages.why import cause_blocks, selection_of
from mika.kernel.builtin import SELECTED
from mika.kernel.inspect import Note, Table


def _row(kind: str, target: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, target=target, score=score, hazard=0.001, parts=(), vetoes=(), shift=0.0)


def _selected(seq: int, kind: str, target: str) -> SimpleNamespace:
    row = _row(kind, target, 0.1 * seq)
    data = SimpleNamespace(fired=(f"{kind}:{target}",), rows=(row,), draw=0.3, candidates=1, bound=0.0, total=0.0)
    return SimpleNamespace(seq=seq, at=seq, type=SimpleNamespace(name=SELECTED.name), data=data)


class _Store:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self.events = {e.seq: e for e in events}

    def get_events(self, seqs):
        return [self.events[s] for s in seqs if s in self.events]

    def query_mind(self, sql, args):
        type_name, after, before, limit = args
        return [(s,) for s in sorted(self.events) if self.events[s].type.name == type_name and after < s < before][:limit]


def _ui(events: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(kernel=SimpleNamespace(mind=SimpleNamespace(store=_Store(events))), decode=lambda e: e)


def _started(seq: int, trigger: str, target: str | None, **more) -> SimpleNamespace:
    return SimpleNamespace(seq=seq, data=SimpleNamespace(kind="INITIATIVE", target=target, trigger=trigger, **more))


def test_the_episode_finds_its_own_choice_not_the_latest_one():
    # tête 10 ; choix 11 envers Bob, 12 envers Alice (le sien), 13 envers Chloé, puis le départ d'Alice (14)
    events = [_selected(11, "INITIATIVE", "bob"), _selected(12, "INITIATIVE", "alice"),
              _selected(13, "INITIATIVE", "chloe")]
    event, row, exact = selection_of(_ui(events), _started(14, "selected:10", "alice"))
    assert event.seq == 12 and row.target == "alice" and not exact
    # contre-exemple : l'ancienne approximation (le dernier choix avant le départ) aurait pris celui de Chloé
    assert max(events, key=lambda e: e.seq).data.fired != ("INITIATIVE:alice",)


def test_the_exact_number_wins_when_the_episode_carries_it():
    events = [_selected(11, "INITIATIVE", "alice"), _selected(12, "INITIATIVE", "alice")]
    event, row, exact = selection_of(_ui(events), _started(14, "selected:10", "alice", selected=12))
    assert event.seq == 12 and exact
    # un numéro qui ne désigne pas un choix ne fait pas foi : on retombe sur le déclencheur
    event, _row_, exact = selection_of(_ui(events), _started(14, "selected:10", "alice", selected=999))
    assert event.seq == 11 and not exact


def test_a_reply_has_no_arbiter_choice():
    events = [_selected(11, "INITIATIVE", "alice")]
    assert selection_of(_ui(events), _started(14, "perception:9", "alice")) == (None, None, False)


def test_a_choice_without_a_target_matches_nobody_in_particular():
    events = [_selected(11, "INITIATIVE", "user_1"), _selected(12, "INITIATIVE", "any")]
    event, row, _exact = selection_of(_ui(events), _started(14, "selected:10", None))
    assert event.seq == 12 and row.target == "any"


def test_a_murmur_before_speaking_follows_the_choice_whatever_its_target():
    # le murmure (prélude) n'a pas de cible : il suit la ligne tirée juste avant, envers qui que ce soit
    events = [_selected(11, "INITIATIVE", "alice")]
    murmur = SimpleNamespace(seq=14, data=SimpleNamespace(kind="MURMUR", target=None, trigger="prélude:selected:10"))
    event, row, exact = selection_of(_ui(events), murmur)
    assert event.seq == 11 and row.target == "alice" and not exact
    # contre-exemple : sans prélude, une initiative sans cible ne s'attribue pas le choix envers Alice
    assert selection_of(_ui(events), _started(14, "selected:10", None)) == (None, None, False)


class _Names:
    """Des noms d'opérateur sans noyau : assez pour rendre la cause d'une parole."""

    def who(self, target):
        return {"alice": "Alice"}.get(target or "", target or "personne en particulier")

    def arbiter_row(self, kind, target):
        return f"{kind.lower()} envers {self.who(target)}"

    def reason(self, owner, code):
        return {"need_social": "Envie de compagnie"}.get(code, code)

    def veto(self, owner, code):
        return code

    def faculty(self, owner):
        return owner


def test_the_cause_of_an_initiative_is_the_arbiter_line_in_words():
    row = SimpleNamespace(kind="INITIATIVE", target="alice", score=1.2, hazard=0.002, vetoes=(), shift=0.0,
                          shifts=(), aging=0.0, threshold=0.0, parts=(("needs", "need_social", 1.2),))
    other = SimpleNamespace(kind="INITIATIVE", target="bob", score=-3.0, hazard=0.0001, vetoes=(), shift=0.0,
                            shifts=(), aging=0.0, threshold=0.0, parts=())
    data = SimpleNamespace(fired=("INITIATIVE:alice",), rows=(row, other), draw=0.42, candidates=2, bound=0.0,
                           total=0.0)
    chosen = SimpleNamespace(seq=11, at=11, type=SimpleNamespace(name=SELECTED.name), data=data)
    ui = _ui([chosen])
    ui.names = _Names()
    spoke = cause_blocks(ui, _started(14, "selected:10", "alice", reply_to=None, reason="need_social"))
    lead = next(b for b in spoke if isinstance(b, Note))
    assert lead.text.startswith("Elle a pris la parole d'elle-même") and "envers Alice" in lead.text
    assert "0,42" in lead.text and "Parmi 2 ligne(s)" in lead.text  # le tirage et les lignes, à la française
    steps = next(b for b in spoke if isinstance(b, Table))
    assert any("Envie de compagnie" in str(c) for r in steps.rows for c in r.cells)  # la preuve en mots
    murmur = SimpleNamespace(seq=13, data=SimpleNamespace(kind="MURMUR", target=None, trigger="prélude:selected:10",
                                                         reply_to=None, reason=""))
    before = next(b for b in cause_blocks(ui, murmur) if isinstance(b, Note))
    assert before.text.startswith("Un murmure juste avant d'agir")
    # contre-exemple : une réponse ne passe pas par l'arbitre (elle n'est pas « prise d'elle-même »)
    asked = _started(14, "perception:9", "alice", reply_to=9, reason="")
    assert not any(isinstance(b, Note) and "d'elle-même" in b.text for b in cause_blocks(ui, asked))
