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
    "chat",
    "memory",
    "conscience",
    "modules",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True  # dev only

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

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- VTuber settings ---
CLAUDE_OAUTH_TOKEN = env("CLAUDE_OAUTH_TOKEN", default="")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
TELEGRAM_TOKEN = env("TELEGRAM_TOKEN", default="")
VTUBER_NAME = env("VTUBER_NAME", default="Mika")
CLAUDE_MODEL = env("CLAUDE_MODEL", default="claude-opus-4-6")
CLAUDE_MODEL_LIGHT = env("CLAUDE_MODEL_LIGHT", default="claude-sonnet-4-5")
MEMORY_SHORT_TERM_LIMIT = env.int("MEMORY_SHORT_TERM_LIMIT", default=20)
API_PORT = env.int("API_PORT", default=8000)
PERSONALITY_PATH = PROJECT_ROOT / "personality.yaml"

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
EMOTION_DECAY_RATE = env.float("EMOTION_DECAY_RATE", default=0.02)  # intensity lost per second
EMOTION_MOOD_SHIFT_RATE = env.float("EMOTION_MOOD_SHIFT_RATE", default=0.01)

# --- Conscience ---
CONSCIENCE_DECISION_INTERVAL = env.int("CONSCIENCE_DECISION_INTERVAL", default=30)
CONSCIENCE_COOLDOWN_SECONDS = env.int("CONSCIENCE_COOLDOWN_SECONDS", default=300)
CONSCIENCE_ACT_THRESHOLD = env.float("CONSCIENCE_ACT_THRESHOLD", default=0.5)

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
