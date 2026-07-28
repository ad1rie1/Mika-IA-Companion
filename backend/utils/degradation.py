"""Degradation ledger — making "this has been broken since boot" answerable.

The engine swallows a lot of failures on purpose, and the purpose is sound:
a background loop has no supervisor, so an exception that escapes ends it for
the lifetime of the process; and not knowing who someone is must never cost
them their answer. Measured across the backend there are 161 broad handlers
that log at DEBUG, fall back silently, or simply ``pass``.

Individually each is defensible. Collectively they mean a partial failure is
indistinguishable from normal operation: a hook broken on the first turn
after a deploy produces exactly the same observable behaviour as a hook with
nothing to do — an empty prompt block, a missing panel section, a drive that
never relieves. Nobody tails DEBUG logs on a personal install.

So this does not change *whether* failures are swallowed. It counts them.

    except Exception as exc:
        degradations.record("journal context", exc)
        return ""

One line replacing the ``logger.debug`` that was there, no control-flow
change — which is deliberate. Rewriting 161 sites into context managers
would be a large diff whose risk is entirely in the parts that behave
differently. For the handful of sites that swallow with a bare ``pass`` and
have no fallback value to produce, ``degraded()`` reads better:

    with degraded("emotion snapshot"):
        await emotion_engine.save_snapshot(person_id)

The ledger is in-RAM and process-scoped, like the drive engine: it describes
this run, and a restart is exactly when you want the counters cleared.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Keep the ledger from growing without bound if a caller ever passes a label
# built from user input. A label is meant to name a *site*, not an instance.
MAX_LABELS = 256


@dataclass
class Degradation:
    """Everything known about one failing site."""

    label: str
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    last_error: str = ""
    # Distinct exception types seen here. A site that fails one way is a bug
    # to fix; a site failing three different ways is usually a dependency
    # that is simply absent.
    error_types: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "age_seconds": round(time.time() - self.first_seen, 1) if self.first_seen else 0.0,
            "last_error": self.last_error,
            "error_types": sorted(self.error_types),
        }


class DegradationLedger:
    """Process-wide tally of swallowed failures, keyed by site label."""

    def __init__(self) -> None:
        self._sites: dict[str, Degradation] = {}
        # Background loops, cron ticks and the ASGI loop all record here.
        self._lock = threading.Lock()

    def record(
        self,
        label: str,
        exc: BaseException | None = None,
        *,
        level: int = logging.DEBUG,
    ) -> None:
        """Tally one swallowed failure at ``label``. Never raises.

        Never raises is not defensive padding: every call site is already
        inside an ``except`` block handling something else, and an
        instrumentation bug that replaced a degraded feature with a crash
        would be a strictly worse outcome than the silence it set out to fix.
        """
        try:
            now = time.time()
            detail = f"{type(exc).__name__}: {exc}" if exc is not None else ""
            with self._lock:
                site = self._sites.get(label)
                if site is None:
                    if len(self._sites) >= MAX_LABELS:
                        return
                    site = Degradation(label=label, first_seen=now)
                    self._sites[label] = site
                site.count += 1
                site.last_seen = now
                if exc is not None:
                    site.last_error = detail
                    site.error_types.add(type(exc).__name__)
            logger.log(level, "degraded: %s (%s)", label, detail or "no detail")
        except Exception:  # pragma: no cover - instrumentation must not bite
            pass

    def snapshot(self) -> list[dict[str, Any]]:
        """All recorded sites, most frequent first."""
        with self._lock:
            sites = [s.as_dict() for s in self._sites.values()]
        sites.sort(key=lambda s: (-s["count"], s["label"]))
        return sites

    def count_for(self, label: str) -> int:
        with self._lock:
            site = self._sites.get(label)
            return site.count if site else 0

    def total(self) -> int:
        with self._lock:
            return sum(s.count for s in self._sites.values())

    def reset(self) -> None:
        """Tests, and the dashboard's "I have read these" button."""
        with self._lock:
            self._sites.clear()


degradations = DegradationLedger()


@contextmanager
def degraded(label: str, *, level: int = logging.DEBUG):
    """Swallow any failure in the block and tally it under ``label``.

    Works in async code as-is: the body may ``await`` freely, because the
    context manager itself has nothing to suspend on.

    Use where the old code was a bare ``except Exception: pass`` — the shape
    with no fallback value to compute. Where the handler produces a fallback
    (``return ""``), keep the ``try/except`` and call ``degradations.record``
    instead: the control flow stays visible at the call site instead of
    hiding inside a manager.
    """
    try:
        yield
    except Exception as exc:
        degradations.record(label, exc, level=level)
