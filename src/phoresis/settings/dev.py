"""Development settings — local Postgres, DEBUG=True."""

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "phoresis"]

# Phase 1: keep manifest storage off in dev to avoid collectstatic friction.
# Reconstruct STORAGES (rather than mutating the dict imported from base) so that
# importing both dev and another settings module in the same process can't
# corrupt the staticfiles backend reference.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

INTERNAL_IPS = ["127.0.0.1"]

# Print emails to the runserver console rather than trying to deliver via SMTP.
# Without this, any code path that calls send_mail() (password reset flow, our
# error notifications, etc.) blocks for ~30s on a connection to localhost:25
# and ultimately fails — annoying in dev and a real footgun if the message is
# triggered from inside a web request (the user just sees a hung page).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
