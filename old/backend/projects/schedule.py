"""Schedule rule parser + evaluator for Project.schedule_rule.

Supported rules (all examples tested):
    ""                        no schedule — manual advance only
    "interval:5m"             every 5 minutes (units: s / m / h / d)
    "interval:30s"            every 30 seconds
    "cron:0 9 * * MON-FRI"    cron expression — uses croniter if available,
                              else falls back to a minimal 5-field parser
                              (lists, ranges, steps, day/month names, cron
                              day-of-week numbering: Sunday = 0 or 7)
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
    """Return next cron fire time after ``now``. Uses croniter if installed
    (it is pinned in requirements.txt), otherwise the fallback below."""
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


# Numérotation CRON, pas Python : dimanche = 0 (ou 7), lundi = 1 … samedi = 6.
_DOW_NOMS = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
_MOIS_NOMS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _valeurs_du_champ(
    field: str, lo: int, hi: int, noms: dict[str, int] | None = None,
) -> set[int]:
    """Développe un champ cron en ensemble d'entiers de ``[lo, hi]``.

    Formes : ``*``, ``*/n``, ``a``, ``a-b``, ``a-b/n``, listes à virgules,
    noms de jours ou de mois. Lève ``ValueError`` sur une forme illisible :
    l'appelant en fait un avertissement et ``None``, jamais une échéance
    fausse.
    """
    noms = noms or {}

    def _entier(s: str) -> int:
        s = s.strip().upper()
        if s in noms:
            return noms[s]
        n = int(s)
        if not (lo <= n <= hi):
            raise ValueError(f"{n} hors de [{lo}, {hi}]")
        return n

    valeurs: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("segment vide")
        pas = 1
        plage = part
        if "/" in part:
            plage, pas_s = part.split("/", 1)
            pas = int(pas_s)
            if pas < 1:
                raise ValueError(f"pas invalide : {pas_s}")
        if plage == "*":
            debut, fin = lo, hi
        elif "-" in plage:
            a, b = plage.split("-", 1)
            debut, fin = _entier(a), _entier(b)
            if fin < debut:
                raise ValueError(f"plage inversée : {plage}")
        else:
            debut = _entier(plage)
            # ``a/n`` sans plage : cron le lit « de a jusqu'au maximum ».
            fin = hi if "/" in part else debut
        valeurs.update(range(debut, fin + 1, pas))
    return valeurs


def _fallback_cron_next(expr: str, now: datetime) -> Optional[datetime]:
    """Analyseur cron minimal — ``minute heure jour mois jour_semaine``.

    Utilisé seulement quand croniter manque. Il portait deux défauts que
    croniter masquait sur toute installation qui l'avait : le jour de la
    semaine était lu en numérotation Python (lundi = 0) alors que cron
    compte dimanche = 0 — ``0 9 * * 0`` tombait le lundi, ``1-5`` couvrait
    mardi-samedi et ``7`` ne tombait jamais ; et un pas (``*/5``) ou une
    plage sur un autre champ que le jour rendait ``None``, c'est-à-dire un
    ``next_run_at`` vide pour toujours, sans un mot.

    Numérotation cron partout, convertie vers ``weekday()`` à la comparaison.
    Jour du mois et jour de la semaine se combinent comme dans Vixie cron et
    croniter : en OU quand les deux sont restreints, en ET sinon.
    """
    fields = expr.split()
    if len(fields) != 5:
        logger.warning("Fallback cron needs 5 fields, got %r", expr)
        return None
    minute_f, hour_f, dom_f, month_f, dow_f = fields

    try:
        minutes = _valeurs_du_champ(minute_f, 0, 59)
        heures = _valeurs_du_champ(hour_f, 0, 23)
        jours = _valeurs_du_champ(dom_f, 1, 31)
        mois = _valeurs_du_champ(month_f, 1, 12, _MOIS_NOMS)
        # cron : dimanche = 0 ou 7, lundi = 1 … ; Python : lundi = 0 … dimanche = 6
        jours_semaine = {
            (n + 6) % 7 for n in _valeurs_du_champ(dow_f, 0, 7, _DOW_NOMS)
        }
    except ValueError as exc:
        logger.warning("Invalid cron expression %r (fallback parser): %s", expr, exc)
        return None

    # Vixie : un champ qui commence par ``*`` est « non restreint », même ``*/2``.
    dom_restreint = not dom_f.startswith("*")
    dow_restreint = not dow_f.startswith("*")

    def _jour_ok(c: datetime) -> bool:
        ok_dom, ok_dow = c.day in jours, c.weekday() in jours_semaine
        if dom_restreint and dow_restreint:
            return ok_dom or ok_dow
        return ok_dom and ok_dow

    # Recherche jusqu'à un an : ``0 0 29 2 *`` tombe rarement, mais tombe.
    # Sauter au jour ou à l'heure suivants quand ils ne conviennent pas garde
    # la boucle courte — quelques centaines d'itérations au pire.
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = now + timedelta(days=366)
    while candidate <= end:
        if candidate.month not in mois or not _jour_ok(candidate):
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if candidate.hour not in heures:
            candidate = (candidate + timedelta(hours=1)).replace(minute=0)
            continue
        if candidate.minute in minutes:
            return candidate
        candidate += timedelta(minutes=1)
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
        # Respect next_run_at (bumped after each advance): once the idle
        # window is reached, fire at most once per window instead of on
        # every runner tick for as long as Mika stays idle.
        if project.next_run_at and project.next_run_at > now:
            return False
        try:
            from old.backend.conscience.engine import conscience_engine
            idle = conscience_engine.get_idle_seconds()
        except Exception:
            idle = 0.0
        return idle >= float(parsed.value)  # type: ignore[arg-type]

    if parsed.kind == "event":
        # Event matches tag next_run_at manually (see runner.notify_event).
        # Here we just obey the timestamp.
        return bool(project.next_run_at and project.next_run_at <= now)

    return False
