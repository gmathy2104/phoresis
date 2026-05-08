"""
Pytest fixtures for gel_analyzer tests.
"""

import io

import numpy as np
import pytest
from PIL import Image

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from gel_analyzer.models import Band, GelAnalysis, GelImage, Lane, MWMarker

User = get_user_model()


@pytest.fixture(autouse=True)
def isolate_media_root(tmp_path, settings):
    """
    Redirect MEDIA_ROOT to a per-test tmp dir so test uploads don't pollute
    the dev media folder.

    Without this, every test that builds a `GelImage` via SimpleUploadedFile
    (the `gel_image` / `uploaded_gel_file` fixtures below, plus their
    derivatives) writes a real file under MEDIA_ROOT/gel_images/... and
    Django's storage backend silently appends a random suffix on filename
    collision — so a single test run can leave hundreds of `test_gel.png`,
    `test_gel_xxxxx.png`, `clc_test_*.png`, `e2e_*.png` orphans in
    `C:\\dev\\phoresis\\media\\` that nothing references after the
    test DB is rolled back. tmp_path is removed by pytest at the end of
    the test, so the leak stops at the boundary of one test.
    """
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture
def test_user(db):
    """Create a test user."""
    return User.objects.create_user(username="test_user", email="test@example.com", password="testpass123")


@pytest.fixture
def api_client():
    """Return a DRF APIClient for testing."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def authenticated_api_client(api_client, test_user):
    """Return a DRF APIClient force-authenticated as ``test_user``.

    Phoresis does not have an APIKey model — DRF defaults are AllowAny, so we
    use ``force_authenticate`` to attach a real user to the request for
    consistency with view-level expectations.
    """
    api_client.force_authenticate(user=test_user)
    return api_client


@pytest.fixture
def sample_gel_png_bytes():
    """Create a sample gel image as PNG bytes."""
    # Create a simple grayscale image with some "bands"
    img_array = np.zeros((500, 400), dtype=np.uint8)
    # Add some horizontal bands
    for y in [100, 150, 200, 300, 400]:
        img_array[y - 5 : y + 5, 50:350] = 200
    # Add background noise
    noise = np.random.randint(0, 50, (500, 400), dtype=np.uint8)
    img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)

    img = Image.fromarray(img_array, mode="L")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


@pytest.fixture
def sample_gel_16bit_tiff_bytes():
    """Create a sample 16-bit TIFF gel image."""
    # Create a 16-bit grayscale image
    img_array = np.zeros((300, 200), dtype=np.uint16)
    # Add some bands with higher intensity values
    for y in [50, 100, 150, 200, 250]:
        img_array[y - 3 : y + 3, 30:170] = 40000
    # Add some noise
    noise = np.random.randint(0, 5000, (300, 200), dtype=np.uint16)
    img_array = np.clip(img_array + noise, 0, 65535).astype(np.uint16)

    img = Image.fromarray(img_array, mode="I;16")
    buffer = io.BytesIO()
    img.save(buffer, format="TIFF")
    buffer.seek(0)
    return buffer.read()


@pytest.fixture
def uploaded_gel_file(sample_gel_png_bytes):
    """Create an uploaded file from sample PNG."""
    return SimpleUploadedFile(name="test_gel.png", content=sample_gel_png_bytes, content_type="image/png")


@pytest.fixture
def uploaded_tiff_file(sample_gel_16bit_tiff_bytes):
    """Create an uploaded file from sample TIFF."""
    return SimpleUploadedFile(name="test_gel.tiff", content=sample_gel_16bit_tiff_bytes, content_type="image/tiff")


@pytest.fixture
def gel_image(db, test_user, uploaded_gel_file):
    """Create a GelImage instance."""
    return GelImage.objects.create(
        original_file=uploaded_gel_file,
        original_filename="test_gel.png",
        file_format=GelImage.FileFormat.PNG,
        width=400,
        height=500,
        bit_depth=8,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=test_user,
    )


@pytest.fixture
def gel_analysis(db, gel_image, test_user):
    """Create a GelAnalysis instance."""
    return GelAnalysis.objects.create(
        gel_image=gel_image, name="Test Analysis", status=GelAnalysis.Status.DRAFT, created_by=test_user
    )


@pytest.fixture
def sample_analysis(gel_analysis):
    """Alias for plan-referenced fixture name; same as gel_analysis."""
    return gel_analysis


@pytest.fixture
def sample_lane(db, gel_analysis):
    """Create a sample Lane instance."""
    return Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=50,
        y=10,
        width=40,
        height=480,
        sample_name="Sample 1",
    )


@pytest.fixture
def ladder_lane(db, gel_analysis):
    """Create a ladder Lane instance."""
    return Lane.objects.create(
        analysis=gel_analysis,
        lane_number=2,
        lane_type=Lane.LaneType.LADDER,
        detection_source=Lane.DetectionSource.MANUAL,
        x=100,
        y=10,
        width=40,
        height=480,
    )


@pytest.fixture
def band(db, sample_lane, test_user):
    """Create a Band instance."""
    return Band.objects.create(
        lane=sample_lane,
        detection_source=Band.DetectionSource.MANUAL,
        position_y=100,
        bbox_x=50,
        bbox_y=90,
        bbox_width=40,
        bbox_height=20,
        estimated_mw_kda=55.0,
        intensity_normalized=75.5,
        created_by=test_user,
    )


@pytest.fixture
def sample_band(band):
    """Alias for plan-referenced fixture name; same as band."""
    return band


@pytest.fixture
def yolo_band(db, sample_lane):
    """Create a YOLO-detected Band instance."""
    return Band.objects.create(
        lane=sample_lane,
        detection_source=Band.DetectionSource.YOLO,
        confidence=0.95,
        position_y=150,
        polygon=[[50, 145], [90, 145], [90, 155], [50, 155]],
        bbox_x=50,
        bbox_y=145,
        bbox_width=40,
        bbox_height=10,
        estimated_mw_kda=35.0,
        intensity_normalized=50.0,
    )


@pytest.fixture
def mw_marker(db, ladder_lane):
    """Create a MWMarker instance."""
    return MWMarker.objects.create(lane=ladder_lane, mw_kda=75.0, position_y=120)


@pytest.fixture
def authenticated_client(authenticated_api_client):
    """Plan-referenced fixture name; alias for authenticated_api_client."""
    return authenticated_api_client


@pytest.fixture
def calibration_lane(db, gel_analysis):
    """Create a CALIBRATION-type Lane."""
    return Lane.objects.create(
        analysis=gel_analysis,
        lane_number=3,
        lane_type=Lane.LaneType.CALIBRATION,
        detection_source=Lane.DetectionSource.MANUAL,
        x=150,
        y=10,
        width=40,
        height=480,
    )


@pytest.fixture
def calibration_band(db, calibration_lane, test_user):
    """Create a Band of type CALIBRATION inside a CALIBRATION lane."""
    return Band.objects.create(
        lane=calibration_lane,
        detection_source=Band.DetectionSource.MANUAL,
        band_type=Band.BandType.CALIBRATION,
        position_y=120,
        bbox_x=150,
        bbox_y=110,
        bbox_width=40,
        bbox_height=20,
        created_by=test_user,
    )


@pytest.fixture
def calib_lane_with_point(db, calibration_lane, test_user):
    """A CALIBRATION lane containing one CALIBRATION band + quant_point."""
    from gel_analyzer.models import ProteinQuantCalibrationPoint

    band = Band.objects.create(
        lane=calibration_lane,
        detection_source=Band.DetectionSource.MANUAL,
        band_type=Band.BandType.CALIBRATION,
        position_y=130,
        bbox_x=150,
        bbox_y=120,
        bbox_width=40,
        bbox_height=20,
        created_by=test_user,
    )
    ProteinQuantCalibrationPoint.objects.create(
        band=band,
        load_amount=10.0,
        load_unit=ProteinQuantCalibrationPoint.UNIT_UG,
        role=ProteinQuantCalibrationPoint.ROLE_CALIBRATION,
    )
    return calibration_lane


@pytest.fixture
def three_calib_points_analysis(db, gel_analysis, test_user):
    """Analysis with 3 CALIBRATION lanes, each with a CALIBRATION band +
    densitometry + quant_point at loads 5/10/15 µg."""
    from gel_analyzer.models import (
        DensitometryResult,
        ProteinQuantCalibrationPoint,
    )

    loads = [5.0, 10.0, 15.0]
    # Roughly linear corrected_area vs load (slope ~1000 area / µg)
    areas = [5000.0, 10000.0, 15000.0]
    for i, (load, area) in enumerate(zip(loads, areas, strict=False)):
        lane = Lane.objects.create(
            analysis=gel_analysis,
            lane_number=10 + i,
            lane_type=Lane.LaneType.CALIBRATION,
            detection_source=Lane.DetectionSource.MANUAL,
            x=200 + i * 50,
            y=10,
            width=40,
            height=480,
        )
        band = Band.objects.create(
            lane=lane,
            detection_source=Band.DetectionSource.MANUAL,
            band_type=Band.BandType.CALIBRATION,
            position_y=100 + i * 5,
            bbox_x=200 + i * 50,
            bbox_y=90 + i * 5,
            bbox_width=40,
            bbox_height=20,
            created_by=test_user,
        )
        DensitometryResult.objects.create(
            band=band,
            peak_center_y=100.0 + i * 5,
            peak_amplitude=200.0,
            peak_sigma=5.0,
            fwhm=12.0,
            integrated_area=area,
            background_area=0.0,
            corrected_area=area,
            fit_r_squared=0.99,
            snr=20.0,
        )
        ProteinQuantCalibrationPoint.objects.create(
            band=band,
            load_amount=load,
            load_unit=ProteinQuantCalibrationPoint.UNIT_UG,
            role=ProteinQuantCalibrationPoint.ROLE_CALIBRATION,
        )
    return gel_analysis


@pytest.fixture
def complete_analysis(db, gel_image, test_user):
    """Create a complete analysis with multiple lanes and bands."""
    analysis = GelAnalysis.objects.create(
        gel_image=gel_image, name="Complete Test Analysis", status=GelAnalysis.Status.IN_PROGRESS, created_by=test_user
    )

    # Create ladder lane
    ladder = Lane.objects.create(
        analysis=analysis,
        lane_number=1,
        lane_type=Lane.LaneType.LADDER,
        detection_source=Lane.DetectionSource.MANUAL,
        x=20,
        y=10,
        width=40,
        height=480,
    )

    # Create sample lanes
    for i in range(2, 6):
        lane = Lane.objects.create(
            analysis=analysis,
            lane_number=i,
            lane_type=Lane.LaneType.SAMPLE,
            detection_source=Lane.DetectionSource.MANUAL,
            x=20 + (i - 1) * 50,
            y=10,
            width=40,
            height=480,
            sample_name=f"Sample {i - 1}",
        )
        # Add some bands
        for y, mw in [(100, 75), (200, 50), (300, 25)]:
            Band.objects.create(
                lane=lane,
                detection_source=Band.DetectionSource.MANUAL,
                position_y=y,
                bbox_x=lane.x,
                bbox_y=y - 5,
                bbox_width=40,
                bbox_height=10,
                estimated_mw_kda=mw,
                intensity_normalized=60 + np.random.randint(-20, 20),
                created_by=test_user,
            )

    # Add ladder markers
    for y, mw in [(80, 100), (150, 75), (220, 50), (320, 25), (420, 10)]:
        MWMarker.objects.create(lane=ladder, mw_kda=mw, position_y=y)

    # Update counts
    analysis.update_counts()

    return analysis
