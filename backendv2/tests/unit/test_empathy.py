"""L'empathie (ADR 0083) : un souvenir, une croyance, un moment portent ce que la personne concernée en ressent et ce
qu'elle-même en ressent — jugés par la relecture, jamais devinés d'après les mots.

Avant, une croyance confiée n'avait aucune émotion : devant une proche, toute confidence tue se disait « un moment
difficile », grossesse comprise (sonde réelle du 2026-10-09 : « Inès t'a confié traverser un moment difficile »,
pour une bonne nouvelle qu'Inès gardait). Rien ne disait non plus, en se souvenant, ce que la personne vivait ni ce
qu'elle-même en ressentait. Chaque cible échoue sur l'arbre d'avant.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import memory as mc
from mika.faculties.memory.extraction import Extraction, XCroyance, XEvenement, XSouvenir
from mika.faculties.memory.faculty import MemoryParams, MemoryState, _retained
from mika.faculties.memory.recall import _body, _recall
from mika.kernel.events import Content
from mika.kernel.frame import Audience
from mika.ports.vectors import VectorItem
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME, Frame, Store, alice_says, ask, drafts, index

ALICE, INES = "user_2", "user_5"
CLOSE = Audience(persons=(ALICE,), public=False, level=int(Sensitivity.PERSONAL),
                 witness_level=int(Sensitivity.CONFIDENCE), private_ok=True)


# ── La relecture juge ce que chacun ressent ─────────────────────────────────


async def test_the_reread_says_what_the_person_feels_and_what_she_feels():
    db = Store()
    said = (alice_says("je suis enceinte !!! et l'écho c'est lundi, j'ai un peu peur"),)
    ex = Extraction(
        souvenirs=[XSouvenir(texte="Alice m'a annoncé qu'elle est enceinte", personnes=["P1"], messages=[10000],
                             ressenti="heureuse", mon_ressenti="contente")],
        croyances=[XCroyance(texte="Alice est enceinte", personnes=["P1"], messages=[10000], source="P1",
                             ressenti="ravie", mon_ressenti="contente")],
        evenements=[XEvenement(texte="Son échographie", quand="2026-10-12", personnes=["P1"], messages=[10000],
                               ressenti="inquiète", mon_ressenti="curieuse")])
    out = {d.type.name: d.data for d in await drafts(db, ex, said)}
    assert (out[mc.REMEMBERED.name].felt, out[mc.REMEMBERED.name].emotion) == ("happy", "happy")
    assert (out[mc.BELIEVED.name].felt, out[mc.BELIEVED.name].emotion) == ("happy", "happy")
    assert (out[mc.EVENT_NOTED.name].felt, out[mc.EVENT_NOTED.name].emotion) == ("anxious", "curious")
    db.conn.close()


# ── Une confidence tue : ce que la personne en ressent ──────────────────────


async def _unsaid_for(felt: str | None, *, sensitivity: int = int(Sensitivity.PERSONAL)) -> str:
    """La ligne de retenue que reçoit Alice, une proche, quand elle demande des nouvelles d'Inès, qui lui a confié en
    secret « Inès est enceinte de trois mois »."""
    db = Store()
    text = "Inès est enceinte de trois mois"
    db.put(mc.BELIEVED.draft(text=Content.of(text, level=sensitivity), about=(INES,), told_by=(INES,),
                             heard_by=(INES,), source=INES, sensitivity=sensitivity, secret=True, felt=felt), 1,
           FRAME.now)
    ask(db, "des nouvelles d'Inès ? elle est enceinte de trois mois ?")
    vectors = await index(db, [VectorItem(1, mc.BELIEF, text, (INES,))])
    frame = Frame(CLOSE)
    recall = await _recall(MemoryState(), frame, {"store": db, "vectors": vectors})
    db.conn.close()
    assert recall is not None and not any(text in r.label for r in recall.beliefs)  # le secret ne sort pas
    return "\n".join(recall.unsaid)


async def test_a_joyful_secret_is_not_a_difficult_moment():
    joyful = await _unsaid_for("happy")
    assert "Inès" in joyful and "bonne nouvelle" in joyful and "difficile" not in joyful
    assert "difficile" in await _unsaid_for("sad")  # contrôle : une peine reste une peine
    unknown = await _unsaid_for(None, sensitivity=int(Sensitivity.CONFIDENCE))
    assert "difficile" not in unknown and "tient à cœur" in unknown  # on ne sait pas : seulement que ça compte


# ── En se souvenant : ce que la personne vit, ce qu'elle-même en ressent ────


async def test_a_recalled_belief_says_both_feelings_in_words():
    db = Store()
    text = "Alice est enceinte de trois mois"
    db.put(mc.BELIEVED.draft(text=Content.of(text), about=(ALICE,), told_by=(ALICE,), heard_by=(ALICE,),
                             source=ALICE, sensitivity=2, felt="happy", emotion="happy"), 1, FRAME.now)
    ask(db, "tu te souviens que je suis enceinte de trois mois ?")
    vectors = await index(db, [VectorItem(1, mc.BELIEF, text, (ALICE,))])
    frame = Frame(CLOSE)
    body = _body(await _recall(MemoryState(), frame, {"store": db, "vectors": vectors}), frame, witness=False)
    db.conn.close()
    assert body is not None
    line = next(ln for ln in body.content.splitlines() if text in ln)
    assert "Alice le vit avec joie" in line and "tu en es contente" in line
    assert not any(ch.isdigit() for ch in line.replace("trois", ""))  # des mots, jamais un nombre


# ── Les temps durs : ce que la personne ressent elle-même ───────────────────


def test_what_the_person_feels_tells_her_hard_times():
    cx = NS(params=MemoryParams(), facts=NS(get=lambda _r: None), now=FRAME.now)

    def believed(felt):
        return NS(type=mc.BELIEVED, seq=7, at=FRAME.now, data=mc.BELIEVED.draft(
            text=Content(ref="r"), about=(ALICE,), told_by=(ALICE,), importance=0.95, felt=felt).data)

    assert ALICE in _retained(MemoryState(), believed("anxious"), cx).hard  # son père à l'hôpital : elle s'inquiète
    assert ALICE not in _retained(MemoryState(), believed("happy"), cx).hard
