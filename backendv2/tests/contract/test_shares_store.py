"""Le port des fichiers qu'elle envoie (ADR 0062), contre le vrai disque et sa doublure en mémoire.

- un identifiant qui n'est pas 32 caractères hexadécimaux n'atteint jamais le disque (``../``, un nom, une
  majuscule) ;
- une écriture est atomique (un fichier temporaire puis un renommage : jamais un fichier à moitié écrit, rien
  de temporaire qui traîne), idempotente, en 0600 dans un dossier en 0700 ;
- oublier un sujet efface ses fichiers et seulement eux ; effacer rend ce qui a été effacé.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest

from mika.adapters.shares import DiskShares, MemoryShares
from mika.ports.shares import MAX_SHARE_BYTES, valid_id

A = "a" * 32
B = "0123456789abcdef" * 2
C = "f" * 32


def run(coro):
    return asyncio.run(coro)


def test_only_hex_ids_reach_the_disk(tmp_path):
    store = DiskShares(tmp_path / "partages")
    for bad in ("../" + "a" * 29, "A" * 32, "a" * 31, "a" * 33, "notes.md", "", "a" * 31 + "/"):
        assert not valid_id(bad)
        with pytest.raises(ValueError):
            run(store.put(bad, b"x", subjects=("user_1",)))
        assert run(store.read(bad)) is None
    assert run(store.delete(["../../etc/passwd"])) == 0
    assert not (tmp_path / "partages").exists() or list((tmp_path / "partages").iterdir()) == []


def test_a_write_is_atomic_private_and_idempotent(tmp_path):
    root = tmp_path / "partages"
    store = DiskShares(root)
    run(store.put(A, b"bonjour", subjects=("user_1", "name:alice")))
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o700
    for p in root.iterdir():
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p
        assert not p.name.startswith("."), "un fichier temporaire est resté"
    meta = json.loads((root / f"{A}.json").read_text(encoding="utf-8"))
    assert meta["subjects"] == ["name:alice", "user_1"] and meta["size"] == 7 and len(meta["sha256"]) == 64
    before = os.stat(root / f"{A}.bin").st_mtime_ns
    run(store.put(A, b"bonjour", subjects=("user_1",)))  # le même appel rejoué : rien ne se réécrit
    assert os.stat(root / f"{A}.bin").st_mtime_ns == before
    assert run(store.read(A)) == b"bonjour" and run(store.read(A, 3)) == b"bon"
    assert store.files() == [A]


def test_too_big_is_refused(tmp_path):
    store = DiskShares(tmp_path / "partages")
    with pytest.raises(ValueError):
        run(store.put(A, b"x" * (MAX_SHARE_BYTES + 1), subjects=()))
    assert run(store.read(A)) is None


def test_forget_takes_only_what_names_the_subject(tmp_path):
    store = DiskShares(tmp_path / "partages")
    run(store.put(A, b"pour alice", subjects=("user_2",)))
    run(store.put(B, b"projet sur alice", subjects=("user_1", "user_2")))
    run(store.put(C, b"pour bob", subjects=("user_3",)))
    assert run(store.forget("user_2")) == 2
    assert store.files() == [C]
    assert run(store.read(A)) is None and run(store.read(B)) is None
    assert sorted(p.name for p in (tmp_path / "partages").iterdir()) == [f"{C}.bin", f"{C}.json"]
    assert run(store.forget("user_2")) == 0
    assert run(store.delete([C, A])) == 1 and store.files() == []


def test_the_memory_double_keeps_the_same_rules():
    store = MemoryShares()
    with pytest.raises(ValueError):
        run(store.put("../x", b"x", subjects=()))
    run(store.put(A, b"un", subjects=("user_1",)))
    run(store.put(B, b"deux", subjects=("user_2",)))
    assert run(store.read(A)) == b"un" and run(store.read(B, 2)) == b"de"
    assert run(store.forget("user_1")) == 1 and store.files() == [B]
    assert run(store.delete([B])) == 1 and run(store.read(B)) is None
