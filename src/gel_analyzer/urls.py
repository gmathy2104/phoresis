"""URL config for gel_analyzer (Phase 3 shells)."""

from django.urls import path

from .views import analyses as analysis_views
from .views import images as image_views

app_name = "gel_analyzer"

urlpatterns = [
    # Images
    path("images/", image_views.image_list_view, name="image_list"),
    path("images/upload/", image_views.image_upload_view, name="image_upload"),
    path("images/<uuid:pk>/", image_views.image_detail_view, name="image_detail"),
    path("images/<uuid:pk>/delete/", image_views.image_delete_view, name="image_delete"),
    # Analyses
    path("analyses/", analysis_views.analysis_list_view, name="analysis_list"),
    path("images/<uuid:image_pk>/analyses/create/", analysis_views.analysis_create_view, name="analysis_create"),
    # Phase 4 will add: analyses/<uuid:pk>/, analyses/<uuid:pk>/annotate/, api/...
]
