"""Ce qu'un opérateur fait depuis la ligne de commande vaut ce qu'il fait depuis la console.

Deux chemins qui font « la même chose » différemment, c'est une promesse non tenue :
``mika forget user_2`` effaçait ses mots sur le web mais gardait ceux de son compte extérieur ;
``mika identity link`` répondait ``ok`` sur une session authentifiée que le réducteur ignore ;
``mika forge promote`` ne validait pas la version promue ; rien n'était audité. La ligne de
commande passe désormais par les actions et l'oubli de la console.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from mika.app import cli
from mika.app.console import LABELS
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.inspector.names import Names
from mika.kernel.events import Origin
from mika.plugins.forge import SWITCHED, WRITTEN
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build, connect, reply, said


def _subjects(data: Path) -> set[str]:
    db = sqlite3.connect(data / "mind.db")
    try:
        return {s for (s,) in db.execute("SELECT subject FROM content_subjects")}
    finally:
        db.close()


def _journal(data: Path, type_name: str) -> list[tuple[int]]:
    db = sqlite3.connect(data / "mind.db")
    try:
        return list(db.execute("SELECT seq FROM events WHERE type = ?", (type_name,)))
    finally:
        db.close()


def _live(data: Path, scene) -> None:  # type: ignore[no-untyped-def]
    kernel, clock, _, _ = build(data, reply("D'accord !"))

    async def main() -> None:
        await boot(kernel)
        await scene(kernel)
        await kernel.lanes.join()
        await kernel.stop()

    run_virtual(clock, main)


async def _alice_on_two_addresses(kernel) -> None:  # type: ignore[no-untyped-def]
    await connect(kernel, "user_2", "Alice Martin")
    await (await kernel.perceive(said("user_2", "salut, c'est Alice, mon chat s'appelle Moustache"))).reply
    await (await kernel.perceive(said("ext_5", "coucou depuis mon compte extérieur", channel="external"))).reply
    await kernel.mind.append([identity_c.LINKED.draft(handle="ext_5", person="user_2", by="operator")],
                             emitter="identity", correlation="opérateur", origin=Origin.EXTERNAL)


def test_forgetting_a_person_from_the_command_line_forgets_all_her_addresses(tmp_path):
    _live(tmp_path, _alice_on_two_addresses)
    before = _subjects(tmp_path)
    assert {"user_2", "ext_5"} <= before  # ses mots, sur ses deux adresses

    got = asyncio.run(cli.forget(tmp_path, "user_2"))

    left = _subjects(tmp_path)
    assert not left & {"user_2", "ext_5", "name:alice", "name:alice martin"}  # rien d'elle, sur aucune adresse
    assert "ext_5" in got["clés"] and "name:alice" in got["clés"]  # ses adresses et le nom qui ne désigne qu'elle
    assert got["contenus_effacés"] > 0
    assert _journal(tmp_path, rt.OPERATED.name)  # audité, comme dans la console


def test_identity_link_refuses_what_the_reducer_would_ignore(tmp_path):
    """Une session authentifiée prouve déjà qui écrit : la relier ne fait rien. La ligne de commande le dit,
    au lieu de répondre ``ok``."""

    async def scene(kernel) -> None:  # type: ignore[no-untyped-def]
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bea")

    _live(tmp_path, scene)
    linked_before = len(_journal(tmp_path, identity_c.LINKED.name))
    assert cli.main(["--data", str(tmp_path), "identity", "link", "user_3", "user_2"]) == 1
    assert len(_journal(tmp_path, identity_c.LINKED.name)) == linked_before


def test_identity_link_goes_through_the_console_action_and_is_audited(tmp_path):
    async def scene(kernel) -> None:  # type: ignore[no-untyped-def]
        await connect(kernel, "user_2", "Alice")
        await (await kernel.perceive(said("ext_5", "coucou", channel="external"))).reply

    _live(tmp_path, scene)
    out = asyncio.run(cli.identity_command(tmp_path, "link", "ext_5", "Alice"))  # un nom, comme dans la console
    assert out["ok"], out
    out_again = asyncio.run(cli.identity_command(tmp_path, "link", "ext_5", "user_2"))
    assert not out_again["ok"]  # déjà reliée : refusé, comme dans la console

    async def check() -> tuple[str, list[tuple[str, str, str]]]:
        kernel = await cli._offline(tmp_path)
        try:
            person = kernel.mind.frame().get(identity_c.PERSON("ext_5"))
            ops = [(e.data.action, e.data.by, e.data.outcome)
                   for e in (kernel.mind.decode(s) for s in kernel.mind.store.latest([rt.OPERATED.name], 50))]
        finally:
            await cli._close(kernel, tmp_path)
        return person, ops

    person, ops = asyncio.run(check())
    assert person == "user_2"
    assert ("identity.relier", cli.CLI_BY, "done") in ops and ("identity.relier", cli.CLI_BY, "refused") in ops

    async def named() -> tuple[str, str]:
        kernel = await cli._offline(tmp_path)
        try:
            names = Names(kernel, LABELS)
            return names.action("cli.identity.relier"), names.action("cli.oublier.person")
        finally:
            await cli._close(kernel, tmp_path)

    # la console nomme ce qu'a fait la ligne de commande
    assert asyncio.run(named()) == ("Relier à une personne (ligne de commande)", "Oublier · personne (ligne de commande)")

    # une adresse qui n'a jamais écrit se relie d'avance, vers une personne connue seulement
    assert asyncio.run(cli.identity_command(tmp_path, "link", "ext_77", "user_2"))["ok"]
    assert not asyncio.run(cli.identity_command(tmp_path, "link", "ext_78", "Personne Inconnue"))["ok"]


def test_forge_promote_vouches_for_the_version_like_the_console(tmp_path):
    """Promouvoir, c'est aussi « je valide cette version » : sans ce ``trusted``, la version promue
    depuis la ligne de commande ne lisait pas ses secrets, contrairement à la console."""

    async def scene(kernel) -> None:  # type: ignore[no-untyped-def]
        await kernel.mind.append([WRITTEN.draft(app="cafe", version=1, title="Veille café", fingerprint="f1")],
                                 emitter="forge", correlation="genese", origin=Origin.GENESIS)

    _live(tmp_path, scene)
    assert cli.main(["--data", str(tmp_path), "forge", "promote", "cafe"]) == 0

    async def states() -> list[str]:
        kernel = await cli._offline(tmp_path)
        try:
            return [kernel.mind.decode(s).data.state for s in kernel.mind.store.latest([SWITCHED.name], 10)]
        finally:
            await cli._close(kernel, tmp_path)

    assert sorted(asyncio.run(states())) == ["promoted", "trusted"]
    assert cli.main(["--data", str(tmp_path), "forge", "promote", "cafe"]) == 1  # déjà promue : dit, refusé
    assert cli.main(["--data", str(tmp_path), "forge", "promote", "inconnue"]) == 1
