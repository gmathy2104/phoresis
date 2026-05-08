"""
Densitometry API endpoints.

Provides REST API for:
- Running densitometry analysis (sync and async)
- Retrieving densitometry results
- Exporting results to CSV
- Getting lane profiles and band details
"""

import json
from uuid import UUID

from celery.result import AsyncResult

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from gel_analyzer.models import (
    Band,
    DensitometryJob,
    DensitometryResult,
    GelAnalysis,
    Lane,
    LaneDensitometrySummary,
)
from gel_analyzer.services.densitometry import (
    DensitometryParams,
    DensitometryService,
)
from gel_analyzer.services.densitometry.export import (
    DensitometryExporter,
    generate_csv_filename,
)
from gel_analyzer.services.file_handler import GelFileHandler
from gel_analyzer.tasks import export_densitometry_csv_task, run_densitometry_task
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


# ============================================================================
# Analysis-level endpoints
# ============================================================================


@login_required
@require_http_methods(["GET"])
def api_get_densitometry(request, pk: UUID):
    """
    Get densitometry results for an analysis.

    Returns stored densitometry data from database if available,
    or empty results if not yet computed.

    GET /api/analyses/<uuid>/densitometry/
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    # Get lane summaries
    lane_summaries = (
        LaneDensitometrySummary.objects.filter(lane__analysis=analysis)
        .select_related("lane")
        .order_by("lane__lane_number")
    )

    # Get band results
    band_results = (
        DensitometryResult.objects.filter(band__lane__analysis=analysis)
        .select_related("band", "band__lane")
        .order_by("band__lane__lane_number", "band__position_y")
    )

    # Build response
    lanes_data = []
    for summary in lane_summaries:
        lane_bands = [r for r in band_results if r.band.lane_id == summary.lane_id]

        lanes_data.append(
            {
                "lane_id": summary.lane_id,
                "lane_number": summary.lane.lane_number,
                "lane_type": summary.lane.lane_type,
                "total_integrated_area": summary.total_integrated_area,
                "poi_integrated_area": summary.poi_integrated_area,
                "poi_percentage": summary.poi_percentage,
                "other_integrated_area": summary.other_integrated_area,
                "mw_reference_area": summary.mw_reference_area,
                "band_count": summary.band_count,
                "poi_band_count": summary.poi_band_count,
                "normalization_method": summary.normalization_method,
                "computed_at": summary.computed_at.isoformat() if summary.computed_at else None,
                "profile_data": summary.profile_data,
                "bands": [
                    {
                        "band_id": str(r.band_id),
                        "band_type": r.band.band_type,
                        "position_y": r.band.position_y,
                        # bbox_y / bbox_height drive the chromatogram's
                        # integration-zone shading. Without them the JS in
                        # chromatogram-utils.calculateBandBounds falls back to
                        # ±3σ around the peak center, which doesn't match a
                        # user-edited bbox.
                        "bbox_y": r.band.bbox_y,
                        "bbox_height": r.band.bbox_height,
                        "estimated_mw_kda": r.band.estimated_mw_kda,
                        "peak_center_y": r.peak_center_y,
                        "peak_amplitude": r.peak_amplitude,
                        "peak_sigma": r.peak_sigma,
                        "fwhm": r.fwhm,
                        "integrated_area": r.integrated_area,
                        "corrected_area": r.corrected_area,
                        "fit_r_squared": r.fit_r_squared,
                        "snr": r.snr,
                        "relative_percent_lane": r.relative_percent_lane,
                        "relative_percent_gel": r.relative_percent_gel,
                        # Quantification outputs (written by
                        # ProteinQuantService.apply_to_analysis after the
                        # user clicks "Save & apply" in the calibration
                        # modal). Without these the results-table re-fetch
                        # after QUANT_CALIBRATION_CHANGED brings down the
                        # rest of the densitometry but leaves the
                        # estimated-amount column at "—" — exactly the bug
                        # the user reported. The DRF v1 mirror at
                        # api/views.py:densitometry_results already
                        # surfaces these; this FBV was the gap.
                        "estimated_amount": r.estimated_amount,
                        "estimated_amount_unit": r.estimated_amount_unit,
                    }
                    for r in lane_bands
                ],
            }
        )

    # Compute gel-level statistics
    gel_total_area = sum(ld["total_integrated_area"] for ld in lanes_data)
    sample_purities = [
        ld["poi_percentage"] for ld in lanes_data if ld["poi_percentage"] and ld["lane_type"] == "SAMPLE"
    ]
    avg_purity = sum(sample_purities) / len(sample_purities) if sample_purities else None

    return JsonResponse(
        {
            "success": True,
            "analysis_id": str(analysis.id),
            "has_results": len(lanes_data) > 0,
            "lanes": lanes_data,
            "summary": {
                "lanes_count": len(lanes_data),
                "total_bands": sum(ld["band_count"] for ld in lanes_data),
                "gel_total_area": gel_total_area,
                "average_poi_percentage": avg_purity,
            },
        }
    )


@login_required
@require_http_methods(["POST"])
def api_run_densitometry(request, pk: UUID):
    """
    Run densitometry analysis synchronously (preview mode).

    For quick preview without saving to database.
    Use async endpoint for persistent analysis.

    POST /api/analyses/<uuid>/densitometry/run/
    Body: { params: {...}, lane_ids: [...] }
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    params_dict = body.get("params", {})
    lane_ids = body.get("lane_ids")

    try:
        # Build params
        params = DensitometryParams.from_dict(params_dict) if params_dict else DensitometryParams()

        # Load image
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Run analysis (preview mode, no save)
        service = DensitometryService(params)
        result = service.analyze_analysis(analysis, image, lane_ids)

        return JsonResponse({"success": result.success, **result.to_dict()})

    except Exception:
        logger.exception(f"Densitometry sync failed for {pk}")
        return JsonResponse({"success": False, "error": "An internal error occurred."}, status=500)


@login_required
@require_http_methods(["POST"])
def api_run_densitometry_async(request, pk: UUID):
    """
    Start asynchronous densitometry analysis via Celery.

    Returns task ID for status polling. Results are saved to database.

    POST /api/analyses/<uuid>/densitometry/async/
    Body: { params: {...}, lane_ids: [...] }
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    params_dict = body.get("params", {})
    lane_ids = body.get("lane_ids")

    try:
        # Create job record
        job = DensitometryJob.objects.create(
            analysis=analysis,
            params=params_dict or {},
            lane_ids=lane_ids,
            created_by=request.user,
        )

        # Start Celery task — pass job_id so the task finds the job by PK
        # (avoids race condition where task starts before task_id is saved)
        task = run_densitometry_task.delay(
            analysis_id=str(analysis.id),
            params_dict=params_dict,
            user_id=request.user.id,
            lane_ids=lane_ids,
            save_results=True,
            job_id=str(job.id),
        )

        # Update job with task ID
        job.task_id = task.id
        job.save(update_fields=["task_id"])

        return JsonResponse(
            {
                "success": True,
                "task_id": task.id,
                "job_id": str(job.id),
                "status": "PENDING",
            }
        )

    except Exception:
        logger.exception(f"Failed to start densitometry task for {pk}")
        return JsonResponse({"success": False, "error": "An internal error occurred."}, status=500)


@login_required
@require_http_methods(["GET"])
def api_densitometry_job_status(request, pk: UUID, job_id: UUID):
    """
    Get status of a densitometry job.

    GET /api/analyses/<uuid>/densitometry/jobs/<job_id>/
    """
    job = get_object_or_404(DensitometryJob, pk=job_id, analysis_id=pk)

    response = {
        "job_id": str(job.id),
        "task_id": job.task_id,
        "status": job.status,
        "progress": job.progress,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }

    if job.status == DensitometryJob.Status.COMPLETED and job.result:
        response["result"] = job.result

    # Also check Celery task status
    if job.task_id:
        task_result = AsyncResult(job.task_id)
        response["celery_status"] = task_result.status
        if task_result.status == "PROGRESS":
            response["celery_meta"] = task_result.info

    return JsonResponse(response)


# ============================================================================
# Lane-level endpoints
# ============================================================================


@login_required
@require_http_methods(["GET"])
def api_lane_profile(request, pk: int):
    """
    Get intensity profile for a lane.

    Returns the lane intensity profile with optional MW axis.

    GET /api/lanes/<int>/profile/
    """
    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    try:
        # Check for stored profile data
        try:
            summary = lane.densitometry_summary
            if summary.profile_data:
                profile_data = summary.profile_data
                # Ensure valleys are computed even for cached profiles
                if "valleys" not in profile_data:
                    import numpy as np

                    from gel_analyzer.services.band_detection.peak_detector import find_valleys

                    intensities = profile_data.get("intensities", profile_data.get("processed_intensities", []))
                    if intensities and len(intensities) > 5:
                        proc_data = np.array(intensities, dtype=np.float64)
                        profile_data["valleys"] = find_valleys(proc_data, min_distance=10).tolist()
                    else:
                        profile_data["valleys"] = []
                return JsonResponse(
                    {
                        "success": True,
                        "lane_id": lane.id,
                        "lane_number": lane.lane_number,
                        "profile": profile_data,
                        "from_cache": True,
                    }
                )
        except LaneDensitometrySummary.DoesNotExist:
            pass

        # Generate fresh profile
        import dataclasses

        from gel_analyzer.services.band_detection import BandDetectionParams
        from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
        from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor, detect_image_polarity

        params = BandDetectionParams()
        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)

        # Detect polarity and invert entire image if white background
        image_inverted = False
        image_polarity = detect_image_polarity(image)
        if image_polarity == "always" or params.invert_profile == "always":
            image = image.max() - image
            params = dataclasses.replace(params, invert_profile="never")
            image_inverted = True
        elif image_polarity == "never":
            params = dataclasses.replace(params, invert_profile="never")

        extractor = IntensityProfileExtractor(params)
        processor = ProfileProcessor(params)

        profile = extractor.extract_profile(image, lane)
        profile = processor.process(profile)
        if image_inverted:
            profile.was_inverted = True

        # Compute valleys for the processed profile
        import numpy as np

        from gel_analyzer.services.band_detection.peak_detector import find_valleys

        proc_data = np.array(profile.processed_intensities, dtype=np.float64)
        if len(proc_data) > 5:
            profile.valley_indices = find_valleys(proc_data, min_distance=10).tolist()

        return JsonResponse(
            {
                "success": True,
                "lane_id": lane.id,
                "lane_number": lane.lane_number,
                "profile": {
                    "y_positions": profile.y_positions,
                    "intensities": [round(v, 2) for v in profile.processed_intensities],
                    "raw_intensities": [round(v, 2) for v in profile.raw_intensities],
                    "background": [round(v, 2) for v in profile.background],
                    "was_inverted": profile.was_inverted,
                    "valleys": profile.valley_indices,
                },
                "from_cache": False,
            }
        )

    except Exception:
        logger.exception(f"Failed to get lane profile for {pk}")
        return JsonResponse({"success": False, "error": "An internal error occurred."}, status=500)


@login_required
@require_http_methods(["GET"])
def api_lane_densitometry(request, pk: int):
    """
    Get densitometry summary for a lane.

    GET /api/lanes/<int>/densitometry/
    """
    lane = get_object_or_404(Lane, pk=pk)

    try:
        summary = lane.densitometry_summary

        # Get band results
        band_results = (
            DensitometryResult.objects.filter(band__lane=lane).select_related("band").order_by("band__position_y")
        )

        return JsonResponse(
            {
                "success": True,
                "lane_id": lane.id,
                "lane_number": lane.lane_number,
                "lane_type": lane.lane_type,
                "summary": {
                    "total_integrated_area": summary.total_integrated_area,
                    "poi_integrated_area": summary.poi_integrated_area,
                    "poi_percentage": summary.poi_percentage,
                    "other_integrated_area": summary.other_integrated_area,
                    "mw_reference_area": summary.mw_reference_area,
                    "band_count": summary.band_count,
                    "poi_band_count": summary.poi_band_count,
                    "normalization_method": summary.normalization_method,
                    "computed_at": summary.computed_at.isoformat() if summary.computed_at else None,
                },
                "bands": [
                    {
                        "band_id": str(r.band_id),
                        "band_type": r.band.band_type,
                        "position_y": r.band.position_y,
                        "estimated_mw_kda": r.band.estimated_mw_kda,
                        "corrected_area": r.corrected_area,
                        "relative_percent_lane": r.relative_percent_lane,
                        "fit_r_squared": r.fit_r_squared,
                    }
                    for r in band_results
                ],
            }
        )

    except LaneDensitometrySummary.DoesNotExist:
        return JsonResponse(
            {
                "success": True,
                "lane_id": lane.id,
                "lane_number": lane.lane_number,
                "has_results": False,
                "message": "No densitometry results available for this lane",
            }
        )


# ============================================================================
# Band-level endpoints
# ============================================================================


@login_required
@require_http_methods(["GET"])
def api_band_densitometry(request, pk: UUID):
    """
    Get densitometry details for a band.

    GET /api/bands/<uuid>/densitometry/
    """
    band = get_object_or_404(Band.objects.select_related("lane"), pk=pk)

    try:
        result = band.densitometry

        return JsonResponse(
            {
                "success": True,
                "band_id": str(band.id),
                "band_type": band.band_type,
                "position_y": band.position_y,
                "estimated_mw_kda": band.estimated_mw_kda,
                "densitometry": {
                    "peak_center_y": result.peak_center_y,
                    "peak_amplitude": result.peak_amplitude,
                    "peak_sigma": result.peak_sigma,
                    "fwhm": result.fwhm,
                    "integrated_area": result.integrated_area,
                    "background_area": result.background_area,
                    "corrected_area": result.corrected_area,
                    "fit_r_squared": result.fit_r_squared,
                    "fit_quality": result.fit_quality,
                    "snr": result.snr,
                    "relative_percent_lane": result.relative_percent_lane,
                    "relative_percent_gel": result.relative_percent_gel,
                    "computed_at": result.computed_at.isoformat() if result.computed_at else None,
                },
            }
        )

    except DensitometryResult.DoesNotExist:
        return JsonResponse(
            {
                "success": True,
                "band_id": str(band.id),
                "has_results": False,
                "message": "No densitometry results available for this band",
            }
        )


# ============================================================================
# Export endpoints
# ============================================================================


@login_required
@require_http_methods(["POST"])
def api_export_densitometry(request, pk: UUID):
    """
    Export densitometry results to CSV.

    POST /api/analyses/<uuid>/densitometry/export/
    Body: { format: "csv", include_profile: false, async: false }
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    export_format = body.get("format", "csv")
    include_profile = body.get("include_profile", False)
    run_async = body.get("async", False)

    if export_format != "csv":
        return JsonResponse(
            {"success": False, "error": f"Unsupported format: {export_format}. Only CSV is supported."}, status=400
        )

    if run_async:
        # Start async export task
        task = export_densitometry_csv_task.delay(
            analysis_id=str(analysis.id),
            include_profile=include_profile,
            user_id=request.user.id,
        )

        return JsonResponse(
            {
                "success": True,
                "task_id": task.id,
                "status": "PENDING",
            }
        )

    # Synchronous export
    try:
        # Load image and run analysis
        image = GelFileHandler.load_image_as_array(analysis.gel_image)
        service = DensitometryService()
        result = service.analyze_analysis(analysis, image)

        if not result.success:
            return JsonResponse({"success": False, "error": result.error_message or "Analysis failed"}, status=500)

        # Generate CSV
        exporter = DensitometryExporter()
        csv_content = exporter.export_csv(result, analysis, include_profile)

        # Return as file download
        filename = generate_csv_filename(analysis)
        response = HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        return response

    except Exception:
        logger.exception(f"Densitometry export failed for {pk}")
        return JsonResponse({"success": False, "error": "An internal error occurred."}, status=500)


@login_required
@require_http_methods(["GET"])
def api_export_status(request, pk: UUID, task_id: str):
    """
    Get status of an export task.

    GET /api/analyses/<uuid>/densitometry/export/<task_id>/
    """
    # S5: Verify the task belongs to this analysis
    analysis = get_object_or_404(GelAnalysis, pk=pk)
    if not DensitometryJob.objects.filter(analysis=analysis, celery_task_id=task_id).exists():
        return JsonResponse({"error": "Task not found for this analysis"}, status=404)

    task_result = AsyncResult(task_id)

    response = {
        "task_id": task_id,
        "status": task_result.status,
    }

    if task_result.ready():
        result = task_result.result
        if isinstance(result, dict):
            response.update(result)

            # If successful, generate download URL
            if result.get("success") and result.get("file_path"):
                response["download_url"] = default_storage.url(result["file_path"])

    return JsonResponse(response)


# ============================================================================
# Peak Detection endpoints
# ============================================================================


@login_required
@require_http_methods(["POST"])
def api_detect_peaks(request, pk: int):
    """
    Detect peaks in a lane's intensity profile.

    Returns detected peaks with matching information (orphan vs matched).

    POST /api/lanes/<int>/peaks/detect/
    Body: {
        params: { sensitivity: 0.85, ... },
        match_tolerance_px: 15
    }
    """
    from gel_analyzer.services.band_detection import BandDetectionParams
    from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
    from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor
    from gel_analyzer.services.densitometry import (
        AdvancedPeakDetector,
        PeakDeconvolutionService,
        PeakDetectionParams,
        PeakMatchingService,
    )

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    params_dict = body.get("params", {})
    match_tolerance = body.get("match_tolerance_px", 15)

    try:
        # Build detection params
        detection_params = PeakDetectionParams.from_dict(params_dict)

        # Load image and extract profile
        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)
        band_params = BandDetectionParams()

        extractor = IntensityProfileExtractor(band_params)
        processor = ProfileProcessor(band_params)

        profile = extractor.extract_profile(image, lane)
        profile = processor.process(profile)

        # Detect peaks
        detector = AdvancedPeakDetector(detection_params)
        peaks = detector.detect_peaks(profile)

        # Optionally deconvolve wide peaks
        if detection_params.enable_deconvolution and peaks:
            deconv_service = PeakDeconvolutionService()
            peaks = deconv_service.deconvolve_wide_peaks(
                profile, peaks, width_threshold=detection_params.deconvolution_threshold_px
            )

        # Get existing bands for this lane
        existing_bands = list(lane.bands.all())

        # Match peaks to bands
        matching_service = PeakMatchingService(tolerance_px=match_tolerance)
        result = matching_service.match_peaks_to_bands(peaks, existing_bands, lane.id)

        return JsonResponse(
            {
                "success": result.success,
                "lane_id": lane.id,
                "peaks": [p.to_dict() for p in result.peaks],
                "total_peaks": result.total_peaks,
                "orphan_count": result.orphan_count,
                "matched_count": result.matched_count,
                "shoulder_count": result.shoulder_count,
            }
        )

    except Exception:
        logger.exception(f"Peak detection failed for lane {pk}")
        return JsonResponse({"success": False, "error": "An internal error occurred."}, status=500)


@login_required
@require_http_methods(["POST"])
def api_detect_and_create_bands(request, pk: UUID):
    """
    Detect peaks in all lanes for VISUALIZATION ONLY.

    NOTE: This endpoint does NOT create bands in the database.
    Band creation should happen in the Annotation module.
    This endpoint only detects peaks and returns them for display
    on the electropherogram as visual indicators (triangles/markers).

    POST /api/analyses/<uuid>/peaks/detect-and-create/
    Body: {
        params: { sensitivity: 0.85, ... },
        match_tolerance_px: 15,
        lane_ids: [1, 2, 3]  // optional, defaults to all lanes
    }
    """
    from gel_analyzer.services.band_detection import BandDetectionParams
    from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
    from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor
    from gel_analyzer.services.densitometry import (
        AdvancedPeakDetector,
        PeakDeconvolutionService,
        PeakDetectionParams,
        PeakMatchingService,
    )

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    params_dict = body.get("params", {})
    match_tolerance = body.get("match_tolerance_px", 15)
    lane_ids = body.get("lane_ids")

    try:
        # Build detection params
        detection_params = PeakDetectionParams.from_dict(params_dict)

        # Load image
        image = GelFileHandler.load_image_as_array(analysis.gel_image)
        band_params = BandDetectionParams()

        extractor = IntensityProfileExtractor(band_params)
        processor = ProfileProcessor(band_params)

        # Get lanes
        lanes_query = analysis.lanes.all()
        if lane_ids:
            lanes_query = lanes_query.filter(id__in=lane_ids)
        lanes = list(lanes_query.prefetch_related("bands"))

        # Track results
        total_peaks_detected = 0
        bands_matched = 0
        lane_results = []

        detector = AdvancedPeakDetector(detection_params)
        deconv_service = PeakDeconvolutionService() if detection_params.enable_deconvolution else None
        matching_service = PeakMatchingService(tolerance_px=match_tolerance)

        for lane in lanes:
            try:
                # Extract and process profile
                profile = extractor.extract_profile(image, lane)
                profile = processor.process(profile)

                # Detect peaks
                peaks = detector.detect_peaks(profile)

                # Optionally deconvolve
                if deconv_service and peaks:
                    peaks = deconv_service.deconvolve_wide_peaks(
                        profile, peaks, width_threshold=detection_params.deconvolution_threshold_px
                    )

                # Match to existing bands
                existing_bands = list(lane.bands.all())
                result = matching_service.match_peaks_to_bands(peaks, existing_bands, lane.id)

                total_peaks_detected += result.total_peaks
                bands_matched += result.matched_count

                # NOTE: No band creation here - visualization only
                # Orphan peaks are displayed as visual markers (triangles)
                # To create actual bands, use the Annotation Editor

                # Serialize peaks for frontend visualization
                peaks_data = [
                    {
                        "y_position": p.y_position,
                        "height": p.height,
                        "width_px": p.width_px,
                        "prominence": p.prominence,
                        "is_orphan": p.is_orphan,
                        "is_shoulder": getattr(p, "is_shoulder", False),
                        "matched_band_id": str(p.matched_band_id) if p.matched_band_id else None,
                    }
                    for p in result.peaks
                ]

                lane_results.append(
                    {
                        "lane_id": lane.id,
                        "lane_number": lane.lane_number,
                        "peaks_detected": result.total_peaks,
                        "orphans": result.orphan_count,
                        "matched": result.matched_count,
                        "peaks": peaks_data,
                    }
                )

            except Exception as e:
                logger.warning(f"Peak detection failed for lane {lane.id}: {e}")
                lane_results.append(
                    {
                        "lane_id": lane.id,
                        "lane_number": lane.lane_number,
                        "error": "Processing failed",
                    }
                )

        return JsonResponse(
            {
                "success": True,
                "lanes_processed": len(lanes),
                "total_peaks_detected": total_peaks_detected,
                "bands_matched": bands_matched,
                "lanes": lane_results,
                # No bands_created or bands_data - visualization only
            }
        )

    except Exception:
        logger.exception(f"Bulk peak detection failed for analysis {pk}")
        return JsonResponse({"success": False, "error": "An internal error occurred."}, status=500)
