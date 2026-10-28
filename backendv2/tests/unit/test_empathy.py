"""L'empathie (ADR 0083) : un souvenir, une croyance, un moment portent ce que la personne concernée en ressent et ce
qu'elle-même en ressent — plusieurs facettes, chacune d'intensité 0 à 1 (« colère 0,8, dégoût 0,4 »), jugées par la
relecture, jamais devinées d'après les mots — et chaque élément est relié à ses émotions : « ce qui t'énerve » se
cherche.

Avant, une croyance confiée n'avait aucune émotion : devant une proche, toute confidence tue se disait « un moment
difficile », grossesse comprise (sonde réelle du 2026-10-09 : « Inès t'a confié traverser un moment difficile »,
pour une bonne nouvelle qu'Inès gardait). Rien ne disait non plus, en se souvenant, ce que la personne vivait ni ce
qu'elle-même en ressentait, ni ne permettait de chercher par émotion. Chaque cible échoue sur l'arbre d'avant.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import memory as mc
from mika.contracts import runtime as rt
from mika.faculties.memory import consolidation as cons
from mika.faculties.memory.extraction import (
    Conversation,
    Extraction,
    Line,
    Speaker,
    XCroyance,
    XEvenement,
    XSouvenir,
    render,
)
from mika.faculties.memory.faculty import MemoryParams, MemoryState, _retained
from mika.faculties.memory.recall import _body, _recall
from mika.faculties.memory.tools import SearchArgs, memory_search
from mika.kernel.events import Content
from mika.kernel.frame import Audience
from mika.ports.vectors import VectorItem
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME, Frame, Store, alice_says, ask, drafts, index

ALICE, INES = "user_2", "user_5"
CLOSE = Audience(persons=(ALICE,), public=False, level=int(Sensitivity.PERSONAL),
                 witness_level=int(Sensitivity.CONFIDENCE), private_ok=True)


# ── La relecture juge ce que chacun ressent ─────────────────────────────────


def test_the_reread_starts_from_what_she_said_she_felt():
    """Ce qu'elle a déclaré en répondant (sa balise) se montre à la relecture, en mots, après sa réplique : son
    « mon_ressenti » en part au lieu de se juger à neuf (ADR 0107). Jamais un nombre ; le calme ne se dit pas ; une
    réplique qui racontait sans nom ne dit rien de plus."""
    class Events:
        def get_events(self, seqs):
            notes = {11: '[["emotion", "sad:0.600,anxious:0.300"]]', 12: '[["emotion", "neutral:0.500"]]',
                     13: '[["emotion", "sad:0.700"]]'}
            return [NS(seq=s, type=rt.UTTERANCE.name, data=f'{{"annotations": {notes[s]}, "provenance": '
                                                            f'{"[\"veiled:1\"]" if s == 13 else "[]"}}}')
                    for s in seqs]

    lines = (Line(10, FRAME.now, "Alice [P1]", "mon chat est mort cette nuit", ALICE),
             Line(11, FRAME.now, "Mika", "Oh non, Alice… je suis là."),
             Line(12, FRAME.now, "Mika", "Tu veux en parler ?"),
             Line(13, FRAME.now, "Mika", "Une amie a vécu ça aussi."))
    conv = cons._her_lines(Events(), Conversation(f"private:{ALICE}", (Speaker("P1", ALICE, "Alice"),), lines))
    text = render(conv, now=FRAME.local(), beliefs=(), promises=())
    assert "je suis là. (en l'écrivant : tristesse et un peu d'inquiétude)" in text
    assert "en parler ? " not in text and "0.6" not in text and "0,6" not in text
    assert text.count("en l'écrivant") == 1  # ni le calme, ni ce qui se racontait sans nom



async def test_the_reread_says_what_the_person_feels_and_what_she_feels():
    db = Store()
    said = (alice_says("je suis enceinte !!! et l'écho c'est lundi, j'ai un peu peur"),)
    ex = Extraction(
        souvenirs=[XSouvenir(texte="Alice m'a annoncé qu'elle est enceinte", personnes=["P1"], messages=[10000],
                             ressenti="heureuse", mon_ressenti="contente")],
        croyances=[XCroyance(texte="Alice est enceinte", personnes=["P1"], messages=[10000], source="P1",
                             ressenti={"joie": 0.9, "excitation": 0.6, "compréhension": 0.3},
                             mon_ressenti="amusement, amour, joie")],
        evenements=[XEvenement(texte="Son échographie", quand="2026-10-12", personnes=["P1"], messages=[10000],
                               ressenti="inquiète", mon_ressenti="curieuse")])
    out = {d.type.name: d.data for d in await drafts(db, ex, said)}
    souvenir, belief, moment = out[mc.REMEMBERED.name], out[mc.BELIEVED.name], out[mc.EVENT_NOTED.name]
    assert (souvenir.felt, souvenir.emotion) == ((("happy", 0.7),), "happy")
    # plusieurs facettes, la plus forte d'abord ; « compréhension » n'est pas une de ses 29 émotions
    assert belief.felt == (("happy", 0.9), ("excited", 0.6))
    assert belief.empathy == (("amused", 0.7), ("love", 0.7), ("happy", 0.7))
    assert (moment.felt, moment.empathy) == ((("anxious", 0.7),), (("curious", 0.7),))
    db.conn.close()


async def test_what_moves_strongly_is_kept_better():
    """Un moment chargé se garde mieux (ADR 0107) : ce que la relecture juge anodin (1) mais vécu fortement — par la
    personne ou par elle — monte au moins à « important », souvenir, croyance et moment ; vécu sans force, il reste
    anodin ; et une importance déjà haute ne baisse pas."""
    said = (alice_says("mon frère a eu un accident, il va bien mais j'ai eu tellement peur"),)
    ex = Extraction(
        souvenirs=[XSouvenir(texte="Alice a eu très peur pour son frère", personnes=["P1"], messages=[10000],
                             importance=1, ressenti={"peur": 0.9})],
        croyances=[XCroyance(texte="Le frère d'Alice a eu un accident", personnes=["P1"], messages=[10000],
                             source="P1", importance=1, mon_ressenti={"inquiétude": 0.8})],
        evenements=[XEvenement(texte="Le repas chez ses parents", quand="2026-10-12", personnes=["P1"],
                               messages=[10000], importance=1, ressenti={"soulagement": 0.4}),
                    XEvenement(texte="Le match de son frère", quand="2026-10-14", personnes=["P1"],
                               messages=[10000], importance=1, ressenti={"excitation": 0.9})])
    db = Store()
    got = await drafts(db, ex, said)
    db.conn.close()
    out = {d.type.name: d.data for d in got}
    moments = {str(d.data.text.text): d.data.importance for d in got if d.type.name == mc.EVENT_NOTED.name}
    p = MemoryParams()
    assert out[mc.REMEMBERED.name].importance == p.charged_importance  # la peur de la personne
    assert out[mc.BELIEVED.name].importance == p.charged_importance  # sa propre inquiétude
    assert moments["Le match de son frère"] == p.charged_importance  # attendu avec excitation
    assert moments["Le repas chez ses parents"] < p.charged_importance  # un soulagement léger : rien de plus
    loud = Extraction(souvenirs=[XSouvenir(texte="Alice a eu très peur pour son frère", personnes=["P1"],
                                           messages=[10000], importance=4, ressenti={"peur": 0.9})])
    db = Store()
    (kept,) = [d.data for d in await drafts(db, loud, said) if d.type.name == mc.REMEMBERED.name]
    db.conn.close()
    assert kept.importance > p.charged_importance  # marquant le reste


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
    text = "Bob a encore menti à Alice"
    db.put(mc.BELIEVED.draft(text=Content.of(text), about=(ALICE,), told_by=(ALICE,), heard_by=(ALICE,),
                             source=ALICE, sensitivity=2, felt={"colère": 0.8, "dégoût": 0.4},
                             empathy={"triste": 0.6, "inquiète": 0.3}), 1, FRAME.now)
    ask(db, "tu te souviens que Bob a encore menti à Alice ?")
    vectors = await index(db, [VectorItem(1, mc.BELIEF, text, (ALICE,))])
    frame = Frame(CLOSE)
    body = _body(await _recall(MemoryState(), frame, {"store": db, "vectors": vectors}), frame, witness=False)
    db.conn.close()
    assert body is not None
    line = next(ln for ln in body.content.splitlines() if text in ln)
    assert "Alice le vit avec colère et un peu de dégoût" in line
    assert "toi, tu en es triste, avec un peu d'inquiétude" in line
    assert not any(ch.isdigit() for ch in line)  # des mots, jamais un nombre


# ── Les temps durs : ce que la personne ressent elle-même ───────────────────


def test_what_the_person_feels_tells_her_hard_times():
    cx = NS(params=MemoryParams(), facts=NS(get=lambda _r: None), now=FRAME.now)

    def believed(felt):
        return NS(type=mc.BELIEVED, seq=7, at=FRAME.now, data=mc.BELIEVED.draft(
            text=Content(ref="r"), about=(ALICE,), told_by=(ALICE,), importance=0.95, felt=felt).data)

    # son père à l'hôpital : elle s'inquiète, malgré un peu de soulagement qu'il soit pris en charge
    assert ALICE in _retained(MemoryState(), believed({"inquiète": 0.8, "soulagée": 0.3}), cx).hard
    assert ALICE not in _retained(MemoryState(), believed({"heureuse": 0.8, "inquiète": 0.2}), cx).hard
    # toutes les facettes comptent, pas seulement la première : un peu inquiète, mais soulagée et heureuse
    assert ALICE not in _retained(MemoryState(), believed({"inquiète": 0.5, "soulagée": 0.5, "heureuse": 0.5}), cx).hard


# ── « Qu'est-ce qui t'énerve ? » : chercher par émotion ─────────────────────


async def test_what_angers_her_is_found_by_feeling():
    db = Store()
    rows = ((1, "Bob s'est moqué de mon dessin devant tout le monde", mc.REMEMBERED, {}, {"colère": 0.8}),
            (2, "Carol m'a offert un carnet à dessin", mc.REMEMBERED, {}, {"joie": 0.9}),
            (3, "Le voisin d'Alice fait du bruit toute la nuit", mc.BELIEVED, {"agacement": 0.9}, {}))
    for seq, text, kind, felt, empathy in rows:
        about = (ALICE,) if kind is mc.BELIEVED else ()
        db.put(kind.draft(text=Content.of(text), about=about, told_by=about, heard_by=about, sensitivity=1,
                          felt=felt, empathy=empathy), seq, FRAME.now)
    vectors = await index(db, [VectorItem(seq, mc.SOUVENIR if kind is mc.REMEMBERED else mc.BELIEF, text, ())
                               for seq, text, kind, _f, _e in rows])

    async def search(**kw):
        return await memory_search(SearchArgs(query="ce qui m'énerve", **kw),
                                   NS(ports={"store": db, "vectors": vectors}, frame=Frame(CLOSE)))

    mine = await search(ressenti=["colère", "agacement"])
    assert "moqué de mon dessin" in mine and "carnet" not in mine and "voisin" not in mine
    assert "en colère" in mine  # ce qu'elle en a ressenti, en mots
    theirs = await search(ressenti=["agacement"], de_qui="la_personne")
    assert "voisin" in theirs and "moqué" not in theirs
    db.conn.close()
