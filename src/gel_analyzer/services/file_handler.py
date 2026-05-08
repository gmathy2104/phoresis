"""
File handling service for gel image format detection and conversion.

Supports:
- .gel (Bio-Rad proprietary, often TIFF internally)
- .tiff/.tif (may be 16-bit)
- .png
- .jpg/.jpeg
"""

import contextlib
import io
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import GelImage

logger = get_logger(__name__)


class GelFileHandler:
    """
    Handles gel image file processing including:
    - Format detection
    - Reading various formats
    - 16-bit to 8-bit normalization
    - Web-optimized PNG conversion
    - Thumbnail generation
    """

    SUPPORTED_EXTENSIONS = {".gel", ".scn", ".tiff", ".tif", ".png", ".jpg", ".jpeg"}
    THUMBNAIL_SIZE = (256, 256)
    MAX_DISPLAY_DIMENSION = 2048
    DISPLAY_QUALITY = 85  # JPEG quality for display files

    @classmethod
    def detect_format(cls, file_path: Path) -> str:
        """
        Detect file format from extension and magic bytes.

        Args:
            file_path: Path to the gel image file.

        Returns:
            Format string: 'GEL', 'TIFF', 'PNG', 'JPEG', or 'UNKNOWN'
        """
        ext = file_path.suffix.lower()

        # Check magic bytes for verification
        try:
            with open(file_path, "rb") as f:
                header = f.read(32)
        except OSError as e:
            logger.warning(f"Could not read file header: {e}")
            return cls._format_from_extension(ext)

        # SCN magic bytes (MIME multipart container from Bio-Rad ChemiDoc)
        if header.startswith(b"MIME-Version:"):
            return "SCN"

        # TIFF magic bytes (also used by .gel files)
        if header[:2] in (b"II", b"MM"):  # Little/Big endian TIFF
            return "GEL" if ext == ".gel" else "TIFF"

        # PNG magic bytes
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            return "PNG"

        # JPEG magic bytes
        if header[:3] == b"\xff\xd8\xff":
            return "JPEG"

        # Fall back to extension
        return cls._format_from_extension(ext)

    @classmethod
    def _format_from_extension(cls, ext: str) -> str:
        """Get format from file extension."""
        ext_map = {
            ".gel": "GEL",
            ".scn": "SCN",
            ".tiff": "TIFF",
            ".tif": "TIFF",
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
        }
        return ext_map.get(ext, "UNKNOWN")

    @classmethod
    def read_image(cls, file_path: Path) -> tuple[np.ndarray, dict]:
        """
        Read gel image from file, handling various formats.

        Args:
            file_path: Path to the gel image file.

        Returns:
            Tuple of (numpy array, metadata dict)

        Raises:
            ValueError: If format is not supported.
            IOError: If file cannot be read.
        """
        file_format = cls.detect_format(file_path)
        metadata = {
            "format": file_format,
            "bit_depth": None,
            "width": None,
            "height": None,
            "file_size_bytes": file_path.stat().st_size if file_path.exists() else None,
        }

        log = logger.bind(file=str(file_path), format=file_format)

        if file_format == "SCN":
            # Bio-Rad .scn MIME container
            from gel_analyzer.services.scn_parser import SCNParser

            img_array, scn_meta = SCNParser.parse(file_path)
            metadata["bit_depth"] = 16
            metadata["scn_metadata"] = scn_meta

        elif file_format in ("GEL", "TIFF"):
            # Use tifffile for TIFF-based formats
            try:
                import tifffile

                img_array = tifffile.imread(str(file_path))
                metadata["bit_depth"] = img_array.dtype.itemsize * 8
                log.debug(f"Read TIFF/GEL with dtype={img_array.dtype}")
            except ImportError:
                log.warning("tifffile not installed, falling back to PIL")
                img_array, metadata["bit_depth"] = cls._read_with_pil(file_path)
            except Exception as e:
                log.error(f"Failed to read with tifffile: {e}")
                img_array, metadata["bit_depth"] = cls._read_with_pil(file_path)

        elif file_format in ("PNG", "JPEG"):
            img_array, metadata["bit_depth"] = cls._read_with_pil(file_path)

        else:
            raise ValueError(f"Unsupported format: {file_format}")

        # Handle multi-dimensional arrays (e.g., color images)
        if len(img_array.shape) == 3:
            if img_array.shape[0] in [3, 4]:  # (C, H, W)
                img_array = img_array[0]  # Take first channel
            elif img_array.shape[2] in [3, 4]:  # (H, W, C)
                # Convert to grayscale
                img_array = np.mean(img_array[:, :, :3], axis=2).astype(img_array.dtype)
            log.debug(f"Converted multi-channel to grayscale: {img_array.shape}")

        metadata["height"], metadata["width"] = img_array.shape[:2]

        log.info(
            f"Read gel image: {file_path.name}, {metadata['width']}x{metadata['height']}, {metadata['bit_depth']}-bit"
        )

        return img_array, metadata

    @classmethod
    def _read_with_pil(cls, file_path: Path) -> tuple[np.ndarray, int]:
        """Read image using PIL/Pillow."""
        with Image.open(file_path) as img:
            if img.mode == "L":
                bit_depth = 8
            elif img.mode == "I;16":
                bit_depth = 16
            elif img.mode in ("RGB", "RGBA"):
                bit_depth = 8
            else:
                bit_depth = 8
            return np.array(img), bit_depth

    @classmethod
    def normalize_to_8bit(cls, img_array: np.ndarray) -> np.ndarray:
        """
        Normalize image to 8-bit for web display.

        Handles 16-bit images by scaling to 0-255 range.

        Args:
            img_array: Input numpy array.

        Returns:
            8-bit numpy array (uint8).
        """
        if img_array.dtype == np.uint8:
            return img_array

        # Handle 16-bit images
        if img_array.dtype in (np.uint16, np.int16):
            img_min = img_array.min()
            img_max = img_array.max()
            if img_max > img_min:
                normalized = (img_array - img_min) / (img_max - img_min) * 255
            else:
                normalized = np.zeros_like(img_array)
            return normalized.astype(np.uint8)

        # Handle float images
        if img_array.dtype in (np.float32, np.float64):
            img_min = img_array.min()
            img_max = img_array.max()
            if img_max > img_min:
                normalized = (img_array - img_min) / (img_max - img_min) * 255
            else:
                normalized = np.zeros_like(img_array)
            return normalized.astype(np.uint8)

        # Default: try to convert
        return img_array.astype(np.uint8)

    @classmethod
    def create_display_image(cls, img_array: np.ndarray) -> tuple[bytes, int, int]:
        """
        Create web-optimized PNG for display.

        Args:
            img_array: Input numpy array.

        Returns:
            Tuple of (PNG bytes, display_width, display_height).
            Dimensions may differ from input if the image was resized.
        """
        # Normalize to 8-bit
        img_8bit = cls.normalize_to_8bit(img_array)

        # Resize if too large
        h, w = img_8bit.shape[:2]
        if max(h, w) > cls.MAX_DISPLAY_DIMENSION:
            scale = cls.MAX_DISPLAY_DIMENSION / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            pil_img = Image.fromarray(img_8bit)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            logger.debug(f"Resized display image from {w}x{h} to {new_w}x{new_h}")
        else:
            new_w, new_h = w, h
            pil_img = Image.fromarray(img_8bit)

        # Ensure grayscale mode
        if pil_img.mode != "L":
            pil_img = pil_img.convert("L")

        # Save to bytes as PNG
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)

        return buffer.read(), new_w, new_h

    @classmethod
    def create_thumbnail(cls, img_array: np.ndarray) -> bytes:
        """
        Create thumbnail image.

        Args:
            img_array: Input numpy array.

        Returns:
            PNG bytes for thumbnail.
        """
        # Normalize to 8-bit
        img_8bit = cls.normalize_to_8bit(img_array)

        # Create thumbnail
        pil_img = Image.fromarray(img_8bit)
        pil_img.thumbnail(cls.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

        # Ensure grayscale mode
        if pil_img.mode != "L":
            pil_img = pil_img.convert("L")

        # Save to bytes as PNG
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)

        return buffer.read()

    @classmethod
    def validate_file(cls, file_path: Path) -> tuple[bool, str | None]:
        """
        Validate that file is a supported gel image format.

        Args:
            file_path: Path to the file to validate.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not file_path.exists():
            return False, "File does not exist"

        ext = file_path.suffix.lower()
        if ext not in cls.SUPPORTED_EXTENSIONS:
            return False, f"Unsupported file format: {ext}. Supported: {cls.SUPPORTED_EXTENSIONS}"

        file_format = cls.detect_format(file_path)
        if file_format == "UNKNOWN":
            return False, "Unable to detect file format from magic bytes"

        try:
            cls.read_image(file_path)
        except Exception as e:
            return False, f"Unable to read image: {str(e)}"

        return True, None

    @classmethod
    def process_uploaded_file(cls, file_path: Path) -> dict:
        """
        Process an uploaded gel image file.

        Creates display and thumbnail versions.

        Args:
            file_path: Path to the uploaded file.

        Returns:
            Dict with metadata and generated file bytes:
            {
                'metadata': {...},
                'display_bytes': bytes,
                'thumbnail_bytes': bytes,
            }
        """
        log = logger.bind(file=str(file_path))
        log.info("Processing uploaded gel image")

        # Validate file
        is_valid, error = cls.validate_file(file_path)
        if not is_valid:
            raise ValueError(error)

        # Read image and get metadata
        img_array, metadata = cls.read_image(file_path)

        # For display: invert zero_is=white SCN images so Coomassie
        # gels render with the expected white background / dark bands.
        # The raw img_array stays untouched for band detection.
        display_array = img_array
        scn_meta = metadata.get("scn_metadata", {})
        if scn_meta.get("zero_is") == "white":
            display_array = np.iinfo(img_array.dtype).max - img_array
            log.debug("Inverted display copy for zero_is=white SCN")

        # Create display image (may be resized for web)
        display_bytes, display_w, display_h = cls.create_display_image(display_array)
        log.debug(f"Created display image: {len(display_bytes)} bytes, {display_w}x{display_h}")

        # Store original dimensions separately, then overwrite with display dims.
        # The model width/height must match the display PNG so the annotation
        # editor SVG viewBox aligns with band-detection coordinates.
        metadata["original_width"] = metadata["width"]
        metadata["original_height"] = metadata["height"]
        metadata["width"] = display_w
        metadata["height"] = display_h

        # Create thumbnail
        thumbnail_bytes = cls.create_thumbnail(display_array)
        log.debug(f"Created thumbnail: {len(thumbnail_bytes)} bytes")

        log.success(
            f"Processed gel image: {display_w}x{display_h} (original {metadata['original_width']}x{metadata['original_height']}), {metadata['format']}"
        )

        return {
            "metadata": metadata,
            "display_bytes": display_bytes,
            "thumbnail_bytes": thumbnail_bytes,
        }

    @classmethod
    def load_image_as_array(
        cls,
        gel_image: "GelImage",
        resize_to_display: bool = True,
    ) -> np.ndarray:
        """
        Load a GelImage model's file as a numpy array.

        Prefers original_file for maximum bit depth (16-bit TIFF/SCN/GEL),
        falls back to display_file (8-bit PNG). If the original image
        dimensions differ from display dims, resizes to match so lane
        bbox coordinates (stored in display-space) remain valid.

        Args:
            gel_image: GelImage model instance with file fields.
            resize_to_display: When True (default), resize the loaded array
                to gel_image.width x gel_image.height so that lane annotations
                (stored in display-space) are aligned. Set to False to load
                the file at its native resolution — required by crop_image so
                the raw original is not silently degraded.

        Returns:
            Numpy array (grayscale, uint8 or uint16).

        Raises:
            ValueError: If no image file is available.
            IOError: If image cannot be read.
        """
        # Prefer original_file for maximum bit depth
        file_field = gel_image.original_file or gel_image.display_file
        if not file_field:
            raise ValueError(f"GelImage {gel_image.pk} has no image file")

        log = logger.bind(gel_image_id=str(gel_image.pk), filename=file_field.name)
        log.debug("Loading gel image as array")

        try:
            # Read file content from storage backend (Azure Blob / filesystem)
            try:
                with file_field.open("rb") as f:
                    file_content = f.read()
            except FileNotFoundError as e:
                storage_backend = type(file_field.storage).__name__
                log.error(
                    f"File not found via {storage_backend}: {file_field.name}. "
                    f"Ensure storage env vars (AZURE_STORAGE_KEY) are set."
                )
                raise OSError(
                    f"Gel image not found: {file_field.name} "
                    f"(storage: {storage_backend}). "
                    f"Check AZURE_STORAGE_KEY is set in the worker environment."
                ) from e

            # Determine format from filename
            filename = file_field.name.lower()
            is_scn = filename.endswith(".scn")
            is_tiff = filename.endswith((".tif", ".tiff", ".gel"))

            if is_scn:
                # Write to tempfile for SCN parser (needs file path)
                from gel_analyzer.services.scn_parser import SCNParser

                with tempfile.NamedTemporaryFile(suffix=".scn", delete=False) as tmp:
                    tmp.write(file_content)
                    tmp_path = Path(tmp.name)
                try:
                    img_array, _ = SCNParser.parse(tmp_path)
                finally:
                    with contextlib.suppress(OSError):
                        tmp_path.unlink()

                # Normalize SCN polarity to match .gel convention (high=bright, low=dark).
                # SCN files with zero_is="white" have inverted polarity: 0=white, HIGH=dark.
                # Without this, the entire detection pipeline sees reversed data.
                scanner_meta = getattr(gel_image, "scanner_metadata", None) or {}
                if scanner_meta.get("zero_is") == "white":
                    max_val = np.iinfo(img_array.dtype).max if img_array.dtype.kind == "u" else img_array.max()
                    img_array = max_val - img_array
                    log.info("Inverted SCN image (zero_is=white) to match standard polarity")

            elif is_tiff:
                # Use tifffile for TIFF-based formats — but fall back to PIL on
                # *any* failure, not just ImportError. tifffile delegates exotic
                # codecs (LZW, JPEG, JPEG2000, ...) to the imagecodecs package,
                # which we don't ship. Pillow handles LZW natively, so the
                # fallback covers gel scanners that produce LZW-compressed TIFF.
                try:
                    import tifffile

                    img_array = tifffile.imread(io.BytesIO(file_content))
                except Exception as tiff_err:
                    log.warning(
                        f"tifffile failed ({tiff_err}); falling back to PIL"
                    )
                    pil_img = Image.open(io.BytesIO(file_content))
                    img_array = np.array(pil_img)
            else:
                # Use PIL for PNG/JPEG
                pil_img = Image.open(io.BytesIO(file_content))
                img_array = np.array(pil_img)

            # Handle multi-channel images (convert to grayscale)
            if len(img_array.shape) == 3:
                if img_array.shape[2] in [3, 4]:  # (H, W, C)
                    img_array = np.mean(img_array[:, :, :3], axis=2).astype(img_array.dtype)
                elif img_array.shape[0] in [3, 4]:  # (C, H, W)
                    img_array = img_array[0]  # Take first channel

            # Resize to display dims if needed (lane annotations are in display-space).
            # Set resize_to_display=False to preserve the native resolution — required
            # by crop_image so it doesn't silently destroy image data.
            if resize_to_display:
                display_w = getattr(gel_image, "width", None)
                display_h = getattr(gel_image, "height", None)
                if display_w and display_h:
                    img_h, img_w = img_array.shape[:2]
                    if img_h != display_h or img_w != display_w:
                        pil_img = Image.fromarray(img_array)
                        pil_img = pil_img.resize((display_w, display_h), Image.Resampling.LANCZOS)
                        img_array = np.array(pil_img)
                        log.info(
                            f"Resized from {img_w}x{img_h} to {display_w}x{display_h} for coordinate compatibility"
                        )

            log.debug(f"Loaded image: shape={img_array.shape}, dtype={img_array.dtype}")
            return img_array

        except Exception as e:
            log.error(f"Failed to load image: {e}")
            raise OSError(f"Failed to load gel image: {e}") from e

    @classmethod
    def crop_image(cls, gel_image: "GelImage", x: int, y: int, width: int, height: int) -> tuple[int, int]:
        """
        Crop a GelImage to the specified rectangle.

        Replaces both the display file and original file with cropped versions.
        The original raw file is permanently replaced — this is a destructive operation.

        Args:
            gel_image: GelImage model instance.
            x: Left edge in display-space pixels.
            y: Top edge in display-space pixels.
            width: Crop width in display-space pixels.
            height: Crop height in display-space pixels.

        Returns:
            Tuple of (new_width, new_height) after cropping.

        Raises:
            ValueError: If crop rect is out of bounds or too small.
        """
        from django.core.files.base import ContentFile

        log = logger.bind(gel_image_id=str(gel_image.pk), crop=f"{x},{y},{width},{height}")
        log.info("Cropping gel image")

        # Validate crop rect
        if width < 50 or height < 50:
            raise ValueError(f"Crop area too small ({width}x{height}). Minimum is 50x50.")
        if x < 0 or y < 0:
            raise ValueError("Crop coordinates must be non-negative.")
        if x + width > gel_image.width or y + height > gel_image.height:
            raise ValueError(
                f"Crop rect ({x},{y},{width},{height}) exceeds image bounds ({gel_image.width}x{gel_image.height})."
            )

        # ── DISPLAY PIPELINE: crop the display PNG (preserves original colors) ──
        if not gel_image.display_file:
            raise ValueError("No display file available for cropping")

        display_array = cls.load_image_from_file_field(gel_image.display_file)
        log.debug(f"Loaded display array: shape={display_array.shape}, dtype={display_array.dtype}")

        cropped_display = display_array[y : y + height, x : x + width]
        display_bytes, display_w, display_h = cls.create_display_image(cropped_display)
        log.debug(f"New display image: {display_w}x{display_h}, {len(display_bytes)} bytes")

        thumbnail_bytes = cls.create_thumbnail(cropped_display)

        # ── ORIGINAL PIPELINE: crop the raw original (preserves bit depth for detection) ──
        orig_bytes = None
        orig_ext = None
        if gel_image.original_file:
            try:
                # Load at NATIVE resolution — resize_to_display=False to avoid the
                # destructive Lanczos that used to happen here and degraded the
                # original file on every crop.
                orig_array = cls.load_image_as_array(gel_image, resize_to_display=False)
                native_h, native_w = orig_array.shape[:2]
                display_w_now = gel_image.width
                display_h_now = gel_image.height

                # Convert display-space crop rect → native-space crop rect
                if display_w_now and display_h_now and (native_h != display_h_now or native_w != display_w_now):
                    sx = native_w / display_w_now
                    sy = native_h / display_h_now
                    nx = int(round(x * sx))
                    ny = int(round(y * sy))
                    nw = int(round(width * sx))
                    nh = int(round(height * sy))
                    log.info(
                        f"Crop rect display→native: ({x},{y},{width},{height}) "
                        f"× ({sx:.3f},{sy:.3f}) → ({nx},{ny},{nw},{nh})"
                    )
                else:
                    # Display dims == native dims, no mapping needed
                    nx, ny, nw, nh = x, y, width, height

                # Clamp to native bounds (guards against rounding beyond edge)
                nx = max(0, min(nx, native_w - 1))
                ny = max(0, min(ny, native_h - 1))
                nw = max(1, min(nw, native_w - nx))
                nh = max(1, min(nh, native_h - ny))

                cropped_orig = orig_array[ny : ny + nh, nx : nx + nw]
                log.debug(f"Cropped original array: shape={cropped_orig.shape}, dtype={cropped_orig.dtype}")

                if cropped_orig.dtype in (np.uint16, np.int16):
                    pil_img = Image.fromarray(cropped_orig)
                    orig_buffer = io.BytesIO()
                    pil_img.save(orig_buffer, format="TIFF")
                    orig_buffer.seek(0)
                    orig_bytes = orig_buffer.read()
                    orig_ext = ".tif"
                else:
                    pil_img = Image.fromarray(cls.normalize_to_8bit(cropped_orig))
                    if pil_img.mode != "L":
                        pil_img = pil_img.convert("L")
                    orig_buffer = io.BytesIO()
                    pil_img.save(orig_buffer, format="PNG", optimize=True)
                    orig_buffer.seek(0)
                    orig_bytes = orig_buffer.read()
                    orig_ext = ".png"
            except Exception as e:
                # HISTORICAL BUG: this used to be log.warning, which silently
                # swallowed IO/encode failures. When the original save failed,
                # the model's width/height were still updated to the cropped
                # display dims, leaving an inconsistent state (TIFF full-gel
                # + display dims = crop rect) that later broke detection via
                # an aspect-ratio-changing resize in load_image_as_array.
                # Surfacing as ERROR + re-raising so the API returns 500 and
                # the crop can be retried rather than leaving a silent
                # corruption.
                log.error(
                    f"Crop of original file failed — aborting crop to avoid "
                    f"inconsistent state (display dims updated without matching "
                    f"original). Error: {e}",
                    exc_info=True,
                )
                raise

        # Build filenames
        base_name = Path(gel_image.original_filename or "image").stem
        display_filename = f"display/{base_name}_cropped.png"
        thumb_filename = f"thumbnails/{base_name}_cropped_thumb.png"
        orig_filename = f"originals/{base_name}_cropped{orig_ext or '.png'}"

        # Save to model fields
        gel_image.display_file.save(display_filename, ContentFile(display_bytes), save=False)
        gel_image.thumbnail.save(thumb_filename, ContentFile(thumbnail_bytes), save=False)
        if orig_bytes and gel_image.original_file:
            gel_image.original_file.save(orig_filename, ContentFile(orig_bytes), save=False)
        gel_image.width = display_w
        gel_image.height = display_h
        gel_image.save()

        log.success(f"Cropped gel image to {display_w}x{display_h}")
        return display_w, display_h

    @classmethod
    def load_image_from_file_field(cls, file_field) -> np.ndarray:
        """
        Load image from a Django file field as numpy array.

        This is a lower-level method that works directly with file fields.

        Args:
            file_field: Django FileField or FieldFile.

        Returns:
            Numpy array.
        """
        if not file_field:
            raise ValueError("No file field provided")

        try:
            with file_field.open("rb") as f:
                file_content = f.read()
        except FileNotFoundError as e:
            storage_backend = type(file_field.storage).__name__
            raise OSError(
                f"File not found: {file_field.name} "
                f"(storage: {storage_backend}). "
                f"Check AZURE_STORAGE_KEY is set in the worker environment."
            ) from e

        # Try to read with PIL
        pil_img = Image.open(io.BytesIO(file_content))
        img_array = np.array(pil_img)

        # Convert to grayscale if needed
        if len(img_array.shape) == 3 and img_array.shape[2] in [3, 4]:
            img_array = np.mean(img_array[:, :, :3], axis=2).astype(np.uint8)

        return img_array
