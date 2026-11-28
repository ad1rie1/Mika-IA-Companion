"""« Corriger » (ADR 0307) : les mots ne changent pas, quoi que le modèle rende. Sa réponse est débarrassée de ce
qu'il met autour, posée entre les blancs de bord de ton texte, puis alignée mot par mot : seules s'appliquent les
corrections qui ne touchent pas aux mots (accents, casse, ponctuation et ses espaces, un mot collé, coupé ou redoublé,
une forme proche) ; un mot ajouté ou retiré, un chiffre changé, un mot remplacé par un autre, un préambule sont écartés
et comptés. Un long mail s'aligne en un instant, quoi qu'il contienne."""

from __future__ import annotations

import time

import pytest

from mika.app.me.writing import cleaned, merged

TEXT = "Bonjour Albert, je te renvoi le fichier corriger demain matin.\n"
FIXED = "Bonjour Albert, je te renvoie le fichier corrigé demain matin.\n"


def fix(text: str, answer: str) -> tuple[str, int, int]:
    return merged(text, cleaned(answer, text))


def test_what_it_wraps_around_goes_and_your_edges_stay():
    assert cleaned("« Bonjour Albert, je te renvoie le fichier corrigé demain matin. »", TEXT) == FIXED
    assert cleaned("```\nsalut ça va\n```", "  salu ca va") == "  salut ça va"
    # tes guillemets restent, et deux citations ne sont pas une paire qui enveloppe tout
    assert cleaned("« entre guillemets »", "« entre guillemet »") == "« entre guillemets »"
    assert cleaned("« Oui » pour lundi, et pour mardi « non »", '"Oui" pour lundi, et pour mardi "non"') == \
        "« Oui » pour lundi, et pour mardi « non »"


@pytest.mark.parametrize(("text", "answer", "expected"), [
    (TEXT, FIXED, (FIXED, 2, 0)),
    ("Ses ok", "C'est OK", ("C'est OK", 2, 0)),
    ("sa va?", "ça va ?", ("ça va ?", 2, 0)),
    ("sa", "ça", ("ça", 1, 0)),
    ("quelque soit le jour", "quel que soit le jour", ("quel que soit le jour", 1, 0)),
    ("parceque", "parce que", ("parce que", 1, 0)),
    ("je je viens", "je viens", ("je viens", 1, 0)),
    ("Salut. ca va? oui", "Salut, ça va ? Oui.", ("Salut, ça va ? Oui.", 5, 0)),
])
def test_an_ordinary_correction_goes_through(text, answer, expected):
    assert fix(text, answer) == expected


@pytest.mark.parametrize(("text", "answer", "expected"), [
    ("Je peux pas venir lundi", "Je peux venir lundi", ("Je peux pas venir lundi", 0, 1)),  # un mot retiré
    ("je peux pas", "je ne peux pas", ("je peux pas", 0, 1)),  # un mot ajouté
    ("Je refuse ta proposition.", "J'accepte ta proposition.", ("Je refuse ta proposition.", 0, 1)),
    ("ça coute 300 euros", "ça coûte 500 euros", ("ça coûte 300 euros", 1, 1)),  # le chiffre reste, l'accent passe
    ("lundi a 14h", "mardi à 14 h", ("lundi à 14 h", 2, 1)),
    (TEXT, "Voici le texte corrigé :\n\n" + FIXED, (FIXED, 2, 1)),  # le préambule écarté, les fautes corrigées
    ("Bonjour Albert", "Bien sûr Albert", ("Bonjour Albert", 0, 1)),  # pas deux mots pour un, sauf une élision
    # une réponse au message plutôt qu'une correction : rien n'en est posé, pas même sa ponctuation
    (TEXT, "Bien sûr Albert ! Je t'envoie tout ça demain, promis.\n", (TEXT, 0, 5)),
])
def test_what_touches_the_words_is_set_aside_and_counted(text, answer, expected):
    assert fix(text, answer) == expected


def test_a_long_mail_aligns_in_an_instant_whatever_it_holds():
    """Vingt mille signes, répétitifs ou d'une seule phrase, corrigés ou réécrits : jamais plus d'une seconde (le
    calcul est fait hors de la boucle du serveur, mais il ne doit pas la retenir longtemps)."""
    long = ("je te renvoi le fichier corriger demain matin, a plus tard. " * 340)[:20_000]
    one = long.replace(". ", ", ")
    rewritten = "Tout autre chose, vraiment rien à voir. " * 500
    for text, answer, expected in ((long, long.replace("renvoi ", "renvoie "), long.replace("renvoi ", "renvoie ")),
                                   (one, one.replace("corriger", "corrigé"), one.replace("corriger", "corrigé")),
                                   (one, rewritten, one)):
        t0 = time.perf_counter()
        fixed, _changes, _refused = merged(text, answer)
        assert time.perf_counter() - t0 < 1.0
        assert fixed == expected  # jamais tronqué, jamais réécrit
