"""Forms for GelAnalysis."""

from django import forms

from gel_analyzer.models import GelAnalysis


class GelAnalysisCreateForm(forms.ModelForm):
    class Meta:
        model = GelAnalysis
        fields = ["name", "notes"]


# =============================================================================
# API Serialization Helpers (for JSON responses)
# =============================================================================


def lane_to_dict(lane) -> dict:
    """Serialize a Lane instance to a dictionary for JSON API responses."""
    return {
        "id": lane.pk,
        "lane_number": lane.lane_number,
        "lane_type": lane.lane_type,
        "lane_type_display": lane.get_lane_type_display(),
        "detection_source": lane.detection_source,
        # Shape and geometry
        "lane_shape": lane.lane_shape,
        "x": float(lane.x) if lane.x else 0,
        "y": float(lane.y) if lane.y else 0,
        "width": float(lane.width) if lane.width else 0,
        "height": float(lane.height) if lane.height else 0,
        "polygon": lane.polygon or [],
        # Sample conditions
        "is_reduced": lane.is_reduced,
        "condition_display": lane.condition_display,
        # Protein load
        "protein_load_ug": float(lane.protein_load_ug) if lane.protein_load_ug else None,
        "protein_load_type": lane.protein_load_type or "",
        "protein_load_type_display": lane.get_protein_load_type_display() if lane.protein_load_type else "",
        # Sample info — Phoresis stores per-lane extras in `sample_metadata` JSON.
        "sample_name": lane.sample_name or "",
        "sample_metadata": lane.sample_metadata or {},
        # Ladder template (for LADDER type lanes)
        "ladder_template_id": str(lane.ladder_template_id) if lane.ladder_template_id else None,
        "ladder_template_name": lane.ladder_template.name if lane.ladder_template_id else None,
        # Notes and nested bands
        "notes": lane.notes or "",
        "bands": [band_to_dict(band) for band in lane.bands.all()],
    }


def band_to_dict(band) -> dict:
    """Serialize a Band instance to a dictionary for JSON API responses."""
    band_type = band.band_type or "OTHER"
    band_type_display = band.get_band_type_display() if band.band_type else "Other"

    return {
        "id": str(band.pk),  # UUID to string
        "lane_id": band.lane_id,
        "band_type": band_type,
        "band_type_display": band_type_display,
        "detection_source": band.detection_source,
        "position_y": float(band.position_y) if band.position_y else None,
        "polygon": band.polygon or [],
        "bbox_x": float(band.bbox_x) if band.bbox_x else None,
        "bbox_y": float(band.bbox_y) if band.bbox_y else None,
        "bbox_width": float(band.bbox_width) if band.bbox_width else None,
        "bbox_height": float(band.bbox_height) if band.bbox_height else None,
        "estimated_mw_kda": float(band.estimated_mw_kda) if band.estimated_mw_kda else None,
        "intensity": float(band.intensity_raw) if band.intensity_raw else None,
        "relative_intensity": float(band.intensity_normalized) if band.intensity_normalized else None,
        "label": band.label or "",
        "notes": band.notes or "",
        "metadata": band.metadata or {},
    }


def analysis_to_dict(analysis, include_annotations: bool = False) -> dict:
    """Serialize a GelAnalysis instance to a dictionary for JSON API responses."""
    data = {
        "id": str(analysis.pk),  # UUID to string
        "name": analysis.name,
        "notes": analysis.notes or "",
        "status": analysis.status,
        "status_display": analysis.get_status_display(),
        "total_lanes": analysis.total_lanes,
        "total_bands": analysis.total_bands,
        "is_editable": analysis.is_editable,
        "gel_image": {
            "id": str(analysis.gel_image_id),
            "gel_type": analysis.gel_image.gel_type,
            "width": analysis.gel_image.width,
            "height": analysis.gel_image.height,
        }
        if analysis.gel_image
        else None,
    }

    if include_annotations:
        data["lanes"] = [lane_to_dict(lane) for lane in analysis.lanes.prefetch_related("bands").all()]

    return data
