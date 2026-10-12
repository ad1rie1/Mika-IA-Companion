"""Le schéma de ses bases, déclaré par les entités et tenu par les migrations (ADR 0101).

``migrate_data(data)`` passe chaque base d'un dossier de données à la dernière révision, avant que quoi que ce
soit ne s'ouvre (le serveur, les commandes qui écrivent). Une base dont les tables ont été créées par les entités
elles-mêmes (``create``, ce que font les tests et le simulateur) sans jamais avoir été migrée est complétée par
elles puis marquée à la dernière révision : les entités sont la dernière révision, ce que ``differences`` vérifie.

``python -m mika.app.schema revision <base> "<message>"`` écrit une révision en comparant les entités à la base
telle que les révisions précédentes la laissent ; on la relit avant de la garder.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from mika.adapters.database import sqlite_engine
from mika.app.migrations import _declared
from mika.ports.sql import DATABASES

#: les modules qui déclarent des entités : les importer remplit les ``MetaData`` de ``mika.ports.sql``
MODELS = (
    "mika.adapters.web.accounts",
    "mika.app.settings",
    "mika.adapters.llm.calls",
    "mika.runtime.traces",
    "mika.runtime.series",
    "mika.adapters.mail.models",
    "mika.adapters.feeds.models",
    "mika.adapters.teams.models",
)

#: le fichier de chaque base dans un dossier de données (SQLite)
FILES = {"mind": "mind.db", "views": "views.db", "mail": "mail.db", "feeds": "feeds.db", "teams": "teams.db"}

_HERE = Path(__file__).parent / "migrations"


def load_models() -> None:
    for name in MODELS:
        importlib.import_module(name)


def _config(name: str) -> Config:
    if name not in DATABASES:
        raise ValueError(f"base inconnue : {name!r} ({', '.join(DATABASES)})")
    load_models()
    cfg = Config()
    cfg.set_main_option("script_location", str(_HERE / name))
    cfg.attributes["metadata"] = DATABASES[name]
    return cfg


def migrate(name: str, engine: Engine) -> None:
    """Passe la base ``name`` à la dernière révision (marquée d'abord si ses tables viennent des entités seules)."""
    cfg = _config(name)
    metadata = DATABASES[name]
    with engine.connect() as probe:
        tables = set(inspect(probe).get_table_names())
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        if "alembic_version" not in tables and tables & set(metadata.tables):
            # née des entités (en partie peut-être) : complétée par elles, elle est alors la dernière révision
            metadata.create_all(conn, checkfirst=True)
            conn.commit()
            command.stamp(cfg, "head")
        command.upgrade(cfg, "head")
        conn.commit()


def migrate_data(data: Path) -> None:
    """Chaque base du dossier de données à sa dernière révision (fichiers SQLite)."""
    data.mkdir(parents=True, exist_ok=True)
    for name, file in FILES.items():
        engine = sqlite_engine(data / file)
        try:
            migrate(name, engine)
        finally:
            engine.dispose()


def differences(name: str, engine: Engine) -> list[Any]:
    """Ce qui sépare la base des entités déclarées (vide : la base est à jour) — les tables qu'on ne déclare pas
    (journal, projections) ne comptent pas."""
    load_models()
    metadata = DATABASES[name]
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": _declared(metadata), "compare_type": True})
        return list(compare_metadata(ctx, metadata))


def revision(name: str, message: str) -> Path:
    """Écrit une révision de la base ``name`` : les entités comparées à une base SQLite vide passée aux révisions
    existantes. Rend le fichier écrit."""
    cfg = _config(name)
    with tempfile.TemporaryDirectory() as tmp:
        engine = sqlite_engine(Path(tmp) / f"{name}.db")
        try:
            with engine.connect() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
                conn.commit()
                script = command.revision(cfg, message=message, autogenerate=True)
        finally:
            engine.dispose()
    scripts = script if isinstance(script, list) else [script]
    path = Path(scripts[0].path)
    # le gabarit d'Alembic laisse des espaces en fin de ligne (« Revises: » d'une première révision)
    path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n",
                    encoding="utf-8")
    return path


def main(argv: Mapping[int, str] | list[str]) -> int:
    args = list(argv)
    if len(args) == 3 and args[0] == "revision":
        print(revision(args[1], args[2]))
        return 0
    print('usage : python -m mika.app.schema revision <base> "<message>"', file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
