"""Register the Dashboard app in the navigation registry."""

from phoresis_core.navigation import nav_registry

nav_registry.register_app(
    app_label="dashboard",
    display_name="Dashboard",
    group="Management",
    icon="layout-dashboard",
    url="/",
    pages=[{"name": "Home", "url": "/", "icon": "home"}],
    keywords=["home", "overview", "kpi"],
    shortcut_key="d",
)
