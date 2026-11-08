"""Le résumé d'un épisode se lit une fois (K11-07, audit du 2026-11-05) : sa page dessinée et ses blocs (le repli, et la
bascule « Tableau ») tirent ses chiffres, son issue et ses dernières paroles de la même lecture
(``episode_overview.summary``) et disent les mêmes mots — avant, un épisode sans fin se disait de deux façons."""

from __future__ import annotations

import html

import pytest

from mika.contracts import runtime as rt
from mika.inspector.pages.episode_overview import OPEN
from mika.kernel.events import Origin
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

URL = "/inspecteur/episode/un-episode"


def _both(client) -> tuple[str, str]:
    """La page dessinée du résumé, et ses blocs (la bascule « Tableau »)."""
    drawn = client.get(URL)
    blocks = client.get(f"{URL}?vue_pg1=table")
    assert drawn.status_code == blocks.status_code == 200
    drawn_text, blocks_text = html.unescape(drawn.text), html.unescape(blocks.text)
    assert 'class="now-card episode-hero' in drawn_text and 'class="now-card episode-hero' not in blocks_text
    return drawn_text, blocks_text


@pytest.mark.parametrize("ended", [False, True])
def test_the_drawn_summary_and_its_blocks_say_the_same(world, ended):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    drafts = [rt.EPISODE_STARTED.draft(kind="TASK")]
    if ended:
        drafts.append(rt.EPISODE_ENDED.draft(kind="TASK", outcome="failed", detail="Service indisponible"))
    client.portal.call(lambda: kernel.mind.append(drafts, emitter="runtime", origin=Origin.GENESIS,
                                                 correlation="un-episode"))
    drawn, blocks = _both(client)
    if ended:
        assert "Service indisponible" in drawn and "Service indisponible" in blocks
        assert "Aucune fin n’est enregistrée" not in drawn + blocks
    else:  # une seule phrase pour un épisode ouvert, des deux côtés, et le lien pour vérifier ce qui tourne
        assert OPEN in drawn and OPEN in blocks
        assert "Vérifier l’activité actuelle" in drawn and "Vérifier l’activité actuelle" in blocks
    for page in (drawn, blocks):  # la même durée, dite pareil (un début et une fin du même instant : « < 1 s »)
        assert ("< 1 s" in page) is ended and ("fin ou début absent" in page) is not ended
