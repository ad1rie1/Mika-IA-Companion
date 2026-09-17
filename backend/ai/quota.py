"""AI quota tracking + limiter.

Every call routed through ``ai.router.AIRouter`` (``complete``, ``chat`` as
well as ``chat_with_tools``) is metered:
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
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.conf import settings
from django.utils import timezone
from utils.degradation import degradations

logger = logging.getLogger(__name__)


# ── Async-context safety ─────────────────────────────────────────
#
# ``check()`` and ``record()`` are called from ``AIRouter.complete``,
# which is a coroutine: every one of their ORM touches ran on the ASGI
# loop thread, where Django refuses them (``SynchronousOnlyOperation``).
# Both were wrapped in ``except Exception`` — so the failure was silent
# and the *feature* was silently absent:
#
#   - ``_persist`` never wrote a row outside tests, so ``AIQuotaUsage``
#     stayed empty and ``hydrate()`` re-populated nothing on restart:
#     every process boot started the month at zero.
#   - ``_project_monthly_limit`` fell into its handler and returned 0,
#     which means *unlimited* — a project's ``monthly_token_budget``
#     could never fire.
#
# The read is handed to the shared config worker and waited on (one
# indexed row on a WAL database, microseconds — and ``check`` must
# decide *before* the call). The write goes to its own single worker and
# is **not** waited on: it is a write, it contends with six background
# loops, and blocking the loop for up to ``DB_LOCK_TIMEOUT`` to bookkeep
# a call that already happened is a far worse trade than a late row.
# A single worker also keeps concurrent get_or_create/UPDATE pairs on
# the same row serialised.
_write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quota-db")


# ── Context variables ────────────────────────────────────────────

# Set by ProjectRunner (and any other project-scoped caller) to attribute
# a call to a project's budget. Cleared after the call.
current_project_id: ContextVar[Optional[int]] = ContextVar(
    "ai_quota_project_id", default=None,
)

# Optional per-call usage set by providers that know their token counts.
# Layout: {"in": int, "out": int} plus, only when non-zero, "cache_read" and
# "cache_write" (only Claude ever posts them). Opened fresh by the router
# before each call (``_reset_usage``), closed after (``_restore_usage``).
_usage_ctx: ContextVar[Optional[dict]] = ContextVar(
    "ai_quota_usage_ctx", default=None,
)


def set_usage(
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """Providers call this right after the API round-trip to hand real
    token counts to the router. No-op when not running under the router.

    Les compteurs se **cumulent** : une boucle d'outils appelle le provider
    une fois par tour, et écraser à chaque tour ne facturerait que le dernier
    — soit une fraction du poste le plus lourd du système. Le routeur ouvre
    une fenêtre vierge avant chaque appel (``_reset_usage``), donc un appel
    simple retrouve exactement ses propres chiffres.

    Les jetons de cache voyagent à part : ce sont des jetons consommés — ils
    comptent dans le quota — mais ils ne se paient pas au tarif d'entrée
    plein (0,1× en lecture, 1,25× en écriture), et les fondre dans ``in``
    facturait dix fois son prix la lecture du préfixe en cache, c'est-à-dire
    l'essentiel de chaque tour outillé.
    """
    try:
        current = _usage_ctx.get() or {}
        merged = {
            "in": int(current.get("in", 0)) + int(input_tokens),
            "out": int(current.get("out", 0)) + int(output_tokens),
        }
        # Les clés de cache n'apparaissent que portées : le relevé d'un
        # provider sans cache garde la forme à deux clés qu'il a toujours eue.
        cache_read = int(current.get("cache_read", 0)) + int(cache_read_tokens)
        cache_write = int(current.get("cache_write", 0)) + int(cache_write_tokens)
        if cache_read:
            merged["cache_read"] = cache_read
        if cache_write:
            merged["cache_write"] = cache_write
        _usage_ctx.set(merged)
    except Exception as exc:
        degradations.record("ai.quota.set_usage", exc)


def _reset_usage():
    """Ouvre la fenêtre de relevé d'un appel routé ; renvoie le jeton qui
    la referme (``_restore_usage``).

    Une *fenêtre*, pas une remise à zéro : un outil MCP peut relancer le
    routeur depuis l'intérieur d'une boucle d'outils (``files_analyze_image``
    décrit une image pendant que la conversation attend), et une remise à
    zéro plate effaçait l'usage que la boucle englobante avait déjà cumulé
    itération par itération — le tour ne facturait plus que ce qui suivait
    l'outil.
    """
    return _usage_ctx.set(None)


def _restore_usage(token) -> None:
    """Referme la fenêtre ouverte par ``_reset_usage`` : le relevé de
    l'appel englobant, s'il y en a un, redevient visible tel qu'il était.
    Tolère ``None`` (fenêtre jamais ouverte) et ne lève jamais."""
    if token is None:
        return
    try:
        _usage_ctx.reset(token)
    except (ValueError, RuntimeError) as exc:
        degradations.record("ai.quota._restore_usage", exc)


def _take_usage() -> Optional[dict]:
    value = _usage_ctx.get()
    _usage_ctx.set(None)
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

# Sources : tarifs Anthropic relevés via le skill ``claude-api`` (cache du
# 2026-06-24), lignes OpenAI inchangées. Par million de jetons, (entrée,
# sortie), converti au jeton dans ``_lookup_pricing``. Un id absent retombe
# sur la famille par préfixe le plus long ; une famille absente vaut $0 —
# et, chez un provider *payant*, se dit une fois à voix haute
# (``_warn_unpriced``) : un $0 muet est indiscernable d'un modèle local, et
# c'est ainsi que Fable, Mythos et toute la série 5 ont tourné « gratuits »
# sur le tableau de bord.
_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    # Fable / Mythos — même palier, même tarif au jeton
    "claude-fable":       (10.0, 50.0),
    "claude-fable-5":     (10.0, 50.0),
    "claude-fable-5-1":   (10.0, 50.0),
    "claude-mythos":      (10.0, 50.0),
    "claude-mythos-5":    (10.0, 50.0),
    "claude-mythos-5-1":  (10.0, 50.0),
    # Opus — $5/$25 depuis 4.6 (et Opus 5) ; 4.0/4.1, dépréciés, gardent
    # l'ancien tarif tant qu'ils répondent.
    "claude-opus":        (5.0, 25.0),
    "claude-opus-5":      (5.0, 25.0),
    "claude-opus-4":      (5.0, 25.0),
    "claude-opus-4-0":    (15.0, 75.0),
    "claude-opus-4-1":    (15.0, 75.0),
    "claude-opus-4-6":    (5.0, 25.0),
    "claude-opus-4-7":    (5.0, 25.0),
    "claude-opus-4-8":    (5.0, 25.0),
    # Sonnet — 5 à $2/$10, la génération 4.x à $3/$15
    "claude-sonnet":      (2.0, 10.0),
    "claude-sonnet-5":    (2.0, 10.0),
    "claude-sonnet-4":    (3.0, 15.0),
    "claude-sonnet-4-5":  (3.0, 15.0),
    "claude-sonnet-4-6":  (3.0, 15.0),
    # Haiku
    "claude-haiku":       (1.0, 5.0),
    "claude-haiku-4":     (1.0, 5.0),
    "claude-haiku-4-5":   (1.0, 5.0),
    # OpenAI
    "gpt-4o":             (2.5, 10.0),
    "gpt-4o-mini":        (0.15, 0.6),
    "gpt-4.1":            (2.0, 8.0),
    "gpt-4.1-mini":       (0.4, 1.6),
    "gpt-4.1-nano":       (0.1, 0.4),
    "o1":                 (15.0, 60.0),
    "o1-mini":            (3.0, 12.0),
}

# Jetons de cache (Claude) : la lecture se paie 0,1× le tarif d'entrée,
# l'écriture 1,25× (TTL de 5 min — le TTL d'une heure écrit à 2×, mais le
# provider ne le demande jamais). Exception publiée : Claude Fable 5.1 lit
# son cache à $0,25/M, soit 0,025× ; Mythos 5.1 n'était pas confirmé au
# lancement et reste au taux général.
_CACHE_READ_MULTIPLIER = 0.1
_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_READ_PER_MILLION_OVERRIDES: dict[str, float] = {
    "claude-fable-5-1": 0.25,
}

# (provider, modèle) déjà signalés sans tarif — un avertissement par paire et
# par processus, pas un par appel.
_unpriced_warned: set[tuple[str, str]] = set()


def _match_family(table: dict, norm: str) -> Optional[str]:
    """Clé exacte, sinon le préfixe le plus long (claude-opus-4-7 →
    claude-opus-4 → claude-opus) ; None quand rien ne correspond."""
    if norm in table:
        return norm
    matches = [k for k in table if norm.startswith(k)]
    if not matches:
        return None
    return max(matches, key=len)


def _warn_unpriced(provider: str, norm: str) -> None:
    key = (provider, norm)
    if key in _unpriced_warned:
        return
    _unpriced_warned.add(key)
    logger.warning(
        "Aucun tarif connu pour %s/%s — facturé $0 sur le tableau de bord ; "
        "les compteurs de jetons, eux, restent exacts. Ajouter une ligne dans "
        "ai/quota.py::_PRICING_PER_MILLION.",
        provider, norm,
    )


def _lookup_pricing(provider: str, model: str) -> tuple[float, float]:
    """Return (in_per_token_usd, out_per_token_usd).

    Exact model match first, then progressively shorter prefix match
    (claude-opus-4-7 → claude-opus-4 → claude-opus). Ollama / unknown
    providers are free — but an unknown model at a *paid* provider is said
    out loud, once.

    Both Ollama variants are $0-per-token: local costs electricity, and the
    hosted one is billed by subscription, not by usage. The token *counters*
    still run — they are what a quota is made of — only the USD column is
    zero. Matched on the prefix so a future ``ollama_*`` variant cannot
    silently fall through to the pricing table.
    """
    if provider.startswith("ollama"):
        return (0.0, 0.0)

    norm = model.lower().strip()
    key = _match_family(_PRICING_PER_MILLION, norm)
    if key is None:
        _warn_unpriced(provider, norm)
        return (0.0, 0.0)
    in_per_m, out_per_m = _PRICING_PER_MILLION[key]
    return (in_per_m / 1_000_000, out_per_m / 1_000_000)


def _lookup_cache_pricing(provider: str, model: str) -> tuple[float, float]:
    """Return (cache_read_per_token_usd, cache_write_per_token_usd).

    Dérivé du tarif d'entrée du modèle — un modèle gratuit ou inconnu a un
    cache gratuit — sauf pour les lectures dont le tarif est publié à part.
    """
    in_rate, _ = _lookup_pricing(provider, model)
    if in_rate == 0.0:
        return (0.0, 0.0)
    norm = model.lower().strip()
    key = _match_family(_CACHE_READ_PER_MILLION_OVERRIDES, norm)
    if key is not None:
        read_rate = _CACHE_READ_PER_MILLION_OVERRIDES[key] / 1_000_000
    else:
        read_rate = in_rate * _CACHE_READ_MULTIPLIER
    return (read_rate, in_rate * _CACHE_WRITE_MULTIPLIER)


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
        self._pending: set[Future] = set()

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
        """Read from the Project model, 0 means unlimited.

        Goes through ``db_read`` so it works from the ASGI loop as well as
        from a sync view — otherwise the handler below turns every budget
        into "unlimited" the moment the caller is a coroutine.
        """
        try:
            from configs.service import db_read
            from projects.models import Project

            def _fetch():
                return (
                    Project.objects.only("monthly_token_budget")
                    .filter(pk=project_id)
                    .first()
                )

            p = db_read(_fetch)
            if p is None:
                return 0
            return int(getattr(p, "monthly_token_budget", 0) or 0)
        except Exception as exc:
            degradations.record("ai.quota._project_monthly_limit", exc)
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
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Bump counters + persist to DB. Returns the computed USD cost.

        Les jetons de cache comptent dans le quota comme n'importe quel jeton
        consommé, chacun à son tarif. En base ils sont fondus dans
        ``tokens_in`` — la table n'a pas de colonne pour eux, et le coût, lui,
        est exact — de sorte qu'un total relu à l'hydratation vaut celui
        compté ici.
        """
        tokens_in = max(0, int(tokens_in))
        tokens_out = max(0, int(tokens_out))
        cache_read = max(0, int(cache_read_tokens))
        cache_write = max(0, int(cache_write_tokens))
        total = tokens_in + tokens_out + cache_read + cache_write
        in_rate, out_rate = _lookup_pricing(provider, model)
        read_rate, write_rate = _lookup_cache_pricing(provider, model)
        cost = (
            tokens_in * in_rate
            + tokens_out * out_rate
            + cache_read * read_rate
            + cache_write * write_rate
        )

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
        self._dispatch_persist(
            role=role,
            provider=provider,
            model=model,
            project_id=project_id,
            tokens_in=tokens_in + cache_read + cache_write,
            tokens_out=tokens_out,
            cost_usd=cost,
            today=today,
        )

        return cost

    def _dispatch_persist(self, **kwargs) -> None:
        """Persist inline from a sync caller, off-loop from an async one.

        Fire-and-forget in the async case: the counters that matter for
        limiting are already updated in RAM, and this row is bookkeeping.
        """
        from configs.service import in_async_context

        if not in_async_context():
            try:
                self._persist(**kwargs)
            except Exception as exc:
                degradations.record("ai.quota.persist_inline", exc)
                logger.debug("Quota DB persistence failed", exc_info=True)
            return

        def _call():
            from django.db import close_old_connections
            close_old_connections()
            self._persist(**kwargs)

        try:
            future = _write_pool.submit(_call)
        except Exception as exc:          # pool shut down (interpreter exit)
            degradations.record("ai.quota.persist_submit", exc)
            return

        self._pending.add(future)
        future.add_done_callback(self._on_persisted)

    def _on_persisted(self, future: Future) -> None:
        self._pending.discard(future)
        try:
            # Nothing awaits this future — without reading it here the
            # failure would stay inside the executor and surface nowhere.
            future.result()
        except Exception as exc:
            degradations.record("ai.quota.persist_offloop", exc)
            logger.debug("Quota DB persistence failed", exc_info=True)

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for in-flight persistence writes. Used by tests and shutdown."""
        from concurrent.futures import wait
        pending = list(self._pending)
        if pending:
            wait(pending, timeout=timeout)

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
            except Exception as exc:
                degradations.record("ai.quota.hydrate", exc)
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
            except Exception as exc:
                degradations.record("ai.quota.hydrate", exc)
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
        self.flush()
        with self._lock:
            self._roles.clear()
            self._projects.clear()
            self._global = QuotaCounters()
            self._hydrated = False


quota_tracker = QuotaTracker()
