"""Sauvegarde et restauration du dossier de données.

Une sauvegarde est une archive ``mika-AAAAMMJJ-HHMMSS.tar.gz`` de ce qui ne
se reconstruit pas :

- ``mind.db`` (sa vie : journal, contenus, instantanés, comptes, réglages) et
  les autres bases (caches du courrier et des flux, stockage des apps
  forgées), copiées par l'API de sauvegarde de SQLite : cohérentes même
  serveur en marche, WAL compris ;
- ses apps forgées (``forge/``, avec leurs versions), ses ateliers
  (``ateliers/``, avec leur git) et les fichiers qu'elle a envoyés
  (``partages/``, ADR 0062 : leurs octets ne sont pas dans le journal) ; un
  lien symbolique est gardé comme un lien (sa cible, dans le manifeste) et
  recréé à la restauration : sans lui, le prochain commit de l'atelier
  enregistrerait sa suppression ;
- ``secret.key`` quand la clé de chiffrement vient de ce fichier (sans elle,
  les secrets rangés dans les réglages sont perdus) ;
- ``MANIFEST.json`` : tête du journal, empreinte de l'état **rejoué depuis la
  copie**, empreinte du code qui l'a rejouée, somme SHA-256 de chaque fichier.

``views.db`` n'y est pas : projections et vecteurs se reconstruisent depuis
le journal au démarrage suivant.

Restaurer vérifie les sommes, rejoue la copie et compare son empreinte au
manifeste **avant** de toucher au dossier de données. L'empreinte de l'état
dépend du code autant que des données (un champ de tranche, un réducteur
corrigé, un upcaster la changent) : elle ne se compare que sous le code qui a
écrit l'archive. Sous un autre (une mise à jour depuis), la copie est rejouée
depuis la genèse et doit retomber sur la même tête sans qu'aucun réducteur ne
lève ; c'est dit dans les remarques. L'ancien dossier est
mis de côté, jamais effacé. Restaurer prend le verrou du dossier
(``datadir``) : sous un serveur en marche, c'est refusé — il écrirait encore,
par ses descripteurs ouverts, dans le dossier mis de côté.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.app import datadir
from mika.app.composition import faculties
from mika.kernel.codec import digest
from mika.kernel.inspect import describe_error
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME

FORMAT = 1
MANIFEST = "MANIFEST.json"
#: jetables : se reconstruisent depuis le journal
SKIPPED = frozenset({"views.db", "views.db-wal", "views.db-shm", "sauvegardes.json", "sauvegardes.partial",
                     datadir.LOCK_NAME})
#: dossiers jamais archivés : ceux des appels de la CLI de Claude Code (prompts privés, jetons de session)
#: d'une installation d'avant leur déménagement sous XDG_RUNTIME_DIR
SKIPPED_DIRS = frozenset({"claude-code"})
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
ARCHIVE_PREFIX = "mika-"
#: ce que la console lit des sauvegardes : la dernière, la dernière vérification (dans le dossier de données)
RECORD = "sauvegardes.json"


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


def code_fingerprint() -> str:
    """Empreinte du code qui rejoue : les sources du paquet ``mika``. Deux empreintes d'état ne se
    comparent que sous la même : l'état rejoué en dépend autant que des données."""
    root = Path(__file__).resolve().parent.parent
    h = hashlib.blake2b(digest_size=16)
    for path in sorted(root.rglob("*.py")):
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\x00")
        h.update(path.read_bytes() + b"\x00")
    return h.hexdigest()


def state_of(mind_db: Path) -> tuple[int, str]:
    """(tête, empreinte de l'état persisté) d'une copie de ``mind.db``, rejouée
    dans un dossier jetable (la copie n'est jamais modifiée)."""
    head, state, _ = _replay(mind_db)
    return head, state


def _replay(mind_db: Path, *, genesis: bool = False) -> tuple[int, str, list[str]]:
    """(tête, empreinte, tranches dont un réducteur a levé) d'une copie de ``mind.db`` rejouée dans un
    dossier jetable. ``genesis`` : sans ses instantanés (écrits par le code d'alors), tout le journal
    repasse par les réducteurs d'aujourd'hui."""
    with tempfile.TemporaryDirectory(prefix="mika-verif-") as tmp:
        work = Path(tmp)
        shutil.copy2(mind_db, work / "mind.db")
        if genesis:
            db = sqlite3.connect(str(work / "mind.db"))
            try:
                with db:
                    db.execute("DELETE FROM snapshots")
            finally:
                db.close()

        async def replay() -> tuple[int, str, list[str]]:
            store = SqliteStore(work / "mind.db", work / "views.db", threaded=False)
            mind = Mind(Registry([RUNTIME, *faculties()]), store, RealClock(), RandomIdGen())
            report = await mind.boot(append_boot=False)
            state = digest({o: mind.root.slices[o] for o in mind.registry.persisted_owners()})
            tainted = sorted(mind.root.tainted.keys())
            await mind.close()
            return report.head, state, tainted

        return asyncio.run(replay())


def _check(manifest: dict[str, Any], mind_db: Path) -> tuple[int, str, list[str]]:
    """Confronte la copie à son manifeste ; rend (tête, empreinte, remarques).

    Sous le code qui a écrit l'archive, l'état rejoué doit être celui du manifeste. Sous un autre (une
    mise à jour depuis, ou une archive d'avant l'empreinte du code), l'empreinte ne se compare pas :
    des données intactes y rejouent autrement. La copie repasse alors depuis la genèse par le code
    courant et doit retomber sur la même tête sans tranche en échec."""
    if manifest.get("code") == code_fingerprint():
        head, state = state_of(mind_db)
        if (head, state) != (manifest["head"], manifest["state"]):
            raise BackupError("la copie ne rejoue pas à l'état enregistré dans le manifeste")
        return head, state, []
    head, state, tainted = _replay(mind_db, genesis=True)
    if head != manifest["head"]:
        raise BackupError("la copie ne rejoue pas à la tête enregistrée dans le manifeste")
    if tainted:
        raise BackupError(f"archive écrite par une autre version du code : la copie ne se rejoue pas avec "
                          f"celle-ci (tranche(s) en échec : {', '.join(tainted)}) ; relance avec la version "
                          f"qui l'a écrite")
    return head, state, ["archive écrite par une autre version du code : état non comparé, "
                         "copie rejouée depuis la genèse sans erreur"]


def _walk(data: Path) -> tuple[list[Path], list[Path]]:
    """(fichiers, liens symboliques) à archiver, relatifs au dossier. Un lien est un lien
    (jamais suivi : un dossier lié n'est pas parcouru deux fois)."""
    files, links = [], []
    for path in sorted(data.rglob("*")):
        rel = path.relative_to(data)
        if rel.name in SKIPPED or rel.parts[0].startswith(".") or rel.parts[0] in SKIPPED_DIRS:
            continue
        if path.is_symlink():
            links.append(rel)
            continue
        if path.is_dir():
            continue
        if any(rel.name.endswith(".db" + s) for s in _SQLITE_SIDECARS):
            continue
        files.append(rel)
    return files, links


def _members(data: Path) -> list[Path]:
    """Les fichiers à archiver (les liens symboliques à part : ``_links``)."""
    return _walk(data)[0]


def _links(data: Path) -> list[Path]:
    """Les liens symboliques à garder comme des liens (leur cible, dans le manifeste)."""
    return _walk(data)[1]


def _safe_rel(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and not PurePosixPath(rel).is_absolute() and ".." not in parts \
        and not parts[0].startswith(".") and "\x00" not in rel


def _relink(root: Path, links: object) -> None:
    """Recrée dans ``root`` les liens symboliques du manifeste. Un lien n'est créé que dans
    le dossier (jamais à travers un lien qui en sortirait) ; une entrée invalide refuse
    l'archive."""
    if not isinstance(links, dict):
        raise BackupError("liens illisibles dans le manifeste")
    base = root.resolve()
    for rel, target in sorted(links.items()):
        if not isinstance(rel, str) or not _safe_rel(rel) or not isinstance(target, str) or not target \
                or "\x00" in target:
            raise BackupError(f"lien invalide dans l'archive : {rel!r}")
        path = root / rel
        if not path.parent.resolve().is_relative_to(base):  # avant de créer quoi que ce soit
            raise BackupError(f"lien hors du dossier dans l'archive : {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            raise BackupError(f"lien en double dans l'archive : {rel}")
        path.symlink_to(target)


def backup(data: Path, dest: Path, *, keep: int = 0, now: datetime | None = None) -> Summary:
    """Écrit une archive dans ``dest`` ; garde les ``keep`` plus récentes (0 : toutes).

    Une tentative qui échoue (disque plein, dossier des archives devenu illisible…) se note avec sa
    cause en mots (``tentative``, lue par la console) et ne laisse pas d'archive partielle derrière
    elle ; l'erreur sort en ``BackupError``."""
    data, dest = data.resolve(), dest.resolve()
    if not (data / "mind.db").exists():
        raise BackupError(f"pas de mind.db dans {data}")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    archive = dest / f"{ARCHIVE_PREFIX}{stamp}.tar.gz"
    try:
        done = _write(data, dest, archive, stamp, keep)
    except (BackupError, OSError, sqlite3.Error, tarfile.TarError) as exc:
        why = str(exc) if isinstance(exc, BackupError) else _why(exc, dest)
        with contextlib.suppress(OSError):  # la cause à noter est l'échec, pas ce nettoyage
            archive.with_suffix(".partial").unlink(missing_ok=True)
        note(data, "tentative", {"at": _us(now), "dossier": str(dest), "ok": False, "erreur": why})
        if isinstance(exc, BackupError):
            raise
        raise BackupError(why) from exc
    note(data, "sauvegarde", {"at": _us(now), "archive": str(archive), "dossier": str(dest),
                              "tete": done.head, "fichiers": done.files, "octets": done.size, "garde": keep,
                              "remarques": list(done.warnings)})
    return done


def _why(exc: BaseException, dest: Path) -> str:
    """La cause d'un échec d'écriture, en mots : un disque plein le dit tel quel (le système le dit en
    anglais, SQLite aussi) et nomme le dossier des archives plutôt que le fichier de travail qui y
    était écrit ; le reste passe par ``describe_error``."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        where = Path(str(exc.filename2 or exc.filename or dest))
        return f"plus de place sur le disque : {dest if where.is_relative_to(dest) else where}"
    if isinstance(exc, sqlite3.Error) and exc.sqlite_errorcode & 0xFF == sqlite3.SQLITE_FULL:
        return f"plus de place sur le disque : {dest}"
    return describe_error(exc)


def _write(data: Path, dest: Path, archive: Path, stamp: str, keep: int) -> Summary:
    """L'archive elle-même (``backup`` note ce qu'elle a donné)."""
    if dest == data or data in dest.parents:
        raise BackupError("la destination ne peut pas être dans le dossier de données")
    dest.mkdir(parents=True, exist_ok=True)
    warnings = []
    if os.environ.get("MIKA_SECRET_KEY", "").strip():
        warnings.append("la clé de chiffrement vient de MIKA_SECRET_KEY : sauvegarde-la à part")
    with tempfile.TemporaryDirectory(prefix=".mika-sauvegarde-", dir=dest) as tmp:
        stage = Path(tmp) / "data"
        stage.mkdir()
        files: dict[str, str] = {}
        members, linked = _walk(data)
        links = {rel.as_posix(): os.readlink(data / rel) for rel in linked}
        for rel in members:
            src, dst = data / rel, stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if _is_sqlite(src):
                _copy_sqlite(src, dst)
            else:
                shutil.copy2(src, dst)
            files[rel.as_posix()] = _sha256(dst)
        head, state = state_of(stage / "mind.db")
        manifest = {"format": FORMAT, "created": stamp, "head": head, "state": state, "code": code_fingerprint(),
                    "files": files, "links": links}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(stage, arcname="data")
        partial.replace(archive)
    if keep > 0:
        for old in sorted(dest.glob(f"{ARCHIVE_PREFIX}*.tar.gz"))[:-keep]:
            old.unlink()
    return Summary(archive, head, state, len(files), archive.stat().st_size, tuple(warnings))


def _us(now: datetime | None) -> int:
    return int((now or datetime.now(UTC)).timestamp() * 1_000_000)


def note(data: Path, kind: str, fields: dict[str, Any]) -> None:
    """Note dans le dossier de données ce qu'une sauvegarde ou une vérification a donné (la console
    le lit : Système › Stockage). Écrit d'un coup, jamais à moitié ; un échec d'écriture ne fait pas
    échouer la sauvegarde."""
    path = Path(data) / RECORD
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(current, dict):
            current = {}
        current[kind] = fields
        partial = path.with_suffix(".partial")
        partial.write_text(json.dumps(current, indent=1, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)
    except (OSError, ValueError):
        pass


def overview(data: Path) -> dict[str, Any]:
    """Pour la console : la dernière sauvegarde, la dernière vérification, et les archives présentes
    dans le dossier de la dernière sauvegarde (nom, octets, date)."""
    got = recorded(data)
    folder = Path(str((got.get("sauvegarde") or {}).get("dossier") or ""))
    archives: list[dict[str, Any]] = []
    if str(folder) not in ("", ".") and folder.is_dir():
        for f in sorted(folder.glob(f"{ARCHIVE_PREFIX}*.tar.gz"), reverse=True):
            try:
                st = f.stat()
            except OSError:
                continue
            archives.append({"nom": f.name, "octets": st.st_size, "at": int(st.st_mtime * 1_000_000)})
    return {**got, "archives": archives}


def recorded(data: Path) -> dict[str, Any]:
    """Ce que les dernières sauvegardes et vérifications ont noté (vide : jamais)."""
    try:
        got = json.loads((Path(data) / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


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
    _relink(root, manifest.get("links", {}))  # une archive d'avant les liens n'en a pas
    return manifest


def verify(archive: Path, *, record: Path | None = None, now: datetime | None = None) -> Summary:
    """Vérifie une archive sans rien restaurer : sommes, rejeu, empreinte (``_check``). ``record`` : le
    dossier de données où noter le résultat (réussi ou non) pour la console."""
    try:
        with tempfile.TemporaryDirectory(prefix="mika-verif-") as tmp:
            manifest = _extract(archive, Path(tmp))
            head, state, warnings = _check(manifest, Path(tmp) / "data" / "mind.db")
    except BackupError as exc:
        if record is not None:
            note(record, "verification", {"at": _us(now), "archive": str(archive), "ok": False, "erreur": str(exc)})
        raise
    if record is not None:
        note(record, "verification", {"at": _us(now), "archive": str(archive), "ok": True, "tete": head,
                                      "remarques": warnings})
    return Summary(archive, head, state, len(manifest["files"]), archive.stat().st_size, tuple(warnings))


def restore(archive: Path, data: Path, *, force: bool = False, now: datetime | None = None) -> Summary:
    """Restaure dans ``data``. Un dossier non vide n'est remplacé qu'avec
    ``force`` ; il est alors mis de côté (``<data>.avant-restauration-…``).

    Le verrou du dossier est pris d'abord : un Mika qui tourne dessus (``DataDirBusy``) ne voit
    rien bouger. Il passe au dossier restauré avec son fichier, tenu jusqu'au bout."""
    data = data.resolve()
    fresh = not data.exists()
    datadir.hold(data)  # crée le dossier s'il n'existait pas : on le retire si rien n'est restauré
    lock = data / datadir.LOCK_NAME
    done = False
    try:
        if any(p.name != datadir.LOCK_NAME for p in data.iterdir()) and not force:
            raise BackupError(f"{data} n'est pas vide : relance avec --force (l'ancien dossier sera mis de côté)")
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        stage_root = Path(tempfile.mkdtemp(prefix=f".{data.name}.restauration-", dir=data.parent))
        try:
            manifest = _extract(archive, stage_root)
            stage = stage_root / "data"
            try:
                head, state, warnings = _check(manifest, stage / "mind.db")
            except BackupError as exc:
                raise BackupError(f"{exc} : rien n'est touché") from exc
            (stage / MANIFEST).unlink()
            lock.replace(stage / datadir.LOCK_NAME)  # le verrou (son inode, tenu) suit le dossier restauré
            if any(data.iterdir()):
                aside = data.parent / f"{data.name}.avant-restauration-{stamp}"
                data.rename(aside)
                warnings.append(f"ancien dossier mis de côté : {aside}")
            else:
                data.rmdir()
            stage.rename(data)
            done = True
            for sub in ("forge", "ateliers", "partages"):
                (data / sub).mkdir(exist_ok=True)
            (data / "partages").chmod(0o700)  # ce qu'elle a envoyé à chacun : à elle seule
            key = data / "secret.key"
            if key.exists():
                key.chmod(0o600)
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)
    finally:
        datadir.release(data)
        if fresh and not done:  # rien de restauré : le dossier n'existait pas, il n'existe plus
            lock.unlink(missing_ok=True)
            try:
                data.rmdir()
            except OSError:
                pass
    return Summary(archive, head, state, len(manifest["files"]), archive.stat().st_size, tuple(warnings))
