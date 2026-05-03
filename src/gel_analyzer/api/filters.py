"""
Django Filter classes for Gel Analyzer API.
"""

import django_filters
from django_filters import CharFilter, NumberFilter, UUIDFilter

from gel_analyzer.models import (
    Band,
    DensitometryJob,
    GelAnalysis,
    GelImage,
    LadderTemplate,
    Lane,
    SavedComparison,
)


class GelImageFilter(django_filters.FilterSet):
    gel_type = CharFilter(lookup_expr="iexact")
    file_format = CharFilter(lookup_expr="iexact")

    class Meta:
        model = GelImage
        fields = ["gel_type", "file_format"]


class GelAnalysisFilter(django_filters.FilterSet):
    status = CharFilter(lookup_expr="iexact")
    gel_image = UUIDFilter(field_name="gel_image__id")

    class Meta:
        model = GelAnalysis
        fields = ["status", "gel_image"]


class LaneFilter(django_filters.FilterSet):
    analysis = UUIDFilter(field_name="analysis__id")
    lane_type = CharFilter(lookup_expr="iexact")

    class Meta:
        model = Lane
        fields = ["analysis", "lane_type"]


class BandFilter(django_filters.FilterSet):
    lane = NumberFilter(field_name="lane__id")
    band_type = CharFilter(lookup_expr="iexact")
    detection_source = CharFilter(lookup_expr="iexact")
    has_mw = django_filters.BooleanFilter(field_name="estimated_mw_kda", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Band
        fields = ["lane", "band_type", "detection_source"]


class LadderTemplateFilter(django_filters.FilterSet):
    category = CharFilter(lookup_expr="iexact")
    manufacturer = CharFilter(lookup_expr="icontains")
    is_active = django_filters.BooleanFilter()
    is_global = django_filters.BooleanFilter()

    class Meta:
        model = LadderTemplate
        fields = ["category", "manufacturer", "is_active", "is_global"]


class SavedComparisonFilter(django_filters.FilterSet):
    is_public = django_filters.BooleanFilter()
    created_by = NumberFilter(field_name="created_by__id")

    class Meta:
        model = SavedComparison
        fields = ["is_public", "created_by"]


class DensitometryJobFilter(django_filters.FilterSet):
    analysis = UUIDFilter(field_name="analysis__id")
    status = CharFilter(lookup_expr="iexact")

    class Meta:
        model = DensitometryJob
        fields = ["analysis", "status"]
