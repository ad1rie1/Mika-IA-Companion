"""« Corriger » (ADR 0307) : ce qui revient du modèle est relu avant de remplacer ce que tu as écrit — débarrassé de ce
qu'il ajoute autour, entre les blancs de bord de ton texte ; ses corrections comptées (un mot, un signe, un blanc) ; une
réponse qui ne ressemble plus au texte (une reformulation, une réponse au message) refusée. Les accents et les
majuscules ne comptent pas pour juger de la ressemblance."""

from __future__ import annotations

from mika.app.me.writing import changes, cleaned, faithful

TEXT = "Bonjour Albert, je te renvoi le fichier corriger demain matin.\n"


def test_what_it_wraps_around_goes_and_your_edges_stay():
    assert cleaned("« Bonjour Albert, je te renvoie le fichier corrigé demain matin. »", TEXT) == \
        "Bonjour Albert, je te renvoie le fichier corrigé demain matin.\n"
    assert cleaned("```\nsalut ça va\n```", "  salu ca va") == "  salut ça va"
    assert cleaned("« entre guillemets »", "« entre guillemet »") == "« entre guillemets »"  # les tiens restent


def test_each_fault_counts_once_spaces_included():
    fixed = "Bonjour Albert, je te renvoie le fichier corrigé demain matin.\n"
    assert changes(TEXT, fixed) == 2
    assert changes("Ça va?", "Ça va ?") == 1
    assert changes(TEXT, TEXT) == 0


def test_a_rewrite_is_not_a_correction():
    assert faithful("a cote de ca", "à côté de ça")  # les accents ne comptent pas
    assert faithful(TEXT, "Bonjour Albert, je te renvoie le fichier corrigé demain matin.")
    assert not faithful("t'es dispo demain ?", "Bien sûr, je suis disponible demain à 14 h, que veux-tu faire ?")
    assert not faithful("je te renvoi le fichier", "Voici le texte corrigé : je te renvoie le fichier, comme convenu.")
