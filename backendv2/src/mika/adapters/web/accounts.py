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

Un jeton ``mobile`` porte aussi, s'il en a donné un, **où le notifier** (ADR 0077) : le
jeton Firebase du téléphone et la clé avec laquelle sceller ce qui lui part
(``POST /auth/push``). Révoqué, il les perd ; un même jeton Firebase ne sert qu'un jeton
de l'application à la fois (une application réinstallée sans déconnexion ne reçoit pas
deux fois).
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

from sqlalchemy import Index, delete, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from mika.ports.sql import Id, Key, LongText, MindBase, table_args

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
#: une connexion ouverte (``/ws``, ``/ws/world``) revérifie son identifiant au moins aussi souvent (secondes) : ce
#: qu'aucun écouteur n'a pu dire — un jeton révoqué par la ligne de commande, une session expirée
CREDENTIAL_CHECK_S = 10.0
#: la longueur d'un identifiant de compte, et d'un nom affiché (le reste est coupé)
USERNAME_MAX = 150
FULL_NAME_MAX = 120
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
    """Ce qui empêche de créer ce compte (ou de changer ce mot de passe), en français ; l'identifiant compris : chaque
    création passe par ici."""
    out = []
    if len(username) > USERNAME_MAX:
        out.append(f"L'identifiant est trop long ({USERNAME_MAX} caractères au plus).")
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
    #: un téléphone qui a dit où le notifier (ADR 0077)
    push: bool = False

    @property
    def key(self) -> str:
        """La clé de ses connexions (``token:<id>``)."""
        return f"{TOKEN_KEY}{self.id}"


@dataclass(frozen=True, slots=True)
class PushRegistration:
    """Où notifier un téléphone (ADR 0077) : son jeton Firebase et la clé (base64) qui scelle ce qui lui part."""

    token_id: int
    device_token: str
    key: str

    @property
    def session(self) -> str:
        """La clé des connexions de ce téléphone (``token:<id>``) : ouvert, il reçoit par sa connexion."""
        return f"{TOKEN_KEY}{self.token_id}"


class AccountRow(MindBase):
    """Un compte : son identifiant, l'empreinte de son mot de passe, ses droits."""

    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Id, primary_key=True)
    username: Mapped[str] = mapped_column(Key(USERNAME_MAX), unique=True)
    full_name: Mapped[str] = mapped_column(Key(FULL_NAME_MAX), default="")
    password: Mapped[str] = mapped_column(Key(255))
    operator: Mapped[bool]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[int]


class SessionRow(MindBase):
    """Une session web : son jeton opaque, son compte, son échéance."""

    __tablename__ = "sessions"
    __table_args__ = table_args(Index("sessions_account", "account"), Index("sessions_expires", "expires_at"))
    key: Mapped[str] = mapped_column(Key(64), primary_key=True)
    account: Mapped[int]
    created_at: Mapped[int]
    expires_at: Mapped[int]


class ClientTokenRow(MindBase):
    """Un jeton de client natif : son empreinte (jamais le secret), ce qu'il ouvre, d'où il vient, et où notifier son
    téléphone (un jeton Firebase va jusqu'à 4 096 caractères : un texte, sans index — les jetons sont peu nombreux)."""

    __tablename__ = "client_tokens"
    __table_args__ = table_args(Index("client_tokens_account", "account"))
    id: Mapped[int] = mapped_column(Id, primary_key=True)
    account: Mapped[int]
    label: Mapped[str] = mapped_column(Key(60), default="")
    digest: Mapped[str] = mapped_column(Key(64), unique=True)
    created_at: Mapped[int]
    last_used: Mapped[int | None]
    revoked_at: Mapped[int | None]
    client: Mapped[str] = mapped_column(Key(16), default=CLIENT_SCREEN)
    source: Mapped[str] = mapped_column(Key(16), default=SOURCE_CLI)
    push_token: Mapped[str | None] = mapped_column(LongText)
    push_key: Mapped[str | None] = mapped_column(Key(128))
    push_at: Mapped[int | None]


ENTITIES = (AccountRow, SessionRow, ClientTokenRow)


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def account_of_handle(handle: str | None) -> int | None:
    """Le compte d'une adresse ``user_<pk>`` ; ``None`` pour toute autre adresse."""
    if not handle or not handle.startswith("user_"):
        return None
    tail = handle[len("user_"):]
    return int(tail) if tail.isdigit() else None


class Accounts:
    """Sur le port de magasin : écritures par ``run_mind``, lectures par ``read_mind`` / ``query_mind``."""

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
        await self.store.run_mind(lambda sql: sql.create(*ENTITIES))

    def _read(self, fn: Callable[[Any], Any]) -> Any:
        """``fn(session)`` sur la connexion de lecture."""
        return self.store.read_mind(lambda sql: fn(sql.session))

    def count(self) -> int:
        return int(self.store.query_mind(select(func.count()).select_from(AccountRow))[0][0])

    @staticmethod
    def _account(row: AccountRow | None) -> Account | None:
        if row is None:
            return None
        return Account(int(row.id), row.username, row.full_name, bool(row.operator), bool(row.active))

    def by_name(self, username: str) -> tuple[Account, str] | None:
        row = self._read(lambda s: s.scalar(select(AccountRow).where(AccountRow.username == username)))
        if row is None:
            return None
        acc = self._account(row)
        assert acc is not None
        return acc, row.password

    async def create(self, username: str, password: str, *, operator: bool, full_name: str = "") -> Account:
        hashed = hash_password(password)
        now = int(time.time())
        name = " ".join(full_name.split())[:FULL_NAME_MAX]

        def insert(sql: Any) -> None:
            sql.session.add(AccountRow(username=username, full_name=name, password=hashed, operator=operator,
                                       active=True, created_at=now))

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
            if sql.session.scalar(select(func.count()).select_from(AccountRow)):
                return
            sql.session.add(AccountRow(username=username, full_name="", password=hashed, operator=True, active=True,
                                       created_at=now))
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
            sql.session.add(SessionRow(key=key, account=account.id, created_at=now, expires_at=now + SESSION_TTL_S))
            sql.execute(delete(SessionRow).where(SessionRow.expires_at < now))

        await self.store.run_mind(insert)
        return key

    async def close_session(self, key: str) -> None:
        await self.store.run_mind(lambda sql: sql.execute(delete(SessionRow).where(SessionRow.key == key)))

    # ── administration (l'inspecteur) ──
    def all(self) -> list[Account]:
        rows = self._read(lambda s: list(s.scalars(select(AccountRow).order_by(AccountRow.id))))
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
        after_name = target.full_name if full_name is None else " ".join(full_name.split())[:FULL_NAME_MAX]
        now = int(time.time())
        dropped: list[int] = []

        def write(sql: Any) -> None:
            sql.execute(update(AccountRow).where(AccountRow.id == account_id)
                        .values(operator=after_operator, active=after_active, full_name=after_name))
            if hashed is not None:
                sql.execute(update(AccountRow).where(AccountRow.id == account_id).values(password=hashed))
            if not after_active or hashed is not None:
                sql.execute(delete(SessionRow).where(SessionRow.account == account_id))
                # un jeton obtenu par ce mot de passe tombe avec lui ; ceux d'un opérateur restent
                by_login = (ClientTokenRow.account == account_id) & (ClientTokenRow.source == SOURCE_LOGIN) \
                    & ClientTokenRow.revoked_at.is_(None)
                dropped.extend(int(r[0]) for r in sql.query(select(ClientTokenRow.id).where(by_login)))
                sql.execute(update(ClientTokenRow).where(by_login)
                            .values(revoked_at=now, push_token=None, push_key=None))

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
        now = int(time.time())
        row = self._read(lambda s: s.scalar(
            select(AccountRow).join(SessionRow, SessionRow.account == AccountRow.id)
            .where(SessionRow.key == key, SessionRow.expires_at >= now)))
        acc = self._account(row)
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
        made: list[int] = []

        def insert(sql: Any) -> None:
            row = ClientTokenRow(account=account_id, label=clean, digest=token_digest(raw), created_at=now,
                                 client=client, source=source)
            sql.session.add(row)
            sql.session.flush()
            made.append(int(row.id))

        await self.store.run_mind(insert)
        info = ClientToken(made[0], account_id, account.username, clean, now, None, False, client, source)
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
        query = (select(ClientTokenRow, AccountRow.username)
                 .outerjoin(AccountRow, AccountRow.id == ClientTokenRow.account).order_by(ClientTokenRow.id))
        if account_id is not None:
            query = query.where(ClientTokenRow.account == account_id)
        rows = self._read(lambda s: s.execute(query).all())
        return [ClientToken(int(t.id), int(t.account), name or "?", t.label, int(t.created_at), t.last_used,
                            t.revoked_at is not None, t.client or CLIENT_SCREEN, t.source or SOURCE_CLI,
                            t.push_token is not None) for t, name in rows]

    def token_client(self, token_id: int) -> str:
        """Ce qu'ouvre ce jeton (``screen`` pour un jeton inconnu : dans le doute, un écran)."""
        rows = self.store.query_mind(select(ClientTokenRow.client).where(ClientTokenRow.id == token_id))
        client = rows[0][0] if rows else None
        return client if client in TOKEN_CLIENTS else CLIENT_SCREEN

    def has_mobile(self, account_id: int) -> bool:
        """Ce compte a-t-il une application de téléphone vivante (un jeton ``mobile`` non révoqué) ?"""
        rows = self.store.query_mind(select(ClientTokenRow.id).where(
            ClientTokenRow.account == account_id, ClientTokenRow.client == CLIENT_MOBILE,
            ClientTokenRow.revoked_at.is_(None)).limit(1))
        return bool(rows)

    def token(self, raw: str | None) -> tuple[Account, int] | None:
        """Le compte (actif) d'un jeton valide, et l'identifiant du jeton ; ``None`` sinon."""
        if not raw or not raw.startswith(TOKEN_PREFIX) or len(raw) > 200:
            return None
        digest = token_digest(raw)
        found = self._read(lambda s: s.execute(
            select(AccountRow, ClientTokenRow.id).join(ClientTokenRow, ClientTokenRow.account == AccountRow.id)
            .where(ClientTokenRow.digest == digest, ClientTokenRow.revoked_at.is_(None))).first())
        if found is None:
            return None
        acc = self._account(found[0])
        return (acc, int(found[1])) if acc is not None and acc.active else None

    async def use_token(self, raw: str | None) -> tuple[Account, int] | None:
        """Comme ``token``, et la date de dernier usage notée (ce que la liste des jetons montre)."""
        found = self.token(raw)
        if found is not None:
            now, token_id = int(time.time()), found[1]
            await self.store.run_mind(lambda sql: sql.execute(
                update(ClientTokenRow).where(ClientTokenRow.id == token_id).values(last_used=now)))
        return found

    async def revoke_token(self, token_id: int) -> bool:
        """Révoque un jeton (il ne vaut plus rien, ses connexions se ferment) ; ``False`` s'il n'existe pas ou
        l'était déjà."""
        now = int(time.time())
        done: list[bool] = []

        def write(sql: Any) -> None:
            cur = sql.execute(update(ClientTokenRow)
                              .where(ClientTokenRow.id == token_id, ClientTokenRow.revoked_at.is_(None))
                              .values(revoked_at=now, push_token=None, push_key=None))
            done.append(bool(getattr(cur, "rowcount", 0)))

        await self.store.run_mind(write)
        if not (done and done[0]):
            return False
        for listener in list(self.on_token_revoke):
            await listener(token_id)
        if self.token_client(token_id) == CLIENT_MOBILE:
            await self._changed()  # plus d'application qui reçoit hors ligne, peut-être : la joignabilité suit
        return True

    # ── notifications du téléphone (ADR 0077) ──
    async def set_push(self, token_id: int, device_token: str, key: str) -> None:
        """Où notifier ce téléphone. Le même jeton Firebase quitte tout autre jeton de l'application : une
        application réinstallée sans déconnexion laisse l'ancien jeton vivant, il ne recevrait pas en double."""
        now = int(time.time())

        def write(sql: Any) -> None:
            sql.execute(update(ClientTokenRow)
                        .where(ClientTokenRow.push_token == device_token, ClientTokenRow.id != token_id)
                        .values(push_token=None, push_key=None))
            sql.execute(update(ClientTokenRow)
                        .where(ClientTokenRow.id == token_id, ClientTokenRow.revoked_at.is_(None))
                        .values(push_token=device_token, push_key=key, push_at=now))

        await self.store.run_mind(write)

    async def clear_push(self, token_id: int, device_token: str | None = None) -> None:
        """Ce téléphone ne veut plus de notifications, ou ``device_token`` (son jeton Firebase) ne vaut plus — et
        seulement s'il est toujours celui-là : un jeton neuf donné entre-temps reste."""
        where = [ClientTokenRow.id == token_id]
        if device_token is not None:
            where.append(ClientTokenRow.push_token == device_token)
        await self.store.run_mind(lambda sql: sql.execute(
            update(ClientTokenRow).where(*where).values(push_token=None, push_key=None)))

    def push_registrations(self, account_id: int) -> list[PushRegistration]:
        """Les téléphones vivants de ce compte qui ont dit où les notifier."""
        rows = self.store.query_mind(
            select(ClientTokenRow.id, ClientTokenRow.push_token, ClientTokenRow.push_key)
            .join(AccountRow, AccountRow.id == ClientTokenRow.account)
            .where(ClientTokenRow.account == account_id, ClientTokenRow.client == CLIENT_MOBILE,
                   ClientTokenRow.revoked_at.is_(None), AccountRow.active.is_(True),
                   ClientTokenRow.push_token.is_not(None), ClientTokenRow.push_key.is_not(None))
            .order_by(ClientTokenRow.id))
        return [PushRegistration(int(r[0]), str(r[1]), str(r[2])) for r in rows]

    def push_count(self) -> int:
        """Combien de téléphones vivants ont dit où les notifier (ce que la console montre)."""
        rows = self.store.query_mind(select(func.count()).select_from(ClientTokenRow).where(
            ClientTokenRow.client == CLIENT_MOBILE, ClientTokenRow.revoked_at.is_(None),
            ClientTokenRow.push_token.is_not(None)))
        return int(rows[0][0]) if rows else 0

    def credential(self, key: str | None) -> Account | None:
        """Ce qu'une connexion ouverte revérifie : sa session web, ou son jeton (``token:<id>``)."""
        if key and key.startswith(TOKEN_KEY):
            try:
                token_id = int(key[len(TOKEN_KEY):])
            except ValueError:
                return None
            row = self._read(lambda s: s.scalar(
                select(AccountRow).join(ClientTokenRow, ClientTokenRow.account == AccountRow.id)
                .where(ClientTokenRow.id == token_id, ClientTokenRow.revoked_at.is_(None))))
            acc = self._account(row)
            return acc if acc is not None and acc.active else None
        return self.session(key)

    def still_valid(self, key: str | None, *, operator: bool) -> bool:
        """La règle des connexions ouvertes, sur ``/ws`` comme sur ``/ws/world`` : leur identifiant vaut encore
        (session ni expirée ni effacée, jeton non révoqué — dans ce processus ou un autre —, compte actif) et leurs
        droits n'ont pas changé. Une lecture impossible lève : l'appelant décide s'il ferme."""
        account = self.credential(key)
        return account is not None and account.operator == operator
