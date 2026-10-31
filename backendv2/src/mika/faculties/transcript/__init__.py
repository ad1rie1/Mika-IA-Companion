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
Tout reste au journal : sa mémoire les consolide comme le reste de sa vie.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import partial
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, delete, false, func, select, update

from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, MINUTE, local, local_date_of_night
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, Faculty, Tier, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Disclosure,
    InspectContext,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    describe_error,
    paginate,
)
from mika.kernel.prompt import ChatTurn, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.delivery import TOO_LATE
from mika.ports.llm import LLMRequest, Message
from mika.ports.llm_budget import fit_by_halving, halved
from mika.ports.paging import fold_text
from mika.ports.sql import HANDLE_MAX, fit, json_values, upsert
from mika.ports.store import Sql
from mika.vocab.affect import Declared, emotion_cell, strip_prosody
from mika.vocab.circadian import DAYS_FR, MONTHS_FR
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import clean_display_name, fold, is_internal
from mika.vocab.phrasebook import phrase, phrases

#: Messages relus au plus pour composer l'historique (le budget coupe ensuite).
THREAD_WINDOW = 320
#: Le début de cette fenêtre avance par paquets de tant de messages.
WINDOW_STEP = 20
#: Un message qui arrive après un tel silence porte un repère de temps.
MARK_AFTER = 20 * MINUTE


class TranscriptParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window: Annotated[int, Knob(
        label="Messages relus pour l'historique", group="Fil", lo=5, hi=500,
        help="Combien de messages du fil (après le dernier résumé) sont relus pour composer l'historique d'un "
             "tour ; le budget du prompt en coupe ensuite le début s'il le faut.")] = THREAD_WINDOW
    window_step: Annotated[int, Knob(
        label="Le début de l'historique avance par paquets de (messages)", group="Fil", lo=1, hi=250,
        help="Le début de l'historique ne glisse pas à chaque message : il avance par paquets de tant de messages "
             "(au plus la moitié de la fenêtre), si bien que le début du prompt reste identique d'un tour à "
             "l'autre et reste en cache. 1 : il glisse à chaque message.")] = WINDOW_STEP
    mark_after_us: Annotated[int, Knob(
        label="Repère de temps après un silence de", group="Fil", lo=5 * MINUTE, hi=DAY,
        help="Dans l'historique, un message qui arrive après un tel silence est précédé d'un repère de temps "
             "(« [25 minutes plus tard] », « [plus tard, vers 17h] », « [le lendemain, mardi 14h13] ») : elle sait "
             "quand chaque chose a été dite, et depuis combien de temps on ne s'était pas parlé.")] = MARK_AFTER
    #: au-delà de tant de messages depuis le dernier résumé, le début se replie…
    compact_after: Annotated[int, Knob(
        label="Résumer au-delà de (messages)", group="Résumé des longs fils", lo=20, hi=2000,
        help="Quand le fil avec quelqu'un compte plus de messages que cela depuis son dernier résumé, son début "
             "(déjà relu par la mémoire) se replie en un résumé : un appel au modèle.")] = 120
    #: … en gardant les derniers tels quels
    keep: Annotated[int, Knob(
        label="Messages gardés tels quels", group="Résumé des longs fils", lo=10, hi=1000,
        help="Les derniers messages que le résumé laisse intacts ; un repli n'a lieu que s'il reste assez de "
             "messages à replier au-delà (ci-dessous).")] = 60
    compact_min_fold: Annotated[int, Knob(
        label="Messages à replier au moins", group="Résumé des longs fils", lo=2, hi=500,
        help="Un repli n'a lieu que s'il y a au moins tant de messages déjà relus par la mémoire à replier : pas "
             "un appel au modèle pour trois phrases.")] = 10
    compact_batch: Annotated[int, Knob(
        label="Messages repliés par appel", group="Résumé des longs fils", lo=20, hi=2000,
        help="Un appel replie au plus tant de messages, les plus anciens d'abord ; un retard se rattrape en "
             "plusieurs passages plutôt qu'en un prompt démesuré.")] = 200
    compact_retry_us: Annotated[int, Knob(
        label="Réessayer un repli après", group="Résumé des longs fils", lo=MINUTE, hi=DAY,
        help="Si l'appel au modèle échoue, le repli suivant attend ce délai : pas de rafale d'appels.")] = 10 * MINUTE
    compact_max_tokens: Annotated[int, Knob(
        label="Longueur d'un résumé (jetons)", group="Résumé des longs fils", lo=200, hi=4000,
        help="La réponse du modèle qui résume est bornée à tant de jetons.")] = 800


@dataclass(frozen=True, slots=True)
class TranscriptState:
    head: int = 0
    last_from: FrozenDict[str, int] = field(default_factory=FrozenDict)
    last_to: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: personne → (dernier message résumé, référence du texte du résumé)
    summaries: FrozenDict[str, tuple[int, str]] = field(default_factory=FrozenDict)
    #: fil → qui parlait dans ce qu'il replie, et les messages qu'il tait (ADR 0082) ; vide : un résumé d'avant
    speakers: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)
    withheld: FrozenDict[str, tuple[int, ...]] = field(default_factory=FrozenDict)


#: v2 : un résumé sait qui parlait (l'oubli de l'un l'efface) et ce qu'il tait ; un secret déclaré après coup le fait
#: refaire (ADR 0082)
TRANSCRIPT = Faculty("transcript", state=TranscriptState, init=lambda p: TranscriptState(), params=TranscriptParams,
                     state_version=2)
TRANSCRIPT.declare(c.COMPACTED, c.SUMMARY_RESET, c.JUDGED, c.STRAND_SET)


def _params(p: TranscriptParams | None) -> TranscriptParams:
    return p if p is not None else TranscriptParams()


@TRANSCRIPT.reducer(c.COMPACTED)
def _compacted(s: TranscriptState, e, cx) -> TranscriptState:
    d = e.data
    ref = d.summary.ref or ""
    withheld = (*s.withheld.get(d.person, ()), *d.withheld)
    return replace(s, summaries=s.summaries.set(d.person, (d.upto, ref)),
                   speakers=s.speakers.set(d.person, tuple(sorted({*s.speakers.get(d.person, ()), *d.speakers}))),
                   withheld=s.withheld.set(d.person, tuple(sorted(set(withheld)))) if withheld else s.withheld)


def _without(s: TranscriptState, person: str) -> TranscriptState:
    return replace(s, summaries=s.summaries.delete(person), speakers=s.speakers.delete(person),
                   withheld=s.withheld.delete(person))


@TRANSCRIPT.reducer(c.SUMMARY_RESET)
def _reset(s: TranscriptState, e, cx) -> TranscriptState:
    return _without(s, e.data.person)


@TRANSCRIPT.reducer(SUBJECT_FORGOTTEN)
def _speaker_forgotten(s: TranscriptState, e, cx) -> TranscriptState:
    """L'oubli de quelqu'un qui parlait dans un salon efface le résumé de ce salon (son texte, déjà, par ses sujets) ;
    un résumé de salon d'avant, qui ne dit pas qui parlait, aussi — dans le doute (ADR 0082)."""
    who = e.data.subject
    for person in [p for p in s.summaries if p.startswith("room:")
                   and (who in s.speakers.get(p, ()) or not s.speakers.get(p))]:
        s = _without(s, person)
    # et le résumé de son propre fil (son texte est déjà effacé par ses sujets) ; son dernier message et le dernier
    # vers elle restent : un compte qui existe garde son fil (audit du 2026-10-26)
    return _without(s, who)


@TRANSCRIPT.reducer(rt.PERCEPTION_RECEIVED)
def _received(s: TranscriptState, e, cx) -> TranscriptState:
    return replace(s, head=e.seq, last_from=s.last_from.set(e.data.handle, e.at))


@TRANSCRIPT.reducer(rt.UTTERANCE)
def _uttered(s: TranscriptState, e, cx) -> TranscriptState:
    if not e.data.visible:
        return s
    s = replace(s, head=e.seq)
    if e.data.target:
        s = replace(s, last_to=s.last_to.set(e.data.target, e.at))
    return s


@TRANSCRIPT.fact(c.LAST_FROM)
def _last_from(s: TranscriptState, cx, handle: str) -> int:
    return s.last_from.get(handle, 0)


@TRANSCRIPT.fact(c.LAST_TO)
def _last_to(s: TranscriptState, cx, handle: str) -> int:
    return s.last_to.get(handle, 0)


@TRANSCRIPT.fact(c.HEAD)
def _head(s: TranscriptState, cx) -> int:
    return s.head


# ── Le fil matérialisé ────────────────────────────────────────────────────

#: ``typed`` : avec des pièces jointes, combien de caractères du début de ``text`` la personne a tapés (le reste
#: est ce qu'elle en a perçu, pour le prompt) ; nul quand il n'y a rien à séparer (version 2 de la table).
#: ``unanswered`` : pourquoi un message reçu est resté sans réponse pour de bon (``c.UNANSWERED_*``), posé par la
#: fin d'épisode qui l'a réglé ; nul sinon (version 3). ``tools`` : les outils dont elle s'est servie pour écrire un
#: de ses messages (version 6, ADR 0108). ``mode`` : le mode dans lequel le message a été écrit (version 8, ADR 0116)
#: ; ``strand`` : son fil de travail (version 9, ADR 0164)
_COLUMNS = ("id", "at", "role", "person", "channel", "room", "source", "kind", "text", "client_msg_id",
            "reply_to", "emotion", "emotion_intensity", "attachments", "typed", "unanswered", "tools", "verdict",
            "verdict_note", "mode", "strand")


class Thread:
    """T0 : une ligne par message visible (``contracts.transcript.thread_table``)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(c.thread_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(c.thread_table(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = c.thread_table(sfx)
        rows = [_stored(row) for e in events if (row := _row(e)) is not None]
        if rows:
            upsert(sql, t, rows, keys=["id"])
        # après les lignes : une fin ne laisse sans réponse que des messages reçus avant elle
        for issue, seq in (pair for e in events if e.type.name == rt.EPISODE_ENDED.name for pair in _left(e.data)):
            sql.execute(update(t).where(t.c.id == seq, t.c.role == "user").values(unanswered=issue))
        # l'avis de son opératrice sur une de ses réponses (ADR 0113) : le dernier vaut ; un commentaire oublié ne
        # revient pas à la reconstruction
        for e in events:
            if e.type.name == c.JUDGED.name:
                d = e.data
                note = None if d.comment is None or _forgotten(d.comment) else (d.comment.text or None)
                sql.execute(update(t).where(t.c.id == d.seq, t.c.role == "assistant")
                            .values(verdict=d.verdict or None, verdict_note=note if d.verdict else None))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t = c.thread_table(sfx)
        sql.execute(delete(t).where(t.c.person == fit(subject, HANDLE_MAX)))


def _stored(row: tuple[Any, ...]) -> dict[str, Any]:
    """Une ligne telle qu'écrite : l'adresse et le salon bornés (``fit`` : jamais un ajout refusé pour une adresse
    trop longue), et le texte replié que cherche la console."""
    out = dict(zip(_COLUMNS, row, strict=True))
    out["person"] = fit(out["person"], HANDLE_MAX)
    out["room"] = fit(out["room"], HANDLE_MAX) if out["room"] is not None else None
    out["strand"] = fit(out["strand"], c.STRAND_MAX) if out["strand"] is not None else None
    out["folded"] = fold_text(out["text"])
    return out


def _forgotten(text: Any) -> bool:
    """Un texte relu après l'oubli de qui il concerne : sa référence reste, plus son texte."""
    return text is not None and getattr(text, "ref", None) is not None and getattr(text, "text", None) is None


def _row(e: Any) -> tuple[Any, ...] | None:
    d = e.data
    if _forgotten(getattr(d, "text", None)):
        # une reconstruction (une nouvelle version de la table) relit tout le journal : ce qui a été oublié ne revient
        # pas, ni en texte vide ni par les noms de ses pièces jointes (audit du lot L2 du 2026-10-03)
        return None
    if e.type.name == rt.PERCEPTION_RECEIVED.name:
        attachments = json.dumps([a.model_dump() for a in d.attachments], ensure_ascii=False) if d.attachments else "[]"
        text = d.text.text or ""
        typed = None if d.typed_chars is None else max(0, min(len(text), d.typed_chars))
        return (e.seq, e.at, "user", d.handle, d.channel, d.room, d.channel, "message", text,
                d.client_msg_id, None, None, None, attachments, typed, None, None, None, None, d.mode or None,
                d.strand)
    if e.type.name == rt.UTTERANCE.name and d.visible:
        declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
        # ce qui est parti avec son message : des identifiants seulement (leur nom, leur taille, leur sort sont à
        # leur propriétaire — l'écran les lui demande)
        sent = json.dumps([{"id": a} for a in d.attachments]) if d.attachments else "[]"
        return (e.seq, e.at, "assistant", d.target or "", d.channel, d.room, _source(d.kind), d.kind,
                strip_prosody(d.text.text or ""), None, d.reply_to,
                declared.emotion.value if declared else None, declared.intensity if declared else None, sent, None,
                None, _tools_of(d), None, None, d.mode or None, d.strand)
    return None


def _tools_of(d: rt.Utterance) -> str | None:
    """Les outils dont elle s'est servie pour écrire ce message, dans l'ordre et sans doublon : ``[[nom, réussi],
    …]`` en JSON — leurs noms seulement, jamais ce qu'elle leur a demandé (ce texte-là n'a pas de sujets déclarés,
    l'oubli ne l'atteindrait pas) ; nul sans outil."""
    seen: list[list[Any]] = []
    for tool in d.tools:
        pair = [tool.name, bool(tool.ok)]
        if pair not in seen:
            seen.append(pair)
    return json.dumps(seen) if seen else None


def _source(kind: str) -> str:
    return "conscience" if kind != Kind.REPLY else "reply"


#: comment une fin d'épisode qui laisse un message sans réponse se dit dans le fil (toute autre fin — un échec,
#: des tentatives épuisées, une file pleine, un arrêt — est une panne)
_ISSUES = {"abstained": c.UNANSWERED_ABSTAINED, "timeout": c.UNANSWERED_TIMEOUT}


def _issue(outcome: str, detail: str) -> str:
    """Pourquoi un message est resté sans réponse, en un mot : lu trop tard (repris au-delà du délai de réponse),
    elle s'est tue, un délai dépassé, une panne — jamais la cause technique, que seule la console détaille."""
    if detail.startswith(TOO_LATE):
        return c.UNANSWERED_LATE
    return _ISSUES.get(outcome, c.UNANSWERED_FAILED)


def _left(d: rt.EpisodeEnded) -> list[tuple[str, int]]:
    """Les messages qu'une fin laisse sans réponse pour de bon, chacun avec pourquoi — dans un journal plus ancien
    (``unanswered`` absent), ce que ``leaves_unanswered`` dit de ``reply_to``."""
    if d.unanswered is not None:
        seqs: tuple[int, ...] = d.unanswered
    elif d.reply_to is not None and d.leaves_unanswered(d.reply_to):
        seqs = (d.reply_to,)
    else:
        return []
    issue = _issue(d.outcome, d.detail)
    return [(issue, int(seq)) for seq in seqs]


#: version 9 : le fil de travail d'un message (``strand``, ADR 0164) ;
#: version 8 : le mode dans lequel un message a été écrit (``mode``, ADR 0116) ;
#: version 7 : l'avis de son opératrice sur ses réponses (``verdict``, ``verdict_note``, ADR 0113), d'où
#: ``transcript.judged`` ; version 6 : la colonne ``tools`` (les outils dont elle s'est servie pour écrire un de ses messages, ADR 0108) ;
#: version 5 : la table déclarée pour les deux moteurs (ADR 0101), et ``folded`` (le texte replié que cherche la
#: console) ; version 3 : la colonne ``unanswered`` (pourquoi un message reçu est resté sans réponse), d'où les fins
#: d'épisode ; version 2 : la colonne ``typed`` (ce que la personne a tapé, à part de ce que ses pièces jointes ont
#: donné) — la table se reconstruit depuis le journal au premier démarrage
TRANSCRIPT.projector(c.THREAD_TABLE, version=9, tier=Tier.T0,
                     types=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, rt.EPISODE_ENDED, c.JUDGED])(Thread)


class Strands:
    """T0 : le dernier réglage de chaque fil de travail (``contracts.transcript.strands_table``, ADR 0164). Un
    titre ou une description oubliés ne reviennent pas à la reconstruction."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(c.strands_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(c.strands_table(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = c.strands_table(sfx)
        rows = [{"person": fit(e.data.person, HANDLE_MAX), "strand": fit(e.data.strand, c.STRAND_MAX), "at": e.at,
                 "title": _kept(e.data.title), "description": _kept(e.data.description),
                 "archived": bool(e.data.archived)}
                for e in events if e.type.name == c.STRAND_SET.name]
        if rows:
            upsert(sql, t, rows, keys=["person", "strand"])

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t = c.strands_table(sfx)
        sql.execute(delete(t).where(t.c.person == fit(subject, HANDLE_MAX)))


def _kept(text: Any) -> str | None:
    """Un texte réglé tel que la projection le garde : vide ou oublié, rien."""
    return None if text is None or _forgotten(text) else (text.text or None)


TRANSCRIPT.projector(c.STRANDS_TABLE, version=1, tier=Tier.T0, types=[c.STRAND_SET])(Strands)


def _columns() -> list[Any]:
    t = c.thread_table()
    return [t.c[n] for n in _COLUMNS]


def _messages_of(store: Any, *where: Any, newest_first: bool = True, limit: int | None = None) -> list[Any]:
    """Les lignes du fil qui répondent à ``where`` (les colonnes de ``_COLUMNS``), triées par numéro."""
    t = c.thread_table()
    query = select(*_columns()).where(*where).order_by(t.c.id.desc() if newest_first else t.c.id)
    return store.query_mind(query.limit(limit) if limit is not None else query)


def recent(store: Any, person: str, limit: int) -> list[dict[str, Any]]:
    """La fin du fil d'une personne, du plus ancien au plus récent."""
    t = c.thread_table()
    rows = _messages_of(store, t.c.person == person, limit=limit)
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def after(store: Any, person: str, after_id: int, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Tout ce qu'elle a manqué depuis ``after_id`` (les plus récents si ça
    dépasse ``limit``, et on le dit)."""
    t = c.thread_table()
    rows = _messages_of(store, t.c.person == person, t.c.id > after_id, limit=limit + 1)
    truncated = len(rows) > limit
    rows = rows[:limit]
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)], truncated


def thread_of(store: Any, person: str, limit: int, before: int | None = None, after: int = 0) -> list[dict[str, Any]]:
    """Le fil avec une adresse, entre ``after`` et ``before`` (le message en
    cours de réponse n'y est pas : il arrive comme dernier tour)."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    rows = _messages_of(store, t.c.person == person, t.c.id < bound, t.c.id > after, limit=limit)
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def oldest_after(store: Any, person: str, after: int, limit: int) -> list[dict[str, Any]]:
    """Les ``limit`` plus anciens messages du fil privé d'une adresse après
    ``after``, dans l'ordre : ce qu'un résumé replie en premier (il n'est relu
    qu'en privé, un salon n'a rien à y faire ; un fil de travail non plus)."""
    t = c.thread_table()
    rows = _messages_of(store, t.c.person == person, t.c.room.is_(None), t.c.strand.is_(None), t.c.id > after,
                        newest_first=False, limit=limit)
    return [dict(zip(_COLUMNS, r, strict=True)) for r in rows]


def _count(store: Any, *where: Any) -> int:
    t = c.thread_table()
    rows = store.query_mind(select(func.count()).select_from(t).where(*where))
    return int(rows[0][0]) if rows else 0


def count_after(store: Any, person: str, after: int) -> int:
    t = c.thread_table()
    return _count(store, t.c.person == person, t.c.room.is_(None), t.c.strand.is_(None), t.c.id > after)


def window_start(total: int, window: int, step: int) -> int:
    """Le rang du premier message montré sur ``total`` : les ``window`` derniers
    au plus, mais un début qui n'avance que par paquets de ``step`` (au plus la
    moitié de la fenêtre) — entre deux sauts, le début du fil, donc du prompt,
    ne bouge pas."""
    start = max(0, total - window)
    step = max(1, min(step, window // 2))
    return -(-start // step) * step


def _window(store: Any, where: Sequence[Any], window: int, step: int) -> list[dict[str, Any]]:
    limit = window
    if step > 1:
        total = _count(store, *where)
        limit = total - window_start(total, window, step)
    rows = _messages_of(store, *where, limit=limit)
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def private_thread(store: Any, handles: Sequence[str], limit: int, before: int | None = None,
                   after: int = 0, step: int = 1) -> list[dict[str, Any]]:
    """Le fil privé avec une personne, toutes ses adresses confondues (ce
    qu'elle a dit dans un salon n'y est pas : hors de son contexte ; ses fils
    de travail non plus, ADR 0164)."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    return _window(store, (t.c.person.in_(list(handles)), t.c.room.is_(None), t.c.strand.is_(None), t.c.id < bound,
                           t.c.id > after), limit, step)


def strand_thread(store: Any, handle: str, strand: str, limit: int, before: int | None = None,
                  step: int = 1) -> list[dict[str, Any]]:
    """Un fil de travail (ADR 0164) : ses seuls messages, rien d'autre de leur fil."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    return _window(store, (t.c.person == handle, t.c.strand == strand, t.c.id < bound), limit, step)


def strand_history(store: Any, handle: str, strand: str, before: int | None, limit: int) -> tuple[list[dict[str, Any]],
                                                                                                   bool]:
    """Les messages d'un fil de travail tels qu'un écran les relit : les ``limit`` derniers avant ``before`` (tous
    s'il est nul), du plus ancien au plus récent, et s'il en reste de plus anciens."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    rows = _messages_of(store, t.c.person == handle, t.c.strand == strand, t.c.id < bound, limit=limit + 1)
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows[:limit])], len(rows) > limit


def strand_setting(store: Any, handle: str, strand: str) -> dict[str, Any] | None:
    """Le dernier réglage d'un fil de travail (titre, description, archivé) ; ``None`` : jamais réglé."""
    t = c.strands_table()
    rows = store.query_mind(select(t.c.title, t.c.description, t.c.archived, t.c.at)
                            .where(t.c.person == handle, t.c.strand == strand))
    if not rows:
        return None
    title, description, archived, at = rows[0]
    return {"title": title or "", "description": description or "", "archived": bool(archived), "at": int(at)}


def strands_of(store: Any, handle: str) -> list[dict[str, Any]]:
    """Les fils de travail d'une adresse, du plus récemment actif au plus ancien : ceux qui ont des messages et ceux
    qu'on a seulement réglés. Pour chacun : son identifiant, son titre, sa description, archivé ou non, combien de
    messages, le premier et le dernier instant, et le début de son premier message (de quoi le nommer sans titre)."""
    t, st = c.thread_table(), c.strands_table()
    stats = store.query_mind(select(t.c.strand, func.count(), func.min(t.c.id), func.min(t.c.at), func.max(t.c.at))
                             .where(t.c.person == handle, t.c.strand.is_not(None)).group_by(t.c.strand))
    firsts = {int(first) for _s, _n, first, _a, _b in stats}
    openers = {int(i): str(text or "") for i, text in
               store.query_mind(select(t.c.id, t.c.text).where(t.c.id.in_(sorted(firsts))))} if firsts else {}
    out: dict[str, dict[str, Any]] = {}
    for strand, count, first, first_at, last_at in stats:
        out[str(strand)] = {"id": str(strand), "title": "", "description": "", "archived": False,
                            "count": int(count), "first_at": int(first_at), "last_at": int(last_at),
                            "opener": openers.get(int(first), "")}
    for strand, title, description, archived, at in store.query_mind(
            select(st.c.strand, st.c.title, st.c.description, st.c.archived, st.c.at).where(st.c.person == handle)):
        item = out.setdefault(str(strand), {"id": str(strand), "count": 0, "first_at": int(at), "last_at": int(at),
                                            "opener": ""})
        item.update(title=title or "", description=description or "", archived=bool(archived))
    return sorted(out.values(), key=lambda x: (-x["last_at"], x["id"]))


def room_thread(store: Any, room: str, limit: int, before: int | None = None, step: int = 1,
                after: int = 0) -> list[dict[str, Any]]:
    """Ce qui s'est dit dans un salon (public pour ce salon), tous ensemble."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    return _window(store, (t.c.room == room, t.c.id < bound, t.c.id > after), limit, step)


def _message(store: Any, seq: int) -> dict[str, Any] | None:
    t = c.thread_table()
    rows = _messages_of(store, t.c.id == seq)
    return dict(zip(_COLUMNS, rows[0], strict=True)) if rows else None


def _any(store: Any, *where: Any) -> bool:
    """Au moins un message du fil répond à ``where``."""
    t = c.thread_table()
    return bool(store.query_mind(select(t.c.id).where(*where).limit(1)))


# ── Les repères de temps ──────────────────────────────────────────────────

#: Avant cette heure, une heure de la nuit appartient encore à la veille : « le
#: lendemain » se compte en jours vécus, pas en passages de minuit.
DAY_STARTS_AT = 5


def _number(n: int) -> str:
    """Un nombre en lettres (de zéro à treize)."""
    return phrases("transcript.time.numbers")[n]


def _clock(dt: datetime) -> str:
    return phrase("transcript.time.clock", hour=dt.hour, minute=f"{dt.minute:02d}")


def _about(dt: datetime) -> str:
    """L'heure à la demi-heure près : « vers 17h », « vers 17h30 », « vers minuit »."""
    h, m = divmod(((dt.hour * 60 + dt.minute + 15) // 30 * 30) % (24 * 60), 60)
    if h == 0:
        return phrase("transcript.time.about_midnight_half") if m else phrase("transcript.time.about_midnight")
    if h == 12:
        return phrase("transcript.time.about_noon_half") if m else phrase("transcript.time.about_noon")
    return phrase("transcript.time.about_half", hour=h) if m else phrase("transcript.time.about_hour", hour=h)


def _lapse(minutes: int) -> str:
    """Un silence de moins de deux heures, dit comme on le dit (à cinq minutes près)."""
    m = max(5, round(minutes / 5) * 5)
    if m == 30:
        return phrase("transcript.time.half_hour_later")
    if m == 45:
        return phrase("transcript.time.three_quarters_later")
    if m < 55:
        return phrase("transcript.time.minutes_later", minutes=m)
    if m < 75:
        return phrase("transcript.time.hour_later")
    return phrase("transcript.time.hour_half_later") if m < 105 else phrase("transcript.time.two_hours_later")


def _day(dt: datetime) -> str:
    """Le jour et l'heure ; une heure de la nuit dit de quelle nuit il s'agit."""
    if dt.hour < DAY_STARTS_AT:
        return phrase("transcript.time.night_of", eve=DAYS_FR[(dt.weekday() - 1) % 7], weekday=DAYS_FR[dt.weekday()],
                      clock=_clock(dt))
    return phrase("transcript.time.day", weekday=DAYS_FR[dt.weekday()], clock=_clock(dt))


def _date(dt: datetime, year: bool) -> str:
    if year:
        return phrase("transcript.time.date_year", weekday=DAYS_FR[dt.weekday()], day=dt.day,
                      month=MONTHS_FR[dt.month - 1], year=dt.year, clock=_clock(dt))
    return phrase("transcript.time.date", weekday=DAYS_FR[dt.weekday()], day=dt.day, month=MONTHS_FR[dt.month - 1],
                  clock=_clock(dt))


def gap_mark(prev: int, at: int, tz: ZoneInfo, after_us: int = MARK_AFTER) -> str:
    """Le repère d'un message par rapport au précédent, tel qu'on le perçoit :
    rien quand il suit de près ; « 25 minutes plus tard », « une heure plus
    tard », puis « plus tard, vers 17h » le même jour ; « le lendemain, mardi
    14h13 », « cinq jours plus tard, samedi 18h08 », « trois semaines plus
    tard, lundi 19 octobre, 9h02 » au-delà. Compté en jours vécus du calendrier
    local, et fonction des deux instants seulement : le même repère d'un prompt
    à l'autre (le préfixe en cache ne bouge pas)."""
    if at - prev < after_us:
        return ""
    then, now = local(prev, tz), local(at, tz)
    days = (local_date_of_night(at, tz, DAY_STARTS_AT) - local_date_of_night(prev, tz, DAY_STARTS_AT)).days
    if days <= 0:
        minutes = (at - prev) // MINUTE
        if minutes < 110:
            return _lapse(minutes)
        if now.hour < DAY_STARTS_AT:
            return phrase("transcript.time.later_night", about=_about(now))
        return phrase("transcript.time.later", about=_about(now))
    if days == 1:
        return phrase("transcript.time.next_day", day=_day(now))
    if days == 2:
        return phrase("transcript.time.day_after", day=_day(now))
    if days < 7:
        return phrase("transcript.time.days_later_day", days=_number(days), day=_day(now))
    if days == 7:
        lap = phrase("transcript.time.week_later")
    elif days < 14:
        lap = phrase("transcript.time.days_later", days=_number(days))
    elif days < 30:
        lap = phrase("transcript.time.weeks_later", weeks=_number(days // 7))
    elif days < 365:
        months = max(1, round(days / 30.44))
        lap = phrase("transcript.time.month_later") if months == 1 else \
            phrase("transcript.time.months_later", months=_number(months))
    else:
        years = days // 365
        lap = phrase("transcript.time.year_later") if years == 1 else phrase("transcript.time.years_later", years=years)
    return phrase("transcript.time.lapse_date", lapse=lap, date=_date(now, now.year != then.year))


#: au-delà, un message auquel elle répond est un message qu'elle lit en retard (elle dormait, elle était prise)
READ_LATE_US = 20 * MINUTE


def read_late(at: int, now: int, tz: ZoneInfo) -> str:
    """Quand elle lit seulement maintenant un message écrit bien avant (la nuit, pendant qu'elle dormait) : « tu
    ne le lis que maintenant, jeudi vers 7h ». Sans ça, le repère du message (« vers 3h ») lui fait répondre comme
    si elle était éveillée à 3 h (sonde réelle du 2026-10-02 : « non je dors pas », à 7 h 14)."""
    if now - at < READ_LATE_US:
        return ""
    same = local_date_of_night(at, tz, DAY_STARTS_AT) == local_date_of_night(now, tz, DAY_STARTS_AT)
    when = _about(local(now, tz)) if same else _day(local(now, tz))
    return phrase("transcript.time.read_late", when=when)


def opening_mark(at: int, now: int, tz: ZoneInfo) -> str:
    """Le repère absolu d'un message qui ouvre l'historique : « lundi 28
    septembre, 18h02 » (avec l'année quand ce n'est pas celle-ci)."""
    dt = local(at, tz)
    return _date(dt, dt.year != local(now, tz).year)


# ── L'historique du prompt ────────────────────────────────────────────────



@dataclass(frozen=True, slots=True)
class ThreadView:
    """Ce que montre l'historique : le fil (la clé de sa coupe), ses tours, et
    comment se présente le message en cours (son repère, qui parle)."""

    key: str
    turns: tuple[ChatTurn, ...] = ()
    current: ChatTurn | None = None


def speakers(frame: Frame, handles: Sequence[str]) -> dict[str, str]:
    """Le nom sous lequel chacun parle dans le fil d'un salon : son nom
    d'affichage nettoyé, jamais son adresse ; des homonymes se distinguent par
    un numéro, dans l'ordre (stable) de leurs adresses."""
    out: dict[str, str] = {}
    taken: dict[str, int] = {}
    for h in sorted({h for h in handles if not is_internal(h)}):
        # quelqu'un dont on ne connaît pas le nom : « Quelqu'un »
        name = clean_display_name(frame.get(identity_c.IDENTITY(h)).name) or phrase("transcript.thread.someone")
        n = taken[fold(name)] = taken.get(fold(name), 0) + 1
        out[h] = name if n == 1 else f"{name} ({n})"
    return out


def tagged(r: Mapping[str, Any]) -> str:
    """Son propre message tel qu'elle l'a écrit : avec sa balise d'émotion (le
    fil la garde en annotation), pour que le modèle ne désapprenne pas à la mettre."""
    text = r["text"] or ""
    if not text.strip() or not r.get("emotion"):
        return text
    value = f"{float(r['emotion_intensity'] or 0.0):.2f}".rstrip("0")
    return f"{text} [EMOTION:{r['emotion']}:{value + '0' if value.endswith('.') else value}]"




#: ce que dit le repère d'un message resté sans réponse (la colonne ``unanswered``) : un fait, à la deuxième
#: personne, jamais la cause technique — à « t'es là ? », elle sait qu'elle n'a pas répondu et pourquoi, et ne
#: s'excuse pas d'une panne quand elle s'est tue exprès ; ce qu'elle en dit, elle le décide. Les mots sont sous
#: ``transcript.thread.unanswered`` (persona/voix.yaml) ; un délai dépassé se dit comme une panne.
LEFT_UNANSWERED = {
    c.UNANSWERED_ABSTAINED: "abstained",
    c.UNANSWERED_FAILED: "failed",
    c.UNANSWERED_TIMEOUT: "failed",
    c.UNANSWERED_LATE: "late",
}


def left_unanswered(cause: str | None) -> str:
    """Le repère d'un message resté sans réponse pour ``cause`` (``""`` : répondu, en attente ou pas pour elle)."""
    words = LEFT_UNANSWERED.get(cause or "")
    return phrase(f"transcript.thread.unanswered.{words}") if words else ""


def _first(mark: str, note: str) -> str:
    return f"{mark} — {note}" if mark else note


def used_tools(raw: str | None) -> str:
    """Ce que dit le repère d'un de ses messages écrit avec ses outils (la colonne ``tools``, ADR 0108). Le fil ne
    garde que ce qu'elle a dit, pas ce que ses outils lui ont rendu : sans ce repère, au tour suivant, elle relisait
    « j'ai regardé les prévisions » sans trace de la recherche, se croyait prise à inventer et s'en accusait.
    ``""`` : aucun outil (ou une valeur illisible)."""
    try:
        pairs = json.loads(raw) if raw else []
    except ValueError:
        return ""
    if not isinstance(pairs, list):
        return ""
    named = [(str(p[0]), bool(p[1])) for p in pairs if isinstance(p, list) and len(p) == 2]
    worked = list(dict.fromkeys(name for name, ok in named if ok))
    failed = list(dict.fromkeys(name for name, ok in named if not ok and name not in worked))
    notes = []
    if worked:
        notes.append(phrase("transcript.thread.used_tools", tools=", ".join(worked)))
    if failed:
        notes.append(phrase("transcript.thread.tools_failed", tools=", ".join(failed)))
    return " ; ".join(notes)


def thread_turns(rows: Sequence[Mapping[str, Any]], tz: ZoneInfo, now: int, after_us: int,
                 names: Mapping[str, str] | None = None) -> list[ChatTurn]:
    """Les tours du fil, chacun avec son repère par rapport au précédent (et le
    repère absolu qui le remplace s'il ouvre l'historique) ; dans un salon,
    chacun sous son nom. Un message qu'elle a écrit d'elle-même le dit dans son
    repère (« [jeudi 19h06 — c'est toi qui lui as écrit] ») : personne ne l'avait
    relancée. Un message de la personne resté sans réponse le dit aussi (« [mardi
    14h13 — tu n'as pas pu lui répondre : une panne] ») : posé par la fin qui l'a
    réglé, avant le tour suivant — le préfixe en cache ne bouge pas. Un des siens
    écrit avec ses outils dit lesquels (ADR 0108) : ce qu'elle y affirmait venait
    d'eux, pas de son imagination."""
    out: list[ChatTurn] = []
    prev: int | None = None
    for r in rows:
        at = int(r["at"])
        mark = gap_mark(prev, at, tz, after_us) if prev is not None else ""
        prev = at
        opening = opening_mark(at, now, tz)
        if r["role"] == "assistant":
            note = ""
            if r.get("kind") == Kind.INITIATIVE:
                # sans lui, le repère seul (« [jeudi 19h06] ») se lit comme un message vide de la personne, qui
                # l'aurait relancée (HUM-22)
                note = phrase("transcript.thread.she_spoke_first") if r.get("room") else \
                    phrase("transcript.thread.she_wrote_first")
            tools = used_tools(r.get("tools"))
            note = _first(note, tools) if tools else note
            out.append(ChatTurn("assistant", tagged(r), id=r["id"], mark=_first(mark, note) if note else mark,
                                opening=_first(opening, note) if note else opening))
        else:
            left = left_unanswered(r.get("unanswered"))
            out.append(ChatTurn("user", r["text"] or "", speaker=(names or {}).get(r["person"], ""), id=r["id"],
                                mark=_first(mark, left) if left else mark,
                                opening=_first(opening, left) if left else opening))
    return out


@TRANSCRIPT.enricher("thread", episodes=CONVERSATIONAL, deadline_ms=1500)
async def _thread(s: TranscriptState, frame: Frame, ports: Mapping[str, Any]) -> ThreadView | None:
    """Le fil avec l'interlocuteur. Ce que les autres lui ont dit en privé n'y
    est pas : cela passe par la mémoire, filtrée par la divulgation (un fil
    partagé verbatim ferait lire à Bob ce qu'Alice a écrit en privé). Dans un
    salon, le fil du salon — tout le monde l'a lu —, chacun sous son nom. En
    privé, ses adresses reliées s'ajoutent seulement si sa fiche est ouverte,
    et le résumé du début du fil est prioritaire dans le budget. Dans un fil de
    travail (ADR 0164), ses seuls messages, sous ce qui dit de quoi il parle :
    le reste de leur vie passe par sa mémoire."""
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target:
        return None
    p = _params(frame.env.params_of("transcript", frame.root))
    tz = frame.env.tz_of(frame.root)
    before = ep.attrs.get("reply_to")
    room = ep.attrs.get("room")
    strand = ep.attrs.get("strand")
    asked = _message(store, before) if before is not None else None
    names: dict[str, str] = {}
    pinned: list[ChatTurn] = []
    gap = False
    # Le brut reste disponible jusqu'au résumé, avec une marge pour son traitement en arrière-plan.
    limit = p.window

    def summary_for(key: str) -> int:
        summary = s.summaries.get(key)
        if summary is None or (before is not None and summary[0] >= before):
            return 0
        text = store.content([summary[1]]).get(summary[1])
        if not text:
            return 0  # résumé oublié : ne pas masquer le brut
        pinned.append(ChatTurn("user", phrase("transcript.thread.summary", text=text), id=summary[0], pinned=True))
        return summary[0]

    t = c.thread_table()
    if room:
        since = summary_for(f"room:{room}")
        rows = room_thread(store, room, limit, before=before, step=p.window_step, after=since)
        gap = bool(rows) and _any(store, t.c.room == room, t.c.id > since, t.c.id < rows[0]["id"])
        names = speakers(frame, [str(r["person"]) for r in rows if r["role"] != "assistant"] +
                         ([str(asked["person"])] if asked else []))
        key = f"room:{room}"
    elif strand:
        # un fil de travail : ses messages seulement, ni résumé ni autres adresses ; ce qui dit de quoi il parle
        # en tête, jamais coupé
        key = f"strand:{ep.target}:{strand}"
        pinned.append(ChatTurn("user", strand_about(strand_setting(store, ep.target, strand)), pinned=True))
        rows = strand_thread(store, ep.target, strand, limit, before=before, step=p.window_step)
        gap = bool(rows) and _any(store, t.c.person == ep.target, t.c.strand == strand, t.c.id < rows[0]["id"])
    else:
        aud = frame.audience
        handles: tuple[str, ...] = (ep.target,)
        key = f"private:{ep.target}"
        if aud is not None and aud.private_ok:
            person = frame.get(identity_c.PERSON(ep.target))
            # ses adresses dont la liaison est confirmée (une liaison par simple recoupement : son seul fil)
            handles = tuple(sorted({ep.target, *frame.get(identity_c.THREAD(ep.target))}))
            key = f"private:{person}"
        # Chaque résumé couvre son adresse seulement. Celui d'Alice sur un écran ne masque pas
        # des messages plus anciens, jamais résumés, sur son autre adresse confirmée.
        rows = []
        for handle in handles:
            since = summary_for(handle)
            part = private_thread(store, (handle,), limit, before=before, after=since, step=p.window_step)
            gap |= bool(part) and _any(store, t.c.person == handle, t.c.room.is_(None), t.c.strand.is_(None),
                                       t.c.id > since, t.c.id < part[0]["id"])
            rows += part
        rows.sort(key=lambda r: r["id"])
    if gap:
        pinned.append(ChatTurn("user", phrase("transcript.thread.gap"), pinned=True))
    turns = pinned + thread_turns(rows, tz, frame.now, p.mark_after_us, names)
    # le message en cours (la question, ou « maintenant » pour une initiative), situé par rapport au dernier tour
    at = int(asked["at"]) if asked else frame.now
    mark = gap_mark(int(rows[-1]["at"]), at, tz, p.mark_after_us) if rows else ""
    late = read_late(at, frame.now, tz)
    if late:
        mark = f"{mark} — {late}" if mark else late
    who = names.get(str(asked["person"]), "") if (room and asked) else ""
    return ThreadView(key, tuple(turns), ChatTurn("user", "", speaker=who, mark=mark) if (mark or who) else None)


def strand_about(setting: Mapping[str, Any] | None) -> str:
    """Ce qu'elle relit en tête d'un fil de travail (ADR 0164) : son titre et sa description tels que son
    opératrice les a écrits, et que ce qui s'est dit ailleurs n'y est pas."""
    title = str((setting or {}).get("title") or "").strip()
    description = str((setting or {}).get("description") or "").strip()
    if title and description:
        return phrase("transcript.strand.about.both", title=title, description=description)
    if title:
        return phrase("transcript.strand.about.title", title=title)
    if description:
        return phrase("transcript.strand.about.description", description=description)
    return phrase("transcript.strand.about.none")


def compact_system(name: str, persona: str) -> str:
    """La consigne du résumé d'un fil long, au nom de celle qui s'en souviendra (celui de sa persona : jamais écrit
    ici), puis qui elle est (``persona``, sa persona rendue : ``self.portrayed``) — le résumé est écrit à sa place, et
    épinglé dans son fil (ADR 0153)."""
    intro = phrase("self.portrayed.intro", name=name, persona=persona)
    return phrase("transcript.compact.system", name=name) + "\n\n" + intro


def _compact_request(frame: Frame, person: str, rows: Sequence[Mapping[str, Any]], previous: str | None,
                     withheld: Collection[int], p: TranscriptParams, times: int, *, system: str,
                     call_id: str) -> tuple[LLMRequest, bool]:
    """L'appel du résumé, avec le début du fil divisé par deux ``times`` fois (``fit_by_halving``) ; et s'il reste
    de quoi diviser."""
    cut = halved(rows, times, least=1)
    prompt = (phrase("transcript.compact.previous", text=previous) + "\n\n" if previous else "") + \
        phrase("transcript.compact.next") + "\n" + _compact_lines(frame, person, cut, p.mark_after_us, withheld)
    return LLMRequest(role="compact", call_id=call_id, system_stable=system, messages=(Message("user", prompt),),
                      max_tokens=p.compact_max_tokens, lane="background", priority=3), len(cut) > 1


def _compact_lines(frame: Frame, person: str, rows: Sequence[Mapping[str, Any]], after_us: int,
                   withheld: Collection[int] = ()) -> str:
    """Les échanges à replier, chacun sous le nom de qui parle et daté comme
    dans l'historique (le premier en absolu). Ce qu'on lui a demandé de garder pour soi, dit dans un salon, n'y
    entre pas : le résumé reste devant le salon bien après les messages (``withheld``, ADR 0082)."""
    tz = frame.env.tz_of(frame.root)
    name = clean_display_name(frame.get(identity_c.IDENTITY(person)).name) or phrase("transcript.compact.someone")
    her = self_c.name_of(frame.get(self_c.PERSONA))
    lines = []
    prev: int | None = None
    for r in rows:
        at = int(r["at"])
        mark = gap_mark(prev, at, tz, after_us) if prev is not None else opening_mark(at, frame.now, tz)
        prev = at
        who = (phrase("transcript.compact.her_initiative", her=her) if r.get("kind") == Kind.INITIATIVE else her) \
            if r["role"] == "assistant" else (clean_display_name(frame.get(identity_c.IDENTITY(r["person"])).name) or name)
        text = phrase("transcript.compact.withheld") if int(r["id"]) in withheld else r["text"]
        lines.append(f"{f'[{mark}] ' if mark else ''}{who} : {text}")
    return "\n".join(lines)


def secret_sources(store: Any, room: str, upto: int) -> set[int]:
    """Les messages d'un salon (jusqu'à ``upto``) d'où vient ce qu'on lui a demandé de garder pour soi — par la porte
    de la mémoire (ADR 0078). Les sources des secrets se déplient en Python (``json_values``), puis le fil dit
    lesquelles sont de ce salon."""
    sources: set[int] = set()
    v = memory_c.KNOWLEDGE
    for (raw,) in store.query_mind(select(v.c.sources).where(v.c.secret == 1)):
        for x in json_values(raw):
            try:
                seq = int(x)
            except (TypeError, ValueError):
                continue
            if seq <= upto:
                sources.add(seq)
    t = c.thread_table()
    found: set[int] = set()
    wanted = sorted(sources)
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        found |= {int(r[0]) for r in store.query_mind(select(t.c.id).where(t.c.room == room, t.c.id.in_(chunk)))}
    return found


@TRANSCRIPT.process("transcript.compact", wake_on=[memory_c.CONSOLIDATED], lane="background",
                    catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Compact:
    """Replie le début des fils trop longs, un fil par passage (les appels de
    modèle restent rares), et seulement ce que la mémoire a déjà relu."""

    def __init__(self) -> None:
        self.seen = -1
        self.retry_at = 0
        self.failures: OrderedDict[str, tuple[int, int, int]] = OrderedDict()

    def next_due(self, state: TranscriptState, frame: Frame, last_run: int | None) -> int | None:
        checkpoint = frame.get(memory_c.CHECKPOINT)
        if checkpoint == self.seen and not self.failures:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: TranscriptState = ctx.state
        store = ctx.ports.get("store")
        checkpoint = frame.get(memory_c.CHECKPOINT)
        if store is None or ctx.llm is None:
            self.seen = checkpoint
            return
        p = _params(frame.env.params_of("transcript", frame.root))
        t = c.thread_table()
        topics = [(str(person), None) for (person,) in store.query_mind(
            select(t.c.person).distinct().where(t.c.room.is_(None)).order_by(t.c.person))]
        topics += [(f"room:{room}", str(room)) for (room,) in store.query_mind(
            select(t.c.room).distinct().where(t.c.room.is_not(None)).order_by(t.c.room))]
        for person, room in topics:
            failed_at, cap, attempts = self.failures.get(person, (0, p.compact_batch, 0))
            if failed_at > frame.now:
                continue
            summary = state.summaries.get(person)
            if room and summary:
                kept = secret_sources(store, room, summary[0])
                fresh = sorted(kept - set(state.withheld.get(person, ())))
                if fresh:
                    # un secret dit dans ce salon (déclaré après coup) était repris : on le replie de nouveau, tu ;
                    # la clé dit les secrets qui le refont (un second, plus ancien, le refait encore)
                    commit = await ctx.emit(c.SUMMARY_RESET.draft(
                        person=person, reason="secret",
                        dedupe_key=f"résumé-refait:{person}:{','.join(map(str, fresh))}"))
                    if commit.deduped:
                        continue  # déjà refait : un salon coincé ne retient pas les autres
                    return
            since = summary[0] if summary else 0
            where = (t.c.room == room, t.c.id > since) if room else (
                t.c.person == person, t.c.room.is_(None), t.c.id > since)
            total = _count(store, *where)
            if total <= p.compact_after:
                continue
            # les plus anciens d'abord, par lots : jamais « résumé » ce qui n'a pas été lu ; ni ce qu'il faut garder
            # tel quel (``keep`` peut dépasser ``compact_after`` : une borne négative, SQLite la lisait « sans
            # borne » et repliait tout, MariaDB la refuse)
            got = _messages_of(store, *where, t.c.id <= checkpoint, newest_first=False,
                               limit=max(0, min(total - p.keep, p.compact_batch, cap)))
            folded = [dict(zip(_COLUMNS, r, strict=True)) for r in got]
            if not folded or (len(folded) < p.compact_min_fold and not attempts):
                continue
            previous = store.content([summary[1]]).get(summary[1]) if summary else None
            withheld = secret_sources(store, room, folded[-1]["id"]) & {int(r["id"]) for r in folded} if room else set()
            self.retry_at = frame.now + p.compact_retry_us  # si l'appel lève, pas de rafale
            system = compact_system(self_c.name_of(frame.get(self_c.PERSONA)), frame.get(self_c.PORTRAYED("compact")))

            # le début du fil se replie par moitiés jusqu'à tenir : la suite attend le passage d'après
            request, times = fit_by_halving(ctx.llm, partial(
                _compact_request, frame, person, folded, previous, withheld, p, system=system,
                call_id=f"{ctx.run_id}#{person}"))
            folded = halved(folded, times, least=1)
            response, text = None, ""
            try:
                response = await ctx.llm.call(request)
                text = (response.text or "").strip() if response.stop != "max_tokens" else ""
            except Exception as exc:  # noqa: BLE001 — un fil en panne ne retient pas les autres
                logging.getLogger(__name__).warning("compactage %s : %s", person, type(exc).__name__)
            if not text:
                retry = frame.now + min(DAY, p.compact_retry_us * 2 ** min(attempts, 16))
                self.failures[person] = (retry, max(1, len(folded) // 2), attempts + 1)
                self.failures.move_to_end(person)
                while len(self.failures) > 256:
                    self.failures.popitem(last=False)
                logging.getLogger(__name__).warning("compactage incomplet, lot réduit à %s message(s)",
                                                    max(1, len(folded) // 2))
                continue
            self.failures.pop(person, None)
            self.retry_at = 0
            speakers = tuple(sorted({str(r["person"]) for r in folded if r["role"] == "user" and r["person"]}))
            await ctx.emit(c.COMPACTED.draft(person=person, upto=folded[-1]["id"], summary=Content.of(text, level=2),
                                             count=len(folded), call_id=request.call_id, model=response.model,
                                             speakers=speakers if room else (),
                                             withheld=tuple(sorted(withheld & {int(r["id"]) for r in folded}))))
            return  # un fil par passage ; le suivant au prochain réveil
        self.seen = checkpoint
        self.retry_at = min((v[0] for v in self.failures.values()), default=0)


@TRANSCRIPT.section("history", zone=Zone.HISTORY, episodes=CONVERSATIONAL)
def _history(s: TranscriptState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    view: ThreadView | None = enrich.get("thread")
    if view is None or not (view.turns or view.current):
        return None
    return SectionBody(view.turns, thread=view.key, current=view.current)


# ── Inspection ────────────────────────────────────────────────────────────

#: Tant de messages par page (curseur « avant ») ; un texte replié au-delà de
#: tant de caractères, et jamais plus que tant envoyés à la console.
PAGE = 50
INSPECT_CHARS = 300
TEXT_CAP = 4000
FORGOTTEN = "(oublié)"
ROLES = (("user", "la personne"), ("assistant", "elle"))


def _clip(text: str | None, limit: int = INSPECT_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _internal(r: Mapping[str, Any]) -> bool:
    """Adressé à personne (ou venu de sa propre tuyauterie) : pas un échange."""
    return not r["person"] or is_internal(r["person"])


def _who(frame: Frame, handle: str) -> Cell:
    """La personne derrière une adresse, en lien vers sa fiche."""
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    return Ref.subject("person", person, f"{name} ({handle})" if name else handle)


def _page(store: Any, clauses: Sequence[Any], before: int | None,
          size: int = PAGE) -> tuple[list[dict[str, Any]], Pager | None]:
    """Une page du fil, du plus récent au plus ancien, et le curseur de la suivante."""
    where = list(clauses)
    if before:
        where.append(c.thread_table().c.id < before)
    found = _messages_of(store, *where, limit=size + 1)
    rows = [dict(zip(_COLUMNS, r, strict=True)) for r in found[:size]]
    more = len(found) > size and rows
    return rows, Pager(older=(("avant", str(rows[-1]["id"])),)) if more else Pager()


def _episodes(ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """L'épisode de chaque réponse (sa corrélation) — et, par elle, celui de la
    question qu'elle règle."""
    out: dict[int, str] = {}
    for r in rows:
        if r["role"] != "assistant":
            continue
        found = ctx.events((rt.UTTERANCE,), 1, before=int(r["id"]) + 1)
        if found and found[0].seq == r["id"]:
            out[int(r["id"])] = found[0].correlation
            if r["reply_to"] is not None:
                out.setdefault(int(r["reply_to"]), found[0].correlation)
    return out


MESSAGE_COLUMNS = (Column("n°", "fit", detail=True), Column("quand", "fit"), Column("qui parle", role="title"), "avec",
                   Column("où", detail=True), Column("texte", role="body"), Column("émotion", detail=True),
                   "réponse", Column("épisode", detail=True))


def _answers(ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Pour chaque message reçu de la page, la parole qui l'a réglé (son n°) : celle qui y répond, ou celle qui
    répond au dernier message de sa rafale et l'a lu avec (``Utterance.answers``). Absent : encore en attente, ou
    réglé sans parole (``_silences`` dit pourquoi)."""
    store = ctx.store
    asked = [r for r in rows if r["role"] == "user" and not _internal(r)]
    if store is None or not asked:
        return {}
    ids = [int(r["id"]) for r in asked]
    t = c.thread_table()
    # par numéro : deux paroles qui répondent au même message, la dernière l'emporte (sur les deux moteurs)
    out = {int(q): int(a) for a, q in store.query_mind(
        select(t.c.id, t.c.reply_to).where(t.c.role == "assistant", t.c.reply_to.in_(ids)).order_by(t.c.id))}
    for r in asked:
        q = int(r["id"])
        if q in out:
            continue
        # le premier énoncé vers la même adresse, au même endroit, qui répond à un message d'après : il a peut-être
        # lu celui-ci avec (une rafale reçoit une seule réponse, à son dernier message)
        later = store.query_mind(
            select(t.c.id).where(t.c.person == r["person"], t.c.role == "assistant", t.c.id > q, t.c.reply_to > q,
                                 func.coalesce(t.c.room, "") == (r["room"] or "")).order_by(t.c.id).limit(1))
        if not later:
            continue
        seq = int(later[0][0])
        found = ctx.events((rt.UTTERANCE,), 1, before=seq + 1)
        if found and found[0].seq == seq and q in found[0].data.answers:
            out[q] = seq
    return out


#: une rafale dont le dernier message est sur une autre page : sa fin se cherche parmi tant de messages suivants
BURST_LOOKUP = 5
#: comment se dit une fin qui laisse un message sans réponse (le détail d'une panne suit)
SILENCES = {"abstained": "s'est tue", "failed": "panne", "timeout": "panne : délai dépassé",
            "interrupted": "interrompue par un arrêt", "superseded": "supplantée", "preempted": "a cédé la place",
            "cancelled": "annulée"}
#: une cause tient en tant de caractères dans la colonne « réponse » (sa page la dit en entier)
CAUSE_CHARS = 80


def _ended_leaving(ctx: InspectContext, reply_to: int, q: int) -> Any | None:
    """La dernière fin d'épisode qui répondait à ``reply_to``, si elle laisse le message ``q`` sans réponse."""
    found = ctx.events((rt.EPISODE_ENDED,), 1, where=("reply_to", reply_to))
    return found[0] if found and found[0].data.leaves_unanswered(q) else None


def _silences(ctx: InspectContext, rows: Sequence[Mapping[str, Any]], pending: set[int],
              answers: Mapping[int, int]) -> dict[int, Any]:
    """Pour chaque message reçu de la page réglé sans parole, la fin d'épisode qui l'a laissé sans réponse
    (``EpisodeEnded.leaves_unanswered``) ; ``None`` : il ne lui était pas adressé (dans un salon, elle entend tout
    mais ne répond qu'à ce qui lui parle). Les plus récents d'abord : la fin d'une rafale porte sur son dernier
    message et règle aussi ceux d'avant. Absent : sa fin n'est pas retrouvée."""
    store = ctx.store
    out: dict[int, Any] = {}
    asked = [r for r in rows if r["role"] == "user" and not _internal(r)
             and int(r["id"]) not in pending and int(r["id"]) not in answers]
    for r in sorted(asked, key=lambda r: int(r["id"]), reverse=True):
        q = int(r["id"])
        if q in out:
            continue
        got = ctx.events((rt.PERCEPTION_RECEIVED,), 1, before=q + 1)
        if got and got[0].seq == q and not got[0].data.addressed:
            out[q] = None
            continue
        ended = _ended_leaving(ctx, q, q)
        if ended is None and store is not None:
            # une rafale dont la fin porte sur un message d'après, de la même adresse au même endroit
            t = c.thread_table()
            for (later,) in store.query_mind(
                    select(t.c.id).where(t.c.person == r["person"], t.c.role == "user", t.c.id > q,
                                         func.coalesce(t.c.room, "") == (r["room"] or ""))
                    .order_by(t.c.id).limit(BURST_LOOKUP)):
                ended = _ended_leaving(ctx, int(later), q)
                if ended is not None:
                    break
        if ended is not None:
            for seq in ended.data.unanswered or (q,):
                out.setdefault(int(seq), ended)
    return out


def _cause(outcome: str, detail: str) -> str:
    """Pourquoi un message est resté sans réponse, en quelques mots : un silence (« s'est tue », ou ce qui l'a fait
    taire — « s'est ravisée », « allait redire son dernier message »), « trop tard », une panne et son détail
    (« panne : délai dépassé »)."""
    detail = " ".join((detail or "").split())
    if detail.startswith(TOO_LATE):
        return "trop tard"
    if outcome == "abstained" and detail:
        # un silence que le modèle n'a pas rendu se dit en une phrase sur elle (« elle s'est ravisée »)
        return _clip(detail.removeprefix("elle "), CAUSE_CHARS)
    head = SILENCES.get(outcome, outcome or "fin inconnue")
    return _clip(f"{head} : {describe_error(detail)}", CAUSE_CHARS) if detail else head


def _answer_cell(r: Mapping[str, Any], pending: set[int], answers: Mapping[int, int],
                 silences: Mapping[int, Any]) -> Cell:
    """La colonne « réponse » d'un message reçu : en attente, la parole qui l'a réglé, ou sans réponse — et
    pourquoi, en mots, avec un lien vers l'explication (« Pourquoi n'a-t-elle pas répondu ? »)."""
    if r["role"] != "user" or _internal(r):
        return ""
    q = int(r["id"])
    if q in pending:
        return Badge("en attente", "warn")
    if q in answers:
        return Ref.why(answers[q], f"répondue → n° {answers[q]}")
    if q not in silences:
        return Text("sans réponse", "muted")
    ended = silences[q]
    if ended is None:
        return Text("sans réponse : ne lui était pas adressé", "muted")
    return Ref.why(q, f"sans réponse : {_cause(ended.data.outcome, ended.data.detail)}")


def _messages(frame: Frame, ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> tuple[Row, ...]:
    pending = {int(x) for x in frame.get(rt.AWAITING)}
    episodes = _episodes(ctx, rows)
    answers = _answers(ctx, rows)
    silences = _silences(ctx, rows, pending, answers)
    out = []
    for r in rows:
        mine = r["role"] == "assistant"
        corr = episodes.get(int(r["id"]))
        if corr is None and silences.get(int(r["id"])) is not None:
            corr = silences[int(r["id"])].correlation  # l'épisode qui l'a laissé sans réponse
        out.append(Row((
            Ref("event", str(r["id"]), str(r["id"])), When(r["at"]),
            Badge("elle", "info") if mine else Badge("la personne"), _who(frame, r["person"]),
            f"salon « {r['room']} »" if r["room"] else "en privé",
            Text((r["text"] or "")[:TEXT_CAP], clamp=INSPECT_CHARS),
            emotion_cell(r["emotion"], r["emotion_intensity"]) if mine and r["emotion"] else "",
            _answer_cell(r, pending, answers, silences),
            Ref("episode", corr, "épisode") if corr else "—",
        ), tone="muted" if _internal(r) else "", href=Ref.why(int(r["id"])) if mine and corr else None,
            detail=(Prose(r["text"] or FORGOTTEN, title="Message", reading=True),)))
    return tuple(out)


def _summaries(store: Any, s: TranscriptState, frame: Frame, handles: Sequence[str] | None) -> Block | None:
    folded = [(p, v) for p, v in sorted(s.summaries.items()) if handles is None or p in handles]  # le rendu pagine
    if not folded:
        return None
    texts = store.content([ref for _p, (_upto, ref) in folded if ref])
    rows = tuple((_who(frame, p), Ref("event", str(upto), str(upto)),
                  Text(_clip(texts[ref], TEXT_CAP), clamp=INSPECT_CHARS) if texts.get(ref) else FORGOTTEN)
                 for p, (upto, ref) in folded)
    return Disclosure(f"Débuts de fil repliés en résumé ({len(rows)})", (
        Table(("avec", "replié jusqu'au message", "résumé"), rows, title="Fils repliés", empty="aucun fil replié"),))


def _no_store() -> list[Block]:
    return [Note("Le magasin n'est pas disponible : le fil ne peut pas être relu.", tone="muted")]


HANDLE = Param("handle", "Personne ou identifiant", placeholder="Alice, user_7, ext_42…")
QUERY = Param("q", "texte", placeholder="un mot…")
ROLE = Param("role", "qui parle", kind="select", choices=ROLES)


@TRANSCRIPT.inspect("messages", title="Messages", section="fil", order=10, params=[HANDLE, QUERY, ROLE],
                    description="Tout ce qui a été dit, du plus récent au plus ancien.")
def _all_messages(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    handle, q, role = str(ctx.value("handle") or ""), str(ctx.value("q") or ""), str(ctx.value("role") or "")
    t = c.thread_table()
    clauses: list[Any] = []
    matched = None
    if handle:
        known_handles = sorted({str(r[0]) for r in store.query_mind(select(t.c.person).distinct())} |
                               set(s.summaries))
        exact = [h for h in known_handles if h == handle]
        matched = exact or [h for h in known_handles if handle.casefold() in _who(frame, h).text.casefold()]
        clauses.append(t.c.person.in_(matched) if matched else false())
    if q:
        # le texte replié à l'écriture, comparé en binaire : casse et accents ignorés, pareil sur les deux moteurs
        clauses.append(func.instr(t.c.folded, fold_text(q)) > 0)
    if role:
        clauses.append(t.c.role == role)
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, clauses, before)
    known = bool(matched) or handle in s.last_from or handle in s.last_to or handle in s.summaries
    if handle and not rows and not known and not before:
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    awaiting = frame.get(rt.AWAITING)
    scope = f" avec « {handle} »" if handle else ""
    found = f" contenant « {q} »" if q else ""
    blocks: list[Block] = [
        Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), title=f"Messages{scope}{found}", pager=pager,
              layout="feed", link_label="Pourquoi cette réponse ?",
              empty="aucun message ne correspond" if handle or q or role else "aucun message"),
    ]
    if awaiting and not (handle or q or role):
        blocks.insert(0, Stats((Stat("Questions sans réponse", len(awaiting), tone="warn",
                                     href=Ref.view("transcript", "questions", "questions")),)))
    folded = _summaries(store, s, frame, matched) if not (q or role) else None
    if folded is not None:
        blocks.append(folded)
    return blocks


def _awaiting(s: TranscriptState, frame: Frame) -> int:
    return len(frame.get(rt.AWAITING))


@TRANSCRIPT.inspect("questions", title="Questions sans réponse", section="fil", order=20, badge=_awaiting,
                    description="Ce qu'on lui a demandé et à quoi elle n'a pas encore répondu.")
def _questions(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    waiting = sorted((int(x) for x in frame.get(rt.AWAITING)), reverse=True)
    page, pager = paginate(waiting, ctx.pager(size=PAGE))
    t = c.thread_table()
    found = {int(r[0]): r for r in store.query_mind(
        select(t.c.id, t.c.at, t.c.person, t.c.text).where(t.c.id.in_(list(page))))} if page else {}
    rows = []
    for seq in page:
        r = found.get(seq)
        link = Ref("event", str(seq), str(seq))
        if r is None:
            rows.append(Row((link, "—", Text("—", "muted"), Text(FORGOTTEN, "muted")), href=link))
            continue
        rows.append(Row((link, When(r[1]), _who(frame, r[2]), Text(_clip(r[3], TEXT_CAP), clamp=INSPECT_CHARS)),
                        href=link))
    return [Table((Column("n°", "fit", detail=True), Column("reçue", "fit"), Column("de", role="title"), Column("texte", role="body")), tuple(rows), pager=pager,
                  layout="feed", link_label="Voir le message source",
                  title="Questions sans réponse", empty="aucune question en attente",
                  caption="Une question reste ici tant qu'aucune réponse ne l'a réglée ; « reçue » dit depuis quand "
                          "elle attend.")]


def _stats(store: Any, handles: Sequence[str]) -> Stats:
    t = c.thread_table()
    total, received = store.query_mind(
        select(func.count(), func.coalesce(func.sum(case((t.c.role == "user", 1), else_=0)), 0))
        .where(t.c.person.in_(list(handles))))[0]
    return Stats((Stat("messages", int(total)), Stat("reçus", int(received)),
                  Stat("envoyés", int(total) - int(received))))


@TRANSCRIPT.inspect("echanges", title="Échanges", subject="person", order=40,
                    description="Ce qu'ils se sont dit, tous ses moyens de communication confondus, du plus récent au "
                                "plus ancien.")
def _exchanges(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    if person.startswith("name:"):
        return [Note("Connue seulement de nom : elle ne lui a jamais écrit.", tone="muted")]
    store = ctx.store
    if store is None:
        return _no_store()
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    t = c.thread_table()
    rows, pager = _page(store, [t.c.person.in_(handles)], ctx.int_param("avant", 0) or None)
    blocks: list[Block] = [_stats(store, handles),
                           Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager, title="Échanges",
                                 layout="feed", link_label="Pourquoi cette réponse ?",
                                 empty="aucun échange pour l'instant")]
    folded = _summaries(store, s, frame, handles)
    if folded is not None:
        blocks.append(folded)
    return blocks


@TRANSCRIPT.inspect("fil", title="Fil", subject="handle", subject_param="handle", order=50,
                    description="Les messages de ce moyen de communication seulement.")
def _handle_thread(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle = ctx.subject or ctx.param("handle")
    if not handle:
        return [Note("Ouvre la fiche d'un moyen de communication : Identités et moyens de communication, puis le "
                     "moyen de communication.", tone="muted")]
    store = ctx.store
    if store is None:
        return _no_store()
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, [c.thread_table().c.person == handle], before)
    if not rows and not before and not (handle in s.last_from or handle in s.last_to):
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    blocks: list[Block] = [_stats(store, [handle]),
                           Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager, title="Messages",
                                 layout="feed", link_label="Pourquoi cette réponse ?",
                                 empty="aucun message")]
    folded = _summaries(store, s, frame, [handle])
    if folded is not None:
        blocks.append(folded)
    return blocks


# l'avis de son opératrice sur ses réponses (ADR 0113) : l'action et sa vue, enregistrées sur la faculté
from mika.faculties.transcript import actions as _actions  # noqa: E402, F401
from mika.faculties.transcript import inspect as _inspect  # noqa: E402, F401

# ── L'oubli d'une personne, l'expiration d'une inconnue de passage (audit du 2026-10-26) ──────────────


@TRANSCRIPT.reducer(identity_c.EXPIRED)
def _stranger_expired(s: TranscriptState, e, cx) -> TranscriptState:
    """Une inconnue de passage oubliée : plus de dernier message d'elle ni vers elle, plus de résumé de son fil."""
    person = e.data.person
    return replace(_without(s, person), last_from=s.last_from.delete(person), last_to=s.last_to.delete(person))
