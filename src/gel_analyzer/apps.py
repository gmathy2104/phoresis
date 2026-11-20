"""Django app config for gel_analyzer."""

from django.apps import AppConfig


class GelAnalyzerConfig(AppConfig):
    name = "gel_analyzer"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Gel Analyzer"

    def ready(self):
        """Initialize app when Django starts."""
        # Import signals and system checks to register them
        import gel_analyzer.checks  # noqa: F401
        import gel_analyzer.signals  # noqa: F401
