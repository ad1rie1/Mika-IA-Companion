"""Le script de sa vie : ce que l'avance rapide va dérouler, dans l'ordre du temps.

Le script est écrit une fois dans ``corpus.db`` (table ``replay_steps``), puis lu en flux
par le pilote : un million de pas ne tiennent pas en mémoire à côté du noyau, et un curseur
dans une table rend la reprise après plantage triviale.

Les pas :

- ``in`` : un message d'une autre personne, à sa date, sur son adresse. ``release_at`` :
  l'heure de sa réponse quand elle a répondu. Le pilote retient alors le message
  (``reply_wait``) jusque-là, et le noyau fait une vraie réponse, avec ``reply_to``, au moment
  dit (étape 0 : « retenir puis libérer », même la nuit, même après un plantage) ;
- ``her`` : **ses** mots, ses messages consécutifs fusionnés, avec la balise d'émotion lue
  par Claude Code (pas de balise au palier R). Trois sortes :
  * ``reply`` : elle répond à ce qu'on lui a écrit (dans les ``REPLY_WINDOW``, sans que la
    personne ait rouvert entre-temps), libérée à son heure ;
  * ``initiative`` : elle écrit la première ;
  * ``room`` : sa parole dans un salon qui ne répond à rien d'adressé (une REPLY sans
    ``reply_to``, jamais une initiative : étape 0) ;
- ``persona`` : un changement de chapitre de sa vie, donc une révision de sa persona ;
- ``knowledge`` : ce que ses archives non rejouées disent (palier C, ses notes, son journal),
  émis à sa date par la couture ``mika.app.genesis``.

Une séance datée seulement en plage est déroulée d'un bloc à son point, ses messages
espacés d'une minute.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from twin.corpus import Corpus
from twin.dates import fold
from twin.timing import DAY, MINUTE, US

#: ses messages consécutifs ne forment une seule parole que s'ils se suivent d'aussi près
HER_BURST = 15 * MINUTE
#: en deçà, une conversation est en cours (``social.conversation_gap_us`` : 2 h) — au-delà, elle l'ouvre
CONVERSATION_GAP = 2 * 60 * MINUTE
#: au-delà, ce n'est plus une réponse (``others.delay_max_us`` du moteur : 2 jours)
REPLY_WINDOW = 2 * DAY
#: au salon, un message est adressé s'il la nomme ou s'il suit l'un des siens d'aussi près
ROOM_FOLLOW = 10 * MINUTE
REPLAYED_TIERS = ("A", "B", "R")

STEPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_steps (
    id INTEGER PRIMARY KEY, at INTEGER NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS replay_steps_by_time ON replay_steps (at, id);
"""


@dataclass
class _Pending:
    ids: list[int] = field(default_factory=list)
    first_at: int = 0
    handle: str = ""


def emotion_tag(emotion: str | None, intensity: float | None) -> str:
    if not emotion or intensity is None:
        return ""
    return f" [EMOTION:{emotion}:{max(0.05, min(1.0, intensity)):.2f}]"


@dataclass
class ScriptReport:
    steps: int = 0
    undated_sessions: int = 0  # sans date du tout : rien ne dit où la vivre
    knowledge_without_date: int = 0
    chapters: int = 0


def build_script(corpus: Corpus, *, her_names: tuple[str, ...] = (),
                 personas: dict[str, dict[str, Any]] | None = None) -> ScriptReport:
    """Écrit le script entier dans ``replay_steps`` (et l'efface d'abord). ``personas`` : ses personas relues
    (``chapitre-N``) ; à défaut, celles de la table ``syntheses``."""
    db = corpus.db
    db.executescript(STEPS_SCHEMA)
    db.execute("DELETE FROM replay_steps")
    report = ScriptReport()
    me = db.execute("SELECT id FROM persons WHERE is_me = 1").fetchone()
    me_id = me["id"] if me else -1
    persons = {r["id"]: (r["handle"], r["name"]) for r in db.execute("SELECT id, handle, name FROM persons "
                                                                      "WHERE ignored = 0 OR is_me = 1")}
    person_of = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    emotions = _emotions(corpus)
    names = tuple(n for n in (fold(x) for x in her_names) if len(n) >= 3)
    marks = ",".join("?" * len(REPLAYED_TIERS))
    report.undated_sessions = db.execute(
        f"SELECT COUNT(*) FROM sessions WHERE document IS NULL AND tier IN ({marks}) AND t_point IS NULL",  # noqa: S608
        REPLAYED_TIERS).fetchone()[0]
    for conv in db.execute(f"SELECT DISTINCT conversation FROM sessions WHERE document IS NULL "  # noqa: S608
                           f"AND tier IN ({marks}) AND t_point IS NOT NULL", REPLAYED_TIERS).fetchall():
        cid = conv["conversation"]
        group = bool(db.execute("SELECT is_group FROM conversations WHERE id = ?", (cid,)).fetchone()["is_group"])
        # à qui elle écrit quand personne n'a encore écrit dans le fil : l'autre membre de la conversation (un SMS
        # resté sans réponse, un mail envoyé)
        members = [persons[p][0] for (p,) in db.execute(
            "SELECT DISTINCT pa.person FROM members m JOIN participants pa ON pa.id = m.participant "
            "WHERE m.conversation = ? AND pa.person IS NOT NULL", (cid,)) if p != me_id and p in persons]
        rows = []
        for s in db.execute(f"SELECT id, t_point, persons FROM sessions WHERE conversation = ? AND tier IN ({marks}) "  # noqa: S608
                            "AND t_point IS NOT NULL ORDER BY t_point", (cid, *REPLAYED_TIERS)):
            msgs = db.execute("SELECT id, author, text, t_point, t_precision, kind FROM messages WHERE session = ? "
                              "ORDER BY t_point IS NULL, t_point, rank", (s["id"],)).fetchall()
            exact = all(m["t_precision"] == "exacte" for m in msgs)
            for i, m in enumerate(msgs):
                at = m["t_point"] if exact and m["t_point"] is not None else s["t_point"] + i * MINUTE
                rows.append((at, s["id"], m, s))
        rows.sort(key=lambda r: (r[0], r[2]["id"]))
        for at, kind, data in _conversation_steps(rows, f"salon-{cid}" if group else None, person_of, persons, me_id,
                                                  emotions, names, members[0] if members else None):
            db.execute("INSERT INTO replay_steps (at, kind, data) VALUES (?, ?, ?)",
                       (at, kind, json.dumps(data, ensure_ascii=False)))
            report.steps += 1
    known, undated = _knowledge_steps(corpus, persons, person_of)
    report.steps += known
    report.knowledge_without_date = undated
    report.chapters = _persona_steps(corpus, personas)
    report.steps += report.chapters
    db.commit()
    return report


def _emotions(corpus: Corpus) -> dict[int, tuple[str, float]]:
    out: dict[int, tuple[str, float]] = {}
    if not corpus.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'annotations'").fetchone():
        return out
    for r in corpus.db.execute("SELECT data FROM annotations ORDER BY version"):
        for e in json.loads(r["data"]).get("emotions", []):
            out[int(e["id"])] = (e["emotion"], float(e["intensite"]))
    return out


def _conversation_steps(rows, room, person_of, persons, me_id, emotions, names,  # type: ignore[no-untyped-def]
                        member: str | None) -> Iterator[tuple[int, str, dict[str, Any]]]:
    """Les pas d'une conversation : les entrants, et ses paroles avec leur sorte."""
    pending: dict[str, _Pending] = {}  # par adresse : ce qu'on lui a écrit depuis sa dernière parole
    inbound: dict[int, dict[str, Any]] = {}  # les entrants déjà rangés (pour poser leur heure de libération)
    out: list[tuple[int, str, dict[str, Any]]] = []
    her: list[tuple[int, str, int]] = []
    last_speaker: str | None = None
    last_inbound: int | None = None
    last_in_at: int | None = None
    last_her_at: int | None = None
    default_handle: str | None = member
    burst_session: int | None = None

    def flush() -> None:
        nonlocal her, last_her_at
        if not her:
            return
        ids = [i for i, _, _ in her]
        at = her[0][2]
        tagged = [emotions[i] for i in ids if i in emotions]
        text = "\n".join(t for _, t, _ in her) + (emotion_tag(*max(tagged, key=lambda e: e[1])) if tagged else "")
        # à qui elle répond : en privé, la personne qui lui a écrit et attend encore (dans la fenêtre d'une
        # réponse) ; au salon, seulement le tout dernier message, s'il lui était adressé — la conversation avance
        if room is None:
            waiting = [p for p in pending.values() if p.ids and at - p.first_at <= REPLY_WINDOW]
        else:
            waiting = [p for p in pending.values() if p.ids and last_inbound is not None
                       and p.ids[-1] == last_inbound and at - p.first_at <= REPLY_WINDOW]
        target = last_speaker or default_handle or ""
        if waiting:
            p = max(waiting, key=lambda p: p.ids[-1])
            for mid in p.ids:
                inbound[mid]["release_at"] = at
            out.append((at, "her", {"kind": "reply", "target": p.handle, "text": text, "archive": ids,
                                    "room": room, "reply_to": p.ids}))
        elif room is not None:
            out.append((at, "her", {"kind": "room", "target": target, "text": text, "archive": ids, "room": room,
                                    "reply_to": []}))
        elif last_in_at is not None and at - last_in_at <= CONVERSATION_GAP:
            # la personne a écrit il y a peu : elle relance une conversation en cours, elle ne l'ouvre pas
            out.append((at, "her", {"kind": "continue", "target": target, "text": text, "archive": ids,
                                    "room": None, "reply_to": []}))
        else:
            out.append((at, "her", {"kind": "initiative", "target": target, "text": text, "archive": ids,
                                    "room": None, "reply_to": []}))
        pending.clear()  # parler règle ce qui précède : ce qu'elle n'a pas relevé reste sans réponse
        last_her_at = at
        her = []

    for at, _sid, m, s in rows:
        if default_handle is None:
            first = [p for p in json.loads(s["persons"] or "[]") if p in persons]
            default_handle = persons[first[0]][0] if first else None
        if m["author"] is None or m["kind"] in ("systeme", "supprime") or not (m["text"] or "").strip():
            continue
        person = person_of.get(m["author"])
        if person == me_id:
            # une rafale : ses messages qui se suivent de près, dans une même séance
            if her and (at - her[-1][2] > HER_BURST or _sid != burst_session):
                flush()
            her.append((m["id"], m["text"], at))
            burst_session = _sid
            continue
        flush()
        if person is None or person not in persons:
            continue
        handle, name = persons[person]
        addressed = room is None or _addressed(m["text"], names) or (
            last_her_at is not None and at - last_her_at <= ROOM_FOLLOW)
        step = {"handle": handle, "name": name, "text": m["text"], "archive": [m["id"]], "room": room,
                "addressed": addressed, "release_at": None}
        inbound[m["id"]] = step
        out.append((at, "in", step))
        last_speaker, last_inbound, last_in_at = handle, m["id"], at
        if addressed:
            p = pending.setdefault(handle, _Pending(handle=handle))
            if p.ids and at - p.first_at > REPLY_WINDOW:
                p.ids = []  # une relance après la fenêtre d'une réponse : les anciens restent sans réponse
            if not p.ids:
                p.first_at = at
            p.ids.append(m["id"])
    flush()
    yield from out


def _addressed(text: str, names: tuple[str, ...]) -> bool:
    words = set(re.findall(r"[a-z]+", fold(text)))
    return any(n in words for n in names)


def _knowledge_steps(corpus: Corpus, persons: dict[int, tuple[str, str]],
                     person_of: dict[int, int]) -> tuple[int, int]:
    """Le savoir d'archive : les éléments lus des séances C et de ses textes. Rend (pas écrits, sans date)."""
    db = corpus.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'annotations'").fetchone():
        return 0, 0
    n = undated = 0
    for r in db.execute(
            "SELECT s.id, s.t_point, s.t_end, s.t_precision, s.tier, s.document, s.persons, a.data FROM sessions s "
            "JOIN annotations a ON a.session = s.id WHERE (s.tier = 'C' OR s.document IS NOT NULL) "
            "AND a.version = (SELECT MAX(version) FROM annotations WHERE session = s.id)").fetchall():
        data = json.loads(r["data"])
        items = {k: data.get(k, []) for k in ("souvenirs", "croyances", "evenements") if data.get(k)}
        if not items:
            continue
        # elle le sait à la fin de ce qui le lui a appris : la fin de la séance, de la journée, ou de la plage (une
        # page de journal du 12 mars racontant la soirée n'est pas sue à 14 h) ; une note bornée seulement par son
        # fichier, à cette borne
        at = r["t_end"] if r["t_end"] is not None else r["t_point"]
        if at is None:
            undated += 1
            continue
        session_persons = [p for p in json.loads(r["persons"] or "[]") if p in persons]
        authors = {m["id"]: person_of.get(m["author"]) for m in db.execute(
            "SELECT id, author FROM messages WHERE session = ?", (r["id"],))}
        for values in items.values():
            for item in values:
                # qui le lui a confié : les auteurs des messages d'où il est tiré (pas tout le salon) ;
                # sans ancre, les personnes de la séance
                anchors = {authors[m] for m in item.get("messages", []) if m in authors and authors[m] in persons}
                tellers = anchors or set(session_persons)
                item["told_by"] = sorted(persons[p][0] for p in tellers if p in persons and persons[p][0] != "elle")
        db.execute("INSERT INTO replay_steps (at, kind, data) VALUES (?, 'knowledge', ?)",
                   (at, json.dumps({"session": r["id"], "own": r["document"] is not None,
                                    "precision": r["t_precision"], **items}, ensure_ascii=False)))
        n += 1
    return n, undated


def _persona_steps(corpus: Corpus, personas: dict[str, dict[str, Any]] | None) -> int:
    """Un changement de chapitre : sa persona de ce chapitre (relue, si on la donne), au premier jour du chapitre."""
    db = corpus.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'syntheses'").fetchone():
        return 0
    row = db.execute("SELECT data FROM syntheses WHERE kind = 'chapitres' ORDER BY version DESC LIMIT 1").fetchone()
    if not row:
        return 0
    stored = {r["key"]: json.loads(r["data"]) for r in db.execute(
        "SELECT key, data FROM syntheses WHERE kind = 'persona' ORDER BY version")}
    start = db.execute("SELECT MIN(t_point) FROM sessions WHERE t_point IS NOT NULL").fetchone()[0] or 0
    n = 0
    for i, ch in enumerate(json.loads(row["data"]).get("chapitres", [])):
        key = f"chapitre-{i + 1}"
        doc = (personas or {}).get(key) or stored.get(key)
        if not doc:
            continue
        at = max(start, _month_start_us(ch["debut"]))
        db.execute("INSERT INTO replay_steps (at, kind, data) VALUES (?, 'persona', ?)",
                   (at, json.dumps({"chapitre": i + 1, "titre": ch["titre"], "doc": doc}, ensure_ascii=False)))
        n += 1
    return n


def _month_start_us(month: str) -> int:
    y, m = (int(x) for x in month.split("-"))
    return int(datetime(y, m, 1, tzinfo=UTC).timestamp()) * US


def steps(corpus: Corpus, after: tuple[int, int] = (-(2**62), 0),
          page: int = 1000) -> Iterator[tuple[int, int, str, dict[str, Any]]]:
    """Les pas après ``(at, id)``, dans l'ordre : (id, at, sorte, données). Lus par pages : le pilote écrit dans
    la même base pendant qu'il avance, aucun curseur ne reste ouvert entre deux pas."""
    at0, id0 = after
    while True:
        rows = corpus.db.execute("SELECT id, at, kind, data FROM replay_steps WHERE at > ? OR (at = ? AND id > ?) "
                                 "ORDER BY at, id LIMIT ?", (at0, at0, id0, page)).fetchall()
        if not rows:
            return
        for r in rows:
            yield r["id"], r["at"], r["kind"], json.loads(r["data"])
        at0, id0 = rows[-1]["at"], rows[-1]["id"]
