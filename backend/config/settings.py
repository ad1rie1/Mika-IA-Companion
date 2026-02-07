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
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = env("TELEGRAM_TOKEN", default="")
VTUBER_NAME = env("VTUBER_NAME", default="Mika")
CLAUDE_MODEL = env("CLAUDE_MODEL", default="claude-sonnet-4-5-20250929")
MEMORY_SHORT_TERM_LIMIT = env.int("MEMORY_SHORT_TERM_LIMIT", default=20)
API_PORT = env.int("API_PORT", default=8000)
PERSONALITY_PATH = PROJECT_ROOT / "personality.yaml"
