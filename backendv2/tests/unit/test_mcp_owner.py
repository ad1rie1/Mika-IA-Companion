"""À qui est un service MCP (C9-03, audit du 2026-11-05) : depuis l'ADR 0192, une personne branche ses propres
services. Venus d'ailleurs le dit sur chaque ligne (son nom à elle, ou la personne, vers sa fiche), le filtre quand
plusieurs en ont branché (``?qui=``), et la fiche d'un service d'une personne le porte à côté de son nom."""

from __future__ import annotations

from mika.contracts import self_ as self_c
from mika.kernel.inspect import Badge, Nav, Ref, Table, Text
from mika.ports.mcp import ServerStatus
from mika.runtime.inspection import Inspection
from tests.unit.test_mcp_plugin import FakePort, live

HERS = ServerStatus(name="meteo", kind="distant", enabled=True, ready=True, state="connecte", purpose="la météo")
BEAS = ServerStatus(name="agenda", kind="distant", enabled=True, ready=True, state="connecte", purpose="son agenda",
                    owner="personne:user_2")


class Statuses(FakePort):
    def statuses(self):
        return [HERS, BEAS]

    def status(self, server):
        return next((s for s in (HERS, BEAS) if s.name == server), None)


def _view(blocks: list) -> tuple[Table, Nav | None]:
    table = next(b for b in blocks if isinstance(b, Table) and b.title == "Les services branchés")
    return table, next((b for b in blocks if isinstance(b, Nav) and b.title == "À qui"), None)


def test_each_service_says_whose_it_is_and_filters_by_owner(tmp_path):
    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        spec = ins.find("mcp", "serveurs")
        her = self_c.name_of(kernel.mind.frame().get(self_c.PERSONA))
        return (her, await ins.arun(spec, {}), await ins.arun(spec, {"qui": "personne:user_2"}),
                await ins.arun(spec, {"qui": "elle"}), ins.head("serveur", "agenda"), ins.head("serveur", "meteo"))

    her, every, beas, hers, head_bea, head_hers = live(tmp_path, scenario, Statuses())
    table, owners = _view(every)
    column = [c if isinstance(c, str) else c.label for c in table.columns].index("à qui")
    whose = {row.cells[0].text: row.cells[column] for row in table.rows}
    assert whose["meteo"] == Text(her)
    assert whose["agenda"] == Ref.subject("person", "user_2", "Béa")  # vers sa fiche
    assert owners is not None and [i.text for i in owners.items] == ["Tout le monde", her, "Béa"]
    assert [row.cells[0].text for row in _view(beas)[0].rows] == ["agenda"]
    assert [row.cells[0].text for row in _view(hers)[0].rows] == ["meteo"]
    assert head_bea.badges[0] == Badge("à Béa", "info")
    assert head_hers.badges[0].text == "connecté" and f"à {her}" not in [b.text for b in head_hers.badges]  # un des siens


def test_with_a_single_owner_there_is_nothing_to_filter(tmp_path):
    class Hers(Statuses):
        def statuses(self):
            return [HERS]

    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        return await ins.arun(ins.find("mcp", "serveurs"), {})

    assert _view(live(tmp_path, scenario, Hers()))[1] is None
