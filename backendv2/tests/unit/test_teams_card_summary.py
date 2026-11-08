"""La carte d'accord d'une réponse Teams (F1-01, audit du 2026-11-05) : son résumé est gardé au journal et lu deux
fois — sur la carte de qui décide (frontendv2 le montre tel quel) et dans « À valider » par l'opératrice. Il dit à
qui elle répond, où, et comment ça partira, en mots neutres : ni le nom de qui décide (deux fois sur sa propre carte,
« de Adrien »), ni « ton accord », ni un titre inventé (« « une conversation » ») pour un tête-à-tête qui n'en a pas."""

from __future__ import annotations

import pytest

from mika.app.mindport import KernelPort
from mika.contracts import runtime as rt
from mika.kernel.clock import MINUTE
from mika.plugins.teams.tools import MODE_WORDS, summary_of
from tests.fixtures.mika import connect
from tests.unit.test_teams import DM, GROUP, QUESTION, Model, conv, events, live, msg, push, sleep


@pytest.mark.parametrize(("title", "kind", "said"), [
    ("", "dm", "Répondre sur Teams à Alice Martin en privé — à envoyer après accord"),
    # le nom d'un tête-à-tête n'est que celui de l'autre personne : déjà dit
    ("Alice Martin", "dm", "Répondre sur Teams à Alice Martin en privé — à envoyer après accord"),
    ("Projet vitrine", "group", "Répondre sur Teams à Alice Martin dans « Projet vitrine » — à envoyer après accord"),
    ("", "group", "Répondre sur Teams à Alice Martin dans un groupe — à envoyer après accord"),
    ("", "", "Répondre sur Teams à Alice Martin — à envoyer après accord"),
])
def test_the_summary_says_where_without_inventing_a_title(title, kind, said):
    assert summary_of("Alice Martin", title, kind, "validation") == said


def test_each_way_of_leaving_is_said_without_a_name():
    assert summary_of("Alice", "", "dm", "brouillon").endswith("— posée dans Teams pour être envoyée")
    assert summary_of("Alice", "", "dm", "autonome").endswith("— envoyée sans accord")
    for words in MODE_WORDS.values():  # lus aussi par l'opératrice : neutres
        assert "{who}" not in words and "ton " not in words and "ta place" not in words


def test_the_card_names_neither_the_decider_nor_a_made_up_title(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), msg(clock, 2, "Et pour la démo ?", conv=GROUP),
                   conversations=[conv(DM), conv(GROUP, "Projet vitrine", "group")])
        await sleep(30 * MINUTE)
        refs = [p.data.summary.ref for p in events(kernel, rt.EFFECT_PROPOSED)]
        return kernel.mind.store.content(refs), await KernelPort(kernel).approval_cards("user_1")

    kept, cards = live(tmp_path, Model(), scenario, mode="validation")
    summaries = sorted(kept.values())
    assert summaries == ["Répondre sur Teams à Alice Martin dans « Projet vitrine » — à envoyer après accord",
                         "Répondre sur Teams à Alice Martin en privé — à envoyer après accord"]
    for text in summaries:
        assert "Adrien" not in text and "à la place de" not in text and "une conversation" not in text
    texts = sorted(card["text"].split("\n", 1)[0] for card in cards)
    assert texts == ["Dans Teams — « Projet vitrine » :", "Dans Teams, en privé :"]
