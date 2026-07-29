import os
import warnings
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

# Hardcoded `["*"]` until now — the one line in this file that opted out of
# the posture every other line argues for (loopback by default, no CORS
# wildcard, CSRF enforced, WebSocket origins allow-listed).
#
# `*` disables Django's Host header validation, which is what stops a
# request carrying `Host: evil.test` from making the app generate absolute
# URLs (password-reset links, redirects) pointing at an attacker's domain.
# It also makes the DEBUG-only `django-debug-toolbar`-style leaks reachable
# from any name that resolves to the box.
#
# Default covers the loopback names the app actually serves plus the LAN
# addresses someone setting API_HOST=0.0.0.0 means to use; override with
# ALLOWED_HOSTS in .env for a real deployment or a reverse proxy.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[
    "localhost", "127.0.0.1", "[::1]", ".localhost",
])
if env("API_HOST", default="127.0.0.1") not in ("127.0.0.1", "localhost", "::1"):
    # Serving the LAN: accept the host names that reach us there. Narrower
    # than `*` (still rejects a spoofed public domain) without demanding the
    # operator enumerate their own IP.
    ALLOWED_HOSTS += [".local", ".lan"]
    import socket as _socket

    try:
        _hostname = _socket.gethostname()
        ALLOWED_HOSTS += [_hostname, _socket.gethostbyname(_hostname)]
    except Exception:
        pass

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
    # Interface d'administration, rendue par le serveur.
    "GestionSysteme",
    "configs",
    "identity",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Only meaningful now that sessions carry authority: while every endpoint
    # was anonymous, a forged request bought an attacker nothing they couldn't
    # already do directly. With a logged-in owner session there are mutating
    # endpoints worth forging — the admin rewrites provider API keys.
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Must sit after AuthenticationMiddleware — it reads request.user.
    "GestionSysteme.middleware.GestionAuthMiddleware",
]

# CSRF cookie/origin settings live just after the CORS + session block below,
# because they derive their defaults from it.

# Django's admin login doubles as the GestionSystème login when the gate is on:
# both want a staff account, so there is no second credential to manage.
LOGIN_URL = env("LOGIN_URL", default="/admin/login/")

# Django ships these but does not enable them; without the list,
# `validate_password` is a no-op and /auth/bootstrap would happily accept
# "123" for the account that owns the admin — which holds the whole
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
# The wildcard is NOT the dev default: the admin is unauthenticated by default,
# so `*` let any page the user happened to visit read the whole conversation
# history and rewrite the config (e.g. repoint ai.openai.base_url) from the
# browser. The dev frontend origins are allow-listed explicitly instead.
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:4173", "http://127.0.0.1:4173",
])
# On by default, and it has to be: the frontend authenticates with a session
# cookie and every request goes out with `credentials: "include"`. Without
# `Access-Control-Allow-Credentials: true` in the response, the browser
# discards it — login failed with "invalid credentials" even when the
# credentials were right, because the client never got to read the 200.
#
# Safe here precisely because CORS_ALLOW_ALL_ORIGINS is False: credentials
# and a wildcard origin cannot be combined, and the allowed origins are
# listed explicitly above.
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)

# Allow the session cookie to ride cross-site requests in dev (frontend on a
# different port). Tighten/secure in production.
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", default="Lax")

# Origins allowed to submit a CSRF-protected request. Mirrors the CORS
# allow-list: "may talk to the backend" is one decision, not two.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=CORS_ALLOWED_ORIGINS)
# The SPA reads the token from the cookie to echo it in X-CSRFToken, so it
# cannot be HttpOnly. That is the standard Django SPA setup: the cookie is not
# the secret — the *matching pair* (cookie + header) is what a cross-site page
# cannot produce, since it can neither read the cookie nor set the header.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = env("CSRF_COOKIE_SAMESITE", default=SESSION_COOKIE_SAMESITE)

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

# SQLite, tuned for a process that is almost never idle.
#
# Six background loops write continuously (conscience 30s, consolidator 60s,
# sleep 60s, project runner 30s, module scheduler 1s, emotion snapshots), and
# every `sync_to_async` call runs in its own thread with its own connection.
# In the default `journal_mode=DELETE` a single writer blocks every reader,
# and Python's default 5s busy timeout then surfaces as `database is locked`.
#
# WAL lets readers proceed during a write, which is the actual access pattern
# here: a conversation turn reads memory/identity/projects while the loops
# keep writing. `synchronous=NORMAL` is the standard companion — durable
# against process crashes, only at risk on an OS-level crash, which is the
# right trade for an audit trail nobody would miss the last second of.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": PROJECT_ROOT / "data" / "vtuber.db",
        "OPTIONS": {
            "timeout": env.int("DB_LOCK_TIMEOUT", default=30),
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA foreign_keys=ON;"
                # Give the page cache room; the working set (souvenirs,
                # messages, identity) is small enough to mostly live in RAM.
                "PRAGMA cache_size=-32000;"
            ),
        },
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
VTUBER_NAME = env("VTUBER_NAME", default="Mika")

# --- Multi-provider AI ---

# Role → provider:model mapping (defaults to Claude if not set)

API_PORT = env.int("API_PORT", default=8000)
# Loopback by default: the admin exposes the conversation history and the
# config editor (with provider API keys) and is unauthenticated unless
# DASHBOARD_REQUIRE_AUTH is on. Set API_HOST=0.0.0.0 to serve the LAN — run.py
# warns when that is combined with no auth gate.
API_HOST = env("API_HOST", default="127.0.0.1")
# When True, /gestion/ requires an authenticated staff user.
# Off by default so a fresh single-user install isn't locked out of its own
# admin before a superuser exists.
DASHBOARD_REQUIRE_AUTH = env.bool("DASHBOARD_REQUIRE_AUTH", default=False)

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
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="paraphrase-multilingual-MiniLM-L12-v2")

# Emotional memory (snapshot aggregation)

# --- Emotion Engine ---
# Physics parameters (mass, stiffness, damping, impulse gain) are derived
# at runtime from the `temperament` block in personality.yaml.

# --- Conscience ---

# --- Projects ---
# How many (system_prompt, user_prompt, response) triples to keep per
# project as a rolling buffer. Used for audit / debugging the runner's
# LLM calls. Setting this to 0 disables history capture entirely.

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

# Django's own ``FileResponse`` always wraps the file in a *synchronous*
# iterator (``iter(lambda: filelike.read(block_size), b"")``), so served under
# ASGI every static file trips ``StreamingHttpResponse.__aiter__``'s warning
# about consuming a sync iterator asynchronously. Nothing in this codebase
# returns a streaming response, so the warning can only ever come from Django
# serving a file, where the sync read is what the class does by design and
# there is no async alternative to switch to. Filtered on the exact message so
# the mirror-image warning (an async iterator consumed synchronously, which
# *would* be our bug) still surfaces.
warnings.filterwarnings(
    "ignore",
    message="StreamingHttpResponse must consume synchronous iterators",
    category=Warning,
)
