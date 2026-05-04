"""
DRF ViewSets for Gel Analyzer API.
"""

import dataclasses

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status as drf_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from gel_analyzer.api.filters import (
    BandFilter,
    GelAnalysisFilter,
    GelImageFilter,
    LadderTemplateFilter,
    LaneFilter,
    SavedComparisonFilter,
)
from gel_analyzer.api.serializers import (
    BandSerializer,
    BandWriteSerializer,
    DensitometryJobSerializer,
    GelAnalysisDetailSerializer,
    GelAnalysisListSerializer,
    GelAnalysisWriteSerializer,
    GelImageDetailSerializer,
    GelImageListSerializer,
    GelImageUploadSerializer,
    LadderTemplateDetailSerializer,
    LadderTemplateListSerializer,
    LaneSerializer,
    LaneWriteSerializer,
    SavedComparisonSerializer,
)
from gel_analyzer.api.throttles import ComputationRateThrottle, WriteRateThrottle
from gel_analyzer.models import (
    Band,
    DensitometryJob,
    DensitometryResult,
    GelAnalysis,
    GelImage,
    LadderTemplate,
    Lane,
    LaneDensitometrySummary,
    SavedComparison,
)

VALID_STATUS_TRANSITIONS = {
    "DRAFT": ["IN_PROGRESS"],
    "IN_PROGRESS": ["COMPLETED", "DRAFT"],
    "COMPLETED": ["APPROVED", "REJECTED", "IN_PROGRESS"],
    "APPROVED": [],
    "REJECTED": ["IN_PROGRESS"],
}


@extend_schema_view(
    list=extend_schema(summary="List Gel Images", tags=["Gel Images"]),
    retrieve=extend_schema(summary="Get Gel Image Details", tags=["Gel Images"]),
    create=extend_schema(
        summary="Upload Gel Image",
        tags=["Gel Images"],
        description="Upload a gel image (GEL/SCN/TIFF/PNG/JPEG). Generates display PNG and thumbnail.",
    ),
    partial_update=extend_schema(summary="Update Gel Image", tags=["Gel Images"]),
    destroy=extend_schema(summary="Delete Gel Image", tags=["Gel Images"]),
)
class GelImageViewSet(viewsets.ModelViewSet):
    """ViewSet for GelImage -- full CRUD with Azure-safe URLs."""

    queryset = GelImage.objects.all().order_by("-uploaded_at")
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = GelImageFilter
    search_fields = ["original_filename"]
    ordering_fields = ["uploaded_at", "original_filename"]
    ordering = ["-uploaded_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GelImageDetailSerializer
        if self.action == "create":
            return GelImageUploadSerializer
        return GelImageListSerializer

    def get_throttles(self):
        if self.action in ("create", "partial_update", "destroy"):
            return [WriteRateThrottle()]
        return super().get_throttles()

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


# =============================================================================
# GelAnalysis ViewSet
# =============================================================================


@extend_schema_view(
    list=extend_schema(summary="List Analyses", tags=["Gel Analyses"]),
    retrieve=extend_schema(summary="Get Analysis Details (Full Tree)", tags=["Gel Analyses"]),
    create=extend_schema(summary="Create Analysis", tags=["Gel Analyses"]),
    partial_update=extend_schema(summary="Update Analysis", tags=["Gel Analyses"]),
    destroy=extend_schema(summary="Delete Analysis", tags=["Gel Analyses"]),
)
class GelAnalysisViewSet(viewsets.ModelViewSet):
    """ViewSet for GelAnalysis — full CRUD with nested lanes/bands tree."""

    queryset = GelAnalysis.objects.select_related("gel_image").order_by("-created_at")
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = GelAnalysisFilter
    search_fields = ["name"]
    ordering_fields = ["created_at", "status"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GelAnalysisDetailSerializer
        if self.action in ("create", "partial_update"):
            return GelAnalysisWriteSerializer
        return GelAnalysisListSerializer

    def get_throttles(self):
        if self.action in ("create", "partial_update", "destroy"):
            return [WriteRateThrottle()]
        return super().get_throttles()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(summary="Transition Analysis Status", tags=["Gel Analyses"])
    @action(detail=True, methods=["post"], url_path="status")
    def status_transition(self, request, pk=None):
        """Transition analysis status with validation."""
        analysis = self.get_object()
        new_status = request.data.get("status")
        if not new_status:
            return Response(
                {"detail": "status field is required."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        valid = VALID_STATUS_TRANSITIONS.get(analysis.status, [])
        if new_status not in valid:
            return Response(
                {"detail": f"Cannot transition from {analysis.status} to {new_status}. Valid: {valid}"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        analysis.status = new_status
        analysis.save(update_fields=["status"])
        return Response(GelAnalysisListSerializer(analysis).data)

    # -----------------------------------------------------------------
    # Calibration
    # -----------------------------------------------------------------

    @extend_schema(summary="Get Stored Calibration", tags=["Calibration"])
    @action(detail=True, methods=["get"], url_path="calibration")
    def calibration(self, request, pk=None):
        """Get stored MW calibration data."""
        analysis = self.get_object()
        cal = analysis.ladder_calibrations.select_related("template").first()
        if not cal:
            return Response(
                {"detail": "No calibration data."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "id": str(cal.id),
                "method": cal.method,
                "coefficients": cal.coefficients,
                "r_squared": cal.r_squared,
                "matched_band_count": cal.matched_band_count,
                "band_matches": cal.band_matches,
                "template_name": cal.template.name if cal.template else None,
            }
        )

    # -----------------------------------------------------------------
    # Detection
    # -----------------------------------------------------------------

    @extend_schema(summary="Trigger Band Detection (Async)", tags=["Detection"])
    @action(detail=True, methods=["post"], url_path="detect-bands", throttle_classes=[ComputationRateThrottle])
    def detect_bands(self, request, pk=None):
        """Trigger async band detection for all lanes in this analysis."""
        analysis = self.get_object()
        from gel_analyzer.tasks import detect_bands_bulk_task

        task = detect_bands_bulk_task.delay(
            str(analysis.id),
            params_dict=request.data.get("params", {}),
            user_id=request.user.id,
            save_results=request.data.get("save_results", False),
        )
        return Response(
            {"task_id": task.id, "status": "PENDING"},
            status=drf_status.HTTP_202_ACCEPTED,
        )

    @extend_schema(summary="Get Default Detection Parameters", tags=["Detection"])
    @action(detail=False, methods=["get"], url_path="detection-params")
    def detection_params(self, request):
        """Return default BandDetectionParams as JSON."""
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        params = BandDetectionParams()
        return Response(dataclasses.asdict(params))

    # -----------------------------------------------------------------
    # Densitometry
    # -----------------------------------------------------------------

    @extend_schema(summary="Get Densitometry Results", tags=["Densitometry"])
    @action(detail=True, methods=["get"], url_path="densitometry")
    def densitometry_results(self, request, pk=None):
        """Get stored densitometry for all lanes."""
        analysis = self.get_object()
        lanes = Lane.objects.filter(analysis=analysis).order_by("lane_number")
        results = []
        for lane in lanes:
            try:
                summary = LaneDensitometrySummary.objects.get(lane=lane)
                band_results = []
                for band in lane.bands.all():
                    try:
                        dr = DensitometryResult.objects.get(band=band)
                        band_results.append(
                            {
                                "band_id": str(band.id),
                                "peak_center_y": dr.peak_center_y,
                                "peak_amplitude": dr.peak_amplitude,
                                "fwhm": dr.fwhm,
                                "corrected_area": dr.corrected_area,
                                "relative_percent_lane": dr.relative_percent_lane,
                                "fit_r_squared": dr.fit_r_squared,
                                "snr": dr.snr,
                            }
                        )
                    except DensitometryResult.DoesNotExist:
                        pass
                results.append(
                    {
                        "lane_id": lane.id,
                        "lane_number": lane.lane_number,
                        "poi_percentage": summary.poi_percentage,
                        "total_integrated_area": summary.total_integrated_area,
                        "band_count": summary.band_count,
                        "bands": band_results,
                        "profile_data": summary.profile_data,
                    }
                )
            except LaneDensitometrySummary.DoesNotExist:
                pass
        if not results:
            return Response(
                {"detail": "No densitometry data."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        return Response({"analysis_id": str(analysis.id), "lanes": results})

    @extend_schema(summary="Run Densitometry (Async)", tags=["Densitometry"])
    @action(detail=True, methods=["post"], url_path="densitometry/run", throttle_classes=[ComputationRateThrottle])
    def run_densitometry(self, request, pk=None):
        """Trigger async densitometry."""
        analysis = self.get_object()
        from gel_analyzer.tasks import run_densitometry_task

        job = DensitometryJob.objects.create(
            analysis=analysis,
            params=request.data.get("params", {}),
            lane_ids=request.data.get("lane_ids", []),
            created_by=request.user,
        )
        task = run_densitometry_task.delay(
            str(analysis.id),
            params_dict=job.params,
            user_id=request.user.id,
            lane_ids=job.lane_ids or None,
            job_id=str(job.id),
        )
        job.task_id = task.id
        job.save(update_fields=["task_id"])
        return Response(
            DensitometryJobSerializer(job).data,
            status=drf_status.HTTP_202_ACCEPTED,
        )

    @extend_schema(summary="Poll Densitometry Job", tags=["Densitometry"])
    @action(detail=True, methods=["get"], url_path=r"densitometry/jobs/(?P<job_id>[0-9a-f-]+)")
    def densitometry_job(self, request, pk=None, job_id=None):
        """Poll densitometry job status."""
        try:
            job = DensitometryJob.objects.get(id=job_id, analysis_id=pk)
            return Response(DensitometryJobSerializer(job).data)
        except DensitometryJob.DoesNotExist:
            return Response(
                {"detail": "Job not found."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

    # -----------------------------------------------------------------
    # Reports
    # -----------------------------------------------------------------

    @extend_schema(summary="Generate Report", tags=["Reports"])
    @action(detail=True, methods=["post"], url_path="report", throttle_classes=[ComputationRateThrottle])
    def generate_report(self, request, pk=None):
        """Generate Word/Excel/PowerPoint report (async via CSV export task)."""
        analysis = self.get_object()
        fmt = request.data.get("format", "csv")
        if fmt not in ("csv", "docx", "xlsx", "pptx"):
            return Response(
                {"detail": f"Invalid format: {fmt}"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        from gel_analyzer.tasks import export_densitometry_csv_task

        task = export_densitometry_csv_task.delay(
            str(analysis.id),
            include_profile=request.data.get("include_profile", False),
            user_id=request.user.id,
        )
        return Response(
            {"task_id": task.id, "status": "PENDING", "format": fmt},
            status=drf_status.HTTP_202_ACCEPTED,
        )


# =============================================================================
# Lane ViewSet
# =============================================================================


@extend_schema_view(
    list=extend_schema(summary="List Lanes", tags=["Lanes"]),
    retrieve=extend_schema(summary="Get Lane Details", tags=["Lanes"]),
    create=extend_schema(summary="Create Lane", tags=["Lanes"]),
    partial_update=extend_schema(summary="Update Lane", tags=["Lanes"]),
    destroy=extend_schema(summary="Delete Lane", tags=["Lanes"]),
)
class LaneViewSet(viewsets.ModelViewSet):
    """ViewSet for Lane — CRUD + profile/densitometry actions."""

    queryset = (
        Lane.objects.select_related("analysis", "ladder_template").prefetch_related("bands").order_by("lane_number")
    )
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = LaneFilter
    ordering_fields = ["lane_number"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return LaneWriteSerializer
        return LaneSerializer

    def get_throttles(self):
        if self.action in ("create", "partial_update", "destroy"):
            return [WriteRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        summary="Get Lane Intensity Profile",
        tags=["Lane Data"],
        description="Returns 1D intensity profile for D3 electropherogram rendering.",
    )
    @action(detail=True, methods=["get"], url_path="profile")
    def profile(self, request, pk=None):
        """Get intensity profile data for D3.js electropherogram."""
        lane = self.get_object()
        try:
            summary = LaneDensitometrySummary.objects.get(lane=lane)
            if summary.profile_data:
                return Response(
                    {
                        "lane_id": lane.id,
                        "positions": summary.profile_data.get("positions", []),
                        "intensities": summary.profile_data.get("intensities", []),
                        "was_inverted": summary.profile_data.get("was_inverted", False),
                        "lane_height": lane.height,
                    }
                )
        except LaneDensitometrySummary.DoesNotExist:
            pass
        return Response(
            {"detail": "No profile data available. Run densitometry first."},
            status=drf_status.HTTP_404_NOT_FOUND,
        )

    @extend_schema(summary="Get Lane Densitometry Summary", tags=["Lane Data"])
    @action(detail=True, methods=["get"], url_path="densitometry")
    def densitometry(self, request, pk=None):
        """Get lane densitometry summary (purity %, areas)."""
        lane = self.get_object()
        try:
            summary = LaneDensitometrySummary.objects.get(lane=lane)
            return Response(
                {
                    "lane_id": lane.id,
                    "normalization_method": summary.normalization_method,
                    "total_integrated_area": summary.total_integrated_area,
                    "poi_integrated_area": summary.poi_integrated_area,
                    "poi_percentage": summary.poi_percentage,
                    "band_count": summary.band_count,
                    "poi_band_count": summary.poi_band_count,
                    "profile_data": summary.profile_data,
                }
            )
        except LaneDensitometrySummary.DoesNotExist:
            return Response(
                {"detail": "No densitometry data for this lane."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )


# =============================================================================
# Band ViewSet
# =============================================================================


@extend_schema_view(
    list=extend_schema(summary="List Bands", tags=["Bands"]),
    retrieve=extend_schema(summary="Get Band Details", tags=["Bands"]),
    create=extend_schema(summary="Create Band", tags=["Bands"]),
    partial_update=extend_schema(summary="Update Band", tags=["Bands"]),
    destroy=extend_schema(summary="Delete Band", tags=["Bands"]),
)
class BandViewSet(viewsets.ModelViewSet):
    """ViewSet for Band — CRUD + densitometry/MW estimation."""

    queryset = Band.objects.select_related("lane", "lane__analysis").order_by("position_y")
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = BandFilter
    ordering_fields = ["position_y", "estimated_mw_kda"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return BandWriteSerializer
        return BandSerializer

    def get_throttles(self):
        if self.action in ("create", "partial_update", "destroy"):
            return [WriteRateThrottle()]
        return super().get_throttles()

    @extend_schema(summary="Get Band Densitometry Result", tags=["Band Data"])
    @action(detail=True, methods=["get"], url_path="densitometry")
    def densitometry(self, request, pk=None):
        """Get Gaussian fit parameters for this band."""
        band = self.get_object()
        try:
            result = DensitometryResult.objects.get(band=band)
            return Response(
                {
                    "band_id": str(band.id),
                    "peak_center_y": result.peak_center_y,
                    "peak_amplitude": result.peak_amplitude,
                    "peak_sigma": result.peak_sigma,
                    "fwhm": result.fwhm,
                    "integrated_area": result.integrated_area,
                    "background_area": result.background_area,
                    "corrected_area": result.corrected_area,
                    "fit_r_squared": result.fit_r_squared,
                    "snr": result.snr,
                    "relative_percent_lane": result.relative_percent_lane,
                    "relative_percent_gel": result.relative_percent_gel,
                }
            )
        except DensitometryResult.DoesNotExist:
            return Response(
                {"detail": "No densitometry result for this band."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

    @extend_schema(summary="Estimate Band MW", tags=["Band Data"])
    @action(detail=True, methods=["get"], url_path="estimate-mw")
    def estimate_mw(self, request, pk=None):
        """Get MW estimation for this band."""
        band = self.get_object()
        return Response(
            {
                "band_id": str(band.id),
                "estimated_mw_kda": band.estimated_mw_kda,
                "position_y": band.position_y,
            }
        )


# =============================================================================
# LadderTemplate ViewSet
# =============================================================================


@extend_schema_view(
    list=extend_schema(summary="List Ladder Templates", tags=["Ladder Templates"]),
    retrieve=extend_schema(summary="Get Ladder Template", tags=["Ladder Templates"]),
    create=extend_schema(summary="Create Ladder Template", tags=["Ladder Templates"]),
    partial_update=extend_schema(summary="Update Ladder Template", tags=["Ladder Templates"]),
    destroy=extend_schema(summary="Delete Ladder Template", tags=["Ladder Templates"]),
)
class LadderTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for LadderTemplate — CRUD + default template."""

    queryset = LadderTemplate.objects.all().order_by("name")
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = LadderTemplateFilter
    search_fields = ["name", "manufacturer"]
    ordering_fields = ["name", "mw_range_max"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LadderTemplateDetailSerializer
        return LadderTemplateListSerializer

    def get_throttles(self):
        if self.action in ("create", "partial_update", "destroy"):
            return [WriteRateThrottle()]
        return super().get_throttles()

    @extend_schema(summary="Get Default Template", tags=["Ladder Templates"])
    @action(detail=False, methods=["get"], url_path="default")
    def default(self, request):
        """Return the first active global template as the default."""
        template = LadderTemplate.objects.filter(is_active=True, is_global=True).first()
        if not template:
            return Response(
                {"detail": "No default template."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        return Response(LadderTemplateDetailSerializer(template).data)


# =============================================================================
# SavedComparison ViewSet
# =============================================================================


@extend_schema_view(
    list=extend_schema(summary="List Comparisons", tags=["Comparisons"]),
    retrieve=extend_schema(summary="Get Comparison", tags=["Comparisons"]),
    create=extend_schema(summary="Create Comparison", tags=["Comparisons"]),
    partial_update=extend_schema(summary="Update Comparison", tags=["Comparisons"]),
    destroy=extend_schema(summary="Delete Comparison", tags=["Comparisons"]),
)
class SavedComparisonViewSet(viewsets.ModelViewSet):
    """ViewSet for SavedComparison — CRUD + full comparison data."""

    queryset = SavedComparison.objects.all().order_by("-created_at")
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = SavedComparisonFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        return SavedComparisonSerializer

    def get_throttles(self):
        if self.action in ("create", "partial_update", "destroy"):
            return [WriteRateThrottle()]
        return super().get_throttles()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(
        summary="Get Full Comparison Data",
        tags=["Comparisons"],
        description="Returns all lanes with profiles and densitometry for overlay charts.",
    )
    @action(detail=True, methods=["get"], url_path="data")
    def comparison_data(self, request, pk=None):
        """Get full comparison data for rendering overlay charts."""
        comparison = self.get_object()
        lanes = (
            comparison.lanes.select_related("analysis__gel_image", "ladder_template")
            .prefetch_related("bands")
            .order_by("savedcomparisonlane__order")
        )
        lane_data = []
        for lane in lanes:
            summary = None
            try:
                s = LaneDensitometrySummary.objects.get(lane=lane)
                summary = {
                    "poi_percentage": s.poi_percentage,
                    "total_integrated_area": s.total_integrated_area,
                    "profile_data": s.profile_data,
                }
            except LaneDensitometrySummary.DoesNotExist:
                pass
            lane_data.append(
                {
                    "id": lane.id,
                    "lane_number": lane.lane_number,
                    "sample_name": lane.sample_name,
                    "gel_image_name": (
                        lane.analysis.gel_image.original_filename if lane.analysis and lane.analysis.gel_image else None
                    ),
                    "bands": BandSerializer(lane.bands.all(), many=True).data,
                    "densitometry_summary": summary,
                }
            )
        return Response(
            {
                "id": str(comparison.id),
                "name": comparison.name,
                "view_settings": comparison.view_settings,
                "lanes": lane_data,
            }
        )
