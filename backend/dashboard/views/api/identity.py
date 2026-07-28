"""Dashboard API — the identity layer.

The person fiche (``persons.py``) answers *what does Mika know about
Thomas*: memory ``Entity`` + ``PersonProfile`` + souvenirs. This module
answers the other half, which had no UI at all: *is the person speaking
right now actually Thomas, how sure is she, and what does that certainty
unlock*.

The distinction matters operationally because certainty is not decoration:
``may_disclose_private_context()`` decides whether the person fiche is
injected into the prompt at all. A handle sitting at CLAIMED means Mika
greets them by name and deliberately withholds their history — and until
now nothing in the dashboard could show that, let alone resolve it. A
passive claim is filed ``PENDING`` and only Mika's MCP tools could act on
it; the owner of the install could not see it, accept it, or revoke a
binding that was wrong.

Read:
  GET  /dashboard/api/identity                    identities + handles + certainty
  GET  /dashboard/api/identity/claims             the evidence ledger
  GET  /dashboard/api/identity/policy             calibration constants
  GET  /dashboard/api/identity/<id>               one identity, full ledger

Write — every one delegates to ``identity_resolver``. None of these
recompute a certainty or touch ``Identity.entity`` directly: a second
implementation of the trust arithmetic is exactly how the dashboard and
the prompt would start disagreeing about who someone is.
  POST /dashboard/api/identity/claims/<id>/accept  {reason, evidence_kind}
  POST /dashboard/api/identity/claims/<id>/reject  {reason}
  POST /dashboard/api/identity/<id>/bind           {entity_name}
  POST /dashboard/api/identity/<id>/evidence       {kind, detail, name}
  POST /dashboard/api/identity/<id>/revoke         {reason}
"""
from __future__ import annotations

import json

from asgiref.sync import async_to_sync
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate, pick
from identity import trust as trust_policy
from identity.trust import Certainty, ChannelTrust


def _body(request) -> dict:
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)


def _as_trust(value) -> ChannelTrust:
    """Coerce a stored ``trust`` column into the enum.

    Unknown values fall back to PUBLIC, the same default
    ``trust.channel_trust()`` applies to a transport whose guarantees
    nobody has written down: assume the weakest.
    """
    try:
        return ChannelTrust(str(value or "").strip().lower())
    except ValueError:
        return ChannelTrust.PUBLIC


def _handle_row(h) -> dict:
    return {
        "id": h.pk,
        "person_id": h.person_id,
        "channel": h.channel,
        "kind": h.kind,
        "trust": h.trust,
        "ceiling": round(trust_policy.ceiling_for(_as_trust(h.trust)), 3),
        "is_ephemeral": h.is_ephemeral,
        "delivery_ref": h.delivery_ref,
        "display_name": h.display_name,
        "created_at": iso(h.created_at),
        "last_seen": iso(h.last_seen),
    }


def _best_handle(handles):
    """The handle that affords the most, most recently seen.

    Ranked by the channel *ceiling* rather than a hand-written ordering:
    the ceiling already encodes how much a transport can ever be worth,
    so a second ranking table would only be one more thing to keep in
    sync with ``identity/trust.py``.
    """
    real = [h for h in handles if not h.is_ephemeral] or list(handles)
    if not real:
        return None
    return max(
        real,
        key=lambda h: (
            trust_policy.ceiling_for(_as_trust(h.trust)),
            h.last_seen,
        ),
    )


def _decide(identity, handles):
    """Effective trust + certainty for an identity, as the prompt sees it.

    Mirrors ``IdentityResolver._resolve_context_sync``: the stored
    certainty is raised to the channel floor and clamped by its ceiling.
    Reported for the strongest handle, i.e. the best case — the caveat
    being that a turn happening in a public room is evaluated lower, and
    that is a property of the room, not of the row.
    """
    handle = _best_handle(handles)
    channel_trust = _as_trust(handle.trust) if handle else ChannelTrust.PUBLIC
    stored = float(identity.certainty or 0.0)
    effective = max(stored, trust_policy.floor_for(channel_trust))
    name = (
        (identity.entity.name if identity.entity_id else "")
        or identity.display_name
    )
    return handle, trust_policy.evaluate(effective, channel_trust, name)


def _identity_row(identity, *, decision, handle, pending, total) -> dict:
    entity = identity.entity if identity.entity_id else None
    return {
        "id": identity.pk,
        "display_name": identity.display_name,
        "entity": {"id": entity.pk, "name": entity.name} if entity else None,
        "certainty_stored": round(float(identity.certainty or 0.0), 3),
        "certainty": round(decision.certainty, 3),
        "level": decision.level.name.lower(),
        "trust": decision.trust.value,
        "ceiling": round(trust_policy.ceiling_for(decision.trust), 3),
        "may_disclose": decision.may_disclose,
        "is_confident": decision.is_confident,
        "primary_person_id": handle.person_id if handle else None,
        "primary_channel": handle.channel if handle else "",
        "bound_at": iso(identity.bound_at),
        "bound_via": identity.bound_via,
        "binding_reason": identity.binding_reason,
        "claims_pending": pending,
        "claims_total": total,
        "created_at": iso(identity.created_at),
        "last_seen": iso(identity.last_seen),
    }


def _claim_row(c) -> dict:
    from identity.models import IdentityClaim

    labels = dict(IdentityClaim.Kind.choices)
    identity = c.identity
    known_as = (
        (identity.entity.name if identity.entity_id else "")
        or identity.display_name
    )
    return {
        "id": c.pk,
        "identity_id": c.identity_id,
        "identity_name": known_as,
        "claimed_name": c.claimed_name,
        "kind": c.kind,
        "kind_label": labels.get(c.kind, c.kind),
        "weight": trust_policy.EVIDENCE_WEIGHTS.get(
            c.kind, trust_policy.COUNTER_EVIDENCE_WEIGHTS.get(c.kind, 0.0),
        ),
        "status": c.status,
        "evidence": c.evidence,
        "channel": c.channel,
        "trust": c.trust,
        "ceiling": round(trust_policy.ceiling_for(_as_trust(c.trust)), 3),
        "applied_weight": round(c.applied_weight, 4),
        "resolution_note": c.resolution_note,
        "person_id": c.handle.person_id if c.handle_id else None,
        "created_at": iso(c.created_at),
        "resolved_at": iso(c.resolved_at),
    }


# ── Read ────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def identities(request):
    """Paginated identities, pending claims first.

    ``anon_*`` handles are hidden by default (``include_ephemeral=1``
    to see them): a browser tab that never authenticated is a socket,
    not a returning visitor, and on a busy install they would bury the
    handful of rows that represent someone Mika actually knows.
    """
    from identity.models import Identity, IdentityClaim

    limit, offset = paginate(request, default=25)
    q = pick(request, "q")
    state = pick(request, "state")
    include_ephemeral = request.GET.get("include_ephemeral") == "1"

    qs = (
        Identity.objects
        .select_related("entity")
        .prefetch_related("handles")
        .annotate(
            pending_count=Count(
                "claims",
                filter=Q(claims__status=IdentityClaim.Status.PENDING),
                distinct=True,
            ),
            claims_count=Count("claims", distinct=True),
            handle_count=Count("handles", distinct=True),
            real_handle_count=Count(
                "handles", filter=Q(handles__is_ephemeral=False), distinct=True,
            ),
        )
    )
    if not include_ephemeral:
        # Only drop rows whose handles are *all* ephemeral — an identity
        # with no handle at all is an orphan the retention sweep will
        # collect, and hiding it here would hide the fact that it exists.
        qs = qs.exclude(Q(handle_count__gt=0) & Q(real_handle_count=0))
    if q:
        qs = qs.filter(
            Q(display_name__icontains=q)
            | Q(entity__name__icontains=q)
            | Q(handles__person_id__icontains=q)
        ).distinct()
    if state == "bound":
        qs = qs.filter(entity__isnull=False)
    elif state == "unbound":
        qs = qs.filter(entity__isnull=True)
    elif state == "pending":
        qs = qs.filter(pending_count__gt=0)

    qs = qs.order_by("-pending_count", "-last_seen")
    total = qs.count()

    rows = []
    for identity in qs[offset:offset + limit]:
        handles = list(identity.handles.all())
        handle, decision = _decide(identity, handles)
        row = _identity_row(
            identity, decision=decision, handle=handle,
            pending=identity.pending_count, total=identity.claims_count,
        )
        row["handles"] = [_handle_row(h) for h in handles]
        rows.append(row)

    return JsonResponse({
        "total": total, "limit": limit, "offset": offset, "rows": rows,
        "summary": _summary(),
    })


def _summary() -> dict:
    """Counters for the stat row.

    Scoped to *durable* identities — the same set the table shows by
    default. On a real install the ephemeral rows dominate by an order of
    magnitude (86 sockets against 9 real handles here), so a card reading
    "95 identités" above a table of 9 would be read as a broken filter
    rather than as two different questions.
    """
    from identity.models import Identity, IdentityClaim, IdentityHandle

    all_ids = Identity.objects.annotate(
        handle_count=Count("handles", distinct=True),
        real_handle_count=Count(
            "handles", filter=Q(handles__is_ephemeral=False), distinct=True,
        ),
    )
    ephemeral_only = all_ids.filter(handle_count__gt=0, real_handle_count=0)
    durable = all_ids.exclude(pk__in=ephemeral_only.values("pk"))

    return {
        "identities": durable.count(),
        "identities_ephemeral_only": ephemeral_only.count(),
        "bound": durable.filter(entity__isnull=False).count(),
        "unbound": durable.filter(entity__isnull=True).count(),
        "claims_pending": IdentityClaim.objects.filter(
            status=IdentityClaim.Status.PENDING,
        ).count(),
        "handles": IdentityHandle.objects.filter(is_ephemeral=False).count(),
        "handles_ephemeral": IdentityHandle.objects.filter(
            is_ephemeral=True,
        ).count(),
        # How many identities currently clear the disclosure bar on their
        # best channel — i.e. how many people Mika may recall the history
        # of. The number that matters if this page only shows one.
        "may_disclose": sum(
            1
            for i in durable.select_related("entity").prefetch_related("handles")
            if _decide(i, list(i.handles.all()))[1].may_disclose
        ),
    }


@require_http_methods(["GET"])
def identity_detail(request, identity_id: int):
    """One identity: handles, full claim ledger, and the prompt line.

    ``description`` is the exact sentence ``resolve_context`` hands the
    prompt builder — not a rendering of it. What Mika reads about this
    person is the thing worth showing.
    """
    from identity.models import Identity, IdentityClaim

    identity = (
        Identity.objects
        .select_related("entity")
        .prefetch_related("handles")
        .filter(pk=identity_id)
        .first()
    )
    if identity is None:
        return _error("identity introuvable", status=404)

    handles = list(identity.handles.all())
    handle, decision = _decide(identity, handles)
    claims = list(
        IdentityClaim.objects
        .select_related("identity", "identity__entity", "handle")
        .filter(identity=identity)
        .order_by("-created_at")[:100]
    )
    pending = sum(
        1 for c in claims if c.status == IdentityClaim.Status.PENDING
    )

    row = _identity_row(
        identity, decision=decision, handle=handle,
        pending=pending, total=len(claims),
    )
    row["handles"] = [_handle_row(h) for h in handles]
    row["claims"] = [_claim_row(c) for c in claims]
    row["description"] = decision.description
    return JsonResponse(row)


@require_http_methods(["GET"])
def claims(request):
    """The evidence ledger — every reason to believe, or to stop."""
    from identity.models import IdentityClaim

    limit, offset = paginate(request, default=50)
    status = pick(request, "status")
    qs = IdentityClaim.objects.select_related(
        "identity", "identity__entity", "handle",
    )
    if status:
        qs = qs.filter(status=status)
    # Pending first whatever the filter: a claim nobody resolved is the
    # only row on this page that is waiting on a human.
    qs = qs.annotate(
        _pending_first=Case(
            When(status=IdentityClaim.Status.PENDING, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    ).order_by("_pending_first", "-created_at")
    total = qs.count()
    return JsonResponse({
        "total": total, "limit": limit, "offset": offset,
        "rows": [_claim_row(c) for c in qs[offset:offset + limit]],
        "pending": IdentityClaim.objects.filter(
            status=IdentityClaim.Status.PENDING,
        ).count(),
    })


@require_http_methods(["GET"])
def policy(request):
    """The calibration itself, read off ``identity/trust.py``.

    Every number on this page (0.45 is not enough, 0.70 unlocks a
    history, a public room caps at 0.70 forever) comes from constants
    nobody can see from the UI. Serving them here means the page
    explains its own verdicts instead of asking you to trust them —
    and reading them from the module means the explanation cannot
    drift from the policy that actually runs.
    """
    from identity.models import IdentityClaim

    return JsonResponse({
        "levels": [
            {"name": level.name.lower(), "value": float(level)}
            for level in Certainty
        ],
        "evidence_weights": dict(trust_policy.EVIDENCE_WEIGHTS),
        "counter_evidence_weights": dict(trust_policy.COUNTER_EVIDENCE_WEIGHTS),
        "channels": [
            {
                "trust": t.value,
                "floor": round(trust_policy.floor_for(t), 3),
                "ceiling": round(trust_policy.ceiling_for(t), 3),
            }
            for t in ChannelTrust
        ],
        "thresholds": {
            "confident": trust_policy.CONFIDENT_THRESHOLD,
            "private_context": trust_policy.PRIVATE_CONTEXT_THRESHOLD,
        },
        "kinds": [
            {"value": v, "label": label}
            for v, label in IdentityClaim.Kind.choices
        ],
        "internal_person_ids": sorted(
            p for p in trust_policy.INTERNAL_PERSON_IDS if p
        ),
        "ephemeral_prefix": trust_policy.EPHEMERAL_PERSON_PREFIX,
    })


# ── Write ───────────────────────────────────────────────────────

def _resolver_call(coro_fn, *args, **kwargs) -> JsonResponse:
    """Run one resolver coroutine and map its verdict onto HTTP.

    The resolver answers ``{"ok": False, "error": ...}`` rather than
    raising — it is written for LLM-supplied arguments, where a typo must
    never break a turn. The dashboard is stricter: a refused write has to
    reach the operator as a failure, not as a silent 200.
    """
    try:
        result = async_to_sync(coro_fn)(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim below
        return _error(f"echec: {exc}", status=500)
    if isinstance(result, dict) and not result.get("ok", True):
        return _error(result.get("error", "refuse"), status=400)
    return JsonResponse(result if isinstance(result, dict) else {"ok": True})


def _identity_or_404(identity_id: int):
    from identity.models import Identity

    return (
        Identity.objects
        .select_related("entity")
        .prefetch_related("handles")
        .filter(pk=identity_id)
        .first()
    )


def _person_id_for(identity) -> str | None:
    handle = _best_handle(list(identity.handles.all()))
    return handle.person_id if handle else None


@require_http_methods(["POST"])
def claim_accept(request, claim_id: int):
    from identity.resolver import identity_resolver

    body = _body(request)
    return _resolver_call(
        identity_resolver.accept_claim,
        claim_id,
        reason=str(body.get("reason") or "Accepte depuis le dashboard"),
        evidence_kind=str(body.get("evidence_kind") or ""),
    )


@require_http_methods(["POST"])
def claim_reject(request, claim_id: int):
    from identity.resolver import identity_resolver

    body = _body(request)
    return _resolver_call(
        identity_resolver.reject_claim,
        claim_id,
        reason=str(body.get("reason") or "Rejete depuis le dashboard"),
    )


@require_http_methods(["POST"])
def identity_bind(request, identity_id: int):
    """Bind a handle to a memory Entity with no claim to accept.

    The deliberate path is ``accept_claim``; this covers the case the
    claim flow cannot reach — an identity nobody ever filed a claim for
    (a Telegram contact that only ever said "salut"), or a binding that
    points at the wrong person and has to be re-pointed by hand.
    """
    from identity.resolver import identity_resolver

    identity = _identity_or_404(identity_id)
    if identity is None:
        return _error("identity introuvable", status=404)

    entity_name = str(_body(request).get("entity_name") or "").strip()
    if not entity_name:
        return _error("entity_name requis")

    person_id = _person_id_for(identity)
    if not person_id:
        return _error("cette identite n'a aucun handle a lier")

    result = async_to_sync(identity_resolver.link_entity)(person_id, entity_name)
    if result is None:
        return _error("liaison refusee (handle introuvable)", status=400)
    return JsonResponse({
        "ok": True,
        "entity_name": entity_name,
        "certainty": round(float(result.certainty or 0.0), 3),
        "level": trust_policy.label_for(
            float(result.certainty or 0.0),
        ).name.lower(),
    })


@require_http_methods(["POST"])
def identity_evidence(request, identity_id: int):
    """Record one piece of evidence for or against the current binding.

    This is the lever for the situations accept/reject cannot express:
    they got a shared fact wrong (``contradicted``), someone vouched for
    them (``vouched``), they proved something only that person knows
    (``shared_memory``). Weight and ceiling are applied by the resolver.
    """
    from identity.resolver import identity_resolver

    identity = _identity_or_404(identity_id)
    if identity is None:
        return _error("identity introuvable", status=404)

    body = _body(request)
    kind = str(body.get("kind") or "").strip()
    known = set(trust_policy.EVIDENCE_WEIGHTS) | set(
        trust_policy.COUNTER_EVIDENCE_WEIGHTS
    )
    if kind not in known:
        # The resolver treats an unknown kind as weight 0 on purpose (it
        # runs on LLM arguments). From a form with a fixed dropdown, an
        # unknown kind is a bug, and a write that silently does nothing
        # is worse than a refusal.
        return _error(f"kind inconnu: {kind or '(vide)'}")

    person_id = _person_id_for(identity)
    if not person_id:
        return _error("cette identite n'a aucun handle")

    return _resolver_call(
        identity_resolver.record_evidence,
        person_id,
        kind=kind,
        detail=str(body.get("detail") or "Saisi depuis le dashboard"),
        name=str(body.get("name") or ""),
    )


@require_http_methods(["POST"])
def identity_revoke(request, identity_id: int):
    """Stop believing — unbinds when the doubt is strong enough.

    Deliberately not a delete: the ledger keeps why she believed and why
    she stopped, which is the whole point of ``IdentityClaim``.
    """
    from identity.resolver import identity_resolver

    identity = _identity_or_404(identity_id)
    if identity is None:
        return _error("identity introuvable", status=404)

    person_id = _person_id_for(identity)
    if not person_id:
        return _error("cette identite n'a aucun handle")

    return _resolver_call(
        identity_resolver.revoke,
        person_id,
        reason=str(_body(request).get("reason") or "Revoque depuis le dashboard"),
    )
