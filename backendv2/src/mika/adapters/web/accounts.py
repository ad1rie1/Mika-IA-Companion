"""Comptes et sessions, rangés dans ``mind.db`` (sauvegardés avec sa vie).

Mots de passe : ``scrypt`` (sel aléatoire, paramètres dans l'empreinte).
Sessions : jeton aléatoire opaque, durée bornée. Le premier compte ne se crée
que tant qu'il n'en existe aucun ; il est opérateur.

Vérifier un mot de passe coûte **un** scrypt, que le compte existe ou non (le
leurre est calculé une fois) : la durée ne dit pas qui a un compte. ``verify``
le fait hors de la boucle (un scrypt la figeait ~20 ms par essai).
Une session révoquée (compte désactivé, mot de passe changé, droits retirés)
prévient ceux qui écoutent (``on_revoke``) : ses WebSockets se ferment.

Jetons de client natif (ADR 0051) : un moteur de jeu n'a ni cookie ni ``Origin``,
il s'authentifie par un jeton porteur de son compte (``mw_…``). Un jeton parle
sous l'adresse du compte (``user_<pk>``) : l'identité reste authentifiée, comme
depuis le navigateur. Il n'est gardé qu'en empreinte (SHA-256 : un jeton tiré au
hasard sur 256 bits n'a pas besoin d'un hachage lent), montré une seule fois, et
révocable un par un — un jeton révoqué prévient ``on_token_revoke`` : ses
connexions se ferment. Un compte désactivé rend tous ses jetons muets.

Un jeton dit aussi **ce qu'il ouvre** (ADR 0062) : ``client`` ``screen`` (un écran, un
moteur : on n'y lit que si on est là) ou ``mobile`` (l'application du téléphone, qui
reçoit hors ligne : une messagerie, par où elle peut écrire à quelqu'un d'absent), et
**d'où il vient** : ``source`` ``cli``, ``console`` ou ``login`` (l'application l'a
obtenu par identifiant et mot de passe, ``POST /auth/token``). Un jeton obtenu par
mot de passe suit ce mot de passe : le changer, ou désactiver le compte, le révoque ;
un jeton donné par un opérateur (ligne de commande, console) reste.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

SESSION_TTL_S = 14 * 24 * 3600
#: le préfixe d'un jeton de client natif (il se reconnaît dans un journal, et ne ressemble à aucune session)
TOKEN_PREFIX = "mw_"
#: la clé de « session » d'une connexion ouverte par un jeton (``token:<id>``) : ce qu'elle revérifie, ce qu'on
#: révoque ; une clé de session web n'a jamais de deux-points (``token_urlsafe``), les deux ne se confondent pas
TOKEN_KEY = "token:"
#: ce qu'ouvre un jeton : un écran (navigateur, moteur de jeu) ou l'application du téléphone (une messagerie)
CLIENT_SCREEN = "screen"
CLIENT_MOBILE = "mobile"
TOKEN_CLIENTS = frozenset({CLIENT_SCREEN, CLIENT_MOBILE})
#: d'où vient un jeton : la ligne de commande, la console, ou une connexion par mot de passe (l'application)
SOURCE_CLI = "cli"
SOURCE_CONSOLE = "console"
SOURCE_LOGIN = "login"
TOKEN_SOURCES = frozenset({SOURCE_CLI, SOURCE_CONSOLE, SOURCE_LOGIN})
#: jetons vivants obtenus par mot de passe gardés par compte : au-delà, les moins récemment utilisés partent
#: (une application réinstallée dix fois ne laisse pas dix portes ouvertes)
LOGIN_TOKENS_KEPT = 10
_N, _R, _P = 2**14, 8, 1
_COMMON = frozenset({"password", "motdepasse", "azertyuiop", "qwertyuiop", "12345678", "123456789", "iloveyou",
                     "password1", "baseball", "football", "sunshine", "princess", "letmein1", "trustno1"})
_DECOY: list[str] = []


def decoy_hash() -> str:
    """Une empreinte de leurre, calculée une seule fois : vérifier un mot de passe contre
    elle coûte exactement un scrypt, comme contre un vrai compte."""
    if not _DECOY:
        _DECOY.append(hash_password(secrets.token_urlsafe(16)))
    return _DECOY[0]


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


@dataclass(frozen=True, slots=True)
class ClientToken:
    """Un jeton de client natif, tel qu'on le montre : jamais le secret, seulement de quoi le reconnaître."""

    id: int
    account: int
    username: str
    label: str
    created_at: int
    last_used: int | None
    revoked: bool
    client: str = CLIENT_SCREEN
    source: str = SOURCE_CLI

    @property
    def key(self) -> str:
        """La clé de ses connexions (``token:<id>``)."""
        return f"{TOKEN_KEY}{self.id}"


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Accounts:
    """Sur le port de magasin : écritures par ``run_mind``, lectures par ``query_mind``."""

    def __init__(self, store: Any) -> None:
        self.store = store
        #: prévenu après chaque création ou modification (l'application en fait une personne)
        self.on_change: Callable[[], Awaitable[Any]] | None = None
        #: prévenus quand les sessions d'un compte cessent de valoir (identifiant du compte)
        self.on_revoke: list[Callable[[int], Awaitable[Any]]] = []
        #: prévenus quand un jeton de client natif est révoqué (identifiant du jeton)
        self.on_token_revoke: list[Callable[[int], Awaitable[Any]]] = []

    async def _changed(self) -> None:
        if self.on_change is not None:
            await self.on_change()

    async def _revoked(self, account_id: int) -> None:
        for listener in list(self.on_revoke):
            await listener(account_id)

    async def open(self) -> None:
        def create(sql: Any) -> None:
            sql.execute("CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                        "full_name TEXT NOT NULL DEFAULT '', password TEXT NOT NULL, operator INTEGER NOT NULL, "
                        "active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)")
            sql.execute("CREATE TABLE IF NOT EXISTS sessions(key TEXT PRIMARY KEY, account INTEGER NOT NULL, "
                        "created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
            sql.execute("CREATE TABLE IF NOT EXISTS client_tokens(id INTEGER PRIMARY KEY, account INTEGER NOT NULL, "
                        "label TEXT NOT NULL DEFAULT '', digest TEXT UNIQUE NOT NULL, created_at INTEGER NOT NULL, "
                        "last_used INTEGER, revoked_at INTEGER)")
            # ADR 0062 : ce qu'ouvre le jeton et d'où il vient (une table d'avant n'a ni l'un ni l'autre)
            cols = {r[1] for r in sql.execute("PRAGMA table_info(client_tokens)").fetchall()}
            if "client" not in cols:
                sql.execute(f"ALTER TABLE client_tokens ADD COLUMN client TEXT NOT NULL DEFAULT '{CLIENT_SCREEN}'")
            if "source" not in cols:
                sql.execute(f"ALTER TABLE client_tokens ADD COLUMN source TEXT NOT NULL DEFAULT '{SOURCE_CLI}'")

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
        await self._changed()
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
        await self._changed()
        return found[0] if found else None

    def authenticate(self, username: str, password: str) -> Account | None:
        found = self.by_name(username)
        if found is None:
            check_password(password, decoy_hash())  # un scrypt, comme un vrai essai
            return None
        acc, stored = found
        return acc if acc.active and check_password(password, stored) else None

    async def verify(self, username: str, password: str) -> Account | None:
        """Comme ``authenticate``, le scrypt hors de la boucle (la lecture du compte, elle, y reste)."""
        found = self.by_name(username)
        stored = found[1] if found is not None else decoy_hash()
        ok = await asyncio.to_thread(check_password, password, stored)
        if found is None or not ok:
            return None
        return found[0] if found[0].active else None

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

    # ── administration (l'inspecteur) ──
    def all(self) -> list[Account]:
        rows = self.store.query_mind("SELECT id, username, full_name, operator, active FROM accounts ORDER BY id")
        return [a for a in (self._account(r) for r in rows) if a is not None]

    async def update(self, account_id: int, *, operator: bool | None = None, active: bool | None = None,
                     password: str | None = None, full_name: str | None = None) -> str | None:
        """Modifie un compte ; rend un refus en français, ou ``None``. Jamais de
        verrouillage : on ne retire pas le dernier opérateur actif."""
        target = next((a for a in self.all() if a.id == account_id), None)
        if target is None:
            return "Compte inconnu."
        after_operator = target.operator if operator is None else operator
        after_active = target.active if active is None else active
        if target.operator and target.active and not (after_operator and after_active):
            others = [a for a in self.all() if a.operator and a.active and a.id != account_id]
            if not others:
                return "C'est le dernier opérateur actif : on ne peut pas le retirer."
        if password is not None:
            problems = password_problems(password, target.username)
            if problems:
                return " ".join(problems)
        hashed = hash_password(password) if password is not None else None
        after_name = target.full_name if full_name is None else " ".join(full_name.split())[:120]
        now = int(time.time())
        dropped: list[int] = []

        def write(sql: Any) -> None:
            sql.execute("UPDATE accounts SET operator=?, active=?, full_name=? WHERE id=?",
                        (int(after_operator), int(after_active), after_name, account_id))
            if hashed is not None:
                sql.execute("UPDATE accounts SET password=? WHERE id=?", (hashed, account_id))
            if not after_active or hashed is not None:
                sql.execute("DELETE FROM sessions WHERE account=?", (account_id,))
                # un jeton obtenu par ce mot de passe tombe avec lui ; ceux d'un opérateur restent
                dropped.extend(int(r[0]) for r in sql.execute(
                    "SELECT id FROM client_tokens WHERE account=? AND source=? AND revoked_at IS NULL",
                    (account_id, SOURCE_LOGIN)).fetchall())
                sql.execute("UPDATE client_tokens SET revoked_at=? WHERE account=? AND source=? AND revoked_at IS NULL",
                            (now, account_id, SOURCE_LOGIN))

        await self.store.run_mind(write)
        for token_id in dropped:
            for listener in list(self.on_token_revoke):
                await listener(token_id)
        await self._changed()
        if not after_active or hashed is not None or (target.operator and not after_operator):
            # sessions effacées, ou droits retirés : ses WebSockets ouvertes ne valent plus
            await self._revoked(account_id)
        return None

    def session(self, key: str | None) -> Account | None:
        if not key:
            return None
        rows = self.store.query_mind(
            "SELECT a.id, a.username, a.full_name, a.operator, a.active FROM sessions s JOIN accounts a "
            "ON a.id = s.account WHERE s.key=? AND s.expires_at >= ?", (key, int(time.time())))
        acc = self._account(rows[0]) if rows else None
        return acc if acc is not None and acc.active else None

    # ── jetons de client natif ──
    async def create_token(self, account_id: int, label: str = "", *, client: str = CLIENT_SCREEN,
                           source: str = SOURCE_CLI) -> tuple[ClientToken, str]:
        """Un jeton neuf pour ce compte (actif) : rend sa fiche et le secret, qu'on ne reverra jamais.
        ``ValueError`` (en français) pour un compte inconnu ou désactivé, ou une sorte de client inconnue."""
        if client not in TOKEN_CLIENTS:
            raise ValueError(f"Sorte de client inconnue : {client!r} (screen ou mobile).")
        if source not in TOKEN_SOURCES:
            raise ValueError(f"Origine de jeton inconnue : {source!r}.")
        account = next((a for a in self.all() if a.id == account_id), None)
        if account is None or not account.active:
            raise ValueError("Compte inconnu ou désactivé : pas de jeton.")
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        clean = " ".join(label.split())[:60]
        now = int(time.time())

        def insert(sql: Any) -> None:
            sql.execute("INSERT INTO client_tokens(account, label, digest, created_at, client, source) "
                        "VALUES(?,?,?,?,?,?)", (account_id, clean, token_digest(raw), now, client, source))

        await self.store.run_mind(insert)
        rows = self.store.query_mind("SELECT id FROM client_tokens WHERE digest=?", (token_digest(raw),))
        info = ClientToken(int(rows[0][0]), account_id, account.username, clean, now, None, False, client, source)
        if client == CLIENT_MOBILE:
            await self._changed()  # une application qui reçoit hors ligne : on peut désormais lui écrire
        return info, raw

    async def prune_login_tokens(self, account_id: int, keep: int = LOGIN_TOKENS_KEPT) -> list[int]:
        """Au-delà de ``keep`` jetons vivants obtenus par mot de passe, révoque les moins récemment utilisés ;
        rend leurs identifiants."""
        live = [t for t in self.tokens(account_id) if t.source == SOURCE_LOGIN and not t.revoked]
        live.sort(key=lambda t: (t.last_used or t.created_at, t.id))
        doomed = live[:max(0, len(live) - keep)]
        for t in doomed:
            await self.revoke_token(t.id)
        return [t.id for t in doomed]

    def tokens(self, account_id: int | None = None) -> list[ClientToken]:
        """Les jetons (révoqués compris), du plus ancien au plus récent — jamais leur secret."""
        sql = ("SELECT t.id, t.account, COALESCE(a.username, '?'), t.label, t.created_at, t.last_used, t.revoked_at, "
               "t.client, t.source FROM client_tokens t LEFT JOIN accounts a ON a.id = t.account")
        params: tuple[Any, ...] = ()
        if account_id is not None:
            sql += " WHERE t.account=?"
            params = (account_id,)
        rows = self.store.query_mind(sql + " ORDER BY t.id", params)
        return [ClientToken(int(r[0]), int(r[1]), r[2], r[3], int(r[4]), r[5], r[6] is not None,
                            r[7] or CLIENT_SCREEN, r[8] or SOURCE_CLI) for r in rows]

    def token_client(self, token_id: int) -> str:
        """Ce qu'ouvre ce jeton (``screen`` pour un jeton inconnu : dans le doute, un écran)."""
        rows = self.store.query_mind("SELECT client FROM client_tokens WHERE id=?", (token_id,))
        client = rows[0][0] if rows else None
        return client if client in TOKEN_CLIENTS else CLIENT_SCREEN

    def has_mobile(self, account_id: int) -> bool:
        """Ce compte a-t-il une application de téléphone vivante (un jeton ``mobile`` non révoqué) ?"""
        rows = self.store.query_mind("SELECT 1 FROM client_tokens WHERE account=? AND client=? AND revoked_at IS NULL "
                                     "LIMIT 1", (account_id, CLIENT_MOBILE))
        return bool(rows)

    def token(self, raw: str | None) -> tuple[Account, int] | None:
        """Le compte (actif) d'un jeton valide, et l'identifiant du jeton ; ``None`` sinon."""
        if not raw or not raw.startswith(TOKEN_PREFIX) or len(raw) > 200:
            return None
        rows = self.store.query_mind(
            "SELECT a.id, a.username, a.full_name, a.operator, a.active, t.id FROM client_tokens t JOIN accounts a "
            "ON a.id = t.account WHERE t.digest=? AND t.revoked_at IS NULL", (token_digest(raw),))
        if not rows:
            return None
        acc = self._account(rows[0][:5])
        return (acc, int(rows[0][5])) if acc is not None and acc.active else None

    async def use_token(self, raw: str | None) -> tuple[Account, int] | None:
        """Comme ``token``, et la date de dernier usage notée (ce que la liste des jetons montre)."""
        found = self.token(raw)
        if found is not None:
            now, token_id = int(time.time()), found[1]
            await self.store.run_mind(lambda sql: sql.execute("UPDATE client_tokens SET last_used=? WHERE id=?",
                                                              (now, token_id)))
        return found

    async def revoke_token(self, token_id: int) -> bool:
        """Révoque un jeton (il ne vaut plus rien, ses connexions se ferment) ; ``False`` s'il n'existe pas ou
        l'était déjà."""
        now = int(time.time())
        done: list[bool] = []

        def write(sql: Any) -> None:
            cur = sql.execute("UPDATE client_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                              (now, token_id))
            done.append(bool(getattr(cur, "rowcount", 0)))

        await self.store.run_mind(write)
        if not (done and done[0]):
            return False
        for listener in list(self.on_token_revoke):
            await listener(token_id)
        if self.token_client(token_id) == CLIENT_MOBILE:
            await self._changed()  # plus d'application qui reçoit hors ligne, peut-être : la joignabilité suit
        return True

    def credential(self, key: str | None) -> Account | None:
        """Ce qu'une connexion ouverte revérifie : sa session web, ou son jeton (``token:<id>``)."""
        if key and key.startswith(TOKEN_KEY):
            try:
                token_id = int(key[len(TOKEN_KEY):])
            except ValueError:
                return None
            rows = self.store.query_mind(
                "SELECT a.id, a.username, a.full_name, a.operator, a.active FROM client_tokens t JOIN accounts a "
                "ON a.id = t.account WHERE t.id=? AND t.revoked_at IS NULL", (token_id,))
            acc = self._account(rows[0]) if rows else None
            return acc if acc is not None and acc.active else None
        return self.session(key)
