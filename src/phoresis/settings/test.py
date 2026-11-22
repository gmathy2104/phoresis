"""Test settings — eager Celery, fast password hasher, in-memory cache."""

from .base import *

DEBUG = False
SECRET_KEY = "test-secret-not-secret"
ALLOWED_HOSTS = ["*"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# No lockout while testing (client.login() passes no request, and a suite full of deliberate bad
# passwords would lock itself out); the lockout tests turn it back on.
AXES_ENABLED = False

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# DRF settings for tests — Phoresis does not yet ship a base REST_FRAMEWORK
# block, so define the bare minimum (pagination, schema class, throttle rates)
# here. Throttle rates are very high so throttling never trips during tests.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "user": "100000/hour",
        "user_write": "100000/hour",
        "user_computation": "100000/hour",
    },
}
