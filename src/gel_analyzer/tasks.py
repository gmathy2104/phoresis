"""
Celery tasks for Gel Analyzer module.

Includes async tasks for derivative-based band detection on gel electrophoresis images.
"""

import os
from datetime import timedelta

from celery import shared_task

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from phoresis_core.celery_utils import robust_task
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


# Default TTL for orphan GelImage rows (uploaded but never wired to a
# GelAnalysis). Operator can override via env without code change.
ORPHAN_GEL_IMAGE_TTL_HOURS = int(os.environ.get("PHORESIS_ORPHAN_GEL_IMAGE_TTL_HOURS", "24"))


@robust_task(
    soft_time_limit=300,  # 5 min — query is light, but file deletes can be slow on a slow disk
    time_limit=360,
)
def purge_orphan_gel_images(self, ttl_hours: int | None = None) -> dict:
    """
    Delete GelImage rows that were uploaded more than ``ttl_hours`` ago and
    have never been attached to a GelAnalysis (e.g. user uploaded then
    closed the tab). The post_delete signal in
    ``gel_analyzer.signals.delete_gel_image_files`` cascades the cleanup
    to the original / display / thumbnail files on disk.

    Args:
        ttl_hours: How old (in hours) an unused GelImage must be before
            it qualifies for purge. Defaults to PHORESIS_ORPHAN_GEL_IMAGE_TTL_HOURS
            (24 by default).

    Returns:
        Dict with ``found`` (qualifying rows at task start) and ``deleted``
        (rows actually removed; can be lower if a row was attached to an
        analysis between query and delete, or if the file delete raised).
    """
    from gel_analyzer.models import GelImage

    ttl = int(ttl_hours if ttl_hours is not None else ORPHAN_GEL_IMAGE_TTL_HOURS)
    cutoff = timezone.now() - timedelta(hours=ttl)

    queryset = (
        GelImage.objects.annotate(_n_analyses=Count("analyses"))
        .filter(_n_analyses=0, uploaded_at__lt=cutoff)
        .order_by("uploaded_at")
    )
    found = queryset.count()
    if not found:
        logger.info("purge_orphan_gel_images: no orphans (TTL=%dh, cutoff=%s)", ttl, cutoff.isoformat())
        return {"found": 0, "deleted": 0, "ttl_hours": ttl}

    deleted = 0
    # Iterate then delete one-by-one so a single bad row doesn't roll back
    # the whole sweep. Each delete fires the post_delete signal -> file
    # cleanup. Use the queryset PKs because the QuerySet is unstable across
    # iteration (filtering on Count() forces re-evaluation).
    for pk in list(queryset.values_list("pk", flat=True)):
        try:
            with transaction.atomic():
                # Re-check: an analysis could have been attached between
                # the count() and now (race). Skip if so.
                img = GelImage.objects.annotate(_n=Count("analyses")).filter(pk=pk, _n=0).first()
                if img is None:
                    continue
                img.delete()
                deleted += 1
        except Exception as exc:
            logger.warning(f"purge_orphan_gel_images: failed to delete GelImage {pk}: {exc}")

    logger.info(
        "purge_orphan_gel_images: removed %d/%d orphan rows (TTL=%dh)",
        deleted,
        found,
        ttl,
    )
    return {"found": found, "deleted": deleted, "ttl_hours": ttl}


@robust_task(
    autoretry_for=(IOError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=120,  # 2 minutes soft limit
    time_limit=180,  # 3 minutes hard limit
)
def detect_bands_lane_task(
    self,
    lane_id: int,
    params_dict: dict | None = None,
    user_id: int | None = None,
    save_results: bool = False,
) -> dict:
    """
    Detect bands in a single lane asynchronously.

    Args:
        lane_id: ID of the Lane to process
        params_dict: Optional detection parameters dict
        user_id: User ID (required if save_results=True)
        save_results: Whether to save detected bands to database

    Returns:
        Dict with detection results
    """
    from django.contrib.auth import get_user_model

    from gel_analyzer.models import Band, Lane
    from gel_analyzer.services.band_detection import (
        BandDetectionParams,
        BandDetectionService,
    )
    from gel_analyzer.services.file_handler import GelFileHandler

    User = get_user_model()

    logger.info(f"[Task {self.request.id}] === BAND DETECTION TASK STARTED === lane_id={lane_id}, save={save_results}")

    try:
        # Get lane and related data
        lane = Lane.objects.select_related("analysis__gel_image").get(pk=lane_id)
        analysis = lane.analysis

        # Get user if saving
        user = None
        if save_results:
            if user_id is None:
                raise ValueError("user_id required when save_results=True")
            user = User.objects.get(pk=user_id)

        # Build detection params
        params = BandDetectionParams.from_dict(params_dict) if params_dict else BandDetectionParams()

        # Load image
        logger.debug(f"[Task {self.request.id}] Loading image for lane {lane.lane_number}")
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Create service and run detection
        service = BandDetectionService(params)

        if save_results:
            with transaction.atomic():
                # Delete existing auto-detected bands
                deleted_count = Band.objects.filter(
                    lane=lane,
                    detection_source=Band.DetectionSource.AUTO,
                ).delete()[0]

                if deleted_count > 0:
                    logger.debug(f"[Task {self.request.id}] Deleted {deleted_count} existing auto-detected bands")

                # Run detection and save
                result = service.detect_and_save(
                    lane=lane,
                    image=image,
                    user=user,
                    delete_existing=False,  # Already deleted above
                )

                # Update analysis counts
                analysis.update_counts()
        else:
            # Preview mode
            result = service.detect_bands_in_lane(lane, image)

        logger.info(
            f"[Task {self.request.id}] === BAND DETECTION TASK COMPLETED === "
            f"lane_id={lane_id}, bands={len(result.bands)}, "
            f"time={result.processing_time_ms:.1f}ms"
        )

        response = result.to_dict()
        response["task_id"] = self.request.id

        return response

    except Lane.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Lane {lane_id} not found")
        raise ValueError(f"Lane {lane_id} not found") from None

    except Exception:
        logger.exception(f"[Task {self.request.id}] Band detection failed for lane {lane_id}")
        raise


@robust_task(
    autoretry_for=(IOError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=600,  # 10 minutes soft limit
    time_limit=720,  # 12 minutes hard limit
)
def detect_bands_bulk_task(
    self,
    analysis_id: str,
    lane_ids: list[int] | None = None,
    params_dict: dict | None = None,
    user_id: int | None = None,
    save_results: bool = False,
) -> dict:
    """
    Detect bands in multiple lanes asynchronously.

    Args:
        analysis_id: UUID of the GelAnalysis to process
        lane_ids: Optional list of specific lane IDs (None = all lanes)
        params_dict: Optional detection parameters dict
        user_id: User ID (required if save_results=True)
        save_results: Whether to save detected bands to database

    Returns:
        Dict with bulk detection results
    """
    from django.contrib.auth import get_user_model

    from gel_analyzer.models import Band, GelAnalysis
    from gel_analyzer.services.band_detection import (
        BandDetectionParams,
        BandDetectionService,
    )
    from gel_analyzer.services.file_handler import GelFileHandler

    User = get_user_model()

    logger.info(
        f"[Task {self.request.id}] === BULK BAND DETECTION TASK STARTED === "
        f"analysis_id={analysis_id}, lane_count={len(lane_ids) if lane_ids else 'all'}, "
        f"save={save_results}"
    )

    try:
        # Get analysis and lanes
        analysis = GelAnalysis.objects.select_related("gel_image").get(pk=analysis_id)

        lanes = analysis.lanes.all()
        if lane_ids:
            lanes = lanes.filter(pk__in=lane_ids)
        lanes = list(lanes.order_by("lane_number"))

        if not lanes:
            logger.warning(f"[Task {self.request.id}] No lanes to process")
            return {
                "success": True,
                "lanes_processed": 0,
                "total_bands": 0,
                "results": [],
                "task_id": self.request.id,
            }

        # Get user if saving
        user = None
        if save_results:
            if user_id is None:
                raise ValueError("user_id required when save_results=True")
            user = User.objects.get(pk=user_id)

        # Build detection params
        params = BandDetectionParams.from_dict(params_dict) if params_dict else BandDetectionParams()

        # Load image once for all lanes
        logger.debug(f"[Task {self.request.id}] Loading image")
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Create service
        service = BandDetectionService(params)
        results = []

        with transaction.atomic():
            for i, lane in enumerate(lanes, 1):
                # Report progress to frontend
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "current": i,
                        "total": len(lanes),
                        "lane_number": lane.lane_number,
                    },
                )

                logger.debug(f"[Task {self.request.id}] Processing lane {lane.lane_number} ({i}/{len(lanes)})")

                if save_results:
                    # Delete existing auto-detected bands
                    Band.objects.filter(
                        lane=lane,
                        detection_source=Band.DetectionSource.AUTO,
                    ).delete()

                    result = service.detect_and_save(
                        lane=lane,
                        image=image,
                        user=user,
                        delete_existing=False,
                    )
                else:
                    result = service.detect_bands_in_lane(lane, image)

                results.append(result)

            # Update analysis counts if saved
            if save_results:
                analysis.update_counts()

        total_bands = sum(len(r.bands) for r in results)
        successful = sum(1 for r in results if r.success)

        logger.info(
            f"[Task {self.request.id}] === BULK BAND DETECTION TASK COMPLETED === "
            f"analysis_id={analysis_id}, lanes={len(results)}, bands={total_bands}"
        )

        return {
            "success": True,
            "analysis_id": str(analysis_id),
            "lanes_processed": len(results),
            "lanes_successful": successful,
            "total_bands": total_bands,
            "results": [r.to_dict() for r in results],
            "task_id": self.request.id,
        }

    except GelAnalysis.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Analysis {analysis_id} not found")
        raise ValueError(f"Analysis {analysis_id} not found") from None

    except Exception:
        logger.exception(f"[Task {self.request.id}] Bulk band detection failed for analysis {analysis_id}")
        raise


@robust_task(
    autoretry_for=(IOError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=600,
    time_limit=720,
)
def detect_bands_cv2_bulk_task(
    self,
    analysis_id: str,
    lane_ids: list[int] | None = None,
    params_dict: dict | None = None,
    user_id: int | None = None,
    save_results: bool = False,
    bg_type: str | None = None,
) -> dict:
    """Detect bands in multiple lanes using CV2 vision detector (async)."""
    from django.contrib.auth import get_user_model

    from gel_analyzer.models import Band, GelAnalysis, Lane
    from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector
    from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams
    from gel_analyzer.services.file_handler import GelFileHandler

    User = get_user_model()

    logger.info(
        f"[Task {self.request.id}] === CV2 BULK DETECTION STARTED === "
        f"analysis_id={analysis_id}, lane_count={len(lane_ids) if lane_ids else 'all'}, "
        f"save={save_results}, bg_type={bg_type}"
    )

    try:
        analysis = GelAnalysis.objects.select_related("gel_image").get(pk=analysis_id)
        lanes = analysis.lanes.all()
        if lane_ids:
            lanes = lanes.filter(pk__in=lane_ids)
        lanes = list(lanes.order_by("lane_number"))

        if not lanes:
            return {
                "success": True,
                "lanes_processed": 0,
                "total_bands": 0,
                "results": [],
                "task_id": self.request.id,
            }

        user = None
        if save_results:
            if user_id is None:
                raise ValueError("user_id required when save_results=True")
            user = User.objects.get(pk=user_id)

        params = CV2DetectionParams.from_dict(params_dict) if params_dict else CV2DetectionParams()
        image = GelFileHandler.load_image_as_array(analysis.gel_image)
        detector = CV2BandDetector(params)
        results = []

        with transaction.atomic():
            for i, lane in enumerate(lanes, 1):
                self.update_state(
                    state="PROGRESS", meta={"current": i, "total": len(lanes), "lane_number": lane.lane_number}
                )

                b = lane.bbox
                x, y, w, h = b["x"], b["y"], b["width"], b["height"]
                lane_crop = image[y : y + h, x : x + w]
                bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h), bg_type_override=bg_type)

                if save_results:
                    Band.objects.filter(
                        lane=lane,
                        detection_source=Band.DetectionSource.CV2_VISION,
                    ).delete()

                    band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"

                    for j, detected in enumerate(bands, 1):
                        Band.objects.create(
                            lane=lane,
                            band_number=j,
                            position_y=detected.position_y,
                            bbox_x=detected.bbox_x,
                            bbox_y=detected.bbox_y,
                            bbox_width=detected.bbox_width,
                            bbox_height=detected.bbox_height,
                            polygon=detected.polygon,
                            confidence=detected.confidence,
                            detection_source=Band.DetectionSource.CV2_VISION,
                            band_type=band_type,
                            intensity_raw=detected.intensity_raw,
                            intensity_peak=detected.intensity_peak,
                            area_pixels=detected.area_pixels,
                            created_by=user,
                        )

                results.append(
                    {
                        "lane_id": lane.pk,
                        "lane_number": lane.lane_number,
                        "band_count": len(bands),
                        "bands": [bd.to_dict() for bd in bands],
                        "success": True,
                    }
                )

            if save_results:
                analysis.update_counts()

        total_bands = sum(r["band_count"] for r in results)

        logger.info(
            f"[Task {self.request.id}] === CV2 BULK DETECTION COMPLETED === lanes={len(results)}, bands={total_bands}"
        )

        return {
            "success": True,
            "analysis_id": str(analysis_id),
            "lanes_processed": len(results),
            "lanes_successful": sum(1 for r in results if r["success"]),
            "total_bands": total_bands,
            "results": results,
            "task_id": self.request.id,
        }

    except GelAnalysis.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Analysis {analysis_id} not found")
        raise ValueError(f"Analysis {analysis_id} not found") from None
    except Exception:
        logger.exception(f"[Task {self.request.id}] CV2 bulk detection failed")
        raise


@shared_task(bind=True, soft_time_limit=5, time_limit=10)
def band_detection_ping_task(self) -> dict:
    """
    Simple ping task to check if Celery is running for band detection.

    Returns:
        Dict with pong response and task info
    """
    return {
        "status": "pong",
        "module": "gel_analyzer",
        "task_id": self.request.id,
        "worker": self.request.hostname,
    }


# ============================================================================
# Profile Peak Detection Tasks
# ============================================================================


@robust_task(
    autoretry_for=(IOError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=600,  # 10 minutes soft limit
    time_limit=720,  # 12 minutes hard limit
)
def detect_peaks_profile_bulk_task(
    self,
    analysis_id: str,
    lane_ids: list[int],
    params_dict: dict | None = None,
    user_id: int | None = None,
) -> dict:
    """
    Detect peaks from intensity profiles for multiple lanes asynchronously.

    Uses AdvancedPeakDetector from densitometry services to detect peaks
    in the intensity profile and create bands.

    Args:
        analysis_id: UUID of the GelAnalysis to process
        lane_ids: List of lane IDs to process
        params_dict: Detection parameters dict
            - sensitivity: float (0.5-1.0, default 0.85)
            - min_peak_distance: int (pixels, default 10)
            - match_tolerance_px: int (pixels, default 15)
            - smoothing_window: int (default 11)
            - enable_deconvolution: bool (default False)
            - enable_shoulder_detection: bool (default True)
        user_id: User ID for audit trail

    Returns:
        Dict with detection results
    """
    from django.contrib.auth import get_user_model

    from gel_analyzer.models import Band, GelAnalysis, Lane
    from gel_analyzer.services.band_detection import BandDetectionParams
    from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
    from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor
    from gel_analyzer.services.densitometry import (
        AdvancedPeakDetector,
        PeakDeconvolutionService,
        PeakDetectionParams,
        PeakMatchingService,
    )
    from gel_analyzer.services.file_handler import GelFileHandler

    User = get_user_model()

    logger.bind(
        task_id=self.request.id,
        analysis_id=analysis_id,
        lane_ids=lane_ids,
        lane_count=len(lane_ids),
    ).info("Profile peak detection task started")

    try:
        # Get analysis
        analysis = GelAnalysis.objects.select_related("gel_image").get(pk=analysis_id)

        # Get lanes with prefetch
        lanes = list(
            Lane.objects.filter(pk__in=lane_ids, analysis=analysis).prefetch_related("bands").order_by("lane_number")
        )

        if not lanes:
            logger.bind(
                task_id=self.request.id,
                analysis_id=analysis_id,
                lane_ids_received=lane_ids,
            ).error("No lanes found matching provided IDs")
            return {
                "success": False,
                "error": f"No lanes found for IDs: {lane_ids}",
                "lanes_processed": 0,
                "total_bands_created": 0,
                "results": [],
                "task_id": self.request.id,
            }

        # Get user for audit (validates existence; not currently consumed downstream)
        if user_id:
            User.objects.get(pk=user_id)

        # Build detection params
        params_dict = params_dict or {}
        detection_params = PeakDetectionParams.from_dict(params_dict)
        band_params = BandDetectionParams(
            smoothing_window=params_dict.get("smoothing_window", 11),
        )

        # Load image once
        logger.debug(f"[Task {self.request.id}] Loading image")
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Setup extractors
        extractor = IntensityProfileExtractor(band_params)
        processor = ProfileProcessor(band_params)

        results = []
        total_bands_created = 0

        with transaction.atomic():
            for i, lane in enumerate(lanes, 1):
                # Report progress
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "current": i,
                        "total": len(lanes),
                        "lane_number": lane.lane_number,
                    },
                )

                logger.debug(f"[Task {self.request.id}] Processing lane {lane.lane_number} ({i}/{len(lanes)})")

                try:
                    # Extract and process profile
                    profile = extractor.extract_profile(image, lane)
                    profile = processor.process(profile)

                    # Detect peaks
                    detector = AdvancedPeakDetector(detection_params)
                    peaks = detector.detect_peaks(profile)

                    # Optionally deconvolve
                    if detection_params.enable_deconvolution and peaks:
                        deconv_service = PeakDeconvolutionService()
                        peaks = deconv_service.deconvolve_wide_peaks(
                            profile, peaks, width_threshold=detection_params.deconvolution_threshold_px
                        )

                    # Get existing bands (already prefetched)
                    existing_bands = list(lane.bands.all())
                    match_tolerance = params_dict.get("match_tolerance_px", 15)

                    # Match peaks to bands
                    matching_service = PeakMatchingService(tolerance_px=match_tolerance)
                    match_result = matching_service.match_peaks_to_bands(peaks, existing_bands, lane.id)

                    # Determine band type based on lane type
                    band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"

                    # Create bands for orphan peaks
                    bands_created = 0
                    for peak in match_result.peaks:
                        if peak.is_orphan:
                            Band.objects.create(
                                lane=lane,
                                detection_source="PROFILE",
                                band_type=band_type,
                                position_y=peak.y_position,
                                bbox_x=lane.x,
                                bbox_y=max(0, peak.y_position - peak.width_px // 2),
                                bbox_width=lane.width,
                                bbox_height=peak.width_px,
                            )
                            bands_created += 1

                    total_bands_created += bands_created

                    results.append(
                        {
                            "lane_id": lane.id,
                            "lane_number": lane.lane_number,
                            "success": True,
                            "peaks_detected": match_result.total_peaks,
                            "orphan_count": match_result.orphan_count,
                            "matched_count": match_result.matched_count,
                            "bands_created": bands_created,
                        }
                    )

                except Exception as e:
                    logger.warning(f"[Task {self.request.id}] Failed to process lane {lane.lane_number}: {e}")
                    results.append(
                        {
                            "lane_id": lane.id,
                            "lane_number": lane.lane_number,
                            "success": False,
                            "error": str(e),
                        }
                    )

            # Update analysis counts
            analysis.update_counts()

        logger.info(
            f"[Task {self.request.id}] === PROFILE PEAK DETECTION TASK COMPLETED === "
            f"analysis_id={analysis_id}, lanes={len(results)}, bands_created={total_bands_created}"
        )

        return {
            "success": True,
            "analysis_id": str(analysis_id),
            "lanes_processed": len(results),
            "lanes_successful": sum(1 for r in results if r.get("success")),
            "total_bands_created": total_bands_created,
            "results": results,
            "task_id": self.request.id,
        }

    except GelAnalysis.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Analysis {analysis_id} not found")
        raise ValueError(f"Analysis {analysis_id} not found") from None

    except Exception:
        logger.exception(f"[Task {self.request.id}] Profile peak detection failed for analysis {analysis_id}")
        raise


# ============================================================================
# Densitometry Tasks
# ============================================================================


@robust_task(
    autoretry_for=(IOError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=600,  # 10 minutes soft limit (increased for large analyses)
    time_limit=720,  # 12 minutes hard limit
)
def run_densitometry_task(
    self,
    analysis_id: str,
    params_dict: dict | None = None,
    user_id: int | None = None,
    lane_ids: list[int] | None = None,
    save_results: bool = True,
    job_id: str | None = None,
) -> dict:
    """
    Run densitometry analysis asynchronously.

    Analyzes all (or specified) lanes in a GelAnalysis, computing
    Gaussian fits and integrated areas for each band.

    Args:
        analysis_id: UUID of the GelAnalysis to process
        params_dict: Optional densitometry parameters dict
        user_id: User ID (required if save_results=True)
        lane_ids: Optional list of specific lane IDs (None = all lanes)
        save_results: Whether to save results to database
        job_id: UUID of the DensitometryJob created by the view (preferred lookup)

    Returns:
        Dict with densitometry results
    """
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from gel_analyzer.models import DensitometryJob, GelAnalysis
    from gel_analyzer.services.densitometry import (
        DensitometryParams,
        DensitometryService,
    )
    from gel_analyzer.services.file_handler import GelFileHandler

    User = get_user_model()

    logger.info(
        f"[Task {self.request.id}] === DENSITOMETRY TASK STARTED === "
        f"analysis_id={analysis_id}, lanes={lane_ids or 'all'}, save={save_results}"
    )

    # Find or create job record
    job = None
    try:
        analysis = GelAnalysis.objects.select_related("gel_image").get(pk=analysis_id)

        # Prefer lookup by job_id (passed from view) to avoid race condition
        # where the task starts before the view saves task_id to the job.
        if job_id:
            job = DensitometryJob.objects.filter(pk=job_id).first()

        # Fallback: lookup by task_id (backward compat)
        if not job:
            job = DensitometryJob.objects.filter(
                analysis=analysis,
                task_id=self.request.id,
            ).first()

        if not job:
            job = DensitometryJob.objects.create(
                analysis=analysis,
                task_id=self.request.id,
                status=DensitometryJob.Status.RUNNING,
                started_at=timezone.now(),
                params=params_dict or {},
                lane_ids=lane_ids,
                created_by_id=user_id,
            )
        else:
            # Ensure task_id is set (may be empty if we found by job_id)
            if not job.task_id:
                job.task_id = self.request.id
                job.save(update_fields=["task_id"])
            job.mark_running()

    except GelAnalysis.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Analysis {analysis_id} not found")
        return {
            "success": False,
            "error": f"Analysis {analysis_id} not found",
            "task_id": self.request.id,
        }

    try:
        # Get user if saving
        user = None
        if save_results:
            if user_id is None:
                raise ValueError("user_id required when save_results=True")
            user = User.objects.get(pk=user_id)

        # Build params
        params = DensitometryParams.from_dict(params_dict) if params_dict else DensitometryParams()

        # Load image
        logger.debug(f"[Task {self.request.id}] Loading image")
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Create service
        service = DensitometryService(params)

        # Progress callback
        def progress_callback(current, total, lane_number):
            progress = int((current / total) * 100)
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": current,
                    "total": total,
                    "lane_number": lane_number,
                    "progress": progress,
                },
            )
            if job:
                job.update_progress(progress)

        # Run analysis
        if save_results:
            result = service.analyze_and_save(
                analysis=analysis,
                image=image,
                user=user,
                lane_ids=lane_ids,
                progress_callback=progress_callback,
            )
        else:
            result = service.analyze_analysis(
                analysis=analysis,
                image=image,
                lane_ids=lane_ids,
                progress_callback=progress_callback,
            )

        logger.info(
            f"[Task {self.request.id}] === DENSITOMETRY TASK COMPLETED === "
            f"analysis_id={analysis_id}, lanes={result.lanes_processed}, "
            f"bands={result.total_bands}, time={result.processing_time_ms:.0f}ms"
        )

        response = result.to_dict()
        response["task_id"] = self.request.id

        if job:
            job.mark_completed(
                result={
                    "lanes_processed": result.lanes_processed,
                    "total_bands": result.total_bands,
                    "gel_total_area": result.gel_total_area,
                    "average_poi_percentage": result.average_poi_percentage,
                }
            )

        return response

    except Exception as e:
        logger.exception(f"[Task {self.request.id}] Densitometry failed for analysis {analysis_id}")

        if job:
            job.mark_failed(str(e))

        raise


@robust_task(
    soft_time_limit=60,
    time_limit=90,
)
def export_densitometry_csv_task(
    self,
    analysis_id: str,
    include_profile: bool = False,
    user_id: int | None = None,
) -> dict:
    """
    Generate CSV export for densitometry results.

    Args:
        analysis_id: UUID of the GelAnalysis
        include_profile: Whether to include profile data in export
        user_id: User ID for audit

    Returns:
        Dict with export file path or content
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    from gel_analyzer.models import GelAnalysis
    from gel_analyzer.services.densitometry import DensitometryService
    from gel_analyzer.services.densitometry.export import DensitometryExporter, generate_csv_filename
    from gel_analyzer.services.file_handler import GelFileHandler

    logger.info(f"[Task {self.request.id}] === DENSITOMETRY EXPORT STARTED === analysis_id={analysis_id}")

    try:
        analysis = GelAnalysis.objects.select_related("gel_image").get(pk=analysis_id)

        # Run fresh analysis (or load from DB if available)
        # For now, run fresh analysis
        image = GelFileHandler.load_image_as_array(analysis.gel_image)
        service = DensitometryService()
        result = service.analyze_analysis(analysis, image)

        if not result.success:
            return {
                "success": False,
                "error": result.error_message or "Analysis failed",
                "task_id": self.request.id,
            }

        # Generate CSV
        exporter = DensitometryExporter()
        csv_content = exporter.export_csv(result, analysis, include_profile)

        # Generate filename
        filename = generate_csv_filename(analysis)

        # Save to storage
        file_path = f"exports/densitometry/{filename}"
        saved_path = default_storage.save(file_path, ContentFile(csv_content.encode("utf-8")))

        logger.info(f"[Task {self.request.id}] === DENSITOMETRY EXPORT COMPLETED === file={saved_path}")

        return {
            "success": True,
            "file_path": saved_path,
            "filename": filename,
            "task_id": self.request.id,
        }

    except GelAnalysis.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Analysis {analysis_id} not found")
        raise ValueError(f"Analysis {analysis_id} not found") from None

    except Exception:
        logger.exception(f"[Task {self.request.id}] Densitometry export failed for analysis {analysis_id}")
        raise


@shared_task(bind=True, soft_time_limit=5, time_limit=10)
def densitometry_ping_task(self) -> dict:
    """
    Simple ping task to check if Celery is running for densitometry.

    Returns:
        Dict with pong response and task info
    """
    return {
        "status": "pong",
        "module": "gel_analyzer.densitometry",
        "task_id": self.request.id,
        "worker": self.request.hostname,
    }


# ============================================================================
# Hybrid Band Detection Tasks
# ============================================================================


@robust_task(
    autoretry_for=(IOError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=600,
    time_limit=720,
)
def detect_bands_hybrid_bulk_task(
    self,
    analysis_id: str,
    lane_ids: list[int] | None = None,
    params_dict: dict | None = None,
    user_id: int | None = None,
    save_results: bool = False,
) -> dict:
    """Detect bands in multiple lanes using hybrid detector (async)."""
    from django.contrib.auth import get_user_model

    from gel_analyzer.models import Band, GelAnalysis, Lane
    from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
    from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams
    from gel_analyzer.services.file_handler import GelFileHandler

    User = get_user_model()

    logger.info(
        f"[Task {self.request.id}] === HYBRID BULK DETECTION STARTED === "
        f"analysis_id={analysis_id}, lane_count={len(lane_ids) if lane_ids else 'all'}, "
        f"save={save_results}"
    )

    try:
        analysis = GelAnalysis.objects.select_related("gel_image").get(pk=analysis_id)
        lanes = analysis.lanes.all()
        if lane_ids:
            lanes = lanes.filter(pk__in=lane_ids)
        lanes = list(lanes.order_by("lane_number"))

        if not lanes:
            return {
                "success": True,
                "lanes_processed": 0,
                "total_bands": 0,
                "results": [],
                "task_id": self.request.id,
            }

        user = None
        if save_results:
            if user_id is None:
                raise ValueError("user_id required when save_results=True")
            user = User.objects.get(pk=user_id)

        params = HybridDetectionParams.from_dict(params_dict) if params_dict else HybridDetectionParams()
        image = GelFileHandler.load_image_as_array(analysis.gel_image)
        detector = HybridDetector(params)
        results = []

        with transaction.atomic():
            for i, lane in enumerate(lanes, 1):
                self.update_state(
                    state="PROGRESS", meta={"current": i, "total": len(lanes), "lane_number": lane.lane_number}
                )

                b = lane.bbox
                x, y, w, h = b["x"], b["y"], b["width"], b["height"]
                lane_crop = image[y : y + h, x : x + w]
                bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h))

                if save_results:
                    # Replace ALL auto-detected bands (hybrid, CV2/d1d2,
                    # profile, CV2 vision, YOLO, SAM) but preserve MANUAL
                    # annotations (user-created bands via Ctrl+click or
                    # drag-to-draw). The user ran a new detection method —
                    # they want the previous auto results replaced, not
                    # stacked.
                    auto_sources = [
                        Band.DetectionSource.HYBRID,
                        Band.DetectionSource.AUTO,
                        Band.DetectionSource.CV2_VISION,
                        Band.DetectionSource.PROFILE,
                        Band.DetectionSource.YOLO,
                        Band.DetectionSource.SAM,
                    ]
                    Band.objects.filter(
                        lane=lane,
                        detection_source__in=auto_sources,
                    ).delete()

                    band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"

                    for j, detected in enumerate(bands, 1):
                        band_metadata = {
                            "hybrid_phase": getattr(detected, "_hybrid_phase", "primary"),
                        }
                        Band.objects.create(
                            lane=lane,
                            band_number=j,
                            position_y=detected.position_y,
                            bbox_x=detected.bbox_x,
                            bbox_y=detected.bbox_y,
                            bbox_width=detected.bbox_width,
                            bbox_height=detected.bbox_height,
                            polygon=detected.polygon,
                            confidence=detected.confidence,
                            detection_source=Band.DetectionSource.HYBRID,
                            band_type=band_type,
                            intensity_raw=detected.intensity_raw,
                            intensity_peak=detected.intensity_peak,
                            area_pixels=detected.area_pixels,
                            metadata=band_metadata,
                            created_by=user,
                        )

                results.append(
                    {
                        "lane_id": lane.pk,
                        "lane_number": lane.lane_number,
                        "band_count": len(bands),
                        "bands": [bd.to_dict() for bd in bands],
                        "summary": detector.last_summary,
                        "success": True,
                    }
                )

            if save_results:
                analysis.update_counts()

        total_bands = sum(r["band_count"] for r in results)

        logger.info(
            f"[Task {self.request.id}] === HYBRID BULK DETECTION COMPLETED === "
            f"lanes={len(results)}, bands={total_bands}"
        )

        return {
            "success": True,
            "analysis_id": str(analysis_id),
            "lanes_processed": len(results),
            "lanes_successful": sum(1 for r in results if r["success"]),
            "total_bands": total_bands,
            "results": results,
            "task_id": self.request.id,
        }

    except GelAnalysis.DoesNotExist:
        logger.error(f"[Task {self.request.id}] Analysis {analysis_id} not found")
        raise ValueError(f"Analysis {analysis_id} not found") from None
    except Exception:
        logger.exception(f"[Task {self.request.id}] Hybrid bulk detection failed")
        raise
