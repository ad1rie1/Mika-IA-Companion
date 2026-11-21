"""``transcript`` : le fil de conversation.

Quand le fil avec quelqu'un devient long, son début — déjà relu par la
mémoire — se replie en un résumé (``compact``) : le modèle voit le résumé puis
les derniers échanges ; le verbatim reste au journal et dans l'historique.

Un message = l'événement qui l'a créé (perception reçue, énoncé visible) ;
son identifiant est le ``seq`` de cet événement. Le texte vit dans la
projection T0 ``thread`` (même transaction que l'ajout : un client qui
demande l'historique voit toujours le message qu'on vient de lui annoncer).
Les jetons prosodiques y sont retirés : ils sont pour la voix, pas pour le
fil que relisent le modèle et la personne.

L'historique du prompt est le fil tel qu'on le perçoit (ADR 0041) : un tour
qui arrive après un silence porte un repère de temps (« [le lendemain, mardi
14h13] »), calculé en jours vécus et seulement entre deux messages — stable
d'un prompt à l'autre ; dans un salon chacun parle sous son nom ; ses propres
tours gardent leur balise d'émotion ; la fenêtre avance par paquets. Un message
resté sans réponse le dit dans son repère, en mots et sans détail technique
(« [mardi 14h13 — tu n'as pas pu lui répondre : une panne] », « [tu avais
choisi de ne rien répondre] ») : comme la personne, elle sait qu'elle n'a pas
répondu.

En mode pro, son opératrice ouvre des fils de travail (ADR 0164) : chaque
message en porte l'identifiant (``strand``), choisi par le client. Le fil privé
ne les relit pas ; un fil de travail ne relit que ses messages, sous son titre
et sa petite description (``transcript.strand_set``, le dernier réglage vaut).
Son opératrice peut aussi forcer l'effort de réflexion des réponses qu'elle reçoit
(ADR 0287), pour toute sa conversation ou pour un fil (``transcript.effort_set``) :
l'épisode qui lui répond le lit quand il compose.
Tout reste au journal : sa mémoire les consolide comme le reste de sa vie.

Carte des modules (le sens de leurs imports : ``marks`` ← ``faculty`` ← ``thread`` ← ``history`` ; ``compact`` lit
``faculty``, ``thread`` et ``marks``) :

- ``faculty`` : ses réglages (``TranscriptParams``), l'état (``TranscriptState``), la faculté (``TRANSCRIPT``), ses
  réducteurs — dont l'oubli d'une personne et l'expiration d'une inconnue de passage — et ses faits
  (``transcript.head``, ``transcript.last_from``, ``transcript.last_to``) ;
- ``marks`` : les repères de temps du fil (``gap_mark``, ``opening_mark``, ``read_late``) et celui d'un message resté
  sans réponse (``left_unanswered``) ;
- ``thread`` : le fil matérialisé — les projections ``thread``, ``strands`` et ``thread_efforts`` — et les requêtes
  qui le relisent (``recent``, ``after``, ``private_thread``, ``strand_thread``, ``room_thread``, ``strand_history``,
  ``strands_of``, ``efforts_of``…) ;
- ``history`` : l'historique du prompt — l'enrichisseur ``thread``, les tours datés (``thread_turns``), sa balise
  relue (``tagged``), ce qu'elle relit en tête d'un fil de travail (``strand_about``), la section ``history`` ;
- ``compact`` : le repli des longs fils en un résumé (processus ``transcript.compact``) ;
- ``actions`` : juger une de ses réponses, régler un fil de travail, forcer l'effort d'une conversation ou d'un fil ;
- ``inspect`` : ce que la console montre du fil.
"""

from __future__ import annotations

# isort: off
from mika.faculties.transcript import faculty  # noqa: F401
from mika.faculties.transcript import marks  # noqa: F401
from mika.faculties.transcript import thread  # noqa: F401
from mika.faculties.transcript import history  # noqa: F401
from mika.faculties.transcript import compact  # noqa: F401
from mika.faculties.transcript import actions  # noqa: F401
from mika.faculties.transcript import inspect  # noqa: F401
# isort: on
from mika.faculties.transcript.compact import Compact
from mika.faculties.transcript.faculty import TRANSCRIPT, TranscriptParams, TranscriptState
from mika.faculties.transcript.history import strand_about, tagged, thread_turns
from mika.faculties.transcript.marks import gap_mark, opening_mark, read_late
from mika.faculties.transcript.thread import (
    Thread,
    after,
    asked_effort,
    effort_for,
    efforts_of,
    recent,
    strand_history,
    strands_of,
    window_start,
)

__all__ = [
    "TRANSCRIPT",
    "Compact",
    "Thread",
    "TranscriptParams",
    "TranscriptState",
    "after",
    "asked_effort",
    "effort_for",
    "efforts_of",
    "gap_mark",
    "opening_mark",
    "read_late",
    "recent",
    "strand_about",
    "strand_history",
    "strands_of",
    "tagged",
    "thread_turns",
    "window_start",
]
