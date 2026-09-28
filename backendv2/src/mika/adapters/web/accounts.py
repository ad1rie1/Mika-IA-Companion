"""Comptes et sessions, rangés dans ``mind.db`` (sauvegardés avec sa vie).

Mots de passe : ``scrypt`` (sel aléatoire, paramètres dans l'empreinte).
Sessions : jeton aléatoire opaque, durée bornée. Le premier compte ne se crée
que tant qu'il n'en existe aucun ; il est opérateur.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

SESSION_TTL_S = 14 * 24 * 3600
_N, _R, _P = 2**14, 8, 1
_COMMON = frozenset({"password", "motdepasse", "azertyuiop", "qwertyuiop", "12345678", "123456789", "iloveyou",
                     "password1", "baseball", "football", "sunshine", "princess", "letmein1", "trustno1"})


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(digest) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


def password_problems(password: str, username: str = "") -> list[str]:
    out = []
    if len(password) < 8:
        out.append("Le mot de passe doit contenir au moins 8 caractères.")
    if password.isdigit():
        out.append("Le mot de passe ne peut pas être entièrement numérique.")
    if password.lower() in _COMMON:
        out.append("Ce mot de passe est trop courant.")
    if username and len(username) >= 3 and username.lower() in password.lower():
        out.append("Le mot de passe ressemble trop au nom d'utilisateur.")
    return out


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    username: str
    full_name: str
    operator: bool
    active: bool

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    @property
    def handle(self) -> str:
        return f"user_{self.id}"


class Accounts:
    """Sur le port de magasin : écritures par ``run_mind``, lectures par ``query_mind``."""

    def __init__(self, store: Any) -> None:
        self.store = store

    async def open(self) -> None:
        def create(sql: Any) -> None:
            sql.execute("CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                        "full_name TEXT NOT NULL DEFAULT '', password TEXT NOT NULL, operator INTEGER NOT NULL, "
                        "active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)")
            sql.execute("CREATE TABLE IF NOT EXISTS sessions(key TEXT PRIMARY KEY, account INTEGER NOT NULL, "
                        "created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")

        await self.store.run_mind(create)

    def count(self) -> int:
        return int(self.store.query_mind("SELECT COUNT(*) FROM accounts")[0][0])

    def _account(self, row: tuple[Any, ...] | None) -> Account | None:
        if row is None:
            return None
        return Account(int(row[0]), row[1], row[2], bool(row[3]), bool(row[4]))

    def by_name(self, username: str) -> tuple[Account, str] | None:
        rows = self.store.query_mind("SELECT id, username, full_name, operator, active, password FROM accounts "
                                     "WHERE username=?", (username,))
        if not rows:
            return None
        acc = self._account(rows[0][:5])
        assert acc is not None
        return acc, rows[0][5]

    async def create(self, username: str, password: str, *, operator: bool, full_name: str = "") -> Account:
        hashed = hash_password(password)
        now = int(time.time())

        def insert(sql: Any) -> None:
            sql.execute("INSERT INTO accounts(username, full_name, password, operator, active, created_at) "
                        "VALUES(?,?,?,?,1,?)", (username, full_name, hashed, int(operator), now))

        await self.store.run_mind(insert)
        found = self.by_name(username)
        assert found is not None
        return found[0]

    async def bootstrap(self, username: str, password: str) -> Account | None:
        """Le premier compte, opérateur — ``None`` s'il en existe déjà un."""
        hashed = hash_password(password)
        now = int(time.time())
        created: list[bool] = []

        def insert(sql: Any) -> None:
            if sql.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
                return
            sql.execute("INSERT INTO accounts(username, full_name, password, operator, active, created_at) "
                        "VALUES(?,?,?,1,1,?)", (username, "", hashed, now))
            created.append(True)

        await self.store.run_mind(insert)
        if not created:
            return None
        found = self.by_name(username)
        return found[0] if found else None

    def authenticate(self, username: str, password: str) -> Account | None:
        found = self.by_name(username)
        if found is None:
            check_password(password, hash_password("leurre"))  # même coût qu'un vrai essai
            return None
        acc, stored = found
        return acc if acc.active and check_password(password, stored) else None

    async def open_session(self, account: Account) -> str:
        key = secrets.token_urlsafe(32)
        now = int(time.time())

        def insert(sql: Any) -> None:
            sql.execute("INSERT INTO sessions(key, account, created_at, expires_at) VALUES(?,?,?,?)",
                        (key, account.id, now, now + SESSION_TTL_S))
            sql.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))

        await self.store.run_mind(insert)
        return key

    async def close_session(self, key: str) -> None:
        await self.store.run_mind(lambda sql: sql.execute("DELETE FROM sessions WHERE key=?", (key,)))

    def session(self, key: str | None) -> Account | None:
        if not key:
            return None
        rows = self.store.query_mind(
            "SELECT a.id, a.username, a.full_name, a.operator, a.active FROM sessions s JOIN accounts a "
            "ON a.id = s.account WHERE s.key=? AND s.expires_at >= ?", (key, int(time.time())))
        acc = self._account(rows[0]) if rows else None
        return acc if acc is not None and acc.active else None
