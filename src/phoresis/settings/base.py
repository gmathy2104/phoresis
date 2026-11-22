"""
Base settings shared by all environments.

Phase 1 base.py is intentionally minimal — Django built-ins only.
Each Phoresis app appends itself to INSTALLED_APPS / MIDDLEWARE in its
own task. This keeps every intermediate commit able to boot via
`manage.py check` and `manage.py makemigrations`.
"""

import os
from pathlib import Path
from urllib.parse import quote

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
    "guided_tours",
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

# Allow login with email OR username. install.ps1 asks the operator for an
# email and create_initial_users derives `username = local-part-of-email`,
# so users naturally try to log in with the email they entered -- and the
# default ModelBackend (username-only) refuses. Our backend tries email
# first (case-insensitive), then username.
AUTHENTICATION_BACKENDS = [
    "accounts.backends.EmailOrUsernameModelBackend",
]

# DRF / drf-spectacular base configuration. Without DEFAULT_SCHEMA_CLASS
# pointing at drf-spectacular's AutoSchema, GET /api/schema/ raises
# AssertionError when introspecting other DRF views (e.g. SpectacularSwaggerView).
# Test settings layer in higher throttle rates on top of this dict.
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Throttle rates for the custom scopes declared in
    # gel_analyzer/api/throttles.py. Without these keys, every
    # v1-viewset write request (Bands, Lanes, GelImages, GelAnalysis,
    # LadderTemplates, SavedComparisons) crashes in DRF's get_throttles()
    # with ImproperlyConfigured: "No default throttle rate set for
    # 'user_write' scope". Numbers tuned for a single-user laptop
    # deployment: ~5 writes/min and 1 heavy compute/min covers a busy
    # annotation session, low enough that a runaway client gets caught.
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/hour",
        "user_write": "300/hour",
        "user_computation": "60/hour",
    },
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
# REDIS_PASSWORD is optional: the Docker stack's Redis is internal to its network and has none,
# the macOS install (scripts/mac/phoresis.sh) runs its own password-protected Redis on 127.0.0.1.
# Quoted, so any character is safe in the URL.
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
_REDIS_AUTH = f":{quote(REDIS_PASSWORD, safe='')}@" if REDIS_PASSWORD else ""
_REDIS_BASE = f"redis://{_REDIS_AUTH}{REDIS_HOST}:{REDIS_PORT}"

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

# Periodic tasks. Run by `celery beat` (the `scheduler` container). The
# orphan-purge sweeps GelImage rows uploaded but never wired to an analysis
# (closed-tab leaks). Default schedule: once per day at 03:30 local time —
# off-peak relative to the Watchtower 03:00 image refresh, so the two
# don't fight for resources at the same minute. The boot trigger lives in
# phoresis_core.celery_app via the worker_ready signal so a fresh restart
# doesn't have to wait until 03:30 to clear last-night's orphans.
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "purge-orphan-gel-images-daily": {
        "task": "gel_analyzer.tasks.purge_orphan_gel_images",
        "schedule": crontab(hour=3, minute=30),
        "options": {"queue": "default"},
    },
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{_REDIS_BASE}/{REDIS_DB_CACHE}",
    }
}

# ── Media on two disks (opt-in; docs/INSTALL-MAC.md, phoresis_core/media_tiers.py) ──
# MEDIA_ROOT stays the fast disk every upload is written to. When PHORESIS_MEDIA_ARCHIVE_ROOT names a
# folder on a second disk (an external drive on the Mac), a nightly task moves the oldest files of the
# prefixes below there once MEDIA_ROOT outgrows its quota, and the storage reads them back from either
# place under the same name: no row changes. Unset (Windows / Docker), it is a plain FileSystemStorage.
PHORESIS_MEDIA_ARCHIVE_ROOT = os.environ.get("PHORESIS_MEDIA_ARCHIVE_ROOT", "").strip()


def _env_gb(key: str, default: str) -> int:
    """A size given in GB (decimals allowed), in bytes."""
    return int(float(os.environ.get(key) or default) * 1024**3)


# Size MEDIA_ROOT may reach before the oldest archivable files leave for the archive disk.
PHORESIS_MEDIA_HOT_QUOTA_BYTES = _env_gb("PHORESIS_MEDIA_HOT_QUOTA_GB", "50")
# Free space to keep on MEDIA_ROOT's disk, whatever fills it (the quota only counts media).
PHORESIS_MEDIA_MIN_FREE_BYTES = _env_gb("PHORESIS_MEDIA_MIN_FREE_GB", "20")
# Free space to keep on the archive disk: archiving stops there rather than filling it.
PHORESIS_MEDIA_ARCHIVE_MIN_FREE_BYTES = _env_gb("PHORESIS_MEDIA_ARCHIVE_MIN_FREE_GB", "5")
# A file younger than this stays on the fast disk: gels being worked on are never the ones moved.
PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS = int(os.environ.get("PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS") or "30")
# What may be archived, in order. Originals are the bulk (16-bit scanner files) and are only read to
# re-process a gel; display PNGs and thumbnails stay, so an old gel still shows with the disk unplugged.
PHORESIS_MEDIA_ARCHIVE_PREFIXES = [
    p.strip()
    for p in os.environ.get("PHORESIS_MEDIA_ARCHIVE_PREFIXES", "gel_images/originals/").split(",")
    if p.strip()
]

STORAGES = {
    "default": {
        "BACKEND": "phoresis_core.media_tiers.TieredMediaStorage"
        if PHORESIS_MEDIA_ARCHIVE_ROOT
        else "django.core.files.storage.FileSystemStorage"
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if PHORESIS_MEDIA_ARCHIVE_ROOT:
    # 04:15: after the Mac's nightly backup (02:30) and the orphan purge (03:30).
    CELERY_BEAT_SCHEDULE["archive-media-nightly"] = {
        "task": "phoresis_core.tasks.archive_media",
        "schedule": crontab(hour=4, minute=15),
        "options": {"queue": "default"},
    }

# Phase 1 — STALE_TASK_REGISTRY is empty until gel_analyzer lands in Phase 2.
STALE_TASK_TIMEOUT_HOURS = 2

# Densitometry saturation flag: a band is "saturated" when MORE than this share (0-1) of the pixels its
# area was measured on sit at the end of the image's scale (gel_analyzer/services/densitometry/saturation.py).
# A warning only: the areas are never corrected. Read at every display and export, so a new value needs
# no re-run; 0 flags any saturated pixel.
GEL_ANALYZER_SATURATED_PIXEL_THRESHOLD = float(os.environ.get("GEL_ANALYZER_SATURATED_PIXEL_THRESHOLD", "0.01"))

# Band model -- run IN THE BROWSER by the annotation editor, after the lane model (WebGPU first, CPU
# fallback). sha256 is the identity of the shipped file: gel_analyzer's system check
# (gel_analyzer/checks.py) refuses a file that does not match it. The file comes from ds-hub-django,
# where it is trained and exported; a new model means a new file AND its sha256 here.
GEL_ANALYZER_BAND_MODEL = {
    "name": "gel-seg bands-only 2026-10-23, Gels pass 1 iteration 1 (yolo11l-seg, 1280)",
    "static_path": "gel_analyzer/ml/bands_2026-10-23.onnx",
    "sha256": "1e704b600444603f5ab160d828410b5dd9abe166c4ada7b38e1d02fff2224ea7",
    # The model the file was exported from (its weights digest, in ds-hub-django's ml_annotator).
    "source_sha256": "f1ccc2d94fd2ffeccddbb0c6389a99629796f2de4d9d756fe338288ea64f1c9d",
    "class_names": ["band"],
    # The size it was TRAINED at: at another size the bands reach it at a scale it never learned.
    "imgsz": 1280,
    # Proposals under this score are not shown; the panel's slider moves it.
    "confidence": 0.25,
    # The slider's floor: the browser sends every box from this score up, and the slider filters them on the page.
    "min_confidence": 0.05,
    # NMS overlap: two distinct bands never share half their box.
    "iou": 0.5,
    # ultralytics keeps 300 by default, and dense gels carry 376 to 500 bands.
    "max_det": 2000,
}
