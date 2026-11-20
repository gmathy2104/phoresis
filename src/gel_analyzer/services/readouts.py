"""
What a western blot lane reads: the two readouts that are not a purity.

Spec ``docs/superpowers/specs/2026-10-02-gel-assays-readouts-design.md`` §4.1.
A purity (SDS-PAGE, readout ``PURITY``) is the POI share of the lane and stays
where it always was (``LaneDensitometrySummary.poi_percentage`` through
``signals.py``). A western blot stains only what its antibody recognises, so
its lane answers another question:

* ``MOLECULE_VARIANTS`` (anti-molecule blot): which share of the molecule's
  signal sits above the POI band (aggregates), on it (main band) and below it
  (clipping) -- :func:`protein_variants`;
* ``HOST_CELL_PROTEINS`` (anti-HCP blot): how much HCP signal the lane holds, in
  arbitrary units and in % of a reference lane of the same membrane --
  :func:`host_cell_proteins`.

The two calculations are PURE: they take :class:`BandReading` lists and touch no
model, so a test builds a lane by hand and the densitometry page (T3b) can call
them on the same inputs. :func:`lane_bands` is the ONE reader that builds those
lists from the database.

Rules shared by both (§4.1): a band whose ``corrected_area`` is not above zero
never counts (as the lane-total normaliser does), nor does an ``MW_REFERENCE``
or ``CALIBRATION`` band. Values are rounded only at the end.
"""

from __future__ import annotations

from dataclasses import dataclass

POI = "POI"
OTHER = "OTHER"
COUNTED_BAND_TYPES = frozenset({POI, OTHER})

NO_POI_BAND = "no POI band"
NO_REFERENCE_LANE = "no reference lane"
REFERENCE_WITHOUT_HCP_SIGNAL = "reference lane has no HCP signal"
REFERENCE_NOT_ANALYSED = "reference lane not analysed yet"
# A lane with no densitometry summary: the screens say so instead of showing zeros.
LANE_NOT_ANALYSED = "not analysed yet"

COMPARED_BY_MW = "molecular weight"
COMPARED_BY_POSITION = "position"

# A band's part in its lane's western readout (:func:`band_roles`): the screens colour a band by it.
AGGREGATE = "aggregate"
MAIN_BAND = "main"
CLIPPING = "clipping"
HCP_BAND = "hcp"
LEFT_OUT = "left_out"

# The values each readout writes into ``SampleAnalysis.results`` (AnalyticalResultField codes,
# seeded by process_development 0030/0058). The publisher moves exactly these, plus ``reason``,
# under ``results["stale_values"]`` when the row goes stale.
VARIANT_VALUE_KEYS = ("aggregate_percent", "main_band_percent", "fragment_percent")
HCP_VALUE_KEYS = ("hcp_signal_vs_reference_percent", "hcp_total_signal", "band_count")


@dataclass(frozen=True)
class BandReading:
    """One band as the readouts see it: its type, where it sits, its signal."""

    band_type: str  # POI / OTHER / MW_REFERENCE / CALIBRATION
    position_y: float  # image pixels, y grows downwards (= lower MW on a gel the right way up)
    corrected_area: float | None  # DensitometryResult.corrected_area
    estimated_mw_kda: float | None = None  # set on a calibrated analysis


def _counts(band: BandReading) -> bool:
    return band.band_type in COUNTED_BAND_TYPES and band.corrected_area is not None and band.corrected_area > 0


def _variant_roles(counted):
    """``(compared_by, roles)`` of an anti-molecule lane's COUNTED bands, one role per band in order.

    The POI span is ``[min, max]`` of the POI bands; a POI band is the main band, an OTHER band above
    the span an aggregate, below it a clipping product, inside it part of the main band. ``(None, None)``
    when no POI band counts. The one classification :func:`protein_variants` sums and
    :func:`band_roles` shows: two would let a screen colour a band as an aggregate that the published
    percentages count in the main band.
    """
    poi = [band for band in counted if band.band_type == POI]
    if not poi:
        return None, None

    # ``height``: smaller = higher on the gel, whichever comparison is used.
    if all(band.estimated_mw_kda is not None for band in counted):
        compared_by = COMPARED_BY_MW

        def height(band):
            return -band.estimated_mw_kda

    else:
        compared_by = COMPARED_BY_POSITION

        def height(band):
            return band.position_y

    span_top = min(height(band) for band in poi)
    span_bottom = max(height(band) for band in poi)

    roles = []
    for band in counted:
        if band.band_type == POI:
            roles.append(MAIN_BAND)
        elif height(band) < span_top:
            roles.append(AGGREGATE)
        elif height(band) > span_bottom:
            roles.append(CLIPPING)
        else:
            roles.append(MAIN_BAND)
    return compared_by, roles


def protein_variants(bands) -> dict:
    """Aggregates / main band / clipping of an anti-molecule lane, in % of the counted signal.

    The POI span is ``[min, max]`` of the POI bands. An OTHER band above it is an aggregate, below
    it a clipping product (``fragment_percent``), inside it part of the main band with the POI.

    "Above" is a HIGHER molecular weight when every counted band carries ``estimated_mw_kda`` (a
    calibrated analysis): that comparison survives an image uploaded upside down. Otherwise it is a
    SMALLER ``position_y`` -- and an upside-down image then swaps aggregates and clipping, which
    nothing here can detect. ``compared_by`` says which one was used.

    No POI band: the three values are None, reason "no POI band" -- which band is the molecule is
    never guessed.
    """
    counted = [band for band in bands if _counts(band)]
    compared_by, roles = _variant_roles(counted)
    if roles is None:
        return {
            "aggregate_percent": None,
            "main_band_percent": None,
            "fragment_percent": None,
            "compared_by": None,
            "reason": NO_POI_BAND,
        }

    aggregate = main = fragment = 0.0
    for band, role in zip(counted, roles, strict=False):
        if role == AGGREGATE:
            aggregate += band.corrected_area
        elif role == CLIPPING:
            fragment += band.corrected_area
        else:
            main += band.corrected_area

    total = aggregate + main + fragment  # > 0: at least one POI band counted
    return {
        "aggregate_percent": round(aggregate / total * 100, 2),
        "main_band_percent": round(main / total * 100, 2),
        "fragment_percent": round(fragment / total * 100, 2),
        "compared_by": compared_by,
        "reason": None,
    }


def _hcp_signal(bands) -> tuple[int, float]:
    """(count, summed corrected area) of the HCP bands: the counted OTHER bands, POI excluded."""
    hcp = [band for band in bands if _counts(band) and band.band_type == OTHER]
    return len(hcp), sum(band.corrected_area for band in hcp)


def host_cell_proteins(bands, reference_bands) -> dict:
    """HCP signal of an anti-HCP lane: band count, total (a.u.) and % of the reference lane.

    HCP bands are the OTHER bands. A POI band is cross-reacting molecule, not HCP: it is excluded
    from the signal and only counted (``poi_band_count``) -- counted in, a concentrated product
    would show a high "HCP" signal.

    ``hcp_total_signal`` depends on the exposure and is not comparable from one blot to another;
    ``hcp_signal_vs_reference_percent`` is (same membrane, same exposure). It is None, with a
    reason, when ``reference_bands`` is None ("no reference lane") or the reference holds no HCP
    signal; the total is always given -- the fallback the owner asked for (D3). The reference lane
    itself reads 100.
    """
    band_count, total = _hcp_signal(bands)
    poi_band_count = sum(1 for band in bands if _counts(band) and band.band_type == POI)

    percent = None
    reason = None
    if reference_bands is None:
        reason = NO_REFERENCE_LANE
    else:
        _ref_count, reference_total = _hcp_signal(reference_bands)
        if reference_total > 0:
            percent = round(total / reference_total * 100, 2)
        else:
            reason = REFERENCE_WITHOUT_HCP_SIGNAL

    return {
        "band_count": band_count,
        "hcp_total_signal": round(total, 2),
        "hcp_signal_vs_reference_percent": percent,
        "poi_band_count": poi_band_count,
        "reason": reason,
    }


def band_roles(readout: str, bands) -> dict:
    """Each band's part in its lane's western readout: ``{"compared_by", "roles"}``, roles in input order.

    Anti-molecule (``MOLECULE_VARIANTS``): ``aggregate`` / ``main`` / ``clipping`` by
    :func:`_variant_roles`, the rule :func:`protein_variants` sums -- every role None on a lane with no
    POI band (no value either). Anti-HCP (``HOST_CELL_PROTEINS``): ``hcp`` for a counted OTHER band,
    ``left_out`` for a counted POI band (cross-reacting molecule, :func:`host_cell_proteins`). A band
    that does not count (no area, MW reference, calibration) and any other readout: None. The screens
    colour a band by it and never classify one themselves.
    """
    from gel_analyzer.models import GelAssay

    bands = list(bands)
    roles = [None] * len(bands)
    compared_by = None
    counted_at = [index for index, band in enumerate(bands) if _counts(band)]
    if readout == GelAssay.Readout.MOLECULE_VARIANTS:
        compared_by, variant_roles = _variant_roles([bands[index] for index in counted_at])
        if variant_roles is not None:
            for index, role in zip(counted_at, variant_roles, strict=False):
                roles[index] = role
    elif readout == GelAssay.Readout.HOST_CELL_PROTEINS:
        for index in counted_at:
            roles[index] = LEFT_OUT if bands[index].band_type == POI else HCP_BAND
    return {"compared_by": compared_by, "roles": roles}


def lane_bands(lane) -> list[BandReading]:
    """The lane's bands that carry a persisted densitometry, as :class:`BandReading`.

    The ONE ORM reader of this module. A band with no ``DensitometryResult`` (never integrated, or
    wiped by a band edit) is left out: it has no signal to count.

    Bands a caller PREFETCHED on the lane (``prefetch_related("bands")``, with
    ``select_related("densitometry")``) are read from that prefetch, with no query: the gel export
    reads whole tables this way (Databricks export design I7, ``gel_analyzer/api/export/rows.py``).
    Otherwise one query, as always. Same bands, same order (``Band.Meta.ordering``) either way.
    ⚠️ A prefetch is a snapshot: a WRITER never passes one taken before the run it publishes.
    """
    from gel_analyzer.models import DensitometryResult

    if "bands" in getattr(lane, "_prefetched_objects_cache", {}):
        bands = lane.bands.all()
    else:
        bands = lane.bands.select_related("densitometry")
    readings = []
    for band in bands:
        try:
            densitometry = band.densitometry
        except DensitometryResult.DoesNotExist:
            continue
        readings.append(
            BandReading(
                band_type=band.band_type,
                position_y=band.position_y,
                corrected_area=densitometry.corrected_area,
                estimated_mw_kda=band.estimated_mw_kda,
            )
        )
    return readings
