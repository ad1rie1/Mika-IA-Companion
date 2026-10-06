"""Les séances : l'unité de lecture et de rejeu.

Une **séance** est un échange d'un seul tenant : les messages d'une conversation sans
silence de plus de ``GAP`` entre deux d'entre eux. Un document (une note, une page de
journal) est une séance à lui seul. Claude Code lira les séances par lots ; l'avance
rapide les rejouera ; les paliers se décident séance par séance.

La **signifiance** (0–1) se calcule ici sans modèle, pour trier avant de dépenser :
- sa part dans l'échange (une conversation à deux où elle parle compte plus qu'un groupe
  où elle se tait) ;
- la longueur ;
- le poids affectif des mots, de la ponctuation et des émojis ;
- la place de la personne dans sa vie (le volume échangé, la relation donnée à la main).

Un envoi de masse, une personne ignorée, un fil sans texte valent 0.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from twin.corpus import Corpus
from twin.dates import fold
from twin.timing import HOUR, Origin, Precision, Temps

GAP = 3 * HOUR

#: des mots qui disent qu'il se passe quelque chose (repliés : sans accents, minuscules)
AFFECT_WORDS = [
    "je t'aime", "je t aime", "tu me manques", "manque", "triste", "pleure", "pleurer", "peur", "angoisse", "stress",
    "desolee", "desole", "pardon", "merci", "colere", "enerve", "deteste", "dispute", "rupture", "separe", "quitte",
    "mort", "deces", "enterrement", "malade", "hopital", "urgence", "enceinte", "bebe", "naissance", "mariage",
    "anniversaire", "felicitations", "bravo", "reussi", "diplome", "examen", "bac", "concours", "demenag",
    "licenci", "nouveau travail", "embauche", "vacances", "voyage", "amoureuse", "amoureux", "bisou", "calin",
    "heureuse", "heureux", "fiere", "fier", "honte", "seule", "solitude", "deprime", "epuisee", "fatiguee",
    "love you", "miss you", "sorry", "thank you", "happy birthday", "congrats",
]
_AFFECT = re.compile("|".join(re.escape(w) for w in AFFECT_WORDS))
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿❤]")
_INTENSE = re.compile(r"[!?]{2,}|\b[A-ZÉÈÀ]{4,}\b")

#: relations données à la main qui pèsent d'office
CLOSE_RELATIONS = ("mere", "pere", "maman", "papa", "soeur", "frere", "conjoint", "mari", "femme", "copain",
                   "copine", "fille", "fils", "amie proche", "ami proche", "meilleure amie", "meilleur ami")


@dataclass
class SessionReport:
    sessions: int = 0
    documents: int = 0
    messages: int = 0


def build_sessions(corpus: Corpus) -> SessionReport:
    """Recalcule toutes les séances (tant que la lecture n'a pas commencé)."""
    db = corpus.db
    if db.execute("SELECT COUNT(*) FROM sessions WHERE status != 'todo'").fetchone()[0]:
        raise RuntimeError("des séances ont déjà été lues : les recouper changerait ce que Claude Code a lu")
    db.execute("DELETE FROM sessions")
    db.execute("UPDATE messages SET session = NULL")
    report = SessionReport()
    me = db.execute("SELECT id FROM persons WHERE is_me = 1").fetchone()
    me_id = me["id"] if me else -1
    person_of = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    ignored = {r["id"] for r in db.execute("SELECT id FROM persons WHERE ignored = 1")}
    weight = _person_weights(db, me_id)

    for conv in db.execute("SELECT id, is_group FROM conversations").fetchall():
        rows = db.execute("SELECT id, author, kind, text, t_start, t_end, t_point, t_precision, t_origin, rank "
                          "FROM messages WHERE conversation = ? ORDER BY t_point IS NULL, t_point, rank",
                          (conv["id"],)).fetchall()
        for run in _split(rows):
            sid = _store_run(db, conv["id"], bool(conv["is_group"]), run, person_of, me_id, ignored, weight)
            db.executemany("UPDATE messages SET session = ? WHERE id = ?", [(sid, r["id"]) for r in run])
            report.sessions += 1
            report.messages += len(run)
    for d in db.execute("SELECT * FROM documents").fetchall():
        sig = _document_significance(d["text"])
        db.execute("INSERT INTO sessions (document, n_messages, n_her, chars, persons, t_start, t_end, t_point, "
                   "t_precision, t_origin, significance) VALUES (?, 1, 1, ?, '[]', ?, ?, ?, ?, ?, ?)",
                   (d["id"], len(d["text"]), d["t_start"], d["t_end"], d["t_point"], d["t_precision"],
                    d["t_origin"], sig))
        report.documents += 1
    db.commit()
    return report


def _split(rows: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    runs: list[list[sqlite3.Row]] = []
    for r in rows:
        if runs:
            prev = runs[-1][-1]
            same = (r["t_point"] is not None and prev["t_point"] is not None and r["t_point"] - prev["t_point"] <= GAP) \
                or (r["t_point"] is None and prev["t_point"] is None)
            if same:
                runs[-1].append(r)
                continue
        runs.append([r])
    return runs


def _store_run(db: sqlite3.Connection, conv: int, group: bool, run: list[sqlite3.Row], person_of: dict[int, int],
               me_id: int, ignored: set[int], weight: dict[int, float]) -> int:
    persons = sorted({person_of[r["author"]] for r in run if r["author"] is not None
                      and person_of.get(r["author"]) not in (None, me_id)})
    n_her = sum(1 for r in run if r["author"] is not None and person_of.get(r["author"]) == me_id)
    chars = sum(len(r["text"]) for r in run)
    points = [r["t_point"] for r in run if r["t_point"] is not None]
    starts = [r["t_start"] for r in run if r["t_start"] is not None]
    ends = [r["t_end"] for r in run if r["t_end"] is not None]
    if points:
        t = Temps.span(min(starts) if starts else None, max(ends) if ends else None, Origin.SOURCE,
                       point=points[0])
        exact = all(r["t_precision"] == Precision.EXACT.value for r in run)
        precision = Precision.EXACT.value if exact else t.precision.value
        origin = run[0]["t_origin"]
    else:
        t, precision, origin = Temps.unknown(), Precision.UNKNOWN.value, run[0]["t_origin"]
    if all(r["kind"] in ("masse", "systeme") for r in run) or (persons and set(persons) <= ignored) or chars == 0:
        sig = 0.0
    else:
        sig = significance(run, n_her, chars, group, max((weight.get(p, 0.0) for p in persons), default=0.0))
    cur = db.execute(
        "INSERT INTO sessions (conversation, n_messages, n_her, chars, persons, t_start, t_end, t_point, t_precision, "
        "t_origin, significance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conv, len(run), n_her, chars, json.dumps(persons), t.start, t.end, t.point, precision, origin, sig))
    return int(cur.lastrowid or 0)


def significance(run: list[sqlite3.Row], n_her: int, chars: int, group: bool, person_weight: float) -> float:
    n = len(run)
    texts = [r["text"] for r in run]
    folded = fold(" ".join(texts))
    affect = len(_AFFECT.findall(folded)) + 0.5 * len(_EMOJI.findall(" ".join(texts))) \
        + 0.5 * sum(len(_INTENSE.findall(t)) for t in texts)
    share = n_her / n if n else 0.0
    participation = 1.0 - abs(share - 0.5) * 2 if n_her else (0.15 if group else 0.35)
    length = min(1.0, math.log1p(chars) / math.log1p(4000))
    feeling = min(1.0, affect / 6)
    # le contenu d'abord : un « ok » échangé avec une proche reste banal
    score = 0.15 * participation + 0.25 * length + 0.35 * feeling + 0.25 * person_weight
    if group:
        score *= 0.8 if n_her else 0.5
    return round(max(0.0, min(1.0, score)), 4)


def _document_significance(text: str) -> float:
    """Ses notes et son journal : c'est elle qui écrit, sur elle — d'office important."""
    folded = fold(text)
    affect = len(_AFFECT.findall(folded))
    return round(min(1.0, 0.55 + 0.25 * min(1.0, math.log1p(len(text)) / math.log1p(3000))
                     + 0.2 * min(1.0, affect / 4)), 4)


def _person_weights(db: sqlite3.Connection, me_id: int) -> dict[int, float]:
    """La place de chacun dans sa vie : le volume échangé (log), une relation proche donnée à la main."""
    volume: dict[int, int] = defaultdict(int)
    for r in db.execute("SELECT pa.person, COUNT(*) n FROM messages m JOIN participants pa ON pa.id = m.author "
                        "WHERE pa.person IS NOT NULL AND pa.person != ? GROUP BY pa.person", (me_id,)):
        volume[r["person"]] = r["n"]
    top = max(volume.values(), default=1)
    weights = {p: math.log1p(n) / math.log1p(top) for p, n in volume.items()}
    for r in db.execute("SELECT id, relation FROM persons WHERE relation != ''"):
        if any(rel in fold(r["relation"]) for rel in CLOSE_RELATIONS):
            weights[r["id"]] = max(weights.get(r["id"], 0.0), 0.9)
    return weights
