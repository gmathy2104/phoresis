"""ASGI entry point — reserved for future async views/SSE."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")
application = get_asgi_application()
