# `gel_analyzer`

Gel electrophoresis image analysis — the scientific core of Phoresis.

## Purpose

End-to-end pipeline for SDS-PAGE / Dot Blot / Western Blot images:
- Upload + thumbnail + display-image generation.
- Lane and band annotation (interactive editor with SVG.js + ONNX SAM).
- MW calibration (single + multi-ladder, Hungarian + RANSAC matching).
- Hybrid band detection (CV2 + d1/d2 derivative + cross-lane consensus).
- Densitometry (Gaussian fitting, peak deconvolution, normalization, POI purity).
- Lane comparison (electropherograms + 4-panel cross-lane view).
- Report generation (Word, Excel, PowerPoint).

## Models (14)

| Model | Purpose | Notes |
|---|---|---|
| `GelImage` | uploaded gel + thumbnail + display | uploaded_by FK to accounts.User |
| `GelAnalysis` | analysis session | created_by, approved_by FKs |
| `Lane` | rectangle / quad / polygon lane | sample_metadata JSONField (no central sample registry — Phoresis is single-purpose) |
| `Band` | individual band | created_by FK; metadata JSONField for hybrid_phase etc. |
| `MWMarker` | MW value at a Y position | linked to LADDER lanes |
| `LadderTemplate` | reusable MW ladder | global templates seeded by `seed_ladder_templates` |
| `LadderBandDefinition` | individual band in a ladder | mw_kda + band_order |
| `LadderCalibration` | per-lane calibration result | log-linear / polynomial fit coefficients |
| `MultiLadderCalibrationConfig` | analysis-level multi-ladder config | gel-smile correction support |
| `DensitometryResult` | per-band Gaussian fit + integration | one-to-one with Band |
| `LaneDensitometrySummary` | per-lane aggregates + POI purity | one-to-one with Lane |
| `DensitometryJob` | async densitometry tracking | RUNNING/FAILED state machine |
| `SavedComparison` | persisted lane comparison | view_settings JSONField |
| `SavedComparisonLane` | M2M through with order | preserves comparison panel order |

## Services

```
services/
├── band_detection/        # 14 files — CV2 + derivative + hybrid + cross-lane
│   └── BandDetectionService — primary entry point
├── calibration/           # single + multi-ladder calibration
│   └── LadderCalibrationService, MultiLadderCalibrationService
├── densitometry/          # 10 files — Gaussian fitting + deconvolution + normalizer
│   └── DensitometryService — primary entry point
├── sam/                   # MobileSAM ONNX encoder + decoder
├── studio/                # template-learning UI for the admin
├── report/                # Word / Excel / PowerPoint exports (Phase 4)
├── file_handler.py        # upload pipeline (cv2 / tifffile / Pillow)
├── scn_parser.py          # Bio-Rad .scn format
└── template_learning.py   # learn ladder pattern from training calibrations
```

All services log via `phoresis_core.logging_config.get_logger(__name__)`.

## Celery tasks (9)

`tasks.py` exports:
- `detect_bands_lane_task`, `detect_bands_bulk_task`, `detect_bands_cv2_bulk_task`, `detect_bands_hybrid_bulk_task`
- `detect_peaks_profile_bulk_task` (DEPRECATED — kept for backward compat)
- `band_detection_ping_task`, `densitometry_ping_task`
- `run_densitometry_task`, `export_densitometry_csv_task`

All wrap `@robust_task(...)` from phoresis_core.

## URL surface

- `GET /images/`, `/images/upload/`, `/images/<uuid>/`, `/images/<uuid>/delete/`
- `GET /analyses/`, `/analyses/<uuid>/`, `/analyses/<uuid>/annotate/`, `/analyses/<uuid>/densitometry/`
- `GET /comparisons/`, `/comparisons/?lanes=<id1>,<id2>` or `?comparison=<uuid>`
- `POST /api/...` ~50 non-DRF JSON endpoints
- `/api/v1/...` 6 DRF ModelViewSets (Phase 4)

## ML models (108 MB, Git LFS)

`static/gel_analyzer/ml/`:
- `gel_analysis.onnx` (44 MB) — YOLO gel-type + lane/band detection
- `sam/mobile_sam.pt` (39 MB) + `sam/mobilesam_decoder.onnx` (16 MB) + `sam/mobilesam_decoder_quant.onnx` (8.5 MB)

## Integration notes

- `Lane.sample_metadata` is the extension point for analyzer-specific data — never break the existing schema; add fields here.
- `signals.py` is intentionally empty — see its docstring for how to reintroduce hooks if a future app adds a sample registry.
