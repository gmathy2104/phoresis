"""
Serialization helpers for Saved Comparison API.
"""


def saved_comparison_to_dict(comparison, include_lanes=False):
    """
    Serialize a SavedComparison instance to a dictionary for JSON API.

    Args:
        comparison: SavedComparison instance
        include_lanes: If True, include detailed lane data

    Returns:
        dict: Serialized comparison data
    """
    data = {
        "id": str(comparison.pk),
        "name": comparison.name,
        "description": comparison.description,
        "is_public": comparison.is_public,
        "view_settings": comparison.view_settings or {},
        "lane_count": comparison.lanes.count(),
        "created_by": {
            "id": comparison.created_by_id,
            "username": comparison.created_by.username if comparison.created_by else None,
            "display_name": (
                (comparison.created_by.get_full_name().strip() or comparison.created_by.username)
                if comparison.created_by
                else None
            ),
        },
        "created_at": comparison.created_at.isoformat() if comparison.created_at else None,
        "updated_at": comparison.updated_at.isoformat() if comparison.updated_at else None,
    }

    # Always compute summary fields needed for card display
    through_qs = comparison.savedcomparisonlane_set.select_related(
        "lane__analysis__gel_image",
    ).order_by("order")

    gel_types = set()
    calibrated_count = 0
    lanes_data = []

    for through_obj in through_qs:
        lane = through_obj.lane
        gel_type = None
        has_calibration = False

        if lane.analysis and lane.analysis.gel_image:
            gel_type = lane.analysis.gel_image.gel_type
            gel_types.add(gel_type)

        if lane.analysis:
            has_calibration = lane.analysis.ladder_calibrations.exists()
            if has_calibration:
                calibrated_count += 1

        if include_lanes:
            lanes_data.append(
                {
                    "id": lane.pk,
                    "lane_number": lane.lane_number,
                    "sample_name": lane.sample_name or None,
                    "order": through_obj.order,
                    "analysis_name": lane.analysis.name if lane.analysis else None,
                    "gel_type": gel_type,
                    "has_calibration": has_calibration,
                    "has_densitometry": hasattr(lane, "densitometry_summary") and lane.densitometry_summary is not None,
                }
            )

    data["gel_types"] = list(gel_types)
    data["calibrated_count"] = calibrated_count

    if include_lanes:
        data["lanes"] = lanes_data

    return data
