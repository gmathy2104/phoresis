"""Root URLconf for the Phoresis project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("", include(("gel_analyzer.urls", "gel_analyzer"), namespace="gel_analyzer")),
    path("", include(("dashboard.urls", "dashboard"), namespace="dashboard")),
]
