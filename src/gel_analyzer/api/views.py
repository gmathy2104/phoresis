"""
DRF ViewSets for Gel Analyzer API.
"""

import dataclasses

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status as drf_status
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from gel_analyzer.access import IsGelAnalyzerUser, IsSavedComparisonOwnerOrReadOnly, saved_comparisons_readable_by
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
    DensitometryResultSerializer,
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
    MWMarkerSerializer,
    ProteinQuantCalibrationSerializer,
    ProteinQuantFitPreviewSerializer,
    ProteinQuantFitResultSerializer,
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
    MWMarker,
    ProteinQuantCalibration,
    SavedComparison,
)
from gel_analyzer.services.analysis_status import ACTION_FOR_TRANSITION, StatusChangeRefused, apply_status_action
from gel_analyzer.services.quantification.lane_type_change import CalibrationPointsHeld, guard_lane_type_change


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

    permission_classes = [IsGelAnalyzerUser]
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

    permission_classes = [IsGelAnalyzerUser]
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

    @extend_schema(
        summary="Transition Analysis Status",
        tags=["Gel Analyses"],
        description=(
            "Body: `status` (the target) and, to reject, `reason`. Beyond the writer gate of every write "
            "here, the analysis page's rules apply: approve and reject are staff or Gel QA Team only (403), "
            "a rejection needs a reason (400), complete, reopen and COMPLETED → IN_PROGRESS are the "
            "creator's (403)."
        ),
    )
    @action(detail=True, methods=["post"], url_path="status")
    def status_transition(self, request, pk=None):
        """Transition analysis status — the rules are ``services/analysis_status.py``'s, shared with the page."""
        analysis = self.get_object()
        new_status = request.data.get("status")
        if not new_status:
            return Response(
                {"detail": "status field is required."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        # A JSON list or object is no status name (and cannot be a dict key: a 500, not a 400).
        action_name = ACTION_FOR_TRANSITION.get((analysis.status, new_status)) if isinstance(new_status, str) else None
        if action_name is None:
            valid = [str(target) for source, target in ACTION_FOR_TRANSITION if source == analysis.status]
            return Response(
                {"detail": f"Cannot transition from {analysis.status} to {new_status}. Valid: {valid}"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        try:
            apply_status_action(analysis, action_name, request.user, reason=request.data.get("reason", ""))
        except StatusChangeRefused as exc:
            return Response({"detail": str(exc)}, status=exc.http_status)
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

    @extend_schema(
        summary="Trigger Band Detection (Async)",
        tags=["Detection"],
        description=(
            "Run hybrid band detection (CV2 primary, d1/d2 gap-fill) across all "
            "SAMPLE lanes of the analysis. Returns a Celery task id; poll the "
            "task to retrieve detected bands. With ``save_results=true`` the "
            "detected bands are persisted; otherwise the call is dry-run."
        ),
        examples=[
            OpenApiExample(
                "Default sensitivity",
                value={"params": {}, "save_results": True},
                request_only=True,
            ),
            OpenApiExample(
                "Faint-band mode",
                value={
                    "params": {
                        "smoothing_window": 5,
                        "min_band_width": 3,
                        "include_faint_bands": True,
                    },
                    "save_results": False,
                },
                request_only=True,
            ),
        ],
    )
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
                                # bbox_y / bbox_height drive the chromatogram's
                                # integration-zone shading (chromatogram-utils.js
                                # calculateBandBounds). Without them the JS falls
                                # back to a ±3σ window centered on the peak —
                                # visually wrong after a manual bbox edit.
                                "bbox_y": band.bbox_y,
                                "bbox_height": band.bbox_height,
                                "peak_center_y": dr.peak_center_y,
                                "peak_amplitude": dr.peak_amplitude,
                                "fwhm": dr.fwhm,
                                "corrected_area": dr.corrected_area,
                                "relative_percent_lane": dr.relative_percent_lane,
                                "fit_r_squared": dr.fit_r_squared,
                                "snr": dr.snr,
                                # Spec §8.1 — quantification fields surfaced for the
                                # UI's results-table and quantification curve tab.
                                "estimated_amount": dr.estimated_amount,
                                "estimated_amount_unit": dr.estimated_amount_unit,
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

    @extend_schema(
        summary="Run Densitometry (Async)",
        tags=["Densitometry"],
        description=(
            "Kick off the densitometry Celery pipeline for the analysis. Creates "
            "a DensitometryJob row, dispatches the task, returns the job; clients "
            "poll the job-detail endpoint until status == COMPLETED. With an empty "
            "``lane_ids`` array all lanes are processed. 403 for an APPROVED analysis "
            "(final: its densitometry is never re-run); 400 for a retired or unknown "
            "``params.normalization_method`` (``gel_total`` and ``reference_band`` were "
            "removed). Loading Control on a lane without an MW_REFERENCE band carrying "
            "signal is refused by the run itself: the job ends FAILED, its "
            "``error_message`` naming the lanes, and nothing is saved."
        ),
        responses={202: DensitometryJobSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                "All lanes",
                value={"params": {}, "lane_ids": []},
                request_only=True,
            ),
            OpenApiExample(
                "Selective rerun",
                value={"params": {"clahe_enabled": True}, "lane_ids": ["uuid-1", "uuid-2"]},
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"], url_path="densitometry/run", throttle_classes=[ComputationRateThrottle])
    def run_densitometry(self, request, pk=None):
        """Trigger async densitometry."""
        analysis = self.get_object()
        from gel_analyzer.services.analysis_status import APPROVED_IS_FINAL, is_final
        from gel_analyzer.services.densitometry import DensitometryParams
        from gel_analyzer.tasks import run_densitometry_task

        if is_final(analysis):
            return Response({"detail": APPROVED_IS_FINAL}, status=drf_status.HTTP_403_FORBIDDEN)
        try:
            DensitometryParams.from_dict(request.data.get("params") or {})
        except (TypeError, ValueError) as exc:
            # A retired normalization names why (NormalizationMethod._missing_)
            return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)

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

    @extend_schema(
        summary="Generate Report",
        tags=["Reports"],
        description=(
            "Trigger asynchronous report generation for an analysis. Returns a "
            "Celery task id immediately; poll the task to retrieve the file URL."
        ),
        examples=[
            OpenApiExample(
                "CSV densitometry export",
                value={"format": "csv", "include_profile": True},
                request_only=True,
            ),
        ],
    )
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

    # -----------------------------------------------------------------
    # MW Markers (Task A7)
    # -----------------------------------------------------------------

    @extend_schema(
        summary="List MW Markers for Analysis",
        tags=["Calibration"],
        description=(
            "Read-only list of all MW markers (known molecular weights) attached "
            "to LADDER lanes in this analysis. Used by the calibration UI to "
            "render expected vs detected marker positions."
        ),
        responses={200: MWMarkerSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="mw-markers")
    def mw_markers(self, request, pk=None):
        """Return all MW markers across all LADDER lanes in this analysis."""
        analysis = self.get_object()
        markers = (
            MWMarker.objects.filter(lane__analysis=analysis)
            .select_related("lane", "band")
            .order_by("lane__lane_number", "-mw_kda")
        )
        return Response(MWMarkerSerializer(markers, many=True).data)


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

    permission_classes = [IsGelAnalyzerUser]
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

    def partial_update(self, request, *args, **kwargs):
        """PATCH /v1/lanes/<id>/ — with quantification-aware downgrade guard.

        If the lane is being moved out of CALIBRATION/CONTROL and dependent
        ProteinQuantCalibrationPoint rows exist on its bands, return 409
        unless ``?force=true`` is passed in the query string; with force,
        purge the calibration points and demote the corresponding bands to
        OTHER before performing the regular update.

        The 409 carries ``dependent_band_ids`` so the frontend can render
        an informed confirmation ("This lane has 3 calibration points;
        switching to SAMPLE will discard them — continue?") before
        re-issuing the PATCH with ``?force=true``.

        The rule is ``guard_lane_type_change``, shared with the editor's lane
        PUT and bulk update; the purge and the update commit together.
        """
        from django.db import transaction

        instance = self.get_object()
        force = request.query_params.get("force", "").lower() == "true"
        try:
            with transaction.atomic():
                guard_lane_type_change(instance, request.data.get("lane_type"), force=force)
                return super().partial_update(request, *args, **kwargs)
        except CalibrationPointsHeld as refusal:
            return Response(refusal.payload(), status=drf_status.HTTP_409_CONFLICT)

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

    permission_classes = [IsGelAnalyzerUser]
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

    @extend_schema(
        summary="Get Band Densitometry Result",
        tags=["Band Data"],
        description=(
            "Returns the Gaussian-fit densitometry result for a single band "
            "(peak center, sigma, integrated area, R², SNR, and the optional "
            "quantification projection)."
        ),
        responses={200: DensitometryResultSerializer, 404: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"], url_path="densitometry")
    def densitometry(self, request, pk=None):
        """Get Gaussian fit parameters for this band."""
        band = self.get_object()
        try:
            result = DensitometryResult.objects.get(band=band)
            return Response(DensitometryResultSerializer(result).data)
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

    permission_classes = [IsGelAnalyzerUser]
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


_COMPARISON_WRITE_RULE = (
    "Creator only: 403 on a public comparison that is not yours, 404 on another account's private one "
    "(it is not readable, as if it did not exist)."
)


@extend_schema_view(
    list=extend_schema(
        summary="List Comparisons",
        tags=["Comparisons"],
        description="Your own comparisons and every public one. Another account's private comparison is never listed.",
    ),
    retrieve=extend_schema(
        summary="Get Comparison",
        tags=["Comparisons"],
        description="Readable when it is yours or public; another account's private comparison answers 404.",
    ),
    create=extend_schema(summary="Create Comparison", tags=["Comparisons"]),
    partial_update=extend_schema(summary="Update Comparison", tags=["Comparisons"], description=_COMPARISON_WRITE_RULE),
    destroy=extend_schema(summary="Delete Comparison", tags=["Comparisons"], description=_COMPARISON_WRITE_RULE),
)
class SavedComparisonViewSet(viewsets.ModelViewSet):
    """ViewSet for SavedComparison — CRUD + full comparison data.

    A comparison is its creator's unless public (``gel_analyzer/access.py``, A SAVED
    COMPARISON IS ITS CREATOR'S): ``get_queryset`` hides another account's private one
    from every action -- the list, the detail, ``data/`` and the writes, which then 404 --
    and ``IsSavedComparisonOwnerOrReadOnly`` refuses a write on a public one that is not
    the caller's (403).
    """

    permission_classes = [IsGelAnalyzerUser, IsSavedComparisonOwnerOrReadOnly]
    queryset = SavedComparison.objects.all().order_by("-created_at")
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = SavedComparisonFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return saved_comparisons_readable_by(self.request.user, super().get_queryset())

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
        description=(
            "Returns all lanes with profiles and densitometry for overlay charts. Same visibility as Get "
            "Comparison: another account's private comparison answers 404."
        ),
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


# =============================================================================
# Protein Quantification — function-based views
# =============================================================================


def _serialize_calib(c):
    """Serialize a ProteinQuantCalibration row for the quantification endpoints.

    Delegates to ProteinQuantCalibrationSerializer so the wire format is
    described by drf-spectacular. The legacy ad-hoc keys (``created_by`` as
    username string, ``superseded_at`` ISO-formatted) are preserved for
    backward compatibility with the existing quantification-modal JS.
    """
    base = ProteinQuantCalibrationSerializer(c).data
    # The Phoresis JS expected created_by as a username string, not a user PK;
    # also keep id as a plain str to match the historical wire shape.
    base["id"] = str(c.id)
    base["created_by"] = c.created_by.username if c.created_by else None
    return base


def _build_full_result(analysis, params):
    """Run a full preview: fit + project samples + project controls, each flagged against the standards' range."""
    from gel_analyzer.services.quantification.service import (
        ProteinQuantCalibrationService,
        calibration_area_span,
        calibration_range_of,
    )

    svc = ProteinQuantCalibrationService(params)
    cal_points = svc.collect_calibration_points(analysis)
    result = svc.fit(cal_points, excluded_band_ids=params.excluded_band_ids)
    if not result.success:
        return result, svc
    span = calibration_area_span(((p.band_id, p.corrected_area) for p in cal_points), params.excluded_band_ids)
    result.calibration_area_range = span
    # Add control projections
    ctrls = svc.collect_control_points(analysis)
    for c in ctrls:
        if c.corrected_area is not None:
            c.predicted_amount = svc.project(c.corrected_area, result)
            c.calibration_range = calibration_range_of(c.corrected_area, span)
    result.control_points = ctrls
    # Sample projections
    samples = svc.collect_sample_bands(analysis)
    for s in samples:
        if s.corrected_area is not None:
            s.predicted_amount = svc.project(s.corrected_area, result)
            s.calibration_range = calibration_range_of(s.corrected_area, span)
    result.sample_projections = samples
    return result, svc


@extend_schema(
    summary="Get / Save Protein Quantification Calibration",
    tags=["Quantification"],
    description=(
        "GET returns the active calibration for this analysis (or null). "
        "POST fits a new calibration from CALIBRATION-typed bands, supersedes "
        "any prior active calibration, and back-fills estimated_amount on every "
        "POI band's DensitometryResult in a single transaction. POST is refused "
        "with 403 on an APPROVED analysis: an approved analysis is final."
    ),
    request=ProteinQuantFitPreviewSerializer,
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="GET: {active: ProteinQuantCalibration | null}",
        ),
        201: ProteinQuantCalibrationSerializer,
        403: OpenApiTypes.OBJECT,
        404: OpenApiTypes.OBJECT,
        422: OpenApiTypes.OBJECT,
    },
    examples=[
        OpenApiExample(
            "Save linear µg calibration",
            value={"method": "LINEAR", "unit": "UG", "notes": "Standard curve from std-mix lot 42"},
            request_only=True,
        ),
    ],
)
@api_view(["GET", "POST"])
@permission_classes([IsGelAnalyzerUser])
def quantification_root(request, analysis_id):
    """GET → active calibration (or null); POST → save & apply a new fit."""
    from gel_analyzer.services.quantification.models import QuantParams

    try:
        analysis = GelAnalysis.objects.get(pk=analysis_id)
    except GelAnalysis.DoesNotExist:
        return Response({"detail": "Analysis not found."}, status=drf_status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
        return Response({"active": _serialize_calib(active) if active else None})

    # POST = save & apply, never on an approved analysis (services/analysis_status.py); save_active
    # checks again under the row lock, for an approval landing between this check and the write.
    from gel_analyzer.services.analysis_status import APPROVED_IS_FINAL, AnalysisIsFinal, is_final

    if is_final(analysis):
        return Response({"detail": APPROVED_IS_FINAL}, status=drf_status.HTTP_403_FORBIDDEN)
    params = QuantParams(
        method=request.data.get("method", "LINEAR"),
        unit=request.data.get("unit", "UG"),
        excluded_band_ids=request.data.get("excluded_band_ids", []),
    )
    result, svc = _build_full_result(analysis, params)
    if not result.success:
        return Response(
            {"detail": result.error_message, **result.to_dict()},
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    # save_active uses transaction.atomic() internally, but apply_to_analysis is
    # the second leg of "Save & apply" and must commit together — otherwise a
    # crash between the two leaves the analysis with an active calibration but
    # no estimated_amount values written.
    from django.db import transaction

    try:
        with transaction.atomic():
            calib = svc.save_active(analysis, result, user=request.user, notes=request.data.get("notes", ""))
            svc.apply_to_analysis(calib)
    except AnalysisIsFinal as refusal:
        return Response({"detail": str(refusal)}, status=drf_status.HTTP_403_FORBIDDEN)
    return Response(_serialize_calib(calib), status=drf_status.HTTP_201_CREATED)


@extend_schema(
    summary="Preview Protein Quantification Fit",
    tags=["Quantification"],
    description=(
        "Dry-run a fit without persisting. Returns 200 with QuantFitResult.to_dict() "
        "on success, 422 with the same shape on failure (e.g. missing densitometry "
        "for calibration bands, fewer than 4 points for FOUR_PL, singular fit)."
    ),
    request=ProteinQuantFitPreviewSerializer,
    responses={
        200: ProteinQuantFitResultSerializer,
        404: OpenApiTypes.OBJECT,
        422: ProteinQuantFitResultSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsGelAnalyzerUser])
def quantification_preview(request, analysis_id):
    """Dry-run a fit without persisting; returns result.to_dict() with status
    200 on success or 422 on failure (e.g. missing densitometry, < 4 points
    for FOUR_PL)."""
    from gel_analyzer.services.quantification.models import QuantParams

    try:
        analysis = GelAnalysis.objects.get(pk=analysis_id)
    except GelAnalysis.DoesNotExist:
        return Response({"detail": "Analysis not found."}, status=drf_status.HTTP_404_NOT_FOUND)

    params = QuantParams(
        method=request.data.get("method", "LINEAR"),
        unit=request.data.get("unit", "UG"),
        excluded_band_ids=request.data.get("excluded_band_ids", []),
    )
    result, _ = _build_full_result(analysis, params)
    return Response(
        result.to_dict(),
        status=drf_status.HTTP_200_OK if result.success else drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


@extend_schema(
    summary="Patch / Deactivate Protein Quantification Calibration",
    tags=["Quantification"],
    description=(
        "PATCH updates ``excluded_band_ids`` and/or ``notes`` on an existing "
        "calibration without re-fitting (use the root POST to re-fit). "
        "DELETE deactivates the calibration (sets is_active=False, "
        "superseded_at=now()) but keeps the row for audit. Both are refused "
        "with 403 on an APPROVED analysis: an approved analysis is final."
    ),
    request=ProteinQuantCalibrationSerializer,
    responses={
        200: ProteinQuantCalibrationSerializer,
        204: None,
        403: OpenApiTypes.OBJECT,
        404: OpenApiTypes.OBJECT,
    },
)
@api_view(["PATCH", "DELETE"])
@permission_classes([IsGelAnalyzerUser])
def quantification_detail(request, analysis_id, calib_id):
    """PATCH → update excluded_band_ids/notes; DELETE → deactivate."""
    from django.utils import timezone

    try:
        calib = ProteinQuantCalibration.objects.select_related("analysis").get(pk=calib_id, analysis_id=analysis_id)
    except ProteinQuantCalibration.DoesNotExist:
        return Response({"detail": "Calibration not found."}, status=drf_status.HTTP_404_NOT_FOUND)

    from gel_analyzer.services.analysis_status import APPROVED_IS_FINAL, is_final

    if is_final(calib.analysis):
        return Response({"detail": APPROVED_IS_FINAL}, status=drf_status.HTTP_403_FORBIDDEN)

    if request.method == "PATCH":
        # update_fields prevents racing with recompute_if_active, which writes
        # coefficients/r_squared/equation/last_recomputed_at. A bare save()
        # would clobber those columns with the row state fetched above.
        fields_to_save: list[str] = []
        if "excluded_band_ids" in request.data:
            calib.excluded_band_ids = request.data["excluded_band_ids"]
            fields_to_save.append("excluded_band_ids")
        if "notes" in request.data:
            calib.notes = request.data["notes"]
            fields_to_save.append("notes")
        if fields_to_save:
            calib.save(update_fields=fields_to_save)
        return Response(_serialize_calib(calib))

    # DELETE = deactivate
    calib.is_active = False
    calib.superseded_at = timezone.now()
    calib.save(update_fields=["is_active", "superseded_at"])
    return Response(status=drf_status.HTTP_204_NO_CONTENT)


@extend_schema(
    summary="Quantification Calibration History",
    tags=["Quantification"],
    description=(
        "Returns every calibration ever saved for this analysis "
        "(active + superseded), ordered by created_at descending. Used by the "
        "quantification audit panel."
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="{history: ProteinQuantCalibration[]}",
        ),
        404: OpenApiTypes.OBJECT,
    },
)
@api_view(["GET"])
@permission_classes([IsGelAnalyzerUser])
def quantification_history(request, analysis_id):
    """Return all calibrations (active + superseded) for the analysis."""
    # Mirror the 404 guard used by the sibling views — otherwise a fabricated
    # analysis_id silently returns {"history": []} with HTTP 200 and clients
    # cannot distinguish "no history" from "wrong analysis".
    if not GelAnalysis.objects.filter(pk=analysis_id).exists():
        return Response({"detail": "Analysis not found."}, status=drf_status.HTTP_404_NOT_FOUND)

    history = ProteinQuantCalibration.objects.filter(analysis_id=analysis_id).order_by("-created_at")
    return Response({"history": [_serialize_calib(c) for c in history]})
