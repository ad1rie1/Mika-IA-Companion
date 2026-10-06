"""Qui est qui : des participants de chaque canal aux personnes de sa vie, et « elle ».

Un participant est quelqu'un tel qu'une source le nomme : « Julie » dans WhatsApp, le
numéro +33611… dans les SMS, julie@exemple.fr dans les mails, « ~Juju☆ » dans MSN. Une
personne les réunit, avec une adresse canonique ``ext_<slug>``. C'est l'adresse par
laquelle elle lui écrira pendant l'avance rapide.

**« Elle »** (la titulaire des archives) se reconnaît canal par canal, adaptativement :

1. l'indice de son lecteur (un SMS envoyé, un mail rangé dans « Envoyés », le profil
   d'un export Meta, le fichier WhatsApp qui nomme l'autre) ;
2. sinon, sa présence : dans un canal, elle est dans presque toutes les conversations,
   et personne d'autre ne l'est ;
3. pour MSN, ses pseudos : le côté dont les pseudos reviennent de fichier en fichier.

**Les autres** se regroupent sur ce qui ne trompe pas : un numéro, une adresse mail, un
nom complet (prénom et nom). Un prénom seul, deux pseudos MSN communs : c'est proposé,
jamais fusionné en silence. Claude Code tranche ensuite les cas ambigus, sur extraits.

``travail/personnes.yaml`` est la revue. Une décision écrite à la main l'emporte
toujours : fusionner (mettre deux participants sous la même personne), séparer,
renommer, donner la relation, ignorer un robot.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from twin.corpus import Corpus
from twin.dates import fold
from twin.records import INSTAGRAM, ME, MESSENGER, MSN, NOTES, WHATSAPP
from twin.timing import from_us

ME_HANDLE = "elle"
NAME_KEYED = (WHATSAPP, MESSENGER, INSTAGRAM)
#: part des conversations d'un canal où elle doit apparaître pour être reconnue par sa présence
PRESENCE_SHARE = 0.6
#: … et que le deuxième participant le plus présent ne doit pas atteindre
RUNNER_UP_SHARE = 0.5


@dataclass
class PeopleReport:
    persons: int = 0
    me_participants: int = 0
    merged_auto: int = 0
    manual_applied: int = 0
    to_check: int = 0
    ignored: int = 0
    me_by_channel: dict[str, str] = field(default_factory=dict)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")
    return s[:40] or "personne"


def name_key(name: str) -> str:
    """« Julie  MARTIN » et « julie martin » : la même clé ; un nom d'un seul mot n'en a pas."""
    words = re.findall(r"[a-z]+", fold(name))
    return " ".join(words) if len(words) >= 2 else ""


def pseudo_key(name: str) -> str:
    """Le cœur d'un pseudo MSN : ses lettres (« ~Juju☆ (en cours) » → « juju en cours »)."""
    return " ".join(re.findall(r"[a-z]{2,}", fold(name)))


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def resolve_people(corpus: Corpus, review_path: Path, tz: ZoneInfo) -> PeopleReport:
    db = corpus.db
    report = PeopleReport()
    me_id = _ensure_me(db)
    report.manual_applied = _apply_manual(db, review_path, me_id)

    parts = {r["id"]: r for r in db.execute("SELECT * FROM participants")}
    free = {pid for pid, r in parts.items() if r["person"] is None}

    # 1. elle
    me = _detect_me(db, parts, free, report)
    # son propre nom, son numéro, son adresse vus ailleurs (un groupe, un autre export) : c'est elle aussi
    my_keys = {k for pid, r in parts.items() if r["person"] == me_id or pid in me for k in _identity_keys(r)
               if not k.startswith("msn:")}
    me |= {pid for pid in free - me if not parts[pid]["manual"] and my_keys & set(_identity_keys(parts[pid]))}
    for pid in me:
        db.execute("UPDATE participants SET person = ? WHERE id = ?", (me_id, pid))
    free -= me

    # 2. les autres : numéro, adresse, nom complet — et les pseudos MSN d'un même côté
    uf = _UnionFind()
    keyed: dict[str, int] = {}
    known: dict[str, int] = {}  # clé → personne existante (déjà rattachée)
    for r in parts.values():
        for k in _identity_keys(r):
            if r["person"] is not None and r["person"] != me_id:
                known.setdefault(k, r["person"])
    for pid in sorted(free):
        uf.find(pid)
        for k in _identity_keys(parts[pid]):
            if k in keyed:
                uf.union(pid, keyed[k])
                report.merged_auto += 1
            else:
                keyed[k] = pid
    clusters: dict[int, list[int]] = defaultdict(list)
    for pid in sorted(free):
        clusters[uf.find(pid)].append(pid)

    volumes = _volumes(db)
    for members in clusters.values():
        existing = {known[k] for pid in members for k in _identity_keys(parts[pid]) if k in known}
        if len(existing) == 1:
            person = existing.pop()
        else:
            person = _new_person(db, members, parts, volumes)
            if len(existing) > 1:
                db.execute("UPDATE persons SET review = ? WHERE id = ?",
                           ("touche plusieurs personnes déjà connues : à vérifier", person))
        for pid in members:
            db.execute("UPDATE participants SET person = ? WHERE id = ?", (person, pid))

    _flag_reviews(db, report)
    db.commit()
    report.persons = db.execute("SELECT COUNT(*) FROM persons WHERE is_me = 0").fetchone()[0]
    report.me_participants = db.execute("SELECT COUNT(*) FROM participants WHERE person = ?", (me_id,)).fetchone()[0]
    write_review(corpus, review_path, tz)
    return report


# -- elle --------------------------------------------------------------------------------------------

def _ensure_me(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT id FROM persons WHERE is_me = 1").fetchone()
    if row:
        return int(row["id"])
    cur = db.execute("INSERT INTO persons (name, handle, is_me) VALUES (?, ?, 1)", ("elle", ME_HANDLE))
    return int(cur.lastrowid or 0)


def _detect_me(db: sqlite3.Connection, parts: dict[int, sqlite3.Row], free: set[int], report: PeopleReport) -> set[int]:
    me: set[int] = set()
    candidates = {pid for pid in free if not parts[pid]["manual"]}
    for pid in candidates:
        r = parts[pid]
        if r["me_hint"] == 1 or (r["channel"] == NOTES and r["key"] == ME):
            me.add(pid)
            report.me_by_channel.setdefault(r["channel"], f"indice du lecteur : {r['me_reason'] or 'ses notes'}")
    hinted = {parts[p]["channel"] for p in me}

    # présence : par canal, la participante de presque toutes les conversations
    per_channel: dict[str, Counter[int]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for row in db.execute("SELECT c.channel, m.conversation, m.participant FROM members m "
                          "JOIN conversations c ON c.id = m.conversation"):
        per_channel[row["channel"]][row["participant"]] += 1
    for row in db.execute("SELECT channel, COUNT(*) n FROM conversations GROUP BY channel"):
        totals[row["channel"]] = row["n"]

    msn_sides = _msn_me_sides(parts, candidates, per_channel.get(MSN, Counter()), totals.get(MSN, 0))
    if msn_sides and MSN not in hinted:
        me |= msn_sides
        report.me_by_channel[MSN] = "pseudos qui reviennent dans presque tous les fichiers"
        hinted.add(MSN)

    for channel, counts in per_channel.items():
        if channel in hinted or channel == MSN or totals[channel] < 3:
            continue
        ranked = counts.most_common(2)
        top, n_top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        if n_top >= PRESENCE_SHARE * totals[channel] and second <= RUNNER_UP_SHARE * n_top and top in candidates:
            me.add(top)
            report.me_by_channel[channel] = f"présente dans {n_top}/{totals[channel]} conversations"
    return me


def _msn_me_sides(parts: dict[int, sqlite3.Row], free: set[int], counts: Counter[int], total: int) -> set[int]:
    """Les côtés MSN qui sont elle : le groupe de pseudos présent dans le plus de fichiers."""
    sides = [pid for pid in free if parts[pid]["channel"] == MSN]
    if total < 2 or not sides:
        return set()
    uf = _UnionFind()
    by_pseudo: dict[str, int] = {}
    for pid in sides:
        uf.find(pid)
        for alias in [parts[pid]["name"], *json.loads(parts[pid]["aliases"])]:
            k = pseudo_key(alias)
            if not k:
                continue
            if k in by_pseudo:
                uf.union(pid, by_pseudo[k])
            else:
                by_pseudo[k] = pid
    groups: dict[int, set[int]] = defaultdict(set)
    for pid in sides:
        groups[uf.find(pid)].add(pid)
    best = max(groups.values(), key=lambda g: sum(counts.get(p, 0) for p in g))
    covered = sum(counts.get(p, 0) for p in best)
    return best if covered >= PRESENCE_SHARE * total else set()


# -- les autres -----------------------------------------------------------------------------------------

def _identity_keys(r: sqlite3.Row) -> list[str]:
    keys = []
    address = (r["address"] or "").strip().lower()
    if address.startswith("+") and len(address) >= 8:
        keys.append(f"tel:{address}")
    elif "@" in address:
        keys.append(f"mail:{address}")
    # la clé d'un participant est un nom dans les messageries qui nomment par le carnet d'adresses
    for name in [r["name"], r["key"] if r["channel"] in NAME_KEYED else ""]:
        k = name_key(name or "")
        if k:
            keys.append(f"nom:{k}")
    if r["channel"] == MSN:  # les côtés MSN d'une même personne partagent leurs pseudos
        for alias in json.loads(r["aliases"] or "[]"):
            k = pseudo_key(alias)
            if len(k) >= 4:
                keys.append(f"msn:{k}")
    return keys


def _volumes(db: sqlite3.Connection) -> dict[int, tuple[int, int | None, int | None]]:
    return {r["author"]: (r["n"], r["lo"], r["hi"]) for r in db.execute(
        "SELECT author, COUNT(*) n, MIN(t_point) lo, MAX(t_point) hi FROM messages WHERE author IS NOT NULL "
        "GROUP BY author")}


def _new_person(db: sqlite3.Connection, members: list[int], parts: dict[int, sqlite3.Row],
                volumes: dict[int, tuple[int, int | None, int | None]]) -> int:
    def weight(pid: int) -> tuple[int, int]:
        name = parts[pid]["name"] or ""
        return (len(name.split()) >= 2, volumes.get(pid, (0, None, None))[0])

    best = max(members, key=weight)
    name = parts[best]["name"] or parts[best]["address"] or parts[best]["key"]
    handle = _free_handle(db, "ext_" + slugify(name))
    cur = db.execute("INSERT INTO persons (name, handle) VALUES (?, ?)", (name, handle))
    return int(cur.lastrowid or 0)


def _free_handle(db: sqlite3.Connection, base: str) -> str:
    handle, n = base, 2
    while db.execute("SELECT 1 FROM persons WHERE handle = ?", (handle,)).fetchone():
        handle, n = f"{base}-{n}", n + 1
    return handle


def _flag_reviews(db: sqlite3.Connection, report: PeopleReport) -> None:
    """Ce qui mérite un regard humain : prénoms seuls homonymes, envois de masse."""
    first_names: dict[str, set[int]] = defaultdict(set)
    for r in db.execute("SELECT id, name FROM persons WHERE is_me = 0 AND manual = 0"):
        words = re.findall(r"[a-z]+", fold(r["name"]))
        if len(words) == 1:
            first_names[words[0]].add(r["id"])
    for name, ids in first_names.items():
        if len(ids) > 1:
            for pid in ids:
                db.execute("UPDATE persons SET review = ? WHERE id = ? AND review = ''",
                           (f"même prénom « {name} » que {len(ids) - 1} autre(s) : la même personne ?", pid))
    bulk = {r["author"] for r in db.execute(
        "SELECT author FROM messages WHERE author IS NOT NULL GROUP BY author HAVING SUM(kind = 'masse') * 2 > COUNT(*)")}
    members: dict[int, set[int]] = defaultdict(set)
    for r in db.execute("SELECT pa.id, pa.person FROM participants pa JOIN persons p ON p.id = pa.person "
                        "WHERE p.is_me = 0 AND p.manual = 0 AND p.ignored = 0"):
        members[r["person"]].add(r["id"])
    for person, pids in members.items():
        if pids and pids <= bulk:
            db.execute("UPDATE persons SET ignored = 1, review = 'envois de masse : ignorée' WHERE id = ?", (person,))
            report.ignored += 1
    report.to_check = db.execute("SELECT COUNT(*) FROM persons WHERE review != '' AND manual = 0").fetchone()[0]


# -- la revue -----------------------------------------------------------------------------------------

def _ref(r: sqlite3.Row) -> str:
    return f"{r['channel']}:{r['key']}"


def _apply_manual(db: sqlite3.Connection, path: Path, me_id: int) -> int:
    """Ce que la main a changé dans la revue : appliqué, et plus jamais recalculé.

    La revue liste tout le monde ; seule une différence avec la base est une décision :
    un participant déplacé (vers une autre personne, vers « elle » ou hors d'« elle »),
    un nom, une relation, « ignorer ». Une personne sans ``id`` est créée ; une personne
    dont la main a retiré tous les participants disparaît.
    """
    if not path.is_file():
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_ref = {_ref(r): r["id"] for r in db.execute("SELECT id, channel, key FROM participants")}
    current = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    changes = 0

    targets: dict[int, int] = {}  # participant → personne voulue
    for ref in (data.get("elle") or {}).get("participants") or []:
        if str(ref) in by_ref:
            targets[by_ref[str(ref)]] = me_id
    for entry in data.get("personnes") or []:
        refs = [by_ref[str(x)] for x in entry.get("participants") or [] if str(x) in by_ref]
        name = str(entry.get("nom") or "").strip()
        relation = str(entry.get("relation") or "")
        ignored = int(bool(entry.get("ignorer")))
        row = db.execute("SELECT * FROM persons WHERE id = ? AND is_me = 0", (entry.get("id"),)).fetchone() \
            if entry.get("id") else None
        if row is None:
            if not refs:
                continue
            person = int(db.execute("INSERT INTO persons (name, handle, relation, ignored, manual) "
                                    "VALUES (?, ?, ?, ?, 1)",
                                    (name or "?", _free_handle(db, "ext_" + slugify(name or "personne")), relation,
                                     ignored)).lastrowid or 0)
            changes += 1
        else:
            person = int(row["id"])
            if (name or row["name"], relation, ignored) != (row["name"], row["relation"], row["ignored"]):
                db.execute("UPDATE persons SET name = ?, relation = ?, ignored = ?, manual = 1, review = '' "
                           "WHERE id = ?", (name or row["name"], relation, ignored, person))
                changes += 1
        for pid in refs:
            targets[pid] = person

    for pid, person in targets.items():
        if current.get(pid) != person:
            db.execute("UPDATE participants SET person = ?, manual = 1 WHERE id = ?", (person, pid))
            if person != me_id:
                db.execute("UPDATE persons SET manual = 1, review = '' WHERE id = ?", (person,))
            changes += 1
    listed = set(targets)
    for pid, person in current.items():
        if person == me_id and pid not in listed:  # retirée d'« elle » sans être placée ailleurs
            db.execute("UPDATE participants SET person = NULL, manual = 1 WHERE id = ?", (pid,))
            changes += 1
    db.execute("DELETE FROM persons WHERE is_me = 0 AND id NOT IN (SELECT DISTINCT person FROM participants "
               "WHERE person IS NOT NULL)")
    return changes


def write_review(corpus: Corpus, path: Path, tz: ZoneInfo) -> None:
    db = corpus.db
    volumes = _volumes(db)

    def describe(r: sqlite3.Row) -> dict[str, object]:
        n, lo, hi = volumes.get(r["id"], (0, None, None))
        span = f"{from_us(lo, tz):%Y-%m}…{from_us(hi, tz):%Y-%m}" if lo and hi else "—"
        out: dict[str, object] = {"ref": _ref(r), "nom": r["name"] or "", "messages": n, "periode": span}
        if r["address"]:
            out["adresse"] = r["address"]
        aliases = json.loads(r["aliases"] or "[]")
        if aliases:
            out["pseudos"] = aliases[:8]
        if r["me_reason"]:
            out["indice"] = r["me_reason"]
        return out

    me = db.execute("SELECT id FROM persons WHERE is_me = 1").fetchone()
    me_parts = [describe(r) for r in db.execute("SELECT * FROM participants WHERE person = ? ORDER BY channel, key",
                                                (me["id"] if me else -1,))]
    persons = []
    for p in db.execute("SELECT * FROM persons WHERE is_me = 0"):
        ps = [describe(r) for r in db.execute("SELECT * FROM participants WHERE person = ? ORDER BY channel, key",
                                             (p["id"],))]
        total = sum(int(x["messages"]) for x in ps)  # type: ignore[call-overload]
        persons.append((total, {
            "id": p["id"], "nom": p["name"], "adresse": p["handle"], "relation": p["relation"],
            "ignorer": bool(p["ignored"]), "a_verifier": p["review"],
            "participants": [x["ref"] for x in ps], "detail": ps,
        }))
    persons.sort(key=lambda t: -t[0])
    doc = {
        "elle": {"participants": [x["ref"] for x in me_parts], "detail": me_parts},
        "personnes": [p for _, p in persons],
    }
    header = ("# Revue des personnes — corriger puis relancer `jumeau personnes`. La main l'emporte toujours.\n"
              "# - fusionner : mettre les « participants » de deux personnes sous une seule (et supprimer l'autre) ;\n"
              "# - elle : ses comptes vont sous « elle.participants » ;\n"
              "# - relation : mère, père, sœur, conjoint, amie, collègue… ; ignorer : true pour un robot ou un service.\n"
              "# « detail » est relu à chaque passage : inutile de le modifier.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
