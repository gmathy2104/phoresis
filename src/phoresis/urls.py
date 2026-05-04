"""Root URLconf for the Phoresis project."""

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

# Custom error handlers
handler400 = "phoresis_core.error_handling.views.handler400"
handler403 = "phoresis_core.error_handling.views.handler403"
handler404 = "phoresis_core.error_handling.views.handler404"
handler500 = "phoresis_core.error_handling.views.handler500"
