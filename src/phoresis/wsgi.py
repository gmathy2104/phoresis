"""WSGI entry point — used by gunicorn in the web container (Phase 5)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")
application = get_wsgi_application()
