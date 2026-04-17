"""AI quota tracking + limiter.

Every call routed through ``ai.router.AIRouter.complete`` is metered:
  - token counts (provider-native when available, char-based fallback)
  - USD cost (pricing table; $0 for local Ollama)
  - attributed to a role (AIRole) and, when set, to a project id

The tracker maintains in-RAM daily and monthly totals per role and per
project for O(1) limit checks, and persists per-day aggregates in the
``AIQuotaUsage`` DB table on each record. On startup ``hydrate()`` can
be called to re-populate the RAM counters from DB.

Limiting policy
---------------
* **Global daily / monthly** token caps (from settings).
* **Per-role daily / monthly** token caps (from settings, overrides
  global on miss — settings take precedence).
* **Per-project monthly** token budget (from ``Project.monthly_token_budget``).

When a cap is exceeded, the router raises ``QuotaExceeded`` *before*
making the LLM call. The caller can catch this and fall back (return
silence for the conscience, defer a project tick, etc.).

Token counting
--------------
Providers that can report real usage (Claude, OpenAI) set
``_usage_ctx`` via ``set_usage``. The router reads it after the call.
If unset, we estimate tokens from the character count (≈ chars / 4).
Ollama always uses the estimate but costs $0 regardless.
"""
from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Context variables ────────────────────────────────────────────

# Set by ProjectRunner (and any other project-scoped caller) to attribute
# a call to a project's budget. Cleared after the call.
current_project_id: ContextVar[Optional[int]] = ContextVar(
    "ai_quota_project_id", default=None,
)

# Optional per-call usage set by providers that know their token counts.
# Layout: {"in": int, "out": int}. Cleared before each call.
_usage_ctx: ContextVar[Optional[dict]] = ContextVar(
    "ai_quota_usage_ctx", default=None,
)


def set_usage(input_tokens: int, output_tokens: int) -> None:
    """Providers call this right after the API round-trip to hand real
    token counts to the router. No-op when not running under the router."""
    try:
        _usage_ctx.set({"in": int(input_tokens), "out": int(output_tokens)})
    except Exception:
        pass


def _reset_usage() -> None:
    _usage_ctx.set(None)


def _take_usage() -> Optional[dict]:
    value = _usage_ctx.get()
    _reset_usage()
    return value


# ── Exceptions ───────────────────────────────────────────────────


class QuotaExceeded(Exception):
    """Raised when an LLM call would push a counter past its cap."""

    def __init__(self, scope: str, used: int, limit: int, detail: str = ""):
        self.scope = scope      # e.g. "role:conversation:daily", "project:42:monthly"
        self.used = used
        self.limit = limit
        msg = f"Quota {scope} dépassé ({used}/{limit} tokens)"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


# ── Pricing table (USD per token, best-effort — override via settings) ──

# Sources: Anthropic + OpenAI public pricing pages as of early 2026.
# Values are per 1M tokens, converted to per-token in _MODEL_PRICING_USD.
# Any model not listed falls back to the family-level entry below; any
# family not listed is billed as $0 (local / unknown → no cost surprise).
_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    # Claude Opus family (priciest)
    "claude-opus":        (15.0, 75.0),
    "claude-opus-4":      (15.0, 75.0),
    "claude-opus-4-6":    (15.0, 75.0),
    "claude-opus-4-7":    (15.0, 75.0),
    # Claude Sonnet
    "claude-sonnet":      (3.0, 15.0),
    "claude-sonnet-4":    (3.0, 15.0),
    "claude-sonnet-4-5":  (3.0, 15.0),
    "claude-sonnet-4-6":  (3.0, 15.0),
    # Claude Haiku
    "claude-haiku":       (0.8, 4.0),
    "claude-haiku-4":     (0.8, 4.0),
    "claude-haiku-4-5":   (0.8, 4.0),
    # OpenAI
    "gpt-4o":             (2.5, 10.0),
    "gpt-4o-mini":        (0.15, 0.6),
    "gpt-4.1":            (2.0, 8.0),
    "gpt-4.1-mini":       (0.4, 1.6),
    "gpt-4.1-nano":       (0.1, 0.4),
    "o1":                 (15.0, 60.0),
    "o1-mini":            (3.0, 12.0),
}


def _lookup_pricing(provider: str, model: str) -> tuple[float, float]:
    """Return (in_per_token_usd, out_per_token_usd).

    Exact model match first, then progressively shorter prefix match
    (claude-opus-4-7 → claude-opus-4 → claude-opus). Ollama / unknown
    providers are free.
    """
    if provider == "ollama":
        return (0.0, 0.0)

    norm = model.lower().strip()
    # Exact
    if norm in _PRICING_PER_MILLION:
        in_per_m, out_per_m = _PRICING_PER_MILLION[norm]
        return (in_per_m / 1_000_000, out_per_m / 1_000_000)
    # Prefix search, longest first
    matches = [k for k in _PRICING_PER_MILLION if norm.startswith(k)]
    if matches:
        matches.sort(key=len, reverse=True)
        in_per_m, out_per_m = _PRICING_PER_MILLION[matches[0]]
        return (in_per_m / 1_000_000, out_per_m / 1_000_000)
    return (0.0, 0.0)


def estimate_tokens_from_chars(chars: int) -> int:
    """Rough fallback when no native count is available.

    Uses 4 chars ≈ 1 token, a well-known approximation for English/French
    that's within ~20% of Claude's real tokenizer on typical prose.
    """
    if chars <= 0:
        return 0
    return max(1, chars // 4)


# ── Data holders ─────────────────────────────────────────────────


@dataclass
class QuotaCounters:
    """In-RAM totals for a single scope (role or project)."""
    day_key: str = ""           # YYYY-MM-DD
    month_key: str = ""         # YYYY-MM
    tokens_day: int = 0
    tokens_month: int = 0
    calls_day: int = 0
    calls_month: int = 0
    cost_usd_day: float = 0.0
    cost_usd_month: float = 0.0

    def roll(self, today: date) -> None:
        """Zero the day totals when the date flips; month on month flip."""
        dk = today.isoformat()
        mk = f"{today.year:04d}-{today.month:02d}"
        if dk != self.day_key:
            self.day_key = dk
            self.tokens_day = 0
            self.calls_day = 0
            self.cost_usd_day = 0.0
        if mk != self.month_key:
            self.month_key = mk
            self.tokens_month = 0
            self.calls_month = 0
            self.cost_usd_month = 0.0

    def add(self, tokens: int, cost: float) -> None:
        self.tokens_day += tokens
        self.tokens_month += tokens
        self.cost_usd_day += cost
        self.cost_usd_month += cost
        self.calls_day += 1
        self.calls_month += 1


@dataclass
class QuotaSnapshot:
    """Serializable view of the tracker for the API endpoint."""
    today: str
    month: str
    roles: dict = field(default_factory=dict)
    projects: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)


# ── Tracker singleton ────────────────────────────────────────────


class QuotaTracker:
    """Thread-safe in-RAM tracker with DB persistence."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._roles: dict[str, QuotaCounters] = {}
        self._projects: dict[int, QuotaCounters] = {}
        self._global = QuotaCounters()
        self._hydrated = False

    # -- Limit lookups (read from settings each call so env changes bite) --

    def _global_daily_limit(self) -> int:
        from configs.service import config_service
        return int(config_service.get("ai.quota.daily_tokens", default=0) or 0)

    def _global_monthly_limit(self) -> int:
        from configs.service import config_service
        return int(config_service.get("ai.quota.monthly_tokens", default=0) or 0)

    def _role_daily_limit(self, role: str) -> int:
        # Env var form: AI_QUOTA_ROLE_<ROLE_UPPER>_DAILY
        key = f"AI_QUOTA_ROLE_{role.upper()}_DAILY"
        return int(getattr(settings, key, 0) or 0)

    def _role_monthly_limit(self, role: str) -> int:
        key = f"AI_QUOTA_ROLE_{role.upper()}_MONTHLY"
        return int(getattr(settings, key, 0) or 0)

    def _project_monthly_limit(self, project_id: int) -> int:
        """Read from the Project model, 0 means unlimited."""
        try:
            from projects.models import Project
            p = Project.objects.only("monthly_token_budget").filter(pk=project_id).first()
            if p is None:
                return 0
            return int(getattr(p, "monthly_token_budget", 0) or 0)
        except Exception:
            logger.debug("project limit lookup failed for %s", project_id, exc_info=True)
            return 0

    # -- Counter helpers ----------------------------------------------

    def _get_role(self, role: str) -> QuotaCounters:
        c = self._roles.get(role)
        if c is None:
            c = QuotaCounters()
            self._roles[role] = c
        return c

    def _get_project(self, project_id: int) -> QuotaCounters:
        c = self._projects.get(project_id)
        if c is None:
            c = QuotaCounters()
            self._projects[project_id] = c
        return c

    def _today(self) -> date:
        return timezone.localdate()

    # -- Public API ---------------------------------------------------

    def check(self, role: str, project_id: Optional[int] = None,
              expected_tokens: int = 0) -> None:
        """Raise QuotaExceeded if the next call (rough cost `expected_tokens`)
        would push a limiter past its cap.

        Pass a positive ``expected_tokens`` estimate (e.g. prompt length
        in tokens) to avoid overshoot — we'll refuse a call that would
        exceed the cap *during* processing, not after.
        """
        with self._lock:
            today = self._today()
            self._global.roll(today)
            role_ctr = self._get_role(role)
            role_ctr.roll(today)

            # Global caps
            gd = self._global_daily_limit()
            if gd and self._global.tokens_day + expected_tokens > gd:
                raise QuotaExceeded(
                    "global:daily", self._global.tokens_day, gd,
                    f"role={role}",
                )
            gm = self._global_monthly_limit()
            if gm and self._global.tokens_month + expected_tokens > gm:
                raise QuotaExceeded(
                    "global:monthly", self._global.tokens_month, gm,
                    f"role={role}",
                )

            # Per-role caps
            rd = self._role_daily_limit(role)
            if rd and role_ctr.tokens_day + expected_tokens > rd:
                raise QuotaExceeded(
                    f"role:{role}:daily", role_ctr.tokens_day, rd,
                )
            rm = self._role_monthly_limit(role)
            if rm and role_ctr.tokens_month + expected_tokens > rm:
                raise QuotaExceeded(
                    f"role:{role}:monthly", role_ctr.tokens_month, rm,
                )

            # Per-project caps
            if project_id is not None:
                proj_ctr = self._get_project(project_id)
                proj_ctr.roll(today)
                pm = self._project_monthly_limit(project_id)
                if pm and proj_ctr.tokens_month + expected_tokens > pm:
                    raise QuotaExceeded(
                        f"project:{project_id}:monthly",
                        proj_ctr.tokens_month, pm,
                    )

    def record(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        project_id: Optional[int] = None,
    ) -> float:
        """Bump counters + persist to DB. Returns the computed USD cost."""
        total = max(0, int(tokens_in)) + max(0, int(tokens_out))
        in_rate, out_rate = _lookup_pricing(provider, model)
        cost = tokens_in * in_rate + tokens_out * out_rate

        with self._lock:
            today = self._today()
            self._global.roll(today)
            self._global.add(total, cost)

            role_ctr = self._get_role(role)
            role_ctr.roll(today)
            role_ctr.add(total, cost)

            if project_id is not None:
                proj_ctr = self._get_project(project_id)
                proj_ctr.roll(today)
                proj_ctr.add(total, cost)

        # DB persistence — best-effort, never fail an LLM call because of it
        try:
            self._persist(
                role=role,
                provider=provider,
                model=model,
                project_id=project_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                today=today,
            )
        except Exception:
            logger.debug("Quota DB persistence failed", exc_info=True)

        return cost

    def _persist(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        project_id: Optional[int],
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        today: date,
    ) -> None:
        from ai.models import AIQuotaUsage
        from django.db.models import F

        obj, created = AIQuotaUsage.objects.get_or_create(
            role=role,
            project_id=project_id,
            date=today,
            provider=provider,
            model=model,
        )
        if created:
            obj.call_count = 1
            obj.tokens_in = tokens_in
            obj.tokens_out = tokens_out
            obj.cost_usd = cost_usd
            obj.save()
        else:
            # Atomic increments to survive concurrent writes.
            AIQuotaUsage.objects.filter(pk=obj.pk).update(
                call_count=F("call_count") + 1,
                tokens_in=F("tokens_in") + tokens_in,
                tokens_out=F("tokens_out") + tokens_out,
                cost_usd=F("cost_usd") + cost_usd,
            )

    def hydrate(self) -> None:
        """Re-populate in-RAM counters from DB for the current day+month.

        Idempotent and safe to call multiple times — resets RAM counters
        first so retries don't double-count.
        """
        with self._lock:
            if self._hydrated:
                return
            try:
                from ai.models import AIQuotaUsage
            except Exception:
                return
            today = self._today()
            first_of_month = today.replace(day=1)
            # Reset
            self._roles.clear()
            self._projects.clear()
            self._global = QuotaCounters()
            # Month totals
            try:
                rows = list(
                    AIQuotaUsage.objects.filter(date__gte=first_of_month)
                )
            except Exception:
                logger.debug("quota hydrate: DB read failed", exc_info=True)
                self._hydrated = True
                return

            for row in rows:
                total = (row.tokens_in or 0) + (row.tokens_out or 0)
                self._global.roll(today)
                self._global.tokens_month += total
                self._global.calls_month += row.call_count
                self._global.cost_usd_month += row.cost_usd

                role_ctr = self._get_role(row.role)
                role_ctr.roll(today)
                role_ctr.tokens_month += total
                role_ctr.calls_month += row.call_count
                role_ctr.cost_usd_month += row.cost_usd

                if row.project_id is not None:
                    proj_ctr = self._get_project(row.project_id)
                    proj_ctr.roll(today)
                    proj_ctr.tokens_month += total
                    proj_ctr.calls_month += row.call_count
                    proj_ctr.cost_usd_month += row.cost_usd

                if row.date == today:
                    self._global.tokens_day += total
                    self._global.calls_day += row.call_count
                    self._global.cost_usd_day += row.cost_usd
                    role_ctr.tokens_day += total
                    role_ctr.calls_day += row.call_count
                    role_ctr.cost_usd_day += row.cost_usd
                    if row.project_id is not None:
                        self._projects[row.project_id].tokens_day += total
                        self._projects[row.project_id].calls_day += row.call_count
                        self._projects[row.project_id].cost_usd_day += row.cost_usd

            self._hydrated = True
            logger.info(
                "Quota tracker hydrated: %d roles, %d projects, "
                "%d tokens today / %d this month",
                len(self._roles), len(self._projects),
                self._global.tokens_day, self._global.tokens_month,
            )

    def snapshot(self) -> QuotaSnapshot:
        """Read-only view for the HTTP endpoint."""
        with self._lock:
            today = self._today()
            self._global.roll(today)
            for c in self._roles.values():
                c.roll(today)
            for c in self._projects.values():
                c.roll(today)

            roles_out = {
                role: {
                    "tokens_day": c.tokens_day,
                    "tokens_month": c.tokens_month,
                    "calls_day": c.calls_day,
                    "calls_month": c.calls_month,
                    "cost_usd_day": round(c.cost_usd_day, 6),
                    "cost_usd_month": round(c.cost_usd_month, 6),
                    "limit_daily": self._role_daily_limit(role),
                    "limit_monthly": self._role_monthly_limit(role),
                }
                for role, c in sorted(self._roles.items())
            }
            projects_out = {}
            for pid, c in sorted(self._projects.items()):
                projects_out[str(pid)] = {
                    "tokens_day": c.tokens_day,
                    "tokens_month": c.tokens_month,
                    "calls_day": c.calls_day,
                    "calls_month": c.calls_month,
                    "cost_usd_day": round(c.cost_usd_day, 6),
                    "cost_usd_month": round(c.cost_usd_month, 6),
                    "limit_monthly": self._project_monthly_limit(pid),
                }
            return QuotaSnapshot(
                today=today.isoformat(),
                month=f"{today.year:04d}-{today.month:02d}",
                roles=roles_out,
                projects=projects_out,
                limits={
                    "global_daily": self._global_daily_limit(),
                    "global_monthly": self._global_monthly_limit(),
                },
            )

    # -- Test helpers ------------------------------------------------

    def reset(self) -> None:
        """Wipe in-RAM state. Used by tests between cases."""
        with self._lock:
            self._roles.clear()
            self._projects.clear()
            self._global = QuotaCounters()
            self._hydrated = False


quota_tracker = QuotaTracker()
