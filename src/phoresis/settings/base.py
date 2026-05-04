"""
Base settings shared by all environments.

Phase 1 base.py is intentionally minimal — Django built-ins only.
Each Phoresis app appends itself to INSTALLED_APPS / MIDDLEWARE in its
own task. This keeps every intermediate commit able to boot via
`manage.py check` and `manage.py makemigrations`.
"""

import os
from pathlib import Path

# settings/base.py lives at src/phoresis/settings/base.py.
# parents[0]=settings/, parents[1]=phoresis/, parents[2]=src/, parents[3]=repo root.
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
    "drf_spectacular",
    "django_filters",
    "simple_history",
    # Phoresis apps
    "phoresis_core",
    "accounts",
    "gel_analyzer",
    "dashboard",
    "phoresis_ui",
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
    "phoresis_core.error_handling.middleware.ExceptionContextMiddleware",
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
AUTH_USER_MODEL = "accounts.User"

# DRF / drf-spectacular base configuration. Without DEFAULT_SCHEMA_CLASS
# pointing at drf-spectacular's AutoSchema, GET /api/schema/ raises
# AssertionError when introspecting other DRF views (e.g. SpectacularSwaggerView).
# Test settings layer in higher throttle rates on top of this dict.
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Brussels"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
# STATIC_ROOT / MEDIA_ROOT are env-overridable so the Docker image can point
# them at /srv/{staticfiles,media} (writable volumes) without a code change.
# The dev/local default keeps everything inside the repo for convenience.
STATIC_ROOT = os.environ.get("STATIC_ROOT") or (BASE_DIR / "staticfiles")
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or (BASE_DIR / "media")

REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
REDIS_DB_CELERY = os.environ.get("REDIS_DB_CELERY", "0")
REDIS_DB_CACHE = os.environ.get("REDIS_DB_CACHE", "1")
_REDIS_BASE = f"redis://{REDIS_HOST}:{REDIS_PORT}"

CELERY_BROKER_URL = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
CELERY_RESULT_BACKEND = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
# Celery's `task_queues` setting expects a sequence of kombu.Queue OBJECTS
# (it iterates and accesses `q.name`). Passing strings raises AttributeError
# at worker startup. Easier path: just don't declare static queues -- let
# `task_create_missing_queues=True` (Celery default) auto-create whatever
# the `-Q default,heavy` CLI flag asks for at boot.
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_CREATE_MISSING_QUEUES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Recycle each worker child after this many tasks to mitigate memory creep —
# the ML services (band detection, SAM, densitometry) load ~100 MB ONNX models
# per child, and over hours of uptime the prefork children gradually retain
# arena pages they could release. 50 tasks ≈ a few hours of typical lab use.
CELERY_WORKER_MAX_TASKS_PER_CHILD = int(os.environ.get("CELERY_WORKER_MAX_TASKS_PER_CHILD", "50"))
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
