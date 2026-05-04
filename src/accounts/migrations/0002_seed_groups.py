"""Seed the three Phoresis groups: Lab User, Reviewer, Admin.

Phase 1 only seeds the Group rows - concrete `Permission` rows are attached
in Phase 2 once `gel_analyzer` models exist.
"""
from django.db import migrations

GROUPS = ["Lab User", "Reviewer", "Admin"]


def seed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


def unseed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_groups, reverse_code=unseed_groups),
    ]
