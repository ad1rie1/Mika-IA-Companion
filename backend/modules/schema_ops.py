"""Table lifecycle helpers for plugin modules.

We bypass Django's migration framework to create/drop tables owned by
individual modules. Models should typically declare
``class Meta: managed = False`` so ``makemigrations`` ignores them and
the module itself owns their schema via ``schema_editor``.

The ORM (``Model.objects.*``) is unaffected by ``managed=False``; only
the schema-management hooks are.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.db import connection

logger = logging.getLogger(__name__)


def _existing_tables() -> set[str]:
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def create_tables_for(models: Iterable[type]) -> list[str]:
    """Create tables for any of ``models`` whose db_table does not exist yet.

    Returns the list of db_table names that were actually created.
    Models already backed by a table are left untouched.
    """
    present = _existing_tables()
    created: list[str] = []
    with connection.schema_editor() as editor:
        for model in models:
            table = model._meta.db_table
            if table in present:
                logger.debug("Table %s already present, skipping", table)
                continue
            try:
                editor.create_model(model)
                created.append(table)
                logger.info(
                    "Created table %s for model %s.%s",
                    table, model.__module__, model.__name__,
                )
            except Exception:
                logger.exception(
                    "Failed to create table %s for model %s", table, model.__name__,
                )
    return created


def drop_tables_for(models: Iterable[type]) -> list[str]:
    """Drop tables for ``models``. Silently skips tables that do not exist.

    Returns the list of db_table names that were actually dropped.
    """
    present = _existing_tables()
    dropped: list[str] = []
    # Drop in reverse so FK dependencies are honored when a module
    # declares parents before children.
    with connection.schema_editor() as editor:
        for model in reversed(list(models)):
            table = model._meta.db_table
            if table not in present:
                continue
            try:
                editor.delete_model(model)
                dropped.append(table)
                logger.info("Dropped table %s", table)
            except Exception:
                logger.exception("Failed to drop table %s", table)
    return dropped
