"""
Round Band.estimated_mw_kda to 1 decimal place.

Older calibration runs (legacy single-ladder path) wrote raw float MWs,
producing values like 47.83247919... — visually noisy in every UI surface
that shows MW. New writes are rounded at the service level; this
migration brings existing rows in line. No-op for rows where the value
is already at 1 decimal or null.
"""

from django.db import migrations


def round_mw(apps, schema_editor):
    Band = apps.get_model("gel_analyzer", "Band")
    qs = Band.objects.exclude(estimated_mw_kda__isnull=True)
    updated = 0
    for band in qs.only("id", "estimated_mw_kda").iterator(chunk_size=2000):
        rounded = round(float(band.estimated_mw_kda), 1)
        if rounded != band.estimated_mw_kda:
            band.estimated_mw_kda = rounded
            band.save(update_fields=["estimated_mw_kda"])
            updated += 1
    if updated:
        print(f"Rounded estimated_mw_kda on {updated} band rows to 1 decimal")


def noop_reverse(apps, schema_editor):
    """Rounding is lossy; the migration is intentionally non-reversible
    in the data sense, but we expose a no-op so `migrate <app> 0008`
    still succeeds for schema rollbacks."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("gel_analyzer", "0008_add_quant_calib_last_recomputed_at"),
    ]

    operations = [
        migrations.RunPython(round_mw, noop_reverse),
    ]
