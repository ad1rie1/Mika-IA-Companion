"""Access accounts edited from the dashboard configuration.

``/auth/bootstrap`` creates the *first* account and then returns 409
forever, so every login after it required a terminal and
``createsuperuser``. The new ``Accès · Comptes`` section closes that gap
by editing real ``User`` rows through the generic record_list editor.

Three properties are load-bearing and pinned here:

1. **A password is never read back and never weak.** The read path
   reports presence only (the column holds a hash, not a secret), and a
   written one goes through the same ``validate_password`` as bootstrap —
   the dashboard must not be the door around ``AUTH_PASSWORD_VALIDATORS``.
2. **No lockout.** Deleting, deactivating and demoting the last active
   admin are the same mistake; all three are refused, loudly, with a 4xx
   rather than a 200 that quietly does nothing.
3. **Real accounts, not config rows.** A row created here authenticates —
   otherwise the section would be a convincing-looking no-op.
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.test import Client

from configs.registry import registry
from configs.service import ValidationError, config_service


pytestmark = pytest.mark.django_db

User = get_user_model()

STRONG = "correct-horse-42-battery"
OTHER_STRONG = "unrelated-tulip-91-anchor"


@pytest.fixture
def item():
    it = registry.get("accounts.users")
    assert it is not None, "accounts.users must be declared"
    return it


@pytest.fixture
def backend():
    from configs import backends
    return backends.resolve("accounts.users")


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(username="owner", password=STRONG)


def _payload(**over):
    base = {
        "username": "thomas", "display_name": "Thomas", "email": "t@example.test",
        "password": STRONG, "is_staff": False, "is_superuser": False,
        "enabled": True,
    }
    base.update(over)
    return base


# ── Declaration ─────────────────────────────────────────────────

class TestSchema:

    def test_section_is_declared_first(self):
        keys = [s.key for s in registry.sections()]
        assert "accounts" in keys
        # The section deciding who reads every other one comes first.
        assert keys.index("accounts") < keys.index("ai_providers")

    def test_item_is_a_record_list_with_a_password_field(self, item):
        assert item.type == "record_list"
        fields = {f.key: f for f in item.record.fields}
        assert fields["password"].sensitive is True
        assert fields["person_id"].readonly is True

    def test_backend_is_the_user_adapter_not_the_generic_table(self, backend):
        from dashboard.config_backend import UserAccountBackend
        assert isinstance(backend, UserAccountBackend)


# ── Storage is the real user table ──────────────────────────────

class TestStorage:

    def test_created_row_is_an_account_that_can_authenticate(self, item, backend):
        backend.add_row(item, _payload())
        user = User.objects.get(username="thomas")
        assert user.first_name == "Thomas"
        assert authenticate(username="thomas", password=STRONG) == user

    def test_nothing_lands_in_the_generic_record_table(self, item, backend):
        from configs.models import ConfigRecordItem
        backend.add_row(item, _payload())
        assert not ConfigRecordItem.objects.filter(parent_key="accounts.users").exists()

    def test_listing_reports_presence_of_a_password_never_its_hash(self, item, backend, admin_user):
        rows = backend.list_rows(item)
        payload = rows[0]["payload"]
        assert payload["password"]["has_value"] is True
        assert admin_user.password not in json.dumps(payload)

    def test_decrypt_secrets_does_not_open_a_read_path_either(self, item, backend, admin_user):
        rows = backend.list_rows(item, decrypt_secrets=True)
        assert rows[0]["payload"]["password"]["has_value"] is True
        assert admin_user.password not in json.dumps(rows[0]["payload"])

    def test_person_id_is_the_handle_identity_uses(self, item, backend, admin_user):
        rows = backend.list_rows(item)
        assert rows[0]["payload"]["person_id"] == f"user_{admin_user.pk}"

    def test_enabled_maps_to_is_active(self, item, backend, admin_user):
        backend.add_row(item, _payload(enabled=False))
        assert User.objects.get(username="thomas").is_active is False


# ── Passwords ───────────────────────────────────────────────────

class TestPasswords:

    def test_weak_password_is_refused_at_creation(self, item, backend):
        with pytest.raises(ValidationError):
            backend.add_row(item, _payload(password="123"))
        assert not User.objects.filter(username="thomas").exists()

    def test_password_is_mandatory_at_creation(self, item, backend):
        with pytest.raises(ValidationError):
            backend.add_row(item, _payload(password=""))

    def test_blank_password_on_update_keeps_the_current_one(self, item, backend):
        row = backend.add_row(item, _payload())
        backend.update_row(item, row["row_id"], {"display_name": "Tom"})
        user = User.objects.get(username="thomas")
        assert user.first_name == "Tom"
        assert authenticate(username="thomas", password=STRONG) == user

    def test_new_password_replaces_the_old_one(self, item, backend):
        row = backend.add_row(item, _payload())
        backend.update_row(item, row["row_id"], {"password": OTHER_STRONG})
        assert authenticate(username="thomas", password=STRONG) is None
        assert authenticate(username="thomas", password=OTHER_STRONG) is not None

    def test_weak_password_is_refused_on_update_too(self, item, backend):
        row = backend.add_row(item, _payload())
        with pytest.raises(ValidationError):
            backend.update_row(item, row["row_id"], {"password": "azerty"})
        assert authenticate(username="thomas", password=STRONG) is not None


# ── Usernames ───────────────────────────────────────────────────

class TestUsernames:

    def test_duplicate_username_is_refused(self, item, backend, admin_user):
        with pytest.raises(ValidationError):
            backend.add_row(item, _payload(username="owner"))

    def test_empty_username_is_refused(self, item, backend):
        with pytest.raises(ValidationError):
            backend.add_row(item, _payload(username="  "))

    def test_renaming_to_its_own_username_is_allowed(self, item, backend):
        row = backend.add_row(item, _payload())
        backend.update_row(item, row["row_id"], {"username": "thomas", "display_name": "T"})
        assert User.objects.get(username="thomas").first_name == "T"

    def test_unknown_row_is_a_keyerror(self, item, backend):
        with pytest.raises(KeyError):
            backend.update_row(item, "99999", {"display_name": "x"})


# ── Lockout guards ──────────────────────────────────────────────

class TestLockout:

    def test_last_admin_cannot_be_deleted(self, item, backend, admin_user):
        with pytest.raises(ValidationError):
            backend.delete_row(item, str(admin_user.pk))
        assert User.objects.filter(pk=admin_user.pk).exists()

    def test_last_admin_cannot_be_deactivated(self, item, backend, admin_user):
        with pytest.raises(ValidationError):
            backend.update_row(item, str(admin_user.pk), {"enabled": False})
        admin_user.refresh_from_db()
        assert admin_user.is_active is True

    def test_last_admin_cannot_be_demoted(self, item, backend, admin_user):
        with pytest.raises(ValidationError):
            backend.update_row(item, str(admin_user.pk), {"is_superuser": False})
        admin_user.refresh_from_db()
        assert admin_user.is_superuser is True

    def test_last_dashboard_access_cannot_be_removed(self, item, backend, admin_user):
        # Superuser flag kept, staff flag dropped: /admin/ would still open,
        # /dashboard/ would not — the middleware is staff-gated.
        with pytest.raises(ValidationError):
            backend.update_row(item, str(admin_user.pk), {"is_staff": False})

    def test_a_second_admin_unlocks_the_first(self, item, backend, admin_user):
        backend.add_row(item, _payload(is_staff=True, is_superuser=True))
        backend.delete_row(item, str(admin_user.pk))
        assert not User.objects.filter(pk=admin_user.pk).exists()

    def test_an_inactive_second_admin_does_not_count(self, item, backend, admin_user):
        backend.add_row(item, _payload(is_staff=True, is_superuser=True, enabled=False))
        with pytest.raises(ValidationError):
            backend.delete_row(item, str(admin_user.pk))

    def test_a_database_with_no_admin_is_not_frozen(self, item, backend):
        # No admin exists at all (bootstrap never run). Editing an ordinary
        # account takes nothing away, so the guard must stay out of the way
        # — otherwise "no admin yet" would mean "no writes ever".
        row = backend.add_row(item, _payload())
        backend.update_row(item, row["row_id"], {"display_name": "Tom"})
        assert User.objects.get(username="thomas").first_name == "Tom"

    def test_a_non_admin_is_freely_deleted(self, item, backend, admin_user):
        row = backend.add_row(item, _payload())
        backend.delete_row(item, row["row_id"])
        assert not User.objects.filter(username="thomas").exists()


# ── HTTP surface ────────────────────────────────────────────────

class TestHttp:
    """Through the real config endpoints, CSRF enforced — the default test
    client disables it, which would pass against an unprotected app."""

    @pytest.fixture
    def client(self, admin_user):
        c = Client(enforce_csrf_checks=True)
        c.force_login(admin_user)
        c.get("/auth/whoami")
        return c

    def _token(self, client):
        return client.cookies["csrftoken"].value

    def _post(self, client, url, body, method="POST"):
        return getattr(client, method.lower())(
            url, data=json.dumps(body), content_type="application/json",
            HTTP_X_CSRFTOKEN=self._token(client),
        )

    def test_rows_endpoint_lists_accounts(self, client, admin_user):
        res = client.get("/dashboard/api/config/rows?key=accounts.users")
        assert res.status_code == 200
        rows = json.loads(res.content)["rows"]
        assert [r["payload"]["username"] for r in rows] == ["owner"]

    def test_create_over_http(self, client):
        res = self._post(client, "/dashboard/api/config/rows/create", {
            "parent_key": "accounts.users", "payload": _payload(),
        })
        assert res.status_code == 200, res.content
        assert authenticate(username="thomas", password=STRONG) is not None

    def test_weak_password_answers_400(self, client):
        res = self._post(client, "/dashboard/api/config/rows/create", {
            "parent_key": "accounts.users", "payload": _payload(password="123"),
        })
        assert res.status_code == 400
        assert "error" in json.loads(res.content)

    def test_deleting_the_last_admin_answers_409_not_500(self, client, admin_user):
        res = self._post(
            client,
            f"/dashboard/api/config/rows/{admin_user.pk}?parent_key=accounts.users",
            {}, method="DELETE",
        )
        assert res.status_code == 409
        assert User.objects.filter(pk=admin_user.pk).exists()

    def test_audit_log_never_records_a_password(self, client):
        from configs.models import ConfigChangeLog
        self._post(client, "/dashboard/api/config/rows/create", {
            "parent_key": "accounts.users", "payload": _payload(),
        })
        log = ConfigChangeLog.objects.filter(key="accounts.users").latest("id")
        assert STRONG not in json.dumps(log.after)

    def test_schema_exposes_the_section(self, client):
        res = client.get("/dashboard/api/config/schema")
        sections = json.loads(res.content)["sections"]
        section = next(s for s in sections if s["key"] == "accounts")
        assert section["items"][0]["key"] == "accounts.users"

    def test_values_snapshot_skips_the_record_list(self, client):
        # A record_list has no scalar value; it must not appear as `null`
        # in the values payload the UI renders inputs from.
        assert "accounts.users" not in config_service.snapshot_redacted()
