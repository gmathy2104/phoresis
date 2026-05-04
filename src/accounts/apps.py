"""Django app config for accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Accounts"

    def ready(self) -> None:
        from . import signals  # noqa: F401 — registers post_save signal
