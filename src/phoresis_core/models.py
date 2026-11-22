"""Core models — `ErrorLog` for error persistence."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.timezone import now


class ErrorLog(models.Model):
    """Persistence target for ERROR-level loguru records.

    Populated by `phoresis_core.logging_config.db_error_sink`.
    """

    SOURCE_TYPE_HTTP = "http"
    SOURCE_TYPE_CELERY = "celery"
    SOURCE_TYPE_COMMAND = "command"
    SOURCE_TYPE_OTHER = "other"
    SOURCE_TYPE_CHOICES = (
        (SOURCE_TYPE_HTTP, "HTTP request"),
        (SOURCE_TYPE_CELERY, "Celery task"),
        (SOURCE_TYPE_COMMAND, "Management command"),
        (SOURCE_TYPE_OTHER, "Other / unknown"),
    )

    timestamp = models.DateTimeField(default=now)
    level = models.CharField(max_length=20)
    message = models.TextField()
    pathname = models.TextField(blank=True, null=True)
    func_name = models.CharField(max_length=255, blank=True, null=True)
    lineno = models.IntegerField(blank=True, null=True)
    exception_type = models.CharField(max_length=255, blank=True, null=True)
    exception_text = models.TextField(blank=True, null=True)

    request_path = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who triggered the error (if any)",
    )
    error_id = models.CharField(
        max_length=25,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Unique reference shown to users (e.g., PHOR-20260503-A7F3B2)",
    )

    http_method = models.CharField(max_length=10, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    referer = models.TextField(blank=True, null=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    view_name = models.CharField(max_length=255, blank=True, null=True)
    view_func_name = models.CharField(max_length=255, blank=True, null=True)

    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        blank=True,
        null=True,
        db_index=True,
    )
    app_label = models.CharField(max_length=50, blank=True, null=True, db_index=True)

    task_name = models.CharField(max_length=255, blank=True, null=True)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    queue_name = models.CharField(max_length=64, blank=True, null=True)
    retry_count = models.IntegerField(blank=True, null=True)
    hostname = models.CharField(max_length=255, blank=True, null=True)
    task_args = models.JSONField(blank=True, null=True)
    task_kwargs = models.JSONField(blank=True, null=True)

    request_data = models.JSONField(blank=True, null=True)
    error_signature = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    is_handled = models.BooleanField(default=False)

    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_errors",
    )
    acknowledged_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Error log"
        verbose_name_plural = "Error logs"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        if self.error_id:
            return f"[{self.error_id}] {self.level} – {self.message[:60]}"
        return f"[{self.level}] {self.timestamp} – {self.message[:80]}"


class ArchivedMediaFile(models.Model):
    """A media file moved from MEDIA_ROOT to the archive disk (``phoresis_core.media_tiers``).

    The row is what still knows the file exists while the archive disk is unplugged: its name stays
    taken, and opening it says "reconnect the disk" instead of "file not found".
    """

    name = models.CharField(max_length=500, unique=True, help_text="Storage name, relative to MEDIA_ROOT")
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    archived_at = models.DateTimeField(default=now)
    delete_pending = models.BooleanField(
        default=False, help_text="Deleted while the archive disk was unplugged: removed at the next pass"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
