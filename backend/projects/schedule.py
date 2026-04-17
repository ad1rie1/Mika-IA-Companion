"""Schedule rule parser + evaluator for Project.schedule_rule.

Supported rules (all examples tested):
    ""                        no schedule — manual advance only
    "interval:5m"             every 5 minutes (units: s / m / h / d)
    "interval:30s"            every 30 seconds
    "cron:0 9 * * MON-FRI"    cron expression — uses croniter if available,
                              else falls back to a minimal 5-field parser
                              supporting minute-specificity only
    "idle:30m"                fires when conscience idle_seconds >= 30 min
    "event:email.new"         fires when the named module event is observed
                              (the bus tags next_run_at; here we just check)
    "manual"                  same as ""

Public API:
    parse_rule(rule) -> ParsedRule
    compute_next_run(rule, from_dt) -> datetime | None
    is_due(rule, project) -> bool          (ctx-aware: includes idle)

All functions are pure except `is_due`, which reads runtime state from
the conscience engine. Defensive: unknown rules produce ``None`` (no
schedule) rather than raising, so a malformed field doesn't kill the runner.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


_INTERVAL_RE = re.compile(r"^interval:(\d+)\s*([smhd])$", re.IGNORECASE)
_IDLE_RE = re.compile(r"^idle:(\d+)\s*([smhd])$", re.IGNORECASE)
_CRON_RE = re.compile(r"^cron:(.+)$", re.IGNORECASE)
_EVENT_RE = re.compile(r"^event:([\w.]+)$", re.IGNORECASE)

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class ParsedRule:
    kind: str  # "none" | "interval" | "cron" | "idle" | "event"
    # interval / idle → seconds; cron → cron expression; event → event name
    value: object | None = None


def parse_rule(rule: str) -> ParsedRule:
    """Parse a raw schedule_rule string into a ParsedRule. Never raises."""
    s = (rule or "").strip()
    if not s or s.lower() == "manual":
        return ParsedRule(kind="none")

    m = _INTERVAL_RE.match(s)
    if m:
        value, unit = int(m.group(1)), m.group(2).lower()
        seconds = max(5, value * _UNIT_SECONDS[unit])  # floor 5s to avoid runaway
        return ParsedRule(kind="interval", value=seconds)

    m = _IDLE_RE.match(s)
    if m:
        value, unit = int(m.group(1)), m.group(2).lower()
        seconds = max(60, value * _UNIT_SECONDS[unit])
        return ParsedRule(kind="idle", value=seconds)

    m = _CRON_RE.match(s)
    if m:
        expr = m.group(1).strip()
        return ParsedRule(kind="cron", value=expr)

    m = _EVENT_RE.match(s)
    if m:
        return ParsedRule(kind="event", value=m.group(1))

    logger.warning("Unknown schedule rule: %r — treating as manual", rule)
    return ParsedRule(kind="none")


def compute_next_run(
    rule: str, from_dt: Optional[datetime] = None
) -> Optional[datetime]:
    """Compute the next fire time for a rule, given a baseline.

    For "none" and "event" rules the answer is None — the runner uses
    other signals to decide eligibility.

    For "idle" we compute a floor equal to NOW + idle_window — the
    actual "is_due" check is delegated to is_due() at runtime because
    it depends on live idle state.
    """
    parsed = parse_rule(rule)
    now = from_dt or timezone.now()

    if parsed.kind == "interval":
        return now + timedelta(seconds=int(parsed.value))  # type: ignore[arg-type]

    if parsed.kind == "idle":
        # Next check is at NOW + window — but is_due() will inspect the
        # conscience's actual idle seconds at that moment.
        return now + timedelta(seconds=int(parsed.value))  # type: ignore[arg-type]

    if parsed.kind == "cron":
        return _next_cron(str(parsed.value), now)

    return None  # "none", "event" → no clock-based next_run


def _next_cron(expr: str, now: datetime) -> Optional[datetime]:
    """Return next cron fire time after ``now``. Uses croniter if installed,
    otherwise a tiny fallback that only supports minute-level fields."""
    try:
        from croniter import croniter  # type: ignore[import-not-found]
    except ImportError:
        try:
            return _fallback_cron_next(expr, now)
        except Exception:
            logger.warning("Invalid cron expression %r (fallback parser)", expr)
            return None

    try:
        base = now.replace(second=0, microsecond=0)
        it = croniter(expr, base)
        return it.get_next(datetime)
    except Exception:
        logger.warning("Invalid cron expression %r", expr)
        return None


def _fallback_cron_next(expr: str, now: datetime) -> Optional[datetime]:
    """Minimal cron parser for `minute hour dom month dow` — supports:
      - Exact integers
      - `*` (any)
      - Simple comma lists: `0,30` | `MON,WED,FRI` (day-of-week names)
      - Day-of-week ranges: `MON-FRI`

    Not a full cron. Used only when croniter isn't installed — a permissive
    fallback that covers the common "every weekday at 9h" case.
    """
    fields = expr.split()
    if len(fields) != 5:
        logger.warning("Fallback cron needs 5 fields, got %r", expr)
        return None

    minute_f, hour_f, dom_f, month_f, dow_f = fields

    def _matches_int(val: int, field: str) -> bool:
        if field == "*":
            return True
        for part in field.split(","):
            try:
                if int(part) == val:
                    return True
            except ValueError:
                pass
        return False

    _DOW_MAP = {
        "SUN": 6, "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5,
    }

    def _matches_dow(val_mon_based: int, field: str) -> bool:
        # `val_mon_based` uses Python weekday() where Monday=0..Sunday=6
        if field == "*":
            return True
        parts = field.split(",")
        for part in parts:
            part = part.strip().upper()
            if "-" in part:
                # split once: anything beyond a single hyphen is malformed
                segs = part.split("-", 1)
                if len(segs) != 2 or not segs[0] or not segs[1] or "-" in segs[1]:
                    continue
                lo, hi = segs[0], segs[1]
                lo_i = _DOW_MAP.get(lo, _parse_int(lo))
                hi_i = _DOW_MAP.get(hi, _parse_int(hi))
                if lo_i is None or hi_i is None:
                    continue
                if lo_i <= val_mon_based <= hi_i:
                    return True
            else:
                num = _DOW_MAP.get(part, _parse_int(part))
                if num is not None and num == val_mon_based:
                    return True
        return False

    # Search up to 7 days ahead, minute by minute. Plenty fast.
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = now + timedelta(days=7)
    while candidate <= end:
        if (
            _matches_int(candidate.minute, minute_f)
            and _matches_int(candidate.hour, hour_f)
            and _matches_int(candidate.day, dom_f)
            and _matches_int(candidate.month, month_f)
            and _matches_dow(candidate.weekday(), dow_f)
        ):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def is_due(project, now: Optional[datetime] = None) -> bool:
    """Runtime check: is this project currently due for an advance tick?

    - "none" → never due via schedule (only user/admin push)
    - "interval", "cron" → due iff next_run_at <= now
    - "idle" → due iff conscience idle_seconds >= window
    - "event" → not evaluated here; events tag next_run_at directly

    Caller should ensure project.status is ACTIVE beforehand; we don't
    check it here to keep this function pure.
    """
    now = now or timezone.now()
    parsed = parse_rule(project.schedule_rule)

    if parsed.kind == "none":
        return False

    if parsed.kind in ("interval", "cron"):
        return bool(project.next_run_at and project.next_run_at <= now)

    if parsed.kind == "idle":
        try:
            from conscience.engine import conscience_engine
            idle = conscience_engine.get_idle_seconds()
        except Exception:
            idle = 0.0
        return idle >= float(parsed.value)  # type: ignore[arg-type]

    if parsed.kind == "event":
        # Event matches tag next_run_at manually (see runner.notify_event).
        # Here we just obey the timestamp.
        return bool(project.next_run_at and project.next_run_at <= now)

    return False
