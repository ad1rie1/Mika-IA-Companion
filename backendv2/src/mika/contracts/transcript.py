"""Contrat de ``transcript`` : le fil de conversation.

Un message a pour identifiant le ``seq`` de l'événement qui l'a créé
(perception reçue, ou énoncé visible) : questions et réponses partagent une
seule suite, strictement croissante, stable aux reconstructions.
"""

from __future__ import annotations

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "transcript"

#: Instant du dernier message reçu de cette adresse (0 si jamais).
LAST_FROM = FactFamily("transcript.last_from", arg=str, type=int)
#: Instant du dernier message qu'elle a envoyé à cette adresse (0 si jamais).
LAST_TO = FactFamily("transcript.last_to", arg=str, type=int)
#: Identifiant du dernier message du fil.
HEAD = FactKey("transcript.head", type=int)

THREAD_TABLE = "thread"

#: Pourquoi un message reçu est resté sans réponse pour de bon — la colonne ``unanswered`` du fil, nulle pour un
#: message répondu, encore en attente ou qui ne lui était pas adressé (``EpisodeEnded.unanswered``) : elle a
#: choisi de se taire, une panne, un délai dépassé, une question lue trop tard.
UNANSWERED_ABSTAINED = "abstained"
UNANSWERED_FAILED = "failed"
UNANSWERED_TIMEOUT = "timeout"
UNANSWERED_LATE = "late"


class Compacted(Payload):
    """Le début du fil avec une personne, replié en un résumé (les messages
    restent au journal ; seul ce que voit le modèle change)."""

    person: str
    upto: int
    summary: Content
    count: int = 0
    call_id: str = ""
    model: str = ""


COMPACTED = event_type("transcript.compacted", OWNER, Compacted, public=True, content=("summary",),
                       subjects=("person",))
