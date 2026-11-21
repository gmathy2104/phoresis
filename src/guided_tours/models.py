"""Who has seen which tour, and what people do in a tour.

Ported from ds-hub-django (``guided_tours/models.py``), same tables.

A tour lives in a JSON file, not in the database: ``tour_id`` is a slug of the registry, with no foreign key.
Neither table carries a simple-history trail: the progress row is
per-user interface state rewritten at each tour, and the events table is itself the log.
"""

from django.conf import settings
from django.db import models


class TourProgress(models.Model):  # no-history-needed: per-user UI state rewritten at each tour; TourEvent is the log
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        DISMISSED = "dismissed", "Dismissed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tour_progress")
    tour_id = models.CharField(max_length=64)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "tour_id"], name="gt_one_progress_per_user_tour")]
        verbose_name = "tour progress"
        verbose_name_plural = "tour progress"

    def __str__(self):
        return f"{self.user} · {self.tour_id} v{self.version} · {self.status}"


class TourEvent(models.Model):  # no-history-needed: an append-only log, never edited
    class Event(models.TextChoices):
        OFFERED = "offered", "Offered"
        DECLINED = "declined", "Declined"
        STARTED = "started", "Started"
        STEP = "step", "Step reached"
        COMPLETED = "completed", "Completed"
        DISMISSED = "dismissed", "Dismissed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tour_events")
    tour_id = models.CharField(max_length=64)
    version = models.PositiveIntegerField()
    event = models.CharField(max_length=12, choices=Event.choices)
    step_key = models.CharField(max_length=64, blank=True)
    step_index = models.PositiveSmallIntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["tour_id", "event"], name="gt_event_tour_event")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.tour_id} v{self.version} · {self.event}"
