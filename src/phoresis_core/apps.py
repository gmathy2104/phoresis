"""App config for phoresis_core."""

from django.apps import AppConfig


class PhoresisCoreConfig(AppConfig):
    name = "phoresis_core"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Phoresis Core"

    def ready(self) -> None:
        # Wire loguru once Django is fully initialised.
        from .logging_config import setup_logging

        setup_logging()
        # Navigation autodiscover is added in Task 10 (extends this method).
