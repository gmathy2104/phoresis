"""
Constants for Phoresis report generation (Word, PowerPoint, Excel).

The colour and typography tokens here mirror the live web app's design
tokens (`src/phoresis_ui/static/phoresis_ui/css/tokens.css`) so the
exported reports stay visually aligned with what the user sees on
screen. The lane / band palettes mirror the gel-viewer overlay styles
in `gel_viewer_standalone.css` and `gel-preview.js`.
"""

from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

# ── Brand palette ─────────────────────────────────────────────────────
# Anchored on the live app's accent-600 (tokens.css: --color-accent-600).
PHORESIS_ACCENT = (37, 99, 235)  # #2563EB — primary action / headers
PHORESIS_ACCENT_DARK = (29, 78, 216)  # #1D4ED8
PHORESIS_ACCENT_LIGHT = (219, 234, 254)  # #DBEAFE — subtle fills
PHORESIS_INK = (15, 23, 42)  # #0F172A — primary text
MUTED_GRAY = (100, 116, 139)  # #64748B — secondary text
BORDER_GRAY = (226, 232, 240)  # #E2E8F0 — subtle borders
ALT_ROW_FILL = (245, 247, 250)  # very-light blue-gray for table zebra

# Hex strings for libraries that prefer them (openpyxl, RGBColor)
PHORESIS_ACCENT_HEX = "2563EB"  # accent-600, without the hash (python-pptx, openpyxl, python-docx shading)
TABLE_HEADER_BG = PHORESIS_ACCENT_HEX
TABLE_HEADER_FG = "FFFFFF"
TABLE_ALT_ROW = "F5F7FA"

# ── Typography ────────────────────────────────────────────────────────
# Inter is the live app's `--font-sans`. Fallback to system sans-serif
# at the python-docx / pptx layer (each library handles fallback itself).
BODY_FONT = "Inter"
HEADING_FONT = "Inter"

# Font sizes (pt)
TITLE_SIZE = 28
SECTION_H1_SIZE = 16
SECTION_H2_SIZE = 14
SECTION_H3_SIZE = 12
BODY_SIZE = 11
TABLE_SIZE = 10  # bumped from 9 — 9pt is hard to read in Word at 100% zoom
SMALL_SIZE = 10

# Asset paths
# Logo intentionally unset; downstream builders must guard against missing logo.
PHORESIS_LOGO_PATH = ""  # add when a vector / png lives somewhere stable

# Image widths (inches) for Word doc
IMAGE_FULL_WIDTH = 6.5
IMAGE_HALF_WIDTH = 3.1
IMAGE_DIGITAL_LANE_WIDTH = 2.0

# ── Chart palette ─────────────────────────────────────────────────────
# Mirrors the live densitometry chart panels (D3 chromatogram + Three.js
# terrain): the web chose a different palette for plots than for gel
# overlays — green/amber/gray reads as "good band / reference / other"
# in a chart, while the brand BAND_PALETTE above uses distinct hues
# tuned for distinguishing rectangles on a gel image. Used by the
# matplotlib chart renderers ONLY (electropherogram, POI purity bars,
# 3D terrain). Gel renderers continue to use BAND_PALETTE.
#
# Sources:
#   src/gel_analyzer/static/gel_analyzer/css/densitometry.css (--dm-*)
#   src/gel_analyzer/static/gel_analyzer/js/densitometry/panels/
#     chromatogram-panel.js  (profile + band fills)
#   src/gel_analyzer/templates/gel_analyzer/analyses/densitometry.html
#     (Three.js scene + POI purity bar tier coloring)

CHART_PROFILE_COLOR = "#2196F3"  # densitometry chromatogram line

CHART_BAND_PALETTE_HEX = {
    "POI": "#22C55E",  # green   (--dm-poi-color)
    "MW_REFERENCE": "#FFC107",  # amber   (chromatogram-panel.js)
    "OTHER": "#9E9E9E",  # gray    (chromatogram-panel.js)
    "CALIBRATION": "#F87171",  # red-400 (the gel overlay's calibration bands)
}

# POI-purity tier colours — matches the bar coloring rule in
# densitometry.html (>=target / >=minimum / below).
POI_PURITY_TIER_HIGH = "#22C55E"  # ≥ POI_PURITY_TARGET
POI_PURITY_TIER_MID = "#FFC107"  # ≥ POI_PURITY_MINIMUM, < target
POI_PURITY_TIER_LOW = "#EF4444"  # < POI_PURITY_MINIMUM

# Chart theme tokens (dark — Word/PPT exports)
CHART_DARK_BG = "#0f172a"  # --dm-bg-dark
CHART_DARK_PANEL = "#1e293b"  # --dm-bg-panel
CHART_DARK_TEXT = "#94a3b8"  # --dm-text-secondary
CHART_DARK_GRID = "#475569"  # --dm-border-light

# Chart theme tokens (light — Excel embeds, where a dark canvas would
# clash with the white spreadsheet grid).
CHART_LIGHT_BG = "#ffffff"
CHART_LIGHT_TEXT = "#334155"
CHART_LIGHT_GRID = "#e2e8f0"


# ── Methodology text blocks ───────────────────────────────────────────
METHODOLOGY_DENSITOMETRY = """
Quantitative band analysis is performed using Gaussian peak fitting with rolling ball background subtraction.
Each band's intensity profile is extracted perpendicular to the migration direction and fitted to a Gaussian
function using scipy's curve_fit algorithm with robust least-squares optimization. Peak parameters (amplitude,
center, sigma) are extracted and validated against quality metrics (R² > 0.80). Full Width at Half Maximum
(FWHM) is calculated from the fitted sigma parameter, and integrated area is computed using the trapezoidal
rule with background correction.
"""

METHODOLOGY_CALIBRATION = """
Molecular weight estimation employs log-linear regression of known MW ladder standards against relative
migration (Rf) values. The Rf is calculated as the normalized distance migrated from the well (0.0) to the
dye front (1.0). Calibration curves follow the equation log₁₀(MW) = slope × Rf + intercept, with quality
assessed by R² values. For multi-ladder analyses, position-aware interpolation is applied to correct for
gel distortion effects ("smile"). MW estimates are computed by inverse transformation: MW = 10^(log₁₀(MW)).
"""

METHODOLOGY_PURITY = """
Purity calculations are based on the relative integrated area of Protein of Interest (POI) bands compared
to the total integrated area of all detected bands in the lane. The formula is: Purity (%) = (POI Area /
Total Lane Area) × 100. Background-corrected areas are used to ensure accurate quantification. All bands
classified as "OTHER" are considered impurities or host cell proteins, while bands marked as "MW_REFERENCE"
are excluded from purity calculations. A lane whose POI band carries no signal has no purity (never 0%).
The gel's mean purity averages its sample lanes only: a control lane is not a sample's measurement.
"""

METHODOLOGY_MOLECULE_VARIANTS = """
On an anti-molecule western blot the antibody stains the molecule only, so a lane is not read as a purity.
Its signal (POI and Other bands with a background-corrected area above zero) is split around the Protein of
Interest (POI) band: HMWS (high molecular weight species) is the signal above the POI band, the main band the
signal on it (an Other band level with it included), LMWS (low molecular weight species) the signal below it,
each in % of the lane. Above and below are compared by molecular weight when every counted band is calibrated,
else by position on the image. A lane with no POI band has no value.
"""

METHODOLOGY_HOST_CELL_PROTEINS = """
On an anti-HCP western blot the HCP signal of a lane is the sum of its Other bands' background-corrected areas
(arbitrary units, which depend on the exposure: compare within one blot only). A POI band is cross-reacting
molecule, not host-cell protein: it is left out of the signal. Each lane's signal is given in % of the
reference lane's, on the same membrane; without a reference lane only the raw signal is reported.
"""

# The methods paragraph of each readout (GelAssay.Readout): (title, text). NONE has none.
READOUT_METHODOLOGY = {
    "PURITY": ("Purity Calculation", METHODOLOGY_PURITY),
    "MOLECULE_VARIANTS": ("HMWS / Main Band / LMWS", METHODOLOGY_MOLECULE_VARIANTS),
    "HOST_CELL_PROTEINS": ("Host-Cell Proteins", METHODOLOGY_HOST_CELL_PROTEINS),
}

METHODOLOGY_QUANTIFICATION = """
Protein quantification converts background-corrected band areas into absolute amounts using a
standard curve. Calibration-typed bands of known load are fitted against their corrected areas
(linear, 2nd-degree polynomial, or 4-parameter logistic regression). The active calibration is
applied to every band of the sample and control lanes but the MW references to estimate its amount;
the sample table lists the Protein-of-Interest bands. A band whose area lies outside the range of the
non-excluded standards' areas is extrapolated: its estimate is kept and flagged above or below range.
Control bands of known load are projected back through the fit and reported as percent recovery;
values outside the 80–120% range are flagged out-of-spec. Residuals are reported as a percentage of
the declared load.
"""

UNIT_DISPLAY = {
    "UG": "µg",
    "UG_ML": "µg/mL",
}


def saturation_text(band) -> str:
    """A saturated band's warning ("⚠ 8.3 % clipped", its stored share of pixels at the end of the scale); "" else.

    ``band.saturated`` is ``DensitometryResult.saturated`` (the threshold setting, read at every read): never compared
    here, a warning only -- no value is corrected for it.
    """
    if not band.saturated:
        return ""
    fraction = band.saturated_pixel_fraction
    return "⚠ saturated" if fraction is None else f"⚠ {fraction * 100:.1f} % clipped"


def unit_display(unit_code) -> str:
    """Map a quantification unit code (UG / UG_ML) to its display label.

    Returns '' for blank / None so report cells stay empty when no calibration.
    """
    return UNIT_DISPLAY.get(unit_code or "", "")


def calibration_range_display(range_code) -> str:
    """The label of a ``DensitometryResult.CalibrationRange`` code (the model's own); '—' when unknown."""
    from gel_analyzer.models import DensitometryResult

    return dict(DensitometryResult.CalibrationRange.choices).get(range_code or "", "—")


def is_outside_calibration_range(range_code) -> bool:
    """True for an estimate extrapolated above or below the standards' areas."""
    from gel_analyzer.models import DensitometryResult

    return range_code in (
        DensitometryResult.CalibrationRange.ABOVE_RANGE,
        DensitometryResult.CalibrationRange.BELOW_RANGE,
    )


# Display name mappings
BAND_TYPE_DISPLAY = {
    "POI": "Protein of Interest",
    "OTHER": "Other",
    "MW_REFERENCE": "MW Reference",
    "CALIBRATION": "Calibration Point",
}

LANE_TYPE_DISPLAY = {
    "SAMPLE": "Sample",
    "LADDER": "MW Ladder",
    "EMPTY": "Empty",
    "CONTROL": "Control",
    "DOT": "Dot",
    "CALIBRATION": "Calibration Standard",
}


# ── Lane / Band palettes ──────────────────────────────────────────────
# Keyed by ENUM CODE (matches Lane.lane_type / Band.band_type in the
# database — never on the get_*_display() string, which is fragile).
#
# Tuples are RGBA in the 0–255 range. The web viewer uses very low
# fill alpha (CSS rgba(…,0.06) for lanes, 0.10 for bands) so the gel
# image shows through. Pillow renders on dark backgrounds without the
# CSS blend mode benefits, so we use slightly higher alphas — but not
# much: the priority is keeping the gel image readable. Strokes carry
# the colour signal; the fill is just a tint.
#
# Mirror of:
#   .gv-lane.sample/.ladder/.control/.empty in gel_viewer_standalone.css
#   .gv-band.poi/.mw_reference/.other       (idem)

LANE_PALETTE = {
    "SAMPLE": {"fill": (59, 130, 246, 18), "stroke": (59, 130, 246, 230), "dashed": False},
    "LADDER": {"fill": (249, 115, 22, 22), "stroke": (249, 115, 22, 235), "dashed": False},
    "CONTROL": {"fill": (34, 197, 94, 18), "stroke": (34, 197, 94, 235), "dashed": False},
    "EMPTY": {"fill": (107, 114, 128, 14), "stroke": (107, 114, 128, 200), "dashed": True},
    "DOT": {"fill": (59, 130, 246, 18), "stroke": (59, 130, 246, 230), "dashed": False},
    "CALIBRATION": {"fill": (248, 113, 113, 18), "stroke": (248, 113, 113, 235), "dashed": False},
}

BAND_PALETTE = {
    "POI": {"fill": (168, 85, 247, 40), "stroke": (168, 85, 247, 235)},  # purple
    "MW_REFERENCE": {"fill": (249, 115, 22, 38), "stroke": (249, 115, 22, 235)},  # orange
    "OTHER": {"fill": (34, 197, 94, 38), "stroke": (34, 197, 94, 235)},  # green
    "CALIBRATION": {"fill": (248, 113, 113, 40), "stroke": (248, 113, 113, 235)},  # red-400
}

# Hex variants for matplotlib / Plotly equivalents
LANE_PALETTE_HEX = {
    "SAMPLE": "#3B82F6",
    "LADDER": "#F97316",
    "CONTROL": "#22C55E",
    "EMPTY": "#6B7280",
    "DOT": "#3B82F6",
    "CALIBRATION": "#F87171",
}

BAND_PALETTE_HEX = {
    "POI": "#A855F7",
    "MW_REFERENCE": "#F97316",
    "OTHER": "#22C55E",
    "CALIBRATION": "#F87171",
}


def lane_colors(lane_type):
    """Return a {fill, stroke, dashed} dict for the given lane_type code.

    Falls back to SAMPLE so a missing/unknown type still draws something.
    """
    return LANE_PALETTE.get((lane_type or "SAMPLE").upper(), LANE_PALETTE["SAMPLE"])


def band_colors(band_type):
    """Return a {fill, stroke} dict for the given band_type code.

    Falls back to OTHER for unknown / missing codes.
    """
    return BAND_PALETTE.get((band_type or "OTHER").upper(), BAND_PALETTE["OTHER"])


# ── PIL font resolution (single source) ───────────────────────────
# Order: Inter (the app's own face, when installed) -> DejaVuSans (bundled
# w/ Pillow, present on Debian slim) -> Arial (Windows/dev) -> bitmap default.
# DejaVu is intentionally BEFORE Arial: Arial is absent on the Debian
# slim render host. Warn-once on fallback to the bitmap default.
_FONT_CANDIDATES = (
    "Inter-Regular.ttf",
    "Inter.ttf",
    "DejaVuSans.ttf",
    "Arial.ttf",
    "arial.ttf",
)
_FONT_FALLBACK_WARNED = False


def resolve_pil_font(size: int):
    """Return a PIL ImageFont at ``size`` px, trying the app's face then
    bundled then system faces, falling back to the bitmap default.

    Warns exactly once per process when it has to fall back to the
    non-scalable bitmap default (label sizing then ignores ``size``).
    """
    from PIL import ImageFont

    global _FONT_FALLBACK_WARNED
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    if not _FONT_FALLBACK_WARNED:
        logger.warning(
            "resolve_pil_font: no TrueType face found "
            f"({', '.join(_FONT_CANDIDATES)}); falling back to PIL bitmap "
            "default — report label sizing will be approximate."
        )
        _FONT_FALLBACK_WARNED = True
    return ImageFont.load_default()


# ── Comparison Report Configuration ──────────────────────────────

REPORT_SECTIONS = [
    ("overview", "Comparison Overview"),
    ("sample_summary", "Sample Summary"),
    ("digital_gel", "Side-by-Side Digital Gel"),
    ("gel_images", "Gel Images"),
    ("band_comparison", "Band Comparison"),
    ("lane_details", "Individual Lane Details"),
    ("poi_purity", "POI Purity Chart"),
    ("quantification", "Protein Quantification"),
    ("materials_methods", "Materials & Methods"),
]

ALL_SECTION_KEYS = [key for key, _ in REPORT_SECTIONS]

REPORT_FORMATS = ["docx", "xlsx", "pptx"]

FORMAT_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

FORMAT_EXTENSIONS = {
    "docx": ".docx",
    "xlsx": ".xlsx",
    "pptx": ".pptx",
}

POI_PURITY_TARGET = 90
POI_PURITY_MINIMUM = 70

# Accent color palette (hex) for multi-sample charts.
# Anchored on the live app's accent-600 first so the primary lane lines up
# with the rest of the UI. Subsequent colours sweep the same hue family
# used by the gel-viewer overlay (purple POI, green other, orange ladder).
ACCENT_COLORS_HEX = [
    "#2563EB",  # accent-600 (live UI primary)
    "#A855F7",  # purple — POI
    "#22C55E",  # green — other
    "#F97316",  # orange — MW reference
    "#EC4899",  # pink — band token
    "#14B8A6",  # teal
    "#F59E0B",  # amber
    "#6366F1",  # indigo
]

# ── Densitometry Report Configuration ────────────────────────────────

DENSITOMETRY_REPORT_SECTIONS = [
    ("overview", "Analysis Overview"),
    ("sample_summary", "Sample Summary Table"),
    ("gel_image", "Full Gel Image"),
    ("digital_gel", "Digital Gel (All Lanes)"),
    ("poi_purity", "POI Purity Chart"),
    ("lane_details", "Lane Details"),
    ("quantification", "Protein Quantification"),
    ("terrain_view", "3D Terrain View"),
    ("materials_methods", "Materials & Methods"),
]

DENSITOMETRY_ALL_SECTION_KEYS = [key for key, _ in DENSITOMETRY_REPORT_SECTIONS]


# ── Gel-image variants (spec D3) ─────────────────────────────────
# When the 'gel_image' / 'gel_images' section is included, the PPTX builders
# render ONE gel slide per selected variant, in this canonical order. Absent /
# empty selection defaults to ["FULL"].
GEL_VARIANTS_CANONICAL_ORDER = ["LANES_ONLY", "KEY_BANDS", "FULL"]
GEL_VARIANTS_ALLOWED = set(GEL_VARIANTS_CANONICAL_ORDER)
# A gel picture's variant, as a slide title names it.
GEL_VARIANT_TITLES = {"LANES_ONLY": "lanes only", "KEY_BANDS": "key bands", "FULL": "all bands"}
GEL_VARIANTS_DEFAULT = ["FULL"]


# ── matplotlib style (single source) ──────────────────────────────
# Convention: fixed dpi >= 200; never use bbox_inches='tight' (it makes
# pixel size non-deterministic) — placement is aspect-locked instead.
MPL_DPI = 200

# Viewer accent cycle (hex) for line/scatter series.
MPL_COLOR_CYCLE = [
    LANE_PALETTE_HEX["SAMPLE"],  # blue
    BAND_PALETTE_HEX["POI"],  # purple
    LANE_PALETTE_HEX["CONTROL"],  # green
    LANE_PALETTE_HEX["LADDER"],  # orange
    "#EC4899",  # pink
    "#14B8A6",  # teal
    "#F59E0B",  # amber
    "#6366F1",  # indigo
]


def mpl_style() -> dict:
    """Return a matplotlib rcParams dict for report charts.

    Apply with ``plt.rc_context(mpl_style())`` — this never mutates the
    global rcParams. Enforces fixed dpi >= 200 and ``savefig.bbox =
    'standard'`` (i.e. NOT 'tight') for deterministic pixel sizing.
    """
    from cycler import cycler

    return {
        "figure.dpi": MPL_DPI,
        "savefig.dpi": MPL_DPI,
        "savefig.bbox": "standard",
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.prop_cycle": cycler(color=MPL_COLOR_CYCLE),
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
