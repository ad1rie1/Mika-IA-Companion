"""Les fils des moments (ADR 0079) : un moment de la vie de quelqu'un garde son identité quand il est reporté, quand
la personne le redit elle-même, quand il revient chaque année, et quand une situation finie recommence.

Avant, chaque nouvelle notation était un autre moment (son ``seq``) : ce qu'elle en avait dit (« bonne chance pour
demain ») était rangé sous l'ancien numéro — redit par la personne le même soir, l'encouragement repartait ; un
suivi jugé sur l'ancien numéro, remplacé entre-temps, se perdait ; « il est de nouveau malade » ouvrait une situation
sans rien savoir de la précédente. Chaque cible échoue sur l'arbre d'avant ; les contrôles montrent qu'un moment
vraiment déplacé garde son propre encouragement.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.memory.archive import recall_life
from mika.faculties.memory.consolidation import Consolidate
from mika.faculties.memory.extraction import Conversation, Extraction, People, XEvenement, render
from mika.faculties.memory.faculty import (
    MemoryParams,
    MemoryState,
    _followed,
    _life_recalled,
    _noted,
    moment_thread,
)
from mika.faculties.memory.life import Follow, _told_about
from mika.faculties.needs import NeedsParams
from mika.faculties.others.faculty import _cheer
from mika.kernel.clock import DAY, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, said
from tests.unit.test_knowledge_coherence import ALICE, FRAME, Frame, Store, alice_says, drafts

MONDAY = at_paris(2026, 10, 5, 8, 45)
SAM = "ext_1"
CX = NS(params=None, facts=NS(get=lambda _ref: None))


def _event(draft, seq, at):
    return NS(type=draft.type, data=draft.data, seq=seq, at=at)


def _note(text, when, person="user_2", **kw):
    return memory_c.EVENT_NOTED.draft(text=Content(ref=f"{text}.ref", text=text), when=when, about=(person,),
                                      told_by=(person,), heard_by=(person,), **kw)


# ── Le fil d'un moment ──────────────────────────────────────────────────────


def test_a_rescheduled_moment_keeps_its_thread():
    s = _noted(MemoryState(), _event(_note("son entretien chez Ubisoft", 30 * DAY), 1, DAY), CX)
    s = _noted(s, _event(_note("son entretien chez Ubisoft", 33 * DAY, replaces=1), 7, 2 * DAY), CX)
    s = _noted(s, _event(_note("son entretien chez Ubisoft", 34 * DAY, replaces=7), 9, 3 * DAY), CX)
    assert list(s.events) == [9] and s.events[9].thread == 1  # reporté deux fois : le même moment
    assert moment_thread(s, None, 7) == 1 and moment_thread(s, None, 9) == 1 and moment_thread(s, None, 4) == 4


def test_a_follow_on_a_replaced_moment_lands_on_its_head():
    """« Alors, cet entretien ? » jugé pendant que la personne le redisait elle-même (le même jour) : le suivi
    tombe sur le moment tel qu'il est noté maintenant, pas dans le vide."""
    s = _noted(MemoryState(), _event(_note("son entretien", 30 * DAY), 1, DAY), CX)
    s = _noted(s, _event(_note("son entretien", 30 * DAY, replaces=1), 5, 2 * DAY), CX)
    s = _followed(s, _event(memory_c.MOMENT_FOLLOWED.draft(event=1, thread=1, occurrence=30 * DAY), 6,
                            31 * DAY), CX)
    assert s.events[5].followed_at == 31 * DAY
    # un suivi d'une autre date (le moment a été déplacé depuis) ne compte pas pour la nouvelle
    s = _noted(s, _event(_note("son entretien", 40 * DAY, replaces=5), 8, 32 * DAY), CX)
    s = _followed(s, _event(memory_c.MOMENT_FOLLOWED.draft(event=1, thread=1, occurrence=30 * DAY), 9,
                            33 * DAY), CX)
    assert s.events[8].followed_at == 0


# ── Une situation qui revient ───────────────────────────────────────────────


async def test_a_situation_coming_back_reopens_its_thread():
    db = Store()
    db.put(memory_c.EVENT_NOTED.draft(text=Content.of("Le chat Moustache est malade"), when=FRAME.now - 20 * DAY,
                                      ongoing=True, about=("user_2",), told_by=("user_2",), heard_by=("user_2",)), 1)
    db.put(memory_c.SITUATION_ENDED.draft(event=1), 2, FRAME.now - 10 * DAY)
    ex = _extraction("Le chat Moustache est malade")
    noted = [d for d in await drafts(db, ex, (alice_says("Moustache est de nouveau malade"),))
             if d.type.name == memory_c.EVENT_NOTED.name]
    assert len(noted) == 1 and noted[0].data.ongoing and noted[0].data.replaces is None
    assert noted[0].data.recurs == 1  # la même situation, de nouveau
    db.conn.close()


async def test_a_situation_ended_long_ago_starts_a_new_thread():
    db = Store()
    db.put(memory_c.EVENT_NOTED.draft(text=Content.of("Le chat Moustache est malade"), when=FRAME.now - 400 * DAY,
                                      ongoing=True, about=("user_2",), told_by=("user_2",), heard_by=("user_2",)), 1)
    db.put(memory_c.SITUATION_ENDED.draft(event=1), 2, FRAME.now - 300 * DAY)
    noted = [d for d in await drafts(db, _extraction("Le chat Moustache est malade"),
                                     (alice_says("Moustache est malade"),))
             if d.type.name == memory_c.EVENT_NOTED.name]
    assert len(noted) == 1 and noted[0].data.recurs is None  # trop loin : une autre histoire
    db.conn.close()


async def test_a_relapse_the_reread_designates_reopens_its_thread():
    """« Il recommence à plus manger » : la relecture voit les situations finies depuis peu et désigne celle qui
    revient, même dite avec d'autres mots (sonde réelle du 2026-10-09 : sans elles, la rechute du chat de Carol n'était
    qu'un souvenir, et Mika ne suivait plus rien). Une situation finie il y a longtemps ne se montre pas."""
    db = Store()
    for seq, text, began, ended in ((1, "Moustache, le chat d'Alice, est malade", 3, 1),
                                    (3, "Alice cherche un appartement", 400, 300)):
        db.put(memory_c.EVENT_NOTED.draft(text=Content.of(text), when=FRAME.now - began * DAY, ongoing=True,
                                          about=("user_2",), told_by=("user_2",), heard_by=("user_2",)), seq)
        db.put(memory_c.SITUATION_ENDED.draft(event=seq), seq + 1, FRAME.now - ended * DAY)
    conv = Conversation("private:user_2", ALICE, (alice_says("oh non, il recommence à plus rien avaler"),))
    ended, gone = Consolidate._ended_situations(FRAME, db, MemoryState(), conv, MemoryParams(), {"user_2": "Alice"})
    assert [i for i, _w, _t in ended] == [1]  # pas celle finie il y a dix mois
    assert "[#1] (Alice) du " in render(conv, now=FRAME.local(), beliefs=[], promises=[], ended=ended)
    ex = Extraction(evenements=[XEvenement(texte="Rechute de son matou", quand="2026-10-08", en_cours=True,
                                           personnes=["P1"], messages=[10000], remplace=1)])
    out = await Consolidate()._drafts(ex, FRAME, MemoryState(), db, conv, People.of(ALICE, {}, "Mika", scope=conv.key),
                                      [], [], None, MemoryParams(), "audit", moments=gone)
    (noted,) = [d for d in out if d.type.name == memory_c.EVENT_NOTED.name]
    assert noted.data.recurs == 1 and noted.data.ongoing and noted.data.replaces is None  # la même, de nouveau
    db.conn.close()


def _extraction(text):
    return Extraction(evenements=[XEvenement(texte=text, quand="2026-10-08", en_cours=True, personnes=["P1"],
                                             messages=[10000])])


def test_a_recurrence_is_said_as_such():
    s = _noted(MemoryState(), _event(_note("son chat Moustache est malade", 10 * DAY, ongoing=True), 1, 10 * DAY),
               CX)
    s = _noted(s, _event(_note("son chat Moustache est malade", 40 * DAY, ongoing=True, recurs=1), 4, 40 * DAY),
               CX)
    assert s.events[4].thread == 1 and s.events[4].recurs == 1 and 1 not in s.events


# ── Ce qu'elle en a dit : une fois par fil (de bout en bout) ────────────────


class Script:
    def __init__(self):
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role == "extract":
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", {}),), stop="tool_use")
        if req.role in ("profile", "compact"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens, et si je lui écrivais")
        if req.role in ("narrative", "journal", "dream"):
            return LLMResponse("Une journée.")
        if req.role == "initiative":
            return LLMResponse("Bonne chance pour demain ! [EMOTION:happy:0.5]")
        return LLMResponse("d'accord [EMOTION:happy:0.4]")


async def _until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


async def _append(kernel, draft):
    commit = await kernel.mind.append([draft], emitter="memory", correlation=f"genese:{draft.data.when}",
                                      origin=Origin.GENESIS)
    return commit.seqs[-1]


def _cheers(kernel):
    return [kernel.mind.decode(e) for e in kernel.mind.store.read() if e.type == rt.EPISODE_STARTED.name
            and others_c.CHEER in kernel.mind.decode(e).data.reason.split(",")]


def _run(tmp_path, scenario):
    kernel, clock, _llm, _out = build(tmp_path, Script(), start=MONDAY)

    async def main():
        await boot(kernel)
        await kernel.set_params("needs", NeedsParams(social_floor=1.0, expression_floor=1.0))
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def _meet(kernel):
    await befriend(kernel, SAM, social_c.FRIEND)
    for text in ("salut !", "bonne soirée !"):
        p = await kernel.perceive(said(SAM, text, channel="external", display_name="Sam"))
        if p.reply is not None:
            await p.reply
        await asyncio.sleep(60)


def _offered(kernel):
    frame = kernel.mind.frame()
    return [c for c in _cheer(frame.state("others"), frame) if c.target and c.args.get("subject")]


def test_a_first_hand_restatement_does_not_cheer_twice(tmp_path):
    """Elle l'a encouragé la veille au soir ; il redit lui-même son entretien du lendemain, à la même heure : c'est
    le même moment — pas un second « bonne chance »."""
    thursday = at_paris(2026, 10, 8, 14, 0)

    async def scenario(kernel):
        await _meet(kernel)
        first = await _append(kernel, _note("son entretien chez Ubisoft", thursday, SAM, importance=0.7))
        await _until(kernel, at_paris(2026, 10, 7, 21, 30))
        cheered = len(_cheers(kernel))
        await _append(kernel, _note("son entretien chez Ubisoft", thursday, SAM, importance=0.7, replaces=first))
        return cheered, _offered(kernel)

    cheered, offered = _run(tmp_path, scenario)
    assert cheered == 1  # la veille au soir, une fois
    assert offered == []  # redit le même soir : déjà encouragé


def test_a_rescheduled_moment_gets_one_cheer_for_its_new_date(tmp_path):
    """Contrôle : déplacé à lundi, le même moment a droit à son encouragement de la nouvelle veille."""
    thursday, monday = at_paris(2026, 10, 8, 14, 0), at_paris(2026, 10, 12, 14, 0)

    async def scenario(kernel):
        await _meet(kernel)
        first = await _append(kernel, _note("son entretien chez Ubisoft", thursday, SAM, importance=0.7))
        await _until(kernel, at_paris(2026, 10, 7, 21, 30))
        await _append(kernel, _note("son entretien chez Ubisoft", monday, SAM, importance=0.7, replaces=first))
        await _until(kernel, at_paris(2026, 10, 11, 23, 0))
        return [c.at for c in _cheers(kernel)]

    cheers = _run(tmp_path, scenario)
    assert len(cheers) == 2  # la veille de jeudi, puis la veille de lundi
    assert at_paris(2026, 10, 11, 0, 0) <= cheers[1] <= at_paris(2026, 10, 11, 23, 0)


def test_the_archive_keeps_the_thread():
    db = Store()
    db.put(_note("son entretien", FRAME.now + DAY), 1)
    db.put(_note("son entretien", FRAME.now + 3 * DAY, replaces=1), 5)
    (raw,) = db.query(f"SELECT payload FROM {memory_c.LIFE_TABLE}")
    assert '"thread": 1' in raw[0]
    db.conn.close()


# ── Ce que la relecture de sa vie recharge ; une adresse reliée depuis (audit du 2026-10-12) ─────────────────


def test_her_life_reloaded_at_a_message_is_only_what_she_keeps_in_mind():
    """À chaque message, sa vie se relisait dans l'archive : tous les moments de la personne, même passés depuis
    longtemps. Le moment noté suivant (de n'importe qui) les chassait de la tranche, le message suivant les y remettait
    — recopiés dans le journal à chaque fois. Seul revient ce que la tranche garde : à venir, en cours, passé depuis
    peu ; et ce qui est revenu y reste."""
    db = Store()
    db.put(_note("son déménagement", FRAME.now - 20 * DAY), 1, FRAME.now - 25 * DAY)
    db.put(_note("son entretien chez Ubisoft", FRAME.now + 2 * DAY), 2, FRAME.now - DAY)
    db.put(_note("son chat Moustache est malade", FRAME.now - 20 * DAY, ongoing=True), 3, FRAME.now - 20 * DAY)
    message = NS(seq=10, at=FRAME.now, data=NS(handle="user_2"))
    (reloaded,) = recall_life(MemoryState(), FRAME, message, {"store": db})
    assert sorted(item.id for item in reloaded.data.items) == [2, 3]  # le déménagement d'il y a vingt jours, non
    s = _life_recalled(MemoryState(), _event(reloaded, 11, FRAME.now), CX)
    s = _noted(s, _event(_note("son dîner", FRAME.now + 3 * DAY, person="user_3"), 12, FRAME.now), CX)
    assert {2, 3} <= set(s.events)  # le moment suivant n'en chasse rien
    assert recall_life(s, FRAME, message, {"store": db}) == []  # rien ne revient dans le journal au message suivant
    db.conn.close()


WEB = "web_ab12cd"


class _Linked(Frame):
    """Un cadre où l'adresse ``web_…`` a été reliée à Alice depuis qu'un moment y a été noté."""

    def get(self, key):
        if key.name == "identity.person" and key.arg == WEB:
            return "user_2"
        if key.name == "transcript.head":
            return 10001
        return super().get(key)


async def test_a_moment_noted_under_an_address_linked_since_is_taken_up_by_the_person():
    """Un moment noté quand Alice écrivait sans compte (``web_…``) ; l'adresse a été reliée à elle depuis. Quand elle
    raconte comment ça s'est passé, ou que Mika le lui demande, le moment est repris — la relecture comparait la
    personne aux clés notées alors, sans les résoudre, et lui redemandait « alors, cet entretien ? » (audit du
    2026-10-12)."""
    frame = _Linked()
    s = _noted(MemoryState(), _event(_note("son entretien chez Ubisoft", FRAME.now - DAY, person=WEB), 1,
                                     FRAME.now - 3 * DAY), CX)
    texts = NS(content=lambda refs: {r: "son entretien chez Ubisoft" for r in refs})
    told = NS(seq=20, at=FRAME.now, data=NS(handle="user_2", addressed=True,
                                            text=Content(ref="m", text="l'entretien s'est super bien passé !")))
    assert [d.data.event for d in _told_about(s, frame, told, {"store": texts})] == [1]  # elle le raconte
    db = Store()
    db.execute("INSERT INTO thread(id,at,role,person,text,room) VALUES(?,?,?,?,?,?)",
               (10001, FRAME.now, "assistant", "user_2", "alors, cet entretien chez Ubisoft ?", None))
    db.texts["son entretien chez Ubisoft.ref"] = "son entretien chez Ubisoft"
    emitted = []

    async def emit(*drafts, **_kw):
        emitted.extend(drafts)

    await Follow().run(NS(frame=frame, state=s, ports={"store": db}, emit=emit))
    assert [d.data.event for d in emitted] == [1]  # elle le lui demande
    db.conn.close()
