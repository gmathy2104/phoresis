"""
The western-blot readouts as the screens and the reports show them.

In ds-hub-django this module is also the ONE writer of those readouts into
Process Development -- hence its name, kept so the code ported from the hub
imports it unchanged. Phoresis has no such registry: a readout is computed from
the persisted bands each time a page or a report asks (``services/readouts.py``),
and nothing is stored or published. :func:`western_routing` therefore always
answers None and :func:`publish_gel_readouts` writes nothing.

:func:`lane_readouts` gives every screen the same values through the same
:func:`_lane_values` -- the JS never computes a readout.
"""

from __future__ import annotations

from gel_analyzer.models import GelAssay, Lane, LaneDensitometrySummary
from gel_analyzer.services.readouts import (
    LANE_NOT_ANALYSED,
    REFERENCE_NOT_ANALYSED,
    host_cell_proteins,
    lane_bands,
    protein_variants,
)


def western_routing(analysis):
    """Where a western readout is published: nowhere in Phoresis, so always None.

    In the hub it answers ``(assay, analysis_type)`` for an assay routed to a Process Development
    type; the callers ported from there read None as "this gel publishes nothing".
    """
    return None


def publish_gel_readouts(analysis) -> dict:
    """Publish the analysis's western readouts: a no-op in Phoresis (module docstring)."""
    return {"published": 0, "skipped": "Phoresis publishes no readout"}


def _summary_of(lane):
    try:
        return lane.densitometry_summary
    except LaneDensitometrySummary.DoesNotExist:
        return None


def _prefetched_lanes(analysis):
    """The analysis's lanes when a caller prefetched them (``prefetch_related("lanes")``), else None.

    Taken as ALL its lanes: a caller prefetches them whole, never filtered -- a filtered prefetch
    would drop lanes from :func:`lane_readouts` and could hide the reference lane.
    """
    if "lanes" in getattr(analysis, "_prefetched_objects_cache", {}):
        return list(analysis.lanes.all())
    return None


def _reference_lane(analysis):
    """``analysis.readout_reference_lane`` -- the prefetched lane object when the lanes were prefetched.

    So the reference carries its prefetched summary and bands (no query). A reference that is not
    among them (a lane of another analysis, which ``GelAnalysis.clean`` refuses) is read through the
    FK.
    """
    reference_id = analysis.readout_reference_lane_id
    if reference_id is None:
        return None
    for lane in _prefetched_lanes(analysis) or ():
        if lane.pk == reference_id:
            return lane
    return analysis.readout_reference_lane


def _reference_bands(analysis):
    """``(reference lane, its bands or None, reason when there is no usable reference)``."""
    reference = _reference_lane(analysis)
    if reference is None:
        return None, None, None  # host_cell_proteins says "no reference lane"
    if _summary_of(reference) is None:
        return reference, None, REFERENCE_NOT_ANALYSED
    return reference, lane_bands(reference), None


def _lane_values(assay, lane, reference_bands, reference_reason) -> dict:
    """The readout of one analysed lane: ``services/readouts.py`` on its persisted bands.

    The ONE path every screen and report takes. HCP: ``reference_reason`` (a reference lane is set
    but not analysed yet) replaces the calculation's "no reference lane", which only sees
    ``reference_bands`` being None.
    """
    bands = lane_bands(lane)
    if assay.readout == GelAssay.Readout.MOLECULE_VARIANTS:
        return protein_variants(bands)
    values = host_cell_proteins(bands, reference_bands)
    if reference_reason and values["hcp_signal_vs_reference_percent"] is None:
        values["reason"] = reference_reason
    return values


def assay_summary(analysis) -> dict | None:
    """``{"id", "name", "readout"}`` of the assay that reads the analysis's image, or None."""
    gel_image = analysis.gel_image
    if gel_image is None or gel_image.assay_id is None:
        return None
    assay = gel_image.assay
    return {"id": assay.pk, "name": assay.name, "readout": assay.readout}


def lane_readouts(analysis) -> list[dict]:
    """The western readout of each lane, as the densitometry page shows it.

    One entry per SAMPLE lane, plus the HCP reference lane whatever its type (an HCP standard is
    often typed CONTROL), in lane order: ``lane_id``, ``lane_number``, ``lane_type``,
    ``sample_name`` (the typed name -- never ``Lane.display_name``), ``values`` (the
    ``services/readouts.py`` dict without its ``reason``, or None for a lane not analysed yet --
    never zeros), ``reason`` (why a value is missing, else None) and ``is_reference``.

    Empty for an image without a western assay. Callers select_related ``gel_image__assay`` and
    ``readout_reference_lane`` -- or prefetch the lanes WHOLE, with ``densitometry_summary``
    selected and their ``bands`` prefetched with ``densitometry`` selected: then no query at all.
    """
    gel_image = analysis.gel_image
    assay = gel_image.assay if gel_image is not None and gel_image.assay_id is not None else None
    if assay is None or assay.readout not in GelAssay.WESTERN_READOUTS:
        return []

    reference, reference_bands, reference_reason = None, None, None
    if assay.readout == GelAssay.Readout.HOST_CELL_PROTEINS:
        reference, reference_bands, reference_reason = _reference_bands(analysis)
    reference_id = reference.pk if reference is not None else None

    entries = []
    lanes = _prefetched_lanes(analysis)
    if lanes is None:
        lanes = analysis.lanes.select_related("densitometry_summary").order_by("lane_number", "pk")
    else:
        lanes = sorted(lanes, key=lambda lane: (lane.lane_number, lane.pk))
    for lane in lanes:
        is_reference = reference_id is not None and lane.pk == reference_id
        if lane.lane_type != Lane.LaneType.SAMPLE and not is_reference:
            continue
        if _summary_of(lane) is None:
            values, reason = None, LANE_NOT_ANALYSED
        else:
            values = dict(_lane_values(assay, lane, reference_bands, reference_reason))
            reason = values.pop("reason", None)
        entries.append(
            {
                "lane_id": lane.pk,
                "lane_number": lane.lane_number,
                "lane_type": lane.lane_type,
                "sample_name": lane.sample_name,
                "values": values,
                "reason": reason,
                "is_reference": is_reference,
            }
        )
    return entries
