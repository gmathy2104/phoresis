"""Test settings — eager Celery, fast password hasher, in-memory cache."""

from .base import *

DEBUG = False
SECRET_KEY = "test-secret-not-secret"
ALLOWED_HOSTS = ["*"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
