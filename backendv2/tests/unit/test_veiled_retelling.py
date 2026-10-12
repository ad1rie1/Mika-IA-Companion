"""Raconter sans nommer (ADR 0091).

Ce qu'elle savait des autres se disait nommément, ou pas du tout. Une humaine raconterait « une amie vient de perdre
son travail » à quelqu'un qui ne la rencontrera jamais. Elle le peut maintenant — gradué par ce qu'elle sait de qui
l'écoute (le personnel à qui elle connaît, une confidence à une amie dont elle est sûre), à qui n'a **aucun lien
connu** avec la personne, en réponse seulement, avec la version que la relecture a écrite sans rien qui permette de la
reconnaître. Jamais un secret, même anonymisé ; jamais la vie de sa propriétaire ; jamais à côté du nom ; jamais une
preuve d'identité ; la relecture n'en apprend rien ; l'oubli n'en laisse rien.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from mika.contracts import memory as mc
from mika.contracts import runtime as rt
from mika.contracts.social import relations_table
from mika.contracts.transcript import thread_table
from mika.faculties.memory.extraction import (
    Conversation,
    Extraction,
    Line,
    People,
    Speaker,
    XCroyance,
    render,
    veiled_of,
    veiled_refusal,
)
from mika.faculties.memory.faculty import MemoryParams, MemoryState
from mika.faculties.memory.links import links_of
from mika.faculties.memory.projections import Items, Told
from mika.faculties.memory.recall import _recall
from mika.faculties.memory.veiled import _veiled, asks_news, echoed
from mika.kernel.clock import DAY
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.frame import Audience
from mika.kernel.prompt import Budget, Composer, SectionBody, unveiled
from mika.ports.paging import fold_text
from mika.ports.sql import upsert
from mika.vocab import privacy
from mika.vocab.privacy import ChannelTrust, Sensitivity
from mika.vocab.retelling import retellable
from tests.unit.test_audit_regressions import event
from tests.unit.test_knowledge_coherence import FRAME, Frame, mika_says
from tests.unit.test_readings import store

NOW = FRAME.now
OWNER, ALICE, BOB, INES, CHLOE = "user_1", "user_2", "user_3", "user_5", "user_6"
NAMES = {OWNER: "Nora Petit", ALICE: "Alice Durand", BOB: "Bob Leroy", INES: "Inès Moreau", CHLOE: "Chloé Martin"}
CLOSE = {OWNER: "close", ALICE: "friend", BOB: "acquaintance", INES: "friend", CHLOE: "acquaintance"}
LAYOFF = "quelqu'un que je connais vient de perdre son travail"
BREAKUP = "quelqu'un que je connais vient de se séparer"


class Hears(Frame):
    """Qui l'écoute, et ce que sa politique lui ouvre ; le graphe social (``ties``) au besoin."""

    env = NS(tz_of=FRAME.env.tz_of, params_of=lambda *_: MemoryParams())

    def __init__(self, who: str, *, certainty: float = 0.9, public: bool = False, ties=None, presumed=None):
        d = privacy.decide(certainty, ChannelTrust.ACCOUNT, closeness=CLOSE.get(who, ""), public=public,
                           owner=who == OWNER)
        self.ties = dict(ties or {})
        self.presumed = dict(presumed or {})
        super().__init__(audience=Audience(persons=(who,), public=public, level=int(d.level),
                                           witness_level=int(d.witness_level), private_ok=not public,
                                           certainty=certainty, room="salon" if public else None,
                                           veiled_level=int(d.veiled_level), untied_level=int(d.untied_level),
                                           tied_level=int(d.tied_level), ties=tuple(self.ties.get(who, ()))))
        self.episode = NS(target=who, kind="REPLY", attrs={"reply_to": 10000})

    def get(self, key):
        if key.name == "identity.identity":
            return NS(name=NAMES.get(key.arg, ""))
        if key.name == "social.closeness":
            return CLOSE.get(key.arg, "stranger")
        if key.name == "social.ties":
            return self.ties.get(key.arg, ())
        if key.name == "identity.owners":
            return (OWNER,)
        if key.name in ("identity.handles", "social.circle"):
            return ()
        if key.name == "identity.presumed":
            return self.presumed.get(key.arg, "")
        return super().get(key)


def alices_life():
    """Alice confie à Mika, en privé : un licenciement (personnel), une rupture (confidence), une grossesse qu'elle
    demande de garder pour soi (secret)."""
    db = store()
    told = {"about": (ALICE,), "told_by": (ALICE,), "heard_by": (ALICE,)}
    db.put(mc.BELIEVED.draft(text=Content.of("Alice a été licenciée de chez Ubisoft", level=2), sensitivity=2,
                             importance=0.7, veiled=Content.of(LAYOFF, level=2), **told), 5, NOW - DAY)
    db.put(mc.REMEMBERED.draft(text=Content.of("Alice m'a confié sa rupture avec Paul", level=3), sensitivity=3,
                               importance=0.7, veiled=Content.of(BREAKUP, level=3), **told), 6, NOW - DAY)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice est enceinte", level=3), sensitivity=3, importance=0.8,
                             secret=True, veiled=Content.of("quelqu'un que je connais attend un enfant", level=3),
                             **told), 7, NOW - DAY)
    db.put(mc.BELIEVED.draft(text=Content.of("Nora déménage à Lyon", level=2), sensitivity=2, importance=0.7,
                             about=(OWNER,), told_by=(OWNER,), heard_by=(OWNER,),
                             veiled=Content.of("quelqu'un que je connais déménage", level=2)), 8, NOW - DAY)
    return db


def ask(db, who: str, text: str = "salut ! quoi de neuf ?", *, room: str | None = None) -> None:
    upsert(db, thread_table(), {"id": 10000, "at": NOW, "role": "user", "person": who, "text": text, "room": room},
           keys=["id"])


async def told_to(db, frame: Hears) -> list[str]:
    recall = await _recall(MemoryState(), frame, {"store": db, "vectors": None})
    return [v.text for v in recall.veiled]


# ── qui entend quoi ────────────────────────────────────────────────────────


async def test_an_acquaintance_hears_the_layoff_without_a_name_a_friend_the_breakup_too():
    db = alices_life()
    ask(db, CHLOE)
    assert await told_to(db, Hears(CHLOE)) == [LAYOFF]  # une connaissance : le personnel, sans nom
    ask(db, INES)
    # une amie dont elle est sûre, sans lien avec Alice : le licenciement et la rupture, sans nom (ADR 0092 : une
    # amie de Mika n'entend plus la vie d'Alice nommément)
    assert sorted(await told_to(db, Hears(INES))) == sorted([LAYOFF, BREAKUP])
    assert await told_to(db, Hears(INES, certainty=0.75)) == [LAYOFF]  # pas assez sûre : pas la confidence
    body = _veiled(MemoryState(), Hears(CHLOE), {"recall": await _recall(MemoryState(), Hears(CHLOE),
                                                                          {"store": db, "vectors": None})})
    assert "Alice" not in body.content and "Ubisoft" not in body.content and "Paul" not in body.content
    assert "enfant" not in body.content and "déménage" not in body.content  # ni le secret, ni la vie de sa propriétaire
    assert body.veils == ("Alice Durand", "Alice") and body.provenance == ("veiled:5",)
    assert "quelqu'un que tu aimes bien" in body.content  # ce qu'Alice est pour elle, sans son genre


async def test_nothing_new_in_a_room_to_someone_uncertain_or_unknown():
    db = alices_life()
    ask(db, CHLOE, room="salon")
    assert await told_to(db, Hears(CHLOE, public=True)) == []
    ask(db, CHLOE)
    assert await told_to(db, Hears(CHLOE, certainty=0.5)) == []
    assert privacy.veiled(0.9, ChannelTrust.ACCOUNT, closeness="stranger") == Sensitivity.ANODYNE
    assert privacy.veiled(0.9, ChannelTrust.ACCOUNT, closeness="acquaintance") == Sensitivity.PERSONAL
    assert privacy.veiled(0.9, ChannelTrust.ACCOUNT, closeness="friend") == Sensitivity.CONFIDENCE
    assert privacy.veiled(0.9, ChannelTrust.ACCOUNT, owner=True) == Sensitivity.CONFIDENCE
    assert privacy.veiled(0.9, ChannelTrust.PUBLIC, closeness="close") == Sensitivity.ANODYNE
    assert privacy.decide(0.9, ChannelTrust.ACCOUNT, closeness="friend").veiled_level == Sensitivity.CONFIDENCE


async def test_only_in_reply_and_only_when_asked_or_relevant():
    db = alices_life()
    ask(db, CHLOE, "salut !")
    assert await told_to(db, Hears(CHLOE)) == []  # un bonjour ne fait pas raconter la vie des autres
    initiative = Hears(CHLOE)
    initiative.episode = NS(target=CHLOE, kind="INITIATIVE", attrs={})
    ask(db, CHLOE)
    assert await told_to(db, initiative) == []  # jamais en initiative
    assert asks_news("Quoi de neuf ?") and asks_news("t'as des nouvelles ?") and not asks_news("ça va ?")


async def test_what_could_be_said_by_name_is_unchanged():
    from mika.faculties.memory.recall import items_by_id, verdict_of

    db = alices_life()
    ask(db, INES)
    friend = Hears(INES, ties={INES: (ALICE,)})  # Alice l'a nommée elle-même : un lien prouvé
    layoff = items_by_id(db, [5])[5]
    assert verdict_of(friend, layoff, INES, friend.audience, {}, db).ok  # une amie qui la connaît l'entend nommé…
    assert await told_to(db, friend) == []  # … donc jamais sans nom
    untied = Hears(INES)
    assert not verdict_of(untied, layoff, INES, untied.audience, {}, db).ok  # sans lien : pas nommément
    ask(db, ALICE)
    assert await told_to(db, Hears(ALICE)) == []  # à la personne elle-même : rien sans nom, c'est sa vie


# ── aucun lien connu ───────────────────────────────────────────────────────


def said_to(target: str, provenance: str):
    """Une de ses répliques à ``target``, avec ce que son prompt montrait (sa provenance)."""
    return rt.UTTERANCE.draft(kind="REPLY", text=Content.of("…"), target=target, visible=True,
                              voice=VoiceProvenance(call_id="t", persona_hash="h", role="reply", model="m"),
                              provenance=(provenance,))


def thread(db, seq: int, who: str, text: str, room: str | None = None) -> None:
    """Un message du fil, tel que l'écrit ``transcript`` : son texte replié (``folded``) compris — la mémoire y cherche
    un prénom pareil sur les deux moteurs (ADR 0101)."""
    db.execute("INSERT INTO thread(id,at,role,person,text,room,folded) VALUES(?,?,?,?,?,?,?)",
               (seq, NOW - DAY, "user", who, text, room, fold_text(text)))


def answer(db, seq: int, who: str, text: str) -> None:
    """Sa réponse à ``who``, la ligne du fil de l'énoncé ``seq``."""
    upsert(db, thread_table(), {"id": seq, "at": NOW - DAY, "role": "assistant", "person": who, "text": text,
                                "room": None, "folded": fold_text(text)}, keys=["id"])


def shown_and_said(db, seq: int, who: str, item: int, text: str) -> None:
    Told().apply(db, [event(said_to(who, f"veiled:{item}"), seq, NOW - DAY)], "")
    answer(db, seq, who, text)


@pytest.mark.parametrize("link", ["ties", "room", "named_together", "told_about", "named_in_messages",
                                  "told_named", "unknown_name"])
async def test_every_kind_of_link_closes(link):
    db = alices_life()
    frame, names = Hears(CHLOE), dict(NAMES)
    if link == "ties":
        frame = Hears(CHLOE, ties={CHLOE: (ALICE,)})
    elif link == "room":
        thread(db, 20, CHLOE, "coucou tout le monde", room="soirée")
        thread(db, 21, ALICE, "salut !", room="soirée")
    elif link == "named_together":
        db.put(mc.REMEMBERED.draft(text=Content.of("Chloé et Alice ont dîné ensemble"), about=(ALICE, CHLOE),
                                   sensitivity=1), 30, NOW - DAY)
    elif link == "told_about":
        db.put(mc.BELIEVED.draft(text=Content.of("Chloé dit qu'Alice adore le ski"), about=(ALICE,),
                                 told_by=(CHLOE,), sensitivity=1), 31, NOW - DAY)
    elif link == "named_in_messages":
        thread(db, 22, CHLOE, "au fait, tu connais Alice ?")
    elif link == "told_named":
        db.put(mc.REMEMBERED.draft(text=Content.of("Alice aime le café"), about=(ALICE,), sensitivity=1), 9,
               NOW - DAY)
        Told().apply(db, [event(said_to(CHLOE, "memory:9"), 40, NOW - DAY)], "")
    elif link == "unknown_name":
        NAMES.pop(ALICE)
    try:
        assert links_of(frame, db, CHLOE, ALICE, {}) is True
        ask(db, CHLOE)
        assert await told_to(db, frame) == []
    finally:
        NAMES.clear()
        NAMES.update(names)
    assert links_of(Hears(CHLOE), alices_life(), CHLOE, ALICE, {}) is False  # sans lien : rien ne ferme


def relate(db, subject: str, other: str, kind: str = "friend", status: str = "active") -> None:
    """Une arête du graphe social (``social_relations``), telle que la relecture l'aurait rangée."""
    upsert(db, relations_table(), {"subject": subject, "key": f"{other}|{kind}|{subject}", "other": other, "item": 1,
                                   "payload": json.dumps({"other": other, "kind": kind, "status": status})},
           keys=["subject", "key"])


async def test_a_friend_in_common_closes_at_the_second_degree():
    """Zoé a nommé Alice et Chloé comme amies : Chloé pourrait reconnaître « une amie qui vient de perdre son
    travail ». Au second degré, ça ferme ; au premier seulement, non. Une relation finie ou hostile entre elles ferme
    dès le premier : un lien qui ferme n'a pas à être prouvé (ADR 0092)."""
    db = alices_life()
    relate(db, "user_7", ALICE)
    relate(db, "user_7", CHLOE)
    assert links_of(Hears(CHLOE), db, CHLOE, ALICE, {}) is True
    assert links_of(Hears(CHLOE), db, CHLOE, ALICE, {}, depth=1) is False
    ask(db, CHLOE)
    assert await told_to(db, Hears(CHLOE)) == []
    db = alices_life()
    relate(db, CHLOE, ALICE, kind="hostile", status="ended")
    assert links_of(Hears(CHLOE), db, CHLOE, ALICE, {}, depth=1) is True


async def test_a_mention_that_points_at_the_listener_is_a_link():
    """Sonde réelle du 2026-10-11 : Alice a parlé de « Bob, mon collègue » — une mention que l'identité présume être
    Bob, jamais reliée. Bob reconnaîtrait sa collègue dans « une amie a été licenciée avec toute son équipe » : la
    mention compte pour lui, le récit sans nom se ferme."""
    db = alices_life()
    bob = "name:x:bob"
    db.put(mc.BELIEVED.draft(text=Content.of("Bob est un collègue d'Alice"), about=(ALICE, bob), told_by=(ALICE,),
                             sensitivity=1), 32, NOW - DAY)
    assert links_of(Hears(BOB), db, BOB, ALICE, {}) is False  # sans la présomption : rien ne les relie
    frame = Hears(BOB, presumed={bob: BOB})
    assert links_of(frame, db, BOB, ALICE, {}) is True
    ask(db, BOB)
    assert await told_to(db, frame) == []
    db = alices_life()
    relate(db, ALICE, bob, kind="colleague", status="uncertain")
    assert links_of(Hears(BOB, presumed={bob: BOB}), db, BOB, ALICE, {}, depth=1) is True  # l'arête du graphe aussi


async def test_a_name_she_does_not_know_is_a_detail_of_the_story():
    """Sonde réelle du 2026-10-11 : « Alice et Paul se sont séparés » concerne Alice — Paul, que Mika ne connaît pas,
    n'est qu'un détail de l'histoire (ADR 0058) que la version sans nom tait. Elle se raconte ; le bloc tait aussi
    « Paul ». Paul présumé être quelqu'un de connu, ou écrit par qui écoute : ça ferme."""
    paul = "name:x:paul"
    split = "une amie vient de se séparer de son compagnon"

    def life():
        db = store()
        db.put(mc.REMEMBERED.draft(text=Content.of("Alice et Paul se sont séparés", level=2), sensitivity=2,
                                   importance=0.7, veiled=Content.of(split, level=2), about=(ALICE, paul),
                                   told_by=(ALICE,), heard_by=(ALICE,)), 5, NOW - DAY)
        return db

    db = life()
    ask(db, INES)
    assert await told_to(db, Hears(INES)) == [split]
    body = _veiled(MemoryState(), Hears(INES), {"recall": await _recall(MemoryState(), Hears(INES),
                                                                         {"store": db, "vectors": None})})
    assert set(body.veils) == {"Alice Durand", "Alice", "paul"}
    assert await told_to(db, Hears(INES, presumed={paul: BOB})) == []  # Paul, c'est peut-être Bob : une personne
    db = life()
    thread(db, 3, INES, "tu connais Paul ? le grand brun")
    ask(db, INES)
    assert await told_to(db, Hears(INES)) == []  # elle a parlé de Paul : elle reconnaîtrait l'histoire


async def test_the_same_story_is_told_once():
    """Sonde réelle du 2026-10-11 : la rupture était rangée deux fois (un souvenir, une croyance), chacune avec sa
    version sans nom. Elle ne la raconte qu'une fois, et le budget laisse passer le licenciement."""
    db = alices_life()
    db.put(mc.BELIEVED.draft(text=Content.of("Alice et Paul ont rompu", level=3), sensitivity=3, importance=0.75,
                             veiled=Content.of("une amie et son compagnon se sont séparés récemment", level=3),
                             about=(ALICE,), told_by=(ALICE,), heard_by=(ALICE,)), 9, NOW - DAY)
    ask(db, INES)
    told = await told_to(db, Hears(INES))
    assert len(told) == 2 and LAYOFF in told


def test_her_name_is_found_anywhere_in_what_they_wrote():
    """Le prénom d'Alice dans le tout premier message de Chloé, sous trois mille autres : c'est un lien. Les graphies
    qu'un ``LIKE`` ne replie pas (« ALICE », « Inès », « INÈS », « ines ») aussi ; un mot qui contient le prénom, non."""
    db = alices_life()
    thread(db, 1, CHLOE, "tu connais ALICE ?")
    for n in range(3000):
        thread(db, 100 + n, CHLOE, f"message banal numéro {n}")
    assert links_of(Hears(CHLOE), db, CHLOE, ALICE, {}) is True
    for said in ("je croise Inès demain", "INÈS est là", "ines m'a écrit"):
        db = alices_life()
        thread(db, 1, CHLOE, said)
        assert links_of(Hears(CHLOE), db, CHLOE, INES, {}) is True, said
    db = alices_life()
    thread(db, 1, CHLOE, "les inestimables, quel film")
    assert links_of(Hears(CHLOE), db, CHLOE, INES, {}) is False


def test_a_link_that_cannot_be_read_closes():
    class Broken:
        def query_mind(self, *_a, **_k):
            raise RuntimeError("base verrouillée")

    assert links_of(Hears(CHLOE), Broken(), CHLOE, ALICE, {}) is None
    assert not retellable(admitted=False, veiled=LAYOFF, persons=(ALICE,), sensitivity=2, level=2, listener=CHLOE,
                          linked=None).ok


# ── jamais ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("change,why", [
    ({"secret": True}, "secret"), ({"lie": True}, "mensonge"), ({"between_us": True}, "entre-eux"),
    ({"derived": True}, "derive"), ({"claim": False}, "pas-un-fait"), ({"persons": ("name:x:alice",)}, "mention"),
    ({"persons": (ALICE, BOB)}, "plusieurs-personnes"), ({"listener": ALICE}, "concerne-qui-ecoute"),
    ({"told_by": (CHLOE,)}, "concerne-qui-ecoute"), ({"heard_by": (CHLOE,)}, "concerne-qui-ecoute"),
    ({"owners": (ALICE,)}, "proprietaire"), ({"importance": 0.95}, "marquant"), ({"sensitivity": 3}, "trop-sensible"),
    ({"linked": True}, "lien"), ({"admitted": True}, "deja-dicible"), ({"veiled": ""}, "pas-de-version-sans-nom"),
])
def test_never(change, why):
    base = dict(admitted=False, veiled=LAYOFF, persons=(ALICE,), sensitivity=2, level=2, listener=CHLOE,
                linked=False)
    assert retellable(**base).ok
    assert retellable(**{**base, **change}).why == why


def test_a_veiled_version_that_names_someone_is_dropped():
    people = People.of((Speaker("P1", ALICE, "Alice"),), {}, "Mika", scope="private:user_2")
    assert veiled_of("  quelqu'un que je connais cherche du travail ", people) == \
        "quelqu'un que je connais cherche du travail"
    assert veiled_of("Alice cherche du travail", people) is None
    assert veiled_of("quelqu'un que je connais s'est cassé le poignet le 10 octobre", people) is None  # une date
    assert veiled_of("quelqu'un que je connais a déménagé en 2025", people) is None
    assert veiled_of("quelqu'un que je connais est plâtré pour 6 semaines", people)  # une durée ne situe personne
    assert veiled_of("x" * 241, people) is None
    # ce qui se reconnaît (ADR 0092) : un mois, un jour, un nom propre, un sigle, un nom de l'original même en minuscules
    original = "Alice a été licenciée de chez Ubisoft"
    assert veiled_refusal("quelqu'un que je connais reprend des études en janvier", people) == "datee"
    assert veiled_refusal("quelqu'un que je connais passe son permis jeudi", people) == "datee"
    assert veiled_refusal("une amie part vivre en Italie", people) == "nom-propre"
    assert veiled_refusal("quelqu'un que je connais a signé un CDI", people) == "nom-propre"
    assert veiled_refusal("quelqu'un que je connais a perdu son poste chez ubisoft", people, original) == \
        "reprend-un-nom"
    assert veiled_refusal("Karim a perdu son boulot", people, "Karim a perdu son boulot") == "reprend-un-nom"
    assert veiled_refusal(LAYOFF, people, original) == ""
    assert veiled_refusal("Une amie part vivre à l'étranger. Elle est contente.", people, "Alice part en Italie") == ""


# ── une fois raconté ───────────────────────────────────────────────────────


async def test_once_told_it_is_kept_without_a_name_and_counted():
    db = alices_life()
    shown_and_said(db, 50, CHLOE, 5, "Oh tu sais, quelqu'un que je connais vient de perdre son travail, c'est dur.")
    assert db.query(f"SELECT item, handle, veiled FROM {mc.TOLD_TABLE}") == [(5, CHLOE, 1)]
    ask(db, CHLOE)
    recall = await _recall(MemoryState(), Hears(CHLOE), {"store": db, "vectors": None})
    assert [(v.item, v.kept) for v in recall.veiled] == [(5, True)]  # pas une nouvelle : elle le garde sans nom
    kept = _veiled(MemoryState(), Hears(CHLOE), {"recall": recall}).content
    assert "Garde-le sans nom" in kept and "de ta vie à toi, pas de la sienne" in kept  # pas « ton amie » (sonde)
    shown_and_said(db, 51, INES, 5, "quelqu'un que je connais vient de perdre son travail")
    ask(db, INES)
    budget = Hears(INES)
    budget.env = NS(tz_of=FRAME.env.tz_of, params_of=lambda *_: MemoryParams(veiled_per_person=1))
    recall = await _recall(MemoryState(), budget, {"store": db, "vectors": None})
    assert [(v.item, v.kept) for v in recall.veiled] == [(5, True)]  # déjà une sur Alice à Inès : pas la rupture
    recall = await _recall(MemoryState(), Hears(INES), {"store": db, "vectors": None})
    assert [(v.item, v.kept) for v in recall.veiled] == [(6, False), (5, True)]  # deux par personne : la rupture
    Told().apply(db, [event(said_to(CHLOE, "memory:5"), 52, NOW - DAY)], "")
    Told().apply(db, [event(said_to(CHLOE, "veiled:5"), 53, NOW - DAY)], "")
    assert db.query(f"SELECT veiled FROM {mc.TOLD_TABLE} WHERE item=5 AND handle=?", (CHLOE,)) == [(0,)]  # nommé : nommé


async def test_shown_is_not_told_only_what_she_said_counts():
    """Son prompt lui montrait le licenciement sans nom ; elle a parlé d'autre chose. Ce n'est pas « raconté » : ni
    gardé sans nom (« tu le lui as déjà dit » serait faux), ni dans le budget. Qu'elle le dise une fois, c'est raconté
    — et une autre réponse qui n'en dit rien ne le défait pas."""
    db = alices_life()
    shown_and_said(db, 50, CHLOE, 5, "Ah cool ! Et toi, ta semaine, ça a donné quoi ?")
    ask(db, CHLOE)
    recall = await _recall(MemoryState(), Hears(CHLOE), {"store": db, "vectors": None})
    assert [(v.item, v.kept) for v in recall.veiled] == [(5, False)]  # toujours une nouvelle qu'elle peut raconter
    shown_and_said(db, 60, CHLOE, 5, "Bof, quelqu'un que je connais n'a plus de travail, ça m'a secouée.")
    shown_and_said(db, 70, CHLOE, 5, "Bonne soirée !")
    recall = await _recall(MemoryState(), Hears(CHLOE), {"store": db, "vectors": None})
    assert [(v.item, v.kept) for v in recall.veiled] == [(5, True)]
    strict = Hears(CHLOE)
    strict.env = NS(tz_of=FRAME.env.tz_of, params_of=lambda *_: MemoryParams(veiled_said_share=1.0))
    recall = await _recall(MemoryState(), strict, {"store": db, "vectors": None})
    assert [(v.item, v.kept) for v in recall.veiled] == [(5, False)]  # « perdre » manquait : la moitié seulement


def test_what_counts_as_said():
    assert echoed("quelqu'un de mon entourage a perdu son boulot, enfin son travail", LAYOFF, 0.5)
    assert not echoed("quelqu'un que je connais, tu sais", LAYOFF, 0.5)  # les mots qui le tournent ne comptent pas
    assert echoed("", "quelqu'un que je connais", 0.5)  # rien à départager : compté, ce qui ferme le moins mal


async def test_what_was_told_without_a_name_stays_under_the_verdict():
    """Raconté sans nom à Chloé : il lui revient « garde-le sans nom » — tant qu'il pourrait encore se raconter. Devenu
    secret, ou Chloé liée à Alice depuis, il ne revient plus."""
    db = alices_life()
    shown_and_said(db, 50, CHLOE, 5, "quelqu'un que je connais vient de perdre son travail")
    ask(db, CHLOE)
    assert [(v.item, v.kept) for v in (await _recall(MemoryState(), Hears(CHLOE), {"store": db, "vectors": None})
                                       ).veiled] == [(5, True)]
    assert await told_to(db, Hears(CHLOE, ties={CHLOE: (ALICE,)})) == []  # un lien depuis
    db.execute(f"UPDATE {mc.ITEMS_TABLE} SET secret=1 WHERE id=5")
    assert await told_to(db, Hears(CHLOE)) == []  # devenu secret


def test_a_veiled_story_never_proves_an_identity():
    from mika.faculties.identity.faculty import IdentityState
    from mika.faculties.identity.reading import _candidates

    db = alices_life()
    db.execute("INSERT INTO thread(id,at,role,person,text,room) VALUES(?,?,?,?,?,?)",
               (1, NOW - DAY, "user", ALICE, "j'ai été licenciée", None))
    db.execute(f"UPDATE {mc.ITEMS_TABLE} SET sources='[1]' WHERE id=5")
    assert 5 in {c.id for c in _candidates(db, IdentityState(), ALICE)}
    Told().apply(db, [event(said_to(CHLOE, "veiled:5"), 50, NOW - DAY)], "")
    assert 5 not in {c.id for c in _candidates(db, IdentityState(), ALICE)}  # Chloé pourrait le redire


# ── jamais à côté du nom ───────────────────────────────────────────────────


def test_the_composer_drops_a_veiled_block_next_to_the_name():
    from mika.kernel.faculty import SectionSpec, Zone

    spec = SectionSpec("memory", "veiled", Zone.VOLATILE, frozenset({"REPLY"}), lambda *_: None, (), (), 28, 0,
                       frozenset(), frozenset(), "SANS NOM", False)
    body = SectionBody(f"- {LAYOFF}", level=2, veils=("Alice Durand", "Alice"))
    common = dict(kind="REPLY", audience_level=1, muted_tags=frozenset(), budget=Budget(max_tokens=24_000),
                  veiled_level=2)
    kept, _ = Composer().compose([(spec, body)], message="tu as des nouvelles ?", **common)
    assert LAYOFF in kept.system_volatile + "".join(t.content for t in kept.history) + str(kept.chat_messages())
    named, trace = Composer().compose([(spec, body)], message="tu as des nouvelles d'Alice ?", **common)
    assert LAYOFF not in str(named.chat_messages())
    closed, _ = Composer().compose([(spec, body)], message="tu as des nouvelles ?", **{**common, "veiled_level": 1})
    assert LAYOFF not in str(closed.chat_messages())  # au-dessus de son niveau sans nom : rien
    assert unveiled(("Inès",), "ines est passée") and not unveiled(("Alice",), "Alicia est passée")


# ── la relecture n'en apprend rien, l'oubli n'en laisse rien ───────────────


def test_the_reread_learns_nothing_from_a_veiled_reply():
    line = Line(10001, NOW, "Mika", f"tu sais, {LAYOFF}", veiled=True)
    shown = render(Conversation("private:user_6", (Speaker("P1", CHLOE, "Chloé"),), (line,)), now=FRAME.local(),
                   beliefs=[], promises=[])
    assert LAYOFF not in shown and "rien à en retenir" in shown


async def test_a_note_about_herself_from_a_veiled_reply_is_not_kept():
    from tests.unit.test_knowledge_coherence import Store, drafts

    veiled = Line(10001, NOW, "Mika", "moi j'ai une amie qui vient de perdre son travail", veiled=True)
    ex = Extraction(croyances=[XCroyance(texte="J'ai une amie qui a perdu son travail", genre="fait",
                                         sur_elle=True, messages=[10001])])
    out = await drafts(Store(), ex, (Line(10000, NOW, "Chloé", "quoi de neuf ?", CHLOE), veiled),
                       speakers=(Speaker("P1", CHLOE, "Chloé"),), key="private:user_6")
    assert [d for d in out if d.type.name == mc.BELIEVED.name] == []
    honest = await drafts(Store(), ex, (Line(10000, NOW, "Chloé", "quoi de neuf ?", CHLOE), mika_says("…")),
                          speakers=(Speaker("P1", CHLOE, "Chloé"),), key="private:user_6")
    assert [d.data.about_self for d in honest if d.type.name == mc.BELIEVED.name] == [True]  # dit sans voile : retenu


def test_forgetting_her_leaves_nothing_veiled():
    db = alices_life()
    Items().forget(db, ALICE, "")
    assert db.query(f"SELECT id FROM {mc.ITEMS_TABLE} WHERE veiled != ''") == [(8,)]  # celui de Nora reste
    assert mc.REMEMBERED.content_fields >= {"veiled"} and "about" in mc.BELIEVED.subject_fields


async def test_the_reread_writes_the_veiled_version_only_for_what_may_have_one():
    from tests.unit.test_knowledge_coherence import Store, alice_says, drafts

    said = alice_says("je me suis fait virer de chez Ubisoft, je cherche du boulot")
    fact = XCroyance(texte="Alice a été licenciée de chez Ubisoft", personnes=["P1"], sensibilite="personnel",
                     sans_nom="quelqu'un que je connais vient de perdre son travail", messages=[10000])
    out = await drafts(Store(), Extraction(croyances=[fact]), (said,))
    (believed,) = [d.data for d in out if d.type.name == mc.BELIEVED.name]
    assert believed.veiled.text == LAYOFF
    hush = fact.model_copy(update={"secret": True})
    (secret,) = [d.data for d in await drafts(Store(), Extraction(croyances=[hush]), (said,))
                 if d.type.name == mc.BELIEVED.name]
    assert secret.veiled is None  # un secret n'a pas de version sans nom
    named = fact.model_copy(update={"sans_nom": "Alice vient de perdre son travail"})
    (kept,) = [d.data for d in await drafts(Store(), Extraction(croyances=[named]), (said,))
               if d.type.name == mc.BELIEVED.name]
    assert kept.veiled is None  # la relecture a laissé le nom : le filet l'écarte
    brand = fact.model_copy(update={"sans_nom": "quelqu'un que je connais a perdu son poste chez ubisoft"})
    (shop,) = [d.data for d in await drafts(Store(), Extraction(croyances=[brand]), (said,))
               if d.type.name == mc.BELIEVED.name]
    assert shop.veiled is None  # l'employeur de l'original, même en minuscules (ADR 0092)
    opinion = fact.model_copy(update={"genre": "avis", "texte": "Alice trouve son ancien chef injuste"})
    (avis,) = [d.data for d in await drafts(Store(), Extraction(croyances=[opinion]), (said,))
               if d.type.name == mc.BELIEVED.name]
    assert avis.veiled is None  # un avis n'est pas un simple fait


def test_a_date_in_common_does_not_hint_at_a_secret():
    """Sonde réelle du 2026-10-11 : « sa mère hospitalisée, le dimanche 11 octobre 2026 » devenait secret parce qu'un
    secret de la même semaine disait aussi « octobre 2026 » — et rien de ce qu'Alice confiait ensuite ne se racontait
    plus, même sans nom. Une date en commun ne fait rien deviner ; un sujet en commun, si."""
    from mika.faculties.memory.extraction import echoes

    secret = ["Alice m'a dit qu'elle s'est séparée de Paul la semaine du 5 octobre 2026"]
    assert not echoes("Alice m'a dit, le dimanche 11 octobre 2026, que sa mère a été hospitalisée", secret, {"alice"})
    assert echoes("Alice s'est séparée de Paul, elle a du mal", secret, {"alice"})


class _NearestFirst:
    """Un index où la recherche ordinaire est remplie par ce qui peut se dire (plus proche de la question) : seul
    ce qu'on cherche à part, parmi ce qui a une version sans nom (``keys``), trouve le licenciement d'Alice."""

    def __init__(self):
        self.asked: list[object] = []

    async def search(self, query, k, *, kinds=None, keys=None, persons=None):
        self.asked.append(keys)
        sims = {5: 0.72, 100: 0.9, 101: 0.88}
        pool = {100: 0.9, 101: 0.88} if keys is None else {i: s for i, s in sims.items() if i in keys}
        return sorted(pool.items(), key=lambda kv: -kv[1])[:k]


async def test_what_she_could_tell_without_a_name_is_searched_apart():
    """Ce qu'elle pourrait raconter sans nommer personne se cherche à part (ADR 0099) : une question proche
    (« quelqu'un cherche du travail ? ») le trouve même quand ce qui peut se dire ici, plus proche, remplit la
    recherche ordinaire."""
    db = alices_life()
    ask(db, INES, "tu connais quelqu'un qui cherche du travail en ce moment ?")
    vectors = _NearestFirst()
    recall = await _recall(MemoryState(), Hears(INES), {"store": db, "vectors": vectors})
    assert LAYOFF in [v.text for v in recall.veiled]
    assert any(keys for keys in vectors.asked)  # la recherche à part a bien eu lieu
    ask(db, CHLOE, "tu connais quelqu'un qui cherche du travail en ce moment ?", room="salon")
    salon = _NearestFirst()
    await _recall(MemoryState(), Hears(CHLOE, public=True), {"store": db, "vectors": salon})
    assert not any(keys for keys in salon.asked)  # rien à raconter dans un salon : pas de recherche à part
