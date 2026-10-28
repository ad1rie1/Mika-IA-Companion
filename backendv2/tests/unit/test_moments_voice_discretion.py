"""Ce qu'elle déplace, ce qu'elle a vécu, ce qu'elle tait (ADR 0076) — trouvés par la sonde réelle du 2026-10-09.

- « finalement mon entretien est reporté à lundi » déplace le moment noté, il n'en ajoute pas un second : la relecture
  voit les moments à venir avec leur numéro et désigne celui qu'elle remplace, qui lui lègue son secret ;
- un souvenir à la première personne est toujours le sien : écrit à la place de Carol (« J'ai eu une petite fille »),
  il devient ce que Carol lui a dit ;
- ce qu'elle tait se tait avec jugement, pas avec une phrase toute faite qui avoue un secret ;
- la CLI reçoit l'effort de réflexion du fournisseur ; le modèle de plongements se charge au démarrage.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from mika.app.server import _warm
from mika.contracts import memory as mc
from mika.faculties.memory import consolidation as cons
from mika.faculties.memory.extraction import (
    Conversation,
    Extraction,
    Line,
    People,
    Speaker,
    XEvenement,
    XSouvenir,
    render,
    voice_of,
)
from mika.faculties.memory.faculty import MemoryParams, MemoryState
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from mika.vocab.phrasebook import phrase
from tests.unit.test_knowledge_coherence import ALICE, FRAME, Store, alice_says

CAROL = (Speaker("P1", "user_4", "Carol"),)


def _interview(db: Store, *, secret: bool = False) -> int:
    db.put(mc.EVENT_NOTED.draft(text=Content.of("son entretien d'embauche chez Ubisoft"), when=FRAME.now + 2 * DAY,
                                about=("user_2",), sensitivity=2, told_by=("user_2",), heard_by=("user_2",),
                                secret=secret, importance=0.8), 65)
    return 65


def _monday() -> str:
    return (FRAME.local() + timedelta(days=5)).date().isoformat()


async def _drafts(db: Store, ex: Extraction, line: str, moments) -> list:
    conv = Conversation("private:user_2", ALICE, (alice_says(line),))
    people = People.of(ALICE, {}, "Mika", scope=conv.key)
    return await cons._drafts(ex, FRAME, MemoryState(), db, conv, people, [], [], None, MemoryParams(), "audit",
                              moments=moments)


# ── un moment déplacé ─────────────────────────────────────────────────────


def test_the_extraction_sees_the_upcoming_moments_with_their_numbers():
    db = Store()
    old = _interview(db)
    conv = Conversation("private:user_2", ALICE, (alice_says("finalement il est reporté à lundi"),))
    shown, upcoming = cons._moments(FRAME, db, MemoryState(), conv, {"user_2": "Alice [P1]"})
    assert [i for i, _w, _t in shown] == [old] and set(upcoming) == {old}
    text = render(conv, now=FRAME.local(), beliefs=(), promises=(), moments=shown)
    assert phrase("memory.extraction.render.moments") in text
    assert f"[#{old}] (Alice [P1]) le " in text and "son entretien d'embauche chez Ubisoft" in text
    db.conn.close()


async def test_a_postponed_moment_replaces_the_one_it_moves_and_inherits_its_secret():
    """L'ancien moment était secret (il laisse deviner une recherche d'emploi) : le moment déplacé le reste, et
    l'ancien est remplacé, pas laissé à côté."""
    db = Store()
    old = _interview(db, secret=True)
    conv = Conversation("private:user_2", ALICE, (alice_says("finalement il est reporté à lundi"),))
    _shown, upcoming = cons._moments(FRAME, db, MemoryState(), conv, {})
    ex = Extraction(evenements=[XEvenement(texte="son entretien chez Ubisoft, reporté à lundi", quand=_monday(),
                                           personnes=["P1"], messages=[10000], remplace=old)])
    events = [d.data for d in await _drafts(db, ex, "finalement il est reporté à lundi", upcoming)
              if d.type.name == mc.EVENT_NOTED.name]
    assert len(events) == 1 and events[0].replaces == old and events[0].secret
    assert events[0].when > FRAME.now + 4 * DAY
    db.conn.close()


async def test_a_number_that_was_not_shown_replaces_nothing():
    """Contre-exemple : un numéro inventé (ou d'un moment qu'elle n'a pas vu) ne déplace rien."""
    db = Store()
    _interview(db)
    ex = Extraction(evenements=[XEvenement(texte="son examen de piano", quand=_monday(), personnes=["P1"],
                                           messages=[10000], remplace=999)])
    events = [d.data for d in await _drafts(db, ex, "lundi j'ai mon examen de piano", {})
              if d.type.name == mc.EVENT_NOTED.name]
    assert len(events) == 1 and events[0].replaces is None
    db.conn.close()


# ── un souvenir est le sien ───────────────────────────────────────────────


def test_a_first_person_souvenir_in_someone_elses_words_is_theirs():
    said = Line(10000, FRAME.now, "Carol", "je viens d'avoir une petite fille, Jeanne, je suis épuisée mais "
                                           "tellement heureuse", "user_4")
    assert voice_of("J'ai eu une petite fille, Jeanne : je suis épuisée mais tellement heureuse.", [said]) == said
    assert voice_of("J'ai félicité Carol pour la naissance de Jeanne ; elle est épuisée mais heureuse.",
                    [said]) is None, "son souvenir à elle"
    assert voice_of("Carol a eu une petite fille, Jeanne, elle est épuisée mais heureuse", [said]) is None, \
        "pas à la première personne : une croyance sur Carol"


async def test_the_souvenir_written_in_carols_place_becomes_what_carol_told_her():
    db = Store()
    line = Line(10000, FRAME.now, "Carol", "je viens d'avoir une petite fille, Jeanne, je suis épuisée mais "
                                           "tellement heureuse", "user_4")
    conv = Conversation("private:user_4", CAROL, (line,))
    ex = Extraction(souvenirs=[XSouvenir(texte="J'ai eu une petite fille, Jeanne : je suis épuisée mais tellement "
                                               "heureuse.", personnes=["P1"], messages=[10000], importance=3)])
    people = People.of(CAROL, {}, "Mika", scope=conv.key)
    got = [d.data for d in await cons._drafts(ex, FRAME, MemoryState(), db, conv, people, [], [], None,
                                              MemoryParams(), "audit")
           if d.type.name == mc.REMEMBERED.name]
    assert len(got) == 1 and got[0].text.text.startswith("Carol") and got[0].told_by == ("user_4",)
    db.conn.close()


# ── ce qu'elle tait ───────────────────────────────────────────────────────


def test_what_she_keeps_to_herself_is_kept_with_judgment_not_a_stock_phrase():
    """La consigne ne lui fait plus dire « ce n'est pas à moi d'en parler » (qui avoue un secret) : elle a son avis,
    tiré de ce qui peut se dire, sans laisser deviner — et si elle ment, elle le sait (``test_lies``)."""
    advice = phrase("memory.recall.unsaid_advice")
    assert "pas à toi d'en parler" not in advice and "dis simplement" not in advice
    assert "ton avis" in advice and "mensonge" in advice
    assert "pas à toi d'en parler" not in phrase("memory.unsaid.private", who="Alice")


# ── la CLI et le démarrage ────────────────────────────────────────────────


def test_the_cli_receives_the_effort_and_refuses_an_unknown_one(tmp_path):
    from mika.adapters.llm.claude_code import ClaudeCodeBackend
    from mika.adapters.mcp.relay import Relay
    from mika.ports.llm import LLMRequest

    be = ClaudeCodeBackend("haiku", relay=Relay(), relay_base="http://x", effort="medium", work_dir=tmp_path)
    argv = be.argv(LLMRequest(role="reply", call_id="e#0", system_stable=""), tmp_path, mcp=False, deferred=False)
    assert argv[argv.index("--effort") + 1] == "medium"
    plain = ClaudeCodeBackend("haiku", relay=Relay(), relay_base="http://x", work_dir=tmp_path)
    assert "--effort" not in plain.argv(LLMRequest(role="reply", call_id="e#1", system_stable=""), tmp_path, mcp=False, deferred=False)
    with pytest.raises(ValueError):
        ClaudeCodeBackend("haiku", relay=Relay(), relay_base="http://x", effort="énorme", work_dir=tmp_path)


async def test_the_embedding_model_is_warmed_at_startup_and_a_failure_stops_nothing(caplog):
    class Warmable:
        warmed = 0

        async def warm(self):
            self.warmed += 1

    class Broken:
        async def warm(self):
            raise OSError("modèle introuvable")

    w = Warmable()
    await _warm(w)
    await _warm(object())  # un modèle sans préchargement (les tests, le simulateur) : rien à faire
    with caplog.at_level(logging.ERROR, logger="mika.server"):
        await _warm(Broken())
    assert w.warmed == 1 and "préchargement" in caplog.text


def test_her_memory_is_ready_before_her_first_reply():
    """Le modèle de plongements se charge pendant la relecture de sa vie ; elle ne se met à vivre (reprises, premiers
    messages) qu'une fois chargé — borné : au-delà de ``WARM_WAIT_S``, elle vit sans, comme avant. Sinon un message
    qui attendait au démarrage recevait une réponse sans souvenirs (lot I du chantier « émotions, conscience,
    mémoire »). L'ordre se lit dans le code (l'AST, jamais le texte) : l'attente précède ``kernel.live()``."""
    import ast
    import inspect

    from mika.app import server

    tree = ast.parse(inspect.getsource(server))
    life = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    calls = [n for n in ast.walk(life) if isinstance(n, ast.Call)]
    waited = [c.lineno for c in calls if getattr(c.func, "attr", "") == "wait_for"
              and any(isinstance(a, ast.Name) and a.id == "WARM_WAIT_S" for a in c.args)]
    live = [c.lineno for c in calls if getattr(c.func, "attr", "") == "live"]
    assert waited and live and waited[0] < live[0]
    assert 0 < server.WARM_WAIT_S <= 120


def test_a_named_day_is_placed_on_the_calendar_not_guessed():
    """« Finalement il est reporté à lundi » : la relecture voit chaque jour autour nommé et daté (« lundi 13 octobre
    »), de la semaine qui précède les messages aux deux semaines qui viennent — elle ne calcule plus « lundi » au jugé
    (ADR 0099)."""
    from datetime import date

    from mika.faculties.memory.extraction import CALENDAR_MAX, calendar, day_words

    days = calendar(date(2026, 10, 9), date(2026, 10, 9)).split(", ")  # un vendredi
    assert day_words(date(2026, 10, 12)) in days  # le lundi qui vient
    assert day_words(date(2026, 10, 5)) in days  # le lundi d'avant
    assert days[0] == day_words(date(2026, 10, 2)) and days[-1] == day_words(date(2026, 10, 23))
    assert len(calendar(date(2026, 1, 1), date(2026, 10, 9)).split(", ")) == CALENDAR_MAX  # une vieille conversation
    conv = Conversation("private:user_2", ALICE, (alice_says("finalement il est reporté à lundi"),))
    text = render(conv, now=FRAME.local(), beliefs=(), promises=())
    assert phrase("memory.extraction.render.calendar", days=calendar(FRAME.local().date(), FRAME.local().date())) \
        in text
