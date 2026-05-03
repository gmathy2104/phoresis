"""Root URLconf for the Phoresis project.

App-specific includes are added in their respective tasks:
- accounts: this task
- dashboard: Task 11
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
]
