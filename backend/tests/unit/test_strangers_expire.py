"""Les inconnues de passage s'oublient (audit du 2026-10-26) : une adresse jamais reliée ni authentifiée, dont elle
n'est pas proche, silencieuse depuis ``stranger_ttl_days``, disparaît de toutes les tranches qui la gardaient —
identité, posture, heures, attentes, fil. Une amie, un compte, une personne connue de nom restent. Et l'oubli d'une
personne (``kernel.subject_forgotten``) atteint désormais les mêmes tranches."""

from __future__ import annotations

import asyncio

from mika.app import composition
from mika.contracts import identity as identity_c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, US
from mika.kernel.events import Origin
from mika.sim.clock import run_virtual
from tests.fixtures.mika import DOC, befriend, build, connect, reply, said

#: ce que chaque faculté range sous la clé d'une personne ou d'une adresse
KEPT = (("identity", "handles"), ("affect", "stances"), ("others", "hours"), ("attention", "exchanges"),
        ("transcript", "last_from"), ("social", "contacts"))


def _where(kernel, who: str) -> list[str]:
    slices = kernel.mind.root.slices
    return [f"{owner}.{field}" for owner, field in KEPT if who in getattr(slices[owner], field)]


def _run(tmp_path, scenario, *, ttl_days: int = 7):
    kernel, clock, llm, out = build(tmp_path, reply("coucou"))

    async def main():
        await kernel.start(configure=lambda k: composition.configure(
            k, DOC, {"identity": {"stranger_ttl_days": ttl_days}}))
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_a_stranger_silent_for_long_is_forgotten_by_every_faculty(tmp_path):
    async def scenario(kernel):
        await kernel.perceive(said("ext_7", "bonjour, je passe par là", channel="external", authenticated=False))
        await asyncio.sleep(300)
        before = _where(kernel, "ext_7")
        assert {"identity.handles", "others.hours", "attention.exchanges", "transcript.last_from"} <= set(before), before
        await asyncio.sleep(10 * DAY / US)
        assert _where(kernel, "ext_7") == []
        expired = kernel.mind.store.latest([identity_c.EXPIRED.name], 10)
        assert len(expired) == 1
        assert kernel.mind.root.slices["identity"].by_person.get("ext_7") is None

    _run(tmp_path, scenario)


def test_a_friend_a_named_person_and_an_account_never_expire(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Adrien")
        await kernel.perceive(said("user_1", "salut"))
        await kernel.perceive(said("ext_8", "hello", channel="external", authenticated=False))
        await befriend(kernel, "ext_8", "friend")
        await kernel.perceive(said("ext_9", "bonsoir", channel="external", authenticated=False))
        await kernel.mind.append([identity_c.NAME_BOUND.draft(name="name:carol", person="ext_9")],
                                 emitter="identity", correlation="op", origin=Origin.EXTERNAL)
        await asyncio.sleep(10 * DAY / US)
        handles = kernel.mind.root.slices["identity"].handles
        assert {"user_1", "ext_8", "ext_9"} <= set(handles)
        assert kernel.mind.store.latest([identity_c.EXPIRED.name], 10) == []

    _run(tmp_path, scenario)


def test_forgetting_a_person_reaches_every_faculty(tmp_path):
    async def scenario(kernel):
        await kernel.perceive(said("ext_7", "bonjour, je passe par là", channel="external", authenticated=False))
        await asyncio.sleep(300)
        assert "others.hours" in _where(kernel, "ext_7")
        await kernel.mind.append([SUBJECT_FORGOTTEN.draft(subject="ext_7")], emitter="kernel",
                                 origin=Origin.KERNEL, correlation="forget")
        left = _where(kernel, "ext_7")
        # l'adresse reste (un compte existe), déliée, et son lien aussi (contact, dernier message) ; ce qu'elle a
        # appris d'elle et ressenti pour elle s'en va
        assert left == ["identity.handles", "transcript.last_from", "social.contacts"], left

    _run(tmp_path, scenario)
