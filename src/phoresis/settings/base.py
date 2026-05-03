"""
Base settings shared by all environments.

Phase 1 base.py is intentionally minimal — Django built-ins only.
Each Phoresis app appends itself to INSTALLED_APPS / MIDDLEWARE in its
own task. This keeps every intermediate commit able to boot via
`manage.py check` and `manage.py makemigrations`.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = BASE_DIR / "src"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "simple_history",
    # Phoresis apps are appended in their own tasks (4, 7, 11, 12).
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # ExceptionContextMiddleware is appended in Task 9.
]

ROOT_URLCONF = "phoresis.urls"
WSGI_APPLICATION = "phoresis.wsgi.application"
ASGI_APPLICATION = "phoresis.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "phoresis"),
        "USER": os.environ.get("DB_USER", "phoresis"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "phoresis"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# AUTH_USER_MODEL is set in Task 4 once accounts.User exists.

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Brussels"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
REDIS_DB_CELERY = os.environ.get("REDIS_DB_CELERY", "0")
REDIS_DB_CACHE = os.environ.get("REDIS_DB_CACHE", "1")
_REDIS_BASE = f"redis://{REDIS_HOST}:{REDIS_PORT}"

CELERY_BROKER_URL = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
CELERY_RESULT_BACKEND = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
CELERY_TASK_QUEUES = ("default", "heavy")
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{_REDIS_BASE}/{REDIS_DB_CACHE}",
    }
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Phase 1 — STALE_TASK_REGISTRY is empty until gel_analyzer lands in Phase 2.
STALE_TASK_TIMEOUT_HOURS = 2
