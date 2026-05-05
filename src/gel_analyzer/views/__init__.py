"""HTML views for gel_analyzer (Phase 3+). DRF API viewsets land in Phase 4.

Image Views:
- image_list_view: List all images with filtering
- image_upload_view: Upload new images
- image_detail_view: View image details
- image_delete_view: Delete an image

Analysis Views:
- analysis_list_view: List all analyses with filtering
- analysis_create_view: Create new analysis
- analysis_detail_view: View analysis details (read-only)
- analysis_annotate_view: Interactive annotation editor

API Views (JSON):
- api_lanes: List/create lanes for analysis
- api_bulk_lanes: Bulk create lanes (YOLO detection)
- api_bulk_update_lanes: Bulk update multiple lanes
- api_bulk_delete_lanes: Bulk delete multiple lanes
- api_lane_detail: Lane CRUD
- api_lane_bands: Create bands in lane
- api_band_detail: Band CRUD
- api_analysis_data: Full analysis data
- api_image_proxy: Image proxy for CORS-free access
"""

from .analyses import analysis_annotate_view, analysis_create_view, analysis_detail_view, analysis_list_view
from .api import (  # Band Detection API; Async Band Detection API; UNPLUGGED: api_detect_peaks_profile_async,  # Profile Peak Detection deprecated; Ladder Templates API; Calibration API (single-ladder); Multi-Ladder Calibration API; SAM Embeddings API; UNPLUGGED: Profile Peak Detection API deprecated in favour of Auto (d1/d2) detection; api_detect_peaks_from_profile,; Band Detection Teaching/Calibration API; CV2 Vision Band Detection API; Hybrid Band Detection API; Cross-Lane Consensus API; Comparison API; Status Workflow API
    api_analysis_apply_calibration,
    api_analysis_apply_multi_calibration,
    api_analysis_calibrate,
    api_analysis_calibrate_multi,
    api_analysis_calibration,
    api_analysis_data,
    api_analysis_multi_calibration,
    api_analysis_status_transition,
    api_analysis_yolo_results,
    api_band_detail,
    api_band_estimate_mw,
    api_bands_bulk_update_polygons,
    api_bulk_delete_bands,
    api_bulk_delete_lanes,
    api_bulk_lanes,
    api_bulk_update_lanes,
    api_calibrate_detection,
    api_crop_image,
    api_default_ladder_template,
    api_detect_bands_async,
    api_detect_bands_bulk,
    api_detect_bands_cv2_async,
    api_detect_bands_cv2_calibrate,
    api_detect_bands_cv2_lane,
    api_detect_bands_cv2_lane_save,
    api_detect_bands_diagnostic,
    api_detect_bands_hybrid_async,
    api_detect_bands_hybrid_lane,
    api_detect_bands_hybrid_lane_save,
    api_detect_bands_lane,
    api_detect_bands_lane_save,
    api_detection_params_defaults,
    api_image_proxy,
    api_images_with_densitometry,
    api_ladder_template_detail,
    api_ladder_templates,
    api_lane_apply_ladder_template,
    api_lane_bands,
    api_lane_comparison_data,
    api_lane_detail,
    api_lane_match_template,
    api_lanes,
    api_sam_embeddings,
    api_task_status,
    cross_lane_consensus_view,
)
from .comparison import comparison_list_view, sample_comparison_view
from .comparison_api import api_saved_comparison_detail, api_saved_comparisons
from .densitometry import densitometry_view
from .densitometry_api import (  # Peak Detection API
    api_band_densitometry,
    api_densitometry_job_status,
    api_detect_and_create_bands,
    api_detect_peaks,
    api_export_densitometry,
    api_export_status,
    api_get_densitometry,
    api_lane_densitometry,
    api_lane_profile,
    api_run_densitometry,
    api_run_densitometry_async,
)
from .images import image_delete_view, image_detail_view, image_list_view, image_upload_view
from .report_api import api_generate_analysis_report, api_generate_comparison_report, api_generate_densitometry_report
from .studio import (
    api_studio_auto_assign,
    api_studio_lanes_available,
    api_studio_redetect,
    api_studio_save,
    template_studio_view,
)
from .training import (
    api_template_train_now,
    api_template_training_status,
    template_calibration_view,
    template_clear_rf_patterns_view,
    template_save_rf_patterns_view,
    template_training_list_view,
)

__all__ = [
    # Image views
    "image_list_view",
    "image_upload_view",
    "image_detail_view",
    "image_delete_view",
    # Analysis views
    "analysis_list_view",
    "analysis_create_view",
    "analysis_detail_view",
    "analysis_annotate_view",
    # API views
    "api_lanes",
    "api_bulk_lanes",
    "api_bulk_update_lanes",
    "api_bulk_delete_lanes",
    "api_bulk_delete_bands",
    "api_lane_detail",
    "api_lane_bands",
    "api_lane_apply_ladder_template",
    "api_band_detail",
    "api_analysis_data",
    "api_analysis_yolo_results",
    "api_image_proxy",
    "api_crop_image",
    # Band Detection API
    "api_detect_bands_lane",
    "api_detect_bands_lane_save",
    "api_detect_bands_diagnostic",
    "api_detect_bands_bulk",
    "api_detection_params_defaults",
    # Async Band Detection API
    "api_detect_bands_async",
    "api_task_status",
    # Ladder Templates API
    "api_ladder_templates",
    "api_ladder_template_detail",
    "api_default_ladder_template",
    # Calibration API (single-ladder)
    "api_lane_match_template",
    "api_analysis_calibrate",
    "api_analysis_apply_calibration",
    "api_analysis_calibration",
    # Multi-Ladder Calibration API
    "api_analysis_calibrate_multi",
    "api_analysis_apply_multi_calibration",
    "api_analysis_multi_calibration",
    "api_band_estimate_mw",
    # SAM Embeddings API
    "api_sam_embeddings",
    "api_bands_bulk_update_polygons",
    # Training views (admin only)
    "template_training_list_view",
    "template_calibration_view",
    "template_save_rf_patterns_view",
    "template_clear_rf_patterns_view",
    "api_template_training_status",
    "api_template_train_now",
    # Studio (admin ladder training workbench)
    "template_studio_view",
    "api_studio_lanes_available",
    "api_studio_auto_assign",
    "api_studio_save",
    "api_studio_redetect",
    # Densitometry views
    "densitometry_view",
    # Comparison views
    "comparison_list_view",
    "sample_comparison_view",
    # Densitometry API
    "api_get_densitometry",
    "api_run_densitometry",
    "api_run_densitometry_async",
    "api_densitometry_job_status",
    "api_lane_profile",
    "api_lane_densitometry",
    "api_band_densitometry",
    "api_export_densitometry",
    "api_export_status",
    # Peak Detection API
    "api_detect_peaks",
    "api_detect_and_create_bands",
    # UNPLUGGED: Profile Peak Detection API deprecated in favour of Auto (d1/d2) detection
    # 'api_detect_peaks_from_profile',
    # 'api_detect_peaks_profile_async',
    # Band Detection Teaching/Calibration API
    "api_calibrate_detection",
    # CV2 Vision Band Detection API
    "api_detect_bands_cv2_lane",
    "api_detect_bands_cv2_lane_save",
    "api_detect_bands_cv2_calibrate",
    "api_detect_bands_cv2_async",
    # Hybrid Band Detection API
    "api_detect_bands_hybrid_lane",
    "api_detect_bands_hybrid_lane_save",
    "api_detect_bands_hybrid_async",
    # Cross-Lane Consensus API
    "cross_lane_consensus_view",
    # Comparison API
    "api_lane_comparison_data",
    "api_images_with_densitometry",
    # Saved Comparison API
    "api_saved_comparisons",
    "api_saved_comparison_detail",
    # Report API
    "api_generate_analysis_report",
    "api_generate_comparison_report",
    "api_generate_densitometry_report",
    # Status Workflow API
    "api_analysis_status_transition",
]
