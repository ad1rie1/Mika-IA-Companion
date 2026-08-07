"""One source of truth for application config: the registry + the database.

There used to be two. `settings.py` declared ~31 constants that existed only
to be read back through `ConfigItem.env_fallback` and materialised into
`ConfigValue` rows on first boot. That arrangement had three problems and no
upside once the dashboard existed:

- **Two declared defaults per key.** `settings.py` said `default=0.5` and
  `config_schema.py` said `default=0.5`, and the first always won at seed
  time — so the registry default, the one a reader would look at, was
  decorative.
- **A bridge that silently didn't work for seven keys**, because it named a
  *settings attribute* and nobody had declared one (`GEMINI_API_KEY`,
  `AI_ROLE_VISION_CAPTION`, `SLEEP_CHECK_INTERVAL`, …).
- **`AI_ROLE_*` could only ever seed a broken value.** They carried the
  legacy `provider:model` form, while `AIRouter._resolve` looks the value up
  as an *internal name* declared in the `ai.models` record list. A seeded
  `claude:claude-opus-4-6` resolves to nothing and raises
  `UnconfiguredRoleError`.

Everything is now configured in GestionSystème. Nothing is configured twice.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from configs.registry import registry
from configs.service import ConfigService


def _settings_constants() -> set[str]:
    """Top-level UPPERCASE assignments in settings.py."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "config" / "settings.py").read_text()
    return {
        node.targets[0].id
        for node in ast.parse(src).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.isupper()
    }


# ---------------------------------------------------------------------------
# 1. The bridge is gone
# ---------------------------------------------------------------------------


class TestNoEnvBridge:

    def test_a_config_item_cannot_even_declare_an_env_fallback(self):
        """A knob reachable from two places drifts. The field itself is
        gone, so the guard is on the dataclass rather than on its values:
        re-adding it has to be a deliberate edit to `ConfigItem`, not a
        line slipped into one schema."""
        import dataclasses

        from configs.types import ConfigItem

        fields = {f.name for f in dataclasses.fields(ConfigItem)}
        assert "env_fallback" not in fields, (
            "la config applicative se parametre dans le dashboard, pas "
            "dans .env"
        )
        assert not any(hasattr(i, "env_fallback") for i in registry.all_items())

    def test_the_seeding_machinery_is_gone(self):
        """It existed only to serve the bridge."""
        assert not hasattr(ConfigService, "seed_from_env")
        assert not hasattr(ConfigService, "env_overrides_ignored")

    def test_settings_no_longer_shadows_a_config_key(self):
        """The concrete failure: two declared defaults for one knob, the
        settings one silently winning, the registry one decorative."""
        constants = _settings_constants()
        shadowed = []
        for item in registry.all_items():
            # Historic naming: memory.decay_rate ← MEMORY_DECAY_RATE
            guess = item.key.replace(".", "_").upper()
            if guess in constants:
                shadowed.append(f"{item.key} / settings.{guess}")
        assert not shadowed, f"config declaree deux fois: {shadowed}"

    def test_no_ai_role_constant_survives(self):
        """They could only ever seed a value `AIRouter._resolve` rejects."""
        leftovers = {c for c in _settings_constants() if c.startswith("AI_ROLE_")}
        assert leftovers == set()


# ---------------------------------------------------------------------------
# 2. What settings.py is still allowed to hold
# ---------------------------------------------------------------------------


class TestSettingsScope:
    """Infrastructure — things Django needs before any database exists —
    plus values read by computed name."""

    def test_infrastructure_is_still_declared(self):
        from django.conf import settings

        for name in ("API_HOST", "API_PORT", "DEBUG", "TIME_ZONE",
                     "CHROMA_PERSIST_DIR", "FORGE_DIR", "PERSONALITY_PATH"):
            assert hasattr(settings, name), name

    def test_no_legacy_module_credential_survives(self):
        """The email account and the RSS feed list are ORM rows edited in
        the dashboard, and the provider credentials live encrypted in
        `ConfigValue`. Their `.env` ancestors seeded those tables on first
        boot from a *settings attribute*, which is the same two-sources
        arrangement as `env_fallback` wearing a different hat: the seed ran
        only against an empty table, so after the first boot the variable
        was inert with no feedback, and a rotated credential in `.env`
        silently did nothing.

        Asserted on prefixes rather than a literal list — `POP3_USER` would
        be the same mistake under a new name.
        """
        legacy = {
            c for c in _settings_constants()
            if c.startswith(("IMAP_", "SMTP_", "POP3_", "RSS_", "TELEGRAM_"))
            or c.endswith(("_API_KEY", "_OAUTH_TOKEN", "_BASE_URL"))
        }
        assert legacy == set(), f"credential/module config hors dashboard: {legacy}"

    def test_per_role_quota_constants_are_kept(self):
        """`ai/quota.py` builds these names at runtime
        (`AI_QUOTA_ROLE_<ROLE>_DAILY`), so a grep for the literal finds
        nothing and a careless cleanup would silently disable per-role
        quotas by defaulting them to 0 = unlimited."""
        constants = _settings_constants()
        assert "AI_QUOTA_ROLE_CONVERSATION_DAILY" in constants
        assert "AI_QUOTA_ROLE_VISION_CAPTION_MONTHLY" in constants

    def test_quota_reads_them_by_computed_name(self):
        import inspect

        from ai import quota

        src = inspect.getsource(quota)
        assert 'f"AI_QUOTA_ROLE_{role.upper()}_DAILY"' in src


# ---------------------------------------------------------------------------
# 3. A fresh install still boots
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFreshInstallDefaults:
    """With no `.env` seeding, the registry default is the *only* thing
    standing between a fresh clone and a crashing background loop."""

    def test_every_operational_knob_has_a_default(self):
        """Asserted on the *registry*, not through ``config_service``: the
        service memoises, and its cache is primed from the real
        ``data/vtuber.db`` during ``AppConfig.ready()`` (hence Django's
        "accessing the database during app initialization" warning), so a
        read here can return the developer's own configuration rather than
        what a fresh clone would see.
        """
        # The AI roles are deliberately unset: nothing works until you
        # declare a model and map it, which is the intended first-run
        # experience. Everything else must have a working value.
        missing = [
            i.key for i in registry.all_items()
            if i.type not in ("record_list", "secret")
            and not i.key.startswith("ai.role.")
            and i.default in (None, "")
        ]
        assert not missing, f"pas de defaut utilisable: {missing}"

    @pytest.mark.parametrize("key,expected", [
        ("conscience.act_threshold", 0.5),
        ("conscience.decision_interval", 30),
        ("memory.consolidation_interval", 60),
        ("memory.sleep_check_interval", 60),
        ("projects.runner_interval", 30),
        ("modules.cron_tick_interval", 60),
    ])
    def test_the_loop_cadences_have_a_declared_default(self, key, expected):
        """These drive the background loops; a None here is a crash at boot
        on a clone nobody has configured yet."""
        assert registry.get(key).default == expected

    def test_the_ai_roles_declare_no_default(self):
        """Deliberate: a role must point at a model declared in `ai.models`,
        and no such model exists on a fresh clone. `AIRouter._resolve` then
        raises `UnconfiguredRoleError`, which the processor turns into
        "Configuration > IA · Roles" — the intended first-run experience.

        This is also why the old `AI_ROLE_*` bridge was worse than useless:
        it seeded the legacy `provider:model` form into a field resolved as
        an internal model name, so it could only ever seed a broken value.
        """
        roles = [i for i in registry.all_items() if i.key.startswith("ai.role.")]
        assert roles
        assert all(i.default in (None, "") for i in roles)


# ---------------------------------------------------------------------------
# 4. ALLOWED_HOSTS
# ---------------------------------------------------------------------------


class TestAllowedHosts:
    """The one line in settings.py that opted out of the posture every other
    line argues for."""

    def test_it_is_not_wildcarded(self):
        from django.conf import settings

        assert "*" not in settings.ALLOWED_HOSTS

    def test_loopback_is_served(self):
        from django.conf import settings

        assert "127.0.0.1" in settings.ALLOWED_HOSTS
        assert "localhost" in settings.ALLOWED_HOSTS

    def test_a_spoofed_host_is_refused(self, client):
        resp = client.get("/gestion/", HTTP_HOST="evil.test")
        assert resp.status_code == 400

    def test_a_legitimate_host_is_served(self, client):
        resp = client.get("/gestion/", HTTP_HOST="127.0.0.1")
        assert resp.status_code == 200
