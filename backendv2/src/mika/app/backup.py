"""Sauvegarde et restauration du dossier de données.

Une sauvegarde est une archive ``mika-AAAAMMJJ-HHMMSS.tar.gz`` de ce qui ne
se reconstruit pas :

- ``mind.db`` (sa vie : journal, contenus, instantanés, comptes, réglages) et
  les autres bases (caches du courrier et des flux, stockage des apps
  forgées), copiées par l'API de sauvegarde de SQLite : cohérentes même
  serveur en marche, WAL compris ;
- ses apps forgées (``forge/``, avec leurs versions) et ses ateliers
  (``ateliers/``, avec leur git) ;
- ``secret.key`` quand la clé de chiffrement vient de ce fichier (sans elle,
  les secrets rangés dans les réglages sont perdus) ;
- ``MANIFEST.json`` : tête du journal, empreinte de l'état **rejoué depuis la
  copie**, somme SHA-256 de chaque fichier.

``views.db`` n'y est pas : projections et vecteurs se reconstruisent depuis
le journal au démarrage suivant.

Restaurer vérifie les sommes, rejoue la copie et compare son empreinte au
manifeste **avant** de toucher au dossier de données ; l'ancien dossier est
mis de côté, jamais effacé.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.app.composition import faculties
from mika.kernel.codec import digest
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME

FORMAT = 1
MANIFEST = "MANIFEST.json"
#: jetables : se reconstruisent depuis le journal
SKIPPED = frozenset({"views.db", "views.db-wal", "views.db-shm"})
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
ARCHIVE_PREFIX = "mika-"


class BackupError(RuntimeError):
    """Une sauvegarde ou une restauration refusée ; le message dit pourquoi."""


@dataclass(frozen=True, slots=True)
class Summary:
    archive: Path
    head: int
    state: str
    files: int
    size: int
    warnings: tuple[str, ...] = ()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_sqlite(path: Path) -> bool:
    if path.suffix != ".db":
        return False
    with path.open("rb") as f:
        return f.read(16) == b"SQLite format 3\x00"


def _copy_sqlite(src: Path, dst: Path) -> None:
    """Copie cohérente, même pendant que le serveur écrit (API de sauvegarde)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(str(dst))
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
        problem = target.execute("PRAGMA integrity_check").fetchone()[0]
        if problem != "ok":
            raise BackupError(f"copie de {src.name} corrompue : {problem}")
    finally:
        target.close()
        source.close()


def state_of(mind_db: Path) -> tuple[int, str]:
    """(tête, empreinte de l'état persisté) d'une copie de ``mind.db``, rejouée
    dans un dossier jetable (la copie n'est jamais modifiée)."""
    with tempfile.TemporaryDirectory(prefix="mika-verif-") as tmp:
        work = Path(tmp)
        shutil.copy2(mind_db, work / "mind.db")

        async def replay() -> tuple[int, str]:
            store = SqliteStore(work / "mind.db", work / "views.db", threaded=False)
            mind = Mind(Registry([RUNTIME, *faculties()]), store, RealClock(), RandomIdGen())
            report = await mind.boot(append_boot=False)
            state = digest({o: mind.root.slices[o] for o in mind.registry.persisted_owners()})
            await mind.close()
            return report.head, state

        return asyncio.run(replay())


def _members(data: Path) -> list[Path]:
    out = []
    for path in sorted(data.rglob("*")):
        rel = path.relative_to(data)
        if path.is_dir() or path.is_symlink() or rel.name in SKIPPED or rel.parts[0].startswith("."):
            continue
        if any(rel.name.endswith(".db" + s) for s in _SQLITE_SIDECARS):
            continue
        out.append(rel)
    return out


def backup(data: Path, dest: Path, *, keep: int = 0, now: datetime | None = None) -> Summary:
    """Écrit une archive dans ``dest`` ; garde les ``keep`` plus récentes (0 : toutes)."""
    data, dest = data.resolve(), dest.resolve()
    if not (data / "mind.db").exists():
        raise BackupError(f"pas de mind.db dans {data}")
    if dest == data or data in dest.parents:
        raise BackupError("la destination ne peut pas être dans le dossier de données")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    archive = dest / f"{ARCHIVE_PREFIX}{stamp}.tar.gz"
    warnings = []
    if os.environ.get("MIKA_SECRET_KEY", "").strip():
        warnings.append("la clé de chiffrement vient de MIKA_SECRET_KEY : sauvegarde-la à part")
    with tempfile.TemporaryDirectory(prefix=".mika-sauvegarde-", dir=dest) as tmp:
        stage = Path(tmp) / "data"
        stage.mkdir()
        files: dict[str, str] = {}
        for rel in _members(data):
            src, dst = data / rel, stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if _is_sqlite(src):
                _copy_sqlite(src, dst)
            else:
                shutil.copy2(src, dst)
            files[rel.as_posix()] = _sha256(dst)
        head, state = state_of(stage / "mind.db")
        manifest = {"format": FORMAT, "created": stamp, "head": head, "state": state, "files": files}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(stage, arcname="data")
        partial.replace(archive)
    if keep > 0:
        for old in sorted(dest.glob(f"{ARCHIVE_PREFIX}*.tar.gz"))[:-keep]:
            old.unlink()
    return Summary(archive, head, state, len(files), archive.stat().st_size, tuple(warnings))


def _extract(archive: Path, into: Path) -> dict[str, Any]:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(into, filter="data")  # ni chemin absolu, ni « .. », ni lien vers l'extérieur
    except (tarfile.TarError, OSError) as exc:
        raise BackupError(f"archive illisible : {exc}") from exc
    root = into / "data"
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("archive sans manifeste lisible") from exc
    if manifest.get("format") != FORMAT:
        raise BackupError(f"format de sauvegarde inconnu : {manifest.get('format')!r}")
    for rel, expected in manifest.get("files", {}).items():
        path = root / rel
        if not path.is_file() or _sha256(path) != expected:
            raise BackupError(f"fichier absent ou altéré dans l'archive : {rel}")
    return manifest


def verify(archive: Path) -> Summary:
    """Vérifie une archive sans rien restaurer : sommes, rejeu, empreinte."""
    with tempfile.TemporaryDirectory(prefix="mika-verif-") as tmp:
        manifest = _extract(archive, Path(tmp))
        head, state = state_of(Path(tmp) / "data" / "mind.db")
    if (head, state) != (manifest["head"], manifest["state"]):
        raise BackupError("la copie ne rejoue pas à l'état enregistré dans le manifeste")
    return Summary(archive, head, state, len(manifest["files"]), archive.stat().st_size)


def restore(archive: Path, data: Path, *, force: bool = False, now: datetime | None = None) -> Summary:
    """Restaure dans ``data``. Un dossier non vide n'est remplacé qu'avec
    ``force`` ; il est alors mis de côté (``<data>.avant-restauration-…``)."""
    data = data.resolve()
    if data.exists() and any(data.iterdir()) and not force:
        raise BackupError(f"{data} n'est pas vide : relance avec --force (l'ancien dossier sera mis de côté)")
    data.parent.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    stage_root = Path(tempfile.mkdtemp(prefix=f".{data.name}.restauration-", dir=data.parent))
    try:
        manifest = _extract(archive, stage_root)
        stage = stage_root / "data"
        head, state = state_of(stage / "mind.db")
        if (head, state) != (manifest["head"], manifest["state"]):
            raise BackupError("la copie ne rejoue pas à l'état enregistré dans le manifeste : rien n'est touché")
        (stage / MANIFEST).unlink()
        warnings = []
        if data.exists():
            aside = data.parent / f"{data.name}.avant-restauration-{stamp}"
            data.rename(aside)
            warnings.append(f"ancien dossier mis de côté : {aside}")
        stage.rename(data)
        for sub in ("forge", "ateliers"):
            (data / sub).mkdir(exist_ok=True)
        key = data / "secret.key"
        if key.exists():
            key.chmod(0o600)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return Summary(archive, head, state, len(manifest["files"]), archive.stat().st_size, tuple(warnings))
