"""Une seule porte (ADR 0078) : ce que les autres facultés tirent de ce qu'elle sait ne se redit pas plus loin que
ce que ses sources permettent.

L'audit du 2026-10-09 a trouvé plusieurs lecteurs de ``memory_items`` hors de la mémoire, chacun avec son filtre, et
autant de fuites : un rêve rendait à Sam le secret que Bob avait confié sur lui ; la révision d'un tel secret devenait
une pensée qu'elle racontait à Sam ; une confidence que Bob lui avait faite, sans personne concernée, entrait dans
le récit qu'elle montre à tout le monde ; une note secrète à elle ouvrait son journal intime à n'importe quel salon ;
une réflexion sur Sam voyait ce que Bob avait dit en secret ; « ce qui n'appartient qu'à vous » montrait à Sam ce
qu'il partageait avec Léa ; une croyance devenue secrète restait une matière d'initiative. Chaque cas ci-dessous
échoue sur l'arbre d'avant ; le contrôle de chacun montre que la porte ne ferme pas ce qui peut se dire.
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from mika.contracts import memory as mc
from mika.contracts import self_ as self_c
from mika.faculties.goals.prompt import life_of
from mika.faculties.memory.projections import Items, Told
from mika.faculties.needs import NeedsState, _belief_changed, _learned_a_belief
from mika.faculties.self import SelfParams, material
from mika.faculties.self.night import journal_ref
from mika.faculties.social.sections import between_us
from mika.kernel.clock import DAY, US
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.frame import Audience
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from mika.vocab.knowledge import knowns
from mika.vocab.lineage import Lineage, admits, requirement
from mika.vocab.privacy import PUBLIC_FLOOR, Sensitivity, private_to
from tests.fixtures.mika import at_paris, boot, build, said

SAM, BOB, LEA = "user_2", "user_3", "user_4"
NOW = 20 * DAY


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        Items().create(self, "")
        Told().create(self, "")
        self.seq = 0

    def execute(self, sql, args=()):
        return self.conn.execute(sql, args)

    def executemany(self, sql, rows):
        return self.conn.executemany(sql, rows)

    def query(self, sql, args=()):
        return self.execute(sql, args).fetchall()

    query_mind = query

    def content(self, refs):
        return {}

    def put(self, draft, at=NOW - DAY) -> int:
        self.seq += 1
        Items().apply(self, [NS(type=draft.type, data=draft.data, seq=self.seq, at=at)], "")
        return self.seq

    def known(self):
        return knowns(self.query(mc.SELECT_KNOWN + " ORDER BY id"), mc.KNOWN_COLUMNS)


DEFAULTS = {"identity.person": "", "identity.presumed": "", "identity.handles": (), "memory.life_events": (),
            "social.closeness": "stranger"}


class Frame:
    """Ce qu'une faculté lit d'un instant : des faits (par défaut : personne n'est relié, rien n'est présumé)."""

    def __init__(self, audience: Audience | None = None, facts: dict | None = None):
        self.audience, self.facts, self.now, self.root, self.episode = audience, facts or {}, NOW, None, None
        self.env = NS(tz_of=lambda _root: ZoneInfo("Europe/Paris"))

    def get(self, ref):
        key = (ref.name, getattr(ref, "arg", None))
        return self.facts[key] if key in self.facts else DEFAULTS.get(ref.name)


def belief(text, about, told_by, *, secret=False, sensitivity=2, between=False):
    return mc.BELIEVED.draft(text=Content.of(text, level=sensitivity), about=about, told_by=told_by,
                             heard_by=told_by, source=told_by[0] if told_by else None, secret=secret,
                             sensitivity=sensitivity, between_us=between)


def souvenir(text, about=(), told_by=(), *, secret=False, sensitivity=1, importance=0.6):
    return mc.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=about, told_by=told_by,
                               heard_by=told_by, secret=secret, sensitivity=sensitivity, importance=importance,
                               emotion="sad")


# ── Ce qu'elle se raconte d'elle-même (montré partout) ──────────────────────


def test_the_story_of_herself_never_carries_a_confidence_told_by_someone():
    db = DB()
    db.put(souvenir("CANARI Bob m'a confié qu'il a peur de perdre son travail", told_by=(BOB,), sensitivity=3,
                    importance=0.9))
    db.put(souvenir("J'ai passé l'après-midi à dessiner", sensitivity=2, importance=0.5))
    told, felt = material(db.known(), Frame(), shown=10)
    texts = [k.text for k in told]
    assert not any("CANARI" in t for t in texts)  # une confidence de Bob, même sans personne concernée
    assert "J'ai passé l'après-midi à dessiner" in texts  # contrôle : sa vie à elle se raconte
    assert felt  # ce qui l'a marquée sans pouvoir se dire reste un ressenti, sans qui ni quoi


# ── Son journal intime ──────────────────────────────────────────────────────


def _journal(lineage):
    return self_c.JournalReading("2026-09-28", "intime", (), "sad", "partageable", lineage)


def test_an_about_less_secret_journal_is_not_read_in_a_room():
    her_secret = Lineage(requirements=(requirement(1, (), int(Sensitivity.PERSONAL), secret=True),))
    room = Audience(persons=(SAM,), public=True, level=int(Sensitivity.ANODYNE))
    assert journal_ref(_journal(her_secret), SAM, room, Frame(room)) == "partageable"
    confidant = Audience(persons=(SAM,), public=False, level=int(Sensitivity.CONFIDENCE),
                         witness_level=int(Sensitivity.CONFIDENCE), private_ok=True)
    # contrôle : en grande confiance, en privé, son journal intime se montre encore
    assert journal_ref(_journal(her_secret), SAM, confidant, Frame(confidant)) == "intime"
    # un journal d'avant la filiation garde l'ancienne règle (il ne parle de personne)
    assert journal_ref(_journal(None), SAM, room, Frame(room)) == "intime"


# ── Ce qu'une réflexion sur Sam a sous les yeux ─────────────────────────────


def test_a_reflection_about_sam_does_not_see_what_bob_told_in_secret():
    db = DB()
    db.put(belief("CANARI Sam va être licencié", (SAM,), (BOB,), secret=True))
    db.put(belief("Sam adore la city pop", (SAM,), (SAM,), sensitivity=1))
    db.put(belief("Sam cherche un appartement à Lyon", (SAM,), (SAM,)))
    seen = [t for t, _sv in life_of(db, Frame(), SAM)]
    assert not any("CANARI" in t for t in seen)
    assert "Sam adore la city pop" in seen and "Sam cherche un appartement à Lyon" in seen  # contrôle


# ── Ce qui n'appartient qu'à elles deux ─────────────────────────────────────


def test_between_us_is_only_what_she_and_the_person_share():
    db = DB()
    mine = db.put(belief("Sam m'appelle Mikachu", (SAM,), (SAM,), sensitivity=1, between=True))
    db.put(belief("CANARI Sam et Léa m'appellent Mimi", (SAM, LEA), (SAM,), sensitivity=1, between=True))
    db.put(belief("CANARI Bob dit que Sam m'appelle Bichette", (SAM,), (BOB,), sensitivity=1, between=True))
    private = Audience(persons=(SAM,), public=False, level=int(Sensitivity.PERSONAL),
                       witness_level=int(Sensitivity.PERSONAL), private_ok=True)
    shown = between_us(db, Frame(private), SAM)
    assert [i for i, _t in shown] == [mine]


# ── Une matière d'initiative ────────────────────────────────────────────────


def _event(draft, seq):
    return NS(type=draft.type, data=draft.data, seq=seq, at=NOW)


def test_needs_forgets_a_told_that_became_secret():
    cx = NS(params=None, facts=NS(get=lambda _ref: None), now=NOW)
    told = mc.BELIEVED.draft(text=Content(ref="7.text", level=2), about=(SAM,), told_by=(SAM,), source=SAM,
                             sensitivity=2)
    s = _learned_a_belief(NeedsState(), _event(told, 7), cx)
    assert [t.item for t in s.told.get(SAM, ())] == [7]  # contrôle : ce qu'il a dit de lui est une matière
    s = _belief_changed(s, _event(mc.REINFORCED.draft(item=7, secret=True), 8), cx)
    assert not s.told.get(SAM)  # « garde-le pour toi » : plus une matière
    secret = mc.BELIEVED.draft(text=Content(ref="9.text", level=2), about=(SAM,), told_by=(SAM,), source=SAM,
                               secret=True)
    assert not _learned_a_belief(NeedsState(), _event(secret, 9), cx).told.get(SAM)
    opinion = mc.BELIEVED.draft(text=Content(ref="10.text"), about=(SAM,), told_by=(SAM,), source=SAM,
                                knowledge_kind="opinion")
    assert not _learned_a_belief(NeedsState(), _event(opinion, 10), cx).told.get(SAM)


# ── Un rêve fait du secret d'un autre (de bout en bout) ─────────────────────


class Script:
    def __init__(self):
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role == "extract":
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", {}),), stop="tool_use")
        if req.role in ("profile", "compact"):
            return LLMResponse("{}")
        if req.role == "journal":
            return LLMResponse("Une journée tranquille.")
        if req.role == "dream":
            return LLMResponse("CANARI-REVE je cours dans un couloir sans fin")
        if req.role in ("murmur", "narrative"):
            return LLMResponse("hmm")
        return LLMResponse("d'accord [EMOTION:happy:0.4]")


async def _until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


def _run(tmp_path, scenario, start=at_paris(2026, 9, 28, 17, 0)):
    script = Script()
    kernel, clock, llm, _out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm


def _replies(llm):
    return [c.system_stable + "\n".join(m.content for m in c.messages) for c in llm.calls if c.role == "reply"]


@pytest.mark.parametrize("told_by,secret,admitted", [((BOB,), True, False), ((SAM,), False, True)])
def test_a_dream_keeps_what_its_sources_allow(tmp_path, told_by, secret, admitted):
    """Elle rêve, la nuit, d'un souvenir sur Sam : le rêve garde ce que sa source permet — le secret que Bob a
    confié ne se raconte pas à Sam (et l'oubli de Bob l'atteint) ; ce que Sam lui a dit lui-même, si."""

    async def scenario(kernel):
        await kernel.set_params("self", SelfParams(dream_chance=1.0))
        await kernel.mind.append([souvenir("Sam a perdu son travail", about=(SAM,), told_by=told_by, secret=secret,
                                           sensitivity=2, importance=0.9)],
                                 emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await _until(kernel, at_paris(2026, 9, 29, 9, 0))
        return [kernel.mind.decode(e) for e in kernel.mind.store.read() if e.type == self_c.DREAMT.name]

    dreams, _llm = _run(tmp_path, scenario)
    assert dreams and all(d.data.lineage is not None for d in dreams)
    for d in dreams:
        assert admits(d.data.lineage, SAM, private_to(SAM)).ok == admitted
        assert (BOB in d.data.about) == secret  # le secret de Bob : l'oubli de Bob atteint le rêve


@pytest.mark.parametrize("told_by,secret,shown", [((BOB,), True, False), ((SAM,), False, True)])
def test_bobs_secret_about_sam_never_reaches_sam_through_a_dream(tmp_path, told_by, secret, shown):
    """Au réveil, un rêve vif revient le matin à qui elle parle : pas à Sam quand il est fait du secret de Bob."""
    lineage = Lineage(sources=(1,), requirements=(requirement(1, (SAM,), 2, told_by=told_by, heard_by=told_by,
                                                              secret=secret),))

    async def scenario(kernel):
        await kernel.set_params("self", SelfParams(dream_chance=0.0, dream_recall=1.0))
        await _until(kernel, at_paris(2026, 9, 29, 2, 0))
        await kernel.mind.append([self_c.DREAMT.draft(
            night="2026-09-28", text=Content.of("CANARI-REVE Sam cherche du travail dans un couloir sans fin",
                                                level=2),
            voice=VoiceProvenance(call_id="genese", persona_hash="-", role="dream", model="-"),
            kind=self_c.NIGHTMARE, vividness=1.0, emotion="scared", about=(SAM,), sensitivity=2, lineage=lineage)],
            emitter="self", correlation="rêve", origin=Origin.GENESIS)
        await _until(kernel, at_paris(2026, 9, 29, 9, 0))
        await (await kernel.perceive(said(SAM, "salut ! bien dormi ?"))).reply

    _none, llm = _run(tmp_path, scenario)
    to_sam = _replies(llm)
    assert to_sam and ("CANARI-REVE" in to_sam[0]) == shown


# ── La révision d'un secret (de bout en bout) ───────────────────────────────


@pytest.mark.parametrize("told_by,secret,shown", [((BOB,), True, False), ((SAM,), False, True)])
def test_a_revised_secret_belief_is_not_a_thought_sam_hears(tmp_path, told_by, secret, shown):
    script = Script()
    kernel, clock, llm, _out = build(tmp_path, script, start=at_paris(2026, 9, 28, 10, 0))

    async def main():
        await boot(kernel)
        try:
            src = told_by[0]

            def told(text, replaces=None):
                return mc.BELIEVED.draft(text=Content.of(text, level=2), about=(SAM,), told_by=told_by,
                                         heard_by=told_by, source=src, secret=secret, sensitivity=2,
                                         replaces=replaces)

            first = await kernel.mind.append([told("CANARI-AVANT Sam garde son poste")], emitter="memory",
                                             correlation="genese", origin=Origin.GENESIS)
            await kernel.mind.append([told("CANARI-APRES Sam est licencié", replaces=first.seqs[0])], emitter="memory",
                                     correlation="genese", origin=Origin.GENESIS)
            await _until(kernel, at_paris(2026, 9, 28, 11, 0))
            await (await kernel.perceive(said(SAM, "tu penses à quoi en ce moment ?"))).reply
            return [kernel.mind.decode(e) for e in kernel.mind.store.read() if e.type == "attention.thought_born"]
        finally:
            await kernel.stop()

    thoughts = run_virtual(clock, main)
    assert any(t.data.origin == "revision" for t in thoughts)  # elle y a repensé
    to_sam = [c.system_stable + "\n".join(m.content for m in c.messages) for c in llm.calls if c.role == "reply"]
    assert to_sam
    assert ("CANARI-APRES" in to_sam[-1]) == shown


def test_public_floor_is_what_any_room_hears():
    assert PUBLIC_FLOOR.public and PUBLIC_FLOOR.level == Sensitivity.ANODYNE
    assert private_to(SAM).private_ok and not private_to(SAM).public and private_to(SAM).level == Sensitivity.ANODYNE
