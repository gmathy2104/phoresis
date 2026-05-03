"""
GelImage model for storing uploaded gel electrophoresis images.

Supports SDS-PAGE gels, Dot Blots, and Western Blots with format conversion
and web-optimized display files.
"""

import uuid

from simple_history.models import HistoricalRecords

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class GelImage(models.Model):
    """
    Primary storage for gel electrophoresis images.

    Stores the original file unchanged, plus web-optimized display
    and thumbnail versions. Supports .gel, .tiff, .png, .jpg formats.
    """

    class GelType(models.TextChoices):
        """Types of gel electrophoresis images."""

        SDS_PAGE = "SDS_PAGE", "SDS-PAGE"
        DOT_BLOT = "DOT_BLOT", "Dot Blot"
        WESTERN_BLOT = "WESTERN_BLOT", "Western Blot"
        UNKNOWN = "UNKNOWN", "Unknown"

    class FileFormat(models.TextChoices):
        """Supported file formats."""

        GEL = "GEL", "Bio-Rad .gel"
        SCN = "SCN", "Bio-Rad .scn"
        TIFF = "TIFF", "TIFF"
        PNG = "PNG", "PNG"
        JPEG = "JPEG", "JPEG"
        UNKNOWN = "UNKNOWN", "Unknown"

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # File storage
    original_file = models.FileField(
        upload_to="gel_images/originals/%Y/%m/", max_length=500, help_text="Original uploaded file (never modified)"
    )
    display_file = models.ImageField(
        upload_to="gel_images/display/%Y/%m/",
        max_length=500,
        blank=True,
        null=True,
        help_text="Web-optimized PNG version",
    )
    thumbnail = models.ImageField(
        upload_to="gel_images/thumbnails/%Y/%m/", max_length=500, blank=True, null=True, help_text="256x256 thumbnail"
    )

    # File metadata
    original_filename = models.CharField(max_length=255, help_text="Original filename as uploaded")
    file_format = models.CharField(max_length=20, choices=FileFormat.choices, default=FileFormat.UNKNOWN)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True, help_text="Original file size in bytes")

    # Image dimensions
    width = models.PositiveIntegerField(null=True, blank=True, help_text="Image width in pixels")
    height = models.PositiveIntegerField(null=True, blank=True, help_text="Image height in pixels")
    bit_depth = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)], help_text="Bit depth (8, 16, etc.)"
    )

    # Gel type (can be inferred from YOLO or explicitly set)
    gel_type = models.CharField(max_length=20, choices=GelType.choices, default=GelType.UNKNOWN)

    # Description and notes
    description = models.TextField(blank=True, help_text="Optional description of the gel image")

    # Scanner metadata (Bio-Rad .scn files)
    scanner_metadata = models.JSONField(
        blank=True,
        null=True,
        default=None,
        help_text="Scanner metadata extracted from .scn files (model, exposure, filter, etc.)",
    )

    # Audit fields
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_gel_images"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Audit trail
    history = HistoricalRecords(history_change_reason_field=models.TextField(null=True))

    class Meta:
        verbose_name = "Gel Image"
        verbose_name_plural = "01. Gel Images"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["gel_type"], name="ga_image_geltype_idx"),
            models.Index(fields=["uploaded_at"], name="ga_image_uploaded_idx"),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.get_gel_type_display()})"

    @property
    def has_display_file(self) -> bool:
        """Check if display file exists."""
        return bool(self.display_file)

    @property
    def has_thumbnail(self) -> bool:
        """Check if thumbnail exists."""
        return bool(self.thumbnail)

    @property
    def dimensions_str(self) -> str:
        """Get dimensions as string."""
        if self.width and self.height:
            return f"{self.width} x {self.height}"
        return "-"
