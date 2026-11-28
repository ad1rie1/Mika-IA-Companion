"""Les octets des fichiers qu'elle envoie (port ``shares``, ADR 0062).

``DiskShares`` : un dossier (``partages/`` dans le dossier de données, sauvegardé avec lui), un fichier
``<id>.bin`` par envoi et sa fiche ``<id>.json`` (sujets, taille, SHA-256). Seuls des identifiants de
32 caractères hexadécimaux atteignent le disque ; chaque écriture passe par un fichier temporaire puis
``os.replace`` (jamais un fichier à moitié écrit) ; le dossier est en 0700, les fichiers en 0600 ; tout ce qui
touche le disque sort de la boucle (``asyncio.to_thread``).

``MemoryShares`` : la même chose en mémoire, pour les essais et le simulateur.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from mika.ports.shares import MAX_SHARE_BYTES, valid_id

DIR_MODE = 0o700
FILE_MODE = 0o600


def _subjects(subjects: Iterable[str]) -> list[str]:
    return sorted({str(s) for s in subjects if s})


class DiskShares:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ── chemins ──
    def _paths(self, file: str) -> tuple[Path, Path]:
        if not valid_id(file):
            raise ValueError(f"identifiant de fichier invalide : {file!r}")
        return self.root / f"{file}.bin", self.root / f"{file}.json"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, DIR_MODE)

    def _write_atomic(self, path: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".partage-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, FILE_MODE)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ── le port ──
    def _put(self, file: str, data: bytes, subjects: list[str]) -> None:
        blob, sidecar = self._paths(file)
        if len(data) > MAX_SHARE_BYTES:
            raise ValueError(f"fichier trop gros : {len(data)} octets (au plus {MAX_SHARE_BYTES})")
        self._ensure_root()
        sha = hashlib.sha256(data).hexdigest()
        meta = {"subjects": subjects, "size": len(data), "sha256": sha}
        if blob.is_file() and sidecar.is_file():
            try:
                known = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                known = {}
            if known.get("sha256") == sha and blob.stat().st_size == len(data):
                if sorted(known.get("subjects") or []) != subjects:  # de nouveaux sujets : la fiche suit
                    merged = _subjects([*known.get("subjects", []), *subjects])
                    self._write_atomic(sidecar, json.dumps({**meta, "subjects": merged}).encode())
                return  # déjà là, à l'identique : rien à réécrire
        self._write_atomic(blob, bytes(data))
        self._write_atomic(sidecar, json.dumps(meta).encode())

    async def put(self, file: str, data: bytes, *, subjects: Iterable[str]) -> None:
        await asyncio.to_thread(self._put, file, bytes(data), _subjects(subjects))

    def _read(self, file: str, limit: int) -> bytes | None:
        if not valid_id(file):
            return None
        blob, _ = self._paths(file)
        try:
            with blob.open("rb") as f:
                return f.read(max(0, limit))
        except OSError:
            return None

    async def read(self, file: str, limit: int = MAX_SHARE_BYTES) -> bytes | None:
        return await asyncio.to_thread(self._read, file, limit)

    def _delete(self, files: Sequence[str]) -> int:
        n = 0
        for file in files:
            if not valid_id(file):
                continue
            blob, sidecar = self._paths(file)
            existed = blob.exists()
            for p in (blob, sidecar):
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()
            n += int(existed)
        return n

    async def delete(self, files: Sequence[str]) -> int:
        return await asyncio.to_thread(self._delete, list(files))

    def _forget(self, subject: str) -> int:
        if not subject or not self.root.is_dir():
            return 0
        doomed = []
        for sidecar in sorted(self.root.glob("*.json")):
            file = sidecar.stem
            if not valid_id(file):
                continue
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if subject in (meta.get("subjects") or ()):
                doomed.append(file)
        return self._delete(doomed)

    async def forget(self, subject: str) -> int:
        return await asyncio.to_thread(self._forget, str(subject))

    def files(self) -> list[str]:
        """Les identifiants présents (la console, les essais)."""
        if not self.root.is_dir():
            return []
        return sorted(p.stem for p in self.root.glob("*.bin") if valid_id(p.stem))


class MemoryShares:
    """Le port en mémoire : mêmes règles (identifiants, taille, sujets), sans disque."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.subjects: dict[str, list[str]] = {}

    async def put(self, file: str, data: bytes, *, subjects: Iterable[str]) -> None:
        if not valid_id(file):
            raise ValueError(f"identifiant de fichier invalide : {file!r}")
        if len(data) > MAX_SHARE_BYTES:
            raise ValueError(f"fichier trop gros : {len(data)} octets (au plus {MAX_SHARE_BYTES})")
        self.blobs[file] = bytes(data)
        self.subjects[file] = _subjects([*self.subjects.get(file, []), *subjects])

    async def read(self, file: str, limit: int = MAX_SHARE_BYTES) -> bytes | None:
        data = self.blobs.get(file)
        return None if data is None else data[:max(0, limit)]

    async def delete(self, files: Sequence[str]) -> int:
        n = 0
        for file in files:
            n += int(self.blobs.pop(file, None) is not None)
            self.subjects.pop(file, None)
        return n

    async def forget(self, subject: str) -> int:
        return await self.delete([f for f, s in sorted(self.subjects.items()) if subject in s])

    def files(self) -> list[str]:
        return sorted(self.blobs)
