"""Bridge between the generic ``record_list`` config editor and the
``EmailAccount`` Django model.

Design:
  - The config record schema declares fields (name, email, imap_*, smtp_*).
  - This adapter maps those field names 1:1 to ``EmailAccount`` columns.
  - ``row_id`` surfaced to the UI is the model's integer PK stringified —
    we don't need a UUID since the adapter owns the lookup.
  - Passwords: encrypted at rest via ``configs.secrets``; redacted in read
    path; new value (non-empty) overwrites; empty input preserves existing
    (standard secret semantics).
  - ``is_active`` maps to ``enabled`` on the wire.

Registration happens once at import time (imported from the schema).
"""
from __future__ import annotations

from configs import backends, secrets

_FIELDS = (
    "name", "email_address",
    "imap_host", "imap_port", "imap_user", "imap_password",
    "smtp_host", "smtp_port", "smtp_user", "smtp_password",
)
_SECRETS = {"imap_password", "smtp_password"}


class EmailAccountBackend:
    """CRUD over ``modules.plugins.email.models.EmailAccount``."""

    def _all(self):
        from modules.plugins.email.models import EmailAccount
        return EmailAccount.objects.all().order_by("id")

    def _get(self, row_id):
        """Lookup by stringified PK. Missing row → KeyError (→ 404 at the view)."""
        from modules.plugins.email.models import EmailAccount
        try:
            pk = int(row_id)
        except (TypeError, ValueError):
            raise KeyError(f"Invalid email account id: {row_id!r}")
        try:
            return EmailAccount.objects.get(pk=pk)
        except EmailAccount.DoesNotExist:
            raise KeyError(f"Email account {row_id} not found")

    # ── Serialization ───────────────────────────────────────────

    def _serialize(self, obj, *, decrypt_secrets: bool):
        payload = {f: getattr(obj, f) for f in _FIELDS}
        # Secrets : chiffrés au repos comme dans le backend générique, donc
        # déchiffrés ici avant d'être rendus — et rédigés par défaut pour que
        # l'UI ne les réémette jamais.
        for f in _SECRETS:
            raw = payload.get(f) or ""
            clair = secrets.decrypt(raw) if raw else ""
            if decrypt_secrets:
                payload[f] = clair
            else:
                payload[f] = secrets.redact(clair)
        return {
            "row_id": str(obj.pk),
            "payload": payload,
            "enabled": obj.is_active,
            "order": obj.pk,
            "updated_at": obj.created_at.isoformat() if obj.created_at else "",
        }

    def _apply(self, obj, item, payload):
        """Copy payload → model, preserving secrets when input is empty."""
        record = item.record
        for field in record.fields:
            key = field.key
            if key not in _FIELDS:
                continue
            incoming = payload.get(key, None)
            if field.sensitive:
                # Empty / missing input keeps the existing value (standard
                # secret semantics). Replace only when a new value is typed.
                if incoming in (None, ""):
                    continue
                # Chiffré au repos, comme tout champ sensible du registre
                # (cf. configs/backends.py::_clean_payload) : la redaction en
                # lecture ne protège que l'affichage, pas data/vtuber.db.
                setattr(obj, key, secrets.encrypt(str(incoming)))
                continue
            if incoming is None:
                continue
            # Type coercion for numeric ports
            if field.type == "int":
                try: incoming = int(incoming)
                except (TypeError, ValueError): continue
            setattr(obj, key, incoming)

        if "enabled" in payload:
            obj.is_active = bool(payload["enabled"])

    # ── Public API ──────────────────────────────────────────────

    def list_rows(self, item, *, decrypt_secrets=False):
        return [self._serialize(o, decrypt_secrets=decrypt_secrets) for o in self._all()]

    def add_row(self, item, payload):
        from modules.plugins.email.models import EmailAccount
        obj = EmailAccount()
        self._apply(obj, item, payload)
        # Required columns — make sure email_address is set
        if not obj.email_address:
            raise ValueError("email_address est obligatoire")
        if not obj.name:
            obj.name = obj.email_address
        if not obj.imap_user:
            obj.imap_user = obj.email_address
        obj.save()
        return self._serialize(obj, decrypt_secrets=False)

    def update_row(self, item, row_id, payload):
        obj = self._get(row_id)
        self._apply(obj, item, payload)
        obj.save()
        return self._serialize(obj, decrypt_secrets=False)

    def delete_row(self, item, row_id):
        # Silent on missing row — matches the generic backend behavior.
        try:
            obj = self._get(row_id)
        except KeyError:
            return
        obj.delete()


# Register at import — the schema file imports this module, which runs
# this side-effect. Idempotent.
backends.register("email.accounts", EmailAccountBackend())
