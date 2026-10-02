"""Contrat d'``expression`` : la balise déclarée, telle qu'un énoncé la porte ;
le murmure, tel que son épisode le dit."""

from __future__ import annotations

OWNER = "expression"

#: Clé d'annotation d'un énoncé : ``"sad:0.800"`` (``vocab.affect.Declared``).
EMOTION_ANNOTATION = "emotion"
#: Un nom hors des 29 (compté, jamais une impulsion).
UNKNOWN_EMOTION_ANNOTATION = "emotion_unknown"
#: Clé d'annotation d'un énoncé qui pose une question (``"1"``) : on en attend la réponse.
QUESTION_ANNOTATION = "question"

#: La raison d'un épisode de murmure : ``"murmure:<adresse>"`` — l'adresse de la personne à qui elle
#: s'apprête à écrire (le murmure lui-même ne s'adresse à personne : il se montre sur ses écrans à elle).
MURMUR = "murmure"
#: … ou ``"murmure-sans-suite:<adresse>"`` : elle y pense, puis se ravise — l'initiative ne suit pas.
MURMUR_ADRIFT = "murmure-sans-suite"
