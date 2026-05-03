"""Root URLconf for the Phoresis project.

App-specific includes are added in their respective tasks:
- accounts: Task 6
- dashboard: Task 11
"""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
