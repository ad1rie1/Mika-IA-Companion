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
tours gardent leur balise d'émotion ; la fenêtre avance par paquets.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
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
    paginate,
)
from mika.kernel.prompt import ChatTurn, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, Message
from mika.ports.store import Sql
from mika.vocab.affect import Declared, emotion_cell, strip_prosody
from mika.vocab.circadian import DAYS_FR, MONTHS_FR
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import clean_display_name, fold, is_internal

#: Messages relus au plus pour composer l'historique (le budget coupe ensuite).
THREAD_WINDOW = 60
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


TRANSCRIPT = Faculty("transcript", state=TranscriptState, init=lambda p: TranscriptState(), params=TranscriptParams)
TRANSCRIPT.declare(c.COMPACTED)


def _params(p: TranscriptParams | None) -> TranscriptParams:
    return p if p is not None else TranscriptParams()


@TRANSCRIPT.reducer(c.COMPACTED)
def _compacted(s: TranscriptState, e, cx) -> TranscriptState:
    ref = e.data.summary.ref or ""
    return replace(s, summaries=s.summaries.set(e.data.person, (e.data.upto, ref)))


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
#: est ce qu'elle en a perçu, pour le prompt) ; nul quand il n'y a rien à séparer (version 2 de la table)
_COLUMNS = ("id", "at", "role", "person", "channel", "room", "source", "kind", "text", "client_msg_id",
            "reply_to", "emotion", "emotion_intensity", "attachments", "typed")


class Thread:
    """T0 : une ligne par message visible."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {c.THREAD_TABLE}{sfx}("
            "id INTEGER PRIMARY KEY, at INTEGER NOT NULL, role TEXT NOT NULL, person TEXT NOT NULL, "
            "channel TEXT, room TEXT, source TEXT, kind TEXT, text TEXT NOT NULL, client_msg_id TEXT, "
            "reply_to INTEGER, emotion TEXT, emotion_intensity REAL, attachments TEXT, typed INTEGER)"
        )
        sql.execute(f"CREATE INDEX IF NOT EXISTS {c.THREAD_TABLE}{sfx}_person ON {c.THREAD_TABLE}{sfx}(person, id)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.THREAD_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        rows = [row for e in events if (row := _row(e)) is not None]
        if rows:
            marks = ",".join("?" * len(_COLUMNS))
            sql.executemany(f"INSERT OR REPLACE INTO {c.THREAD_TABLE}{sfx}({','.join(_COLUMNS)}) VALUES({marks})", rows)

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.THREAD_TABLE}{sfx} WHERE person=?", (subject,))


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
                d.client_msg_id, None, None, None, attachments, typed)
    if e.type.name == rt.UTTERANCE.name and d.visible:
        declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
        return (e.seq, e.at, "assistant", d.target or "", d.channel, d.room, _source(d.kind), d.kind,
                strip_prosody(d.text.text or ""), None, d.reply_to,
                declared.emotion.value if declared else None, declared.intensity if declared else None, "[]", None)
    return None


def _source(kind: str) -> str:
    return "conscience" if kind != Kind.REPLY else "reply"


#: version 2 : la colonne ``typed`` (ce que la personne a tapé, à part de ce que ses pièces jointes ont donné) —
#: la table se reconstruit depuis le journal au premier démarrage
TRANSCRIPT.projector(c.THREAD_TABLE, version=2, tier=Tier.T0, types=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE])(Thread)


def recent(store: Any, person: str, limit: int) -> list[dict[str, Any]]:
    """La fin du fil d'une personne, du plus ancien au plus récent."""
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? ORDER BY id DESC LIMIT ?",
        (person, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def after(store: Any, person: str, after_id: int, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Tout ce qu'elle a manqué depuis ``after_id`` (les plus récents si ça
    dépasse ``limit``, et on le dit)."""
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? AND id>? ORDER BY id DESC LIMIT ?",
        (person, after_id, limit + 1),
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)], truncated


def thread_of(store: Any, person: str, limit: int, before: int | None = None, after: int = 0) -> list[dict[str, Any]]:
    """Le fil avec une adresse, entre ``after`` et ``before`` (le message en
    cours de réponse n'y est pas : il arrive comme dernier tour)."""
    bound = before if before is not None else 2**62
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? AND id<? AND id>? ORDER BY id DESC LIMIT ?",
        (person, bound, after, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def oldest_after(store: Any, person: str, after: int, limit: int) -> list[dict[str, Any]]:
    """Les ``limit`` plus anciens messages du fil d'une adresse après ``after``,
    dans l'ordre : ce qu'un résumé replie en premier."""
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? AND id>? ORDER BY id LIMIT ?",
        (person, after, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in rows]


def count_after(store: Any, person: str, after: int) -> int:
    rows = store.query_mind(f"SELECT COUNT(*) FROM {c.THREAD_TABLE} WHERE person=? AND id>?", (person, after))
    return int(rows[0][0]) if rows else 0


def window_start(total: int, window: int, step: int) -> int:
    """Le rang du premier message montré sur ``total`` : les ``window`` derniers
    au plus, mais un début qui n'avance que par paquets de ``step`` (au plus la
    moitié de la fenêtre) — entre deux sauts, le début du fil, donc du prompt,
    ne bouge pas."""
    start = max(0, total - window)
    step = max(1, min(step, window // 2))
    return -(-start // step) * step


def _window(store: Any, where: str, args: Sequence[Any], window: int, step: int) -> list[dict[str, Any]]:
    total = int(store.query_mind(f"SELECT COUNT(*) FROM {c.THREAD_TABLE} WHERE {where}", tuple(args))[0][0])
    start = window_start(total, window, step)
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
        (*args, total - start, start),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in rows]


def private_thread(store: Any, handles: Sequence[str], limit: int, before: int | None = None,
                   after: int = 0, step: int = 1) -> list[dict[str, Any]]:
    """Le fil privé avec une personne, toutes ses adresses confondues (ce
    qu'elle a dit dans un salon n'y est pas : hors de son contexte)."""
    bound = before if before is not None else 2**62
    marks = ",".join("?" * len(handles))
    return _window(store, f"person IN ({marks}) AND room IS NULL AND id<? AND id>?", (*handles, bound, after),
                   limit, step)


def room_thread(store: Any, room: str, limit: int, before: int | None = None, step: int = 1) -> list[dict[str, Any]]:
    """Ce qui s'est dit dans un salon (public pour ce salon), tous ensemble."""
    bound = before if before is not None else 2**62
    return _window(store, "room=? AND id<?", (room, bound), limit, step)


def _message(store: Any, seq: int) -> dict[str, Any] | None:
    rows = store.query_mind(f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE id=?", (seq,))
    return dict(zip(_COLUMNS, rows[0], strict=True)) if rows else None


# ── Les repères de temps ──────────────────────────────────────────────────

#: Avant cette heure, une heure de la nuit appartient encore à la veille : « le
#: lendemain » se compte en jours vécus, pas en passages de minuit.
DAY_STARTS_AT = 5
_NUMBERS = ("zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
            "treize")


def _clock(dt: datetime) -> str:
    return f"{dt.hour}h{dt.minute:02d}"


def _about(dt: datetime) -> str:
    """L'heure à la demi-heure près : « vers 17h », « vers 17h30 », « vers minuit »."""
    h, m = divmod(((dt.hour * 60 + dt.minute + 15) // 30 * 30) % (24 * 60), 60)
    if h in (0, 12):
        return f"vers {'minuit' if h == 0 else 'midi'}{' et demie' if m else ''}"
    return f"vers {h}h{'30' if m else ''}"


def _lapse(minutes: int) -> str:
    """Un silence de moins de deux heures, dit comme on le dit (à cinq minutes près)."""
    m = max(5, round(minutes / 5) * 5)
    if m == 30:
        return "une demi-heure plus tard"
    if m == 45:
        return "trois quarts d'heure plus tard"
    if m < 55:
        return f"{m} minutes plus tard"
    if m < 75:
        return "une heure plus tard"
    return "une heure et demie plus tard" if m < 105 else "presque deux heures plus tard"


def _day(dt: datetime) -> str:
    """Le jour et l'heure ; une heure de la nuit dit de quelle nuit il s'agit."""
    if dt.hour < DAY_STARTS_AT:
        return f"dans la nuit de {DAYS_FR[(dt.weekday() - 1) % 7]} à {DAYS_FR[dt.weekday()]}, {_clock(dt)}"
    return f"{DAYS_FR[dt.weekday()]} {_clock(dt)}"


def _date(dt: datetime, year: bool) -> str:
    return f"{DAYS_FR[dt.weekday()]} {dt.day} {MONTHS_FR[dt.month - 1]}{f' {dt.year}' if year else ''}, {_clock(dt)}"


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
        return f"plus tard{' dans la nuit' if now.hour < DAY_STARTS_AT else ''}, {_about(now)}"
    if days == 1:
        return f"le lendemain, {_day(now)}"
    if days == 2:
        return f"le surlendemain, {_day(now)}"
    if days < 7:
        return f"{_NUMBERS[days]} jours plus tard, {_day(now)}"
    if days == 7:
        lap = "une semaine plus tard"
    elif days < 14:
        lap = f"{_NUMBERS[days]} jours plus tard"
    elif days < 30:
        lap = f"{_NUMBERS[days // 7]} semaines plus tard"
    elif days < 365:
        months = max(1, round(days / 30.44))
        lap = "un mois plus tard" if months == 1 else f"{_NUMBERS[months]} mois plus tard"
    else:
        years = days // 365
        lap = "un an plus tard" if years == 1 else f"{years} ans plus tard"
    return f"{lap}, {_date(now, now.year != then.year)}"


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
    return f"tu ne le lis que maintenant, {when}"


def opening_mark(at: int, now: int, tz: ZoneInfo) -> str:
    """Le repère absolu d'un message qui ouvre l'historique : « lundi 28
    septembre, 18h02 » (avec l'année quand ce n'est pas celle-ci)."""
    dt = local(at, tz)
    return _date(dt, dt.year != local(now, tz).year)


# ── L'historique du prompt ────────────────────────────────────────────────

#: Comment apparaît, dans le fil d'un salon, quelqu'un dont on ne connaît pas le nom.
SOMEONE = "Quelqu'un"
SUMMARY_TURN = "(Plus tôt, entre vous — en résumé : {text})"


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
        name = clean_display_name(frame.get(identity_c.IDENTITY(h)).name) or SOMEONE
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


#: ce que dit le repère d'un message qu'elle a écrit d'elle-même : sans lui, le repère seul (« [jeudi 19h06] »)
#: se lit comme un message vide de la personne, qui l'aurait relancée (HUM-22)
SHE_WROTE_FIRST = "c'est toi qui lui as écrit"
SHE_SPOKE_FIRST = "c'est toi qui as pris la parole"


def _first(mark: str, note: str) -> str:
    return f"{mark} — {note}" if mark else note


def thread_turns(rows: Sequence[Mapping[str, Any]], tz: ZoneInfo, now: int, after_us: int,
                 names: Mapping[str, str] | None = None) -> list[ChatTurn]:
    """Les tours du fil, chacun avec son repère par rapport au précédent (et le
    repère absolu qui le remplace s'il ouvre l'historique) ; dans un salon,
    chacun sous son nom. Un message qu'elle a écrit d'elle-même le dit dans son
    repère (« [jeudi 19h06 — c'est toi qui lui as écrit] ») : personne ne l'avait
    relancée."""
    out: list[ChatTurn] = []
    prev: int | None = None
    for r in rows:
        at = int(r["at"])
        mark = gap_mark(prev, at, tz, after_us) if prev is not None else ""
        prev = at
        opening = opening_mark(at, now, tz)
        if r["role"] == "assistant" and r.get("kind") == Kind.INITIATIVE:
            note = SHE_SPOKE_FIRST if r.get("room") else SHE_WROTE_FIRST
            out.append(ChatTurn("assistant", tagged(r), id=r["id"], mark=_first(mark, note),
                                opening=_first(opening, note)))
        elif r["role"] == "assistant":
            out.append(ChatTurn("assistant", tagged(r), id=r["id"], mark=mark, opening=opening))
        else:
            out.append(ChatTurn("user", r["text"] or "", speaker=(names or {}).get(r["person"], ""), id=r["id"],
                                mark=mark, opening=opening))
    return out


@TRANSCRIPT.enricher("thread", episodes=CONVERSATIONAL, deadline_ms=1500)
async def _thread(s: TranscriptState, frame: Frame, ports: Mapping[str, Any]) -> ThreadView | None:
    """Le fil avec l'interlocuteur. Ce que les autres lui ont dit en privé n'y
    est pas : cela passe par la mémoire, filtrée par la divulgation (un fil
    partagé verbatim ferait lire à Bob ce qu'Alice a écrit en privé). Dans un
    salon, le fil du salon — tout le monde l'a lu —, chacun sous son nom. En
    privé, ses adresses reliées s'ajoutent seulement si sa fiche est ouverte,
    et le résumé du début du fil est épinglé (jamais coupé faute de place)."""
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target:
        return None
    p = _params(frame.env.params_of("transcript", frame.root))
    tz = frame.env.tz_of(frame.root)
    before = ep.attrs.get("reply_to")
    room = ep.attrs.get("room")
    asked = _message(store, before) if before is not None else None
    names: dict[str, str] = {}
    pinned: list[ChatTurn] = []
    if room:
        rows = room_thread(store, room, p.window, before=before, step=p.window_step)
        names = speakers(frame, [str(r["person"]) for r in rows if r["role"] != "assistant"] +
                         ([str(asked["person"])] if asked else []))
        key = f"room:{room}"
    else:
        summary = s.summaries.get(ep.target)
        since = summary[0] if summary else 0
        aud = frame.audience
        handles: tuple[str, ...] = (ep.target,)
        key = f"private:{ep.target}"
        if aud is not None and aud.private_ok:
            person = frame.get(identity_c.PERSON(ep.target))
            # ses adresses dont la liaison est confirmée (une liaison par simple recoupement : son seul fil)
            handles = tuple(sorted({ep.target, *frame.get(identity_c.THREAD(ep.target))}))
            key = f"private:{person}"
        rows = private_thread(store, handles, p.window, before=before, after=since, step=p.window_step)
        text = store.content([summary[1]]).get(summary[1]) if summary else None
        if summary and text:
            pinned.append(ChatTurn("user", SUMMARY_TURN.format(text=text), id=since, pinned=True))
    turns = pinned + thread_turns(rows, tz, frame.now, p.mark_after_us, names)
    # le message en cours (la question, ou « maintenant » pour une initiative), situé par rapport au dernier tour
    at = int(asked["at"]) if asked else frame.now
    mark = gap_mark(int(rows[-1]["at"]), at, tz, p.mark_after_us) if rows else ""
    late = read_late(at, frame.now, tz)
    if late:
        mark = f"{mark} — {late}" if mark else late
    who = names.get(str(asked["person"]), "") if (room and asked) else ""
    return ThreadView(key, tuple(turns), ChatTurn("user", "", speaker=who, mark=mark) if (mark or who) else None)


COMPACT_SYSTEM = """Tu aides Mika à se souvenir d'une longue conversation. On te donne le début de son fil avec \
quelqu'un (et le résumé des échanges encore plus anciens, s'il existe) ; un repère entre crochets dit quand un \
message a été écrit. Écris un résumé à la première personne, du point de vue de Mika (« On a parlé de… », « Il \
m'a dit que… »), en 5 à 10 phrases : les faits, ce qui a été promis, le ton de la relation. Situe ce qui compte \
par sa date (« le lundi 28 septembre au soir »), jamais par « hier » ou « la semaine dernière » : ce résumé sera \
relu bien plus tard. N'invente rien. Réponds seulement par le résumé."""


def _compact_lines(frame: Frame, person: str, rows: Sequence[Mapping[str, Any]], after_us: int) -> str:
    """Les échanges à replier, chacun sous le nom de qui parle et daté comme
    dans l'historique (le premier en absolu)."""
    tz = frame.env.tz_of(frame.root)
    name = clean_display_name(frame.get(identity_c.IDENTITY(person)).name) or "La personne"
    lines = []
    prev: int | None = None
    for r in rows:
        at = int(r["at"])
        mark = gap_mark(prev, at, tz, after_us) if prev is not None else opening_mark(at, frame.now, tz)
        prev = at
        who = ("Mika (d'elle-même)" if r.get("kind") == Kind.INITIATIVE else "Mika") if r["role"] == "assistant" \
            else name
        lines.append(f"{f'[{mark}] ' if mark else ''}{who} : {r['text']}")
    return "\n".join(lines)


@TRANSCRIPT.process("transcript.compact", wake_on=[memory_c.CONSOLIDATED], lane="background",
                    catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Compact:
    """Replie le début des fils trop longs, un fil par passage (les appels de
    modèle restent rares), et seulement ce que la mémoire a déjà relu."""

    def __init__(self) -> None:
        self.seen = -1
        self.retry_at = 0

    def next_due(self, state: TranscriptState, frame: Frame, last_run: int | None) -> int | None:
        checkpoint = frame.get(memory_c.CHECKPOINT)
        if checkpoint == self.seen:
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
        for (person,) in store.query_mind(f"SELECT DISTINCT person FROM {c.THREAD_TABLE} ORDER BY person"):
            summary = state.summaries.get(person)
            since = summary[0] if summary else 0
            total = count_after(store, person, since)
            if total <= p.compact_after:
                continue
            # les plus anciens d'abord, par lots : jamais « résumé » ce qui n'a pas été lu
            folded = [r for r in oldest_after(store, person, since, min(total - p.keep, p.compact_batch))
                      if r["id"] <= checkpoint]
            if len(folded) < p.compact_min_fold:
                continue
            previous = store.content([summary[1]]).get(summary[1]) if summary else None
            lines = _compact_lines(frame, person, folded, p.mark_after_us)
            prompt = (f"Résumé précédent : {previous}\n\n" if previous else "") + f"Suite des échanges :\n{lines}"
            self.retry_at = frame.now + p.compact_retry_us  # si l'appel lève, pas de rafale
            request = LLMRequest(role="compact", call_id=f"{ctx.run_id}#{person}", system_stable=COMPACT_SYSTEM,
                                 messages=(Message("user", prompt),), max_tokens=p.compact_max_tokens,
                                 lane="background", priority=3)
            response = await ctx.llm.call(request)
            self.retry_at = 0
            text = (response.text or "").strip()
            if not text:
                self.seen = checkpoint  # rien d'utilisable : on réessaiera à la prochaine consolidation
                return
            await ctx.emit(c.COMPACTED.draft(person=person, upto=folded[-1]["id"], summary=Content.of(text, level=2),
                                             count=len(folded), call_id=request.call_id, model=response.model))
            return  # un fil par passage ; le suivant au prochain réveil
        self.seen = checkpoint


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


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


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


def _page(store: Any, clauses: Sequence[str], args: Sequence[Any], before: int | None,
          size: int = PAGE) -> tuple[list[dict[str, Any]], Pager | None]:
    """Une page du fil, du plus récent au plus ancien, et le curseur de la suivante."""
    where, params = list(clauses), list(args)
    if before:
        where.append("id<?")
        params.append(before)
    clause = f"WHERE {' AND '.join(where)} " if where else ""
    found = store.query_mind(f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} {clause}ORDER BY id DESC LIMIT ?",
                             (*params, size + 1))
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


MESSAGE_COLUMNS = (Column("n°", "fit", detail=True), Column("quand", "fit"), "qui parle", "avec",
                   Column("où", detail=True), "texte", Column("émotion", detail=True),
                   "réponse", Column("épisode", detail=True))


def _answers(ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Pour chaque message reçu de la page, la parole qui l'a réglé (son n°) : celle qui y répond, ou celle qui
    répond au dernier message de sa rafale et l'a lu avec (``Utterance.answers``). Absent : sans réponse (elle
    s'est tue, la réponse a échoué) ou encore en attente."""
    store = ctx.store
    asked = [r for r in rows if r["role"] == "user" and not _internal(r)]
    if store is None or not asked:
        return {}
    ids = [int(r["id"]) for r in asked]
    marks = ",".join("?" * len(ids))
    out = {int(q): int(a) for a, q in store.query_mind(
        f"SELECT id, reply_to FROM {c.THREAD_TABLE} WHERE role='assistant' AND reply_to IN ({marks})", tuple(ids))}
    for r in asked:
        q = int(r["id"])
        if q in out:
            continue
        # le premier énoncé vers la même adresse, au même endroit, qui répond à un message d'après : il a peut-être
        # lu celui-ci avec (une rafale reçoit une seule réponse, à son dernier message)
        later = store.query_mind(
            f"SELECT id FROM {c.THREAD_TABLE} WHERE person=? AND role='assistant' AND id>? AND reply_to>? "
            "AND COALESCE(room, '')=? ORDER BY id LIMIT 1", (r["person"], q, q, r["room"] or ""))
        if not later:
            continue
        seq = int(later[0][0])
        found = ctx.events((rt.UTTERANCE,), 1, before=seq + 1)
        if found and found[0].seq == seq and q in found[0].data.answers:
            out[q] = seq
    return out


def _answer_cell(r: Mapping[str, Any], pending: set[int], answers: Mapping[int, int]) -> Cell:
    """La colonne « réponse » d'un message reçu : en attente, la parole qui l'a réglé, ou sans réponse."""
    if r["role"] != "user" or _internal(r):
        return ""
    q = int(r["id"])
    if q in pending:
        return Badge("en attente", "warn")
    if q in answers:
        return Ref.why(answers[q], f"répondue → n° {answers[q]}")
    return Text("sans réponse", "muted")


def _messages(frame: Frame, ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> tuple[Row, ...]:
    pending = {int(x) for x in frame.get(rt.AWAITING)}
    episodes = _episodes(ctx, rows)
    answers = _answers(ctx, rows)
    out = []
    for r in rows:
        mine = r["role"] == "assistant"
        corr = episodes.get(int(r["id"]))
        out.append(Row((
            Ref("event", str(r["id"]), str(r["id"])), When(r["at"]),
            Badge("elle", "info") if mine else Badge("la personne"), _who(frame, r["person"]),
            f"salon « {r['room']} »" if r["room"] else "en privé",
            Text((r["text"] or "")[:TEXT_CAP], clamp=INSPECT_CHARS),
            emotion_cell(r["emotion"], r["emotion_intensity"]) if mine and r["emotion"] else "",
            _answer_cell(r, pending, answers),
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


HANDLE = Param("handle", "Personne ou identifiant", placeholder="Alice, tg_42, user_7…")
QUERY = Param("q", "texte", placeholder="un mot…")
ROLE = Param("role", "qui parle", kind="select", choices=ROLES)


@TRANSCRIPT.inspect("messages", title="Messages", section="fil", order=10, params=[HANDLE, QUERY, ROLE],
                    description="Tout ce qui a été dit, du plus récent au plus ancien.")
def _all_messages(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    handle, q, role = str(ctx.value("handle") or ""), str(ctx.value("q") or ""), str(ctx.value("role") or "")
    clauses, args = [], []
    matched = None
    if handle:
        known_handles = sorted({str(r[0]) for r in store.query_mind(f"SELECT DISTINCT person FROM {c.THREAD_TABLE}")} |
                               set(s.summaries))
        exact = [h for h in known_handles if h == handle]
        matched = exact or [h for h in known_handles if handle.casefold() in _who(frame, h).text.casefold()]
        clauses.append("person IN (" + ",".join("?" for _ in matched) + ")" if matched else "0")
        args.extend(matched)
    if q:
        clauses.append("text LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    if role:
        clauses.append("role=?")
        args.append(role)
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, clauses, args, before)
    known = bool(matched) or handle in s.last_from or handle in s.last_to or handle in s.summaries
    if handle and not rows and not known and not before:
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    awaiting = frame.get(rt.AWAITING)
    scope = f" avec « {handle} »" if handle else ""
    found = f" contenant « {q} »" if q else ""
    blocks: list[Block] = [
        Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), title=f"Messages{scope}{found}", pager=pager,
              filters=("handle", "q", "role"),
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
    marks = ",".join("?" * len(page))
    found = {int(r[0]): r for r in store.query_mind(
        f"SELECT id, at, person, text FROM {c.THREAD_TABLE} WHERE id IN ({marks})", tuple(page))} if page else {}
    rows = []
    for seq in page:
        r = found.get(seq)
        link = Ref("event", str(seq), str(seq))
        if r is None:
            rows.append(Row((link, "—", Text("—", "muted"), Text(FORGOTTEN, "muted")), href=link))
            continue
        rows.append(Row((link, When(r[1]), _who(frame, r[2]), Text(_clip(r[3], TEXT_CAP), clamp=INSPECT_CHARS)),
                        href=link))
    return [Table((Column("n°", "fit"), Column("reçue", "fit"), "de", "texte"), tuple(rows), pager=pager,
                  title="Questions sans réponse", empty="aucune question en attente",
                  caption="Une question reste ici tant qu'aucune réponse ne l'a réglée ; « reçue » dit depuis quand "
                          "elle attend.")]


def _stats(store: Any, handles: Sequence[str]) -> Stats:
    marks = ",".join("?" * len(handles))
    total, received = store.query_mind(
        f"SELECT COUNT(*), COALESCE(SUM(role='user'), 0) FROM {c.THREAD_TABLE} WHERE person IN ({marks})",
        tuple(handles))[0]
    return Stats((Stat("messages", int(total)), Stat("reçus", int(received)),
                  Stat("envoyés", int(total) - int(received))))


@TRANSCRIPT.inspect("echanges", title="Échanges", subject="person", order=40,
                    description="Ce qu'ils se sont dit, toutes ses adresses confondues, du plus récent au plus ancien.")
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
    marks = ",".join("?" * len(handles))
    rows, pager = _page(store, [f"person IN ({marks})"], handles, ctx.int_param("avant", 0) or None)
    blocks: list[Block] = [_stats(store, handles),
                           Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager, title="Échanges",
                                 empty="aucun échange pour l'instant")]
    folded = _summaries(store, s, frame, handles)
    if folded is not None:
        blocks.append(folded)
    return blocks


@TRANSCRIPT.inspect("fil", title="Fil", subject="handle", subject_param="handle", order=50,
                    description="Les messages de cette adresse seulement.")
def _handle_thread(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle = ctx.subject or ctx.param("handle")
    if not handle:
        return [Note("Ouvre la fiche d'une adresse : Identités, puis l'adresse.", tone="muted")]
    store = ctx.store
    if store is None:
        return _no_store()
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, ["person=?"], [handle], before)
    if not rows and not before and not (handle in s.last_from or handle in s.last_to):
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    blocks: list[Block] = [_stats(store, [handle]),
                           Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager, title="Messages",
                                 empty="aucun message")]
    folded = _summaries(store, s, frame, [handle])
    if folded is not None:
        blocks.append(folded)
    return blocks
