"""Bridge between the generic ``record_list`` config editor and Django's
user model — the accounts that log into the frontend and GestionSystème.

Same shape as ``modules/plugins/email/config_backend.py``: the config UI
knows nothing about ``User``, it just edits rows; this adapter maps them
onto real accounts. Nothing is stored in ``ConfigRecordItem``.

Why it exists: ``/auth/bootstrap`` creates the **first** account and then
closes forever (409), so every account after that needed a terminal and
``createsuperuser``. The owner of a personal install shouldn't have to
leave GestionSystème to hand a second login to someone.

Three rules the generic backend can't express, all enforced here:

  - **Passwords are never read back.** Django stores a hash, not a
    secret; the read path reports "défini / vide" and never a preview of
    the hash. A blank input keeps the current password (standard secret
    semantics), a non-blank one goes through ``validate_password`` — the
    same validators ``/auth/bootstrap`` uses, so "123" is refused here
    too.
  - **No lockout.** A write that would leave zero active superusers, or
    zero active staff accounts, is refused. Deleting, deactivating and
    demoting are all the same mistake from GestionSystème's point of view:
    the next reload of ``/gestion/`` under ``DASHBOARD_REQUIRE_AUTH``
    has nobody left to let in.
  - **Refusals are loud.** ``ValidationError`` → 4xx with a French
    message, never a silent no-op — this is a form, not an LLM argument.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from configs import backends
from configs.service import ValidationError

# Payload keys ↔ model attributes. ``display_name`` is deliberately mapped
# onto ``first_name``: ``communication.views._display_name`` reads
# ``get_full_name()`` first, so that is the field Mika actually calls the
# person by.
_FLAGS = ("is_staff", "is_superuser")


class UserAccountBackend:
    """CRUD over ``django.contrib.auth`` users, driven by the config UI."""

    # ── Lookup ──────────────────────────────────────────────────

    def _model(self):
        return get_user_model()

    def _all(self):
        return self._model().objects.all().order_by("id")

    def _get(self, row_id):
        """Lookup by stringified PK. Missing row → KeyError (→ 404 at the view)."""
        User = self._model()
        try:
            pk = int(row_id)
        except (TypeError, ValueError):
            raise KeyError(f"Identifiant de compte invalide: {row_id!r}")
        try:
            return User.objects.get(pk=pk)
        except User.DoesNotExist:
            raise KeyError(f"Compte {row_id} introuvable")

    # ── Serialization ───────────────────────────────────────────

    def _serialize(self, obj, *, decrypt_secrets: bool = False):
        """``decrypt_secrets`` is honoured by never leaking anything: a
        password hash is not a secret we can hand back, so both paths
        report presence only."""
        return {
            "row_id": str(obj.pk),
            "payload": {
                "username": obj.get_username(),
                "display_name": (obj.first_name or "").strip(),
                "email": getattr(obj, "email", "") or "",
                # The UI renders a `secret` field from this dict; length 0
                # means "no character count", not "empty" (see has_value).
                "password": {
                    "has_value": bool(obj.password),
                    "preview": "défini",
                    "length": 0,
                },
                "is_staff": bool(obj.is_staff),
                "is_superuser": bool(obj.is_superuser),
                "person_id": f"user_{obj.pk}",
            },
            "enabled": bool(obj.is_active),
            "order": obj.pk,
            "updated_at": obj.date_joined.isoformat() if getattr(obj, "date_joined", None) else "",
        }

    # ── Guards ──────────────────────────────────────────────────

    def _guard_no_lockout(self, obj, *, is_active: bool, is_staff: bool, is_superuser: bool,
                          deleting: bool = False) -> None:
        """Refuse a write that would leave nobody able to administer.

        Counts the *other* active accounts, then adds this one back twice:
        as it stands, and as it is about to stand. Demoting the only
        superuser and deleting them are then caught by the same
        arithmetic.

        The comparison is deliberately *before vs after*, not "after must
        be ≥ 1": a database that already has no admin (nobody ran
        bootstrap, or the only admin is deactivated) is not made worse by
        renaming an ordinary account, and blocking every write until an
        admin exists would be a lockout of its own.
        """
        User = self._model()
        others = User.objects.filter(is_active=True).exclude(pk=obj.pk)
        base_supers = others.filter(is_superuser=True).count()
        base_staff = others.filter(is_staff=True).count()

        was_active = obj.is_active and obj.pk is not None
        before_supers = base_supers + (1 if was_active and obj.is_superuser else 0)
        before_staff = base_staff + (1 if was_active and obj.is_staff else 0)

        keeps = (not deleting) and is_active
        after_supers = base_supers + (1 if keeps and is_superuser else 0)
        after_staff = base_staff + (1 if keeps and is_staff else 0)

        if after_supers == 0 and before_supers > 0:
            raise ValidationError(
                "Impossible : ce serait le dernier compte administrateur actif. "
                "Crée ou active un autre superutilisateur d'abord."
            )
        if after_staff == 0 and before_staff > 0:
            raise ValidationError(
                "Impossible : ce serait le dernier compte avec accès à l'administration. "
                "Donne l'accès administration à un autre compte d'abord."
            )

    def _clean_username(self, raw, *, exclude_pk=None) -> str:
        username = (raw or "").strip()
        if not username:
            raise ValidationError("Le nom d'utilisateur est obligatoire")
        qs = self._model().objects.filter(username=username)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if qs.exists():
            raise ValidationError(f"Le nom d'utilisateur « {username} » est déjà pris")
        return username

    def _set_password(self, obj, raw) -> None:
        password = str(raw)
        try:
            validate_password(password, user=obj)
        except DjangoValidationError as exc:
            raise ValidationError(" ".join(exc.messages))
        obj.set_password(password)

    # ── Public API ──────────────────────────────────────────────

    def list_rows(self, item, *, decrypt_secrets=False):
        return [self._serialize(o) for o in self._all()]

    def add_row(self, item, payload):
        User = self._model()
        obj = User()
        obj.username = self._clean_username(payload.get("username"))
        obj.first_name = (payload.get("display_name") or "").strip()
        if hasattr(obj, "email"):
            obj.email = (payload.get("email") or "").strip()
        obj.is_staff = bool(payload.get("is_staff"))
        obj.is_superuser = bool(payload.get("is_superuser"))
        obj.is_active = bool(payload.get("enabled", True))

        password = payload.get("password")
        if password in (None, ""):
            raise ValidationError("Un mot de passe est obligatoire à la création")
        self._set_password(obj, password)

        obj.save()
        return self._serialize(obj)

    def update_row(self, item, row_id, payload):
        obj = self._get(row_id)

        if "username" in payload:
            obj.username = self._clean_username(payload["username"], exclude_pk=obj.pk)
        if "display_name" in payload:
            obj.first_name = (payload["display_name"] or "").strip()
        if "email" in payload and hasattr(obj, "email"):
            obj.email = (payload["email"] or "").strip()

        next_flags = {f: bool(payload[f]) if f in payload else getattr(obj, f) for f in _FLAGS}
        next_active = bool(payload["enabled"]) if "enabled" in payload else obj.is_active
        self._guard_no_lockout(
            obj, is_active=next_active,
            is_staff=next_flags["is_staff"], is_superuser=next_flags["is_superuser"],
        )
        for flag, value in next_flags.items():
            setattr(obj, flag, value)
        obj.is_active = next_active

        # Blank / absent password keeps the current one — the UI omits the
        # field entirely when the input is left empty.
        password = payload.get("password")
        if password not in (None, ""):
            self._set_password(obj, password)

        obj.save()
        return self._serialize(obj)

    def delete_row(self, item, row_id):
        # Silent on a missing row — matches the generic backend behavior.
        try:
            obj = self._get(row_id)
        except KeyError:
            return
        self._guard_no_lockout(
            obj, is_active=obj.is_active, is_staff=obj.is_staff,
            is_superuser=obj.is_superuser, deleting=True,
        )
        obj.delete()


# Register at import — the schema module imports this one, which runs the
# side-effect. Idempotent.
backends.register("accounts.users", UserAccountBackend())
