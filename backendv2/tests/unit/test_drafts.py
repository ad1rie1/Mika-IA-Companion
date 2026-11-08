"""La marque de ce qu'elle n'a pas su, dans un brouillon : une seule, pour le courrier et pour Teams (K0-15).

Un « [À COMPLÉTER » se reconnaît sous toutes ses graphies ; le client web le relit de son côté
(``frontendv2/src/screens/mail/format.ts``), avec les mêmes exemples.
"""

from __future__ import annotations

import pytest

from mika.ports import drafts, mail, teams


def test_mail_and_teams_read_the_same_mark():
    assert mail.to_fill is drafts.to_fill and teams.to_fill is drafts.to_fill


@pytest.mark.parametrize("text", [
    "Nous pourrions démarrer le [À COMPLÉTER : date].",
    "[a completer]",
    "[À COMPLÉTER]",  # accents décomposés
    "[ À remplir ]",
    "[compléter]",
    "［À PRÉCISER］",  # crochets pleine chasse
])
def test_every_spelling_of_the_mark_is_seen(text):
    assert drafts.to_fill(text)


@pytest.mark.parametrize("texts", [
    ("À COMPLÉTER sans crochet",),
    ("Rien à compléter ici.", ""),
    ("[à compléterons]",),
    (),
])
def test_what_is_not_the_mark_is_left_alone(texts):
    assert not drafts.to_fill(*texts)


def test_one_marked_text_among_several_is_enough_and_a_missing_one_is_nothing():
    assert drafts.to_fill("Bonjour", "[à préciser]")
    assert not drafts.to_fill(None, "")  # type: ignore[arg-type]  # un texte absent
