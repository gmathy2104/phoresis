"""
URL routing for Gel Analyzer DRF API.
"""

from drf_spectacular.views import SpectacularRedocView, SpectacularSwaggerView
from rest_framework.permissions import IsAuthenticated
from rest_framework.routers import DefaultRouter

from django.urls import include, path

from gel_analyzer.api.views import (
    BandViewSet,
    GelAnalysisViewSet,
    GelImageViewSet,
    LadderTemplateViewSet,
    LaneViewSet,
    SavedComparisonViewSet,
    quantification_detail,
    quantification_history,
    quantification_preview,
    quantification_root,
)
from phoresis_core.api_schema import PhoresisSchemaView as GelAnalyzerSchemaView

app_name = "gel_analyzer_api"

router = DefaultRouter()
router.register(r"images", GelImageViewSet, basename="gel-image")
router.register(r"analyses", GelAnalysisViewSet, basename="gel-analysis")
router.register(r"lanes", LaneViewSet, basename="lane")
router.register(r"bands", BandViewSet, basename="band")
router.register(r"ladder-templates", LadderTemplateViewSet, basename="ladder-template")
router.register(r"comparisons", SavedComparisonViewSet, basename="saved-comparison")

quantification_urlpatterns = [
    path(
        "analyses/<uuid:analysis_id>/quantification/",
        quantification_root,
        name="quantification-root",
    ),
    path(
        "analyses/<uuid:analysis_id>/quantification/preview/",
        quantification_preview,
        name="quantification-preview",
    ),
    path(
        "analyses/<uuid:analysis_id>/quantification/history/",
        quantification_history,
        name="quantification-history",
    ),
    path(
        "analyses/<uuid:analysis_id>/quantification/<uuid:calib_id>/",
        quantification_detail,
        name="quantification-detail",
    ),
]

# drf-spectacular serves its Swagger and ReDoc views AllowAny by default: IsAuthenticated closes them.
urlpatterns = [
    # API v1 endpoints
    path("v1/", include(router.urls)),
    # Protein quantification (function-based; under v1/)
    path("v1/", include(quantification_urlpatterns)),
    # OpenAPI Schema
    path("schema/", GelAnalyzerSchemaView.as_view(), name="schema"),
    # Swagger UI
    path(
        "docs/",
        SpectacularSwaggerView.as_view(
            url_name="gel_analyzer:gel_analyzer_api:schema",
            permission_classes=[IsAuthenticated],
        ),
        name="swagger-ui",
    ),
    # ReDoc
    path(
        "redoc/",
        SpectacularRedocView.as_view(
            url_name="gel_analyzer:gel_analyzer_api:schema",
            permission_classes=[IsAuthenticated],
        ),
        name="redoc",
    ),
]
