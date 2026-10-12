"""La voie MariaDB des tests (ADR 0101, point 11).

Avec ``--mariadb``, les magasins des tests vivent dans des bases jetables d'un serveur MariaDB
(``mika_test_<session>_<n>_<base>``) : ``make_mind``, les montages de ``tests/fixtures``, le simulateur, le faux
magasin ``SqlDB`` et l'application elle-même (``MIKA_DATABASE_URL`` + un préfixe par test). Les bases d'un test sont
supprimées à sa fin, celles qui resteraient à la fin de la session. Sans ``--mariadb``, des fichiers SQLite, comme
toujours.

Le serveur : ``MIKA_TEST_MARIADB`` (une adresse sans base), sinon le serveur local par son socket, sous l'utilisateur
du système (``unix_socket`` : aucun mot de passe). Ce compte n'a de droits que sur les bases ``mika\\_test\\_%`` ;
il se crée une fois, en administrateur du serveur (``sudo mariadb``) — ``CREATE USER`` et ``GRANT OPTION`` : les
bases des apps de la Forge ont chacune leur utilisateur (ADR 0101, point 8) :

    CREATE USER '<utilisateur>'@'localhost' IDENTIFIED VIA unix_socket;
    GRANT ALL PRIVILEGES ON `mika\\_test\\_%`.* TO '<utilisateur>'@'localhost' WITH GRANT OPTION;
    GRANT CREATE USER ON *.* TO '<utilisateur>'@'localhost';
"""

from __future__ import annotations

import getpass
import os
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from mika.adapters.database import Target

URL_ENV = "MIKA_TEST_MARIADB"
DEFAULT_URL = f"mariadb+pymysql://{getpass.getuser()}@localhost/?unix_socket=/var/lib/mysql/mysql.sock"

_RUN = uuid.uuid4().hex[:8]
_state: dict[str, object] = {"url": None, "n": 0}
_made: list[Target] = []


def enable(url: str | None = None) -> None:
    _state["url"] = url or os.environ.get(URL_ENV) or DEFAULT_URL


def active() -> bool:
    return _state["url"] is not None


def url() -> str:
    assert active(), "voie MariaDB non active"
    return str(_state["url"])


def prefix() -> str:
    """Un préfixe neuf pour un jeu de bases (``mika_test_<session>_<n>_``)."""
    _state["n"] = int(_state["n"]) + 1  # type: ignore[call-overload]
    return f"mika_test_{_RUN}_{_state['n']}_"


def target(tmp: Path, name: str) -> Target:
    """Une base : un fichier de ``tmp`` sous SQLite, une base jetable du serveur sous ``--mariadb``."""
    if not active():
        return Target(path=tmp / f"{name}.db")
    t = Target(url=url(), name=f"{prefix()}{name}")
    _made.append(t)
    return t


#: le préfixe des bases de chaque dossier de test : rouvrir un magasin sur le même dossier (un redémarrage) retrouve
#: les mêmes bases, comme les mêmes fichiers
_by_dir: dict[Path, str] = {}


def store_targets(tmp: Path) -> tuple[Path | Target, Path | Target]:
    """``mind`` et ``views`` d'un magasin de test (les mêmes pour le même dossier)."""
    if not active():
        return tmp / "mind.db", tmp / "views.db"
    key = Path(tmp).resolve()
    p = _by_dir.get(key)
    if p is None:
        # le premier dossier du test prend le préfixe de l'application (``MIKA_DATABASE_PREFIX``) : une commande lancée
        # sur ce dossier (``schema.targets``) retrouve ses bases
        given = os.environ.get("MIKA_DATABASE_PREFIX", "")
        p = _by_dir[key] = given if given and given not in _by_dir.values() else prefix()
    mind, views = Target(url=url(), name=f"{p}mind"), Target(url=url(), name=f"{p}views")
    _made.extend((mind, views))
    return mind, views


def drop_made() -> None:
    """Les bases faites depuis le dernier appel (la fin d'un test)."""
    seen: set[str] = set()
    while _made:
        t = _made.pop()
        if str(t) not in seen:
            seen.add(str(t))
            t.drop()
    _by_dir.clear()


def drop_session() -> None:
    """Tout ce qui reste de cette session sur le serveur (un test interrompu, une base faite par l'application)."""
    drop_session_prefix(f"mika_test_{_RUN}_")


def drop_session_prefix(start: str) -> None:
    """Les bases dont le nom commence par ``start`` (``mika_test_…`` seulement : rien d'autre ne se supprime ici)."""
    if not active() or not start.startswith(f"mika_test_{_RUN}_"):
        return
    pattern = start.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"
    server = create_engine(make_url(url()).set(database=None), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as conn:
            names = [r[0] for r in conn.exec_driver_sql(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE %s", (pattern,))]
            for name in names:
                conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{name}`")
                if "_forge_" in name:  # la base d'une app de la Forge a son utilisateur, du même nom
                    conn.exec_driver_sql(f"DROP USER IF EXISTS '{name}'@'localhost'")
    finally:
        server.dispose()
