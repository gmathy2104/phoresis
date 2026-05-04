"""
URL configuration for gel_analyzer app.

URL Structure:
- /images/ : Image list, upload, detail, delete
- /analyses/ : Analysis list, create, detail, annotate
- /api/ : JSON API endpoints for annotation CRUD
"""

from django.urls import include, path

from gel_analyzer.views import (
    analysis_annotate_view,
    analysis_create_view,
    analysis_detail_view,
    analysis_list_view,
    api_analysis_apply_calibration,
    api_analysis_apply_multi_calibration,
    api_analysis_calibrate,
    api_analysis_calibrate_multi,
    api_analysis_calibration,
    api_analysis_data,
    api_analysis_multi_calibration,
    api_analysis_status_transition,
    api_analysis_yolo_results,
    api_band_densitometry,
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
    api_densitometry_job_status,
    api_detect_and_create_bands,
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
    api_detect_peaks,
    api_detection_params_defaults,
    api_export_densitometry,
    api_export_status,
    api_generate_analysis_report,
    api_generate_comparison_report,
    api_generate_densitometry_report,
    api_get_densitometry,
    api_image_proxy,
    api_images_with_densitometry,
    api_ladder_template_detail,
    api_ladder_templates,
    api_lane_apply_ladder_template,
    api_lane_bands,
    api_lane_comparison_data,
    api_lane_densitometry,
    api_lane_detail,
    api_lane_match_template,
    api_lane_profile,
    api_lanes,
    api_run_densitometry,
    api_run_densitometry_async,
    api_sam_embeddings,
    api_saved_comparison_detail,
    api_saved_comparisons,
    api_studio_auto_assign,
    api_studio_lanes_available,
    api_studio_redetect,
    api_studio_save,
    api_task_status,
    api_template_train_now,
    api_template_training_status,
    comparison_list_view,
    cross_lane_consensus_view,
    densitometry_view,
    image_delete_view,
    image_detail_view,
    image_list_view,
    image_upload_view,
    sample_comparison_view,
    template_calibration_view,
    template_clear_rf_patterns_view,
    template_save_rf_patterns_view,
    template_studio_view,
    template_training_list_view,
)

app_name = "gel_analyzer"

urlpatterns = [
    # DRF API (formal REST API with OpenAPI docs)
    path("api/", include("gel_analyzer.api.urls", namespace="gel_analyzer_api")),
    # Images
    path("images/", image_list_view, name="image_list"),
    path("images/upload/", image_upload_view, name="image_upload"),
    path("images/<uuid:pk>/", image_detail_view, name="image_detail"),
    path("images/<uuid:pk>/delete/", image_delete_view, name="image_delete"),
    # Analyses
    path("analyses/", analysis_list_view, name="analysis_list"),
    path("images/<uuid:image_pk>/analyses/create/", analysis_create_view, name="analysis_create"),
    path("analyses/<uuid:pk>/", analysis_detail_view, name="analysis_detail"),
    path("analyses/<uuid:pk>/annotate/", analysis_annotate_view, name="analysis_annotate"),
    # API Endpoints (JSON)
    path("api/analyses/<uuid:pk>/lanes/", api_lanes, name="api_lanes"),
    path("api/analyses/<uuid:pk>/lanes/bulk/", api_bulk_lanes, name="api_bulk_lanes"),
    path("api/analyses/<uuid:pk>/lanes/bulk-update/", api_bulk_update_lanes, name="api_bulk_update_lanes"),
    path("api/analyses/<uuid:pk>/lanes/bulk-delete/", api_bulk_delete_lanes, name="api_bulk_delete_lanes"),
    path("api/analyses/<uuid:pk>/bands/bulk-delete/", api_bulk_delete_bands, name="api_bulk_delete_bands"),
    path("api/analyses/<uuid:pk>/data/", api_analysis_data, name="api_analysis_data"),
    path("api/analyses/<uuid:pk>/yolo-results/", api_analysis_yolo_results, name="api_yolo_results"),
    path("api/lanes/<int:pk>/", api_lane_detail, name="api_lane_detail"),
    path("api/lanes/<int:pk>/bands/", api_lane_bands, name="api_lane_bands"),
    path(
        "api/lanes/<int:pk>/apply-ladder-template/",
        api_lane_apply_ladder_template,
        name="api_lane_apply_ladder_template",
    ),
    path("api/bands/<uuid:pk>/", api_band_detail, name="api_band_detail"),
    path("api/images/<uuid:pk>/proxy/", api_image_proxy, name="api_image_proxy"),
    path("api/images/<uuid:pk>/crop/", api_crop_image, name="api_crop_image"),
    # Band Detection API (Auto d1/d2 Derivative)
    path("api/lanes/<int:pk>/detect-bands/", api_detect_bands_lane, name="api_detect_bands_lane"),
    path("api/lanes/<int:pk>/detect-bands/save/", api_detect_bands_lane_save, name="api_detect_bands_lane_save"),
    path(
        "api/lanes/<int:pk>/detect-bands/diagnostic/", api_detect_bands_diagnostic, name="api_detect_bands_diagnostic"
    ),
    path("api/analyses/<uuid:pk>/detect-bands/", api_detect_bands_bulk, name="api_detect_bands_bulk"),
    path("api/detection/params/", api_detection_params_defaults, name="api_detection_params"),
    # Async Band Detection (Celery Tasks)
    path("api/analyses/<uuid:pk>/detect-bands/async/", api_detect_bands_async, name="api_detect_bands_async"),
    path("api/tasks/<str:task_id>/status/", api_task_status, name="api_task_status"),
    # Ladder Templates API
    path("api/ladder-templates/", api_ladder_templates, name="api_ladder_templates"),
    path("api/ladder-templates/default/", api_default_ladder_template, name="api_default_ladder_template"),
    path("api/ladder-templates/<uuid:pk>/", api_ladder_template_detail, name="api_ladder_template_detail"),
    # Calibration API (single-ladder)
    path("api/lanes/<int:pk>/match-template/", api_lane_match_template, name="api_lane_match_template"),
    path("api/analyses/<uuid:pk>/calibrate/", api_analysis_calibrate, name="api_analysis_calibrate"),
    path("api/analyses/<uuid:pk>/apply-calibration/", api_analysis_apply_calibration, name="api_apply_calibration"),
    path("api/analyses/<uuid:pk>/calibration/", api_analysis_calibration, name="api_analysis_calibration"),
    # Multi-Ladder Calibration API
    path("api/analyses/<uuid:pk>/calibrate-multi/", api_analysis_calibrate_multi, name="api_calibrate_multi"),
    path(
        "api/analyses/<uuid:pk>/apply-multi-calibration/",
        api_analysis_apply_multi_calibration,
        name="api_apply_multi_calibration",
    ),
    path("api/analyses/<uuid:pk>/multi-calibration/", api_analysis_multi_calibration, name="api_multi_calibration"),
    path("api/bands/<uuid:pk>/estimate-mw/", api_band_estimate_mw, name="api_band_estimate_mw"),
    # SAM Embeddings API
    path("api/analyses/<uuid:pk>/sam-embeddings/", api_sam_embeddings, name="api_sam_embeddings"),
    path("api/bands/bulk-update-polygons/", api_bands_bulk_update_polygons, name="api_bands_bulk_update_polygons"),
    # Admin Training Views (staff only)
    path("admin/templates/training/", template_training_list_view, name="admin_template_training_list"),
    path("admin/templates/<uuid:pk>/calibrate/", template_calibration_view, name="admin_template_calibration"),
    path("admin/templates/<uuid:pk>/save-rf/", template_save_rf_patterns_view, name="admin_template_save_rf"),
    path("admin/templates/<uuid:pk>/clear-rf/", template_clear_rf_patterns_view, name="admin_template_clear_rf"),
    path(
        "api/admin/templates/<uuid:pk>/training-status/",
        api_template_training_status,
        name="api_template_training_status",
    ),
    path("api/admin/templates/<uuid:pk>/train-now/", api_template_train_now, name="api_template_train_now"),
    # Studio - cross-gel training workbench
    path("admin/templates/<uuid:pk>/studio/", template_studio_view, name="admin_template_studio"),
    path(
        "api/admin/templates/<uuid:pk>/studio/lanes/",
        api_studio_lanes_available,
        name="api_studio_lanes_available",
    ),
    path(
        "api/admin/templates/<uuid:pk>/studio/auto-assign/",
        api_studio_auto_assign,
        name="api_studio_auto_assign",
    ),
    path(
        "api/admin/templates/<uuid:pk>/studio/save/",
        api_studio_save,
        name="api_studio_save",
    ),
    path(
        "api/admin/templates/<uuid:pk>/studio/redetect/",
        api_studio_redetect,
        name="api_studio_redetect",
    ),
    # Densitometry View
    path("analyses/<uuid:pk>/densitometry/", densitometry_view, name="analysis_densitometry"),
    # Densitometry API
    path("api/analyses/<uuid:pk>/densitometry/", api_get_densitometry, name="api_densitometry"),
    path("api/analyses/<uuid:pk>/densitometry/run/", api_run_densitometry, name="api_run_densitometry"),
    path("api/analyses/<uuid:pk>/densitometry/async/", api_run_densitometry_async, name="api_run_densitometry_async"),
    path(
        "api/analyses/<uuid:pk>/densitometry/jobs/<uuid:job_id>/",
        api_densitometry_job_status,
        name="api_densitometry_job_status",
    ),
    path("api/analyses/<uuid:pk>/densitometry/export/", api_export_densitometry, name="api_export_densitometry"),
    path("api/analyses/<uuid:pk>/densitometry/export/<str:task_id>/", api_export_status, name="api_export_status"),
    path("api/lanes/<int:pk>/profile/", api_lane_profile, name="api_lane_profile"),
    path("api/lanes/<int:pk>/densitometry/", api_lane_densitometry, name="api_lane_densitometry"),
    path("api/bands/<uuid:pk>/densitometry/", api_band_densitometry, name="api_band_densitometry"),
    # Peak Detection API (Densitometry - visualization only)
    path("api/lanes/<int:pk>/peaks/detect/", api_detect_peaks, name="api_detect_peaks"),
    path(
        "api/analyses/<uuid:pk>/peaks/detect-and-create/",
        api_detect_and_create_bands,
        name="api_detect_and_create_bands",
    ),
    # Band Detection Teaching/Calibration API
    path("api/analyses/<uuid:pk>/calibrate-detection/", api_calibrate_detection, name="api_calibrate_detection"),
    # CV2 Vision Band Detection API
    path("api/lanes/<int:pk>/detect-bands-cv2/", api_detect_bands_cv2_lane, name="api_detect_bands_cv2_lane"),
    path(
        "api/lanes/<int:pk>/detect-bands-cv2/save/",
        api_detect_bands_cv2_lane_save,
        name="api_detect_bands_cv2_lane_save",
    ),
    path(
        "api/analyses/<uuid:pk>/detect-bands-cv2/calibrate/",
        api_detect_bands_cv2_calibrate,
        name="api_detect_bands_cv2_calibrate",
    ),
    path(
        "api/analyses/<uuid:pk>/detect-bands-cv2/async/", api_detect_bands_cv2_async, name="api_detect_bands_cv2_async"
    ),
    # Hybrid Band Detection API
    path("api/lanes/<int:pk>/detect-bands-hybrid/", api_detect_bands_hybrid_lane, name="api_detect_bands_hybrid_lane"),
    path(
        "api/lanes/<int:pk>/detect-bands-hybrid/save/",
        api_detect_bands_hybrid_lane_save,
        name="api_detect_bands_hybrid_lane_save",
    ),
    path(
        "api/analyses/<uuid:pk>/detect-bands-hybrid/async/",
        api_detect_bands_hybrid_async,
        name="api_detect_bands_hybrid_async",
    ),
    # Cross-Lane Consensus API (POST run / DELETE undo)
    path(
        "analyses/<uuid:analysis_id>/cross-lane-consensus/",
        cross_lane_consensus_view,
        name="cross_lane_consensus",
    ),
    # Comparison Views
    path("comparisons/", comparison_list_view, name="comparison_list"),
    path("comparisons/compare/", sample_comparison_view, name="sample_comparison"),
    # Comparison API
    path("api/lanes/<int:pk>/comparison-data/", api_lane_comparison_data, name="api_lane_comparison_data"),
    path("api/images/with-densitometry/", api_images_with_densitometry, name="api_images_with_densitometry"),
    # Saved Comparison API
    path("api/comparisons/", api_saved_comparisons, name="api_saved_comparisons"),
    path("api/comparisons/<uuid:pk>/", api_saved_comparison_detail, name="api_saved_comparison_detail"),
    # Report API
    path("api/analyses/<uuid:pk>/report/generate/", api_generate_analysis_report, name="api_generate_analysis_report"),
    path(
        "api/comparisons/<uuid:pk>/report/generate/",
        api_generate_comparison_report,
        name="api_generate_comparison_report",
    ),
    path(
        "api/analyses/<uuid:pk>/densitometry/report/generate/",
        api_generate_densitometry_report,
        name="api_generate_densitometry_report",
    ),
    # Status Workflow API
    path("api/analyses/<uuid:pk>/status/", api_analysis_status_transition, name="api_analysis_status_transition"),
]
