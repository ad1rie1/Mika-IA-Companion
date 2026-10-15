"""Contrat de ``transcript`` : le fil de conversation.

Un message a pour identifiant le ``seq`` de l'événement qui l'a créé
(perception reçue, ou énoncé visible) : questions et réponses partagent une
seule suite, strictement croissante, stable aux reconstructions.
"""

from __future__ import annotations

from functools import cache

from sqlalchemy import BigInteger, Column, Double, Index, Table

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.ports.sql import HANDLE_MAX, Key, LongText, projection_table

OWNER = "transcript"

#: Instant du dernier message reçu de cette adresse (0 si jamais).
LAST_FROM = FactFamily("transcript.last_from", arg=str, type=int)
#: Instant du dernier message qu'elle a envoyé à cette adresse (0 si jamais).
LAST_TO = FactFamily("transcript.last_to", arg=str, type=int)
#: Identifiant du dernier message du fil.
HEAD = FactKey("transcript.head", type=int)

THREAD_TABLE = "thread"


@cache
def thread_table(sfx: str = "") -> Table:
    """``thread`` (suffixée de sa version) : une ligne par message visible — ce que relisent toutes les facultés qui
    lisent le fil (ADR 0101 : déclarée pour les deux moteurs, hors des migrations ; elle évolue par sa version).

    ``id`` est le ``seq`` de l'événement qui a créé le message. ``person`` (l'adresse) et ``room`` sont des clés
    bornées à ``HANDLE_MAX`` : la projection y range une valeur plus longue par ``fit`` plutôt que de faire échouer
    l'ajout, et une lecture par la valeur brute ne la trouve pas. ``folded`` : le texte replié (``fold_text`` : casse
    et accents ignorés), ce que cherche la console — pareil sur les deux moteurs, là où ``LIKE`` ne l'est pas ; la
    projection l'écrit toujours (nul seulement pour une ligne posée à la main, que la recherche ne trouve pas).
    ``tools`` : pour un de ses messages, les outils dont elle s'est servie pour l'écrire (``rt.Utterance.tools``, en
    JSON : ``[[nom, réussi], …]``, leurs noms seulement) ; nul pour un message reçu (ADR 0108). ``verdict`` et
    ``verdict_note`` : pour un de ses messages, l'avis de son opératrice (``VERDICT_*``) et ce qu'elle a écrit avec
    — ce qu'elle aurait dû dire, ou pourquoi (ADR 0113) ; nuls sinon."""
    name = f"{THREAD_TABLE}{sfx}"
    return projection_table(
        name,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("at", BigInteger, nullable=False),
        Column("role", LongText, nullable=False),
        Column("person", Key(HANDLE_MAX), nullable=False),
        Column("channel", LongText),
        Column("room", Key(HANDLE_MAX)),
        Column("source", LongText),
        Column("kind", LongText),
        Column("text", LongText, nullable=False),
        Column("client_msg_id", LongText),
        Column("reply_to", BigInteger),
        Column("emotion", LongText),
        Column("emotion_intensity", Double),
        Column("attachments", LongText),
        Column("typed", BigInteger),
        Column("unanswered", LongText),
        Column("tools", LongText),
        Column("folded", LongText),
        Column("verdict", LongText),
        Column("verdict_note", LongText),
        Index(f"{name}_person", "person", "id"),
        Index(f"{name}_room", "room", "id"),
    )


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
    #: qui parle dans les messages repliés (un salon : tous) : l'oubli de l'un efface le résumé (ADR 0082)
    speakers: tuple[str, ...] = ()
    #: les messages tus dans le résumé, sources de ce qu'on lui a demandé de garder pour soi (un salon)
    withheld: tuple[int, ...] = ()


class SummaryReset(Payload):
    """Le résumé d'un fil est à refaire : un secret dit dans ce salon (déclaré après coup) y était repris. Le fil
    se replie de nouveau, ce secret tu (ADR 0082)."""

    person: str
    reason: str = ""


#: l'avis de son opératrice sur une de ses réponses (ADR 0113)
VERDICT_OK = "ok"
VERDICT_KO = "ko"
VERDICTS = (VERDICT_OK, VERDICT_KO)


class Judged(Payload):
    """Son opératrice dit, depuis le chat ou la console, si une de ses réponses était adaptée — et, si elle veut, ce
    qu'elle aurait dû dire ou pourquoi : un exemple concret pour sa voix (ADR 0113). Ce n'est pas quelque chose
    qu'elle vit : aucune autre faculté ne le lit (l'événement n'est pas public), seul le fil le garde.
    ``verdict`` vide : l'avis retiré."""

    #: le message jugé (son ``seq``, l'identifiant du message dans le fil)
    seq: int
    verdict: str
    comment: Content | None = None
    #: qui juge (l'adresse de l'opératrice)
    by: str = ""
    #: à qui elle répondait : l'oubli de cette personne emporte l'avis
    person: str = ""


COMPACTED = event_type("transcript.compacted", OWNER, Compacted, public=True, content=("summary",),
                       subjects=("person", "speakers"))
SUMMARY_RESET = event_type("transcript.summary_reset", OWNER, SummaryReset, public=True)
JUDGED = event_type("transcript.judged", OWNER, Judged, content=("comment",), subjects=("person", "by"))
