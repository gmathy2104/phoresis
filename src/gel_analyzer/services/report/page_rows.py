"""
The analysis page's lane values, for the reports: one producer, never a second computation.

A report prints each lane as the analysis page does (``analysis_detail.page_summary``): the columns of the
gel's readout -- a purity on an SDS-PAGE, HMWS / main band / LMWS on an anti-molecule western, the HCP
signal against a reference lane on an anti-HCP western -- each lane's cell (its text, or the reason a value
is missing) and its sample. Until 2026-10-13 the reports printed the lane summary's raw POI share as "Purity"
on every gel: 0.0 % on each lane of an anti-HCP blot, the main band of an anti-molecule blot as a purity, and
0.0 % on a lane with no POI band, where the page said "no POI band".

A comparison report prints its lanes as the comparison page does (``comparison_items.enrich``): grouped by kind
(one assay, ``comparison_items.kind_of``), each kind with its readout's columns, and a purity kind with the mean
purity of its sample lanes (``services/mean_purity.py``). The comparison report printed one "Purity" column and
one chart for SDS-PAGE purities and western POI shares together, and no mean.
"""

from __future__ import annotations

from dataclasses import dataclass

from gel_analyzer.models import GelAnalysis, GelAssay, Lane
from gel_analyzer.services.analysis_detail import (
    band_role_map,
    lane_rows,
    page_summary,
    saturated_bands,
    summary_lanes_prefetch,
    summary_payload,
)
from gel_analyzer.services.mean_purity import MeanPurity, mean_purity
from gel_analyzer.services.readouts import HCP_VALUE_KEYS, VARIANT_VALUE_KEYS

Readout = GelAssay.Readout


@dataclass(frozen=True)
class PageReadout:
    """What the gel is read for, as the page names it."""

    readout: str  # GelAssay.Readout
    label: str  # analysis_detail.READOUT_LABELS
    columns: list  # analysis_detail.readout_columns: [{key, label, title}], after the lane's own fields
    # The page's summary (analysis_detail.summary_payload): what its header and cards say, and its checks.
    assay_label: str = ""
    status_hint: str = ""  # the header's hint ("Ready to mark as complete", "Approved by …"); "" when none
    cards: tuple = ()  # [{label, value, sub, tone, readout?}]: the page's metric cards, the readout's own included
    checks: tuple = ()  # [{kind, level, title, detail}]: the page's "To check" items, warnings first


@dataclass(frozen=True)
class ComparisonKind:
    """One kind of a comparison, as its page groups the lanes: one assay, so one readout and its columns."""

    key: str  # comparison_items.kind_key: the assay's name
    label: str
    readout: str  # GelAssay.Readout
    readout_label: str
    columns: list  # readout_columns(readout, has_quant=False): the comparison reads the readout, not the quantification
    lanes: list  # the report's lanes of this kind, in the comparison's order
    mean: MeanPurity | None = None  # a purity kind's mean purity over its lanes; None on any other kind


def apply_page_rows(analysis: GelAnalysis, lanes_data) -> PageReadout:
    """Copy the page's row of each lane onto its report lane (``LaneReportData`` fields ``sample`` ... ``saturated_bands``).

    ``lanes_data``: the report's lanes of ``analysis`` (matched by ``lane_id``). The analysis is read again with
    the page's own prefetch, so the rows are the page's whatever the caller loaded.
    """
    analysis = (
        GelAnalysis.objects.select_related("gel_image__assay")
        .prefetch_related(summary_lanes_prefetch())
        .get(pk=analysis.pk)
    )
    lanes = list(analysis.lanes.all())
    summary = page_summary(analysis, lanes)
    _apply_rows(lanes, summary["rows"], lanes_data)
    _apply_roles(band_role_map(summary, lanes), lanes_data)
    payload = summary_payload(analysis, summary, lanes)
    return PageReadout(
        summary["readout"],
        summary["readout_label"],
        summary["columns"],
        assay_label=payload["assay_label"],
        status_hint=(payload["hint"] or {}).get("text", ""),
        cards=tuple(payload["cards"]),
        checks=tuple(payload["checks"]),
    )


def apply_comparison_rows(lanes_data) -> list[ComparisonKind]:
    """The comparison page's rows for a comparison report's lanes, and its kinds in the comparison's order.

    What ``comparison_items.enrich`` does for the page, from the same producers: each analysis read whole, its kind
    (``kind_of``), ``lane_readouts`` on a western, then ``lane_rows`` for the compared lanes only. Each report lane
    gets its row (the fields :func:`apply_page_rows` sets) and its ``kind_key``.
    """
    from gel_analyzer.services.comparison_items import kind_of
    from gel_analyzer.services.readout_publisher import lane_readouts

    compared = {lane.lane_id: lane for lane in lanes_data}
    analyses = (
        GelAnalysis.objects.filter(pk__in={lane.analysis_id for lane in lanes_data if lane.analysis_id})
        .select_related("gel_image__assay")
        .prefetch_related(summary_lanes_prefetch())
    )
    kinds, images = {}, {}
    for analysis in analyses:
        kind = kind_of(analysis.gel_image)
        kinds.setdefault(kind["key"], kind)
        images.setdefault(kind["key"], analysis.gel_image)
        lanes = [lane for lane in analysis.lanes.all() if lane.pk in compared]
        readouts = lane_readouts(analysis) if kind["readout"] in GelAssay.WESTERN_READOUTS else None
        rows = lane_rows(analysis, lanes, kind["readout"], has_quant=False, readouts=readouts)
        _apply_rows(lanes, rows, [compared[lane.pk] for lane in lanes])
        roles = band_role_map({"readout": kind["readout"], "readouts": readouts or []}, lanes)
        _apply_roles(roles, [compared[lane.pk] for lane in lanes])
        for lane in lanes:
            compared[lane.pk].kind_key = kind["key"]

    out = []
    for key in dict.fromkeys(lane.kind_key for lane in lanes_data if lane.kind_key):
        kind = kinds[key]
        members = [lane for lane in lanes_data if lane.kind_key == key]
        mean = None
        if kind["readout"] == Readout.PURITY:
            # The lanes the comparison shows, by the one rule (the page averages by each row's in_mean_purity).
            mean = mean_purity(
                images[key], ((lane.lane_type_code, lane.readout_numbers.get("purity")) for lane in members)
            )
        out.append(
            ComparisonKind(key, kind["label"], kind["readout"], kind["readout_label"], kind["columns"], members, mean)
        )
    return out


def _apply_rows(lanes, rows, lanes_data):
    """Copy each ``lane_rows`` row, and the lane's saturated bands, onto the report lane of the same lane id."""
    rows = {row["id"]: row for row in rows}
    numbers = {lane.pk: lane.lane_number for lane in lanes}
    saturated = {}
    for lane_number, number, word in saturated_bands(lanes):
        saturated.setdefault(lane_number, []).append(f"B{number} ({word})")
    for lane_data in lanes_data:
        row = rows.get(lane_data.lane_id)
        if row is None:
            continue
        lane_data.sample = row["sample"]
        lane_data.readout_cells = dict(row["cells"])
        lane_data.readout_numbers = _numbers(row)
        lane_data.readout_reason = row["reason"]
        lane_data.is_read = row["is_read"]
        lane_data.is_reference = row["is_reference"]
        lane_data.saturated_bands = saturated.get(numbers[lane_data.lane_id], [])


def _apply_roles(roles: dict, lanes_data):
    """Give each report band its role in the western readout (``band_role_map``: ``{str(band pk): role}``)."""
    for lane_data in lanes_data:
        for band in lane_data.bands:
            band.role = roles.get(band.band_id)


def gel_mw_ticks(analysis_id) -> list:
    """The kDa ticks of a gel, in image pixels, as the sample identity card draws them (``sample_gels``: the ladder's
    calibration, else its MW reference bands): those of its first ladder lane, else of its first lane; [] when none."""
    from gel_analyzer.services.sample_gels import lane_strip_entries

    lanes = (
        Lane.objects.filter(analysis_id=analysis_id)
        .select_related("analysis__gel_image__assay", "densitometry_summary")
        .prefetch_related("bands__densitometry")
        .order_by("lane_number", "x")
    )
    lane = next((lane for lane in lanes if lane.lane_type == Lane.LaneType.LADDER), None) or lanes.first()
    if lane is None:
        return []
    return lane_strip_entries([lane])[lane.pk]["mw_ticks"]


def lane_strips(lane_ids) -> dict:
    """``{lane id: entry}``: each lane's ``sample_gels.lane_strip_entries`` entry -- the sample identity card's
    producer (the whole gel's lane outlines, the lane's bands and stored profile, the nearest ladder's kDa ticks)."""
    from gel_analyzer.services.sample_gels import lane_strip_entries

    if not lane_ids:
        return {}
    lanes = (
        Lane.objects.filter(pk__in=lane_ids)
        .select_related("analysis__gel_image__assay", "densitometry_summary")
        .prefetch_related("bands__densitometry")
    )
    return lane_strip_entries(lanes)


def _numbers(row) -> dict:
    """The number behind each cell of the row, by column key: what a workbook writes instead of the text."""
    numbers = {key: row["values"].get(key) for key in row["cells"]}
    numbers["bands"] = row["band_count"]
    if "poi_kda" in row["cells"]:
        numbers["poi_kda"] = row["poi_kda"]
    numbers.pop("measured", None)  # a sum of projected loads with its unit: the cell's text says it whole
    return numbers


def sample_text(lane) -> str:
    """The lane's sample as a report prints it: "no sample" on a sample lane that has none, else "—"."""
    if lane.sample:
        return lane.sample
    return "no sample" if lane.lane_type_code == Lane.LaneType.SAMPLE else "—"


def cell_text(lane, key: str) -> str:
    """The page's cell: its text, else the reason its value is missing; "" for a column the lane has no cell in."""
    cell = lane.readout_cells.get(key)
    if cell is None:
        return ""
    return cell["text"] or cell["reason"] or ""


# The one value a readout is summed up by, in a narrow column: its key, and the words around its cell.
HEADLINE_KEYS = {
    Readout.PURITY: ("purity", "{}"),
    Readout.MOLECULE_VARIANTS: (VARIANT_VALUE_KEYS[1], "main {}"),
    Readout.HOST_CELL_PROTEINS: (HCP_VALUE_KEYS[0], "{} of ref."),
}


def headline_text(readout: str, lane) -> str:
    """The lane's main value for its readout -- "20.2 %", "main 65.0 %", "41.3 % of ref." -- or the page's reason;
    "-" for a lane the readout does not read."""
    key, words = HEADLINE_KEYS.get(readout, (None, "{}"))
    if key is None or key not in lane.readout_cells:
        return "-"
    if lane.readout_numbers.get(key) is None:
        return cell_text(lane, key) or "-"
    return words.format(cell_text(lane, key))


def readout_card(cards) -> dict | None:
    """The page's card of the gel's readout (Mean purity, Main band (mean), HCP reference), or None."""
    return next((card for card in cards if card.get("readout")), None)


def card_text(card: dict) -> str:
    """A card as one line of text: "48.6 % (6 of 7 sample lanes)"."""
    return f"{card['value']} ({card['sub']})" if card.get("sub") else str(card["value"])


def mean_purity_text(mean: MeanPurity | None) -> str:
    """A mean purity and the lanes it averages, as the reports print it: "48.6% (6 of 7 sample lanes)", or "N/A"."""
    if mean is None or mean.value is None:
        return "N/A"
    return f"{mean.value:.1f}% ({mean.lanes_text})"
