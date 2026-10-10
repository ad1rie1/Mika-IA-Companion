"""Le temps des choses (ADR 0084) : une date dite avec sa précision, ce qui arrive dans le monde, ce qu'elle vivra à
travers quelqu'un, et à quel point c'est sûr.

Avant, un moment n'avait qu'un jour : « en novembre » devenait le 1er novembre (et « bonne chance » la veille) ; ce
qui arrivait dans le monde se rangeait dans la vie de qui en parlait ; rien ne distinguait un rendez-vous fixé d'une
rumeur, ni ne gardait une prévision (« Léa pense qu'elle sera prise »). Elle n'a pas de corps : un moment qu'elle
s'inventerait n'est pas un moment ; elle vit à travers ses relations. Chaque cible échoue sur l'arbre d'avant.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from mika.contracts import memory as mc
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory.archive import decode
from mika.faculties.memory.extraction import Extraction, XEvenement, XPrevision
from mika.faculties.memory.faculty import (
    MemoryParams,
    MemoryState,
    _ahead,
    _forget_life,
    _life_events,
    _noted,
)
from mika.faculties.memory.recall import Recall, _ahead_moments, expected_line, items_by_id
from mika.faculties.memory.recall import _ahead as ahead_section
from mika.faculties.others.faculty import OthersParams, _cheer_window
from mika.kernel.events import Content
from mika.kernel.frame import Audience
from mika.vocab import timespan
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME, Frame, Store, alice_says, drafts, mika_says

UTC = ZoneInfo("UTC")
NOW = FRAME.now  # jeudi 8 octobre 2026, midi
ALICE, CAROL = "user_2", "user_4"
CX = NS(params=MemoryParams(), facts=NS(get=lambda _r: None), now=NOW, tz=UTC)
FRIEND = Audience(persons=(CAROL,), public=False, level=int(Sensitivity.PERSONAL),
                  witness_level=int(Sensitivity.PERSONAL), private_ok=True)


def _event(draft_data, seq=5):
    """L'événement tel que le noyau l'écrit : son texte a sa référence (celle du magasin de test)."""
    data = draft_data.model_copy(update={"text": Content(ref=f"{seq}.text", text=draft_data.text.text)})
    return NS(type=mc.EVENT_NOTED, data=data, seq=seq, at=NOW)


async def _noted_from(said: str, *events: XEvenement) -> list:
    db = Store()
    out = await drafts(db, Extraction(evenements=list(events)), (alice_says(said),))
    db.conn.close()
    return [d.data for d in out if d.type.name == mc.EVENT_NOTED.name]


# ── Une date garde sa précision ─────────────────────────────────────────────


async def test_a_month_is_a_month():
    assert timespan.words(timespan.parse("2026-11", UTC), NOW, UTC) == "en novembre"
    assert timespan.words(timespan.parse("printemps 2027", UTC), NOW, UTC) == "au printemps 2027"
    assert timespan.words(timespan.parse("2026-11-03/2026-11-10", UTC), NOW, UTC) == "du 3 au 10 novembre"
    (ev,) = await _noted_from("je déménage à Lyon en novembre",
                              XEvenement(texte="Son déménagement à Lyon", quand="2026-11", personnes=["P1"],
                                         messages=[10000]))
    assert ev.precision == "month" and ev.until > ev.when  # pas le 1er novembre
    life = mc.life_event_of(1, ev)
    assert life.vague and _cheer_window(life, FRAME, OthersParams()) is None  # une période n'a pas de veille


def test_old_moments_replay_unchanged():
    old = mc.EVENT_NOTED.payload.model_validate({"text": {"ref": "r"}, "when": NOW, "about": [ALICE],
                                                 "told_by": [ALICE]})
    ev = mc.life_event_of(3, old)
    assert (ev.precision, ev.until, ev.scope, ev.shared, ev.likelihood, ev.vague, ev.ends) == \
        ("", 0, "person", False, None, False, NOW)
    # une ligne de l'archive d'avant, sans les champs nouveaux, se relit à l'identique
    raw = json.dumps({k: v for k, v in asdict(ev).items()
                      if k not in ("until", "precision", "scope", "shared", "official", "likelihood")})
    assert decode(raw) == ev


# ── Le monde n'est la vie de personne ───────────────────────────────────────


async def test_a_world_moment_is_nobodys_life():
    (ev,) = await _noted_from("la présidentielle c'est en avril 2027",
                              XEvenement(texte="L'élection présidentielle", quand="2027-04", monde=True,
                                         date_officielle=True, personnes=["Macron"], messages=[10000]))
    assert (ev.scope, ev.about, ev.told_by, ev.official) == ("world", (), (ALICE,), True)
    s = _noted(MemoryState(), _event(ev), CX)
    assert _life_events(s, CX, ALICE) == ()  # ni la vie d'Alice, qui en parlait
    assert [m.id for m in _ahead(s, CX)] == [5]  # mais elle le voit venir
    gone = _forget_life(s, NS(data=NS(subject=ALICE)), CX)
    assert _ahead(gone, CX) == ()  # oublier qui le lui a dit l'emporte


# ── Pas de vie physique inventée ; ce qu'elle vit à travers quelqu'un ───────


async def test_she_never_notes_a_physical_life_of_her_own():
    db = Store()
    lines = (alice_says("et toi tu fais quoi ce week-end ?"),
             mika_says("samedi je vais au cinéma voir le dernier Miyazaki"))
    invented = XEvenement(texte="Aller au cinéma voir le dernier Miyazaki", quand="2026-10-10", sur_elle=True,
                          messages=[10001])
    out = await drafts(db, Extraction(evenements=[invented]), lines)
    assert [d for d in out if d.type.name == mc.EVENT_NOTED.name] == []  # elle n'a pas de corps
    db.conn.close()


async def test_a_shared_moment_is_hers_through_them():
    (ev,) = await _noted_from("samedi je t'emmène au salon du jeu vidéo, je te montrerai tout !",
                              XEvenement(texte="Le salon du jeu vidéo avec Alice", quand="2026-10-10",
                                         personnes=["P1"], partage=True, messages=[10000]))
    assert ev.shared and ev.about == (ALICE,) and ev.scope == "person"
    s = _noted(MemoryState(), _event(ev), CX)
    assert [m.id for m in _life_events(s, CX, ALICE)] == [5]  # la vie d'Alice
    assert [m.id for m in _ahead(s, CX)] == [5]  # et ce qu'elle-même vivra à travers elle
    body = _ahead_section_for(s, ev)
    assert "Le salon du jeu vidéo avec Alice" in body and "— tu le vivras à travers Alice" in body


# ── À quel point c'est sûr, en mots ─────────────────────────────────────────


async def test_likelihood_by_nature():
    p = MemoryParams()
    assert (lk.likelihood(lk.FIRST_HAND, None, p), lk.likelihood(lk.REPORTED, None, p),
            lk.likelihood(lk.OFFICIAL, None, p)) == (0.9, 0.7, 0.98)
    assert lk.likelihood(lk.FIRST_HAND, "peut-être", p) == 0.5  # ce qu'en dit la personne l'abaisse
    assert lk.likelihood(lk.REPORTED, "certain", p) == 0.7  # l'affirmer ne le rend pas plus sûr
    own, reported = await _noted_from(
        "jeudi j'ai mon entretien chez Ubisoft ; et Bob se marie le 17",
        XEvenement(texte="Son entretien chez Ubisoft", quand="2026-10-12", personnes=["P1"], messages=[10000]),
        XEvenement(texte="Le mariage de Bob", quand="2026-10-17", personnes=["Bob"], messages=[10000]))
    assert (own.likelihood, reported.likelihood) == (0.9, 0.7)  # de sa bouche, ou rapporté


def _ahead_section_for(s, ev) -> str:
    db = Store()
    db.put(mc.EVENT_NOTED.draft(**ev.model_dump()), 5, NOW)

    class Seen(Frame):
        def get(self, key):
            return _ahead(s, CX) if key.name == "memory.ahead" else super().get(key)

    frame = Seen(FRIEND)
    moments = _ahead_moments(frame, db, CAROL, FRIEND, MemoryParams(), {})
    body = ahead_section(s, frame, {"recall": Recall(ahead=moments)})
    db.conn.close()
    assert body is not None
    return body.content


async def test_no_number_in_the_prompt():
    (ev,) = await _noted_from("la présidentielle c'est en avril 2027",
                              XEvenement(texte="L'élection présidentielle", quand="2026-10-11", monde=True,
                                         date_officielle=True, messages=[10000]))
    body = _ahead_section_for(_noted(MemoryState(), _event(ev), CX), ev)
    assert "L'élection présidentielle (c'est sûr)" in body
    assert not any(n in body for n in ("0.9", "0,9", "%", "98"))  # sa vraisemblance en mots, jamais un nombre


# ── Une prévision, au plus comme une déduction ──────────────────────────────


async def test_a_prediction_is_capped_like_an_inference():
    db = Store()
    pv = XPrevision(texte="Alice sera prise au conservatoire", quand="2026-11", probabilite="certain",
                    personnes=["P1"], point_de_vue="P1", messages=[10000])
    out = await drafts(db, Extraction(previsions=[pv]), (alice_says("je suis sûre d'être prise en novembre !"),))
    (b,) = [d for d in out if d.type.name == mc.BELIEVED.name]
    assert (b.data.knowledge_kind, b.data.holder, b.data.expected_precision) == ("prediction", ALICE, "month")
    assert b.data.likelihood == 0.6  # « certain », dit par qui prévoit : au plus comme une déduction
    db.put(b, 7, NOW)
    line = expected_line(items_by_id(db, [7])[7], FRAME)
    assert line == " (attendu en novembre ; c'est probable)"
    db.conn.close()
