"""Production settings — strict, no DEBUG, env-driven secrets."""
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # noqa: F405 — must be set in prod
ALLOWED_HOSTS = [h.strip() for h in os.environ["DJANGO_ALLOWED_HOSTS"].split(",") if h.strip()]  # noqa: F405

SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
