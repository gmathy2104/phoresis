# Quantification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add end-to-end protein quantification (CALIBRATION lanes/bands, fit linear/poly2/4PL curves, project samples, surface in densito + comparison + reports).

**Architecture:** Mirror the existing `LadderCalibration` pattern. New models `ProteinQuantCalibration` + `ProteinQuantCalibrationPoint` parallel to `LadderCalibration` + `MWMarker`. New service `services/quantification/` parallel to `services/calibration/`, with shared fit-math helpers. UI extends Properties Panel + Context menu, adds a calibration modal, adds a tab to the chromatogram panel, refactors the results table to lane-level + drill-down. Reports gain a "Quantification" section in Word/Excel/PowerPoint.

**Tech Stack:** Django 5.2 + DRF, Celery (no new tasks needed), scipy.optimize.curve_fit (4PL), Pillow + matplotlib + python-docx + openpyxl + python-pptx for reports, vanilla JS + Alpine + HTMX + SVG.js for UI (no new deps).

**Spec:** `docs/specs/2026-05-07-quantification-design.md` (read this before starting any task).

**Branch:** `feat/quantification` (already created, has the densitometry fix `784c5c8` as base).

---

## File structure (mapping)

### Backend — Create

```
src/gel_analyzer/models/quantification.py                        # ProteinQuantCalibration + Point
src/gel_analyzer/services/calibration/fitters_shared.py          # log-linear + polynomial extracted
src/gel_analyzer/services/quantification/__init__.py
src/gel_analyzer/services/quantification/models.py               # QuantParams, QuantPoint, QuantResult
src/gel_analyzer/services/quantification/fitters.py              # _fit_linear, _fit_polynomial_2, _fit_4pl
src/gel_analyzer/services/quantification/service.py              # ProteinQuantCalibrationService
src/gel_analyzer/services/quantification/invalidation.py         # recompute_if_active hook
src/gel_analyzer/services/report/quantification_chart.py         # PNG calibration curve
src/gel_analyzer/migrations/<NN>_quantification_models.py        # 4 migrations (or one combined)
src/gel_analyzer/tests/test_models/test_quantification.py
src/gel_analyzer/tests/test_services/test_quantification_fitters.py
src/gel_analyzer/tests/test_services/test_quantification_service.py
src/gel_analyzer/tests/test_services/test_quantification_invalidation.py
src/gel_analyzer/tests/test_views/test_api_quantification.py
src/gel_analyzer/tests/test_quantification_integration.py
```

### Backend — Modify

```
src/gel_analyzer/models/__init__.py                              # re-export new models
src/gel_analyzer/models/annotations.py                           # +CALIBRATION choices, +loading_volume_ul
src/gel_analyzer/models/densitometry.py                          # +estimated_amount fields
src/gel_analyzer/admin.py                                        # register new models
src/gel_analyzer/services/calibration/service.py                 # delegate to fitters_shared
src/gel_analyzer/api/serializers.py                              # +loading_volume_ul, +quant_point, +estimated_amount
src/gel_analyzer/api/views.py                                    # +6 quantification endpoints, lane downgrade
src/gel_analyzer/api/urls.py                                     # wire new routes
src/gel_analyzer/tasks.py                                        # call recompute_if_active at end of run_densitometry_task
src/gel_analyzer/services/report/densitometry_data_collector.py  # +collect_quantification_data
src/gel_analyzer/services/report/densitometry_builder.py         # +Quantification section (Word)
src/gel_analyzer/services/report/densitometry_excel_builder.py   # +3 sheets
src/gel_analyzer/services/report/densitometry_pptx_builder.py    # +Quantification slide
src/gel_analyzer/services/report/comparison_builder.py           # color rows + quantification cols
src/gel_analyzer/docs/README.md                                  # short note about CALIBRATION
```

### Frontend — Create

```
src/gel_analyzer/static/gel_analyzer/css/quantification.css                          # color tokens (or extend existing)
src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/quantification-modal.js  # modal class
src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/quantification-curve-tab.js
src/gel_analyzer/templates/gel_analyzer/includes/_quantification_modal.html          # modal markup
```

### Frontend — Modify

```
src/gel_analyzer/static/gel_analyzer/js/gel-viewer/panels/properties-panel.js
src/gel_analyzer/static/gel_analyzer/js/gel-viewer/panels/context-menu.js
src/gel_analyzer/static/gel_analyzer/js/gel-viewer/renderer.js                       # SVG lane overlay color picker
src/gel_analyzer/static/gel_analyzer/js/densitometry/densitometry-event-bus.js       # +QUANT_CALIBRATION_CHANGED
src/gel_analyzer/static/gel_analyzer/js/densitometry/densitometry-app.js
src/gel_analyzer/static/gel_analyzer/js/densitometry/densitometry-api-client.js      # quantification calls
src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/chromatogram-panel.js    # tabs
src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/results-table-panel.js   # lane-level refactor
src/gel_analyzer/static/gel_analyzer/js/sample-comparison/sample-comparison-app.js   # column groups
src/gel_analyzer/templates/gel_analyzer/analyses/annotate_standalone.html            # context menu items
src/gel_analyzer/templates/gel_analyzer/analyses/densitometry.html                   # modal include + tabs
src/gel_analyzer/templates/gel_analyzer/comparisons/compare.html                     # comparison table
```

---

## Phase 1 — Models & Migrations

### Task 1.1: Add CALIBRATION to `Lane.LaneType` + tests

**Files:**
- Modify: `src/gel_analyzer/models/annotations.py:20-27`
- Modify: `src/gel_analyzer/tests/test_models/test_annotations.py:32-37`

- [ ] **Step 1: Add the failing assertion**

In `src/gel_analyzer/tests/test_models/test_annotations.py`, extend `test_lane_type_choices`:
```python
def test_lane_type_choices(self):
    """Test lane type choices are valid."""
    assert Lane.LaneType.SAMPLE == "SAMPLE"
    assert Lane.LaneType.LADDER == "LADDER"
    assert Lane.LaneType.EMPTY == "EMPTY"
    assert Lane.LaneType.CONTROL == "CONTROL"
    assert Lane.LaneType.DOT == "DOT"
    assert Lane.LaneType.CALIBRATION == "CALIBRATION"
```

- [ ] **Step 2: Run test, verify it fails**

```
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest src/gel_analyzer/tests/test_models/test_annotations.py::TestLane::test_lane_type_choices -v
```
Expected: FAIL `AttributeError: type object 'LaneType' has no attribute 'CALIBRATION'`.

- [ ] **Step 3: Add the choice**

In `src/gel_analyzer/models/annotations.py`, inside `Lane.LaneType` (after the `DOT` line):
```python
        CALIBRATION = "CALIBRATION", "Calibration Standard"
```

- [ ] **Step 4: Run test, verify it passes**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gel_analyzer/models/annotations.py src/gel_analyzer/tests/test_models/test_annotations.py
git commit -m "feat(models): add CALIBRATION to Lane.LaneType"
```

---

### Task 1.2: Add CALIBRATION to `Band.BandType` + tests

**Files:**
- Modify: `src/gel_analyzer/models/annotations.py:215-220`
- Modify: `src/gel_analyzer/tests/test_models/test_annotations.py` (find the `test_band_type_choices` if exists; otherwise add one)

- [ ] **Step 1: Add (or extend) the test**

```python
def test_band_type_choices(self):
    assert Band.BandType.MW_REFERENCE == "MW_REFERENCE"
    assert Band.BandType.POI == "POI"
    assert Band.BandType.OTHER == "OTHER"
    assert Band.BandType.CALIBRATION == "CALIBRATION"
```
Add to `TestBand` class (search for the class declaration; if not present, add a new minimal test class).

- [ ] **Step 2: Run test, verify it fails**

```
... -m pytest src/gel_analyzer/tests/test_models/test_annotations.py -k band_type_choices -v
```
Expected: FAIL.

- [ ] **Step 3: Add the choice**

In `src/gel_analyzer/models/annotations.py`, inside `Band.BandType`:
```python
        CALIBRATION = "CALIBRATION", "Calibration Point"
```

- [ ] **Step 4: Run test, verify it passes**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(models): add CALIBRATION to Band.BandType"
```

---

### Task 1.3: Add `Lane.loading_volume_ul` field

**Files:**
- Modify: `src/gel_analyzer/models/annotations.py` (Lane model, after `protein_load_type`)
- Test: `src/gel_analyzer/tests/test_models/test_annotations.py` (TestLane class)

- [ ] **Step 1: Write the failing test**

```python
def test_loading_volume_ul_optional(self, sample_lane):
    """loading_volume_ul is optional and stores µL."""
    assert sample_lane.loading_volume_ul is None
    sample_lane.loading_volume_ul = 12.5
    sample_lane.save()
    sample_lane.refresh_from_db()
    assert sample_lane.loading_volume_ul == 12.5

def test_loading_volume_ul_rejects_negative(self, sample_lane):
    from django.core.exceptions import ValidationError
    sample_lane.loading_volume_ul = -1.0
    with pytest.raises(ValidationError):
        sample_lane.full_clean()
```

- [ ] **Step 2: Run, verify failure** — `... -m pytest src/gel_analyzer/tests/test_models/test_annotations.py -k loading_volume_ul -v`. Expected: FAIL `AttributeError`.

- [ ] **Step 3: Add the field**

In `Lane` model, after the `protein_load_type` field:
```python
    loading_volume_ul = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Loading volume in µL (used to convert µg/mL → µg for samples)",
    )
```

- [ ] **Step 4: Generate migration**

```
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py makemigrations gel_analyzer --name add_loading_volume_ul
```

- [ ] **Step 5: Apply + run test**

```
... manage.py migrate
... -m pytest src/gel_analyzer/tests/test_models/test_annotations.py -k loading_volume_ul -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gel_analyzer/models/annotations.py src/gel_analyzer/migrations/ src/gel_analyzer/tests/test_models/test_annotations.py
git commit -m "feat(models): add Lane.loading_volume_ul"
```

---

### Task 1.4: Combined migration for the two new choices

The choice additions in 1.1 and 1.2 require a migration too (TextChoices changes the `choices` tuple Django stores).

- [ ] **Step 1: Generate migration**

```
... manage.py makemigrations gel_analyzer --name add_calibration_choices
```

- [ ] **Step 2: Verify the migration only touches `choices`** (no field-type churn). Inspect the generated file. If it touches more fields than `Lane.lane_type` and `Band.band_type`, abort and investigate.

- [ ] **Step 3: Apply**

```
... manage.py migrate
```

- [ ] **Step 4: Commit**

```bash
git add src/gel_analyzer/migrations/
git commit -m "feat(models): migration for CALIBRATION choices"
```

---

### Task 1.5: Create `ProteinQuantCalibrationPoint` model

**Files:**
- Create: `src/gel_analyzer/models/quantification.py`
- Modify: `src/gel_analyzer/models/__init__.py` (re-export)
- Test: `src/gel_analyzer/tests/test_models/test_quantification.py` (new)

- [ ] **Step 1: Write the failing test**

`src/gel_analyzer/tests/test_models/test_quantification.py`:
```python
"""Tests for ProteinQuantCalibrationPoint model."""
import pytest
from django.core.exceptions import ValidationError

from gel_analyzer.models import Band, Lane, ProteinQuantCalibrationPoint

pytestmark = pytest.mark.django_db


@pytest.fixture
def calibration_lane(sample_analysis, test_user):
    return Lane.objects.create(
        analysis=sample_analysis,
        lane_number=99,
        lane_type=Lane.LaneType.CALIBRATION,
        x=10, y=10, width=50, height=200,
    )


@pytest.fixture
def calibration_band(calibration_lane, test_user):
    return Band.objects.create(
        lane=calibration_lane,
        band_type=Band.BandType.CALIBRATION,
        position_y=100,
        bbox_x=10, bbox_y=90, bbox_width=50, bbox_height=20,
        created_by=test_user,
        detection_source=Band.DetectionSource.MANUAL,
    )


class TestProteinQuantCalibrationPoint:
    def test_create_with_valid_data(self, calibration_band):
        point = ProteinQuantCalibrationPoint.objects.create(
            band=calibration_band,
            load_amount=10.0,
            load_unit="UG",
        )
        assert point.role == "CALIBRATION"  # default
        assert point.is_excluded_from_fit is False
        assert point.load_amount == 10.0

    def test_load_amount_rejects_negative(self, calibration_band):
        point = ProteinQuantCalibrationPoint(
            band=calibration_band, load_amount=-1.0, load_unit="UG"
        )
        with pytest.raises(ValidationError):
            point.full_clean()

    def test_one_to_one_with_band(self, calibration_band):
        ProteinQuantCalibrationPoint.objects.create(
            band=calibration_band, load_amount=10.0, load_unit="UG"
        )
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            ProteinQuantCalibrationPoint.objects.create(
                band=calibration_band, load_amount=20.0, load_unit="UG"
            )
```

- [ ] **Step 2: Run, verify failure** — `... -m pytest src/gel_analyzer/tests/test_models/test_quantification.py -v`. Expected: ImportError on `ProteinQuantCalibrationPoint`.

- [ ] **Step 3: Create the model file**

`src/gel_analyzer/models/quantification.py`:
```python
"""Protein quantification models — one ProteinQuantCalibration per analysis +
calibration / control points anchored on Band rows."""

import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class ProteinQuantCalibrationPoint(models.Model):
    """A single calibration or control point — load amount declared by the user
    on a CALIBRATION-typed Band. The calibration role is derived from the parent
    lane's type (CALIBRATION vs CONTROL) and persisted for audit."""

    UNIT_UG = "UG"
    UNIT_UG_ML = "UG_ML"
    UNIT_CHOICES = [(UNIT_UG, "µg"), (UNIT_UG_ML, "µg/mL")]

    ROLE_CALIBRATION = "CALIBRATION"
    ROLE_CONTROL = "CONTROL"
    ROLE_CHOICES = [(ROLE_CALIBRATION, "Calibration"), (ROLE_CONTROL, "Control")]

    band = models.OneToOneField(
        "Band",
        on_delete=models.CASCADE,
        related_name="quant_point",
        limit_choices_to={"band_type": "CALIBRATION"},
    )
    load_amount = models.FloatField(validators=[MinValueValidator(0)])
    load_unit = models.CharField(max_length=10, choices=UNIT_CHOICES)
    is_excluded_from_fit = models.BooleanField(default=False)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CALIBRATION,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quantification Point"
        verbose_name_plural = "09. Quantification Points"
        indexes = [models.Index(fields=["role"])]

    def __str__(self) -> str:
        return f"{self.role} point: {self.load_amount} {self.load_unit}"
```

- [ ] **Step 4: Re-export**

In `src/gel_analyzer/models/__init__.py` add:
```python
from .quantification import ProteinQuantCalibrationPoint  # noqa: F401
```
(Keep alphabetical / convention with the existing imports.)

- [ ] **Step 5: Migration**

```
... manage.py makemigrations gel_analyzer --name add_quant_calibration_point
... manage.py migrate
```

- [ ] **Step 6: Run tests**

```
... -m pytest src/gel_analyzer/tests/test_models/test_quantification.py -v
```
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gel_analyzer/models/ src/gel_analyzer/migrations/ src/gel_analyzer/tests/test_models/test_quantification.py
git commit -m "feat(models): add ProteinQuantCalibrationPoint"
```

---

### Task 1.6: Create `ProteinQuantCalibration` model with partial unique constraint

**Files:**
- Modify: `src/gel_analyzer/models/quantification.py`
- Modify: `src/gel_analyzer/models/__init__.py`
- Test: `src/gel_analyzer/tests/test_models/test_quantification.py`

- [ ] **Step 1: Write failing tests**

Append to `test_quantification.py`:
```python
class TestProteinQuantCalibration:
    def test_create_active(self, sample_analysis, test_user):
        from gel_analyzer.models import ProteinQuantCalibration
        calib = ProteinQuantCalibration.objects.create(
            analysis=sample_analysis,
            method="LINEAR",
            unit="UG",
            coefficients={"a": 0.0021, "b": 0.43},
            r_squared=0.98,
            equation="y = 0.0021·area + 0.43",
            created_by=test_user,
        )
        assert calib.is_active is True
        assert calib.superseded_at is None

    def test_only_one_active_per_analysis(self, sample_analysis, test_user):
        from gel_analyzer.models import ProteinQuantCalibration
        from django.db import IntegrityError
        ProteinQuantCalibration.objects.create(
            analysis=sample_analysis, method="LINEAR", unit="UG",
            coefficients={"a": 1, "b": 0}, r_squared=0.99, equation="y=x",
            created_by=test_user,
        )
        with pytest.raises(IntegrityError):
            ProteinQuantCalibration.objects.create(
                analysis=sample_analysis, method="LINEAR", unit="UG",
                coefficients={"a": 2, "b": 0}, r_squared=0.99, equation="y=2x",
                created_by=test_user, is_active=True,
            )

    def test_superseded_allows_new_active(self, sample_analysis, test_user):
        """When the previous one is marked is_active=False, a new active is allowed."""
        from gel_analyzer.models import ProteinQuantCalibration
        from django.utils import timezone
        old = ProteinQuantCalibration.objects.create(
            analysis=sample_analysis, method="LINEAR", unit="UG",
            coefficients={"a": 1, "b": 0}, r_squared=0.99, equation="y=x",
            created_by=test_user,
        )
        old.is_active = False
        old.superseded_at = timezone.now()
        old.save()
        new = ProteinQuantCalibration.objects.create(
            analysis=sample_analysis, method="LINEAR", unit="UG",
            coefficients={"a": 2, "b": 0}, r_squared=0.99, equation="y=2x",
            created_by=test_user,
        )
        assert new.is_active is True
```

- [ ] **Step 2: Run, verify failure** — ImportError on `ProteinQuantCalibration`.

- [ ] **Step 3: Add the model**

Append to `src/gel_analyzer/models/quantification.py`:
```python
class ProteinQuantCalibration(models.Model):
    """One active protein quantification calibration per analysis. Older fits are
    kept with is_active=False, superseded_at=now() for audit."""

    METHOD_LINEAR = "LINEAR"
    METHOD_POLY2 = "POLYNOMIAL_2"
    METHOD_4PL = "FOUR_PL"
    METHOD_CHOICES = [
        (METHOD_LINEAR, "Linear"),
        (METHOD_POLY2, "Polynomial (deg 2)"),
        (METHOD_4PL, "4-Parameter Logistic"),
    ]

    UNIT_UG = "UG"
    UNIT_UG_ML = "UG_ML"
    UNIT_CHOICES = [(UNIT_UG, "µg"), (UNIT_UG_ML, "µg/mL")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey(
        "GelAnalysis", on_delete=models.CASCADE, related_name="quant_calibrations"
    )
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES)
    coefficients = models.JSONField()
    r_squared = models.FloatField()
    equation = models.CharField(max_length=255)
    excluded_band_ids = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_quant_calibrations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Protein Quantification Calibration"
        verbose_name_plural = "10. Protein Quantification Calibrations"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["analysis"],
                condition=models.Q(is_active=True),
                name="uniq_active_quant_calibration_per_analysis",
            ),
        ]
        indexes = [models.Index(fields=["analysis", "is_active"])]

    def __str__(self) -> str:
        flag = "active" if self.is_active else "superseded"
        return f"{self.method} calib ({flag}) — analysis {self.analysis_id}"
```

- [ ] **Step 4: Re-export in `__init__.py`**

```python
from .quantification import ProteinQuantCalibration, ProteinQuantCalibrationPoint  # noqa: F401
```

- [ ] **Step 5: Migration**

```
... manage.py makemigrations gel_analyzer --name add_protein_quant_calibration
... manage.py migrate
```

- [ ] **Step 6: Run tests**

`... -m pytest src/gel_analyzer/tests/test_models/test_quantification.py -v` → all PASS.

- [ ] **Step 7: Commit**

```bash
git commit -am "feat(models): add ProteinQuantCalibration with partial unique constraint"
```

---

### Task 1.7: Add `DensitometryResult.estimated_amount` fields

**Files:**
- Modify: `src/gel_analyzer/models/densitometry.py:62-63`
- Test: `src/gel_analyzer/tests/test_models/test_quantification.py`

- [ ] **Step 1: Write failing test**

Append to `test_quantification.py`:
```python
class TestDensitometryResultEstimatedAmount:
    def test_fields_default_null(self, sample_band, test_user):
        from gel_analyzer.models import DensitometryResult
        dr = DensitometryResult.objects.create(
            band=sample_band, peak_center_y=100, peak_amplitude=50,
            peak_sigma=5, fwhm=11.77, integrated_area=500,
            corrected_area=500, fit_r_squared=0.99, snr=20,
        )
        assert dr.estimated_amount is None
        assert dr.estimated_amount_unit == ""

    def test_can_persist_estimated_amount(self, sample_band, test_user):
        from gel_analyzer.models import DensitometryResult
        dr = DensitometryResult.objects.create(
            band=sample_band, peak_center_y=100, peak_amplitude=50,
            peak_sigma=5, fwhm=11.77, integrated_area=500,
            corrected_area=500, fit_r_squared=0.99, snr=20,
            estimated_amount=12.3, estimated_amount_unit="UG",
        )
        dr.refresh_from_db()
        assert dr.estimated_amount == 12.3
        assert dr.estimated_amount_unit == "UG"
```

- [ ] **Step 2: Run, expect FAIL** (TypeError unexpected kwarg).

- [ ] **Step 3: Add the fields**

In `src/gel_analyzer/models/densitometry.py`, append to `DensitometryResult` (just before `class Meta`):
```python
    # Quantification (computed from active ProteinQuantCalibration; null until calibrated)
    estimated_amount = models.FloatField(
        null=True, blank=True,
        help_text="Predicted protein amount via active quantification calibration",
    )
    estimated_amount_unit = models.CharField(
        max_length=10, blank=True,
        help_text="Unit snapshot at fit time (UG or UG_ML)",
    )
```

- [ ] **Step 4: Migration**

```
... manage.py makemigrations gel_analyzer --name add_densitometry_estimated_amount
... manage.py migrate
```

- [ ] **Step 5: Run tests** — `... -m pytest src/gel_analyzer/tests/test_models/test_quantification.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(models): add DensitometryResult.estimated_amount{,_unit}"
```

---

### Task 1.8: Admin registrations

**Files:**
- Modify: `src/gel_analyzer/admin.py`

- [ ] **Step 1: Read current admin.py to understand the registration style** (`Read src/gel_analyzer/admin.py`).

- [ ] **Step 2: Register both new models**

Append at the end of `admin.py`:
```python
from gel_analyzer.models import ProteinQuantCalibration, ProteinQuantCalibrationPoint


@admin.register(ProteinQuantCalibration)
class ProteinQuantCalibrationAdmin(admin.ModelAdmin):
    list_display = ("id", "analysis", "method", "unit", "r_squared", "is_active", "created_at")
    list_filter = ("method", "unit", "is_active")
    search_fields = ("analysis__id",)
    readonly_fields = ("id", "created_at", "superseded_at")


@admin.register(ProteinQuantCalibrationPoint)
class ProteinQuantCalibrationPointAdmin(admin.ModelAdmin):
    list_display = ("band", "load_amount", "load_unit", "role", "is_excluded_from_fit", "created_at")
    list_filter = ("role", "load_unit", "is_excluded_from_fit")
    search_fields = ("band__id",)
    readonly_fields = ("created_at",)
```

- [ ] **Step 3: Smoke check** — `... manage.py check` (no errors).

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(admin): register quantification models"
```

---

### Task 1.9: Document the kept-for-traceability fields

**Files:**
- Modify: `src/gel_analyzer/docs/README.md`

- [ ] **Step 1: Add a short section after the Models table**

```markdown
## Quantification (added 2026-05-07)

`ProteinQuantCalibration` (one active per analysis) + `ProteinQuantCalibrationPoint`
mirror the `LadderCalibration` / `MWMarker` pattern. CALIBRATION lanes carry one
CALIBRATION-typed band whose `quant_point` declares the loaded amount. CONTROL
lanes use the same band/point pair but the `role` field is set to CONTROL — they
are projected onto the curve for QC, never fitted.

`Lane.protein_load_ug` and `Lane.protein_load_type` are kept as-is for sample
loading-condition traceability; they no longer feed the calibration. Use
`Band.quant_point.load_amount` for calibration math.
```

- [ ] **Step 2: Commit**

```bash
git commit -am "docs(gel_analyzer): note quantification model addition"
```

---

## Phase 2 — Shared fitters extraction

### Task 2.1: Create `fitters_shared.py` with extracted helpers (behaviour-preserving)

**Files:**
- Create: `src/gel_analyzer/services/calibration/fitters_shared.py`
- Modify: `src/gel_analyzer/services/calibration/service.py:604-728`

- [ ] **Step 1: Run the existing MW calibration tests, capture green baseline**

```
... -m pytest src/gel_analyzer/tests/test_services/ -k "calibration or ladder" -v
```
Note the count of passing tests. (We must not regress.)

- [ ] **Step 2: Create the shared module**

`src/gel_analyzer/services/calibration/fitters_shared.py`:
```python
"""Curve-fit helpers shared between MW calibration (gel_analyzer.services.calibration)
and protein quantification calibration (gel_analyzer.services.quantification).

Behaviour-preserving extraction from CalibrationService — function bodies are copied
verbatim from service.py, only the residual write-back is parameterized via a
callback so quantification's BandMatch can be a different shape."""

from __future__ import annotations

import numpy as np
from scipy.stats import linregress


def fit_log_linear(rf: np.ndarray, log_mw: np.ndarray):
    """log10(MW) = slope·Rf + intercept. Returns (slope, intercept, r_squared, residuals)."""
    result = linregress(rf, log_mw)
    predicted = result.slope * rf + result.intercept
    residuals = log_mw - predicted
    return float(result.slope), float(result.intercept), float(result.rvalue ** 2), residuals


def fit_polynomial(x: np.ndarray, y: np.ndarray, degree: int):
    """Generic polynomial fit. Returns (coeffs, r_squared, residuals)."""
    coeffs = np.polyfit(x, y, degree)
    predicted = np.polyval(coeffs, x)
    ss_res = np.sum((y - predicted) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    residuals = y - predicted
    return coeffs.tolist(), float(r_squared), residuals


def format_polynomial_equation(coeffs: list, var: str = "x", lhs: str = "y") -> str:
    """Format polynomial coefficients as a human-readable equation string."""
    terms: list[str] = []
    degree = len(coeffs) - 1
    for i, c in enumerate(coeffs):
        power = degree - i
        c_str = f"{c:.4f}"
        if power == 0:
            terms.append(c_str)
        elif power == 1:
            terms.append(f"{c_str}*{var}")
        else:
            terms.append(f"{c_str}*{var}^{power}")
    return f"{lhs} = " + " + ".join(terms)
```

- [ ] **Step 3: Refactor `CalibrationService._fit_log_linear` and `_fit_polynomial`** to delegate.

In `src/gel_analyzer/services/calibration/service.py`, replace the body of `_fit_log_linear` (around line 604) with:
```python
    def _fit_log_linear(self, rf, log_mw, matches):
        from .fitters_shared import fit_log_linear
        try:
            slope, intercept, r_squared, residuals = fit_log_linear(rf, log_mw)
        except Exception as e:
            logger.error(f"Log-linear fit failed: {e}")
            return CalibrationResult(success=False, error_message=f"Regression failed: {e}")
        for i, m in enumerate(matches):
            m.residual = float(residuals[i])
        slope_sign = "+" if intercept >= 0 else ""
        equation = f"log10(MW) = {slope:.4f} * Rf {slope_sign}{intercept:.4f}"
        return CalibrationResult(
            success=True, method="LOG_LINEAR",
            coefficients={"slope": slope, "intercept": intercept},
            r_squared=r_squared, equation=equation, band_matches=matches,
        )
```

Replace `_fit_polynomial` body (around line 656) with:
```python
    def _fit_polynomial(self, rf, log_mw, matches, degree):
        from .fitters_shared import fit_polynomial, format_polynomial_equation
        try:
            coeffs, r_squared, residuals = fit_polynomial(rf, log_mw, degree)
        except Exception as e:
            logger.error(f"Polynomial fit (degree={degree}) failed: {e}")
            return CalibrationResult(success=False, error_message=f"Polynomial regression failed: {e}")
        for i, m in enumerate(matches):
            m.residual = float(residuals[i])
        equation = format_polynomial_equation(coeffs, var="Rf", lhs="log10(MW)")
        return CalibrationResult(
            success=True, method=f"POLYNOMIAL_{degree}",
            coefficients={"coeffs": coeffs}, r_squared=r_squared,
            equation=equation, band_matches=matches,
        )
```

Then delete the now-unused `_format_polynomial_equation` method (lines 712-728) — its job is done by the shared helper.

- [ ] **Step 4: Re-run MW calibration tests, verify still green**

```
... -m pytest src/gel_analyzer/tests/test_services/ -k "calibration or ladder" -v
```
Same count as Step 1.

- [ ] **Step 5: Commit**

```bash
git add src/gel_analyzer/services/calibration/
git commit -m "refactor(calibration): extract fit helpers to fitters_shared (no behavior change)"
```

---

## Phase 3 — Quantification service

### Task 3.1: Quantification dataclasses

**Files:**
- Create: `src/gel_analyzer/services/quantification/__init__.py`
- Create: `src/gel_analyzer/services/quantification/models.py`

- [ ] **Step 1: Empty package init**

`src/gel_analyzer/services/quantification/__init__.py`:
```python
"""Protein quantification calibration service."""
```

- [ ] **Step 2: Dataclasses**

`src/gel_analyzer/services/quantification/models.py`:
```python
"""Dataclasses for the protein quantification calibration service."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Method = Literal["LINEAR", "POLYNOMIAL_2", "FOUR_PL"]
Unit = Literal["UG", "UG_ML"]
Role = Literal["CALIBRATION", "CONTROL"]


@dataclass
class QuantParams:
    method: Method = "LINEAR"
    unit: Unit = "UG"
    excluded_band_ids: list[str] = field(default_factory=list)


@dataclass
class QuantPoint:
    band_id: str
    lane_id: int
    lane_number: int
    role: Role
    load_amount: float | None      # known for CALIBRATION + CONTROL; None for SAMPLE
    load_unit: Unit | None
    corrected_area: float | None   # None if densitometry not yet run
    is_excluded: bool = False
    residual: float | None = None  # filled at fit time
    predicted_amount: float | None = None  # filled at fit time


@dataclass
class QuantResult:
    success: bool
    method: Method = "LINEAR"
    unit: Unit = "UG"
    coefficients: dict = field(default_factory=dict)
    r_squared: float = 0.0
    equation: str = ""
    calibration_points: list[QuantPoint] = field(default_factory=list)
    control_points: list[QuantPoint] = field(default_factory=list)
    sample_projections: list[QuantPoint] = field(default_factory=list)
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "method": self.method,
            "unit": self.unit,
            "coefficients": self.coefficients,
            "r_squared": round(self.r_squared, 6),
            "equation": self.equation,
            "calibration_points": [_pt_to_dict(p) for p in self.calibration_points],
            "control_points":     [_pt_to_dict(p, with_recovery=True) for p in self.control_points],
            "sample_projections": [_pt_to_dict(p, sample=True) for p in self.sample_projections],
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


def _pt_to_dict(p: QuantPoint, *, with_recovery: bool = False, sample: bool = False) -> dict:
    base = {
        "band_id": p.band_id,
        "lane_number": p.lane_number,
        "corrected_area": p.corrected_area,
        "is_excluded": p.is_excluded,
    }
    if not sample:
        base["load_amount"] = p.load_amount
        base["load_unit"] = p.load_unit
        base["predicted_amount"] = p.predicted_amount
        if p.residual is not None and p.load_amount:
            base["residual_pct"] = round((p.residual / p.load_amount) * 100, 2)
    if with_recovery and p.predicted_amount is not None and p.load_amount:
        base["known_amount"] = p.load_amount
        base["recovery_pct"] = round((p.predicted_amount / p.load_amount) * 100, 2)
        base["out_of_spec"] = not (80 <= base["recovery_pct"] <= 120)
    if sample:
        base["estimated_amount"] = p.predicted_amount
    return base
```

- [ ] **Step 3: Smoke import**

```
... -c "from gel_analyzer.services.quantification.models import QuantParams, QuantPoint, QuantResult"
```
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add src/gel_analyzer/services/quantification/
git commit -m "feat(quantification): scaffold service package + dataclasses"
```

---

### Task 3.2: Fitters (linear / poly2 / 4PL) with TDD

**Files:**
- Create: `src/gel_analyzer/services/quantification/fitters.py`
- Test: `src/gel_analyzer/tests/test_services/test_quantification_fitters.py`

- [ ] **Step 1: Write the failing tests**

`src/gel_analyzer/tests/test_services/test_quantification_fitters.py`:
```python
"""Tests for quantification fitters."""
import numpy as np
import pytest

from gel_analyzer.services.quantification import fitters


class TestLinear:
    def test_perfect_line(self):
        x = np.array([1, 2, 3, 4, 5], dtype=float)
        y = 2 * x + 1  # slope=2, intercept=1
        coeffs, r2, residuals = fitters.fit_linear(x, y)
        assert coeffs["a"] == pytest.approx(2.0)
        assert coeffs["b"] == pytest.approx(1.0)
        assert r2 == pytest.approx(1.0)
        assert all(abs(r) < 1e-9 for r in residuals)

    def test_inverse_predict(self):
        # given y = 2x + 1, inverse: x = (y - 1) / 2
        coeffs = {"a": 2.0, "b": 1.0}
        assert fitters.predict_linear_inverse(coeffs, 7.0) == pytest.approx(3.0)


class TestPoly2:
    def test_perfect_quadratic(self):
        x = np.array([0, 1, 2, 3, 4], dtype=float)
        y = 2 * x ** 2 + 3 * x + 1
        coeffs, r2, residuals = fitters.fit_poly2(x, y)
        assert r2 == pytest.approx(1.0)
        assert coeffs["coeffs"] == pytest.approx([2.0, 3.0, 1.0])

    def test_predict_inverse_returns_real_root_in_range(self):
        # y = 2x² + 3x + 1; pick x=2, y=15. Solve: 2x² + 3x + 1 - 15 = 0 → x = 2 or x ≈ -3.5
        # Service should return x=2 (positive root closest to interpolation range).
        coeffs = {"coeffs": [2.0, 3.0, 1.0]}
        x_range = (0.0, 4.0)
        assert fitters.predict_poly2_inverse(coeffs, 15.0, x_range=x_range) == pytest.approx(2.0)


class TestFourPL:
    def test_4pl_converges_on_classic_dataset(self):
        # synthetic 4PL: a=0, d=100, c=10, b=1.2 → y = 100/(1+(x/10)^-1.2) more or less
        x = np.array([0.5, 1, 2, 5, 10, 20, 50, 100], dtype=float)
        a, d, c, b = 0.0, 100.0, 10.0, 1.2
        y = d + (a - d) / (1 + (x / c) ** b)
        coeffs, r2, residuals = fitters.fit_4pl(x, y)
        assert r2 > 0.999
        assert coeffs["c"] == pytest.approx(c, rel=0.05)

    def test_4pl_rejects_too_few_points(self):
        x = np.array([1, 2, 3], dtype=float)
        y = np.array([1, 2, 3], dtype=float)
        with pytest.raises(ValueError, match="at least 4"):
            fitters.fit_4pl(x, y)

    def test_4pl_inverse(self):
        coeffs = {"a": 0.0, "d": 100.0, "c": 10.0, "b": 1.2}
        # y = 50 → x = 10 (the c parameter, by definition)
        assert fitters.predict_4pl_inverse(coeffs, 50.0) == pytest.approx(10.0, rel=0.01)
```

- [ ] **Step 2: Run, verify failure** — `... -m pytest src/gel_analyzer/tests/test_services/test_quantification_fitters.py -v`. Expected: ImportError on fitters module.

- [ ] **Step 3: Implement fitters**

`src/gel_analyzer/services/quantification/fitters.py`:
```python
"""Curve-fitting primitives for protein quantification.

All fitters take 1-D numpy arrays (area, amount) and return:
  (coefficients_dict, r_squared, residuals)

Inverse predictors take coefficients + observed area and return predicted amount.
The inverse for poly2 picks the root closest to the original interpolation range
to stay physically meaningful (load amount > 0)."""

from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit

from gel_analyzer.services.calibration.fitters_shared import (
    fit_polynomial,
    format_polynomial_equation,
)


# ---------- Linear y = a·x + b ----------------------------------------------


def fit_linear(area: np.ndarray, amount: np.ndarray):
    """Fit y = a·x + b. Returns ({a, b}, r², residuals)."""
    coeffs_list, r2, residuals = fit_polynomial(area, amount, 1)
    a, b = float(coeffs_list[0]), float(coeffs_list[1])
    return {"a": a, "b": b}, r2, residuals


def predict_linear_inverse(coeffs: dict, amount: float) -> float | None:
    """Given y = a·x + b and observed y, return x = (y - b) / a."""
    a, b = coeffs.get("a", 0.0), coeffs.get("b", 0.0)
    if a == 0:
        return None
    return (amount - b) / a


def linear_equation(coeffs: dict, unit: str) -> str:
    a, b = coeffs["a"], coeffs["b"]
    sign = "+" if b >= 0 else "-"
    return f"{unit} = {a:.4g}·area {sign} {abs(b):.4g}"


# ---------- Polynomial deg 2 y = a·x² + b·x + c -----------------------------


def fit_poly2(area: np.ndarray, amount: np.ndarray):
    coeffs_list, r2, residuals = fit_polynomial(area, amount, 2)
    return {"coeffs": [float(c) for c in coeffs_list]}, r2, residuals


def predict_poly2_inverse(coeffs: dict, amount: float, x_range: tuple[float, float] | None = None) -> float | None:
    """Solve a·x² + b·x + c - amount = 0. Pick the root closest to x_range mid (or the
    positive one if x_range is None). Return None if no real root."""
    a, b, c = coeffs["coeffs"]
    discriminant = b * b - 4 * a * (c - amount)
    if discriminant < 0:
        return None
    sqrt_d = np.sqrt(discriminant)
    if a == 0:
        # degenerate: linear case
        return None if b == 0 else (amount - c) / b
    r1 = (-b + sqrt_d) / (2 * a)
    r2 = (-b - sqrt_d) / (2 * a)
    if x_range is not None:
        target = (x_range[0] + x_range[1]) / 2
        return r1 if abs(r1 - target) <= abs(r2 - target) else r2
    return r1 if r1 >= 0 else r2


def poly2_equation(coeffs: dict, unit: str) -> str:
    return format_polynomial_equation(coeffs["coeffs"], var="area", lhs=unit)


# ---------- 4-Parameter Logistic --------------------------------------------


def _four_pl(x, a, d, c, b):
    """4PL function: y = d + (a - d) / (1 + (x / c) ** b)."""
    return d + (a - d) / (1 + (x / c) ** b)


def fit_4pl(area: np.ndarray, amount: np.ndarray):
    """Fit y = d + (a - d) / (1 + (x / c)^b). Requires >= 4 points."""
    if len(area) < 4:
        raise ValueError("4PL requires at least 4 points")
    a0 = float(np.min(amount))
    d0 = float(np.max(amount))
    c0 = float(np.median(area))
    b0 = 1.0
    try:
        popt, _ = curve_fit(
            _four_pl, area, amount,
            p0=[a0, d0, c0, b0], maxfev=5000,
        )
    except Exception as e:
        raise ValueError(f"4PL did not converge: {e}") from e
    a, d, c, b = (float(v) for v in popt)
    predicted = _four_pl(area, a, d, c, b)
    ss_res = np.sum((amount - predicted) ** 2)
    ss_tot = np.sum((amount - np.mean(amount)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    residuals = amount - predicted
    return {"a": a, "d": d, "c": c, "b": b}, float(r2), residuals


def predict_4pl_inverse(coeffs: dict, amount: float) -> float | None:
    """Solve 4PL for x given y. y = d + (a-d)/(1 + (x/c)^b) → x = c * ((a-d)/(y-d) - 1)^(1/b)."""
    a, d, c, b = coeffs["a"], coeffs["d"], coeffs["c"], coeffs["b"]
    try:
        ratio = (a - d) / (amount - d)
        if ratio <= 1:
            return None
        return c * (ratio - 1) ** (1.0 / b)
    except (ZeroDivisionError, ValueError):
        return None


def four_pl_equation(coeffs: dict, unit: str) -> str:
    a, d, c, b = coeffs["a"], coeffs["d"], coeffs["c"], coeffs["b"]
    return f"{unit} = {d:.4g} + ({a:.4g} - {d:.4g}) / (1 + (area / {c:.4g})^{b:.4g})"
```

- [ ] **Step 4: Run tests, verify all pass**

```
... -m pytest src/gel_analyzer/tests/test_services/test_quantification_fitters.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gel_analyzer/services/quantification/fitters.py src/gel_analyzer/tests/test_services/test_quantification_fitters.py
git commit -m "feat(quantification): linear/poly2/4PL fitters + inverse predictors"
```

---

### Task 3.3: `ProteinQuantCalibrationService` — collect_* methods

**Files:**
- Create: `src/gel_analyzer/services/quantification/service.py`
- Test: `src/gel_analyzer/tests/test_services/test_quantification_service.py`

- [ ] **Step 1: Write failing test**

`src/gel_analyzer/tests/test_services/test_quantification_service.py`:
```python
"""Tests for ProteinQuantCalibrationService.collect_*."""
import pytest

from gel_analyzer.models import (
    Band, DensitometryResult, Lane, ProteinQuantCalibrationPoint,
)
from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

pytestmark = pytest.mark.django_db


@pytest.fixture
def calib_setup(sample_analysis, test_user):
    """Build a calibration lane + band + densitometry + point."""
    lane = Lane.objects.create(
        analysis=sample_analysis, lane_number=10,
        lane_type=Lane.LaneType.CALIBRATION,
        x=0, y=0, width=50, height=200,
    )
    band = Band.objects.create(
        lane=lane, band_type=Band.BandType.CALIBRATION,
        position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
        created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
    )
    DensitometryResult.objects.create(
        band=band, peak_center_y=100, peak_amplitude=50,
        peak_sigma=5, fwhm=11.77, integrated_area=1000,
        corrected_area=1000, fit_r_squared=0.99, snr=20,
    )
    ProteinQuantCalibrationPoint.objects.create(
        band=band, load_amount=10.0, load_unit="UG", role="CALIBRATION",
    )
    return sample_analysis, lane, band


class TestCollectCalibrationPoints:
    def test_returns_band_with_densitometry(self, calib_setup):
        analysis, lane, band = calib_setup
        svc = ProteinQuantCalibrationService()
        points = svc.collect_calibration_points(analysis)
        assert len(points) == 1
        p = points[0]
        assert p.band_id == str(band.id)
        assert p.load_amount == 10.0
        assert p.corrected_area == 1000.0
        assert p.role == "CALIBRATION"

    def test_skips_band_without_densitometry(self, sample_analysis, test_user):
        lane = Lane.objects.create(
            analysis=sample_analysis, lane_number=11,
            lane_type=Lane.LaneType.CALIBRATION,
            x=0, y=0, width=50, height=200,
        )
        band = Band.objects.create(
            lane=lane, band_type=Band.BandType.CALIBRATION,
            position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        ProteinQuantCalibrationPoint.objects.create(
            band=band, load_amount=10.0, load_unit="UG", role="CALIBRATION",
        )
        svc = ProteinQuantCalibrationService()
        points = svc.collect_calibration_points(sample_analysis)
        assert len(points) == 1
        assert points[0].corrected_area is None  # collected but flagged as missing

    def test_excludes_control_points(self, calib_setup, sample_analysis, test_user):
        # Add a CONTROL lane + band + point
        ctrl_lane = Lane.objects.create(
            analysis=sample_analysis, lane_number=12,
            lane_type=Lane.LaneType.CONTROL,
            x=0, y=0, width=50, height=200,
        )
        ctrl_band = Band.objects.create(
            lane=ctrl_lane, band_type=Band.BandType.CALIBRATION,
            position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        DensitometryResult.objects.create(
            band=ctrl_band, peak_center_y=100, peak_amplitude=50, peak_sigma=5,
            fwhm=11.77, integrated_area=900, corrected_area=900,
            fit_r_squared=0.99, snr=20,
        )
        ProteinQuantCalibrationPoint.objects.create(
            band=ctrl_band, load_amount=10.0, load_unit="UG", role="CONTROL",
        )
        svc = ProteinQuantCalibrationService()
        cal_points = svc.collect_calibration_points(sample_analysis)
        ctrl_points = svc.collect_control_points(sample_analysis)
        assert len(cal_points) == 1
        assert len(ctrl_points) == 1
        assert ctrl_points[0].role == "CONTROL"
```

- [ ] **Step 2: Run, expect failure** (ImportError on service).

- [ ] **Step 3: Create the service skeleton with collect methods**

`src/gel_analyzer/services/quantification/service.py`:
```python
"""ProteinQuantCalibrationService — fits a curve from CALIBRATION-tagged points
and projects samples onto it. Mirror of CalibrationService for protein quantification."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from phoresis_core.logging_config import get_logger

from .models import QuantParams, QuantPoint, QuantResult
from . import fitters

if TYPE_CHECKING:
    from gel_analyzer.models import Band, GelAnalysis, ProteinQuantCalibration

logger = get_logger(__name__)


class ProteinQuantCalibrationService:
    def __init__(self, params: QuantParams | None = None):
        self.params = params or QuantParams()

    # ------------ Collection -------------------------------------------------

    def collect_calibration_points(self, analysis: "GelAnalysis") -> list[QuantPoint]:
        """All CALIBRATION-typed bands inside CALIBRATION-typed lanes of the analysis."""
        from gel_analyzer.models import Band, Lane
        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.CALIBRATION,
                band_type=Band.BandType.CALIBRATION,
                quant_point__isnull=False,
            )
            .select_related("lane", "quant_point")
            .prefetch_related("densitometry")
        )
        return [self._band_to_point(b, role="CALIBRATION") for b in bands]

    def collect_control_points(self, analysis: "GelAnalysis") -> list[QuantPoint]:
        """All CALIBRATION-typed bands inside CONTROL-typed lanes."""
        from gel_analyzer.models import Band, Lane
        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.CONTROL,
                band_type=Band.BandType.CALIBRATION,
                quant_point__isnull=False,
            )
            .select_related("lane", "quant_point")
            .prefetch_related("densitometry")
        )
        return [self._band_to_point(b, role="CONTROL") for b in bands]

    def collect_sample_bands(self, analysis: "GelAnalysis") -> list[QuantPoint]:
        """All non-MW_REFERENCE bands of SAMPLE lanes that have densitometry."""
        from gel_analyzer.models import Band, Lane
        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.SAMPLE,
            )
            .exclude(band_type=Band.BandType.MW_REFERENCE)
            .select_related("lane")
            .prefetch_related("densitometry")
        )
        return [self._band_to_sample_point(b) for b in bands]

    @staticmethod
    def _band_to_point(band: "Band", *, role: str) -> QuantPoint:
        densito = getattr(band, "densitometry", None)
        qp = band.quant_point
        return QuantPoint(
            band_id=str(band.id),
            lane_id=band.lane_id,
            lane_number=band.lane.lane_number,
            role=role,
            load_amount=qp.load_amount,
            load_unit=qp.load_unit,
            corrected_area=densito.corrected_area if densito else None,
            is_excluded=qp.is_excluded_from_fit,
        )

    @staticmethod
    def _band_to_sample_point(band: "Band") -> QuantPoint:
        densito = getattr(band, "densitometry", None)
        return QuantPoint(
            band_id=str(band.id),
            lane_id=band.lane_id,
            lane_number=band.lane.lane_number,
            role="CALIBRATION",  # placeholder; sample projections don't carry roles
            load_amount=None,
            load_unit=None,
            corrected_area=densito.corrected_area if densito else None,
        )
```

- [ ] **Step 4: Run, expect PASS on the 3 tests**.

- [ ] **Step 5: Commit**

```bash
git add src/gel_analyzer/services/quantification/service.py src/gel_analyzer/tests/test_services/test_quantification_service.py
git commit -m "feat(quantification): collect calibration/control/sample points"
```

---

### Task 3.4: `ProteinQuantCalibrationService.fit`

**Files:**
- Modify: `src/gel_analyzer/services/quantification/service.py`
- Test: `src/gel_analyzer/tests/test_services/test_quantification_service.py`

- [ ] **Step 1: Write failing tests**

Append to `test_quantification_service.py`:
```python
class TestFit:
    def _make_points(self, areas, amounts, role="CALIBRATION"):
        from gel_analyzer.services.quantification.models import QuantPoint
        return [
            QuantPoint(
                band_id=f"b{i}", lane_id=i, lane_number=i, role=role,
                load_amount=a, load_unit="UG", corrected_area=area,
            )
            for i, (area, a) in enumerate(zip(areas, amounts), start=1)
        ]

    def test_linear_fit_perfect(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
        points = self._make_points([1000, 2000, 3000, 4000], [5, 10, 15, 20])
        result = svc.fit(points)
        assert result.success
        assert result.r_squared == pytest.approx(1.0)
        assert result.coefficients["a"] == pytest.approx(0.005)
        assert result.coefficients["b"] == pytest.approx(0.0)

    def test_excludes_outliers(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
        points = self._make_points([1000, 2000, 3000, 9999], [5, 10, 15, 20])
        result = svc.fit(points, excluded_band_ids=["b4"])
        assert result.success
        assert result.r_squared == pytest.approx(1.0)
        assert sum(1 for p in result.calibration_points if p.is_excluded) == 1

    def test_rejects_when_missing_corrected_area(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
        points = self._make_points([1000, 2000, None, 4000], [5, 10, 15, 20])
        result = svc.fit(points)
        assert not result.success
        assert "densitometry" in (result.error_message or "").lower()

    def test_4pl_requires_4_points(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="FOUR_PL", unit="UG"))
        points = self._make_points([1000, 2000, 3000], [5, 10, 15])
        result = svc.fit(points)
        assert not result.success
        assert "4" in (result.error_message or "")
```

- [ ] **Step 2: Run, expect FAIL** (no `fit` method).

- [ ] **Step 3: Implement `fit`**

Append to `service.py`:
```python
    # ------------ Fit --------------------------------------------------------

    def fit(self, points: list[QuantPoint], excluded_band_ids: list[str] | None = None) -> QuantResult:
        excluded = set(excluded_band_ids or [])
        for p in points:
            p.is_excluded = p.band_id in excluded
        non_excluded = [p for p in points if not p.is_excluded]
        missing = [p.band_id for p in non_excluded if p.corrected_area is None]
        if missing:
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=f"Densitometry missing on {len(missing)} band(s); run densitometry first",
                calibration_points=points,
            )
        if len(non_excluded) < 2:
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=f"Need at least 2 non-excluded points, got {len(non_excluded)}",
                calibration_points=points,
            )
        if self.params.method == "FOUR_PL" and len(non_excluded) < 4:
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=f"4PL requires at least 4 non-excluded points, got {len(non_excluded)}",
                calibration_points=points,
            )

        areas = np.array([p.corrected_area for p in non_excluded], dtype=float)
        amounts = np.array([p.load_amount for p in non_excluded], dtype=float)

        try:
            if self.params.method == "LINEAR":
                coeffs, r2, residuals = fitters.fit_linear(areas, amounts)
                eq = fitters.linear_equation(coeffs, self.params.unit)
            elif self.params.method == "POLYNOMIAL_2":
                coeffs, r2, residuals = fitters.fit_poly2(areas, amounts)
                eq = fitters.poly2_equation(coeffs, self.params.unit)
            elif self.params.method == "FOUR_PL":
                coeffs, r2, residuals = fitters.fit_4pl(areas, amounts)
                eq = fitters.four_pl_equation(coeffs, self.params.unit)
            else:
                return QuantResult(
                    success=False, error_message=f"Unknown method: {self.params.method}",
                    calibration_points=points,
                )
        except Exception as e:
            logger.error(f"Quantification fit failed: {e}")
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=str(e), calibration_points=points,
            )

        # residuals = observed - predicted, so predicted = observed - residual
        for p, r in zip(non_excluded, residuals):
            p.residual = float(r)
            p.predicted_amount = float(p.load_amount - r)

        return QuantResult(
            success=True,
            method=self.params.method,
            unit=self.params.unit,
            coefficients=coeffs,
            r_squared=r2,
            equation=eq,
            calibration_points=points,
        )
```

- [ ] **Step 4: Run tests** — `... -m pytest src/gel_analyzer/tests/test_services/test_quantification_service.py::TestFit -v`. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(quantification): service.fit (linear/poly2/4PL with exclusion)"
```

---

### Task 3.5: `service.project` + `apply_to_analysis`

**Files:**
- Modify: `src/gel_analyzer/services/quantification/service.py`
- Test: `src/gel_analyzer/tests/test_services/test_quantification_service.py`

- [ ] **Step 1: Write failing tests**

Append:
```python
class TestProjectAndApply:
    def test_project_inverse_linear(self):
        from gel_analyzer.services.quantification.models import QuantResult
        result = QuantResult(
            success=True, method="LINEAR", unit="UG",
            coefficients={"a": 0.005, "b": 0.0}, r_squared=1.0, equation="...",
        )
        svc = ProteinQuantCalibrationService()
        assert svc.project(2000, result) == pytest.approx(10.0)

    def test_apply_to_analysis_writes_estimated_amount(self, calib_setup, sample_analysis, test_user):
        analysis, cal_lane, cal_band = calib_setup
        sample_lane = Lane.objects.create(
            analysis=analysis, lane_number=20, lane_type=Lane.LaneType.SAMPLE,
            x=0, y=0, width=50, height=200,
        )
        sample_band = Band.objects.create(
            lane=sample_lane, band_type=Band.BandType.POI,
            position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        DensitometryResult.objects.create(
            band=sample_band, peak_center_y=100, peak_amplitude=50, peak_sigma=5,
            fwhm=11.77, integrated_area=2000, corrected_area=2000,
            fit_r_squared=0.99, snr=20,
        )
        svc = ProteinQuantCalibrationService()
        # Build calibration manually
        calib = sample_analysis.quant_calibrations.create(
            method="LINEAR", unit="UG",
            coefficients={"a": 0.005, "b": 0.0}, r_squared=1.0, equation="UG = 0.005·area",
            created_by=test_user,
        )
        n = svc.apply_to_analysis(calib)
        assert n >= 1
        sample_band.densitometry.refresh_from_db()
        assert sample_band.densitometry.estimated_amount == pytest.approx(10.0)
        assert sample_band.densitometry.estimated_amount_unit == "UG"
```

- [ ] **Step 2: Run, expect FAIL**.

- [ ] **Step 3: Implement `project` and `apply_to_analysis`**

Append to `service.py`:
```python
    # ------------ Projection / persistence -----------------------------------

    def project(self, area: float, result: QuantResult) -> float | None:
        """Inverse-transform an area to an amount via the active fit coefficients."""
        if not result.success or area is None:
            return None
        if result.method == "LINEAR":
            return fitters.predict_linear_inverse(result.coefficients, area)
        if result.method == "POLYNOMIAL_2":
            # Fit was amounts = f(areas), so to predict amount we evaluate the polynomial
            # forward (not inverse). Override the call accordingly.
            coeffs = result.coefficients["coeffs"]
            return float(np.polyval(coeffs, area))
        if result.method == "FOUR_PL":
            # Same: 4PL was fit as amount = f(area). Forward evaluation:
            a = result.coefficients["a"]
            d = result.coefficients["d"]
            c = result.coefficients["c"]
            b = result.coefficients["b"]
            return float(d + (a - d) / (1 + (area / c) ** b))
        return None

    def apply_to_analysis(self, calibration: "ProteinQuantCalibration") -> int:
        """Persist DensitometryResult.estimated_amount{,_unit} for all SAMPLE/CONTROL
        bands of the calibration's analysis. Returns count of rows updated."""
        from gel_analyzer.models import Band, DensitometryResult, Lane

        result = QuantResult(
            success=True, method=calibration.method, unit=calibration.unit,
            coefficients=calibration.coefficients, r_squared=calibration.r_squared,
            equation=calibration.equation,
        )
        target_bands = (
            Band.objects.filter(
                lane__analysis=calibration.analysis,
                lane__lane_type__in=[Lane.LaneType.SAMPLE, Lane.LaneType.CONTROL],
                densitometry__isnull=False,
            )
            .exclude(band_type=Band.BandType.MW_REFERENCE)
            .select_related("densitometry", "lane")
        )
        updated = 0
        for band in target_bands:
            estimated = self.project(band.densitometry.corrected_area, result)
            if estimated is None or estimated < 0:
                continue
            DensitometryResult.objects.filter(pk=band.densitometry.pk).update(
                estimated_amount=float(estimated),
                estimated_amount_unit=calibration.unit,
            )
            updated += 1
        logger.info(f"Quantification calibration {calibration.id} applied to {updated} bands")
        return updated
```

> Note for the engineer: `project` interpretation depends on which axis was `x` during the fit. Here we fit `amount = f(area)`, so `project(area)` is forward evaluation — not inverse. The names in the dataclass and the test assert this. The 4PL inverse helper in `fitters.py` is kept for completeness but isn't called from `apply_to_analysis`.

- [ ] **Step 4: Run tests** — both PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(quantification): project + apply_to_analysis"
```

---

### Task 3.6: `service.save_active`

**Files:**
- Modify: `src/gel_analyzer/services/quantification/service.py`
- Test: same test file

- [ ] **Step 1: Write failing test**

```python
class TestSaveActive:
    def test_save_creates_active_and_supersedes_previous(self, calib_setup, test_user):
        analysis, _, _ = calib_setup
        svc = ProteinQuantCalibrationService()
        # First fit
        from gel_analyzer.services.quantification.models import QuantResult
        r1 = QuantResult(success=True, method="LINEAR", unit="UG",
                          coefficients={"a": 0.005, "b": 0}, r_squared=0.99, equation="...")
        c1 = svc.save_active(analysis, r1, user=test_user)
        assert c1.is_active is True
        # Second fit
        r2 = QuantResult(success=True, method="LINEAR", unit="UG",
                          coefficients={"a": 0.0048, "b": 0.1}, r_squared=0.995, equation="...")
        c2 = svc.save_active(analysis, r2, user=test_user)
        c1.refresh_from_db()
        assert c1.is_active is False
        assert c1.superseded_at is not None
        assert c2.is_active is True
        # Only one active
        assert analysis.quant_calibrations.filter(is_active=True).count() == 1
```

- [ ] **Step 2: Run, expect FAIL**.

- [ ] **Step 3: Implement `save_active`**

Append to `service.py`:
```python
    def save_active(
        self,
        analysis: "GelAnalysis",
        result: QuantResult,
        *,
        user=None,
        notes: str = "",
    ) -> "ProteinQuantCalibration":
        from django.db import transaction
        from django.utils import timezone

        from gel_analyzer.models import ProteinQuantCalibration

        if not result.success:
            raise ValueError(f"Cannot save a failed fit: {result.error_message}")

        with transaction.atomic():
            previous = analysis.quant_calibrations.filter(is_active=True)
            previous.update(is_active=False, superseded_at=timezone.now())
            calib = ProteinQuantCalibration.objects.create(
                analysis=analysis,
                method=result.method,
                unit=result.unit,
                coefficients=result.coefficients,
                r_squared=result.r_squared,
                equation=result.equation,
                excluded_band_ids=[
                    p.band_id for p in result.calibration_points if p.is_excluded
                ],
                is_active=True,
                created_by=user,
                notes=notes,
            )
        return calib
```

- [ ] **Step 4: Run test, verify PASS**.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(quantification): save_active with supersede"
```

---

### Task 3.7: `recompute_if_active` invalidation hook + densito wiring

**Files:**
- Create: `src/gel_analyzer/services/quantification/invalidation.py`
- Modify: `src/gel_analyzer/tasks.py` (find `run_densitometry_task`)
- Test: `src/gel_analyzer/tests/test_services/test_quantification_invalidation.py`

- [ ] **Step 1: Write failing test**

`src/gel_analyzer/tests/test_services/test_quantification_invalidation.py`:
```python
"""Tests for the quantification recompute-if-active hook."""
import pytest

from gel_analyzer.models import Band, DensitometryResult, Lane, ProteinQuantCalibration
from gel_analyzer.services.quantification.invalidation import recompute_if_active

pytestmark = pytest.mark.django_db


def test_no_active_calibration_is_noop(sample_analysis):
    # No calibration exists → must not raise, must return None / 0 sentinel
    assert recompute_if_active(sample_analysis) == 0


def test_active_calibration_refits_and_reapplies(sample_analysis, test_user):
    """Given an active calibration + densitometry data, recompute_if_active should
    write fresh DensitometryResult.estimated_amount values."""
    cal_lane = Lane.objects.create(
        analysis=sample_analysis, lane_number=1, lane_type=Lane.LaneType.CALIBRATION,
        x=0, y=0, width=50, height=200,
    )
    sample_lane = Lane.objects.create(
        analysis=sample_analysis, lane_number=2, lane_type=Lane.LaneType.SAMPLE,
        x=0, y=0, width=50, height=200,
    )
    cal_bands = []
    for i, (area, amount) in enumerate([(1000, 5), (2000, 10), (3000, 15)], start=1):
        b = Band.objects.create(
            lane=cal_lane, band_type=Band.BandType.CALIBRATION,
            position_y=i * 50, bbox_x=0, bbox_y=i * 50 - 10,
            bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        DensitometryResult.objects.create(
            band=b, peak_center_y=i*50, peak_amplitude=50, peak_sigma=5,
            fwhm=11.77, integrated_area=area, corrected_area=area,
            fit_r_squared=0.99, snr=20,
        )
        from gel_analyzer.models import ProteinQuantCalibrationPoint
        ProteinQuantCalibrationPoint.objects.create(
            band=b, load_amount=amount, load_unit="UG", role="CALIBRATION",
        )
        cal_bands.append(b)
    sample_band = Band.objects.create(
        lane=sample_lane, band_type=Band.BandType.POI,
        position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
        created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
    )
    DensitometryResult.objects.create(
        band=sample_band, peak_center_y=100, peak_amplitude=50, peak_sigma=5,
        fwhm=11.77, integrated_area=2500, corrected_area=2500,
        fit_r_squared=0.99, snr=20,
    )
    ProteinQuantCalibration.objects.create(
        analysis=sample_analysis, method="LINEAR", unit="UG",
        coefficients={"a": 0.005, "b": 0.0}, r_squared=1.0, equation="...",
        created_by=test_user,
    )

    n = recompute_if_active(sample_analysis)
    assert n >= 1
    sample_band.densitometry.refresh_from_db()
    assert sample_band.densitometry.estimated_amount == pytest.approx(12.5)
```

- [ ] **Step 2: Run, expect FAIL** (ImportError).

- [ ] **Step 3: Implement invalidation module**

`src/gel_analyzer/services/quantification/invalidation.py`:
```python
"""Recompute the active protein quantification calibration after densitometry changes.

Called at the end of `run_densitometry_task` (after the bulk write-back), NOT from
the densito invalidation signal — at signal-fire time the DensitometryResult rows
have just been deleted, so corrected_area is unavailable. The recompute window is
post-densitometry-write."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import GelAnalysis

logger = get_logger(__name__)


def recompute_if_active(analysis: "GelAnalysis") -> int:
    """If the analysis has an active ProteinQuantCalibration, refit it from the
    current densitometry and reapply (writes DensitometryResult.estimated_amount
    on every SAMPLE/CONTROL band). Returns count of rows updated; 0 if no active
    calibration exists or if refit failed."""
    from gel_analyzer.models import ProteinQuantCalibration
    from .models import QuantParams
    from .service import ProteinQuantCalibrationService

    active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
    if active is None:
        return 0

    svc = ProteinQuantCalibrationService(QuantParams(method=active.method, unit=active.unit))
    points = svc.collect_calibration_points(analysis)
    result = svc.fit(points, excluded_band_ids=active.excluded_band_ids)
    if not result.success:
        logger.warning(
            f"recompute_if_active({analysis.pk}): refit failed: {result.error_message}"
        )
        return 0

    # Update the active row's coefficients in place (no new active record — we are
    # responding to upstream densito changes, not to a user-initiated recalibration)
    active.coefficients = result.coefficients
    active.r_squared = result.r_squared
    active.equation = result.equation
    active.save(update_fields=["coefficients", "r_squared", "equation"])

    return svc.apply_to_analysis(active)
```

- [ ] **Step 4: Wire into densitometry task**

Read `src/gel_analyzer/tasks.py`. Find `run_densitometry_task`. At the end of the task body (just before the final return), append:
```python
    # Refit + reapply the active protein-quantification calibration if any.
    # Imported lazily to keep tasks.py free of service-package imports during
    # Celery worker boot.
    from gel_analyzer.services.quantification.invalidation import recompute_if_active
    try:
        recompute_if_active(analysis)
    except Exception as exc:  # never let quantification break a densito run
        logger.warning(f"Quantification recompute skipped after densitometry: {exc}")
```

(If `analysis` isn't already a local in scope at the end, derive it from the same place the task does at the start. Use `logger` from the existing imports.)

- [ ] **Step 5: Run integration test, verify PASS**.

```
... -m pytest src/gel_analyzer/tests/test_services/test_quantification_invalidation.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/gel_analyzer/services/quantification/invalidation.py src/gel_analyzer/tasks.py src/gel_analyzer/tests/test_services/test_quantification_invalidation.py
git commit -m "feat(quantification): recompute_if_active hook + wire into densitometry task"
```

---

## Phase 4 — REST API

### Task 4.1: Extend `LaneSerializer` + `BandSerializer`

**Files:**
- Modify: `src/gel_analyzer/api/serializers.py`
- Test: `src/gel_analyzer/tests/test_views/test_api_quantification.py`

- [ ] **Step 1: Read `serializers.py` to find LaneSerializer + BandSerializer**

```
... rg "class LaneSerializer|class BandSerializer" src/gel_analyzer/api/serializers.py
```

- [ ] **Step 2: Add fields**

In `LaneSerializer.Meta.fields` add `loading_volume_ul`. Allow it as writeable.

In `BandSerializer`:
- Verify that `corrected_area` is already exposed (the band-level Properties Panel "Calibration" section in Task 5.4 reads `band.densitometry?.corrected_area` to show the ✓/⚠ availability indicator). If the existing serializer doesn't surface it, add a `corrected_area = serializers.FloatField(source="densitometry.corrected_area", read_only=True, allow_null=True)`.
- Add `estimated_amount` and `estimated_amount_unit` as read-only sourced from `densitometry` (`SerializerMethodField` or similar — match existing pattern of how `intensity_normalized` is exposed).
- Add `quant_point` as a nested serializer:
  ```python
  class QuantPointSerializer(serializers.ModelSerializer):
      class Meta:
          model = ProteinQuantCalibrationPoint
          fields = ("load_amount", "load_unit", "is_excluded_from_fit", "role")
          read_only_fields = ("role",)
  ```
- Wire `quant_point = QuantPointSerializer(required=False, allow_null=True)` on `BandSerializer`.
- Override `update()` to handle nested writes:
  ```python
  def update(self, instance, validated_data):
      qp_data = validated_data.pop("quant_point", None)
      band = super().update(instance, validated_data)
      if band.band_type == Band.BandType.CALIBRATION and qp_data is not None:
          ProteinQuantCalibrationPoint.objects.update_or_create(
              band=band,
              defaults={
                  "load_amount": qp_data["load_amount"],
                  "load_unit": qp_data["load_unit"],
                  "is_excluded_from_fit": qp_data.get("is_excluded_from_fit", False),
                  "role": "CONTROL" if band.lane.lane_type == Lane.LaneType.CONTROL else "CALIBRATION",
              },
          )
      elif band.band_type != Band.BandType.CALIBRATION:
          # type was demoted; remove any orphan point
          ProteinQuantCalibrationPoint.objects.filter(band=band).delete()
      return band
  ```

- [ ] **Step 3: Validate consistency rules in `BandSerializer.validate`**

```python
def validate(self, attrs):
    band_type = attrs.get("band_type", getattr(self.instance, "band_type", None))
    qp = attrs.get("quant_point")
    if band_type == Band.BandType.CALIBRATION and qp is None and self.instance is None:
        raise serializers.ValidationError(
            "band_type=CALIBRATION requires a quant_point with load_amount and load_unit"
        )
    # parent lane must be CALIBRATION or CONTROL
    if band_type == Band.BandType.CALIBRATION:
        lane = attrs.get("lane") or (self.instance.lane if self.instance else None)
        if lane and lane.lane_type not in (Lane.LaneType.CALIBRATION, Lane.LaneType.CONTROL):
            raise serializers.ValidationError(
                "band_type=CALIBRATION must live in a CALIBRATION or CONTROL lane"
            )
    # unit consistency with active calibration
    if qp is not None and band_type == Band.BandType.CALIBRATION:
        from gel_analyzer.models import ProteinQuantCalibration
        analysis = (attrs.get("lane") or self.instance.lane).analysis
        active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
        if active and qp["load_unit"] != active.unit:
            raise serializers.ValidationError(
                f"Unit {qp['load_unit']} differs from the active calibration's unit {active.unit}"
            )
    return attrs
```

- [ ] **Step 4: Add an API test for the band PATCH happy path**

`src/gel_analyzer/tests/test_views/test_api_quantification.py`:
```python
import pytest

pytestmark = pytest.mark.django_db


def test_patch_band_to_calibration_with_quant_point(authenticated_client, calibration_band):
    url = f"/gel-analyzer/api/bands/{calibration_band.id}/"
    response = authenticated_client.patch(
        url,
        {"band_type": "CALIBRATION", "quant_point": {"load_amount": 10.0, "load_unit": "UG"}},
        format="json",
    )
    assert response.status_code == 200
    calibration_band.refresh_from_db()
    assert calibration_band.quant_point.load_amount == 10.0


def test_patch_band_calibration_without_quant_point_400(authenticated_client, calibration_band):
    # Strip an existing quant_point first to make this a "creation" path
    if hasattr(calibration_band, "quant_point"):
        calibration_band.quant_point.delete()
    url = f"/gel-analyzer/api/bands/{calibration_band.id}/"
    response = authenticated_client.patch(url, {"band_type": "CALIBRATION"}, format="json")
    assert response.status_code == 400


def test_patch_band_calibration_in_sample_lane_400(authenticated_client, sample_band):
    url = f"/gel-analyzer/api/bands/{sample_band.id}/"
    response = authenticated_client.patch(
        url,
        {"band_type": "CALIBRATION", "quant_point": {"load_amount": 10.0, "load_unit": "UG"}},
        format="json",
    )
    assert response.status_code == 400
    assert "CALIBRATION lane" in response.json().get("non_field_errors", [""])[0] \
           or "lane" in response.content.decode().lower()
```

(Use existing `authenticated_client` fixture. If `calibration_band` / `sample_band` fixtures don't exist, add them to `conftest.py` mirroring the patterns in tests above.)

- [ ] **Step 5: Run tests, fix until green**.

- [ ] **Step 6: Commit**

```bash
git add src/gel_analyzer/api/serializers.py src/gel_analyzer/tests/
git commit -m "feat(api): extend Band/Lane serializers with quantification fields"
```

---

### Task 4.2: Lane PATCH downgrade with `?force=true`

**Files:**
- Modify: `src/gel_analyzer/api/views.py` (find lane update view)
- Test: `src/gel_analyzer/tests/test_views/test_api_quantification.py`

- [ ] **Step 1: Write failing tests**

```python
def test_lane_downgrade_409_without_force(authenticated_client, calib_lane_with_point):
    lane = calib_lane_with_point
    url = f"/gel-analyzer/api/lanes/{lane.id}/"
    response = authenticated_client.patch(url, {"lane_type": "SAMPLE"}, format="json")
    assert response.status_code == 409
    body = response.json()
    assert "dependent_band_ids" in body and len(body["dependent_band_ids"]) >= 1


def test_lane_downgrade_with_force_purges(authenticated_client, calib_lane_with_point):
    lane = calib_lane_with_point
    url = f"/gel-analyzer/api/lanes/{lane.id}/?force=true"
    response = authenticated_client.patch(url, {"lane_type": "SAMPLE"}, format="json")
    assert response.status_code == 200
    lane.refresh_from_db()
    assert lane.lane_type == "SAMPLE"
    # Bands' quant_points are gone
    from gel_analyzer.models import ProteinQuantCalibrationPoint
    assert ProteinQuantCalibrationPoint.objects.filter(band__lane=lane).count() == 0
```

(Add a `calib_lane_with_point` fixture to `conftest.py` building a CALIBRATION lane with one CALIBRATION-typed band + quant_point.)

- [ ] **Step 2: Run, expect FAIL**.

- [ ] **Step 3: Implement the downgrade logic in the lane update view**

In the view that handles `PATCH /api/lanes/<id>/` (search for it; likely `LaneViewSet.partial_update` or a function-based view in `views.py`):
```python
def partial_update(self, request, *args, **kwargs):
    instance = self.get_object()
    new_type = request.data.get("lane_type")
    force = request.query_params.get("force", "").lower() == "true"

    is_downgrade = (
        new_type
        and instance.lane_type in ("CALIBRATION", "CONTROL")
        and new_type not in ("CALIBRATION", "CONTROL")
    )
    if is_downgrade:
        from gel_analyzer.models import ProteinQuantCalibrationPoint
        dependent_ids = list(
            ProteinQuantCalibrationPoint.objects
            .filter(band__lane=instance)
            .values_list("band_id", flat=True)
        )
        if dependent_ids and not force:
            return Response(
                {
                    "detail": "Lane has calibration points. Pass ?force=true to purge them.",
                    "dependent_band_ids": [str(b) for b in dependent_ids],
                },
                status=409,
            )
        if dependent_ids and force:
            from django.db import transaction
            from gel_analyzer.models import Band
            with transaction.atomic():
                ProteinQuantCalibrationPoint.objects.filter(band__lane=instance).delete()
                Band.objects.filter(lane=instance, band_type="CALIBRATION").update(
                    band_type="OTHER",
                )
    return super().partial_update(request, *args, **kwargs)
```

- [ ] **Step 4: Run tests, verify PASS**.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(api): lane downgrade 409 + ?force=true purge"
```

---

### Task 4.3: GET / preview / save / patch / delete / history endpoints

**Files:**
- Modify: `src/gel_analyzer/api/views.py` (add 6 view functions or methods)
- Modify: `src/gel_analyzer/api/urls.py`
- Test: `src/gel_analyzer/tests/test_views/test_api_quantification.py`

- [ ] **Step 1: Write failing tests for preview + save**

```python
def test_preview_returns_fit_metadata(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/gel-analyzer/api/analyses/{analysis.id}/quantification/preview/"
    response = authenticated_client.post(
        url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["r_squared"] > 0.99


def test_save_creates_active_calibration(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/gel-analyzer/api/analyses/{analysis.id}/quantification/"
    response = authenticated_client.post(
        url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json",
    )
    assert response.status_code == 201
    from gel_analyzer.models import ProteinQuantCalibration
    assert ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).count() == 1


def test_save_then_save_supersedes_previous(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/gel-analyzer/api/analyses/{analysis.id}/quantification/"
    authenticated_client.post(url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json")
    authenticated_client.post(url, {"method": "POLYNOMIAL_2", "unit": "UG", "excluded_band_ids": []}, format="json")
    from gel_analyzer.models import ProteinQuantCalibration
    assert ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).count() == 1


def test_get_returns_active_or_null(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/gel-analyzer/api/analyses/{analysis.id}/quantification/"
    response = authenticated_client.get(url)
    assert response.status_code == 200
    assert response.json()["active"] is None  # nothing saved yet


def test_history_returns_supersedes(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    save_url = f"/gel-analyzer/api/analyses/{analysis.id}/quantification/"
    authenticated_client.post(save_url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json")
    authenticated_client.post(save_url, {"method": "POLYNOMIAL_2", "unit": "UG", "excluded_band_ids": []}, format="json")
    history_url = f"/gel-analyzer/api/analyses/{analysis.id}/quantification/history/"
    response = authenticated_client.get(history_url)
    assert response.status_code == 200
    assert len(response.json()["history"]) == 2
```

(Add `three_calib_points_analysis` fixture: an analysis with 3 CALIBRATION lanes, each with a CALIBRATION band + densitometry + quant_point at loads 5/10/15 µg.)

- [ ] **Step 2: Run, expect 404**.

- [ ] **Step 3: Implement views**

Add to `src/gel_analyzer/api/views.py`:
```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from gel_analyzer.models import GelAnalysis, ProteinQuantCalibration
from gel_analyzer.services.quantification.models import QuantParams
from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService


def _build_full_result(analysis, params: QuantParams):
    """Run a full preview: fit + project samples + project controls."""
    svc = ProteinQuantCalibrationService(params)
    cal_points = svc.collect_calibration_points(analysis)
    result = svc.fit(cal_points, excluded_band_ids=params.excluded_band_ids)
    if not result.success:
        return result, svc
    # Add control projections
    ctrls = svc.collect_control_points(analysis)
    for c in ctrls:
        if c.corrected_area is not None:
            c.predicted_amount = svc.project(c.corrected_area, result)
    result.control_points = ctrls
    # Sample projections
    samples = svc.collect_sample_bands(analysis)
    for s in samples:
        if s.corrected_area is not None:
            s.predicted_amount = svc.project(s.corrected_area, result)
    result.sample_projections = samples
    return result, svc


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def quantification_root(request, analysis_id):
    """GET → active calib + points; POST → save & apply."""
    analysis = GelAnalysis.objects.get(pk=analysis_id)
    if request.method == "GET":
        active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
        return Response({"active": _serialize_calib(active) if active else None})
    # POST = save
    params = QuantParams(
        method=request.data.get("method", "LINEAR"),
        unit=request.data.get("unit", "UG"),
        excluded_band_ids=request.data.get("excluded_band_ids", []),
    )
    result, svc = _build_full_result(analysis, params)
    if not result.success:
        return Response({"detail": result.error_message, **result.to_dict()}, status=422)
    calib = svc.save_active(analysis, result, user=request.user, notes=request.data.get("notes", ""))
    svc.apply_to_analysis(calib)
    return Response(_serialize_calib(calib), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def quantification_preview(request, analysis_id):
    analysis = GelAnalysis.objects.get(pk=analysis_id)
    params = QuantParams(
        method=request.data.get("method", "LINEAR"),
        unit=request.data.get("unit", "UG"),
        excluded_band_ids=request.data.get("excluded_band_ids", []),
    )
    result, _ = _build_full_result(analysis, params)
    return Response(result.to_dict(), status=200 if result.success else 422)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def quantification_detail(request, analysis_id, calib_id):
    calib = ProteinQuantCalibration.objects.get(pk=calib_id, analysis_id=analysis_id)
    if request.method == "PATCH":
        if "excluded_band_ids" in request.data:
            calib.excluded_band_ids = request.data["excluded_band_ids"]
        if "notes" in request.data:
            calib.notes = request.data["notes"]
        calib.save()
        return Response(_serialize_calib(calib))
    # DELETE = deactivate
    from django.utils import timezone
    calib.is_active = False
    calib.superseded_at = timezone.now()
    calib.save(update_fields=["is_active", "superseded_at"])
    return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def quantification_history(request, analysis_id):
    history = ProteinQuantCalibration.objects.filter(analysis_id=analysis_id).order_by("-created_at")
    return Response({"history": [_serialize_calib(c) for c in history]})


def _serialize_calib(c: ProteinQuantCalibration) -> dict:
    return {
        "id": str(c.id),
        "method": c.method,
        "unit": c.unit,
        "coefficients": c.coefficients,
        "r_squared": c.r_squared,
        "equation": c.equation,
        "excluded_band_ids": c.excluded_band_ids,
        "is_active": c.is_active,
        "superseded_at": c.superseded_at.isoformat() if c.superseded_at else None,
        "created_by": c.created_by.username if c.created_by else None,
        "created_at": c.created_at.isoformat(),
        "notes": c.notes,
    }
```

- [ ] **Step 4: Wire URLs**

In `src/gel_analyzer/api/urls.py`, add:
```python
from . import views
urlpatterns += [
    path("analyses/<analysis_id>/quantification/",
         views.quantification_root, name="quantification-root"),
    path("analyses/<analysis_id>/quantification/preview/",
         views.quantification_preview, name="quantification-preview"),
    path("analyses/<analysis_id>/quantification/history/",
         views.quantification_history, name="quantification-history"),
    path("analyses/<analysis_id>/quantification/<uuid:calib_id>/",
         views.quantification_detail, name="quantification-detail"),
]
```

- [ ] **Step 5: Run all API tests**

```
... -m pytest src/gel_analyzer/tests/test_views/test_api_quantification.py -v
```
Iterate until green.

- [ ] **Step 6: Commit**

```bash
git add src/gel_analyzer/api/views.py src/gel_analyzer/api/urls.py src/gel_analyzer/tests/
git commit -m "feat(api): quantification endpoints (GET/POST/preview/history/PATCH/DELETE)"
```

---

## Phase 5 — UI Annotation

### Task 5.1: CSS color tokens

**Files:**
- Modify: `src/gel_analyzer/static/gel_analyzer/css/_gel-viewer.css` (or whichever file holds the existing `gv-prop-type-*` classes — search for it)

- [ ] **Step 1: Find the existing color tokens**

```
... rg "gv-prop-type-sample|gv-prop-type-ladder" src/gel_analyzer/static/
```
Note the file. (Most likely `_gel-viewer.css` or a Tailwind component layer.)

- [ ] **Step 2: Add the new tokens, side by side with existing ones**

```css
.gv-prop-type-calibration       { background-color: #8B5CF6; color: #fff; }
.gv-prop-type-control           { background-color: #06B6D4; color: #fff; }
.gv-band-type-calibration       { color: #8B5CF6; }
.gv-lane-overlay--calibration   { stroke: #8B5CF6; fill: rgba(139, 92, 246, 0.08); }
.gv-lane-overlay--control       { stroke: #06B6D4; fill: rgba(  6, 182, 212, 0.08); }
.gv-table-row--calibration      { background-color: #F5F3FF; }
.gv-table-row--control          { background-color: #ECFEFF; }
```

- [ ] **Step 3: Rebuild CSS**

```
npm run build:css
```

- [ ] **Step 4: Smoke check** — open the annotate view in browser, no JS yet but the badges should render in violet/cyan when a lane has type CALIBRATION/CONTROL (set via Django admin).

- [ ] **Step 5: Commit**

```bash
git add src/gel_analyzer/static/gel_analyzer/css/ src/phoresis_ui/static/phoresis_ui/css/output.css
git commit -m "feat(ui): color tokens for CALIBRATION + CONTROL"
```

---

### Task 5.2: SVG renderer extension for new lane overlay colors

**Files:**
- Modify: `src/gel_analyzer/static/gel_analyzer/js/gel-viewer/renderer.js` (find the function that picks lane stroke/fill by type)

- [ ] **Step 1: Locate the color-picking function**

```
... rg "lane_type|laneType|stroke" src/gel_analyzer/static/gel_analyzer/js/gel-viewer/renderer.js | head -30
```

- [ ] **Step 2: Extend the switch / lookup map with `CALIBRATION` and `CONTROL`**

In whatever block already maps `SAMPLE → blue`, `LADDER → yellow`, `EMPTY → gray`, add:
```js
case 'CALIBRATION': return { stroke: '#8B5CF6', fill: 'rgba(139,92,246,0.08)' };
case 'CONTROL':     return { stroke: '#06B6D4', fill: 'rgba(6,182,212,0.08)' };
```

- [ ] **Step 3: Smoke check** — change a lane's type to CALIBRATION via Django admin, reload the annotate view, observe violet outline.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(viewer): SVG lane overlay colors for CALIBRATION + CONTROL"
```

---

### Task 5.3: Properties Panel — Lane CALIBRATION + loading_volume_ul

**Files:**
- Modify: `src/gel_analyzer/static/gel_analyzer/js/gel-viewer/panels/properties-panel.js` (lines ~165-280, the `_renderLaneProperties` method)

- [ ] **Step 1: Add CALIBRATION option to the lane type dropdown**

Find the lane-type `<select>` block (around line 183) and append:
```html
<option value="CALIBRATION" ${lane.lane_type === 'CALIBRATION' ? 'selected' : ''}>Calibration</option>
```

- [ ] **Step 2: Hide protein_load_ug and protein_load_type when CALIBRATION/CONTROL; show loading_volume_ul**

After the existing `Conditions` section, add a conditional `Loading volume` field:
```html
<div class="gv-prop-field gv-prop-col-2"
     id="prop-loading-volume-section"
     style="display: ${['CALIBRATION', 'CONTROL'].includes(lane.lane_type) ? '' : 'none'};">
    <label for="prop-loading-volume">Loading volume (µL)</label>
    <input type="number" id="prop-loading-volume" data-field="loading_volume_ul"
           class="form-control form-control-sm"
           value="${lane.loading_volume_ul || ''}" step="0.1" min="0" placeholder="—">
</div>
```

In the lane-type change handler (search for `onchange` near `prop-lane-type`), update visibility:
```js
const showLoadingVolume = ['CALIBRATION', 'CONTROL'].includes(newType);
document.getElementById('prop-loading-volume-section').style.display = showLoadingVolume ? '' : 'none';
const loadField = document.getElementById('prop-protein-load')?.closest('.gv-prop-field');
const loadTypeField = document.getElementById('prop-load-type')?.closest('.gv-prop-field');
if (loadField) loadField.style.display = showLoadingVolume ? 'none' : '';
if (loadTypeField) loadTypeField.style.display = showLoadingVolume ? 'none' : '';
```

- [ ] **Step 3: Wire the lane-type downgrade confirmation modal**

When the lane-type select changes from CALIBRATION/CONTROL → other and the lane has dependent points (check by counting bands of type CALIBRATION in the lane), show a JS-level `confirm()` (later upgradeable to a proper modal — keep simple for v1):
```js
async function maybeConfirmLaneTypeChange(currentType, newType, laneId) {
    const isDowngrade = ['CALIBRATION', 'CONTROL'].includes(currentType)
                        && !['CALIBRATION', 'CONTROL'].includes(newType);
    if (!isDowngrade) return true;
    const bands = stateManager.getBandsForLane(laneId);
    const hasPoints = bands.some(b => b.band_type === 'CALIBRATION');
    if (!hasPoints) return true;
    return window.confirm(
        `Cette lane contient des points de calibration. Les valeurs (charge + unité) seront supprimées. Continuer ?`
    );
}
```
And wrap the lane-type change in this guard. On confirm, the API call must include `?force=true` in the query string.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(viewer): lane-level CALIBRATION + loading_volume_ul UI"
```

---

### Task 5.4: Properties Panel — Band CALIBRATION section

**Files:**
- Modify: `src/gel_analyzer/static/gel_analyzer/js/gel-viewer/panels/properties-panel.js` (band rendering block around line 670-760)

- [ ] **Step 1: Add CALIBRATION option to the band-type dropdown**

```html
<option value="CALIBRATION" ${band.band_type === 'CALIBRATION' ? 'selected' : ''}>Calibration Point</option>
```

- [ ] **Step 2: Add a "Calibration" section that appears when band_type === 'CALIBRATION'**

After the existing band fields, render:
```html
<section class="gv-prop-section" id="prop-band-calib-section"
         style="display: ${band.band_type === 'CALIBRATION' ? '' : 'none'};">
    <h6 class="gv-prop-section-title">Calibration</h6>
    <div class="gv-prop-grid">
        <div class="gv-prop-field">
            <label for="prop-band-load-amount">Loaded amount</label>
            <input type="number" id="prop-band-load-amount" data-field="quant_point.load_amount"
                   class="form-control form-control-sm" min="0" step="0.01"
                   value="${band.quant_point?.load_amount ?? ''}" placeholder="—">
        </div>
        <div class="gv-prop-field">
            <label for="prop-band-load-unit">Unit</label>
            <select id="prop-band-load-unit" data-field="quant_point.load_unit" class="form-select form-select-sm"
                    ${activeCalibUnit ? 'disabled' : ''}>
                <option value="UG"    ${(band.quant_point?.load_unit || 'UG') === 'UG' ? 'selected' : ''}>µg</option>
                <option value="UG_ML" ${band.quant_point?.load_unit === 'UG_ML' ? 'selected' : ''}>µg/mL</option>
            </select>
            ${activeCalibUnit ? '<small class="text-muted">Unit fixed by active calibration</small>' : ''}
        </div>
        <div class="gv-prop-field gv-prop-col-2">
            <small id="prop-band-densito-status" class="text-muted">
                ${band.densitometry?.corrected_area
                    ? '✓ Densitometry available'
                    : '⚠ Run densitometry to use this point'}
            </small>
        </div>
    </div>
</section>
```

`activeCalibUnit` is fetched once per session via `apiClient.getActiveQuantCalibration(analysisId)` — cache the unit on the panel instance.

- [ ] **Step 3: Wire the nested PATCH on save**

In the existing save handler that PATCHes `/api/bands/<id>/`, build:
```js
const patchBody = {
    band_type: bandType,
    ...
};
if (bandType === 'CALIBRATION') {
    patchBody.quant_point = {
        load_amount: parseFloat(document.getElementById('prop-band-load-amount').value),
        load_unit: document.getElementById('prop-band-load-unit').value,
    };
}
apiClient.patchBand(bandId, patchBody);
```

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(viewer): band-level CALIBRATION + load_amount UI"
```

---

### Task 5.5: Context menu — Lane Type / Band Type / Set calibration value

**Files:**
- Modify: `src/gel_analyzer/templates/gel_analyzer/analyses/annotate_standalone.html` (lines 469-485 lane group; 506-520 band group; 522-525 set-mw)
- Modify: `src/gel_analyzer/static/gel_analyzer/js/gel-viewer/panels/context-menu.js` (action handler)

- [ ] **Step 1: Add `Calibration` to lane and band groups in the template**

Insert after `data-value="CONTROL"` in the lane group:
```html
<button class="gv-context-menu-item" data-action="set-type" data-value="CALIBRATION">
    <i class="bi bi-droplet-half"></i> Calibration
</button>
```
Insert after `data-value="MW_REFERENCE"` in the band group:
```html
<button class="gv-context-menu-item" data-action="set-band-type" data-value="CALIBRATION">
    <i class="bi bi-droplet-half"></i> Calibration
</button>
```

- [ ] **Step 2: Add the `Set calibration value…` button**

Right after the existing `Set MW…` button (line 522):
```html
<button class="gv-context-menu-item" data-action="set-calibration-value" id="ctx-set-calib-value">
    <i class="bi bi-eyedropper"></i> Set calibration value…
</button>
```

It should be hidden by CSS when the band's type is not CALIBRATION. In `context-menu.js`, in the `show()` method, add:
```js
const item = this.menu.querySelector('#ctx-set-calib-value');
if (item) {
    const sel = this.getSelection();
    const isCalibBand = sel?.type === 'band'
        && this._stateManager?.getBand(sel.id)?.band_type === 'CALIBRATION';
    item.style.display = isCalibBand ? '' : 'none';
}
```

- [ ] **Step 3: Implement the action handler**

In `context-menu.js`, in the `_handleAction` switch, add:
```js
case 'set-calibration-value':
    if (type === 'band') {
        const amountStr = window.prompt('Enter loaded amount:');
        if (!amountStr) break;
        const amount = parseFloat(amountStr);
        if (!isFinite(amount) || amount < 0) {
            this.showMessage('Invalid amount');
            break;
        }
        const unit = window.prompt('Unit (UG or UG_ML):', 'UG');
        if (!['UG', 'UG_ML'].includes(unit)) {
            this.showMessage('Invalid unit');
            break;
        }
        if (this.handlers.onUpdateBand) {
            this.handlers.onUpdateBand(id, {
                band_type: 'CALIBRATION',
                quant_point: { load_amount: amount, load_unit: unit },
            });
        }
    }
    break;
```

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(viewer): context menu Calibration types + Set calibration value"
```

---

## Phase 6 — UI Densitometry modal

### Task 6.1: Modal markup + scaffold

**Files:**
- Create: `src/gel_analyzer/templates/gel_analyzer/includes/_quantification_modal.html`
- Modify: `src/gel_analyzer/templates/gel_analyzer/analyses/densitometry.html` (include the new partial + add the toolbar button)

- [ ] **Step 1: Create the modal partial**

`src/gel_analyzer/templates/gel_analyzer/includes/_quantification_modal.html`:
```html
{# Quantification calibration modal — opened from densitometry.html toolbar. #}
<div class="dm-modal" id="quantification-modal" hidden>
    <div class="dm-modal-backdrop" data-close></div>
    <div class="dm-modal-card dm-modal-card--wide">
        <header class="dm-modal-header">
            <h3>Protein quantification calibration</h3>
            <div class="dm-modal-toolbar">
                <label>Method
                    <select id="qcm-method">
                        <option value="LINEAR">Linear</option>
                        <option value="POLYNOMIAL_2">Polynomial (deg 2)</option>
                        <option value="FOUR_PL">4-PL</option>
                    </select>
                </label>
                <label>Unit
                    <select id="qcm-unit">
                        <option value="UG">µg</option>
                        <option value="UG_ML">µg/mL</option>
                    </select>
                </label>
                <label><input type="checkbox" id="qcm-show-controls-on-curve" checked> Show controls on curve</label>
            </div>
            <button class="dm-modal-close" data-close>×</button>
        </header>
        <div class="dm-modal-grid dm-modal-grid--2x2">
            <section class="dm-modal-cell">
                <h4>Calibration points</h4>
                <table class="dm-table" id="qcm-points-table">
                    <thead><tr><th>Lane</th><th>Load</th><th>Area</th><th>Residual</th><th>✗</th></tr></thead>
                    <tbody></tbody>
                </table>
                <div class="dm-modal-stats">
                    R²: <span id="qcm-r2">—</span> · N: <span id="qcm-n">—</span>
                    <br>Eq: <code id="qcm-equation">—</code>
                </div>
            </section>
            <section class="dm-modal-cell">
                <h4>Calibration curve</h4>
                <canvas id="qcm-curve-chart" width="500" height="350"></canvas>
            </section>
            <section class="dm-modal-cell">
                <h4>Controls / QC</h4>
                <table class="dm-table" id="qcm-controls-table">
                    <thead><tr><th>Lane</th><th>Known</th><th>Predicted</th><th>%Recovery</th></tr></thead>
                    <tbody></tbody>
                </table>
            </section>
            <section class="dm-modal-cell">
                <h4>Samples projected</h4>
                <table class="dm-table" id="qcm-samples-table">
                    <thead><tr><th>Lane</th><th>Sample</th><th>Area</th><th>Estimated</th></tr></thead>
                    <tbody></tbody>
                </table>
            </section>
        </div>
        <footer class="dm-modal-footer">
            <button class="btn btn-secondary" data-close>Cancel</button>
            <button class="btn btn-outline-primary" id="qcm-refit">Refit</button>
            <button class="btn btn-primary" id="qcm-save">Save & apply</button>
        </footer>
    </div>
</div>
```

- [ ] **Step 2: Include in densitometry.html + add toolbar button**

Find the existing toolbar row (probably near the MW calibration button). Insert next to it:
```html
<button class="btn btn-outline-secondary btn-sm" id="open-quantification-modal">
    <i class="bi bi-droplet-half"></i> Quantification
</button>
```

At the bottom of the page (before `</body>` or before `{% endblock %}`):
```html
{% include "gel_analyzer/includes/_quantification_modal.html" %}
```

- [ ] **Step 3: Smoke check** — load densitometry view, click button, modal opens (empty for now). No JS yet so it stays empty.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(densitometry): scaffold quantification calibration modal"
```

---

### Task 6.2: Modal JS class — fetch + render points + curve

**Files:**
- Create: `src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/quantification-modal.js`
- Modify: `src/gel_analyzer/static/gel_analyzer/js/densitometry/densitometry-api-client.js` (add quant calls)
- Modify: `src/gel_analyzer/static/gel_analyzer/js/densitometry/densitometry-app.js` (instantiate the modal)

- [ ] **Step 1: API client extension**

In `densitometry-api-client.js`, append:
```js
async previewQuantification(analysisId, body) {
    return this._post(`/gel-analyzer/api/analyses/${analysisId}/quantification/preview/`, body);
}
async saveQuantification(analysisId, body) {
    return this._post(`/gel-analyzer/api/analyses/${analysisId}/quantification/`, body);
}
async getActiveQuantification(analysisId) {
    return this._get(`/gel-analyzer/api/analyses/${analysisId}/quantification/`);
}
```

- [ ] **Step 2: Modal class skeleton**

`quantification-modal.js`:
```js
(function (global) {
    'use strict';

    class QuantificationModal {
        constructor({ apiClient, analysisId, eventBus }) {
            this.api = apiClient;
            this.analysisId = analysisId;
            this.bus = eventBus;
            this.el = document.getElementById('quantification-modal');
            this.lastResult = null;
            this._wire();
        }

        open() {
            this.el.hidden = false;
            this.refit();
        }

        close() {
            this.el.hidden = true;
        }

        _wire() {
            this.el.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => this.close()));
            document.getElementById('qcm-refit').addEventListener('click', () => this.refit());
            document.getElementById('qcm-save').addEventListener('click', () => this.save());
            ['qcm-method', 'qcm-unit'].forEach(id => {
                document.getElementById(id).addEventListener('change', () => this.refit());
            });
        }

        async refit() {
            const body = this._readForm();
            const r = await this.api.previewQuantification(this.analysisId, body);
            this.lastResult = r;
            this._render(r);
        }

        async save() {
            if (!this.lastResult || !this.lastResult.success) return;
            const body = this._readForm();
            const calib = await this.api.saveQuantification(this.analysisId, body);
            this.bus.emit('QUANT_CALIBRATION_CHANGED', { calib });
            this.close();
        }

        _readForm() {
            const excluded = Array.from(document.querySelectorAll('#qcm-points-table input[type=checkbox]:checked'))
                                  .map(cb => cb.dataset.bandId);
            return {
                method: document.getElementById('qcm-method').value,
                unit: document.getElementById('qcm-unit').value,
                excluded_band_ids: excluded,
            };
        }

        _render(r) {
            this._renderPointsTable(r.calibration_points || []);
            this._renderControlsTable(r.control_points || []);
            this._renderSamplesTable(r.sample_projections || []);
            document.getElementById('qcm-r2').textContent = r.r_squared?.toFixed(4) ?? '—';
            document.getElementById('qcm-n').textContent =
                (r.calibration_points || []).filter(p => !p.is_excluded).length;
            document.getElementById('qcm-equation').textContent = r.equation || '—';
            this._renderCurve(r);
            const saveBtn = document.getElementById('qcm-save');
            saveBtn.disabled = !r.success;
        }

        _renderPointsTable(points) {
            const tbody = document.querySelector('#qcm-points-table tbody');
            tbody.innerHTML = points.map(p => `
                <tr class="${p.is_excluded ? 'dm-row-ghost' : ''}">
                    <td>${p.lane_number}</td>
                    <td>${p.load_amount} ${p.load_unit}</td>
                    <td>${p.corrected_area?.toFixed(1) ?? '—'}</td>
                    <td>${p.residual_pct ?? '—'}</td>
                    <td><input type="checkbox" data-band-id="${p.band_id}" ${p.is_excluded ? 'checked' : ''}></td>
                </tr>
            `).join('');
            tbody.querySelectorAll('input[type=checkbox]').forEach(cb => {
                cb.addEventListener('change', () => this._debouncedRefit());
            });
        }

        _renderControlsTable(controls) {
            const tbody = document.querySelector('#qcm-controls-table tbody');
            tbody.innerHTML = controls.map(c => `
                <tr class="${c.out_of_spec ? 'dm-row-warn' : ''}">
                    <td>${c.lane_number}</td>
                    <td>${c.known_amount}</td>
                    <td>${c.predicted_amount?.toFixed(2) ?? '—'}</td>
                    <td>${c.recovery_pct ?? '—'}%</td>
                </tr>
            `).join('');
        }

        _renderSamplesTable(samples) {
            const tbody = document.querySelector('#qcm-samples-table tbody');
            tbody.innerHTML = samples.map(s => `
                <tr>
                    <td>${s.lane_number}</td>
                    <td>—</td>
                    <td>${s.corrected_area?.toFixed(1) ?? '—'}</td>
                    <td>${s.estimated_amount?.toFixed(2) ?? '—'}</td>
                </tr>
            `).join('');
        }

        _renderCurve(r) {
            // Use Chart.js (already vendored). Build a scatter dataset for fit points,
            // a line dataset for the curve, plus optional control + sample scatter.
            const canvas = document.getElementById('qcm-curve-chart');
            if (!canvas) return;
            // ... If the project doesn't have Chart.js, fall back to a simple SVG scatter.
            // Implementation deferred — see Task 6.3 for the chart.
        }

        _debouncedRefit() {
            clearTimeout(this._refitTimer);
            this._refitTimer = setTimeout(() => this.refit(), 200);
        }
    }

    global.QuantificationModal = QuantificationModal;
})(window);
```

- [ ] **Step 3: Wire from densitometry-app.js**

```js
const quantModal = new QuantificationModal({
    apiClient: this.api,
    analysisId: this.analysisId,
    eventBus: this.bus,
});
document.getElementById('open-quantification-modal').addEventListener('click', () => quantModal.open());
this.bus.on('QUANT_CALIBRATION_CHANGED', () => this.refreshPanels());
```

- [ ] **Step 4: Add `QUANT_CALIBRATION_CHANGED` to the event bus**

In `densitometry-event-bus.js`, register the new event constant alongside existing ones.

- [ ] **Step 5: Smoke check** — open modal, click Refit, observe tables populated.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(densitometry): quantification modal — fetch + render"
```

---

### Task 6.3: Calibration curve chart in modal

**Files:**
- Modify: `quantification-modal.js` `_renderCurve` method

- [ ] **Step 1: Verify Chart.js is vendored**

```
... rg "Chart.js|chart.js|chart.min.js" src/gel_analyzer/static/gel_analyzer/js/vendor/
```
If present, use it. If not, use a small custom Canvas2D plot — see step below.

- [ ] **Step 2: Implement `_renderCurve` with Chart.js (or equivalent)**

```js
_renderCurve(r) {
    const canvas = document.getElementById('qcm-curve-chart');
    if (!canvas || !r.calibration_points) return;
    if (this.chart) this.chart.destroy();
    const ctx = canvas.getContext('2d');
    const fitPoints = r.calibration_points.filter(p => !p.is_excluded && p.corrected_area != null)
                       .map(p => ({ x: p.corrected_area, y: p.load_amount }));
    const ghostPoints = r.calibration_points.filter(p => p.is_excluded && p.corrected_area != null)
                       .map(p => ({ x: p.corrected_area, y: p.load_amount }));
    const showCtrls = document.getElementById('qcm-show-controls-on-curve').checked;
    const ctrls = showCtrls ? r.control_points
                       .filter(c => c.corrected_area != null && c.predicted_amount != null)
                       .map(c => ({ x: c.corrected_area, y: c.predicted_amount })) : [];
    const samples = r.sample_projections
                       .filter(s => s.corrected_area != null && s.estimated_amount != null)
                       .map(s => ({ x: s.corrected_area, y: s.estimated_amount }));
    // Build curve line: 50 evaluation points between min and max area
    const allAreas = [...fitPoints, ...ctrls, ...samples].map(p => p.x);
    const xMin = Math.min(...allAreas), xMax = Math.max(...allAreas);
    const curveData = [];
    for (let i = 0; i <= 50; i++) {
        const x = xMin + (xMax - xMin) * (i / 50);
        const y = this._evalCurve(r, x);
        if (y !== null) curveData.push({ x, y });
    }
    this.chart = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [
                { label: 'Calibration', data: fitPoints, backgroundColor: '#8B5CF6', pointRadius: 5 },
                { label: 'Excluded',    data: ghostPoints, backgroundColor: 'rgba(139,92,246,0.3)', pointRadius: 5 },
                { label: 'Controls',    data: ctrls, backgroundColor: '#06B6D4', pointStyle: 'rectRot', pointRadius: 6 },
                { label: 'Samples',     data: samples, backgroundColor: '#9CA3AF', pointStyle: 'crossRot', pointRadius: 5 },
                { label: 'Fit', type: 'line', data: curveData, borderColor: '#8B5CF6', borderWidth: 2, fill: false, pointRadius: 0 },
            ],
        },
        options: {
            scales: { x: { title: { display: true, text: 'Corrected area' } },
                      y: { title: { display: true, text: `Amount (${r.unit === 'UG' ? 'µg' : 'µg/mL'})` } } },
        },
    });
}

_evalCurve(r, x) {
    if (r.method === 'LINEAR') return r.coefficients.a * x + r.coefficients.b;
    if (r.method === 'POLYNOMIAL_2') {
        const [a, b, c] = r.coefficients.coeffs;
        return a * x * x + b * x + c;
    }
    if (r.method === 'FOUR_PL') {
        const { a, d, c, b } = r.coefficients;
        return d + (a - d) / (1 + Math.pow(x / c, b));
    }
    return null;
}
```

If Chart.js is not vendored, use a fallback Canvas2D drawing — much simpler scatter + polyline. Don't add a new CDN/dep.

- [ ] **Step 3: Hook the show-controls-on-curve checkbox to re-render**

```js
document.getElementById('qcm-show-controls-on-curve')
    .addEventListener('change', () => this._render(this.lastResult));
```

- [ ] **Step 4: Smoke check** — open modal, observe curve.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(densitometry): quantification calibration curve chart"
```

---

## Phase 7 — UI Densitometry tabs + results table

### Task 7.1: Chromatogram panel tabs

**Files:**
- Modify: `src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/chromatogram-panel.js`
- Modify: `src/gel_analyzer/templates/gel_analyzer/analyses/densitometry.html` (chromatogram panel block)

- [ ] **Step 1: Add tab markup**

Above the existing chromatogram canvas, insert:
```html
<div class="dm-tabs" role="tablist">
    <button class="dm-tab active" data-tab="chromatogram">Chromatogram</button>
    <button class="dm-tab" data-tab="poi-purity">POI Purity</button>
    <button class="dm-tab" data-tab="quantification">Quantification curve</button>
</div>
<div class="dm-tab-pane active" data-tab-pane="chromatogram">
    <!-- existing chromatogram canvas -->
</div>
<div class="dm-tab-pane" data-tab-pane="poi-purity" hidden>
    <canvas id="dm-poi-purity-chart"></canvas>
</div>
<div class="dm-tab-pane" data-tab-pane="quantification" hidden>
    <canvas id="dm-quantification-chart"></canvas>
    <div class="dm-tab-empty" id="dm-quantification-empty" hidden>
        No active quantification calibration. Open Quantification modal to set up.
    </div>
</div>
```

- [ ] **Step 2: Wire tab switching with `safeLocalGet/safeLocalSet`**

In `chromatogram-panel.js`, add at constructor end:
```js
this._setupTabs();
```
And the method:
```js
_setupTabs() {
    const KEY = 'phoresis.densito.chromatogramTab';
    const saved = (typeof safeLocalGet === 'function' && safeLocalGet(KEY)) || 'chromatogram';
    this._activateTab(saved);
    this.container.querySelectorAll('.dm-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            this._activateTab(tab);
            if (typeof safeLocalSet === 'function') safeLocalSet(KEY, tab);
        });
    });
}
_activateTab(tab) {
    this.container.querySelectorAll('.dm-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    this.container.querySelectorAll('.dm-tab-pane').forEach(p => {
        const match = p.dataset.tabPane === tab;
        p.hidden = !match;
        p.classList.toggle('active', match);
    });
    if (tab === 'quantification') this._renderQuantificationTab();
}
```

- [ ] **Step 3: Render quantification tab content**

```js
async _renderQuantificationTab() {
    const data = await this.api.getActiveQuantification(this.analysisId);
    const empty = document.getElementById('dm-quantification-empty');
    const canvas = document.getElementById('dm-quantification-chart');
    if (!data?.active) {
        empty.hidden = false;
        canvas.style.display = 'none';
        return;
    }
    empty.hidden = true;
    canvas.style.display = '';
    // Fetch a preview to get full point/control/sample structure for the chart
    const r = await this.api.previewQuantification(this.analysisId, {
        method: data.active.method, unit: data.active.unit,
        excluded_band_ids: data.active.excluded_band_ids,
    });
    // Reuse the QuantificationModal._renderCurve logic — extract to a shared helper
    // file (e.g. quantification-curve-renderer.js) if duplication grows.
    QuantificationCurveRenderer.render(canvas, r);
}
```
And extract `_renderCurve` from the modal into `static/gel_analyzer/js/densitometry/panels/quantification-curve-renderer.js` so both can call it.

- [ ] **Step 4: Subscribe to `QUANT_CALIBRATION_CHANGED`**

```js
this.bus.on('QUANT_CALIBRATION_CHANGED', () => this._renderQuantificationTab());
```

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(densitometry): chromatogram panel tabs (POI / Quantification curve)"
```

---

### Task 7.2: Results table refactor — lane-level + drill-down + presets

**Files:**
- Modify: `src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/results-table-panel.js` (full rewrite of the rendering function — keep the API surface stable)

- [ ] **Step 1: Read the current implementation to understand the data shape it consumes**

```
... rg "render|table|td|tr" src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/results-table-panel.js | head -40
```

- [ ] **Step 2: Replace per-band rendering with per-lane**

Render structure:
```html
<table class="dm-table dm-table--lane-level">
    <thead>
        <tr>
            <th colspan="3" class="dm-section-identity">Identity</th>
            <th colspan="4" class="dm-section-densito">Densitometry</th>
            <th colspan="2" class="dm-section-quant">Quantification</th>
            <th colspan="2" class="dm-section-quality">Quality</th>
        </tr>
        <tr>
            <th>Lane#</th><th>Type</th><th>Sample</th>
            <th>Total area</th><th># bands</th><th>POI area</th><th>% purity</th>
            <th>Estimated amount</th><th>Recovery %</th>
            <th>Avg fit R²</th><th>Flag</th>
        </tr>
    </thead>
    <tbody><!-- one row per lane, see render fn --></tbody>
</table>
```

Each lane row gets data attributes `data-lane-id` + `data-lane-type` and a click expander that injects a sub-table with bands. Use a single state-mutation function to avoid double-rendering.

Pseudo-render:
```js
_renderLaneRow(lane, summary, activeCalib) {
    const tint = `dm-row--${lane.lane_type.toLowerCase()}`;
    const estAmount = activeCalib && summary.poi_estimated_amount
        ? `${summary.poi_estimated_amount.toFixed(2)} ${activeCalib.unit === 'UG' ? 'µg' : 'µg/mL'}`
        : '—';
    const recovery = (lane.lane_type === 'CONTROL' && summary.recovery_pct != null)
        ? `${summary.recovery_pct.toFixed(0)}%` : '—';
    const flag = (lane.lane_type === 'CONTROL' && (summary.recovery_pct < 80 || summary.recovery_pct > 120))
        ? '<span class="dm-flag dm-flag-warn" title="Out-of-spec recovery">⚠</span>' : '';
    return `
        <tr class="${tint}" data-lane-id="${lane.id}">
            <td class="dm-sticky-left">${lane.lane_number}</td>
            <td class="dm-sticky-left"><span class="gv-prop-type-${lane.lane_type.toLowerCase()}">${lane.lane_type_display}</span></td>
            <td>${lane.sample_name || ''}</td>
            <td>${summary.total_integrated_area?.toFixed(1) ?? '—'}</td>
            <td>${summary.band_count}</td>
            <td>${summary.poi_integrated_area?.toFixed(1) ?? '—'}</td>
            <td>${summary.poi_percentage?.toFixed(1) ?? '—'}%</td>
            <td>${estAmount}</td>
            <td>${recovery}</td>
            <td>${summary.avg_fit_r_squared?.toFixed(3) ?? '—'}</td>
            <td>${flag}</td>
        </tr>
    `;
}
```

- [ ] **Step 3: Drill-down expand handler**

On row click, build a sub-table of bands for that lane and insert as a new `<tr>` after the lane row. On second click, collapse.

- [ ] **Step 4: Column presets**

Add a small toolbar at the top of the table:
```html
<select id="dm-table-preset">
    <option value="standard">Standard</option>
    <option value="minimal">Minimal</option>
    <option value="full">Full</option>
</select>
```
Persist via `safeLocalSet('phoresis.densito.tablePreset', value)`. Apply by toggling `display: none` on chosen `<th>` / `<td>` columns.

- [ ] **Step 5: Subscribe to `QUANT_CALIBRATION_CHANGED`** so the table re-renders when calibration changes.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(densitometry): results table refactor (lane-level + drill-down + presets)"
```

---

## Phase 8 — UI Comparison

### Task 8.1: Comparison table refactor

**Files:**
- Modify: `src/gel_analyzer/templates/gel_analyzer/comparisons/compare.html`
- Modify: `src/gel_analyzer/static/gel_analyzer/js/sample-comparison/sample-comparison-app.js`

- [ ] **Step 1: Replace flat table headers with grouped headers**

```html
<thead>
    <tr>
        <th colspan="2" class="cmp-sticky-left">&nbsp;</th>
        <th colspan="3" class="cmp-section-identity">Identity</th>
        <th colspan="4" class="cmp-section-densito">Densitometry</th>
        <th colspan="3" class="cmp-section-quant" id="cmp-quant-header">Quantification</th>
        <th colspan="3" class="cmp-section-quality">Quality</th>
    </tr>
    <tr>
        <th class="cmp-sticky-left">Lane#</th>
        <th class="cmp-sticky-left">Type</th>
        <th>Sample</th><th>Condition</th><th>Loading (µg)</th>
        <th>Loading vol (µL)</th>
        <th>Total area</th><th># bands</th><th>POI area</th><th>% purity</th>
        <th>Est. amount</th><th>%Rec</th><th>Calib method</th>
        <th>Avg fit R²</th><th># MW markers</th><th>Status</th>
    </tr>
</thead>
```

- [ ] **Step 2: Hide the Quantification group when no compared analysis has an active calibration**

```js
const anyActive = analyses.some(a => a.active_quant_calibration);
document.getElementById('cmp-quant-header').style.display = anyActive ? '' : 'none';
this.table.querySelectorAll('.cmp-section-quant').forEach(td => td.style.display = anyActive ? '' : 'none');
```

- [ ] **Step 3: Tint rows by lane type using existing `gv-table-row--*` classes** (added in Task 5.1).

- [ ] **Step 4: Add the "Show only quantified lanes" filter checkbox**

```html
<label class="cmp-toolbar-filter">
    <input type="checkbox" id="cmp-only-quant"> Show only quantified lanes
</label>
```
Handler: `this.table.querySelectorAll('tr[data-row-type=lane]').forEach(r => r.hidden = filter && !r.dataset.estimatedAmount);`.

- [ ] **Step 5: Persist column preset** via `safeLocalSet('phoresis.compare.tableColumns', preset)`.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(compare): grouped table + quantification cols + tint rows"
```

---

## Phase 9 — Reports

### Task 9.1: Quantification chart helper (PNG)

**Files:**
- Create: `src/gel_analyzer/services/report/quantification_chart.py`
- Test: `src/gel_analyzer/tests/test_services/test_quantification_chart.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from io import BytesIO
from PIL import Image

from gel_analyzer.services.report.quantification_chart import build_calibration_curve_png


def test_returns_png_bytes():
    points = [(1000, 5), (2000, 10), (3000, 15)]
    coeffs = {"a": 0.005, "b": 0}
    blob = build_calibration_curve_png(
        points=points, coeffs=coeffs, method="LINEAR",
        unit_label="µg", controls=[(1500, 7.5)], samples=[(2500, 12.5)],
    )
    img = Image.open(BytesIO(blob))
    assert img.format == "PNG"
    assert img.size[0] > 0 and img.size[1] > 0
```

- [ ] **Step 2: Run, expect FAIL**.

- [ ] **Step 3: Implement using matplotlib** (already in deps via scipy)

```python
"""Build the calibration-curve PNG for the report (Word + PowerPoint)."""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def build_calibration_curve_png(
    *, points: list[tuple[float, float]], coeffs: dict, method: str,
    unit_label: str, controls: list[tuple[float, float]] | None = None,
    samples: list[tuple[float, float]] | None = None, width: int = 800, height: int = 600,
) -> bytes:
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ax.scatter(xs, ys, c="#8B5CF6", s=50, label="Calibration", zorder=3)
    if controls:
        ax.scatter([c[0] for c in controls], [c[1] for c in controls],
                   c="#06B6D4", marker="D", s=60, label="Controls", zorder=3)
    if samples:
        ax.scatter([s[0] for s in samples], [s[1] for s in samples],
                   c="#9CA3AF", marker="x", s=40, label="Samples", zorder=2)
    if xs:
        x_eval = np.linspace(min(xs), max(xs), 100)
        if method == "LINEAR":
            y_eval = coeffs["a"] * x_eval + coeffs["b"]
        elif method == "POLYNOMIAL_2":
            y_eval = np.polyval(coeffs["coeffs"], x_eval)
        elif method == "FOUR_PL":
            a, d, c, b = coeffs["a"], coeffs["d"], coeffs["c"], coeffs["b"]
            y_eval = d + (a - d) / (1 + (x_eval / c) ** b)
        else:
            y_eval = None
        if y_eval is not None:
            ax.plot(x_eval, y_eval, c="#8B5CF6", linewidth=2, label="Fit", zorder=1)
    ax.set_xlabel("Corrected area")
    ax.set_ylabel(f"Amount ({unit_label})")
    ax.set_title("Protein quantification calibration")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()
```

- [ ] **Step 4: Test passes.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(report): calibration curve PNG via matplotlib"
```

---

### Task 9.2: Data collector method

**Files:**
- Modify: `src/gel_analyzer/services/report/densitometry_data_collector.py`

- [ ] **Step 1: Add a method**

```python
def collect_quantification_data(self, analysis):
    """Return a dict ready to be consumed by the 3 builders."""
    from gel_analyzer.models import ProteinQuantCalibration
    from gel_analyzer.services.quantification.models import QuantParams
    from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

    active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
    if active is None:
        return None
    svc = ProteinQuantCalibrationService(QuantParams(method=active.method, unit=active.unit))
    cal = svc.collect_calibration_points(analysis)
    result = svc.fit(cal, excluded_band_ids=active.excluded_band_ids)
    if not result.success:
        return None
    ctrls = svc.collect_control_points(analysis)
    for c in ctrls:
        if c.corrected_area is not None:
            c.predicted_amount = svc.project(c.corrected_area, result)
    samples = svc.collect_sample_bands(analysis)
    for s in samples:
        if s.corrected_area is not None:
            s.predicted_amount = svc.project(s.corrected_area, result)
    # Build curve PNG once and cache
    from .quantification_chart import build_calibration_curve_png
    png = build_calibration_curve_png(
        points=[(p.corrected_area, p.load_amount) for p in cal if not p.is_excluded and p.corrected_area is not None],
        coeffs=active.coefficients, method=active.method,
        unit_label="µg" if active.unit == "UG" else "µg/mL",
        controls=[(c.corrected_area, c.predicted_amount) for c in ctrls if c.predicted_amount is not None],
        samples=[(s.corrected_area, s.predicted_amount) for s in samples if s.predicted_amount is not None],
    )
    return {
        "calibration": active,
        "result": result,
        "controls": ctrls,
        "samples": samples,
        "curve_png": png,
    }
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(report): collect_quantification_data on data collector"
```

---

### Task 9.3: Word builder section

**Files:**
- Modify: `src/gel_analyzer/services/report/densitometry_builder.py`

- [ ] **Step 1: Read the existing builder to follow its patterns** (sections, styles).

- [ ] **Step 2: Add a new method** at the right insertion point (after POI Purity):

```python
def _add_quantification_section(self, doc, data):
    if data is None:
        return
    doc.add_heading("Quantification", level=1)
    calib = data["calibration"]
    p = doc.add_paragraph()
    p.add_run("Method: ").bold = True; p.add_run(calib.method); p.add_run("    ")
    p.add_run("Unit: ").bold = True; p.add_run(calib.unit); p.add_run("    ")
    p.add_run("R²: ").bold = True; p.add_run(f"{calib.r_squared:.4f}")
    doc.add_paragraph(calib.equation, style="Intense Quote")
    # Calibration table
    doc.add_heading("Calibration points", level=2)
    self._render_calibration_table(doc, data["result"].calibration_points, calib.unit)
    # Curve PNG
    doc.add_heading("Calibration curve", level=2)
    from io import BytesIO
    doc.add_picture(BytesIO(data["curve_png"]), width=docx.shared.Inches(6))
    # Controls
    if data["controls"]:
        doc.add_heading("Quality controls", level=2)
        self._render_controls_table(doc, data["controls"], calib.unit)
    # Samples
    doc.add_heading("Sample quantification", level=2)
    self._render_sample_quant_table(doc, data["samples"], calib.unit)
```

(Implement the `_render_*_table` helpers using the existing python-docx table API matching the style of nearby tables in the file.)

Call `_add_quantification_section(doc, self.data_collector.collect_quantification_data(analysis))` from the main builder method, just after the POI Purity section.

- [ ] **Step 3: Smoke test** — manually build a Word report on a fully populated analysis, open it, verify the section renders.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(report): Word quantification section"
```

---

### Task 9.4: Excel builder sheets

**Files:**
- Modify: `src/gel_analyzer/services/report/densitometry_excel_builder.py`

- [ ] **Step 1: Add three new sheets** after the existing ones, gated on `data is not None`:

```python
def _add_quantification_sheets(self, wb, data):
    if data is None:
        return
    calib = data["calibration"]
    # 1. Quantification_Calibration
    ws = wb.create_sheet("Quantification_Calibration")
    ws.append(["Method", calib.method])
    ws.append(["Unit", calib.unit])
    ws.append(["Equation", calib.equation])
    ws.append(["R²", round(calib.r_squared, 6)])
    ws.append(["N points", sum(1 for p in data["result"].calibration_points if not p.is_excluded)])
    ws.append([])
    ws.append(["Lane", "Load amount", "Unit", "Corrected area", "Residual %", "Excluded"])
    for p in data["result"].calibration_points:
        ws.append([p.lane_number, p.load_amount, p.load_unit, p.corrected_area,
                   round((p.residual / p.load_amount) * 100, 2) if p.residual and p.load_amount else None,
                   p.is_excluded])
    # 2. Quantification_Controls
    ws = wb.create_sheet("Quantification_Controls")
    ws.append(["Lane", "Known amount", "Predicted amount", "Recovery %", "Out of spec"])
    for c in data["controls"]:
        recov = (c.predicted_amount / c.load_amount) * 100 if c.predicted_amount and c.load_amount else None
        ws.append([c.lane_number, c.load_amount, c.predicted_amount,
                   round(recov, 2) if recov else None,
                   recov is not None and not (80 <= recov <= 120)])
    # 3. Quantification_Samples
    ws = wb.create_sheet("Quantification_Samples")
    ws.append(["Lane", "Band ID", "Area", f"Estimated ({calib.unit})"])
    for s in data["samples"]:
        ws.append([s.lane_number, s.band_id, s.corrected_area, s.predicted_amount])
```

Wire it from the main builder method.

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(report): Excel quantification sheets"
```

---

### Task 9.5: PowerPoint slide

**Files:**
- Modify: `src/gel_analyzer/services/report/densitometry_pptx_builder.py`

- [ ] **Step 1: Add a slide** after the POI Purity slide, two-column layout (curve + KPI box + mini-table). Use `python-pptx`'s `add_slide`, `add_picture` (from BytesIO of `data["curve_png"]`), and `add_table` for the top-8 sample table.

```python
def _add_quantification_slide(self, prs, data):
    if data is None:
        return
    layout = prs.slide_layouts[5]  # Title only
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = "Quantification"
    from io import BytesIO
    from pptx.util import Inches
    slide.shapes.add_picture(BytesIO(data["curve_png"]), Inches(0.5), Inches(1.2), Inches(5.5))
    # KPI box
    txBox = slide.shapes.add_textbox(Inches(6.2), Inches(1.2), Inches(3.0), Inches(1.5))
    tf = txBox.text_frame
    calib = data["calibration"]
    tf.text = f"R² = {calib.r_squared:.4f}"
    tf.add_paragraph().text = f"N = {sum(1 for p in data['result'].calibration_points if not p.is_excluded)}"
    if data["controls"]:
        recoveries = [
            (c.predicted_amount / c.load_amount) * 100
            for c in data["controls"] if c.predicted_amount and c.load_amount
        ]
        if recoveries:
            tf.add_paragraph().text = f"Mean recovery = {sum(recoveries) / len(recoveries):.1f}%"
    # Mini sample table top 8
    samples = sorted(data["samples"], key=lambda s: s.predicted_amount or 0, reverse=True)[:8]
    tbl_shape = slide.shapes.add_table(rows=len(samples) + 1, cols=3,
                                        left=Inches(6.2), top=Inches(2.8), width=Inches(3.5), height=Inches(3)).table
    tbl_shape.cell(0, 0).text = "Lane"; tbl_shape.cell(0, 1).text = "Area"; tbl_shape.cell(0, 2).text = f"Est. ({calib.unit})"
    for i, s in enumerate(samples, start=1):
        tbl_shape.cell(i, 0).text = str(s.lane_number)
        tbl_shape.cell(i, 1).text = f"{s.corrected_area:.0f}"
        tbl_shape.cell(i, 2).text = f"{s.predicted_amount:.2f}" if s.predicted_amount else "—"
```

Wire from the main builder.

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(report): PowerPoint quantification slide"
```

---

## Phase 10 — End-to-end smoke test

### Task 10.1: Manual smoke checklist

**Files:** none (manual run + screenshots)

- [ ] **Step 1: Re-run the full Python test suite**

```
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest -v
```
Expected: all green except the documented xfails (scipy 1.14 + `BandDetectionParams`).

- [ ] **Step 2: Lint + format**

```
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 3: Manual run**

  1. Start dev: `pwsh scripts/phoresis.ps1 up` (or native runserver + worker).
  2. Upload a gel with at least 3 ladder + 3 calibration + 1 control + 2 sample lanes.
  3. Annotate: mark calibration lanes as CALIBRATION + their POI band as CALIBRATION + load (5/10/20 µg). Mark control lane as CONTROL + its band as CALIBRATION + load 10 µg.
  4. Run densitometry.
  5. Open Quantification modal: click Refit. Verify R² > 0.9, control row shows recovery near 100%, sample rows show predicted amounts.
  6. Save & apply. Verify chromatogram → Quantification curve tab now shows the curve. Verify results-table shows the Quantification group with values.
  7. Open Comparison view with 2 analyses. Verify the Quantification column group is visible and tinted rows.
  8. Generate Word, Excel, PowerPoint reports. Open all three. Verify each contains a Quantification section / sheet / slide with the curve PNG, calibration table, controls, samples.

- [ ] **Step 4: Document results in the PR description (or session notes).**

- [ ] **Step 5: Final commit if any tweak needed; otherwise done.**

---

## Self-review notes (post-implementation)

After all tasks are done, before opening a PR:

- Confirm no `Lane.LaneType` choice or `Band.BandType` choice was hardcoded in tests outside of the new test file (run `grep -rn "lane_type__in" src/gel_analyzer/` and audit hits).
- Confirm `properties-panel.js` and `densitometry.html` weren't accidentally split (out-of-scope per spec §12).
- Confirm `services/calibration/service.py` MW-calibration tests count is exactly the same as the baseline captured in Task 2.1 Step 1.
- Confirm the four migrations are idempotent in both directions: run `manage.py migrate gel_analyzer <previous>` and back to head — no errors.
- Re-read the spec one last time and check each section against the merged code.

---

## Appendix A — Quick command cheat sheet

```bash
# Run all tests
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest -v

# Run only quantification tests
... -m pytest -v -k quantification

# Generate + apply migrations
... manage.py makemigrations gel_analyzer
... manage.py migrate

# Rebuild CSS after token additions
npm run build:css

# Lint
uv run ruff check .
```
