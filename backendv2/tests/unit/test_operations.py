"""Les actions d'opérateur, par le moteur générique : un formulaire invalide ne
fait rien et dit pourquoi, champ par champ ; une action valide journalise ses
événements avec l'origine « extérieure » et un audit qui nomme l'opérateur ;
un double envoi ne refait rien ; une garde changée supplante ; une action
irréversible exige qu'on retape la clé ; une action qui émettrait ce qu'elle
n'a pas déclaré est refusée."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import BaseModel, Field

from mika.contracts import runtime as rt
from mika.kernel.events import Origin, Payload
from mika.kernel.facts import FactKey
from mika.kernel.faculty import Faculty
from mika.kernel.guards import Guard
from mika.kernel.operate import Done, Refused
from mika.runtime.operations import perform
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build


@dataclass(frozen=True, slots=True)
class Board:
    notes: tuple[str, ...] = ()
    closed: bool = False


class Pinned(Payload):
    text: str
    by: str = ""


class Closed(Payload):
    pass


BOARD = Faculty("board", state=Board, init=lambda p: Board())
PINNED = BOARD.event("pinned", Pinned)
CLOSED = BOARD.event("closed", Closed)
STRAY = BOARD.event("stray", Closed)


@BOARD.reducer(PINNED)
def _pinned(s: Board, e, cx) -> Board:
    return replace(s, notes=(*s.notes, e.data.text))


@BOARD.reducer(CLOSED)
def _closed(s: Board, e, cx) -> Board:
    return replace(s, closed=True)


class PinArgs(BaseModel):
    text: str = Field(min_length=1, max_length=40)
    times: int = Field(default=1, ge=1, le=3)


@BOARD.action("epingler", title="Épingler", args=PinArgs, emits=[PINNED])
def _pin(s: Board, frame, args: PinArgs, ctx) -> Done:
    if args.text == "interdit":
        raise Refused("Ce texte est refusé.", {"text": "pas celui-là"})
    return Done(drafts=tuple(PINNED.draft(text=args.text, by=ctx.by) for _ in range(args.times)),
                message="Épinglé.",
                guard=Guard("toujours ouvert", predicate=lambda view: True))


class NoArgs(BaseModel):
    pass


@BOARD.action("fermer", title="Fermer", args=NoArgs, emits=[CLOSED], retype=True, subject="",
              available=lambda s, frame, key: not s.closed)
def _close(s: Board, frame, args, ctx) -> Done:
    return Done(drafts=(CLOSED.draft(),), message="Fermé.")


@BOARD.action("tricher", title="Tricher", args=NoArgs, emits=[CLOSED])
def _cheat(s: Board, frame, args, ctx) -> Done:
    return Done(drafts=(STRAY.draft(),))


def form(**values: str) -> dict[str, list[str]]:
    return {"_champs": [k for k in values if not k.startswith("_")], **{k: [v] for k, v in values.items()}}


def events(kernel, name: str) -> list:
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types={name})]


def test_the_operator_path(tmp_path):
    kernel, clock, _ = build(tmp_path, [BOARD])

    async def main():
        await kernel.start()
        out = {}
        out["bad"] = await perform(kernel, "board.epingler", form(text="", times="9"), by="user_1", nonce="n1")
        out["refused"] = await perform(kernel, "board.epingler", form(text="interdit"), by="user_1", nonce="n2")
        out["ok"] = await perform(kernel, "board.epingler", form(text="courses", times="2"), by="user_1", nonce="n3")
        out["again"] = await perform(kernel, "board.epingler", form(text="courses", times="2"), by="user_1",
                                     nonce="n3")
        out["stray"] = await perform(kernel, "board.tricher", form(), by="user_1", nonce="n4")
        out["unknown"] = await perform(kernel, "board.rien", form(), by="user_1", nonce="n5")
        out["no_retype"] = await perform(kernel, "board.fermer", form(), by="user_1", subject="tableau", nonce="n6")
        out["retyped"] = await perform(kernel, "board.fermer", form(_confirmer="tableau"), by="user_1",
                                       subject="tableau", nonce="n7")
        out["unavailable"] = await perform(kernel, "board.fermer", form(_confirmer="tableau"), by="user_1",
                                           subject="tableau", nonce="n8")
        out["notes"] = kernel.mind.frame().state("board").notes
        out["pinned"] = events(kernel, PINNED.name)
        out["audit"] = events(kernel, rt.OPERATED.name)
        await kernel.stop()
        return out

    out = run_virtual(clock, main)
    bad = out["bad"]
    assert not bad.ok and set(bad.errors) == {"text", "times"}  # chaque champ dit ce qui ne va pas
    assert "3" in bad.errors["times"]
    assert not out["refused"].ok and out["refused"].errors == {"text": "pas celui-là"}
    assert out["ok"].ok and out["ok"].message == "Épinglé." and len(out["ok"].seqs) == 2
    assert out["again"].deduped and out["notes"] == ("courses", "courses")  # un double envoi ne refait rien
    pinned = out["pinned"]
    assert all(e.origin is Origin.EXTERNAL and e.correlation.startswith("opérateur:board.epingler") for e in pinned)
    assert not out["stray"].ok and "board.stray" in out["stray"].message
    assert not out["unknown"].ok
    assert not out["no_retype"].ok and "_confirmer" in out["no_retype"].errors
    assert out["retyped"].ok
    assert not out["unavailable"].ok  # une fois fermé, « fermer » n'est plus offert
    audit = {(e.data.action, e.data.outcome) for e in out["audit"]}
    assert ("board.epingler", "done") in audit and ("board.epingler", "refused") in audit
    assert ("board.tricher", "refused") in audit and ("board.fermer", "done") in audit
    assert all(e.data.by == "user_1" for e in out["audit"])


def test_a_changed_situation_supersedes(tmp_path):
    kernel, clock, _ = build(tmp_path, [BOARD])

    @BOARD.action("prudent", title="Prudent", args=NoArgs, emits=[PINNED])
    def _careful(s, frame, args, ctx) -> Done:
        return Done(drafts=(PINNED.draft(text="x"),), guard=Guard("jamais", predicate=lambda view: False))

    try:
        kernel, clock, _ = build(tmp_path, [BOARD])

        async def main():
            await kernel.start()
            got = await perform(kernel, "board.prudent", form(), by="user_1", nonce="p1")
            audit = events(kernel, rt.OPERATED.name)
            await kernel.stop()
            return got, audit

        got, audit = run_virtual(clock, main)
        assert not got.ok and "La situation a changé" in got.message
        assert [e.data.outcome for e in audit] == ["superseded"]
    finally:
        BOARD.actions[:] = [a for a in BOARD.actions if a.name != "prudent"]


def test_an_action_that_acts_outside_the_journal_runs_once_per_form(tmp_path):
    """Une action peut agir hors du journal (recharger une app, revenir à une version
    précédente) : un double envoi du même formulaire ne l'exécute pas deux fois —
    ni pendant qu'elle tourne, ni après un redémarrage (l'audit garde le jeton)."""
    effects: list[str] = []

    @BOARD.action("rembobiner", title="Rembobiner", args=NoArgs, emits=[])
    def _rewind(s, frame, args, ctx) -> Done:
        effects.append(ctx.by)
        return Done(message="Rembobiné.")

    try:
        kernel, clock, _ = build(tmp_path, [BOARD])

        async def main():
            await kernel.start()
            first = await perform(kernel, "board.rembobiner", form(), by="user_1", nonce="r1")
            again = await perform(kernel, "board.rembobiner", form(), by="user_1", nonce="r1")
            other = await perform(kernel, "board.rembobiner", form(), by="user_1", nonce="r2")
            await kernel.stop()
            return first, again, other

        first, again, other = run_virtual(clock, main)
        assert first.ok and again.deduped and other.ok
        assert effects == ["user_1", "user_1"]  # r1 une fois, r2 une fois
        restarted, clock2, _ = build(tmp_path, [BOARD], seed=1, start=clock.now() + 60_000_000)

        async def after_restart():
            await restarted.start()
            got = await perform(restarted, "board.rembobiner", form(), by="user_1", nonce="r1")
            await restarted.stop()
            return got

        assert run_virtual(clock2, after_restart).deduped and len(effects) == 2
    finally:
        BOARD.actions[:] = [a for a in BOARD.actions if a.name != "rembobiner"]


COUNT = FactKey("board.count", type=int)


@BOARD.fact(COUNT)
def _count(s: Board, cx) -> int:
    return len(s.notes)


def test_a_guard_checks_what_the_action_read(tmp_path):
    """KER-28 : la garde d'une action compare ce que l'action a **lu** à l'état au moment d'écrire. Une note
    épinglée par quelqu'un d'autre pendant que l'action réfléchissait (elle attend un port, un réseau) change
    ce qu'elle a lu : rien n'est écrit, et l'opérateur l'apprend. (Avant, la garde comparait la tête à
    elle-même : elle ne voyait jamais rien changer.)"""
    box: dict = {}

    @BOARD.action("compter", title="Compter", args=NoArgs, emits=[PINNED])
    async def _count_then_pin(s, frame, args, ctx) -> Done:
        seen = frame.get(COUNT)
        await box["kernel"].mind.append([PINNED.draft(text="intrus")], emitter="board", correlation="ailleurs")
        return Done(drafts=(PINNED.draft(text=f"il y en avait {seen}"),), guard=Guard("le compte", reads=(COUNT,)))

    @BOARD.action("compter_seul", title="Compter seul", args=NoArgs, emits=[PINNED])
    async def _count_alone(s, frame, args, ctx) -> Done:
        seen = frame.get(COUNT)
        return Done(drafts=(PINNED.draft(text=f"il y en avait {seen}"),), guard=Guard("le compte", reads=(COUNT,)))

    try:
        kernel, clock, _ = build(tmp_path, [BOARD])
        box["kernel"] = kernel

        async def main():
            await kernel.start()
            raced = await perform(kernel, "board.compter", form(), by="user_1", nonce="g1")
            calm = await perform(kernel, "board.compter_seul", form(), by="user_1", nonce="g2")
            notes = kernel.mind.frame().state("board").notes
            await kernel.stop()
            return raced, calm, notes

        raced, calm, notes = run_virtual(clock, main)
        assert not raced.ok and "La situation a changé" in raced.message
        assert calm.ok  # contre-exemple : rien n'a bougé entre la lecture et l'écriture
        assert notes == ("intrus", "il y en avait 1")
    finally:
        BOARD.actions[:] = [a for a in BOARD.actions if a.name not in ("compter", "compter_seul")]


def test_a_failed_action_gives_its_form_back(tmp_path):
    """CON-30 : le jeton d'un formulaire ne se consomme que si l'action a abouti ou a été refusée. Une panne
    le rend : renvoyer le même formulaire réessaie, au lieu de répondre « déjà envoyé » sur une action qui
    n'a rien fait. Une réussite, elle, ne se refait pas."""
    tries: list[int] = []

    @BOARD.action("fragile", title="Fragile", args=PinArgs, emits=[PINNED])
    def _fragile(s, frame, args, ctx) -> Done:
        tries.append(1)
        if len(tries) == 1:
            raise OSError(5, "disque indisponible")
        return Done(drafts=(PINNED.draft(text=args.text),), message="Épinglé.")

    try:
        kernel, clock, _ = build(tmp_path, [BOARD])

        async def main():
            await kernel.start()
            failed = await perform(kernel, "board.fragile", form(text="à garder"), by="user_1", nonce="f1")
            retried = await perform(kernel, "board.fragile", form(text="à garder"), by="user_1", nonce="f1")
            again = await perform(kernel, "board.fragile", form(text="à garder"), by="user_1", nonce="f1")
            refused = await perform(kernel, "board.epingler", form(text="interdit"), by="user_1", nonce="f2")
            refused_again = await perform(kernel, "board.epingler", form(text="ok"), by="user_1", nonce="f2")
            audit = [(e.data.action, e.data.outcome) for e in events(kernel, rt.OPERATED.name)]
            await kernel.stop()
            return failed, retried, again, refused, refused_again, audit

        failed, retried, again, refused, refused_again, audit = run_virtual(clock, main)
        assert not failed.ok and failed.retry
        # l'erreur est dite en français, jamais un repr Python
        assert "disque indisponible" in failed.message and "OSError(" not in failed.message
        assert retried.ok and not retried.deduped and len(tries) == 2
        assert again.deduped and len(tries) == 2  # une réussite ne se refait pas
        assert not refused.ok and refused_again.deduped  # un refus consomme le jeton
        assert ("board.fragile", "failed") in audit and ("board.fragile", "done") in audit
    finally:
        BOARD.actions[:] = [a for a in BOARD.actions if a.name != "fragile"]
