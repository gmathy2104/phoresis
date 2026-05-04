"""
Tests for GelFileHandler service.
"""

import io

import numpy as np
import pytest
from PIL import Image

from gel_analyzer.services import GelFileHandler


class TestFormatDetection:
    """Tests for format detection."""

    def test_detect_format_png(self, tmp_path, sample_gel_png_bytes):
        """Test PNG format detection."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(sample_gel_png_bytes)

        assert GelFileHandler.detect_format(file_path) == "PNG"

    def test_detect_format_tiff(self, tmp_path, sample_gel_16bit_tiff_bytes):
        """Test TIFF format detection."""
        file_path = tmp_path / "test.tiff"
        file_path.write_bytes(sample_gel_16bit_tiff_bytes)

        assert GelFileHandler.detect_format(file_path) == "TIFF"

    def test_detect_format_gel_extension(self, tmp_path, sample_gel_16bit_tiff_bytes):
        """Test GEL format detection (TIFF with .gel extension)."""
        file_path = tmp_path / "test.gel"
        file_path.write_bytes(sample_gel_16bit_tiff_bytes)

        assert GelFileHandler.detect_format(file_path) == "GEL"

    def test_detect_format_jpeg(self, tmp_path):
        """Test JPEG format detection."""
        img = Image.new("L", (100, 100), color=128)
        file_path = tmp_path / "test.jpg"
        img.save(file_path, format="JPEG")

        assert GelFileHandler.detect_format(file_path) == "JPEG"

    def test_detect_format_unknown(self, tmp_path):
        """Test unknown format detection."""
        file_path = tmp_path / "test.xyz"
        file_path.write_bytes(b"not an image")

        assert GelFileHandler.detect_format(file_path) == "UNKNOWN"


class TestReadImage:
    """Tests for reading images."""

    def test_read_png(self, tmp_path, sample_gel_png_bytes):
        """Test reading PNG image."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(sample_gel_png_bytes)

        img_array, metadata = GelFileHandler.read_image(file_path)

        assert img_array is not None
        assert metadata["format"] == "PNG"
        assert metadata["bit_depth"] == 8
        assert metadata["width"] == 400
        assert metadata["height"] == 500

    def test_read_tiff_16bit(self, tmp_path, sample_gel_16bit_tiff_bytes):
        """Test reading 16-bit TIFF image."""
        file_path = tmp_path / "test.tiff"
        file_path.write_bytes(sample_gel_16bit_tiff_bytes)

        img_array, metadata = GelFileHandler.read_image(file_path)

        assert img_array is not None
        assert metadata["format"] == "TIFF"
        assert metadata["bit_depth"] == 16
        assert metadata["width"] == 200
        assert metadata["height"] == 300

    def test_read_color_image_conversion(self, tmp_path):
        """Test that color images are converted to grayscale."""
        # Create RGB image
        img = Image.new("RGB", (100, 100), color=(128, 64, 32))
        file_path = tmp_path / "test.png"
        img.save(file_path, format="PNG")

        img_array, metadata = GelFileHandler.read_image(file_path)

        # Should be 2D (grayscale)
        assert len(img_array.shape) == 2


class TestNormalization:
    """Tests for image normalization."""

    def test_normalize_8bit_passthrough(self):
        """Test that 8-bit images pass through unchanged."""
        img = np.array([[0, 128, 255]], dtype=np.uint8)
        result = GelFileHandler.normalize_to_8bit(img)

        np.testing.assert_array_equal(img, result)

    def test_normalize_16bit(self):
        """Test 16-bit to 8-bit normalization."""
        img = np.array([[0, 32768, 65535]], dtype=np.uint16)
        result = GelFileHandler.normalize_to_8bit(img)

        assert result.dtype == np.uint8
        assert result[0, 0] == 0
        assert result[0, 2] == 255
        # Middle value should be ~128
        assert 120 < result[0, 1] < 136

    def test_normalize_float(self):
        """Test float to 8-bit normalization."""
        img = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
        result = GelFileHandler.normalize_to_8bit(img)

        assert result.dtype == np.uint8
        assert result[0, 0] == 0
        assert result[0, 2] == 255
        assert 120 < result[0, 1] < 136

    def test_normalize_constant_image(self):
        """Test normalization of constant image (no contrast)."""
        img = np.full((10, 10), 128, dtype=np.uint16)
        result = GelFileHandler.normalize_to_8bit(img)

        # Should return zeros (min == max case)
        assert np.all(result == 0)


class TestDisplayAndThumbnail:
    """Tests for display and thumbnail creation."""

    def test_create_display_image(self, sample_gel_png_bytes, tmp_path):
        """Test display image creation."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(sample_gel_png_bytes)

        img_array, _ = GelFileHandler.read_image(file_path)
        display_bytes, display_w, display_h = GelFileHandler.create_display_image(img_array)

        # Should return valid PNG bytes
        assert len(display_bytes) > 0
        assert display_w > 0
        assert display_h > 0
        # Verify it's a valid image
        img = Image.open(io.BytesIO(display_bytes))
        assert img.format == "PNG"

    def test_create_display_image_resize(self):
        """Test display image resizes large images."""
        # Create large image
        large_img = np.zeros((4000, 3000), dtype=np.uint8)
        display_bytes, display_w, display_h = GelFileHandler.create_display_image(large_img)

        img = Image.open(io.BytesIO(display_bytes))
        # Should be resized to max dimension 2048
        assert max(img.width, img.height) <= GelFileHandler.MAX_DISPLAY_DIMENSION
        assert display_w == img.width
        assert display_h == img.height

    def test_create_thumbnail(self, sample_gel_png_bytes, tmp_path):
        """Test thumbnail creation."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(sample_gel_png_bytes)

        img_array, _ = GelFileHandler.read_image(file_path)
        thumbnail_bytes = GelFileHandler.create_thumbnail(img_array)

        # Should return valid PNG bytes
        assert len(thumbnail_bytes) > 0
        img = Image.open(io.BytesIO(thumbnail_bytes))
        assert img.format == "PNG"
        # Should fit within thumbnail size
        assert img.width <= GelFileHandler.THUMBNAIL_SIZE[0]
        assert img.height <= GelFileHandler.THUMBNAIL_SIZE[1]


class TestValidation:
    """Tests for file validation."""

    def test_validate_valid_png(self, tmp_path, sample_gel_png_bytes):
        """Test validation of valid PNG."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(sample_gel_png_bytes)

        is_valid, error = GelFileHandler.validate_file(file_path)

        assert is_valid is True
        assert error is None

    def test_validate_nonexistent_file(self, tmp_path):
        """Test validation of nonexistent file."""
        file_path = tmp_path / "nonexistent.png"

        is_valid, error = GelFileHandler.validate_file(file_path)

        assert is_valid is False
        assert "does not exist" in error

    def test_validate_unsupported_format(self, tmp_path):
        """Test validation of unsupported format."""
        file_path = tmp_path / "test.xyz"
        file_path.write_bytes(b"some data")

        is_valid, error = GelFileHandler.validate_file(file_path)

        assert is_valid is False
        assert "Unsupported" in error

    def test_validate_corrupted_file(self, tmp_path):
        """Test validation of corrupted image file."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(b"\x89PNG\r\n\x1a\ncorrupted data")

        is_valid, error = GelFileHandler.validate_file(file_path)

        assert is_valid is False
        assert "Unable to read" in error


class TestLoadImageAsArray:
    """Tests for load_image_as_array method."""

    def test_load_image_prefers_original(self):
        """Should prefer original_file over display_file for max bit depth."""
        from unittest.mock import MagicMock

        gel_image = MagicMock()
        gel_image.pk = "test-uuid"
        gel_image.width = 200
        gel_image.height = 300

        # Create 16-bit TIFF content for original_file
        img_16bit = np.zeros((300, 200), dtype=np.uint16)
        img_16bit[100:110, 50:150] = 40000
        tiff_buffer = io.BytesIO()
        Image.fromarray(img_16bit, mode="I;16").save(tiff_buffer, format="TIFF")
        tiff_bytes = tiff_buffer.getvalue()

        # Create 8-bit PNG content for display_file
        img_8bit = np.full((300, 200), 128, dtype=np.uint8)
        png_buffer = io.BytesIO()
        Image.fromarray(img_8bit, mode="L").save(png_buffer, format="PNG")
        png_buffer.getvalue()

        # Set up original_file (TIFF) and display_file (PNG)
        original_file = MagicMock()
        original_file.name = "test.tiff"
        original_file.__bool__ = lambda self: True
        original_file.open = MagicMock(return_value=io.BytesIO(tiff_bytes))
        original_file.open.return_value.__enter__ = lambda s: s
        original_file.open.return_value.__exit__ = MagicMock(return_value=False)

        display_file = MagicMock()
        display_file.name = "test_display.png"
        display_file.__bool__ = lambda self: True

        gel_image.original_file = original_file
        gel_image.display_file = display_file

        result = GelFileHandler.load_image_as_array(gel_image)

        # Should have loaded from original (TIFF), not display (PNG)
        original_file.open.assert_called_once_with("rb")
        display_file.open.assert_not_called()
        # Result should be 2D grayscale
        assert len(result.shape) == 2

    def test_load_image_falls_back_to_display(self):
        """Should fall back to display_file when original_file is missing."""
        from unittest.mock import MagicMock

        gel_image = MagicMock()
        gel_image.pk = "test-uuid"
        gel_image.width = 100
        gel_image.height = 100

        # Create 8-bit PNG for display_file
        img_8bit = np.full((100, 100), 128, dtype=np.uint8)
        png_buffer = io.BytesIO()
        Image.fromarray(img_8bit, mode="L").save(png_buffer, format="PNG")
        png_bytes = png_buffer.getvalue()

        display_file = MagicMock()
        display_file.name = "test_display.png"
        display_file.__bool__ = lambda self: True
        display_file.open = MagicMock(return_value=io.BytesIO(png_bytes))
        display_file.open.return_value.__enter__ = lambda s: s
        display_file.open.return_value.__exit__ = MagicMock(return_value=False)

        # No original_file
        gel_image.original_file = None
        gel_image.display_file = display_file

        result = GelFileHandler.load_image_as_array(gel_image)

        display_file.open.assert_called_once_with("rb")
        assert result.shape == (100, 100)

    def test_load_image_resizes_to_display_dims(self):
        """Should resize original image to display dims for coordinate compat."""
        from unittest.mock import MagicMock

        gel_image = MagicMock()
        gel_image.pk = "test-uuid"
        # Display dims are smaller than original
        gel_image.width = 200
        gel_image.height = 300

        # Create a larger original image (400x600)
        img_large = np.zeros((600, 400), dtype=np.uint8)
        img_large[200:220, 100:300] = 200
        png_buffer = io.BytesIO()
        Image.fromarray(img_large, mode="L").save(png_buffer, format="PNG")
        png_bytes = png_buffer.getvalue()

        original_file = MagicMock()
        original_file.name = "test.png"
        original_file.__bool__ = lambda self: True
        original_file.open = MagicMock(return_value=io.BytesIO(png_bytes))
        original_file.open.return_value.__enter__ = lambda s: s
        original_file.open.return_value.__exit__ = MagicMock(return_value=False)

        gel_image.original_file = original_file
        gel_image.display_file = None

        result = GelFileHandler.load_image_as_array(gel_image)

        # Should be resized to display dims
        assert result.shape == (300, 200)


class TestProcessUploadedFile:
    """Tests for process_uploaded_file method."""

    def test_process_uploaded_file(self, tmp_path, sample_gel_png_bytes):
        """Test complete file processing."""
        file_path = tmp_path / "test.png"
        file_path.write_bytes(sample_gel_png_bytes)

        result = GelFileHandler.process_uploaded_file(file_path)

        assert "metadata" in result
        assert "display_bytes" in result
        assert "thumbnail_bytes" in result
        assert result["metadata"]["format"] == "PNG"
        assert result["metadata"]["width"] == 400
        assert result["metadata"]["height"] == 500

    def test_process_uploaded_file_invalid(self, tmp_path):
        """Test processing invalid file raises error."""
        file_path = tmp_path / "test.xyz"
        file_path.write_bytes(b"not an image")

        with pytest.raises(ValueError):
            GelFileHandler.process_uploaded_file(file_path)
