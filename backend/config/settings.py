import os
from pathlib import Path

import environ

# backend/
BASE_DIR = Path(__file__).resolve().parent.parent
# vtuber/ (project root, where .env and personality.yaml live)
PROJECT_ROOT = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(str(PROJECT_ROOT / ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-secret-change-me")
DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "channels",
    "ai",
    "communication",
    "emotion",
    "drives",
    "memory",
    "conscience",
    "files",
    "modules",
    "projects",
    "dashboard",
    "configs",
    "identity",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Must sit after AuthenticationMiddleware — it reads request.user.
    "dashboard.middleware.DashboardAuthMiddleware",
]

# Django's admin login doubles as the dashboard login when the gate is on:
# both want a staff account, so there is no second credential to manage.
LOGIN_URL = env("LOGIN_URL", default="/admin/login/")

# Django ships these but does not enable them; without the list,
# `validate_password` is a no-op and /auth/bootstrap would happily accept
# "123" for the account that owns the dashboard — which holds the whole
# conversation history and the provider API keys.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# CORS. Note: credentialed requests (session cookies for the frontend login)
# cannot be combined with the wildcard origin — to use auth from a separate
# frontend origin, keep CORS_ALLOW_ALL_ORIGINS=False + list CORS_ALLOWED_ORIGINS
# and set CORS_ALLOW_CREDENTIALS=True.
#
# The wildcard is NOT the dev default: the dashboard API is unauthenticated,
# so `*` let any page the user happened to visit read the whole conversation
# history and rewrite the config (e.g. repoint ai.openai.base_url) from the
# browser. The dev frontend origins are allow-listed explicitly instead.
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:4173", "http://127.0.0.1:4173",
])
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=False)

# Allow the session cookie to ride cross-site requests in dev (frontend on a
# different port). Tighten/secure in production.
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", default="Lax")

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": PROJECT_ROOT / "data" / "vtuber.db",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Auto-discover templates + static directories shipped by module plugins
# (``modules/plugins/<name>/templates`` and ``modules/plugins/<name>/static``).
# Plugins are sub-packages of the ``modules`` app, not installed apps
# themselves, so Django's APP_DIRS / AppDirectoriesFinder won't pick
# them up unless we register their paths explicitly.
_MODULE_PLUGINS_DIR = BASE_DIR / "modules" / "plugins"
_MODULE_TEMPLATE_DIRS = [
    p for p in _MODULE_PLUGINS_DIR.glob("*/templates") if p.is_dir()
] if _MODULE_PLUGINS_DIR.is_dir() else []
_MODULE_STATIC_DIRS = [
    p for p in _MODULE_PLUGINS_DIR.glob("*/static") if p.is_dir()
] if _MODULE_PLUGINS_DIR.is_dir() else []

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": _MODULE_TEMPLATE_DIRS,
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = list(_MODULE_STATIC_DIRS)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Align ORM __date bucketing with the wall clock used by the circadian /
# sleep / journal logic (which reasons in naive local time). Without this,
# Django's default TIME_ZONE ("America/Chicago") shifts day boundaries ~7h.
TIME_ZONE = env("TIME_ZONE", default="Europe/Paris")
USE_TZ = True

# --- VTuber settings ---
CLAUDE_OAUTH_TOKEN = env("CLAUDE_OAUTH_TOKEN", default="")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
TELEGRAM_TOKEN = env("TELEGRAM_TOKEN", default="")
VTUBER_NAME = env("VTUBER_NAME", default="Mika")
CLAUDE_MODEL = env("CLAUDE_MODEL", default="claude-opus-4-6")
CLAUDE_MODEL_LIGHT = env("CLAUDE_MODEL_LIGHT", default="claude-sonnet-4-5")

# --- Multi-provider AI ---
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", default="")  # For Azure/custom endpoints
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://localhost:11434")

# Role → provider:model mapping (defaults to Claude if not set)
AI_ROLE_CONVERSATION = env("AI_ROLE_CONVERSATION", default=f"claude:{CLAUDE_MODEL}")
AI_ROLE_CONVERSATION_TOOLS = env("AI_ROLE_CONVERSATION_TOOLS", default=f"claude:{CLAUDE_MODEL}")
AI_ROLE_EMAIL_TRIAGE = env("AI_ROLE_EMAIL_TRIAGE", default=f"claude:{CLAUDE_MODEL_LIGHT}")
AI_ROLE_SIGNAL_INTERPRETATION = env("AI_ROLE_SIGNAL_INTERPRETATION", default=f"claude:{CLAUDE_MODEL_LIGHT}")
AI_ROLE_MEMORY_EXTRACTION = env("AI_ROLE_MEMORY_EXTRACTION", default=f"claude:{CLAUDE_MODEL_LIGHT}")
AI_ROLE_VALIDITY_CHECK = env("AI_ROLE_VALIDITY_CHECK", default=f"claude:{CLAUDE_MODEL_LIGHT}")

MEMORY_SHORT_TERM_LIMIT = env.int("MEMORY_SHORT_TERM_LIMIT", default=20)
API_PORT = env.int("API_PORT", default=8000)
# Loopback by default: the dashboard exposes the conversation history and the
# config editor (with provider API keys) and is unauthenticated unless
# DASHBOARD_REQUIRE_AUTH is on. Set API_HOST=0.0.0.0 to serve the LAN — run.py
# warns when that is combined with no auth gate.
API_HOST = env("API_HOST", default="127.0.0.1")
# When True, /dashboard/ (pages + API) requires an authenticated staff user.
# Off by default so a fresh single-user install isn't locked out of its own
# admin before a superuser exists.
DASHBOARD_REQUIRE_AUTH = env.bool("DASHBOARD_REQUIRE_AUTH", default=False)
AI_CALL_TIMEOUT = env.int("AI_CALL_TIMEOUT", default=60)

# When True, owned WebSocket consumers must be authenticated (else connection
# is refused). External modules (Telegram, ...) authenticate via their own API.
#
# On by default: the frontend is the one channel where Mika can be *certain*
# who she is talking to, and the whole identity-certainty model is built on
# that. An anonymous browser tab is indistinguishable from any other, so
# nothing it says can ever be attached to a person with confidence.
#
# The first-run lock-out this would normally cause is handled by
# POST /auth/bootstrap, which creates the initial account and then disables
# itself permanently (see communication/views.py).
CONSUMER_REQUIRE_AUTH = env.bool("CONSUMER_REQUIRE_AUTH", default=True)

# Person ids treated as the operator/owner — they see private module context
# (unread emails, pending wakes). Authenticated users (user_*) and Mika's own
# internal channels are always trusted; this adds extras (e.g. your tg_<id>).
OWNER_PERSON_IDS = env.list("OWNER_PERSON_IDS", default=[])

PERSONALITY_PATH = PROJECT_ROOT / "personality.yaml"

# --- AI Quota / Limiter ---
# Token budgets act as a circuit breaker: when a counter would be
# pushed past its cap, ``ai.quota.QuotaTracker.check`` raises
# ``QuotaExceeded`` *before* the LLM call. 0 = unlimited.
# Global caps apply to every call; per-role caps apply on top for a
# specific AIRole. Per-project caps live on ``Project.monthly_token_budget``.
AI_QUOTA_DAILY_TOKENS = env.int("AI_QUOTA_DAILY_TOKENS", default=0)
AI_QUOTA_MONTHLY_TOKENS = env.int("AI_QUOTA_MONTHLY_TOKENS", default=0)

# Per-role overrides. Add as many as you need. Role names match
# ``AIRole`` values uppercased (conversation → AI_QUOTA_ROLE_CONVERSATION_*).
AI_QUOTA_ROLE_CONVERSATION_DAILY = env.int("AI_QUOTA_ROLE_CONVERSATION_DAILY", default=0)
AI_QUOTA_ROLE_CONVERSATION_MONTHLY = env.int("AI_QUOTA_ROLE_CONVERSATION_MONTHLY", default=0)
AI_QUOTA_ROLE_CONVERSATION_TOOLS_DAILY = env.int("AI_QUOTA_ROLE_CONVERSATION_TOOLS_DAILY", default=0)
AI_QUOTA_ROLE_CONVERSATION_TOOLS_MONTHLY = env.int("AI_QUOTA_ROLE_CONVERSATION_TOOLS_MONTHLY", default=0)
AI_QUOTA_ROLE_EMAIL_TRIAGE_DAILY = env.int("AI_QUOTA_ROLE_EMAIL_TRIAGE_DAILY", default=0)
AI_QUOTA_ROLE_EMAIL_TRIAGE_MONTHLY = env.int("AI_QUOTA_ROLE_EMAIL_TRIAGE_MONTHLY", default=0)
AI_QUOTA_ROLE_SIGNAL_INTERPRETATION_DAILY = env.int("AI_QUOTA_ROLE_SIGNAL_INTERPRETATION_DAILY", default=0)
AI_QUOTA_ROLE_SIGNAL_INTERPRETATION_MONTHLY = env.int("AI_QUOTA_ROLE_SIGNAL_INTERPRETATION_MONTHLY", default=0)
AI_QUOTA_ROLE_MEMORY_EXTRACTION_DAILY = env.int("AI_QUOTA_ROLE_MEMORY_EXTRACTION_DAILY", default=0)
AI_QUOTA_ROLE_MEMORY_EXTRACTION_MONTHLY = env.int("AI_QUOTA_ROLE_MEMORY_EXTRACTION_MONTHLY", default=0)
AI_QUOTA_ROLE_VALIDITY_CHECK_DAILY = env.int("AI_QUOTA_ROLE_VALIDITY_CHECK_DAILY", default=0)
AI_QUOTA_ROLE_VALIDITY_CHECK_MONTHLY = env.int("AI_QUOTA_ROLE_VALIDITY_CHECK_MONTHLY", default=0)
AI_QUOTA_ROLE_VISION_CAPTION_DAILY = env.int("AI_QUOTA_ROLE_VISION_CAPTION_DAILY", default=0)
AI_QUOTA_ROLE_VISION_CAPTION_MONTHLY = env.int("AI_QUOTA_ROLE_VISION_CAPTION_MONTHLY", default=0)

# --- Scheduler ---
CRON_TICK_INTERVAL = env.int("CRON_TICK_INTERVAL", default=60)  # seconds

# --- Email Module ---
IMAP_HOST = env("IMAP_HOST", default="")
IMAP_PORT = env.int("IMAP_PORT", default=993)
IMAP_USER = env("IMAP_USER", default="")
IMAP_PASSWORD = env("IMAP_PASSWORD", default="")
SMTP_HOST = env("SMTP_HOST", default="")
SMTP_PORT = env.int("SMTP_PORT", default=587)
SMTP_USER = env("SMTP_USER", default="")
SMTP_PASSWORD = env("SMTP_PASSWORD", default="")

# --- Forge (modules auto-gérés par l'IA, espace confiné) ---
FORGE_DIR = env("FORGE_DIR", default=str(PROJECT_ROOT / "data" / "forge_modules"))

# --- Contextual Memory ---
CHROMA_PERSIST_DIR = env("CHROMA_PERSIST_DIR", default=str(PROJECT_ROOT / "data" / "chromadb"))
CONSOLIDATION_INTERVAL = env.int("CONSOLIDATION_INTERVAL", default=60)  # seconds
MEMORY_DECAY_RATE = env.float("MEMORY_DECAY_RATE", default=0.95)  # per day
MEMORY_MIN_IMPORTANCE = env.float("MEMORY_MIN_IMPORTANCE", default=0.1)
MEMORY_RETRIEVAL_SOUVENIRS = env.int("MEMORY_RETRIEVAL_SOUVENIRS", default=5)
MEMORY_RETRIEVAL_CONNAISSANCES = env.int("MEMORY_RETRIEVAL_CONNAISSANCES", default=10)
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="paraphrase-multilingual-MiniLM-L12-v2")

# Emotional memory (snapshot aggregation)
EMOTION_SNAPSHOT_INTERVAL = env.int("EMOTION_SNAPSHOT_INTERVAL", default=30)
EMOTION_SNAPSHOT_RETENTION_DAYS = env.int("EMOTION_SNAPSHOT_RETENTION_DAYS", default=2)

# --- Emotion Engine ---
# Physics parameters (mass, stiffness, damping, impulse gain) are derived
# at runtime from the `temperament` block in personality.yaml.

# --- Conscience ---
CONSCIENCE_DECISION_INTERVAL = env.int("CONSCIENCE_DECISION_INTERVAL", default=30)
CONSCIENCE_COOLDOWN_SECONDS = env.int("CONSCIENCE_COOLDOWN_SECONDS", default=300)
CONSCIENCE_ACT_THRESHOLD = env.float("CONSCIENCE_ACT_THRESHOLD", default=0.5)

# --- Projects ---
# How many (system_prompt, user_prompt, response) triples to keep per
# project as a rolling buffer. Used for audit / debugging the runner's
# LLM calls. Setting this to 0 disables history capture entirely.
PROJECT_PROMPT_HISTORY_SIZE = env.int("PROJECT_PROMPT_HISTORY_SIZE", default=30)

# RSS Observer
# Format: comma-separated "name|url" pairs, e.g. "Tech|https://example.com/rss,Gaming|https://other.com/feed"
_rss_raw = env("RSS_FEEDS", default="")
RSS_FEEDS = []
if _rss_raw:
    for entry in _rss_raw.split(","):
        entry = entry.strip()
        if "|" in entry:
            name, url = entry.split("|", 1)
            RSS_FEEDS.append({"name": name.strip(), "url": url.strip()})
        elif entry:
            RSS_FEEDS.append({"name": entry, "url": entry})
RSS_POLL_INTERVAL = env.int("RSS_POLL_INTERVAL", default=600)

# --- Logging ---
# Format: timestamp [request_id] level module: message
# request_id is "-" for background tasks outside a pipeline call.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "pipeline.tracing.RequestIdFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(request_id)s] %(levelname)-8s %(name)s: %(message)s",
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # Silence noisy Django internals
        "django": {"level": "WARNING", "propagate": True},
        "django.request": {"level": "WARNING", "propagate": True},
        "uvicorn.access": {"level": "WARNING", "propagate": True},
        # Pipeline + AI at DEBUG so request traces are fully visible when needed
        "pipeline": {"level": "DEBUG", "propagate": True},
        "ai": {"level": "DEBUG", "propagate": True},
    },
}
