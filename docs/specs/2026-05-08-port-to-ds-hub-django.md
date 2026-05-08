# Port plan — quantification + densitometry/comparison overhaul → ds-hub-django

**Source:** Phoresis branch `feat/quantification` (PR #4)
**Target:** `ds-hub-django/gel_analyzer/` (latest `main`)
**Status:** Not started — drafted 2026-05-08
**Owner:** GM

## TL;DR — what's hard vs easy

**Most of this port is mechanical.** The Phoresis branch was deliberately kept on shared code paths — services, panels, templates, CSS, JS modules — so the vast majority of files (~80%) copy across with `cp`-level effort. The auto-save plumbing, the per-band table refactor, the calibration R² fix, the quantification-curve renderer, the new content chart, the back-button visibility, the MW rounding, the throttle config — all of these touch files that exist verbatim in both repos.

**The hard part is two things:**

### 1. Models — explicit divergence required

ds-hub-django ships a multi-tenant hub. The gel_analyzer models in ds-hub carry **process-sample wiring** that Phoresis doesn't have:

- `Lane.process_sample` (FK to `process_development.ProcessSample` or equivalent)
- The lane-cards / sample-comparison UI threads `process_sample.sample_id` through as the canonical sample identifier — see `sample-comparison-state.js` already references `lane.process_sample?.sample_id || lane.sample_name || ...`
- The "Add Samples to Comparison" wizard pulls process samples from a tenant-scoped queryset

**Do not flatten this on the way in.** When porting model changes:

- Apply Phoresis's new fields (`BandQuantPoint`, `ProteinQuantCalibration`, `DensitometryResult.estimated_amount`, etc.) **as additions**.
- Keep every `process_sample` FK, related_name, and queryset filter that ds-hub already has.
- The new `ProteinQuantCalibration.analysis` FK transitively scopes through `GelAnalysis → process_sample → organisation`. Confirm the `analysis` FK in ds-hub already carries that scoping; if so, no extra work needed.
- The new endpoints inherit ds-hub's auth/tenant decorators by virtue of being `@login_required` and going through the same `get_object_or_404(GelAnalysis, pk=pk)` lookup that already filters by org membership in ds-hub.

**Audit point:** after porting models, run `git diff main -- gel_analyzer/models/` and read it line-by-line. Anything red (deletion) that mentions `process_sample`, `organisation`, `created_by_org`, or any tenant field is a port bug — undo and re-apply only the additions.

### 2. Migration numbering

ds-hub is at `0006`; Phoresis ran `0005..0009` for this work. Renumber on the way in, see "Migration numbering" below.

Everything else is paste + smoke test.

## Why this exists

Phoresis is the upstream playground for the gel-analyzer feature set; ds-hub-django is the downstream production deploy. The 89-commit branch on Phoresis (PR #4) ships:

- A full protein quantification feature (calibration model + service + API + UI)
- A per-band shape across the densitometry + sample-comparison tables and charts
- Auto-save plumbing centralized in a single helper
- MW calibration cleanups (R²=0 fix, template picker drop, 1-decimal rounding)
- A handful of bugfixes that are independent but rolled into the same branch

ds-hub-django still has the *pre-quantification* shape: `gel_analyzer.migrations` stops at `0006_laddercalibration_excluded_band_ids`, no `quantification` service folder, no per-band table refactor, and no `auto-save.js` / `api-error.js` shared modules.

The two repos have **near-identical** `gel_analyzer/` layouts — most files apply with `cp` + a path adjust, but a few have diverged. This plan calls those out at the file level.

## Pre-flight checks

Before touching a line:

1. `cd ds-hub-django` and confirm `git status` is clean, `main` is up to date.
2. Create a port branch: `git checkout -b feat/quantification-port`.
3. Run the existing test suite **once** as a baseline so any test regressions are visibly the port's fault: `pytest gel_analyzer/ -q`. Save the count.
4. Check ds-hub Python deps for divergence vs Phoresis:
   - scipy: ds-hub historically pins **1.15**; Phoresis runs **1.17+**. Some Phoresis `xfail`s exist *because* of scipy 1.17 changes (`test_does_not_detect_between_bands`). Don't carry those `xfail`s over — under scipy 1.15 the test should pass.
   - DRF version: confirm `>= 3.14` so `WriteRateThrottle` `scope` semantics match.
   - python-docx, Pillow versions: Phoresis added Pillow LZW handling (commit pre-quantification). Verify ds-hub Pillow >= 10.x.
5. Confirm the Phoresis branch is mergeable on top: `cd ../phoresis && git log feat/quantification -1`. Note the head SHA — it's the source of truth.

## Decision: how to port

**Recommended: cherry-pick + manual port, in 6 phases.**

Not a single squashed copy, because:
- ds-hub has its own house style differences (template scoping, the `biostrain_hub` parent module that Phoresis lacks, slightly different settings layout).
- A squashed mega-commit is unreviewable.
- Some Phoresis commits are pure fixes that can land independently and start delivering value before the big refactor lands.

**Phase ordering matters** — each phase produces a working app, so you can stop, smoke-test, and resume.

### Phase 0 — Independent fixes (low risk, ship first)

These don't depend on quantification and are pure improvements. Land them first so the port branch starts useful.

| Phoresis commit (intent) | ds-hub equivalent file | Notes |
|---|---|---|
| LZW TIFF crop 500 fix | `gel_analyzer/services/file_handler.py` (or wherever crop lives) | Pillow `seek(0)` + `convert("RGB")` before crop. Verify ds-hub Pillow version supports the LZW codec; older builds need `Pillow>=10.0`. |
| MW 1-decimal rounding (write paths) | `gel_analyzer/services/calibration/service.py` line ~705 (`band.estimated_mw_kda = round(mw, 1)`) and `multi_ladder_service.py` line ~526 (`round(.., 1)`) | Both files exist verbatim in ds-hub. |
| MW 1-decimal rounding (DTO + export) | `services/calibration/models.py:to_dict`, `services/densitometry/models.py:to_dict`, `services/densitometry/export.py` (CSV `:.1f`) | Same change, same lines. |
| MW data migration | `gel_analyzer/migrations/0007_round_estimated_mw_to_1_decimal.py` (renumber from Phoresis 0009 → ds-hub 0007 because ds-hub's last is 0006) | Body identical: `Band.objects.exclude(estimated_mw_kda__isnull=True)` round-in-place, no-op reverse. |
| MW frontend display 1 decimal | `gel-viewer/panels/properties-panel.js`, `gel-viewer/panels/band-table-panel.js` | Same lines. Already use `.toFixed(1)` in some places, raw float in others — match Phoresis. |
| Back button visibility | `templates/gel_analyzer/analyses/densitometry.html`, `templates/gel_analyzer/comparisons/compare.html`, `templates/gel_analyzer/analyses/annotate_standalone.html`, `static/gel_analyzer/css/{densitometry,comparison,gel_viewer_standalone}.css` | Add `<span>Back</span>` next to icons, pill style, `svg { stroke: currentColor; fill: none }`. |
| DRF throttle config | `ds_hub_django/settings.py` (or `biostrain_hub/settings/base.py` — verify which is the active settings module) | Add `DEFAULT_THROTTLE_RATES = {"user": "1000/hour", "user_write": "300/hour", "user_computation": "60/hour"}` to `REST_FRAMEWORK`. **Critical** — without this every v1 PATCH 500s with `ImproperlyConfigured`. |

After Phase 0: run pytest, smoke test annotate + densito + compare. Commit each fix individually.

### Phase 1 — Backend models + migrations for quantification

Source files (Phoresis):

- `src/gel_analyzer/models/annotations.py` — adds `Band.quant_point` (FK to `BandQuantPoint`) wait actually Phoresis's setup:
  - `0005_add_quant_calibration_point.py` adds `BandQuantPoint` row hanging off `Band`.
  - `0006_add_protein_quant_calibration.py` adds `ProteinQuantCalibration` model on `GelAnalysis`.
  - `0007_add_densitometry_estimated_amount.py` adds `DensitometryResult.estimated_amount` + `estimated_amount_unit`.
  - `0008_add_quant_calib_last_recomputed_at.py` adds `last_recomputed_at` timestamp.

ds-hub steps:

1. Copy `models/annotations.py` and `models/analysis.py` and `models/densitometry.py` *just the new fields*. Don't replace the whole file — diff carefully.
2. Generate ds-hub migrations 0008 → 0011 by running `manage.py makemigrations gel_analyzer` after each model edit, **in the same order as Phoresis** (so the schemas converge).
3. Verify each migration applies cleanly on a fresh DB: `manage.py migrate gel_analyzer 0006`, then forward each step. Then back: `migrate gel_analyzer 0007`, etc.

**Trap:** `protein_load_ug` / `loading_volume_ul` already exist on `Lane` in ds-hub from migration `0004_add_loading_volume_ul.py` (Phoresis only). Confirm the field is also present in ds-hub before assuming. If absent, port `0004` first.

### Phase 2 — Backend services (quantification + calibration cleanups)

**New service module** — copy verbatim from Phoresis:

- `src/gel_analyzer/services/quantification/__init__.py`
- `src/gel_analyzer/services/quantification/fitters.py` — 4PL, polynomial, log-linear (calls into `fitters_shared.py`)
- `src/gel_analyzer/services/quantification/service.py` — `ProteinQuantService` orchestrator (preview, save, apply_to_analysis, drift detection)
- `src/gel_analyzer/services/quantification/models.py` — DTOs

**Shared fitters extraction** — Phoresis extracted curve-fit helpers into:

- `src/gel_analyzer/services/calibration/fitters_shared.py`

…and updated `calibration/service.py` to import from it. This refactor is purely behaviour-preserving but it touches `service.py` heavily. Do this as a single commit on ds-hub: copy `fitters_shared.py` + edit `service.py` to use the helpers.

**Calibration service updates from Phoresis (this session):**

- `service.py:calibrate(template=None)` — make template optional.
- `service.py` template-fallback gated on `template is not None`.
- `multi_ladder_service.py:calibrate_all_ladders(template=None)` — same.
- `multi_ladder_service.py` logger guard for `template.name`.
- `models.py:MultiLadderCalibrationResult.template_name: str | None`.

**Densitometry service updates:**

- `services/densitometry/service.py` — sample-projection filter to POI bands of SAMPLE lanes only (Phoresis commit `285ab78`).
- `services/densitometry/service.py` — `apply_to_analysis()` server-side back-fill of `estimated_amount` after a calibration save.

After Phase 2: tests should still pass. The new quantification service has its own unit tests in Phoresis (`tests/test_services/test_quantification_*.py`) — copy those over and run.

### Phase 3 — Backend API (DRF + FBV endpoints)

Phoresis's `views/api.py` and `views/densitometry_api.py` got these new / updated endpoints:

| Endpoint | File | Phoresis commit |
|---|---|---|
| `POST /api/analyses/<pk>/quantification/preview/` | `views/api.py` | quantification feature |
| `POST /api/analyses/<pk>/quantification/save/` | `views/api.py` | quantification feature |
| `GET /api/analyses/<pk>/quantification/active/` | `views/api.py` | quantification feature |
| `POST /api/analyses/<pk>/quantification/apply/` | `views/api.py` | quantification feature |
| `GET /api/lanes/<pk>/profile/` (densitometry) | `views/densitometry_api.py` — added `estimated_amount` + `estimated_amount_unit` to band dict | `4ca9316` |
| `POST /api/analyses/<pk>/calibrate/` (single ladder) | `views/api.py:api_analysis_calibrate` | `94a1336` — top-level `r_squared`, `average_r_squared`, `calibrations[]`, optional `template_id` |
| `POST /api/analyses/<pk>/calibrate-multi/` | `views/api.py:api_analysis_calibrate_multi` | `94a1336` — optional `template_id` |

**Throttle classes** — Phoresis added `WriteRateThrottle` at `gel_analyzer/api/throttles.py`. Verify ds-hub already has it; if not, copy it. Make sure the v1 viewsets (Bands, Lanes, GelImages, GelAnalysis, LadderTemplates, SavedComparisons) declare `throttle_classes = [WriteRateThrottle]` consistently.

**URL wiring** — port the URL patterns for the new endpoints (`gel_analyzer/urls.py` or `gel_analyzer/api/urls.py` — check ds-hub layout).

**Serializers** — `api/serializers.py:BandSerializer` + `BandWriteSerializer` got new fields (`quant_point`, `densitometry.estimated_amount`, etc.) and a `_validate_band_quant_point` helper. Port verbatim. Also port the `_auto_promote_lane_for_band` helper from Phoresis (it auto-bumps a parent lane to CALIBRATION when a calibration band is added).

After Phase 3: smoke test via `curl`/Postman. The new endpoints should return well-formed JSON. The DRF browsable API page should show the new viewset actions.

### Phase 4 — Frontend shared infrastructure

The auto-save refactor (Phoresis steps 1–7) introduced two **new** shared modules and added two events. Copy these first because every panel migration depends on them:

```
static/gel_analyzer/js/shared/auto-save.js       (NEW — copy verbatim)
static/gel_analyzer/js/shared/api-error.js       (NEW — copy verbatim)
```

Templates need to load these before any panel script:

```html
<!-- Add near the top of every page that uses gel-viewer / densitometry / comparison -->
<script src="{% static 'gel_analyzer/js/shared/api-error.js' %}"></script>
<script src="{% static 'gel_analyzer/js/shared/auto-save.js' %}"></script>
```

…in:

- `templates/gel_analyzer/analyses/annotate_standalone.html`
- `templates/gel_analyzer/analyses/densitometry.html`
- `templates/gel_analyzer/comparisons/compare.html`

**Event bus** — `gel-viewer/event-bus.js`: add `AUTOSAVE_OK: 'autosave:ok'` and `AUTOSAVE_FAILED: 'autosave:failed'`. Same for `densitometry/densitometry-event-bus.js` if it has its own (Phoresis has both).

**Boot** — in `gel-viewer.js`, instantiate `AutoSave.create({eventBus, showToast})` once and store on the gel-viewer instance. Same for `densitometry-app.js` and `sample-comparison-app.js`.

### Phase 5 — Frontend panels (densitometry + comparison)

**Order matters.** Do gel-viewer first so the auto-save plumbing is exercised in the simplest panel, then densitometry, then comparison.

**Gel-viewer migrations:**

1. `gel-viewer/gel-viewer.js`: replace `_updateBand`, `_createBand`, `_deleteBand` fire-and-forget catches with `AutoSave.run()`. Keep `BAND_SAVE_*` events for the temp-ID swap path.
2. `gel-viewer/gel-viewer.js`: SAM polygon refine (lines ~2312, 2375), calibration data fetch (lines ~604, 2193), annotation reload (lines ~858, 1935), bulk lane operations.
3. `gel-viewer/panels/properties-panel.js`: switch to `AUTOSAVE_OK` / `AUTOSAVE_FAILED` listeners. Reuse existing `_setSaveErrorState` and `_flashSavedInput`. Remove bespoke try/catch in `_autoSaveCalibrationValue`.
4. `gel-viewer/api-client.js`: every throw-on-error path uses `extractApiError(response, 'fallback message')`.
5. `gel-viewer/panels/calibration-panel.js`:
   - R²=0 fix: harden `_updateR2Display` (cascade to `result.calibration.r_squared` and `result.result.r_squared`).
   - Drop the template picker UI from `_calibration_panel.html` (Step 1 block + footer-hint default).
   - Rename internal step number from 3 → 2 in the visible UI.
   - `_renderLadderList`: enable the Run Calibration button as soon as any ladder lane has ≥3 MW-assigned bands.
   - `_runCalibration`: relax gate to `selectedTemplate || lanesWithMW.length > 0`.
   - `api-client.js:calibrateSingle/calibrateMulti`: omit `template_id` from body when null.

**Densitometry panel migrations:**

| File | Change |
|---|---|
| `densitometry/densitometry-api-client.js` | Use `extractApiError`. Add `getActiveQuantification`, `previewQuantification`, `saveQuantification`, `applyQuantification` methods. |
| `densitometry/panels/results-table-panel.js` | **Full rewrite** — per-band shape (one row per band where `band_type !== 'OTHER'`), columns `Lane# | Type | Sample | Band | Total area | Band area | % lane | Est. amount | Recovery % | Fit R² | Flag`. Click → `state.selectBand(bandId)`. Drop drill-down. |
| `densitometry/panels/chromatogram-panel.js` | Add Quantification curve sub-view via `renderQuantificationView` host div + `_quantController`. CRITICAL: in `_createChart()` preserve the `.dm-quantification-container` element when wiping `innerHTML`. |
| `densitometry/panels/quantification-curve-renderer.js` | **NEW file** — copy verbatim from Phoresis. D3-based interactive renderer with hover, click-to-select, magnifier-aware. Per-role y-field extraction (`load_amount` for calibration, `predicted_amount` for control, `estimated_amount` for sample). |
| `densitometry/panels/quantification-modal.js` | **NEW file** — calibration method picker (LIN/POLY2/4PL), exclusion + retry UX, drift detection. Copy verbatim. |
| `densitometry/panels/gel-overview-panel.js`, `band-detail-panel.js` | Add CALIBRATION + lane-type colors (Phoresis commit `b2f6a4c`). |
| `templates/gel_analyzer/analyses/densitometry.html` | Add quant container `<div id="dm-quantification-container">` with `<div id="dm-quantification-host">` and `<div id="dm-quantification-empty-wrap">`. Add view-toggle button for "Quantification curve". Add modal HTML. Inline POI Purity renderer changes (grouped bars per lane, per-POI). Drop `?v=` cache busters since manifest hashing handles prod. |
| `static/gel_analyzer/css/densitometry.css` | Add `.dm-quantification-*` classes, `.gv-prop-type-mw_reference` etc. Container scrollbar containment fix (`inset:0; overflow:hidden; padding:8px 8px 4px 8px`). Per-band row hover/selected styles for `.dm-band-row` at top level. |

**Sample comparison panel migrations:**

| File | Change |
|---|---|
| `sample-comparison/sample-comparison-api.js` | Use `extractApiError`. |
| `sample-comparison/panels/band-detail-panel.js` | "No MW calibration" empty state — when a lane has zero bands with `estimated_mw_kda`, render the explicit notice instead of stacking every band at `topPercent=50%`. Bands in a partially-calibrated lane that lack MW: hidden with footer count. |
| `sample-comparison/panels/results-table-panel.js` | **Full rewrite** — same per-band shape as densitometry. Click → `state.selectBand(bandId)`. |
| `sample-comparison/panels/poi-purity-panel.js` | Grouped bars: outer scaleBand per sample, inner scaleBand per POI band. Tooltip with band ref / MW / area / purity. Click cascade. Listens to `BAND_SELECTED` in addition to `SAMPLE_SELECTED`. |
| `sample-comparison/panels/content-chart-panel.js` | **NEW file** — third view ("Content"), grouped bars of `estimated_amount` per POI per sample. Emits `content-chart:availability` event so the host page can show/hide the view button. |
| `sample-comparison/sample-comparison-app.js` | Mount the new ContentChart panel. |
| `templates/gel_analyzer/comparisons/compare.html` | Add Content view button (initially `display: none`), Content container, script tag for `content-chart-panel.js`. Update switchView to handle the new view. Listen for `content-chart:availability` to show/hide the button. |
| `static/gel_analyzer/css/comparison.css` | `.dm-lane-no-mw*` styles for the empty state. `.cmp-band-row` top-level hover/selected. `.cmp-content-*` chart styles. |

### Phase 6 — Tests + smoke verification

**Port tests:**

- `tests/test_services/test_quantification_*.py` (4 files: `test_quantification_service`, `test_quantification_fitters`, `test_quantification_drift`, `test_quantification_apply`)
- `tests/test_views/test_api_quantification.py` — DRF + FBV endpoint coverage
- `tests/test_services/test_calibration_*.py` — pick up the optional-template + R² test additions if any

Run: `pytest gel_analyzer/ -q`. Compare to baseline from pre-flight step 3.

**Manual smoke checklist (matches PR #4's test plan):**

1. Run a single-ladder calibration → R² indicator shows real value (not `0.0000`).
2. Open MW Calibration modal → no template picker visible, Run Calibration enables when ≥3 MW-assigned bands.
3. Right-click a band → Set as Calibration → properties panel + lane color update; right-click again to set the loaded amount → green flash, no save button.
4. Open densitometry → Measurement tab → one row per important band; click any row → gel overview, band detail, chromatogram, POI bar all sync.
5. Densitometry → Graphical View → Quantification curve → click a calibration / control / sample point → same cascade.
6. Multi-POI lane → POI Purity tab shows grouped bars (one bar per POI inside the lane group).
7. Apply calibration to a sample analysis with quantified POIs → open `/compare/` → Content view button appears.
8. Comparison → Band Detail → lanes without MW calibration show explicit notice (not stray middle bar).
9. Hard-reload all three modules → Back button visible (label + icon, pill style).
10. All MW values display with 1 decimal across annotation / densitometry / comparison.
11. Stop the runserver mid-edit → red toast surfaces actual fetch error, inline Retry button on properties-panel.
12. Restart and click Retry → save succeeds, toast clears.

## Cross-cutting concerns

### Migration numbering

ds-hub is at `0006`. Phoresis's relevant migrations (in order):

| Phoresis | Purpose | ds-hub equivalent |
|---|---|---|
| `0004_add_loading_volume_ul` | `Lane.loading_volume_ul` | Verify it exists in ds-hub already; if not, port as the next missing number. |
| `0005_add_quant_calibration_point` | `BandQuantPoint` model | ds-hub `0007_*` |
| `0006_add_protein_quant_calibration` | `ProteinQuantCalibration` model | ds-hub `0008_*` |
| `0007_add_densitometry_estimated_amount` | `DensitometryResult.estimated_amount` | ds-hub `0009_*` |
| `0008_add_quant_calib_last_recomputed_at` | `last_recomputed_at` timestamp | ds-hub `0010_*` |
| `0009_round_estimated_mw_to_1_decimal` | data migration rounding existing values | ds-hub `0011_*` |

Use `manage.py makemigrations gel_analyzer --name <descriptive>` after each model edit so dependencies wire automatically. Don't hand-write the dependency list.

### Settings module

ds-hub uses `ds_hub_django/settings.py` (or `biostrain_hub/settings/<env>.py` — verify). Phoresis uses `phoresis/settings/{base,dev,prod,test}.py`. The throttle config block needs to land in whichever one ds-hub treats as base — likely `settings.py` directly or `settings/base.py`.

### CSP / static / WhiteNoise

Phoresis runs WhiteNoise with manifest hashing — that's why we dropped `?v=` cache busters. ds-hub may differ. Verify:

- Is WhiteNoise active in ds-hub? Check `MIDDLEWARE` for `whitenoise.middleware.WhiteNoiseMiddleware`.
- If yes: drop cache busters to match.
- If no: leave them in place (they're the only invalidation mechanism without manifest hashing).

### Multi-tenant / auth divergence

ds-hub-django is a multi-tenant hub with `organisation_management`, `authentication`, etc. Phoresis is single-user.

Check whether any of the new endpoints need a tenant scope:

- `ProteinQuantCalibration` likely needs to inherit ds-hub's tenant filtering — find how `GelAnalysis` is tenant-scoped in ds-hub and apply the same pattern. Probably handled automatically through the `analysis` FK if `GelAnalysis` is already scoped.
- `BandQuantPoint` hangs off `Band`, transitively scoped via `Lane → GelAnalysis`.
- Endpoints: confirm they go through the same `LoginRequiredMixin` / org-membership decorator that the existing endpoints use.

If unsure: search how `views/api.py:api_analysis_calibrate` is decorated in ds-hub and apply identical decoration to the new quant endpoints.

### Templates: Django comment syntax

Phoresis hit this ≥3 times: `{# ... #}` is **single-line only**; multi-line needs `{% comment %} ... {% endcomment %}`. Run `grep -rn '{#[^#]*$' gel_analyzer/templates/` after editing any template to catch mid-paste mistakes.

### Reports

ds-hub has a `services/report/` folder with `densitometry_builder.py`, `comparison_builder.py`, etc. These don't *need* changes for quantification — they read from `Band.estimated_mw_kda` which gets server-back-filled. But:

- The new `estimated_amount` field could enrich Excel / PPTX exports. **Out of scope** for this port; flag as a follow-up.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration ordering conflict with parallel ds-hub work | Medium | Run `manage.py makemigrations --check` before merging; rebase on `main` if drift detected. |
| Tests fail under scipy 1.15 (ds-hub) where they pass on Phoresis 1.17 | Low | Phoresis has 4 documented `xfail`s — they may *pass* on 1.15. Don't carry the `xfail` decorators over without testing. |
| Multi-tenant scoping bypass on new quant endpoints | High if ignored | Trace `api_analysis_calibrate` decorators in ds-hub and copy them onto the new quant endpoints. Code review must check this. |
| `Lane.process_sample` FK or related queryset filtering accidentally wiped during model port | **High** — would break the comparison wizard | Always *add* fields, never replace whole files. After each model edit run `git diff main -- gel_analyzer/models/` and confirm no `process_sample`-related lines disappeared. The Phoresis branch deliberately doesn't carry process-sample plumbing — copying its model files wholesale would silently delete ds-hub features. |
| WhiteNoise vs static-serving mismatch | Low | If cache busters were already dropped on ds-hub or never used, this is a no-op. |
| Auto-save events conflicting with existing event names | Low | The two new events (`autosave:ok`, `autosave:failed`) are namespaced. Grep ds-hub for the exact strings before adding. |
| Band Editor's "Apply ladder template" button missing / different shape | Medium | The calibration modal port assumes this button drives MW assignment. Verify it exists in ds-hub `band-table-panel.js` (line ~564 in Phoresis). If the UX differs, leave the calibration modal's template picker until ds-hub catches up. |

## Suggested commit ordering on the port branch

```
1. fix: LZW TIFF crop edge case
2. fix: DRF throttle config gap (DEFAULT_THROTTLE_RATES)
3. fix: MW back button visibility across the three modules
4. fix(mw): round estimated MW to 1 decimal everywhere + back-fill DB
5. refactor(calibration): extract fitters_shared.py
6. feat(calibration): make ladder template optional + R²=0 fix
7. feat: protein quantification — models + migrations
8. feat: protein quantification — service + DTOs + tests
9. feat: protein quantification — DRF + FBV endpoints + serializers
10. feat: shared auto-save + api-error JS modules
11. refactor(gel-viewer): migrate band ops + properties-panel to AutoSave
12. refactor(gel-viewer): migrate api-client to extractApiError
13. refactor(gel-viewer): drop template picker from MW calibration modal
14. feat(densito): per-band measurement table
15. feat(densito): grouped POI purity bars
16. feat(densito): quantification curve sub-view
17. feat(densito): quantification modal
18. fix(densito): _createChart preserves quant container
19. fix(densito): quant panel scrollbar containment
20. feat(comparison): align comparison panels with densitometry shape
21. feat(comparison): no-MW empty state on band detail
22. feat(comparison): grouped POI purity + new Content chart
23. fix(densito): teach panels about CALIBRATION + lane-type colors
24. chore: drop ?v= cache busters (if WhiteNoise + manifest hashing in use)
```

Each commit should pass tests in isolation. Don't bundle commits that break each other.

## When to merge

PR-only. The feature is too large to push directly to `main` even with the v1.0.x bug-hunt waiver. Open the port PR with this plan linked in the description, request review, merge after green CI.

## Estimated effort

- **Phase 0 (independent fixes):** half a day, low cognitive load.
- **Phases 1–3 (backend):** 1–2 days, mostly mechanical port + test pass.
- **Phase 4 (shared frontend):** half a day.
- **Phase 5 (panels):** 2–3 days, the bulk of the work — many files, careful CSS adjustments per ds-hub theme.
- **Phase 6 (tests + smoke):** half a day.

**Total:** 4–6 working days assuming no surprises. The risk register entries can each add 0.5–1 day if they bite.

## Open questions to answer before starting

1. Is `Lane.loading_volume_ul` already in ds-hub? (Determines whether to port Phoresis's `0004_add_loading_volume_ul.py` first.)
2. What's ds-hub's settings module path? (Determines where the throttle config lands.)
3. Does ds-hub use WhiteNoise + manifest hashing in dev? (Determines whether to drop `?v=` busters.)
4. Does the multi-tenant filter on `GelAnalysis` propagate automatically through the new FKs, or do we need explicit org-scope checks on the quant endpoints?
5. Is the Band Editor's "Apply ladder template" button shape identical between Phoresis and ds-hub? (Determines whether the calibration modal's template-picker drop is safe in ds-hub.)

Answer these in a checklist comment on the port PR before merging.
