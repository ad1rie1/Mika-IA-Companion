"""Retention sweep — keeps append-only tables from growing forever.

Some tables already prune themselves (``Observation`` at 48h, ``ForgeLog``
at 300 rows/module, ``RSSEntry`` at 200/feed, ``ProjectPromptHistory`` as a
ring buffer). Several did not, and one of them grows *independently of
usage*: ``ConscienceLog`` gets a row on every decision cycle regardless of
outcome — at the default 30s interval that is ~2 880 rows/day, over a
million a year, on an install nobody ever talks to.

The policies here are deliberately generous: this is Mika's audit trail and
her past, not a cache. The point is a ceiling, not aggressive cleanup.

Called once per consolidator tick; each table is swept independently so one
failure never blocks the others.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    """One table's retention rule.

    ``keep_days`` deletes by age; ``keep_rows`` keeps only the N newest.
    Both may apply — age first, then the row ceiling as a backstop for a
    burst that fits inside the window.
    """
    app_label: str
    model_name: str
    date_field: str = "created_at"
    keep_days: int | None = None
    keep_rows: int | None = None
    # Rows matching this filter are never deleted (e.g. unresolved work).
    protect: dict | None = None
    note: str = ""


POLICIES: tuple[Policy, ...] = (
    # Written every decision cycle, mostly "skip" — the only table whose
    # growth is independent of user activity.
    Policy("conscience", "ConscienceLog", keep_days=30, keep_rows=50_000,
           note="decision audit trail"),
    # One row per consolidation tick, and only the latest is ever read
    # (checkpoint resume). Everything older is pure weight.
    Policy("memory", "ConsolidationLog", date_field="ran_at",
           keep_days=14, keep_rows=5_000,
           note="only the newest row is read, for the checkpoint"),
    # Faded ruminations are done being turned over; active/resolved ones
    # are still referenced by journals and digestion.
    Policy("conscience", "Rumination", date_field="created_at", keep_days=90,
           protect={"status__in": ("active", "resolved")},
           note="faded thoughts only"),
    # Per-tick project bookkeeping. Its sibling ProjectPromptHistory already
    # has a ring buffer; this one was simply missed.
    Policy("projects", "ProjectLog", keep_days=90, keep_rows=20_000,
           note="project audit trail"),
)


async def run_sweep() -> dict[str, int]:
    """Apply every policy. Returns {label: rows_deleted} for what it touched."""
    deleted: dict[str, int] = {}
    for policy in POLICIES:
        try:
            count = await _sweep_one(policy)
        except Exception:
            # A missing app/model or a locked table must not break the tick.
            logger.debug("Retention sweep failed for %s.%s",
                         policy.app_label, policy.model_name, exc_info=True)
            continue
        if count:
            deleted[f"{policy.app_label}.{policy.model_name}"] = count
    if deleted:
        logger.info("Retention sweep removed %s", deleted)
    return deleted


async def _sweep_one(policy: Policy) -> int:
    from django.apps import apps

    model = apps.get_model(policy.app_label, policy.model_name)

    def _delete() -> int:
        removed = 0
        base = model.objects.all()
        if policy.protect:
            base = base.exclude(**policy.protect)

        if policy.keep_days is not None:
            cutoff = timezone.now() - timedelta(days=policy.keep_days)
            # Delete by pk list: .delete() on a sliced/complex queryset is
            # not portable, and this keeps the statement bounded.
            ids = list(
                base.filter(**{f"{policy.date_field}__lt": cutoff})
                .values_list("pk", flat=True)[:10_000]
            )
            if ids:
                removed += model.objects.filter(pk__in=ids).delete()[0]

        if policy.keep_rows is not None:
            surplus = list(
                base.order_by(f"-{policy.date_field}")
                .values_list("pk", flat=True)[policy.keep_rows:]
            )
            if surplus:
                removed += model.objects.filter(
                    pk__in=surplus[:10_000]).delete()[0]

        return removed

    return await sync_to_async(_delete)()
