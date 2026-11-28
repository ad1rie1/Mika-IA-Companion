"""Le fil matérialisé : les projections T0 ``thread`` (une ligne par message visible) et ``strands`` (le dernier
réglage de chaque fil de travail), et les requêtes qui les relisent — pour l'historique, la console, le chat et
l'API par personne."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, update

from mika.contracts import expression as expression_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
from mika.faculties.transcript.faculty import TRANSCRIPT
from mika.kernel.faculty import Tier
from mika.ports.delivery import TOO_LATE
from mika.ports.paging import fold_text
from mika.ports.sql import HANDLE_MAX, fit, upsert
from mika.ports.store import Sql
from mika.vocab.affect import Declared
from mika.vocab.episodes import Kind
from mika.vocab.tag import strip_prosody

#: ``typed`` : avec des pièces jointes, combien de caractères du début de ``text`` la personne a tapés (le reste
#: est ce qu'elle en a perçu, pour le prompt) ; nul quand il n'y a rien à séparer (version 2 de la table).
#: ``unanswered`` : pourquoi un message reçu est resté sans réponse pour de bon (``c.UNANSWERED_*``), posé par la
#: fin d'épisode qui l'a réglé ; nul sinon (version 3). ``tools`` : les outils dont elle s'est servie pour écrire un
#: de ses messages (version 6, ADR 0108). ``mode`` : le mode dans lequel le message a été écrit (version 8, ADR 0116)
#: ; ``strand`` : son fil de travail (version 9, ADR 0164)
THREAD_COLUMNS = ("id", "at", "role", "person", "channel", "room", "source", "kind", "text", "client_msg_id",
                  "reply_to", "emotion", "emotion_intensity", "attachments", "typed", "unanswered", "tools",
                  "verdict", "verdict_note", "mode", "strand")


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
    out = dict(zip(THREAD_COLUMNS, row, strict=True))
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


#: version 10 : ``folded`` déplie les ligatures (ADR 0212) ; version 9 : le fil de travail d'un message (``strand``,
#: ADR 0164) ;
#: version 8 : le mode dans lequel un message a été écrit (``mode``, ADR 0116) ;
#: version 7 : l'avis de son opératrice sur ses réponses (``verdict``, ``verdict_note``, ADR 0113), d'où
#: ``transcript.judged`` ; version 6 : la colonne ``tools`` (les outils dont elle s'est servie pour écrire un de ses messages, ADR 0108) ;
#: version 5 : la table déclarée pour les deux moteurs (ADR 0101), et ``folded`` (le texte replié que cherche la
#: console) ; version 3 : la colonne ``unanswered`` (pourquoi un message reçu est resté sans réponse), d'où les fins
#: d'épisode ; version 2 : la colonne ``typed`` (ce que la personne a tapé, à part de ce que ses pièces jointes ont
#: donné) — la table se reconstruit depuis le journal au premier démarrage
TRANSCRIPT.projector(c.THREAD_TABLE, version=10, tier=Tier.T0,
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


class Efforts:
    """T0 : l'effort de réflexion forcé pour une conversation ou un fil de travail
    (``contracts.transcript.efforts_table``, ADR 0287) ; le dernier réglage vaut, « auto » retire la ligne."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(c.efforts_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(c.efforts_table(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = c.efforts_table(sfx)
        for e in events:
            if e.type.name != c.EFFORT_SET.name:
                continue
            person, strand = fit(e.data.person, HANDLE_MAX), fit(e.data.strand, c.STRAND_MAX)
            if e.data.effort:
                upsert(sql, t, {"person": person, "strand": strand, "at": e.at,
                                "effort": fit(e.data.effort, c.EFFORT_MAX)}, keys=["person", "strand"])
            else:
                sql.execute(delete(t).where(t.c.person == person, t.c.strand == strand))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t = c.efforts_table(sfx)
        sql.execute(delete(t).where(t.c.person == fit(subject, HANDLE_MAX)))


TRANSCRIPT.projector(c.EFFORTS_TABLE, version=1, tier=Tier.T0, types=[c.EFFORT_SET])(Efforts)


def efforts_of(store: Any, handle: str) -> dict[str, str]:
    """L'effort de réflexion que ``handle`` a forcé (ADR 0287) : par fil de travail, et sous la clé vide pour toute
    sa conversation. Ce qui est en « auto » n'y est pas."""
    t = c.efforts_table()
    return {str(strand): str(effort)
            for strand, effort in store.query_mind(select(t.c.strand, t.c.effort).where(t.c.person == handle))}


def effort_for(store: Any, handle: str, strand: str | None) -> str:
    """L'effort forcé là où ``handle`` écrit (ADR 0287) : celui de ce fil de travail, sinon celui de toute sa
    conversation ; « » : rien de forcé."""
    forced = efforts_of(store, handle)
    return forced.get(strand or "") or forced.get("", "")


def asked_effort(store: Any, req: Any) -> str:
    """L'effort de réflexion d'un épisode, tel que le lanceur le demande à la composition (ADR 0287) : celui que la
    personne a forcé là où elle a écrit — seulement pour la réponse à un de ses messages, en privé. Une initiative,
    un salon, un travail de fond : rien (« »), le rôle décide."""
    target = getattr(req, "target", None)
    if not target or getattr(req, "reply_to", None) is None or getattr(req, "room", None):
        return ""
    return effort_for(store, target, getattr(req, "strand", None))


def _columns() -> list[Any]:
    t = c.thread_table()
    return [t.c[n] for n in THREAD_COLUMNS]


def messages_of(store: Any, *where: Any, newest_first: bool = True, limit: int | None = None) -> list[Any]:
    """Les lignes du fil qui répondent à ``where`` (les colonnes de ``THREAD_COLUMNS``), triées par numéro."""
    t = c.thread_table()
    query = select(*_columns()).where(*where).order_by(t.c.id.desc() if newest_first else t.c.id)
    return store.query_mind(query.limit(limit) if limit is not None else query)


def recent(store: Any, person: str, limit: int) -> list[dict[str, Any]]:
    """La fin du fil d'une personne, du plus ancien au plus récent."""
    t = c.thread_table()
    rows = messages_of(store, t.c.person == person, limit=limit)
    return [dict(zip(THREAD_COLUMNS, r, strict=True)) for r in reversed(rows)]


def after(store: Any, person: str, after_id: int, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Tout ce qu'elle a manqué depuis ``after_id`` (les plus récents si ça
    dépasse ``limit``, et on le dit)."""
    t = c.thread_table()
    rows = messages_of(store, t.c.person == person, t.c.id > after_id, limit=limit + 1)
    truncated = len(rows) > limit
    rows = rows[:limit]
    return [dict(zip(THREAD_COLUMNS, r, strict=True)) for r in reversed(rows)], truncated


def message_count(store: Any, *where: Any) -> int:
    t = c.thread_table()
    rows = store.query_mind(select(func.count()).select_from(t).where(*where))
    return int(rows[0][0]) if rows else 0


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
        total = message_count(store, *where)
        limit = total - window_start(total, window, step)
    rows = messages_of(store, *where, limit=limit)
    return [dict(zip(THREAD_COLUMNS, r, strict=True)) for r in reversed(rows)]


def private_thread(store: Any, handles: Sequence[str], limit: int, before: int | None = None,
                   after: int = 0, step: int = 1) -> list[dict[str, Any]]:
    """Le fil privé avec une personne, toutes ses adresses confondues (ce
    qu'elle a dit dans un salon n'y est pas : hors de son contexte ; ses fils
    de travail non plus, ADR 0164)."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    return _window(store, (*c.thread_where(t, handles=handles), t.c.id < bound, t.c.id > after), limit, step)


def strand_thread(store: Any, handle: str, strand: str, limit: int, before: int | None = None,
                  step: int = 1) -> list[dict[str, Any]]:
    """Un fil de travail (ADR 0164) : ses seuls messages, rien d'autre de leur fil."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    return _window(store, (*c.thread_where(t, handles=(handle,), strand=strand), t.c.id < bound), limit, step)


def strand_history(store: Any, handle: str, strand: str, before: int | None, limit: int) -> tuple[list[dict[str, Any]],
                                                                                                   bool]:
    """Les messages d'un fil tels qu'un écran les relit : les ``limit`` derniers avant ``before`` (tous s'il est nul),
    du plus ancien au plus récent, et s'il en reste de plus anciens. ``strand`` vide : le fil avec elle, c'est-à-dire
    ce que ``recent`` en donne, sans ses fils de travail (ADR 0215)."""
    bound = before if before is not None else 2**62
    t = c.thread_table()
    thread = t.c.strand == strand if strand else t.c.strand.is_(None)
    rows = messages_of(store, t.c.person == handle, thread, t.c.id < bound, limit=limit + 1)
    return [dict(zip(THREAD_COLUMNS, r, strict=True)) for r in reversed(rows[:limit])], len(rows) > limit


#: ce qu'un message qui porte des fichiers rend à ``with_files``
_FILE_LINE = ("id", "at", "role", "attachments")


def with_files(store: Any, handle: str, strand: str, limit: int, message: int | None = None) -> list[dict[str, Any]]:
    """Les messages d'un fil qui portent quelque chose, du plus récent au plus ancien, ``limit`` au plus (ADR 0312) :
    les pièces de la personne, ce qu'elle lui a envoyé (des fichiers, mais aussi ses petites bulles, ADR 0119, que
    le lecteur écarte) — ``id``, ``at``, ``role``, ``attachments`` (le JSON de la ligne). Le même fil que
    ``strand_history`` : ``strand`` vide, le fil avec elle sans ses fils de travail ; ``message`` : ce seul message.
    Un message de la personne d'avant la séparation de ses pièces (``typed`` nul) n'en annonce aucune, comme à
    l'écran."""
    if store is None:
        return []
    t = c.thread_table()
    thread = t.c.strand == strand if strand else t.c.strand.is_(None)
    query = (select(*(t.c[n] for n in _FILE_LINE))
             .where(t.c.person == handle, thread, t.c.attachments.is_not(None), t.c.attachments != "[]",
                    (t.c.role == "assistant") | t.c.typed.is_not(None)))
    if message is not None:
        query = query.where(t.c.id == message)
    query = query.order_by(t.c.id.desc()).limit(limit)
    return [dict(zip(_FILE_LINE, r, strict=True)) for r in store.query_mind(query)]


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
    return _window(store, (*c.thread_where(t, room=room), t.c.id < bound, t.c.id > after), limit, step)


def message_at(store: Any, seq: int) -> dict[str, Any] | None:
    t = c.thread_table()
    rows = messages_of(store, t.c.id == seq)
    return dict(zip(THREAD_COLUMNS, rows[0], strict=True)) if rows else None


def any_message(store: Any, *where: Any) -> bool:
    """Au moins un message du fil répond à ``where``."""
    t = c.thread_table()
    return bool(store.query_mind(select(t.c.id).where(*where).limit(1)))
