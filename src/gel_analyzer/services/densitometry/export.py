"""
The densitometry CSV export: the analysis's SAVED densitometry, as the densitometry page shows it.

Owner, 2026-10-13: the export re-ran the densitometry with default parameters. An analysis run with
Loading Control came out in Lane Total, its areas measured on the current annotations rather than
the saved run, beside amounts stored against the saved run, under a "# Parameters" block naming
the defaults. It now reads what the runs saved and nothing else: no image is loaded, nothing is
measured. :func:`export_saved_csv` is the one function behind the page's POST and the Celery task.

What it reads:

- per band, ``DensitometryResult``: areas, shares, fit, estimated amount and its range, saturation;
- per lane, ``LaneDensitometrySummary``: totals, purity (``signals.published_purity``), the
  normalization the lane was saved with;
- the gel's mean purity through ``services/mean_purity.py``, the one definition;
- the "# Parameters" of the last COMPLETED ``DensitometryJob``, and each lane's own normalization.

Refused, never compensated: an analysis with no saved densitometry raises
:class:`NoSavedDensitometry`; a lane whose bands are not all in the saved densitometry (an edit
clears a lane's, ``signals.invalidate_lane_densitometry``) is left out and named in the file; a
saved lane the last completed run did not write is named too, the parameters printed not being its.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

from .models import DensitometryParams
from .saturation import is_saturated, saturated_pixel_threshold

if TYPE_CHECKING:
    from gel_analyzer.models import DensitometryJob, DensitometryResult, GelAnalysis, LaneDensitometrySummary

logger = get_logger(__name__)

RUN_THE_DENSITOMETRY_FIRST = (
    "Run the densitometry first: this analysis has no saved densitometry to export "
    "(an edit to a lane or to its bands clears that lane's)."
)


class NoSavedDensitometry(Exception):
    """The analysis has no saved densitometry: the export refuses, it never measures one."""

    def __init__(self):
        super().__init__(RUN_THE_DENSITOMETRY_FIRST)


def _lanes_text(numbers) -> str:
    """The lanes named as the page's checks name them: "Lane 3", "Lanes 3, 5"."""
    numbers = sorted(numbers)
    return f"Lane {numbers[0]}" if len(numbers) == 1 else "Lanes " + ", ".join(str(n) for n in numbers)


def _summary_of(lane) -> LaneDensitometrySummary | None:
    from gel_analyzer.models import LaneDensitometrySummary

    try:
        return lane.densitometry_summary
    except LaneDensitometrySummary.DoesNotExist:
        return None


def _result_of(band) -> DensitometryResult | None:
    from gel_analyzer.models import DensitometryResult

    try:
        return band.densitometry
    except DensitometryResult.DoesNotExist:
        return None


def _fit_successful(result: DensitometryResult) -> bool:
    """Whether the band's Gaussian fit held: ``_save_results`` stores R² 0.0 for a fit that failed or
    fell under ``min_fit_r_squared``, whose area is then the trapezoid's and its peak values unset."""
    return result.fit_r_squared > 0.0


def _saturation_cells(fraction) -> list[str]:
    """The band's "Saturated Pixels (%)" and "Saturated" cells: empty when it was not counted."""
    saturated = is_saturated(fraction)
    if saturated is None:
        return ["", ""]
    return [f"{fraction * 100:.2f}", "yes" if saturated else "no"]


def _last_completed_job(analysis) -> DensitometryJob | None:
    from gel_analyzer.models import DensitometryJob

    return (
        DensitometryJob.objects.filter(analysis=analysis, status=DensitometryJob.Status.COMPLETED)
        .order_by("-completed_at", "-created_at")
        .first()
    )


def _written_by(job: DensitometryJob, summary: LaneDensitometrySummary) -> bool:
    """Whether ``job``'s run wrote ``summary``: a run saves its lane summaries (``computed_at``,
    ``auto_now``) after the job starts and before it is marked completed."""
    return (job.started_at or job.created_at) <= summary.computed_at <= job.completed_at


def _run_parameters(job: DensitometryJob) -> list[tuple[str, object]]:
    """The parameters ``job``'s run computed with: its request completed with the defaults, as the
    task builds them (``DensitometryParams.from_dict``; the keys the request left out read with the
    code's defaults of today). A request the code no longer accepts -- a retired normalization --
    is printed as it was sent."""
    try:
        return list(DensitometryParams.from_dict(job.params or {}).to_dict().items())
    except (TypeError, ValueError):
        return sorted((job.params or {}).items())


def export_saved_csv(analysis: GelAnalysis, include_profile: bool = False) -> str:
    """The CSV of ``analysis``'s saved densitometry (module docstring): a few queries, no measure.

    Columns, their order and their names are the ones the export always had. The "Est. Unit" cell
    prints the unit as the pages do (µg, µg/mL), no longer its stored code (UG, UG_ML).

    Raises:
        NoSavedDensitometry: no lane of the analysis has saved densitometry.
    """
    from django.db.models import Prefetch

    from gel_analyzer.models import Band
    from gel_analyzer.services.mean_purity import mean_purity
    from gel_analyzer.signals import published_purity

    lanes = list(
        analysis.lanes.select_related("densitometry_summary")
        .prefetch_related(
            Prefetch("bands", queryset=Band.objects.select_related("densitometry").order_by("position_y", "pk"))
        )
        .order_by("lane_number", "pk")
    )

    # A lane is exported whole or not at all: its summary and every band's result, from one run.
    saved, not_saved = [], []
    for lane in lanes:
        bands = list(lane.bands.all())
        summary = _summary_of(lane)
        results = [_result_of(band) for band in bands]
        if summary is not None and all(result is not None for result in results):
            saved.append((lane, summary, list(zip(bands, results, strict=False))))
        elif bands:
            not_saved.append(lane.lane_number)
    if not saved:
        raise NoSavedDensitometry()

    job = _last_completed_job(analysis)
    from_other_run = [lane.lane_number for lane, summary, _ in saved if job and not _written_by(job, summary)]
    rows = [(band, result) for _, _, band_rows in saved for band, result in band_rows]
    # Every lane, as mean_purity asks: one left out of the file has no purity here, and still counts among
    # the sample lanes its text names (the page card's "n of m sample lanes")
    purities = {lane.pk: published_purity(summary) for lane, summary, _ in saved}
    mean = mean_purity(analysis.gel_image, ((lane.lane_type, purities.get(lane.pk)) for lane in lanes))
    # Amounts show only under an active calibration, as on the page: a deactivated one leaves its amounts behind
    amounts_active = analysis.quant_calibrations.filter(is_active=True).exists()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header section
    writer.writerow(["# Gel Densitometry Analysis Report"])
    writer.writerow(["# Generated", datetime.now().isoformat()])
    writer.writerow(["# Analysis ID", str(analysis.id)])
    writer.writerow(["# Analysis Name", analysis.name])
    writer.writerow(["# Image", analysis.gel_image.original_filename if analysis.gel_image else "N/A"])
    writer.writerow(["# Results", "the saved densitometry, as the densitometry page shows it: nothing re-measured"])
    writer.writerow(
        ["# Densitometry Run", job.completed_at.isoformat() if job else "not on record: its parameters are unknown"]
    )
    writer.writerow(["# Est. Amount", "as stored by the active quantification calibration, with its range"])
    if not_saved:
        writer.writerow(
            [
                "# Not In This File",
                f"{_lanes_text(not_saved)}: bands without saved densitometry (an edit since the run cleared it, "
                "or the run did not include them). Run the densitometry again to include them.",
            ]
        )
    if from_other_run:
        writer.writerow(
            [
                "# Not From This Run",
                f"{_lanes_text(from_other_run)}: saved by another run. The parameters below are not theirs, "
                "except their normalization (normalization_method by lane).",
            ]
        )
    writer.writerow([])

    # Summary section. A run saves only the lanes it integrated: every lane here is a successful one.
    writer.writerow(["# Summary"])
    writer.writerow(["Lanes Processed", len(saved)])
    writer.writerow(["Lanes Successful", len(saved)])
    writer.writerow(["Total Bands", len(rows)])
    writer.writerow(["Gel Total Area", f"{sum(summary.total_integrated_area for _, summary, _ in saved):.2f}"])
    if mean.value is not None:
        writer.writerow(["Average Purity (%)", f"{mean.value:.2f}"])
        writer.writerow(["Average Purity Lanes", mean.lanes_text])
    # A warning only: no area below is corrected for it (saturation.py)
    writer.writerow(["Saturated Bands", sum(1 for _, result in rows if result.saturated)])
    writer.writerow(["Saturation Threshold (% of pixels)", f"{saturated_pixel_threshold() * 100:g}"])
    writer.writerow([])

    # Parameters section: the last completed run's, and the normalization each lane was saved with
    writer.writerow(["# Parameters"])
    for key, value in _run_parameters(job) if job else []:
        writer.writerow([key, value])
    by_method: dict[str, list[int]] = {}
    for lane, summary, _ in saved:
        by_method.setdefault(summary.get_normalization_method_display(), []).append(lane.lane_number)
    writer.writerow(
        [
            "normalization_method by lane",
            "; ".join(f"{label}: {_lanes_text(numbers)}" for label, numbers in by_method.items()),
        ]
    )
    writer.writerow([])

    # Lane summary table
    writer.writerow(["# Lane Summary"])
    writer.writerow(
        [
            "Lane Number",
            "Lane Type",
            "Total Area",
            "POI Area",
            "Other Area",
            "Purity (%)",
            "Band Count",
            "POI Bands",
        ]
    )
    for lane, summary, _ in saved:
        purity = published_purity(summary)
        writer.writerow(
            [
                lane.lane_number,
                lane.lane_type,
                f"{summary.total_integrated_area:.2f}",
                f"{summary.poi_integrated_area:.2f}" if summary.poi_integrated_area else "",
                f"{summary.other_integrated_area:.2f}" if summary.other_integrated_area else "",
                f"{purity:.2f}" if purity is not None else "",
                summary.band_count,
                summary.poi_band_count,
            ]
        )
    writer.writerow([])

    # Band details table
    writer.writerow(["# Band Details"])
    writer.writerow(
        [
            "Lane",
            "Band ID",
            "Band Type",
            "Position Y",
            "MW (kDa)",
            "Peak Center",
            "Amplitude",
            "Sigma",
            "FWHM",
            "Corrected Area",
            "R-squared",
            "SNR",
            "% Lane",
            "% Gel",
            "Fit Quality",
            "Est. Amount",
            "Est. Unit",
            "Calibration Range",
            "Saturated Pixels (%)",
            "Saturated",
        ]
    )
    for lane, _, band_rows in saved:
        for band, result in band_rows:
            fit = _fit_successful(result)
            amount = result.estimated_amount if amounts_active else None
            writer.writerow(
                [
                    lane.lane_number,
                    band.id,
                    band.band_type,
                    band.position_y,
                    f"{band.estimated_mw_kda:.1f}" if band.estimated_mw_kda else "",
                    f"{result.peak_center_y:.2f}" if fit else "",
                    f"{result.peak_amplitude:.2f}" if fit else "",
                    f"{result.peak_sigma:.2f}" if fit else "",
                    f"{result.fwhm:.2f}" if fit else "",
                    f"{result.corrected_area:.2f}",
                    f"{result.fit_r_squared:.4f}" if fit else "",
                    f"{result.snr:.2f}" if result.snr else "",
                    f"{result.relative_percent_lane:.2f}" if result.relative_percent_lane else "",
                    f"{result.relative_percent_gel:.2f}" if result.relative_percent_gel else "",
                    result.fit_quality if fit else "failed",
                    f"{amount:.4g}" if amount is not None else "",
                    result.get_estimated_amount_unit_display() if amount is not None else "",
                    result.estimated_amount_range if amount is not None and result.estimated_amount_range else "",
                    *_saturation_cells(result.saturated_pixel_fraction),
                ]
            )

    if include_profile:
        writer.writerow([])
        writer.writerow(["# Profile Data"])
        for lane, summary, _ in saved:
            _write_profile(writer, lane.lane_number, summary.profile_data)

    return output.getvalue()


def _write_profile(writer, lane_number: int, profile: dict | None) -> None:
    """One lane's saved profile (``LaneProfileData.to_dict``, as the run stored it)."""
    if not profile or not profile.get("y_positions"):
        return
    writer.writerow([f"# Lane {lane_number} Profile"])
    writer.writerow(["Y Position", "Intensity", "MW (kDa)", "Background", "Raw"])
    background = profile.get("background") or []
    raw = profile.get("raw_intensities") or []
    mw_values = profile.get("mw_values") or []
    for i, y in enumerate(profile["y_positions"]):
        mw = mw_values[i] if i < len(mw_values) else None
        writer.writerow(
            [
                y,
                f"{profile['intensities'][i]:.2f}",
                f"{mw:.2f}" if mw else "",
                f"{background[i]:.2f}" if i < len(background) else "",
                f"{raw[i]:.2f}" if i < len(raw) else "",
            ]
        )
    writer.writerow([])


def generate_csv_filename(analysis: GelAnalysis) -> str:
    """
    Generate a filename for CSV export.

    Args:
        analysis: GelAnalysis model.

    Returns:
        Filename string.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = analysis.name.replace(" ", "_")[:30] if analysis.name else "analysis"
    return f"densitometry_{name}_{timestamp}.csv"
