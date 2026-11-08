"""La prochaine séance d'un but se dit d'une seule règle (décision Q05 de l'audit du 2026-11-05, constat K11-08) :
l'en-tête de la faculté, la liste des buts vivants, la fiche et son rythme disent la même chose — quand, ou ce qui la
retient —, et la fiche dessinée la lit dans l'en-tête de la faculté au lieu de la recalculer. Avant, la liste disait
« dès que possible » la nuit quand la fiche disait qu'elle dort, et l'en-tête parlait d'une séance pour un but en pause
que la fiche dessinée taisait."""

from __future__ import annotations

import re

from mika.faculties.goals.inspect import NEXT_SESSION
from mika.kernel.inspect import Fields, Grid
from mika.runtime.inspection import Inspection
from mika.runtime.operations import perform
from tests.fixtures.mika import at_paris, connect
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée
from tests.unit.test_goals_console import explore, form, live, tab, table

NIGHT = at_paris(2026, 9, 29, 2, 0)


def _said(blocks: list, title: str) -> str:
    """La prochaine séance dans les champs ``title`` d'un onglet (repliés dans une grille ou non)."""
    fields = [b for b in blocks if isinstance(b, Fields)] + [f for b in blocks if isinstance(b, Grid)
                                                            for f in b.items if isinstance(f, Fields)]
    return str(dict(next(f for f in fields if f.title == title).pairs)[NEXT_SESSION])


def test_every_view_of_a_goal_says_the_same_next_session(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = str(await explore(kernel))
        ins = Inspection(kernel)
        out = {"head": dict(ins.head("goal", gid).facts).get(NEXT_SESSION),
               "list": str(table(await tab(kernel, "vivants", ""), "Buts vivants").rows[0].cells[7]),
               "card": _said(await tab(kernel, "resume", gid), "Prochaine séance"),
               "rhythm": _said(await tab(kernel, "politique", gid), "Son rythme")}
        got = await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="pause")
        assert got.ok, got
        out["paused"] = dict(ins.head("goal", gid).facts).get(NEXT_SESSION)
        out["paused_list"] = str(table(await tab(kernel, "vivants", ""), "Buts vivants").rows[0].cells[7])
        return out

    out = live(tmp_path, scenario, start=NIGHT)
    # la nuit, elle dort : partout la même raison, jamais « dès que possible » d'un côté et la raison de l'autre
    assert out["head"] == out["list"] == out["card"] == out["rhythm"] == "elle dort : aucune séance la nuit"
    # en pause, il n'en a pas : l'en-tête le tait (son statut le dit), la liste met un tiret
    assert out["paused"] is None and out["paused_list"] == "—"


def test_the_drawn_fiche_reads_the_next_session_in_the_faculty_head(world):  # noqa: F811
    client, live_, _ = world
    bootstrap(client)
    kernel = live_.kernel
    stop(client, kernel)  # aucune séance ne part pendant qu'on lit
    gid = str(client.portal.call(explore, kernel))
    said = client.portal.call(lambda: dict(Inspection(kernel).head("goal", gid).facts)[NEXT_SESSION])
    page = drawn(client, f"/inspecteur/fiche/goal/{gid}")
    head = page[page.index('class="obj-head-facts"'):]
    head = head[:head.index("</p>")]
    shown = re.search(rf'<span class="now-muted">{NEXT_SESSION}</span> ([^<]+)</span>', head)
    assert shown is not None and shown.group(1) == said
    resume = page[page.index("<dt>Prochaine séance</dt>"):]
    assert resume.startswith(f"<dt>Prochaine séance</dt><dd>{said}</dd>")
    got = client.portal.call(lambda: perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="p"))
    assert got.ok, got
    paused = drawn(client, f"/inspecteur/fiche/goal/{gid}")
    assert NEXT_SESSION not in paused[paused.index('class="obj-head-facts"'):].split("</p>", 1)[0]
    assert "<dt>Prochaine séance</dt>" not in paused
