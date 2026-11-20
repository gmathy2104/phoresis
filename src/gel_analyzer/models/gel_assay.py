"""
GelAssay: what a gel image measures, as data the owner edits.

A gel type says how the gel was run (SDS-PAGE, western blot...); an assay says
what it is read for. Two western blots of the same membrane format answer
different questions: an anti-HCP blot shows residual host-cell proteins, an
anti-molecule blot shows the molecule's aggregates and clipping. Only an assay
whose readout is PURITY reads a lane's POI share as a purity
(``gel_analyzer/services/purity.py::lane_measures_purity``).

What stays in code: the readout kinds (``GelAssay.Readout``) and their
calculations (``services/readouts.py``). Names, gel types and how many assays
exist are rows.

Ported from ds-hub-django. There, an assay also names the Process Development
analysis type its readout is published to; Phoresis has no such registry, so a
readout is computed and shown, never published elsewhere.
"""

from simple_history.models import HistoricalRecords

from django.core.exceptions import ValidationError
from django.db import models

from .gel_image import GelImage


class GelAssay(models.Model):
    """A named assay run on a gel: its gel type and what its lanes are read for."""

    class Readout(models.TextChoices):
        PURITY = "PURITY", "Purity (POI share of the lane)"
        MOLECULE_VARIANTS = (
            "MOLECULE_VARIANTS",
            "Protein of interest variants (aggregates / main band / clipping)",
        )
        HOST_CELL_PROTEINS = "HOST_CELL_PROTEINS", "Host-cell proteins"
        NONE = "NONE", "No readout"

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Shown in the assay select, e.g. Western blot — anti-HCP",
    )
    gel_type = models.CharField(
        max_length=20,
        choices=GelImage.GelType.choices,
        help_text="The gel type an image must have to use this assay",
    )
    readout = models.CharField(
        max_length=30,
        choices=Readout.choices,
        help_text="What a lane of this assay is read for. Only PURITY reads the POI share as a purity.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Inactive assays are not offered for new images")
    display_order = models.IntegerField(default=0)

    history = HistoricalRecords(history_change_reason_field=models.TextField(null=True))

    # The readouts computed by services/readouts.py -- never a purity.
    WESTERN_READOUTS = frozenset({Readout.MOLECULE_VARIANTS, Readout.HOST_CELL_PROTEINS})

    class Meta:
        verbose_name = "Gel Assay"
        verbose_name_plural = "00. Gel Assays"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        errors = {}
        # The POI share of a lane is a purity only on a gel that stains every
        # protein of the lane.
        if self.readout == self.Readout.PURITY and self.gel_type != GelImage.GelType.SDS_PAGE:
            errors["readout"] = "A purity readout needs an SDS-PAGE gel: on a blot, the POI share follows the antibody."
        # Every image on this assay was validated against its gel type
        # (GelImage.clean); changing it would leave them all on an assay of
        # another gel type -- a western image on an SDS-PAGE purity assay would
        # start reading as a purity.
        if self.pk is not None:
            previous = GelAssay.objects.filter(pk=self.pk).values_list("gel_type", flat=True).first()
            if previous is not None and previous != self.gel_type:
                used_by = self.images.count()
                if used_by:
                    images = "1 image uses" if used_by == 1 else f"{used_by} images use"
                    errors["gel_type"] = f"{images} this assay: its gel type cannot change. Create a new assay instead."
        if errors:
            raise ValidationError(errors)
