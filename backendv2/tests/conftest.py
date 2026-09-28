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


def make_mind(tmp: Path, faculties: Iterable[Faculty], *, clock=None, threaded: bool = False, **kw) -> Mind:
    store = SqliteStore(tmp / "mind.db", tmp / "views.db", threaded=threaded)
    reg = Registry(list(faculties), arbitration=kw.pop("arbitration", None))
    return Mind(reg, store, clock or ManualClock(START), SeededIdGen(0), **kw)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path
