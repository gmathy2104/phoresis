"""Root URLconf for the Phoresis project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from phoresis_core import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("", include(("gel_analyzer.urls", "gel_analyzer"), namespace="gel_analyzer")),
    path("healthz/", healthz.readiness, name="healthz"),
    path("healthz/celery/", healthz.celery_only, name="healthz_celery"),
    path("healthz/live/", healthz.liveness, name="healthz_live"),
    path("", include(("dashboard.urls", "dashboard"), namespace="dashboard")),
]

# Dev-only: serve user-uploaded media via runserver. In production Caddy
# intercepts /media/* and serves the files directly from the named volume
# (see docker/Caddyfile §"handle_path /media/*"), so this branch is dead code
# under DEBUG=False. Without these lines, dev runserver returns 404 on every
# uploaded image, even though the file lives at MEDIA_ROOT — Django won't
# serve MEDIA_URL on its own without an explicit URL pattern.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom error handlers
handler400 = "phoresis_core.error_handling.views.handler400"
handler403 = "phoresis_core.error_handling.views.handler403"
handler404 = "phoresis_core.error_handling.views.handler404"
handler500 = "phoresis_core.error_handling.views.handler500"
