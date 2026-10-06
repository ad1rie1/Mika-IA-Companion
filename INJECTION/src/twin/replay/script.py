"""Le script de sa vie : ce que l'avance rapide va dérouler, dans l'ordre du temps.

Seules les séances rejouées (paliers A, B, R) entrent ici. Le script contient :

- les messages des autres (``Inbound``), à leur date, sur l'adresse de leur personne ;
- **ses** paroles (``Utterance``) : ses messages consécutifs fusionnés (le noyau répond une
  fois par tour, une rafale n'en donne pas trois), avec la balise d'émotion lue par Claude
  Code (``[EMOTION:nom:intensité]``). Sans annotation (palier R), pas de balise : ses
  mots sont vécus sans impulsion d'affect. Une parole est de l'une de trois sortes :
  * ``immediate`` : elle a répondu en moins de ``IMMEDIATE_S``. Le rejoueur rend ses mots
    dans l'épisode de réponse que le message entrant déclenche ;
  * ``delayed`` : elle a répondu plus tard. Sur le moment, le rejoueur se tait ; le pilote
    soumet un épisode de réponse à l'heure réelle ;
  * ``initiative`` : elle a écrit la première.

Une séance datée seulement en plage est déroulée d'un bloc à son point, ses messages
espacés d'une minute dans leur ordre.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from twin.corpus import Corpus
from twin.timing import MINUTE, US

#: en deçà, sa réponse est servie dans l'épisode que le message entrant déclenche
#: (la passerelle accorde 120 s à la conversation : on reste loin en dessous)
IMMEDIATE_S = 90
REPLAYED_TIERS = ("A", "B", "R")


@dataclass(frozen=True, slots=True)
class Inbound:
    at: int
    handle: str
    name: str
    text: str
    archive: tuple[int, ...]
    room: str | None = None
    session: int = 0


@dataclass(frozen=True, slots=True)
class Utterance:
    at: int
    target: str  # l'adresse de la personne (ou, en salon, celle de la dernière qui a parlé)
    text: str  # ses mots, balise d'émotion comprise
    archive: tuple[int, ...]
    kind: Literal["immediate", "delayed", "initiative"]
    room: str | None = None
    session: int = 0
    reply_to: tuple[int, ...] = field(default=())  # les messages entrants auxquels elle répond


Step = Inbound | Utterance


def emotion_tag(emotion: str | None, intensity: float | None) -> str:
    if not emotion or intensity is None:
        return ""
    return f" [EMOTION:{emotion}:{max(0.05, min(1.0, intensity)):.2f}]"


def build_script(corpus: Corpus) -> Iterator[Step]:
    """Le script entier, trié par date (un générateur : des millions de messages ne tiennent pas en mémoire)."""
    db = corpus.db
    me = db.execute("SELECT id FROM persons WHERE is_me = 1").fetchone()
    me_id = me["id"] if me else -1
    persons = {r["id"]: (r["handle"], r["name"]) for r in db.execute("SELECT id, handle, name FROM persons")}
    person_of = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    emotions = _emotions(corpus)
    steps: list[Step] = []
    for s in db.execute(f"SELECT * FROM sessions WHERE document IS NULL AND tier IN "  # noqa: S608
                        f"({','.join('?' * len(REPLAYED_TIERS))}) ORDER BY t_point IS NULL, t_point, id",
                        REPLAYED_TIERS):
        if s["t_point"] is None:
            continue  # sans date du tout : rien ne dit où la vivre
        conv = db.execute("SELECT is_group FROM conversations WHERE id = ?", (s["conversation"],)).fetchone()
        room = f"salon-{s['conversation']}" if conv and conv["is_group"] else None
        rows = db.execute("SELECT id, author, text, t_point, t_precision, kind FROM messages WHERE session = ? "
                          "ORDER BY t_point IS NULL, t_point, rank", (s["id"],)).fetchall()
        steps.extend(_session_steps(s, rows, room, person_of, persons, me_id, emotions))
    steps.sort(key=lambda st: (st.at, 0 if isinstance(st, Inbound) else 1))
    yield from steps


def _emotions(corpus: Corpus) -> dict[int, tuple[str, float]]:
    out: dict[int, tuple[str, float]] = {}
    if not corpus.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'annotations'").fetchone():
        return out
    for r in corpus.db.execute("SELECT data FROM annotations ORDER BY version"):
        for e in json.loads(r["data"]).get("emotions", []):
            out[int(e["id"])] = (e["emotion"], float(e["intensite"]))
    return out


def _session_steps(s, rows, room, person_of, persons, me_id, emotions) -> list[Step]:  # type: ignore[no-untyped-def]
    exact = all(r["t_precision"] == "exacte" for r in rows)
    out: list[Step] = []
    pending_in: list[int] = []  # messages entrants depuis sa dernière parole
    last_in_at: int | None = None
    # une initiative en tête de séance va à la première personne de la séance
    session_persons = [p for p in json.loads(s["persons"] or "[]") if p in persons]
    default = persons[session_persons[0]][0] if session_persons else None
    last_handle: str | None = None
    her: list[tuple[int, str, int]] = []  # (id, texte, date) de sa rafale en cours
    for i, r in enumerate(rows):
        at = r["t_point"] if exact else s["t_point"] + i * MINUTE
        if r["author"] is None or r["kind"] in ("systeme", "supprime") or not (r["text"] or "").strip():
            continue
        person = person_of.get(r["author"])
        if person == me_id:
            her.append((r["id"], r["text"], at))
            continue
        if her:
            out.append(_utterance(her, s, room, last_handle, default, pending_in, last_in_at, emotions))
            her, pending_in = [], []
        if person is None or person not in persons:
            continue
        handle, name = persons[person]
        out.append(Inbound(at, handle, name, r["text"], (r["id"],), room, s["id"]))
        pending_in.append(r["id"])
        last_in_at, last_handle = at, handle
    if her:
        out.append(_utterance(her, s, room, last_handle, default, pending_in, last_in_at, emotions))
    return out


def _utterance(her, s, room, last_handle, default, pending_in, last_in_at, emotions) -> Utterance:  # type: ignore[no-untyped-def]
    ids = tuple(i for i, _, _ in her)
    text = "\n".join(t for _, t, _ in her)
    tagged = [emotions[i] for i in ids if i in emotions]
    tag = emotion_tag(*max(tagged, key=lambda e: e[1])) if tagged else ""
    at = her[0][2]
    if not pending_in or last_handle is None:
        kind: Literal["immediate", "delayed", "initiative"] = "initiative"
    elif last_in_at is not None and at - last_in_at <= IMMEDIATE_S * US:
        kind = "immediate"
    else:
        kind = "delayed"
    return Utterance(at, last_handle or default or "", text + tag, ids, kind, room, s["id"], tuple(pending_in))
