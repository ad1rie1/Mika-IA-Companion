from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from mika.adapters.store_sqlite import SqliteStore
from mika.kernel.clock import US, ManualClock
from mika.kernel.faculty import Faculty
from mika.kernel.ids import SeededIdGen
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind

START = 1_790_000_000 * US  # 2026-09-21, un instant fixe


# ── Les tests longs : à la demande ────────────────────────────────────────
# Marqués ``@pytest.mark.slow`` (scénarios complets, vies de plusieurs semaines, performances), ils sont
# écartés d'un lancement ordinaire. ``--slow`` les ajoute ; ``-m slow`` ne lance qu'eux ; viser leur fichier
# (``pytest tests/unit/test_long_life.py``) les lance aussi.


#: combien de tests longs ont été écartés (dit en fin de lancement)
_SLOW_LEFT = pytest.StashKey[int]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--slow", action="store_true", default=False, help="lance aussi les tests longs (slow)")


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
    store = SqliteStore(tmp / "mind.db", tmp / "views.db", threaded=threaded)
    reg = Registry(list(faculties), arbitration=kw.pop("arbitration", None))
    return Mind(reg, store, clock or ManualClock(START), SeededIdGen(0), **kw)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path
