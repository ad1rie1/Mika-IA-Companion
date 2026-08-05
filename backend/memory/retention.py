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
failure never blocks the others. Une passe ne fait pas que supprimer : elle
perime aussi les revendications d'identite laissees sans decision, seule
categorie de ligne « en attente » que rien d'autre ne vient jamais fermer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone
from utils.degradation import degradations

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
    # One handle (and one Identity) per anonymous socket. The frontend
    # reconnects on backoff, so these accumulate on their own: an install
    # with zero messages had already collected 68 of them. Only the
    # ephemeral ones are swept — a handle Mika can actually reach someone
    # on is exactly what the identity layer is for.
    Policy("identity", "IdentityHandle", date_field="last_seen", keep_days=7,
           protect={"is_ephemeral": False},
           note="anonymous per-connection handles"),
    # Resolved claims are the identity ledger. Kept long enough to explain a
    # binding, not forever. Les revendications en attente restent protegees
    # de la suppression — elles attendent le jugement de Mika — mais plus
    # inconditionnellement : `_expire_pending_claims` les perime au-dela de
    # PENDING_CLAIM_TTL_DAYS, apres quoi elles retombent sous cette regle.
    Policy("identity", "IdentityClaim", keep_days=180, keep_rows=10_000,
           protect={"status": "pending"},
           note="identity evidence ledger"),
)


async def run_sweep() -> dict[str, int]:
    """Apply every policy. Returns {label: rows_touched} for what it changed."""
    deleted: dict[str, int] = {}

    # Avant les suppressions : une revendication perimee ici et deja hors
    # fenetre repart dans la meme passe, plutot que d'attendre la suivante.
    try:
        expired = await _expire_pending_claims()
    except Exception as exc:
        degradations.record("memory.retention.run_sweep", exc)
        logger.debug("Pending identity claim expiry failed", exc_info=True)
    else:
        if expired:
            deleted["identity.IdentityClaim (perimees)"] = expired

    for policy in POLICIES:
        try:
            count = await _sweep_one(policy)
        except Exception as exc:
            # A missing app/model or a locked table must not break the tick.
            degradations.record("memory.retention.run_sweep", exc)
            logger.debug("Retention sweep failed for %s.%s",
                         policy.app_label, policy.model_name, exc_info=True)
            continue
        if count:
            deleted[f"{policy.app_label}.{policy.model_name}"] = count

    try:
        orphans = await _sweep_orphan_identities()
    except Exception as exc:
        degradations.record("memory.retention.run_sweep", exc)
        logger.debug("Orphan identity sweep failed", exc_info=True)
    else:
        if orphans:
            deleted["identity.Identity"] = orphans

    if deleted:
        logger.info("Retention sweep touched %s", deleted)
    return deleted


async def _expire_pending_claims() -> int:
    """Perime les revendications d'identite laissees sans decision.

    Une ``IdentityClaim`` en attente n'avait aucun chemin de sortie
    automatique : seule une decision de Mika la retirait, alors que le bloc
    de prompt lui dit precisement que rien ne l'oblige a trancher. Chaque
    revendication trainante — et le detecteur passif en produit de fausses
    par construction — repartait donc dans le prompt a chaque tour.

    Le passage en ``rejected`` ne touche pas a la certitude : une
    revendication en attente n'a jamais ete comptee, donc l'abandonner ne
    retire rien. Elle reste dans le registre avec la raison de sa sortie,
    puis retombe sous la politique des 180 jours.
    """
    from django.apps import apps

    from identity.trust import PENDING_CLAIM_TTL_DAYS

    IdentityClaim = apps.get_model("identity", "IdentityClaim")

    def _expire() -> int:
        cutoff = timezone.now() - timedelta(days=PENDING_CLAIM_TTL_DAYS)
        ids = list(
            IdentityClaim.objects.filter(
                status=IdentityClaim.Status.PENDING,
                created_at__lt=cutoff,
            ).values_list("pk", flat=True)[:10_000]
        )
        if not ids:
            return 0
        return IdentityClaim.objects.filter(pk__in=ids).update(
            status=IdentityClaim.Status.REJECTED,
            resolution_note="expiree sans decision",
            resolved_at=timezone.now(),
        )

    return await sync_to_async(_expire)()


async def _sweep_orphan_identities() -> int:
    """Drop Identities left with no handles and nobody behind them.

    Deleting an ephemeral handle doesn't cascade upward — the FK points the
    other way — so sweeping handles alone would trade one orphan table for
    another. An Identity is only removed when it has no remaining handle AND
    no memory entity AND no claim worth keeping: at that point it is a row
    that represents a socket somebody once opened.
    """
    from django.apps import apps

    Identity = apps.get_model("identity", "Identity")

    def _delete() -> int:
        ids = list(
            Identity.objects.filter(
                handles__isnull=True, entity__isnull=True,
            )
            .exclude(claims__status="pending")
            .values_list("pk", flat=True)[:10_000]
        )
        if not ids:
            return 0
        return Identity.objects.filter(pk__in=ids).delete()[0]

    return await sync_to_async(_delete)()


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
