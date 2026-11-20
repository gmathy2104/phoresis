"""
What the analysis page shows: the gel's readout, the lane values, the checks.

A gel is read for what its image's assay measures (``GelAssay.readout``): a purity on an SDS-PAGE,
HMWS / main band / LMWS on an anti-molecule western, the HCP signal against a reference
lane on an anti-HCP western. Until 2026-10-10 the page read every gel as a purity: an anti-HCP blot
showed "0.0 %" purity on every lane and one "No POI band" warning per lane -- on a blot where no POI
is expected -- while its real values sat on the densitometry page only.

Nothing is computed here. A purity is ``signals.published_purity`` (the value Process Development
receives: none without a POI band carrying signal, never 0 %), a western value is
``readout_publisher.lane_readouts`` (the function that publishes it), so the page cannot drift from
what the samples hold. An image without an assay is read through the purity gate's own fallback
(``signals.image_measures_purity``: an SDS-PAGE is a purity gel, anything else has no readout).

The lane values are given as CELLS -- one per column of :func:`readout_columns`, already formatted,
with the reason of a missing value -- so the cards (template) and the lane spreadsheet
(``static/gel_analyzer/js/lane-spreadsheet.js``) print the same thing from one list.

Whether the values REACHED Process Development is read from its official rows
(:func:`delivery_checks`), never assumed: a western publishes at the densitometry run only, so a
sample assigned after the run waits for the next one.
"""

from __future__ import annotations

from django.db.models import Prefetch
from django.urls import reverse

from gel_analyzer.models import Band, DensitometryResult, GelAnalysis, GelAssay, Lane, LaneDensitometrySummary
from gel_analyzer.services import readouts as readout_roles
from gel_analyzer.services.densitometry.saturation import saturated_pixel_threshold
from gel_analyzer.services.mean_purity import lane_in_mean_purity, mean_purity
from gel_analyzer.services.readout_publisher import lane_readouts
from gel_analyzer.services.readouts import (
    COMPARED_BY_POSITION,
    HCP_VALUE_KEYS,
    LANE_NOT_ANALYSED,
    NO_POI_BAND,
    NO_REFERENCE_LANE,
    VARIANT_VALUE_KEYS,
    BandReading,
    band_roles,
)
from gel_analyzer.signals import image_measures_purity, lane_publishes_purity, published_purity

Readout = GelAssay.Readout

NO_BANDS = "no bands"

# What each readout is called on the page (header tag, metric, lane panel).
READOUT_LABELS = {
    Readout.PURITY: "Purity",
    Readout.MOLECULE_VARIANTS: "HMWS / main band / LMWS",
    Readout.HOST_CELL_PROTEINS: "Host-cell proteins",
    Readout.NONE: "No readout",
}

# The lanes a readout is measured on, shown as cards: the samples, the controls beside them, and
# the HCP reference lane whatever its type (an HCP standard is often typed CONTROL).
READ_LANE_TYPES = frozenset({Lane.LaneType.SAMPLE, Lane.LaneType.CONTROL})

PURITY_GOOD = 90
PURITY_FAIR = 70

# The western columns are the publisher's own keys (services/readouts.py), labelled in their order:
# typed again here, a key renamed there would blank every cell of the page to "—" without an error.
HCP_PERCENT, HCP_TOTAL, HCP_BANDS = HCP_VALUE_KEYS
AGGREGATES, MAIN_BAND, CLIPPING = VARIANT_VALUE_KEYS
# HMWS / LMWS: high / low molecular weight species, the owner's generic terms (2026-10-12) for what the
# result keys still call aggregate_percent / fragment_percent (the Process Development and export contract).
VARIANT_TEXTS = (
    ("HMWS", "High molecular weight species: signal above the POI band, % of the lane"),
    ("Main band", "Signal on the POI band, % of the lane"),
    ("LMWS", "Low molecular weight species: signal below the POI band, % of the lane"),
)
HCP_TEXTS = (
    ("HCP % of ref.", "HCP signal of the lane in % of the reference lane's (same membrane)"),
    ("HCP signal", "Summed HCP band signal, arbitrary units: compare within this blot only"),
    ("HCP bands", "Bands counted as HCP (POI bands left out)"),
)
# Why a POI band does not count on an anti-HCP blot: the check, the band's role and the reading guide say it alike.
POI_LEFT_OUT_TEXT = "On an anti-HCP blot a POI band is cross-reacting molecule, not host-cell protein."

# A band's part in its lane's western readout (``readouts.band_roles``), as the annotation editor names it:
# (label, why). The variant roles ARE the ``VARIANT_TEXTS`` lines -- one string, never reworded.
ROLE_TEXTS = {
    readout_roles.AGGREGATE: VARIANT_TEXTS[0],
    readout_roles.MAIN_BAND: VARIANT_TEXTS[1],
    readout_roles.CLIPPING: VARIANT_TEXTS[2],
    readout_roles.HCP_BAND: ("HCP band", "Counted in the HCP signal of the lane"),
    readout_roles.LEFT_OUT: ("Left out", f"{POI_LEFT_OUT_TEXT} It is left out of the HCP signal."),
}
# A band with no role, on a lane the reading lists but has not measured yet.
ROLE_HINT_NOT_ANALYSED = "Its role in the reading appears after a densitometry run (a band edit clears it)"

# The checks the annotation editor's card shows: what annotating changes. The densitometry and delivery ones
# (not analysed, not routed / sent, held elsewhere) stay on the analysis and densitometry pages.
ANNOTATION_CHECK_KINDS = frozenset(
    {
        "no_lanes",
        "no_bands",
        "no_sample",
        "no_poi",
        "no_reference",
        "poi_excluded",
        "lane_without_bands",
        "no_mw",
        "by_position",
        "no_assay",
    }
)


def page_readout(gel_image) -> str:
    """The readout the page reads the gel for: its assay's, else the gel type's fallback."""
    if gel_image.assay_id is not None:
        return gel_image.assay.readout
    return Readout.PURITY if image_measures_purity(gel_image) else Readout.NONE


def readout_columns(readout: str, has_quant: bool) -> list[dict]:
    """The value columns of the lane cards and spreadsheet, after the lane's own fields."""
    if readout == Readout.PURITY:
        columns = [
            {"key": "bands", "label": "Bands", "title": "Bands annotated on the lane"},
            {"key": "poi_kda", "label": "POI kDa", "title": "Molecular weight of the POI band (MW calibration)"},
            {
                "key": "purity",
                "label": "Purity",
                "title": "POI share of the lane: the purity Process Development receives",
            },
        ]
        if has_quant:
            columns.append(
                {
                    "key": "measured",
                    "label": "Measured",
                    "title": "POI load projected by the quantification calibration",
                }
            )
        return columns
    if readout == Readout.MOLECULE_VARIANTS:
        return [{"key": "bands", "label": "Bands", "title": "Bands annotated on the lane"}] + [
            {"key": key, "label": label, "title": title}
            for key, (label, title) in zip(VARIANT_VALUE_KEYS, VARIANT_TEXTS, strict=False)
        ]
    if readout == Readout.HOST_CELL_PROTEINS:
        return [
            {"key": key, "label": label, "title": title}
            for key, (label, title) in zip(HCP_VALUE_KEYS, HCP_TEXTS, strict=False)
        ]
    return [{"key": "bands", "label": "Bands", "title": "Bands annotated on the lane"}]


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _cell(text, *, tone=None):
    return {"text": text, "reason": None, "tone": tone}


def _missing(reason):
    return {"text": "", "reason": reason, "tone": None}


def _percent(value, reason=None):
    return _missing(reason or "—") if value is None else _cell(f"{value:.1f} %")


def _purity_tone(value):
    if value >= PURITY_GOOD:
        return "ok"
    return "warn" if value >= PURITY_FAIR else "bad"


def _measured_load(lane):
    """Sum of the POI bands' projected loads, or None -- never a misleading 0 µg."""
    total, unit, seen = 0.0, "", False
    for band in lane.bands.all():
        if band.band_type != "POI":
            continue
        densitometry = getattr(band, "densitometry", None)
        if densitometry is None or densitometry.estimated_amount is None:
            continue
        total += float(densitometry.estimated_amount)
        unit = unit or densitometry.estimated_amount_unit or ""
        seen = True
    return (total, unit) if seen else None


def _summary_of(lane):
    try:
        return lane.densitometry_summary
    except LaneDensitometrySummary.DoesNotExist:
        return None


def lane_rows(analysis, lanes, readout: str, has_quant: bool, readouts=None) -> list[dict]:
    """One row per lane, in lane order: who it is, and the cells of :func:`readout_columns`.

    ``lanes`` are the analysis's lanes with ``bands`` (and their ``densitometry``),
    ``densitometry_summary`` and ``process_sample`` loaded. A lane the readout is not measured on
    (a ladder, an empty lane) has its ``bands`` cell only; a missing value carries its reason.
    ``readouts``: ``lane_readouts(analysis)`` when the caller already has it (:func:`page_summary`).
    """
    western = {}
    if readout in GelAssay.WESTERN_READOUTS:
        entries = readouts if readouts is not None else lane_readouts(analysis)
        western = {entry["lane_id"]: entry for entry in entries}

    rows = []
    for lane in lanes:
        bands = list(lane.bands.all())
        summary = _summary_of(lane)
        entry = western.get(lane.pk)
        is_reference = bool(entry and entry["is_reference"])
        poi_kda = next((b.estimated_mw_kda for b in bands if b.band_type == "POI" and b.estimated_mw_kda), None)

        row = {
            "id": lane.pk,
            "lane_number": lane.lane_number,
            "lane_type": lane.lane_type,
            "sample": lane.sample_name or "",
            # The hub links a lane to a sample's page and flags a discarded one; a Phoresis sample is a
            # free-text name. Kept as keys so the templates and the JS ported from the hub read them.
            "sample_url": None,
            "sample_flag": None,
            "band_count": len(bands),
            "has_poi": any(b.band_type == "POI" for b in bands),
            "poi_kda": poi_kda,
            "analysed": summary is not None,
            "is_read": lane.lane_type in READ_LANE_TYPES or is_reference,
            "is_reference": is_reference,
            "values": {},
            "reason": None,
            "cells": {"bands": _cell(str(len(bands)))},
        }

        if readout == Readout.PURITY and lane.lane_type in READ_LANE_TYPES:
            purity = published_purity(summary) if summary is not None else None
            if purity is None:
                # A lane with no band at all is not a lane missing its POI (a densitometry run gives
                # it a summary all the same).
                if not bands:
                    row["reason"] = NO_BANDS
                else:
                    row["reason"] = NO_POI_BAND if summary is not None else LANE_NOT_ANALYSED
            row["values"]["purity"] = purity
            row["cells"]["poi_kda"] = _missing("—") if poi_kda is None else _cell(f"{poi_kda:.1f}")
            row["cells"]["purity"] = (
                _missing(row["reason"]) if purity is None else _cell(f"{purity:.1f} %", tone=_purity_tone(purity))
            )
            if has_quant:
                measured = _measured_load(lane)
                row["cells"]["measured"] = (
                    _missing("—")
                    if measured is None
                    else _cell(f"{measured[0]:.1f} {'µg/mL' if measured[1] == 'UG_ML' else 'µg'}")
                )

        elif readout in GelAssay.WESTERN_READOUTS and entry is not None:
            values = entry["values"] or {}
            row["values"] = values
            # The publisher's reason, except on a lane with no band at all: "no POI band" there
            # would send the user looking for a band to type.
            row["reason"] = NO_BANDS if not bands and entry["reason"] == NO_POI_BAND else entry["reason"]
            if readout == Readout.MOLECULE_VARIANTS:
                for key in VARIANT_VALUE_KEYS:
                    row["cells"][key] = _percent(values.get(key), row["reason"])
            elif not values:
                for key in HCP_VALUE_KEYS:
                    row["cells"][key] = _missing(entry["reason"] or "—")
            else:
                row["cells"][HCP_PERCENT] = _percent(values.get(HCP_PERCENT), entry["reason"] or NO_REFERENCE_LANE)
                row["cells"][HCP_TOTAL] = _cell(f"{values[HCP_TOTAL]:,.0f}")
                row["cells"][HCP_BANDS] = _cell(str(values[HCP_BANDS]))

        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Metrics and checks
# ---------------------------------------------------------------------------


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _lanes(numbers) -> str:
    numbers = sorted(numbers)
    return f"Lane {numbers[0]}" if len(numbers) == 1 else "Lanes " + ", ".join(str(n) for n in numbers)


def headline_metric(readout: str, rows: list[dict], gel_image) -> dict | None:
    """The readout's own metric card, after Lanes / Bands / Analysed."""
    samples = [row for row in rows if row["lane_type"] == Lane.LaneType.SAMPLE]
    if readout == Readout.PURITY:
        mean = mean_purity(gel_image, ((row["lane_type"], row["values"].get("purity")) for row in rows))
        return {
            "label": "Mean purity",
            "value": "—" if mean.value is None else f"{mean.value:.1f} %",
            "sub": mean.lanes_text,
            "tone": None if mean.value is None else _purity_tone(mean.value),
            "title": "Mean of the sample lanes' purity; a control lane, or a lane without a POI band, is left out",
        }
    if readout == Readout.MOLECULE_VARIANTS:
        read = [row["values"] for row in samples if row["values"].get(MAIN_BAND) is not None]
        main = _mean(v[MAIN_BAND] for v in read)
        if main is None:
            return {"label": "Main band (mean)", "value": "—", "sub": "No lane measured yet", "tone": None, "title": ""}
        aggregates = _mean(v[AGGREGATES] for v in read)
        clipping = _mean(v[CLIPPING] for v in read)
        return {
            "label": "Main band (mean)",
            "value": f"{main:.1f} %",
            "sub": f"HMWS {aggregates:.1f} % · LMWS {clipping:.1f} %",
            "tone": None,
            "title": f"Mean over {len(read)} sample lane{'s' if len(read) != 1 else ''}",
        }
    if readout == Readout.HOST_CELL_PROTEINS:
        reference = next((row for row in rows if row["is_reference"]), None)
        if reference is None:
            return {
                "label": "HCP reference",
                "value": "Not set",
                "sub": "Only the raw signal is shown",
                "tone": "warn",
                "title": "The lane every HCP % is computed against",
            }
        return {
            "label": "HCP reference",
            "value": f"Lane {reference['lane_number']}",
            "sub": reference["sample"] or "No sample",
            "tone": None,
            "title": "The lane every HCP % is computed against",
        }
    return None


def delivery_checks(analysis, lanes, readout: str) -> list[dict]:
    """The lanes whose values did not reach another system: none, Phoresis publishes nowhere.

    In ds-hub-django this reads Process Development's official rows and warns when a lane's value
    never arrived. Kept, answering an empty list, so :func:`build_checks` stays the hub's.
    """
    return []


def build_checks(analysis, rows: list[dict], readout: str, *, ladder_count: int, lanes=()) -> list[dict]:
    """What is missing for this gel's readout, worst first: ``level`` is ``warn`` or ``info``.

    Only what the readout needs: a POI band is asked for on a purity or an anti-molecule gel,
    never on an anti-HCP blot (where a POI band is cross-reacting molecule, left out of the signal);
    a reference lane on an anti-HCP blot only; the MW calibration where it changes a value.
    """
    checks = []
    gel_image = analysis.gel_image
    annotate = reverse("gel_analyzer:analysis_annotate", kwargs={"pk": analysis.pk}) if analysis.is_editable else None
    densitometry = reverse("gel_analyzer:analysis_densitometry", kwargs={"pk": analysis.pk})

    def add(kind, level, title, detail, url=None, link=None):
        checks.append({"kind": kind, "level": level, "title": title, "detail": detail, "url": url, "link": link})

    if not rows:
        add(
            "no_lanes",
            "warn",
            "No lanes annotated yet",
            "Annotate the lanes of the gel to start.",
            annotate,
            "Annotate",
        )
        return checks
    if analysis.total_bands == 0:
        add("no_bands", "warn", "No bands detected yet", "Detect or draw the bands of each lane.", annotate, "Annotate")

    samples = [row for row in rows if row["lane_type"] == Lane.LaneType.SAMPLE]

    no_sample = [row["lane_number"] for row in samples if not row["sample"]]
    if no_sample:
        add(
            "no_sample",
            "warn",
            f"{_lanes(no_sample)}: no sample",
            "No value reaches Process Development without one: assign it from the lane table.",
        )

    if readout != Readout.NONE:
        not_analysed = [
            row["lane_number"] for row in rows if row["is_read"] and row["band_count"] and not row["analysed"]
        ]
        if not_analysed:
            add(
                "not_analysed",
                "warn",
                f"{_lanes(not_analysed)}: densitometry not run",
                "The densitometry computes the values.",
                densitometry,
                "Densitometry",
            )

    if readout in (Readout.PURITY, Readout.MOLECULE_VARIANTS):
        no_poi = [row["lane_number"] for row in samples if row["band_count"] and not row["has_poi"]]
        no_poi += [
            row["lane_number"] for row in samples if row["has_poi"] and row["analysed"] and row["reason"] == NO_POI_BAND
        ]
        if no_poi:
            measured = (
                "No purity without it" if readout == Readout.PURITY else "HMWS, main band and LMWS are read around it"
            )
            add(
                "no_poi",
                "warn",
                f"{_lanes(no_poi)}: no POI band",
                f"{measured}: type the band of the protein of interest.",
                annotate,
                "Annotate",
            )

    if readout == Readout.HOST_CELL_PROTEINS:
        reference = next((row for row in rows if row["is_reference"]), None)
        if analysis.readout_reference_lane_id is None:
            add(
                "no_reference",
                "warn",
                "No HCP reference lane",
                "The % of reference cannot be computed: only the raw signal is shown. Pick the reference on "
                "the densitometry page, or in the annotation editor: the lane's HCP reference switch, or a "
                "right-click on the lane.",
                densitometry,
                "Densitometry",
            )
        elif reference is not None and not reference["analysed"]:
            add(
                "reference_not_analysed",
                "warn",
                f"Reference lane {reference['lane_number']} not analysed yet",
                "The % of reference waits for its densitometry.",
                densitometry,
                "Densitometry",
            )
        with_poi = [row["lane_number"] for row in rows if (row["values"] or {}).get("poi_band_count")]
        if with_poi:
            add(
                "poi_excluded",
                "info",
                f"{_lanes(with_poi)}: POI band left out of the HCP signal",
                POI_LEFT_OUT_TEXT,
            )

    if readout in (Readout.PURITY, Readout.MOLECULE_VARIANTS) and analysis.total_bands:
        no_bands = [row["lane_number"] for row in samples if not row["band_count"]]
        if no_bands:
            add("lane_without_bands", "info", f"{_lanes(no_bands)}: no bands", "Nothing to measure.")

    # The molecular weight, read from the bands: a MW can come from a ladder template without a
    # LadderCalibration row, so "no calibration" alone is no proof that a kDa is missing.
    if ladder_count:
        no_kda = [row["lane_number"] for row in samples if row["has_poi"] and row["poi_kda"] is None]
        if readout == Readout.PURITY and no_kda:
            add(
                "no_mw",
                "info",
                f"{_lanes(no_kda)}: no POI molecular weight",
                "Calibrate the ladder to read the kDa of the POI band.",
                annotate,
                "Annotate",
            )
        elif readout == Readout.MOLECULE_VARIANTS and any(
            (row["values"] or {}).get("compared_by") == COMPARED_BY_POSITION for row in rows
        ):
            add(
                "by_position",
                "info",
                "HMWS and LMWS placed by position",
                "Without a MW calibration, above and below the POI band are read from the image: an image "
                "uploaded upside down swaps them. Calibrate the ladder to compare by molecular weight.",
                annotate,
                "Annotate",
            )

    saturated = saturated_bands(lanes)
    if saturated:
        listing = ", ".join(f"lane {lane} B{number} ({word})" for lane, number, word in saturated)
        several = len(saturated) > 1
        whose = "each one's" if several else "its"
        add(
            "saturated",
            "warn",
            f"{_lanes({lane for lane, _number, _word in saturated})}: saturated band{'s' if several else ''}",
            f"{listing}: more than {saturated_pixel_threshold() * 100:g} % of {whose} "
            "pixels sit at the end of the image's scale (black on a stained gel, white on a fluorescent blot), where "
            "the scanner clips. A clipped band's area stops growing with the load: it reads too low, and every share "
            "computed from it (the purity, the readout) is off. The values are kept as computed: load less or image "
            "with a shorter exposure, then run the densitometry again.",
            densitometry,
            "Densitometry",
        )

    if gel_image.assay_id is None:
        fallback = "a purity" if readout == Readout.PURITY else "nothing"
        add(
            "no_assay",
            "info",
            "No assay on this image",
            f"It is read from its gel type ({gel_image.get_gel_type_display()}): {fallback}. "
            "Set its assay so the gel is read for what it measures.",
            reverse("gel_analyzer:image_edit", kwargs={"pk": gel_image.pk}),
            "Edit image",
        )

    checks += delivery_checks(analysis, lanes, readout)
    return sorted(checks, key=lambda check: check["level"] != "warn")


# A band's type as the saturation check names it (the measurements table's words).
_BAND_WORDS = {
    Band.BandType.POI: "POI",
    Band.BandType.OTHER: "Other",
    Band.BandType.MW_REFERENCE: "MW reference",
    Band.BandType.CALIBRATION: "Calibration",
}


def band_number(band, rank: int) -> int:
    """A band's number as the pages name it ("B3"): its stored ``Band.band_number`` (1-indexed from the top of the
    lane), else -- a band drawn in the editor often has none -- ``rank``, its rank from the top among the lane's bands
    (``Band.Meta.ordering``), which is what that number means. The densitometry page, the saturation check and the
    reports name a band by it."""
    return band.band_number or rank


def saturated_bands(lanes) -> list[tuple[int, int, str]]:
    """``(lane number, band number, type word)`` of every saturated band (``DensitometryResult.saturated``).

    The band number is :func:`band_number`. A LADDER lane's bands are left out: their area feeds no value (a marker's position gives the kDa), and a
    bright ladder clips on most fluorescent blots -- a warning on every gel would be read as noise. The
    measurements table still badges them.
    """
    found = []
    for lane in lanes:
        if lane.lane_type == Lane.LaneType.LADDER:
            continue
        for rank, band in enumerate(lane.bands.all(), 1):
            try:
                result = band.densitometry
            except DensitometryResult.DoesNotExist:
                continue
            if result.saturated:
                word = _BAND_WORDS.get(band.band_type, band.band_type)
                found.append((lane.lane_number, band_number(band, rank), word))
    return sorted(found, key=lambda item: (item[0], item[1]))


def next_step(analysis, rows: list[dict], checks: list[dict]) -> str:
    """The header's hint for an in-progress analysis: the first thing left to do."""
    if not rows:
        return "Next: annotate the lanes"
    if analysis.total_bands == 0:
        return "Next: detect the bands"
    if any(row["is_read"] and row["band_count"] and not row["analysed"] for row in rows):
        return "Next: run the densitometry"
    if any(check["kind"] == "no_reference" for check in checks):
        return "Next: pick the HCP reference lane"
    if any(check["kind"] == "not_sent" for check in checks):
        return "Next: run the densitometry again to send the values"
    return "Ready to mark as complete"


# ---------------------------------------------------------------------------
# Calibrations (the metric cards)
# ---------------------------------------------------------------------------


def r_squared_quality(r_squared):
    """Return quality label for R² value."""
    if r_squared is None:
        return "unknown"
    if r_squared >= 0.99:
        return "excellent"
    if r_squared >= 0.95:
        return "good"
    if r_squared >= 0.90:
        return "acceptable"
    return "poor"


def calibration_info(analysis):
    """
    Get calibration status and details for context display.

    Returns dict with:
    - status: 'calibrated' or 'not_calibrated'
    - ladder_count: number of calibrated ladders
    - best_r_squared: highest R² value
    - r_squared_quality: 'excellent', 'good', 'acceptable', 'poor'
    - template_name: ladder template name
    """
    calibrations = list(analysis.ladder_calibrations.all())

    if not calibrations:
        return {
            "status": "not_calibrated",
            "message": "No MW calibration performed",
        }

    # Find best R² among all calibrations
    r_squared_values = [c.r_squared for c in calibrations if c.r_squared is not None]
    best_r2 = max(r_squared_values) if r_squared_values else None

    # Get template name from first calibration
    template_name = None
    for c in calibrations:
        if c.template:
            template_name = c.template.name
            break

    return {
        "status": "calibrated",
        "ladder_count": len(calibrations),
        "best_r_squared": best_r2,
        "r_squared_quality": r_squared_quality(best_r2),
        "template_name": template_name,
    }


def quant_calibration_info(analysis):
    """
    Get *protein quantification* calibration status — distinct from the MW
    ladder calibration. Returns dict with:

    - status: 'calibrated' or 'not_calibrated'
    - r_squared: fit quality of the active calibration
    - r_squared_quality: quality bucket label
    - method: raw method code (LINEAR / POLYNOMIAL_2 / FOUR_PL)
    - method_display: human label
    - unit: UG or UG_ML
    - unit_display: µg / µg/mL
    - point_count: number of calibration points used in the fit
    """
    try:
        active = analysis.quant_calibrations.filter(is_active=True).first()
    except Exception:
        active = None

    if not active:
        return {
            "status": "not_calibrated",
            "message": "No quantification calibration",
        }

    method_labels = {
        "LINEAR": "Linear",
        "POLYNOMIAL_2": "Polynomial (deg 2)",
        "FOUR_PL": "4-Parameter Logistic",
    }
    unit_labels = {"UG": "µg", "UG_ML": "µg/mL"}

    # Count points belonging to this analysis (across all CALIBRATION-typed
    # lanes). We don't restrict by is_excluded_from_fit on purpose — the
    # caller cares about the user-declared standards, not the fitter's
    # internal exclusion set.
    from gel_analyzer.models import ProteinQuantCalibrationPoint

    point_count = ProteinQuantCalibrationPoint.objects.filter(band__lane__analysis=analysis).count()

    return {
        "status": "calibrated",
        "r_squared": active.r_squared,
        "r_squared_quality": r_squared_quality(active.r_squared),
        "method": active.method,
        "method_display": method_labels.get(active.method, active.method),
        "unit": active.unit,
        "unit_display": unit_labels.get(active.unit, active.unit),
        "equation": active.equation,
        "point_count": point_count,
        "last_updated": active.last_recomputed_at or active.created_at,
    }


# ---------------------------------------------------------------------------
# One summary for every gel page (spec 2026-10-12-gel-modern-ui-design.md §3)
# ---------------------------------------------------------------------------


def summary_lanes_prefetch():
    """The analysis's lanes WHOLE, as :func:`page_summary` reads them with no query of their own.

    Their summary, sample and bands with their densitometry: ``lane_readouts`` then takes them from
    the prefetch (``readout_publisher._prefetched_lanes``), ``lane_rows`` and ``delivery_checks`` too.
    Never filtered: a filtered prefetch would hide the HCP reference lane.
    """
    bands = Prefetch("bands", queryset=Band.objects.select_related("densitometry"))
    return Prefetch(
        "lanes",
        queryset=Lane.objects.select_related("densitometry_summary")
        .prefetch_related(bands)
        .order_by("lane_number", "pk"),
    )


def page_summary(analysis, lanes) -> dict:
    """The gel's readout as a gel page prints it: one composition for every page that shows it.

    The analysis page, the densitometry page and its API read this dict, so their cards, checks and
    lane values cannot drift apart. ``lanes``: the analysis's lanes loaded whole (a prefetch at least
    :func:`summary_lanes_prefetch`'s). ``readouts`` is ``lane_readouts``' list, computed once here on
    a western ([] otherwise): the densitometry API serves the same list.
    """
    calibration = calibration_info(analysis)
    quant = quant_calibration_info(analysis)
    has_quant = quant["status"] == "calibrated"
    readout = page_readout(analysis.gel_image)
    readouts = lane_readouts(analysis) if readout in GelAssay.WESTERN_READOUTS else []
    rows = lane_rows(analysis, lanes, readout, has_quant, readouts=readouts)
    ladder_count = sum(1 for lane in lanes if lane.lane_type == Lane.LaneType.LADDER)
    checks = build_checks(analysis, rows, readout, ladder_count=ladder_count, lanes=lanes)
    read_rows = [row for row in rows if row["is_read"]]
    return {
        "readout": readout,
        "readout_label": READOUT_LABELS.get(readout, readout),
        "columns": readout_columns(readout, has_quant),
        "rows": rows,
        "readouts": readouts,
        "checks": checks,
        "next_step": next_step(analysis, rows, checks),
        "headline": headline_metric(readout, rows, analysis.gel_image),
        "sample_count": sum(1 for row in rows if row["lane_type"] == Lane.LaneType.SAMPLE),
        "control_count": sum(1 for row in rows if row["lane_type"] == Lane.LaneType.CONTROL),
        "read_count": len(read_rows),
        "analysed_count": sum(1 for row in read_rows if row["analysed"]),
        "calibration_info": calibration,
        "quant_calibration_info": quant,
    }


def assay_label(gel_image) -> str:
    """The assay as the pages name it: its row's name, else "<gel type> · no assay" (detail.html)."""
    if gel_image.assay_id is not None:
        return gel_image.assay.name
    return f"{gel_image.get_gel_type_display()} · no assay"


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _status_hint(analysis, next_text):
    """The header hint of ``analyses/detail.html``, by status (none on a rejected analysis)."""
    status = analysis.status
    if status == GelAnalysis.Status.DRAFT:
        return {"icon": "pencil", "text": "Draft — annotate the lanes to start", "tone": None}
    if status == GelAnalysis.Status.IN_PROGRESS:
        return {"icon": "signpost-2", "text": next_text, "tone": None}
    if status == GelAnalysis.Status.COMPLETED:
        return {"icon": "hourglass-split", "text": "Awaiting QA review", "tone": None}
    if status == GelAnalysis.Status.APPROVED:
        approver = analysis.approved_by
        name = (approver.get_full_name() or approver.username) if approver else ""
        return {"icon": "check-circle", "text": f"Approved by {name}" if name else "Approved", "tone": "ok"}
    return None


def _cards(analysis, summary):
    """The metric cards of ``analyses/detail.html``, as text: counts, readout, calibrations."""
    total_lanes, total_bands = analysis.total_lanes, analysis.total_bands
    control_count = summary["control_count"]
    lanes_sub = f"+ {_plural(control_count, 'control')} · " if control_count else ""
    cards = [
        {
            "label": "Sample lanes",
            "value": str(summary["sample_count"]),
            "sub": f"{lanes_sub}{_plural(total_lanes, 'lane')} in all",
        },
        {"label": "Bands", "value": str(total_bands), "sub": "annotated" if total_bands else "none detected yet"},
    ]
    if summary["readout"] != Readout.NONE:
        read, analysed = summary["read_count"], summary["analysed_count"]
        cards.append(
            {
                "label": "Densitometry",
                "value": f"{analysed} / {read}",
                "sub": "lanes analysed",
                "tone": "ok" if read and analysed == read else None,
            }
        )
    if summary["headline"]:
        cards.append({**summary["headline"], "readout": True})
    calibration = summary["calibration_info"]
    if calibration["status"] == "calibrated":
        r2 = calibration["best_r_squared"]
        template = f" · {calibration['template_name']}" if calibration["template_name"] else ""
        cards.append(
            {
                "label": "MW calibration",
                "value": "R² —" if r2 is None else f"R² {r2:.3f}",
                "sub": f"{_plural(calibration['ladder_count'], 'ladder')}{template}",
                "title": "Molecular weight calibration (ladder → kDa)",
            }
        )
    quant = summary["quant_calibration_info"]
    if quant["status"] == "calibrated":
        r2 = quant["r_squared"]
        cards.append(
            {
                "label": "Quantification",
                "value": "R² —" if r2 is None else f"R² {r2:.3f}",
                "sub": f"{_plural(quant['point_count'], 'point')} · {quant['method_display']} · {quant['unit_display']}",
                "title": quant["equation"] or "",
            }
        )
    return cards


def reading_guide(readout: str, reference_lane_number=None) -> list[dict]:
    """What a band counts as on a gel of this readout, as the annotation editor's card lists it.

    A purity is read by band type (the colours the gel is drawn in); a western by the band's role
    (``band_roles``: the swatch its band form shows, and the gel's colour once coloured by readout).
    ``swatch`` names a ga-workbench colour token the browser maps (``b-poi``, ``b-other``, ``b-mw``,
    ``z-aggregate``, ``z-main``, ``z-clipping``, ``left-out``, ``ref``): the colours stay the theme's, the
    words are these.
    """

    def item(swatch, label, text):
        return {"swatch": swatch, "label": label, "text": text}

    if readout == Readout.PURITY:
        return [
            item("b-poi", "POI", "Its share of the lane is the purity Process Development receives"),
            item("b-other", "Other", "Every other band, in the lane total"),
            item("b-mw", "MW reference", "Ladder bands, never counted"),
        ]
    if readout == Readout.MOLECULE_VARIANTS:
        return [
            item(swatch, *ROLE_TEXTS[role])
            for swatch, role in (
                ("z-aggregate", readout_roles.AGGREGATE),
                ("z-main", readout_roles.MAIN_BAND),
                ("z-clipping", readout_roles.CLIPPING),
            )
        ]
    if readout == Readout.HOST_CELL_PROTEINS:
        if reference_lane_number is not None:
            reference = item(
                "ref", f"Reference: lane {reference_lane_number}", "Every HCP % is computed against it (same membrane)"
            )
        else:
            reference = item("ref", "No reference lane yet", "Set one on a SAMPLE or CONTROL lane")
        return [
            item("b-other", "HCP bands", "The Other bands: the HCP signal of the lane"),
            item("left-out", "POI band", f"{POI_LEFT_OUT_TEXT} Left out."),
            reference,
        ]
    return [item("b-other", READOUT_LABELS[Readout.NONE], "The bands are annotated; nothing is computed on this gel")]


def _role_hints(summary) -> dict:
    """``{lane pk: text}``: why the bands of a lane the reading lists have no role yet (a lane it does not list
    -- a ladder, a control that is not the reference, any lane of a purity gel -- gets none: its bands are
    read by their type).

    Only the two reasons that leave every band of the lane without a role (``readouts.band_roles``): not
    analysed, and no POI band on an anti-molecule lane. An anti-HCP lane with no reference keeps its roles --
    that reason is about the % of reference, not about the bands.
    """
    hints = {}
    for entry in summary["readouts"]:
        if entry["values"] is None and entry["reason"] == LANE_NOT_ANALYSED:
            hints[entry["lane_id"]] = ROLE_HINT_NOT_ANALYSED
        elif entry["reason"] == NO_POI_BAND:
            hints[entry["lane_id"]] = f"No role in the reading: {NO_POI_BAND}"
    return hints


def summary_payload(analysis, summary, lanes) -> dict:
    """What the browser renders of :func:`page_summary`: text, numbers and booleans only.

    It goes through ``script_json`` (a plain ``json.dumps``): no datetime, no model, no queryset --
    ``quant_calibration_info`` carries a datetime and must never reach it. ``purity`` is the number
    behind the purity cell (the bars), ``publishes`` whether that lane's purity reaches Process
    Development (``signals.lane_publishes_purity``: a SAMPLE lane of a purity gel, never on a rejected
    analysis).
    """
    readout = summary["readout"]
    publishes = {}
    if readout == Readout.PURITY:
        publishes = {lane.pk: lane_publishes_purity(lane) for lane in lanes}
    checks = [
        {key: check[key] for key in ("kind", "level", "title", "detail", "url", "link")} for check in summary["checks"]
    ]
    reference = next((row["lane_number"] for row in summary["rows"] if row["is_reference"]), None)
    hints = _role_hints(summary)
    return {
        "readout": readout,
        "readout_label": summary["readout_label"],
        "assay_label": assay_label(analysis.gel_image),
        "status": analysis.status,
        "status_label": analysis.get_status_display(),
        "hint": _status_hint(analysis, summary["next_step"]),
        "cards": _cards(analysis, summary),
        "checks": checks,
        "columns": summary["columns"],
        "rows": [
            {**payload_row(row, readout, publishes.get(row["id"], False)), "role_hint": hints.get(row["id"])}
            for row in summary["rows"]
        ],
        # The annotation editor's reading (slice 3c): what each colour means, each role's words, its checks.
        "guide": reading_guide(readout, reference),
        "role_texts": {role: {"label": label, "why": why} for role, (label, why) in ROLE_TEXTS.items()},
        "annotation_checks": [check for check in checks if check["kind"] in ANNOTATION_CHECK_KINDS],
    }


def payload_row(row, readout: str, publishes: bool) -> dict:
    """One :func:`lane_rows` row as the browser reads it: the summary payload's rows and the
    comparison's lane readouts (``services/comparison_items.py``) print the same cells."""
    return {
        "id": row["id"],
        "lane_number": row["lane_number"],
        "lane_type": row["lane_type"],
        "sample": row["sample"],
        "sample_url": row["sample_url"],
        "is_read": row["is_read"],
        "is_reference": row["is_reference"],
        "reason": row["reason"],
        "cells": row["cells"],
        "purity": row["values"].get("purity") if readout == Readout.PURITY else None,
        "publishes": publishes,
        # Whether a mean purity counts this lane (services/mean_purity.py): the comparison averages
        # the lanes it shows by this flag, never by a rule of its own.
        "in_mean_purity": lane_in_mean_purity(row["lane_type"]),
    }


def _corrected_area(band):
    try:
        return band.densitometry.corrected_area
    except DensitometryResult.DoesNotExist:
        return None


def band_role_map(summary, lanes) -> dict:
    """``{str(band pk): role}`` for the bands of the lanes whose published readout has values.

    A role exists where a value does: a lane ``lane_readouts`` lists with values (a SAMPLE lane or
    the HCP reference, analysed). Every other band -- a ladder, a control that is not the reference,
    a lane not analysed, a purity or no-readout gel -- has none and is drawn by its type. The roles
    come from ``readouts.band_roles``, the classification the published percentages sum; all the
    lane's bands go in, in order, so a band never takes its neighbour's role.
    """
    valued = {entry["lane_id"] for entry in summary["readouts"] if entry["values"] is not None}
    roles = {}
    for lane in lanes:
        if lane.pk not in valued:
            continue
        bands = list(lane.bands.all())
        readings = [
            BandReading(band.band_type, band.position_y, _corrected_area(band), band.estimated_mw_kda) for band in bands
        ]
        for band, role in zip(bands, band_roles(summary["readout"], readings)["roles"], strict=False):
            roles[str(band.pk)] = role
    return roles
