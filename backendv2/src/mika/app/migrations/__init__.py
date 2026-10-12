"""Les migrations de schéma (Alembic, ADR 0101) : un dossier par base (``mind``, ``views``, ``mail``, ``feeds``,
``teams``), chacun avec son ``env.py`` d'une ligne, son modèle de révision et ses ``versions/``.

Ce que les migrations gèrent : les **entités déclarées** de la base (``mika.ports.sql``), et rien d'autre. Les tables
que le code crée lui-même — le journal du magasin, les projections, qui évoluent par leur version et une
reconstruction depuis le journal — sont ignorées : une révision ne les crée ni ne les supprime.

Une révision s'écrit avec ``python -m mika.app.schema revision <base> "<message>"`` (Alembic compare les entités à
une base vide) et se relit avant d'être gardée.
"""

from __future__ import annotations

from typing import Any

from alembic import context
from sqlalchemy import MetaData

from mika.ports.sql import Key


def _declared(metadata: MetaData) -> Any:
    def include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        table = obj if type_ == "table" else getattr(obj, "table", None)
        table_name = getattr(table, "name", name if type_ == "table" else None)
        return table_name is None or table_name in metadata.tables

    return include


def _render(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Une ``Key(n)`` s'écrit ``sa.String(length=n)`` dans une révision : une migration ne dépend pas du code qui
    l'a vue naître (la borne vérifiée à l'écriture est une affaire du code, pas du schéma)."""
    if type_ == "type" and isinstance(obj, Key):
        return f"sa.String(length={obj.length})"
    return False


def run() -> None:
    """Le corps de chaque ``env.py`` : la connexion et les entités viennent de ``mika.app.schema`` (pas de ligne de
    commande ``alembic``, pas d'``alembic.ini``)."""
    config = context.config
    metadata: MetaData = config.attributes["metadata"]
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("les migrations passent par mika.app.schema (une connexion fournie)")
    context.configure(
        connection=connection,
        target_metadata=metadata,
        include_object=_declared(metadata),
        render_item=_render,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite ne modifie pas une colonne en place
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
