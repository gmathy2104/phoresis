# Report Generation Implementation Guide

Reference architecture for building multi-format (Word/Excel/PowerPoint) report modules in Phoresis. Based on the **Comparison Report** implementation. Follow this pattern when creating report generation for other modules (e.g., Densitometry, Analysis).

---

## Architecture Overview

```
views/report_api.py          # HTTP endpoint: parse format/sections, dispatch to builder
services/report/
    constants.py              # Section keys, format maps, thresholds, shared constants
    {module}_data_collector.py  # Query DB, build typed dataclass tree
    {module}_builder.py         # Word (.docx) builder using python-docx
    {module}_excel_builder.py   # Excel (.xlsx) builder using openpyxl
    {module}_pptx_builder.py    # PowerPoint (.pptx) builder using python-pptx
    poi_purity_chart.py         # Shared matplotlib chart renderers (reusable)
    __init__.py                 # Public exports
```

### Data Flow

```
HTTP POST (format, sections, options)
    -> API view validates input
    -> DataCollector.collect(entity, user) -> ReportData dataclass
    -> Builder(data, sections, options).build() -> BytesIO
    -> HttpResponse with Content-Disposition attachment
```

---

## Step-by-Step Implementation

### 1. Constants (`constants.py`)

Define all section metadata, format mappings, and shared values.

```python
# Section registry: (key, human_label)
REPORT_SECTIONS = [
    ('overview', 'Overview'),
    ('sample_summary', 'Sample Summary Table'),
    ('digital_gel', 'Side-by-Side Digital Gel'),
    ('gel_images', 'Reconstructed Gel Images'),
    ('band_comparison', 'Band Comparison (MW-clustered)'),
    ('lane_details', 'Individual Lane Details'),
    ('poi_purity', 'POI Purity Chart'),
    ('materials_methods', 'Materials & Methods'),
]
ALL_SECTION_KEYS = [k for k, _ in REPORT_SECTIONS]

# Supported output formats
REPORT_FORMATS = ['docx', 'xlsx', 'pptx']
FORMAT_CONTENT_TYPES = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}
FORMAT_EXTENSIONS = {'docx': '.docx', 'xlsx': '.xlsx', 'pptx': '.pptx'}

# Thresholds, methodology text, branding paths...
```

**Key principle:** All section keys, format strings, and threshold values live in `constants.py`. Builders import from here, never hardcode.

---

### 2. Data Collector (`{module}_data_collector.py`)

Queries the database and returns a **typed dataclass tree**. Builders never touch the ORM directly.

```python
@dataclass
class BandReportData:
    band_number: int
    band_type: str
    estimated_mw_kda: Optional[float]
    corrected_area: Optional[float]
    relative_percent_lane: Optional[float]
    # ... all fields needed by any builder

@dataclass
class LaneReportData:
    lane_id: int
    lane_number: int
    sample_name: str
    x: int; y: int; width: int; height: int  # geometry for image cropping
    bands: list[BandReportData]
    profile_data: Optional[dict]  # electropherogram Y-values
    gel_image_id: Optional[int]   # FK for server-side image loading
    # ...

@dataclass
class ModuleReportData:
    """Top-level container with all data for all builders."""
    name: str
    lanes: list[LaneReportData]
    created_by_name: str
    report_generated_at: str
    report_generated_by: str
    # ... module-specific fields
```

**Key principles:**
- Collector does ALL database queries (with `select_related`/`prefetch_related`)
- Returns pure dataclasses - no Django model instances leak to builders
- Profile data (electropherogram points) stored as `dict` for matplotlib rendering
- Geometry (`x`, `y`, `width`, `height`) stored for server-side image cropping
- `gel_image_id` stored so builders can load images on-demand from storage

---

### 3. Word Builder (`{module}_builder.py`)

Uses `python-docx`. This is the richest builder with all sections.

```python
class ModuleReportBuilder:
    def __init__(self, data: ModuleReportData, sections=None, **options):
        self.data = data
        self.sections = sections  # None = all
        self.doc = Document()
        self._setup_styles()

    def _should_include(self, key: str) -> bool:
        return self.sections is None or key in self.sections

    def build(self) -> BytesIO:
        self._add_cover_page()  # always
        section_map = [
            ('overview', self._add_overview),
            ('sample_summary', self._add_sample_summary),
            # ...
        ]
        section_num = 1
        for key, method in section_map:
            if self._should_include(key):
                method(section_num)
                section_num += 1
        self._add_footer()  # always
        buf = BytesIO()
        self.doc.save(buf)
        buf.seek(0)
        return buf
```

**Image rendering methods** (Pillow-based, reused by PPTX builder):
- `_render_digital_gel(lanes)` -> BytesIO PNG: synthetic lane strips from profile data
- `_render_reconstructed_gel(lanes, show_bands)` -> BytesIO PNG: cropped real gel images stitched side-by-side with optional band overlay rectangles
- `_render_electropherogram(lane, index)` -> BytesIO PNG: matplotlib intensity profile
- `_render_lane_composite(lane, index)` -> BytesIO PNG: side-by-side real crop + digital lane + MW scale

**Key principles:**
- Section numbering is dynamic (counter increments only for included sections)
- Cover page and footer are always present
- Image methods return `BytesIO` or `None` - callers handle the None case
- Band clustering algorithm (`_cluster_bands_by_mw`) is reused across builders via `__new__` pattern

---

### 4. Excel Builder (`{module}_excel_builder.py`)

Uses `openpyxl`. Creates multi-sheet workbooks. Image-only sections are skipped.

```python
# Sections that don't apply to spreadsheets
_EXCEL_SKIP_SECTIONS = {'digital_gel', 'gel_images', 'materials_methods'}

class ModuleExcelBuilder:
    def __init__(self, data, sections=None, **options):
        self.data = data
        self.sections = sections
        self.wb = Workbook()
        self.wb.remove(self.wb.active)  # remove default sheet

    def _should_include(self, key: str) -> bool:
        if key in _EXCEL_SKIP_SECTIONS:
            return False
        return self.sections is None or key in self.sections

    def build(self) -> BytesIO:
        sheet_map = [
            ('overview', self._add_overview_sheet),
            ('sample_summary', self._add_sample_summary_sheet),
            # ...
        ]
        for key, method, in sheet_map:
            if self._should_include(key):
                method()
        if not self.wb.sheetnames:
            self._add_overview_sheet()  # ensure at least 1 sheet
        buf = BytesIO()
        self.wb.save(buf)
        buf.seek(0)
        return buf
```

**Branding constants** (from `constants.py`):
```python
_ACCENT_HEX = TABLE_HEADER_BG  # '2563EB', the app's accent-600
_HEADER_FILL = PatternFill(start_color=_ACCENT_HEX, ...)
_HEADER_FONT = Font(name='Inter', bold=True, color='FFFFFF', size=11)
_BODY_FONT = Font(name='Inter', size=10)
```

**Utility methods:**
- `_write_header_row(ws, headers)` - accent header row
- `_auto_width(ws, headers)` - auto-size columns
- Charts embedded as images via matplotlib render -> `XlImage(chart_buf)`

---

### 5. PowerPoint Builder (`{module}_pptx_builder.py`)

Uses `python-pptx`. Subclass `pptx_base.BasePptxReportBuilder`: it builds on python-pptx's default template made a
16:9 deck in code (no template file), and maps the decks' slide kinds to its layouts (`pptx_base.LAYOUTS`).

```python
class ModulePowerPointBuilder(BasePptxReportBuilder):
    def __init__(self, data, sections=None, **options):
        super().__init__()  # self.prs: the neutral 16:9 deck
        self.data = data
        self.sections = sections
        self.slide_number = 0
```

**Shared slide helpers:**
- `_new_slide()` - adds a title slide without its empty body, increments counter
- `_add_header_bar(slide, title, height=1.0)` - sets the layout's title
- `_add_slide_number(slide)` - no-op: `build()` numbers every slide but the cover, bottom right
- `_add_kv_table(slide, data, top)` - two-column key-value table
- `_add_data_table(slide, headers, rows, top, max_rows)` - compact data table: plain header over an accent rule, faint zebra
- `_add_image_to_slide(slide, image_buf, top, max_width, max_height)` - centered image with aspect ratio preservation

**Side-by-side layout pattern** (e.g., gel image + table):
```python
def _add_gel_table_slide(self):
    slide = self._new_slide()
    self._add_header_bar(slide, 'Title', height=0.8)

    # Left: image (55% width)
    gel_buf = self._render_image(...)
    if gel_buf:
        slide.shapes.add_picture(gel_buf, Inches(0.3), Inches(1.0), ...)

    # Right: compact table (45% width)
    table_shape = slide.shapes.add_table(
        n_rows, n_cols,
        Inches(7.4), Inches(1.0),    # positioned right
        Inches(5.6), Inches(height),
    )
    # Use Pt(7) for compact tables
```

**Reusing Word builder renderers:**
```python
from .comparison_builder import ComparisonReportBuilder

builder = ComparisonReportBuilder.__new__(ComparisonReportBuilder)  # skip __init__
builder.data = self.data
image_buf = builder._render_reconstructed_gel(self.data.lanes, show_bands=True)
```

This `__new__` pattern lets PPTX/Excel builders call Pillow/matplotlib render methods defined in the Word builder without duplicating code. The render methods only use `self.data` and parameters, never `self.doc`.

---

### 6. API Endpoint (`views/report_api.py`)

Single POST endpoint per entity type, dispatching to the correct builder.

```python
@login_required
@require_http_methods(["POST"])
def api_generate_report(request, pk: UUID):
    entity = get_object_or_404(Model, pk=pk)

    # Parse optional JSON body (backward compatible with empty body)
    report_format = 'docx'
    sections = None
    band_overlay = True

    if request.body:
        body = json.loads(request.body) if request.body else {}
        report_format = body.get('format', 'docx')
        sections = body.get('sections', None)
        band_overlay = body.get('band_overlay', True)

    # Validate
    if report_format not in REPORT_FORMATS: ...
    if sections is not None:
        invalid = [s for s in sections if s not in ALL_SECTION_KEYS]
        if invalid: ...

    # Collect data
    collector = DataCollector()
    data = collector.collect(entity, request.user)

    # Dispatch to builder
    if report_format == 'docx':
        builder = WordBuilder(data, sections=sections, band_overlay=band_overlay)
    elif report_format == 'xlsx':
        builder = ExcelBuilder(data, sections=sections, band_overlay=band_overlay)
    elif report_format == 'pptx':
        builder = PowerPointBuilder(data, sections=sections, band_overlay=band_overlay)

    doc_buffer = builder.build()

    # Return file download
    ext = FORMAT_EXTENSIONS[report_format]
    content_type = FORMAT_CONTENT_TYPES[report_format]
    response = HttpResponse(doc_buffer.getvalue(), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}{ext}"'
    return response
```

**API contract:**
```
POST /api/{module}/<uuid>/report/generate/
Body: { "format": "docx"|"xlsx"|"pptx", "sections": [...], "band_overlay": true }
Response: File download
```

---

### 7. Frontend Modal (Django template)

The report config modal uses **hierarchical section groups** with parent-child toggle behavior.

#### HTML Structure
```html
<div id="report-config-modal" class="dm-modal-overlay">
  <div class="dm-modal">
    <!-- Format selection: 3 radio cards (Word/Excel/PowerPoint) -->
    <div class="dm-report-format-group">
      <label class="dm-report-format-option">
        <input type="radio" name="report_format" value="docx" checked>
        <span class="dm-report-format-card">Word .docx</span>
      </label>
      <!-- ... excel, pptx ... -->
    </div>

    <!-- Section groups with parent-child hierarchy -->
    <div class="dm-report-sections-list">
      <!-- Group: Summary -->
      <div class="dm-report-section-group" data-group="summary">
        <div class="dm-report-group-header">
          <input type="checkbox" data-group-toggle="summary" checked>
          <span class="dm-report-group-chevron">&#x25BE;</span>
          <span>Summary</span>
        </div>
        <div class="dm-report-group-children" data-group-body="summary">
          <label><input type="checkbox" data-section-key="overview" checked> Overview</label>
          <label><input type="checkbox" data-section-key="sample_summary" checked> Sample Summary</label>
        </div>
      </div>

      <!-- Group: Gel Visuals (disabled for Excel format) -->
      <div class="dm-report-section-group" data-group="gel_visuals">
        <!-- ... children with data-depends-on for sub-options -->
      </div>

      <!-- Standalone items outside groups -->
      <label><input type="checkbox" data-section-key="materials_methods" checked> Materials & Methods</label>
    </div>
  </div>
</div>
```

#### JavaScript Pattern
```javascript
const reportModal = {
    overlay: document.getElementById('report-config-modal'),

    open() { this.overlay.style.display = 'flex'; this.updateAllGroups(); },
    close() { this.overlay.style.display = 'none'; },

    getFormat() {
        return this.overlay.querySelector('input[name="report_format"]:checked')?.value || 'docx';
    },

    getSections() {
        const sections = [];
        this.overlay.querySelectorAll('input[data-section-key]:checked').forEach(cb => {
            if (!cb.disabled) sections.push(cb.dataset.sectionKey);
        });
        return sections;
    },

    // Group toggle: enable/disable all children when parent checkbox changes
    onGroupToggle(groupName) {
        const toggle = this.overlay.querySelector(`input[data-group-toggle="${groupName}"]`);
        const body = this.overlay.querySelector(`[data-group-body="${groupName}"]`);
        const enabled = toggle.checked;
        body.classList.toggle('dm-report-group-disabled', !enabled);
        body.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.disabled = !enabled;
            if (!enabled) cb.checked = false;
        });
        // Collapse chevron
        const chevron = toggle.closest('.dm-report-group-header')?.querySelector('.dm-report-group-chevron');
        if (chevron) chevron.classList.toggle('collapsed', !enabled);
        this.updateDependencies();
    },

    // Sub-option dependencies (e.g., band_overlay depends on gel_images)
    updateDependencies() {
        this.overlay.querySelectorAll('[data-depends-on]').forEach(el => {
            const parentKey = el.dataset.dependsOn;
            const parentCb = this.overlay.querySelector(`input[data-section-key="${parentKey}"]`);
            const cb = el.querySelector('input[type="checkbox"]');
            if (parentCb && cb) {
                const enabled = parentCb.checked && !parentCb.disabled;
                cb.disabled = !enabled;
                if (!enabled) cb.checked = false;
            }
        });
    },

    // Format change: disable image-only sections for Excel
    onFormatChange() {
        const format = this.getFormat();
        const gelGroup = this.overlay.querySelector('[data-group="gel_visuals"]');
        if (format === 'xlsx') {
            gelGroup.classList.add('disabled-section');
            gelGroup.querySelectorAll('input').forEach(cb => { cb.disabled = true; cb.checked = false; });
        } else {
            gelGroup.classList.remove('disabled-section');
            // Re-enable based on group toggle state
            this.onGroupToggle('gel_visuals');
        }
    },

    async generate() {
        const format = this.getFormat();
        const sections = this.getSections();
        const bandOverlay = /* ... */;
        const response = await fetch(reportUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ format, sections, band_overlay: bandOverlay }),
        });
        // Download blob...
    },
};
```

#### CSS Classes (`.dm-` prefix for dark theme)
```css
.dm-report-section-group { border-radius: 8px; margin-bottom: 2px; }
.dm-report-section-group.disabled-section { opacity: 0.4; pointer-events: none; }
.dm-report-group-header { display: flex; gap: 8px; padding: 8px 10px; cursor: pointer; font-weight: 600; }
.dm-report-group-chevron { transition: transform 0.15s ease; }
.dm-report-group-chevron.collapsed { transform: rotate(-90deg); }
.dm-report-group-children { padding-left: 18px; border-left: 2px solid rgba(255,255,255,0.06); margin-left: 18px; }
.dm-report-group-children.dm-report-group-disabled { opacity: 0.35; pointer-events: none; }
.dm-report-sub-option { padding-left: 36px; font-size: 0.8rem; }
```

---

## Branding Reference

| Element | Value |
|---------|-------|
| Accent | `#2563EB` (`PHORESIS_ACCENT`, the app's accent-600) |
| Dark accent | `#1D4ED8` (`PHORESIS_ACCENT_DARK`) |
| Font (headers) | `Inter`, bold (`HEADING_FONT`) |
| Font (body) | `Inter` (`BODY_FONT`) |
| Logo | none (`PHORESIS_LOGO_PATH` is empty) |
| Header font sizes | Word: 14pt section, 11pt body / Excel: 11pt / PPTX: 28pt slide title, 10pt table |
| Compact table font | PPTX: 7pt for side-by-side layouts |
| Accent palette (8 colors) | Blue, Purple, Green, Orange, Pink, Teal, Amber, Indigo |

---

## Server-Side Image Rendering

All report images are rendered server-side (no client-side capture needed for comparison reports).

### Reconstructed Gel (`_render_reconstructed_gel`)
- Loads `GelImage` from DB via `gel_image_id`
- Crops each lane using geometry (`x`, `y`, `width`, `height`) with padding
- Resizes all crops to uniform `100px x 400px`
- Stitches side-by-side with header (sample name, lane#), accent color bar, and footer (gel type)
- Optional band overlay: translucent rectangles with MW labels, coordinates mapped from original image space to crop space
- Returns `BytesIO` PNG or `None`

### Digital Gel (`_render_digital_gel`)
- Uses `profile_data` (Y intensity array) from `LaneDensitometrySummary`
- Renders synthetic lane strips as grayscale columns
- Same visual layout as reconstructed gel (header, accent bar, footer)

### Electropherogram (`_render_electropherogram`)
- matplotlib line chart of intensity vs position/MW
- Band regions highlighted with colored fills
- POI bands in purple, Other in green, Ladder in orange
- `dark_theme` parameter for Word (dark bg) vs PPTX/Excel (white bg)

### POI Purity Chart (`poi_purity_chart.py`)
- matplotlib horizontal bar chart
- One bar per sample, colored by accent palette
- Threshold lines at 90% (green) and 70% (yellow)
- Value labels on bars
- Shared across all three builders

---

## Checklist for New Module

1. [ ] Define section keys in `constants.py`
2. [ ] Create `{module}_data_collector.py` with typed dataclasses
3. [ ] Create Word builder with all sections + image renderers
4. [ ] Create Excel builder (skip image-only sections)
5. [ ] Create PowerPoint builder (reuse Word builder renderers via `__new__`)
6. [ ] Add API endpoint in `views/report_api.py`
7. [ ] Add URL pattern
8. [ ] Add frontend modal with hierarchical section groups
9. [ ] Export new builders in `__init__.py`
10. [ ] Test all 3 formats with full and partial section selection
