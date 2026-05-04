"""Django app config for gel_analyzer."""

from django.apps import AppConfig


class GelAnalyzerConfig(AppConfig):
    name = "gel_analyzer"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Gel Analyzer"

    def ready(self) -> None:
        # `signals.py` is intentionally a stub in Phoresis — see its docstring.
        # Importing it here is harmless and keeps the AppConfig contract
        # consistent with future extensions.
        from . import signals  # noqa: F401
