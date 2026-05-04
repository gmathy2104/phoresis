# Phoresis — Phase 4 (Heavy Viewers + DRF API + E2E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the three heavy viewers (annotation editor, densitometry view, comparison view), the entire API surface (DRF viewsets + ~50 non-DRF JSON endpoints), and the report-generation pipeline (Word/Excel/PowerPoint exports) — wrapped in Tailwind chrome around the preserved JS-driven internals — and verify the whole thing with a Playwright end-to-end test that exercises the full gel workflow. Tagged `v0.4.0`.

**Architecture:** "Tailwind chrome wrapper" pattern: the page-level header, sidebar, breadcrumbs, side panels, and toolbars are rebuilt with Phoresis design system templatetags, while the JS-driven canvas inside (annotation editor, electropherogram, comparison panels) keeps its 100% original implementation — same DOM IDs, same CSS classes (`gv-*`, `gel-*`, `dm-*`), same JS files (already copied to `static/` in Phase 2). The seam is clean because the JS internals scope themselves under a single root container; we only rebuild what surrounds that container.

The Phase 3 shell pages (image list/upload/detail, analysis list/create) stay; Phase 4 fills in the missing pieces (analysis detail, annotate, densitometry, comparison views) plus the full API surface that those viewers and external clients consume.

**Tech Stack delta:** Adds `python-docx`, `openpyxl`, `python-pptx` (report generation, scipy/matplotlib already pulled in by Phase 2), `playwright`, `pytest-playwright`. No frontend framework changes — Tailwind 4 + HTMX 2 + Alpine.js 3 + D3 v7 + SVG.js 3.x + ONNX Runtime Web are all already in place from Phase 2's static copy.

**Source repo for ports:** `$DSHUB = C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/`. **Target:** `$PHOR = .../phoresis/.claude/worktrees/hopeful-franklin-e45f1b/`.

---

## Build Order Rationale

Phase 4 has tighter inter-task coupling than earlier phases — almost every later piece depends on the API surface and report services. Order:

1. **Deps + scope check** (Task 1) — pulls in python-docx / openpyxl / python-pptx / playwright. Required before any report-builder import works.
2. **services/report port** (Task 2) — 14 files + 5 markdown guides; cleaned of `process_sample` references already in Phase 2's pattern.
3. **Non-DRF API port** (Task 3) — `views/api.py` (4,078 LOC) + 3 sibling API modules. Strips `search_samples_json`, `?samples=` mode, and ProcessSample-shape lane handling. The annotation editor's JS calls these endpoints, so they have to be in place before Task 6 (heavy templates) is testable end-to-end.
4. **DRF API port** (Task 4) — `api/` subpackage (1,015 LOC). Independent of Task 3 — DRF endpoints are a parallel surface.
5. **HTML views upgrade** (Task 5) — replaces Phase 3 stubs with full `analysis_detail_view` + `analysis_annotate_view` + ports `comparison`, `densitometry`, `studio`, `training` views.
6. **Heavy templates** (Task 6) — wraps `annotate_standalone.html`, `densitometry.html`, `comparisons/compare.html` in Tailwind chrome. Plus `analyses/detail.html`, `comparisons/list.html`, `images/delete_modal` HTMX partial, and the analyse-page includes.
7. **URL wiring** (Task 7) — populates `urls.py` with everything from Tasks 3-5. Triggers all view tests.
8. **Test ports** (Task 8) — `test_drf_api.py` + `test_views/` files from source, cleaned of process_development fixtures.
9. **Playwright e2e** (Task 9) — installs browsers, writes the golden-path e2e (login → upload → create analysis → place lanes → save → logout). Spec §11.4 #1.
10. **End-to-end smoke + tag v0.4.0** (Task 10) — ruff/pytest/pre-commit, manual browser walk through every viewer, tag.

---

## Standing Find/Replace Catalogue (Phase 4 additions)

Reuses R1-R10 from Phase 2 plus these Phase-4-specific transformations:

| # | Find | Replace | Notes |
|---|------|---------|-------|
| **R11** | `from base.api_schema import GelAnalyzerSchemaView` | `from phoresis_core.api_schema import PhoresisSchemaView as GelAnalyzerSchemaView` | DRF spectacular schema view — needs a small port in `phoresis_core` (Task 4 step 1) |
| **R12** | `process_sample_id = data.get('process_sample_id')` and the surrounding `if process_sample_id:` block | DELETE the entire block | non-DRF API: views/api.py creates/updates lanes — drop the ProcessSample dispatch |
| **R13** | `process_sample__step_execution__step_template` (in `select_related`) | DELETE the field from the call | views/api.py and views/comparison.py — joins that no longer exist |
| **R14** | `if hasattr(lane, 'process_sample') and lane.process_sample:` | `if False:  # was: ProcessSample lookup — Phoresis has no central registry` | report data collectors |
| **R15** | `?samples=` query mode | DELETE the entire branch | views/comparison.py's `sample_comparison_view` |
| **R16** | `def search_samples_json(...)` (whole function) | DELETE the entire function | views/api.py — was the autocomplete for ProcessSample picker |
| **R17** | `process_sample_info = serializers.SerializerMethodField()` plus `def get_process_sample_info(...)` | DELETE the field and method | api/serializers.py |
| **R18** | `'gel_analyzer/_ga_base_minimal.html'` (template extends) | `'components/base.html'` | heavy templates root extend |
| **R19** | `'gel_analyzer/_ga_base.html'` | `'components/base.html'` | shell extends inside gel_analyzer |
| **R20** | `<i class="bi bi-..."></i>` (Bootstrap-Icons fallback in heavy templates' chrome) | `{% load ui_icons %}{% icon "..." %}` | only in the chrome layer; the inner viewer's gv-* icons stay as-is |

---

## File Structure (additions to Phase 3)

```
src/phoresis_core/
└── api_schema.py                                 # NEW: PhoresisSchemaView (DRF spectacular)

src/gel_analyzer/
├── api/                                          # NEW (DRF subpackage)
│   ├── __init__.py
│   ├── filters.py
│   ├── serializers.py                            # cleaned: no process_sample_info
│   ├── urls.py
│   └── views.py                                  # 6 ModelViewSets
├── services/
│   └── report/                                   # NEW (15 files including 1 .md kept)
│       ├── __init__.py
│       ├── builder.py
│       ├── comparison_builder.py
│       ├── comparison_data_collector.py
│       ├── comparison_excel_builder.py
│       ├── comparison_pptx_builder.py
│       ├── constants.py
│       ├── data_collector.py
│       ├── densitometry_builder.py
│       ├── densitometry_data_collector.py
│       ├── densitometry_excel_builder.py
│       ├── densitometry_pptx_builder.py
│       ├── poi_purity_chart.py
│       ├── terrain_chart.py
│       └── REPORT_IMPLEMENTATION_GUIDE.md        # kept as-is (developer doc)
├── views/
│   ├── api.py                                    # NEW: ~3,800 LOC after process_sample stripping
│   ├── analyses.py                               # UPGRADED: detail + annotate added to Phase 3 list+create
│   ├── comparison.py                             # NEW: list + sample_comparison_view (no ?samples= mode)
│   ├── comparison_api.py                         # NEW
│   ├── densitometry.py                           # NEW
│   ├── densitometry_api.py                       # NEW
│   ├── report_api.py                             # NEW
│   ├── studio.py                                 # NEW
│   └── training.py                               # NEW
├── templates/gel_analyzer/
│   ├── analyses/
│   │   ├── annotate_standalone.html              # NEW: Tailwind chrome around preserved gv-* viewer
│   │   ├── detail.html                           # NEW: full version replacing Phase 3 stub link
│   │   ├── densitometry.html                     # NEW: Tailwind chrome around dm-* viewer
│   │   └── includes/
│   │       ├── _calibration_panel.html
│   │       ├── _cv2_detection_panel.html
│   │       ├── _detection_panel.html
│   │       ├── _electropherogram_panel.html
│   │       ├── _profile_detection_panel.html
│   │       ├── _review_panel.html
│   │       └── _teacher_panel.html
│   ├── comparisons/
│   │   ├── compare.html                          # NEW: Tailwind chrome around dm-comparison viewer
│   │   └── list.html                             # NEW: SavedComparison index page
│   ├── images/
│   │   └── delete.html                           # NEW: replaces the HTMX confirm-modal stub
│   └── admin/
│       ├── template_calibration.html             # NEW
│       ├── template_studio.html                  # NEW
│       └── template_training_list.html           # NEW
├── urls.py                                       # FULLY POPULATED
├── nav.py                                        # EXTENDED with comparison + densitometry actions
└── tests/
    ├── test_drf_api.py                           # NEW (cleaned)
    └── test_views/
        ├── test_analyses.py                      # EXTENDED (detail + annotate cases)
        ├── test_comparison_api.py
        ├── test_cross_lane_consensus_api.py
        ├── test_hybrid_detection_views.py
        └── (test_images.py + test_ui_improvements.py from Phase 3 stay)

tests/e2e/
├── conftest.py                                   # Playwright fixtures
└── test_gel_workflow.py                          # NEW: golden-path e2e
```

---

## Task 1: Phase 4 dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add report-generation deps to runtime + Playwright to dev**

In `pyproject.toml`, append to `dependencies`:

```toml
    # Phase 4 — report generation
    "python-docx>=1.1",
    "openpyxl>=3.1",
    "python-pptx>=1.0",
    "matplotlib>=3.9",          # used by report charts (terrain, poi_purity)
```

And to `[project.optional-dependencies] dev`:

```toml
    "playwright>=1.48",
    "pytest-playwright>=0.5",
```

- [ ] **Step 2: Sync deps**

```bash
uv sync --extra dev
```
Expected: matplotlib + python-docx/openpyxl/pptx + playwright install. ~1 min.

- [ ] **Step 3: Install Playwright browsers**

```bash
.venv/Scripts/python.exe -m playwright install chromium
```
Expected: downloads Chromium (~140 MB). Skipping `firefox` and `webkit` for v1 — the spec only targets Chrome/Edge for the View Transition API anyway.

- [ ] **Step 4: Smoke-import**

```bash
.venv/Scripts/python.exe -c "import docx, openpyxl, pptx, matplotlib; from playwright.sync_api import sync_playwright; print('OK')"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add report-generation deps (docx, openpyxl, pptx, matplotlib) + Playwright"
```

---

## Task 2: services/report port (14 files + cleanup)

**Files:**
- Copy: `$DSHUB/gel_analyzer/services/report/` → `src/gel_analyzer/services/report/` (apply R1, R14)

- [ ] **Step 1: Bulk-copy the directory**

```bash
cp -r "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/services/report" src/gel_analyzer/services/
ls src/gel_analyzer/services/report/ | wc -l
```
Expected: 15 files (14 .py + 1 .md).

- [ ] **Step 2: Apply R1 to every `.py` file in `services/report/`**

```bash
grep -lr "from base.logging_config import get_logger" src/gel_analyzer/services/report/
```
Expected: 9 files. For each, replace `from base.logging_config import get_logger` → `from phoresis_core.logging_config import get_logger`.

Verify zero remaining hits:
```bash
grep -rn "from base" src/gel_analyzer/services/report/
```
Expected: no output.

- [ ] **Step 3: Apply R14 in `data_collector.py`**

In `src/gel_analyzer/services/report/data_collector.py`, find:
```python
        if lane.process_sample:
            sample_name = lane.process_sample.sample_id
        else:
            sample_name = lane.sample_name
```
Replace with:
```python
        # Phoresis has no ProcessSample registry — lanes always carry sample_name directly.
        sample_name = lane.sample_name
```

- [ ] **Step 4: Apply R14 in `comparison_data_collector.py`**

Same pattern — find:
```python
        if hasattr(lane, 'process_sample') and lane.process_sample:
            sample_name = lane.process_sample.sample_id
        else:
            sample_name = lane.sample_name
```
Replace with:
```python
        # Phoresis has no ProcessSample registry.
        sample_name = lane.sample_name
```

- [ ] **Step 5: Verify zero ProcessSample references remain**

```bash
grep -rn "process_sample\|ProcessSample" src/gel_analyzer/services/report/
```
Expected: no output (or only inside .md doc files explaining the historical context).

- [ ] **Step 6: Smoke-import**

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'src'); import os; os.environ['DJANGO_SETTINGS_MODULE']='phoresis.settings.dev'; import django; django.setup(); from gel_analyzer.services.report.builder import build_report; from gel_analyzer.services.report.comparison_builder import build_comparison_report; from gel_analyzer.services.report.densitometry_builder import build_densitometry_report; print('OK')"
```
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add src/gel_analyzer/services/report/
git commit -m "feat(gel_analyzer): port services/report (14 builders, cleaned of ProcessSample lookups)"
```

---

## Task 3: Non-DRF API port — `views/api.py` + 3 sibling API modules

**Files:**
- Copy: `$DSHUB/gel_analyzer/views/api.py` → `src/gel_analyzer/views/api.py` (apply R1, R12, R13, R16)
- Copy: `$DSHUB/gel_analyzer/views/comparison_api.py` → `src/gel_analyzer/views/comparison_api.py` (apply R1, R13)
- Copy: `$DSHUB/gel_analyzer/views/densitometry_api.py` → `src/gel_analyzer/views/densitometry_api.py` (apply R1, R12-13)
- Copy: `$DSHUB/gel_analyzer/views/report_api.py` → `src/gel_analyzer/views/report_api.py` (apply R1)

- [ ] **Step 1: Copy `views/api.py`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/api.py" src/gel_analyzer/views/api.py
```

- [ ] **Step 2: Apply R1 in `views/api.py`**

Find: `from base.logging_config import get_logger` → replace with `from phoresis_core.logging_config import get_logger`.

- [ ] **Step 3: Apply R16 — delete `search_samples_json` (the function and its registration)**

Open `src/gel_analyzer/views/api.py`, locate the entire function definition `def search_samples_json(...)` (likely 30-50 lines), and DELETE it. Also DELETE its URL pattern in Phase 4's `urls.py` (handled in Task 7).

Verify:
```bash
grep -n "search_samples_json" src/gel_analyzer/views/api.py
```
Expected: zero hits.

- [ ] **Step 4: Apply R12 — strip `process_sample_id` handling**

The source's `api_lanes` (POST handler) reads `process_sample_id` from the request body and writes it to `lane.process_sample_id`. Locate every block that does this — there are at least 4 (in `api_lanes` POST, `api_lane_detail` PUT, `api_bulk_lanes`, and `api_bulk_update_lanes`).

For each block that looks like:
```python
            # Handle process_sample_id
            process_sample_id = data.get('process_sample_id')
            if process_sample_id is not None:
                lane.process_sample_id = process_sample_id
```
DELETE it. (The `sample_metadata` JSONField added in Phase 2's Lane model is the new home for any per-lane extra info — clients post `sample_metadata={...}` instead.)

Also delete any block that creates a Lane and passes `process_sample_id=...` to `Lane.objects.create(...)`.

Verify:
```bash
grep -n "process_sample" src/gel_analyzer/views/api.py
```
Expected: zero hits.

- [ ] **Step 5: Apply R13 — strip `select_related('process_sample__...')`**

Find every `select_related(...)` call that includes `process_sample` or `process_sample__step_execution__step_template` and remove that argument from the call.

Verify:
```bash
grep -n "process_sample" src/gel_analyzer/views/api.py
```
Expected: zero hits.

- [ ] **Step 6: Copy and clean `comparison_api.py`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/comparison_api.py" src/gel_analyzer/views/comparison_api.py
```

Apply R1 + R13 the same way. Verify:
```bash
grep -n "from base\|process_sample" src/gel_analyzer/views/comparison_api.py
```
Expected: zero hits.

- [ ] **Step 7: Copy and clean `densitometry_api.py`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/densitometry_api.py" src/gel_analyzer/views/densitometry_api.py
```

Apply R1, R12, R13. Also strip the ProcessSample summary endpoint per spec §7.3 ("Strip `views/densitometry_api.py` of the ProcessSample summary endpoint"). Locate the `def api_lane_densitometry_summary` (or similarly-named) endpoint that returns `{process_sample: {...}, ...}` and DELETE it entirely.

Verify:
```bash
grep -n "from base\|process_sample\|ProcessSample" src/gel_analyzer/views/densitometry_api.py
```
Expected: zero hits.

- [ ] **Step 8: Copy `report_api.py`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/report_api.py" src/gel_analyzer/views/report_api.py
```

Apply R1. The report view doesn't reference ProcessSample directly — it delegates to the data collectors which were cleaned in Task 2.

Verify:
```bash
grep -n "from base" src/gel_analyzer/views/report_api.py
```
Expected: zero hits.

- [ ] **Step 9: Smoke-import**

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'src'); import os; os.environ['DJANGO_SETTINGS_MODULE']='phoresis.settings.dev'; import django; django.setup(); from gel_analyzer.views import api, comparison_api, densitometry_api, report_api; print('non-DRF API OK')"
```
Expected: `non-DRF API OK`.

- [ ] **Step 10: Commit**

```bash
git add src/gel_analyzer/views/api.py src/gel_analyzer/views/comparison_api.py src/gel_analyzer/views/densitometry_api.py src/gel_analyzer/views/report_api.py
git commit -m "feat(gel_analyzer): port non-DRF API endpoints (search_samples_json + ProcessSample handling stripped)"
```

---

## Task 4: DRF API port — `api/` subpackage + `phoresis_core/api_schema.py`

**Files:**
- Create: `src/phoresis_core/api_schema.py`
- Copy: `$DSHUB/gel_analyzer/api/` → `src/gel_analyzer/api/` (apply R1, R11, R17)

- [ ] **Step 1: Create `phoresis_core/api_schema.py`**

The source's `base/api_schema.py` provides a `GelAnalyzerSchemaView` for DRF spectacular. We port it as a generic `PhoresisSchemaView` and let `gel_analyzer/api/urls.py` alias it.

```python
"""DRF Spectacular schema view for Phoresis APIs."""
from drf_spectacular.views import SpectacularAPIView


class PhoresisSchemaView(SpectacularAPIView):
    """Schema view with Phoresis branding and per-app subset support."""
    schema = None  # falls back to default introspection
```

Actually `drf-spectacular` isn't yet in `pyproject.toml` — it was already added in Phase 1's deps (line `"djangorestframework>=3.15"` plus `drf-spectacular` if originally present). Verify:

```bash
grep -n "spectacular" pyproject.toml
```
If absent, append `"drf-spectacular>=0.27"` to `dependencies` and re-run `uv sync --extra dev`.

- [ ] **Step 2: Bulk-copy `gel_analyzer/api/`**

```bash
cp -r "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/api" src/gel_analyzer/
ls src/gel_analyzer/api/
```
Expected: `__init__.py`, `filters.py`, `serializers.py`, `urls.py`, `views.py`.

- [ ] **Step 3: Apply R1 + R11 to `api/urls.py`**

Find:
```python
from base.api_schema import GelAnalyzerSchemaView
```
Replace with:
```python
from phoresis_core.api_schema import PhoresisSchemaView as GelAnalyzerSchemaView
```

- [ ] **Step 4: Apply R17 to `api/serializers.py`** — strip ProcessSample serializer field

Open `src/gel_analyzer/api/serializers.py`, find:
```python
    process_sample_info = serializers.SerializerMethodField()
```
DELETE the line.

Also find:
```python
    def get_process_sample_info(self, obj):
        if obj.process_sample:
            return {'id': str(obj.process_sample.id), 'sample_id': obj.process_sample.sample_id}
        return None
```
DELETE the entire method.

In the same file's `LaneSerializer.Meta.fields`, find `'process_sample_info',` and remove that string from the tuple.

Verify:
```bash
grep -n "process_sample" src/gel_analyzer/api/serializers.py
```
Expected: zero hits.

- [ ] **Step 5: Strip `process_sample` from `LaneSerializer` write fields**

In the same file, also remove `'process_sample'` from any `fields = (...)` tuple that lists it.

In any `select_related` call (in viewsets that come next), `process_sample` and `process_sample__step_execution__step_template` are stripped per R13.

- [ ] **Step 6: Apply R13 to `api/views.py`** — strip `select_related('process_sample')` and `'process_sample__...'`

```bash
grep -n "process_sample" src/gel_analyzer/api/views.py
```
For each hit, remove the field name from the `select_related(...)` call.

Verify:
```bash
grep -n "process_sample" src/gel_analyzer/api/views.py
```
Expected: zero hits.

- [ ] **Step 7: Apply R1 to any `from base.*` imports across `api/`**

```bash
grep -lr "from base" src/gel_analyzer/api/
```
Apply R1 substitutions.

- [ ] **Step 8: Smoke-import**

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'src'); import os; os.environ['DJANGO_SETTINGS_MODULE']='phoresis.settings.dev'; import django; django.setup(); from gel_analyzer.api.views import GelImageViewSet, GelAnalysisViewSet, LaneViewSet, BandViewSet, LadderTemplateViewSet, SavedComparisonViewSet; from gel_analyzer.api.serializers import LaneSerializer; print('DRF OK')"
```
Expected: `DRF OK`.

- [ ] **Step 9: Add `drf_spectacular` to `INSTALLED_APPS`**

Edit `src/phoresis/settings/base.py`. In `INSTALLED_APPS`, append `"drf_spectacular",` to the third-party section (just after `"rest_framework",`).

- [ ] **Step 10: Commit**

```bash
git add src/phoresis_core/api_schema.py src/gel_analyzer/api/ src/phoresis/settings/base.py
git commit -m "feat(gel_analyzer): port DRF API (6 viewsets, ProcessSample fields stripped)"
```

---

## Task 5: HTML views upgrade — analyses (detail + annotate), comparison, densitometry, studio, training

**Files:**
- Modify: `src/gel_analyzer/views/analyses.py` (add detail + annotate)
- Copy + clean: `comparison.py`, `densitometry.py`, `studio.py`, `training.py`

> **Note:** Phase 3 created a slim `analyses.py` with just list + create. Phase 4 *upgrades* it by appending the two heavy view functions, not replacing the file.

- [ ] **Step 1: Append `analysis_detail_view` and `analysis_annotate_view` to `views/analyses.py`**

Read the source `$DSHUB/gel_analyzer/views/analyses.py` and copy ONLY the bodies of `analysis_detail_view` and `analysis_annotate_view` (lines ~210-450, plus the helper functions `_get_calibration_info`, `_get_densitometry_info`, `_get_completion_info`, `_get_warnings`).

Apply R1 to any `from base.*` references. Apply the cleanup pattern from Phase 3 Task 13: `lane.process_sample` references in `_get_densitometry_info` (the helper) — use the same replacement we used in `services/report/data_collector.py` (just `lane.sample_name`).

Concretely, in `_get_densitometry_info`, find:
```python
            sample_name = lane.sample_name
            if not sample_name and lane.process_sample:
                sample_name = lane.process_sample.sample_id
```
Replace with:
```python
            sample_name = lane.sample_name
```

- [ ] **Step 2: Copy `views/comparison.py` (cleaned)**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/comparison.py" src/gel_analyzer/views/comparison.py
```

Apply:
- R1: `from base.logging_config import get_logger` → `from phoresis_core.logging_config import get_logger`
- R15: locate the `?samples=` branch in `sample_comparison_view`. Per spec §7.3, **delete it entirely** — only `?lanes=` and `?comparison=<uuid>` remain.

Concretely, find a block like:
```python
    samples_param = request.GET.get('samples')
    if samples_param:
        # Old ProcessSample-keyed mode
        process_sample_ids = [int(s) for s in samples_param.split(',') if s]
        ...  # ~30 lines of ProcessSample-driven lane fetching
```
DELETE that entire branch. Keep only the `lanes=` and `comparison=<uuid>` branches.

- Also fix the `login_url` argument: change `@login_required(login_url='authentication:user_login')` → `@login_required` (defaults to `LOGIN_URL = "accounts:login"` from Phoresis settings).

- Strip the `_serialize_lane_data` helper's ProcessSample handling: find any `process_sample=None, sample_analysis=None` parameter list and reduce to `(lane,)`. Inside the function, replace any reference to those parameters with the lane's own `sample_name` / `sample_metadata`.

Verify:
```bash
grep -n "from base\|process_sample\|sample_analysis\|samples=" src/gel_analyzer/views/comparison.py
```
Expected: zero hits.

- [ ] **Step 3: Copy `views/densitometry.py` (cleaned)**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/densitometry.py" src/gel_analyzer/views/densitometry.py
```

Apply R1. This file is only 180 LOC and references ProcessSample only via the data_collector (already cleaned in Task 2). Verify:
```bash
grep -n "from base\|process_sample" src/gel_analyzer/views/densitometry.py
```
Expected: zero hits.

- [ ] **Step 4: Copy `views/studio.py` and `views/training.py`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/studio.py" src/gel_analyzer/views/studio.py
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/training.py" src/gel_analyzer/views/training.py
```

Apply R1 to both. Neither references ProcessSample. Verify:
```bash
grep -n "from base" src/gel_analyzer/views/studio.py src/gel_analyzer/views/training.py
```
Expected: zero hits.

- [ ] **Step 5: Copy `views/__init__.py` exports**

The source's `views/__init__.py` (232 LOC) re-exports view functions for the `urls.py` to import via `from gel_analyzer.views import ...`. Copy it:

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/__init__.py" src/gel_analyzer/views/__init__.py
```

Apply R1 if present. Verify all imports inside resolve to existing modules (the file imports `home_view` from `views/home.py` — but Phoresis's home is in the `dashboard` app, not gel_analyzer). REMOVE the `from .home import home_view` line and any export of `home_view` from `__all__`.

Verify:
```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'src'); import os; os.environ['DJANGO_SETTINGS_MODULE']='phoresis.settings.dev'; import django; django.setup(); from gel_analyzer.views import analysis_list_view, analysis_create_view, analysis_detail_view, analysis_annotate_view, image_list_view, image_upload_view, image_detail_view, image_delete_view, comparison_list_view, sample_comparison_view; print('views OK')"
```
Expected: `views OK`.

- [ ] **Step 6: Commit**

```bash
git add src/gel_analyzer/views/
git commit -m "feat(gel_analyzer): port heavy HTML views (annotate, detail, comparison, densitometry, studio, training)"
```

---

## Task 6: Heavy templates port — Tailwind chrome around preserved JS-driven viewers

**Files:**
- Copy + adapt: `analyses/annotate_standalone.html`, `analyses/detail.html`, `analyses/densitometry.html`, `comparisons/compare.html`, `comparisons/list.html`, `images/delete.html`
- Copy verbatim: `analyses/includes/*.html` (7 files)
- Copy + adapt: `admin/template_calibration.html`, `admin/template_studio.html`, `admin/template_training_list.html`

> **Pattern reminder:** For every heavy template, the JS-driven inner viewer (`gv-*`, `dm-*`, `gel-*` classes) stays unchanged. Only the *chrome* layer — page extends, breadcrumb, sidebar inclusion, top action bar — is rewritten in Tailwind.

- [ ] **Step 1: Copy `analyses/annotate_standalone.html`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/analyses/annotate_standalone.html" src/gel_analyzer/templates/gel_analyzer/analyses/annotate_standalone.html
```

Apply R18: find `{% extends "gel_analyzer/_ga_base_minimal.html" %}` → replace with `{% extends "components/base.html" %}`.

The annotate viewer is fullscreen (`gv-container` is the root). It does NOT include the standard sidebar layout — it has its own minimal header (`gv-header`). So the body block bypasses `_layout.html`:

After the `extends`, ensure the template has this structure:
```django
{% extends "components/base.html" %}
{% load static %}

{% block title %}Annotate — {{ analysis.name }}{% endblock %}

{% block head %}
<link rel="stylesheet" href="{% static 'gel_analyzer/css/gel_viewer_standalone.css' %}">
{% endblock %}

{% block body %}
<div id="gel-viewer" class="gv-container">
    <!-- ... existing gv-* markup unchanged ... -->
</div>
{% endblock %}

{% block scripts %}
<!-- ... existing JS includes unchanged ... -->
{% endblock %}
```

The `{% block body %}` overrides `base.html`'s default which wraps `{% block content %}` in `<main class="mx-auto ...">`. Annotate uses fullscreen, so we skip the wrapper.

Apply R20 to the chrome layer only — `<i class="bi bi-arrow-left"></i>` in the header `<a class="gv-back-link">` becomes `{% icon "chevron-left" %}` (load `ui_icons` at top of file). The bi-* icons inside the gv-* viewer's tool palette (the actual annotation tools) stay as-is — they're part of the JS-controlled UI which has its own icon system.

Concretely, look for `<a href="{% url 'gel_analyzer:analysis_detail' pk=analysis.pk %}" class="gv-back-link">` and confirm only the icon inside changes.

- [ ] **Step 2: Copy `analyses/detail.html`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/analyses/detail.html" src/gel_analyzer/templates/gel_analyzer/analyses/detail.html
```

This template is more "shell-like" — it shows analysis metadata + a link to the annotate viewer. Apply R19 (`_ga_base.html` → `components/base.html`), then rewrite the chrome to use Phoresis templatetags. The KPI cards / status banner / approval form become `{% kpi %}` / `{% badge %}` / `{% btn %}`.

Use this skeleton:

```django
{% extends "components/base.html" %}
{% load ui_components ui_icons static %}

{% block title %}{{ analysis.name|default:"Analysis" }} — Phoresis{% endblock %}

{% block body %}{% include 'components/_layout.html' %}{% endblock %}

{% block content %}
<div class="space-y-6">
    <header class="flex items-end justify-between">
        <div>
            <h1 class="text-2xl font-semibold">{{ analysis.name|default:"(unnamed)" }}</h1>
            <p class="mt-1 text-sm text-text-muted">
                Gel <a class="hover:underline" href="{% url 'gel_analyzer:image_detail' pk=analysis.gel_image.pk %}">{{ analysis.gel_image.original_filename }}</a> ·
                {% badge analysis.get_status_display variant="muted" %}
                · created {{ analysis.created_at|date:"M j, Y" }} by {{ analysis.created_by|default:"—" }}
            </p>
        </div>
        <div class="flex gap-2">
            {% btn "Annotate" href="/analyses/"|add:analysis.id|stringformat:"s"|add:"/annotate/" icon="edit" %}
            {% if analysis.lanes.exists %}
                {% btn "Densitometry" href="/analyses/"|add:analysis.id|stringformat:"s"|add:"/densitometry/" variant="secondary" icon="trending-up" %}
            {% endif %}
        </div>
    </header>

    <section class="grid grid-cols-2 gap-4 md:grid-cols-4">
        {% kpi "Lanes"   analysis.total_lanes icon="layers" %}
        {% kpi "Bands"   analysis.total_bands icon="band" %}
        {% kpi "Calibration" calibration_info.ladder_count|default:0 icon="ladder" accent="success" %}
        {% kpi "POI purity" densitometry_info.average_purity|default:"—" icon="trending-up" accent="band" %}
    </section>

    <!-- Existing detail blocks (warnings, recent activity, lane preview) — preserved intact below. -->
    {% block detail_body %}{% endblock %}
</div>
{% endblock %}
```

Hand-merge the source's existing detail markup into the `{% block detail_body %}` if it makes sense, otherwise inline it after the kpis section. The point: the page *looks like* a Phoresis page, not an MDB5 dashboard.

- [ ] **Step 3: Copy `analyses/densitometry.html`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/analyses/densitometry.html" src/gel_analyzer/templates/gel_analyzer/analyses/densitometry.html
```

Same R18 substitution. The densitometry viewer is also fullscreen-ish (`dm-container` root) with its own toolbar — apply the same `{% block body %}` override pattern as annotate, with the additional `<link>` for `densitometry.css`.

- [ ] **Step 4: Copy `comparisons/compare.html`**

```bash
mkdir -p src/gel_analyzer/templates/gel_analyzer/comparisons
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/comparisons/compare.html" src/gel_analyzer/templates/gel_analyzer/comparisons/compare.html
```

Apply R18 + the same fullscreen pattern (it has the `dm-comparison-*` viewer inside).

- [ ] **Step 5: Copy `comparisons/list.html`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/comparisons/list.html" src/gel_analyzer/templates/gel_analyzer/comparisons/list.html
```

This is a shell-style page — apply R19 + rewrite chrome with templatetags (similar to Phase 3's analyses/list.html pattern).

- [ ] **Step 6: Copy `analyses/includes/*.html` (7 files)**

```bash
cp -r "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/analyses/includes" src/gel_analyzer/templates/gel_analyzer/analyses/
ls src/gel_analyzer/templates/gel_analyzer/analyses/includes/ | wc -l
```
Expected: 7 files.

These include partials (`_calibration_panel.html`, `_cv2_detection_panel.html`, etc.) are part of the JS-driven viewer — they ship as-is. Verify no `{% extends "gel_analyzer/_ga_*" %}` references (they shouldn't have any — they're partials, not full pages).

```bash
grep -l "_ga_base" src/gel_analyzer/templates/gel_analyzer/analyses/includes/
```
Expected: no output.

- [ ] **Step 7: Copy `images/delete.html`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/images/delete.html" src/gel_analyzer/templates/gel_analyzer/images/delete.html
```

Apply R19 + rewrite confirm-modal chrome with `{% confirm %}` templatetag from Phase 3.

- [ ] **Step 8: Copy `admin/*.html` (3 files)**

```bash
mkdir -p src/gel_analyzer/templates/gel_analyzer/admin
cp -r "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/templates/gel_analyzer/admin/." src/gel_analyzer/templates/gel_analyzer/admin/
```

Apply R19 to each. These are admin-side pages used by the studio/training views — minimal Tailwind treatment, mostly inheriting Django admin chrome works fine here.

- [ ] **Step 9: Run `manage.py check` to surface any template syntax errors**

```bash
.venv/Scripts/python.exe manage.py check
```
Expected: no issues. If a template fails to load, surface the issue, fix the offending tag/include, re-run.

- [ ] **Step 10: Commit**

```bash
git add src/gel_analyzer/templates/
git commit -m "feat(gel_analyzer): port heavy templates with Tailwind chrome (annotate, detail, densitometry, compare, list, includes, admin)"
```

---

## Task 7: URL wiring + nav.py extension

**Files:**
- Modify: `src/gel_analyzer/urls.py` (full URL set from source, with stripped routes)
- Modify: `src/gel_analyzer/nav.py` (add comparisons + densitometry actions)
- Modify: `src/phoresis/urls.py` (already includes gel_analyzer from Phase 3 — verify)

- [ ] **Step 1: Copy `urls.py` from source**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/urls.py" src/gel_analyzer/urls.py
```

- [ ] **Step 2: Strip removed routes**

In `src/gel_analyzer/urls.py`, DELETE these lines (each corresponds to a removed view in Tasks 3 / 5):

```python
    path("api/samples/search/", api_sample_search, name="api_sample_search"),
    path("api/samples/filter-options/", api_filter_options, name="api_filter_options"),
```

Wait — `api_filter_options` is referenced by the saved-comparison page; verify with the source's actual view file. If the function still exists in `views/api.py` after Task 3 cleanup (it doesn't depend on ProcessSample), keep that route. Otherwise, drop it.

Also verify `api_sample_search` is gone (it was the autocomplete that called `search_samples_json` — both are removed).

- [ ] **Step 3: Strip the home route**

The source `urls.py` has:
```python
    path("", home_view, name="home"),
```
DELETE this — Phoresis's home lives in `dashboard.urls` (Phase 1). The `gel_analyzer:home` URL name is no longer registered.

- [ ] **Step 4: Apply R1 to any `from base.*` imports in `urls.py`**

```bash
grep -n "from base" src/gel_analyzer/urls.py
```
For each hit, apply R1.

- [ ] **Step 5: Sanity-check the import chain**

```bash
.venv/Scripts/python.exe manage.py check
```
Expected: no issues. If any view import fails (because Tasks 3-5 didn't port a referenced view), either remove that URL or back-fill the view.

- [ ] **Step 6: Update `nav.py`** with annotation/densitometry/comparison entries

Edit `src/gel_analyzer/nav.py`:

```python
"""Register the Gel Analyzer app in the navigation registry."""
from phoresis_core.navigation import nav_registry

nav_registry.register_app(
    app_label="gel_analyzer",
    display_name="Gel Analyzer",
    group="Lab Tools",
    icon="image",
    keywords=["gel", "SDS-PAGE", "dot blot", "western blot", "band", "densitometry", "electrophoresis"],
    shortcut_key="g",
    pages=[
        {"name": "Gel images",   "url": "gel_analyzer:image_list",       "icon": "image"},
        {"name": "Analyses",     "url": "gel_analyzer:analysis_list",    "icon": "layers"},
        {"name": "Comparisons",  "url": "gel_analyzer:comparison_list",  "icon": "grid-2x2"},
    ],
    actions=[
        {"name": "Upload gel",   "url": "gel_analyzer:image_upload",     "icon": "upload"},
    ],
)
```

- [ ] **Step 7: Add Comparison link to the sidebar**

Edit `src/phoresis_ui/templates/components/_sidebar.html` and append a third `<a>` link to the `<nav>`, modeled on the existing Gel Images / Analyses links:

```django
<a href="{% url 'gel_analyzer:comparison_list' %}"
   class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-muted hover:bg-surface-elevated hover:text-text transition-colors {% if request.resolver_match.url_name == 'comparison_list' %}bg-accent-50 text-accent-700 font-medium{% endif %}">
    {% icon "grid-2x2" %}
    <span class="whitespace-nowrap" :class="pinned ? '' : 'hidden group-hover:inline'">Comparisons</span>
</a>
```

- [ ] **Step 8: Run all tests to confirm URL resolution still works**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: tests still green. Any test that did `reverse('gel_analyzer:home')` now fails — fix by switching to `reverse('dashboard:home')` (the only place `home` was tested was the layout test in Phase 3, which already uses `dashboard:home`).

- [ ] **Step 9: Commit**

```bash
git add src/gel_analyzer/urls.py src/gel_analyzer/nav.py src/phoresis_ui/templates/components/_sidebar.html
git commit -m "feat(gel_analyzer): wire full URL set + extend nav.py with comparisons"
```

---

## Task 8: Test ports — DRF API tests + per-view tests

**Files:**
- Copy + clean: `tests/test_drf_api.py`
- Copy + clean: `tests/test_views/test_analyses.py`, `test_api.py`, `test_comparison_api.py`, `test_cross_lane_consensus_api.py`, `test_hybrid_detection_views.py`, `test_ui_improvements.py`
- Modify: existing tests (Phase 3 image tests stay; analyses tests merge with Phase 3's stubs)

- [ ] **Step 1: Copy `test_drf_api.py`**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/tests/test_drf_api.py" src/gel_analyzer/tests/test_drf_api.py
```

Apply:
- R1 if present (`from base.logging_config` — unlikely in tests but check)
- Strip `from process_development.*` imports
- Strip any test that asserts `process_sample` field present in serializer output — those tests are now invalid invariants

```bash
grep -n "process_sample\|ProcessSample\|from process_development\|from authentication\|from base" src/gel_analyzer/tests/test_drf_api.py
```
For each hit, apply the appropriate cleanup (delete the test if it asserts ProcessSample presence; remove the import if it imports unused fixtures).

- [ ] **Step 2: Copy view tests**

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/tests/test_views/test_api.py" src/gel_analyzer/tests/test_views/
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/tests/test_views/test_comparison_api.py" src/gel_analyzer/tests/test_views/
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/tests/test_views/test_cross_lane_consensus_api.py" src/gel_analyzer/tests/test_views/
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/tests/test_views/test_hybrid_detection_views.py" src/gel_analyzer/tests/test_views/
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/tests/test_views/test_ui_improvements.py" src/gel_analyzer/tests/test_views/
```

For each file, apply:
- R1 (very unlikely, check)
- Strip `from process_development.*` imports
- Strip tests that assert `process_sample` field on responses

```bash
grep -rn "process_sample\|ProcessSample\|from process_development\|from authentication\|from base" src/gel_analyzer/tests/test_views/
```
For each hit, apply the cleanup.

- [ ] **Step 3: Merge Phase 3's `test_analyses.py` with the source's** detail/annotate cases

The source's `tests/test_views/test_analyses.py` contains tests for `analysis_detail_view` and `analysis_annotate_view`. The Phase 3 file has list + create only. Append the source's detail+annotate test cases to Phoresis's existing file:

```bash
# Append the file with care — manual paste, not a `cat >>` overwrite
```
Open both files side-by-side and copy only the test functions for `*_detail_*` and `*_annotate_*`. Apply the same cleanups.

- [ ] **Step 4: Run all gel_analyzer tests**

```bash
.venv/Scripts/python.exe -m pytest src/gel_analyzer/ -v
```
Expected: ~250+ tests pass (Phase 2's ~150 + ~100 view/api tests). Zero failures.

If a DRF test fails because the spectacular schema URL isn't routed yet, ensure `gel_analyzer/api/urls.py` is included in the project URLs. Verify in `src/gel_analyzer/urls.py`:
```python
    path("api/", include("gel_analyzer.api.urls", namespace="gel_analyzer_api")),
```

- [ ] **Step 5: Commit**

```bash
git add src/gel_analyzer/tests/
git commit -m "test(gel_analyzer): port DRF + view tests (process_development fixtures stripped)"
```

---

## Task 9: Playwright e2e — golden-path gel workflow

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_gel_workflow.py`
- Modify: `pyproject.toml` (add a `[tool.pytest.ini_options]` `markers` entry or separate pytest config for e2e isolation)

- [ ] **Step 1: Create the e2e tree**

```bash
mkdir -p tests/e2e
touch tests/e2e/__init__.py
```

- [ ] **Step 2: Create `tests/e2e/conftest.py`**

```python
"""Playwright fixtures for Phoresis e2e tests.

Spawns `runserver` once per session against a dedicated test database, then
seeds an admin user and a primary lab user before each test.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Start `manage.py runserver` against the test settings, yield the base URL."""
    port = _free_port()
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "phoresis.settings.test"
    env["DB_NAME"] = env.get("DB_NAME", "phoresis_e2e")
    env["DJANGO_DEBUG"] = "false"

    cmd = [sys.executable, "manage.py", "migrate", "--noinput"]
    subprocess.run(cmd, cwd=BASE_DIR, env=env, check=True)

    cmd_seed = [
        sys.executable, "manage.py", "create_initial_users", "--from-env", "--skip-existing",
    ]
    env_seed = env | {
        "ADMIN_EMAIL": "e2e-admin@phoresis.local", "ADMIN_PASSWORD": "e2e-admin-pwd",
        "PRIMARY_USER_EMAIL": "e2e-lab@phoresis.local", "PRIMARY_USER_PASSWORD": "e2e-lab-pwd",
        "PRIMARY_USER_FULL_NAME": "E2E Lab",
    }
    subprocess.run(cmd_seed, cwd=BASE_DIR, env=env_seed, check=True)

    cmd_run = [sys.executable, "manage.py", "runserver", "--noreload", f"{HOST}:{port}"]
    proc = subprocess.Popen(cmd_run, cwd=BASE_DIR, env=env, stdout=subprocess.DEVNULL)

    # Wait for the server to be responsive
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("runserver failed to start within 15 seconds")

    yield f"http://{HOST}:{port}"

    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def browser_context_args(browser_context_args):
    """Default to a 1280×800 viewport for consistent screenshots."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 800}}
```

- [ ] **Step 3: Create the golden-path test**

`tests/e2e/test_gel_workflow.py`:

```python
"""End-to-end: login → dashboard → upload gel → create analysis → save → logout.

Spec §11.4 path #1.
"""
from pathlib import Path

import pytest

FIXTURE_GEL = Path(__file__).resolve().parents[2] / "src/gel_analyzer/tests/data/test_gel.png"


@pytest.mark.e2e
def test_full_gel_workflow(page, live_server) -> None:
    """Walk the primary user through the full upload+analyze+logout cycle."""
    # --- 1. Login ---
    page.goto(f"{live_server}/accounts/login/")
    page.fill('input[name="username"]', "e2e-lab")
    page.fill('input[name="password"]', "e2e-lab-pwd")
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_server}/")

    # --- 2. Dashboard ---
    assert page.locator("h1").inner_text().lower().startswith("welcome")
    # KPIs render with CountUp.js — wait for animation to settle
    page.wait_for_function("() => !document.querySelector('[data-countup]')", timeout=3_000)

    # --- 3. Upload gel ---
    page.goto(f"{live_server}/images/upload/")
    page.set_input_files('input[name="original_file"]', str(FIXTURE_GEL))
    page.select_option('select[name="gel_type"]', "SDS_PAGE")
    page.fill('textarea[name="description"]', "E2E test gel")
    page.click('button:has-text("Upload")')
    page.wait_for_url(f"{live_server}/images/**", timeout=15_000)
    assert "test_gel" in page.locator("h1").inner_text().lower()

    # --- 4. Create analysis ---
    image_url = page.url
    image_pk = image_url.rsplit("/", 2)[-2]
    page.goto(f"{live_server}/images/{image_pk}/analyses/create/")
    page.fill('input[name="name"]', "E2E Analysis 1")
    page.click('button:has-text("Create analysis")')
    page.wait_for_url(f"{live_server}/images/{image_pk}/", timeout=10_000)

    # --- 5. Verify analysis appears in list ---
    page.goto(f"{live_server}/analyses/")
    assert page.locator("text=E2E Analysis 1").count() > 0

    # --- 6. Logout ---
    page.locator('button:has-text("Sign out")').first.click()
    page.wait_for_url(f"{live_server}/accounts/login/**", timeout=5_000)
```

- [ ] **Step 4: Add a fixture image**

If `src/gel_analyzer/tests/data/test_gel.png` doesn't exist (it was created in Phase 2 Task 16 step 1), generate a synthetic one:

```python
.venv/Scripts/python.exe -c "
import io, numpy as np
from PIL import Image
arr = np.full((600, 200), 30, dtype=np.uint8)
for y in [80, 180, 280, 380, 480]: arr[y-6:y+6, 40:160] = 220
img = Image.fromarray(arr, mode='L')
import os; os.makedirs('src/gel_analyzer/tests/data', exist_ok=True)
img.save('src/gel_analyzer/tests/data/test_gel.png')
print('OK')
"
```

- [ ] **Step 5: Mark e2e tests so they don't run by default in `pytest`**

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "e2e: end-to-end tests requiring a live server + browser (slow; opt in with -m e2e)",
]
```

And ensure `testpaths = ["src", "tests/e2e"]` if not already.

Update the default `addopts` to skip e2e by default:

```toml
addopts = ["--strict-markers", "-ra", "--reuse-db", "-m", "not e2e"]
```

- [ ] **Step 6: Run the e2e in opt-in mode**

```bash
.venv/Scripts/python.exe -m pytest tests/e2e/ -v -m e2e --headed=false
```
Expected: 1 e2e test passes in ~10-20 seconds. The browser launches in headless mode.

If the test times out at "wait for upload redirect", check that the file_handler service can process the synthetic PNG (it should — Phase 2's `test_e2e_hybrid` exercises the same code path).

- [ ] **Step 7: Commit**

```bash
git add tests/e2e/ pyproject.toml src/gel_analyzer/tests/data/test_gel.png
git commit -m "test(e2e): add Playwright golden-path workflow (login→upload→analysis→logout)"
```

---

## Task 10: End-to-end smoke + tag v0.4.0

- [ ] **Step 1: Final CSS rebuild**

```bash
npm run build:css
```

- [ ] **Step 2: Run the entire non-e2e suite**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: ~280 tests pass (Phase 1+2+3 ≈ 190 + Phase 4 ≈ 90 view/API tests). Zero failures.

- [ ] **Step 3: Run the e2e suite**

```bash
.venv/Scripts/python.exe -m pytest tests/e2e/ -m e2e -v
```
Expected: 1 test passes.

- [ ] **Step 4: Lint + format**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pre_commit run --all-files
```
Expected: all green.

- [ ] **Step 5: Manual browser smoke — every viewer**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```

Walk through (signed in as e2e lab user with at least one uploaded gel + one analysis):

| URL | Verify |
|---|---|
| `/analyses/<uuid>/` | KPI cards + status banner + buttons (Annotate / Densitometry) render |
| `/analyses/<uuid>/annotate/` | Fullscreen `gv-container` viewer loads; toolbar visible; gel image renders |
| Click "Add lane" in annotate | The lane editor responds (no JS errors) |
| `/analyses/<uuid>/densitometry/` | `dm-container` viewer loads with electropherogram (synthetic data is fine if no real bands yet) |
| `/comparisons/` | List page renders with empty state if no SavedComparisons |
| `/comparisons/?lanes=<id1>,<id2>` | Compare viewer loads with the two lanes side-by-side |
| Theme toggle | The viewers re-render correctly in dark mode (D3 charts repaint via the `phoresis:theme-changed` event) |
| Console (DevTools) | No errors anywhere; no 404s on JS files |

- [ ] **Step 6: Commit any final fixes**

```bash
git status
```
If anything changed:
```bash
git add -u
git commit -m "fix(gel_analyzer): tweaks from Phase 4 browser smoke"
```

- [ ] **Step 7: Tag v0.4.0**

```bash
git tag -a v0.4.0 -m "Phase 4: Heavy viewers + DRF API + e2e — annotate/detail/densitometry/comparison views in Tailwind chrome, ~50 non-DRF JSON endpoints + 6 DRF viewsets, report builders (docx/xlsx/pptx), Playwright golden-path test"
git tag --list
```

---

## Acceptance criteria for Phase 4

This phase is **done** when ALL of the following hold:

1. `uv sync --extra dev` pulls in python-docx, openpyxl, python-pptx, matplotlib, playwright, pytest-playwright; `playwright install chromium` succeeds.
2. `python manage.py check` passes; `python manage.py runserver` boots cleanly with the full URL surface.
3. `pytest -v` (default — excludes `-m e2e`) runs with 0 failures, 0 errors. Approximate count: ~280 tests.
4. `pytest -m e2e -v` runs the Playwright golden-path successfully in headless Chromium.
5. `ruff check .`, `ruff format --check .`, and `pre-commit run --all-files` are all green.
6. `git tag --list` includes `v0.4.0`.
7. `grep -rn "from base\|from authentication\|from process_development\|process_sample\|UserProxy\|SampleAnalysis\|ProcessSample\|search_samples_json\|samples=" src/gel_analyzer/` returns ZERO functional hits (only inside .md docstrings explaining historical context).
8. Spec §7.3 invariants:
    - `views/api.py` exists, contains the ported endpoints minus `search_samples_json` and ProcessSample-related routes.
    - `views/comparison.py` accepts `?lanes=` and `?comparison=<uuid>` only — `?samples=` returns 400 or 404.
    - `views/densitometry_api.py` no longer has the ProcessSample summary endpoint.
    - `services/report/` is import-clean.
    - DRF `LaneSerializer` does NOT include `process_sample_info` or `process_sample` fields.
9. Spec §11.4 path #1 (login → dashboard → upload → analysis → save → logout) passes as a Playwright e2e in `tests/e2e/test_gel_workflow.py`.
10. The three heavy viewers (`annotate_standalone.html`, `densitometry.html`, `comparisons/compare.html`) all extend `components/base.html` and load their respective preserved CSS (`gel_viewer_standalone.css`, `densitometry.css`, `comparison.css`) without modification.
11. The sidebar shows three primary entries (Gel images, Analyses, Comparisons); the command palette includes them.
