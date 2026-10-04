"""``shares`` : les fichiers qu'elle envoie à la personne à qui elle parle (ADR 0062).

Un fichier part **avec un message** : l'outil écrit ses octets (port ``shares``, hors du journal) puis journalise
``shares.shared`` ; l'énoncé qui suit l'emporte (``Utterance.attachments``) et la tranche le note « parti » avec
le numéro de ce message. Une réponse supplantée ou tue après l'outil laisse un fichier qui n'est jamais parti :
la console le dit, la rétention le retire.

La tranche garde, par adresse, les fichiers encore gardés (pour la rétention, le quota du jour, la section du
prompt) ; la projection T0 ``shared_files`` en garde une ligne chacun — nom, taille, sort — que lisent l'écran
(``MindPort.shared``), le téléchargement et la console. Oublier une personne efface ses lignes, son nom (un
contenu) et ses octets ; une reconstruction ne fait pas revenir un fichier dont le nom a été oublié.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import runtime as rt
from mika.contracts import shares as c
from mika.kernel.clock import DAY
from mika.kernel.codec import digest
from mika.kernel.faculty import CatchUp, Faculty, Tier
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.shares import MAX_SHARE_BYTES
from mika.ports.store import Sql

MIB = 1024 * 1024
#: le port des octets (``ports/shares.py``)
PORT = "shares"
#: au plus tant de fichiers gardés par adresse : au-delà, les plus anciens sont retirés (comme la place dépassée)
KEPT_PER_PERSON = 500
#: les instants des derniers envois gardés par adresse (le quota du jour en compte au plus ``per_day``)
STAMPS_KEPT = 128


class SharesParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    per_day: Annotated[int, Knob(
        label="Fichiers par personne et par jour", group="Envoyer", lo=0, hi=100,
        help="Combien de fichiers elle peut préparer pour une même personne sur 24 heures glissantes ; au-delà, "
             "elle garde la suite pour ses messages. 0 : elle n'en envoie plus.")] = 10
    text_max_chars: Annotated[int, Knob(
        label="Longueur d'un texte envoyé (caractères)", group="Envoyer", lo=1_000, hi=500_000,
        help="Un texte qu'elle écrit pour l'envoyer (une liste, une note, du code) ne dépasse pas cette longueur — "
             "ni 512 Kio une fois encodé.")] = 200_000
    project_max_mb: Annotated[int, Knob(
        label="Taille d'un fichier de projet envoyé (Mio)", group="Envoyer", lo=1, hi=MAX_SHARE_BYTES // MIB,
        help="Un fichier de l'atelier d'un projet plus gros que cela n'est pas envoyé (elle le dit).")] = 10
    keep_days: Annotated[int, Knob(
        label="Garder un fichier envoyé (jours)", group="Garder", lo=1, hi=3650,
        help="Au-delà, un fichier envoyé est retiré : ses octets sont effacés, son message dit qu'il n'est plus "
             "disponible.")] = 365
    per_person_mb: Annotated[int, Knob(
        label="Place par personne (Mio)", group="Garder", lo=10, hi=10_000,
        help="Quand les fichiers gardés pour une personne dépassent cette place, les plus anciens sont retirés.")] = 200


def params(p: SharesParams | None) -> SharesParams:
    return p if p is not None else SharesParams()


def params_of(frame: Frame) -> SharesParams:
    return params(frame.env.params_of(c.OWNER, frame.root))


@dataclass(frozen=True, slots=True)
class SharesState:
    #: adresse → les fichiers encore gardés pour elle, du plus ancien au plus récent
    sent: FrozenDict[str, tuple[c.SentView, ...]] = field(default_factory=FrozenDict)
    #: adresse → les instants de ses derniers envois (le quota du jour)
    stamps: FrozenDict[str, tuple[int, ...]] = field(default_factory=FrozenDict)


SHARES = Faculty("shares", state=SharesState, init=lambda p: SharesState(), params=SharesParams)
SHARES.declare(*c.ALL)


@SHARES.reducer(c.SHARED)
def _shared(s: SharesState, e: Any, cx: Any) -> SharesState:
    d = e.data
    kept = s.sent.get(d.target, ())
    if any(v.file == d.file for v in kept):
        return s
    view = c.SentView(file=d.file, at=e.at, size=d.size, name_ref=d.name.ref or "", kind=d.kind, origin=d.origin,
                      project=d.project)
    stamps = (*s.stamps.get(d.target, ()), e.at)[-STAMPS_KEPT:]
    return replace(s, sent=s.sent.set(d.target, (*kept, view)), stamps=s.stamps.set(d.target, stamps))


@SHARES.reducer(c.EXPIRED)
def _expired(s: SharesState, e: Any, cx: Any) -> SharesState:
    gone = set(e.data.files)
    kept = s.sent.get(e.data.target, ())
    left = tuple(v for v in kept if v.file not in gone)
    if len(left) == len(kept):
        return s
    return replace(s, sent=s.sent.set(e.data.target, left) if left else s.sent.delete(e.data.target))


@SHARES.reducer(rt.UTTERANCE)
def _carried(s: SharesState, e: Any, cx: Any) -> SharesState:
    """Le message qui les emporte : ses fichiers sont partis (le premier message qui les porte fait foi)."""
    d = e.data
    if not d.attachments or not d.target or not d.visible:
        return s
    kept = s.sent.get(d.target, ())
    wanted = set(d.attachments)
    if not any(v.file in wanted and not v.message for v in kept):
        return s
    marked = tuple(replace(v, message=e.seq) if v.file in wanted and not v.message else v for v in kept)
    return replace(s, sent=s.sent.set(d.target, marked))


@SHARES.fact(c.SENT_TODAY)
def _sent_today(s: SharesState, cx: Any, handle: str) -> int:
    since = cx.now - DAY
    return sum(1 for at in s.stamps.get(handle, ()) if at > since)


@SHARES.fact(c.RECENT)
def _recent(s: SharesState, cx: Any, handle: str) -> tuple[c.SentView, ...]:
    return s.sent.get(handle, ())


# ── La projection T0 ──────────────────────────────────────────────────────

_COLUMNS = ("id", "at", "person", "subjects", "name", "path", "mime", "size", "digest", "kind", "origin",
            "project", "message", "expired_at", "reason")


def _subjects(target: str, about: Sequence[str]) -> str:
    """Les sujets d'une ligne, entre barres (``|user_7|name:alice|``) : l'oubli d'un seul d'entre eux la retire."""
    keys = sorted({k for k in (target, *about) if k})
    return "|" + "|".join(keys) + "|"


def _forgotten(text: Any) -> bool:
    """Un texte relu après l'oubli de qui il concerne : sa référence reste, plus son texte."""
    return text is not None and getattr(text, "ref", None) is not None and getattr(text, "text", None) is None


class SharedFiles:
    """T0 : une ligne par fichier préparé (même transaction que l'ajout : l'écran qui reçoit le message trouve
    déjà ses fichiers)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {c.TABLE}{sfx}("
            "id TEXT PRIMARY KEY, at INTEGER NOT NULL, person TEXT NOT NULL, subjects TEXT NOT NULL, "
            "name TEXT NOT NULL, path TEXT, mime TEXT NOT NULL, size INTEGER NOT NULL, digest TEXT NOT NULL, "
            "kind TEXT NOT NULL, origin TEXT NOT NULL, project INTEGER, message INTEGER, expired_at INTEGER, "
            "reason TEXT)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {c.TABLE}{sfx}_person ON {c.TABLE}{sfx}(person, at)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.TABLE}{sfx}")

    def apply(self, sql: Sql, items: Sequence[Any], sfx: str) -> None:
        table = f"{c.TABLE}{sfx}"
        for e in items:
            d = e.data
            name = e.type.name
            if name == c.SHARED.name:
                if _forgotten(d.name) or _forgotten(d.path):
                    # une reconstruction relit tout le journal : un fichier dont le nom a été oublié ne revient pas
                    continue
                marks = ",".join("?" * len(_COLUMNS))
                sql.execute(f"INSERT OR IGNORE INTO {table}({','.join(_COLUMNS)}) VALUES({marks})", (
                    d.file, e.at, d.target, _subjects(d.target, d.about), d.name.text or "",
                    d.path.text if d.path is not None else None, d.mime, d.size, d.digest, d.kind, d.origin,
                    d.project, None, None, None))
            elif name == c.EXPIRED.name and d.files:
                marks = ",".join("?" * len(d.files))
                sql.execute(f"UPDATE {table} SET expired_at=?, reason=? WHERE id IN ({marks}) AND expired_at IS NULL",
                            (e.at, d.reason, *d.files))
            elif name == rt.UTTERANCE.name and d.attachments and d.target and d.visible:
                marks = ",".join("?" * len(d.attachments))
                sql.execute(f"UPDATE {table} SET message=? WHERE id IN ({marks}) AND person=? AND message IS NULL",
                            (e.seq, *d.attachments, d.target))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.TABLE}{sfx} WHERE person=? OR instr(subjects, ?) > 0",
                    (subject, f"|{subject}|"))


SHARES.projector(c.TABLE, version=1, tier=Tier.T0, types=[c.SHARED, c.EXPIRED, rt.UTTERANCE])(SharedFiles)


@dataclass(frozen=True, slots=True)
class FileRow:
    """Une ligne de ``shared_files`` : ce qu'on sait d'un fichier préparé."""

    id: str
    at: int
    person: str
    name: str
    path: str | None
    mime: str
    size: int
    digest: str
    kind: str
    origin: str
    project: int | None
    message: int | None
    expired_at: int | None
    reason: str | None

    @property
    def gone(self) -> bool:
        return self.expired_at is not None

    @property
    def sent(self) -> bool:
        return bool(self.message)


def _row(r: Sequence[Any]) -> FileRow:
    got = dict(zip(_COLUMNS, r, strict=True))
    got.pop("subjects")
    return FileRow(**got)


def rows(store: Any, files: Sequence[str]) -> list[FileRow]:
    """Ces fichiers, dans l'ordre demandé (ceux qu'on ne connaît pas, ou plus, n'y sont pas)."""
    wanted = list(dict.fromkeys(f for f in files if isinstance(f, str)))
    if store is None or not wanted:
        return []
    marks = ",".join("?" * len(wanted))
    found = {r[0]: _row(r) for r in store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.TABLE} WHERE id IN ({marks})", tuple(wanted))}
    return [found[f] for f in wanted if f in found]


def row(store: Any, file: str) -> FileRow | None:
    got = rows(store, [file])
    return got[0] if got else None


def of_people(store: Any, handles: Sequence[str], limit: int, before_at: int | None = None) -> list[FileRow]:
    """Les fichiers préparés pour ces adresses, du plus récent au plus ancien (une page)."""
    if store is None or not handles:
        return []
    marks = ",".join("?" * len(handles))
    clause, args = f"person IN ({marks})", list(handles)
    if before_at is not None:
        clause += " AND at<?"
        args.append(before_at)
    found = store.query_mind(f"SELECT {','.join(_COLUMNS)} FROM {c.TABLE} WHERE {clause} ORDER BY at DESC, id "
                             "LIMIT ?", (*args, limit))
    return [_row(r) for r in found]


# ── La rétention ──────────────────────────────────────────────────────────


def _over(files: Sequence[c.SentView], budget: int) -> list[str]:
    """Les plus anciens à retirer pour que ce qui reste tienne dans la place et le nombre gardés."""
    total, count, out = sum(v.size for v in files), len(files), []
    for v in files:
        if total <= budget and count <= KEPT_PER_PERSON:
            break
        out.append(v.file)
        total -= v.size
        count -= 1
    return out


def due_expiries(state: SharesState, now: int, p: SharesParams) -> list[tuple[str, str, tuple[str, ...]]]:
    """(adresse, raison, fichiers) à retirer maintenant : trop vieux, puis la place dépassée."""
    keep, budget = p.keep_days * DAY, p.per_person_mb * MIB
    out = []
    for target, files in state.sent.items():
        old = tuple(v.file for v in files if v.at + keep <= now)
        if old:
            out.append((target, c.RETENTION, old))
        over = tuple(_over([v for v in files if v.file not in old], budget))
        if over:
            out.append((target, c.BUDGET, over))
    return out


@SHARES.process("shares.retention", wake_on=[c.SHARED, c.EXPIRED], lane="background", catch_up=CatchUp.ONCE,
                max_quantum_s=600)
class Retention:
    """Retirer ce qui a fait son temps : un fichier plus vieux que ``keep_days``, ou les plus anciens quand la place
    d'une personne est dépassée. Ses octets s'effacent après le commit (l'effet de ``shares.expired``)."""

    def next_due(self, state: SharesState, frame: Frame, last_run: int | None) -> int | None:
        p = params_of(frame)
        budget = p.per_person_mb * MIB
        earliest: int | None = None
        for files in state.sent.values():
            if not files:
                continue
            if _over(files, budget):
                return frame.now
            due = files[0].at + p.keep_days * DAY
            earliest = due if earliest is None else min(earliest, due)
        return None if earliest is None else max(frame.now, earliest)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        drafts = [c.EXPIRED.draft(files=files, target=target, reason=reason,
                                  dedupe_key=f"partages-retires:{target}:{reason}:{digest(files)}")
                  for target, reason, files in due_expiries(ctx.state, frame.now, params_of(frame))]
        if drafts:
            await ctx.emit(*drafts)


@SHARES.effect(c.EXPIRED, deadline_s=60.0)
async def _erase(ev: Any, ports: Mapping[str, Any]) -> None:
    """Après le commit : les octets des fichiers retirés s'effacent (idempotent, rejouable)."""
    store = ports.get(PORT)
    if store is not None and ev.data.files:
        await store.delete(tuple(ev.data.files))

