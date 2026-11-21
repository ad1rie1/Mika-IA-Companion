"""Ce que le fil montre encore ne se redit pas (ADR 0263).

Le prompt réel du 19 novembre 2026 portait le même fait quatre ou cinq fois : dans son portrait, son récit, « ce que
tu as déjà dit de toi », « ce qui vous lie » — et dans les quarante tours du fil encore affichés, d'où il venait. Elle
le ressortait. Une ligne de sa mémoire connaît les messages d'où elle vient (``memory_items.sources``, les numéros des
tours du fil) : tant que l'historique rendu les montre, la ligne se tait ; quand le fil glisse hors de la fenêtre, elle
revient. Un intertitre resté seul part avec ce qu'il annonçait.
"""

from __future__ import annotations

from mika.contracts import memory as mc
from mika.faculties.memory import kept
from mika.faculties.memory.extraction import XCroyance
from mika.faculties.memory.faculty import MemoryState
from mika.faculties.memory.recall import Recall, Recalled
from mika.faculties.memory.recall_sections import _body, _self_said_section
from mika.faculties.social.sections import between_us
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from mika.kernel.faculty import SectionSpec, Zone
from mika.kernel.frame import Audience
from mika.kernel.prompt import Budget, ChatTurn, Composer, SectionBody
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity, Verdict
from tests.unit.test_knowledge_coherence import FRAME, Store
from tests.unit.test_knowledge_coherence import Frame as Frame_
from tests.unit.test_one_door import DB, SAM, Frame, belief
from tests.unit.test_self_said import item

SAID = "Je ne supporte pas les titres racoleurs"


def _later(days: int):
    """Le même cadre, ``days`` jours plus tard."""
    frame = Frame_()
    frame.now = FRAME.now + days * DAY
    return frame


def _compose(body: SectionBody, *visible: int):
    """Le prompt d'une réponse dont l'historique rendu montre les tours ``visible``."""
    spec = SectionSpec("probe", "section", Zone.VOLATILE, frozenset({"REPLY"}), lambda *a: None)
    history = SectionSpec("probe", "history", Zone.HISTORY, frozenset({"REPLY"}), lambda *a: None)
    turns = tuple(ChatTurn("assistant" if i % 2 else "user", f"message {i}", id=i) for i in visible)
    return Composer().compose([(history, SectionBody(turns)), (spec, body)], kind="REPLY", audience_level=3,
                              muted_tags=frozenset(), message="coucou",
                              budget=Budget(max_tokens=4000, chars_per_token=1.0))


def test_what_she_said_of_herself_is_silent_while_the_thread_shows_her_last_saying_it():
    db = Store()
    db.put(mc.BELIEVED.draft(text=Content.of(SAID), about_self=True, durable=True, sources=(42, 41)), 50, FRAME.now)
    assert item(db, 50).sources == (41, 42)  # les messages d'où elle vient, dans l'ordre
    # elle le redit plus tard : la redite complète ses sources
    (again,) = kept._about_self(XCroyance(texte=SAID, genre="avis", sur_elle=True), db,
                                lambda _: ((57,), (), []), "self", set())
    db.put(again, 60, FRAME.now)
    note = item(db, 50)
    assert note.sources == (41, 42, 57)
    body = _self_said_section(MemoryState(), FRAME, {"recall": Recall(self_said=[note])})
    assert [f.covered_by for f in body.fragments] == [(57,)] and SAID in body.content
    # le fil montre encore sa dernière redite : la ligne ne la redit pas, et la trace dit pourquoi
    prompt, trace = _compose(body, 56, 57, 58)
    assert SAID not in prompt.system_volatile
    assert ("section", "déjà dans l'historique rendu") in trace.dropped and not trace.provenance
    # la fenêtre a glissé (seuls ses premiers messages s'y voient encore, ou plus aucun) : elle s'en souvient
    for visible in ((41, 42), ()):
        prompt, trace = _compose(body, *visible)
        assert SAID in prompt.system_volatile and trace.provenance == ("memory:50",)
    # vingt jours plus tard, le fil court le montre encore — mais il s'y perd : sa mémoire le redit (HUM-6)
    old = _self_said_section(MemoryState(), _later(20), {"recall": Recall(self_said=[note])})
    assert [f.covered_by for f in old.fragments] == [()]
    assert SAID in _compose(old, 56, 57, 58)[0].system_volatile


def test_what_comes_back_to_her_is_still_said_and_its_headings_never_stay_alone():
    """« Ce qui te revient » se redit même quand le fil le montre : ce qu'elle a sous les yeux est ce que son usage
    renforce, et la relecture d'un salon, d'un secret, s'y appuie. Ses intertitres, eux, ne restent jamais seuls."""
    db = Store()
    db.put(mc.BELIEVED.draft(text=Content.of("Arthur a des yoyos tout neufs"), about=("user_2",),
                             told_by=("user_2",), heard_by=("user_2",), sensitivity=1, sources=(12, 14)), 20,
           FRAME.now)
    recalled = [Recalled(item(db, 20), Verdict(ok=True), item(db, 20).text)]
    body = _body(Recall(beliefs=recalled, unsaid=["- quelque chose sur quelqu'un"]), FRAME, witness=False)
    assert [(f.heading, f.covered_by) for f in body.fragments] == [
        (True, ()), (False, ()), (True, ()), (False, ()), (False, ())]
    prompt, trace = _compose(body, 12, 13, 14)
    assert "yoyos" in prompt.system_volatile and phrase("memory.recall.beliefs") in prompt.system_volatile
    assert trace.provenance == ("memory:20",)


def test_what_is_theirs_alone_knows_the_messages_it_comes_from():
    """« Ce qui vous lie » : chaque blague porte ses messages (``between_us``), que sa section donne au composeur."""
    db = DB()
    mine = db.put(belief("Avec Sam, on a une blague sur les yoyos", (SAM,), (SAM,), sensitivity=1, between=True))
    private = Audience(persons=(SAM,), public=False, level=int(Sensitivity.PERSONAL),
                       witness_level=int(Sensitivity.PERSONAL), private_ok=True)
    ((number, text, shown),) = between_us(db, Frame(private), SAM)
    assert number == mine and "yoyos" in text and isinstance(shown, tuple)
