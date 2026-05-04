"""End-to-end smoke: full hybrid band-detection pipeline on a synthetic gel.

Verifies that the ported services produce correct bands when wired through
the live ORM models. This is the Phase 2 acceptance signal.
"""

import io

import numpy as np
import pytest
from PIL import Image

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from gel_analyzer.models import GelAnalysis, GelImage, Lane
from gel_analyzer.services.band_detection import (
    BandDetectionParams,
    BandDetectionService,
)


@pytest.fixture
def synthetic_gel_with_lane(db):
    """Create a synthetic 8-bit gel image with one ladder lane and 5 visible bands."""
    width, height = 200, 600
    arr = np.full((height, width), 30, dtype=np.uint8)  # dark background
    # 5 horizontal bands at known Y positions
    band_ys = [80, 180, 280, 380, 480]
    for y in band_ys:
        arr[y - 6 : y + 6, 40:160] = 220  # bright band
    # Slight noise
    rng = np.random.default_rng(42)
    arr = np.clip(arr.astype(int) + rng.integers(-15, 15, arr.shape), 0, 255).astype(np.uint8)

    img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    user = get_user_model().objects.create_user(username="e2euser", password="x")
    gel = GelImage.objects.create(
        original_file=SimpleUploadedFile("e2e.png", buf.read(), content_type="image/png"),
        original_filename="e2e.png",
        file_format=GelImage.FileFormat.PNG,
        width=width,
        height=height,
        bit_depth=8,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=user,
    )
    analysis = GelAnalysis.objects.create(gel_image=gel, name="E2E", created_by=user)
    lane = Lane.objects.create(
        analysis=analysis,
        lane_number=1,
        lane_type=Lane.LaneType.LADDER,
        x=30,
        y=10,
        width=140,
        height=580,
    )
    return analysis, lane, arr, band_ys


@pytest.mark.django_db
def test_hybrid_detection_finds_synthetic_bands(synthetic_gel_with_lane) -> None:
    analysis, lane, image_array, expected_ys = synthetic_gel_with_lane

    params = BandDetectionParams()
    service = BandDetectionService(params)

    result = service.detect_bands_in_lane(lane, image_array)

    assert result is not None
    detected = result.bands
    assert len(detected) >= 4, f"Expected at least 4 bands, got {len(detected)}"

    # Verify the detected band Y positions cluster around expected_ys (within ±12 px)
    detected_ys = sorted(b.position_y for b in detected)
    matches = 0
    for expected_y in expected_ys:
        if any(abs(dy - expected_y) <= 12 for dy in detected_ys):
            matches += 1
    assert matches >= 4, f"Only {matches}/5 expected bands matched; detected_ys={detected_ys}"
