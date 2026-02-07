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
        "NAME": PROJECT_ROOT / "vtuber.db",
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
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- VTuber settings ---
CLAUDE_OAUTH_TOKEN = env("CLAUDE_OAUTH_TOKEN", default="")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
TELEGRAM_TOKEN = env("TELEGRAM_TOKEN", default="")
VTUBER_NAME = env("VTUBER_NAME", default="Mika")
CLAUDE_MODEL = env("CLAUDE_MODEL", default="claude-sonnet-4-5-20250929")
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
CONSOLIDATION_INTERVAL = env.int("CONSOLIDATION_INTERVAL", default=300)  # seconds
MEMORY_DECAY_RATE = env.float("MEMORY_DECAY_RATE", default=0.95)  # per day
MEMORY_MIN_IMPORTANCE = env.float("MEMORY_MIN_IMPORTANCE", default=0.1)
MEMORY_RETRIEVAL_SOUVENIRS = env.int("MEMORY_RETRIEVAL_SOUVENIRS", default=5)
MEMORY_RETRIEVAL_CONNAISSANCES = env.int("MEMORY_RETRIEVAL_CONNAISSANCES", default=10)
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="paraphrase-multilingual-MiniLM-L12-v2")
HAIKU_MODEL = env("HAIKU_MODEL", default="claude-haiku-4-5-20251001")

# --- Emotion Engine ---
EMOTION_DECAY_RATE = env.float("EMOTION_DECAY_RATE", default=0.02)  # intensity lost per second
EMOTION_MOOD_SHIFT_RATE = env.float("EMOTION_MOOD_SHIFT_RATE", default=0.01)
