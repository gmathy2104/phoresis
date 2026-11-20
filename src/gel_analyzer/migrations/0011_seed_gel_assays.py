"""Seed the three default gel assays.

get_or_create on the name: an assay the owner already renamed or edited is left
alone. Reverse is a no-op: the rows are data the owner may have edited by then.

Existing images keep ``assay = NULL``: their purity gate falls back to the gel
type (SDS-PAGE reads as a purity gel), so nothing changes for gels uploaded
before assays existed.
"""

from django.db import migrations

SEED = (
    ("SDS-PAGE", "SDS_PAGE", "PURITY", 10),
    ("Western blot — anti-product", "WESTERN_BLOT", "MOLECULE_VARIANTS", 20),
    ("Western blot — anti-HCP", "WESTERN_BLOT", "HOST_CELL_PROTEINS", 30),
)


def seed_gel_assays(apps, schema_editor):
    GelAssay = apps.get_model("gel_analyzer", "GelAssay")

    for name, gel_type, readout, display_order in SEED:
        GelAssay.objects.get_or_create(
            name=name,
            defaults={
                "gel_type": gel_type,
                "readout": readout,
                "display_order": display_order,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("gel_analyzer", "0010_gel_assays_readouts_saturation"),
    ]

    operations = [
        migrations.RunPython(seed_gel_assays, migrations.RunPython.noop),
    ]
