"""Sauvegarde et restauration du dossier de données.

Une sauvegarde est une archive ``mika-AAAAMMJJ-HHMMSS.tar.gz`` de ce qui ne
se reconstruit pas :

- ``mind.db`` (sa vie : journal, contenus, instantanés, comptes, réglages) et
  les autres bases (caches du courrier et des flux, stockage des apps
  forgées), copiées par l'API de sauvegarde de SQLite : cohérentes même
  serveur en marche, WAL compris ;
- ses apps forgées (``forge/``, avec leurs versions), ses ateliers
  (``ateliers/``, avec leur git), les fichiers qu'elle a envoyés
  (``partages/``, ADR 0062 : leurs octets ne sont pas dans le journal) et les
  pièces jointes qu'on lui a envoyées (``pieces/``, ADR 0106) ; un
  lien symbolique est gardé comme un lien (sa cible, dans le manifeste) et
  recréé à la restauration : sans lui, le prochain commit de l'atelier
  enregistrerait sa suppression ;
- ``secret.key`` quand la clé de chiffrement vient de ce fichier (sans elle,
  les secrets rangés dans les réglages sont perdus), et la clé Firebase des
  notifications quand elle est posée en fichier (``firebase-service-account.json``,
  ADR 0077) ;
- ``MANIFEST.json`` : tête du journal, empreinte de l'état **rejoué depuis la
  copie**, empreinte du code qui l'a rejouée, somme SHA-256 de chaque fichier.

``views.db`` n'y est pas : projections et vecteurs se reconstruisent depuis
le journal au démarrage suivant.

**Sur un serveur MariaDB** (``MIKA_DATABASE_URL``, ADR 0101 point 10), ses
bases ne sont pas des fichiers du dossier : l'archive porte, à côté du dossier
(``data/``), une copie SQL de chacune (``bases/`` : ``mind``, ``mail``,
``feeds``, ``teams`` et la base de chaque app forgée), faite par
``mariadb-dump`` en un instantané cohérent, serveur en marche
(``backup_server``). La vérification recharge ``mind`` dans une base de
travail et l'y rejoue. La restauration vérifie les sommes et rejoue ``mind``
rechargé dans une base de travail, **copie les bases en service** dans le
dossier mis de côté (``<dossier>/.avant-restauration-…/bases/``), puis recharge
chaque copie à sa place ; ``views`` est vidée (elle se reconstruit). Une copie
qui ne se rechargerait pas en route laisse les bases en service à portée de
main, dans ce dossier mis de côté. Une archive faite sur
fichiers ne se restaure pas sur un serveur, ni l'inverse.

Restaurer vérifie les sommes, rejoue la copie et compare son empreinte au
manifeste **avant** de toucher au dossier de données. L'empreinte de l'état
dépend du code autant que des données (un champ de tranche, un réducteur
corrigé, un upcaster la changent) : elle ne se compare que sous le code qui a
écrit l'archive. Sous un autre (une mise à jour depuis), la copie est rejouée
depuis la genèse et doit retomber sur la même tête sans qu'aucun réducteur ne
lève ; c'est dit dans les remarques. L'ancien contenu est
mis de côté, jamais effacé. Tout se passe **dans** le dossier de données :
l'archive y est préparée (``.restauration-…``), l'ancien contenu y est mis de
côté (``.avant-restauration-…``), puis chaque entrée prend sa place — en
service, l'utilisateur ``mika`` ne peut écrire que dans ``/var/lib/mika``, pas
dans ``/var/lib``. Ces dossiers cachés n'entrent dans aucune archive, et ce que
la sauvegarde ne prend pas (``SKIPPED_DIRS`` : le modèle de plongements) reste
en place. Restaurer prend le verrou du dossier
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
import re
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from mika.adapters.database import Target, as_target
from mika.adapters.store_sql import SqlStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.app import backup_server, datadir, schema
from mika.app.composition import READING, faculties
from mika.app.settings import PUSH_KEY_FILE
from mika.kernel.codec import digest
from mika.kernel.inspect import describe_error
from mika.kernel.registry import Registry
from mika.ports.journal import JournalSnapshot
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME

FORMAT = 1
MANIFEST = "MANIFEST.json"
#: les copies des bases d'un serveur, à côté du dossier, dans l'archive
BASES = "bases"
#: jetables : se reconstruisent depuis le journal
SKIPPED = frozenset({"views.db", "views.db-wal", "views.db-shm", "sauvegardes.json", "sauvegardes.partial",
                     datadir.LOCK_NAME})
#: dossiers jamais archivés : ceux des appels de la CLI de Claude Code (prompts privés, jetons de session)
#: d'une installation d'avant leur déménagement sous XDG_RUNTIME_DIR ; ``cache`` (``HF_HOME`` de l'unité : le modèle
#: de plongements, qui se retélécharge — 1,2 Go pour Qwen3, ADR 0109)
SKIPPED_DIRS = frozenset({"claude-code", "cache"})
#: dans le dossier de données, ce qu'une restauration prépare et ce qu'elle met de côté (cachés : aucune archive ne
#: les prend, une restauration suivante ne les remplace pas)
STAGING, ASIDE, KEPT = ".restauration-", ".avant-restauration-", ".avant-bases-"
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
    """(tête, empreinte de l'état persisté) d'une copie de ``mind.db`` — ou de la copie SQL de ``mind`` (``.sql``,
    sur un serveur) —, rejouée à part (la copie n'est jamais modifiée)."""
    head, state, _ = _replay(mind_db)
    return head, state


def _replay(mind_copy: Path, *, genesis: bool = False) -> tuple[int, str, list[str]]:
    """(tête, empreinte, tranches dont un réducteur a levé) d'une copie de ``mind`` rejouée à part : un fichier
    SQLite dans un dossier jetable, ou une copie SQL rechargée dans des bases de travail du serveur, supprimées
    ensuite. ``genesis`` : sans ses instantanés (écrits par le code d'alors), tout le journal repasse par les
    réducteurs d'aujourd'hui."""
    if mind_copy.suffix == ".sql":
        url, prefix = _server()
        mind, views = backup_server.scratch(url, prefix, 2)
        try:
            backup_server.load(mind_copy, mind)
            return _replay_on(mind, views, genesis)
        finally:
            mind.drop()
            views.drop()
    with tempfile.TemporaryDirectory(prefix="mika-verif-") as tmp:
        work = Path(tmp)
        shutil.copy2(mind_copy, work / "mind.db")
        return _replay_on(work / "mind.db", work / "views.db", genesis)


def _replay_on(mind_at: Path | Target, views_at: Path | Target, genesis: bool) -> tuple[int, str, list[str]]:
    if genesis:
        engine = as_target(mind_at).engine()
        try:
            with engine.begin() as conn:
                conn.execute(delete(JournalSnapshot))
        finally:
            engine.dispose()

    async def replay() -> tuple[int, str, list[str]]:
        store = SqlStore(mind_at, views_at, threaded=False)
        mind = Mind(Registry([RUNTIME, *faculties()], reading=READING), store, RealClock(), RandomIdGen())
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


#: les dossiers des cages : un lien n'y est suivi que par bubblewrap (qui ne voit que ``/usr`` en lecture), jamais
#: par le serveur (``workshop.path`` résout et vérifie ; un serveur MCP vit dans sa cage) — et un dépôt du modèle ou un
#: ``.venv`` en porte légitimement vers le système (``python → /usr/bin/python3``) : les refuser rendrait l'archive
#: entière irrestaurable pour un lien
CAGED_DIRS = ("ateliers", "mcp")


def _relink(root: Path, links: object) -> None:
    """Recrée dans ``root`` les liens symboliques du manifeste. Un lien n'est créé que dans
    le dossier (jamais à travers un lien qui en sortirait) et, hors des cages (``CAGED_DIRS``),
    sa cible reste dans le dossier — ni absolue, ni remontante : ``partages/<id>.bin → /etc/…``,
    le serveur l'ouvrirait lui-même ; une entrée invalide refuse l'archive."""
    if not isinstance(links, dict):
        raise BackupError("liens illisibles dans le manifeste")
    base = root.resolve()
    for rel, target in sorted(links.items()):
        if not isinstance(rel, str) or not _safe_rel(rel) or not isinstance(target, str) or not target \
                or "\x00" in target:
            raise BackupError(f"lien invalide dans l'archive : {rel!r}")
        path = root / rel
        parent = path.parent.resolve()
        if not parent.is_relative_to(base):  # avant de créer quoi que ce soit
            raise BackupError(f"lien hors du dossier dans l'archive : {rel}")
        if PurePosixPath(rel).parts[0] not in CAGED_DIRS and not _stays_inside(parent, target, base):
            raise BackupError(f"lien vers l'extérieur du dossier dans l'archive : {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            raise BackupError(f"lien en double dans l'archive : {rel}")
        path.symlink_to(target)


def _stays_inside(parent: Path, target: str, base: Path) -> bool:
    """La cible d'un lien, vue de son dossier, reste-t-elle dans ``base`` ? (Une cible absolue, jamais.)"""
    if PurePosixPath(target).is_absolute():
        return False
    try:
        return (parent / target).resolve().is_relative_to(base)
    except (OSError, RuntimeError):  # une boucle de liens, un chemin illisible
        return False


def backup(data: Path, dest: Path, *, keep: int = 0, now: datetime | None = None) -> Summary:
    """Écrit une archive dans ``dest`` ; garde les ``keep`` plus récentes (0 : toutes).

    Une tentative qui échoue (disque plein, dossier des archives devenu illisible…) se note avec sa
    cause en mots (``tentative``, lue par la console) et ne laisse pas d'archive partielle derrière
    elle ; l'erreur sort en ``BackupError``."""
    data, dest = data.resolve(), dest.resolve()
    if schema.server_url():
        url, prefix = _server()
        if not backup_server.tables(Target(url=url, name=f"{prefix}mind")):
            raise BackupError(f"pas de base {prefix}mind sur le serveur")
    elif not (data / "mind.db").exists():
        raise BackupError(f"pas de mind.db dans {data}")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    archive = dest / f"{ARCHIVE_PREFIX}{stamp}.tar.gz"
    try:
        done = _write(data, dest, archive, stamp, keep)
    except (BackupError, OSError, sqlite3.Error, tarfile.TarError, backup_server.ServerError, SQLAlchemyError) as exc:
        why = str(exc) if isinstance(exc, BackupError | backup_server.ServerError) else _why(exc, dest)
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


def _server() -> tuple[str, str]:
    """(adresse, préfixe) du serveur de ses bases ; une archive de serveur ne se vérifie ni ne se restaure sans lui."""
    url = schema.server_url()
    if not url:
        raise BackupError("cette archive vient d'un serveur MariaDB : la vérifier ou la restaurer demande ce serveur "
                          "(MIKA_DATABASE_URL)")
    return url, schema.database_prefix()


#: ce qu'une archive de serveur peut nommer : ses bases, et celle d'une app forgée
_BASE_KEY = re.compile(r"^(mind|mail|feeds|teams|forge/[a-z][a-z0-9_]{1,30})$")


def _live(url: str, prefix: str, key: str) -> Target:
    """La base en service d'une clé d'archive (``mind``, ``forge/<app>``…)."""
    name = f"{prefix}forge_{key[6:]}" if key.startswith("forge/") else f"{prefix}{key}"
    return Target(url=url, name=name)


def _server_bases(url: str, prefix: str) -> dict[str, Target]:
    """Ce qu'on sauvegarde sur le serveur : ``mind``, ``mail``, ``feeds``, ``teams`` et la base de chaque app forgée
    (celles qui existent)."""
    out = {key: _live(url, prefix, key) for key in backup_server.KEPT}
    start = f"{prefix}forge_"
    for name in backup_server.named_like(url, start):
        app = name[len(start):]
        if _BASE_KEY.match(f"forge/{app}"):
            out[f"forge/{app}"] = Target(url=url, name=name)
    return out


def _mind_copy(manifest: dict[str, Any], root: Path) -> Path:
    """La copie de ``mind`` dans une archive extraite sous ``root`` : le fichier, ou la copie SQL du serveur."""
    return root / BASES / "mind.sql" if manifest.get("engine") == "mariadb" else root / "data" / "mind.db"


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
    on_server = bool(schema.server_url())
    with tempfile.TemporaryDirectory(prefix=".mika-sauvegarde-", dir=dest) as tmp:
        stage = Path(tmp) / "data"
        stage.mkdir()
        files: dict[str, str] = {}
        members, linked = _walk(data)
        links = {rel.as_posix(): os.readlink(data / rel) for rel in linked}
        for rel in members:
            src, dst = data / rel, stage / rel
            if _is_sqlite(src):
                if on_server:  # un fichier d'avant le serveur : ses bases sont ailleurs, le copier tromperait
                    warnings.append(f"{rel} : une base SQLite d'avant le serveur, laissée hors de l'archive")
                    continue
                _copy_sqlite(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            files[rel.as_posix()] = _sha256(dst)
        bases: dict[str, dict[str, str]] = {}
        if on_server:
            url, prefix = _server()
            for key, target in _server_bases(url, prefix).items():
                rel = f"{BASES}/{key}.sql"
                target.ensure()  # une base encore vide (aucun courrier) se copie vide
                backup_server.dump(target, Path(tmp) / rel)
                bases[key] = {"file": rel, "sha256": _sha256(Path(tmp) / rel)}
            head, state = state_of(Path(tmp) / BASES / "mind.sql")
        else:
            head, state = state_of(stage / "mind.db")
        manifest = {"format": FORMAT, "created": stamp, "head": head, "state": state, "code": code_fingerprint(),
                    "files": files, "links": links}
        if on_server:
            manifest |= {"engine": "mariadb", "bases": bases}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(stage, arcname="data")
            if on_server:
                tar.add(Path(tmp) / BASES, arcname=BASES)
        partial.replace(archive)
    if keep > 0:
        for old in sorted(dest.glob(f"{ARCHIVE_PREFIX}*.tar.gz"))[:-keep]:
            old.unlink()
    return Summary(archive, head, state, len(files), archive.stat().st_size, tuple(warnings))


def _us(now: datetime | None) -> int:
    return int((now or datetime.now(UTC)).timestamp() * 1_000_000)


def note(data: Path, kind: str, fields: dict[str, Any]) -> None:
    """Note dans le dossier de données ce qu'une sauvegarde ou une vérification a donné (la console
    le lit : Système › Stockage et sauvegardes). Écrit d'un coup, jamais à moitié ; un échec d'écriture ne fait pas
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
    bases = manifest.get("bases") or {}
    if manifest.get("engine", "sqlite") not in ("sqlite", "mariadb") or not isinstance(bases, dict) \
            or (manifest.get("engine") == "mariadb" and "mind" not in bases):
        raise BackupError("copies des bases illisibles dans le manifeste")
    for key, entry in bases.items():
        rel = entry.get("file") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not _BASE_KEY.match(key) or rel != f"{BASES}/{key}.sql":
            raise BackupError(f"copie de base invalide dans l'archive : {str(key)[:80]!r}")
        path = into / rel
        if not path.is_file() or _sha256(path) != entry.get("sha256"):
            raise BackupError(f"copie de base absente ou altérée dans l'archive : {key}")
    _relink(root, manifest.get("links", {}))  # une archive d'avant les liens n'en a pas
    return manifest


def verify(archive: Path, *, record: Path | None = None, now: datetime | None = None) -> Summary:
    """Vérifie une archive sans rien restaurer : sommes, rejeu, empreinte (``_check``). ``record`` : le
    dossier de données où noter le résultat (réussi ou non) pour la console."""
    try:
        with tempfile.TemporaryDirectory(prefix="mika-verif-") as tmp:
            manifest = _extract(archive, Path(tmp))
            head, state, warnings = _check(manifest, _mind_copy(manifest, Path(tmp)))
    except BackupError as exc:
        if record is not None:
            note(record, "verification", {"at": _us(now), "archive": str(archive), "ok": False, "erreur": str(exc)})
        raise
    if record is not None:
        note(record, "verification", {"at": _us(now), "archive": str(archive), "ok": True, "tete": head,
                                      "remarques": warnings})
    return Summary(archive, head, state, len(manifest["files"]), archive.stat().st_size, tuple(warnings))


def restore(archive: Path, data: Path, *, force: bool = False, now: datetime | None = None) -> Summary:
    """Restaure dans ``data`` (et, sur un serveur, dans ses bases). Un dossier non vide — ou des bases en service —
    n'est remplacé qu'avec ``force`` ; son contenu est alors mis de côté (``<data>/.avant-restauration-…``, les
    bases copiées dans son ``bases/``).

    Le verrou du dossier est pris d'abord : un Mika qui tourne dessus (``DataDirBusy``) ne voit
    rien bouger. Il reste en place, tenu jusqu'au bout. Rien ne s'écrit hors du dossier (voir plus haut)."""
    data = data.resolve()
    server = schema.server_url()
    fresh = not data.exists()
    datadir.hold(data)  # crée le dossier s'il n'existait pas : on le retire si rien n'est restauré
    lock = data / datadir.LOCK_NAME
    done = False
    try:
        old = _replaced(data)
        occupied = bool(old)
        if server:
            occupied = occupied or _server_occupied(*_server())
        if occupied and not force:
            raise BackupError(f"{data} n'est pas vide{' (ou ses bases sur le serveur)' if server else ''} : relance "
                              f"avec --force (l'ancien contenu sera mis de côté)")
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        stage_root = Path(tempfile.mkdtemp(prefix=STAGING, dir=data))
        try:
            manifest = _extract(archive, stage_root)
            from_server = manifest.get("engine") == "mariadb"
            if from_server and not server:
                raise BackupError("cette archive vient d'un serveur MariaDB : elle se restaure sur un serveur "
                                  "(MIKA_DATABASE_URL), pas dans des fichiers — rien n'est touché")
            if server and not from_server:
                raise BackupError("cette archive est faite de fichiers SQLite : elle ne se restaure pas sur un serveur "
                                  "MariaDB — rien n'est touché")
            stage = stage_root / "data"
            try:
                head, state, warnings = _check(manifest, _mind_copy(manifest, stage_root))
            except (BackupError, backup_server.ServerError, SQLAlchemyError) as exc:
                raise BackupError(f"{exc} : rien n'est touché") from exc
            (stage / MANIFEST).unlink()
            aside = data / f"{ASIDE}{stamp}"
            # hors du dossier de travail : la copie survit à son nettoyage si un rechargement échoue en route
            kept = data / f"{KEPT}{stamp}"
            if server:
                if occupied:  # les bases en service, copiées avant d'être remplacées
                    try:
                        _copy_live(*_server(), kept)
                    except (backup_server.ServerError, SQLAlchemyError, OSError) as exc:
                        shutil.rmtree(kept, ignore_errors=True)  # les bases en service sont intactes
                        raise BackupError(f"copie des bases en service impossible ({exc}) : rien n'est touché") \
                            from exc
                try:
                    _reload_bases(*_server(), manifest, stage_root)
                except (backup_server.ServerError, SQLAlchemyError, OSError) as exc:
                    raise BackupError(_reload_failed(exc, kept, aside)) from exc
            _swap(data, stage, old, aside, reloaded=server)
            done = True
            if old:
                warnings.append(f"ancien contenu mis de côté : {aside}")
            if kept.exists():
                aside.mkdir(exist_ok=True)
                kept.rename(aside / BASES)
                warnings.append(f"bases en service copiées avant d'être remplacées : {aside / BASES}")
            for sub in ("forge", "ateliers", "partages", "pieces"):
                (data / sub).mkdir(exist_ok=True)
            (data / "partages").chmod(0o700)  # ce qu'elle a envoyé à chacun : à elle seule
            (data / "pieces").chmod(0o700)  # ce qu'on lui a envoyé (ADR 0106) : à elle seule
            for name in ("secret.key", PUSH_KEY_FILE):  # des clés : à leur propriétaire seul
                key = data / name
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


def _ours(name: str) -> bool:
    """Ce qu'une restauration ne remplace ni ne pose : le verrou, ses propres dossiers de travail et de mise de côté,
    et ce que la sauvegarde ne prend pas (``SKIPPED_DIRS``)."""
    return name == datadir.LOCK_NAME or name in SKIPPED_DIRS or name.startswith((STAGING, ASIDE, KEPT))


def _replaced(data: Path) -> list[Path]:
    """Ce que le dossier tient et qu'une restauration remplace."""
    return sorted(p for p in data.iterdir() if not _ours(p.name))


def _swap(data: Path, stage: Path, old: list[Path], aside: Path, *, reloaded: bool) -> None:
    """Met l'ancien contenu de côté (``aside``), puis pose ce que l'archive rend, entrée par entrée, sans jamais
    écrire dans le dossier parent. Un ancien contenu qui ne se déplace pas est remis à sa place."""
    bases = " ; les bases du serveur, elles, sont déjà rechargées depuis l'archive" if reloaded else ""
    if old:
        moved: list[Path] = []
        try:
            aside.mkdir()
            for path in old:
                path.rename(aside / path.name)
                moved.append(path)
        except OSError as exc:
            for path in reversed(moved):
                with contextlib.suppress(OSError):
                    (aside / path.name).rename(path)
            with contextlib.suppress(OSError):
                aside.rmdir()
            raise BackupError(f"mise de côté de l'ancien contenu impossible ({exc}) : le dossier est laissé tel "
                              f"quel{bases}") from exc
    try:
        for path in sorted(stage.iterdir()):
            if not _ours(path.name):
                path.rename(data / path.name)
    except OSError as exc:
        where = f" ; l'ancien contenu est dans {aside}" if old else ""
        raise BackupError(f"pose de l'archive interrompue ({exc}) : le dossier est incomplet{where}{bases} — "
                          f"relance la restauration") from exc


def _server_occupied(url: str, prefix: str) -> bool:
    return any(backup_server.tables(t) for t in _server_bases(url, prefix).values())


def _copy_live(url: str, prefix: str, into: Path) -> None:
    """Une copie SQL de chaque base en service (``views`` exceptée : elle se reconstruit)."""
    for key, target in _server_bases(url, prefix).items():
        if backup_server.exists(target):
            backup_server.dump(target, into / f"{key}.sql")


def _reload_failed(exc: BaseException, kept: Path, aside: Path) -> str:
    """Ce que dit un rechargement interrompu en route ; la copie des bases d'avant passe dans le dossier mis de côté
    (``aside/bases``), ou reste où elle a été écrite si ce déplacement échoue."""
    said = f"rechargement des bases interrompu ({exc}) : les bases du serveur sont dans un état mêlé, le dossier " \
           f"de données n'est pas touché"
    if not kept.exists():
        return f"{said} ; aucune base n'était en service avant"
    with contextlib.suppress(OSError):
        aside.mkdir(exist_ok=True)
        kept.rename(aside / BASES)
        kept = aside / BASES
    return f"{said} ; les bases d'avant la restauration sont copiées dans {kept}"


def _reload_bases(url: str, prefix: str, manifest: dict[str, Any], root: Path) -> None:
    """Chaque copie rechargée à la place de sa base ; une app forgée absente de l'archive perd sa base et son
    utilisateur ; ``views`` est vidée (ses projections se reconstruisent au démarrage)."""
    live = _server_bases(url, prefix)
    for key, entry in sorted(manifest["bases"].items()):
        target = _live(url, prefix, key)
        target.drop()
        backup_server.load(root / entry["file"], target)
    for key, target in live.items():
        if key.startswith("forge/") and key not in manifest["bases"]:
            backup_server.drop_app(target)
    Target(url=url, name=f"{prefix}views").drop()
