"""Ses bases sur un serveur MariaDB, pour la sauvegarde et la restauration (ADR 0101, point 10).

- **Copier** une base : ``mariadb-dump --single-transaction`` (un instantané cohérent, sans verrou, le serveur en
  marche) vers un fichier SQL, en UTF-8, les octets en hexadécimal ; ni procédure, ni événement, ni déclencheur (ses
  bases n'en ont pas, celles des apps ne peuvent pas en avoir).
- **Recharger** une copie : ``mariadb`` lit le fichier dans une base (créée au besoin, avec sa collation).

Le compte est celui de ``MIKA_DATABASE_URL`` (le socket, l'utilisateur ; un mot de passe éventuel passe par
l'environnement du programme, jamais par sa ligne de commande). Les outils ``mariadb-dump`` et ``mariadb`` viennent
avec le serveur.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from mika.adapters.database import Target

#: les bases qu'on sauvegarde (``views`` se reconstruit depuis le journal)
KEPT = ("mind", "mail", "feeds", "teams")
#: le temps qu'une copie ou un rechargement peut prendre (secondes)
TIMEOUT_S = 3600


class ServerError(RuntimeError):
    """Un outil du serveur a échoué ; le message dit lequel et pourquoi."""


def _tool(name: str) -> str:
    found = shutil.which(name) or shutil.which({"mariadb-dump": "mysqldump", "mariadb": "mysql"}[name])
    if found is None:
        raise ServerError(f"« {name} » est introuvable : il vient avec le serveur MariaDB (paquet mariadb)")
    return found


def _connection(url: str) -> tuple[list[str], dict[str, str]]:
    """Les options de connexion d'un outil du serveur, et son environnement (le mot de passe, s'il y en a un)."""
    u = make_url(url)
    args: list[str] = []
    if u.username:
        args.append(f"--user={u.username}")
    socket = u.query.get("unix_socket")
    if socket:
        args.append(f"--socket={socket if isinstance(socket, str) else socket[0]}")
    elif u.host:
        args += [f"--host={u.host}", f"--port={u.port or 3306}", "--protocol=TCP"]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME")}
    if u.password:
        env["MYSQL_PWD"] = str(u.password)
    return args, env


def _run(command: list[str], env: dict[str, str], *, stdin: Path | None = None, stdout: Path | None = None) -> None:
    try:
        with (stdin.open("rb") if stdin else open(os.devnull, "rb")) as src, \
                (stdout.open("wb") if stdout else open(os.devnull, "wb")) as dst:
            done = subprocess.run(command, stdin=src, stdout=dst, stderr=subprocess.PIPE, env=env,
                                  timeout=TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ServerError(f"{Path(command[0]).name} : plus de {TIMEOUT_S // 60} minutes") from exc
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ServerError(f"{Path(command[0]).name} a échoué : {said[-1] if said else done.returncode}")


def dump(target: Target, into: Path) -> None:
    """La copie d'une base, cohérente même serveur en marche."""
    assert target.url is not None and target.name is not None
    args, env = _connection(target.url)
    into.parent.mkdir(parents=True, exist_ok=True)
    _run([_tool("mariadb-dump"), *args, "--single-transaction", "--skip-lock-tables", "--hex-blob",
          "--default-character-set=utf8mb4", "--skip-comments", "--skip-triggers", "--skip-routines",
          "--skip-events", "--no-create-db", "--add-drop-table", target.name], env, stdout=into)


def load(source: Path, target: Target) -> None:
    """Recharge une copie dans une base (créée au besoin)."""
    assert target.url is not None and target.name is not None
    target.ensure()
    args, env = _connection(target.url)
    _run([_tool("mariadb"), *args, "--default-character-set=utf8mb4", "--batch", target.name], env, stdin=source)


def _admin(url: str):  # noqa: ANN202 — un moteur sans base, en autocommit
    return create_engine(make_url(url).set(database=None), poolclass=NullPool, isolation_level="AUTOCOMMIT")


def tables(target: Target) -> list[str]:
    assert target.url is not None
    engine = _admin(target.url)
    try:
        with engine.connect() as conn:
            return [r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :n ORDER BY table_name"),
                {"n": target.name})]
    finally:
        engine.dispose()


def exists(target: Target) -> bool:
    assert target.url is not None
    engine = _admin(target.url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :n"),
                                {"n": target.name}).first() is not None
    finally:
        engine.dispose()


def named_like(url: str, start: str) -> list[str]:
    """Les bases du serveur dont le nom commence par ``start`` (celles des apps de la Forge, par leur préfixe)."""
    pattern = start.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"
    engine = _admin(url)
    try:
        with engine.connect() as conn:
            return sorted(r[0] for r in conn.execute(text(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE :p"), {"p": pattern}))
    finally:
        engine.dispose()


def scratch(url: str, prefix: str, n: int = 1) -> list[Target]:
    """``n`` bases de travail neuves (``<préfixe>w<hasard>_<i>``), à supprimer par l'appelant."""
    tag = secrets.token_hex(4)
    return [Target(url=url, name=f"{prefix}w{tag}_{i}") for i in range(n)]


def drop_app(target: Target) -> None:
    """Supprime la base d'une app forgée et son utilisateur (du même nom, ADR 0101 point 8)."""
    assert target.url is not None
    target.drop()
    engine = _admin(target.url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(f"DROP USER IF EXISTS '{target.name}'@'localhost'")
    finally:
        engine.dispose()
