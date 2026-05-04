"""
URL routing for Gel Analyzer DRF API.
"""

from drf_spectacular.views import SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from django.urls import include, path

from gel_analyzer.api.views import (
    BandViewSet,
    GelAnalysisViewSet,
    GelImageViewSet,
    LadderTemplateViewSet,
    LaneViewSet,
    SavedComparisonViewSet,
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

urlpatterns = [
    # API v1 endpoints
    path("v1/", include(router.urls)),
    # OpenAPI Schema
    path("schema/", GelAnalyzerSchemaView.as_view(), name="schema"),
    # Swagger UI
    path("docs/", SpectacularSwaggerView.as_view(url_name="gel_analyzer:gel_analyzer_api:schema"), name="swagger-ui"),
    # ReDoc
    path("redoc/", SpectacularRedocView.as_view(url_name="gel_analyzer:gel_analyzer_api:schema"), name="redoc"),
]
