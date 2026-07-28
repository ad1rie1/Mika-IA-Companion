"""Passive identification — reading a name off an ordinary message.

Runs on every inbound turn, so it must be free and it must be quiet: a false
positive makes Mika address a stranger by someone else's name. The bias is
strongly toward returning nothing.
"""
from __future__ import annotations

import pytest

from identity.detection import (
    corroboration_score,
    detect_name_claim,
)


class TestSelfIntroduction:

    @pytest.mark.parametrize("message,expected", [
        ("je m'appelle Thomas", "Thomas"),
        ("Je m’appelle Élodie", "Élodie"),
        ("moi c'est Alice", "Alice"),
        ("Moi, c'est Jean-Luc", "Jean-Luc"),
        ("mon prénom est Camille", "Camille"),
        ("mon nom c'est Dupont", "Dupont"),
        ("salut ! c'est Marc", "Marc"),
        ("ici Sophie", "Sophie"),
        ("Thomas à l'appareil", "Thomas"),
        ("je suis Nicolas", "Nicolas"),
        ("my name is Sarah", "Sarah"),
        ("hey, this is Mike", "Mike"),
    ])
    def test_detects_common_forms(self, message, expected):
        claim = detect_name_claim(message)
        assert claim is not None, f"non détecté: {message!r}"
        assert claim.name == expected
        assert claim.kind == "self_declared"

    def test_keeps_the_triggering_fragment_as_evidence(self):
        claim = detect_name_claim("bonjour, je m'appelle Thomas, ça va ?")
        assert claim is not None
        assert "Thomas" in claim.evidence
        assert len(claim.evidence) < len("bonjour, je m'appelle Thomas, ça va ?")

    def test_name_is_title_cased(self):
        claim = detect_name_claim("moi c'est thomas")
        assert claim is not None
        assert claim.name == "Thomas"


class TestFalsePositives:
    """The expensive failures: states and roles read as names."""

    @pytest.mark.parametrize("message", [
        "je suis fatigué",
        "je suis désolée",
        "je suis pas sûr",
        "je suis développeur",
        "je suis en retard",
        "je suis là",
        "je suis vraiment content",
        "i'm tired",
        "i'm not sure",
        "je suis d'accord",
        "je suis toujours partant",
    ])
    def test_states_are_not_names(self, message):
        assert detect_name_claim(message) is None

    @pytest.mark.parametrize("message", [
        "",
        "   ",
        "ok",
        "salut ça va ?",
        "tu te souviens de ce qu'on disait hier ?",
        "je pense que c'est une bonne idée",
    ])
    def test_ordinary_messages_yield_nothing(self, message):
        assert detect_name_claim(message) is None

    def test_digits_are_not_names(self):
        assert detect_name_claim("je m'appelle Agent007") is None

    def test_absurdly_long_input_is_skipped(self):
        assert detect_name_claim("je m'appelle Thomas " + "x" * 5000) is None


class TestDenial:

    @pytest.mark.parametrize("message,expected", [
        ("je ne suis pas Thomas", "Thomas"),
        ("je suis pas Julie", "Julie"),
        ("c'est pas Marc", "Marc"),
        ("ce n'est pas Sophie", "Sophie"),
        ("i'm not Mike", "Mike"),
    ])
    def test_detects_denials(self, message, expected):
        claim = detect_name_claim(message)
        assert claim is not None
        assert claim.name == expected
        assert claim.is_denial

    def test_denial_beats_the_claim_reading(self):
        """"je ne suis pas Thomas" also matches "je suis X" — the denial wins."""
        claim = detect_name_claim("non, je ne suis pas Thomas")
        assert claim is not None
        assert claim.kind == "denied"

    @pytest.mark.parametrize("message,expected", [
        ("attends, je ne suis pas Thomas en fait", "Thomas"),
        ("je ne suis pas Julie mais sa soeur", "Julie"),
        ("moi c'est Thomas au fait", "Thomas"),
        ("je m'appelle Alice et toi ?", "Alice"),
    ])
    def test_trailing_words_do_not_swallow_the_name(self, message, expected):
        """The two-word pattern is greedy: "Thomas en fait" captures
        "Thomas en", whose second word is a stop-word. Rejecting the whole
        fragment lost the name — and a missed denial leaves Mika calling a
        stranger by a friend's name, which is the expensive direction to fail.
        """
        claim = detect_name_claim(message)
        assert claim is not None, f"non détecté: {message!r}"
        assert claim.name == expected

    def test_two_word_names_still_survive(self):
        claim = detect_name_claim("je m'appelle Jean Dupont")
        assert claim is not None
        assert claim.name == "Jean Dupont"


class TestCorroboration:

    def test_no_facts_no_score(self):
        assert corroboration_score("peu importe", []) == (0.0, "")

    def test_single_shared_word_is_coincidence(self):
        score, _ = corroboration_score(
            "j'aime bien la musique", ["Thomas aime la musique classique"],
        )
        assert score == 0.0

    def test_multiple_shared_terms_score(self):
        score, reason = corroboration_score(
            "notre concert de jazz à Toulouse était incroyable",
            ["Thomas et moi sommes allés à un concert de jazz à Toulouse"],
        )
        assert score > 0.0
        assert "recoupe" in reason

    def test_stopwords_do_not_corroborate(self):
        score, _ = corroboration_score(
            "avec dans pour mais elle nous vous cette",
            ["avec dans pour mais elle nous vous cette"],
        )
        assert score == 0.0

    def test_score_is_bounded(self):
        fact = "concert jazz Toulouse festival musique guitare batterie"
        score, _ = corroboration_score(fact, [fact])
        assert 0.0 < score <= 1.0

    def test_best_matching_fact_is_reported(self):
        score, reason = corroboration_score(
            "le festival de guitare à Toulouse",
            [
                "Thomas déteste les épinards",
                "Thomas était au festival de guitare à Toulouse",
            ],
        )
        assert score > 0.0
        assert "festival" in reason
