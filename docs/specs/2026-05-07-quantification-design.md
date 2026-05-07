# Protein Quantification — Design

**Status:** draft (brainstorming output, awaiting implementation plan)
**Date:** 2026-05-07
**Branch:** `feat/quantification`
**Scope:** end-to-end protein quantification feature for the gel analyzer.

---

## 1. Goal

Enable users to quantify the protein of interest (POI) in sample lanes by:

1. Marking some lanes as **calibration standards** with known loaded amounts (µg or µg/mL).
2. Fitting a calibration curve (linear / polynomial-2 / 4-PL) from `corrected_area` vs `load_amount`.
3. Optionally validating the curve with **control lanes** of known amount (QC, not used in fit).
4. Projecting all sample bands onto the curve to obtain estimated concentrations / quantities.
5. Surfacing the results across the densitometry view, the comparison view, and Word/Excel/PowerPoint reports.

---

## 2. Constraints inherited from the codebase (must respect)

- `DensitometryResult.corrected_area` is the **single source of truth** for band area. The quantification service consumes it; it never re-implements integration. Recent fixes (`784c5c8` cache invalidation + Gaussian truncation, `77a848a` band split server-consistent) ensure split / edited bands propagate to all panels — quantification piggybacks on the same invalidation.
- AGENTS.md rules apply: no CDNs, multi-line Django comments use `{% comment %}`, `localStorage` access wrapped in `safeLocalGet`/`safeLocalSet`, PowerShell 5.1 only.
- App dependency direction (`gel_analyzer → phoresis_core, phoresis_ui, accounts`) is preserved.
- Existing MW calibration code (`services/calibration/`) stays behavioural-stable; only a small extraction of fit helpers is allowed.
- Pillow + python-docx + openpyxl + python-pptx remain the report stack — no Playwright (rejected previously, see memory `feedback_no_overengineering_reports`).

---

## 3. Decisions captured during brainstorming

| # | Topic | Decision |
|---|---|---|
| Q1 | Calibration granularity | One CALIBRATION lane carries one CALIBRATION band; the band holds `(load_amount, load_unit)`. |
| Q2 | Units | Homogeneous per calibration: either µg (mass) or µg/mL (concentration). User picks once, propagated. Optional `Lane.loading_volume_ul` to convert µg/mL → µg for sample reporting. |
| Q3 | Curve models | Linear, Polynomial-2, 4-Parameter Logistic (4PL). |
| Q4 | Controls semantics | QC only — projected onto the curve, never fitted. Recovery % displayed; out-of-spec highlighted. |
| Q5 | Calibration graph location | New tab in the chromatogram panel (`Chromatogram │ POI Purity │ Quantification curve`). Keeps the 4-panel layout. |
| Q6 | Color palette | CALIBRATION = `#8B5CF6` violet, CONTROL = `#06B6D4` cyan. Applied on badges, SVG outlines, table rows, plot markers. |
| Q7 | Type rollback (CALIBRATION/CONTROL → SAMPLE) | Confirmation modal + purge of `ProteinQuantCalibrationPoint`s if confirmed. |
| Q8 | Results table | Lane-level view by default, click-to-expand band drill-down, column groups (Identity / Densitometry / Quantification / Quality), contextual columns. |
| Q9 | Reports | Word, Excel, PowerPoint — section "Quantification" added when an active calibration exists. |
| Q10 | Comparison table | Reorganized: sticky `Lane# + Type`, column groups, quantification columns added, color rows by type. |
| Q11 | Calibration cardinality | One active per analysis + audit history (superseded records preserved). |
| Arch | Architecture approach | Mirror the `LadderCalibration` pattern (new model + new service in parallel; shared fit-math helpers). |

---

## 4. Data model

### 4.1 Modifications to existing models

**`Lane.LaneType`** — new value:
```python
CALIBRATION = "CALIBRATION", "Calibration Standard"
```

**`Band.BandType`** — new value:
```python
CALIBRATION = "CALIBRATION", "Calibration Point"
```

**`Lane`** — new optional field:
```python
loading_volume_ul = models.FloatField(
    null=True, blank=True,
    validators=[MinValueValidator(0)],
    help_text="Loading volume in µL (used to convert µg/mL → µg for samples)",
)
```

**`DensitometryResult`** — two new nullable fields:
```python
estimated_amount      = models.FloatField(null=True, blank=True)
estimated_amount_unit = models.CharField(max_length=10, blank=True)  # snapshot at fit time
```

`Lane.protein_load_ug` and `Lane.protein_load_type` are kept as-is for traceability of sample loading conditions; they no longer participate in calibration. Documented in `src/gel_analyzer/docs/README.md`.

### 4.2 New model — `ProteinQuantCalibrationPoint`

Lives in `src/gel_analyzer/models/quantification.py`. Parallel to `MWMarker`.

```python
class ProteinQuantCalibrationPoint(models.Model):
    band = models.OneToOneField(
        "Band",
        on_delete=models.CASCADE,
        related_name="quant_point",
        limit_choices_to={"band_type": "CALIBRATION"},
    )
    load_amount = models.FloatField(validators=[MinValueValidator(0)])
    load_unit   = models.CharField(max_length=10, choices=[("UG", "µg"), ("UG_ML", "µg/mL")])
    is_excluded_from_fit = models.BooleanField(default=False)
    role = models.CharField(
        max_length=20,
        choices=[("CALIBRATION", "Calibration"), ("CONTROL", "Control")],
        # role is derived from band.lane.lane_type at creation; persisted to support
        # historical audit even after a lane type change.
    )
    created_at = models.DateTimeField(auto_now_add=True)
```

### 4.3 New model — `ProteinQuantCalibration`

Lives in the same `quantification.py`. Parallel to `LadderCalibration`.

```python
class ProteinQuantCalibration(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis  = models.ForeignKey("GelAnalysis", on_delete=models.CASCADE,
                                  related_name="quant_calibrations")
    method    = models.CharField(max_length=20, choices=[
                    ("LINEAR", "Linear"),
                    ("POLYNOMIAL_2", "Polynomial (deg 2)"),
                    ("FOUR_PL", "4-Parameter Logistic"),
               ])
    unit      = models.CharField(max_length=10, choices=[("UG", "µg"), ("UG_ML", "µg/mL")])
    coefficients = models.JSONField()                 # {a,b} | {coeffs:[...]} | {a,b,c,d}
    r_squared    = models.FloatField()
    equation     = models.CharField(max_length=255)
    excluded_band_ids = models.JSONField(default=list)

    is_active        = models.BooleanField(default=True, db_index=True)
    superseded_at    = models.DateTimeField(null=True, blank=True)
    created_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                         null=True, blank=True,
                                         related_name="created_quant_calibrations")
    created_at       = models.DateTimeField(auto_now_add=True)
    notes            = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["analysis"],
                condition=models.Q(is_active=True),
                name="uniq_active_quant_calibration_per_analysis",
            ),
        ]
        indexes = [models.Index(fields=["analysis", "is_active"])]
```

### 4.4 Migration plan

Four migrations, all reversible (all new fields nullable):

1. `Lane.LaneType` choice + `Band.BandType` choice + `Lane.loading_volume_ul`.
2. Create `ProteinQuantCalibrationPoint`.
3. Create `ProteinQuantCalibration` (with the partial unique constraint).
4. `DensitometryResult.estimated_amount` + `.estimated_amount_unit`.

No backfill needed.

---

## 5. Services & calculation flow

### 5.1 New module `services/quantification/`

```
services/quantification/
├── __init__.py
├── models.py     # dataclasses: QuantParams, QuantPoint, QuantResult, QuantProjection
├── service.py    # ProteinQuantCalibrationService
└── fitters.py    # _fit_linear, _fit_polynomial_2, _fit_4pl
```

### 5.2 Shared fit helpers

Extract `_fit_log_linear` and `_fit_polynomial` from `services/calibration/service.py` into a new `services/calibration/fitters_shared.py`. Imported by both calibration services. Behaviour-preserving refactor; existing MW tests must remain green.

### 5.3 Service API

```python
class ProteinQuantCalibrationService:
    def __init__(self, params: QuantParams): ...

    # Read points (only those with DensitometryResult.corrected_area available)
    def collect_calibration_points(self, analysis) -> list[QuantPoint]: ...
    def collect_control_points(self, analysis)     -> list[QuantPoint]: ...

    # Fit
    def fit(self, points, excluded_band_ids=None) -> QuantResult: ...

    # Inverse transform: corrected_area → estimated_amount
    def project(self, area: float, result: QuantResult) -> float | None: ...

    # Persist + propagate
    def save_active(self, analysis, result, *, supersede_previous=True) -> ProteinQuantCalibration: ...
    def apply_to_analysis(self, calibration) -> int:
        """Persist DensitometryResult.estimated_amount{,_unit} for all SAMPLE/CONTROL bands.
        Returns count of bands updated."""
```

### 5.4 Cache invalidation hook

Wherever `784c5c8` invalidates the densitometry lane cache on band edits / splits, add a sibling call:
```python
quantification_signals.recompute_if_active(analysis)
```
which is a no-op if no active calibration exists, otherwise refits + reapplies. No new Django signal — direct hook at the existing invalidation point.

### 5.5 4PL convergence safeguards

- `len(non_excluded_points) >= 4` enforced (else `success=False` with explicit error).
- Initial guesses: `a=min(area), d=max(area), c=median(load), b=1.0`.
- `scipy.optimize.curve_fit(..., maxfev=5000)`. On failure, return failed `QuantResult` — no retry magic.

### 5.6 Sync execution

Linear / poly2 / 4PL on N≤20 points takes a few ms. Projection on a few hundred bands is fast. Everything synchronous in the request/response cycle. No new Celery task needed.

---

## 6. UI — Annotation

### 6.1 Properties Panel — lane

- Type dropdown gains `<option value="CALIBRATION">Calibration Standard</option>`.
- Type badge picks up CSS class `gv-prop-type-calibration` (violet) or `gv-prop-type-control` (cyan; verified/added if missing).
- When `lane_type ∈ {CALIBRATION, CONTROL}`: hide `Load type` + `Load (µg)` fields (those are now band-level). Show optional `Loading volume (µL)` field bound to `Lane.loading_volume_ul`.
- When the user changes a CALIBRATION/CONTROL lane to anything else and the lane has dependent points: show a **confirmation modal** "Cette lane contient N point(s) de calibration. Changer son type supprimera leurs valeurs. Continuer ?". On confirm, PATCH with `?force=true`.

### 6.2 Properties Panel — band

- Type dropdown gains `<option value="CALIBRATION">Calibration Point</option>`.
- When `band_type === 'CALIBRATION'`: new "Calibration" section appears with:
  - `Loaded amount` numeric input (`step=0.01`, `min>0`).
  - `Unit` select `[µg, µg/mL]`. Locked (read-only with info tooltip) once an active calibration exists in the analysis — the calibration is the source of truth for the unit.
  - Densitometry availability indicator: ✓ green if `band.densitometry.corrected_area` is set, ⚠ orange tooltip "Run densitometry to use this point" otherwise.

### 6.3 Context menu

- Lane Type submenu adds `Calibration`.
- Band Type submenu adds `Calibration`.
- New entry `Set concentration…` (next to `Set MW…`), visible only when `band.band_type === 'CALIBRATION'`. Prompts for amount + unit; persists via the same PATCH `/api/bands/<id>/`. Refactor opportunity: extract `prompt(...)` helper to `promptAmount(band, unit, onUpdate)` for reuse.

### 6.4 Color tokens (CSS)

```css
.gv-prop-type-calibration       { background: #8B5CF6; color: white; }
.gv-prop-type-control           { background: #06B6D4; color: white; }
.gv-band-type-calibration       { color: #8B5CF6; }
.gv-lane-overlay--calibration   { stroke: #8B5CF6; fill: rgba(139,92,246,.08); }
.gv-lane-overlay--control       { stroke: #06B6D4; fill: rgba(  6,182,212,.08); }
```

The SVG renderer's stroke/fill picker is extended for the two new lane types.

---

## 7. UI — Densitometry

### 7.1 Quantification calibration modal

Sibling to the MW calibration modal, two-column layout:

```
┌─ Quantification calibration ─────────────────────────────────┐
│ Method: [Linear ▼]   Unit: [µg ▼]   ☐ Show controls overlay  │
│                                                              │
│ ┌────────────────────────┐  ┌─────────────────────────────┐  │
│ │  CALIBRATION POINTS    │  │   CALIBRATION CURVE         │  │
│ │  (table + ✗ checkbox)  │  │   (curve + points + samples)│  │
│ │  R²= ...  N= ...       │  │                             │  │
│ │  Eq: y = ...           │  │                             │  │
│ └────────────────────────┘  └─────────────────────────────┘  │
│ ┌────────────────────────┐  ┌─────────────────────────────┐  │
│ │  CONTROLS / QC         │  │   SAMPLES PROJECTED         │  │
│ │  (known, predicted,    │  │   (lane, area, est.amount)  │  │
│ │   recovery%, ⚠ if oos) │  │                             │  │
│ └────────────────────────┘  └─────────────────────────────┘  │
│                  [Cancel]   [Refit]   [Save & apply]         │
└──────────────────────────────────────────────────────────────┘
```

- Per-point exclusion via checkbox; refit debounced 200 ms. Excluded points stay visible as ghost markers (opacity 0.3) — same UX as the MW modal.
- Method change → refit. Unit change → confirmation modal if any points already entered (no auto-conversion; reset to avoid silent bugs); warn if existing samples will be re-projected.
- Controls out-of-spec threshold: %recovery outside `[80, 120]` highlighted red + ⚠.
- Save & apply: atomic transaction — POST creates new `is_active=True` record, marks the previous one `is_active=False, superseded_at=now()`, calls `apply_to_analysis`. Background panels refresh via `Events.QUANT_CALIBRATION_CHANGED`.
- Refit = preview (no persist). Save = new active version.

### 7.2 Chromatogram panel — tabs

```
[ Chromatogram │ POI Purity │ Quantification curve ]
```

- Active tab persisted in `localStorage` via `safeLocalGet/safeLocalSet` (key `phoresis.densito.chromatogramTab`).
- Quantification curve tab is read-only, shows fit-points (violet), controls (cyan), samples (grey crosses), equation, R², N. Click on a point selects the corresponding lane in the viewer.
- Empty state: "No active quantification calibration. Open Quantification modal to set up."

### 7.3 Results table refactor

One row per lane (was: one per band). Click expands inline a band-level sub-table.

| Section | Columns | Visible when |
|---|---|---|
| Identity | Lane#, Type (badge), Sample name | always |
| Densitometry | Total area, # bands, POI area, % purity | always |
| Quantification | Estimated amount + unit, Recovery % | active calib OR lane=CONTROL |
| Quality | Fit R² avg, Outlier? icon | always |

Sticky-left columns: `Lane#` + `Type`. Row backgrounds tinted by lane type (consistent with viewer palette). Column preset (minimal / standard / full) persisted in `localStorage`.

---

## 8. API REST

### 8.1 Modified existing endpoints

| Endpoint | Change |
|---|---|
| `PATCH /api/lanes/<id>/` | Accepts `lane_type=CALIBRATION`, `loading_volume_ul`. Downgrade away from CALIBRATION/CONTROL with dependent points returns `409 Conflict {detail, dependent_band_ids}` unless `?force=true`. With `?force=true`, deletes dependent `ProteinQuantCalibrationPoint`s in a transaction. |
| `PATCH /api/bands/<id>/` | Accepts `band_type=CALIBRATION` + nested `quant_point: {load_amount, load_unit}`. Validates: nested completeness when `band_type=CALIBRATION`, unit consistency with active calibration, parent lane type ∈ {CALIBRATION, CONTROL}. |
| `GET /api/analyses/<id>/densitometry/results/` | Band serialization gains `estimated_amount` + `estimated_amount_unit`. |

### 8.2 New endpoints

```
GET   /api/analyses/<analysis_id>/quantification/                 # active calib (or null) + points + controls
POST  /api/analyses/<analysis_id>/quantification/preview/         # dry-run fit, no persist
POST  /api/analyses/<analysis_id>/quantification/                 # create + apply (Save & apply)
PATCH /api/analyses/<analysis_id>/quantification/<calib_id>/      # toggle excluded_band_ids, notes
DELETE /api/analyses/<analysis_id>/quantification/<calib_id>/     # deactivate (is_active=False, superseded_at=now)
GET   /api/analyses/<analysis_id>/quantification/history/         # audit history
```

### 8.3 Preview / save payload shape

```jsonc
// POST /preview/
{
  "method": "LINEAR" | "POLYNOMIAL_2" | "FOUR_PL",
  "unit": "UG" | "UG_ML",
  "excluded_band_ids": ["uuid", ...]
}

// → 200
{
  "success": true,
  "method": "LINEAR",
  "unit": "UG",
  "coefficients": {"a": 0.0021, "b": 0.43},
  "r_squared": 0.9987,
  "equation": "y = 0.0021·area + 0.43",
  "calibration_points": [...],   // band_id, lane_number, load_amount, corrected_area,
                                 // predicted_amount, residual_pct, is_excluded
  "control_points":     [...],   // band_id, lane_number, known_amount, predicted_amount,
                                 // recovery_pct, out_of_spec
  "sample_projections": [...],   // band_id, lane_number, corrected_area, estimated_amount
  "warnings": [],
  "error_message": null
}
```

`POST /quantification/` accepts the same body plus optional `notes`. Response: the saved `ProteinQuantCalibration`. Transactional (`with transaction.atomic()`).

### 8.4 Validation rules

- `method == "FOUR_PL"` → `len(non_excluded_points) >= 4`, else 400.
- All non-excluded `quant_point.load_unit` consistent with the request `unit`, else 400 listing the offending bands.
- All `excluded_band_ids` reference bands of CALIBRATION lanes of this analysis.
- `corrected_area` must exist on every retained point — else `422 {detail, missing: [band_ids]}`.

### 8.5 Throttling / permissions

Reuse existing `throttles.py` and DRF permissions. No new permission scope.

---

## 9. Reports

### 9.1 Word

New section "6. Quantification" added when the analysis has an active calibration, with sub-sections:

- 6.1 Calibration table (Lane, Load, Area, Residual %, Excluded?) + Method / Unit / Equation / R² / N.
- 6.2 Calibration curve PNG (via new `services/report/quantification_chart.py`, Pillow + matplotlib).
- 6.3 Quality controls table (Lane, Known, Predicted, %Recovery, In/Out of spec).
- 6.4 Sample quantification table (Lane, Sample, Area, Estimated amount + unit).

### 9.2 Excel

Three new sheets:

- `Quantification_Calibration` — fit metadata + per-point rows.
- `Quantification_Controls` — per-control rows with recovery%.
- `Quantification_Samples` — per-sample-band rows.

Snapshot values, no live formulas. Audit history available via `GET /quantification/history/`.

### 9.3 PowerPoint

One new slide after POI Purity:

- Calibration curve PNG (reused from Word).
- KPI box: R², N, mean recovery%.
- Mini sample table (top 8).

### 9.4 Data collector

New method `collect_quantification_data(analysis) → QuantReportData` on `densitometry_data_collector.py`. Returned struct consumed by all 3 builders. PNG generated once, cached in-memory, reused.

---

## 10. Comparison view

Reorganize `comparisons/compare.html` table:

- Sticky-left: `Lane#` + `Type` (color badge).
- Column groups via `<th colspan>` headers:
  - Identity: Sample name, Condition, Loading volume.
  - Densitometry: Total area, # bands, POI area, % purity.
  - Quantification (hidden if no compared analysis has an active calibration): Estimated amount + unit, %recovery (CONTROL), Calib unit/method.
  - Quality: Fit R² avg, # MW markers, status icon.
- Row backgrounds tinted by lane type (consistent across views).
- "Show only quantified lanes" client-side filter toggle.
- Column preset persisted via `safeLocalSet`.

No new endpoint; band serializer extension from §8.1 covers the data needs.

---

## 11. Tests

- `services/quantification/test_fitters.py` — linear / poly2 / 4PL on synthetic datasets; R²=1.0 on perfect inputs; outlier exclusion; 4PL convergence guarded ≥4 points.
- `services/quantification/test_service.py` — collect ignores bands without densitometry; `apply_to_analysis` updates only SAMPLE/CONTROL bands; recompute triggered by densitometry invalidation.
- `tests/test_api_quantification.py` — preview/save flows, lane downgrade with/without `?force=true`, unit cross-validation, 422 on missing densitometry.
- Integration: 4 calibration + 2 control + 3 sample lanes, mocked densitometry, fit, verify `DensitometryResult.estimated_amount` propagated; split a calibration band, verify auto-refit.
- No new Playwright e2e (per `feedback_no_overengineering_reports`).
- Existing scipy 1.14 + `BandDetectionParams` xfails untouched.

---

## 12. Out of scope (explicit non-goals)

- Multi-protein-per-analysis quantification (multiple parallel calibrations) — single calibration per analysis, as decided in Q11.
- Auto-detection of calibration lanes — user marks them explicitly.
- Conversion between µg and µg/mL across calibration points — homogeneous unit per calibration, by design.
- Uncertainty propagation / confidence intervals on estimated amounts — possible follow-up.
- Splitting `properties-panel.js` (885 lines) or `densitometry.html` (2140 lines) — recognized debt, not in this feature's scope.

---

## 13. Implementation order (high level)

1. Migrations + models + admin registrations.
2. Shared fit helpers extraction + `ProteinQuantCalibrationService` + unit tests.
3. API endpoints + serializers + API tests.
4. UI Annotation: Properties Panel + Context menu + CSS color tokens.
5. UI Densitometry: quantification calibration modal.
6. UI Densitometry: chromatogram tab + results table refactor.
7. UI Comparison: table refactor.
8. Reports: data collector + chart helper + 3 builders.
9. Manual end-to-end smoke test (annotate → densitometry → calibrate → reports) with screenshots of all three report formats. Cross-view consistency check (colors, badges, ordering).

The detailed plan with file-level steps and acceptance gates is produced separately by the writing-plans skill after this design is approved.
