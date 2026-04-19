"""Dashboard views declared by the email module.

Each view returns a dict with ``columns`` + ``rows`` which the generic
dashboard shell (``dashboard/module_view.html`` + ``module_default.js``)
renders as a paginated table. A view that ships its own template/JS
can return any JSON shape.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db.models import Q

from modules.types import ModuleView, ModuleViewAction


def _int(request, key: str, default: int, *, lo: int = 0, hi: int = 500) -> int:
    raw = request.GET.get(key)
    if raw is None:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, v))


async def _inbox_data(request) -> dict:
    from modules.plugins.email.models import Email

    page = _int(request, "page", 0, lo=0, hi=10_000)
    limit = _int(request, "limit", 25, lo=1, hi=100)
    q = (request.GET.get("q") or "").strip()

    qs = Email.objects.select_related("account")
    if q:
        qs = qs.filter(
            Q(subject__icontains=q)
            | Q(from_address__icontains=q)
            | Q(body_text__icontains=q)
        )

    total = await sync_to_async(qs.count)()
    rows = await sync_to_async(
        lambda: list(
            qs.order_by("-email_date")[page * limit:(page + 1) * limit].values(
                "id", "direction", "priority", "from_address",
                "to_addresses", "subject", "email_date",
                "is_read", "account__name",
            )
        )
    )()

    for r in rows:
        d = r.get("email_date")
        r["email_date"] = d.strftime("%Y-%m-%d %H:%M") if d else ""
        r["account"] = r.pop("account__name")
        r["is_read"] = "oui" if r["is_read"] else "non"

    return {
        "columns": [
            {"key": "id", "label": "#"},
            {"key": "direction", "label": "Sens"},
            {"key": "priority", "label": "Priorité"},
            {"key": "from_address", "label": "De"},
            {"key": "to_addresses", "label": "À"},
            {"key": "subject", "label": "Sujet"},
            {"key": "email_date", "label": "Date"},
            {"key": "is_read", "label": "Lu"},
            {"key": "account", "label": "Compte"},
        ],
        "rows": rows,
        "total": total,
        "page": page,
        "limit": limit,
    }


async def _contacts_data(request) -> dict:
    from modules.plugins.email.models import Contact

    page = _int(request, "page", 0, lo=0, hi=10_000)
    limit = _int(request, "limit", 25, lo=1, hi=100)
    q = (request.GET.get("q") or "").strip()

    qs = Contact.objects.all()
    if q:
        qs = qs.filter(
            Q(email_address__icontains=q) | Q(display_name__icontains=q)
        )

    total = await sync_to_async(qs.count)()
    rows = await sync_to_async(
        lambda: list(
            qs.order_by("-last_seen")[page * limit:(page + 1) * limit].values(
                "id", "email_address", "display_name",
                "emails_received", "emails_sent", "last_seen",
            )
        )
    )()
    for r in rows:
        d = r.get("last_seen")
        r["last_seen"] = d.strftime("%Y-%m-%d %H:%M") if d else ""

    return {
        "columns": [
            {"key": "email_address", "label": "Adresse"},
            {"key": "display_name", "label": "Nom"},
            {"key": "emails_received", "label": "Reçus"},
            {"key": "emails_sent", "label": "Envoyés"},
            {"key": "last_seen", "label": "Dernier contact"},
        ],
        "rows": rows,
        "total": total,
        "page": page,
        "limit": limit,
    }


async def _contact_detail(request, item_id: str) -> dict | None:
    """Option A demo — generic key/value modal served from detail_handler."""
    from modules.plugins.email.models import Contact

    try:
        pk = int(item_id)
    except ValueError:
        return None
    try:
        c = await sync_to_async(
            Contact.objects.prefetch_related("accounts").get
        )(pk=pk)
    except Contact.DoesNotExist:
        return None

    accounts = await sync_to_async(
        lambda: ", ".join(a.name for a in c.accounts.all()) or "—"
    )()
    return {
        "fields": [
            {"key": "email", "label": "Adresse", "value": c.email_address},
            {"key": "name", "label": "Nom", "value": c.display_name or "—"},
            {"key": "received", "label": "Reçus", "value": c.emails_received},
            {"key": "sent", "label": "Envoyés", "value": c.emails_sent},
            {"key": "first", "label": "Premier contact",
             "value": c.first_seen.strftime("%Y-%m-%d %H:%M") if c.first_seen else "—"},
            {"key": "last", "label": "Dernier contact",
             "value": c.last_seen.strftime("%Y-%m-%d %H:%M") if c.last_seen else "—"},
            {"key": "accounts", "label": "Comptes", "value": accounts},
            {"key": "notes", "label": "Notes", "value": c.notes or "—"},
        ],
    }


async def _accounts_data(request) -> dict:
    from modules.plugins.email.models import EmailAccount

    rows = await sync_to_async(
        lambda: list(
            EmailAccount.objects.all().values(
                "id", "name", "email_address",
                "imap_host", "smtp_host",
                "is_active", "initial_sync_done", "last_fetch",
            )
        )
    )()
    for r in rows:
        d = r.get("last_fetch")
        r["last_fetch"] = d.strftime("%Y-%m-%d %H:%M") if d else ""
        r["is_active"] = "oui" if r["is_active"] else "non"
        r["initial_sync_done"] = "oui" if r["initial_sync_done"] else "non"

    return {
        "columns": [
            {"key": "id", "label": "#"},
            {"key": "name", "label": "Nom"},
            {"key": "email_address", "label": "Adresse"},
            {"key": "imap_host", "label": "IMAP"},
            {"key": "smtp_host", "label": "SMTP"},
            {"key": "is_active", "label": "Actif"},
            {"key": "initial_sync_done", "label": "Sync initial"},
            {"key": "last_fetch", "label": "Dernière récup."},
        ],
        "rows": rows,
        "total": len(rows),
    }


async def _inbox_detail(request, item_id: str) -> dict | None:
    """Option B demo — returns a rich payload the custom inbox.js consumes.

    The generic renderer would also understand this (fields list); the
    point is that the module's own JS can pull extra structure (body,
    HTML, priority) and render it however it wants.
    """
    from modules.plugins.email.models import Email

    try:
        pk = int(item_id)
    except ValueError:
        return None
    try:
        e = await sync_to_async(Email.objects.select_related("account").get)(pk=pk)
    except Email.DoesNotExist:
        return None

    return {
        "id": e.id,
        "account": e.account.name,
        "direction": e.direction,
        "priority": e.priority,
        "is_read": e.is_read,
        "from": e.from_address,
        "to": e.to_addresses,
        "cc": e.cc_addresses,
        "subject": e.subject,
        "date": e.email_date.strftime("%Y-%m-%d %H:%M") if e.email_date else "",
        "has_attachments": e.has_attachments,
        "body_text": e.body_text,
        "body_html": e.body_html,
        # Key/value shape for the generic renderer fallback (when a view
        # has detail_handler but no custom template).
        "fields": [
            {"key": "from", "label": "De", "value": e.from_address},
            {"key": "to", "label": "À", "value": e.to_addresses},
            {"key": "subject", "label": "Sujet", "value": e.subject},
            {"key": "date", "label": "Date",
             "value": e.email_date.strftime("%Y-%m-%d %H:%M") if e.email_date else "—"},
            {"key": "account", "label": "Compte", "value": e.account.name},
            {"key": "priority", "label": "Priorité", "value": e.priority},
            {"key": "body", "label": "Corps", "value": e.body_text},
        ],
    }


async def _mark_all_read(request) -> dict:
    """Mark every inbound email as read. Wired to the inbox view as a demo
    side-effect action."""
    from modules.plugins.email.models import Email

    updated = await sync_to_async(
        Email.objects.filter(direction="inbound", is_read=False).update
    )(is_read=True)
    return {"ok": True, "updated": updated}


def email_views() -> list[ModuleView]:
    return [
        # Option B — custom template + custom JS shipped by the module.
        # The generic shell still serves JSON at the standard data/detail
        # endpoints; the module's JS renders a split master/detail pane.
        ModuleView(
            key="inbox", label="Boîte de réception", icon="✉", order=10,
            data_handler=_inbox_data,
            detail_handler=_inbox_detail,
            id_field="id",
            template="email/inbox.html",
            js="/static/email/views/inbox.js",
            actions=[
                ModuleViewAction(
                    key="mark_all_read",
                    label="Tout marquer comme lu",
                    handler=_mark_all_read,
                    confirm="Marquer tous les emails entrants comme lus ?",
                ),
            ],
        ),
        # Option A — generic shell, detail_handler opens a key/value modal.
        ModuleView(
            key="contacts", label="Contacts", icon="☻", order=20,
            data_handler=_contacts_data,
            detail_handler=_contact_detail,
            id_field="id",
        ),
        # Simple list, no detail.
        ModuleView(
            key="accounts", label="Comptes", icon="⚙", order=30,
            data_handler=_accounts_data,
        ),
    ]
