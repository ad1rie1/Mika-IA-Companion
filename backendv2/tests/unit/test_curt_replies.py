"""Répondre à peine : une seule règle d'un message bref, deux fenêtres.

La règle est celle d'``others`` (``contracts/others.py::few_words``) : trois mots au plus, ni une question ni un
bonjour. ``others`` la lit sur la conversation en cours (ses trois derniers messages, ``curt_run``), ``attention`` sur
l'échange passé d'où naît une pensée (les deux tiers de ses messages, aucun au-delà de huit mots, ``mostly_curt``).
Un bonjour ou une question n'est répondre à peine ni dans l'une ni dans l'autre.
"""

from __future__ import annotations

import pytest

from mika.contracts import others as others_c
from mika.faculties.attention.watch import LONG_WORDS, mostly_curt
from mika.faculties.others.faculty import CURT_RUN, curt_run

BRIEF = ["ouais", "bof", "je sais pas", "laisse tomber", "ok.", "Mouais…"]
NOT_BRIEF = [
    "salut",  # un bonjour est court par nature
    "Salut !",
    "coucou toi",
    "ça va ?",  # une question n'est pas répondre à peine
    "ouais ?",
    "je sais pas trop",  # quatre mots
    "je crois que j'ai tout raté",
    "",
    "   ",
]


@pytest.mark.parametrize("text", BRIEF)
def test_a_few_words_are_brief(text):
    assert others_c.few_words(text)


@pytest.mark.parametrize("text", NOT_BRIEF)
def test_a_greeting_a_question_or_four_words_are_not_brief(text):
    assert not others_c.few_words(text)


def test_few_words_counts_at_most_three_words():
    assert others_c.FEW_WORDS == 3
    assert others_c.few_words("pas trop envie")
    assert not others_c.few_words("pas trop envie là")


# ── La conversation en cours (others) ──────────────────────────────────────


def test_three_brief_replies_in_a_row_are_a_curt_run():
    assert CURT_RUN == 3
    assert curt_run(("ouais", "bof", "je sais pas"))


def test_a_greeting_among_them_breaks_the_run():
    assert not curt_run(("ouais", "salut", "bof"))
    assert not curt_run(("ouais", "bof", "ça va ?"))


def test_only_the_last_replies_of_the_conversation_count():
    assert curt_run(("je crois que j'ai tout raté à mon entretien", "ouais", "bof", "je sais pas"))
    assert not curt_run(("ouais", "bof", "je sais pas", "tu fais quoi ce soir ?"))


def test_fewer_than_three_replies_are_no_run():
    assert not curt_run(("ouais", "bof"))
    assert not curt_run(())


# ── L'échange passé d'où naît une pensée (attention) ───────────────────────


def test_an_exchange_of_brief_replies_was_curt():
    assert mostly_curt(["ouais", "bof", "je sais pas"])


def test_a_greeting_and_a_question_are_not_answering_barely():
    # l'ancienne règle d'attention (quatre mots au plus, comptés entre les blancs) disait oui
    assert not mostly_curt(["salut", "ça va ?", "ouais"])


def test_four_words_are_no_longer_a_brief_reply():
    # l'ancienne règle d'attention disait oui : ses trois messages avaient quatre mots au plus
    assert not mostly_curt(["ouais", "je sais pas trop", "pas vraiment envie là"])


def test_two_thirds_of_brief_replies_are_enough():
    assert mostly_curt(["ouais", "bof", "je sais pas trop quoi faire"])
    assert mostly_curt(["ouais", "bof", "laisse tomber", "pas trop envie d'en parler"])
    assert not mostly_curt(["ouais", "je sais pas trop quoi faire", "c'est compliqué en ce moment"])


def test_one_message_of_more_than_eight_words_says_something():
    assert LONG_WORDS == 8
    assert mostly_curt(["ouais", "bof", "un deux trois quatre cinq six sept huit"])
    assert not mostly_curt(["ouais", "bof", "je crois que j'ai tout raté à mon entretien hier"])


def test_fewer_than_three_messages_are_not_an_exchange_answered_barely():
    assert not mostly_curt(["ouais", "bof"])
    assert not mostly_curt([])


# ── Une règle, deux fenêtres ─────────────────────────────────────────────


@pytest.mark.parametrize("text", BRIEF + NOT_BRIEF)
def test_both_windows_read_the_same_rule(text):
    # le même message trois fois : la conversation en cours et l'échange passé disent la même chose que la règle
    assert len(text.split()) <= LONG_WORDS
    assert curt_run((text,) * CURT_RUN) == others_c.few_words(text)
    assert mostly_curt([text] * 3) == others_c.few_words(text)
