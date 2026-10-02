"""La console des gens, par les cas de l'audit (ADR 0035).

- le registre des preuves lit une ligne de plus que sa page : « plus anciens »
  n'est offert que s'il en reste (avant : exactement une page menait à une page vide) ;
- la note d'un opérateur et le nom démenti s'oublient avec la personne : le
  registre les lit « (oublié) » ;
- oublier une personne oublie aussi les noms qui ne désignent qu'elle
  (« name:alice », ce que d'autres ont dit d'elle) — pas ceux d'un homonyme ;
- les libellés ne forcent pas le féminin, et une adresse qui ne parle que pour
  elle-même n'est jamais dite « liée ».
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from mika.app.composition import faculties
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import social as social_c
from mika.faculties.identity import Handle, _apply
from mika.faculties.identity.inspect import FORGOTTEN, MAX_LEDGER, certainty_fr
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import Table
from mika.kernel.registry import Registry
from mika.ports.llm import LLMResponse
from mika.runtime import inspection
from mika.runtime.inspection import Inspection
from mika.runtime.operations import perform
from mika.runtime.state import RUNTIME
from mika.sim.clock import run_virtual
from mika.vocab import privacy
from tests.fixtures.mika import befriend, boot, build, connect, said


def respond(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    return LLMResponse("d'accord [EMOTION:happy:0.4]")


def when(at: int) -> str:
    return f"t{at}"


def show(kernel, owner, name, *, subject="", **params):
    spec = inspection.find(kernel, owner, name)
    return Inspection(kernel).run(spec, params, when, subject=subject)


def ledger(blocks) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and (b.title or "").startswith("Registre"))


def form(**values: str) -> dict[str, list[str]]:
    return {"_champs": [*values, "confirmed"], **{k: [v] for k, v in values.items()}}


def run(tmp_path, scenario):
    kernel, clock, llm, out = build(tmp_path, respond)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def ledger_rows(kernel, handle: str, n: int) -> None:
    """``n`` lignes au registre de cette adresse (des liaisons et déliaisons d'opérateur)."""
    for i in range(n):
        person = "user_1" if i % 2 == 0 else None
        await kernel.mind.append([identity_c.LINKED.draft(handle=handle, person=person, by="operator")],
                                 emitter="identity", correlation=f"op:{i}", origin=Origin.EXTERNAL)


def test_the_ledger_offers_older_rows_only_when_there_are_some(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Adrien", operator=True)
        p = await kernel.perceive(said("tg_5", "salut", channel="telegram", display_name="Didi"))
        await p.reply
        await ledger_rows(kernel, "tg_5", MAX_LEDGER)
        exactly = ledger(show(kernel, "identity", "preuves", subject="tg_5"))
        await ledger_rows(kernel, "tg_6", MAX_LEDGER + 1)
        one_more = ledger(show(kernel, "identity", "preuves", subject="tg_6"))
        return exactly, one_more

    exactly, one_more = run(tmp_path, scenario)
    assert len(exactly.rows) == MAX_LEDGER and not exactly.pager.older  # avant : une page vide derrière
    assert len(one_more.rows) == MAX_LEDGER and one_more.pager.older


def test_an_operator_note_is_forgotten_with_the_person(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Alice")
        await befriend(kernel, "user_2", "close")
        p = await kernel.perceive(said("tg_9", "moi c'est Alice", channel="telegram", display_name="Bob"))
        await p.reply
        got = await perform(kernel, "identity.preuve",
                            form(kind="vouched", note="CANARI-NOTE elle me l'a dit", confirmed="on"),
                            by="user_1", subject="tg_9", nonce="n1")
        before = ledger(show(kernel, "identity", "preuves", subject="tg_9"))
        await kernel.forget("user_2")  # la note concerne Alice (la personne revendiquée)
        after = ledger(show(kernel, "identity", "preuves", subject="tg_9"))
        return got, before, after

    got, before, after = run(tmp_path, scenario)
    assert got.ok
    detail = [str(r.cells[3]) for r in before.rows]
    assert any("CANARI-NOTE" in d for d in detail)
    detail = [str(r.cells[3]) for r in after.rows]
    assert not any("CANARI-NOTE" in d for d in detail) and any(FORGOTTEN in d for d in detail)


def test_forgetting_a_person_reaches_the_names_only_she_carries(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Alice")
        await connect(kernel, "user_2", "Bob")
        await connect(kernel, "user_3", "Chloé Martin")
        await connect(kernel, "user_4", "Chloé Durand")
        # Bob lui a parlé d'« Alice » sans qu'on sache laquelle : un souvenir rangé sous « name:alice »
        await kernel.mind.append([memory_c.BELIEVED.draft(
            text=Content.of("Bob m'a dit qu'Alice déménage", level=2), about=("name:alice",), sensitivity=2)],
            emitter="memory", correlation="g", origin=Origin.GENESIS)
        insp = Inspection(kernel)
        alice = insp.head("person", "user_1", when)
        chloe = insp.head("person", "user_3", when)
        return alice, chloe

    alice, chloe = run(tmp_path, scenario)
    assert "name:alice" in alice.aliases  # seule Alice porte ce nom : l'oublier l'oublie aussi
    assert "name:chloe martin" in chloe.aliases and "name:chloe" not in chloe.aliases  # un homonyme garde le prénom


def test_labels_do_not_force_the_feminine_nor_call_an_unbound_handle_bound(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Adrien", operator=True)
        p = await kernel.perceive(said("tg_5", "salut", channel="telegram", display_name="Didi"))
        await p.reply
        insp = Inspection(kernel)
        return insp.head("person", "user_1", when), insp.head("handle", "tg_5", when)

    adrien, handle = run(tmp_path, scenario)
    assert "propriétaire" in adrien.subtitle and "sa propriétaire" not in adrien.subtitle
    assert "inconnue" not in adrien.subtitle
    badges = {b.text for b in handle.badges}
    assert "certitude 0,85 (sûre du compte)" in badges and "non liée" in badges
    assert certainty_fr(privacy.BOUND) == "0,85 (liée)"  # contrôle : une vraie liaison se dit liée


# ── Le journal existant se rejoue ─────────────────────────────────────────


def test_old_evidence_and_profiles_still_replay():
    """Une preuve et un profil d'avant la version 2 (nom, note, ton, intérêts et
    sujets délicats en clair) se relisent ; un démenti ancien se juge comme avant,
    par le nom."""
    registry = Registry([RUNTIME, *faculties()])
    _t, ev = registry.events.decode("identity.evidence", 1, json.dumps(
        {"handle": "tg_5", "kind": identity_c.DENIED, "name": "Alice", "item": None, "message": 3, "by": "kernel",
         "note": "elle hésite"}))
    assert ev.name is None and ev.legacy_name == "Alice" and ev.legacy_note == "elle hésite" and not ev.denies
    bound = Handle(channel="telegram", trust=privacy.ChannelTrust.ACCOUNT, first_seen=0, name="Alice",
                   person="user_1", certainty=privacy.BOUND, via="operator")
    assert _apply(bound, SimpleNamespace(at=0, data=ev)).person is None  # le démenti ancien délie, comme avant
    _t, profile = registry.events.decode("social.profile_revised", 1, json.dumps(
        {"person": "user_1", "summary": {"ref": "9.summary", "level": 2}, "tone": "doux", "interests": ["montagne"],
         "sensitive": ["sa santé"], "upto": 4, "call_id": "", "model": ""}))
    assert isinstance(profile, social_c.ProfileRevised)
    assert profile.tone is None and profile.legacy_tone == "doux"
    assert profile.legacy_interests == ("montagne",) and profile.legacy_sensitive == ("sa santé",)
