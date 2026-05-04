"""Aggregation helpers for the dashboard home page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone


@dataclass(frozen=True)
class DashboardKPIs:
    total_gels: int
    total_analyses: int
    pending_analyses: int
    recent_uploads_7d: int


def get_kpis() -> DashboardKPIs:
    """Compute the dashboard KPI tuple."""
    from gel_analyzer.models import GelAnalysis, GelImage

    seven_days_ago = timezone.now() - timedelta(days=7)
    return DashboardKPIs(
        total_gels=GelImage.objects.count(),
        total_analyses=GelAnalysis.objects.count(),
        pending_analyses=GelAnalysis.objects.filter(
            status__in=[GelAnalysis.Status.DRAFT, GelAnalysis.Status.IN_PROGRESS]
        ).count(),
        recent_uploads_7d=GelImage.objects.filter(uploaded_at__gte=seven_days_ago).count(),
    )


def get_recent_gels(limit: int = 6):
    """Return the most-recently-uploaded gels with annotation counts."""
    from gel_analyzer.models import GelImage

    return list(
        GelImage.objects.select_related("uploaded_by")
        .annotate(analyses_count=Count("analyses"))
        .order_by("-uploaded_at")[:limit]
    )
