"""
Constants for gel analysis Word report generation.

Contains GSK branding colors, fonts, sizing, and methodology text blocks.
"""

# GSK Brand Colors (RGB tuples for python-docx)
GSK_ORANGE = (244, 121, 32)
GSK_BLUE = (59, 113, 202)
TABLE_HEADER_BG = "4472C4"
MUTED_GRAY = (108, 117, 125)

# Fonts
BODY_FONT = "GSKPrecision Thin"
HEADING_FONT = "GSKPrecision"

# Font sizes (Pt)
TITLE_SIZE = 28
SECTION_H1_SIZE = 16
SECTION_H2_SIZE = 14
SECTION_H3_SIZE = 12
BODY_SIZE = 11
TABLE_SIZE = 9
SMALL_SIZE = 10

# Assets path
GSK_LOGO_PATH = "base/static/base/images/gsk_logo_template.png"

# Image widths (inches) for Word doc
IMAGE_FULL_WIDTH = 6.5
IMAGE_HALF_WIDTH = 3.1
IMAGE_DIGITAL_LANE_WIDTH = 2.0

# Methodology text blocks
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
are excluded from purity calculations.
"""

# Display name mappings
BAND_TYPE_DISPLAY = {
    "POI": "Protein of Interest",
    "OTHER": "Other",
    "MW_REFERENCE": "MW Reference",
}

LANE_TYPE_DISPLAY = {
    "SAMPLE": "Sample",
    "LADDER": "MW Ladder",
    "EMPTY": "Empty",
    "CONTROL": "Control",
    "DOT": "Dot",
}

# ── Comparison Report Configuration ──────────────────────────────

# Available report sections as (key, label) tuples
REPORT_SECTIONS = [
    ("overview", "Comparison Overview"),
    ("sample_summary", "Sample Summary"),
    ("digital_gel", "Side-by-Side Digital Gel"),
    ("gel_images", "Gel Images"),
    ("band_comparison", "Band Comparison"),
    ("lane_details", "Individual Lane Details"),
    ("poi_purity", "POI Purity Chart"),
    ("materials_methods", "Materials & Methods"),
]

ALL_SECTION_KEYS = [key for key, _ in REPORT_SECTIONS]

# Supported export formats
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

# POI Purity thresholds
POI_PURITY_TARGET = 90
POI_PURITY_MINIMUM = 70

# Accent color palette (hex) matching frontend sample comparison
ACCENT_COLORS_HEX = [
    "#3B82F6",  # blue
    "#A855F7",  # purple
    "#22C55E",  # green
    "#F97316",  # orange
    "#EC4899",  # pink
    "#14B8A6",  # teal
    "#F59E0B",  # amber
    "#6366F1",  # indigo
]

# ── Densitometry Report Configuration ────────────────────────────

DENSITOMETRY_REPORT_SECTIONS = [
    ("overview", "Analysis Overview"),
    ("sample_summary", "Sample Summary Table"),
    ("gel_image", "Full Gel Image"),
    ("digital_gel", "Digital Gel (All Lanes)"),
    ("poi_purity", "POI Purity Chart"),
    ("lane_details", "Lane Details"),
    ("terrain_view", "3D Terrain View"),
    ("materials_methods", "Materials & Methods"),
]

DENSITOMETRY_ALL_SECTION_KEYS = [key for key, _ in DENSITOMETRY_REPORT_SECTIONS]
