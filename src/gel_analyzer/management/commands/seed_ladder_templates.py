"""
Management command to seed MW ladder templates.

Seeds commonly used commercial MW ladders as global templates that all users
can use for calibration.

Usage:
    python manage.py seed_ladder_templates          # Create/update templates
    python manage.py seed_ladder_templates --dry-run  # Preview without changes
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from gel_analyzer.models import (
    BandColor,
    LadderBandDefinition,
    LadderCategory,
    LadderTemplate,
)

# Bio-Rad Precision Plus Protein ladders
PRECISION_PLUS_LADDERS = {
    "PRECISION_PLUS_UNSTAINED": {
        "name": "Precision Plus Protein Unstained Standards",
        "manufacturer": "Bio-Rad",
        "catalog_number": "1610363",
        "category": LadderCategory.UNSTAINED,
        "description": "Ten clearly resolved bands from 10-250 kDa. Standard ladder for accurate MW determination.",
        "bands": [
            {"mw_kda": 250, "band_order": 1, "color": BandColor.NONE},
            {"mw_kda": 150, "band_order": 2, "color": BandColor.NONE},
            {"mw_kda": 100, "band_order": 3, "color": BandColor.NONE},
            {"mw_kda": 75, "band_order": 4, "color": BandColor.NONE},
            {"mw_kda": 50, "band_order": 5, "color": BandColor.NONE},
            {"mw_kda": 37, "band_order": 6, "color": BandColor.NONE},
            {"mw_kda": 25, "band_order": 7, "color": BandColor.NONE},
            {"mw_kda": 20, "band_order": 8, "color": BandColor.NONE},
            {"mw_kda": 15, "band_order": 9, "color": BandColor.NONE},
            {"mw_kda": 10, "band_order": 10, "color": BandColor.NONE},
        ],
    },
    "PRECISION_PLUS_ALL_BLUE": {
        "name": "Precision Plus Protein All Blue Standards",
        "manufacturer": "Bio-Rad",
        "catalog_number": "1610373",
        "category": LadderCategory.PRESTAINED,
        "description": "Ten blue-stained bands from 10-250 kDa. Visible during electrophoresis and transfer.",
        "bands": [
            {"mw_kda": 250, "band_order": 1, "color": BandColor.BLUE},
            {"mw_kda": 150, "band_order": 2, "color": BandColor.BLUE},
            {"mw_kda": 100, "band_order": 3, "color": BandColor.BLUE},
            {"mw_kda": 75, "band_order": 4, "color": BandColor.BLUE},
            {"mw_kda": 50, "band_order": 5, "color": BandColor.BLUE, "is_reference_band": True},
            {"mw_kda": 37, "band_order": 6, "color": BandColor.BLUE},
            {"mw_kda": 25, "band_order": 7, "color": BandColor.BLUE, "is_reference_band": True},
            {"mw_kda": 20, "band_order": 8, "color": BandColor.BLUE},
            {"mw_kda": 15, "band_order": 9, "color": BandColor.BLUE},
            {"mw_kda": 10, "band_order": 10, "color": BandColor.BLUE},
        ],
    },
    "PRECISION_PLUS_DUAL_COLOR": {
        "name": "Precision Plus Protein Dual Color Standards",
        "manufacturer": "Bio-Rad",
        "catalog_number": "1610374",
        "category": LadderCategory.DUAL_COLOR,
        "description": "Ten bands with pink (25, 75 kDa) and blue reference bands. "
        "Easy MW identification during electrophoresis.",
        "bands": [
            {"mw_kda": 250, "band_order": 1, "color": BandColor.BLUE},
            {"mw_kda": 150, "band_order": 2, "color": BandColor.BLUE},
            {"mw_kda": 100, "band_order": 3, "color": BandColor.BLUE},
            {"mw_kda": 75, "band_order": 4, "color": BandColor.PINK, "is_reference_band": True},
            {"mw_kda": 50, "band_order": 5, "color": BandColor.BLUE},
            {"mw_kda": 37, "band_order": 6, "color": BandColor.BLUE},
            {"mw_kda": 25, "band_order": 7, "color": BandColor.PINK, "is_reference_band": True},
            {"mw_kda": 20, "band_order": 8, "color": BandColor.BLUE},
            {"mw_kda": 15, "band_order": 9, "color": BandColor.BLUE},
            {"mw_kda": 10, "band_order": 10, "color": BandColor.BLUE},
        ],
    },
}

# Thermo Fisher PageRuler ladders
PAGE_RULER_LADDERS = {
    "PAGE_RULER_PRESTAINED": {
        "name": "PageRuler Prestained Protein Ladder",
        "manufacturer": "Thermo Fisher",
        "catalog_number": "26616",
        "category": LadderCategory.PRESTAINED,
        "description": "Ten prestained protein bands covering 10-180 kDa range.",
        "bands": [
            {"mw_kda": 180, "band_order": 1, "color": BandColor.BLUE},
            {"mw_kda": 130, "band_order": 2, "color": BandColor.BLUE},
            {"mw_kda": 100, "band_order": 3, "color": BandColor.BLUE},
            {"mw_kda": 70, "band_order": 4, "color": BandColor.ORANGE, "is_reference_band": True},
            {"mw_kda": 55, "band_order": 5, "color": BandColor.BLUE},
            {"mw_kda": 40, "band_order": 6, "color": BandColor.BLUE},
            {"mw_kda": 35, "band_order": 7, "color": BandColor.BLUE},
            {"mw_kda": 25, "band_order": 8, "color": BandColor.BLUE},
            {"mw_kda": 15, "band_order": 9, "color": BandColor.BLUE},
            {"mw_kda": 10, "band_order": 10, "color": BandColor.GREEN},
        ],
    },
    "PAGE_RULER_PLUS_PRESTAINED": {
        "name": "PageRuler Plus Prestained Protein Ladder",
        "manufacturer": "Thermo Fisher",
        "catalog_number": "26619",
        "category": LadderCategory.PRESTAINED,
        "description": "Twelve prestained protein bands covering 10-250 kDa range. "
        "Sharp bands for accurate MW determination.",
        "bands": [
            {"mw_kda": 250, "band_order": 1, "color": BandColor.BLUE},
            {"mw_kda": 180, "band_order": 2, "color": BandColor.BLUE},
            {"mw_kda": 130, "band_order": 3, "color": BandColor.BLUE},
            {"mw_kda": 100, "band_order": 4, "color": BandColor.BLUE},
            {"mw_kda": 70, "band_order": 5, "color": BandColor.ORANGE, "is_reference_band": True},
            {"mw_kda": 55, "band_order": 6, "color": BandColor.BLUE},
            {"mw_kda": 40, "band_order": 7, "color": BandColor.BLUE},
            {"mw_kda": 35, "band_order": 8, "color": BandColor.BLUE},
            {"mw_kda": 25, "band_order": 9, "color": BandColor.BLUE, "is_reference_band": True},
            {"mw_kda": 15, "band_order": 10, "color": BandColor.BLUE},
            {"mw_kda": 10, "band_order": 11, "color": BandColor.GREEN},
        ],
    },
}

# Invitrogen/Thermo Fisher See Blue ladders
SEE_BLUE_LADDERS = {
    "SEE_BLUE_PLUS2": {
        "name": "SeeBlue Plus2 Pre-stained Protein Standard",
        "manufacturer": "Thermo Fisher",
        "catalog_number": "LC5925",
        "category": LadderCategory.PRESTAINED,
        "description": "Nine multicolored bands from 4-250 kDa. "
        "Easy identification during electrophoresis and blotting.",
        "bands": [
            {"mw_kda": 250, "band_order": 1, "color": BandColor.BLUE},
            {"mw_kda": 148, "band_order": 2, "color": BandColor.GREEN, "is_reference_band": True},
            {"mw_kda": 98, "band_order": 3, "color": BandColor.BLUE},
            {"mw_kda": 64, "band_order": 4, "color": BandColor.PINK, "is_reference_band": True},
            {"mw_kda": 50, "band_order": 5, "color": BandColor.BLUE},
            {"mw_kda": 36, "band_order": 6, "color": BandColor.YELLOW, "is_reference_band": True},
            {"mw_kda": 22, "band_order": 7, "color": BandColor.BLUE},
            {"mw_kda": 16, "band_order": 8, "color": BandColor.PURPLE, "is_reference_band": True},
            {"mw_kda": 6, "band_order": 9, "color": BandColor.BLUE},
            {"mw_kda": 4, "band_order": 10, "color": BandColor.BLUE},
        ],
    },
}

# Combine all ladders
ALL_LADDERS = {
    **PRECISION_PLUS_LADDERS,
    **PAGE_RULER_LADDERS,
    **SEE_BLUE_LADDERS,
}


class DryRunException(Exception):
    """Exception raised to rollback during dry-run mode."""

    pass


class Command(BaseCommand):
    help = "Seed MW ladder templates for gel calibration"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without actually modifying the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be saved"))

        try:
            with transaction.atomic():
                stats = self._seed_templates()

                if dry_run:
                    raise DryRunException("Dry run completed")

        except DryRunException:
            pass

        # Print summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Ladder Templates Seeding Summary"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"  Templates created: {stats['templates_created']}")
        self.stdout.write(f"  Templates updated: {stats['templates_updated']}")
        self.stdout.write(f"  Total bands: {stats['total_bands']}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run - no changes were saved"))
        else:
            self.stdout.write(self.style.SUCCESS("\nAll templates seeded successfully!"))

    def _seed_templates(self) -> dict:
        """Seed all ladder templates."""
        stats = {
            "templates_created": 0,
            "templates_updated": 0,
            "total_bands": 0,
        }

        for code, data in ALL_LADDERS.items():
            template, created = LadderTemplate.objects.update_or_create(
                code=code,
                defaults={
                    "name": data["name"],
                    "manufacturer": data["manufacturer"],
                    "catalog_number": data.get("catalog_number", ""),
                    "category": data["category"],
                    "description": data.get("description", ""),
                    "is_global": True,
                    "is_active": True,
                    "created_by": None,  # System-created
                },
            )

            action = "Created" if created else "Updated"
            if created:
                stats["templates_created"] += 1
            else:
                stats["templates_updated"] += 1

            self.stdout.write(f"  {action}: {template.name}")

            # Seed bands
            bands = data.get("bands", [])
            self._seed_bands(template, bands, stats)

        return stats

    def _seed_bands(self, template: LadderTemplate, bands: list, stats: dict):
        """Seed bands for a template."""
        # Delete existing bands and recreate
        deleted_count = template.bands.all().delete()[0]
        if deleted_count > 0:
            self.stdout.write(f"    Deleted {deleted_count} existing bands")

        for band_data in bands:
            LadderBandDefinition.objects.create(
                template=template,
                mw_kda=band_data["mw_kda"],
                band_order=band_data["band_order"],
                color=band_data.get("color", BandColor.NONE),
                is_reference_band=band_data.get("is_reference_band", False),
                relative_intensity=band_data.get("relative_intensity"),
            )
            stats["total_bands"] += 1

        self.stdout.write(f"    Added {len(bands)} bands")

        # Update computed fields (band_count, mw_range)
        template.update_computed_fields()
