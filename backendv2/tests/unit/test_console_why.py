"""« Pourquoi a-t-elle parlé ? » retrouve **le** choix de l'arbitre qui a lancé un épisode (CON-17), et le dit en mots.

Plusieurs choix peuvent se suivre de près (envers Bob, puis envers Alice) : le
plus récent avant le départ n'est pas forcément le sien. Le numéro exact, quand
l'épisode le porte (``EpisodeStarted.selected``), fait foi ; sinon, le premier
choix après la tête notée par le déclencheur (``selected:<tête>``) qui a tiré
cette sorte envers cette cible.

Son humeur, telle que son prompt la lui disait (« Ton humeur générale est… »),
se lit comme une citation de son prompt, pas comme une phrase adressée à qui lit
la page ; ses nombres (lignes, outils, tours de conversation) sont accordés.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import insert

from mika.inspector.pages.decisions import ARBITER_COLUMNS
from mika.inspector.pages.why import (
    cause_blocks,
    inner_state,
    mood_blocks,
    prompt_measure,
    prompt_view,
    selection_of,
    tools_view,
)
from mika.inspector.ui import env
from mika.kernel.builtin import SELECTED
from mika.kernel.faculty import Zone
from mika.kernel.inspect import Disclosure, Fields, Note, Table, Text, num_fr
from mika.kernel.prompt import HEADER_FMT
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.journal import JournalEvent
from mika.runtime.traces import STABLE_KEY
from mika.vocab.episodes import Tag
from tests.fixtures.sqldb import SqlDB


def _row(kind: str, target: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, target=target, score=score, hazard=0.001, parts=(), vetoes=(), shift=0.0)


def _selected(seq: int, kind: str, target: str) -> SimpleNamespace:
    row = _row(kind, target, 0.1 * seq)
    data = SimpleNamespace(fired=(f"{kind}:{target}",), rows=(row,), draw=0.3, candidates=1, bound=0.0, total=0.0)
    return SimpleNamespace(seq=seq, at=seq, type=SimpleNamespace(name=SELECTED.name), data=data)


class _Store(SqlDB):
    """Le journal de ces événements (leurs numéros et leurs types, dans la vraie table) ; les événements eux-mêmes,
    tels quels."""

    def __init__(self, events: list[SimpleNamespace]) -> None:
        super().__init__()
        self.events = {e.seq: e for e in events}
        self.create(JournalEvent)
        if events:
            self.execute(insert(JournalEvent.__table__), [
                {"seq": e.seq, "id": f"e{e.seq}", "type": e.type.name, "v": 1, "at": e.at, "causation": None,
                 "correlation": "c", "basis": 0, "origin": "{}", "data": "{}"} for e in events])

    def get_events(self, seqs):
        return [self.events[s] for s in seqs if s in self.events]


#: la politique de l'arbitre que lit sa table (le rythme maximal de chaque sorte, ADR 0177) : celle du noyau composé
POLICY = ArbitrationPolicy(max_rates={"INITIATIVE": 0.1})


def _ui(events: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(kernel=SimpleNamespace(mind=SimpleNamespace(store=_Store(events)),
                                                  registry=SimpleNamespace(arbitration=POLICY)),
                           decode=lambda e: e)


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

    def who_cell(self, target):
        return Text(self.who(target))


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
    assert "0,42" in lead.text and "Parmi 2 lignes" in lead.text  # le tirage et les lignes, à la française
    steps = next(b for b in spoke if isinstance(b, Table))
    assert any("Envie de compagnie" in str(c) for r in steps.rows for c in r.cells)  # la preuve en mots
    # les lignes non retenues se lisent comme la table de l'arbitre : la sorte, la cible et le rythme maximal, repliés,
    # ont leurs colonnes (cinq colonnes seulement les laissaient tomber au rendu)
    others = next(b for b in spoke if isinstance(b, Disclosure)).items[0]
    assert others.columns == ARBITER_COLUMNS and all(len(r.cells) == len(others.columns) for r in others.rows)
    murmur = SimpleNamespace(seq=13, data=SimpleNamespace(kind="MURMUR", target=None, trigger="prélude:selected:10",
                                                         reply_to=None, reason=""))
    before = next(b for b in cause_blocks(ui, murmur) if isinstance(b, Note))
    assert before.text.startswith("Un murmure juste avant d'agir")
    # contre-exemple : une réponse ne passe pas par l'arbitre (elle n'est pas « prise d'elle-même »)
    asked = _started(14, "perception:9", "alice", reply_to=9, reason="")
    assert not any(isinstance(b, Note) and "d'elle-même" in b.text for b in cause_blocks(ui, asked))


# ── son humeur citée de son prompt, des nombres accordés ─────────────────


#: une section affective de la zone volatile (son humeur), et une qui ne l'est pas (qui elle a en face)
MOOD = SimpleNamespace(key="mood", zone=Zone.VOLATILE, tags=(Tag.AFFECTIVE,), title="SON HUMEUR")
WHO = SimpleNamespace(key="who", zone=Zone.VOLATILE, tags=(), title="QUI TU AS EN FACE")
SAID = "Ton humeur générale est contente, comme d'habitude."


def _said_with_mood() -> tuple[SimpleNamespace, dict, SimpleNamespace]:
    """Un noyau qui déclare ces deux sections, la trace d'un prompt qui les a montrées, et la parole qui les cite."""
    blocks = {k.key: HEADER_FMT.format(title=k.title) + "\n" + text + "\n"
              for k, text in ((WHO, "Adrien, ton ami."), (MOOD, SAID))}
    trace = {STABLE_KEY: "", "messages": [{"role": "user", "content": blocks["who"] + blocks["mood"] + "salut"}],
             "compose": {"sizes": [(k, len(b)) for k, b in blocks.items()], "included": list(blocks),
                         "anchors": [(k, b.split("\n", 1)[0] + "\n") for k, b in blocks.items()],
                         "chars": 1, "history_turns": 1}}
    ui = SimpleNamespace(kernel=SimpleNamespace(registry=SimpleNamespace(sections=(WHO, MOOD))),
                         names=SimpleNamespace(section={"mood": "Son humeur", "who": "Qui elle a en face"}.get))
    utterance = SimpleNamespace(data=SimpleNamespace(sections=("who", "mood"), annotation=lambda _key: None))
    return ui, trace, utterance


def test_her_mood_reads_as_a_quote_from_her_prompt_on_both_renderings():
    ui, trace, utterance = _said_with_mood()
    # la page dessinée : le libellé dit d'où vient le texte, au « tu » parce qu'il s'adresse à elle
    state, missing = inner_state(ui, trace, utterance)
    assert state == [("dans son prompt : son humeur", SAID + "\n")] and not missing
    # le repli (les blocs de la console) dit le même libellé
    fields = next(b for b in mood_blocks(ui, trace, utterance) if isinstance(b, Fields))
    assert [label for label, _cell in fields.pairs] == ["dans son prompt : son humeur"]
    # contre-exemple : une section qui n'est pas affective (qui elle a en face) n'est pas son humeur
    assert not any("qui elle a en face" in label for label, _text in state)


def test_tools_and_prompt_say_their_numbers_in_agreed_words():
    one = tools_view({"tools": ["web_search"], "tool_calls": []})
    assert one["summary"] == "1 outil en main, 0 appelé." and one["held"] == "L'outil qu'elle avait en main"
    many = tools_view({"tools": ["a", "b", "c"], "tool_calls": [{"name": "a", "ok": True}, {"name": "b", "ok": False}]})
    assert many["summary"] == "3 outils en main, 2 appelés." and many["held"] == "Les 3 outils qu'elle avait en main"
    assert prompt_measure({"chars": 1, "history_turns": 1}) == "1 caractère, 1 tour de conversation"
    assert prompt_measure({"chars": 12345, "history_turns": 0}) == f"{num_fr(12345)} caractères, 0 tour de conversation"
    ui, trace, _utterance = _said_with_mood()
    trace["compose"]["history_turns"] = 3
    shown = prompt_view(ui, trace)
    assert shown["measure"] == "1 caractère, 3 tours de conversation" and prompt_view(ui, None)["measure"] == ""
    # les gabarits partagés par la parole, l'épisode et le silence écrivent ces libellés, jamais « (s) »
    macros = env.from_string('{% import "handmade/parole/macros.html" as p %}{{ p.prompt_head(prompt) }}{{ p.tools(t) }}')
    html = macros.render(prompt=shown, t=one)
    assert "1 caractère, 3 tours de conversation." in html and "L&#39;outil qu&#39;elle avait en main" in html
    assert "(s)" not in html and "Les 1 outils" not in html

