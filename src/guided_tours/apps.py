from django.apps import AppConfig


class GuidedToursConfig(AppConfig):
    name = "guided_tours"
    verbose_name = "Guided tours"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Every app is registered by now: read their tours/*.json once (guided_tours/registry.py)
        from guided_tours import registry

        registry.load()
