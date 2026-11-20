"""
BandDetectionService - Orchestrator for the band detection pipeline.

Uses chromatography-inspired derivative analysis (DerivativeDetector)
for automatic peak identification via d1/d2 zero-crossings.

Detection workflow:
1. Load image and lane data
2. Detect polarity and invert image if white background
3. Apply CLAHE contrast enhancement (optional)
4. Extract intensity profile from lane region
5. Process profile (SG smooth, background subtraction, compute derivatives)
6. Detect peaks via DerivativeDetector (d1/d2 zero-crossing analysis)
7. Build band geometry from peaks
8. Refine band polygons using MobileSAM (automatic)
9. Optionally persist results to database

Operating modes:
- Preview mode: Returns detected bands without saving
- Save mode: Creates Band model instances in database
- Ladder-guided mode: Template-based detection for ladder lanes (uses legacy PeakDetector)

MobileSAM Integration:
When enabled (default), the service automatically refines band
polygons using MobileSAM's decoder. This produces precise
segmentation masks from bounding box prompts.
"""

from __future__ import annotations

import base64
import dataclasses
import time
from typing import TYPE_CHECKING

import numpy as np

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from gel_analyzer.models import Band, GelAnalysis, GelImage, LadderTemplate, Lane

from .geometry_builder import BandGeometryBuilder
from .models import BandDetectionParams, BandDetectionResult, BandDetectionSource, DetectedBand
from .peak_detector import PeakDetector  # DEPRECATED: used only by _detect_ladder_guided()
from .profile_extractor import IntensityProfileExtractor
from .profile_processor import ProfileProcessor

logger = get_logger(__name__)

# SAM configuration
SAM_ENABLED = True  # Enable automatic SAM polygon refinement


class BandDetectionService:
    """
    Orchestrates band detection for gel electrophoresis lanes.

    The service coordinates five pipeline stages:
    1. IntensityProfileExtractor: Extract 1D intensity profile from lane region
    2. ProfileProcessor: SG smoothing, background subtraction, derivative computation
    3. DerivativeDetector: d1/d2 zero-crossing peak detection
    4. BandGeometryBuilder: Create band bounding boxes and polygons
    5. MobileSAM: Refine band polygons (optional)

    Usage:
        service = BandDetectionService(params)

        # Preview mode (no database changes)
        result = service.detect_bands_in_lane(lane, image)

        # Save mode (creates Band instances)
        result = service.detect_and_save(lane, image, user)

        # Bulk detection for entire analysis
        results = service.detect_all_lanes(analysis, user, save_results=True)
    """

    def __init__(self, params: BandDetectionParams | None = None, enable_sam: bool = True):
        """
        Initialize service with detection parameters.

        Args:
            params: Detection parameters. If None, uses defaults.
            enable_sam: If True, automatically refine polygons with MobileSAM.
        """
        self.params = params or BandDetectionParams()
        self.enable_sam = enable_sam and SAM_ENABLED

        # Initialize pipeline components
        self.extractor = IntensityProfileExtractor(self.params)
        self.processor = ProfileProcessor(self.params)
        self.peak_detector = PeakDetector(self.params)
        self.geometry_builder = BandGeometryBuilder(self.params)

        # SAM services (lazy-loaded)
        self._sam_encoder = None
        self._sam_decoder = None
        self._cached_embeddings = None
        self._cached_image_id = None

    def _detect_and_invert_image(
        self,
        image: np.ndarray,
        scaled_params: BandDetectionParams,
    ) -> tuple[np.ndarray, BandDetectionParams, bool]:
        """Detect white background and invert the entire image if needed.

        Instead of inverting 1D profiles after extraction, invert the full
        image so the entire pipeline (CLAHE, profile extraction, background
        subtraction, peak detection) operates on a dark-background image.
        This is far more robust than post-hoc profile inversion.

        Returns:
            Tuple of (possibly inverted image, updated params, was_inverted).
        """
        invert_mode = scaled_params.invert_profile

        if invert_mode == "never":
            return image, scaled_params, False

        if invert_mode == "always":
            logger.info("Image polarity: mode='always', inverting full image")
            inverted = image.max() - image
            # Disable profile-level inversion since image is already inverted
            updated_params = dataclasses.replace(scaled_params, invert_profile="never")
            return inverted, updated_params, True

        # Auto-detect using image-level statistics
        from .profile_processor import detect_image_polarity

        image_polarity = detect_image_polarity(image)

        if image_polarity == "always":
            logger.info("Image polarity: bright background detected, inverting full image")
            inverted = image.max() - image
            updated_params = dataclasses.replace(scaled_params, invert_profile="never")
            return inverted, updated_params, True

        # Dark background or ambiguous — no inversion needed
        # For ambiguous, leave invert_profile="auto" so lane-level heuristics
        # in ProfileProcessor can still trigger if needed
        if image_polarity == "never":
            updated_params = dataclasses.replace(scaled_params, invert_profile="never")
            return image, updated_params, False

        return image, scaled_params, False

    def _apply_clahe(self, image: np.ndarray) -> np.ndarray:
        """Apply CLAHE preprocessing to enhance local contrast for band detection.

        Supports uint8, uint16, and float images. For 16-bit inputs, CLAHE
        operates natively in uint16 to preserve the full dynamic range
        (65,536 levels vs 256 for uint8). Float inputs are normalized to
        uint16 for maximum precision.
        """
        if not self.params.clahe_enabled:
            return image

        # Convert to grayscale if needed
        if len(image.shape) == 3:
            work = np.dot(image[..., :3], [0.299, 0.587, 0.114]).astype(image.dtype)
        else:
            work = image.copy()

        # Normalize to uint8 or uint16 for OpenCV CLAHE
        if work.dtype == np.uint8:
            pass  # Already good
        elif work.dtype == np.uint16:
            pass  # CLAHE supports uint16 natively
        elif work.dtype in (np.float32, np.float64):
            # Float -> normalize to uint16 for maximum precision
            w_min, w_max = work.min(), work.max()
            if w_max > w_min:
                work = ((work - w_min) / (w_max - w_min) * 65535).astype(np.uint16)
            else:
                work = np.zeros_like(work, dtype=np.uint16)
        else:
            # Fallback: normalize to uint8
            from gel_analyzer.services.file_handler import GelFileHandler

            work = GelFileHandler.normalize_to_8bit(work)

        import cv2

        # Scale tile grid to keep tiles ~100px regardless of image size.
        # Hardcoded (8,8) creates ~256px tiles on large images (2048px),
        # destroying the local contrast CLAHE is meant to enhance.
        h, w = work.shape[:2]
        tiles_y = max(4, min(32, h // 100))
        tiles_x = max(4, min(32, w // 100))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(tiles_x, tiles_y))
        return clahe.apply(work)

    def detect_bands_in_lane(
        self,
        lane: Lane,
        image: np.ndarray,
        gel_image: GelImage | None = None,
    ) -> BandDetectionResult:
        """
        Detect bands in a single lane (preview mode).

        Runs the full detection pipeline without persisting results.
        Use this for previewing detection before saving.

        Args:
            lane: Lane model instance with geometry.
            image: Gel image as numpy array (grayscale or RGB).
            gel_image: Optional GelImage model for SAM embedding caching.
                      If not provided, attempts to get from lane.analysis.

        Returns:
            BandDetectionResult with detected bands and metadata.
        """
        start_time = time.time()

        # Get gel_image for SAM caching
        if gel_image is None:
            try:
                gel_image = lane.analysis.gel_image
            except AttributeError:
                gel_image = None

        try:
            # Scale pixel-based params for this lane's profile length.
            # Params operate on the 1D profile (length = lane height), NOT the
            # full image. The display image is already resized to max 2048px,
            # so image.shape[0] would over-scale on normal-sized lanes.
            profile_length = lane.height
            scaled_params = self.params.scaled(profile_length)

            # Build pipeline with scaled params for this run
            extractor = IntensityProfileExtractor(scaled_params)
            processor = ProfileProcessor(scaled_params)
            geometry_builder = BandGeometryBuilder(scaled_params)

            logger.info(
                f"=== Band detection: lane {lane.lane_number} ===\n"
                f"  Image: shape={image.shape}, dtype={image.dtype}, "
                f"range=[{image.min()}, {image.max()}]\n"
                f"  Lane: x={lane.x}, y={lane.y}, w={lane.width}, h={lane.height}\n"
                f"  Params: sensitivity={scaled_params.sensitivity}, "
                f"invert={scaled_params.invert_profile}, clahe={scaled_params.clahe_enabled}"
            )

            if scaled_params is not self.params:
                logger.info(
                    f"Lane {lane.lane_number}: scaled params for {profile_length}px lane "
                    f"(max_band_width={scaled_params.max_band_width_px}, "
                    f"rolling_ball={scaled_params.rolling_ball_radius}, "
                    f"peak_distance={scaled_params.peak_distance})"
                )

            # Step 0: Detect polarity and invert full image if white background
            image, scaled_params, was_inverted = self._detect_and_invert_image(image, scaled_params)
            if was_inverted:
                logger.info(f"Lane {lane.lane_number}: using inverted image for detection")
            # Rebuild processor with potentially updated params
            processor = ProfileProcessor(scaled_params)

            # Step 1: Extract intensity profile (use CLAHE-enhanced image if enabled)
            logger.debug(f"Extracting profile for lane {lane.lane_number}")
            detection_image = self._apply_clahe(image)
            profile = extractor.extract_profile(detection_image, lane)

            if profile.is_empty:
                logger.warning(f"Empty profile for lane {lane.lane_number}")
                return BandDetectionResult(
                    lane_id=lane.pk,
                    lane_number=lane.lane_number,
                    bands=[],
                    profile=profile,
                    params_used=scaled_params,
                    success=True,
                    processing_time_ms=(time.time() - start_time) * 1000,
                )

            # Step 2: Process profile (smooth + background subtraction)
            logger.debug(f"Processing profile for lane {lane.lane_number}")
            profile = processor.process(profile)
            # If image was inverted, mark on profile for UI reporting
            if was_inverted:
                profile.was_inverted = True

            # Step 3: Detect peaks (derivative-based detection)
            logger.debug(f"Detecting peaks for lane {lane.lane_number}")
            from .derivative_detector import DerivativeDetector

            detector = DerivativeDetector(scaled_params)
            peaks, threshold_used = detector.detect(profile)

            logger.debug(f"Found {len(peaks)} peaks in lane {lane.lane_number}")

            # Step 4: Build band geometry (bboxes only, empty polygons)
            logger.debug(f"Building geometry for lane {lane.lane_number}")
            bands = geometry_builder.build_bands(peaks, profile, lane, image)

            # Step 5: Refine polygons with SAM (automatic)
            if bands and self.enable_sam and gel_image:
                logger.debug(f"Refining {len(bands)} bands with SAM")
                bands = self.refine_bands_with_sam(bands, gel_image, image)

            processing_time = (time.time() - start_time) * 1000

            sam_status = "with SAM" if self.enable_sam and gel_image else "without SAM"
            logger.info(
                f"Lane {lane.lane_number}: detected {len(bands)} bands in {processing_time:.1f}ms ({sam_status})"
            )

            return BandDetectionResult(
                lane_id=lane.pk,
                lane_number=lane.lane_number,
                bands=bands,
                profile=profile,
                params_used=scaled_params,
                success=True,
                processing_time_ms=processing_time,
                threshold_used=threshold_used,
                detection_diagnostics=detector.diagnostics,
            )

        except Exception as e:
            logger.error(f"Band detection failed for lane {lane.lane_number}: {e}")
            return BandDetectionResult(
                lane_id=lane.pk,
                lane_number=lane.lane_number,
                bands=[],
                profile=None,
                params_used=self.params,
                success=False,
                error_message=str(e),
                processing_time_ms=(time.time() - start_time) * 1000,
            )

    def detect_and_save(
        self,
        lane: Lane,
        image: np.ndarray,
        user: User,
        delete_existing: bool = True,
        gel_image: GelImage | None = None,
        use_template_guidance: bool = True,
    ) -> BandDetectionResult:
        """
        Detect bands and save results to database.

        For LADDER lanes with a template that has learned Rf patterns,
        uses template-guided detection to filter ghost bands.

        Args:
            lane: Lane model instance.
            image: Gel image as numpy array.
            user: User performing the detection.
            delete_existing: If True, deletes existing auto-detected bands first.
            gel_image: Optional GelImage model for SAM embedding caching.
            use_template_guidance: If True, uses template-guided detection for
                                   LADDER lanes with learned Rf patterns.

        Returns:
            BandDetectionResult with saved Band instances.
        """
        # Import here to avoid circular imports
        from gel_analyzer.models import Band
        from gel_analyzer.models import Lane as LaneModel

        # Check if we should use template-guided detection
        logger.info(
            f"Detection decision for lane {lane.lane_number}: "
            f"use_template_guidance={use_template_guidance}, "
            f"lane_type={lane.lane_type}, "
            f"ladder_template_id={lane.ladder_template_id}"
        )

        if use_template_guidance and lane.lane_type == LaneModel.LaneType.LADDER:
            template = lane.ladder_template
            if template:
                trained_bands = template.bands.filter(expected_rf__isnull=False).count()
                total_bands = template.bands.count()
                logger.info(f"Template {template.code}: {trained_bands}/{total_bands} bands have expected_rf")

                if trained_bands > 0:
                    logger.info(f">>> Using TEMPLATE-GUIDED detection for lane {lane.lane_number}")
                    return self._detect_ladder_guided(
                        lane=lane,
                        image=image,
                        template=template,
                        user=user,
                        delete_existing=delete_existing,
                        gel_image=gel_image,
                    )
                else:
                    logger.warning(f"Template {template.code} has no trained Rf patterns, using standard detection")
            else:
                logger.info(f"Lane {lane.lane_number} is LADDER but has no template assigned")
        else:
            logger.info(f">>> Using STANDARD detection for lane {lane.lane_number}")

        # Fall back to standard detection
        result = self.detect_bands_in_lane(lane, image, gel_image=gel_image)

        if not result.success or not result.bands:
            return result

        # Delete existing CV2-detected bands if requested
        if delete_existing:
            deleted_count = Band.objects.filter(
                lane=lane,
                detection_source=Band.DetectionSource.AUTO,
            ).delete()[0]

            if deleted_count > 0:
                logger.debug(f"Deleted {deleted_count} existing auto-detected bands from lane {lane.lane_number}")

        # Create Band instances
        saved_bands = []
        for i, detected_band in enumerate(result.bands, start=1):
            band = self._create_band_from_detection(
                lane=lane,
                detected_band=detected_band,
                band_number=i,
                user=user,
            )
            saved_bands.append(band)

        logger.info(f"Saved {len(saved_bands)} bands for lane {lane.lane_number}")

        return result

    def _detect_ladder_guided(
        self,
        lane: Lane,
        image: np.ndarray,
        template: LadderTemplate,
        user: User,
        delete_existing: bool = True,
        gel_image: GelImage | None = None,
    ) -> BandDetectionResult:
        """
        Template-guided detection for ladder lanes.

        Uses learned Rf positions to find expected bands and filter ghost bands.
        Automatically sets MW values and creates calibration.

        Args:
            lane: Lane model instance (must be LADDER type).
            image: Gel image as numpy array.
            template: LadderTemplate with learned Rf patterns.
            user: User performing the detection.
            delete_existing: If True, deletes existing bands first.
            gel_image: Optional GelImage for SAM caching.

        Returns:
            BandDetectionResult with detected bands.
        """
        import time

        from gel_analyzer.models import Band

        start_time = time.time()

        # Get gel_image for SAM caching
        if gel_image is None:
            try:
                gel_image = lane.analysis.gel_image
            except AttributeError:
                gel_image = None

        try:
            # Scale pixel-based params for this lane's profile length.
            profile_length = lane.height
            scaled_params = self.params.scaled(profile_length)

            # Build pipeline with scaled params for this run
            extractor = IntensityProfileExtractor(scaled_params)
            processor = ProfileProcessor(scaled_params)
            peak_detector = PeakDetector(scaled_params)
            geometry_builder = BandGeometryBuilder(scaled_params)

            if scaled_params is not self.params:
                logger.info(
                    f"Lane {lane.lane_number} (ladder-guided): scaled params for {profile_length}px lane "
                    f"(max_band_width={scaled_params.max_band_width_px}, "
                    f"rolling_ball={scaled_params.rolling_ball_radius})"
                )

            # Step 0: Detect polarity and invert full image if white background
            image, scaled_params, was_inverted = self._detect_and_invert_image(image, scaled_params)
            if was_inverted:
                logger.info(f"Lane {lane.lane_number} (ladder-guided): using inverted image")
            # Rebuild processor with potentially updated params
            processor = ProfileProcessor(scaled_params)

            # Step 1: Run standard detection to find ALL peaks
            logger.debug(f"Template-guided detection for lane {lane.lane_number} using {template.code}")

            detection_image = self._apply_clahe(image)
            profile = extractor.extract_profile(detection_image, lane)
            if profile.is_empty:
                return BandDetectionResult(
                    lane_id=lane.pk,
                    lane_number=lane.lane_number,
                    bands=[],
                    profile=profile,
                    params_used=scaled_params,
                    success=True,
                    processing_time_ms=(time.time() - start_time) * 1000,
                )

            profile = processor.process(profile)

            # Find peaks with more generous sensitivity
            peak_detector.params.min_peak_prominence = 0.02  # Lower threshold
            peaks = peak_detector.find_peaks(profile)

            if not peaks:
                logger.warning(f"No peaks found in lane {lane.lane_number}")
                return BandDetectionResult(
                    lane_id=lane.pk,
                    lane_number=lane.lane_number,
                    bands=[],
                    profile=profile,
                    params_used=scaled_params,
                    success=True,
                    processing_time_ms=(time.time() - start_time) * 1000,
                )

            # Build band geometry for all peaks
            all_bands = geometry_builder.build_bands(peaks, profile, lane, image)

            # Step 2: Get expected bands from template
            expected_bands = list(template.bands.filter(expected_rf__isnull=False).order_by("band_order"))

            if not expected_bands:
                logger.warning(f"Template {template.code} has no learned Rf patterns")
                # Fall back to all detected bands
                return BandDetectionResult(
                    lane_id=lane.pk,
                    lane_number=lane.lane_number,
                    bands=all_bands,
                    profile=profile,
                    params_used=scaled_params,
                    success=True,
                    processing_time_ms=(time.time() - start_time) * 1000,
                )

            # Step 3: Match peaks to expected Rf positions
            lane_top = lane.y
            lane_height = lane.height

            # Debug: Log all detected peaks with their Rf values
            logger.info(
                f"Lane {lane.lane_number}: Found {len(all_bands)} peaks, lane_top={lane_top}, lane_height={lane_height}"
            )
            for i, band in enumerate(all_bands):
                band_rf = (band.position_y - lane_top) / lane_height
                logger.info(f"  Peak {i}: position_y={band.position_y}, Rf={band_rf:.4f}")

            matched_bands = []
            used_indices = set()

            # Get first and last band orders for special handling
            first_band_order = expected_bands[0].band_order  # Highest MW (top of gel)
            last_band_order = expected_bands[-1].band_order  # Lowest MW (bottom of gel)

            for template_band in expected_bands:
                expected_rf = template_band.expected_rf
                tolerance = template_band.expected_rf_tolerance
                is_first_band = template_band.band_order == first_band_order
                is_last_band = template_band.band_order == last_band_order

                best_band = None
                best_distance = float("inf")
                best_idx = -1

                # Special handling for first band (highest MW):
                # Match to the FIRST unused peak (closest to well/top)
                # This band is always at the top - nothing bigger migrates above it
                if is_first_band:
                    for i, band in enumerate(all_bands):
                        if i in used_indices:
                            continue
                        # Take the first unused peak (lowest position_y = closest to top)
                        band_rf = (band.position_y - lane_top) / lane_height
                        best_band = band
                        best_distance = abs(band_rf - expected_rf)
                        best_idx = i
                        break  # Take the first one

                # Special handling for last band (lowest MW):
                # Match to the LAST unused peak (closest to dye front/bottom)
                elif is_last_band:
                    for i in range(len(all_bands) - 1, -1, -1):
                        band = all_bands[i]
                        if i in used_indices:
                            continue
                        band_rf = (band.position_y - lane_top) / lane_height
                        best_band = band
                        best_distance = abs(band_rf - expected_rf)
                        best_idx = i
                        break  # Take the last one

                # Standard Rf tolerance matching for middle bands
                else:
                    for i, band in enumerate(all_bands):
                        if i in used_indices:
                            continue

                        # Calculate Rf for this band
                        band_rf = (band.position_y - lane_top) / lane_height
                        distance = abs(band_rf - expected_rf)

                        if distance <= tolerance and distance < best_distance:
                            best_band = band
                            best_distance = distance
                            best_idx = i

                # Log matching result for each template band
                if best_band:
                    used_indices.add(best_idx)
                    matched_rf = (best_band.position_y - lane_top) / lane_height
                    match_type = "ANCHOR" if (is_first_band or is_last_band) else "RF"
                    logger.info(
                        f"  Template band {template_band.band_order} ({template_band.mw_kda} kDa): "
                        f"expected_rf={expected_rf:.4f} -> "
                        f"MATCHED ({match_type}) peak {best_idx} at Rf={matched_rf:.4f} (dist={best_distance:.4f})"
                    )
                    # Store match info for calibration
                    best_band.estimated_mw_kda = template_band.mw_kda
                    best_band.template_band_order = template_band.band_order
                    best_band.matched_rf = matched_rf
                    matched_bands.append(best_band)
                else:
                    logger.warning(
                        f"  Template band {template_band.band_order} ({template_band.mw_kda} kDa): "
                        f"expected_rf={expected_rf:.4f} ± {tolerance:.4f} -> NO MATCH FOUND"
                    )

            # Step 4: Refine matched bands with SAM
            if matched_bands and self.enable_sam and gel_image:
                matched_bands = self.refine_bands_with_sam(matched_bands, gel_image, image)

            # Step 5: Delete existing bands and save matched bands
            if delete_existing:
                deleted_count = Band.objects.filter(
                    lane=lane,
                    detection_source__in=[Band.DetectionSource.AUTO, Band.DetectionSource.SAM],
                ).delete()[0]
                if deleted_count > 0:
                    logger.debug(f"Deleted {deleted_count} existing bands from lane {lane.lane_number}")

            # Create Band instances with MW_REFERENCE type
            saved_bands = []
            calibration_matches = []

            for i, detected_band in enumerate(matched_bands, start=1):
                detection_source = Band.DetectionSource.SAM if detected_band.polygon else Band.DetectionSource.AUTO

                band = Band.objects.create(
                    lane=lane,
                    band_number=i,
                    bbox_x=detected_band.bbox_x,
                    bbox_y=detected_band.bbox_y,
                    bbox_width=detected_band.bbox_width,
                    bbox_height=detected_band.bbox_height,
                    position_y=detected_band.position_y,
                    polygon=detected_band.polygon if detected_band.polygon else [],
                    confidence=detected_band.confidence,
                    detection_source=detection_source,
                    band_type=Band.BandType.MW_REFERENCE,  # Always MW_REFERENCE for ladder bands
                    estimated_mw_kda=detected_band.estimated_mw_kda,
                    mw_estimation_method=f"TEMPLATE:{template.code}",
                    intensity_raw=detected_band.intensity_raw,
                    intensity_peak=detected_band.intensity_peak,
                    area_pixels=detected_band.area_pixels,
                    created_by=user,
                )
                saved_bands.append(band)

                # Build calibration match data
                calibration_matches.append(
                    {
                        "band_id": str(band.pk),
                        "template_band_order": getattr(detected_band, "template_band_order", i),
                        "mw_kda": detected_band.estimated_mw_kda,
                        "position_y": detected_band.position_y,
                        "rf": getattr(detected_band, "matched_rf", (detected_band.position_y - lane_top) / lane_height),
                    }
                )

            # Step 6: Auto-create calibration if we have enough matches
            if len(calibration_matches) >= 3:
                self._auto_create_calibration(
                    lane=lane,
                    template=template,
                    matches=calibration_matches,
                    user=user,
                )

            processing_time = (time.time() - start_time) * 1000

            logger.info(
                f"Lane {lane.lane_number}: template-guided detected "
                f"{len(matched_bands)}/{len(expected_bands)} expected bands "
                f"in {processing_time:.1f}ms"
            )

            return BandDetectionResult(
                lane_id=lane.pk,
                lane_number=lane.lane_number,
                bands=matched_bands,
                profile=profile,
                params_used=scaled_params,
                success=True,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"Template-guided detection failed for lane {lane.lane_number}: {e}")
            return BandDetectionResult(
                lane_id=lane.pk,
                lane_number=lane.lane_number,
                bands=[],
                profile=None,
                params_used=self.params,
                success=False,
                error_message=str(e),
                processing_time_ms=(time.time() - start_time) * 1000,
            )

    def _auto_create_calibration(
        self,
        lane: Lane,
        template: LadderTemplate,
        matches: list[dict],
        user: User,
    ) -> None:
        """
        Automatically create calibration from template-guided detection matches.

        Args:
            lane: Ladder lane.
            template: LadderTemplate used for detection.
            matches: List of match dicts with mw_kda, rf, position_y.
            user: User who triggered detection.
        """
        from gel_analyzer.models import LadderCalibration
        from gel_analyzer.services.calibration import CalibrationService
        from gel_analyzer.services.calibration.models import BandMatch

        try:
            service = CalibrationService()

            # Convert match dicts to BandMatch dataclass instances
            band_matches = [
                BandMatch(
                    band_id=m["band_id"],
                    template_band_order=m["template_band_order"],
                    mw_kda=m["mw_kda"],
                    position_y=int(m["position_y"]),
                    rf=m["rf"],
                )
                for m in matches
            ]

            # Run calibration computation
            result = service.calibrate(lane, template, band_matches)

            if not result.success:
                logger.warning(f"Auto-calibration failed for lane {lane.lane_number}: {result.error_message}")
                return

            # Create or update LadderCalibration record
            calibration, created = LadderCalibration.objects.update_or_create(
                analysis=lane.analysis,
                ladder_lane=lane,
                template=template,
                defaults={
                    "method": result.method,
                    "coefficients": result.coefficients,
                    "r_squared": result.r_squared,
                    "band_matches": [m.to_dict() for m in band_matches],
                    "matched_band_count": len(band_matches),
                    "ladder_x_position": lane.x + lane.width // 2,
                    "created_by": user,
                },
            )

            action = "Created" if created else "Updated"
            logger.info(
                f"{action} auto-calibration for lane {lane.lane_number}: "
                f"R²={result.r_squared:.4f}, {len(band_matches)} bands"
            )

        except Exception as e:
            # Don't fail detection if calibration fails
            logger.warning(f"Failed to auto-create calibration: {e}")

    def detect_all_lanes(
        self,
        analysis: GelAnalysis,
        user: User | None = None,
        save_results: bool = False,
        lane_ids: list[int] | None = None,
    ) -> list[BandDetectionResult]:
        """
        Detect bands in all lanes of an analysis.

        Args:
            analysis: GelAnalysis model instance.
            user: User performing detection (required if save_results=True).
            save_results: If True, saves detected bands to database.
            lane_ids: Optional list of specific lane IDs to process.
                     If None, processes all lanes.

        Returns:
            List of BandDetectionResult for each processed lane.
        """
        from gel_analyzer.services.file_handler import GelFileHandler

        # Load image
        try:
            image = GelFileHandler.load_image_as_array(analysis.gel_image)
        except Exception as e:
            logger.error(f"Failed to load image for analysis {analysis.pk}: {e}")
            return []

        # Get lanes to process
        lanes = analysis.lanes.all()
        if lane_ids:
            lanes = lanes.filter(pk__in=lane_ids)

        lanes = lanes.order_by("lane_number")

        if not lanes.exists():
            logger.warning(f"No lanes to process for analysis {analysis.pk}")
            return []

        # Get gel_image for SAM caching (shared across all lanes)
        gel_image = analysis.gel_image

        results = []
        for lane in lanes:
            if save_results:
                if user is None:
                    raise ValueError("User required when save_results=True")
                result = self.detect_and_save(lane, image, user, gel_image=gel_image)
            else:
                result = self.detect_bands_in_lane(lane, image, gel_image=gel_image)

            results.append(result)

        # Log summary
        total_bands = sum(len(r.bands) for r in results)
        successful = sum(1 for r in results if r.success)

        logger.info(
            f"Analysis {analysis.pk}: processed {len(results)} lanes, "
            f"{successful} successful, {total_bands} total bands"
        )

        return results

    def _create_band_from_detection(
        self,
        lane: Lane,
        detected_band: DetectedBand,
        band_number: int,
        user: User,
    ) -> Band:
        """
        Create a Band model instance from DetectedBand.

        Args:
            lane: Parent lane.
            detected_band: Detection result.
            band_number: Band number (1-indexed from top).
            user: User who initiated detection.

        Returns:
            Saved Band model instance.
        """
        from gel_analyzer.models import Band, Lane

        # Determine detection source based on whether SAM was used
        detection_source = Band.DetectionSource.SAM if detected_band.polygon else Band.DetectionSource.AUTO

        # Determine band type based on lane type
        # LADDER lanes -> MW_REFERENCE bands, otherwise OTHER
        band_type = Band.BandType.MW_REFERENCE if lane.lane_type == Lane.LaneType.LADDER else Band.BandType.OTHER

        band = Band.objects.create(
            lane=lane,
            band_number=band_number,
            # Individual bbox fields (bbox is a @property, not a field)
            bbox_x=detected_band.bbox_x,
            bbox_y=detected_band.bbox_y,
            bbox_width=detected_band.bbox_width,
            bbox_height=detected_band.bbox_height,
            position_y=detected_band.position_y,
            polygon=detected_band.polygon if detected_band.polygon else [],  # Empty list, not None
            confidence=detected_band.confidence,
            detection_source=detection_source,
            band_type=band_type,
            intensity_raw=detected_band.intensity_raw,
            intensity_peak=detected_band.intensity_peak,
            area_pixels=detected_band.area_pixels,
            created_by=user,
        )

        return band

    # -------------------------------------------------------------------------
    # SAM Integration Methods
    # -------------------------------------------------------------------------

    def _get_sam_encoder(self):
        """Lazy-load SAM encoder service."""
        if self._sam_encoder is None:
            try:
                from gel_analyzer.services.sam import MobileSAMEncoderService

                self._sam_encoder = MobileSAMEncoderService.get_instance()
            except Exception as e:
                logger.warning(f"Failed to load SAM encoder: {e}")
                self._sam_encoder = False  # Mark as failed
        return self._sam_encoder if self._sam_encoder else None

    def _get_sam_decoder(self):
        """Lazy-load SAM decoder service."""
        if self._sam_decoder is None:
            try:
                from gel_analyzer.services.sam import MobileSAMDecoderService

                self._sam_decoder = MobileSAMDecoderService.get_instance()
            except Exception as e:
                logger.warning(f"Failed to load SAM decoder: {e}")
                self._sam_decoder = False  # Mark as failed
        return self._sam_decoder if self._sam_decoder else None

    def _get_embeddings(
        self,
        gel_image: GelImage,
        image_array: np.ndarray,
    ) -> tuple[np.ndarray, tuple[int, int]] | None:
        """
        Get or generate SAM embeddings for an image.

        Args:
            gel_image: GelImage model instance for caching.
            image_array: Image as numpy array.

        Returns:
            Tuple of (embeddings, original_size) or None if failed.
        """
        encoder = self._get_sam_encoder()
        if encoder is None:
            return None

        # Check cache
        if self._cached_image_id == str(gel_image.pk):
            return self._cached_embeddings

        try:
            # Get cached embeddings (from Redis or generate)
            embeddings_data = encoder.get_cached_embeddings(gel_image)

            # Decode base64 embeddings
            embedding_b64 = embeddings_data["image_embedding"]
            embedding_bytes = base64.b64decode(embedding_b64)
            embedding_np = np.frombuffer(embedding_bytes, dtype=np.float32)

            # Reshape to original dimensions
            shape = embeddings_data["embedding_shape"]
            embedding_np = embedding_np.reshape(shape)

            original_size = tuple(embeddings_data["original_size"])

            # Cache locally
            self._cached_embeddings = (embedding_np, original_size)
            self._cached_image_id = str(gel_image.pk)

            logger.debug(f"SAM embeddings ready for image {gel_image.pk}")
            return self._cached_embeddings

        except Exception as e:
            logger.error(f"Failed to get SAM embeddings: {e}")
            return None

    def refine_bands_with_sam(
        self,
        bands: list[DetectedBand],
        gel_image: GelImage,
        image_array: np.ndarray,
    ) -> list[DetectedBand]:
        """
        Refine band polygons using MobileSAM decoder.

        Args:
            bands: List of DetectedBand with bboxes but empty polygons.
            gel_image: GelImage model instance for embedding caching.
            image_array: Image as numpy array.

        Returns:
            Same bands with polygons filled in by SAM.
        """
        if not bands or not self.enable_sam:
            return bands

        decoder = self._get_sam_decoder()
        if decoder is None:
            logger.warning("SAM decoder not available, skipping refinement")
            return bands

        # Get embeddings
        embeddings_result = self._get_embeddings(gel_image, image_array)
        if embeddings_result is None:
            logger.warning("SAM embeddings not available, skipping refinement")
            return bands

        embeddings, original_size = embeddings_result

        start_time = time.time()

        # Prepare batch request
        band_requests = []
        for i, band in enumerate(bands):
            band_requests.append(
                {
                    "id": i,
                    "bbox": {
                        "x": band.bbox_x,
                        "y": band.bbox_y,
                        "width": band.bbox_width,
                        "height": band.bbox_height,
                    },
                }
            )

        # Run batch refinement
        results = decoder.refine_bands_batch(embeddings, original_size, band_requests)

        # Update bands with SAM polygons
        for result in results:
            idx = result["id"]
            if result["success"] and result["polygon"]:
                bands[idx].polygon = result["polygon"]
                bands[idx].detection_source = BandDetectionSource.SAM

        elapsed_ms = (time.time() - start_time) * 1000
        successful = sum(1 for r in results if r["success"])

        logger.info(f"SAM refinement: {successful}/{len(bands)} bands refined in {elapsed_ms:.1f}ms")

        return bands


def detect_bands_preview(
    lane_id: int,
    params_dict: dict | None = None,
) -> dict:
    """
    Convenience function for API preview endpoint.

    Args:
        lane_id: Lane database ID.
        params_dict: Detection parameters as dict.

    Returns:
        Dict with detection results for JSON response.
    """
    from gel_analyzer.models import Lane
    from gel_analyzer.services.file_handler import GelFileHandler

    try:
        lane = Lane.objects.select_related("analysis__gel_image").get(pk=lane_id)
    except Lane.DoesNotExist:
        return {
            "success": False,
            "error": f"Lane {lane_id} not found",
        }

    # Load image
    try:
        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to load image: {e}",
        }

    # Build params
    params = BandDetectionParams.from_dict(params_dict) if params_dict else BandDetectionParams()

    # Run detection
    service = BandDetectionService(params)
    result = service.detect_bands_in_lane(lane, image)

    return result.to_dict()


def detect_bands_bulk(
    analysis_id: int,
    lane_ids: list[int] | None = None,
    params_dict: dict | None = None,
    user_id: int | None = None,
    save_results: bool = False,
) -> dict:
    """
    Convenience function for API bulk detection endpoint.

    Args:
        analysis_id: GelAnalysis database ID.
        lane_ids: Optional list of specific lanes to process.
        params_dict: Detection parameters as dict.
        user_id: User ID (required if save_results=True).
        save_results: Whether to save results to database.

    Returns:
        Dict with bulk detection results for JSON response.
    """
    from django.contrib.auth import get_user_model

    from gel_analyzer.models import GelAnalysis

    User = get_user_model()

    try:
        analysis = GelAnalysis.objects.get(pk=analysis_id)
    except GelAnalysis.DoesNotExist:
        return {
            "success": False,
            "error": f"Analysis {analysis_id} not found",
        }

    user = None
    if save_results:
        if user_id is None:
            return {
                "success": False,
                "error": "User ID required when saving results",
            }
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return {
                "success": False,
                "error": f"User {user_id} not found",
            }

    # Build params
    params = BandDetectionParams.from_dict(params_dict) if params_dict else BandDetectionParams()

    # Run detection
    service = BandDetectionService(params)
    results = service.detect_all_lanes(
        analysis=analysis,
        user=user,
        save_results=save_results,
        lane_ids=lane_ids,
    )

    return {
        "success": True,
        "analysis_id": analysis_id,
        "lanes_processed": len(results),
        "lanes_successful": sum(1 for r in results if r.success),
        "total_bands_detected": sum(len(r.bands) for r in results),
        "results": [r.to_dict() for r in results],
    }
