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
3. pour MSN, ses pseudos : ceux qui reviennent dans au moins la moitié des fichiers (et ceux
   que Messenger Plus! lui attribue), puis, de proche en proche, les pseudos portés par ses
   côtés et jamais par le côté d'en face — ses pseudos changent avec les années.

**Les autres** se regroupent sur ce qui ne trompe pas : un numéro, une adresse mail, un
nom complet (prénom et nom) — pas un pseudo MSN, qui n'est pas un nom. Un prénom seul, un
pseudo MSN commun à deux contacts, plusieurs numéros réunis par le seul nom : c'est
proposé, jamais fusionné en silence. Claude Code tranche ensuite les cas ambigus, sur extraits.

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
#: part des fichiers MSN où un pseudo doit revenir pour être d'emblée le sien
HER_PSEUDO_SHARE = 0.5


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
    me = _detect_me(db, parts, free, report, me_id)
    # son propre nom, son numéro, son adresse vus ailleurs (un groupe, un autre export) : c'est elle aussi
    my_keys = {k for pid, r in parts.items() if r["person"] == me_id or pid in me for k in _identity_keys(r)
               if not k.startswith("msn:")}
    me |= {pid for pid in free - me if not parts[pid]["manual"] and my_keys & set(_identity_keys(parts[pid]))}
    for pid in me:
        db.execute("UPDATE participants SET person = ? WHERE id = ?", (me_id, pid))
    free -= me

    # 2. les autres : numéro, adresse, nom complet. Un pseudo MSN commun n'est qu'une proposition.
    uf = _UnionFind()
    keyed: dict[str, int] = {}
    known: dict[str, int] = {}  # clé → personne existante (déjà rattachée)
    for r in parts.values():
        for k in _identity_keys(r):
            if r["person"] is not None and r["person"] != me_id and not k.startswith("msn:"):
                known.setdefault(k, r["person"])
    for pid in sorted(free):
        uf.find(pid)
        for k in _identity_keys(parts[pid]):
            if k.startswith("msn:"):
                continue
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
        joined_by_name = _joined_by_name_only(members, parts)
        if joined_by_name:
            db.execute("UPDATE persons SET review = ? WHERE id = ? AND review = ''",
                       (f"plusieurs numéros ou adresses réunis par le seul nom « {joined_by_name} » : "
                        "la même personne ?", person))

    _propose_msn(db, parts)
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


def _detect_me(db: sqlite3.Connection, parts: dict[int, sqlite3.Row], free: set[int], report: PeopleReport,
               me_id: int) -> set[int]:
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

    # MSN : ses pseudos, quels que soient les indices (un journal Plus! ne dit rien des fichiers XML)
    seeds = {pseudo_key(a) for pid, r in parts.items() if r["channel"] == MSN and (pid in me or r["person"] == me_id)
             for a in [r["name"] or "", *json.loads(r["aliases"] or "[]")]}
    msn_sides = _msn_me_sides(db, parts, seeds - {""}) & candidates - me
    if msn_sides:
        me |= msn_sides
        report.me_by_channel.setdefault(MSN, "pseudos qui reviennent de fichier en fichier")
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


def _msn_me_sides(db: sqlite3.Connection, parts: dict[int, sqlite3.Row], seeds: set[str]) -> set[int]:
    """Ses côtés MSN : ceux qui portent un de ses pseudos.

    Ses pseudos : ceux des indices (``seeds``) et ceux qui reviennent dans au moins la moitié des fichiers ;
    puis, de proche en proche, ceux que portent ses côtés **et jamais le côté d'en face** (un ami qui copie
    son pseudo ne devient pas elle). Dans un fichier, un seul côté est elle ; à égalité, aucun."""
    files: dict[int, set[int]] = defaultdict(set)
    for row in db.execute("SELECT m.conversation, m.participant FROM members m "
                          "JOIN conversations c ON c.id = m.conversation WHERE c.channel = ?", (MSN,)):
        files[row["conversation"]].add(row["participant"])
    keys_of = {pid: {k for a in [r["name"] or "", *json.loads(r["aliases"] or "[]")] if (k := pseudo_key(a))}
               for pid, r in parts.items() if r["channel"] == MSN}
    spread: Counter[str] = Counter()
    for sides in files.values():
        spread.update({k for pid in sides for k in keys_of.get(pid, ())})
    hers = set(seeds)
    if len(files) >= 2:
        hers |= {k for k, n in spread.items() if n >= HER_PSEUDO_SHARE * len(files)}
    mine: set[int] = set()
    while hers:
        mine, opposite = set(), set()
        for sides in files.values():
            side = _her_side(sides, keys_of, hers)
            if side is not None:
                mine.add(side)
                opposite |= {k for pid in sides - {side} for k in keys_of.get(pid, ())}
        grown = {k for pid in mine for k in keys_of.get(pid, ())} - opposite - hers
        if not grown:
            break
        hers |= grown
    return mine


def _her_side(sides: set[int], keys_of: dict[int, set[str]], hers: set[str]) -> int | None:
    scored = sorted(((len(keys_of.get(pid, set()) & hers), pid) for pid in sides), reverse=True)
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return scored[0][1]


# -- les autres -----------------------------------------------------------------------------------------

def _identity_keys(r: sqlite3.Row) -> list[str]:
    keys = []
    address = (r["address"] or "").strip().lower()
    if address.startswith("+") and len(address) >= 8:
        keys.append(f"tel:{address}")
    elif "@" in address:
        keys.append(f"mail:{address}")
    if r["channel"] == MSN:  # un pseudo n'est pas un nom : il ne réunit pas, il propose
        for alias in [r["name"] or "", *json.loads(r["aliases"] or "[]")]:
            k = pseudo_key(alias)
            if len(k) >= 4:
                keys.append(f"msn:{k}")
        return list(dict.fromkeys(keys))
    # la clé d'un participant est un nom dans les messageries qui nomment par le carnet d'adresses
    for name in [r["name"], r["key"] if r["channel"] in NAME_KEYED else ""]:
        k = name_key(name or "")
        if k:
            keys.append(f"nom:{k}")
    return keys


def _joined_by_name_only(members: list[int], parts: dict[int, sqlite3.Row]) -> str:
    """Le nom qui, seul, réunit plusieurs numéros ou adresses distincts (deux homonymes ?), sinon ``""``."""
    strong = {k for pid in members for k in _identity_keys(parts[pid]) if k.startswith(("tel:", "mail:"))}
    if len(strong) < 2:
        return ""
    uf = _UnionFind()
    by_key: dict[str, int] = {}
    for pid in members:
        uf.find(pid)
        for k in _identity_keys(parts[pid]):
            if k.startswith(("tel:", "mail:")):
                if k in by_key:
                    uf.union(pid, by_key[k])
                else:
                    by_key[k] = pid
    strong_groups = {uf.find(by_key[k]) for k in strong}
    if len(strong_groups) < 2:
        return ""
    names = Counter(k[4:] for pid in members for k in _identity_keys(parts[pid]) if k.startswith("nom:"))
    return names.most_common(1)[0][0] if names else ""


def _propose_msn(db: sqlite3.Connection, parts: dict[int, sqlite3.Row]) -> None:
    """Un même pseudo chez deux contacts MSN : peut-être la même personne (deux comptes), peut-être pas."""
    owner = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    me = {r["id"] for r in db.execute("SELECT id FROM persons WHERE is_me = 1")}
    by_key: dict[str, set[int]] = defaultdict(set)
    for pid, r in parts.items():
        if r["channel"] != MSN or owner.get(pid) in me or owner.get(pid) is None:
            continue
        for k in _identity_keys(r):
            by_key[k[4:]].add(owner[pid])
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM persons")}
    for key, persons in by_key.items():
        if len(persons) < 2:
            continue
        for person in persons:
            others = ", ".join(sorted(names[o] for o in persons - {person}))
            db.execute("UPDATE persons SET review = ? WHERE id = ? AND review = '' AND manual = 0",
                       (f"pseudo MSN « {key} » commun avec {others} : la même personne ?", person))


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


SNAPSHOT = "revue:personnes"


def _apply_manual(db: sqlite3.Connection, path: Path, me_id: int) -> int:
    """Ce que la main a changé dans la revue : appliqué, et plus jamais recalculé.

    La revue liste tout le monde ; une décision est **ce qui diffère de la revue telle qu'elle a été
    écrite** (son instantané, gardé dans ``decisions``) — pas ce qui diffère de la base : un nom noté
    entre-temps par Claude Code (``personne_noter``) n'est pas écrasé par la revue restée en l'état.
    Une décision : un participant déplacé (vers une autre personne, vers « elle » ou hors d'« elle »),
    un nom, une relation, « ignorer ». Une personne sans ``id`` est créée ; une personne dont la main
    a retiré tous les participants disparaît.
    """
    if not path.is_file():
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    row = db.execute("SELECT value FROM decisions WHERE kind = ? AND ref = ''", (SNAPSHOT,)).fetchone()
    base = json.loads(row["value"]) if row else _review_doc(db)
    by_ref = {_ref(r): r["id"] for r in db.execute("SELECT id, channel, key FROM participants")}
    current = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    changes = 0

    was: dict[str, object] = {str(x): "elle" for x in (base.get("elle") or {}).get("participants") or []}
    fields: dict[int, tuple[str, str, bool]] = {}
    for e in base.get("personnes") or []:
        fields[int(e["id"])] = (str(e.get("nom") or ""), str(e.get("relation") or ""), bool(e.get("ignorer")))
        was.update({str(x): int(e["id"]) for x in e.get("participants") or []})

    her = data.get("elle") or {}
    her_name = str(her.get("nom") or "").strip()
    if her_name and her_name != str((base.get("elle") or {}).get("nom") or "elle"):
        db.execute("UPDATE persons SET name = ? WHERE id = ?", (her_name, me_id))  # son prénom, dit à la main
        changes += 1

    targets: dict[int, int] = {}  # participant → personne voulue
    listed: set[str] = set()
    for ref in (data.get("elle") or {}).get("participants") or []:
        listed.add(str(ref))
        if str(ref) in by_ref and was.get(str(ref)) != "elle":
            targets[by_ref[str(ref)]] = me_id
    for entry in data.get("personnes") or []:
        refs = [str(x) for x in entry.get("participants") or []]
        listed.update(refs)
        name = str(entry.get("nom") or "").strip()
        relation = str(entry.get("relation") or "")
        ignored = bool(entry.get("ignorer"))
        pid_ = entry.get("id")
        row = db.execute("SELECT * FROM persons WHERE id = ? AND is_me = 0", (pid_,)).fetchone() if pid_ else None
        if row is None:
            known = [by_ref[x] for x in refs if x in by_ref]
            if not known:
                continue
            person = int(db.execute("INSERT INTO persons (name, handle, relation, ignored, manual) "
                                    "VALUES (?, ?, ?, ?, 1)",
                                    (name or "?", _free_handle(db, "ext_" + slugify(name or "personne")), relation,
                                     int(ignored))).lastrowid or 0)
            changes += 1
            targets.update({p: person for p in known})
            continue
        person = int(row["id"])
        old_name, old_relation, old_ignored = fields.get(person, (row["name"], row["relation"], bool(row["ignored"])))
        updates = {}
        if name and name != old_name:
            updates["name"] = name
        if relation != old_relation:
            updates["relation"] = relation
        if ignored != old_ignored:
            updates["ignored"] = int(ignored)
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            db.execute(f"UPDATE persons SET {sets}, manual = 1, review = '' WHERE id = ?",  # noqa: S608
                       (*updates.values(), person))
            changes += 1
        targets.update({by_ref[x]: person for x in refs if x in by_ref and was.get(x) != person})

    for pid, person in targets.items():
        if current.get(pid) != person:
            db.execute("UPDATE participants SET person = ?, manual = 1 WHERE id = ?", (person, pid))
            if person != me_id:
                db.execute("UPDATE persons SET manual = 1, review = '' WHERE id = ?", (person,))
            changes += 1
    for ref, place in was.items():
        pid = by_ref.get(ref)
        if place == "elle" and ref not in listed and pid is not None and current.get(pid) == me_id:
            db.execute("UPDATE participants SET person = NULL, manual = 1 WHERE id = ?", (pid,))  # retirée d'« elle »
            changes += 1
    db.execute("DELETE FROM persons WHERE is_me = 0 AND id NOT IN (SELECT DISTINCT person FROM participants "
               "WHERE person IS NOT NULL)")
    return changes


def _review_doc(db: sqlite3.Connection, tz: ZoneInfo | None = None) -> dict[str, object]:
    """La revue telle qu'elle s'écrit : elle, puis les personnes par volume de messages."""
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
    her = db.execute("SELECT name FROM persons WHERE is_me = 1").fetchone()
    return {
        "elle": {"nom": her["name"] if her else "elle", "participants": [x["ref"] for x in me_parts],
                 "detail": me_parts},
        "personnes": [p for _, p in persons],
    }


def write_review(corpus: Corpus, path: Path, tz: ZoneInfo) -> None:
    """Écrit la revue, et garde son instantané : la prochaine lecture n'y verra que ce que la main a changé."""
    db = corpus.db
    doc = _review_doc(db, tz)
    header = ("# Revue des personnes — corriger puis relancer `jumeau personnes`. La main l'emporte toujours.\n"
              "# - fusionner : mettre les « participants » de deux personnes sous une seule (et supprimer l'autre) ;\n"
              "# - elle : ses comptes vont sous « elle.participants » ; « elle.nom » : son prénom, s'il faut le dire ;\n"
              "# - relation : mère, père, sœur, conjoint, amie, collègue… ; ignorer : true pour un robot ou un service.\n"
              "# « detail » est relu à chaque passage : inutile de le modifier.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    db.execute("INSERT INTO decisions (kind, ref, value) VALUES (?, '', ?) "
               "ON CONFLICT (kind, ref) DO UPDATE SET value = excluded.value",
               (SNAPSHOT, json.dumps(doc, ensure_ascii=False)))
    db.commit()
