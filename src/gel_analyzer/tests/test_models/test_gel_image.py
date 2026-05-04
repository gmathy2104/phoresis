"""
Tests for GelImage model.
"""

import pytest

from gel_analyzer.models import GelImage


@pytest.mark.django_db
class TestGelImage:
    """Tests for GelImage model."""

    def test_create_gel_image(self, gel_image):
        """Test basic GelImage creation."""
        assert gel_image.pk is not None
        assert gel_image.original_filename == "test_gel.png"
        assert gel_image.file_format == GelImage.FileFormat.PNG
        assert gel_image.gel_type == GelImage.GelType.SDS_PAGE

    def test_gel_image_str(self, gel_image):
        """Test GelImage string representation."""
        assert "test_gel.png" in str(gel_image)
        assert "SDS-PAGE" in str(gel_image)

    def test_gel_image_dimensions(self, gel_image):
        """Test GelImage dimensions properties."""
        assert gel_image.width == 400
        assert gel_image.height == 500
        assert gel_image.dimensions_str == "400 x 500"

    def test_gel_image_dimensions_str_missing(self, db, test_user, uploaded_gel_file):
        """Test dimensions_str when dimensions are missing."""
        gel_image = GelImage.objects.create(
            original_file=uploaded_gel_file, original_filename="test.png", uploaded_by=test_user
        )
        assert gel_image.dimensions_str == "-"

    def test_has_display_file(self, gel_image):
        """Test has_display_file property."""
        assert gel_image.has_display_file is False
        # When display_file is set, it should be True
        # (not testing file upload here, just the property logic)

    def test_has_thumbnail(self, gel_image):
        """Test has_thumbnail property."""
        assert gel_image.has_thumbnail is False

    def test_gel_type_choices(self):
        """Test gel type choices are valid."""
        assert GelImage.GelType.SDS_PAGE == "SDS_PAGE"
        assert GelImage.GelType.DOT_BLOT == "DOT_BLOT"
        assert GelImage.GelType.WESTERN_BLOT == "WESTERN_BLOT"
        assert GelImage.GelType.UNKNOWN == "UNKNOWN"

    def test_file_format_choices(self):
        """Test file format choices are valid."""
        assert GelImage.FileFormat.GEL == "GEL"
        assert GelImage.FileFormat.TIFF == "TIFF"
        assert GelImage.FileFormat.PNG == "PNG"
        assert GelImage.FileFormat.JPEG == "JPEG"

    def test_uploaded_by_set(self, gel_image, test_user):
        """Test that uploaded_by is set."""
        assert gel_image.uploaded_by == test_user

    def test_timestamps_auto_set(self, gel_image):
        """Test that timestamps are automatically set."""
        assert gel_image.uploaded_at is not None
        assert gel_image.updated_at is not None

    def test_history_tracking(self, gel_image):
        """Test that history is tracked via django-simple-history."""
        assert hasattr(gel_image, "history")
        # Change something and verify history
        gel_image.description = "Updated description"
        gel_image.save()
        assert gel_image.history.count() >= 1


@pytest.mark.django_db
class TestGelImageRelations:
    """Tests for GelImage relationships."""

    def test_analyses_relation(self, gel_image, gel_analysis):
        """Test GelImage to GelAnalysis relationship."""
        assert gel_image.analyses.count() == 1
        assert gel_image.analyses.first() == gel_analysis

    def test_cascade_delete_analyses(self, gel_image, gel_analysis):
        """Test that analyses are deleted when gel image is deleted."""
        analysis_id = gel_analysis.pk
        gel_image.delete()

        from gel_analyzer.models import GelAnalysis

        assert not GelAnalysis.objects.filter(pk=analysis_id).exists()
