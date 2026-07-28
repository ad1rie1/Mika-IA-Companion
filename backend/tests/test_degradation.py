"""The degradation ledger, and the sites wired to it.

Measured across the backend: 189 typed handlers, 135 that log loudly, and
**161 that do not** — 75 at DEBUG, 62 falling back silently, 24 a bare
``pass``. Individually each is defensible; the engine degrades rather than
crashes on purpose, because a background loop has no supervisor and not
knowing who someone is must never cost them their answer.

Collectively they mean a partial failure is indistinguishable from normal
operation. A prompt block that is empty because its query throws looks
exactly like a prompt block with nothing to say.

These tests cover the ledger, and — more importantly — that the hot-path and
unsupervised-loop sites actually report into it.
"""

from __future__ import annotations

import logging

import pytest

from utils.degradation import DegradationLedger, degradations, degraded


@pytest.fixture(autouse=True)
def _clean():
    degradations.reset()
    yield
    degradations.reset()


# ---------------------------------------------------------------------------
# 1. The ledger
# ---------------------------------------------------------------------------


class TestLedger:

    def test_a_recorded_failure_is_counted(self):
        led = DegradationLedger()
        led.record("thing", ValueError("nope"))
        assert led.count_for("thing") == 1

    def test_repeats_accumulate_under_one_label(self):
        led = DegradationLedger()
        for _ in range(5):
            led.record("thing", ValueError("nope"))
        assert led.count_for("thing") == 5
        assert len(led.snapshot()) == 1

    def test_the_last_error_is_kept(self):
        led = DegradationLedger()
        led.record("thing", ValueError("first"))
        led.record("thing", KeyError("second"))
        site = led.snapshot()[0]
        assert "second" in site["last_error"]

    def test_distinct_error_types_are_kept(self):
        """A site failing one way is a bug; a site failing three ways is
        usually a dependency that is simply absent."""
        led = DegradationLedger()
        led.record("thing", ValueError("a"))
        led.record("thing", KeyError("b"))
        assert led.snapshot()[0]["error_types"] == ["KeyError", "ValueError"]

    def test_first_seen_survives_later_failures(self):
        """"Broken since boot" is the question this answers, so the first
        timestamp must not be overwritten by the thousandth."""
        led = DegradationLedger()
        led.record("thing", ValueError("a"))
        first = led.snapshot()[0]["first_seen"]
        led.record("thing", ValueError("b"))
        assert led.snapshot()[0]["first_seen"] == first

    def test_snapshot_is_ordered_by_frequency(self):
        led = DegradationLedger()
        led.record("rare", ValueError())
        for _ in range(3):
            led.record("common", ValueError())
        assert [s["label"] for s in led.snapshot()] == ["common", "rare"]

    def test_total_sums_every_site(self):
        led = DegradationLedger()
        led.record("a", ValueError())
        led.record("b", ValueError())
        led.record("b", ValueError())
        assert led.total() == 3

    def test_recording_without_an_exception_is_allowed(self):
        led = DegradationLedger()
        led.record("thing")
        assert led.count_for("thing") == 1

    def test_the_label_space_is_bounded(self):
        """Guards against a caller building labels from user input: a label
        names a site, not an instance."""
        from utils.degradation import MAX_LABELS

        led = DegradationLedger()
        for i in range(MAX_LABELS + 50):
            led.record(f"label-{i}", ValueError())
        assert len(led.snapshot()) == MAX_LABELS

    def test_recording_never_raises(self):
        """Every call site is already inside an except block handling
        something else. An instrumentation bug that turned a degraded
        feature into a crash would be strictly worse than the silence."""
        led = DegradationLedger()

        class Nasty(Exception):
            def __str__(self):
                raise RuntimeError("even my repr is broken")

        led.record("thing", Nasty())

    def test_reset_clears_everything(self):
        led = DegradationLedger()
        led.record("thing", ValueError())
        led.reset()
        assert led.snapshot() == [] and led.total() == 0


# ---------------------------------------------------------------------------
# 2. The context-manager form
# ---------------------------------------------------------------------------


class TestDegradedContextManager:

    def test_it_swallows_and_counts(self):
        with degraded("block"):
            raise ValueError("boom")
        assert degradations.count_for("block") == 1

    def test_a_clean_block_records_nothing(self):
        with degraded("block"):
            pass
        assert degradations.count_for("block") == 0

    @pytest.mark.asyncio
    async def test_it_works_around_await(self):
        """The body may await freely — the manager has nothing to suspend on,
        which is why a sync contextmanager is the right shape here."""
        import asyncio

        with degraded("async block"):
            await asyncio.sleep(0)
            raise ValueError("boom")
        assert degradations.count_for("async block") == 1

    def test_it_does_not_swallow_cancellation(self):
        """CancelledError derives from BaseException; a loop being shut down
        must not be logged as a degraded feature and kept alive."""
        import asyncio

        with pytest.raises(asyncio.CancelledError):
            with degraded("block"):
                raise asyncio.CancelledError()


# ---------------------------------------------------------------------------
# 3. The wired sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHotPathIsInstrumented:
    """The conversation hot path: a failure here silently removes a block
    from the prompt, every turn, for the life of the process."""

    async def test_journal_context_failure_is_recorded(self):
        from unittest.mock import AsyncMock, patch

        from pipeline import context

        with patch("memory.read.journal_for",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            assert await context._fetch_journal_context() == ""

        assert degradations.count_for("prompt: journal context") == 1

    async def test_self_concept_failure_is_recorded(self):
        from unittest.mock import AsyncMock, patch

        from pipeline import context

        with patch("memory.read.latest_self_narrative",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            assert await context._fetch_self_concept() == ""

        assert degradations.count_for("prompt: self-concept") == 1

    async def test_rumination_context_failure_is_recorded(self):
        from unittest.mock import AsyncMock, patch

        from pipeline import context

        with patch("conscience.read.active_ruminations",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            assert await context._fetch_rumination_context() == ""

        assert degradations.count_for("prompt: rumination context") == 1

    async def test_each_inner_state_section_is_counted_separately(self):
        """One handler covers ten loaders, so a single broken section used
        to read as a panel card with nothing to show."""
        from pipeline.broadcast import _merge_section

        state: dict = {}

        async def boom():
            raise RuntimeError("nope")

        await _merge_section(state, "dream", boom)
        await _merge_section(state, "projects", boom)

        assert degradations.count_for("inner state: dream") == 1
        assert degradations.count_for("inner state: projects") == 1


class TestInstrumentationCoverage:
    """Guards on where the ledger is wired, so the instrumentation is not
    quietly removed by a later edit."""

    def test_every_record_call_sits_inside_an_except_block(self):
        """The mechanical sweep that added these initially mis-converted
        nine *informational* debug logs ("Pruned souvenir #12") into
        degradation records. This is the check that caught it."""
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in root.rglob("*.py"):
            if "__pycache__" in str(path) or "/tests/" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            guarded = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    for sub in node.body:
                        for st in ast.walk(sub):
                            if _is_record_call(st):
                                guarded.add(st.lineno)
            for node in ast.walk(tree):
                if _is_record_call(node) and node.lineno not in guarded:
                    offenders.append(f"{path.name}:{node.lineno}")

        assert not offenders, (
            "degradations.record() outside an except block — a degradation "
            f"ledger is for failures, not for progress logs: {offenders}"
        )

    def test_a_label_never_covers_two_different_functions(self):
        """A label names a *site*. The sweep that added the mechanical ones
        first derived them from the enclosing **class** rather than the
        enclosing function, so five distinct handlers in `EmotionEngine`
        all reported as `emotion.engine.EmotionEngine` — a counter that
        tells you something is broken but not what. This is that check.
        """
        import ast
        import pathlib
        from collections import defaultdict

        root = pathlib.Path(__file__).resolve().parent.parent
        owners = defaultdict(set)

        for path in root.rglob("*.py"):
            if "__pycache__" in str(path) or "/tests/" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for label, func in _labelled_sites(tree):
                owners[label].add(f"{path.name}::{func}")

        shared = {lbl: sorted(o) for lbl, o in owners.items() if len(o) > 1}
        assert not shared, (
            "ces libelles couvrent plusieurs fonctions, le compteur ne "
            f"localise donc rien: {shared}"
        )

    def test_the_unsupervised_loops_report(self):
        """Nothing restarts these loops, so a hook broken inside one stays
        broken for the life of the process."""
        import inspect

        from conscience import engine as conscience_engine
        from memory import sleep
        from memory.storage import consolidator
        from projects import runner

        for module in (runner, conscience_engine, sleep, consolidator):
            src = inspect.getsource(module)
            assert "degradations.record(" in src, module.__name__


def _is_record_call(node) -> bool:
    import ast

    return (
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "record"
        and getattr(getattr(node.func, "value", None), "id", None) == "degradations"
    )


def _labelled_sites(tree):
    """Yield ``(label, enclosing_function)`` for every literal-labelled site."""
    import ast

    stack: list[str] = []

    def walk(node):
        is_fn = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if is_fn:
            stack.append(node.name)
        if _is_record_call(node) and node.args and isinstance(node.args[0], ast.Constant):
            yield node.args[0].value, (stack[-1] if stack else "<module>")
        for child in ast.iter_child_nodes(node):
            yield from walk(child)
        if is_fn:
            stack.pop()

    yield from walk(tree)


# ---------------------------------------------------------------------------
# 4. The endpoint that makes any of this useful
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealthEndpoint:

    def test_it_reports_recorded_degradations(self, client):
        degradations.record("prompt: journal context", ValueError("db down"))

        payload = client.get("/dashboard/api/system/health").json()
        labels = [s["label"] for s in payload["degradations"]["sites"]]
        assert "prompt: journal context" in labels
        assert payload["degradations"]["total_events"] >= 1

    def test_it_reports_bus_subscriptions(self, client):
        payload = client.get("/dashboard/api/system/health").json()
        names = [s["name"] for s in payload["event_bus"]["subscriptions"]]
        assert "projects" in names

    def test_a_healthy_process_reports_nothing_failing(self, client):
        payload = client.get("/dashboard/api/system/health").json()
        assert payload["event_bus"]["failing"] == []
