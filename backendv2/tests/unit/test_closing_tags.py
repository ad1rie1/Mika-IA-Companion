"""Ce qu'elle dit s'arrête à ses balises de fin.

2026-10-14, banc de conversation (Sonnet) : après « [EMOTION: …] [EN_FACE: tired 0.4] », le modèle a ajouté
« Correction de balise : [EN_FACE: anxious 0.2, neutral 0.3] » — les balises retirées, « Correction de balise : »
arrivait à la personne. Passé la première ligne de balises qui suit sa parole, seules les balises comptent ; une
balise en tête de réponse ne coupe rien.
"""

from __future__ import annotations

from mika.faculties.expression import parse

LEAKED = ("Aïe, mal dormi un dimanche. Courage pour la journée.\n\n[EMOTION: happy 0.3, thinking 0.2]\n"
          "[EN_FACE: tired 0.4]\n\nCorrection de balise : [EN_FACE: anxious 0.2, neutral 0.3]")


def test_what_follows_her_closing_tags_is_not_said():
    text, notes = parse(LEAKED)
    assert text == "Aïe, mal dormi un dimanche. Courage pour la journée."
    assert notes["emotion"] == "happy:0.300,thinking:0.200"
    assert "their_feeling" in notes  # les balises qui suivent se lisent toujours


def test_a_tag_before_her_words_cuts_nothing():
    assert parse("[EMOTION: happy 0.4] Coucou toi, ça va ?")[0] == "Coucou toi, ça va ?"
    assert parse("Coucou toi. [EMOTION:happy:0.4]")[0] == "Coucou toi."
    two = "Premier paragraphe.\n\nDeuxième paragraphe, sans balise au milieu.\n[EMOTION: calm 0.3]"
    assert parse(two)[0] == "Premier paragraphe.\n\nDeuxième paragraphe, sans balise au milieu."
