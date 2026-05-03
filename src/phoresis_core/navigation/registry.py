"""Auto-discovery of `nav.py` modules across installed apps.

Called from `PhoresisCoreConfig.ready()` — same pattern as Django's
`admin.autodiscover()`. nav.py modules **must not** import ORM models at
module level; defer to `apps.get_model(...)` inside functions if needed.
"""

from importlib import import_module

from django.apps import apps as django_apps
from django.utils.module_loading import module_has_submodule


def autodiscover_nav_modules() -> None:
    """Import `nav.py` from every installed app that has one."""
    for app_config in django_apps.get_app_configs():
        if module_has_submodule(app_config.module, "nav"):
            import_module(f"{app_config.name}.nav")
