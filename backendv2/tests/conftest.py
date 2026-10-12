from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import pytest

import mika.sim.world as sim_world
from mika.adapters.store_sql import SqlStore
from mika.kernel.clock import US, ManualClock
from mika.kernel.faculty import Faculty
from mika.kernel.ids import SeededIdGen
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind
from tests.fixtures import backend

START = 1_790_000_000 * US  # 2026-09-21, un instant fixe


# ── Les tests longs : à la demande ────────────────────────────────────────
# Marqués ``@pytest.mark.slow`` (scénarios complets, vies de plusieurs semaines, performances), ils sont
# écartés d'un lancement ordinaire. ``--slow`` les ajoute ; ``-m slow`` ne lance qu'eux ; viser leur fichier
# (``pytest tests/unit/test_long_life.py``) les lance aussi.


#: combien de tests longs ont été écartés (dit en fin de lancement)
_SLOW_LEFT = pytest.StashKey[int]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--slow", action="store_true", default=False, help="lance aussi les tests longs (slow)")
    parser.addoption("--mariadb", action="store_true", default=False,
                     help="les magasins des tests sur un serveur MariaDB (MIKA_TEST_MARIADB, sinon le socket local)")


# ── La voie MariaDB (ADR 0101, point 11) ──────────────────────────────────
# ``--mariadb`` : les magasins des tests (``make_mind``, les montages, le simulateur, ``SqlDB``, l'application) vivent
# dans des bases jetables d'un serveur MariaDB, supprimées à la fin de chaque test. Voir ``tests/fixtures/backend.py``.


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "sqlite_only: lit les fichiers SQLite eux-mêmes (écarté de --mariadb)")
    if config.getoption("--mariadb"):
        backend.enable()
        sim_world.STORES = backend.store_targets


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    backend.drop_session()


@pytest.fixture(autouse=True)
def _mariadb_lane(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Sous ``--mariadb`` : l'application d'un test (``schema.targets``) range ses bases sur le serveur, sous un préfixe
    à lui ; ce que le test a créé est supprimé à sa fin."""
    if not backend.active():
        yield
        return
    if request.node.get_closest_marker("sqlite_only"):
        pytest.skip("lit les fichiers SQLite eux-mêmes")
    monkeypatch.setenv("MIKA_DATABASE_URL", backend.url())
    monkeypatch.setenv("MIKA_DATABASE_PREFIX", backend.prefix())
    yield
    backend.drop_made()
    backend.drop_session_prefix(os.environ.get("MIKA_DATABASE_PREFIX", ""))


def _targeted(config: pytest.Config) -> set[Path]:
    """Les fichiers nommés sur la ligne de commande (pas les dossiers) : on ne les écarte jamais."""
    out = set()
    for arg in config.args:
        path = Path(str(arg).split("::")[0])
        if path.suffix == ".py" and path.is_file():
            out.add(path.resolve())
    return out


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--slow") or "slow" in (config.getoption("markexpr") or ""):
        return
    targeted = _targeted(config)
    kept, slow = [], []
    for item in items:
        (slow if item.get_closest_marker("slow") and item.path.resolve() not in targeted else kept).append(item)
    if slow:
        config.hook.pytest_deselected(items=slow)
        items[:] = kept
        config.stash[_SLOW_LEFT] = len(slow)


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    left = config.stash.get(_SLOW_LEFT, 0)
    if left:
        terminalreporter.write_line(f"{left} test(s) long(s) écarté(s) : --slow pour les lancer aussi")


def make_mind(tmp: Path, faculties: Iterable[Faculty], *, clock=None, threaded: bool = False, **kw) -> Mind:
    store = SqlStore(*backend.store_targets(tmp), threaded=threaded)
    reg = Registry(list(faculties), arbitration=kw.pop("arbitration", None))
    return Mind(reg, store, clock or ManualClock(START), SeededIdGen(0), **kw)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path
