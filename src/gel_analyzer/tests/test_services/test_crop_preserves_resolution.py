"""Regression test for crop bug that silently downsampled original to display dims."""

import io

import numpy as np
import pytest
from PIL import Image

from django.core.files.base import ContentFile

from gel_analyzer.models import GelImage
from gel_analyzer.services.file_handler import GelFileHandler


@pytest.mark.django_db
class TestCropPreservesNativeResolution:
    """Cropping must not degrade the native resolution of the raw original."""

    def _save_tiff_bytes(self, array: np.ndarray) -> bytes:
        """Encode a numpy array as TIFF bytes."""
        img = Image.fromarray(array)
        buf = io.BytesIO()
        img.save(buf, format="TIFF")
        return buf.getvalue()

    def _save_png_bytes(self, array: np.ndarray) -> bytes:
        img = Image.fromarray(array)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _make_gel_with_distinct_native_and_display_dims(self):
        """Create a GelImage whose native TIFF (1000x800) is larger than
        the display PNG (500x400), matching the shape of the real bug."""
        # Native TIFF — 1000 wide x 800 tall, random but deterministic
        rng = np.random.default_rng(42)
        native = rng.integers(0, 256, size=(800, 1000), dtype=np.uint8)
        tiff_bytes = self._save_tiff_bytes(native)

        # Display PNG — half-resolution 500x400
        display = rng.integers(0, 256, size=(400, 500), dtype=np.uint8)
        png_bytes = self._save_png_bytes(display)

        gi = GelImage.objects.create(
            width=500,  # DISPLAY width
            height=400,  # DISPLAY height
            original_filename="test_native.tif",
            file_format="TIFF",
            file_size_bytes=len(tiff_bytes),
            gel_type="SDS_PAGE",
        )
        gi.original_file.save("originals/test_native.tif", ContentFile(tiff_bytes), save=False)
        gi.display_file.save("display/test_display.png", ContentFile(png_bytes), save=False)
        gi.save()
        return gi, native.shape, display.shape  # (gi, (native_h, native_w), (display_h, display_w))

    def test_crop_keeps_original_at_native_resolution(self):
        """After cropping a 500x400 display rect of (50, 40, 200, 160),
        the saved original must be the native-space crop rect (400, 320)
        — NOT the display-space rect (200, 160)."""
        gi, (native_h, native_w), (display_h, display_w) = self._make_gel_with_distinct_native_and_display_dims()

        # Crop a 200x160 rectangle in display space at (50, 40)
        display_crop_x, display_crop_y = 50, 40
        display_crop_w, display_crop_h = 200, 160

        GelFileHandler.crop_image(
            gi,
            x=display_crop_x,
            y=display_crop_y,
            width=display_crop_w,
            height=display_crop_h,
        )

        gi.refresh_from_db()

        # Display dims should reflect the display-space crop
        assert gi.width == display_crop_w
        assert gi.height == display_crop_h

        # Load the saved original raw (bypass the resize)
        saved_original = GelFileHandler.load_image_as_array(gi, resize_to_display=False)
        saved_h, saved_w = saved_original.shape[:2]

        # Native coords: scale display crop back up
        sx = native_w / display_w  # 1000 / 500 = 2.0
        sy = native_h / display_h  # 800 / 400 = 2.0
        expected_w = round(display_crop_w * sx)  # 400
        expected_h = round(display_crop_h * sy)  # 320

        assert (saved_w, saved_h) == (expected_w, expected_h), (
            f"Original saved at {saved_w}x{saved_h}, expected {expected_w}x{expected_h} "
            f"(native-space crop rect). The old bug downsampled to display-space "
            f"({display_crop_w}x{display_crop_h})."
        )
        # And strictly bigger than the display crop — this is the data-preservation invariant
        assert saved_w >= display_crop_w
        assert saved_h >= display_crop_h

    def test_load_image_as_array_no_resize_returns_native(self):
        """load_image_as_array with resize_to_display=False must return
        the image at its native TIFF resolution, ignoring gel_image.width/height."""
        gi, (native_h, native_w), _ = self._make_gel_with_distinct_native_and_display_dims()

        native = GelFileHandler.load_image_as_array(gi, resize_to_display=False)
        assert native.shape[:2] == (native_h, native_w)

    def test_load_image_as_array_default_still_resizes(self):
        """Default call (resize_to_display=True implicit) keeps the old
        behaviour so detection pipeline is not changed by this PR."""
        gi, _, (display_h, display_w) = self._make_gel_with_distinct_native_and_display_dims()

        resized = GelFileHandler.load_image_as_array(gi)  # default True
        assert resized.shape[:2] == (display_h, display_w)
