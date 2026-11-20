"""When a lane's POI share is a purity -- the ONE copy of the rule.

Ported from ds-hub-django's ``gel_analyzer/signals.py``. There the same rules
also decide what is published to Process Development; Phoresis publishes
nowhere, so only the reading rules are kept. ``gel_analyzer.signals``
re-exports them under their hub names, so code ported from the hub imports
them unchanged.
"""

from django.db.models import Q

from gel_analyzer.models import GelAssay, GelImage

# The gel types whose POI share of the lane is a purity -- the FALLBACK for
# images without an assay (uploaded before GelAssay existed); an image with an
# assay is decided by its readout. An SDS-PAGE stains every protein of the lane,
# so POI / lane total is one. A western blot stains only what its antibody
# recognises: on an anti-HCP blot every band is a host-cell protein (POI ~ 0 %),
# on an anti-product blot every band is the molecule or one of its variants
# (POI ~ 100 %).
PURITY_GEL_TYPES = frozenset({GelImage.GelType.SDS_PAGE})


def image_measures_purity(gel_image) -> bool:
    """True when a lane's POI share on this gel is a purity: the rule is the IMAGE's.

    The image's assay decides when it has one (readout PURITY); an image without an assay falls
    back to its gel type (``PURITY_GEL_TYPES``).
    """
    if gel_image is None:
        return False
    if gel_image.assay_id is not None:
        return gel_image.assay.readout == GelAssay.Readout.PURITY
    return gel_image.gel_type in PURITY_GEL_TYPES


def lane_measures_purity(lane) -> bool:
    """True when the lane's POI share is a purity: its gel's rule (:func:`image_measures_purity`)."""
    return image_measures_purity(lane.analysis.gel_image)


def lanes_measuring_purity_q() -> Q:
    """``lane_measures_purity`` as a filter on a ``Lane`` queryset; the two must stay one rule."""
    return Q(analysis__gel_image__assay__readout=GelAssay.Readout.PURITY) | Q(
        analysis__gel_image__assay__isnull=True,
        analysis__gel_image__gel_type__in=PURITY_GEL_TYPES,
    )


def published_purity(summary) -> float | None:
    """The purity a lane summary shows: its POI share when a POI band carries signal, else None.

    The normaliser stores POI / (POI + OTHER) = 0 % for a lane with no POI band typed (or none
    with signal); shown as a purity, that 0 % reads as "no product" when the POI was simply never
    typed. The share is above zero exactly when a POI band counts (a corrected area above zero,
    the ``readouts`` rule), so the summary alone decides.
    """
    share = summary.poi_percentage
    return share if share is not None and share > 0 else None


def summaries_publishing_purity_q(prefix: str = "") -> Q:
    """``published_purity(summary) is not None`` as a filter; ``prefix`` reaches the summary from another model."""
    return Q(**{f"{prefix}poi_percentage__gt": 0})
