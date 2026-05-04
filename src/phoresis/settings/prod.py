"""Production settings — strict, no DEBUG, env-driven secrets."""

from .base import *


def _required_env(key: str) -> str:
    """Read a required env var, fail with a clear error message if missing."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Production setting requires env var {key!r}. "
            "Set it in .env (see install.ps1 / docs/INSTALL.md for the full list)."
        )
    return value


DEBUG = False
SECRET_KEY = _required_env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = [h.strip() for h in _required_env("DJANGO_ALLOWED_HOSTS").split(",") if h.strip()]

# CSRF_TRUSTED_ORIGINS is REQUIRED for any state-changing POST when behind a
# reverse proxy. Caddy serves on https://phoresis (or whatever DJANGO_BASE_URL
# the operator configured). Without this, every login / form submit returns
# 403 "Origin checking failed".
# Default: derive https://<host> for each ALLOWED_HOSTS entry. Operators can
# override via DJANGO_CSRF_TRUSTED_ORIGINS=https://foo.com,https://bar.com.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
] or [f"https://{h}" for h in ALLOWED_HOSTS]

# SECURE_PROXY_SSL_HEADER tells Django to trust the X-Forwarded-Proto header
# Caddy injects (Caddyfile sets this on the reverse proxy). Without it, Django
# sees the upstream request as plain HTTP and -- because SESSION_COOKIE_SECURE
# and CSRF_COOKIE_SECURE are True below -- silently drops the session cookie
# on the response. Symptom: user logs in, gets redirected, session cookie
# never sticks, infinite login loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
