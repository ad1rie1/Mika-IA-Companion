"""Ce que les commandes partagent : qui opère, un noyau relu hors ligne, les réglages hors ligne."""

from __future__ import annotations

from pathlib import Path

from mika.adapters.shares import DiskShares
from mika.adapters.store_sql import SqlStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.vectors import SqliteVectorIndex
from mika.app import composition, datadir, embeddings, schema
from mika.app.settings import SecretBox, Settings
from mika.runtime.bootstrap import Kernel

#: qui opère depuis la ligne de commande (l'audit ``runtime.operated`` le dit)
CLI_BY = "ligne de commande"


async def _offline(data: Path, *, vectors: bool = False) -> Kernel:
    """Un noyau relu, rien de vivant : aucun processus, aucun modèle (serveur arrêté)."""
    datadir.hold(data)  # serveur arrêté : une seule écriture à la fois
    bases = schema.targets(data)
    schema.migrate_data(data, bases)
    store = SqlStore(bases["mind"], bases["views"], threaded=False)
    ports: dict[str, object] = {}
    if vectors:  # le modèle ne se charge qu'à un plongement : jamais ici
        ports["vectors"] = SqliteVectorIndex(store, embeddings.embedder())
    # les octets des fichiers qu'elle a envoyés (ADR 0062) : l'oubli d'une personne les efface aussi d'ici
    ports["shares"] = DiskShares(data / "partages")
    kernel = Kernel(composition.deps(store=store, clock=RealClock(), ids=RandomIdGen(), ports=ports))
    try:
        await kernel.mind.boot(append_boot=False)
    except BaseException:
        datadir.release(data)
        raise
    return kernel


async def _close(kernel: Kernel, data: Path) -> None:
    try:
        await kernel.mind.close()
    finally:
        datadir.release(data)


async def _with_settings(data: Path, fn):  # type: ignore[no-untyped-def]
    bases = schema.targets(data)
    schema.migrate_data(data, bases)
    store = SqlStore(bases["mind"], bases["views"], threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(data))
        await settings.open()
        return await fn(settings, store)
    finally:
        await store.close()
