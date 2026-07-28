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
        from GestionSysteme.config_backend import UserAccountBackend
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
        # /gestion/ would not — the middleware is staff-gated.
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
    """À travers les vrais formulaires de GestionSystème, CSRF activé.

    Le client de test désactive CSRF par défaut : une suite écrite sans
    ``enforce_csrf_checks`` passerait contre une application non protégée.

    Ces tests visaient les points JSON de l'ancien ``dashboard``. Ceux-ci ont
    disparu avec lui, mais les règles qu'ils vérifiaient tiennent toujours —
    c'est l'écran qui a changé, pas la politique. Les réponses ne sont plus
    des codes 400/409 mais un formulaire réaffiché avec son message : depuis
    un navigateur c'est ce que l'opérateur doit voir.
    """

    LISTE = "/gestion/configuration/accounts/accounts.users/"
    SECTION = "/gestion/configuration/accounts/"

    @pytest.fixture
    def client(self, admin_user):
        c = Client(enforce_csrf_checks=True)
        c.force_login(admin_user)
        c.get(self.SECTION)          # plante le cookie csrftoken
        return c

    def _post(self, client, url, data):
        payload = dict(data)
        payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        return client.post(url, data=payload)

    @staticmethod
    def _form(**over):
        """``_payload()`` en encodage de formulaire.

        Une case décochée n'est pas envoyée : c'est la convention HTML, et
        c'est ce que le moteur de formulaires interprète comme « faux ».
        """
        brut = _payload(**over)
        data = {
            "username": brut["username"],
            "display_name": brut["display_name"],
            "email": brut["email"],
            "password": brut["password"],
        }
        for drapeau in ("is_staff", "is_superuser"):
            if brut.get(drapeau):
                data[drapeau] = "1"
        return data

    def test_la_page_liste_les_comptes(self, client, admin_user):
        html = client.get(self.SECTION).content.decode()
        assert "owner" in html
        # Le hash ne doit jamais atteindre le navigateur.
        assert admin_user.password not in html

    def test_creation_par_le_formulaire(self, client):
        res = self._post(client, self.LISTE + "nouveau/", self._form())
        assert res.status_code == 302, res.content[:400]
        assert authenticate(username="thomas", password=STRONG) is not None

    def test_un_mot_de_passe_faible_est_refuse(self, client):
        res = self._post(
            client, self.LISTE + "nouveau/", self._form(password="123"),
        )
        assert res.status_code == 200            # formulaire réaffiché
        assert not User.objects.filter(username="thomas").exists()

    def test_supprimer_le_dernier_admin_est_refuse(self, client, admin_user):
        res = self._post(
            client, f"{self.LISTE}{admin_user.pk}/supprimer/", {},
        )
        assert res.status_code == 302            # retour à la section
        assert User.objects.filter(pk=admin_user.pk).exists()

    def test_le_journal_n_enregistre_jamais_un_mot_de_passe(self, client):
        from configs.models import ConfigChangeLog

        self._post(client, self.LISTE + "nouveau/", self._form())
        log = ConfigChangeLog.objects.filter(key="accounts.users").latest("id")
        assert STRONG not in json.dumps(log.after)

    def test_la_section_apparait_dans_la_configuration(self, client):
        from GestionSysteme.views import config as config_view

        cles = [s.key for s in config_view.core_sections()]
        assert "accounts" in cles
        # Et elle passe en premier : c'est la section qui décide qui lit
        # toutes les autres.
        assert cles[0] == "accounts"

    def test_une_ecriture_sans_jeton_csrf_est_refusee(self, admin_user):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(admin_user)
        res = strict.post(self.LISTE + "nouveau/", data=self._form())
        assert res.status_code == 403
        assert not User.objects.filter(username="thomas").exists()

    def test_values_snapshot_skips_the_record_list(self, client):
        # A record_list has no scalar value; it must not appear as `null`
        # in the values payload the UI renders inputs from.
        assert "accounts.users" not in config_service.snapshot_redacted()
